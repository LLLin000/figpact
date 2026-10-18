"""Style drafts browser flow (owner: WorkspaceDraftUI). Real Chromium + real service.

G15b flow is the normal-PASS acceptance path only (never called a draft).
The draft closed loop is the real-FTIR flow below: inherited glyph FAIL
(4.7pt legend/subscript floor) -> preview shows explicit '保存工作草稿' ->
commit save_draft:true -> COMMITTED_DRAFT + wholeFAIL -> stop service ->
new process reopens same overlay -> continue editing xlabel/ticks -> second
save stays wholeFAIL -> strict overlay render refuses PNG. Parent runs all
tests finally; no draft-closure claims beyond what this file measures.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from .conftest import REPO_ROOT, launch_server, open_page, wait_for  # noqa: E402

G15B = REPO_ROOT / 'tools' / 'g15' / 'B' / 'g15b_barchart_decl.py'
assert G15B.is_file(), f'缺 G15b 固定夹具：{G15B}'
FTIR_SCRIPT = REPO_ROOT / 'examples' / 'ftir' / 'plot_ftir.py'
FTIR_CONFIG = REPO_ROOT / 'examples' / 'ftir' / 'ftir.yaml'
assert FTIR_SCRIPT.is_file() and FTIR_CONFIG.is_file(), '缺 FTIR 真实夹具'
FTIR_DATA = FTIR_SCRIPT.parent / '2084_1788253487778_26083154776'

WORK_ROOT = Path(os.environ.get('FIGPACT_BROWSER_WORKDIR')
                 or str(Path(tempfile.gettempdir()) / 'figpact-style-drafts'))
YLABEL = 'ylabel'


def _launch(root: Path, script: Path, overlay: Path, config: Path | None = None):
    overlay.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, '-m', 'figpact.inspector_server',
           '--script', str(script), '--scope', 'main',
           '--overlay', str(overlay), '--port', '0', '--dpi', '120']
    if config is not None:
        cmd += ['--config', str(config)]
    return launch_server(root, command=cmd, config=None)


def _frame(page) -> dict:
    return page.evaluate(
        '() => (window.FigpactInspector && window.FigpactInspector.currentFrame)'
        ' ? window.FigpactInspector.currentFrame() : window.FIGPACT_INSPECTOR_FRAME')


def _wait_style(page, timeout=300.0):
    ok = wait_for(lambda: page.evaluate(
        "() => !!document.getElementById('style-target') && "
        "document.getElementById('style-target').options.length >= 2 && "
        "document.getElementById('inspector-root').dataset.ready === 'true'"),
        'style targets ready', timeout=timeout)
    assert ok, '样式目标未就绪\n' + page.debug()


def _by_label(targets, label):
    for t in targets:
        if t.get('label') == label:
            return t
    raise AssertionError(f'no label {label}: {[t.get("label") for t in targets]}')


def _wait_state(page, want: str, timeout=180.0) -> None:
    _, ok = wait_for(lambda: page.get_attribute('#style-status', 'data-style-state') == want,
                     f'style state {want}', timeout=timeout)
    assert ok, (f'state={page.get_attribute("#style-status", "data-style-state")} '
                f'text={page.inner_text("#style-status")}\n' + page.debug())


def _receipt(page) -> dict:
    return dict((_frame(page).get('style') or {}).get('receipt') or {})


def _arm_ftir_copy(root: Path) -> tuple[Path, Path]:
    """Serve the repo FTIR originals read-only; overlay/outputs stay in tmp case dir.

    plot_ftir.py resolves its figpact import root + data dir from its own
    ancestors, so a /tmp script copy breaks the import (StopIteration) — the
    server serves REPO originals (read-only) while the overlay/output paths
    point at the tmp case dir. Frozen hashes prove the originals untouched.
    """
    frozen = {p: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (FTIR_SCRIPT, FTIR_CONFIG, FTIR_SCRIPT.parent / 'figure_style.py')}
    assert (FTIR_SCRIPT.parent / 'figure_style.py').is_file() and FTIR_DATA.is_dir()
    (root / 'ftir-frozen.json').write_text(
        __import__('json').dumps({str(k): v for k, v in frozen.items()}, ensure_ascii=False),
        encoding='utf-8')
    return FTIR_SCRIPT, FTIR_CONFIG


def test_style_normal_pass_acceptance_g15b(browser):
    """G15b 正常 PASS 验收（非草稿）：ylabel 8 → 保存 → 第二次编辑；对照组。"""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='normal-', dir=str(WORK_ROOT)))
    overlay = root / 'style.json'
    server = _launch(root, G15B, overlay)
    context = None
    try:
        context, page = open_page(browser, server.base_url)
        _wait_style(page)
        yl = _by_label(_frame(page)['style']['targets'], YLABEL)
        page.select_option('#style-target', yl['target_id'])
        page.fill('#style-value', '8')
        page.click('#style-preview')
        _wait_state(page, 'validated')
        assert '确认保存' in page.inner_text('#style-confirm'), '正常候选确认标签被改'
        assert '保存工作草稿' not in page.inner_text('#style-confirm')
        page.click('#style-confirm')
        _wait_state(page, 'saved')
        saved = {t['target_id']: t for t in _frame(page)['style']['targets']}
        assert saved[yl['target_id']]['saved_pt'] == 8.0
        page.fill('#style-value', '9')
        page.click('#style-preview')
        _wait_state(page, 'validated')
        page.click('#style-confirm')
        _wait_state(page, 'saved')
        assert _by_label(_frame(page)['style']['targets'], YLABEL)['current_pt'] == 9.0
    finally:
        try:
            if context is not None:
                context.close()
        finally:
            try:
                server.stop()
            except Exception:
                pass


def test_style_draft_rejects_bad_glyph_despite_explicit(browser):
    """G15b 新整图问题候选被拒绝：无 pending；字节保留（显式草稿也无旁路）。"""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='draft-neg-', dir=str(WORK_ROOT)))
    overlay = root / 'style.json'
    server = _launch(root, G15B, overlay)
    context = None
    try:
        context, page = open_page(browser, server.base_url)
        _wait_style(page)
        yl = _by_label(_frame(page)['style']['targets'], YLABEL)
        page.select_option('#style-target', yl['target_id'])
        page.fill('#style-value', '4')
        page.click('#style-preview')
        _wait_state(page, 'failed')
        assert not page.is_visible('#style-pending'), '失败后不应有待确认'
        assert not overlay.exists(), 'QA 失败写了正式文件'
    finally:
        try:
            if context is not None:
                context.close()
        finally:
            try:
                server.stop()
            except Exception:
                pass


def test_style_ftir_draft_save_reload_continue(browser):
    """真实 FTIR 草稿闭环：继承 glyph FAIL → 草稿保存 → 重开 → 第二次编辑仍 FAIL。

    preview 显式“保存工作草稿”；commit save_draft:true 收据 COMMITTED_DRAFT +
    figure FAIL；停服务后新进程重开同一 overlay 继续改 xlabel/ticks 非零值，
    第二次保存仍是 wholeFAIL；strict overlay render 拒绝 PNG（老字节否定对照）。
    """
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='ftir-draft-', dir=str(WORK_ROOT)))
    script, config = _arm_ftir_copy(root)
    overlay = root / 'style.json'
    server = _launch(root, script, overlay, config)
    context = None
    try:
        context, page = open_page(browser, server.base_url)
        _wait_style(page, timeout=300.0)
        frame = _frame(page)
        yl = _by_label(frame['style']['targets'], YLABEL)
        assert abs(float(yl['current_pt']) - 8.5) < 1e-9, yl
        page.select_option('#style-target', yl['target_id'])
        page.fill('#style-value', '9.5')
        page.click('#style-preview')
        _wait_state(page, 'validated', timeout=300.0)
        # preview 显式草稿标签 + 原图仍有 N 项未通过
        assert '保存工作草稿' in page.inner_text('#style-confirm'), page.inner_text('#style-confirm')
        pend_text = page.inner_text('#style-pending-text')
        assert '原图仍有' in pend_text and '不能合规导出' in pend_text, pend_text
        rec = _receipt(page)
        assert rec.get('local_edit_state') == 'PASS', rec
        assert rec.get('figure_verification_state') == 'FAIL', rec
        delta = rec.get('qa_delta') or {}
        assert delta.get('eligible') is True and not delta.get('new') and not delta.get('worsened'), delta
        # commit save_draft:true → COMMITTED_DRAFT + wholeFAIL
        page.click('#style-confirm')
        _wait_state(page, 'saved', timeout=300.0)
        rec2 = _receipt(page)
        assert rec2.get('source_commit_state') == 'COMMITTED_DRAFT', rec2
        assert rec2.get('figure_verification_state') == 'FAIL', rec2
        assert overlay.exists()
        draft_bytes = overlay.read_bytes()
        badge = page.inner_text('#style-status')
        assert '草稿' in badge and '未通过' in badge, badge
        context.close()
        context = None
        server.stop()
        server = None
        assert overlay.read_bytes() == draft_bytes, '停服改了正式字节'
        # 新进程重开：同一 workspace 同帧同态，继续第二次编辑
        restart_home = root / 'restart'
        server = _launch(restart_home, script, overlay, config)
        context, page = open_page(browser, server.base_url)
        _wait_style(page, timeout=300.0)
        frame2 = _frame(page)
        st2 = (frame2.get('style') or {})
        assert st2.get('workspace_draft') is True, st2
        assert st2.get('issue_count', 0) >= 1, st2
        page.wait_for_function(
            "() => document.getElementById('style-status').textContent.includes('草稿')",
            timeout=30000)
        assert '草稿' in page.inner_text('#style-status'), page.inner_text('#style-status')
        yl2 = _by_label(frame2['style']['targets'], YLABEL)
        assert yl2.get('saved_pt') == 9.5 and yl2.get('current_pt') == 9.5, yl2
        # 第二次编辑：xlabel/ticks 取非零合法值（tick 8.0→8.5）
        xt = _by_label(frame2['style']['targets'], 'x tick labels')
        page.select_option('#style-target', xt['target_id'])
        page.fill('#style-value', '8.5')
        page.click('#style-preview')
        _wait_state(page, 'validated', timeout=300.0)
        rec3 = _receipt(page)
        assert rec3.get('local_edit_state') == 'PASS', rec3
        page.click('#style-confirm')
        _wait_state(page, 'saved', timeout=300.0)
        rec4 = _receipt(page)
        assert rec4.get('source_commit_state') == 'COMMITTED_DRAFT', rec4
        assert rec4.get('figure_verification_state') == 'FAIL', rec4
        assert overlay.read_bytes() != draft_bytes, '第二次草稿保存未落盘'
        second_bytes = overlay.read_bytes()
        # strict overlay render 拒绝 PNG（老字节否定对照：正式图不可合规导出）
        from figpact import style_overlay as ov
        denied = ov.render(str(overlay), str(root / 'strict-should-not-exist.png'))
        assert (denied.get('figure_verification_state') in ('FAIL', 'ERROR')
                or denied.get('local_edit_state') != 'PASS'), denied
        assert not (root / 'strict-should-not-exist.png').exists(), '草稿被合规导出'
        assert overlay.read_bytes() == second_bytes, 'render 拒绝改了正式字节'
    finally:
        try:
            if context is not None:
                context.close()
        finally:
            if server is not None:
                try:
                    server.stop()
                except Exception:
                    pass
        frozen_now = {q: __import__('hashlib').sha256(q.read_bytes()).hexdigest() for q in (
            FTIR_SCRIPT, FTIR_CONFIG, FTIR_SCRIPT.parent / 'figure_style.py')}
        frozen_was = __import__('json').loads((root / 'ftir-frozen.json').read_text(encoding='utf-8'))
        assert {str(k): v for k, v in frozen_now.items()} == frozen_was, '动了 FTIR 源码原件'
