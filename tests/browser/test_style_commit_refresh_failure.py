"""G19 层 1 门禁：commit 真写盘后仅 post-commit 刷新失败 —— 真浏览器故障注入。

服务端是可信启动 harness（--script/--overlay 真服务），故障经测试期 sitecustomize
在子进程内 patch StyleSession._rebuild（生产无 HTTP 故障开关、无此文件）；
flag 文件只武装 commit 后的那一次 _rebuild，ov.apply 本体不动。页面真实点击
preview/confirm，断言：① overlay 字节已存；② UI 显示“文件已保存，但界面刷新失败”
而非保存失败/未写入；③ 无新帧时编辑冻结；④ 同 overlay 重起可恢复。
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

SCRIPT = REPO_ROOT / 'tools' / 'g15' / 'B' / 'g15b_barchart_decl.py'
assert SCRIPT.is_file(), f'缺 G15b 固定夹具：{SCRIPT}'

WORK_ROOT = Path(os.environ.get('FIGPACT_BROWSER_WORKDIR')
                 or str(Path(tempfile.gettempdir()) / 'figpact-g19-refresh-fail'))
NEED = '文件已保存，但界面刷新失败'


def _frame(page) -> dict:
    return page.evaluate(
        '() => (window.FigpactInspector && window.FigpactInspector.currentFrame)'
        ' ? window.FigpactInspector.currentFrame() : window.FIGPACT_INSPECTOR_FRAME')


def _wait_style(page, timeout=60.0):
    ok = wait_for(lambda: page.evaluate(
        "() => { const s = document.getElementById('style-target');"
        " return s && s.options && s.options.length >= 2; }"),
        '样式目标就绪', timeout=timeout, interval=0.2)[1]
    assert ok, '样式目标未就绪\n' + page.debug()


def _launch(root: Path, script: Path, overlay: Path):
    """可信启动 harness：子进程启动后 patch post-commit rebuild（生产无此开关）。

    不用 sitecustomize：它在解释器启动期执行，早于 ``python -m`` 插入 cwd，
    此时 ``import figpact`` 必失败（已由归档 case 的 server-stderr.log 证实）。
    ``-c`` 包装在路径就绪后打补丁，再进同一 ``main``。
    """
    overlay.parent.mkdir(parents=True, exist_ok=True)
    flag = root / 'fail-postcommit'
    if flag.exists():
        flag.unlink()
    harness = '\n'.join([
        'import sys as _sys',
        f'_sys.path.insert(0, {str(REPO_ROOT)!r})',
        'import pathlib as _pl',
        'import figpact.inspector_style as _m',
        f'_FLAG = {str(flag)!r}',
        '_real = _m.StyleSession._rebuild',
        'def _boom(self, overlay_path=None):',
        '    if _pl.Path(_FLAG).exists():',
        '        raise RuntimeError("injected post-commit rebuild failure")',
        '    return _real(self, overlay_path)',
        '_m.StyleSession._rebuild = _boom',
        'from figpact.inspector_server import main as _main',
        '_main(_sys.argv[1:])',
    ])
    return launch_server(root, command=[sys.executable, '-c', harness,
                                       '--script', str(script), '--scope', 'main',
                                       '--overlay', str(overlay),
                                       '--port', '0', '--dpi', '120'],
                         config=None)

def _wait_state(page, want: str, timeout=120.0) -> None:
    _, ok = wait_for(lambda: page.get_attribute('#style-status', 'data-style-state') == want,
                     f'等待样式状态 {want}', timeout=timeout, interval=0.2)
    assert ok, (f'样式状态不是 {want}：'
                f'{page.get_attribute("#style-status", "data-style-state")} / '
                f'{page.inner_text("#style-status")}\n' + page.debug())


def test_commit_refresh_failure_saved_but_stale(browser):
    """真提交 + 伪刷新失败：字节已存 + UI 报刷新失败 + 编辑冻结 + 重载恢复。"""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='case-refresh-fail-', dir=str(WORK_ROOT)))
    overlay = root / 'style.json'
    server = _launch(root, SCRIPT, overlay)
    context = None
    try:
        context, page = open_page(browser, server.base_url)
        _wait_style(page)
        frame = _frame(page)
        targets = list((frame.get('style') or {}).get('targets') or [])
        assert len(targets) >= 1, frame
        tid = targets[0]['target_id']
        page.select_option('#style-target', tid)
        page.fill('#style-value', '8')
        page.click('#style-preview')
        _wait_state(page, 'validated')
        before = overlay.read_bytes() if overlay.exists() else None

        # 故障只武装 post-commit _rebuild：preview 的 _rebuild 在 confirm 点击前
        # 已跑完；ov.apply 本体从不动。flag 文件一建，子进程下一次 _rebuild 即抛错。
        (root / 'fail-postcommit').write_text('1', encoding='utf-8')
        page.click('#style-confirm')  # 真实点击
        _wait_state(page, 'saved')
        try:
            (root / 'fail-postcommit').unlink()
        except OSError:
            pass

        # ① 核心保存已完成：overlay 字节真实落盘。
        assert overlay.exists(), 'refresh 失败不许回滚正式写盘'
        saved = {t['id']: float(t['value']) for t in
                 json.loads(overlay.read_text(encoding='utf-8'))['targets']}
        assert saved.get(tid) == 8.0, saved
        if before is not None:
            assert overlay.read_bytes() != before
        # ② 文案是刷新失败，不是保存失败/未写入。
        badge = page.inner_text('#style-status')
        notice = page.inner_text('#style-notice')
        assert NEED in badge, badge + '\n' + page.debug()
        assert NEED in notice, notice + '\n' + page.debug()
        assert '保存失败' not in badge, badge
        assert '未改动' not in notice and '未写入' not in notice, notice
        # ③ 无新帧：编辑控件冻结（无 stale 帧可继续编辑）。
        for el in ('#style-preview', '#style-confirm', '#style-value', '#style-target'):
            assert page.is_disabled(el), f'{el} 应冻结'
        # ④ 重载恢复：同 overlay 重起服务（正式字节即事实），新页面读到已保存的 8pt。
        overlay_saved = overlay.read_bytes()
        context.close()
        context = None
        server.stop()
        server = _launch(root, SCRIPT, overlay)
        assert overlay.read_bytes() == overlay_saved, '重启前 Overlay 被改'
        context, page = open_page(browser, server.base_url)
        _wait_style(page)
        rows = {t['target_id']: t for t in
                list((_frame(page).get('style') or {}).get('targets') or [])}
        assert rows[tid]['saved_pt'] == 8.0, rows[tid]
        shot = root / 'refresh-fail.png'
        page.screenshot(path=str(shot))
        assert shot.exists()
        print(f'\n[G19-refresh-fail] overlay sha={hashlib.sha256(overlay.read_bytes()).hexdigest()}', flush=True)
    finally:
        try:
            if context is not None:
                context.close()
        finally:
            try:
                server.stop()
            except Exception:
                pass
        print(f'\n[G19-refresh-fail] case dir kept: {root}', flush=True)
