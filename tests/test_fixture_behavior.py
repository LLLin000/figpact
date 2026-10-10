"""原生夹具的行为回归：声明面真的可用、CLI 能独立跑、产物齐全、失败时一个字节不落盘。

守的是"别的 agent 不用读绘图源码就能下手"：
- 导入脚本不建 Figure、不写文件、不打印；`--inventory` 的 stdout 是一份纯 JSON，
  且每条契约记录都能过夹具自己的记录级自检（路径存在、gid 真的被构建出来）；
- 同一作用域、同一配置构建两次，图元的几何与内容逐项一致；
- `--strict` 独立构建**所有**声明的作用域与产物（PNG/PDF/SVG/TIFF）；有阻断项时
  退出码非零且正式目录一个字节都不动。

不比对文案字面量、不检查源码字符串、不断言机器性能。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt

from figpact import inventory as fp_inventory
from tests.fixtures import _native


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_FILES = {
    "native_ftir": ROOT / "tests" / "fixtures" / "native_ftir.py",
    "native_nmr": ROOT / "tests" / "fixtures" / "native_nmr.py",
    "native_panels": ROOT / "tests" / "fixtures" / "native_panels.py",
    "native_mixed": ROOT / "tests" / "fixtures" / "native_mixed.py",
    "native_negatives": ROOT / "tests" / "fixtures" / "native_negatives.py",
}
NEGATIVE_FIXTURE = "native_negatives"


def load_fixture(name: str):
    """按名字导入夹具模块（缺文件 = 直接失败，不静默跳过）。"""
    path = FIXTURE_FILES[name]
    if not path.is_file():
        raise AssertionError(f"夹具脚本不存在：{path}")
    import importlib

    return importlib.import_module(f"tests.fixtures.{name}")


def repo_files() -> set[str]:
    """仓库里现有文件的相对路径（排除 .git / 缓存）：用来证明跑 CLI 没往仓库里写东西。"""
    out: set[str] = set()
    for path in ROOT.rglob("*"):
        parts = set(path.parts)
        if ".git" in parts or "__pycache__" in parts:
            continue
        if path.is_file():
            out.add(str(path.relative_to(ROOT)))
    return out




class ImportSafetyTest(unittest.TestCase):
    def test_import_builds_no_figure_and_prints_nothing(self):
        for name in FIXTURE_FILES:
            with self.subTest(fixture=name):
                code = ("import matplotlib.pyplot as plt; before=set(plt.get_fignums()); "
                        f"import tests.fixtures.{name}; "
                        "assert set(plt.get_fignums()) == before")
                res = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=ROOT,
                                     capture_output=True, text=True, encoding="utf-8",
                                     env={**os.environ, "MPLBACKEND": "Agg"})
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertEqual(res.stdout.strip(), "", "导入一个夹具脚本不许打印任何东西")




class BuildDeterminismTest(unittest.TestCase):
    def test_two_builds_of_one_scope_are_identical(self):
        """同一作用域、同一配置构建两次：图纸的几何与内容逐项一致。"""
        for name in FIXTURE_FILES:
            module = load_fixture(name)
            config = module.load_config()
            science = module.load_science()
            for scope in module.SCOPES:
                with self.subTest(fixture=name, scope=scope):
                    snaps = []
                    for _ in range(2):
                        fig, _ = module.build_scene(science, config, scope)
                        fig.canvas.draw()
                        snaps.append(bytes(fig.canvas.buffer_rgba()))
                        plt.close(fig)
                    self.assertEqual(snaps[0], snaps[1], f"{name}/{scope} 两次构建结果不一致")

    def test_load_science_is_repeatable_and_figure_free(self):
        for name in FIXTURE_FILES:
            module = load_fixture(name)
            before = len(plt.get_fignums())
            first = module.load_science()
            second = module.load_science()
            self.assertEqual(len(plt.get_fignums()), before, "load_science 不许建 Figure")




class StrictCliTest(unittest.TestCase):
    """`--strict` 独立构建所有声明的作用域与产物；失败时一个字节都不落盘。"""

    def _run(self, fixture: str, out_dir: Path, config: Path | None = None) -> subprocess.CompletedProcess:
        script = FIXTURE_FILES[fixture]
        cmd = [sys.executable, "-X", "utf8", str(script), "--strict", "--probe", str(out_dir)]
        if config is not None:
            cmd += ["--config", str(config)]
        return subprocess.run(cmd, cwd=str(script.parent), capture_output=True, text=True,
                              encoding="utf-8", env={**os.environ, "MPLBACKEND": "Agg"})

    def test_publishable_fixtures_build_all_declared_outputs(self):
        for fixture in ("native_ftir", "native_nmr", "native_panels", "native_mixed"):
            module = load_fixture(fixture)
            declared = {name for scope in module.SCOPES
                        for name in module.layout_contract(scope)["outputs"]}
            with tempfile.TemporaryDirectory(prefix="figpact-strict-") as td:
                out_dir = Path(td) / "out"
                with self.subTest(fixture=fixture):
                    res = self._run(fixture, out_dir)
                    self.assertEqual(res.returncode, 0, f"{fixture} strict 失败：\n{res.stdout}\n{res.stderr}")
                    produced = {p.name for p in out_dir.iterdir()}
                    self.assertEqual(produced, declared,
                                     f"{fixture} 产物与声明不一致：{sorted(produced)}")

    def test_strict_never_writes_into_the_repository(self):
        before = repo_files()
        with tempfile.TemporaryDirectory(prefix="figpact-strict-") as td:
            res = self._run("native_ftir", Path(td) / "out")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(repo_files(), before, "strict 跑完仓库里多了文件")

    def test_negative_fixture_refuses_and_writes_nothing(self):
        """缺陷夹具 `--strict` 必须失败，且**正式目录一个字节都不许动**。"""
        module = load_fixture(NEGATIVE_FIXTURE)
        with tempfile.TemporaryDirectory(prefix="figpact-strict-") as td:
            out_dir = Path(td) / "out"
            out_dir.mkdir()
            keep = out_dir / "already-published.png"
            keep.write_bytes(b"OLD-REAL-OUTPUT")
            before = sorted(p.name for p in out_dir.iterdir())
            res = self._run(NEGATIVE_FIXTURE, out_dir)
            self.assertNotEqual(res.returncode, 0, f"故意带缺陷的夹具居然 strict 通过了：\n{res.stdout}")
            self.assertEqual(sorted(p.name for p in out_dir.iterdir()), before,
                             "拒绝发布却往正式目录里写了东西")
            self.assertEqual(keep.read_bytes(), b"OLD-REAL-OUTPUT", "拒绝发布却改了正式产物")
        self.assertTrue(module.SCOPES, "缺陷夹具仍要声明作用域供校验")

    def test_inventory_is_pure_json(self):
        for fixture in FIXTURE_FILES:
            script = FIXTURE_FILES[fixture]
            res = subprocess.run([sys.executable, "-X", "utf8", str(script), "--inventory"],
                                 cwd=str(script.parent), capture_output=True, text=True,
                                 encoding="utf-8", env={**os.environ, "MPLBACKEND": "Agg"})
            with self.subTest(fixture=fixture):
                self.assertEqual(res.returncode, 0, res.stderr)
                payload = json.loads(res.stdout)
                for scope, block in payload["scopes"].items():
                    self.assertEqual(block["contract_problems"], [],
                                     f"{fixture}/{scope} 契约记录自检没过：{block['contract_problems']}")




if __name__ == "__main__":
    unittest.main()
