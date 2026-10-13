#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""legacy 纯 Python Matplotlib 夹具：一条曲线 + 两个标签，**没有任何布局绑定**。

与 `examples/python_native/simple_figure.py` 同类（同样的接缝名、同样的三件图元），
区别只有一处：这里没有任何模块级的毫米位移映射 —— 连那个众所周知的映射名都**一次
也没出现**（`grep` 该名字在本文件零命中），所以没有等价的"可写绑定"藏在别处。

为什么要有这份"没绑定"的夹具
----------------------------
`figpact.python_native` 的定位只认一件事：模块级位移映射的**字典字面量**。本文件里
两个标签的位移直接写在 `ax.annotate(..., xytext=(dx, dy), textcoords="offset points")`
的调用现场，是纯 Matplotlib 的点（pt）常量，既不是毫米、也不在任何可定位的映射里。
于是：

  * `read_layout_binding()` → `{}`（"什么都没声明"是事实）；
  * `plan_layout_edit()` → `NEEDS_AUTHORING`（源码里没有这条绑定，不猜常量、不写文件）；
  * `build_repair_spec()` → 仍然给出**结构完整**的 `AuthoringRepairSpec`：
    `goal.kind == 'new_edit_binding'`，候选位置指向含有该 gid 字面量的函数。

这正是 G4「无绑定图元」这条路径要的真实输入：**直接编辑不了，必须作者级加一个局部
自由度**。想改成可编辑的夹具，请对照 `simple_figure.py` 补上那份映射并让
`build_scene` 读它 —— 本文件故意不做这件事。

对引擎声明的接缝（不新造机制）：`FIGURE_ID / SCOPES / load_science / build_scene /
build_figure_and_registry`。导入本模块：不解析 argv、不建 Figure、不渲染、不写文件、
不打印、不读 YAML、不引入随机/时间。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:  # 直接以脚本方式运行（cwd 可能是任意目录）也能 import figpact
    sys.path.insert(0, _ROOT)

import matplotlib.pyplot as plt  # noqa: E402

from figpact import GidRegistry  # noqa: E402

# ── 对外身份（**不是配置项**：gid 是外部引用认的名字） ───────────────────────
FIGURE_ID = "legacy"
SCOPE = "main"
#: 本夹具只出一张图；作用域留在 gid 里是为了与 NMR/FTIR 同一套命名。
SCOPES = (SCOPE,)

CURVE_GID = "legacy.main.curve"
#: 标签 gid 故意**只出现在 `build_scene` 的调用现场**（字面量），没有模块级常量：
#: `authoring.build_repair_spec` 的候选位置按「哪个函数体里出现该 gid 字面量」找，
#: 常量名在这里帮不上作者级修复的忙。


# ── 画布（毫米）与曲线采样：画布/科学量，不是排版旋钮 ───────────────────────
CANVAS_W_MM = 60.0
CANVAS_H_MM = 45.0
DPI = 300
CURVE_POINTS = 200
CURVE_X_RANGE = (0.0, 10.0)
CURVE_CENTER = 5.0
CURVE_SIGMA = 1.0


def load_science() -> dict:
    """受保护的科研载荷：确定性解析曲线（不读文件、不引入随机/时间）。"""
    x0, x1 = CURVE_X_RANGE
    step = (x1 - x0) / (CURVE_POINTS - 1)
    x = [x0 + step * i for i in range(CURVE_POINTS)]
    y = [math.exp(-((value - CURVE_CENTER) ** 2) / (2.0 * CURVE_SIGMA ** 2)) for value in x]
    return {"x": x, "y": y}


def build_scene(science: dict, config: dict, scope: str):
    """native 入口：候选配置 + 已缓存科研载荷 → `(Figure, GidRegistry)`。

    `config` 由引擎传入，本夹具不从中取任何值（绘制不依赖配置）。两个标签用经典
    legacy 写法摆位：数据锚点 `xy`，显示位移是 `xytext` 的点常量。**没有**任何模块级
    位移映射 —— 所以这里没有可被 `python_native` 定位的排版字面量，改位移必须动源码本体。
    """
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope!r}；本夹具声明 {list(SCOPES)}")

    fig = plt.figure(figsize=(CANVAS_W_MM / 25.4, CANVAS_H_MM / 25.4), dpi=DPI)
    ax = fig.add_axes((0.18, 0.22, 0.76, 0.68))
    reg = GidRegistry(scope=scope)

    curve, = ax.plot(science["x"], science["y"], color="#333333", linewidth=1.0)
    reg.register(curve, CURVE_GID, artist_type="Line2D", science_policy="LOCKED_SCIENCE")

    label_a = ax.annotate("A", xy=(2.0, 0.62), xytext=(0.0, 4.0),
                          textcoords="offset points", ha="center", va="bottom", fontsize=7.0)
    reg.register(label_a, "legacy.main.label.A", artist_type="Annotation",
                 science_policy="LAYOUT")

    label_b = ax.annotate("B", xy=(7.5, 0.62), xytext=(0.0, 9.0),
                          textcoords="offset points", ha="center", va="bottom", fontsize=7.0)
    reg.register(label_b, "legacy.main.label.B", artist_type="Annotation",
                 science_policy="LAYOUT")

    ax.set_xlabel("x (a.u.)")
    ax.set_ylabel("y (a.u.)")
    return fig, reg


def build_figure_and_registry(scope: str = SCOPE, config: dict | None = None):
    """legacy 入口：`python legacy_plain.py` 与旧的 `build_figure_and_registry` 调用方。

    `config` 只为兼容引擎的 legacy 调用约定（`legacy(scope, config=...)`）而接受，
    本夹具不读它。
    """
    return build_scene(load_science(), config if config is not None else {}, scope)


if __name__ == "__main__":
    # 只报图元身份：本夹具不写任何文件（没有 PNG 产物，也没有 YAML）。
    _fig, _registry = build_figure_and_registry()
    plt.close(_fig)
    _gids = sorted(_registry.gids())
    print(f"{len(_gids)} 个图元：{_gids}")
