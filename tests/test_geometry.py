"""六种类型无关关系的几何行为测试：精确值、带符号间隙、诚实的不确定度与拒绝。

数值都是构造出来的物理毫米，测试用**独立算过**的期望值比对，不比对实现细节。
"""
import unittest

import numpy as np

from figpact import geometry


def node(node_id, bounds, **extra):
    payload = {"id": node_id, "measured": True, "bounds_mm": list(bounds), "is_text": False,
               "precise": True}
    payload.update(extra)
    return payload


def polyline(node_id, points, bounds=None, **extra):
    pts = [list(p) for p in points]
    if bounds is None:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bounds = [min(xs), min(ys), max(xs), max(ys)]
    return node(node_id, bounds, polyline_mm=pts, **extra)


def runs_node(node_id, runs, bounds=None, **extra):
    """裁剪后互不相连的多段显示几何（段与段之间本来没有连线）。"""
    polys = [[list(p) for p in run] for run in runs]
    flat = [p for run in polys for p in run]
    if bounds is None:
        bounds = [min(p[0] for p in flat), min(p[1] for p in flat),
                  max(p[0] for p in flat), max(p[1] for p in flat)]
    return node(node_id, bounds, polyline_mm=None, polylines_mm=polys, **extra)


class SixKindsTest(unittest.TestCase):
    def test_align_reports_anchor_spread_and_requires_anchor(self):
        a, b, c = node("a", (0, 0, 4, 2)), node("b", (10, 0, 14, 2)), node("c", (20, 1, 24, 3))
        res = geometry.measure_relation("align", [a, b, c], axis="y", anchor="bottom")
        self.assertEqual(res["status"], "OK")
        self.assertAlmostEqual(res["value_mm"], 1.0, places=12)   # bottoms 0/0/1
        self.assertEqual(res["precision"], "exact")
        self.assertFalse(res["aligned"])
        self.assertEqual(res["anchors_mm"]["c"], 1.0)
        exact = geometry.measure_relation("align", [a, node("d", (0, 0, 4, 2))], anchor="left",
                                          axis="x")
        self.assertAlmostEqual(exact["value_mm"], 0.0, places=12)
        self.assertTrue(exact["aligned"])
        missing = geometry.measure_relation("align", [a, b], axis="x")
        self.assertEqual(missing["status"], "UNSUPPORTED")
        self.assertIsNone(missing["value_mm"])

    def test_gap_is_signed_envelope_edge_separation(self):
        low, high = node("low", (0, 0, 10, 5)), node("high", (0, 8, 10, 13))
        res = geometry.measure_relation("gap", [low, high], axis="y")
        self.assertAlmostEqual(res["value_mm"], 3.0, places=12)
        overlap = geometry.measure_relation("gap", [low, node("high", (0, 3, 10, 13))], axis="y")
        self.assertAlmostEqual(overlap["value_mm"], -2.0, places=12)
        self.assertEqual(overlap["method"], "envelope_edge")
        self.assertEqual(overlap["pairs"], [["low", "high"]])

    def test_clearance_exact_segments_and_crossing(self):
        above = polyline("above", [(0, 3), (10, 3)])
        below = polyline("below", [(0, 0), (5, 0), (10, 0)])
        res = geometry.measure_relation("clearance", [above, below])
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["method"], "segment_segment")
        self.assertEqual(res["precision"], "exact")
        # 数学精确 ≠ 物理标定：引擎不标定到渲染墨迹，任何结果都不许声称 calibrated
        self.assertFalse(res["calibrated"])
        self.assertIsNone(res["uncertainty_mm"])
        self.assertAlmostEqual(res["value_mm"], 3.0, places=9)
        self.assertFalse(res["intersects"])
        crossing = polyline("crossing", [(0, 4), (10, 2)])
        hit = geometry.measure_relation("clearance", [above, crossing])
        self.assertAlmostEqual(hit["value_mm"], 0.0, places=12)
        self.assertTrue(hit["intersects"])
        parallel = polyline("parallel", [(0, 1), (10, 1)])
        miss = geometry.measure_relation("clearance", [above, parallel])
        self.assertAlmostEqual(miss["value_mm"], 2.0, places=12)
        self.assertFalse(miss["intersects"])

    def test_clearance_segment_to_text_envelope_is_envelope_not_fake_precision(self):
        line = polyline("line", [(0, 0), (10, 0)])
        text = node("label", (12, -1, 16, 3), is_text=True, rotation_deg=0.0)
        res = geometry.measure_relation("clearance", [line, text])
        self.assertEqual(res["method"], "centerline_text_envelope")
        self.assertEqual(res["geometry_basis"], "centerline_to_text_ink_envelope")
        self.assertEqual(res["precision"], "envelope")
        self.assertFalse(res["calibrated"])
        self.assertIsNone(res["uncertainty_mm"])
        self.assertAlmostEqual(res["value_mm"], 2.0, places=9)
        self.assertEqual(res["text_object"], "label")
        rotated = node("rotated", (12, -1, 20, 7), is_text=True, rotation_deg=45.0)
        rot = geometry.measure_relation("clearance", [line, rotated])
        self.assertTrue(rot["rotated_text"])
        self.assertEqual(rot["precision"], "envelope")
        self.assertFalse(rot["calibrated"])
        self.assertTrue(any("保守" in note for note in rot["notes"]), rot["notes"])

    def test_clearance_pair_only_and_unknown_method_rejected(self):
        a = polyline("a", [(0, 0), (1, 0)])
        b = polyline("b", [(0, 5), (1, 5)])
        text = node("t", (5, 5, 8, 8), is_text=True)
        self.assertEqual(geometry.measure_relation("clearance", [a, b, text])["status"], "UNSUPPORTED")
        self.assertEqual(
            geometry.measure_relation("clearance", [a, text], method="segment_segment")["status"],
            "UNSUPPORTED")
        self.assertEqual(geometry.measure_relation("clearance", [a, b], method="magic")["status"],
                         "UNSUPPORTED")
        self.assertEqual(geometry.measure_relation("nonsense", [a, b])["status"], "UNSUPPORTED")

    def test_contain_reports_overflow_and_slack(self):
        container = node("panel", (0, 0, 40, 30))
        inside = node("in", (5, 5, 15, 15))
        out = node("out", (30, 20, 45, 35))
        ok = geometry.measure_relation("contain", [container, inside], axis=None)
        self.assertTrue(ok["contained"])
        self.assertLess(ok["value_mm"], 0.0)
        self.assertAlmostEqual(ok["slack_mm"], 5.0, places=12)   # 最近的边留 5 mm 净空
        self.assertEqual(ok["overflow_mm"], {"x": -5.0, "y": -5.0})
        bad = geometry.measure_relation("contain", [container, out], axis=None)
        self.assertFalse(bad["contained"])
        self.assertAlmostEqual(bad["value_mm"], 5.0, places=12)   # +5 on x1 and +5 on y1
        self.assertEqual(bad["overflow_mm"], {"x": 5.0, "y": 5.0})
        single = geometry.measure_relation("contain", [container, out], axis="x")
        self.assertAlmostEqual(single["value_mm"], 5.0, places=12)
        self.assertEqual(single["overflow_mm"], {"x": 5.0})

    def test_equal_size_and_distribute_report_the_right_deviation(self):
        a, b = node("a", (0, 0, 10, 4)), node("b", (0, 0, 12, 7))
        res = geometry.measure_relation("equal_size", [a, b], axis=None)
        self.assertAlmostEqual(res["value_mm"], 3.0, places=12)   # heights 4 vs 7
        self.assertFalse(res["equal"])
        widths = geometry.measure_relation("equal_size", [a, b], axis="x")
        self.assertAlmostEqual(widths["value_mm"], 2.0, places=12)
        self.assertEqual(widths["sizes_mm"]["a"], {"x": 10.0})
        items = [node("p1", (0, 0, 1, 1)), node("p2", (2, 0, 3, 1)), node("p3", (5, 0, 6, 1))]
        dist = geometry.measure_relation("distribute", items, axis="x", anchor="left")
        self.assertEqual(dist["gaps_mm"], [1.0, 2.0])
        self.assertAlmostEqual(dist["value_mm"], 1.0, places=12)
        self.assertEqual(dist["order"], ["p1", "p2", "p3"])
        self.assertEqual(geometry.measure_relation("distribute", items[:2], axis="x")["status"],
                         "UNSUPPORTED")


    def test_gap_baseline_method_uses_first_displayed_vertex(self):
        lower = polyline("lower", [(0, 0), (10, 0)], bounds=[0, -0.1, 10, 0.1])
        upper = polyline("upper", [(0, 2), (10, 2)], bounds=[0, 1.9, 10, 2.1])
        res = geometry.measure_relation("gap", [upper, lower], axis="y", method="baseline")
        self.assertEqual(res["method"], "baseline")
        self.assertAlmostEqual(res["value_mm"], 2.0, places=12)
        self.assertEqual(res["precision"], "exact")
        self.assertFalse(res["calibrated"])
        self.assertEqual(res["first_point_mm"], {"upper": 2.0, "lower": 0.0})
        edge = geometry.measure_relation("gap", [upper, lower], axis="y")
        self.assertAlmostEqual(edge["value_mm"], 1.8, places=12)   # 边到边，含线宽
        self.assertEqual(geometry.measure_relation("gap", [upper, node("t", (0, 5, 1, 6))],
                                                  axis="y", method="baseline")["status"],
                         "UNSUPPORTED")


    def test_stroke_clearance_needs_round_cap_and_join(self):
        def stroked(node_id, points, capstyle, joinstyle, lw_mm=0.5, marker="None", style="-"):
            return polyline(node_id, points, linewidth_mm=lw_mm, solid_capstyle=capstyle,
                            solid_joinstyle=joinstyle, marker=marker, linestyle=style)

        lower = stroked("lower", [(0, 0), (10, 0)], "round", "round", lw_mm=1.0)
        upper = stroked("upper", [(0, 3), (10, 3)], "round", "round", lw_mm=0.5)
        res = geometry.measure_relation("clearance", [lower, upper], method="stroke_segment")
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["geometry_basis"], "centerline_minus_stroke_radii")
        self.assertAlmostEqual(res["centerline_mm"], 3.0, places=12)
        self.assertAlmostEqual(res["value_mm"], 2.25, places=12)   # 3 - (0.5 + 0.25)
        self.assertEqual(res["stroke_radius_mm"], {"a": 0.5, "b": 0.25})
        # 值是**数学模型**的精确结果，不是标定过的可见墨迹：如实标 model_exact + 未标定
        self.assertEqual(res["precision"], "model_exact")
        self.assertFalse(res["calibrated"])
        self.assertIsNone(res["uncertainty_mm"])
        self.assertTrue(any("模型" in note and "墨迹" in note for note in res["notes"]), res["notes"])
        # 中心线相距 3 mm 时，半径和外扩后仍不相交
        self.assertFalse(res["intersects"])
        self.assertFalse(res["centerline_intersects"])

        # 中心线 0.4 mm、半径和 0.75 mm：可见笔迹重叠，但中心线并不相交
        close = stroked("close", [(0, 0.4), (10, 0.4)], "round", "round", lw_mm=0.5)
        overlap = geometry.measure_relation("clearance", [lower, close], method="stroke_segment")
        self.assertAlmostEqual(overlap["centerline_mm"], 0.4, places=12)
        self.assertTrue(overlap["intersects"])
        self.assertFalse(overlap["centerline_intersects"])
        self.assertAlmostEqual(overlap["value_mm"], 0.0, places=12)

        butt = stroked("butt", [(0, 1), (10, 1)], "butt", "miter")
        refused = geometry.measure_relation("clearance", [lower, butt], method="stroke_segment")
        self.assertEqual(refused["status"], "UNSUPPORTED")
        self.assertIsNone(refused["value_mm"])
        self.assertTrue(any("butt" in note for note in refused["notes"]), refused["notes"])
        dotted = stroked("dotted", [(0, 1), (10, 1)], "round", "round", marker="o")
        self.assertEqual(geometry.measure_relation("clearance", [lower, dotted],
                                                   method="stroke_segment")["status"],
                         "UNSUPPORTED")
        # 虚线：半径外扩模型不成立（虚线段之间有完全没有墨迹的间隙），必须拒绝而不是给常数
        dashed = stroked("dashed", [(0, 1), (10, 1)], "round", "round", style="--")
        dash_res = geometry.measure_relation("clearance", [lower, dashed], method="stroke_segment")
        self.assertEqual(dash_res["status"], "UNSUPPORTED")
        self.assertTrue(any("实线" in note for note in dash_res["notes"]), dash_res["notes"])
        unknown = polyline("unknown", [(0, 1), (10, 1)], linewidth_mm=0.5,
                           solid_capstyle="round", solid_joinstyle="round")
        self.assertEqual(geometry.measure_relation("clearance", [lower, unknown],
                                                   method="stroke_segment")["status"],
                         "UNSUPPORTED")
        # 逐元素线宽不同：没有统一半径，绝不拿平均值冒充
        mixed_widths = polyline("mixed", [(0, 1), (10, 1)], linestyle="-", solid_capstyle="round",
                                solid_joinstyle="round", linewidth_pt_per_element=[0.5, 2.0])
        self.assertEqual(geometry.measure_relation("clearance", [lower, mixed_widths],
                                                   method="stroke_segment")["status"],
                         "UNSUPPORTED")

    def test_centerline_clearance_is_named_as_centerline_not_visible_stroke(self):
        a = polyline("a", [(0, 0), (10, 0)], linewidth_mm=2.0)
        b = polyline("b", [(0, 3), (10, 3)], linewidth_mm=2.0)
        res = geometry.measure_relation("clearance", [a, b])
        self.assertEqual(res["geometry_basis"], "centerline")
        self.assertAlmostEqual(res["value_mm"], 3.0, places=12)
        self.assertTrue(any("中心线" in note for note in res["notes"]), res["notes"])
        self.assertTrue(any("线宽" in note for note in res["notes"]), res["notes"])


class HonestyTest(unittest.TestCase):
    def test_unmeasured_nodes_are_not_zero_filled(self):
        res = geometry.measure_relation("gap", [node("a", (0, 0, 1, 1)), dict(id="b", measured=False,
                                                                             bounds_mm=None)])
        self.assertEqual(res["status"], "UNMEASURED")
        self.assertIsNone(res["value_mm"])
        self.assertTrue(any("未测量" in note for note in res["notes"]))

    def test_fully_clipped_is_named_as_clipping_not_missing_box(self):
        res = geometry.measure_relation("gap", [dict(id="hidden", measured=True, bounds_mm=None,
                                                     fully_clipped=True),
                                                node("b", (0, 0, 1, 1))])
        self.assertEqual(res["status"], "UNSUPPORTED")
        self.assertTrue(any("裁切" in note for note in res["notes"]))

    def test_axis_none_never_silently_means_y(self):
        low, high = node("low", (0, 0, 10, 5)), node("high", (0, 8, 10, 13))
        res = geometry.measure_relation("gap", [low, high], axis=None)
        self.assertEqual(res["axis"], "x")
        self.assertEqual(res["declared_axis"], None)
        # 结果是 x 轴投影，必须说清楚：不能把 x 投影的重叠当成二维重叠
        self.assertEqual(res["projection"], "x")
        self.assertTrue(any("投影" in note and "二维" in note for note in res["notes"]), res["notes"])
        self.assertAlmostEqual(res["value_mm"], -10.0, places=12)   # x 方向完全重叠，不是 +3 的 y 间距
        explicit = geometry.measure_relation("gap", [low, high], axis="y")
        self.assertAlmostEqual(explicit["value_mm"], 3.0, places=12)
        self.assertNotIn("projection", explicit)
        self.assertNotIn("declared_axis", explicit)
        self.assertEqual(geometry.measure_relation("gap", [low, high], axis="z")["status"],
                         "UNSUPPORTED")

    def test_tolerance_is_caller_supplied_and_never_claims_calibration(self):
        line = polyline("line", [(0, 0), (10, 0)])
        text = node("label", (13, -1, 17, 3), is_text=True)
        res = geometry.measure_relation("clearance", [line, text], tolerance_mm=2.0)
        self.assertEqual(res["tolerance_mm"], 2.0)
        self.assertEqual(res["tolerance_semantics"], "min_clearance_mm")
        self.assertTrue(res["within_tolerance"])          # 3.0 mm ≥ 2.0 mm
        self.assertFalse(res["calibrated"])
        self.assertIsNone(res["uncertainty_mm"])
        # 调用方的 tolerance 只是验收界，不是标定/精度证据
        self.assertTrue(any("验收界" in note for note in res["notes"]), res["notes"])
        deviation = geometry.measure_relation("equal_size", [node("a", (0, 0, 10, 4)),
                                                             node("b", (0, 0, 10, 7))],
                                              axis="y", tolerance_mm=2.0)
        self.assertFalse(deviation["within_tolerance"])   # 3.0 > 2.0
        self.assertEqual(deviation["tolerance_semantics"], "max_deviation_mm")
        with self.assertRaises(ValueError):
            geometry.measure_relation("gap", [line, line], axis="x", tolerance_mm=-1)

    def test_no_kind_ever_claims_physical_calibration(self):
        """数学精确不等于物理标定：六种关系的任何结果都不许声称 calibrated / uncertainty。

        值本身不受影响（这里同时钉住每一种的独立算过的期望值）。
        """
        left = node("left", (0, 0, 4, 2))
        right = node("right", (10, 0, 14, 2))
        third = node("third", (20, 0, 24, 2))
        container = node("container", (0, 0, 40, 30))
        inside = node("inside", (5, 5, 15, 15))
        above = polyline("above", [(0, 3), (10, 3)])
        below = polyline("below", [(0, 0), (10, 0)])
        text = node("label", (12, -1, 16, 3), is_text=True)

        def stroked(node_id, points, lw_mm):
            return polyline(node_id, points, linewidth_mm=lw_mm, solid_capstyle="round",
                            solid_joinstyle="round", marker="None", linestyle="-")

        cases = {
            "align": (geometry.measure_relation("align", [left, right, third], axis="x",
                                                anchor="left"), 20.0),
            "gap": (geometry.measure_relation("gap", [left, right], axis="x"), 6.0),
            "gap_baseline": (geometry.measure_relation("gap", [above, below], axis="y",
                                                       method="baseline"), 3.0),
            "clearance_segments": (geometry.measure_relation("clearance", [above, below]), 3.0),
            "clearance_text": (geometry.measure_relation("clearance", [below, text]), 2.0),
            # 中心线 3 mm − 半径和 (0.5/2 + 1.0/2) = 2.25：数学模型精确，但不是标定墨迹
            "clearance_stroke": (geometry.measure_relation(
                "clearance", [stroked("s_above", [(0, 3), (10, 3)], 0.5),
                              stroked("s_below", [(0, 0), (10, 0)], 1.0)],
                method="stroke_segment"), 2.25),
            "contain": (geometry.measure_relation("contain", [container, inside], axis=None), -5.0),
            "equal_size": (geometry.measure_relation("equal_size", [left, right], axis="y"), 0.0),
            "distribute": (geometry.measure_relation("distribute", [left, right, third],
                                                     axis="x"), 0.0),
        }
        for label, (res, expected) in cases.items():
            self.assertEqual(res["status"], "OK", label)
            self.assertAlmostEqual(res["value_mm"], expected, places=9, msg=label)
            self.assertFalse(res["calibrated"], label)
            self.assertIsNone(res["uncertainty_mm"], label)

    def test_result_shape_is_json_ready(self):
        import json
        res = geometry.measure_relation("gap", [node("a", (0, 0, 1, 1)), node("b", (2, 0, 3, 1))],
                                        axis="x")
        self.assertEqual(res["unit"], "mm")
        self.assertEqual(res["coordinate_reference"], "canvas_bottom_left")
        self.assertEqual(res["relation"], "gap")
        self.assertEqual(res["objects"], ["a", "b"])
        json.dumps(res)


class LargePolylineTest(unittest.TestCase):
    """大折线必须走剪枝扫描；两条路径的结果必须一致（同一份精确几何）。"""

    def _offset_curves(self, n):
        x = np.linspace(0.0, 10.0, n)
        base = np.sin(x)
        return (polyline("a", np.stack([x, base], axis=1)),
                polyline("b", np.stack([x, base + 3.0], axis=1)))

    def test_pruned_sweep_matches_exact_mesh(self):
        a, b = self._offset_curves(700)          # 699² < 网格上限 → 网格法
        mesh = geometry.measure_relation("clearance", [a, b])
        original = geometry._MESH_LIMIT
        try:
            geometry._MESH_LIMIT = 0             # 强制走剪枝扫描
            sweep = geometry.measure_relation("clearance", [a, b])
        finally:
            geometry._MESH_LIMIT = original
        self.assertEqual(mesh["method"], "segment_segment")
        self.assertEqual(sweep["status"], "OK")
        self.assertAlmostEqual(mesh["value_mm"], sweep["value_mm"], places=9)
        self.assertGreater(mesh["value_mm"], 0.0)
        self.assertLessEqual(mesh["value_mm"], 3.0)
        self.assertEqual(mesh["intersects"], sweep["intersects"])

    def test_large_polylines_still_report_exact_intersection(self):
        n = 2000                                  # 1999² > 网格上限
        x = np.linspace(0.0, 10.0, n)
        flat = polyline("flat", np.stack([x, np.zeros(n)], axis=1))
        slanted = polyline("slant", np.stack([x, -0.5 + x / 10.0], axis=1))
        res = geometry.measure_relation("clearance", [flat, slanted])
        self.assertEqual(res["status"], "OK")
        self.assertTrue(res["intersects"])
        self.assertAlmostEqual(res["value_mm"], 0.0, places=12)
        self.assertFalse(res["calibrated"])

    def test_large_polylines_keep_exact_offset_distance(self):
        n = 2000
        x = np.linspace(0.0, 10.0, n)
        lower = polyline("lower", np.stack([x, np.zeros(n)], axis=1))
        upper = polyline("upper", np.stack([x, np.full(n, 2.5)], axis=1))
        res = geometry.measure_relation("clearance", [lower, upper])
        self.assertAlmostEqual(res["value_mm"], 2.5, places=12)
        self.assertFalse(res["intersects"])

    def test_large_input_with_one_long_spanning_segment_keeps_exact_distance(self):
        # 一条横跨整幅图的长线段 + 起点都在左方的很多行：按起点二分剪枝会整行丢掉它
        n = 1500
        x = np.linspace(0.0, 100.0, n)
        long_a = polyline("long", [[0.0, 0.0], [100.0, 0.0]])
        many_b = polyline("many", np.stack([x, np.full(n, 0.5)], axis=1))
        mesh = geometry.measure_relation("clearance", [long_a, many_b])
        original = geometry._MESH_LIMIT
        try:
            geometry._MESH_LIMIT = 0             # 强制走剪枝扫描
            sweep = geometry.measure_relation("clearance", [long_a, many_b])
        finally:
            geometry._MESH_LIMIT = original
        self.assertAlmostEqual(mesh["value_mm"], 0.5, places=12)
        self.assertAlmostEqual(sweep["value_mm"], 0.5, places=12)
        self.assertEqual(mesh["intersects"], sweep["intersects"])


class SegmentSetDistanceTest(unittest.TestCase):
    """剪枝扫描与网格法必须是同一份精确几何；长线段与后出现的更近行都不能被剪掉。"""

    def _both(self, a, b):
        mesh = geometry._mesh_distance(a, b)
        sweep = geometry._segment_set_distance_sweep(a, b)
        self.assertEqual(mesh[1], sweep[1])
        self.assertAlmostEqual(mesh[0], sweep[0], places=9)
        return mesh

    def test_sweep_keeps_long_segment_that_spans_the_query(self):
        # a[0] 起点远在左方（x=0）却横跨 x=50：只按起点二分就会报 1.0 而不是 0.01
        a = np.array([[[0.0, 0.0], [100.0, 0.0]], [[200.0, 100.0], [201.0, 100.0]]])
        b = np.array([[[1.0, 1.0], [2.0, 1.0]], [[50.0, 0.01], [51.0, 0.01]]])
        value, intersects = self._both(a, b)
        self.assertAlmostEqual(value, 0.01, places=12)
        self.assertFalse(intersects)

    def test_sweep_finds_the_closer_pair_in_a_later_row(self):
        a = np.array([[[0.0, 0.0], [100.0, 0.0]], [[200.0, 100.0], [201.0, 100.0]]])
        b = np.array([[[1.0, 40.0], [2.0, 40.0]],          # 第一行先建立上界 40
                      [[50.0, 0.25], [51.0, 0.25]]])        # 后面的行更近：0.25
        value, intersects = self._both(a, b)
        self.assertAlmostEqual(value, 0.25, places=12)
        self.assertFalse(intersects)

    def test_sweep_still_finds_intersection_behind_a_long_segment(self):
        a = np.array([[[0.0, 5.0], [100.0, 5.0]], [[200.0, 100.0], [201.0, 100.0]]])
        b = np.array([[[0.0, 30.0], [1.0, 30.0]],          # 第一行：距离 25
                      [[60.0, 4.0], [60.0, 6.0]]])         # 与长线段真交叉
        value, intersects = self._both(a, b)
        self.assertEqual(value, 0.0)
        self.assertTrue(intersects)

    def test_sweep_matches_mesh_across_many_rows(self):
        x = np.linspace(0.0, 100.0, 400)
        offset = np.linspace(7.0, 1.5, 399)                # 每行距离不同：最小值在最后一行
        a = np.concatenate([np.stack([np.stack([x[:-1], np.zeros(399)], axis=1),
                                      np.stack([x[1:], np.zeros(399)], axis=1)], axis=1),
                            [[[150.0, 90.0], [260.0, 90.0]]]], axis=0)
        b = np.stack([np.stack([x[:-1], offset], axis=1),
                      np.stack([x[1:], offset], axis=1)], axis=1)
        value, intersects = self._both(a, b)
        self.assertAlmostEqual(value, 1.5, places=9)
        self.assertFalse(intersects)


class TouchingSemanticsTest(unittest.TestCase):
    """`intersects` 与 `value_mm == 0` 必须永远一致：共线重叠/端点接触算接触，正净空绝不算。"""

    def test_collinear_overlap_is_touching_not_a_false_clean(self):
        a = np.array([[[0.0, 0.0], [10.0, 0.0]]])
        b = np.array([[[2.0, 0.0], [8.0, 0.0]]])
        value, intersects = geometry._segment_set_distance(a, b)
        self.assertEqual(value, 0.0)
        self.assertTrue(intersects)
        res = geometry.measure_relation("clearance", [polyline("a", [(0, 0), (10, 0)]),
                                                      polyline("b", [(2, 0), (8, 0)])])
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["value_mm"], 0.0)
        self.assertTrue(res["intersects"])

    def test_endpoints_and_zero_length_segments_touch(self):
        a = np.array([[[0.0, 0.0], [10.0, 0.0]]])
        self.assertEqual(geometry._segment_set_distance(a, np.array([[[10.0, 0.0], [5.0, 3.0]]])),
                         (0.0, True))                       # 端点落在对方端点上
        self.assertEqual(geometry._segment_set_distance(a, np.array([[[3.0, -4.0], [3.0, 0.0]]])),
                         (0.0, True))                       # 端点落在对方内部
        point = np.array([[[10.0, 0.0], [10.0, 0.0]]])      # 零长度线段
        self.assertEqual(geometry._segment_set_distance(a, point), (0.0, True))
        self.assertEqual(geometry._segment_set_distance(point, point), (0.0, True))
        self.assertEqual(geometry._segment_set_distance(a, np.array([[[10.0, 0.5], [10.0, 0.5]]])),
                         (0.5, False))

    def test_positive_clearance_is_never_reported_as_touching(self):
        a = np.array([[[0.0, 0.0], [10.0, 0.0]]])
        for dy in (1e-9, 1e-6, 0.25):
            b = np.array([[[0.0, dy], [10.0, dy]]])
            value, intersects = geometry._segment_set_distance(a, b)
            self.assertFalse(intersects, dy)
            self.assertAlmostEqual(value / dy, 1.0, places=12)
        # 端点错开一点点的共线线段：有正净空就不是接触（不把 1e-6 这种构造差值
        # 当成精确到 1e-15 的物理结论：只要求正、且量级正确）
        value, intersects = geometry._segment_set_distance(
            a, np.array([[[10.0 + 1e-6, 0.0], [20.0, 0.0]]]))
        self.assertFalse(intersects)
        self.assertGreater(value, 0.0)
        self.assertAlmostEqual(value / 1e-6, 1.0, places=6)

    def test_touching_and_crossing_are_scale_invariant(self):
        # 同一构形整体缩放 1e±6：容差按线段尺度缩放，结论必须一模一样
        for k in (1e-6, 1.0, 1e6):
            a = np.array([[[0.0, 0.0], [10.0 * k, 0.0]]])
            crossing = np.array([[[2.0 * k, 1.0 * k], [8.0 * k, -1.0 * k]]])
            value, intersects = geometry._segment_set_distance(a, crossing)
            self.assertEqual(value, 0.0, k)
            self.assertTrue(intersects, k)
            apart = np.array([[[2.0 * k, 0.25 * k], [8.0 * k, 0.25 * k]]])
            value, intersects = geometry._segment_set_distance(a, apart)
            self.assertFalse(intersects, k)
            self.assertAlmostEqual(value / (0.25 * k), 1.0, places=9)


class ClippedRunsTest(unittest.TestCase):
    """裁剪后的多段显示几何（`polylines_mm`）：只对真实存在的段测量，段间没有连线。"""

    def test_runs_are_measured_without_phantom_chords(self):
        two = runs_node("two", [[(0, 0), (10, 0)], [(0, 5), (10, 5)]])
        near = polyline("near", [(5, 2), (6, 2)])
        res = geometry.measure_relation("clearance", [two, near])
        self.assertEqual(res["method"], "segment_segment")
        self.assertAlmostEqual(res["value_mm"], 2.0, places=12)
        self.assertFalse(res["intersects"])
        self.assertTrue(any("多段" in note for note in res["notes"]), res["notes"])
        # 相接成一条假折线会多出 (10,0)-(0,5) 这条并不存在的连线：(9,1)-(9,4) 到它的距离
        # 只有 0.447 —— 鬼影会让净空变小、甚至报相交
        ghost = polyline("ghost", [(9, 1), (9, 4)])
        clean = geometry.measure_relation("clearance", [two, ghost])
        self.assertAlmostEqual(clean["value_mm"], 1.0, places=12)
        self.assertFalse(clean["intersects"])

    def test_intersection_only_from_real_runs(self):
        two = runs_node("two", [[(0, 0), (10, 0)], [(0, 5), (10, 5)]])
        crossing = polyline("cross", [(5, 5.5), (5, 4.5)])
        hit = geometry.measure_relation("clearance", [two, crossing])
        self.assertEqual(hit["value_mm"], 0.0)
        self.assertTrue(hit["intersects"])

    def test_text_envelope_uses_every_run(self):
        two = runs_node("two", [[(0, 0), (10, 0)], [(0, 5), (10, 5)]])
        text = node("label", (2, 6, 4, 8), is_text=True)
        res = geometry.measure_relation("clearance", [two, text])
        self.assertEqual(res["method"], "centerline_text_envelope")
        self.assertAlmostEqual(res["value_mm"], 1.0, places=12)     # 到 y=5 那一段

    def test_non_finite_geometry_is_refused_not_measured_as_envelope(self):
        other = polyline("other", [(0, 5), (10, 5)])
        bad = node("bad", (0, 0, 10, 10), polyline_mm=[[0, 0], [float("nan"), 1.0]])
        res = geometry.measure_relation("clearance", [bad, other])
        self.assertEqual(res["status"], "UNSUPPORTED")
        self.assertIsNone(res["value_mm"])
        # 混在真实段里的 NaN 段也不能被静默跳过（跳过=对着半条几何报"已测量"）
        mixed = runs_node("mixed", [[(0, 0), (10, 0)]])
        mixed["polylines_mm"].append([[0.0, float("inf")], [10.0, float("inf")]])
        refused = geometry.measure_relation("clearance", [mixed, other])
        self.assertEqual(refused["status"], "UNSUPPORTED")
        self.assertIsNone(refused["value_mm"])


if __name__ == "__main__":
    unittest.main()
