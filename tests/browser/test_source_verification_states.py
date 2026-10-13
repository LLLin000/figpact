"""P0a 层 1 门禁：页面上的**两个独立状态**（源码提交 / 图形验证）。

页面是给人看结论的地方，所以这里守的是**措辞规则**与"页面 ≠ 服务端"的漂移：

  * ``source_commit_state``（``NOT_WRITTEN`` / ``COMMITTED`` / ``RECOVERY_REQUIRED``）与
    ``figure_verification_state``（``NOT_RUN`` / ``PASS`` / ``FAIL`` / ``ERROR``）分两处显示；
  * **只有** ``COMMITTED`` + ``PASS`` 才允许出现"修改已保存并通过验证"；
  * 写盘已成事实而验证没过/没跑完 → 只能说"源码已提交，图形验证失败/未完成"；
  * 事后改盘 → 页面必须把旧的 ``PASS`` 撤下来（``data-figure-verification-stale``），
    不许继续拿它当当前文件的验证结果。

台子与 ``test_authoring_writeback_flow.py`` 同形：真子进程 ``figpact.inspector_server`` +
真 Chromium + 服务端正在服务的**脚本副本**（``examples/`` 下的夹具一个字节都不许改）。
页面结论一律与服务端 ``GET /api/plans`` 的原始字段比对——页面只是显示者，不是事实来源。

怎么跑::

    python -m pytest tests/browser/test_source_verification_states.py -q
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from .conftest import (CLIENT_ID, REPO_ROOT, launch_server, open_page, sha256_bytes, wait_for)
from .test_g5b_workflow import await_authorized, plan_strip

#: 线路上的契约字面量：测试守的是协议本身，不引用实现常量。
AUTHORING_KIND = 'authoring_edit'
SAVED_AND_VERIFIED = '修改已保存并通过验证'
COMMITTED_UNVERIFIED = '源码已提交，图形验证失败/未完成'
#: 被服务的夹具：**没有**绑定，gid 只出现在 ``ax.annotate(...)`` 调用现场。
FIXTURE_SCRIPT = REPO_ROOT / 'examples' / 'python_native' / 'legacy_plain.py'
TARGET_GID = 'legacy.main.label.A'
VALUE_PT = [0.0, 2.0]
BASE_XYTEXT = [0.0, 4.0]
#: 页面轮询 ``/api/plans`` 的周期是 3 秒；给它两轮的时间。
PAGE_POLL_TIMEOUT_S = 20.0


def expected_wording(source_state, verification_state):
    """措辞规则（测试自己重写一遍：页面那段文案是**契约**，不是实现细节）。"""
    if source_state == 'COMMITTED' and verification_state == 'PASS':
        return SAVED_AND_VERIFIED
    if source_state == 'COMMITTED':
        return COMMITTED_UNVERIFIED
    return None


class _Case:
    """一个用例的现场：真服务 + 服务端正在服务的那份脚本副本 + 真页面。"""

    def __init__(self, script, config, server):
        self.script = script
        self.config = config
        self.server = server
        self.original = script.read_bytes()
        self._contexts = []

    def open(self, browser):
        context, page = open_page(browser, self.server.base_url)
        self._contexts.append(context)
        self.page = page
        return page

    def close(self):
        for context in self._contexts:
            context.close()
        self._contexts.clear()

    def mint(self):
        status, payload = self.server.json('POST', '/api/plans', {
            'client_id': CLIENT_ID, 'kind': AUTHORING_KIND, 'script': str(self.script),
            'gid': TARGET_GID, 'value_pt': list(VALUE_PT),
            'base_offset_pt': list(BASE_XYTEXT),
            'reason': 'P0a 层 1 门禁：页面授权后才写盘，写盘之后独立重建验证'})
        assert (status, payload['status']) == (200, 'OK'), f'铸造计划被拒：{status} {payload}'
        return payload['plan']

    # ---- 页面现场

    def commit_strip(self, plan_id, *, timeout=PAGE_POLL_TIMEOUT_S):
        """等页面把这条已写盘计划挂到"事后状态"区（页面自己轮询 /api/plans）。"""
        selector = f'[data-commit-id="{plan_id}"]'
        found, ok = wait_for(lambda: self.page.query_selector(selector),
                             f'页面上出现 {plan_id} 的提交/验证状态', timeout=timeout)
        assert ok, (f'页面始终没有显示 {plan_id} 的提交状态'
                    + _evidence(self.page, self.server))
        return found

    @staticmethod
    def strip_view(strip):
        return {'source': strip.get_attribute('data-source-commit-state'),
                'verification': strip.get_attribute('data-figure-verification-state'),
                'stale': strip.get_attribute('data-figure-verification-stale'),
                'status': strip.query_selector('[data-commit-status]').inner_text(),
                'detail': strip.query_selector('[data-commit-detail]').inner_text()}


def _evidence(page, server):
    try:
        notes = page.inner_text('#agent-commits')
    except Exception as error:  # pragma: no cover - 只用在失败消息里
        notes = f'（读不到 #agent-commits：{error}）'
    try:
        tail = server.stderr_tail(20)
    except Exception as error:  # pragma: no cover
        tail = f'（读不到 stderr：{error}）'
    return f'\n#agent-commits:\n{notes}\n--- 服务端 stderr ---\n{tail}'


def _arm_project(root: Path):
    """服务端要加载的脚本副本：与夹具逐字节相同，并保留目录深度（夹具自己按 parents[2] 找根）。

    ``state_home``（``<root>/state``）落在脚本与配置目录之外：那是 HistoryStore 的硬要求。
    """
    project = root / 'project'
    script = project / 'examples' / 'python_native' / FIXTURE_SCRIPT.name
    script.parent.mkdir(parents=True)
    script.write_bytes(FIXTURE_SCRIPT.read_bytes())
    config = project / 'plot.yaml'
    config.write_text('{}\n', encoding='utf-8')
    return script, config


@pytest.fixture
def case(browser, request):
    """真服务子进程（服务脚本副本）+ 真页面；收尾把子进程与临时目录一起清掉。"""
    assert FIXTURE_SCRIPT.is_file(), f'缺少夹具脚本：{FIXTURE_SCRIPT}'
    work_root = Path(tempfile.gettempdir()) / 'figpact-p0a-browser'
    work_root.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='case-', dir=str(work_root)))
    script, config = _arm_project(root)
    server = launch_server(root, command=[sys.executable, '-m', 'figpact.inspector_server',
                                          '--script', str(script), '--config', str(config),
                                          '--scope', 'main', '--dpi', '240', '--port', '0'],
                           config=config)
    handle = _Case(script, config, server)
    try:
        handle.open(browser)
        yield handle
    finally:
        report = getattr(request.node, 'rep_call', None)
        if report is not None and report.failed:
            print('--- 页面 HTML 尾（用例失败现场）---\n' + handle.page.debug(), flush=True)
        handle.close()
        server.stop()
        shutil.rmtree(root, ignore_errors=True)


def _authorize_and_apply(case):
    """铸造 → 页面点「授权」→ 申请它的客户端 apply；返回 (计划, 回执)。"""
    plan = case.mint()
    strip = plan_strip(case.page, plan['plan_id'])
    assert case.server.plan(plan['plan_id'])['state'] == 'PENDING', '页面还没点，不该已经授权'
    strip.query_selector('[data-plan-action="authorize"]').click()
    await_authorized(case.server, plan['plan_id'], case.page)
    status, applied = case.server.apply(plan['plan_id'])
    assert status == 200, f'apply 被拒：{status} {applied}'
    assert applied['source_commit_state'] == 'COMMITTED', applied
    return plan, applied


def test_page_says_saved_and_verified_only_for_committed_and_pass(case):
    """① 页面显示两个独立状态；"已保存并通过验证"只在 COMMITTED + PASS 时出现。"""
    plan, applied = _authorize_and_apply(case)
    view = case.strip_view(case.commit_strip(plan['plan_id']))

    # 页面显示的必须与服务端 /api/plans 的原始字段逐字一致（页面只是显示者）。
    public = case.server.plan(plan['plan_id'])
    assert view['source'] == public['source_commit_state'] == applied['source_commit_state']
    assert view['verification'] == public['figure_verification_state']
    assert view['verification'] == applied['figure_verification_state']
    assert view['stale'] != 'true', '刚写盘的计划不该被标成失效'
    # 兼容字段仍在，且只表达写入语义（写盘是事实）。
    assert applied['commit_state'] == 'COMMITTED_AND_VERIFIED'
    assert sha256_bytes(case.script.read_bytes()) == plan['files'][0]['after_sha256']

    wording = expected_wording(view['source'], view['verification'])
    assert wording is not None, view
    assert view['status'] == wording, view
    # 核心不变量：验证不是 PASS 时，页面上**不许**出现"已保存并通过验证"。
    holder = case.page.inner_text('#agent-commits')
    if view['verification'] == 'PASS':
        assert SAVED_AND_VERIFIED in holder, holder
    else:
        assert SAVED_AND_VERIFIED not in holder, holder
        assert COMMITTED_UNVERIFIED in holder, holder
    # 两个状态各说各的：来源与验证都在行里，不许只留一句含糊的话。
    assert '写入：' in view['detail'] and '验证：' in view['detail'], view


def test_page_drops_an_old_pass_after_the_source_changes(case):
    """② 事后改盘 → 页面撤下旧的 PASS：验证状态不再是 PASS，且带上失效标记。"""
    plan, applied = _authorize_and_apply(case)
    first = case.strip_view(case.commit_strip(plan['plan_id']))

    # 绕过 Hub 改盘：验证证据绑定的字节已经不是磁盘上的字节。
    case.script.write_bytes(case.script.read_bytes() + '# 事后外部改动\n'.encode('utf-8'))

    def stale() -> bool:
        strip = case.page.query_selector(f'[data-commit-id="{plan["plan_id"]}"]')
        if strip is None or strip.get_attribute('data-figure-verification-stale') != 'true':
            return False
        return case.strip_view(strip)

    view, ok = wait_for(stale, '页面把旧的验证结论标成失效', timeout=PAGE_POLL_TIMEOUT_S)
    assert ok, f'页面没有撤下旧结论：{first}' + _evidence(case.page, case.server)

    public = case.server.plan(plan['plan_id'])
    assert public['figure_verification_stale'] is True
    assert public['figure_verification_stale_reason'] == 'SOURCE_CHANGED'
    assert public['figure_verification_state'] != 'PASS'
    assert view['verification'] == public['figure_verification_state'] != 'PASS'
    assert view['source'] == 'COMMITTED', '当时确实写盘了，这条事实不因事后改动而消失'
    assert view['status'] == expected_wording(view['source'], view['verification']), view
    holder = case.page.inner_text('#agent-commits')
    assert SAVED_AND_VERIFIED not in holder, holder
    assert '失效' in view['detail'], view
    assert applied['figure_verification']['script_sha256'] != sha256_bytes(case.script.read_bytes())
