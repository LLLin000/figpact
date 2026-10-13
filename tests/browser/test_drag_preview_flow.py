"""P1 层 1 门禁：图上直接拖动 → 本地预览 → 松开即真实验证。

这一格守的是**三件互相独立的事实**：
  ① 拖动期间页面**一个后端调用都没有**：读数、ghost 轮廓、引线 ghost 全在本地算出来，
     既不逐帧重建 Matplotlib，也不发布选区。用页面自己发出的每一个 ``/api/*`` 调用作证。
  ② 光标旁的毫米读数与"指针真的走了多少毫米"一致，并且**右 / 上为正**。
  ③ 松开后才向引擎要一次回执——**恰好一次**；页面最终那句文案与回执逐项对上：所有检查
     PASS 才允许说"位置检查通过"，否则只能说"检查未通过 (<回执状态>)"。预览本身不是证据。

台子：``conftest.launch_server`` 起一个真 ``figpact.inspector_server`` 子进程，服务的是
**未改动的** ``examples/nmr``（只读，一个字节都不动），浏览器是 conftest 的真 Chromium。
本文件自带一个模块级会话：这样"松开即验证"在会话里留下的候选状态不会跨文件污染别的门禁。

本切片**只做平移拖动**。缩放 / 改尺寸需要引擎侧新的 operation kind 与 Oracle，不在这一格，
所以这里没有任何尺寸相关的断言。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

from .conftest import (NMR_CONFIG, NMR_SCRIPT, launch_server, node_by_gid, open_page,
                       scene_of, wait_for)

#: 被服务的例子源码与配置：只读，用例不碰它们。
assert NMR_SCRIPT.is_file() and NMR_CONFIG.is_file()

#: 页面自己声明的那句"拖动中"和"验证中"，以及引擎 PASS 之后才允许出现的最终文案。
PREVIEW_TEXT = '拖动预览，尚未验证'
VERIFYING_TEXT = '验证中…'
PASS_TEXT = '已重新绘图，位置检查通过'
#: 线路上的契约字面量：测试守的是协议本身，不引用前端实现常量。
EVALUATE_PATH = '/api/intents/evaluate'
SELECTION_PATH = '/api/selection'
#: 拖动目标：nmr 例子里带引线、可整体平移到新位置的峰值标注。
TARGET_GID = 'fig2_nmr.main.peak.hama.2p02'
#: 想拖出的位移（毫米）：向右 1.2、向上 0.9 —— 上为正这条规则靠这个符号顺序验。
WANT_MM = (1.2, 0.9)
#: 读数框的契约形状（含"右/上为正"和"预览未验证"两处措辞）。
READOUT_RE = re.compile(r'ΔX ([+-][0-9.]+) mm · ΔY ([+-][0-9.]+) mm（右/上为正）· 预览未验证')

WORK_ROOT = Path(os.environ.get('TEMP') or tempfile.gettempdir()) / 'figpact-p1-drag'


def expected_badge(receipt):
    """页面那句最终文案的契约（测试自己重写一遍：PASS 才叫通过，否则照抄回执状态）。"""
    passed = (receipt.get('status') == 'OK' and receipt.get('evaluation_state') == 'FEASIBLE'
              and receipt.get('verification_level') == 'RENDER_CHECKED'
              and bool(receipt.get('checks'))
              and all(check.get('status') == 'PASS' for check in receipt['checks']))
    return PASS_TEXT if passed else f"检查未通过 ({receipt.get('status') or '未通过'})"


class ApiLog:
    """页面发出的每一个 ``/api/*`` 调用；拖动期间这里必须**一条非 GET 都没有**。"""

    def __init__(self, page):
        self.calls = []
        page.route('**/api/**', self._handle)

    def _handle(self, route, request):
        self.calls.append((request.method, urlparse(request.url).path, request.post_data))
        route.continue_()

    def clear(self):
        self.calls.clear()

    def posts(self):
        return [call for call in self.calls if call[0] != 'GET']

    def evaluates(self):
        return [call for call in self.calls if call[1] == EVALUATE_PATH]


def viewport_box(page) -> dict:
    """页面自己那块画布矩形的真实尺寸（CSS px）：毫米换算的倍数只能来自它。"""
    return page.evaluate("""() => { const r = document.getElementById('viewport').getBoundingClientRect();
        return {left: r.left, top: r.top, width: r.width, height: r.height}; }""")


def to_client(scene, rect, x_mm, y_mm):
    """页面 ``screenToMm`` 的逆映射（倍数取自视口矩形的实际尺寸）。"""
    canvas = scene['canvas_bounds_mm']
    return (rect['left'] + (x_mm - canvas[0]) / (canvas[2] - canvas[0]) * rect['width'],
            rect['top'] + (canvas[3] - y_mm) / (canvas[3] - canvas[1]) * rect['height'])


def grab_point(page, scene, node):
    """标签内部一个**页面自己承认**的抓取点：命中测试说它就是这个对象，才按得下去。"""
    left, bottom, right, top = node['bounds_mm']
    rect = viewport_box(page)
    for fx in (0.5, 0.3, 0.7, 0.15, 0.85):
        for fy in (0.5, 0.3, 0.7):
            x, y = to_client(scene, rect, left + fx * (right - left), bottom + fy * (top - bottom))
            page.mouse.move(x, y)
            if page.get_attribute('#inspector-root', 'data-hover-id') == node['id']:
                return x, y
    raise AssertionError(f'标签 {node.get("gid")} 内部找不到页面自己承认的命中点')


def badge(page) -> str:
    return page.inner_text('#intent-status-badge')


def ghost_x_mm(page):
    """ghost 轮廓在用户坐标里的 x（毫米）；没有 ghost 就返回 None（不去等它出现）。"""
    element = page.query_selector('#highlights .ghost-outline')
    return None if element is None else float(element.get_attribute('x'))


def ghost_guide_path(page):
    """引线 ghost 的路径数据；没有就返回 None。"""
    element = page.query_selector('#highlights .ghost-guide-outline')
    return None if element is None else element.get_attribute('d')


def readout_mm(page):
    """光标旁读数里的两个毫米值；形状不对就当场失败（它是可见契约）。"""
    match = READOUT_RE.fullmatch(page.inner_text('#drag-readout'))
    assert match, page.inner_text('#drag-readout')
    return float(match.group(1)), float(match.group(2))


@pytest.fixture(scope='module')
def drag_server():
    """真服务子进程（只读地服务未改动的 nmr 例子）+ 这个文件自己的临时 state_home。"""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='case-', dir=str(WORK_ROOT)))
    server = launch_server(root, command=[sys.executable, '-m', 'figpact.inspector_server',
                                          '--example', 'nmr', '--scope', 'main',
                                          '--dpi', '240', '--port', '0'])
    try:
        yield server
    finally:
        server.stop()
        shutil.rmtree(root, ignore_errors=True)


def test_drag_previews_locally_then_verifies_exactly_once_on_release(drag_server, browser):
    """① 拖动期间零后端调用 + 读数正确；② 松开恰好一次 evaluate；③ 最终文案与回执一致。"""
    context, page = open_page(browser, drag_server.base_url)
    log = ApiLog(page)
    try:
        scene = scene_of(page)
        node = node_by_gid(scene, TARGET_GID)
        # 这个夹具必须真的能走完整条路：注册、稳定编号、有测量包围盒、带引线。
        assert node['registered'] and node['identity_stability'] == 'stable' and node['measured'], node
        guide_gid = node.get('linked_guide_gid')
        guide = next((n for n in scene['nodes'] if n.get('gid') == guide_gid or n.get('id') == guide_gid), None)
        assert guide_gid and guide and guide.get('runs_mm'), '这个夹具的标签必须带一条引线，引线 ghost 才算被覆盖'

        # 先选中：拖动只对"当前选中且可 ghost"的对象生效
        x, y = grab_point(page, scene, node)
        page.mouse.click(x, y)
        assert page.get_attribute('#inspector-root', 'data-selected-id') == node['id']

        rect = viewport_box(page)
        canvas = scene['canvas_bounds_mm']
        px_per_mm = rect['width'] / (canvas[2] - canvas[0])
        dx_px, dy_px = round(WANT_MM[0] * px_per_mm), round(WANT_MM[1] * px_per_mm)
        want = (dx_px / px_per_mm, dy_px / px_per_mm)

        # 选区发布是异步的：先让它在按下之前落地，之后出现的每一个 POST 都属于这次拖动
        published = wait_for(lambda: any(call[1] == SELECTION_PATH for call in log.calls),
                             '选区发布', timeout=10.0)[1]
        assert published, log.calls
        page.wait_for_timeout(200)
        log.clear()

        # ---- 按住并移动：预览阶段（读数 / ghost 轮廓 / 引线 ghost）一个后端调用都不许有
        page.mouse.down()
        page.mouse.move(x + dx_px, y - dy_px)
        assert log.posts() == [], log.posts()
        assert page.is_visible('#drag-readout'), '拖动期间光标旁应有毫米读数'
        shown = readout_mm(page)
        assert abs(shown[0] - want[0]) < 0.01 and abs(shown[1] - want[1]) < 0.01, (shown, want)
        # 右 / 上为正：这一拖是向右、向上，两个读数都必须是正的
        assert shown[0] > 0 and shown[1] > 0, shown
        # 读数贴在光标附近，而不是飘在别处
        box = page.evaluate("""() => { const r = document.getElementById('drag-readout').getBoundingClientRect();
            return {left: r.left, top: r.top, width: r.width, height: r.height}; }""")
        assert abs(box['top'] + box['height'] / 2 - (y - dy_px)) < 12, box
        assert 0 <= box['left'] - (x + dx_px) <= 40, box
        assert badge(page) == PREVIEW_TEXT, badge(page)
        ghost_x = ghost_x_mm(page)
        assert ghost_x is not None, '拖动期间应有 ghost 轮廓'
        assert abs(ghost_x - (node['bounds_mm'][0] + shown[0])) < 0.01, (ghost_x, node['bounds_mm'], shown)
        assert ghost_guide_path(page), '引线 ghost 也该跟着走'

        # 反复移动仍旧只是预览：读数回到同一处，一个 POST 都不许出现
        page.mouse.move(x + dx_px - 2, y - dy_px + 2)
        assert log.posts() == [], log.posts()
        page.mouse.move(x + dx_px, y - dy_px)
        assert log.posts() == [], log.posts()
        assert readout_mm(page) == shown
        # 拖动不许改选区
        assert page.get_attribute('#inspector-root', 'data-selected-id') == node['id']

        # ---- 松开：先"验证中"，再由引擎回执定稿
        with page.expect_response(lambda response: urlparse(response.url).path == EVALUATE_PATH
                                  and response.request.method == 'POST') as waiting:
            page.mouse.up()
            immediate = badge(page)
            assert '通过' not in immediate and '已验证' not in immediate and '已保存' not in immediate, immediate
            seen = wait_for(lambda: badge(page) == VERIFYING_TEXT, '验证中', timeout=5.0)[1]
            assert seen, f'松开后应先进入"验证中"，而不是直接下结论：{immediate}'
        receipt = waiting.value.json()

        # ---- 恰好一次 evaluate，而且页面送出去的目标位移就是读数显示的那一份
        evaluate_calls = log.evaluates()
        assert len(evaluate_calls) == 1, [call[:2] for call in log.calls]
        sent = json.loads(evaluate_calls[0][2])
        assert sent['target_gid'] == node['gid'] and sent['operation'] == 'translate', sent
        assert abs(sent['delta_mm'][0] - shown[0]) < 0.01 and abs(sent['delta_mm'][1] - shown[1]) < 0.01, (sent, shown)

        # ---- 最终文案与回执一致：这个夹具是"真重建通过"，所以必须落到 PASS 那句
        expected = expected_badge(receipt)
        assert expected == PASS_TEXT, receipt
        settled = wait_for(lambda: badge(page) == expected, f'最终文案 {expected}', timeout=60.0)[1]
        assert settled, f'{badge(page)} != {expected}；回执 {receipt}'
        assert not page.is_visible('#drag-readout'), '松手后读数框该收起'
        assert page.get_attribute('#inspector-root', 'data-selected-id') == node['id']
        # 实测 / 目标 / 误差三条都在回执与面板里对上
        measured = receipt['measured_delta_mm']
        assert abs(measured[0] - sent['delta_mm'][0]) < 0.01 and abs(measured[1] - sent['delta_mm'][1]) < 0.01, receipt
        assert receipt['error_mm'] is not None and receipt['error_mm'] <= 0.01, receipt
        results = page.inner_text('#intent-eval-results')
        assert '实测位移' in results and '位移误差' in results, results
        # 验证通过 ≠ 已保留：这是会话内的候选，ghost 还停在新位置上等人明确保留或取消
        assert ghost_x_mm(page) is not None
    finally:
        context.close()


def test_drag_layer_leaves_the_existing_selection_paths_alone(drag_server, browser):
    """既有点选 / Alt 轮换 / 方向键微调不变；没净位移或没选中的拖动什么都不发。"""
    context, page = open_page(browser, drag_server.base_url)
    log = ApiLog(page)
    try:
        scene = scene_of(page)
        labels = sorted((n for n in scene['nodes']
                         if n.get('gid') and n['type'] == 'text' and n['measured'] and not n['fully_clipped']
                         and 'guide' not in n['gid']), key=lambda n: n['id'])
        assert len(labels) >= 2, '这个夹具至少要两个可点标签'
        other = next(n for n in labels if n['gid'] != TARGET_GID)

        # ① 点选照旧
        other_x, other_y = grab_point(page, scene, other)
        page.mouse.click(other_x, other_y)
        assert page.get_attribute('#inspector-root', 'data-selected-id') == other['id']
        page.wait_for_timeout(200)
        log.clear()

        # ② 拖了但净位移为零：不发请求，也不留 ghost
        page.mouse.down()
        page.mouse.move(other_x + 12, other_y)
        page.mouse.move(other_x, other_y)
        assert page.is_visible('#drag-readout'), '拖动中仍要有即时预览'
        page.mouse.up()
        assert log.evaluates() == [], log.calls
        assert badge(page) == '未调整', badge(page)
        assert not page.is_visible('#drag-readout')
        assert ghost_x_mm(page) is None

        # ③ 方向键微调照旧：本地示范，不偷偷验证
        page.keyboard.press('ArrowRight')
        assert page.inner_text('#intent-displacement') == '本次调整：ΔX 0.1 mm, ΔY 0 mm'
        assert badge(page) == '位置示范，尚未验证', badge(page)
        assert log.evaluates() == [], log.calls

        # ④ Alt+拖动不是拖动：轮换那条老路不许被拖动层吃掉，也不许顺手验证
        page.keyboard.down('Alt')
        page.mouse.move(other_x, other_y)
        page.mouse.down()
        page.mouse.move(other_x + 20, other_y - 10)
        assert not page.is_visible('#drag-readout'), 'Alt+拖动不该进入拖动预览'
        assert badge(page) == '位置示范，尚未验证', badge(page)
        page.mouse.up()
        page.keyboard.up('Alt')
        assert log.evaluates() == [], log.calls

        # ⑤ 有未处理偏移时点选别的对象仍旧被挡住（既有语义）
        third = next(n for n in labels if n['gid'] != other['gid'])
        third_x, third_y = grab_point(page, scene, third)
        page.mouse.click(third_x, third_y)
        assert page.get_attribute('#inspector-root', 'data-selected-id') == other['id']
        assert page.is_visible('#intent-notice'), '未处理的偏移必须当场说明'
        assert badge(page) == '位置示范，尚未验证', badge(page)
    finally:
        context.close()
