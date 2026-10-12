"""`examples/python_native/simple_figure.py`（纯 Python 原生样例）的自洽检查。

两件事，都打在可观测事实上：
① 现有会话机制能装载它（`load_science` / `build_scene` 原生接缝），图元 gid 稳定；
② **源码级扰动**：把 `LAYOUT_MM` 里 A 的字面量改成 `[0, 0.2]` 后真实重建，
   只有 A 的包围盒按声明的毫米走（实测位移与请求值一起断言），B、曲线与其余全部
   可见几何一动不动。
"""
from __future__ import annotations

import ast
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402

from figpact.session import FigureSession, drawn_shapes, load_module_cached  # noqa: E402

EXAMPLE = ROOT / "examples" / "python_native" / "simple_figure.py"
CURVE = "intent.main.curve"
LABEL_A = "intent.main.label.A"
LABEL_B = "intent.main.label.B"
GIDS = (CURVE, LABEL_A, LABEL_B)
#: 扰动要写入源码的字面量（唯一匹配），以及请求的 A 位移（毫米）。
A_LITERAL = '"intent.main.label.A": [0.0, 0.0]'
A_SHIFTED_LITERAL = '"intent.main.label.A": [0.0, 0.2]'
SHIFT_REQUESTED_MM = (0.0, 0.2)
TOL_MM = 0.01


def _tree(directory: Path) -> list[str]:
    """目录内容清单（`__pycache__` 是装载器的字节码缓存，不是样例的副作用）。"""
    return sorted(str(p.relative_to(directory)) for p in directory.rglob("*")
                  if "__pycache__" not in p.parts)


def measured_geometry(script: Path, config: Path, scope: str = "main"):
    """现有会话机制真实重建一次 → `({实测 mm 包围盒}, [注册 gid])`。

    用公开的 `build_candidate` + `drawn_shapes`（与 `tests/test_session.py` 同一套约定）：
    注册过的图元按 `gid:<gid>` 记名，未注册的按「轴序号 + 类型 + 序号」记名 —— 于是
    「只有 A 动了」这条断言覆盖图上**全部**可见几何，而不是只看两个已知 gid。
    """
    with FigureSession(script, config, scope) as session:
        fig, reg = session.build_candidate(session.candidate_config)
        try:
            shapes = drawn_shapes(fig, reg, include_frames=True)
        finally:
            plt.close(fig)
        gids = sorted(reg.gids())
    geometry = {key: list(rec["bbox_mm"]) for key, rec in shapes.items()
                if rec.get("bbox_mm") is not None}
    return geometry, gids


class PythonNativeExampleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="figpact-python-native-")
        self.root = Path(self._tmp.name)
        # 会话机制按契约要求一个配置**路径**（YAML）；本样例自身不含 YAML（排版位移在
        # 源码里、`build_scene` 不读 config），所以给一份空映射就够。
        self.config = self.root / "simple_figure.yaml"
        self.config.write_text("{}\n", encoding="utf8")

    def tearDown(self):
        plt.close("all")
        self._tmp.cleanup()

    def _perturbed_script(self) -> Path:
        """A 的字面量改成 `[0, 0.2]` 的源码副本（保留原有目录深度，`parents[2]` 引导仍成立）。"""
        source = EXAMPLE.read_text(encoding="utf8")
        self.assertEqual(source.count(A_LITERAL), 1, "样例里 A 的绑定字面量必须唯一、可定位")
        target = self.root / "examples" / "python_native" / EXAMPLE.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.replace(A_LITERAL, A_SHIFTED_LITERAL), encoding="utf8")
        return target

    def test_session_mechanism_loads_example_and_gids_are_stable(self):
        figures_before, tree_before = plt.get_fignums(), _tree(EXAMPLE.parent)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            module = load_module_cached(EXAMPLE, self.config)
        self.assertEqual(buffer.getvalue(), "", "导入样例不许打印")
        self.assertEqual(plt.get_fignums(), figures_before, "导入样例不许建 Figure")
        self.assertEqual(_tree(EXAMPLE.parent), tree_before, "导入样例不许写出任何文件")
        self.assertTrue(callable(module.load_science))
        self.assertTrue(callable(module.build_scene))
        self.assertEqual(tuple(module.SCOPES), ("main",))
        self.assertEqual(sorted(module.LAYOUT_MM), sorted((LABEL_A, LABEL_B)))

        geometry, gids = measured_geometry(EXAMPLE, self.config)
        self.assertEqual(gids, sorted(GIDS), "注册的图元身份必须是这三个 gid")
        for gid in GIDS:
            self.assertIn(f"gid:{gid}", geometry, f"{gid} 的显示几何必须实测得到")

    def test_shifting_label_a_literal_moves_only_label_a(self):
        baseline, gids_base = measured_geometry(EXAMPLE, self.config)
        perturbed, gids_shifted = measured_geometry(self._perturbed_script(), self.config)
        self.assertEqual(gids_shifted, gids_base, "源码扰动不许改变图元身份")
        self.assertEqual(sorted(perturbed), sorted(baseline), "可见几何的键集合必须一致")
        for gid in GIDS:
            self.assertIn(f"gid:{gid}", baseline, f"{gid} 必须在基线里被实测到")
            self.assertIn(f"gid:{gid}", perturbed, f"{gid} 必须在扰动重建里被实测到")

        # 请求值 vs 实测位移：一起断言（容差 0.01 mm）。
        moved = [perturbed[f"gid:{LABEL_A}"][index] - baseline[f"gid:{LABEL_A}"][index]
                 for index in (0, 1)]
        for index, (requested, measured) in enumerate(zip(SHIFT_REQUESTED_MM, moved)):
            self.assertAlmostEqual(
                measured, requested, delta=TOL_MM,
                msg=f"A 的 {'xy'[index]} 位移实测 {measured!r} mm，请求 {requested!r} mm")

        # A 之外的一切（B、曲线、坐标框、刻度文字……）一个毫米都不许动。
        for key in sorted(baseline):
            if key == f"gid:{LABEL_A}":
                continue
            for index, (was, now) in enumerate(zip(baseline[key], perturbed[key])):
                self.assertAlmostEqual(
                    now - was, 0.0, delta=TOL_MM,
                    msg=f"{key} 跟着 A 动了（{'xyxy'[index]}：{was} → {now}）")

    def test_example_has_no_yaml_and_no_ambient_inputs(self):
        source = EXAMPLE.read_text(encoding="utf8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported & {"yaml", "random", "time", "datetime", "os", "glob"}, set(),
                         "样例不许有 YAML 依赖，也不许引入随机/时间/环境")

        module = load_module_cached(EXAMPLE, self.config)
        science = module.load_science()
        self.assertEqual(sorted(science), ["x", "y"])
        self.assertEqual(science, module.load_science(), "科研载荷必须确定性：同样的输入同样的数组")


if __name__ == "__main__":
    unittest.main()
