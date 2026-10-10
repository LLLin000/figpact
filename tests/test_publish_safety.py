"""发布安全与毫米测量：试算沙箱不许碰正式文件；毫米/dpi 关系按**测量口径**分别断言。

全部走 `figpact.publish` / `figpact.qa` / 原生夹具的真 API，不 mock。
位移、面板外框、比例尺长度是**数学几何**量（1e-6 mm）；文字的墨迹宽度是**光栅化**量，
不当作物理单位保证（同 dpi 重复测量逐位一致，跨 dpi 只保证同量级）。
"""
from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from figpact import inventory, publish, qa
from figpact.units import MM_PER_INCH
from tests.fixtures import fixture_data

ROOT = Path(__file__).resolve().parents[1]
FTIR = ROOT / "tests" / "fixtures" / "native_ftir.py"
TOL_VECTOR_MM = 1e-6


def load(name: str):
    import importlib

    return importlib.import_module(f"tests.fixtures.{name}")


def _vertex_mm(fig, art, index: int = 0) -> tuple[float, float]:
    """折线顶点在画布上的毫米坐标（数学几何，不经光栅化）。"""
    fig.canvas.draw()
    pts = art.get_transform().transform(art.get_xydata())
    scale = MM_PER_INCH / float(fig.dpi)
    return (float(pts[index, 0]) * scale, float(pts[index, 1]) * scale)


def _curve_gid(fig, reg, scope: str, sid: str) -> str:
    inv = {item["gid"]: item for item in inventory(fig, reg)["items"]}
    for gid, item in inv.items():
        if gid.endswith(f".curve.{sid}") and f".{scope}." in gid:
            return gid
    raise AssertionError(f"找不到 {scope} 的曲线 {sid}")


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


class StrictRunIsolationTest(unittest.TestCase):
    """端到端：正式输出目录里已有旧文件时，试算（FIGPACT_PROBE_DIR）不得碰它。"""

    def tearDown(self):
        plt.close("all")

    def _run_strict(self, out_dir: Path, probe_env: Path | None) -> subprocess.CompletedProcess:
        env = {**os.environ, "MPLBACKEND": "Agg"}
        if probe_env is not None:
            env[publish.PROBE_ENV] = str(probe_env)
        return subprocess.run([sys.executable, "-X", "utf8", str(FTIR), "--strict", "--out", str(out_dir)],
                              cwd=str(FTIR.parent), capture_output=True, text=True, encoding="utf-8",
                              env=env)

    def test_official_output_survives_a_probe_run(self):
        with tempfile.TemporaryDirectory(prefix="figpact-strict-") as td:
            root = Path(td)
            official = root / "official"
            official.mkdir()
            (official / "fig_ftir_native_main.png").write_bytes(b"OLD-PNG")
            sandbox = root / "probe"

            res = self._run_strict(official, sandbox)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual((official / "fig_ftir_native_main.png").read_bytes(), b"OLD-PNG")
            self.assertEqual(sorted(p.name for p in official.iterdir()), ["fig_ftir_native_main.png"])
            self.assertTrue(list(sandbox.glob("fig_ftir_native_main.png")))

    def test_official_output_is_replaced_when_no_probe_is_active(self):
        with tempfile.TemporaryDirectory(prefix="figpact-strict-") as td:
            official = Path(td) / "official"
            official.mkdir()
            (official / "fig_ftir_native_main.png").write_bytes(b"OLD-PNG")

            res = self._run_strict(official, None)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertNotEqual((official / "fig_ftir_native_main.png").read_bytes(), b"OLD-PNG")
            module = load("native_ftir")
            declared = {name for scope in module.SCOPES
                        for name in module.layout_contract(scope)["outputs"]}
            self.assertEqual({p.name for p in official.iterdir()}, declared)


class MillimetreTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_declared_shift_is_exactly_that_many_millimetres_at_any_dpi(self):
        module = load("native_ftir")
        scope = "main"
        base_cfg = module.load_config()
        moved_cfg = copy.deepcopy(base_cfg)
        moved_cfg["shifts_mm"][scope]["b"] = 3.0

        for dpi in (120, 300):
            base_cfg["render_dpi"] = dpi
            moved_cfg["render_dpi"] = dpi
            base_fig, base_reg = module.build_scene(module.load_science(), base_cfg, scope)
            moved_fig, moved_reg = module.build_scene(module.load_science(), moved_cfg, scope)
            try:
                self.assertEqual(float(moved_fig.dpi), float(dpi))
                self.assertEqual(float(inventory(moved_fig, moved_reg)["figure_dpi"]), float(dpi))
                gid = _curve_gid(base_fig, base_reg, scope, "b")
                before = _vertex_mm(base_fig, base_reg.get(gid))
                after = _vertex_mm(moved_fig, moved_reg.get(gid))
                self.assertAlmostEqual(after[1] - before[1], 3.0, delta=TOL_VECTOR_MM,
                                       msg=f"dpi={dpi} 时 3 mm 位移量出来是 {after[1] - before[1]:.6f} mm")
                self.assertAlmostEqual(after[0] - before[0], 0.0, delta=TOL_VECTOR_MM)
            finally:
                plt.close(base_fig)
                plt.close(moved_fig)

    def test_label_lift_is_millimetres_not_data_units(self):
        """修过的那处：标签上抬走毫米显示位移，数据锚点与数据单位换算无关。"""
        module = load("native_ftir")
        scope = "main"
        base_cfg = module.load_config()
        moved_cfg = copy.deepcopy(base_cfg)
        moved_cfg["band_label_lift_mm"] = base_cfg["band_label_lift_mm"] + 1.5

        base_fig, base_reg = module.build_scene(module.load_science(), base_cfg, scope)
        moved_fig, moved_reg = module.build_scene(module.load_science(), moved_cfg, scope)
        try:
            label_gid = next(g for g in base_reg.all()
                             if g.endswith(".band_label.oh"))
            base_label = base_reg.get(label_gid)
            moved_label = moved_reg.get(label_gid)
            self.assertEqual(tuple(base_label.get_position()), tuple(moved_label.get_position()),
                             "数据坐标被改动了：上抬必须只走显示位移")
            base_pt = base_label.get_transform().transform(base_label.get_position())
            moved_pt = moved_label.get_transform().transform(moved_label.get_position())
            scale = MM_PER_INCH / float(base_fig.dpi)
            self.assertAlmostEqual((moved_pt[1] - base_pt[1]) * scale, 1.5, delta=TOL_VECTOR_MM)
        finally:
            plt.close(base_fig)
            plt.close(moved_fig)


    def test_qa_verdicts_are_dpi_independent(self):
        module = load("native_ftir")
        results = {}
        for dpi in (120, 300):
            cfg = module.load_config()
            cfg["render_dpi"] = dpi
            for scope in module.SCOPES:
                fig, reg = module.build_scene(module.load_science(), cfg, scope)
                fig.canvas.draw()
                results[(scope, dpi)] = (
                    tuple(qa.check_out_of_frame(fig)),
                    len(qa.check_edge_clearance(fig)),
                    len(qa.check_text_overlap(fig)),
                    len(qa.check_text_on_data(fig)),
                )
                plt.close(fig)
        for scope in module.SCOPES:
            self.assertEqual(results[(scope, 120)], results[(scope, 300)],
                             f"{scope} 的 QA 判据在 120/300 dpi 下结论不一致："
                             f"{results[(scope, 120)]} vs {results[(scope, 300)]}")


class PanelPublishSafetyTest(unittest.TestCase):
    """显微图夹具的像素不许因为"保存一次"就变：发布前后字节相同。"""

    def tearDown(self):
        plt.close("all")

    def test_saving_does_not_mutate_the_protected_pixels(self):
        module = load("native_panels")
        before = fixture_data.science_digest()
        cfg = module.load_config()
        with tempfile.TemporaryDirectory(prefix="figpact-panels-") as td:
            for scope in module.SCOPES:
                fig, reg = module.build_scene(module.load_science(), cfg, scope)
                try:
                    target = Path(td) / f"{scope}.png"
                    fig.savefig(target, dpi=float(cfg["render_dpi"]))
                    self.assertGreater(target.stat().st_size, 0)
                finally:
                    plt.close(fig)
        self.assertEqual(fixture_data.science_digest(), before, "渲染过程改动了受保护数组")
        arrays = [np.asarray(fixture_data.micrograph(pid)) for pid in fixture_data.PANEL_IDS]
        for array in arrays:
            self.assertFalse(array.flags.writeable, "受保护像素数组必须只读")


if __name__ == "__main__":
    unittest.main()
