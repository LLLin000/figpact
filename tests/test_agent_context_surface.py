"""P1-b 只读 Agent 上下文通道：scene / constraints / impact 必须与既有真值逐项一致。

全部用**真实临时脚本 + 真实 IntentSession**（不 mock 任何被测事实）：Scene 取自
``session.snapshot()['scene_json']``，约束取自契约声明，impact 取自引擎的附着/归属/绑定
事实；「一致」用真实 ``evaluate`` 回执交叉核对，而不是拿断言复述自己的实现。
"""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

import matplotlib
matplotlib.use('Agg', force=True)

from figpact.hub import SessionHub
from figpact.intents import IntentSession

SCRIPT = '''\
from pathlib import Path

import matplotlib.pyplot as plt
from figpact import GidRegistry, apply_display_shift

FIGURE_ID = 'agent'
SCOPES = ('main',)
CONFIG_PATH = Path(__file__).with_name('agent.yaml')


def load_science():
    return {'x': [0., 1., 2.], 'y': [0., 1., 0.]}


def science_manifest(science):
    return {'nodes': {'agent.main.guide': {'type': 'guide', 'science_policy': 'LAYOUT'}},
            'science': {'protected': {'peak_anchors': {
                'agent.main.A': {'guide_gid': 'agent.main.guide',
                                 'guide_anchor_data': [0.5, 0.5], 'exact_ppm': 0.5}}}}}


def build_scene(science, config, scope):
    fig = plt.figure(figsize=(60 / 25.4, 40 / 25.4), dpi=120)
    ax = fig.add_axes((0.15, 0.2, 0.75, 0.6))
    ax.set(xlim=(0, 2), ylim=(-1, 4))
    reg = GidRegistry()
    curve, = ax.plot(science['x'], science['y'], linewidth=0.5)
    reg.register(curve, 'agent.main.curve', params=[])
    for name, xy in (('A', (0.5, 2.0)), ('B', (1.5, 3.0)), ('C', (0.9, 2.6))):
        label = ax.text(*xy, name, fontsize=7)
        reg.register(label, 'agent.main.' + name, params=['offsets_mm'])
        shift = config['offsets_mm'][name]
        apply_display_shift(label, dx_mm=shift[0], dy_mm=shift[1])
    outside = ax.text(5.0, 9.0, 'D', fontsize=7, clip_on=True)
    reg.register(outside, 'agent.main.D', params=[])
    shift = config['offsets_mm']['A']
    guide, = ax.plot([0.5, 0.5 + shift[0] * 2 / 45], [0.5, 1.8 + shift[1] * 5 / 24], linewidth=0.5)
    reg.register(guide, 'agent.main.guide', params=['offsets_mm'])
    return fig, reg


def layout_contract(scope):
    scopes = {'A': ['main'], 'B': ['main'], 'C': ['main', 'detail']}
    return {'parameters': [
        {'key': name, 'path': ['offsets_mm', name], 'unit': 'mm', 'mutability': 'EDITABLE',
         'operation': 'rebuild', 'scale': 1., 'min': -10., 'max': 10., 'scopes': scopes[name],
         'objects': ['agent.main.' + name] + (['agent.main.guide'] if name == 'A' else [])}
        for name in ('A', 'B', 'C')],
        'nodes': {
            'agent.main.A': {'type': 'text', 'editable': True, 'science_policy': 'LAYOUT'},
            'agent.main.B': {'type': 'text', 'editable': True, 'science_policy': 'LAYOUT',
                             'parent': 'agent.main.A'},
            'agent.main.C': {'type': 'text', 'editable': True, 'science_policy': 'LAYOUT'},
            'agent.main.D': {'type': 'text', 'science_policy': 'LAYOUT'},
            'agent.main.curve': {'type': 'curve', 'science_policy': 'LOCKED_SCIENCE'}},
        'relations': [],
        'groups': [{'id': 'agent.main.group', 'members': ['agent.main.A']}],
        'outputs': ['agent.png']}
'''

CONFIG = 'offsets_mm:\n  A: [0.2, -0.1]\n  B: [0.0, 0.0]\n  C: [0.0, 0.0]\n'
SCOPE = 'main'
LABEL_A = 'agent.main.A'
LABEL_B = 'agent.main.B'
LABEL_C = 'agent.main.C'
LABEL_D = 'agent.main.D'
CURVE = 'agent.main.curve'
GUIDE = 'agent.main.guide'
GROUP = 'agent.main.group'


def _write_workspace(tmp_path):
    script = tmp_path / 'agent_plot.py'
    config = tmp_path / 'agent.yaml'
    script.write_text(SCRIPT, encoding='utf8')
    config.write_text(CONFIG, encoding='utf8')
    return script, config


class _ContextCase(unittest.TestCase):
    """真实临时脚本 + 真实会话：被测的三部分必须来自这里，而不是断言里的常量。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='figpact-agent-context-')
        self.tmp_path = Path(self._tmp.name)
        script, config = _write_workspace(self.tmp_path)
        self.protected = {path: path.read_bytes() for path in (script, config)}
        self.session = IntentSession(script=script, config=config, scope=SCOPE)
        self.hub = SessionHub()

    def tearDown(self):
        self.session.close()
        self._tmp.cleanup()

    # 既有真值的小把柄（测试自己读，不经过被测实现）

    def frame(self):
        return self.session.snapshot()

    def scene(self):
        return json.loads(self.frame()['scene_json'])

    def scene_node(self, gid):
        return next(node for node in self.scene()['nodes'] if node.get('gid') == gid)

    def contract_record(self, key):
        return next(record for record in self.session._core.parameters()
                    if record['key'] == key)

    def publish(self, seq, gid, *, scope=SCOPE):
        frame = self.frame()
        session = frame['session']
        return self.hub.publish_selection({
            'selection_seq': seq, 'session_id': session['session_id'],
            'scene_revision': frame['frame_revision'], 'source_revision': session['source_revision'],
            'scope': scope, 'mode': 'canvas',
            'selected': {'gid': gid, 'type': 'text', 'bounds_mm': None,
                         'linked_guide_gid': None, 'registered': True,
                         'identity_stability': 'stable', 'can_evaluate': True},
            'delta_mm': [0.0, 0.0], 'status': 'DESIRED_ONLY', 'related': [],
            'constraints': ['preserve_science']})

    def evaluate(self, gid, delta=(0.0, 0.15), *, follow=(), scope=SCOPE):
        frame = self.frame()
        return self.session.evaluate({
            'operation_id': str(uuid.uuid4()), **frame['session'], 'scope': scope,
            'target_gid': gid, 'operation': 'translate', 'delta_mm': list(delta),
            'tolerance_mm': 0.01,
            'preserve': {'science': True, 'follow_gids': list(follow), 'fixed_gids': []},
            'demonstration': {'display_only': True}})

    def assert_workspace_untouched(self):
        for path, data in self.protected.items():
            self.assertEqual(path.read_bytes(), data, f'{path.name} 被改写了')


class SceneAndSelectionTest(_ContextCase):
    def test_context_reuses_the_live_scene_and_the_published_selection(self):
        self.assertEqual(self.publish(1, LABEL_A)[0]['status'], 'OK')
        payload, code = self.hub.read_agent_context(self.session)
        self.assertEqual((code, payload['status']), (200, 'OK'))
        self.assertEqual(payload['schema'], 'figpact.hub.agent_context/1')
        self.assertEqual(payload['target_gid'], LABEL_A)
        self.assertEqual(payload['scope'], SCOPE)
        self.assertIs(payload['stale'], False)

        scene = self.scene()
        expected = sorted(node['gid'] for node in scene['nodes']
                          if node.get('gid') and node.get('scope') == SCOPE)
        listed = payload['scene']['nodes']
        self.assertEqual(sorted(entry['gid'] for entry in listed), expected)
        # 每个条目的几何/文本就是同一帧 Scene 的事实，没有被重算一遍
        for entry in listed:
            node = self.scene_node(entry['gid'])
            self.assertEqual(entry['bounds_mm'], node['bounds_mm'])
            self.assertEqual(entry['text'], node['text'])
            self.assertEqual(entry['type'], node['type'])
            self.assertEqual(entry['measured'], bool(node['measured']))
            self.assertEqual(entry['controlled_by'], [list(path) for path in node['controlled_by']])
        self.assertEqual([entry['gid'] for entry in listed if entry['selected']], [LABEL_A])
        self.assertEqual(payload['scene']['scene_sha256'], self.frame()['scene_sha256'])
        self.assertEqual(payload['scene']['coordinate_reference'], 'canvas_bottom_left')
        self.assertEqual(payload['scene']['unit'], 'mm')

    def test_constraints_come_from_the_selection_and_the_contract_declarations(self):
        self.publish(1, LABEL_A)
        payload, _ = self.hub.read_agent_context(self.session)
        constraints = payload['constraints']
        self.assertEqual(constraints['allow_gids'], [LABEL_A, GUIDE])
        self.assertEqual(constraints['follow_gids'], [GUIDE])
        self.assertEqual(constraints['fixed_gids'], [])
        self.assertNotIn(LABEL_A, constraints['deny_gids'])
        self.assertNotIn(GUIDE, constraints['deny_gids'])
        self.assertIn(CURVE, constraints['deny_gids'])
        self.assertEqual(constraints['coordinate_space']['unit'], 'mm')
        self.assertEqual(constraints['coordinate_space']['reference'], 'canvas_bottom_left')
        self.assertIs(constraints['coordinate_space']['calibrated'], False)

        record = self.contract_record('A')
        declared = constraints['hard_limits']['declared_bindings']
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0]['path'], list(record['path']))
        self.assertEqual([declared[0]['min'], declared[0]['max']],
                         [record['min'], record['max']])
        self.assertEqual(declared[0]['objects'], sorted(record['objects']))
        self.assertIs(declared[0]['objects_within_allow'], True)
        self.assertEqual(declared[0]['scopes'], list(record['scopes']))
        # A 的绑定独占：B/C 的声明不落在许可集合里，故不在回执中
        self.assertEqual([entry['key'] for entry in declared], ['A'])
        self.assertIsNone(constraints['hard_limits']['delta_requested_mm'])

        science = self.session._science
        self.assertEqual(constraints['frozen_science']['digest'], science['digest'])
        self.assertIs(constraints['frozen_science']['manifest_declared'], True)

    def test_scene_lists_only_the_target_scope_and_counts_the_rest(self):
        self.publish(1, LABEL_A)
        payload, _ = self.hub.read_agent_context(self.session)
        outside = payload['scene']['nodes_outside_scope']
        registered = [node['gid'] for node in self.scene()['nodes'] if node.get('gid')]
        inside = [gid for gid in registered if self.scene_node(gid)['scope'] == SCOPE]
        self.assertEqual(len(payload['scene']['nodes']), len(inside))
        self.assertEqual(sum(outside.values()), len(registered) - len(inside))

    def test_impact_attachment_closure_and_co_binding_come_from_engine_facts(self):
        self.publish(1, LABEL_A)
        payload, _ = self.hub.read_agent_context(self.session)
        impact = payload['impact']
        self.assertEqual([entry['gid'] for entry in impact['attached']], [GUIDE])
        self.assertEqual(impact['attached'][0]['relation'], 'guide')
        # 归属闭包：引擎自己算的权威闭包（A 下面声明了 B）
        self.assertEqual(impact['ownership_closure'],
                         self.session._core.owned_closure([LABEL_A]))
        self.assertIn(LABEL_B, impact['ownership_closure'])
        # 连带：引线与 A 走同一条声明绑定路径
        self.assertEqual([entry['gid'] for entry in impact['co_bound']], [GUIDE])
        self.assertEqual(impact['co_bound'][0]['path'],
                         [list(self.contract_record('A')['path'])])
        self.assertEqual(impact['cross_scope'], [])
        self.assertEqual(impact['candidate'], None, '没给候选就不编一个')
        self.assertTrue(impact['rules'] and all(isinstance(rule, str) for rule in impact['rules']))

    def test_a_candidate_delta_is_echoed_without_being_approved(self):
        self.publish(1, LABEL_A)
        payload, code = self.hub.read_agent_context(
            self.session, {'delta_mm': [0.0, 0.15], 'intent': '把 A 上移 0.15mm，别碰引线科学端'})
        self.assertEqual(code, 200)
        candidate = payload['impact']['candidate']
        self.assertEqual(candidate['gid'], LABEL_A)
        self.assertEqual(candidate['delta_mm'], [0.0, 0.15])
        self.assertEqual(candidate['intent_text'], '把 A 上移 0.15mm，别碰引线科学端')
        self.assertEqual(payload['intent_text'], candidate['intent_text'])
        self.assertEqual(payload['constraints']['hard_limits']['delta_requested_mm'], [0.0, 0.15])
        # 只回显，不解释：回执里没有任何"已批准/已验证"的措辞
        blob = json.dumps(payload, ensure_ascii=False)
        for word in ('已批准', '已验证', '已保存', '通过'):
            self.assertNotIn(word, blob)

    def test_cross_scope_binding_is_reported_as_a_scope_spanning_declaration(self):
        self.publish(1, LABEL_C)
        payload, _ = self.hub.read_agent_context(self.session)
        declared = payload['constraints']['hard_limits']['declared_bindings']
        self.assertEqual(declared[0]['scopes'], ['main', 'detail'])
        self.assertEqual([entry['binding'] for entry in payload['impact']['cross_scope']],
                         [['offsets_mm', 'C']])
        self.assertEqual(self.evaluate(LABEL_C)['status'], 'NEEDS_AUTHORING',
                         '同一条事实在引擎那边：跨输出版本的候选被拒')


class GhostFactsTest(_ContextCase):
    def test_ghostable_follows_the_scene_fields_and_the_engine_refusals_agree(self):
        self.publish(1, LABEL_A)
        payload, _ = self.hub.read_agent_context(self.session)
        entries = {entry['gid']: entry for entry in payload['scene']['nodes']}
        self.assertIs(entries[LABEL_A]['ghostable'], True)
        self.assertNotIn('ghost_blockers', entries[LABEL_A])
        for gid, kind in ((CURVE, 'curve'), (GUIDE, 'guide')):
            self.assertIs(entries[gid]['ghostable'], False)
            self.assertTrue(any(kind in reason for reason in entries[gid]['ghost_blockers']),
                            entries[gid]['ghost_blockers'])
        # 不可 ghost 的图元在引擎那边确实拿不到整体平移候选
        refused = self.evaluate(CURVE)
        self.assertEqual(refused['status'], 'INVALID_INTENT')
        accepted = self.evaluate(LABEL_A, follow=[GUIDE])
        self.assertEqual(accepted['status'], 'OK', accepted)
        self.assertAlmostEqual(accepted['measured_delta_mm'][1], 0.15, places=8)

    def test_fully_clipped_scene_fact_is_reported_as_a_ghost_blocker(self):
        self.publish(1, LABEL_A)
        payload, _ = self.hub.read_agent_context(self.session)
        entries = {entry['gid']: entry for entry in payload['scene']['nodes']}
        node = self.scene_node(LABEL_D)
        self.assertIs(node['fully_clipped'], True, '夹具前提：D 被完全裁掉')
        self.assertIs(entries[LABEL_D]['ghostable'], False)
        self.assertTrue(any('完全裁掉' in reason for reason in entries[LABEL_D]['ghost_blockers']),
                        entries[LABEL_D]['ghost_blockers'])

    def test_every_ghost_verdict_is_a_function_of_the_real_scene_fields(self):
        self.publish(1, LABEL_A)
        payload, _ = self.hub.read_agent_context(self.session)
        for entry in payload['scene']['nodes']:
            node = self.scene_node(entry['gid'])
            vetoed = bool(node['fully_clipped']) or not node['measured'] \
                or bool(node.get('annotation')) or node['type'] in ('guide', 'curve', 'panel') \
                or 'guide' in entry['gid']
            self.assertIs(entry['ghostable'], not vetoed, entry['gid'])
            self.assertEqual(bool(entry.get('ghost_blockers')), vetoed, entry['gid'])

    def test_non_ghostable_selection_reports_limits_without_inventing_a_candidate(self):
        self.assertEqual(self.publish(1, GUIDE)[0]['status'], 'OK')
        payload, code = self.hub.read_agent_context(self.session)
        self.assertEqual((code, payload['status']), (200, 'OK'))
        self.assertEqual(payload['target_gid'], GUIDE)
        constraints = payload['constraints']
        self.assertEqual(constraints['follow_gids'], [], '引线没有再附着的东西')
        self.assertEqual(constraints['allow_gids'], [GUIDE])
        self.assertNotIn(GUIDE, constraints['deny_gids'])
        # 引线出现在 A 的绑定 objects 里；那次绑定的 objects 整体落不进 {guide}，
        # 因此这条绑定不服务于本次选择（引擎铸造候选的前置条件）。
        declared = constraints['hard_limits']['declared_bindings']
        self.assertEqual([entry['key'] for entry in declared], ['A'])
        self.assertEqual(declared[0]['objects'], sorted([LABEL_A, GUIDE]))
        self.assertIs(declared[0]['objects_within_allow'], False)
        reasons = [entry['why'] for entry in constraints['not_independently_tunable']
                   if entry['gid'] == GUIDE]
        self.assertTrue(any('不可独立微调' in reason for reason in reasons), reasons)
        self.assertTrue(any('预览' in reason for reason in reasons), reasons)
        guide_entry = next(entry for entry in payload['scene']['nodes'] if entry['gid'] == GUIDE)
        self.assertIn('annotation', guide_entry)
        self.assertIs(guide_entry['annotation']['independent_endpoint_editable'], False)
        self.assertEqual(self.evaluate(GUIDE)['status'], 'INVALID_INTENT',
                         '引擎同样不受理引线的整体平移')


class CrossScopeSelectionTest(_ContextCase):
    def test_selection_scope_mismatch_is_flagged_like_the_engine_refuses_it(self):
        self.publish(1, LABEL_A, scope='detail')
        payload, code = self.hub.read_agent_context(self.session)
        self.assertEqual(code, 200)
        mismatch = payload['constraints']['scope_mismatch']
        self.assertEqual((mismatch['selection_scope'], mismatch['target_scope']), ('detail', SCOPE))
        self.assertEqual(payload['scope'], SCOPE, 'scope 取自目标图元本身')
        refused = self.evaluate(LABEL_A, scope='detail')
        self.assertEqual(refused['status'], 'INVALID_INTENT',
                         '同一条事实在引擎那边：跨 scope 意图被拒')

    def test_other_scope_nodes_are_counted_not_listed(self):
        self.publish(1, LABEL_A)
        payload, _ = self.hub.read_agent_context(self.session, {'gid': LABEL_B})
        self.assertEqual(payload['target_gid'], LABEL_B)
        self.assertEqual([entry['gid'] for entry in payload['scene']['nodes']
                          if entry['selected']], [LABEL_B])
        self.assertEqual(payload['constraints']['allow_gids'], [LABEL_B])


class UnknownGidTest(_ContextCase):
    def test_unknown_gid_lists_the_frame_and_refuses_to_invent_anything(self):
        before_frame = self.frame()['frame_revision']
        payload, code = self.hub.read_agent_context(self.session, {'gid': 'agent.main.NOPE'})
        self.assertEqual(code, 404)
        self.assertEqual(payload['status'], 'UNKNOWN_GID')
        self.assertIsNone(payload['target_gid'])
        self.assertIn('agent.main.NOPE', payload['message'])
        known = sorted(node['gid'] for node in self.scene()['nodes'] if node.get('gid'))
        self.assertEqual(sorted(entry['gid'] for entry in payload['scene']['nodes']
                                if entry['scope'] == SCOPE), known)
        self.assertEqual(payload['constraints']['allow_gids'], [])
        self.assertEqual(payload['constraints']['deny_gids'], known)
        self.assertEqual(payload['constraints']['hard_limits']['declared_bindings'], [])
        self.assertIsNone(payload['impact']['candidate'])
        self.assertEqual(payload['impact']['attached'], [])
        self.assertTrue(payload['impact']['rules'])
        # 只读：帧、候选、选区、计划、磁盘字节一律不动
        self.assertEqual(self.frame()['frame_revision'], before_frame)
        self.assertIsNone(self.session._pending)
        self.assertEqual(self.session._accepted, [])
        self.assertEqual(self.frame()['session']['accepted_operation_ids'], [])
        self.assertEqual(self.hub.read_plans(), ({'status': 'OK', 'plans': []}, 200))
        self.assertIsNone(self.hub.selection)
        self.assertEqual(self.hub.hub_revision, 0)
        self.assert_workspace_untouched()

    def test_no_selection_falls_back_to_the_frame_scope_and_rules(self):
        payload, code = self.hub.read_agent_context(self.session)
        self.assertEqual(code, 200)
        self.assertEqual(payload['status'], 'NO_SELECTION')
        self.assertIsNone(payload['target_gid'])
        self.assertEqual(payload['scene']['scope'], SCOPE)
        self.assertEqual(payload['scene']['scope_source'], 'frame')
        self.assertEqual(payload['constraints']['allow_gids'], [])
        self.assertTrue(payload['scene']['nodes'])
        self.assertTrue(payload['impact']['rules'])

    def test_bad_input_is_rejected_without_touching_the_session(self):
        for body in ('gid', [], 3):
            self.assertEqual(self.hub.read_agent_context(self.session, body)[0]['status'],
                             'INVALID_CONTEXT')
        for body in ({'gid': ''}, {'gid': 5}, {'delta_mm': [0.0]}, {'delta_mm': ['x', 1.0]},
                     {'delta_mm': [float('nan'), 0.0]}, {'intent': 7}):
            payload, code = self.hub.read_agent_context(self.session, body)
            self.assertEqual((code, payload['status']), (400, 'INVALID_CONTEXT'), body)
        self.assertIsNone(self.session._pending)
        self.assert_workspace_untouched()

    def test_a_closed_session_is_reported_as_closed(self):
        self.session.close()
        payload, code = self.hub.read_agent_context(self.session)
        self.assertEqual((code, payload['status']), (409, 'SESSION_CLOSED'))


if __name__ == '__main__':
    unittest.main()
