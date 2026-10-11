"""科学不变性：排版动作**不许**改动受保护内容，不同 DPI 也不许改。

测量口径（每条断言都写清是哪种量）：
- `TOL_VECTOR_MM = 1e-6`：**数学几何**——把图元的坐标/端点经它的 transform 换成
  显示像素再换算成毫米。位移、面板外框、比例尺端点长度都属于这一类。
- `TOL_ENVELOPE_MM = 1e-6`：轴对齐包围盒（面板外框由毫米外边距直接算出来）。

断言挑对象时**以夹具声明的节点/路径为准**（`layout_contract(scope)`），不靠 gid
命名或图纸顺序去猜：声明里没有的对象不许画出来，声明了的必须有真对象。

像素级断言用的是 Agg 的画布缓冲（内存里，不落盘），DPI 固定成 254（1 mm = 10 px）
以便整数像素对齐。
"""
from __future__ import annotations

import copy
import hashlib
import unittest

import matplotlib.pyplot as plt
import numpy as np

from figpact import inventory as fp_inventory
from figpact.units import MM_PER_INCH
from tests.fixtures import _native, fixture_data

TOL_VECTOR_MM = 1e-6
TOL_ENVELOPE_MM = 1e-6
#: 254 dpi ⇒ 1 mm 正好 10 px：像素级断言不受四舍五入影响。
PIXEL_DPI = 254


def load(name: str):
    import importlib

    return importlib.import_module(f"tests.fixtures.{name}")


def digest(array) -> str:
    return hashlib.sha256(np.ascontiguousarray(np.asarray(array)).tobytes()).hexdigest()


def figure_digest(fig) -> str:
    """图里**受保护内容**的独立指纹：数组字节、文本、显示窗口、像素。

    不依赖任何引擎中间层：测试自己从真实 Artist 上读回来。
    """
    payload: list[str] = []
    by_gid = _native.artists_by_gid(fig)
    for gid in sorted(by_gid):
        art = by_gid[gid]
        if hasattr(art, "get_xdata") and hasattr(art, "get_ydata"):
            payload.append(f"{gid}|x:{digest(art.get_xdata())}|y:{digest(art.get_ydata())}")
        elif hasattr(art, "get_array"):
            payload.append(f"{gid}|pix:{digest(art.get_array())}|extent:{tuple(np.ravel(art.get_extent()))}")
        elif hasattr(art, "get_x") and hasattr(art, "get_width"):
            # axvspan 出来的窗口矩形：受保护的**显示窗口**，也是科学内容的一部分。
            payload.append(f"{gid}|win:{float(art.get_x())}|{float(art.get_width())}|"
                           f"{float(art.get_y())}|{float(art.get_height())}")
        elif hasattr(art, "get_text"):
            payload.append(f"{gid}|text:{art.get_text()}")
    for ax in fig.axes:
        payload.append(f"view|{tuple(np.round(ax.get_xlim(), 12))}|{tuple(np.round(ax.get_ylim(), 12))}")
    return hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()


def mm_per_px(fig) -> float:
    return MM_PER_INCH / float(fig.dpi)


def envelope_mm(fig, art) -> tuple[float, float, float, float]:
    """图元的显示包围盒（毫米，画布左下原点）。"""
    fig.canvas.draw()
    bb = art.get_window_extent(fig.canvas.get_renderer())
    scale = mm_per_px(fig)
    return (bb.x0 * scale, bb.y0 * scale, bb.width * scale, bb.height * scale)


def vertex_mm(fig, art, index: int = 0) -> tuple[float, float]:
    """折线顶点在画布上的毫米坐标（数学几何，不经光栅化）。"""
    fig.canvas.draw()
    pts = art.get_transform().transform(art.get_xydata())
    scale = mm_per_px(fig)
    return (float(pts[index, 0]) * scale, float(pts[index, 1]) * scale)


def text_anchor_mm(fig, text) -> tuple[float, float]:
    """文字锚点的毫米坐标：走 transform，不走墨迹包围盒（所以是数学几何）。"""
    fig.canvas.draw()
    x, y = text.get_position()
    px = text.get_transform().transform((x, y))
    scale = mm_per_px(fig)
    return (float(px[0]) * scale, float(px[1]) * scale)


def select(fig, reg, *, type_name: str | None = None, points: int | None = None,
           policy_of=None, science_policy: str | None = None, scope: str | None = None) -> list[str]:
    """按**实测特征**挑对象（类型 / 采样点数 / 声明的 science_policy），不猜命名。

    用 `science_policy` 时必须给 `policy_of`（声明的节点表）：没有声明表就没法按声明筛，
    静默筛出空集只会让断言变成"什么都没测"。
    """
    if science_policy is not None and policy_of is None:
        raise AssertionError("按 science_policy 挑对象必须给 policy_of（契约节点表）")
    inv = {item["gid"]: item for item in fp_inventory(fig, reg)["items"]}
    chosen = []
    for gid, item in inv.items():
        if type_name is not None and item["type"] != type_name:
            continue
        if points is not None and f"points={points}" not in item["summary"]:
            continue
        if science_policy is not None:
            if policy_of.get(gid, {}).get("science_policy") != science_policy:
                continue
        if scope is not None and f".{scope}." not in gid:
            continue
        chosen.append(gid)
    return sorted(chosen)


def build(module, scope: str, *, config: dict | None = None):
    cfg = config if config is not None else module.load_config()
    fig, reg = module.build_scene(module.load_science(), cfg, scope)
    return fig, reg, cfg


def policy_map(module, scope: str) -> dict:
    return module.layout_contract(scope)["nodes"]


def declared(module, scope: str, *, type_name: str | None = None,
             science_policy: str | None = None) -> dict[str, dict]:
    """**声明**的节点（契约 `nodes`）里符合条件的那批：{gid: metadata}。

    断言的对象集合来自夹具自己的声明面；`type_name` 用声明里的类型，不靠实测类型去猜
    （画布 patch 实测是 Rectangle，声明里却是 Figure —— 按实测类型筛会把它当成带位窗口）。
    """
    nodes = policy_map(module, scope)
    return {gid: meta for gid, meta in nodes.items()
            if (type_name is None or meta.get("type") == type_name)
            and (science_policy is None or meta.get("science_policy") == science_policy)}


def params_of_path(module, scope: str, path: list) -> dict:
    """契约里**精确路径**等于 `path` 的那条参数记录（找不到 = 直接失败）。"""
    for record in module.layout_contract(scope)["parameters"]:
        if list(record.get("path") or []) == list(path):
            return record
    raise AssertionError(f"契约里没有声明路径 {path}")


def get_at(config: dict, path: list):
    node = config
    for segment in path[:-1]:
        node = node[segment]
    return node[path[-1]]


def set_at(config: dict, path: list, value) -> None:
    node = config
    for segment in path[:-1]:
        node = node[segment]
    node[path[-1]] = value


def rendered_geometry(fig, reg) -> list[tuple]:
    """图里登记图元的**语义投影**：gid / 类型 / 实测快照（包围盒、位置、线宽、字号、点数）。

    非文本/非折线的图元，清点清单里的 `summary` 是 Artist 的 repr（带内存地址）——
    那是地址不是行为，投影里换成空串。
    """
    out = []
    for item in fp_inventory(fig, reg)["items"]:
        summary = item["summary"]
        if summary.startswith("<"):
            summary = ""
        out.append((item["gid"], item["type"], summary,
                    tuple(sorted(item["snapshot"].items()))))
    return sorted(out)


def declared_defect(module, kind: str) -> dict:
    """按**声明的缺陷种类**取缺陷登记（不按 key 名字猜）。"""
    for item in module.DEFECTS.values():
        if item.get("kind") == kind:
            return item
    raise AssertionError(f"{module.FIGURE_ID} 的 DEFECTS 里没有声明 {kind} 这类缺陷")


class FtirInvarianceTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_plotted_arrays_are_the_protected_arrays(self):
        """每个作用域画出来的曲线**就是**声明的那条受保护数组（声明与图纸双向对齐）。"""
        module = load("native_ftir")
        for scope in module.SCOPES:
            science = module.load_science()
            fig, reg, _ = build(module, scope)
            try:
                panels = module.COMPARE_SCOPES if scope in module.COMPARE_SCOPES else (scope,)
                declared_lines = {gid for panel in panels
                                  for gid in declared(module, panel, type_name="Line2D")}
                self.assertTrue(declared_lines, f"{scope} 没声明任何折线")
                drawn = set(select(fig, reg, type_name="Line2D"))
                self.assertTrue(drawn <= declared_lines,
                                f"{scope} 画了没有任何作用域声明的折线：{sorted(drawn - declared_lines)}")
                for sid in module.CURVE_IDS:
                    gid = module.gid(scope, "curve", sid)
                    art = reg.get(gid)
                    if gid not in declared_lines:
                        # 声明里没有 = 这个作用域不画这条曲线（对照图只画 a）：不许偷偷画出来。
                        self.assertIsNone(art, f"{scope} 没声明曲线 {sid}，却把它画出来了")
                        continue
                    self.assertIsNotNone(art, f"{scope} 声明了曲线 {sid}，却没画出来")
                    want_x, want_y = module._expected_series(science, scope, sid)
                    np.testing.assert_array_equal(np.asarray(art.get_xdata(), float), want_x)
                    np.testing.assert_array_equal(np.asarray(art.get_ydata(), float), want_y)
            finally:
                plt.close(fig)

    def test_layout_change_does_not_touch_arrays_or_windows(self):
        """非零排版动作（堆叠台阶 + 逐曲线位移 + 标签上抬）之后，内容逐字节不变。

        位移量按**声明的作用集合**算：`curve_gap_mm` 声明抬升的是「除第一条以外的活跃
        曲线」，逐曲线位移各管自己那条 —— 不是"每条曲线都加同一个毫米数"。
        """
        module = load("native_ftir")
        scope = "main"
        base_cfg = module.load_config()
        gap_delta, shift_delta, lift_delta = 1.5, 3.0, 1.0
        moved_cfg = copy.deepcopy(base_cfg)
        moved_cfg["curve_gap_mm"] = base_cfg["curve_gap_mm"] + gap_delta
        moved_cfg["shifts_mm"]["main"]["b"] = shift_delta
        moved_cfg["band_label_lift_mm"] = base_cfg["band_label_lift_mm"] + lift_delta

        stacked = set(params_of_path(module, scope, ["curve_gap_mm"])["objects"])
        shifted = set(params_of_path(module, scope, ["shifts_mm", scope, "b"])["objects"])
        lifted = set(params_of_path(module, scope, ["band_label_lift_mm"])["objects"])
        self.assertTrue(stacked and shifted and lifted, "声明的作用集合不该是空的")

        base_fig, base_reg, _ = build(module, scope, config=base_cfg)
        moved_fig, moved_reg, _ = build(module, scope, config=moved_cfg)
        try:
            self.assertEqual(figure_digest(base_fig), figure_digest(moved_fig),
                             "排版动作改动了受保护内容（数组/文本/显示窗口/像素）")
            for sid in module.CURVE_IDS:
                gid = module.gid(scope, "curve", sid)
                if base_reg.get(gid) is None:
                    continue
                want = (gap_delta if gid in stacked else 0.0) + (shift_delta if gid in shifted else 0.0)
                before = vertex_mm(base_fig, base_reg.get(gid), 0)
                after = vertex_mm(moved_fig, moved_reg.get(gid), 0)
                self.assertAlmostEqual(after[1] - before[1], want, delta=TOL_VECTOR_MM,
                                       msg=f"{gid} 的毫米位移不是声明的 {want} mm")
                self.assertAlmostEqual(after[0] - before[0], 0.0, delta=TOL_VECTOR_MM)
            for gid in sorted(lifted):
                before = text_anchor_mm(base_fig, base_reg.get(gid))
                after = text_anchor_mm(moved_fig, moved_reg.get(gid))
                self.assertAlmostEqual(after[1] - before[1], lift_delta, delta=TOL_VECTOR_MM,
                                       msg=f"{gid} 的上抬不是 {lift_delta} mm")
                self.assertAlmostEqual(after[0] - before[0], 0.0, delta=TOL_VECTOR_MM)
                self.assertEqual(tuple(base_reg.get(gid).get_position()),
                                 tuple(moved_reg.get(gid).get_position()),
                                 "数据坐标被改动了：上抬必须只走显示位移")
        finally:
            plt.close(base_fig)
            plt.close(moved_fig)

    def test_band_labels_move_by_real_millimetres_not_data_units(self):
        """标签上抬是**毫米显示位移**：数据坐标不动，画布位移正好等于毫米差。

        要移动的对象按声明取：带位文本是 LOCKED_SCIENCE 的 Text 节点。
        """
        module = load("native_ftir")
        scope = "main"
        base_cfg = module.load_config()
        shifted_cfg = copy.deepcopy(base_cfg)
        shifted_cfg["band_label_lift_mm"] = base_cfg["band_label_lift_mm"] + 2.0

        base_fig, base_reg, _ = build(module, scope, config=base_cfg)
        moved_fig, moved_reg, _ = build(module, scope, config=shifted_cfg)
        try:
            protected_text = declared(module, scope, type_name="Text",
                                      science_policy="LOCKED_SCIENCE")
            labels = [module.gid(scope, "band_label", bid) for bid in fixture_data.FTIR_BAND_TEXT]
            for gid in labels:
                self.assertIn(gid, protected_text, f"{gid} 没被声明成受保护文本")
                self.assertIsNotNone(base_reg.get(gid), f"{gid} 没画出来")
            self.assertEqual({base_reg.get(g).get_text() for g in labels},
                             set(fixture_data.FTIR_BAND_TEXT.values()),
                             "被移动的对象不是那四条受保护带位文本")
            for gid in labels:
                before = text_anchor_mm(base_fig, base_reg.get(gid))
                after = text_anchor_mm(moved_fig, moved_reg.get(gid))
                self.assertAlmostEqual(after[1] - before[1], 2.0, delta=TOL_VECTOR_MM,
                                       msg=f"{gid} 的毫米位移不是 2.0 mm")
                self.assertAlmostEqual(after[0] - before[0], 0.0, delta=TOL_VECTOR_MM)
                # 数据坐标一个字节都不许被"换算"过。
                self.assertEqual(tuple(base_reg.get(gid).get_position()),
                                 tuple(moved_reg.get(gid).get_position()))
        finally:
            plt.close(base_fig)
            plt.close(moved_fig)

    def test_band_windows_and_texts_are_protected(self):
        """受保护的显示窗口（cm⁻¹）与受保护的科学文本：按声明的 gid 逐个核对。"""
        module = load("native_ftir")
        bands = fixture_data.ftir_band_limits()
        texts = fixture_data.FTIR_BAND_TEXT
        centers = fixture_data.ftir_band_centers()
        for scope in module.SCOPES:
            if scope in module.COMPARE_SCOPES:
                # 对照图不画带位窗口/带位文本（声明里也没有），别按单格图的形状去要求它。
                self.assertEqual(declared(module, scope, type_name="Rectangle"), {},
                                 f"{scope} 声明了单格图才有的带位窗口")
                continue
            fig, reg, _ = build(module, scope)
            try:
                declared_windows = declared(module, scope, type_name="Rectangle",
                                            science_policy="LOCKED_SCIENCE")
                self.assertEqual(sorted(declared_windows),
                                 sorted(module.gid(scope, "band", bid) for bid in bands),
                                 "声明的带位窗口不是受保护的那四块")
                for bid, (lo, hi) in bands.items():
                    span = reg.get(module.gid(scope, "band", bid))
                    self.assertIsNotNone(span, f"{scope} 带位窗口 {bid} 没画出来")
                    # 窗口是受保护的显示窗口：容差只为吸收 `lo + (hi - lo)` 这种浮点写法，
                    # 不是给"窗口被改了"留余地（0.001 cm⁻¹ 在 4000 cm⁻¹ 轴上都是肉眼可辨的）。
                    got = (float(span.get_x()), float(span.get_x() + span.get_width()))
                    self.assertAlmostEqual(got[0], lo, delta=1e-9,
                                           msg=f"{scope} 带位窗口 {bid} 的下界被改了：{got}")
                    self.assertAlmostEqual(got[1], hi, delta=1e-9,
                                           msg=f"{scope} 带位窗口 {bid} 的上界被改了：{got}")
                    label = reg.get(module.gid(scope, "band_label", bid))
                    self.assertIsNotNone(label, f"{scope} 带位文本 {bid} 没画出来")
                    self.assertEqual(label.get_text(), texts[bid], "受保护的科学文本被改了")
                    self.assertEqual(float(label.get_position()[0]), centers[bid],
                                     f"{scope} 带位文本 {bid} 没对在带位中心上")
            finally:
                plt.close(fig)

    def test_compare_panels_keep_the_declared_processing_chain(self):
        """对照图是**两格**：上格画原始数组、下格画声明的滑动平均。不是"看起来像"。

        两格在同一张 Figure 里：每格按自己作用域的声明取曲线，兄弟格一起核对
        （串味 = 上格画了平滑后的数组、下格画了原始数组，那正是这里要挡住的）。
        """
        module = load("native_ftir")
        science = module.load_science()
        raw = fixture_data.ftir_curves()[0][1]
        processed = fixture_data.ftir_processed_curves()[0][1]
        self.assertFalse(np.array_equal(raw, processed), "对照的两条曲线不该逐字节相同")
        panels = tuple(module.COMPARE_SCOPES)
        self.assertEqual(len(panels), 2, "对照图应当是两格（两个作用域）")
        other = next(scope for scope in panels if scope != module.COMPARE_TOP_SCOPE)

        fig, reg, _ = build(module, module.COMPARE_TOP_SCOPE)
        try:
            for panel in panels:
                self.assertTrue(declared(module, panel, type_name="Axes"),
                                f"{panel} 没声明坐标框")
                checked = 0
                for sid in module.CURVE_IDS:
                    gid = module.gid(panel, "curve", sid)
                    if gid not in declared(module, panel, type_name="Line2D"):
                        self.assertIsNone(reg.get(gid),
                                          f"{panel} 没声明曲线 {sid}，却把它画出来了")
                        continue
                    art = reg.get(gid)
                    self.assertIsNotNone(art, f"{panel} 声明了曲线 {sid}，却没画出来")
                    np.testing.assert_array_equal(
                        np.asarray(art.get_ydata(), float),
                        module._expected_series(science, panel, sid)[1],
                        f"{panel} 的曲线 {sid} 画的不是它声明的那条序列")
                    checked += 1
                self.assertGreater(checked, 0, f"{panel} 一条曲线都没声明")
            # 两格各自画对了：raw 格 = 原始，processed 格 = 处理后（兄弟格没被串味）。
            sid = module.CURVE_IDS[0]
            np.testing.assert_array_equal(
                np.asarray(reg.get(module.gid(module.COMPARE_TOP_SCOPE, "curve", sid)).get_ydata(), float),
                raw, "上格画的不是原始数组")
            np.testing.assert_array_equal(
                np.asarray(reg.get(module.gid(other, "curve", sid)).get_ydata(), float),
                processed, "下格画的不是声明的滑动平均")
        finally:
            plt.close(fig)

    def test_layout_is_dpi_independent_in_millimetres(self):
        module = load("native_ftir")
        scope = "main"
        base_cfg = module.load_config()
        moved_cfg = copy.deepcopy(base_cfg)
        moved_cfg["shifts_mm"]["main"]["b"] = 3.0
        measured = {}
        for dpi in (96, 600):
            base_cfg["render_dpi"] = dpi
            moved_cfg["render_dpi"] = dpi
            base_fig, base_reg, _ = build(module, scope, config=base_cfg)
            moved_fig, moved_reg, _ = build(module, scope, config=moved_cfg)
            gid = module.gid(scope, "curve", "b")
            before = vertex_mm(base_fig, base_reg.get(gid), 0)
            after = vertex_mm(moved_fig, moved_reg.get(gid), 0)
            measured[dpi] = after[1] - before[1]
            self.assertEqual(figure_digest(base_fig), figure_digest(moved_fig),
                             f"dpi={dpi} 时位移改动了受保护内容")
            plt.close(base_fig)
            plt.close(moved_fig)
        self.assertAlmostEqual(measured[96], 3.0, delta=TOL_VECTOR_MM)
        self.assertAlmostEqual(measured[96], measured[600], delta=TOL_VECTOR_MM)


class NmrInvarianceTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_peak_guides_sit_on_the_protected_ppm_and_never_move_in_data_space(self):
        """峰位引导线 = 受保护 ppm 上的两根端点；积分窗口 = 受保护的 ppm 区间。

        引导线按**声明的节点**取（声明里 Line2D 只有谱线 + 四条峰位引导线）：
        不去数"图纸里有多少条两点折线"，那会把装饰几何也算成峰位。
        """
        module = load("native_nmr")
        keys = tuple(module.PEAK_KEYS)
        peaks = fixture_data.nmr_peak_ppm()
        windows = fixture_data.nmr_windows_ppm()
        self.assertEqual(len(keys), len(peaks))
        for scope in module.SCOPES:
            science = module.load_science()
            fig, reg, _ = build(module, scope)
            try:
                expected_lines = {module.gid(scope, "spectrum")}
                expected_lines.update(module.gid(scope, "peak_guide", key) for key in keys)
                self.assertEqual(set(declared(module, scope, type_name="Line2D")), expected_lines,
                                 f"{scope} 声明的折线不是「谱线 + 峰位引导线」")
                drawn = set(select(fig, reg, type_name="Line2D"))
                self.assertTrue(drawn <= expected_lines,
                                f"{scope} 画了没声明的折线：{sorted(drawn - expected_lines)}")
                for key, ppm, (lo, hi) in zip(keys, peaks, windows):
                    guide = reg.get(module.gid(scope, "peak_guide", key))
                    self.assertIsNotNone(guide, f"{scope} 峰位引导线 {key} 没画出来")
                    x = np.asarray(guide.get_xdata(), float)
                    y = np.asarray(guide.get_ydata(), float)
                    self.assertEqual(x.shape, (2,), f"{scope} 峰位引导线 {key} 不是两个端点")
                    self.assertEqual((float(x[0]), float(x[1])), (ppm, ppm),
                                     f"{scope} 峰位引导线 {key} 不在受保护的峰位上")
                    self.assertAlmostEqual(float(y[1]), science["peak_heights"][key], delta=1e-12,
                                           msg=f"{scope} 峰位引导线 {key} 没拉到受保护的峰高")
                    span = reg.get(module.gid(scope, "peak_window", key))
                    self.assertIsNotNone(span, f"{scope} 积分窗口 {key} 没画出来")
                    np.testing.assert_allclose(module._span_ppm_limits(span), (lo, hi),
                                               rtol=0.0, atol=1e-9,
                                               err_msg=f"{scope} 积分窗口 {key} 不是受保护的 ppm 区间")
            finally:
                plt.close(fig)

    def test_assignments_text_is_protected(self):
        """归属文本逐条按声明的 gid 核对：文本是受保护的科学内容，排版可以挪、不可以改字。"""
        module = load("native_nmr")
        assignments = fixture_data.nmr_assignments()
        for scope in module.SCOPES:
            fig, reg, _ = build(module, scope)
            try:
                protected = declared(module, scope, type_name="Text",
                                     science_policy="LOCKED_SCIENCE")
                for key, text in assignments.items():
                    gid = module.gid(scope, "peak_label", key)
                    self.assertIn(gid, protected, f"{gid} 没被声明成受保护文本")
                    label = reg.get(gid)
                    self.assertIsNotNone(label, f"{scope} 归属标签 {key} 没画出来")
                    self.assertEqual(label.get_text(), text, "受保护的归属文本被改了")
            finally:
                plt.close(fig)

    def test_display_shifts_move_guides_and_labels_without_touching_data(self):
        """逐峰毫米位移只动它**声明**的那组对象（引导线 + 窗口 + 标签），别人不动。"""
        module = load("native_nmr")
        scope = module.SCOPES[0]
        base_cfg = module.load_config()
        cfg = copy.deepcopy(base_cfg)
        shifts = cfg[module.SHIFT_KEY]
        ppm_key = next(iter(shifts[scope]))
        delta = 2.5
        shifts[scope][ppm_key] = delta

        affected = set(params_of_path(module, scope,
                                      [module.SHIFT_KEY, scope, ppm_key])["objects"])
        self.assertIn(module.gid(scope, "peak_guide", ppm_key), affected,
                      "声明里没把这条位移接到引导线上，这个测试就测不到东西")
        self.assertIn(module.gid(scope, "peak_label", ppm_key), affected)

        base_fig, base_reg, _ = build(module, scope, config=base_cfg)
        moved_fig, moved_reg, _ = build(module, scope, config=cfg)
        try:
            self.assertEqual(figure_digest(base_fig), figure_digest(moved_fig),
                             "纯显示位移改动了受保护内容")
            for kind, measure in (("peak_guide", lambda fig, art: vertex_mm(fig, art, 0)),
                                  ("peak_label", text_anchor_mm)):
                for key in module.PEAK_KEYS:
                    gid = module.gid(scope, kind, key)
                    want = delta if gid in affected else 0.0
                    before = measure(base_fig, base_reg.get(gid))
                    after = measure(moved_fig, moved_reg.get(gid))
                    self.assertAlmostEqual(after[1] - before[1], want, delta=TOL_VECTOR_MM,
                                           msg=f"{gid} 动了 {after[1] - before[1]} mm，声明是 {want} mm")
                    self.assertAlmostEqual(after[0] - before[0], 0.0, delta=TOL_VECTOR_MM)
        finally:
            plt.close(base_fig)
            plt.close(moved_fig)


class PanelInvarianceTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_image_pixels_are_the_seeded_arrays(self):
        module = load("native_panels")
        for scope in module.SCOPES:
            fig, reg, _ = build(module, scope)
            try:
                images = select(fig, reg, type_name="AxesImage")
                self.assertEqual(len(images), len(fixture_data.PANEL_IDS))
                for gid in images:
                    art = reg.get(gid)
                    pid = gid.rsplit(".", 1)[-1]
                    source = fixture_data.micrograph(pid)
                    self.assertFalse(source.flags.writeable, "受保护像素数组不许可写")
                    np.testing.assert_array_equal(np.asarray(art.get_array()), source)
                    self.assertEqual(digest(art.get_array()), digest(source))
            finally:
                plt.close(fig)

    def test_crop_aspect_and_scale_bar_keep_their_meaning(self):
        module = load("native_panels")
        for scope in module.SCOPES:
            fig, reg, cfg = build(module, scope)
            try:
                images = select(fig, reg, type_name="AxesImage")
                bars = select(fig, reg, type_name="Line2D", points=2,
                              science_policy="LAYOUT", policy_of=policy_map(module, scope))
                self.assertTrue(bars, "比例尺（LAYOUT 折线）没找到")
                for gid in images:
                    art = reg.get(gid)
                    pid = gid.rsplit(".", 1)[-1]
                    field_um = fixture_data.panel_field_width_um(pid)
                    height_um = field_um * fixture_data.PANEL_SHAPE[0] / fixture_data.PANEL_SHAPE[1]
                    np.testing.assert_allclose(np.asarray(art.get_extent(), float),
                                               (0.0, field_um, height_um, 0.0), atol=1e-9)
                    # 裁切语义：显示的 µm/mm 在两个方向必须相同（没有被拉伸）。
                    ax = art.axes
                    x0, y0, w_mm, h_mm = envelope_mm(fig, ax)
                    self.assertAlmostEqual(w_mm / field_um, h_mm / height_um,
                                           delta=1e-6, msg=f"{pid} 面板把图拉变形了")
                for gid in bars:
                    art = reg.get(gid)
                    pid = gid.rsplit(".", 1)[-1]
                    start = vertex_mm(fig, art, 0)
                    end = vertex_mm(fig, art, 1)
                    length_mm = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
                    expected_mm = (fixture_data.SCALE_BAR_UM / fixture_data.panel_field_width_um(pid)
                                   * cfg["panel_w_mm"])
                    self.assertAlmostEqual(length_mm, expected_mm, delta=TOL_VECTOR_MM,
                                           msg=f"{pid} 比例尺长度 {length_mm} mm ≠ {expected_mm} mm")
            finally:
                plt.close(fig)

    def test_translating_panels_preserves_pixel_bytes(self):
        """右列平移 2.0 mm：原图数组逐字节不变，面板大小与科学显示窗口不变。

        画布同步加宽 2 mm；屏幕重采样不属于原图数组的字节一致性承诺。
        """
        module = load("native_panels")
        scope = "main"
        base_cfg = module.load_config()
        base_cfg["render_dpi"] = PIXEL_DPI
        moved_cfg = copy.deepcopy(base_cfg)
        moved_cfg["gap_x_mm"] = base_cfg["gap_x_mm"] + 2.0
        moved_cfg["canvas_w_mm"] = base_cfg["canvas_w_mm"] + 2.0

        base_fig, base_reg, _ = build(module, scope, config=base_cfg)
        moved_fig, moved_reg, _ = build(module, scope, config=moved_cfg)
        try:
            base_axes = {base_reg.get(g).get_gid(): base_reg.get(g)
                         for g in select(base_fig, base_reg, type_name="Axes")}
            moved_axes = {moved_reg.get(g).get_gid(): moved_reg.get(g)
                          for g in select(moved_fig, moved_reg, type_name="Axes")}
            self.assertEqual(set(base_axes), set(declared(module, scope, type_name="Axes")),
                             "画出来的坐标框不等于声明的面板身份")
            self.assertEqual(sorted(moved_axes), sorted(base_axes))
            for gid, base_ax in base_axes.items():
                pid = next(p for p in fixture_data.PANEL_IDS
                           if module.gid(scope, "panel", p) == gid)
                # 声明里的列：右列（col=1）跟着 gap_x_mm 走 2 mm = 20 px，左列一个像素都不动。
                want_px = 20 if module.PANEL_GRID[pid][0] else 0
                moved_ax = moved_axes[gid]
                x0, y0, w_mm, h_mm = envelope_mm(base_fig, base_ax)
                x1, y1, w1, h1 = envelope_mm(moved_fig, moved_ax)
                dx_px = (x1 - x0) / mm_per_px(base_fig)
                with self.subTest(panel=gid):
                    self.assertAlmostEqual(dx_px, want_px, delta=1e-6,
                                           msg=f"{gid} 位移 {dx_px} px，声明是 {want_px} px")
                    self.assertAlmostEqual(w1, w_mm, delta=TOL_ENVELOPE_MM)
                    self.assertAlmostEqual(h1, h_mm, delta=TOL_ENVELOPE_MM)
                    base_image = base_reg.get(module.gid(scope, "image", pid))
                    moved_image = moved_reg.get(module.gid(scope, "image", pid))
                    np.testing.assert_array_equal(base_image.get_array(), moved_image.get_array())
                    self.assertEqual(tuple(base_image.get_extent()), tuple(moved_image.get_extent()))
                    self.assertEqual(tuple(base_ax.get_xlim()), tuple(moved_ax.get_xlim()))
                    self.assertEqual(tuple(base_ax.get_ylim()), tuple(moved_ax.get_ylim()))
        finally:
            plt.close(base_fig)
            plt.close(moved_fig)

    def test_dpi_changes_do_not_change_pixels_or_geometry(self):
        module = load("native_panels")
        scope = "main"
        digests = {}
        widths = {}
        for dpi in (96, 600):
            cfg = module.load_config()
            cfg["render_dpi"] = dpi
            fig, reg, _ = build(module, scope, config=cfg)
            try:
                digests[dpi] = [digest(reg.get(g).get_array()) for g in select(fig, reg, type_name="AxesImage")]
                widths[dpi] = sorted(round(envelope_mm(fig, reg.get(g))[2], 9)
                                     for g in select(fig, reg, type_name="Axes"))
            finally:
                plt.close(fig)
        self.assertEqual(digests[96], digests[600], "像素字节随 dpi 变了")
        self.assertEqual(widths[96], widths[600], "面板毫米宽度随 dpi 变了")




class MixedInvarianceTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_curve_and_image_survive_a_layout_change(self):
        module = load("native_mixed")
        scope = "main"
        base_cfg = module.load_config()
        moved_cfg = copy.deepcopy(base_cfg)
        moved_cfg["panel_gap_mm"] = base_cfg["panel_gap_mm"] + 1.0
        moved_cfg[module.CURVE_LIFT_KEY] = 1.5

        base_fig, base_reg, _ = build(module, scope, config=base_cfg)
        moved_fig, moved_reg, _ = build(module, scope, config=moved_cfg)
        try:
            self.assertEqual(figure_digest(base_fig), figure_digest(moved_fig),
                             "混排图排版后受保护内容变了")
            images = select(base_fig, base_reg, type_name="AxesImage")
            self.assertTrue(images, "混排图里没有显微图")
            for gid in images:
                np.testing.assert_array_equal(np.asarray(moved_reg.get(gid).get_array()),
                                              np.asarray(base_reg.get(gid).get_array()))
        finally:
            plt.close(base_fig)
            plt.close(moved_fig)


class NegativeFixtureTruthTest(unittest.TestCase):
    """缺陷夹具的缺陷必须是**可测的**：不是文档里写着的、实际却没事。"""

    def tearDown(self):
        plt.close("all")

    def test_unused_parameter_really_has_no_effect(self):
        """声明成"会移动注释"的那条纯位移，扰动它必须**真的什么都动不了**。

        量的是**渲染出来的对象**（真实 Artist 的包围盒/位置/数据），不是契约里的
        自我描述：契约自称有接线，可它没接上。
        """
        module = load("native_negatives")
        scope = module.SCOPES[0]
        note_gid = module.gid(scope, "note")
        unused = [record for record in module.layout_contract(scope)["parameters"]
                  if record["mutability"] == "EDITABLE" and record["operation"] == "translate"
                  and record["objects"] == [note_gid]]
        self.assertEqual(len(unused), 1,
                         f"契约里应当正好有一条声明会移动注释 {note_gid} 的纯位移")
        path = list(unused[0]["path"])

        base_cfg = module.load_config()
        cfg = copy.deepcopy(base_cfg)
        delta = 3.0
        set_at(cfg, path, get_at(base_cfg, path) + delta)

        base_fig, base_reg, _ = build(module, scope, config=base_cfg)
        moved_fig, moved_reg, _ = build(module, scope, config=cfg)
        try:
            self.assertEqual(rendered_geometry(base_fig, base_reg),
                             rendered_geometry(moved_fig, moved_reg),
                             f"声明为未接线的参数 {path} 居然有渲染效果")
        finally:
            plt.close(base_fig)
            plt.close(moved_fig)

    def test_declared_binding_differs_from_the_real_one(self):
        """契约说 A 管 xlabel，真正管它的是 B：用**声明的路径**做真实验，不比对常量。

        三次构建、三次量真实字号：基线 / 扰动声明路径 / 扰动真实路径。声明路径动了
        字号不动 = 契约在骗人；真实路径动了 = 受影响集合比声明的多一个对象。
        """
        module = load("native_negatives")
        scope = module.SCOPES[0]
        gid = module.XLABEL_GID(scope)
        declared_param = params_of_path(module, scope, [module.DECLARED_XLABEL_PARAM])
        real_param = params_of_path(module, scope, [module.REAL_FONT_PARAM])
        self.assertIn(gid, declared_param["objects"],
                      f"契约没把 {gid} 声明在 {module.DECLARED_XLABEL_PARAM} 下，这个缺陷测试就没意义")
        self.assertNotIn(gid, real_param["objects"],
                         f"契约把 {gid} 也声明在 {module.REAL_FONT_PARAM} 下，那就不是错误绑定")

        base_cfg = module.load_config()
        bump = 1.5
        declared_cfg = copy.deepcopy(base_cfg)
        real_cfg = copy.deepcopy(base_cfg)
        set_at(declared_cfg, declared_param["path"],
               get_at(base_cfg, declared_param["path"]) + bump)
        set_at(real_cfg, real_param["path"], get_at(base_cfg, real_param["path"]) + bump)

        base = self._xlabel_fontsize(module, scope, base_cfg, gid)
        declared = self._xlabel_fontsize(module, scope, declared_cfg, gid)
        real = self._xlabel_fontsize(module, scope, real_cfg, gid)
        self.assertAlmostEqual(declared, base, delta=1e-9,
                               msg=f"契约说 {module.DECLARED_XLABEL_PARAM} 管 {gid}，扰动它却真的动了字号")
        self.assertNotAlmostEqual(real, base, delta=1e-9,
                                  msg=f"{gid} 的实际控制路径不是契约声明的那条，也没被真实路径改变")

    @staticmethod
    def _xlabel_fontsize(module, scope: str, config: dict, gid: str) -> float:
        fig, reg = module.build_scene(module.load_science(), config, scope)
        try:
            artist = reg.get(gid)
            assert artist is not None, f"找不到 {gid}"
            return float(artist.get_fontsize())
        finally:
            plt.close(fig)

    def test_hidden_science_change_is_reported_by_the_fixture_selfcheck(self):
        """隐蔽的科学改动（0.05% 改写）只有科学自检抓得到；对照作用域必须干净。"""
        module = load("native_negatives")
        defect = declared_defect(module, "HIDDEN_SCIENCE_CHANGE")
        scope = defect["scope"]
        other = next(s for s in module.SCOPES if s != scope)
        science = module.load_science()
        for target, expected in ((scope, True), (other, False)):
            fig, reg = module.build_scene(science, module.load_config(), target)
            try:
                problems = module.science_selfcheck(science, fig=fig)
                self.assertEqual(module.science_selfcheck(science, fig=fig), problems,
                                 "科学自检本身不是确定性的")
                if expected:
                    self.assertTrue(any(defect["rule_id"] in p for p in problems),
                                    f"{target} 的隐蔽科学改动（{defect['kind']}）没被自检抓到：{problems}")
                else:
                    self.assertEqual(problems, [],
                                     f"{target} 画的是受保护数组，科学自检不该报：{problems}")
            finally:
                plt.close(fig)

    def test_collision_scope_has_real_qa_blockers(self):
        """故意碰撞的那个作用域必须有 ≥2 条真实阻断项；对照作用域几何干净。"""
        from figpact import qa

        module = load("native_negatives")
        defect = declared_defect(module, "TEXT_COLLISION")
        scope = defect["scope"]
        other = next(s for s in module.SCOPES if s != scope)
        fig, _ = module.build_scene(module.load_science(), module.load_config(), scope)
        try:
            blockers = qa.blocking_problems(fig)
            self.assertGreaterEqual(len(blockers), 2, f"故意重叠的标签没被 QA 抓到：{blockers}")
            self.assertGreaterEqual(len({qa.diagnostic_key_of(b) for b in blockers}), 2,
                                    "两条真实缺陷被压成了同一个诊断 key")
        finally:
            plt.close(fig)
        # 另一个作用域不许有几何阻断项（它的缺陷在科学面，不在排版面）。
        clean, _reg = module.build_scene(module.load_science(), module.load_config(), other)
        try:
            self.assertEqual(qa.blocking_problems(clean), [])
        finally:
            plt.close(clean)


class FigureImageProtectionTest(unittest.TestCase):
    """`fig.figimage` 的像素 / origin / 显示范围受保护，图幅位置是版面。

    合成图（确定性整数数组，不用任何生产数据）：一张 3×4 的图幅图像，注册成 `figimg`，
    可以按调用方给的节点声明**错标**成 LAYOUT/guide，也可以根本不注册。断言打在
    `capture_science` / `compare_science` 的返回上——那就是会话真正消费的接口。
    """

    PIXELS = ((0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11))

    def tearDown(self):
        plt.close("all")

    def capture(self, *, pixels=None, clim=None, origin="upper", xo=20, yo=20, ox=None,
                gid="figimg", node=None):
        """一张只有图幅图像的合成图 → 它的科学指纹。"""
        from figpact import GidRegistry
        from figpact import science as science_mod

        fig = plt.figure(figsize=(2, 2), dpi=100)
        try:
            image = fig.figimage(np.asarray(self.PIXELS if pixels is None else pixels,
                                            dtype=float),
                                 xo=xo, yo=yo, origin=origin)
            if clim is not None:
                image.set_clim(*clim)
            if ox is not None:
                image.ox = ox
            registry = GidRegistry()
            if gid is not None:
                registry.register(image, gid)
            declarations = {"nodes": {gid: dict(node)}} if node else {"nodes": {}}
            return science_mod.capture_science(fig, registry, declarations=declarations)
        finally:
            plt.close(fig)

    @staticmethod
    def changed(before, after):
        from figpact import science as science_mod

        return science_mod.compare_science(before, after)

    def test_figure_image_pixels_are_protected_even_when_tagged_layout_or_guide(self):
        """错标成 LAYOUT（甚至 guide）的图幅图像，像素照样是科学载荷。"""
        tampered = ((0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 12))
        baseline = self.capture()
        self.assertIn("figimg", baseline["objects"], "图幅图像像素必须进保护载荷")
        self.assertEqual(self.changed(baseline, self.capture()), [], "同一份真图必须指纹一致")
        for node in (None, {"science_policy": "LAYOUT"},
                     {"science_policy": "LAYOUT", "type": "guide"}):
            labelled = self.capture(node=node)
            self.assertEqual(labelled["digest"], baseline["digest"],
                             f"声明怎么标只该影响豁免，不该改真实指纹：{node}")
            diff = self.changed(labelled, self.capture(pixels=tampered, node=node))
            self.assertTrue(diff, f"错标成 {node} 的图幅图像像素篡改必须被拦住")
            self.assertEqual(diff[0]["rule_id"], "SCIENCE_CHANGED")
            self.assertIn("figimg", diff[0]["object_ids"])

    def test_figure_image_origin_clim_and_unregistered_pixels_are_protected(self):
        """origin（数组朝向）与 clim（显示范围）是图像的科学解释；没有 gid 也受保护。"""
        baseline = self.capture()
        flipped = self.changed(baseline, self.capture(origin="lower"))
        self.assertTrue(flipped and "figimg" in flipped[0]["object_ids"],
                        "把 origin 翻过来改变了像素的科学解释，必须被拦住")
        rescaled = self.changed(baseline, self.capture(clim=(2.0, 9.0)))
        self.assertTrue(rescaled and "figimg" in rescaled[0]["object_ids"],
                        "显示范围（clim）变化必须被拦住")
        unnamed = self.capture(gid=None)
        self.assertIn("figure.unregistered.image.0", unnamed["objects"],
                      "没有 gid 的图幅图像照样受保护，按图幅序号记名")
        unregistered = self.changed(unnamed, self.capture(gid=None, pixels=(
            (0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 12))))
        self.assertTrue(unregistered, "未注册图幅图像的像素篡改必须被拦住")
        self.assertIn("figure.unregistered.image.0", unregistered[0]["object_ids"])

    def test_figure_image_placement_is_layout_and_stays_out_of_the_payload(self):
        """换位置（重建时给别的 xo/yo，或直接改 ox）是版面：科学指纹必须不变。"""
        baseline = self.capture()
        self.assertEqual(self.capture(xo=120, yo=90)["digest"], baseline["digest"],
                         "同一张图换个图幅位置，内容指纹必须不变")
        moved = self.capture(ox=200)
        self.assertEqual(moved["digest"], baseline["digest"],
                         "移动图幅图像是版面动作，不许进科学载荷")
        self.assertEqual(self.changed(baseline, moved), [],
                         "版面位移不是受保护载荷的差异")


if __name__ == "__main__":
    unittest.main()
