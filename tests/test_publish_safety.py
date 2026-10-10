"""发布安全与毫米测量：试算沙箱不许碰正式文件；mm 与 dpi 无关。

全部走 `figpact.publish` / `figpact.qa` / `GidRegistry` 真 API。
"""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from figpact import inventory, publish, qa
from tests.fixtures import synth_plot

FIG = synth_plot.FIGURE_ID


def _display_points(fig, reg, gid) -> np.ndarray:
    fig.canvas.draw()
    line = reg.get(gid)
    return line.get_transform().transform(line.get_xydata())


def _width_mm(fig, artist) -> float:
    """把任意 artist 的显示包围盒换成毫米 —— 这就是 QA 判据用的换算。"""
    fig.canvas.draw()
    bb = artist.get_window_extent(fig.canvas.get_renderer())
    return float(bb.width) * qa.MM_PER_INCH / float(fig.dpi)


class ProbeIsolationTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="figpact-test-")
        self.root = Path(self.td)
        self.staging = publish.staging_dir("figpact-test-stage-")
        (self.staging / "Fig9.png").write_bytes(b"CANDIDATE")
        (self.staging / "Fig9.pdf").write_bytes(b"CANDIDATE-PDF")
        self._old_env = os.environ.get(publish.PROBE_ENV)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop(publish.PROBE_ENV, None)
        else:
            os.environ[publish.PROBE_ENV] = self._old_env
        shutil.rmtree(self.staging, ignore_errors=True)
        shutil.rmtree(self.td, ignore_errors=True)
        plt.close("all")

    def test_probe_run_never_touches_official_output(self):
        official = self.root / "official"
        official.mkdir()
        (official / "Fig9.png").write_bytes(b"OFFICIAL")
        sandbox = self.root / "sandbox"

        os.environ[publish.PROBE_ENV] = str(sandbox)
        self.assertEqual(publish.probe_dir(), sandbox)
        written = publish.publish(self.staging, official)

        self.assertEqual(sorted(written), ["Fig9.pdf", "Fig9.png"])
        self.assertEqual((official / "Fig9.png").read_bytes(), b"OFFICIAL", "试算动了正式文件")
        self.assertEqual(sorted(p.name for p in official.iterdir()), ["Fig9.png"], "试算往正式目录写了新文件")
        self.assertEqual((sandbox / "Fig9.png").read_bytes(), b"CANDIDATE")
        self.assertEqual(sorted(p.name for p in sandbox.iterdir()), ["Fig9.pdf", "Fig9.png"])
        self.assertEqual(list(official.glob(".tmp_*")), [], "正式目录里留下了临时文件")
        self.assertEqual(list(sandbox.glob(".tmp_*")), [], "沙箱里留下了临时文件")

    def test_publish_without_probe_replaces_target_atomically(self):
        target = self.root / "out"
        target.mkdir()
        (target / "Fig9.png").write_bytes(b"OLD")
        self.assertIsNone(publish.probe_dir())

        written = publish.publish(self.staging, target)
        self.assertEqual(sorted(written), ["Fig9.pdf", "Fig9.png"])
        self.assertEqual((target / "Fig9.png").read_bytes(), b"CANDIDATE")
        self.assertTrue((target / "Fig9.pdf").is_file())
        self.assertEqual(list(target.glob(".tmp_*")), [])


class MillimetreTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_shift_is_exactly_the_mm_asked_for_at_any_dpi(self):
        base = synth_plot.load_config()
        shifted = copy.deepcopy(base)
        shifted["shifts_mm"]["annotated"]["a"] = 3.0
        gid = f"{FIG}.annotated.curve.a"

        for dpi in (120, 300):
            with matplotlib.rc_context({"figure.dpi": dpi}):
                f0, r0 = synth_plot.build_figure_and_registry("annotated", config=base)
                f1, r1 = synth_plot.build_figure_and_registry("annotated", config=shifted)
                self.assertEqual(float(f1.dpi), float(dpi))
                # inventory 报的 dpi 必须就是这张图的 dpi（换算是靠它，不是写死的 300）
                self.assertEqual(float(inventory(f1, r1)["figure_dpi"]), float(dpi))

                p0 = _display_points(f0, r0, gid)
                p1 = _display_points(f1, r1, gid)
                moved_mm = (p1[:, 1] - p0[:, 1]) * qa.MM_PER_INCH / dpi
                self.assertAlmostEqual(float(np.mean(moved_mm)), 3.0, delta=0.01,
                                       msg=f"dpi={dpi} 时 3 mm 位移量出来是 {float(np.mean(moved_mm)):.3f} mm")
                # 只动竖直方向
                np.testing.assert_allclose(p1[:, 0], p0[:, 0], atol=1e-9)

    def test_text_measurement_in_mm_is_dpi_independent(self):
        widths = {}
        for dpi in (120, 300):
            with matplotlib.rc_context({"figure.dpi": dpi}):
                fig, reg = synth_plot.build_figure_and_registry("annotated")
                widths[dpi] = _width_mm(fig, reg.get(f"{FIG}.annotated.xlabel"))
        self.assertAlmostEqual(widths[120], widths[300], delta=0.05,
                               msg=f"同一段文字的毫米宽度随 dpi 变了：{widths}")

    def test_qa_thresholds_are_dpi_independent(self):
        results = {}
        for dpi in (120, 300):
            with matplotlib.rc_context({"figure.dpi": dpi}):
                fig, _ = synth_plot.build_figure_and_registry("annotated")
                results[dpi] = (
                    qa.check_out_of_frame(fig),
                    len(qa.check_edge_clearance(fig)),
                    len(qa.check_text_overlap(fig)),
                    len(qa.check_text_on_data(fig)),
                )
        self.assertEqual(results[120], results[300],
                         f"QA 判据在 120/300 dpi 下结论不一致：{results}")


if __name__ == "__main__":
    unittest.main()
