#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 原生样例：一条曲线 + 两个文本标签，排版绑定**写在源码里**（没有 YAML）。

对引擎声明的接缝，与 `examples/nmr/08 NMR.py` 同一套约定（不新造机制）：
`FIGURE_ID / SCOPES / load_science / build_scene / build_figure_and_registry`。
导入本模块：不解析 argv、不建 Figure、不渲染、不写文件、不打印。

排版：唯一来源是下面的 `LAYOUT_MM`（gid → `[dx, dy]`，毫米）。`build_scene` 把它当
标签的**显示位移**叠加在数据锚点上；值只影响排版，不参与任何科学计算。
科学：确定性解析高斯曲线，无随机、无时间、不读外部文件。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:  # 直接以脚本方式运行（cwd 可能是任意目录）也能 import figpact
    sys.path.insert(0, _ROOT)

import matplotlib.pyplot as plt  # noqa: E402

from figpact import GidRegistry, apply_display_shift  # noqa: E402

# ── 对外身份（**不是配置项**：gid 是外部引用认的名字） ───────────────────────
FIGURE_ID = "intent"
SCOPE = "main"
#: 本样例只出一张图；作用域留在 gid 里是为了与 NMR/FTIR 同一套命名。
SCOPES = (SCOPE,)

CURVE_GID = "intent.main.curve"

# ── 画布（毫米）与曲线采样：画布/科学量，不是排版旋钮 ───────────────────────
CANVAS_W_MM = 60.0
CANVAS_H_MM = 45.0
DPI = 300
CURVE_POINTS = 200
CURVE_X_RANGE = (0.0, 10.0)
CURVE_CENTER = 5.0
CURVE_SIGMA = 1.0

#: 显式布局绑定：gid → `[dx, dy]`（毫米，dx 向右、dy 向上）。
#: **唯一的排版位移来源**；这些数字不进 YAML、也不参与科学计算。
LAYOUT_MM = {
    "intent.main.label.A": [0.0, 0.0],
    "intent.main.label.B": [0.0, 0.0],
}

#: 两个标签：`(gid, 数据锚点 x, y, 文字)`。锚点是标注位置，`LAYOUT_MM` 的毫米位移在其上叠加。
LABELS = (
    ("intent.main.label.A", 2.0, 0.62, "A"),
    ("intent.main.label.B", 7.5, 0.62, "B"),
)


def _binding(gid: str) -> tuple[float, float]:
    """该 gid 声明的毫米位移 `[dx, dy]`；没声明就是不动。"""
    dx, dy = LAYOUT_MM.get(gid, (0.0, 0.0))
    return float(dx), float(dy)


def load_science() -> dict:
    """受保护的科研载荷：确定性解析曲线（不读文件、不引入随机/时间）。"""
    x0, x1 = CURVE_X_RANGE
    step = (x1 - x0) / (CURVE_POINTS - 1)
    x = [x0 + step * i for i in range(CURVE_POINTS)]
    y = [math.exp(-((value - CURVE_CENTER) ** 2) / (2.0 * CURVE_SIGMA ** 2)) for value in x]
    return {"x": x, "y": y}


def build_scene(science: dict, config: dict, scope: str):
    """native 入口：候选配置 + 已缓存科研载荷 → `(Figure, GidRegistry)`。

    `config` 由引擎传入；本样例**不在 YAML 里放任何排版值**，所以它不参与建图
    —— 位移的唯一来源是源码里的 `LAYOUT_MM`。
    """
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope!r}；本样例声明 {list(SCOPES)}")
    unknown = sorted(set(LAYOUT_MM) - {gid for gid, *_ in LABELS})
    if unknown:
        raise ValueError(f"LAYOUT_MM 里出现了不存在的图元：{unknown}")

    fig = plt.figure(figsize=(CANVAS_W_MM / 25.4, CANVAS_H_MM / 25.4), dpi=DPI)
    ax = fig.add_axes((0.18, 0.22, 0.76, 0.68))
    reg = GidRegistry(scope=scope)

    line, = ax.plot(science["x"], science["y"], color="#333333", linewidth=1.0)
    reg.register(line, CURVE_GID, artist_type="Line2D", science_policy="LOCKED_SCIENCE")

    for gid, point_x, point_y, text in LABELS:
        dx, dy = _binding(gid)
        label = ax.text(point_x, point_y, text, ha="center", va="bottom", fontsize=7.0)
        apply_display_shift(label, dx_mm=dx, dy_mm=dy)
        reg.register(label, gid, artist_type="Text", science_policy="LAYOUT")

    ax.set_xlabel("x (a.u.)")
    ax.set_ylabel("y (a.u.)")
    return fig, reg


def build_figure_and_registry(scope: str = SCOPE):
    """legacy 入口：`python simple_figure.py` 与旧的 `build_figure_and_registry` 调用方。"""
    return build_scene(load_science(), {}, scope)


def make_figure():
    """把样例图写成一个 PNG（只在 `__main__` 跑；导入本模块不写任何文件）。"""
    fig, reg = build_figure_and_registry()
    out = Path(__file__).with_name("simple_figure.png")
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    return out, reg


if __name__ == "__main__":
    path, registry = make_figure()
    print(f"{path}（{len(registry.gids())} 个图元）")
