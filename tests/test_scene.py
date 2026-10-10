"""快照行为测试：节点树、毫米几何、锚点、可编辑路径、未注册可见图元与关系映射。

构造都是确定性的小图（毫米画布 + 固定 dpi），期望值在测试里独立算出来，
不复用被测实现的换算过程。
"""
import json
import types
import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.artist
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

from figpact import scene
from figpact.registry import GidRegistry
from figpact.units import MM_PER_INCH

W_MM, H_MM = 120.0, 60.0
DPI = 100


def mm_canvas(axes=1, **kwargs):
    fig = plt.figure(figsize=(W_MM / MM_PER_INCH, H_MM / MM_PER_INCH), dpi=DPI, **kwargs)
    return fig, fig.subplots(1, axes)


def display_mm(fig, ax, x, y):
    """数据坐标 → 画布毫米（左下角原点），测试自己算。"""
    px = ax.transData.transform((x, y))
    return float(px[0]) * MM_PER_INCH / fig.dpi, float(px[1]) * MM_PER_INCH / fig.dpi


class SnapshotNodeTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_registered_axes_have_one_identity_and_own_inferred_children(self):
        fig, axes = mm_canvas(axes=2)
        reg = GidRegistry(scope="main")
        reg.register(axes[0], "fig.main.panel.A")
        first, = axes[0].plot([0, 1], [0, 1])
        second, = axes[1].plot([0, 1], [1, 0])
        reg.register(first, "fig.main.curve.A")
        reg.register(second, "fig.main.curve.B")

        snap = scene.snapshot(fig, reg, scope="main")
        nodes = {n["id"]: n for n in snap["nodes"]}
        panels = scene.inspect(snap, type="panel")["nodes"]
        self.assertEqual(len(panels), len(axes))
        self.assertEqual(nodes["fig.main.curve.A"]["parent"], "fig.main.panel.A")
        panel_b = nodes[nodes["fig.main.curve.B"]["parent"]]
        self.assertEqual(panel_b["type"], "panel")
        self.assertNotEqual(panel_b["id"], "fig.main.panel.A")
        for ax, panel in ((axes[0], nodes["fig.main.panel.A"]), (axes[1], panel_b)):
            expected = np.asarray(ax.get_window_extent(fig.canvas.get_renderer()).extents)
            np.testing.assert_allclose(panel["bounds_mm"], expected * 25.4 / fig.dpi,
                                       atol=1e-10, rtol=0)
            self.assertNotEqual(panel["id"], panel["parent"])

    def test_registered_nodes_expose_parent_scope_anchors_and_paths(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 5, 10], [0, 2, 0])
        reg.register(line, "fig.main.curve.a", params=["line_width"],
                     controlled_by=[["scalars", "line_width"]])
        label = ax.text(1.0, 8.0, "peak", fontsize=8)
        reg.register(label, "fig.main.label.peak")
        contract = {
            "nodes": {"fig.main.curve.a": {"parent": "root", "editable": True,
                                           "science_policy": "LOCKED_SCIENCE"}},
            "parameters": [{"key": "label_font_pt", "path": ["scalars", "label_font_pt"],
                            "mutability": "EDITABLE", "objects": ["fig.main.label.peak"]}],
            "groups": [{"id": "root", "parent": None,
                        "members": ["fig.main.curve.a", "fig.main.label.peak"]}],
        }
        snap = scene.snapshot(fig, reg, scope="main", revision="rev-1", contract=contract)
        nodes = {n["id"]: n for n in snap["nodes"]}
        curve = nodes["fig.main.curve.a"]
        self.assertTrue(curve["registered"])
        self.assertEqual(curve["type"], "curve")
        self.assertEqual(curve["artist_type"], "Line2D")
        self.assertEqual(curve["scope"], "main")
        self.assertEqual(curve["parent"], "root")
        self.assertEqual(curve["science_policy"], "LOCKED_SCIENCE")
        self.assertEqual(curve["controlled_by"], [["scalars", "line_width"]])
        self.assertEqual(curve["path_source"], "registry")

        exp_x, exp_y = display_mm(fig, ax, 10.0, 0.0)
        top = display_mm(fig, ax, 5.0, 2.0)[1]
        self.assertAlmostEqual(curve["bounds_mm"][2], exp_x, places=6)
        self.assertAlmostEqual(curve["anchors"]["left"], curve["bounds_mm"][0], places=9)
        self.assertAlmostEqual(curve["anchors"]["center_x"],
                               (curve["bounds_mm"][0] + curve["bounds_mm"][2]) / 2.0, places=9)
        self.assertAlmostEqual(curve["anchors"]["bottom"], curve["bounds_mm"][1], places=9)
        self.assertGreater(curve["bounds_mm"][3], curve["bounds_mm"][1])
        self.assertAlmostEqual(curve["bounds_mm"][3], top, delta=0.5)   # 顶点 + 半线宽
        self.assertAlmostEqual(curve["bounds_mm"][1], exp_y, delta=0.5)
        self.assertEqual(len(curve["polyline_mm"]), 3)
        self.assertTrue(curve["precise"])

        peak = nodes["fig.main.label.peak"]
        self.assertTrue(peak["is_text"])
        self.assertFalse(peak["precise"])
        self.assertEqual(peak["rotation_deg"], 0.0)
        self.assertEqual(peak["text"], "peak")
        self.assertEqual(peak["controlled_by"], [["scalars", "label_font_pt"]])
        self.assertEqual(peak["path_source"], "contract")
        self.assertTrue(peak["editable"])
        self.assertEqual(peak["editable_paths"], [["scalars", "label_font_pt"]])
        self.assertIn("baseline", peak["anchors"])
        self.assertEqual(peak["baseline_source"], "font_metrics_descent")

        self.assertEqual(snap["unit"], "mm")
        self.assertEqual(snap["coordinate_reference"], "canvas_bottom_left")
        self.assertEqual(snap["scope"], "main")
        self.assertEqual(snap["revision"], "rev-1")
        self.assertEqual(snap["measurement"]["dpi"], float(DPI))
        self.assertTrue(snap["measurement"]["renderer_available"])
        json.dumps(snap)

    def test_undeclared_nodes_fail_closed_without_contract(self):
        fig, ax = mm_canvas()
        reg = GidRegistry()
        line, = ax.plot([0, 1], [0, 1])
        reg.register(line, "fig.main.curve.a")
        dotted, = ax.plot([0, 1], [1, 2])
        reg.register(dotted, "fig.main.curve.b", params=["shifts_mm.main.ha"])
        ax.set_xlabel("Wavenumber")
        reg.register(ax.xaxis.label, "fig.main.xlabel")
        snap = scene.snapshot(fig, reg, scope="main")
        for node in snap["nodes"]:
            if not node["registered"]:
                continue
            self.assertFalse(node["editable"])
            self.assertEqual(node["editable_paths"], [])
            self.assertEqual(node["science_policy"], "UNCLASSIFIED")
            self.assertEqual(node["controlled_by"], [])
        nodes = {n["id"]: n for n in snap["nodes"]}
        # 参数名照旧保留给 GUI，但绝不是精确路径，也不给可编辑标记
        self.assertEqual(nodes["fig.main.curve.b"]["params"], ["shifts_mm.main.ha"])
        self.assertEqual(nodes["fig.main.curve.b"]["path_source"], "unresolved_params")
        self.assertEqual(nodes["fig.main.curve.b"]["unresolved_bindings"], ["shifts_mm.main.ha"])
        self.assertEqual(snap["parameter_index"], [])
        unresolved = [d for d in snap["diagnostics"] if d["kind"] == "UNRESOLVED_PARAMETER_BINDING"]
        self.assertEqual([d["ids"] for d in unresolved], [["fig.main.curve.b"]])

    def test_unregistered_collections_are_visible_objects_not_omitted(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 1], [0, 1])
        reg.register(line, "fig.main.curve.a")
        ax.errorbar([0, 1], [0, 1], yerr=[0.1, 0.1], fmt="none")
        ax.add_collection(LineCollection([np.array([[0, 0], [1, 1]])], colors="black"))
        snap = scene.snapshot(fig, reg, scope="main")
        orphan = [n for n in snap["nodes"]
                  if not n["registered"] and n["id"].startswith("main::unregistered")]
        self.assertTrue(any(n["type"] == "collection" and n["artist_type"] == "LineCollection"
                            for n in orphan),
                        [(n["type"], n["artist_type"]) for n in orphan])
        self.assertTrue(all(n["descriptor"] for n in orphan))
        flagged = [d for d in snap["diagnostics"] if d["kind"] == "UNREGISTERED_VISIBLE"]
        self.assertEqual(len(flagged), len(orphan))
        # 未注册集合的显示几何依然逐段给出，不能因为没登记就退化成空/0
        collections = [n for n in orphan if n["artist_type"] == "LineCollection"]
        self.assertEqual(len(collections), 2)
        for node in collections:
            self.assertEqual(node["collection_geometry"], "MEASURED")
            self.assertGreaterEqual(len(node["polylines_mm"]), 1)
            self.assertIsNone(node["polyline_mm"])
        # errorbar 的 yerr 竖棒是一根 LineCollection、两个独立线段
        self.assertEqual(sorted(len(n["polylines_mm"]) for n in collections), [1, 2])
        # 同一批孤儿集合在 inventory 里也必须出现，不能只在 scene 里可见
        from figpact.inventory import inventory
        inv = inventory(fig, reg)
        self.assertTrue(any("LineCollection" in desc for desc in inv["unregistered"]),
                        inv["unregistered"])

    def test_tree_has_canvas_root_and_one_panel_per_axes(self):
        fig, axes = mm_canvas(axes=2)
        reg = GidRegistry(scope="compare")
        for index, ax in enumerate(axes):
            line, = ax.plot([0, 1, 2], [0, 1, 0])
            reg.register(line, f"fig.compare.curve.{index}")
        snap = scene.snapshot(fig, reg, scope="compare")
        nodes = {n["id"]: n for n in snap["nodes"]}
        panels = [n for n in snap["nodes"] if n["type"] == "panel"]
        self.assertEqual(len(panels), 2)
        self.assertEqual(nodes["compare::canvas"]["type"], "figure")
        self.assertEqual(nodes["compare::canvas"]["artist_type"], "Figure")
        for panel in panels:
            self.assertEqual(panel["parent"], "compare::canvas")
            self.assertEqual(panel["artist_type"], "Axes")
        for index in range(2):
            self.assertEqual(nodes[f"fig.compare.curve.{index}"]["parent"],
                             f"compare::panel.{index}")
            self.assertEqual(nodes[f"fig.compare.curve.{index}"]["scope"], "compare")
        # 两条曲线都在各自坐标框内：compare 图不该被当成「两个作用域」或越界
        self.assertEqual(snap["containment"]["outside"], [])
        inside = [n["id"] for n in snap["nodes"] if n["type"] == "image"]
        self.assertEqual(inside, [])

    def test_registry_spanning_two_scopes_does_not_misclassify_compare_panels(self):
        """compare 图两格共用一个 registry（真实 FTIR 用法）：按 gid 约定各归各的作用域。"""
        fig, axes = mm_canvas(axes=2)
        reg = GidRegistry()                     # 没有 registry 级 scope 声明
        raw, = axes[0].plot([0, 1], [0, 1])
        proc, = axes[1].plot([0, 1], [1, 2])
        reg.register(raw, "fig2_ftir.compare_raw.curve.sample")
        reg.register(proc, "fig2_ftir.compare_processed.curve.sample")
        snap = scene.snapshot(fig, reg, scope="compare_raw")
        nodes = {n["id"]: n for n in snap["nodes"]}
        self.assertEqual(nodes["fig2_ftir.compare_raw.curve.sample"]["scope"], "compare_raw")
        self.assertEqual(nodes["fig2_ftir.compare_processed.curve.sample"]["scope"], "compare_processed")
        self.assertEqual(snap["out_of_scope"], ["fig2_ftir.compare_processed.curve.sample"])
        self.assertTrue(any(d["kind"] == "OUT_OF_SCOPE_NODE" for d in snap["diagnostics"]))
        self.assertEqual(len([n for n in snap["nodes"] if n["type"] == "panel"]), 2)
        self.assertEqual(snap["containment"]["outside"], [])
        only_raw = scene.inspect(snap, scope="compare_raw")
        self.assertEqual([n["id"] for n in only_raw["nodes"] if n["registered"]],
                         ["fig2_ftir.compare_raw.curve.sample"])

    def test_group_membership_becomes_parent_and_union_envelope(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        first, = ax.plot([0, 1], [0, 0])
        second, = ax.plot([0, 1], [1, 1])
        reg.register(first, "fig.main.curve.a")
        reg.register(second, "fig.main.curve.b")
        contract = {"groups": [{"id": "curves", "parent": None,
                                "members": ["fig.main.curve.a", "fig.main.curve.b"]}]}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        nodes = {n["id"]: n for n in snap["nodes"]}
        group = nodes["curves"]
        self.assertEqual(group["type"], "group")
        self.assertEqual(group["parent"], "main::canvas")
        self.assertEqual(group["envelope_source"], "union_of_members")
        self.assertEqual(nodes["fig.main.curve.a"]["parent"], "curves")
        self.assertAlmostEqual(group["bounds_mm"][1], min(nodes["fig.main.curve.a"]["bounds_mm"][1],
                                                         nodes["fig.main.curve.b"]["bounds_mm"][1]),
                               places=9)
        self.assertGreaterEqual(group["bounds_mm"][3], nodes["fig.main.curve.b"]["bounds_mm"][3])

    def test_curve_nodes_expose_stroke_provenance(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 1], [0, 1], lw=2.0, solid_capstyle="round", solid_joinstyle="round")
        reg.register(line, "fig.main.curve.a")
        snap = scene.snapshot(fig, reg, scope="main")
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.curve.a"][0]
        self.assertAlmostEqual(node["linewidth_pt"], 2.0, places=9)
        self.assertAlmostEqual(node["linewidth_mm"], 2.0 * 25.4 / 72.0, places=9)
        self.assertAlmostEqual(node["stroke_radius_mm"], node["linewidth_mm"] / 2.0, places=12)
        self.assertEqual(node["solid_capstyle"], "round")
        self.assertEqual(node["solid_joinstyle"], "round")
        self.assertEqual(node["polyline_basis"], "centerline")
        # 快照不声称任何物理标定：只声明每个量的来源
        self.assertIs(snap["measurement"]["calibrated"], False)
        self.assertTrue(snap["measurement"]["basis"]["polyline"].startswith(
            "display_transform_of_data"))
        self.assertIn("中心线", snap["measurement"]["basis"]["polyline"])

    def test_node_type_is_semantic_for_every_artist_kind(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 1], [0, 1])
        text = ax.text(0.5, 9.0, "peak")
        image = ax.imshow(np.zeros((4, 4, 3)), extent=[0, 1, 0, 1], aspect="auto")
        patch = plt.Rectangle((2, 2), 1, 1, transform=ax.transData)
        ax.add_patch(patch)
        coll = LineCollection([np.array([[1.0, 1.0], [2.0, 2.0]])], colors="black")
        ax.add_collection(coll)
        legend = ax.legend(["a"])
        expected = {
            "fig.main.curve.a": (line, "curve", "Line2D"),
            "fig.main.label.peak": (text, "text", "Text"),
            "fig.main.image.a": (image, "image", "AxesImage"),
            "fig.main.band.a": (patch, "shape", "Rectangle"),
            "fig.main.bars.a": (coll, "collection", "LineCollection"),
            "fig.main.legend": (legend, "legend", "Legend"),
        }
        for gid, (artist, _, _) in expected.items():
            reg.register(artist, gid)
        snap = scene.snapshot(fig, reg, scope="main")
        nodes = {n["id"]: n for n in snap["nodes"]}
        for gid, (_, kind, artist_type) in expected.items():
            self.assertEqual(nodes[gid]["type"], kind, gid)
            self.assertEqual(nodes[gid]["artist_type"], artist_type, gid)

        # 顶层树：figure → panel（Axes 的实际具体类留在 artist_type）
        canvas = nodes["main::canvas"]
        panel = nodes["main::panel.0"]
        self.assertEqual(canvas["type"], "figure")
        self.assertEqual(canvas["artist_type"], "Figure")
        self.assertEqual(panel["type"], "panel")
        self.assertEqual(panel["artist_type"], "Axes")
        self.assertEqual(panel["parent"], canvas["id"])
        # 面板几何是渲染器实测窗口（测试独立算），不是数据坐标回声
        renderer = fig.canvas.get_renderer()
        extent = ax.get_window_extent(renderer)
        mm_per_px = MM_PER_INCH / renderer.dpi
        self.assertEqual(panel["envelope_source"], "axes_window_extent")
        self.assertAlmostEqual(panel["bounds_mm"][0], extent.x0 * mm_per_px, places=6)
        self.assertAlmostEqual(panel["bounds_mm"][1], extent.y0 * mm_per_px, places=6)
        self.assertAlmostEqual(panel["bounds_mm"][2], extent.x1 * mm_per_px, places=6)
        self.assertAlmostEqual(panel["bounds_mm"][3], extent.y1 * mm_per_px, places=6)

        # inspect 按语义类型过滤真实对象（不是类名别名）
        for kind, id_ in (("curve", "fig.main.curve.a"), ("text", "fig.main.label.peak"),
                          ("image", "fig.main.image.a"), ("shape", "fig.main.band.a"),
                          ("collection", "fig.main.bars.a"), ("legend", "fig.main.legend"),
                          ("panel", "main::panel.0"), ("figure", "main::canvas")):
            self.assertEqual([n["id"] for n in scene.inspect(snap, type=kind)["nodes"]], [id_], kind)

    def test_declared_descriptors_normalize_and_canonical_types_survive(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 1], [0, 1])
        guide, = ax.plot([0, 1], [1, 2])
        # 原生脚本声明的就是 className 描述符（这里用旧参数清单那种带后缀的形式）
        reg.register(line, "fig.main.curve.a", artist_type="Line2D")
        reg.register(guide, "fig.main.guide.a", artist_type="Line2D (Guide)")
        contract = {"nodes": {"fig.main.guide.a": {"type": "guide"}}}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        nodes = {n["id"]: n for n in snap["nodes"]}
        self.assertEqual(nodes["fig.main.curve.a"]["type"], "curve")
        self.assertEqual(nodes["fig.main.curve.a"]["artist_type"], "Line2D")
        # 显式声明的 canonical 作者类型原样保留，不归一、不吞
        self.assertEqual(nodes["fig.main.guide.a"]["type"], "guide")
        self.assertEqual(nodes["fig.main.guide.a"]["artist_type"], "Line2D")
        self.assertEqual([n["id"] for n in scene.inspect(snap, type="guide")["nodes"]],
                         ["fig.main.guide.a"])

    def test_unregistered_custom_artist_is_honest_artist_with_raw_class(self):
        class Ribbon(matplotlib.artist.Artist):
            def draw(self, renderer):
                pass

        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 1], [0, 1])
        reg.register(line, "fig.main.curve.a")
        ax.add_artist(Ribbon())
        snap = scene.snapshot(fig, reg, scope="main")
        orphan = [n for n in snap["nodes"] if n["id"].startswith("main::unregistered")]
        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan[0]["type"], "artist")          # 诚实兜底，不冒充已知类型
        self.assertEqual(orphan[0]["artist_type"], "Ribbon")   # 原始类名不丢
        self.assertFalse(orphan[0]["registered"])
        self.assertTrue(any(d["kind"] == "UNREGISTERED_VISIBLE" and orphan[0]["id"] in d["ids"]
                            for d in snap["diagnostics"]))

    def test_registered_collection_geometry_is_per_segment_in_mm(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        # 两条互不相连的斜线段：任何「连成一条」的实现都会多出一段并不存在的连线
        seg_a = np.array([[1.0, 1.0], [2.0, 3.0]])
        seg_b = np.array([[8.0, 7.0], [9.0, 9.0]])
        coll = LineCollection([seg_a, seg_b], colors="black")
        ax.add_collection(coll)
        reg.register(coll, "fig.main.bars")
        snap = scene.snapshot(fig, reg, scope="main")
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.bars"][0]
        self.assertEqual(node["type"], "collection")
        self.assertEqual(node["artist_type"], "LineCollection")
        self.assertEqual(node["collection_geometry"], "MEASURED")
        self.assertTrue(node["precise"])
        # 绝不合成一条连续折线
        self.assertIsNone(node["polyline_mm"])
        self.assertEqual(node["collection_segments"], 2)
        self.assertEqual(len(node["polylines_mm"]), 2)

        def expected(seg):
            return [list(display_mm(fig, ax, x, y)) for x, y in seg]

        for got, want in zip(node["polylines_mm"], [expected(seg_a), expected(seg_b)]):
            self.assertEqual(len(got), 2)
            for (gx, gy), (wx, wy) in zip(got, want):
                self.assertAlmostEqual(gx, wx, places=6)
                self.assertAlmostEqual(gy, wy, places=6)
        # 两条线段的端点没有互相接上（段 b 起点 != 段 a 终点）
        self.assertNotEqual(node["polylines_mm"][0][1], node["polylines_mm"][1][0])
        # 几何包围盒 = 两段并集，与显示数据一致
        xs = [display_mm(fig, ax, x, y)[0] for x, y in (list(seg_a) + list(seg_b))]
        ys = [display_mm(fig, ax, x, y)[1] for x, y in (list(seg_a) + list(seg_b))]
        gb = node["geometry_bounds_mm"]
        self.assertAlmostEqual(gb[0], min(xs), places=6)
        self.assertAlmostEqual(gb[1], min(ys), places=6)
        self.assertAlmostEqual(gb[2], max(xs), places=6)
        self.assertAlmostEqual(gb[3], max(ys), places=6)
        # 上报的 bounds_mm 就是显示几何的并集（Collection 自带的 window_extent 是空框）
        self.assertTrue(node["measured"])
        self.assertEqual(node["envelope_source"], "collection_display_geometry")
        self.assertEqual(node["bounds_mm"], list(gb))
        self.assertAlmostEqual(node["bounds_mm"][0], min(xs), places=6)
        self.assertAlmostEqual(node["bounds_mm"][3], max(ys), places=6)
        self.assertFalse(any(d["kind"] == "UNMEASURED_GEOMETRY" and "fig.main.bars" in d["ids"]
                             for d in snap["diagnostics"]))

    def test_disconnected_errorbar_bars_never_become_one_polyline(self):
        fig, ax = mm_canvas()
        ax.set_xlim(-0.5, 1.5)
        ax.set_ylim(-1.5, 1.5)
        reg = GidRegistry(scope="main")
        # 两根独立的竖误差棒（x 恒定）＋一条横向折线：连接它们会横跨整幅图
        bars = LineCollection([np.array([[0.0, -1.0], [0.0, 1.0]]),
                               np.array([[1.0, -0.5], [1.0, 0.5]])], colors="black")
        ax.add_collection(bars)
        reg.register(bars, "fig.main.err")
        snap = scene.snapshot(fig, reg, scope="main")
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.err"][0]
        self.assertIsNone(node["polyline_mm"])
        self.assertEqual(len(node["polylines_mm"]), 2)
        for poly in node["polylines_mm"]:
            self.assertEqual(len(poly), 2)
            self.assertAlmostEqual(poly[0][0], poly[1][0], places=6)   # 每根都是竖直的
        # 段间没有桥接：两根棒的 x 各不相同
        self.assertNotAlmostEqual(node["polylines_mm"][0][0][0],
                                  node["polylines_mm"][1][0][0], places=3)

    def test_marker_collection_reports_unsupported_not_fake_polyline(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        reg = GidRegistry(scope="main")
        dots = ax.scatter([0.2, 0.8], [0.3, 0.7])
        reg.register(dots, "fig.main.dots")
        snap = scene.snapshot(fig, reg, scope="main")
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.dots"][0]
        self.assertEqual(node["type"], "collection")
        self.assertEqual(node["artist_type"], "PathCollection")
        self.assertEqual(node["collection_geometry"], "UNSUPPORTED")
        self.assertFalse(node["precise"])
        self.assertIsNone(node["polyline_mm"])
        self.assertIsNone(node["polylines_mm"])
        self.assertTrue(node["collection_geometry_reason"])
        # 包围盒仍然实测（不是 0、不是 None 当有渲染器时）
        self.assertTrue(node["measured"])
        self.assertIsNotNone(node["bounds_mm"])
        kinds = {d["kind"] for d in snap["diagnostics"]}
        self.assertIn("COLLECTION_GEOMETRY_UNSUPPORTED", kinds)

    def test_marker_collection_gets_conservative_visible_envelope(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        dots = ax.scatter([2.0, 8.0], [3.0, 7.0], s=36.0, linewidths=1.0)
        reg.register(dots, "fig.main.dots")
        snap = scene.snapshot(fig, reg, scope="main")
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.dots"][0]
        # 渲染器真会画出来的字形 → 包围盒/锚点是实测的；字形不是中心线几何 → 轮廓仍 UNSUPPORTED
        self.assertTrue(node["measured"])
        self.assertFalse(node["precise"])
        self.assertEqual(node["collection_geometry"], "UNSUPPORTED")
        self.assertIsNone(node["polyline_mm"])
        self.assertIsNone(node["polylines_mm"])            # 绝不把 offset 连成折线
        self.assertEqual(node["envelope_source"],
                         "marker_glyph_bbox_union_plus_half_stroke_clipped")
        self.assertEqual(node["marker_count"], 2)
        self.assertEqual(node["bounds_mm"], node["envelope_mm"])
        x0, y0, x1, y1 = node["bounds_mm"]
        for x, y in ((2.0, 3.0), (8.0, 7.0)):
            cx, cy = display_mm(fig, ax, x, y)
            self.assertLess(x0, cx)
            self.assertGreater(x1, cx)
            self.assertLess(y0, cy)
            self.assertGreater(y1, cy)
        # 保守但不过分：覆盖两个标记中心，且远小于「整幅图」那种假包围盒
        span_x = display_mm(fig, ax, 8.0, 0.0)[0] - display_mm(fig, ax, 2.0, 0.0)[0]
        self.assertGreater(x1 - x0, span_x)
        self.assertLess(x1 - x0, span_x + 6.0)
        self.assertIsNotNone(node["anchors"])
        self.assertAlmostEqual(node["anchors"]["left"], x0, places=9)
        self.assertTrue(node["envelope_note"])

    def test_collection_linewidth_provenance_handles_arrays(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        constant = LineCollection([np.array([[1.0, 1.0], [2.0, 1.0]]),
                                   np.array([[3.0, 3.0], [4.0, 3.0]])], linewidths=1.5)
        mixed = LineCollection([np.array([[1.0, 5.0], [2.0, 5.0]]),
                                np.array([[3.0, 7.0], [4.0, 7.0]])], linewidths=[0.5, 2.0])
        ax.add_collection(constant)
        ax.add_collection(mixed)
        reg.register(constant, "fig.main.bars.constant")
        reg.register(mixed, "fig.main.bars.mixed")
        snap = scene.snapshot(fig, reg, scope="main")
        nodes = {n["id"]: n for n in snap["nodes"]}
        same = nodes["fig.main.bars.constant"]
        self.assertAlmostEqual(same["linewidth_pt"], 1.5, places=9)
        self.assertAlmostEqual(same["linewidth_mm"], 1.5 * 25.4 / 72.0, places=9)
        self.assertAlmostEqual(same["stroke_radius_mm"], same["linewidth_mm"] / 2.0, places=12)
        self.assertNotIn("linewidth_pt_per_element", same)
        # 逐元素线宽不同：原样携带，不猜平均半径
        varied = nodes["fig.main.bars.mixed"]
        self.assertEqual(varied["linewidth_pt_per_element"], [0.5, 2.0])
        self.assertIsNone(varied.get("linewidth_mm"))
        self.assertIsNone(varied.get("stroke_radius_mm"))
        # 单位一致性：geometry_bounds_mm 必须与 polylines_mm 同为 mm（不能一个是 px）
        points = [p for run in same["polylines_mm"] for p in run]
        self.assertAlmostEqual(same["geometry_bounds_mm"][0], min(p[0] for p in points), places=9)
        self.assertAlmostEqual(same["geometry_bounds_mm"][1], min(p[1] for p in points), places=9)
        self.assertAlmostEqual(same["geometry_bounds_mm"][2], max(p[0] for p in points), places=9)
        self.assertAlmostEqual(same["geometry_bounds_mm"][3], max(p[1] for p in points), places=9)
        self.assertEqual(same["bounds_mm"], list(same["geometry_bounds_mm"]))

    def test_rotated_text_envelope_stays_declared_as_rotated(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        label = ax.text(0.5, 0.5, "ppm", rotation=90, fontsize=7, transform=ax.transAxes)
        reg.register(label, "fig.main.label.rot")
        snap = scene.snapshot(fig, reg, scope="main")
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.label.rot"][0]
        self.assertEqual(node["rotation_deg"], 90.0)
        self.assertFalse(node["precise"])
        self.assertNotIn("baseline", node["anchors"] or {})


class UnregisteredAndUnmeasuredTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_visible_unregistered_text_line_image_patch_are_nodes_and_flagged(self):
        fig, ax = mm_canvas(axes=2)
        reg = GidRegistry(scope="main")
        registered, = ax[0].plot([0, 1], [0, 1])
        reg.register(registered, "fig.main.curve.a")
        ax[0].plot([0, 1], [1, 2])                      # 未注册曲线
        ax[0].text(0.2, 0.2, "stray")                   # 未注册文字
        ax[1].imshow(np.zeros((4, 4, 3)), extent=[0, 1, 0, 1])   # 未注册图片
        ax[1].add_patch(plt.Rectangle((0.1, 0.1), 0.2, 0.2))     # 未注册 Patch
        snap = scene.snapshot(fig, reg, scope="main")
        orphan = [n for n in snap["nodes"] if not n["registered"] and n["id"].startswith("main::unregistered")]
        self.assertEqual(len(orphan), 4)
        for node in orphan:
            self.assertIsNone(node["gid"])
            self.assertFalse(node["editable"])
            self.assertTrue(node["descriptor"])
        kinds = sorted(node["artist_type"] for node in orphan)
        self.assertEqual(kinds, ["AxesImage", "Line2D", "Rectangle", "Text"])
        self.assertEqual(sorted({node["type"] for node in orphan}),
                         ["curve", "image", "shape", "text"])
        flagged = [d for d in snap["diagnostics"] if d["kind"] == "UNREGISTERED_VISIBLE"]
        self.assertEqual(len(flagged), 4)
        image = [n for n in orphan if n["artist_type"] == "AxesImage"][0]
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["image"]["shape"], [4, 4, 3])
        self.assertTrue(image["image"]["scientific"])
        self.assertNotIn("array", image["image"])       # 只给引用，不改写像素

    def test_no_renderer_means_unmeasured_not_zeros(self):
        fig, ax = mm_canvas()
        line, = ax.plot([0, 1], [0, 1])
        reg = GidRegistry(scope="main")
        reg.register(line, "fig.main.curve.a")
        fig.canvas = types.SimpleNamespace()             # 没有 get_renderer
        snap = scene.snapshot(fig, reg, scope="main", draw=False)
        self.assertFalse(snap["measurement"]["renderer_available"])
        self.assertIsNone(snap["measurement"]["renderer"])
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.curve.a"][0]
        self.assertFalse(node["measured"])
        self.assertIsNone(node["bounds_mm"])
        self.assertIsNone(node["anchors"])
        self.assertIsNone(node["polyline_mm"])
        self.assertTrue(any(d["kind"] == "UNMEASURED_GEOMETRY" for d in snap["diagnostics"]))
        self.assertEqual(snap["containment"]["outside"], [])

    def test_fully_clipped_curve_is_measured_but_empty(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        reg = GidRegistry(scope="main")
        hidden, = ax.plot([0, 1], [5, 6])
        reg.register(hidden, "fig.main.curve.above")
        visible, = ax.plot([0, 1], [0.2, 0.4])
        reg.register(visible, "fig.main.curve.visible")
        snap = scene.snapshot(fig, reg, scope="main")
        nodes = {n["id"]: n for n in snap["nodes"]}
        self.assertTrue(nodes["fig.main.curve.above"].get("fully_clipped", False))
        self.assertTrue(nodes["fig.main.curve.above"]["measured"])
        self.assertIsNone(nodes["fig.main.curve.above"]["bounds_mm"])
        self.assertFalse(nodes["fig.main.curve.visible"].get("fully_clipped", False))
        self.assertIsNotNone(nodes["fig.main.curve.visible"]["polyline_mm"])


class RegistryIntegrityTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_duplicate_gid_is_rejected_without_overwriting(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        first, = ax.plot([0, 1], [0, 1])
        second, = ax.plot([0, 1], [1, 2])
        reg.register(first, "fig.main.curve.a")
        with self.assertRaises(ValueError):
            reg.register(second, "fig.main.curve.a")
        self.assertIs(reg.get("fig.main.curve.a"), first)
        self.assertIsNone(second.get_gid())
        self.assertEqual(list(reg.all()), ["fig.main.curve.a"])

    def test_two_way_path_mapping_is_exact(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 1], [0, 1])
        label = ax.text(0.5, 0.5, "x")
        reg.register(line, "fig.main.curve.a", params=["line_width"],
                     controlled_by=[["scalars", "line_width"], ["scopes", "main", "shift_mm"]])
        reg.register(label, "fig.main.label.x", params=["label_font_pt"])
        contract = {"parameters": [
            {"key": "line_width", "path": ["scalars", "line_width"], "objects": ["fig.main.curve.a"]},
            {"key": "label_font_pt", "path": ["scalars", "label_font_pt"],
             "mutability": "EDITABLE", "objects": ["fig.main.label.x"]},
        ]}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        nodes = {n["id"]: n for n in snap["nodes"]}
        index = {tuple(entry["path"]): entry["objects"] for entry in snap["parameter_index"]}
        for path, objects in index.items():
            for gid in objects:
                self.assertIn(list(path), nodes[gid]["controlled_by"])
        for node in snap["nodes"]:
            if not node["registered"]:
                continue
            for path in node["controlled_by"]:
                self.assertIn(node["id"], index[tuple(path)])
        self.assertEqual(index[("scalars", "label_font_pt")], ["fig.main.label.x"])
        self.assertEqual(index[("scalars", "line_width")], ["fig.main.curve.a"])
        self.assertEqual(index[("scopes", "main", "shift_mm")], ["fig.main.curve.a"])
        # 注册表自身的双向映射（B/授权侧直接调用这一层）
        self.assertEqual(reg.objects_of_path(["scalars", "line_width"]), ["fig.main.curve.a"])
        self.assertIn(["scalars", "line_width"], reg.paths_for_gid()["fig.main.curve.a"])
        registry_index = {tuple(entry["path"]): entry["objects"] for entry in reg.parameter_index()}
        self.assertEqual(registry_index[("scalars", "line_width")], ["fig.main.curve.a"])

    def test_bind_parameters_reports_dangling_records_without_inventing_nodes(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 1], [0, 1])
        reg.register(line, "fig.main.curve.a", params=["line_width"])
        outcome = reg.bind_parameters([
            {"key": "line_width", "path": ["scalars", "line_width"], "objects": ["fig.main.curve.a"]},
            {"key": "ghost", "path": ["scalars", "ghost"], "objects": ["fig.main.ghost"]},
        ])
        self.assertEqual(outcome["bound"], 1)
        self.assertEqual(outcome["dangling"], ["fig.main.ghost"])
        self.assertEqual(reg.declared_paths_of("fig.main.curve.a"), [["scalars", "line_width"]])
        self.assertIsNone(reg.get("fig.main.ghost"))
        self.assertEqual(reg.params_of("fig.main.curve.a"), ["line_width"])


class RelationSnapshotTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def _nodes(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 40)
        ax.set_ylim(0, 20)
        reg = GidRegistry(scope="main")
        band = plt.Rectangle((5, 5), 10, 5, transform=ax.transData)
        ax.add_patch(band)
        reg.register(band, "fig.main.band", params=["band_gap_mm"],
                     controlled_by=[["scalars", "band_gap_mm"]])
        other = plt.Rectangle((5, 12), 10, 5, transform=ax.transData)
        ax.add_patch(other)
        reg.register(other, "fig.main.band.b", params=["band_gap_mm"],
                     controlled_by=[["scalars", "band_gap_mm"]])
        third = plt.Rectangle((25, 5), 10, 5, transform=ax.transData)
        ax.add_patch(third)
        reg.register(third, "fig.main.band.c", params=["other_mm"],
                     controlled_by=[["scalars", "other_mm"]])
        return fig, ax, reg

    def test_measured_relation_matches_independently_computed_envelope_gap(self):
        fig, ax, reg = self._nodes()
        contract = {"relations": [
            {"id": "r_gap", "kind": "gap", "objects": ["fig.main.band", "fig.main.band.b"],
             "axis": "y", "controlled_by": [["scalars", "band_gap_mm"]]},
        ]}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        nodes = {n["id"]: n for n in snap["nodes"]}
        band_bottom = display_mm(fig, ax, 5.0, 5.0)[1]
        other_bottom = display_mm(fig, ax, 5.0, 12.0)[1]
        expected = other_bottom - nodes["fig.main.band"]["bounds_mm"][3]
        relation = snap["relations"][0]
        self.assertEqual(relation["id"], "r_gap")
        self.assertEqual(relation["status"], "OK")
        self.assertAlmostEqual(relation["value_mm"], expected, places=6)
        self.assertGreater(other_bottom, band_bottom)
        self.assertEqual(relation["mapping"]["status"], "EDITABLE")
        self.assertEqual(relation["mapping"]["objects"], ["fig.main.band", "fig.main.band.b"])
        self.assertEqual(relation["controlled_by"], [["scalars", "band_gap_mm"]])

    def test_relation_mapping_says_unsupported_or_ambiguous_instead_of_choosing(self):
        fig, ax, reg = self._nodes()
        contract = {"relations": [
            {"id": "r_none", "kind": "gap", "objects": ["fig.main.band", "fig.main.band.b"],
             "axis": "y"},
            {"id": "r_two", "kind": "gap", "objects": ["fig.main.band", "fig.main.band.b"],
             "axis": "y", "controlled_by": [["scalars", "band_gap_mm"], ["scalars", "other_mm"]]},
            {"id": "r_align", "kind": "align", "objects": ["fig.main.band", "fig.main.band.b"],
             "axis": "x"},
        ]}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        relations = {r["id"]: r for r in snap["relations"]}
        self.assertEqual(relations["r_none"]["mapping"]["status"], "UNSUPPORTED")
        self.assertEqual(relations["r_none"]["status"], "OK")
        self.assertEqual(relations["r_two"]["mapping"]["status"], "AMBIGUOUS")
        self.assertEqual([option["path"] for option in relations["r_two"]["mapping"]["options"]],
                         [["scalars", "band_gap_mm"], ["scalars", "other_mm"]])
        self.assertEqual(relations["r_align"]["status"], "UNSUPPORTED")
        kinds = {d["kind"] for d in snap["diagnostics"]}
        self.assertIn("UNSUPPORTED_RELATION", kinds)
        self.assertIn("UNSUPPORTED_MEASUREMENT", kinds)

    def test_relation_target_reports_raw_delta_only(self):
        fig, ax, reg = self._nodes()
        contract = {"relations": [
            {"id": "r_gap", "kind": "gap", "objects": ["fig.main.band", "fig.main.band.b"],
             "axis": "y", "target_mm": 1.0, "controlled_by": [["scalars", "band_gap_mm"]]},
        ]}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        relation = snap["relations"][0]
        self.assertEqual(relation["target_mm"], 1.0)
        self.assertAlmostEqual(relation["delta_mm"], relation["value_mm"] - 1.0, places=9)
        self.assertNotIn("within_tolerance", {k for k in relation if relation[k] is not None})

    def test_text_influenced_relations_never_claim_calibration_at_any_dpi(self):
        """文字栅格包围盒参与的关系换 dpi 值就会变（实测：mm 值随 dpi 不同）：
        这种结果绝不许声称已物理标定 —— calibrated 恒 False、uncertainty 恒 None。"""
        values = []
        for dpi in (96, 300):
            fig = plt.figure(figsize=(W_MM / MM_PER_INCH, H_MM / MM_PER_INCH), dpi=dpi)
            ax = fig.add_subplot(111)
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 10)
            reg = GidRegistry(scope="main")
            guide, = ax.plot([0, 10], [9, 9])
            label = ax.text(0.1, 0.8, "peak", transform=ax.transAxes, fontsize=9)
            reg.register(guide, "fig.main.curve.guide")
            reg.register(label, "fig.main.label.peak")
            contract = {"relations": [{"id": "r_letter_gap", "kind": "gap", "axis": "y",
                                       "objects": ["fig.main.curve.guide",
                                                   "fig.main.label.peak"]}]}
            snap = scene.snapshot(fig, reg, scope="main", contract=contract)
            plt.close(fig)
            self.assertIs(snap["measurement"]["calibrated"], False)
            self.assertEqual(snap["measurement"]["dpi"], float(dpi))
            label_node = [n for n in snap["nodes"] if n["id"] == "fig.main.label.peak"][0]
            self.assertFalse(label_node["precise"])          # 文字是渲染器栅格包围盒
            self.assertEqual(label_node["envelope_source"], "renderer_window_extent")
            relation = snap["relations"][0]
            self.assertEqual(relation["status"], "OK")
            self.assertFalse(relation["calibrated"])
            self.assertIsNone(relation["uncertainty_mm"])
            values.append(relation["value_mm"])
        # 同一构形在两个 dpi 下毫米值不同：正是「数学精确不是物理标定」的实测证据
        self.assertNotAlmostEqual(values[0], values[1], places=3)

    def test_dangling_contract_references_are_reported(self):
        fig, ax, reg = self._nodes()
        contract = {"parameters": [{"key": "ghost", "path": ["scalars", "ghost"],
                                    "objects": ["fig.main.missing"]}],
                    "relations": [{"id": "r_missing", "kind": "gap", "axis": "y",
                                   "objects": ["fig.main.band", "fig.main.ghost"]}]}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        dangling = [d for d in snap["diagnostics"] if d["kind"] == "DANGLING_REFERENCE"]
        self.assertTrue(any("fig.main.missing" in d["ids"] for d in dangling))
        self.assertTrue(any("fig.main.ghost" in d["ids"] for d in dangling))
        relation = snap["relations"][0]
        self.assertEqual(relation["status"], "UNSUPPORTED")
        self.assertEqual(relation["objects"], ["fig.main.band", "fig.main.ghost"])
        self.assertNotIn("ghost", [n["id"] for n in snap["nodes"]])


class ClippedGeometryTest(unittest.TestCase):
    """折线离开坐标框再回来：可见段之间本来没有连线，绝不合成假折线。

    修好之前 `_clip_polyline` 会把两段可见部分拼成一条折线，多出 (10,2)-(10,8) 这条
    根本不存在的竖线 —— 净空/碰撞测量就会对着这条鬼影说话。
    """

    def tearDown(self):
        plt.close("all")

    def test_clip_helper_returns_disconnected_runs(self):
        points = np.array([[0.0, 2.0], [20.0, 2.0], [20.0, 8.0], [0.0, 8.0]])
        runs = scene._clip_polyline_runs(points, (0.0, 0.0, 10.0, 10.0))
        self.assertEqual([len(run) for run in runs], [2, 2])
        expect = [[(0.0, 2.0), (10.0, 2.0)], [(10.0, 8.0), (0.0, 8.0)]]
        for run, want in zip(runs, expect):
            for (gx, gy), (wx, wy) in zip(run, want):
                self.assertAlmostEqual(gx, wx, places=12)
                self.assertAlmostEqual(gy, wy, places=12)
        # 每一段自己都是水平段：没有任何一段把 (10,2) 接到 (10,8)
        for run in runs:
            self.assertAlmostEqual(run[0][1], run[1][1], places=12)

    def test_clipped_curve_reports_real_runs_and_clearance(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        # C 形：x=20 的竖边整条在坐标框外，只有 y=2 与 y=8 两条水平段可见
        shape, = ax.plot([0.0, 20.0, 20.0, 0.0], [2.0, 2.0, 8.0, 8.0], lw=1.0,
                         solid_capstyle="round", solid_joinstyle="round")
        probe, = ax.plot([9.5, 9.5], [3.5, 4.5])
        reg.register(shape, "fig.main.curve.shape")
        reg.register(probe, "fig.main.curve.probe")
        contract = {"relations": [{"id": "r_clear", "kind": "clearance",
                                   "objects": ["fig.main.curve.shape", "fig.main.curve.probe"]}]}
        snap = scene.snapshot(fig, reg, scope="main", contract=contract)
        nodes = {n["id"]: n for n in snap["nodes"]}
        shape_node = nodes["fig.main.curve.shape"]
        self.assertTrue(shape_node["polyline_clipped"])
        self.assertEqual(shape_node["polyline_runs"], 2)
        self.assertIsNone(shape_node["polyline_mm"])        # 两段绝不接成一条假折线
        self.assertEqual(len(shape_node["polylines_mm"]), 2)
        ys = sorted(run[0][1] for run in shape_node["polylines_mm"])
        self.assertAlmostEqual(ys[0], display_mm(fig, ax, 0.0, 2.0)[1], places=6)
        self.assertAlmostEqual(ys[1], display_mm(fig, ax, 0.0, 8.0)[1], places=6)
        for run in shape_node["polylines_mm"]:
            self.assertAlmostEqual(run[0][1], run[1][1], places=6)   # 两段都是真实水平段

        # 净空 = 探针下端点 (9.5,3.5) 到真实水平段 y=2 的竖直距离
        expected = display_mm(fig, ax, 0.0, 3.5)[1] - display_mm(fig, ax, 0.0, 2.0)[1]
        ghost = display_mm(fig, ax, 10.0, 0.0)[0] - display_mm(fig, ax, 9.5, 0.0)[0]
        measured = snap["relations"][0]
        self.assertEqual(measured["status"], "OK")
        self.assertEqual(measured["method"], "segment_segment")
        self.assertAlmostEqual(measured["value_mm"], expected, places=6)
        self.assertGreater(measured["value_mm"], ghost)   # 鬼影竖线会给一个更小的距离
        self.assertFalse(measured["intersects"])

    def test_nan_break_is_not_bridged(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        broken, = ax.plot([0.0, 5.0, np.nan, 5.0, 10.0], [1.0, 1.0, np.nan, 3.0, 3.0])
        reg.register(broken, "fig.main.curve.broken")
        snap = scene.snapshot(fig, reg, scope="main")
        node = [n for n in snap["nodes"] if n["id"] == "fig.main.curve.broken"][0]
        # 渲染器在 NaN 处断开笔迹：两段是两段，绝不是一条跨过断口的假折线（也不是 NaN 几何）
        self.assertIsNone(node["polyline_mm"])
        self.assertEqual(len(node["polylines_mm"]), 2)
        self.assertEqual([len(run) for run in node["polylines_mm"]], [2, 2])
        self.assertAlmostEqual(node["polylines_mm"][0][0][1], display_mm(fig, ax, 0.0, 1.0)[1],
                               places=6)
        self.assertAlmostEqual(node["polylines_mm"][1][0][1], display_mm(fig, ax, 0.0, 3.0)[1],
                               places=6)
        for run in node["polylines_mm"]:
            self.assertAlmostEqual(run[0][1], run[1][1], places=6)   # 每段自己都是水平段

    def test_dashed_and_solid_curves_expose_linestyle_provenance(self):
        fig, ax = mm_canvas()
        reg = GidRegistry(scope="main")
        dashed, = ax.plot([0, 1], [0, 1], ls="--", lw=1.0, solid_capstyle="round",
                          solid_joinstyle="round")
        solid, = ax.plot([0, 1], [1, 2], lw=1.0, solid_capstyle="round", solid_joinstyle="round")
        reg.register(dashed, "fig.main.curve.dashed")
        reg.register(solid, "fig.main.curve.solid")
        snap = scene.snapshot(fig, reg, scope="main")
        nodes = {n["id"]: n for n in snap["nodes"]}
        # 圆头圆角 + 实线才有「中心线 ⊖ 半径」模型；线型必须如实上报，虚线的拒绝交给几何层
        self.assertEqual(nodes["fig.main.curve.solid"]["linestyle"], "-")
        self.assertEqual(nodes["fig.main.curve.dashed"]["linestyle"], "--")


class InspectTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_inspect_filters_and_returns_neighbours_parameters_and_relations(self):
        fig, ax = mm_canvas()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        reg = GidRegistry(scope="main")
        line, = ax.plot([0, 5], [0, 5])
        label = ax.text(1, 9, "peak")
        reg.register(line, "fig.main.curve.a")
        reg.register(label, "fig.main.label.peak")
        contract = {
            "groups": [{"id": "curves", "parent": None, "members": ["fig.main.curve.a"]}],
            "parameters": [{"key": "line_width", "path": ["scalars", "line_width"],
                            "objects": ["fig.main.curve.a"]}],
            "relations": [{"id": "r_gap", "kind": "gap", "axis": "y",
                           "objects": ["fig.main.curve.a", "fig.main.label.peak"],
                           "controlled_by": [["scalars", "line_width"]]}],
        }
        snap = scene.snapshot(fig, reg, scope="main", revision="rev-2", contract=contract)
        found = scene.inspect(snap, ids=["fig.main.curve.a"])
        self.assertEqual(found["count"], 1)
        self.assertEqual(found["nodes"][0]["id"], "fig.main.curve.a")
        self.assertEqual(found["neighbors"]["fig.main.curve.a"]["parent"], "curves")
        self.assertEqual(found["neighbors"]["fig.main.curve.a"]["children"], [])
        self.assertEqual([p["path"] for p in found["parameters"]], [["scalars", "line_width"]])
        self.assertEqual([r["id"] for r in found["relations"]], ["r_gap"])
        self.assertEqual(found["measurement"]["dpi"], float(DPI))
        self.assertEqual(found["revision"], "rev-2")

        by_group = scene.inspect(snap, ids=["curves"])
        self.assertEqual(by_group["neighbors"]["curves"]["children"], ["fig.main.curve.a"])
        self.assertEqual([n["id"] for n in scene.inspect(snap, name="peak")["nodes"]],
                         ["fig.main.label.peak"])
        self.assertEqual([n["id"] for n in scene.inspect(snap, type="panel")["nodes"]],
                         ["main::panel.0"])
        self.assertEqual([n["id"] for n in scene.inspect(snap, type="curve")["nodes"]],
                         ["fig.main.curve.a"])
        self.assertEqual(scene.inspect(snap, scope="nope")["count"], 0)
        stray = scene.inspect(snap, name="unregistered")
        self.assertEqual(stray["count"], 0)


if __name__ == "__main__":
    unittest.main()
