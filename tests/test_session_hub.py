"""G5a 会话 Hub：选区往返 / stale 判定 / 几何任务同形 intent / 权限拒绝。

全部用假 session（只记录 ``evaluate`` 入参），不构图、不跑 matplotlib，
也不断言被测源码文本。HTTP 层用真实回环服务器与真实请求。
"""
import copy
import http.client
import json
import threading
import unittest

from figpact.hub import SessionHub
from figpact.inspector_server import InspectorServer


class _FakeSession:
    """只暴露 Hub 需要的 snapshot/evaluate；evaluate 不产生任何真实副作用。"""

    def __init__(self, *, session_id='s-1', scene_revision='scene-1', source_revision='src-1'):
        self.frame = {'frame_revision': scene_revision,
                      'session': {'session_id': session_id, 'scene_revision': scene_revision,
                                  'source_revision': source_revision,
                                  'accepted_operation_ids': ['op-accepted']}}
        self.calls = []
        self.decisions = []

    def snapshot(self):
        return copy.deepcopy(self.frame)

    def evaluate(self, request):
        self.calls.append(copy.deepcopy(request))
        return {'status': 'OK', 'operation_id': request.get('operation_id'),
                'operation': request.get('operation'), 'accepted_frame': self.frame}

    def decide(self, request):
        """处理器的既有 /api/intents/decision 路由替身：只记录，回最小响应。"""
        self.decisions.append(copy.deepcopy(request))
        return {'status': 'OK', 'decision': 'accepted'}

    def set_quality(self, request):
        """处理器的既有 /api/frame/quality 路由替身。"""
        return {'status': 'OK', 'quality': 'HIGH'}


def selection_body(seq, *, gid='intent.main.A', guide='intent.main.guide', delta=(0.0, 0.15),
                   bounds_mm=(10.0, 20.0, 12.5, 23.0), clear=False):
    # clear=True 走「清空选区」路径：显式 selected: null，合法且不检查 gid。
    selected = None if clear else {
        'gid': gid, 'title': 'A', 'type': 'text', 'bounds_mm': list(bounds_mm),
        'linked_guide_gid': guide, 'registered': True,
        'identity_stability': 'STABLE', 'can_evaluate': True}
    return {'selection_seq': seq, 'session_id': 's-1', 'scene_revision': 'scene-1',
            'source_revision': 'src-1', 'scope': 'main', 'mode': 'canvas',
            'selected': selected,
            'delta_mm': list(delta), 'status': 'OK',
            'related': [], 'constraints': []}


def geometry_task(seq, **changes):
    return {'task_id': 'task-1', 'kind': 'geometry', 'goal': '上移 0.15mm',
            'selection_seq': seq, 'delta_mm': [0.0, 0.15], 'tolerance_mm': 0.01,
            'operation_id': 'task-op-1', **changes}


class SelectionTest(unittest.TestCase):
    def test_publish_then_read_round_trip_keeps_gid_and_geometry(self):
        hub, session = SessionHub(), _FakeSession()
        published = selection_body(1)
        self.assertEqual(hub.publish_selection(published), (
            {'status': 'OK', 'selection_seq': 1, 'hub_revision': 1}, 200))
        payload, code = hub.read_selection(session)
        self.assertEqual(code, 200)
        self.assertEqual(payload['status'], 'OK')
        self.assertIs(payload['stale'], False)
        self.assertIsNone(payload['stale_reason'])
        self.assertEqual(payload['selection']['selected']['gid'], 'intent.main.A')
        self.assertEqual(payload['selection']['selected']['bounds_mm'], [10.0, 20.0, 12.5, 23.0])
        self.assertEqual((payload['session_id'], payload['scene_revision'], payload['source_revision']),
                         ('s-1', 'scene-1', 'src-1'))
        self.assertEqual(payload['accepted_operation_ids'], ['op-accepted'])
        # 发布的是副本：外部改动不改变 Hub 状态。
        published['selected']['gid'] = 'intent.main.B'
        self.assertEqual(hub.read_selection(session)[0]['selection']['selected']['gid'], 'intent.main.A')

    def test_read_without_a_published_selection_is_not_stale(self):
        payload, code = SessionHub().read_selection(_FakeSession())
        self.assertEqual(code, 200)
        self.assertIsNone(payload['selection'])
        self.assertIs(payload['stale'], False)

    def test_seq_must_be_a_non_negative_strictly_increasing_int(self):
        hub = SessionHub()
        self.assertEqual(hub.publish_selection(selection_body(0))[1], 200)
        self.assertEqual(hub.publish_selection(selection_body(0)), (
            {'status': 'INVALID_SELECTION', 'message': 'selection_seq 必须严格递增（当前 0）'}, 400))
        self.assertEqual(hub.publish_selection(selection_body(-1))[0]['status'], 'INVALID_SELECTION')
        self.assertEqual(hub.publish_selection(selection_body('2'))[0]['status'], 'INVALID_SELECTION')
        self.assertEqual(hub.publish_selection(selection_body(True))[0]['status'], 'INVALID_SELECTION')
        self.assertEqual(hub.publish_selection(selection_body(1))[1], 200)
        self.assertEqual(hub.hub_revision, 2)
        self.assertEqual(hub.selection_seq, 1)

    def test_selected_without_gid_is_rejected(self):
        hub = SessionHub()
        body = selection_body(1)
        body['selected'] = {'title': '无身份'}
        self.assertEqual(hub.publish_selection(body)[0]['status'], 'INVALID_SELECTION')
        self.assertIsNone(hub.selection)

    def test_clearing_the_selection_is_allowed(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(1))
        # 清空选区就是 selected: null；显式 null 不检查 gid，序号仍需严格递增。
        self.assertEqual(hub.publish_selection(selection_body(2, clear=True)),
                         ({'status': 'OK', 'selection_seq': 2, 'hub_revision': 2}, 200))
        payload, code = hub.read_selection(session)
        self.assertEqual(code, 200)
        self.assertIsNone(payload['selection']['selected'])

    def test_revision_moves_mark_the_published_selection_stale(self):
        for field, live_change in (('session_id', 's-2'), ('scene_revision', 'scene-2'),
                                   ('source_revision', 'src-2')):
            with self.subTest(field=field):
                hub, session = SessionHub(), _FakeSession()
                hub.publish_selection(selection_body(1))
                session.frame['session'][field] = live_change
                payload, _ = hub.read_selection(session)
                self.assertIs(payload['stale'], True)
                self.assertIn(live_change, payload['stale_reason'])
                self.assertEqual(payload['selection']['selected']['gid'], 'intent.main.A')


class TaskTest(unittest.TestCase):
    def test_geometry_task_builds_a_page_shaped_intent_from_the_stored_selection(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(4))
        payload, code = hub.submit_task(geometry_task(4), session)
        self.assertEqual(code, 200)
        self.assertEqual(payload['status'], 'OK')
        self.assertEqual((payload['task_id'], payload['task_status']), ('task-1', 'EVALUATED'))
        self.assertEqual(payload['evaluate']['status'], 'OK')
        self.assertEqual(session.calls, [{
            'operation_id': 'task-op-1', 'session_id': 's-1', 'scene_revision': 'scene-1',
            'source_revision': 'src-1', 'scope': 'main', 'target_gid': 'intent.main.A',
            'operation': 'translate', 'delta_mm': [0.0, 0.15], 'tolerance_mm': 0.01,
            'preserve': {'science': True, 'follow_gids': ['intent.main.guide'], 'fixed_gids': []},
            'demonstration': {'display_only': True}}])

    def test_geometry_task_without_linked_guide_follows_nothing(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(1, guide=None))
        hub.submit_task(geometry_task(1), session)
        self.assertEqual(session.calls[0]['preserve']['follow_gids'], [])
        self.assertEqual(session.calls[0]['preserve'], {'science': True, 'follow_gids': [],
                                                        'fixed_gids': []})

    def test_geometry_task_falls_back_to_the_published_delta_and_generates_an_id(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(1, delta=(-0.2, 0.0)))
        task = geometry_task(1)
        task.pop('delta_mm')
        task.pop('operation_id')
        hub.submit_task(task, session)
        intent = session.calls[0]
        self.assertEqual(intent['delta_mm'], [-0.2, 0.0])
        self.assertTrue(intent['operation_id'].startswith('hub-'))
        self.assertEqual(intent['target_gid'], 'intent.main.A')

    def test_stale_or_mismatched_selection_never_reaches_evaluate(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(4))
        for task in (geometry_task(3),                     # 旧选区序号
                     geometry_task(4, target_gid='intent.main.B'),  # 与选区身份不一致
                     geometry_task('4')):                  # 非 int 序号
            self.assertEqual(hub.submit_task(task, session), (
                {'status': 'STALE_SELECTION',
                 'message': 'target_gid 与当前选区身份不一致' if task.get('target_gid')
                 else '选区已过期；请先读取当前选区再提交几何任务'}, 409))
        # 发布后实时会话已前进：不再用旧选区构造 intent。
        session.frame['session']['scene_revision'] = 'scene-2'
        status, code = hub.submit_task(geometry_task(4), session)
        self.assertEqual(code, 409)
        self.assertEqual(status['status'], 'STALE_SELECTION')
        self.assertIn('scene-1', status['message'])
        self.assertEqual(session.calls, [])
        self.assertEqual(hub.read_tasks()[0]['tasks'], [])

    def test_geometry_task_without_a_previous_selection_is_stale(self):
        hub, session = SessionHub(), _FakeSession()
        self.assertEqual(hub.submit_task(geometry_task(0), session)[1], 409)
        self.assertEqual(session.calls, [])

    def test_geometry_without_any_delta_is_not_a_task(self):
        hub, session = SessionHub(), _FakeSession()
        body = selection_body(1)
        body['delta_mm'] = None
        hub.publish_selection(body)
        task = geometry_task(1)
        task.pop('delta_mm')
        self.assertEqual(hub.submit_task(task, session)[0]['status'], 'INVALID_TASK')
        self.assertEqual(session.calls, [])

    def test_layout_request_is_only_recorded(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(7))
        payload, code = hub.submit_task({'task_id': 'layout-1', 'kind': 'layout_request',
                                         'goal': '标签避让', 'selection_seq': 7}, session)
        self.assertEqual(code, 200)
        self.assertEqual((payload['task_status'], payload['status']), ('RECORDED', 'OK'))
        self.assertEqual(session.calls, [])
        tasks = hub.read_tasks()[0]['tasks']
        self.assertEqual([task['task_id'] for task in tasks], ['layout-1'])
        self.assertEqual(tasks[0]['kind'], 'layout_request')
        self.assertEqual(tasks[0]['goal'], '标签避让')
        self.assertEqual((tasks[0]['selection_seq'], tasks[0]['status'],
                          tasks[0]['evaluate_status']), (7, 'RECORDED', None))
        self.assertTrue(tasks[0]['created_at'].endswith('+00:00'))

    def test_source_write_publish_delete_and_git_are_forbidden(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(1))
        bodies = [{'task_id': 'x', 'kind': kind, 'selection_seq': 1}
                  for kind in ('source_write', 'publish', 'delete', 'git')]
        bodies.append(geometry_task(1, source_write=True))
        bodies.append(geometry_task(1, publish=True))
        bodies.append(geometry_task(1, kind='geometry', publish=False, source_write=False))
        for body in bodies[:-1]:
            payload, code = hub.submit_task(body, session)
            self.assertEqual(code, 403)
            self.assertEqual(payload['status'], 'FORBIDDEN')
            self.assertIn('不授予源码写入或发布权限', payload['message'])
        self.assertEqual(hub.submit_task(bodies[-1], session)[1], 200)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual([task['task_id'] for task in hub.read_tasks()[0]['tasks']], ['task-1'])

    def test_unknown_kind_and_missing_task_id_are_rejected(self):
        hub, session = SessionHub(), _FakeSession()
        self.assertEqual(hub.submit_task({'kind': 'geometry', 'selection_seq': 1}, session)[0]['status'],
                         'INVALID_TASK')
        self.assertEqual(hub.submit_task({'task_id': 'x', 'kind': 'teleport'}, session)[0]['status'],
                         'INVALID_TASK')
        self.assertEqual(hub.submit_task(['not-a-dict'], session)[0]['status'], 'INVALID_TASK')
        self.assertEqual(session.calls, [])

    def test_geometry_task_is_recorded_with_its_evaluate_verdict(self):
        hub, session = SessionHub(), _FakeSession()
        hub.publish_selection(selection_body(2))
        hub.submit_task(geometry_task(2), session)
        task = hub.read_tasks()[0]['tasks'][0]
        self.assertEqual((task['status'], task['evaluate_status'], task['target_gid']),
                         ('EVALUATED', 'OK', 'intent.main.A'))

    def test_tasks_keep_only_the_last_fifty(self):
        hub, session = SessionHub(), _FakeSession()
        for index in range(60):
            hub.publish_selection(selection_body(index))
            hub.submit_task({'task_id': f'layout-{index}', 'kind': 'layout_request',
                             'selection_seq': index}, session)
        tasks = hub.read_tasks()[0]['tasks']
        self.assertEqual(len(tasks), 50)
        self.assertEqual(tasks[0]['task_id'], 'layout-10')
        self.assertEqual(tasks[-1]['task_id'], 'layout-59')
        # 每次被接受的变更各 +1：60 次选区发布 + 60 次任务登记（layout_request 每次都登记）。
        self.assertEqual(hub.hub_revision, 120)


def http_request(port, method, path, body=None, **headers):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    data = None if body is None else json.dumps(body)
    if data is not None:
        headers.setdefault('Content-Type', 'application/json')
    conn.request(method, path, data, headers)
    response = conn.getresponse()
    result = (response.status, json.loads(response.read()))
    conn.close()
    return result


class HubHttpTest(unittest.TestCase):
    def setUp(self):
        self.session = _FakeSession()
        self.server = InspectorServer(self.session)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()

    def test_selection_round_trip_over_http_and_existing_404_unchanged(self):
        status, payload = http_request(self.port, 'GET', '/api/selection')
        self.assertEqual((status, payload['selection']), (200, None))
        self.assertEqual(http_request(self.port, 'POST', '/api/selection', selection_body(1)),
                         (200, {'status': 'OK', 'selection_seq': 1, 'hub_revision': 1}))
        status, payload = http_request(self.port, 'GET', '/api/selection')
        self.assertEqual(status, 200)
        self.assertEqual(payload['selection']['selected']['bounds_mm'], [10.0, 20.0, 12.5, 23.0])
        self.assertEqual(http_request(self.port, 'POST', '/api/selection', selection_body(1))[0], 400)
        self.assertEqual(http_request(self.port, 'GET', '/api/execute'), (404, {'status': 'NOT_FOUND'}))
        self.assertEqual(http_request(self.port, 'POST', '/api/execute', {'script': 'x.py'}),
                         (404, {'status': 'NOT_FOUND'}))
        # 既有路由没被新路由挤掉：/api/intents/decision 与 /api/frame/quality 仍由 session 处理。
        self.assertEqual(http_request(self.port, 'POST', '/api/intents/decision', {'intent_id': 'i-1'}),
                         (200, {'status': 'OK', 'decision': 'accepted'}))
        self.assertEqual(self.session.decisions, [{'intent_id': 'i-1'}])
        self.assertEqual(http_request(self.port, 'POST', '/api/frame/quality', {'dpi': 240}),
                         (200, {'status': 'OK', 'quality': 'HIGH'}))
        status, payload = http_request(self.port, 'GET', '/api/tasks')
        self.assertEqual((status, payload['tasks']), (200, []))

    def test_http_geometry_task_and_layout_request(self):
        http_request(self.port, 'POST', '/api/selection', selection_body(9))
        status, payload = http_request(self.port, 'POST', '/api/tasks', geometry_task(9))
        self.assertEqual(status, 200)
        self.assertEqual(payload['task_status'], 'EVALUATED')
        self.assertEqual(payload['evaluate']['status'], 'OK')
        self.assertEqual(http_request(self.port, 'POST', '/api/tasks', geometry_task(8))[0], 409)
        self.assertEqual(http_request(self.port, 'POST', '/api/tasks',
                                      {'task_id': 'w', 'kind': 'publish', 'selection_seq': 9})[0], 403)
        # publish(1) + EVALUATED 任务(2)：被拒的 409/403 不改变 Hub 状态。
        self.assertEqual(http_request(self.port, 'GET', '/api/selection'), (200, {
            'status': 'OK', 'hub_revision': 2, 'selection': selection_body(9), 'stale': False,
            'stale_reason': None, 'session_id': 's-1', 'scene_revision': 'scene-1',
            'source_revision': 'src-1', 'accepted_operation_ids': ['op-accepted']}))
