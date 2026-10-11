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


class FigureImagePublicationQATest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_visible_figure_image_cropping_blocks_publication_without_a_gid(self):
        for registered in (False, True):
            with self.subTest(registered=registered):
                fig = plt.figure(figsize=(1, 1), dpi=100)
                image = fig.figimage(np.zeros((10, 10)), xo=80, yo=80)
                if registered:
                    image.set_gid("fig.main.image.specimen")
                self.assertEqual(qa.check_out_of_frame(fig), [])
                image.ox = 96
                diagnostics = [qa.diagnose(p) for p in qa.check_out_of_frame(fig,
                                                                            gid_filter="curve")]
                diagnostic, = diagnostics
                self.assertEqual(diagnostic.rule_id, "OUT_OF_FRAME")
                self.assertEqual(diagnostic.severity, "blocking")
                self.assertAlmostEqual(diagnostic.measured, 1.52, places=2)
                plt.close(fig)

    def test_unmeasurable_figure_image_is_a_publication_blocker(self):
        fig = plt.figure(figsize=(1, 1), dpi=100)
        fig.figimage(np.zeros((3, 4)), xo=float("nan"), yo=40)
        diagnostic, = [qa.diagnose(p) for p in qa.check_out_of_frame(fig)]
        self.assertEqual(diagnostic.rule_id, "UNMEASURED_GEOMETRY")
        self.assertEqual(diagnostic.severity, "blocking")


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


def _nested_fixture_source(prefix: str = "panels/") -> str:
    """原生夹具的私有包装脚本：把每个作用域声明的产物都加一层目录。

    只改**声明**：构建、科学自检、严格门、`publish()` 全是生产那套（`runpy` 进它的
    `__main__`），所以验的是真实的私有严格发布，不是 `_install` 级别的替身。
    """
    return (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from tests.fixtures.native_ftir import *\n"
        "\n"
        "\n"
        "_fixture_contract = layout_contract\n"
        "\n"
        "\n"
        "def layout_contract(scope):\n"
        "    contract = dict(_fixture_contract(scope))\n"
        f'    contract["outputs"] = ["{prefix}" + name for name in contract["outputs"]]\n'
        "    return contract\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    from tests.fixtures import _native\n"
        "    raise SystemExit(_native.run(sys.modules[__name__]))\n"
    )


class NestedArtifactPublishTest(unittest.TestCase):
    """声明成 `panels/<名字>` 的产物：暂存与发布都按相对路径落成真目录，平铺行为逐字不变。"""

    def tearDown(self):
        plt.close("all")

    def test_nested_declared_artifacts_publish_under_their_relative_directory(self):
        """端到端：私有严格发布必须真的产出 `<out>/panels/…`，不是被静默丢掉。"""
        with tempfile.TemporaryDirectory(prefix="figpact-nested-") as td:
            root = Path(td)
            script = root / "nested_ftir.py"
            config = root / "nested_ftir.yaml"
            shutil.copyfile(ROOT / "tests" / "fixtures" / "native_ftir.yaml", config)
            script.write_text(_nested_fixture_source(), encoding="utf-8")
            module = load("native_ftir")
            declared = sorted({f"panels/{name}" for scope in module.SCOPES
                               for name in module.layout_contract(scope)["outputs"]})
            self.assertTrue(declared, "夹具必须声明发布产物")

            out = root / "official"
            (out / "panels").mkdir(parents=True)
            replaced = out / declared[0]
            replaced.write_bytes(b"OLD-NESTED")

            env = {**os.environ, "MPLBACKEND": "Agg"}
            env.pop(publish.PROBE_ENV, None)
            res = subprocess.run([sys.executable, "-X", "utf8", str(script), "--config", str(config),
                                  "--strict", "--out", str(out)],
                                 cwd=str(root), capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            for name in declared:
                artifact = out / name
                self.assertTrue(artifact.is_file() and artifact.stat().st_size > 0,
                                f"声明的嵌套产物没有落地：{name}")
            self.assertNotEqual(replaced.read_bytes(), b"OLD-NESTED", "已存在的嵌套产物必须被替换")
            for name in declared:
                flat = out / Path(name).name
                self.assertFalse(flat.exists(), f"产物不该平铺在目标根：{flat.name}")
            self.assertEqual(list(out.rglob(".tmp_*")), [], "嵌套目录里留下了临时文件")

    def test_probe_run_keeps_nested_artifacts_in_the_sandbox(self):
        """嵌套产物在试算模式下同样只进沙箱：正式目录里的同名嵌套文件一个字节都不动。"""
        with tempfile.TemporaryDirectory(prefix="figpact-nested-") as td:
            root = Path(td)
            staging = publish.staging_dir("figpact-test-nested-")
            (staging / "panels").mkdir()
            (staging / "panels" / "Fig9.png").write_bytes(b"CANDIDATE")
            (staging / "Fig9.pdf").write_bytes(b"CANDIDATE-PDF")
            official = root / "official"
            (official / "panels").mkdir(parents=True)
            (official / "panels" / "Fig9.png").write_bytes(b"OFFICIAL")
            sandbox = root / "sandbox"

            old = os.environ.get(publish.PROBE_ENV)
            try:
                os.environ[publish.PROBE_ENV] = str(sandbox)
                written = publish.publish(staging, official)
            finally:
                if old is None:
                    os.environ.pop(publish.PROBE_ENV, None)
                else:
                    os.environ[publish.PROBE_ENV] = old
                shutil.rmtree(staging, ignore_errors=True)

            self.assertEqual(sorted(written), ["Fig9.pdf", "panels/Fig9.png"])
            self.assertEqual((official / "panels" / "Fig9.png").read_bytes(), b"OFFICIAL", "试算动了正式文件")
            self.assertEqual(sorted(p.name for p in official.iterdir()), ["panels"],
                             "试算在正式目录里留下了新文件")
            self.assertEqual((sandbox / "panels" / "Fig9.png").read_bytes(), b"CANDIDATE")
            self.assertEqual((sandbox / "Fig9.pdf").read_bytes(), b"CANDIDATE-PDF")
            self.assertEqual(list(official.rglob(".tmp_*")), [], "正式目录里留下了临时文件")
            self.assertEqual(list(sandbox.rglob(".tmp_*")), [], "沙箱里留下了临时文件")

    def test_publish_refuses_a_staged_link_that_leaves_the_staging_root(self):
        """暂存目录里的符号链接指向根外：拒绝，且目标根里一个字节都不落。"""
        with tempfile.TemporaryDirectory(prefix="figpact-nested-") as td:
            root = Path(td)
            outside = root / "outside"
            outside.mkdir()
            (outside / "stolen.png").write_bytes(b"OUTSIDE")
            target = root / "official"
            target.mkdir()
            staging = publish.staging_dir("figpact-test-escape-")
            old = os.environ.pop(publish.PROBE_ENV, None)
            try:
                (staging / "panels").mkdir()
                try:
                    os.symlink(outside / "stolen.png", staging / "panels" / "leak.png")
                except (OSError, NotImplementedError, AttributeError):
                    self.skipTest("这个平台/权限建不了符号链接，来源逃逸无从验证")
                with self.assertRaises(ValueError):
                    publish.publish(staging, target)
                self.assertEqual(sorted(p.name for p in target.iterdir()), [],
                                 "被拒绝的发布不得在目标根里留下东西")
                self.assertEqual((outside / "stolen.png").read_bytes(), b"OUTSIDE")
            finally:
                if old is not None:
                    os.environ[publish.PROBE_ENV] = old
                shutil.rmtree(staging, ignore_errors=True)

    def test_publish_refuses_a_destination_parent_that_leaves_the_target_root(self):
        """目标根里的父目录是指向根外的符号链接：拒绝，链接那头一个字节都不落。"""
        with tempfile.TemporaryDirectory(prefix="figpact-nested-") as td:
            root = Path(td)
            outside = root / "outside"
            outside.mkdir()
            staging = publish.staging_dir("figpact-test-escape-")
            (staging / "panels").mkdir()
            (staging / "panels" / "Fig9.png").write_bytes(b"CANDIDATE")
            target = root / "official"
            target.mkdir()
            old = os.environ.pop(publish.PROBE_ENV, None)
            try:
                try:
                    os.symlink(outside, target / "panels", target_is_directory=True)
                except (OSError, NotImplementedError, AttributeError):
                    self.skipTest("这个平台/权限建不了目录符号链接，目标逃逸无从验证")
                with self.assertRaises(ValueError):
                    publish.publish(staging, target)
                self.assertEqual(sorted(p.name for p in outside.iterdir()), [],
                                 "符号链接不得把产物写到目标根之外")
            finally:
                if old is not None:
                    os.environ[publish.PROBE_ENV] = old
                shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
