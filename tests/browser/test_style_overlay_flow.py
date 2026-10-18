"""G18 层 1 门禁：Verified Style Overlay 真浏览器连续验收（真实 Chromium + 真服务）。

固定受信入口：``tools/g15/B/g15b_barchart_decl.py`` + ``raw/barchart.py``（原件只读，
工作 Overlay 落在用例临时目录）；服务以无 config 风格启动::

    python -m figpact.inspector_server --script <trusted> --scope main \
        --overlay <tmp>/style.json --port 0 --dpi 120

覆盖（连续工作流 + 否定 fail-closed，真实点击/预览/确认，不走 API 捷径）：
① 画布点 ylabel（exact scene_ids）→ 8 → 预览（正式不变）→ 确认 COMMITTED+PASS；
② 不刷新工作区选 x 刻度 → 8 → 保存，ylabel 仍 8；
③ ylabel → 9 → 保存 → 显式恢复原始并确认，ylabel 回 10、刻度仍 8；
④ 停服、新进程同入口同 Overlay 重开，清单与保存状态一致；
⑤ QA(4pt)/外部 Overlay 更新/源漂移/缺 token/任意字段/坏 Origin 全部明确拒绝且字节保留。
阶段耗时（perf_counter：page ready/选择/预览/确认）记 ``results.json``；基线/终态截图。

怎么跑（父代理统一调度，本文件自己不跑）::

    python -m pytest tests/browser/test_style_overlay_flow.py -q
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from .conftest import (REPO_ROOT, label_hit_point, launch_server, open_page,
                       scene_of, wait_for)

SCRIPT = REPO_ROOT / 'tools' / 'g15' / 'B' / 'g15b_barchart_decl.py'
RAW = REPO_ROOT / 'tools' / 'g15' / 'B' / 'raw' / 'barchart.py'
assert SCRIPT.is_file() and RAW.is_file(), f'缺 G15b 固定夹具：{SCRIPT} / {RAW}'

WORK_ROOT = Path(os.environ.get('FIGPACT_BROWSER_WORKDIR')
                 or str(Path(tempfile.gettempdir()) / 'figpact-g18-style'))

YLABEL = 'ylabel'
XTICK = 'x tick labels'
VALIDATED, SAVED, FAILED = 'validated', 'saved', 'failed'


def _sha(b: bytes | None) -> str:
    return hashlib.sha256(b).hexdigest() if b is not None else ''


def _overlay_bytes(p: Path) -> bytes | None:
    return p.read_bytes() if p.exists() else None


def _saved_map(p: Path) -> dict:
    if not p.exists():
        return {}
    return {t['id']: float(t['value'])
            for t in json.loads(p.read_text(encoding='utf-8')).get('targets', [])}


def _launch(root: Path, script: Path, overlay: Path):
    overlay.parent.mkdir(parents=True, exist_ok=True)
    return launch_server(root, command=[sys.executable, '-m', 'figpact.inspector_server',
                                       '--script', str(script), '--scope', 'main',
                                       '--overlay', str(overlay),
                                       '--port', '0', '--dpi', '120'],
                         config=None)


def _frame(page) -> dict:
    return page.evaluate(
        '() => (window.FigpactInspector && window.FigpactInspector.currentFrame)'
        ' ? window.FigpactInspector.currentFrame() : window.FIGPACT_INSPECTOR_FRAME')


def _targets(frame: dict) -> list[dict]:
    return list((frame.get('style') or {}).get('targets') or [])


def _by_label(targets: list[dict], label: str) -> dict:
    for t in targets:
        if (t.get('label') or '') == label:
            return t
    raise AssertionError(f'帧里没有 label={label!r} 的目标：{[t.get("label") for t in targets]}')


def _node_for(scene: dict, target: dict) -> dict:
    want = set(target.get('scene_ids') or [])
    assert want, f'目标 {target.get("target_id")} 没有 exact scene_ids'
    for n in scene.get('nodes') or []:
        if n.get('id') in want:
            return n
    raise AssertionError(f'scene 里找不到目标 {target.get("target_id")} 的 scene_ids {sorted(want)[:3]}')


def _wait_style(page, *, visible=True, timeout=60.0):
    ok = wait_for(lambda: page.evaluate(
        "() => { const s=document.getElementById('style-section');"
        " return !!(s && !s.hidden); }") is True,
        '样式区可见', timeout=timeout)[1]
    assert ok, '样式区始终 hidden（targets 为空？）' + page.debug()
    if visible:
        opts = page.evaluate(
            "() => Array.from(document.getElementById('style-target').options).map(o=>o.value)")
        assert len(opts) >= 2, f'样式目标过少：{opts}'


def _select(page, tid: str):
    page.select_option('#style-target', tid)
    ok = wait_for(lambda: page.evaluate(
        "() => document.getElementById('style-target').value") == tid,
        f'下拉选中 {tid}', timeout=15.0)[1]
    assert ok, f'下拉没选中 {tid}'


def _fill(page, value) -> None:
    page.fill('#style-value', str(value))
    ok = wait_for(lambda: page.evaluate(
        "() => document.getElementById('style-value').value") == str(value),
        f'输入框={value}', timeout=10.0)[1]
    assert ok, '输入框写入失败'


def _wait_state(page, want: str, timeout=120.0) -> None:
    _, ok = wait_for(lambda: page.get_attribute('#style-status', 'data-style-state') == want,
                     f'style-status={want}', timeout=timeout)
    assert ok, (f'status 不是 {want}：'
                f'{page.get_attribute("#style-status", "data-style-state")}'
                f'/{page.inner_text("#style-status")}'
                f' notice={page.inner_text("#style-notice") if page.is_visible("#style-notice") else "(无)"}'
                + '\n' + page.debug())


def _receipt(page) -> dict:
    return dict((_frame(page).get('style') or {}).get('receipt') or {})


def _pending_text(page) -> str:
    return page.inner_text('#style-pending-text') if page.is_visible('#style-pending') else ''


def _click_canvas_target(page, target: dict) -> None:
    scene = scene_of(page)
    node = _node_for(scene, target)
    x, y = label_hit_point(page, scene, node)
    page.mouse.move(x, y)
    wait_for(lambda: page.get_attribute('#inspector-root', 'data-hover-id') == node['id'],
             f'悬停 {node["id"]}', timeout=15.0)
    page.mouse.click(x, y)
    _, ok = wait_for(lambda: page.evaluate(
        "() => document.getElementById('style-target').value") == target['target_id'],
        f'画布选中同步到下拉 {target["target_id"]}', timeout=15.0)
    assert ok, (f'画布点击未同步样式目标（exact scene_ids 映射失败）：'
                f'点 {node["id"]}，下拉={page.evaluate("() => document.getElementById(\'style-target\').value")}'
                + '\n' + page.debug())


def _preview_expect(page, want: str, timeout=120.0) -> None:
    page.click('#style-preview')
    _wait_state(page, want, timeout=timeout)


def _confirm_expect(page, want: str, timeout=120.0) -> None:
    page.click('#style-confirm')
    _wait_state(page, want, timeout=timeout)


def _arm_copied_source(root: Path):
    """冻结 G15 的副本（目录结构保留，RAW 相对解析不变）；原件一个字节都不动。"""
    src_script, src_raw = SCRIPT.read_bytes(), RAW.read_bytes()
    dest_dir = root / 'proj'
    (dest_dir / 'raw').mkdir(parents=True, exist_ok=True)
    dest_script = dest_dir / 'g15b_barchart_decl.py'
    dest_raw = dest_dir / 'raw' / 'barchart.py'
    dest_script.write_bytes(src_script)
    dest_raw.write_bytes(src_raw)
    return dest_script, dest_raw, src_script, src_raw


def test_style_overlay_continuous_flow(browser):
    """①ylabel8→②x刻度8→③ylabel9→恢复10→④重启一致；耗时+截图+results.json。"""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='case-', dir=str(WORK_ROOT)))
    overlay = root / 'style.json'
    timings: dict[str, float] = {}
    servers: list = []
    context = None
    try:
        server = _launch(root, SCRIPT, overlay)
        servers.append(server)
        t0 = time.perf_counter()
        context, page = open_page(browser, server.base_url)
        timings['page_ready_s'] = time.perf_counter() - t0
        page.screenshot(path=str(root / 'baseline.png'))
        _wait_style(page)
        frame = _frame(page)
        ylabel = _by_label(_targets(frame), YLABEL)
        xtick = _by_label(_targets(frame), XTICK)
        assert ylabel['current_pt'] == 10.0, ylabel
        assert xtick['current_pt'] == 10.0, xtick
        assert ylabel['scene_ids'] and xtick['scene_ids']

        # ① 画布点 ylabel → 8 → 预览（正式不变）→ 确认 COMMITTED+PASS
        t0 = time.perf_counter()
        _click_canvas_target(page, ylabel)
        timings['select_s'] = time.perf_counter() - t0
        _fill(page, 8)
        before = _overlay_bytes(overlay)
        t0 = time.perf_counter()
        _preview_expect(page, VALIDATED)
        timings['preview_s'] = time.perf_counter() - t0
        assert _overlay_bytes(overlay) == before, '预览改了正式 Overlay'
        assert _overlay_bytes(overlay) is None or _sha(_overlay_bytes(overlay)) == _sha(before)
        pend = (_frame(page).get('style') or {}).get('pending') or {}
        assert pend.get('old_pt') == 10.0 and pend.get('new_pt') == 8.0, pend
        assert ylabel['target_id'] in (pend.get('affected') or []), pend
        t0 = time.perf_counter()
        _confirm_expect(page, SAVED)
        timings['confirm_s'] = time.perf_counter() - t0
        got = _by_label(_targets(_frame(page)), YLABEL)
        assert got['current_pt'] == 8.0 and got['saved_pt'] == 8.0, got
        rec = _receipt(page)
        assert rec.get('source_commit_state') == 'COMMITTED', rec
        assert rec.get('figure_verification_state') == 'PASS', rec
        page.click('#style-timing-wrap > summary')
        assert page.is_visible('#style-timings'), '展开验证耗时后应可见耗时清单'
        measured = page.evaluate("() => Array.from(document.getElementById('style-timings').querySelectorAll('dd'), el => el.textContent)")
        assert any('ms' in value and any(c.isdigit() for c in value) for value in measured), measured

        # ② 不刷新：x 刻度 → 8，ylabel 仍 8
        _select(page, xtick['target_id'])
        _fill(page, 8)
        before = _overlay_bytes(overlay)
        _preview_expect(page, VALIDATED)
        assert _overlay_bytes(overlay) == before, '预览改了正式 Overlay'
        _confirm_expect(page, SAVED)
        frame = _frame(page)
        assert _by_label(_targets(frame), YLABEL)['saved_pt'] == 8.0, _targets(frame)
        assert _by_label(_targets(frame), XTICK)['current_pt'] == 8.0, _targets(frame)
        assert _saved_map(overlay) == {ylabel['target_id']: 8.0, xtick['target_id']: 8.0}

        # ③ ylabel → 9 → 保存 → 显式恢复原始并确认（ylabel 回 10，刻度仍 8）
        _select(page, ylabel['target_id'])
        _fill(page, 9)
        _preview_expect(page, VALIDATED)
        _confirm_expect(page, SAVED)
        assert _by_label(_targets(_frame(page)), YLABEL)['current_pt'] == 9.0
        page.click('#style-restore')
        _wait_state(page, VALIDATED)
        pend = (_frame(page).get('style') or {}).get('pending') or {}
        assert '原始样式' in _pending_text(page), _pending_text(page)
        assert pend.get('new_pt') is None and pend.get('target_id') == ylabel['target_id'], pend
        _confirm_expect(page, SAVED)
        frame = _frame(page)
        final_ylabel = _by_label(_targets(frame), YLABEL)
        final_xtick = _by_label(_targets(frame), XTICK)
        assert final_ylabel['current_pt'] == 10.0, final_ylabel
        assert final_ylabel.get('saved_pt') is None, final_ylabel
        assert final_xtick['current_pt'] == 8.0 and final_xtick['saved_pt'] == 8.0, final_xtick
        page.screenshot(path=str(root / 'final.png'))

        overlay_saved = overlay.read_bytes()
        style_saved = _frame(page).get('style')
        (root / 'results.json').write_text(json.dumps({
            'timings_s': timings,
            'server_timings_ms': (style_saved or {}).get('timings_ms'),
            'targets': [{'target_id': t['target_id'], 'current_pt': t['current_pt'],
                         'saved_pt': t.get('saved_pt')} for t in _targets(_frame(page))],
            'overlay_sha256': _sha(overlay_saved),
            'screenshots': ['baseline.png', 'final.png'],
        }, ensure_ascii=False, indent=2), encoding='utf-8')

        # ④ 停服 → 新进程同入口同 Overlay → 重开一致
        context.close()
        context = None
        for s in servers:
            s.stop()
        servers.clear()
        restart_home = root / 'restart'
        server2 = _launch(restart_home, SCRIPT, overlay)
        servers.append(server2)
        assert overlay.read_bytes() == overlay_saved, '重启前 Overlay 被改'
        t0 = time.perf_counter()
        context, page = open_page(browser, server2.base_url)
        timings['restart_page_ready_s'] = time.perf_counter() - t0
        _wait_style(page)
        frame = _frame(page)
        assert _by_label(_targets(frame), YLABEL)['current_pt'] == 10.0
        assert _by_label(_targets(frame), XTICK)['saved_pt'] == 8.0
        assert _saved_map(overlay) == {xtick['target_id']: 8.0}
        (root / 'results.json').write_text(json.dumps({
            **json.loads((root / 'results.json').read_text(encoding='utf-8')),
            'restart_overlay_sha256': _sha(overlay.read_bytes()),
            'restart_page_ready_s': timings['restart_page_ready_s'],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        try:
            if context is not None:
                context.close()
        finally:
            for s in servers:
                try:
                    s.stop()
                except Exception:
                    pass
        print(f'\n[G18-style] case dir kept: {root}', flush=True)


def test_style_overlay_negatives_fail_closed(browser):
    """QA4/外部更新/源漂移/缺 token/任意字段/坏 Origin：拒绝 + 字节保留 + 失败 UI 明确。"""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)

    # ---- A 组：固定入口（QA + 安全 + 外部冲突，同 Overlay 顺序推进）----
    root = Path(tempfile.mkdtemp(prefix='neg-', dir=str(WORK_ROOT)))
    overlay = root / 'style.json'
    server = _launch(root, SCRIPT, overlay)
    context = None
    try:
        context, page = open_page(browser, server.base_url)
        _wait_style(page)
        ylabel = _by_label(_targets(_frame(page)), YLABEL)
        rev0 = _frame(page)['frame_revision']

        # QA：4pt 全图字形下限 → STYLE_REJECTED，正式不变，失败 UI 明确
        _select(page, ylabel['target_id'])
        _fill(page, 4)
        _preview_expect(page, FAILED)
        assert _overlay_bytes(overlay) is None, 'QA 失败写了正式文件'
        assert page.is_visible('#style-notice'), 'QA 失败应有明确提示'
        assert not page.is_visible('#style-pending'), '失败后不应有待确认'
        # 失败可恢复：回到合法值能重新预览（失败态不粘住）
        _fill(page, 8)
        _preview_expect(page, VALIDATED)
        page.click('#style-cancel')
        _wait_state(page, 'cancelled', timeout=30.0)

        # 缺 token：commit 无 X-Figpact-Ui → 403（经页面 fetch，同源真实线路）
        miss = page.evaluate("""async () => {
          const r = await fetch('/api/style/commit', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({candidate_id:'x', frame_revision:'y', expected_sha256:'z'})});
          let d=null; try { d = await r.json(); } catch(e) {}
          return {status: r.status, data: d}; }""")
        assert miss['status'] == 403 and (miss['data'] or {}).get('status') == 'FORBIDDEN', miss
        # 任意字段：preview 多带 overlay/script 路径 → 400 INVALID（可信路径绝不经 HTTP）
        extra = page.evaluate("""async (body) => {
          const r = await fetch('/api/style/preview', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(Object.assign({}, body, {overlay:'/tmp/evil.json'}))});
          let d=null; try { d = await r.json(); } catch(e) {}
          return {status: r.status, data: d}; }""",
            {'frame_revision': rev0, 'target_id': ylabel['target_id'], 'value': 8})
        assert extra['status'] == 400 and (extra['data'] or {}).get('status') == 'INVALID', extra
        assert _overlay_bytes(overlay) is None, '非法请求写了正式文件'
        # 坏 Origin：直连带伪造 Origin → 403 fail-closed（浏览器发不出该头，走服务端直连补）
        st, payload = server.json('POST', '/api/style/preview',
                                  {'frame_revision': rev0, 'target_id': ylabel['target_id'], 'value': 8},
                                  headers={'Origin': 'http://evil.example'})
        assert st == 403 and (payload or {}).get('status') == 'FORBIDDEN', (st, payload)
        assert _overlay_bytes(overlay) is None

        # 外部更新：合法预览后外部改盘 → 确认 OVERLAY_CONFLICT，保留外部字节
        _select(page, ylabel['target_id'])
        _fill(page, 8)
        _preview_expect(page, VALIDATED)
        official_before = _overlay_bytes(overlay)
        overlay.write_bytes(b'{"tampered": true}')
        external = overlay.read_bytes()
        assert external != (official_before or b'')
        page.click('#style-confirm')
        _wait_state(page, FAILED)
        assert overlay.read_bytes() == external, '冲突提交覆盖了外部字节'
        notice = page.inner_text('#style-notice') if page.is_visible('#style-notice') else ''
        assert 'OVERLAY_CONFLICT' in notice or '改动' in notice or '失败' in notice, notice
    finally:
        try:
            if context is not None:
                context.close()
        finally:
            try:
                server.stop()
            except Exception:
                pass
        print(f'\n[G18-style] neg case dir kept: {root}', flush=True)

    # ---- B 组：源漂移（只碰副本，冻结 G15 原件字节必须全程不变）----
    root2 = Path(tempfile.mkdtemp(prefix='drift-', dir=str(WORK_ROOT)))
    frozen_script, frozen_raw = SCRIPT.read_bytes(), RAW.read_bytes()
    overlay2 = root2 / 'style.json'
    script2, raw2, _, _ = _arm_copied_source(root2)
    server2 = _launch(root2, script2, overlay2)
    context2 = None
    try:
        context2, page2 = open_page(browser, server2.base_url)
        _wait_style(page2)
        yl2 = _by_label(_targets(_frame(page2)), YLABEL)
        xt2 = _by_label(_targets(_frame(page2)), XTICK)
        _select(page2, yl2['target_id'])
        _fill(page2, 8)
        _preview_expect(page2, VALIDATED)
        _confirm_expect(page2, SAVED)
        stable = overlay2.read_bytes()
        assert _saved_map(overlay2) == {yl2['target_id']: 8.0}, _saved_map(overlay2)
        # 漂移副本 RAW（注释也算漂移；从不断言执行，只认哈希门）
        raw2.write_bytes(raw2.read_bytes() + b'\n# drift\n')
        _select(page2, xt2['target_id'])
        _fill(page2, 8)
        _preview_expect(page2, FAILED, timeout=180.0)
        assert overlay2.read_bytes() == stable, '源漂移后正式字节被改'
        assert SCRIPT.read_bytes() == frozen_script and RAW.read_bytes() == frozen_raw, '动了冻结 G15 原件'
    finally:
        try:
            if context2 is not None:
                context2.close()
        finally:
            try:
                server2.stop()
            except Exception:
                pass
        print(f'\n[G18-style] drift case dir kept: {root2}', flush=True)
        assert SCRIPT.read_bytes() == frozen_script and RAW.read_bytes() == frozen_raw
