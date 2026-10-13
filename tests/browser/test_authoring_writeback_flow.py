"""G6b 层 1 门禁：``kind='authoring_edit'`` 作者化写回的**真浏览器**端到端与对抗面。

被测的是**无绑定**脚本（``examples/python_native/legacy_plain.py``：模块级连那个众所周知的
位移映射名都一次没出现）的作者化写回：客户端铸造计划 → 页面长出可授权的计划条 → 页面点
「授权」→ 申请它的客户端 apply → 磁盘字节改变、history 追加 ``source_change`` → **另起进程**
独立重建验证显示几何。

为什么这份门禁必须存在：``tests/test_authoring_writeback.py`` 是实现单元自己写的用例，不算
独立验收；而既有的层 1 真浏览器门禁 ``test_g5b_workflow.py`` 只覆盖 ``kind='layout_edit'``，
``authoring_edit`` 这条路径的页面 × 子进程 × 写盘回环此前没有任何独立覆盖。本文件把同一套
台子架到 ``authoring_edit`` 上，并额外守三件 layout_edit 不需要守的事：

  * 补丁**只动目标那一处**（逐行对齐证明：一处插入 + 一处单行替换，其余字节逐位原样）；
  * 单位是 **pt**（``value_pt`` / ``units`` / history 里的 ``requested_pt``），不是 mm；
  * 重建后**别的 gid 与科学指纹一动不动**。

台子：``conftest.launch_server`` 起一个真实 ``python -m figpact.inspector_server --script
<副本> --config <config>`` 子进程（state_home 在该用例的临时目录里），``browser`` 是 conftest
的会话级 Chromium；写盘目标是**服务端正在服务的那份脚本的副本** —— ``examples/`` 下的夹具
源码一个字节都不许被测试改写。计划 / journal / history 的事实一律从磁盘读回，HTTP 码只是入口。

失败时：``conftest.pytest_runtest_makereport`` 打印子进程 stderr 尾部（本文件的服务也登记进
``_LIVE_SERVERS``），本文件的 ``trial`` 夹具另打印页面现场（就绪位、``#agent-plans``、
HTML 尾部）；导入的 g5b 选择器助手在失败消息里也带页面现场。

怎么跑::

    python -m pytest tests/browser/test_authoring_writeback_flow.py -q

临时/状态目录：``FIGPACT_BROWSER_WORKDIR``（默认父代理指定的归档目录）下每个用例一个
``tempfile.mkdtemp``，用例收尾把子进程与这个目录一起删掉，不留残余状态。
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from figpact import python_native

from .conftest import (CLIENT_ID, NO_HEADER, REPO_ROOT, UI_HEADER, launch_server,
                       node_by_gid, open_page, scene_of, sha256_bytes, sha256_file)
from .test_g5b_workflow import await_authorized, click_plan_action, plan_strip, publish_label

#: 线上契约的字面量：测试守的是协议本身，不是实现里的常量。
AUTHORING_KIND = 'authoring_edit'
COMMITTED_AND_VERIFIED = 'COMMITTED_AND_VERIFIED'

#: 被服务的夹具：**没有**任何绑定，gid 字面量只出现在 ``ax.annotate(...)`` 调用现场。
FIXTURE_SCRIPT = REPO_ROOT / 'examples' / 'python_native' / 'legacy_plain.py'
TARGET_GID = 'legacy.main.label.A'
#: 目标调用现场的标签文本（gid 的末段）：调用那一行上只有它，gid 字面量在旁边的 register 行。
TARGET_LABEL = TARGET_GID.rsplit('.', 1)[-1]
OTHER_GIDS = ('legacy.main.curve', 'legacy.main.label.B')
TARGET_KEY = f'gid:{TARGET_GID}'
#: 目标调用现场的原始 ``xytext``（``base_offset_pt`` 声明的就是它）与本次请求的 pt 位移。
BASE_XYTEXT = (0.0, 4.0)
VALUE_PT = (0.0, 2.0)
BASE_LITERAL = 'xytext=(0.0, 4.0)'
#: 2pt 换算成 mm：重建量出来的是 mm 包围盒。
PT_TO_MM = 25.4 / 72.0
SHIFT_MM = (0.0, 2.0 * PT_TO_MM)
#: 重建实测容差（mm）：字体光栅化在亚像素上会有一点抖动。
TOL_MM = 0.2

#: 临时/状态根：父代理指定的归档目录；可用环境变量覆盖（测试本身不绑盘符）。
WORK_ROOT = Path(os.environ.get('FIGPACT_BROWSER_WORKDIR')
                 or 'D:/L/AI/figpact-archive/g6b-v2/browser-authoring')


def _plus(diff: str) -> list[str]:
    return [line for line in diff.splitlines()
            if line.startswith('+') and not line.startswith('+++')]


def _minus(diff: str) -> list[str]:
    return [line for line in diff.splitlines()
            if line.startswith('-') and not line.startswith('---')]


def _inserted_symbol(diff: str) -> str:
    """从 diff 的增行里读出这次插入的模块级映射表名（不引用实现常量，页面显示的也是它）。"""
    match = re.search(r'^\+([A-Z_][A-Z0-9_]*) = \{', diff, re.M)
    assert match, f'diff 里没有「模块级映射表」的新增行：{diff!r}'
    return match.group(1)


def _line_edits(original: str, applied: str):
    """逐行对齐两份文本，产出**非 equal** 的编辑块 ``(标签, 原行, 新行)``。

    在真实内容上按行对齐（``SequenceMatcher`` 直接看两份文本，不是拿"预期补丁"的字符串去
    拼），所以「补丁只动目标那一处」这句话是对全文的逐行证明，不是重建一个期望值。
    """
    before = original.splitlines(keepends=True)
    after = applied.splitlines(keepends=True)
    opcodes = difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != 'equal':
            yield tag, before[i1:i2], after[j1:j2]


def measure(script: Path, config: Path, scope: str = 'main') -> dict:
    """另起一个进程重建一次 → ``{geometry, gids, science_sha256}``（产品自己的重建探针）。"""
    return python_native._measure_geometry(Path(script), Path(config), scope)


def _arm_project(root: Path):
    """服务端要加载的脚本副本：与夹具逐字节相同，并保留目录深度（夹具自己按 parents[2] 找根）。

    工程放在 ``<root>/project`` 下：history 的 state_home（``<root>/state``）必须落在脚本与
    配置目录**之外**，这是 HistoryStore 的硬要求，也是真实工程的形状。
    """
    project = root / 'project'
    script = project / 'examples' / 'python_native' / FIXTURE_SCRIPT.name
    script.parent.mkdir(parents=True)
    script.write_bytes(FIXTURE_SCRIPT.read_bytes())
    config = project / 'plot.yaml'
    config.write_text('{}\n', encoding='utf-8')
    return script, config


class Trial:
    """一个用例的现场：真子进程服务 + 服务端正在服务的那份脚本副本 + 真页面句柄。"""

    def __init__(self, script, config, server):
        self.script = script
        self.config = config
        self.server = server
        #: 服务端加载的那份字节：这次门禁的一切对比都以它为底座。
        self.original = script.read_bytes()
        self._contexts = []

    # ---- 页面

    def open(self, browser):
        """开一个全新浏览器上下文（页面自己声明图帧已核对一致才返回）。"""
        context, page = open_page(browser, self.server.base_url)
        self._contexts.append(context)
        self.page = page
        return page

    def close(self):
        """真关掉所有上下文（不是藏起来）：后端与磁盘的事实必须自己站着。"""
        for context in self._contexts:
            context.close()
        self._contexts.clear()

    # ---- 线路：作者化计划的形状是协议的一部分

    def mint(self, *, gid=TARGET_GID, value_pt=VALUE_PT):
        status, payload = self.server.json('POST', '/api/plans', {
            'client_id': CLIENT_ID, 'kind': AUTHORING_KIND, 'script': str(self.script),
            'gid': gid, 'value_pt': list(value_pt), 'base_offset_pt': list(BASE_XYTEXT),
            'reason': 'G6b 层 1 门禁：给无绑定脚本新增这一处局部自由度，页面授权后才写盘'})
        assert (status, payload['status']) == (200, 'OK'), \
            f'铸造 {AUTHORING_KIND} 计划被拒：HTTP {status} {payload}'
        return payload['plan']

    # ---- 磁盘 / journal / history 的事实读取

    def sha256(self) -> str:
        return sha256_file(self.script)

    def journal_bytes(self, plan) -> bytes:
        path = self.server.journal_path(plan)
        assert path.exists(), f'铸造计划就该留下 journal：{path}'
        return path.read_bytes()

    def checkpoints(self) -> list[dict]:
        return self.server.checkpoints(self.script)


def _failed(node) -> bool:
    """这个用例的调用阶段失败了吗（conftest 的 makereport 钩子把报告挂在用例上）。"""
    report = getattr(node, 'rep_call', None)
    return report is not None and report.failed


@pytest.fixture
def trial(browser, request):
    """一个用例的现场：真服务子进程（服务的是脚本副本）+ 真页面；收尾连临时目录一起清掉。"""
    assert FIXTURE_SCRIPT.is_file(), f'缺少无绑定的夹具脚本：{FIXTURE_SCRIPT}'
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='case-', dir=str(WORK_ROOT)))
    script, config = _arm_project(root)
    server = launch_server(root, command=[sys.executable, '-m', 'figpact.inspector_server',
                                          '--script', str(script), '--config', str(config),
                                          '--scope', 'main', '--dpi', '240', '--port', '0'],
                           config=config)
    handle = Trial(script, config, server)
    try:
        handle.open(browser)
        yield handle
    finally:
        page = getattr(handle, 'page', None)
        if page is not None and _failed(request.node):
            print('--- 页面 HTML 尾（用例失败现场）---\n' + page.debug(), flush=True)
        handle.close()
        server.stop()
        shutil.rmtree(root, ignore_errors=True)


def test_minting_writes_no_source_bytes_and_the_patch_has_three_parts(trial):
    """① 铸造 authoring_edit 计划：待授权、三处补丁齐备、源码与 journal 零改动。"""
    plan = trial.mint()

    assert plan['kind'] == AUTHORING_KIND and plan['gid'] == TARGET_GID
    assert plan['state'] == 'PENDING' and plan['client_id'] == CLIENT_ID
    # 单位是 pt：mm 与 pt 差 2.8 倍，读的人不能靠猜。
    assert plan['units'] == 'pt' and plan['value'] == [0.0, 2.0]
    assert plan['base_offset_pt'] == [0.0, 4.0], '计划必须带头声明它从哪个现场值算起'
    assert [entry['path'] for entry in plan['files']] == [str(trial.script)]

    diff = plan['files'][0]['diff']
    assert diff.count('\n@@ ') == 2, f'补丁该是两处 hunk：{diff}'
    removed = _minus(diff)
    assert len(removed) == 1, f'补丁只该删一行：{removed}'
    assert BASE_LITERAL in removed[0] and 'ax.annotate(' in removed[0], removed
    assert f'"{TARGET_LABEL}"' in removed[0], f'删的不是目标那一行：{removed}'
    added = _plus(diff)
    symbol = _inserted_symbol(diff)
    # 三处补丁：映射表、取值助手、目标那一行的 xytext 改写。
    assert any(f'{symbol} = {{"{TARGET_GID}": [0.0, 2.0]}}' in line for line in added), added
    defs = [line.lstrip('+') for line in added if line.lstrip('+').startswith('def ')]
    assert len(defs) == 1 and defs[0].endswith('(gid, base):'), added
    assert any('.get(gid, (0.0, 0.0))' in line for line in added), added
    helper = re.search(r'^def (\w+)\(gid, base\):$', defs[0]).group(1)
    rewritten = [line for line in added if 'xytext=' in line]
    assert len(rewritten) == 1, f'xytext 只该在目标那一行被改写：{rewritten}'
    assert TARGET_GID in rewritten[0] and f'xytext={helper}(' in rewritten[0], rewritten
    assert BASE_LITERAL not in rewritten[0], rewritten

    # 零字节写用户源码：磁盘仍逐字节等于服务端加载的那份，journal 停在 PREPARED。
    assert trial.sha256() == sha256_bytes(trial.original)
    assert trial.server.journal_status(plan) == 'PREPARED'
    assert trial.checkpoints() == []


def test_the_plan_strip_shows_the_inserted_symbol_and_the_target_line(trial):
    """② 页面长出这条计划：``[data-plan-diff]`` 里看得到新插入的符号与目标那一行。"""
    plan = trial.mint()
    strip = plan_strip(trial.page, plan['plan_id'])
    assert strip.query_selector('[data-plan-action="authorize"]') is not None, '缺授权按钮'
    assert strip.query_selector('[data-plan-status]') is not None, '缺状态位'

    diff = plan['files'][0]['diff']
    shown = strip.query_selector('[data-plan-diff]').inner_text()
    assert _inserted_symbol(diff) in shown, f'页面没显示新插入的符号：{shown!r}'
    assert _minus(diff)[0] in shown, f'页面没显示被改写的那一行：{shown!r}'
    assert TARGET_GID in shown and str(trial.script) in shown and '@@' in shown, shown
    summary = strip.inner_text()
    assert TARGET_GID in summary, f'计划条没写 gid：{summary!r}'
    # 页面自己渲染的值（planValueText 去掉了多余的尾零）：pt 位移读得出来。
    assert '[0, 2]' in summary, f'计划条没写这次的 pt 位移：{summary!r}'

    # 页面显示的和服务器事实同源：仍是待授权、还没 grant、磁盘没动。
    server_plan = trial.server.plan(plan['plan_id'])
    assert server_plan['state'] == 'PENDING' and server_plan['grant'] is None
    assert trial.sha256() == sha256_bytes(trial.original)


def test_forged_page_consent_is_refused_and_changes_nothing(trial):
    """③ 伪造授权：不带／带错 ``X-Figpact-Ui`` 一律 403；计划 PENDING、磁盘与 journal 逐字节不变。"""
    plan = trial.mint()
    plan_strip(trial.page, plan['plan_id'])
    disk_before = trial.script.read_bytes()
    journal_before = trial.journal_bytes(plan)

    for label, token in (('缺 header', NO_HEADER), ('错 token', 'not-the-served-page-token')):
        status, payload = trial.server.authorize(plan['plan_id'], token=token)
        assert (status, payload['status']) == (403, 'FORBIDDEN'), \
            f'{label} 的授权竟然被接受：HTTP {status} {payload}'
        assert UI_HEADER in payload['message'], payload

    refused = trial.server.plan(plan['plan_id'])
    assert refused['state'] == 'PENDING', '伪造的同意不许把计划推成 AUTHORIZED'
    assert refused['grant'] is None, '伪造的同意不许结出 grant'
    assert trial.script.read_bytes() == disk_before, '伪造的同意一个字节都不许写'
    assert trial.journal_bytes(plan) == journal_before, '被拒的授权不许动 journal 一个字节'
    assert trial.server.journal_status(plan) == 'PREPARED'
    assert trial.checkpoints() == []
    # 页面读的是同一个真相：这一条仍挂在待授权位上，也没有冒充"已授权"。
    assert trial.page.query_selector(f'[data-plan-id="{plan["plan_id"]}"]') is not None
    assert '已授权' not in trial.page.inner_text('#agent-plans')


def test_apply_without_page_consent_is_refused_and_writes_nothing(trial):
    """④ 没授权就 apply（带正确的 client 身份）→ 非 200 且零写入。"""
    plan = trial.mint()
    disk_before = trial.script.read_bytes()
    journal_before = trial.journal_bytes(plan)

    status, payload = trial.server.apply(plan['plan_id'])
    assert status != 200, f'未授权的 apply 竟然回 200：{payload}'
    assert (status, payload['status']) == (409, 'PLAN_NOT_PENDING'), payload
    assert trial.script.read_bytes() == disk_before, '未授权的 apply 不许写盘'
    assert trial.journal_bytes(plan) == journal_before, '未授权的 apply 不许动 journal'
    assert trial.server.journal_status(plan) == 'PREPARED'
    assert trial.checkpoints() == []
    assert trial.server.plan(plan['plan_id'])['state'] == 'PENDING'


def test_page_authorize_then_apply_writes_the_planned_bytes_and_appends_history(trial):
    """⑤ 页面点授权 → AUTHORIZED；客户端 apply → 200 + COMMITTED_AND_VERIFIED；
    磁盘 sha256 == 计划的 after；history 出现一条 source_change 且哈希与磁盘/计划一致。"""
    plan = trial.mint()
    plan_strip(trial.page, plan['plan_id'])
    assert trial.server.plan(plan['plan_id'])['state'] == 'PENDING', '页面还没点，不该已经授权'

    click_plan_action(trial.page, plan['plan_id'])
    authorized = await_authorized(trial.server, plan['plan_id'], trial.page)
    grant = authorized['grant']
    assert grant is not None and grant['single_use'] is True and grant['used'] is False, grant
    assert trial.sha256() == sha256_bytes(trial.original), '授权本身不许写盘'
    before_bytes = trial.script.read_bytes()

    status, applied = trial.server.apply(plan['plan_id'])
    assert (status, applied['commit_state']) == (200, COMMITTED_AND_VERIFIED), applied
    assert applied['state'] == 'APPLIED' and applied['checkpoint_id'], applied

    written = trial.script.read_bytes()
    assert written != before_bytes, 'apply 之后磁盘字节必须真的变了'
    assert sha256_bytes(written) == plan['files'][0]['after_sha256'], '磁盘字节不是计划的那一份'
    assert sha256_bytes(trial.original) == plan['files'][0]['before_sha256']
    assert trial.server.journal_status(plan) == 'COMMITTED'

    checkpoints = trial.checkpoints()
    assert len(checkpoints) == 1, f'检查点数不对：{checkpoints}'
    checkpoint = checkpoints[0]
    assert checkpoint['kind'] == 'source_change'
    assert checkpoint['id'] == applied['checkpoint_id']
    payload = checkpoint['payload']
    assert payload['plan_id'] == plan['plan_id'] and payload['gid'] == TARGET_GID
    assert payload['journal_id'] == plan['journal_id']
    assert payload['commit_state'] == COMMITTED_AND_VERIFIED
    # history 里的位移必须带单位：pt 不是 mm。
    assert payload['units'] == 'pt' and payload['requested_pt'] == [0.0, 2.0]
    assert 'requested_mm' not in payload
    change = payload['file_changes'][0]
    assert change['path'] == str(trial.script)
    assert change['before_sha256'] == plan['files'][0]['before_sha256']
    assert change['after_sha256'] == plan['files'][0]['after_sha256']
    assert change['after_sha256'] == sha256_bytes(trial.script.read_bytes())


def test_rebuild_moves_only_the_target_and_the_patch_touches_one_place(trial):
    """⑥ 另起进程重建：只有目标标签按声明走了 2pt，其余几何与科学指纹逐位不变；
    逐行对齐另证补丁只动目标那一处（一处插入 + 一处单行替换）。"""
    baseline = measure(trial.script, trial.config)      # 写盘前先量：这就是底座
    original_text = trial.original.decode('utf-8')

    plan = trial.mint()
    plan_strip(trial.page, plan['plan_id'])
    click_plan_action(trial.page, plan['plan_id'])
    await_authorized(trial.server, plan['plan_id'], trial.page)
    status, applied = trial.server.apply(plan['plan_id'])
    assert (status, applied['commit_state']) == (200, COMMITTED_AND_VERIFIED), applied
    applied_text = trial.script.read_bytes().decode('utf-8')

    edits = list(_line_edits(original_text, applied_text))
    assert sorted(tag for tag, _old, _new in edits) == ['insert', 'replace'], \
        f'补丁不该有第二处改动：{edits}'
    insertions = [line for tag, _old, new in edits if tag == 'insert' for line in new]
    replaced = [(old, new) for tag, old, new in edits if tag == 'replace']
    assert len(replaced) == 1, f'替换块只该有一处：{replaced}'
    (old_lines, new_lines), = replaced
    assert len(old_lines) == 1 and len(new_lines) == 1, '替换必须是「一行换一行」'
    assert BASE_LITERAL in old_lines[0] and f'"{TARGET_LABEL}"' in old_lines[0], old_lines
    assert 'xytext=' in new_lines[0] and TARGET_GID in new_lines[0], new_lines
    assert BASE_LITERAL not in new_lines[0], '目标那一行必须经过取值助手，而不是原样留着'
    inserted_text = ''.join(insertions)
    symbol = _inserted_symbol(plan['files'][0]['diff'])
    assert f'{symbol} = {{"{TARGET_GID}": [0.0, 2.0]}}' in inserted_text, inserted_text
    helper = re.search(r'\ndef (\w+)\(gid, base\):\n', inserted_text)
    assert helper and '.get(gid, (0.0, 0.0))' in inserted_text, inserted_text
    assert f'xytext={helper.group(1)}(' in new_lines[0], '改写用的必须就是这次插入的助手'

    rebuilt = measure(trial.script, trial.config)
    assert rebuilt['gids'] == baseline['gids'] == sorted((TARGET_GID, *OTHER_GIDS))
    assert rebuilt['science_sha256'] == baseline['science_sha256'], '科学载荷的指纹变了'
    assert sorted(rebuilt['geometry']) == sorted(baseline['geometry']), '可见几何的键集合变了'
    for key in sorted(baseline['geometry']):
        if key == TARGET_KEY:
            continue
        assert rebuilt['geometry'][key] == baseline['geometry'][key], f'{key} 跟着目标动了'
    moved = [rebuilt['geometry'][TARGET_KEY][axis] - baseline['geometry'][TARGET_KEY][axis]
             for axis in (0, 1)]
    assert moved[0] == pytest.approx(SHIFT_MM[0], abs=1e-6), f'x 不该动，实测 {moved[0]} mm'
    assert moved[1] == pytest.approx(SHIFT_MM[1], abs=TOL_MM), \
        f'标签实测位移 {moved[1]} mm，请求 {SHIFT_MM[1]} mm'


def test_apply_after_an_external_rewrite_is_stale_and_writes_nothing(trial):
    """⑦ 授权之后、写盘之前文件被外部改写 → 409 STALE_SOURCE：拒绝覆盖，零写入。"""
    plan = trial.mint()
    plan_strip(trial.page, plan['plan_id'])
    click_plan_action(trial.page, plan['plan_id'])
    await_authorized(trial.server, plan['plan_id'], trial.page)

    external = trial.original + '# 外部改写：这一版计划作废\n'.encode('utf-8')
    trial.script.write_bytes(external)
    journal_before = trial.journal_bytes(plan)

    status, payload = trial.server.apply(plan['plan_id'])
    assert (status, payload['status']) == (409, 'STALE_SOURCE'), \
        f'外部改写之后居然还写盘了：HTTP {status} {payload}'
    assert trial.script.read_bytes() == external, '拒绝覆盖外部改写'
    assert trial.journal_bytes(plan) == journal_before, '被拒的 apply 不许动 journal'
    assert trial.server.journal_status(plan) == 'PREPARED'
    assert trial.checkpoints() == []

    refused = trial.server.plan(plan['plan_id'])
    assert refused['state'] == 'AUTHORIZED', '被拒的 apply 不该把计划标成 APPLIED'
    assert refused['grant']['used'] is False, '被拒的 apply 不该烧掉 grant'


def test_backend_session_selection_and_history_survive_a_browser_restart(trial, browser):
    """⑧ 关掉浏览器上下文后：后端会话、选区、已保存 History 都还在；重开页面仍是同一张图、
    同一个 gid 仍能把同一份历史读回来。"""
    plan = trial.mint()
    plan_strip(trial.page, plan['plan_id'])
    click_plan_action(trial.page, plan['plan_id'])
    await_authorized(trial.server, plan['plan_id'], trial.page)
    status, applied = trial.server.apply(plan['plan_id'])
    assert (status, applied['commit_state']) == (200, COMMITTED_AND_VERIFIED), applied

    scene = scene_of(trial.page)
    node = node_by_gid(scene, TARGET_GID)
    publish_label(trial.page, trial.server, scene, node)
    selection_before = trial.server.selection()
    frame_before = trial.server.frame()['frame_revision']
    history_before = trial.checkpoints()
    bytes_before = trial.script.read_bytes()
    assert len(history_before) == 1, f'写盘之后 History 该有一条：{history_before}'

    trial.close()                                       # 真关：后端与磁盘得自己站着

    selection_after = trial.server.selection()
    assert selection_after['selection'] == selection_before['selection'], '选区语义被浏览器带走了'
    assert selection_after['hub_revision'] == selection_before['hub_revision']
    assert selection_after['session_id'] == selection_before['session_id']
    assert selection_after['stale'] is False, selection_after['stale_reason']
    assert trial.server.frame()['frame_revision'] == frame_before, '后端会话不该随浏览器走'
    assert trial.script.read_bytes() == bytes_before
    assert trial.checkpoints() == history_before, '已保存的 History 不该被浏览器带走'
    assert trial.server.plan(plan['plan_id'])['state'] == 'APPLIED'
    assert trial.server.journal_status(plan) == 'COMMITTED'

    # 重开页面：同一张图（同一份历史的工作区身份）、同一个 gid 依然能被点中并发布到 Hub。
    reopened = trial.open(browser)
    reopened_scene = scene_of(reopened)
    assert reopened_scene['source_revision'] == scene['source_revision'], \
        '重开的页面不是同一张图：History 的工作区身份跟着变了'
    reopened_node = node_by_gid(reopened_scene, TARGET_GID)
    publish_label(reopened, trial.server, reopened_scene, reopened_node)
    selected = (trial.server.selection()['selection'] or {}).get('selected') or {}
    assert selected.get('gid') == reopened_node['gid']
    assert trial.checkpoints() == history_before, '重开页面后 History 必须还是同一份'
    assert trial.script.read_bytes() == bytes_before, '重开页面不许再写盘'
