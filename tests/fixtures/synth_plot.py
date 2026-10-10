"""合成绘图 fixture：按 figpact 绘图脚本契约写的一张假图。

契约面（与 examples/ftir、examples/nmr 同一套接缝）：
    SCOPES, FIGURE_ID, SCALARS, SCHEMA, CONFIG_PATH,
    load_config(path=...), list_params(), build_figure_and_registry(scope, ...)

**导入本模块不产生任何输出、不写文件、不建 Figure** —— 测试要能只拿契约就跑。

故意留下的 T6 素材（本仓**不**实现效果引擎，只提供素材让 T6 有东西可验）：
- `unused_knob`：SCHEMA 与 YAML 里都有，任何绘图代码都不读它 → 应报 NO_EFFECT。
- xlabel 被注册成绑 `label_font_pt`，实际字号来自 `axis_font_pt` → 应报 EFFECT_MISMATCH。
- `build_figure_and_registry(..., conflict=True)` 制造两对标签重叠 + 一条压在曲线上。
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from figpact import GidRegistry, apply_display_shift
from figpact import load_config as _engine_load_config
from figpact.config import ConfigError

from tests.fixtures import synth_data

#: 对象身份前缀，不是配置项（gid 是外部引用认的名字）。
FIGURE_ID = "fig9_synth"

#: 「一次 draw_panel 调用 = 一个作用域」。改论文主图不许顺手改掉标注版。
SCOPES = ("main", "annotated")
CURVE_IDS = synth_data.CURVE_IDS
BAR_LABELS = synth_data.BAR_LABELS

CONFIG_PATH = Path(__file__).with_name("synth.yaml")

#: 单条曲线的显示位移上限（mm）。
SHIFT_LIMIT_MM = 10.0
FONT_RANGE = (5.0, 9.0)
#: 画布纵向范围（数据单位），两个 scope 一致：scope 只换排版，不换坐标。
YLIM = (-0.9, 1.3)

#: key → (类型, 下界, 上界)。`unused_knob` 声明了但绘图代码不读它（T6 NO_EFFECT 素材）。
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 40.0, 120.0),
    "canvas_h_mm": (float, 30.0, 120.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "label_font_pt": (float, *FONT_RANGE),
    "line_width": (float, 0.2, 3.0),
    "label_offset_mm": (float, 0.0, 6.0),
    "unused_knob": (float, 0.0, 10.0),
}

SCHEMA = dict(SCALARS)
SCHEMA["shifts_mm"] = (dict,)

#: 人类 / 模型调参清单的分组。测试只吃结构，不吃文案。
PARAM_GROUPS = (
    ("元数据 (Meta)", (
        ("schema_version", "配置契约版本", "—"),
    )),
    ("画布 (Canvas)", (
        ("canvas_w_mm", "画布物理宽度", "mm"),
        ("canvas_h_mm", "画布物理高度", "mm"),
    )),
    ("坐标轴 (Axes)", (
        ("axis_font_pt", "轴标题字号", "pt"),
        ("line_width", "谱线线宽", "pt"),
    )),
    ("标注 (Annotations)", (
        ("label_font_pt", "归属标签字号", "pt"),
        ("label_offset_mm", "标签上抬净空", "mm"),
    )),
    ("未使用 (Unused)", (
        ("unused_knob", "故意没接线的旋钮", "a.u."),
    )),
)


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    """引擎校验 + `shifts_mm` 归一化：`shifts_mm[scope][curve_id]` → mm。

    校验一律走 `figpact.config`，不在本模块重写一套数字检查。
    """
    cfg = _engine_load_config(path, SCHEMA)
    name = Path(path).name

    raw = cfg.get("shifts_mm") or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}：shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw) - set(SCOPES)):
        raise ConfigError(f"{name}：shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")

    shifts: dict[str, dict[str, float]] = {scope: {sid: 0.0 for sid in CURVE_IDS} for scope in SCOPES}
    for scope, per_curve in raw.items():
        if per_curve is None:
            continue
        if not isinstance(per_curve, dict):
            raise ConfigError(f"{name}：shifts_mm.{scope} 必须是 `曲线id: 毫米` 映射")
        if unknown := sorted(set(per_curve) - set(CURVE_IDS)):
            raise ConfigError(f"{name}：shifts_mm.{scope} 里有未知曲线 {unknown}；可用：{list(CURVE_IDS)}")
        for sid, value in per_curve.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} 必须是数字")
            val = float(value)
            if not math.isfinite(val):
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} 不能是 NaN 或 Inf")
            if abs(val) > SHIFT_LIMIT_MM:
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} = {val} 超出 ±{SHIFT_LIMIT_MM} mm")
            shifts[scope][sid] = val
    cfg["shifts_mm"] = shifts
    return cfg


def list_params() -> None:
    """按可见对象分组的参数清单（当前值 / 单位 / 允许范围）。"""
    cfg = load_config()
    for group, entries in PARAM_GROUPS:
        print(f"=== {group} ===")
        for key, desc, unit in entries:
            lo, hi = SCALARS[key][1:]
            print(f"  {key:<16}{desc:<20}{unit:<5}当前 {cfg[key]!r:<8} 范围 [{lo}, {hi}]")
    print("=== 位移 (Shifts) ===")
    for scope in SCOPES:
        print(f"  [{scope}] " + "、".join(f"shifts_mm.{scope}.{sid}" for sid in CURVE_IDS))


def _annotations(ax, reg: GidRegistry, cfg: dict, scope: str, conflict: bool) -> None:
    """归属标签。conflict=True 时制造重叠与压线（QA / 豁免测试的素材）。"""
    fs = cfg["label_font_pt"]
    if conflict:
        # 两对标签各放在同一点上：必然重叠，与字体度量无关。
        pairs = ((3000.0, 1.15, "3p68", "2p02"), (2000.0, 1.05, "4p11", "1p05"))
        for x, y, t1, t2 in pairs:
            for i, text in enumerate((t1, t2)):
                t = ax.text(x, y, text, fontsize=fs)
                reg.register(t, f"{FIGURE_ID}.{scope}.label.{text}", params=["label_font_pt"])
        # 一条直接压在谱线上的文字。
        curve_x, curve_y = synth_data.synthetic_curves()[0]
        on_y = float(np.interp(1200.0, curve_x, curve_y))
        t = ax.text(1200.0, on_y, "probe", fontsize=fs)
        reg.register(t, f"{FIGURE_ID}.{scope}.label.probe", params=["label_font_pt"])
        return

    # label_offset_mm → 数据单位的粗换算（0.1 unit / mm）；这块图的纵轴跨度是 2.2。
    label_y = 1.05 + 0.1 * cfg["label_offset_mm"]
    for x, text in ((3300.0, "3p68"), (1650.0, "2p02")):
        t = ax.text(x, label_y, text, fontsize=fs)
        reg.register(t, f"{FIGURE_ID}.{scope}.label.{text}", params=["label_font_pt"])


def build_figure_and_registry(scope: str, *, config: dict | None = None, conflict: bool = False):
    """构造 (Figure, GidRegistry)。scope ∈ SCOPES；conflict=True 追加重叠标注素材。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope: {scope}；可用：{list(SCOPES)}")
    cfg = config if config is not None else load_config()

    fig, ax = plt.subplots(figsize=(cfg["canvas_w_mm"] / 25.4, cfg["canvas_h_mm"] / 25.4))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.93, bottom=0.16)
    reg = GidRegistry()

    for sid, (x, y) in zip(CURVE_IDS, synth_data.synthetic_curves()):
        (line,) = ax.plot(x, y, lw=cfg["line_width"])
        gid = f"{FIGURE_ID}.{scope}.curve.{sid}"
        reg.register(line, gid, params=["line_width", "shifts_mm"])
        apply_display_shift(line, dy_mm=cfg["shifts_mm"][scope][sid])

    ax.set_xlabel("Wavenumber (cm$^{-1}$)", fontsize=cfg["axis_font_pt"])
    # 故意错绑：声明的是 label_font_pt，实际字号来自 axis_font_pt（T6 EFFECT_MISMATCH 素材）。
    reg.register(ax.xaxis.label, f"{FIGURE_ID}.{scope}.xlabel", params=["label_font_pt"])
    ax.set_ylabel("Transmittance (a.u.)", fontsize=cfg["axis_font_pt"])
    reg.register(ax.yaxis.label, f"{FIGURE_ID}.{scope}.ylabel", params=["axis_font_pt"])

    ax.set_ylim(*YLIM)
    if scope == "annotated":
        _annotations(ax, reg, cfg, scope, conflict)
    return fig, reg


def build_bar_figure_and_registry(scope: str = "main", *, config: dict | None = None):
    """合成柱图（通用契约不许为它改数据结构）：同样的 scope / registry 接缝。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope: {scope}；可用：{list(SCOPES)}")
    cfg = config if config is not None else load_config()

    labels, values, errors = synth_data.bar_series()
    xs = np.arange(len(labels), dtype=float)
    fig, ax = plt.subplots(figsize=(cfg["canvas_w_mm"] / 25.4, cfg["canvas_h_mm"] / 25.4))
    fig.subplots_adjust(left=0.20, right=0.97, top=0.93, bottom=0.20)
    reg = GidRegistry()

    container = ax.bar(xs, values, lw=cfg["line_width"])
    for patch, label in zip(container, labels):
        reg.register(patch, f"{FIGURE_ID}.{scope}.bar.{label}", params=["line_width"])
    ax.set_xticks(xs)
    ax.set_xticklabels(labels)

    # 误差棒：caps 是 Line2D，不登记的话 inventory 会报 unregistered。
    err = ax.errorbar(xs, values, yerr=errors, fmt="none", capsize=2.0,
                      lw=cfg["line_width"], color="black")
    for i, cap in enumerate(getattr(err, "lines", (None, ()))[1] or ()):
        reg.register(cap, f"{FIGURE_ID}.{scope}.bar_cap.{i}", params=["line_width"])

    ax.set_ylabel("Response (a.u.)", fontsize=cfg["axis_font_pt"])
    reg.register(ax.yaxis.label, f"{FIGURE_ID}.{scope}.ylabel", params=["axis_font_pt"])
    ax.set_xlabel("Condition", fontsize=cfg["axis_font_pt"])
    reg.register(ax.xaxis.label, f"{FIGURE_ID}.{scope}.xlabel", params=["axis_font_pt"])
    return fig, reg
