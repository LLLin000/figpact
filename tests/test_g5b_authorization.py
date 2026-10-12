"""G5b 计划授权（``/api/plans`` 系列）：真实回环 HTTP + 真实临时源码 + 真实 state_home。

断言的都是可观察事实：HTTP 状态与错误信封、磁盘字节、``source_writes`` journal 状态、
history 检查点。不跑 matplotlib——计划路由读的是脚本字节与 ast，不构建 Figure。

硬安全边界要证的那一条：网页**不能**靠 body 里的 ``{"authorized": true}`` 让服务器认为
已取得授权；同意必须由服务端注入 ``/frame.js`` 的页面会话令牌带回来。诚实边界：这是
本机单用户同意绑定（回环 + 同源 + 页面会话令牌），不是多用户认证。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from figpact.history import HistoryStore
from figpact.inspector_server import InspectorServer

#: 线路上的契约名字（这里是字面量，不引用实现常量：测试要守的是协议本身）。
UI_HEADER = 'X-Figpact-Ui'
CLIENT_HEADER = 'X-Figpact-Client'
#: ``token=None`` 表示"用页面拿到的令牌"；``NO_HEADER`` 表示这个请求根本不带该 header。
NO_HEADER = object()
NO_BODY = object()
#: ``start(source=NO_SOURCE)`` 表示用本用例工程的身份；显式传 None 表示服务端不知道身份。
NO_SOURCE = object()

SCRIPT_BYTES = b'LAYOUT_MM = {"main.A": [0.0, 0.0], "main.B": [1.0, 2.0]}\n'
CONFIG_BYTES = b'scope: main\n'
CLIENT_A = 'agent-A'
CLIENT_B = 'agent-B'


class _FakeSession:
    """计划路由不读会话；这里只满足 InspectorServer 对既有路由的构造需求。"""

    def snapshot(self):
        return {'frame_revision': 'scene-1', 'session': {'session_id': 's-1'}}

    def evaluate(self, request):
        return {'status': 'OK'}

    def decide(self, request):
        return {'status': 'OK'}

    def set_quality(self, request):
        return {'status': 'OK'}


def _request(port, method, path, body, headers):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        data, sent = None, dict(headers)
        if body is not NO_BODY:
            data = json.dumps(body)
            sent['Content-Type'] = 'application/json'
        conn.request(method, path, data, sent)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def http_json(port, method, path, body=NO_BODY, headers=None):
    status, raw = _request(port, method, path, body, headers or {})
    return status, json.loads(raw)


def http_raw(port, method, path, data, headers):
    """原始字节请求：测的是 Content-Type / Content-Length / 64 KiB 这些**没进 JSON 之前**的拒绝。"""
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        conn.request(method, path, data, dict(headers))
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def get(port, path):
    return http_json(port, 'GET', path)


def http_text(port, path):
    status, raw = _request(port, 'GET', path, NO_BODY, {})
    return status, raw.decode('utf-8')


def _stamp(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class _PlanCase(unittest.TestCase):
    """一条用例一个临时工程 + 一个临时 state_home + 一个真实回环服务器。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='figpact-g5b-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / 'project'
        self.state = self.root / 'state'
        self.project.mkdir()
        self.script = self.project / 'plot.py'
        self.script.write_bytes(SCRIPT_BYTES)
        self.config = self.project / 'plot.yaml'
        self.config.write_bytes(CONFIG_BYTES)

    def start(self, source=NO_SOURCE):
        identity = {'script': str(self.script), 'config': str(self.config), 'scope': 'main'} \
            if source is NO_SOURCE else source
        server = InspectorServer(_FakeSession(), ('127.0.0.1', 0), state_home=self.state,
                                 source=identity)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # addCleanup 是后进先出：shutdown → join → close。
        self.addCleanup(server.server_close)
        self.addCleanup(lambda: thread.join(5))
        self.addCleanup(server.shutdown)
        self.server, self.port = server, server.server_address[1]
        self.token = self.frame_token()
        return server

    # 页面拿令牌的唯一途径：服务端服务页面时注入 /frame.js。

    def frame_token(self):
        status, text = http_text(self.port, '/frame.js')
        self.assertEqual(status, 200)
        self.assertIn('window.FIGPACT_INSPECTOR_FRAME=', text)  # 既有 frame 行为没被顶掉
        match = re.search(r'window\.FIGPACT_UI_TOKEN=("(?:[^"\\]|\\.)*");', text)
        self.assertIsNotNone(match, text)
        token = json.loads(match.group(1))
        self.assertEqual(token, self.server.ui_token)
        self.assertTrue(token)
        return token

    # 五条路由的薄封装。

    def mint(self, *, client=CLIENT_A, value=(0.0, 4.0), gid='main.A', script=None):
        status, payload = http_json(self.port, 'POST', '/api/plans', {
            'client_id': client, 'kind': 'layout_edit', 'script': str(script or self.script),
            'gid': gid, 'value': list(value), 'reason': 'G5b 用例：只改这一个 LAYOUT_MM 字面量'})
        self.assertEqual((status, payload['status']), (200, 'OK'), payload)
        return payload['plan']

    def mint_raw(self, *, client=CLIENT_A, value=(0.0, 4.0), gid='main.A', script=None):
        """不假设成功的铸造：用于断言被拒的请求**不铸造计划**。"""
        return http_json(self.port, 'POST', '/api/plans', {
            'client_id': client, 'kind': 'layout_edit', 'script': str(script or self.script),
            'gid': gid, 'value': list(value), 'reason': 'G5b 用例：只改这一个 LAYOUT_MM 字面量'})

    def authorize(self, plan_id, token=None, body=NO_BODY):
        headers = {} if token is NO_HEADER else {UI_HEADER: self.token if token is None else token}
        return http_json(self.port, 'POST', f'/api/plans/{plan_id}/authorize', body, headers)

    def apply_plan(self, plan_id, client=None, body=NO_BODY):
        headers = {} if client is None else {CLIENT_HEADER: client}
        return http_json(self.port, 'POST', f'/api/plans/{plan_id}/apply', body, headers)

    def cancel_plan(self, plan_id):
        return http_json(self.port, 'POST', f'/api/plans/{plan_id}/cancel')

    def plans(self):
        status, payload = get(self.port, '/api/plans')
        self.assertEqual(status, 200)
        return {plan['plan_id']: plan for plan in payload['plans']}

    def plan_state(self, plan_id):
        return self.plans()[plan_id]['state']

    # 磁盘 / journal / history 的事实读取。

    def script_bytes(self):
        return self.script.read_bytes()

    def journal(self, plan):
        path = self.state / 'source-journals' / f"{plan['journal_id']}.json"
        return json.loads(path.read_text(encoding='utf-8'))

    def checkpoints(self):
        store = HistoryStore(self.script, self.config, 'main', state_home=self.state)
        try:
            return store.source_changes()
        finally:
            store.close()

    # 把时钟拨到 15 分钟之后等价的事实：直接改内存态时间戳（会话级状态本来就不落盘）。

    def expire_plan(self, plan_id):
        self.server.hub._plans[plan_id]['expires_at'] = _stamp(-1)

    def expire_grant(self, plan_id):
        self.server.hub._grants[plan_id]['expires_at'] = _stamp(-1)


class TokenConsentTest(_PlanCase):
    def test_page_token_is_required_and_a_body_field_is_never_consent(self):
        self.start()
        plan = self.mint()
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)  # 铸造计划零字节写用户源码
        for label, kwargs in (('缺 header', {'token': NO_HEADER}),
                              ('错 token', {'token': 'not-the-served-page-token'}),
                              ('空 header', {'token': ''}),
                              ('body 里自称已授权', {'token': NO_HEADER,
                                                'body': {'authorized': True}})):
            with self.subTest(label):
                status, payload = self.authorize(plan['plan_id'], **kwargs)
                self.assertEqual(status, 403, payload)
                self.assertEqual(payload['status'], 'FORBIDDEN')
                self.assertIn(UI_HEADER, payload['message'])
        self.assertEqual(self.plan_state(plan['plan_id']), 'PENDING')
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertEqual(self.journal(plan)['status'], 'PREPARED')
        self.assertEqual(self.checkpoints(), [])
        self.assertEqual(self.server.hub._grants, {})


class PlanStateTest(_PlanCase):
    def test_plans_keep_only_the_last_fifty_and_evict_their_grants(self):
        self.start()
        first = self.mint(value=(0.0, 0.4))['plan_id']
        self.assertEqual(self.authorize(first)[0], 200)          # 第一条带着 grant
        minted = [self.mint(value=(0.0, (index + 1) / 10.0))['plan_id'] for index in range(50)]
        listed = self.plans()
        self.assertEqual(len(listed), 50)
        self.assertNotIn(first, listed)                          # FIFO：最旧的一条被淘汰
        self.assertEqual(list(listed), minted)
        self.assertNotIn(first, self.server.hub._grants)          # grant 与计划同生共死
        status, payload = self.apply_plan(first, client=CLIENT_A)
        self.assertEqual((status, payload['status']), (409, 'PLAN_UNKNOWN'))
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertEqual(self.checkpoints(), [])

    def test_unknown_expired_and_non_pending_plans_are_rejected(self):
        self.start()
        status, payload = self.authorize('f' * 32)
        self.assertEqual((status, payload['status']), (409, 'PLAN_UNKNOWN'))

        expired = self.mint(value=(0.0, 4.0))
        self.expire_plan(expired['plan_id'])
        status, payload = self.authorize(expired['plan_id'])
        self.assertEqual((status, payload['status']), (409, 'PLAN_EXPIRED'))

        granted = self.mint(value=(0.0, 5.0))
        self.assertEqual(self.authorize(granted['plan_id'])[0], 200)
        status, payload = self.authorize(granted['plan_id'])
        self.assertEqual((status, payload['status']), (409, 'PLAN_NOT_PENDING'))

        cancelled = self.mint(value=(0.0, 6.0))
        self.cancel_plan(cancelled['plan_id'])
        status, payload = self.authorize(cancelled['plan_id'])
        self.assertEqual((status, payload['status']), (409, 'PLAN_NOT_PENDING'))

        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertEqual([self.journal(plan)['status'] for plan in (expired, granted, cancelled)],
                         ['PREPARED'] * 3)
        self.assertEqual(self.checkpoints(), [])

    def test_plan_route_passes_through_python_native_rejections_and_mints_nothing(self):
        self.start()
        # 定位歧义（同一 key 出现两次）→ AMBIGUOUS；值非法 → INVALID；没有这条绑定 → NEEDS_AUTHORING。
        self.script.write_bytes(b'LAYOUT_MM = {"main.A": [0.0, 0.0], "main.A": [1.0, 1.0]}\n')
        status, payload = self.mint_raw(gid='main.A')
        self.assertEqual((status, payload['status']), (409, 'AMBIGUOUS'), payload)
        self.assertEqual(payload['confidence'], 'low')
        self.assertTrue(payload['candidates'])
        self.assertEqual(self.plans(), {})

        self.script.write_bytes(SCRIPT_BYTES)
        status, payload = self.mint_raw(value=('x', 1.0))
        self.assertEqual((status, payload['status']), (400, 'INVALID'), payload)
        status, payload = self.mint_raw(gid='main.MISSING')
        self.assertEqual((status, payload['status']), (409, 'NEEDS_AUTHORING'), payload)
        self.assertEqual(self.plans(), {})
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertFalse((self.state / 'source-journals').exists())


class ApplyGateTest(_PlanCase):
    def test_apply_without_page_consent_writes_nothing(self):
        self.start()
        plan = self.mint()
        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['status']), (409, 'PLAN_NOT_PENDING'))

        # 授权之后：没有 X-Figpact-Client 的请求连计划都不查；body 里自称 authorized 也没用。
        self.assertEqual(self.authorize(plan['plan_id'])[0], 200)
        for body in (NO_BODY, {'authorized': True}):
            status, payload = self.apply_plan(plan['plan_id'], body=body)
            self.assertEqual(status, 403, payload)
            self.assertEqual(payload['status'], 'FORBIDDEN')
            self.assertIn(CLIENT_HEADER, payload['message'])
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertEqual(self.journal(plan)['status'], 'PREPARED')
        self.assertEqual(self.checkpoints(), [])
        self.assertEqual(self.plan_state(plan['plan_id']), 'AUTHORIZED')
        self.assertIs(self.plans()[plan['plan_id']]['grant']['used'], False)

    def test_external_rewrite_after_consent_is_stale_source_and_writes_nothing(self):
        self.start()
        plan = self.mint()
        self.assertEqual(self.authorize(plan['plan_id'])[0], 200)
        rewritten = SCRIPT_BYTES.replace(b'[1.0, 2.0]', b'[9.0, 9.0]')
        self.script.write_bytes(rewritten)          # 第三方在同意之后改了盘上的字节

        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['status']), (409, 'STALE_SOURCE'))
        self.assertIn(str(self.script), payload['message'])
        self.assertEqual(self.script_bytes(), rewritten)  # 一个字节都没写
        self.assertEqual(self.journal(plan)['status'], 'PREPARED')
        self.assertEqual(self.checkpoints(), [])
        self.assertEqual(self.plan_state(plan['plan_id']), 'AUTHORIZED')
        self.assertIs(self.plans()[plan['plan_id']]['grant']['used'], False)

    def test_expired_plan_and_expired_grant_are_both_rejected(self):
        self.start()
        plan = self.mint(value=(0.0, 4.0))
        self.assertEqual(self.authorize(plan['plan_id'])[0], 200)
        self.expire_plan(plan['plan_id'])
        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['status']), (409, 'PLAN_EXPIRED'))

        other = self.mint(value=(0.0, 5.0))
        self.assertEqual(self.authorize(other['plan_id'])[0], 200)
        self.expire_grant(other['plan_id'])          # 计划还活着，grant 已经过期
        status, payload = self.apply_plan(other['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['status']), (409, 'GRANT_EXPIRED'))

        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertEqual([self.journal(plan)['status'], self.journal(other)['status']],
                         ['PREPARED', 'PREPARED'])
        self.assertEqual(self.checkpoints(), [])


class ApplySuccessTest(_PlanCase):
    def test_authorized_apply_writes_the_planned_bytes_once_and_appends_a_checkpoint(self):
        self.start()
        plan = self.mint(value=(0.0, 4.0))
        wanted = plan['files'][0]
        self.assertEqual(plan['state'], 'PENDING')
        self.assertEqual(wanted['path'], str(self.script))
        self.assertEqual(wanted['before_sha256'], hashlib.sha256(SCRIPT_BYTES).hexdigest())
        self.assertIn('[0.0, 4.0]', wanted['diff'])

        status, granted = self.authorize(plan['plan_id'])
        self.assertEqual((status, granted['status']), (200, 'OK'))
        self.assertIs(granted['grant']['single_use'], True)
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)   # 同意本身不写源码

        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['commit_state']), (200, 'COMMITTED_AND_VERIFIED'))
        self.assertEqual(payload['journal_id'], plan['journal_id'])
        self.assertEqual(payload['state'], 'APPLIED')
        after = self.script_bytes()
        self.assertEqual(hashlib.sha256(after).hexdigest(), wanted['after_sha256'])
        self.assertIn(b'[0.0, 4.0]', after)
        self.assertEqual(self.journal(plan)['status'], 'COMMITTED')

        records = self.checkpoints()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], payload['checkpoint_id'])
        self.assertEqual(records[0]['payload']['kind'], 'source_change')
        self.assertEqual(records[0]['payload']['plan_id'], plan['plan_id'])
        self.assertEqual([change['after_sha256'] for change in records[0]['payload']['file_changes']],
                         [wanted['after_sha256']])
        self.assertEqual([change['path'] for change in records[0]['payload']['file_changes']],
                         [str(self.script)])

        # 单次使用：第二次 apply 必须被拒，磁盘还停在第一版。
        status, again = self.apply_plan(plan['plan_id'], client=CLIENT_A)
        self.assertEqual(status, 409)
        self.assertIn(again['status'], ('PLAN_APPLIED', 'GRANT_ALREADY_USED'))
        self.assertEqual(self.script_bytes(), after)
        self.assertEqual(len(self.checkpoints()), 1)


class HistoryIdentityTest(_PlanCase):
    def test_write_is_reported_honestly_when_the_server_does_not_know_the_workspace(self):
        self.start(source=None)                     # 服务端不知道 script/config/scope
        plan = self.mint(value=(0.0, 4.0))
        self.assertEqual(self.authorize(plan['plan_id'])[0], 200)
        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['commit_state']), (200, 'COMMITTED_AND_VERIFIED'))
        # 写盘是事实：字节按计划改了，journal COMMITTED；只是检查点没地方记，照实说。
        self.assertEqual(hashlib.sha256(self.script_bytes()).hexdigest(),
                         plan['files'][0]['after_sha256'])
        self.assertEqual(self.journal(plan)['status'], 'COMMITTED')
        self.assertIsNone(payload['checkpoint_id'])
        self.assertEqual(payload['history_error'], 'SOURCE_IDENTITY_UNKNOWN')
        self.assertEqual(self.checkpoints(), [])


class ClientBindingTest(_PlanCase):
    def test_only_the_client_that_asked_for_the_plan_may_apply_it(self):
        self.start()
        plan = self.mint(client=CLIENT_A, value=(0.0, 4.0))
        self.assertEqual(self.authorize(plan['plan_id'])[0], 200)
        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_B)
        self.assertEqual((status, payload['status']), (403, 'FORBIDDEN'))
        self.assertIn(CLIENT_A, payload['message'])       # 计划是 agent-A 申请的
        status, payload = self.apply_plan(plan['plan_id'], client='')
        self.assertEqual((status, payload['status']), (403, 'FORBIDDEN'))
        self.assertIn(CLIENT_HEADER, payload['message'])
        # 被拒的客户端没有把 grant 用掉：申请者仍然能按计划落盘一次。
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertIs(self.plans()[plan['plan_id']]['grant']['used'], False)
        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['commit_state']), (200, 'COMMITTED_AND_VERIFIED'))
        self.assertEqual(hashlib.sha256(self.script_bytes()).hexdigest(),
                         plan['files'][0]['after_sha256'])
        self.assertEqual(len(self.checkpoints()), 1)


class CancelTest(_PlanCase):
    def test_cancel_writes_nothing_and_an_applied_plan_cannot_be_cancelled(self):
        self.start()
        plan = self.mint(value=(0.0, 4.0))
        status, payload = self.cancel_plan(plan['plan_id'])
        self.assertEqual((status, payload['state']), (200, 'CANCELLED'))
        self.assertEqual(self.plan_state(plan['plan_id']), 'CANCELLED')
        self.assertEqual(self.script_bytes(), SCRIPT_BYTES)
        self.assertEqual(self.journal(plan)['status'], 'PREPARED')
        self.assertEqual(self.checkpoints(), [])
        self.assertEqual(self.server.hub._grants, {})
        self.assertEqual(self.authorize(plan['plan_id'])[1]['status'], 'PLAN_NOT_PENDING')
        self.assertEqual(self.apply_plan(plan['plan_id'], client=CLIENT_A)[1]['status'],
                         'PLAN_CANCELLED')
        self.assertEqual(self.cancel_plan(plan['plan_id'])[1]['state'], 'CANCELLED')  # 幂等

        applied = self.mint(value=(0.0, 5.0))
        self.assertEqual(self.authorize(applied['plan_id'])[0], 200)
        self.assertEqual(self.apply_plan(applied['plan_id'], client=CLIENT_A)[0], 200)
        after = self.script_bytes()
        status, payload = self.cancel_plan(applied['plan_id'])
        self.assertEqual((status, payload['status']), (409, 'PLAN_APPLIED'))
        self.assertEqual(self.script_bytes(), after)          # 写盘是事实，取消改不了它
        self.assertEqual(self.plan_state(applied['plan_id']), 'APPLIED')
        self.assertEqual(len(self.checkpoints()), 1)


class TwoClientRaceTest(_PlanCase):
    def test_an_older_plan_cannot_overwrite_the_newer_version(self):
        self.start()
        older = self.mint(client=CLIENT_A, value=(0.0, 4.0))
        newer = self.mint(client=CLIENT_B, value=(0.0, 6.0))
        # 两份计划都从同一版源码铸造：before 相同、after 不同。
        self.assertEqual(older['files'][0]['before_sha256'], newer['files'][0]['before_sha256'])
        self.assertNotEqual(older['files'][0]['after_sha256'], newer['files'][0]['after_sha256'])
        self.assertEqual(self.authorize(older['plan_id'])[0], 200)
        self.assertEqual(self.authorize(newer['plan_id'])[0], 200)

        status, payload = self.apply_plan(newer['plan_id'], client=CLIENT_B)
        self.assertEqual((status, payload['commit_state']), (200, 'COMMITTED_AND_VERIFIED'))
        written = self.script_bytes()
        self.assertEqual(hashlib.sha256(written).hexdigest(),
                         newer['files'][0]['after_sha256'])

        # 旧计划（同一份 before 上的授权）在新版本落盘后必须被磁盘事实挡住。
        status, payload = self.apply_plan(older['plan_id'], client=CLIENT_A)
        self.assertEqual((status, payload['status']), (409, 'STALE_SOURCE'))
        self.assertEqual(self.script_bytes(), written)
        self.assertEqual(hashlib.sha256(self.script_bytes()).hexdigest(),
                         newer['files'][0]['after_sha256'])
        self.assertEqual(self.journal(older)['status'], 'PREPARED')
        self.assertEqual(self.journal(newer)['status'], 'COMMITTED')
        # 两个客户端不会各写一份：history 里只有新版本那一个检查点。
        records = self.checkpoints()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['payload']['plan_id'], newer['plan_id'])
        # 另一份计划也拿不到旧客户端的授权：跨客户端应用一律被拒。
        third = self.mint(client=CLIENT_B, value=(0.0, 7.0))
        self.assertEqual(self.authorize(third['plan_id'])[0], 200)
        self.assertEqual(self.apply_plan(third['plan_id'], client=CLIENT_A)[0], 403)


class RouteCompatibilityTest(_PlanCase):
    def test_existing_routes_and_unknown_plan_shapes_are_unchanged(self):
        self.start()
        status, payload = get(self.port, '/api/plans')
        self.assertEqual((status, payload), (200, {'status': 'OK', 'plans': []}))
        for path in ('/api/plans/x/apply/extra', '/api/plans/x/destroy', '/api/plans/a/b'):
            self.assertEqual(http_json(self.port, 'POST', path, {})[0], 404, path)
        self.assertEqual(get(self.port, '/api/execute')[0], 404)
        # 计划路由沿用既有信封：Content-Type / 空 body / 64 KiB 校验一个都没少。
        status, _ = http_raw(self.port, 'POST', '/api/plans', b'{"client_id": "a"}',
                             {'Content-Type': 'text/plain'})
        self.assertEqual(status, 415)
        status, _ = http_raw(self.port, 'POST', '/api/plans', b'',
                             {'Content-Type': 'application/json'})
        self.assertEqual(status, 400)
        status, _ = http_raw(self.port, 'POST', '/api/plans',
                             json.dumps({'padding': 'x' * 70000}).encode('utf-8'),
                             {'Content-Type': 'application/json'})
        self.assertEqual(status, 413)
