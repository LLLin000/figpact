"""G1 只读 Inspector：导出安全拒绝 + 捕获/投影/导出的行为边界负向测试。

全部用真实 Figure 与真实文件系统断言，不 mock 图元响应、不断言被测源码文本。
`data_mm` / `count_draws` 独立复算，避免复用被测实现的换算过程。
"""
import base64
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import matplotlib
import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from PIL import Image

from figpact import inspector
from figpact.registry import GidRegistry
from figpact.units import MM_PER_INCH

ROOT = Path(__file__).resolve().parents[1]
W_MM, H_MM = 120.0, 60.0


def mm_figure():
    """毫米画布 + 固定 dpi 的真实 Figure（不复用被测实现的换算过程）。"""
    fig = plt.figure(figsize=(W_MM / MM_PER_INCH, H_MM / MM_PER_INCH), dpi=100)
    return fig, fig.gca()


def data_mm(fig, ax, x, y):
    """数据坐标 → 画布毫米（左下角原点），测试自己算。"""
    px = ax.transData.transform((x, y))
    scale = MM_PER_INCH / float(fig.dpi)
    return [float(px[0]) * scale, float(px[1]) * scale]


def count_draws(func):
    """统计一次捕获期间真实的 `Figure.draw` 次数（包装真实方法，不替身）。"""
    real = matplotlib.figure.Figure.draw
    calls: list[str] = []

    def counting(self, renderer):
        calls.append(type(renderer).__name__)
        return real(self, renderer)

    matplotlib.figure.Figure.draw = counting
    try:
        result = func()
    finally:
        matplotlib.figure.Figure.draw = real
    return result, calls


class _Boom(matplotlib.artist.Artist):
    """draw 时真正报错的图元：用来验证渲染器错误路径，不是 mock。"""

    def draw(self, renderer):
        raise RuntimeError('boom')


def _fake_frontend(root: Path) -> Path:
    """测试用前端静态资源：真实文件，导出逻辑照常复制。"""
    directory = root / "frontend"
    directory.mkdir(parents=True)
    (directory / "index.html").write_text(
        "<!DOCTYPE html><title>inspector</title>\n", encoding="utf-8")
    (directory / "inspector.js").write_text("globalThis.FigpactInspector = {};\n", encoding="utf-8")
    (directory / "inspector.css").write_text("body { margin: 0 }\n", encoding="utf-8")
    return directory


class ExportSafetyTest(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="figpact-inspector-safety-"))
        self._frontend = inspector._FRONTEND_DIR
        inspector._FRONTEND_DIR = _fake_frontend(self.td)
        self.fig = plt.figure(figsize=(40.0 / 25.4, 20.0 / 25.4), dpi=100)
        self.line, = self.fig.gca().plot([0.0, 1.0], [0.0, 1.0])

    def tearDown(self):
        inspector._FRONTEND_DIR = self._frontend
        plt.close("all")
        shutil.rmtree(self.td, ignore_errors=True)

    def test_export_refuses_existing_protected_directory_and_preserves_bytes(self):
        protected = self.td / "final-outputs"
        protected.mkdir()
        png = b"\x89PNG\r\n\x1a\nSCIENTIFIC-OUTPUT-BYTES"
        (protected / "Fig_S2_3_2_NMR.png").write_bytes(png)
        (protected / "peak_table.csv").write_bytes(b"ppm,intensity\n3.91,22\n")

        with self.assertRaises(inspector.InspectorError):
            inspector.export_inspector(self.fig, protected)

        self.assertEqual((protected / "Fig_S2_3_2_NMR.png").read_bytes(), png)
        self.assertEqual((protected / "peak_table.csv").read_bytes(), b"ppm,intensity\n3.91,22\n")
        self.assertEqual(sorted(p.name for p in protected.iterdir()),
                         ["Fig_S2_3_2_NMR.png", "peak_table.csv"])

    def test_export_does_not_remove_a_directory_created_during_capture(self):
        destination = self.td / "appeared-during-draw"
        self.fig.canvas.mpl_connect("draw_event", lambda event: destination.mkdir())
        with self.assertRaises(FileExistsError):
            inspector.export_inspector(self.fig, destination)
        self.assertTrue(destination.is_dir(), "Cleanup must not remove another writer's directory")

    def test_export_refuses_a_symlinked_target(self):
        real = self.td / "real-outputs"
        real.mkdir()
        (real / "keep.bin").write_bytes(b"KEEP")
        try:
            os.symlink(real, self.td / "link", target_is_directory=True)
        except OSError:
            self.skipTest("Windows 当前账号不能创建符号链接；该用例只在可创建符号链接的宿主上跑")

        with self.assertRaises(inspector.InspectorError):
            inspector.export_inspector(self.fig, self.td / "link")

        self.assertEqual((real / "keep.bin").read_bytes(), b"KEEP")
        self.assertEqual(sorted(p.name for p in real.iterdir()), ["keep.bin"])

    def test_export_refuses_targets_inside_source_or_frontend_directories(self):
        candidates = (ROOT / "tools" / "inspector" / "g1-new-export",
                      ROOT / "figpact" / "g1-new-export",
                      ROOT / "tests" / "g1-new-export")
        for candidate in candidates:
            with self.assertRaises(inspector.InspectorError):
                inspector.export_inspector(self.fig, candidate)
            self.assertFalse(candidate.exists(), f"不得创建目录：{candidate}")


class CaptureFrameTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_plain_figure_needs_no_yaml_and_keeps_scientific_payload_unchanged(self):
        fig, ax = mm_figure()
        curve, = ax.plot([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, np.nan, 0.0])
        pixels = np.arange(12, dtype=float).reshape(3, 4)
        image = ax.imshow(pixels)
        ax.text(1.0, 2.0, "no yaml label")
        collection = LineCollection([[(0.0, 0.0), (1.0, 1.0)], [(2.0, 2.0), (3.0, 0.0)]])
        ax.add_collection(collection)
        ydata = np.array(curve.get_ydata(), copy=True)
        array = np.array(image.get_array(), copy=True)
        segments = [np.array(seg, copy=True) for seg in collection.get_segments()]

        bundle = inspector.capture_figure(fig)          # 无 registry / contract / manifest
        np.testing.assert_array_equal(curve.get_ydata(), ydata)      # 含 NaN 原样不动
        np.testing.assert_array_equal(image.get_array(), array)
        self.assertEqual([np.array_equal(a, b) for a, b in zip(collection.get_segments(), segments)],
                         [True, True])
        scene_dict = json.loads(bundle["scene_json"])
        self.assertEqual(scene_dict["schema"], "figpact.inspector.scene/1")
        self.assertEqual(scene_dict["scope"], "measurement")
        self.assertIsNone(scene_dict["source_revision"])
        self.assertEqual(scene_dict["unit"], "mm")
        self.assertEqual(scene_dict["coordinate_reference"], "canvas_bottom_left")
        self.assertIs(scene_dict["measurement"]["calibrated"], False)
        self.assertIs(scene_dict["measurement"]["renderer_available"], True)

        again = inspector.capture_figure(fig)
        self.assertEqual(bundle["frame_revision"], again["frame_revision"])

    def test_single_draw_pairs_png_and_geometry(self):
        fig, ax = mm_figure()
        ax.set_xlim(0.0, 2.0)
        ax.set_ylim(0.0, 2.0)
        line, = ax.plot([0.0, 1.0, 2.0], [0.0, 2.0, 0.0])
        reg = GidRegistry(scope="measurement")
        reg.register(line, "fig.main.curve.a")

        bundle, calls = count_draws(
            lambda: inspector.capture_figure(fig, reg, scope="measurement"))
        self.assertEqual(calls, ["RendererAgg"])

        png = base64.b64decode(bundle["png_base64"])
        self.assertEqual(hashlib.sha256(png).hexdigest(), bundle["png_sha256"])
        self.assertEqual(Image.open(io.BytesIO(png)).format, "PNG")
        self.assertEqual(hashlib.sha256(bundle["scene_json"].encode("utf-8")).hexdigest(),
                         bundle["scene_sha256"])
        expected = hashlib.sha256(
            f"{bundle['png_sha256']}\n{bundle['scene_sha256']}".encode("ascii")).hexdigest()
        self.assertEqual(bundle["frame_revision"], expected)
        self.assertEqual(bundle["image_revision"], bundle["frame_revision"])
        self.assertEqual(bundle["geometry_revision"], bundle["frame_revision"])

        scene_dict = json.loads(bundle["scene_json"])
        nodes = {node["id"]: node for node in scene_dict["nodes"]}
        curve = nodes["fig.main.curve.a"]
        for point in curve["runs_mm"][0]:
            self.assertEqual(len(point), 2)
        for actual, expected_mm in ((curve["runs_mm"][0][0], data_mm(fig, ax, 0.0, 0.0)),
                                    (curve["runs_mm"][0][-1], data_mm(fig, ax, 2.0, 0.0))):
            for axis in (0, 1):
                self.assertAlmostEqual(actual[axis], expected_mm[axis], places=9)

    def test_science_payload_change_during_draw_is_refused(self):
        fig, ax = mm_figure()
        line, = ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
        reg = GidRegistry(scope="measurement")
        reg.register(line, "fig.main.curve.a")
        before = np.array(line.get_ydata(), copy=True)

        def mutate(event):
            line.set_ydata([0.0, 5.0, 0.0])      # 受保护载荷在 draw 中途变化

        fig.canvas.mpl_connect("draw_event", mutate)
        with self.assertRaises(inspector.InspectorError):
            inspector.capture_figure(fig, reg, scope="measurement")
        self.assertFalse(np.array_equal(np.asarray(line.get_ydata(), dtype=float),
                                        np.asarray(before, dtype=float)),
                         "回调必须真的改过数据，否则这不是一次真实的失败")

    def test_renderer_error_restores_the_original_canvas(self):
        fig = matplotlib.figure.Figure(figsize=(40.0 / 25.4, 20.0 / 25.4), dpi=100)
        fig.add_artist(_Boom())
        original = fig.canvas

        with self.assertRaises(inspector.InspectorError):
            inspector.capture_figure(fig, scope="measurement")

        self.assertIs(fig.canvas, original)


class ProjectionTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_marker_only_line_has_no_phantom_centerline_hit(self):
        fig, ax = mm_figure()
        marker_line, = ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 0.0], marker="o", linestyle="None")
        reg = GidRegistry(scope="measurement")
        reg.register(marker_line, "fig.main.curve.markers")

        bundle = inspector.capture_figure(fig, reg, scope="measurement")
        scene_dict = json.loads(bundle["scene_json"])
        node = {n["id"]: n for n in scene_dict["nodes"]}["fig.main.curve.markers"]
        self.assertIsNotNone(node["runs_mm"])       # 数据点几何真实存在
        self.assertEqual(node["hit_mode"], "none")
        self.assertIsNone(node["stroke"])
        self.assertIn("hit_note", node)
        self.assertIn("marker", node["hit_note"])

    def test_nan_and_clipping_keep_runs_disconnected(self):
        fig, ax = mm_figure()
        ax.set_xlim(0.0, 4.0)
        ax.set_ylim(0.0, 4.0)
        nan_line, = ax.plot([0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 1.0, np.nan, 1.0, 0.0])
        clipped, = ax.plot([0.0, 2.0, 4.0], [1.0, -1.0, 1.0])
        reg = GidRegistry(scope="measurement")
        reg.register(nan_line, "fig.main.curve.nan")
        reg.register(clipped, "fig.main.curve.clip")

        bundle = inspector.capture_figure(fig, reg, scope="measurement")
        nodes = {n["id"]: n for n in json.loads(bundle["scene_json"])["nodes"]}

        nan_runs = nodes["fig.main.curve.nan"]["runs_mm"]
        self.assertEqual(len(nan_runs), 2)
        self.assertAlmostEqual(nan_runs[0][0][0], data_mm(fig, ax, 0.0, 0.0)[0], places=9)
        self.assertAlmostEqual(nan_runs[0][-1][0], data_mm(fig, ax, 1.0, 0.0)[0], places=9)
        self.assertAlmostEqual(nan_runs[1][0][0], data_mm(fig, ax, 3.0, 0.0)[0], places=9)
        self.assertLess(nan_runs[0][-1][0], nan_runs[1][0][0])     # 断口没有被桥接
        xs = {point[0] for run in nan_runs for point in run}
        self.assertNotIn(data_mm(fig, ax, 2.0, 0.0)[0], xs)         # NaN 顶点不在任何段里

        clip_runs = nodes["fig.main.curve.clip"]["runs_mm"]
        self.assertEqual(len(clip_runs), 2)
        self.assertAlmostEqual(clip_runs[0][0][0], data_mm(fig, ax, 0.0, 0.0)[0], places=9)
        self.assertAlmostEqual(clip_runs[-1][-1][0], data_mm(fig, ax, 4.0, 0.0)[0], places=9)
        self.assertLess(clip_runs[0][-1][0], clip_runs[1][0][0])
        self.assertEqual(nodes["fig.main.curve.clip"]["hit_mode"], "stroke")

    def test_registered_and_unregistered_identities_are_labeled(self):
        fig, ax = mm_figure()
        line, = ax.plot([0.0, 1.0], [0.0, 1.0])
        ax.text(0.5, 0.5, "ephemeral label")
        reg = GidRegistry(scope="measurement")
        reg.register(line, "fig.main.curve.a")

        bundle = inspector.capture_figure(fig, reg, scope="measurement")
        nodes = {n["id"]: n for n in json.loads(bundle["scene_json"])["nodes"]}
        stable = nodes["fig.main.curve.a"]
        self.assertEqual(stable["identity_stability"], "stable")
        self.assertEqual(stable["gid"], "fig.main.curve.a")
        ephemeral = [n for n in nodes.values() if n.get("text") == "ephemeral label"]
        self.assertEqual(len(ephemeral), 1)
        self.assertEqual(ephemeral[0]["identity_stability"], "ephemeral")
        self.assertIsNone(ephemeral[0]["gid"])
        self.assertTrue(ephemeral[0]["id"].startswith("measurement::unregistered."))
        for node in (stable, ephemeral[0]):
            self.assertEqual(node["editable_capability"], "READ_ONLY")

    def test_non_integer_pixel_size_keeps_physical_pixels_and_logical_canvas_distinct(self):
        fig = plt.figure(figsize=(1.405, 1.0), dpi=100)      # 140.5 px → Agg 取 140 px
        fig.gca().plot([0.0, 1.0], [0.0, 1.0])

        bundle = inspector.capture_figure(fig, scope="measurement")
        scene_dict = json.loads(bundle["scene_json"])
        image = scene_dict["image"]
        self.assertEqual(image["width_px"], 140)
        self.assertEqual(image["height_px"], 100)
        for actual, expected in zip(image["bounds_mm"],
                                    [0.0, 0.0, 140 * 25.4 / 100, 100 * 25.4 / 100]):
            self.assertAlmostEqual(actual, expected, places=9)
        canvas_mm = scene_dict["canvas_bounds_mm"]
        self.assertAlmostEqual(canvas_mm[2], 1.405 * 25.4, places=9)
        self.assertAlmostEqual(canvas_mm[2] - image["bounds_mm"][2], 0.5 * 25.4 / 100, places=9)
        self.assertNotEqual(canvas_mm[2], image["bounds_mm"][2])
        png = base64.b64decode(bundle["png_base64"])
        self.assertEqual(Image.open(io.BytesIO(png)).size, (140, 100))

    def test_manifest_guides_and_labels_link_declared_pairs_only(self):
        fig, ax = mm_figure()
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 10.0)
        label = ax.text(3.0, 8.0, "3.91 ppm", fontsize=8)
        guide, = ax.plot([2.0, 4.0], [3.0, 7.0])
        decoy, = ax.plot([5.0, 6.0], [1.0, 2.0])          # gid 像引线也不得推断
        reg = GidRegistry(scope="measurement")
        reg.register(label, "fig2_nmr.main.peak.vancho.3p91", artist_type="Text")
        reg.register(guide, "fig2_nmr.main.guide.vancho.3p91", artist_type="Line2D (Guide)")
        reg.register(decoy, "fig2_nmr.main.guide.vancho.9p99", artist_type="Line2D (Guide)")
        manifest = {"science": {"protected": {"peak_anchors": {
            "fig2_nmr.main.peak.vancho.3p91": {
                "assignment": "vancho",
                "exact_ppm": 3.9123,
                "guide_anchor_data": [3.9123, 22.0],
                "guide_gid": "fig2_nmr.main.guide.vancho.3p91",
            }
        }}}}

        bundle = inspector.capture_figure(fig, reg, scope="measurement", science_manifest=manifest)
        nodes = {n["id"]: n for n in json.loads(bundle["scene_json"])["nodes"]}

        self.assertEqual(nodes["fig2_nmr.main.peak.vancho.3p91"]["linked_guide_gid"],
                         "fig2_nmr.main.guide.vancho.3p91")
        annotation = nodes["fig2_nmr.main.guide.vancho.3p91"]["annotation"]
        self.assertEqual(annotation["linked_label_gid"], "fig2_nmr.main.peak.vancho.3p91")
        self.assertEqual(annotation["declared_exact_ppm"], 3.9123)
        self.assertEqual(annotation["declared_guide_anchor_data"], [3.9123, 22.0])
        self.assertIs(annotation["independent_endpoint_editable"], False)
        for key, (x, y) in (("displayed_first_run_endpoint_mm", (2.0, 3.0)),
                            ("displayed_last_run_endpoint_mm", (4.0, 7.0))):
            for actual, expected in zip(annotation[key], data_mm(fig, ax, x, y)):
                self.assertAlmostEqual(actual, expected, places=9)
        self.assertNotIn("annotation", nodes["fig2_nmr.main.guide.vancho.9p99"])
        self.assertNotIn("linked_guide_gid", nodes["fig2_nmr.main.guide.vancho.9p99"])


class ExportFrameTest(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="figpact-inspector-frame-"))
        self._frontend = inspector._FRONTEND_DIR
        self.frontend = _fake_frontend(self.td)
        inspector._FRONTEND_DIR = self.frontend

    def tearDown(self):
        inspector._FRONTEND_DIR = self._frontend
        plt.close("all")
        shutil.rmtree(self.td, ignore_errors=True)

    def test_export_writes_data_only_frame_js_and_copies_assets(self):
        fig, ax = mm_figure()
        dangerous = '</script><script>alert(1)</script> "quoted" \\backslash'
        label = ax.text(0.5, 2.0, dangerous)
        line, = ax.plot([0.0, 1.0], [0.0, 1.0])
        reg = GidRegistry(scope="measurement")
        reg.register(label, "fig.main.text.label")
        reg.register(line, "fig.main.curve.a")
        neighbor = self.td / "neighbor.bin"
        neighbor.write_bytes(b"NEIGHBOR")

        out = self.td / "inspector-out"
        index = inspector.export_inspector(fig, out, reg, scope="measurement",
                                          source_revision="src-rev-1")
        self.assertEqual(index, out / "index.html")
        for name in ("index.html", "inspector.js", "inspector.css"):
            self.assertEqual((out / name).read_bytes(), (self.frontend / name).read_bytes())
        self.assertEqual(neighbor.read_bytes(), b"NEIGHBOR")

        frame_text = (out / "frame.js").read_text(encoding="utf-8")
        self.assertNotIn("</script>", frame_text)
        self.assertNotIn(dangerous, (out / "index.html").read_text(encoding="utf-8"))
        prefix = "window.FIGPACT_INSPECTOR_FRAME = JSON.parse("
        self.assertTrue(frame_text.startswith(prefix))
        literal = frame_text[len(prefix):].rstrip()
        self.assertTrue(literal.endswith(");"))
        bundle_from_file = json.loads(json.loads(literal[:-2]))

        direct = inspector.capture_figure(fig, reg, scope="measurement",
                                         source_revision="src-rev-1")
        self.assertEqual(bundle_from_file, direct)
        self.assertEqual(json.loads(bundle_from_file["scene_json"])["source_revision"],
                         "src-rev-1")

    def test_failed_export_cleans_only_its_own_partial_files(self):
        fig, ax = mm_figure()
        ax.plot([0.0, 1.0], [0.0, 1.0])
        out = self.td / "partial-out"
        missing = self.td / "frontend-missing.png"
        original = inspector._frontend_assets

        def broken_assets():
            return [self.frontend / "index.html", missing]

        inspector._frontend_assets = broken_assets
        try:
            with self.assertRaises(OSError):
                inspector.export_inspector(fig, out)
        finally:
            inspector._frontend_assets = original

        self.assertFalse(out.exists())
        self.assertTrue((self.frontend / "index.html").is_file())
        self.assertFalse(missing.exists())
        self.assertEqual(sorted(p.name for p in self.td.iterdir()), ["frontend"])
