"""G6b 作者化写回（``kind='authoring_edit'``）：真实回环 HTTP + 真实临时源码 + 真实重建。

被测的是**无绑定**脚本的受控作者化写回：``authoring.plan_authoring_binding`` 生成最小补丁
（模块级位移映射 + 取值助手 + 只改写目标那一个 ``xytext=`` 实参），Hub 用同一条
authorize/apply/cancel 链铸造与放行。断言全打在可观察事实上：HTTP 状态与错误信封、磁盘
字节、``source_writes`` journal 状态、history 检查点，以及**另起进程真实重建**后的显示几何
与科学指纹。文件系统、state_home、HTTP 都是真的：不 mock 任何一层。

单位是 **pt**（调用现场 ``textcoords="offset points"`` 的坐标系）：``value_pt=[0, 0]`` 只该
把脚本改写成等价形式（重建与原件逐位相同），``value_pt=[0, 2.0]`` 只该让目标标签走 2pt。
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import http.client
import json
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact import authoring, python_native  # noqa: E402
from figpact.history import HistoryStore  # noqa: E402
from figpact.inspector_server import InspectorServer  # noqa: E402

FIXTURE = ROOT / 'examples' / 'python_native' / 'legacy_plain.py'
GID = 'legacy.main.label.A'
OTHER_GID = 'legacy.main.label.B'
CURVE_GID = 'legacy.main.curve'
TARGET_KEY = f'gid:{GID}'
#: 目标调用现场的原始 `xytext`：`base_offset_pt` 声明的就是它，补丁从它算起。
BASE_XYTEXT = (0.0, 4.0)
BASE_LITERAL = 'xytext=(0.0, 4.0)'
#: 2pt 换算成 mm（重建量出来的是 mm 包围盒）。
PT_TO_MM = 25.4 / 72.0
SHIFT_MM = (0.0, 2.0 * PT_TO_MM)
#: 重建实测容差（mm）：字体光栅化在亚像素上会有一点抖动。
TOL_MM = 0.2
CLIENT_A, CLIENT_B = 'agent-A', 'agent-B'
#: 线路上的契约名字（测试守协议本身，不引用实现常量）。
UI_HEADER = 'X-Figpact-Ui'
CLIENT_HEADER = 'X-Figpact-Client'
NO_BODY = object()


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


def http_text(port, path):
    status, raw = _request(port, 'GET', path, NO_BODY, {})
    return status, raw.decode('utf-8')


def measure(script: Path, config: Path, scope: str = 'main') -> dict:
    """另起一个进程，按会话真实接缝重建一次 → ``{geometry, gids, science_sha256}``。

    复用既有的重建探针（``python_native._measure_geometry``）：量到的是**磁盘上那份源码**
    画出来的毫米几何，与本次写入无关。刻意不在本进程里量——本进程刚碰过这份源码。
    """
    return python_native._measure_geometry(Path(script), Path(config), scope)


def inserted_block(value_pt: list[float]) -> str:
    """本 kind 应当插入的那一段（含前后各一处换行），逐字写死供字节级比对。"""
    return ('\n'
            f'{authoring.LEGACY_OFFSET_BINDING} = {{"{GID}": '
            f'[{", ".join(repr(number) for number in value_pt)}]}}\n'
            '\n'
            '\n'
            f'def {authoring.LEGACY_OFFSET_HELPER}(gid, base):\n'
            f'    dx, dy = {authoring.LEGACY_OFFSET_BINDING}.get(gid, (0.0, 0.0))\n'
            '    return (base[0] + dx, base[1] + dy)\n'
            '\n')


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


class _WriteBackCase(unittest.TestCase):
    """一条用例一个临时工程 + 一个临时 state_home + 一个真实回环服务器。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='figpact-authoring-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project, self.script, self.config = self.arm('project')
        self.state = self.root / 'state'
        self.original = self.script.read_bytes()
        self.original_text = self.original.decode('utf-8')
        self.server, self.port = None, None

    def arm(self, name, data=None):
        """一份独立的工程副本：``<arm>/examples/python_native/legacy_plain.py`` + ``<arm>/plot.yaml``。

        副本保留目录深度（夹具自己按 ``parents[2]`` 找仓库根），装载路径与真实工程同形。
        """
        home = self.root / name
        script = home / 'examples' / 'python_native' / FIXTURE.name
        script.parent.mkdir(parents=True)
        script.write_bytes(FIXTURE.read_bytes() if data is None else data)
        config = home / 'plot.yaml'
        config.write_text('{}\n', encoding='utf8')
        return home, script, config

    def start(self):
        server = InspectorServer(_FakeSession(), ('127.0.0.1', 0), state_home=self.state,
                                 source={'script': str(self.script),
                                         'config': str(self.config), 'scope': 'main'})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # addCleanup 是后进先出：shutdown → join → close。
        self.addCleanup(server.server_close)
        self.addCleanup(lambda: thread.join(5))
        self.addCleanup(server.shutdown)
        self.server, self.port = server, server.server_address[1]
        self.token = self.frame_token()
        return server

    def frame_token(self):
        """页面拿令牌的唯一途径：服务端服务页面时注入 ``/frame.js``。"""
        status, text = http_text(self.port, '/frame.js')
        self.assertEqual(status, 200)
        match = re.search(r'window\.FIGPACT_UI_TOKEN=("(?:[^"\\]|\\.)*");', text)
        self.assertIsNotNone(match, text)
        token = json.loads(match.group(1))
        self.assertEqual(token, self.server.ui_token)
        return token

    # 路由的薄封装。

    def mint_raw(self, *, client=CLIENT_A, value_pt=(0.0, 2.0), base=BASE_XYTEXT, gid=GID):
        return http_json(self.port, 'POST', '/api/plans', {
            'client_id': client, 'kind': 'authoring_edit', 'script': str(self.script),
            'gid': gid, 'value_pt': list(value_pt),
            'base_offset_pt': None if base is None else list(base),
            'reason': 'G6b 用例：给无绑定脚本新增这一处局部自由度'})

    def mint(self, **kwargs):
        status, payload = self.mint_raw(**kwargs)
        self.assertEqual((status, payload['status']), (200, 'OK'), payload)
        return payload['plan']

    def authorize(self, plan_id, token=None):
        headers = {} if token is None else {UI_HEADER: token}
        return http_json(self.port, 'POST', f'/api/plans/{plan_id}/authorize', NO_BODY, headers)

    def apply_plan(self, plan_id, *, client=CLIENT_A, body=NO_BODY):
        headers = {} if client is None else {CLIENT_HEADER: client}
        return http_json(self.port, 'POST', f'/api/plans/{plan_id}/apply', body, headers)

    # 磁盘 / journal / history 的事实读取。

    def journal(self, plan):
        return json.loads((self.state / 'source-journals' /
                           f"{plan['journal_id']}.json").read_text(encoding='utf-8'))

    def checkpoints(self):
        store = HistoryStore(self.script, self.config, 'main', state_home=self.state)
        try:
            return store.source_changes()
        finally:
            store.close()


class AuthoringPlanGateTest(_WriteBackCase):
    """授权门：没有页面令牌 / 不是申请者 / 还没同意，一个字节都不许动。"""

    def test_apply_without_page_consent_writes_nothing(self):
        self.start()
        plan = self.mint()
        status, payload = self.apply_plan(plan['plan_id'], body={'authorized': True})
        self.assertEqual((status, payload['status']), (409, 'PLAN_NOT_PENDING'))
        self.assertEqual(self.script.read_bytes(), self.original)
        self.assertEqual(self.journal(plan)['status'], 'PREPARED')
        self.assertEqual(self.checkpoints(), [])

    def test_wrong_token_authorize_is_forbidden(self):
        self.start()
        plan = self.mint()
        for label, token in (('缺 header', None), ('错 token', 'not-the-served-page-token'),
                             ('空 header', '')):
            with self.subTest(label):
                status, payload = self.authorize(plan['plan_id'], token)
                self.assertEqual(status, 403, payload)
                self.assertEqual(payload['status'], 'FORBIDDEN')
                self.assertIn(UI_HEADER, payload['message'])
        self.assertEqual(self.script.read_bytes(), self.original)
        self.assertEqual(self.server.hub._plans[plan['plan_id']]['state'], 'PENDING')
        self.assertEqual(self.server.hub._grants, {})
        self.assertEqual(self.checkpoints(), [])

    def test_wrong_client_cannot_apply(self):
        self.start()
        plan = self.mint(client=CLIENT_A)
        self.assertEqual(self.authorize(plan['plan_id'], self.token)[0], 200)
        status, payload = self.apply_plan(plan['plan_id'], client=CLIENT_B)
        self.assertEqual((status, payload['status']), (403, 'FORBIDDEN'))
        self.assertIn(CLIENT_A, payload['message'])
        # 没有 client header 的请求连计划都不查。
        status, payload = self.apply_plan(plan['plan_id'], client=None)
        self.assertEqual((status, payload['status']), (403, 'FORBIDDEN'))
        self.assertEqual(self.script.read_bytes(), self.original)
        self.assertEqual(self.journal(plan)['status'], 'PREPARED')
        self.assertIs(self.server.hub._grants[plan['plan_id']]['used'], False)
        self.assertEqual(self.checkpoints(), [])


class AuthoringPatchBytesTest(_WriteBackCase):
    """授权后的写入：磁盘字节等于计划的 after，且补丁只动目标那一处。"""

    def test_authorized_apply_writes_exactly_the_planned_source(self):
        self.start()
        plan = self.mint(value_pt=[0.0, 2.0])
        self.assertEqual(plan['kind'], 'authoring_edit')
        self.assertEqual(plan['units'], 'pt')
        self.assertEqual(plan['value'], [0.0, 2.0])
        self.assertEqual(plan['base_offset_pt'], [0.0, 4.0])
        self.assertEqual([entry['path'] for entry in plan['files']], [str(self.script)])
        # 铸造计划写 journal/blob，但零字节写用户源码。
        self.assertEqual(self.script.read_bytes(), self.original)
        self.assertEqual(self.journal(plan)['status'], 'PREPARED')

        self.assertEqual(self.authorize(plan['plan_id'], self.token)[0], 200)
        status, payload = self.apply_plan(plan['plan_id'])
        self.assertEqual((status, payload['status']), (200, 'OK'), payload)
        self.assertEqual(payload['commit_state'], python_native.COMMITTED_AND_VERIFIED)
        self.assertIsNotNone(payload['checkpoint_id'])

        written = self.script.read_bytes()
        self.assertEqual(hashlib.sha256(written).hexdigest(), plan['files'][0]['after_sha256'])
        after_text = written.decode('utf-8')

        # ① 目标那一行确实被改写，且其它字节逐位原样：去掉插入的那一段后，
        #    剩下的文本必须等于「原件里只把目标实参换掉」的文本。
        self.assertEqual(self.original_text.count(BASE_LITERAL), 1)
        expected = self.original_text.replace(
            BASE_LITERAL,
            f'xytext={authoring.LEGACY_OFFSET_HELPER}("{GID}", (0.0, 4.0))', 1)
        block = inserted_block([0.0, 2.0])
        self.assertEqual(after_text.count(block), 1, after_text)
        self.assertEqual(after_text.replace(block, '', 1), expected)
        # 插入位置就在 docstring/imports 之后（最后一条 import 与第一处声明之间）。
        self.assertLess(after_text.index('from figpact import GidRegistry'),
                        after_text.index(block))
        self.assertLess(after_text.index(block), after_text.index('FIGURE_ID = "legacy"'))

        # ② 计划的 diff 与上面的事实一致：两个 hunk，一个删行、九个增行。
        diff = plan['files'][0]['diff']
        self.assertEqual(diff.count('\n@@ '), 2, diff)
        removed = [line for line in diff.splitlines()
                   if line.startswith('-') and not line.startswith('---')]
        self.assertEqual(removed, ['-    label_a = ax.annotate("A", xy=(2.0, 0.62), '
                                  + BASE_LITERAL + ','], diff)

        # ③ 补丁在语法与语义上都是「插入一个映射 + 一个助手 + 一次性改写」。
        tree = ast.parse(after_text)
        tables = {target.id: node.value for node in tree.body
                  for target in getattr(node, 'targets', [])
                  if isinstance(target, ast.Name)}
        self.assertEqual(ast.literal_eval(tables[authoring.LEGACY_OFFSET_BINDING]),
                         {GID: [0.0, 2.0]})
        helpers = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(helpers.count(authoring.LEGACY_OFFSET_HELPER), 1)

        # ④ history 里的位移必须带单位：pt 不是 mm。
        (checkpoint,) = self.checkpoints()
        self.assertEqual(checkpoint['payload']['units'], 'pt')
        self.assertEqual(checkpoint['payload']['requested_pt'], [0.0, 2.0])
        self.assertNotIn('requested_mm', checkpoint['payload'])

    def test_route_passes_through_generator_rejections_and_mints_nothing(self):
        self.start()
        status, payload = self.mint_raw(value_pt=('x', 1.0))
        self.assertEqual((status, payload['status']), (400, 'INVALID'), payload)
        status, payload = self.mint_raw(base=(9.0, 9.0))
        self.assertEqual((status, payload['status']), (409, 'STALE_BASE'), payload)
        self.assertEqual(payload['confidence'], 'low')
        self.assertTrue(payload['candidates'])
        status, payload = self.mint_raw(gid='legacy.main.label.MISSING')
        self.assertEqual((status, payload['status']), (409, 'NEEDS_AUTHORING'), payload)
        # 没有 gid 证据时如实列候选：就是那两处 annotate 调用，一个都不许猜着改。
        self.assertEqual([(item['line'], item['text'], item['xytext'])
                          for item in payload['candidates']],
                         [(91, 'A', [0.0, 4.0]), (96, 'B', [0.0, 9.0])])
        self.assertEqual([item['evidence'] for item in payload['candidates']], [[], []])
        self.assertTrue(all('没有任何证据' in item['why'][0] for item in payload['candidates']))

        # 候选不唯一：同一现场多出一处同标签、同形状的调用 → AMBIGUOUS，零写入。
        call = ('    label_a = ax.annotate("A", xy=(2.0, 0.62), xytext=(0.0, 4.0),\n'
                '                          textcoords="offset points", ha="center", '
                'va="bottom", fontsize=7.0)')
        ambiguous = self.original_text.replace(
            call, call.replace('label_a', 'twin') + '\n' + call, 1)
        self.assertNotEqual(ambiguous, self.original_text)
        # 按字节写：文本模式的写会把 LF 翻成 os.linesep，磁盘上就不是同一份字节了。
        self.script.write_bytes(ambiguous.encode('utf-8'))
        status, payload = self.mint_raw()
        self.assertEqual((status, payload['status']), (409, 'AMBIGUOUS'), payload)
        self.assertEqual([(item['line'], item['evidence'])
                          for item in payload['candidates'] if item['evidence']],
                         [(91, ['label']), (93, ['binding', 'label'])])

        # 四次拒绝都不铸造计划、不写 journal、不改磁盘。
        self.assertEqual(self.server.hub._plans, {})
        self.assertEqual(self.script.read_bytes(), ambiguous.encode('utf-8'))
        self.assertFalse((self.state / 'source-journals').exists())


class AuthoringRebuildTest(_WriteBackCase):
    """独立重建：脚本改完之后，画出来的东西必须与声明的位移一致。"""

    def apply_value(self, value_pt):
        self.start()
        plan = self.mint(value_pt=value_pt)
        self.assertEqual(self.authorize(plan['plan_id'], self.token)[0], 200)
        status, payload = self.apply_plan(plan['plan_id'])
        self.assertEqual((status, payload['status']), (200, 'OK'), payload)
        self.assertEqual(hashlib.sha256(self.script.read_bytes()).hexdigest(),
                         plan['files'][0]['after_sha256'])
        return plan

    def test_zero_shift_rebuilds_bit_identically(self):
        plan = self.apply_value([0.0, 0.0])
        self.assertEqual(plan['value'], [0.0, 0.0])
        _home, base_script, base_config = self.arm('baseline')
        baseline = measure(base_script, base_config)
        rebuilt = measure(self.script, self.config)
        self.assertEqual(rebuilt['gids'], baseline['gids'])
        self.assertEqual(rebuilt['gids'], sorted((CURVE_GID, GID, OTHER_GID)))
        self.assertEqual(rebuilt['science_sha256'], baseline['science_sha256'])
        # `value_pt=[0, 0]` 的补丁是等价改写：显示几何逐位相同（不是"容差内相同"）。
        self.assertEqual(rebuilt['geometry'], baseline['geometry'])

    def test_two_point_shift_moves_only_the_target_label(self):
        self.apply_value([0.0, 2.0])
        _home, base_script, base_config = self.arm('baseline')
        baseline = measure(base_script, base_config)
        rebuilt = measure(self.script, self.config)
        self.assertEqual(rebuilt['gids'], baseline['gids'])
        self.assertEqual(rebuilt['science_sha256'], baseline['science_sha256'])
        self.assertEqual(sorted(rebuilt['geometry']), sorted(baseline['geometry']))
        for key in sorted(baseline['geometry']):
            if key == TARGET_KEY:
                continue
            self.assertEqual(rebuilt['geometry'][key], baseline['geometry'][key],
                             f'{key} 跟着目标动了')
        moved = [rebuilt['geometry'][TARGET_KEY][axis] - baseline['geometry'][TARGET_KEY][axis]
                 for axis in (0, 1)]
        self.assertAlmostEqual(moved[0], SHIFT_MM[0], delta=1e-6, msg='x 不该动')
        self.assertAlmostEqual(moved[1], SHIFT_MM[1], delta=TOL_MM,
                               msg=f'标签实测位移 {moved[1]} mm，请求 {SHIFT_MM[1]} mm')


if __name__ == '__main__':
    unittest.main()
