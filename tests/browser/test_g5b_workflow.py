"""G5b 层 1 门禁：真实 Chromium 页面 × 真实 Inspector 子进程 × 确定性 HTTP 客户端。

覆盖（编号即工单条目）：
  ① 页面加载后点击图中标签 → Hub ``/api/selection`` 出现正确 gid；
  ② 客户端 ``POST /api/plans`` 铸造 layout_edit 计划 → 页面出现该待授权计划（含 diff 摘要）；
  ③ 点页面「授权」→ 计划变 AUTHORIZED；
  ④ 客户端带 ``X-Figpact-Client`` apply → 源码字节改变、``COMMITTED_AND_VERIFIED``、
     history 出现 ``source_change`` 检查点（顺带证一次：换成别的客户端会被拒且零写入）；
  ⑤ 伪造授权：绕过页面直接 POST authorize，不带或带错 ``X-Figpact-Ui`` → 403，
     计划仍 PENDING、磁盘一个字节没动；
  ⑥ 未授权直接 apply → 拒绝且零写入；
  ⑦ 计划铸造后、授权前外部改写该文件 → apply 拒绝（STALE_SOURCE）且零写入；
  ⑧ 关掉浏览器上下文后后端会话与已保存 History 完好：重开页面仍是同一张图、同一份历史，
     同一个标签仍能把同一个 gid 发布回 Hub。

写盘目标说明：nmr 例子还没按 G4 约定在源码里声明 ``LAYOUT_MM``，而 ``examples/nmr``
的科学内容不许测试改写，所以计划落在**服务端源码的副本 + 一条显式布局绑定**上
（见 ``conftest.plan_project``）；gid 就是页面点中的那个标签的身份。

怎么跑（服务器与浏览器都是本文件自带夹具，不需要另外起服务）::

    python -m pytest tests/browser/test_g5b_workflow.py -q

失败时 pytest 打印 Inspector 子进程 stderr 尾部；断言消息里带页面现场
（就绪位、``#agent-plans``、HTML 尾部、控制台错误），塌在哪一层一眼可见。
"""
from __future__ import annotations

import pytest

from .conftest import (CLIENT_ID, NO_HEADER, PLAN_VALUE_TEXT, UI_HEADER, click_label,
                       node_by_gid, open_page, scene_of, sha256_bytes, wait_for)

#: 线上契约的字面量：测试守的是协议本身，不是实现里的常量。
COMMITTED_AND_VERIFIED = 'COMMITTED_AND_VERIFIED'
DIFF_OLD = '[0.0, 0.0]'
OTHER_CLIENT = 'someone-else'
#: 重开/新开页面后把选区推回 Hub 的最大点击次数（见 publish_label 的说明）。
PUBLISH_ATTEMPTS = 5
PUBLISH_ATTEMPT_TIMEOUT_S = 3.0


def new_binding_line(gid: str) -> bytes:
    """写盘后那行布局绑定该长什么样（与 conftest.plan_project 造基线时同形）。"""
    return ('LAYOUT_MM = {%r: [0.0, 4.0]}\n' % gid).encode('utf-8')


def _evidence(page) -> str:
    """页面这一层的现场：DOM 状态 + HTML 尾部 + 控制台错误。"""
    console = '\n'.join(page.console_errors[-10:]) or '（无）'
    return f'\n--- 页面现场 ---\n{page.debug()}\n--- 页面控制台 ---\n{console}'


def _selection_seq(server) -> int:
    selection = server.selection()['selection'] or {}
    seq = selection.get('selection_seq')
    return seq if isinstance(seq, int) else 0


def _fresh_publish(server, gid, since_seq):
    """Hub 里出现一个**比 since_seq 更新**的发布，且它选中的就是这个 gid。"""
    payload = server.selection()
    selection = payload['selection'] or {}
    selected = selection.get('selected') or {}
    seq = selection.get('selection_seq')
    if selected.get('gid') == gid and isinstance(seq, int) and seq > since_seq:
        return payload
    return None


def publish_label(page, server, scene, node, *, attempts=PUBLISH_ATTEMPTS):
    """点中图中的标签，直到 Hub 真的收到这个 gid 的**新**发布；返回那次发布的完整回包。

    页面每次加载都把自己的 ``selection_seq`` 从 1 重新数，而 Hub 要求它严格递增：刚装好的
    页面头一两次发布会因为撞上 Hub 里已有的更大序号被判 stale。这不是把断言放宽——每一次
    尝试都必须真实点击并命中这个标签，最终要求序号真的前进、gid 真的对得上。
    """
    for attempt in range(1, attempts + 1):
        since = _selection_seq(server)
        assert click_label(page, scene, node) == node['id'], \
            '指针没有落在目标标签上' + _evidence(page)
        published, found = wait_for(lambda: _fresh_publish(server, node['gid'], since),
                                    f'Hub 收到 {node["gid"]} 的新发布',
                                    timeout=PUBLISH_ATTEMPT_TIMEOUT_S)
        if found:
            return published
    pytest.fail(f'点了 {attempts} 次也没把 {node["gid"]!r} 发布到 Hub：'
                f'{server.selection()["selection"]}' + _evidence(page))


def plan_strip(page, plan_id: str, *, timeout=20.0):
    """等页面自己长出这条计划（页面每 3 秒轮询一次 ``/api/plans``）。"""
    assert page.query_selector('#agent-plans') is not None, \
        '页面里没有 #agent-plans 计划容器（授权 UI 未落地）' + _evidence(page)
    try:
        page.wait_for_selector(f'[data-plan-id="{plan_id}"]', timeout=timeout * 1000)
    except Exception as error:
        pytest.fail(f'计划 {plan_id} 始终没有出现在页面上（{type(error).__name__}）'
                    + _evidence(page))
    return page.query_selector(f'[data-plan-id="{plan_id}"]')


def await_authorized(server, plan_id: str, page=None, *, timeout=15.0):
    """等服务端承认这次页面授权。"""
    def probe():
        plan = server.plan(plan_id)
        return plan if plan['state'] == 'AUTHORIZED' else None

    plan, found = wait_for(probe, f'计划 {plan_id} 变 AUTHORIZED', timeout=timeout)
    assert found, (f'计划 {plan_id} 没有变成 AUTHORIZED：{server.plan(plan_id)}'
                   + (_evidence(page) if page is not None else ''))
    return plan


def await_page_settled(page, plan_id: str, *, timeout=15.0):
    """页面必须不再把这条计划挂在「待授权」位上：撤条或如实写 AUTHORIZED 都算，报失败不算。"""
    def probe():
        strip = page.query_selector(f'[data-plan-id="{plan_id}"]')
        notice = page.inner_text('#agent-plans')
        if '失败' in notice:
            return {'failed': notice}
        if strip is None:
            return {'gone': True, 'notice': notice}
        if 'AUTHORIZED' in strip.inner_text().upper():
            return {'status': True, 'notice': notice}
        return None

    observed, found = wait_for(probe, f'页面不再把 {plan_id} 当待授权', timeout=timeout)
    assert found, '页面始终挂着一条已经授权过的待授权条' + _evidence(page)
    assert 'failed' not in observed, f'页面报了授权失败：{observed["failed"]!r}' + _evidence(page)
    return observed


def test_page_click_publishes_the_label_gid_to_the_hub(page, server, served_label):
    """① 点击图中标签 → Hub /api/selection 出现正确 gid（会话身份也要对得上）。"""
    scene = scene_of(page)
    node = node_by_gid(scene, served_label['gid'])

    published = publish_label(page, server, scene, node)
    selected = published['selection']['selected']
    assert selected['gid'] == node['gid']
    assert selected['bounds_mm'] == node['bounds_mm'], '发布的选区几何与页面场景不一致'
    assert selected['identity_stability'] == node['identity_stability']
    assert published['stale'] is False, f'刚发布的选区不该是 stale：{published["stale_reason"]}'

    # 页面发布的会话身份必须与页面上那张图逐字一致，否则"同一个 gid"只是同名。
    frame = page.evaluate('window.FIGPACT_INSPECTOR_FRAME')
    assert published['session_id'] == frame['session']['session_id']
    assert published['scene_revision'] == frame['frame_revision']
    assert published['source_revision'] == scene['source_revision']


def test_minted_plan_appears_in_the_page_with_its_diff(page, server, plan_project, served_label):
    """② 客户端铸造的计划出现在页面上，并带着可读的 diff 摘要。"""
    plan = server.mint(plan_project.script, served_label['gid'])
    assert plan['state'] == 'PENDING'
    assert plan['client_id'] == CLIENT_ID
    assert plan['files'][0]['path'] == str(plan_project.script)

    strip = plan_strip(page, plan['plan_id'])
    summary = strip.inner_text()
    assert served_label['gid'] in summary, f'计划条没写 gid：{summary!r}'
    assert plan_project.script.name in summary, f'计划条没写目标文件：{summary!r}'

    assert strip.query_selector('[data-plan-action="authorize"]') is not None, '缺授权按钮'
    assert strip.query_selector('[data-plan-action="cancel"]') is not None, '缺取消按钮'
    assert strip.query_selector('[data-plan-status]') is not None, '缺状态位'

    diff = strip.query_selector('[data-plan-diff]').inner_text()
    assert DIFF_OLD in diff and PLAN_VALUE_TEXT in diff, f'diff 摘要没给出改动的两边：{diff!r}'
    assert served_label['gid'] in diff, f'diff 摘要没写 gid：{diff!r}'
    assert str(plan_project.script) in diff, f'diff 摘要没写目标文件：{diff!r}'
    assert '@@' in diff, f'diff 摘要不是 unified diff：{diff!r}'

    # 页面显示的和服务器事实同源：仍是待授权、还没有 grant，磁盘没动。
    server_plan = server.plan(plan['plan_id'])
    assert server_plan['state'] == 'PENDING'
    assert server_plan['grant'] is None
    assert plan_project.sha256() == sha256_bytes(plan_project.baseline), '铸造计划不该改源码'


def test_page_authorize_promotes_the_plan(page, server, plan_project, served_label):
    """③ 页面点「授权」→ 服务端承认 AUTHORIZED，且页面不再挂着"可授权"的条。"""
    plan_project.reset()
    before = plan_project.sha256()
    plan = server.mint(plan_project.script, served_label['gid'])
    strip = plan_strip(page, plan['plan_id'])
    assert server.plan(plan['plan_id'])['state'] == 'PENDING', '页面还没点，不该已经授权'

    strip.query_selector('[data-plan-action="authorize"]').click()
    authorized = await_authorized(server, plan['plan_id'], page)

    grant = authorized['grant']
    assert grant is not None and grant['single_use'] is True and grant['used'] is False, \
        f'授权结出的 grant 形状不对：{grant}'
    await_page_settled(page, plan['plan_id'])

    assert plan_project.sha256() == before, '授权本身不许写盘'
    assert server.journal_status(plan) == 'PREPARED'
    assert server.checkpoints(plan_project.script) == []


def test_authorized_apply_changes_source_and_appends_a_checkpoint(page, server, plan_project,
                                                                 served_label, nmr_source_bytes):
    """④ 页面授权 + 申请它的客户端 apply → 字节改变、COMMITTED_AND_VERIFIED、history 有检查点。"""
    plan_project.reset()
    before = plan_project.sha256()
    assert server.checkpoints(plan_project.script) == []

    plan = server.mint(plan_project.script, served_label['gid'])
    plan_strip(page, plan['plan_id'])
    page.click(f'[data-plan-id="{plan["plan_id"]}"] [data-plan-action="authorize"]')
    await_authorized(server, plan['plan_id'], page)

    # 授权只绑给申请它的客户端：换一个客户端来 apply，必须被挡，而且一个字节都不写。
    other_status, other_payload = server.apply(plan['plan_id'], client_id=OTHER_CLIENT)
    assert (other_status, other_payload['status']) == (403, 'FORBIDDEN'), \
        f'别的客户端竟然能应用这个计划：{other_status} {other_payload}'
    assert plan_project.sha256() == before, '被拒的 apply 不许写盘'

    status, applied = server.apply(plan['plan_id'])
    assert (status, applied['commit_state']) == (200, COMMITTED_AND_VERIFIED), applied
    assert applied['state'] == 'APPLIED'
    assert applied['checkpoint_id'], f'没有记下 source_change 检查点：{applied}'

    # 磁盘字节：除那条布局绑定外，与线上源码逐字节相同；哈希就是计划里那一个。
    assert plan_project.bytes().startswith(nmr_source_bytes)
    assert plan_project.bytes().endswith(new_binding_line(served_label['gid'])), \
        f'源码尾巴不是这次的改动：{plan_project.bytes()[-120:]!r}'
    assert plan_project.sha256() == plan['files'][0]['after_sha256']
    assert before == plan['files'][0]['before_sha256']
    assert server.journal_status(plan) == 'COMMITTED'

    checkpoints = server.checkpoints(plan_project.script)
    assert len(checkpoints) == 1, f'检查点数不对：{checkpoints}'
    checkpoint = checkpoints[0]
    assert checkpoint['kind'] == 'source_change'
    assert checkpoint['id'] == applied['checkpoint_id']
    payload = checkpoint['payload']
    assert payload['plan_id'] == plan['plan_id']
    assert payload['gid'] == served_label['gid']
    assert payload['journal_id'] == plan['journal_id']
    assert payload['commit_state'] == COMMITTED_AND_VERIFIED
    assert payload['requested_mm'] == [0.0, 4.0]
    change = payload['file_changes'][0]
    assert change['path'] == str(plan_project.script)
    assert change['before_sha256'] == before
    assert change['after_sha256'] == plan_project.sha256()


def test_forged_page_consent_is_refused_and_changes_nothing(page, server, plan_project,
                                                            served_label):
    """⑤ 伪造授权：不带 / 带错页面令牌一律 403，计划仍 PENDING，磁盘未动。"""
    plan_project.reset()
    before = plan_project.sha256()
    plan = server.mint(plan_project.script, served_label['gid'])
    plan_strip(page, plan['plan_id'])

    missing_status, missing = server.authorize(plan['plan_id'], token=NO_HEADER)
    assert (missing_status, missing['status']) == (403, 'FORBIDDEN'), \
        f'不带 {UI_HEADER} 竟然被接受：{missing_status} {missing}'
    wrong_status, wrong = server.authorize(plan['plan_id'], token='not-the-page-token')
    assert (wrong_status, wrong['status']) == (403, 'FORBIDDEN'), \
        f'带错 {UI_HEADER} 竟然被接受：{wrong_status} {wrong}'

    forged = server.plan(plan['plan_id'])
    assert forged['state'] == 'PENDING', '伪造的同意不许把计划推成 AUTHORIZED'
    assert forged['grant'] is None, '伪造的同意不许结出 grant'
    assert plan_project.sha256() == before, '伪造的同意一个字节都不许写'
    assert server.journal_status(plan) == 'PREPARED'
    assert server.checkpoints(plan_project.script) == []
    # 页面读的是同一个真相：这一条还在待授权位上，也没有冒充"已授权"。
    assert page.query_selector(f'[data-plan-id="{plan["plan_id"]}"]') is not None
    assert '已授权' not in page.inner_text('#agent-plans')


def test_apply_without_page_consent_is_refused_and_writes_nothing(server, plan_project,
                                                                 served_label):
    """⑥ 没有页面同意就 apply → 拒绝，零写入（journal 仍 PREPARED，没有检查点）。"""
    plan_project.reset()
    before = plan_project.sha256()
    plan = server.mint(plan_project.script, served_label['gid'])

    status, payload = server.apply(plan['plan_id'])
    assert (status, payload['status']) == (409, 'PLAN_NOT_PENDING'), \
        f'未授权 apply 竟然回 {status}：{payload}'
    assert plan_project.sha256() == before and plan_project.bytes() == plan_project.baseline
    assert server.journal_status(plan) == 'PREPARED'
    assert server.checkpoints(plan_project.script) == []
    assert server.plan(plan['plan_id'])['state'] == 'PENDING'


def test_apply_after_an_external_rewrite_is_stale_and_writes_nothing(page, server, plan_project,
                                                                     served_label):
    """⑦ 授权之后、写盘之前文件被外部改写 → STALE_SOURCE，拒绝覆盖。"""
    plan_project.reset()
    baseline = plan_project.bytes()
    plan = server.mint(plan_project.script, served_label['gid'])
    plan_strip(page, plan['plan_id'])
    page.click(f'[data-plan-id="{plan["plan_id"]}"] [data-plan-action="authorize"]')
    await_authorized(server, plan['plan_id'], page)

    external = baseline + '# 外部改写：这一版计划作废\n'.encode('utf-8')
    plan_project.script.write_bytes(external)

    status, payload = server.apply(plan['plan_id'])
    assert (status, payload['status']) == (409, 'STALE_SOURCE'), \
        f'外部改写之后居然还写盘了：{status} {payload}'
    assert plan_project.bytes() == external, '拒绝覆盖外部改写'
    assert server.journal_status(plan) == 'PREPARED'
    assert server.checkpoints(plan_project.script) == []

    refused = server.plan(plan['plan_id'])
    assert refused['state'] == 'AUTHORIZED', '被拒的 apply 不该把计划标成 APPLIED'
    assert refused['grant']['used'] is False, '被拒的 apply 不该烧掉 grant'


def test_backend_session_and_history_survive_a_browser_restart(browser, server, plan_project,
                                                               served_label):
    """⑧ 浏览器上下文关掉后：后端会话、选区语义、磁盘历史都还在；重开页面仍是同一张图。"""
    plan_project.reset()
    plan = server.mint(plan_project.script, served_label['gid'])
    context, page = open_page(browser, server.base_url)
    try:
        plan_strip(page, plan['plan_id'])
        page.click(f'[data-plan-id="{plan["plan_id"]}"] [data-plan-action="authorize"]')
        await_authorized(server, plan['plan_id'], page)
        status, applied = server.apply(plan['plan_id'])
        assert (status, applied['commit_state']) == (200, COMMITTED_AND_VERIFIED), applied

        scene = scene_of(page)
        node = node_by_gid(scene, served_label['gid'])
        selection_before = publish_label(page, server, scene, node)
        history_before = server.checkpoints(plan_project.script)
        bytes_before = plan_project.bytes()
        assert len(history_before) == 1
    finally:
        context.close()

    # 浏览器没了，后端会话与磁盘事实都还在。
    selection_after = server.selection()
    assert selection_after['selection'] == selection_before['selection'], '选区语义被浏览器带走了'
    assert selection_after['hub_revision'] == selection_before['hub_revision']
    assert selection_after['session_id'] == selection_before['session_id']
    assert selection_after['stale'] is False
    assert plan_project.bytes() == bytes_before
    assert server.checkpoints(plan_project.script) == history_before
    assert server.plan(plan['plan_id'])['state'] == 'APPLIED'
    assert server.journal_status(plan) == 'COMMITTED'

    # 重开页面：同一张图、同一个 gid 依然能被点中并重新发布到 Hub。
    context, page = open_page(browser, server.base_url)
    try:
        reopened = scene_of(page)
        assert reopened['source_revision'] == scene['source_revision']
        node = node_by_gid(reopened, served_label['gid'])
        publish_label(page, server, reopened, node)
        selected = (server.selection()['selection'] or {}).get('selected') or {}
        assert selected.get('gid') == node['gid']
        assert server.checkpoints(plan_project.script) == history_before
    finally:
        context.close()
