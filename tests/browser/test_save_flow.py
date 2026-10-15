"""G7b 层 1 门禁：保存闭环（真实 Chromium + 真服务 + NMR 夹具）。"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import time
import yaml
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from .conftest import launch_server, node_by_gid, open_page, scene_of, wait_for
from .test_drag_preview_flow import grab_point as _grab_point

NMR_SCRIPT = Path(__file__).resolve().parents[2] / 'examples' / 'nmr' / '08 NMR.py'
NMR_CONFIG = Path(__file__).resolve().parents[2] / 'examples' / 'nmr' / 'nmr.yaml'
TARGET_GID = 'fig2_nmr.main.peak.hama.2p02'
EVALUATE_PATH = '/api/intents/evaluate'
SELECTION_PATH = '/api/selection'
SAVE_PATH = '/api/save'
WORK_ROOT = Path(os.environ.get('TEMP') or tempfile.gettempdir()) / 'figpact-g7b-save'


class ApiLog:
    def __init__(self, page):
        self.calls = []
        page.route('**/api/**', self._handle)

    def _handle(self, route, request):
        self.calls.append((request.method, urlparse(request.url).path, request.post_data))
        route.continue_()

    def clear(self):
        self.calls.clear()


def _normalize_config(project_dir: Path) -> None:
    spec = importlib.util.spec_from_file_location('nmr_mod_g7b_save', project_dir / '08 NMR.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['nmr_mod_g7b_save'] = mod
    spec.loader.exec_module(mod)
    raw = yaml.safe_load((project_dir / 'nmr.yaml').read_text(encoding='utf-8'))
    prepared = mod.prepare_config(raw)
    (project_dir / 'nmr.yaml').write_text(
        yaml.safe_dump(prepared, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding='utf-8')


def _arm_project(root: Path):
    project_dir = root / 'project' / 'examples' / 'nmr'
    project_dir.parent.mkdir(parents=True, exist_ok=True)
    src_dir = NMR_SCRIPT.parent
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(src_dir, project_dir)
    _normalize_config(project_dir)
    script = project_dir / '08 NMR.py'
    config = project_dir / 'nmr.yaml'
    return script, config


def _launch_server(root: Path):
    script, config = _arm_project(root)
    root.mkdir(parents=True, exist_ok=True)
    server = launch_server(root, command=[sys.executable, '-B', '-m', 'figpact.inspector_server',
                                          '--script', str(script), '--config', str(config),
                                          '--scope', 'main', '--dpi', '240', '--port', '0'])
    return server, script, config


def _settle_quiet(log, *, quiet=0.5, timeout=10.0) -> bool:
    deadline = time.time() + timeout
    last = len(log.calls)
    last_change = time.time()
    while time.time() < deadline:
        now = len(log.calls)
        if now != last:
            last = now
            last_change = time.time()
        if time.time() - last_change >= quiet:
            return True
        time.sleep(0.1)
    return False


def _drag_accept(page, log):
    scene = scene_of(page)
    node = node_by_gid(scene, TARGET_GID)
    assert node['registered'] and node['identity_stability'] == 'stable' and node['measured'], node
    x, y = _grab_point(page, scene, node)
    page.mouse.click(x, y)
    wait_for(lambda: page.get_attribute('#inspector-root', 'data-selected-id') == node['id'],
             f'选中 {node["id"]}', timeout=10.0)
    assert page.get_attribute('#inspector-root', 'data-selected-id') == node['id']

    rect = page.evaluate("""() => { const r = document.getElementById('viewport').getBoundingClientRect();
        return {left: r.left, top: r.top, width: r.width, height: r.height}; }""")
    canvas = scene['canvas_bounds_mm']
    px_per_mm = rect['width'] / (canvas[2] - canvas[0])
    dx_px, dy_px = round(1.2 * px_per_mm), round(0.9 * px_per_mm)

    published = wait_for(lambda: any(call[1] == SELECTION_PATH for call in log.calls),
                         '选区发布', timeout=30.0)[1]
    assert published, log.calls
    _settle_quiet(log)
    log.clear()

    page.mouse.down()
    page.mouse.move(x + dx_px, y - dy_px)
    with page.expect_response(lambda response: urlparse(response.url).path == EVALUATE_PATH
                              and response.request.method == 'POST') as waiting:
        page.mouse.up()
    receipt = waiting.value.json()

    wait_for(lambda: '通过' in page.inner_text('#intent-status-badge')
                    or '未通过' in page.inner_text('#intent-status-badge'),
             '验证完成', timeout=120.0)
    badge = page.inner_text('#intent-status-badge')
    assert '通过' in badge, (badge, receipt)

    wait_for(lambda: not page.is_disabled('#btn-accept'), '接受按钮可用', timeout=10.0)
    page.click('#btn-accept')
    wait_for(lambda: page.locator('.pending-save').count() == 1, '待保存出现', timeout=30.0)
    return node


def test_save_flow_accept_then_save_commits_and_verifies(browser):
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='case-', dir=str(WORK_ROOT)))
    server, script, config = _launch_server(root)
    try:
        context, page = open_page(browser, server.base_url)
        log = ApiLog(page)
        try:
            _drag_accept(page, log)
            entries = page.locator('.pending-save')
            assert entries.count() == 1
            target = page.locator('.pending-save-target').inner_text()
            diff = page.locator('.pending-save-diff').inner_text()
            assert target.strip()
            assert diff.strip()

            with page.expect_response(lambda r: urlparse(r.url).path == SAVE_PATH
                                      and r.request.method == 'POST') as waiting:
                page.click('#save-changes')
                page.wait_for_selector('#save-confirmation:not([hidden])', timeout=10000)
                page.click('#save-confirm')
            resp = waiting.value.json()
            assert resp.get('source_commit_state') == 'COMMITTED', resp
            assert resp.get('figure_verification_state') == 'PASS', resp
            wait_for(lambda: page.inner_text('#save-result') == '修改已保存并通过验证',
                     '保存结果', timeout=30.0)
            assert page.inner_text('#save-result') == '修改已保存并通过验证'
            assert page.locator('.pending-save').count() == 0
        finally:
            context.close()
    finally:
        server.stop()
        shutil.rmtree(root, ignore_errors=True)


def test_save_flow_external_drift_refused_disk_unchanged(browser):
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='case-', dir=str(WORK_ROOT)))
    server, script, config = _launch_server(root)
    try:
        context, page = open_page(browser, server.base_url)
        log = ApiLog(page)
        try:
            _drag_accept(page, log)
            before = config.read_bytes()
            config.write_bytes(before + b'\n# external\n')
            after_external = config.read_bytes()

            with page.expect_response(lambda r: urlparse(r.url).path == SAVE_PATH
                                      and r.request.method == 'POST') as waiting:
                page.click('#save-changes')
                page.wait_for_selector('#save-confirmation:not([hidden])', timeout=10000)
                page.click('#save-confirm')
            resp = waiting.value.json()
            assert resp.get('status') == 'STALE_SOURCE', resp
            wait_for(lambda: page.inner_text('#save-result').strip() != '', '保存结果', timeout=30.0)
            text = page.inner_text('#save-result')
            assert str(config) in text, (text, config)
            assert '已保存' not in text and '已验证' not in text
            assert config.read_bytes() == after_external
        finally:
            context.close()
    finally:
        server.stop()
        shutil.rmtree(root, ignore_errors=True)
