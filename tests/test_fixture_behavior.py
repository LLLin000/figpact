"""合成夹具的行为回归：确定性、形状、峰位不变、scope 隔离、冲突素材可用。

全部调用仓库里真实的共享 API（figpact.qa / GidRegistry / config / inventory / transform），
不 mock、不比对文案字面量。
"""
from __future__ import annotations

import copy
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from figpact import inventory, qa
from figpact.config import ConfigError
from tests.fixtures import synth_data, synth_plot

ROOT = Path(__file__).resolve().parents[1]
FIG = synth_plot.FIGURE_ID


def _display_points(fig, reg, gid) -> np.ndarray:
    """曲线顶点在当前 dpi 下的显示坐标（像素）。"""
    fig.canvas.draw()
    line = reg.get(gid)
    return line.get_transform().transform(line.get_xydata())


def _gid(scope: str, kind: str, name: str) -> str:
    return f"{FIG}.{scope}.{kind}.{name}"


class DataTest(unittest.TestCase):
    def test_generators_are_deterministic(self):
        self.assertEqual(synth_data.export_signature(), synth_data.export_signature())
        c1, c2 = synth_data.synthetic_curves(), synth_data.synthetic_curves()
        for (x1, y1), (x2, y2) in zip(c1, c2):
            np.testing.assert_array_equal(x1, x2)
            np.testing.assert_array_equal(y1, y2)
        x1, y1 = synth_data.nmr_spectrum()
        x2, y2 = synth_data.nmr_spectrum()
        np.testing.assert_array_equal(x1, x2)
        np.testing.assert_array_equal(y1, y2)

    def test_shapes_and_peak_positions(self):
        sig = synth_data.export_signature()
        self.assertEqual(sig["n_curves"], 3)
        self.assertEqual([s[0] for s in sig["curve_shapes"]], [180, 180, 180])
        self.assertEqual(sig["nmr_shape"], [600, 600])
        self.assertEqual(sig["nmr_peak_ppm"], [7.26, 3.91, 2.02, 1.18])
        self.assertEqual(sig["bar_labels"], ["ctrl", "dose_1", "dose_2", "dose_3"])

        x, y = synth_data.nmr_spectrum()
        for ppm in synth_data.nmr_peak_ppm():
            i = int(np.abs(x - ppm).argmin())
            window = np.abs(x - ppm) <= 0.05
            self.assertEqual(float(y[i]), float(y[window].max()), f"峰位 {ppm} ppm 不在极值上")


class SeamTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_scope_and_schema_contracts(self):
        self.assertEqual(synth_plot.SCOPES, ("main", "annotated"))
        self.assertEqual(set(synth_plot.SCALARS), set(synth_plot.SCHEMA) - {"shifts_mm"})
        self.assertIsInstance(synth_plot.FIGURE_ID, str)

        cfg = synth_plot.load_config()
        self.assertEqual(set(cfg["shifts_mm"]), set(synth_plot.SCOPES))
        for scope, per_curve in cfg["shifts_mm"].items():
            self.assertEqual(set(per_curve), set(synth_plot.CURVE_IDS), scope)

    def test_list_params_groups_structure(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            synth_plot.list_params()
        out = buf.getvalue()
        keys = [k for _, entries in synth_plot.PARAM_GROUPS for k, _, _ in entries]
        self.assertTrue(keys)
        self.assertLessEqual(set(keys), set(synth_plot.SCALARS))
        # 每个 schema 参数都必须出现在某个分组里（参数目录不许漏）
        self.assertEqual(set(synth_plot.SCALARS) - set(keys), set())
        for key in keys:
            self.assertIn(key, out)

    def test_unknown_scope_rejected(self):
        with self.assertRaises(ValueError):
            synth_plot.build_figure_and_registry("compare")

    def test_config_validation_goes_through_engine(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.yaml"
            good.write_text(synth_plot.CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            synth_plot.load_config(good)

            bad_range = Path(td) / "range.yaml"
            bad_range.write_text(good.read_text(encoding="utf-8").replace("line_width: 0.8", "line_width: 99.0"),
                                 encoding="utf-8")
            with self.assertRaises(ConfigError):
                synth_plot.load_config(bad_range)

            bad_key = Path(td) / "key.yaml"
            bad_key.write_text(good.read_text(encoding="utf-8") + "\nwhoops: 1\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                synth_plot.load_config(bad_key)

            bad_scope = Path(td) / "scope.yaml"
            bad_scope.write_text(good.read_text(encoding="utf-8").replace("main: {a: 0.0", "main: {a: 0.0, zz: 1.0"),
                                  encoding="utf-8")
            with self.assertRaises(ConfigError):
                synth_plot.load_config(bad_scope)

    def test_import_produces_no_output(self):
        code = "import tests.fixtures.synth_plot as m; assert m.SCOPES == ('main', 'annotated')"
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                           cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, MPLBACKEND="Agg"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "", "模块导入不得写输出")


class ScopeIsolationTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_shift_only_moves_the_selected_scope(self):
        base = synth_plot.load_config()
        shifted = copy.deepcopy(base)
        shifted["shifts_mm"]["annotated"]["a"] = 3.0

        # 主图没变：改 annotated 的位移不许动 main
        f0, r0 = synth_plot.build_figure_and_registry("main", config=base)
        f1, r1 = synth_plot.build_figure_and_registry("main", config=shifted)
        np.testing.assert_allclose(_display_points(f0, r0, _gid("main", "curve", "a")),
                                   _display_points(f1, r1, _gid("main", "curve", "a")), atol=1e-9)

        # 标注版里只有 a 动了，且正好 3.0 mm
        a0, ar0 = synth_plot.build_figure_and_registry("annotated", config=base)
        a1, ar1 = synth_plot.build_figure_and_registry("annotated", config=shifted)
        p0 = _display_points(a0, ar0, _gid("annotated", "curve", "a"))
        p1 = _display_points(a1, ar1, _gid("annotated", "curve", "a"))
        moved_mm = (p1[:, 1] - p0[:, 1]) * qa.MM_PER_INCH / a1.dpi
        self.assertAlmostEqual(float(np.mean(moved_mm)), 3.0, delta=0.01)
        for sid in ("b", "c"):
            np.testing.assert_allclose(_display_points(a0, ar0, _gid("annotated", "curve", sid)),
                                       _display_points(a1, ar1, _gid("annotated", "curve", sid)), atol=1e-9)

    def test_scope_never_touches_scientific_data(self):
        ref_x = synth_data.synthetic_curves()[0][0]
        for scope in synth_plot.SCOPES:
            fig, reg = synth_plot.build_figure_and_registry(scope)
            for sid, (x, y) in zip(synth_plot.CURVE_IDS, synth_data.synthetic_curves()):
                line = reg.get(_gid(scope, "curve", sid))
                np.testing.assert_array_equal(line.get_xdata(), x)
                np.testing.assert_array_equal(line.get_ydata(), y)  # 位移只在 transform 上
            np.testing.assert_array_equal(ref_x, synth_data.synthetic_curves()[0][0])

    def test_bar_fixture_uses_the_same_seam(self):
        fig, reg = synth_plot.build_bar_figure_and_registry("main")
        for label in synth_plot.BAR_LABELS:
            self.assertIn(_gid("main", "bar", label), reg.all())
        inv = inventory(fig, reg)
        self.assertGreaterEqual(len(inv["items"]), len(synth_plot.BAR_LABELS) + 2)
        self.assertEqual(inv["unregistered"], [], "柱图 fixture 不该有未登记可见图元")
        self.assertAlmostEqual(inv["figure_dpi"], float(fig.dpi))


class ConflictMaterialTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_conflict_figure_reports_overlaps_and_on_curve_text(self):
        fig, _ = synth_plot.build_figure_and_registry("annotated", conflict=True)
        overlaps = qa.check_text_overlap(fig)
        self.assertTrue(overlaps, "故意重叠的两对标签必须被 QA 抓到")
        self.assertTrue(any("3p68" in s and "2p02" in s for s in overlaps), overlaps)
        self.assertTrue(any("4p11" in s and "1p05" in s for s in overlaps), overlaps)
        on_data = qa.check_text_on_data(fig, pad_px=1.0)
        self.assertTrue(any("probe" in s for s in on_data), on_data)

    def test_clean_scope_annotations_do_not_collide(self):
        fig, _ = synth_plot.build_figure_and_registry("annotated")
        problems = qa.check_text_overlap(fig) + qa.check_text_on_data(fig)
        for p in problems:
            self.assertNotIn("3p68", p)
            self.assertNotIn("2p02", p)
            self.assertNotIn("probe", p)

    def test_defect_material_is_really_unwired(self):
        # 1) NO_EFFECT 素材：只改 unused_knob，渲染快照必须一模一样
        base = synth_plot.load_config()
        other = copy.deepcopy(base)
        other["unused_knob"] = 9.0
        fa, ra = synth_plot.build_figure_and_registry("annotated", config=base)
        fb, rb = synth_plot.build_figure_and_registry("annotated", config=other)
        inv_a = inventory(fa, ra)
        self.assertEqual(inv_a["items"], inventory(fb, rb)["items"], "unused_knob 居然有渲染效果")
        self.assertNotIn("unused_knob", {p for it in inv_a["items"] for p in it["params"]})

        # 2) EFFECT_MISMATCH 素材：声明 label_font_pt，实际字号来自 axis_font_pt
        cfg = synth_plot.load_config()
        fig, reg = synth_plot.build_figure_and_registry("main")
        xlabel = reg.get(_gid("main", "xlabel"))
        self.assertEqual(reg.params_of(_gid("main", "xlabel")), ["label_font_pt"])
        self.assertAlmostEqual(float(xlabel.get_fontsize()), cfg["axis_font_pt"])
        self.assertNotAlmostEqual(float(xlabel.get_fontsize()), cfg["label_font_pt"])


if __name__ == "__main__":
    unittest.main()
