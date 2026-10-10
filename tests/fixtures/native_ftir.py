"""原生 FTIR 夹具：三条透过率风格曲线 + 带位窗口与带位标签。

**与绘图源码无关**：这张图是什么，全部写在下面对外声明的接缝里 ——
`SCOPES / FIGURE_ID / CONFIG_PATH / SCHEMA / load_config / list_params /
load_science / build_scene / build_figure_and_registry / layout_contract /
science_manifest / science_selfcheck`。别的 agent 不用读本文件其余部分，
就能拿到"有哪些对象、哪个 YAML 路径控制它、会产生什么效果、必须守住什么"。

科学内容（受保护，显示层不许改）：
- 三条曲线共用同一条**严格递减**的波数网格，绘图数组逐字节等于 `fixture_data` 的数组；
- 带位窗口（cm⁻¹）是受保护的显示窗口；
- 带位文本是受保护的科学文本；
- xlim/ylim 是受保护的显示窗口。
（曲线在某个波数处取值走 `fixture_data.interp_descending`：递减网格直接喂
`np.interp` 返回的是没有意义的数——旧夹具就是这么在谱线上放探针文字的。）

排版（真实物理毫米，不许用 0.1 data-unit/mm 之类的猜出来的换算）：
带位标签只在**数据锚点**上再叠一个 `apply_display_shift(..., dy_mm=...)`；
曲线之间的台阶与逐曲线位移同样是毫米显示位移，数据坐标一个字节都不动。

作用域（scope = 命名的作用域/校验归属范围，**不是文件名**）：
- `main` / `annotated`：各自一张单格图，各自一套产物；
- `compare_raw` / `compare_processed`：同一张**两格对照图**里的两个作用域，
  共享同一份产物名（`compare_*`）——发布时按名字去重，只出一份文件，
  但每个作用域只授权自己那格的路径与对象。

导入本模块：不建 Figure、不渲染、不写文件、不打印。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:  # 直接以脚本方式运行（cwd 可能是任意目录）
    sys.path.insert(0, _ROOT)

import math  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from figpact import GidRegistry, apply_display_shift  # noqa: E402
from figpact import load_config as _engine_load_config  # noqa: E402
from figpact.config import ConfigError  # noqa: E402
from figpact.units import MM_PER_INCH  # noqa: E402
from tests.fixtures import _native, fixture_data  # noqa: E402

# ── 对外身份 ────────────────────────────────────────────────────────────────
#: 对象身份前缀，不是配置项：gid 是外部引用认的名字，做成旋钮只会让引用悄悄失效。
FIGURE_ID = "fig_ftir_native"
#: 「一次 build_scene 调用 = 一个作用域」。改论文主图不许顺手改掉标注版。
#: `compare_raw` / `compare_processed` 是**同一张两格图**上的两个作用域：各自授权
#: 自己那格的路径与对象，共享同一份产物名（发布时按名字去重，只写一份文件）。
SCOPES = ("main", "annotated", "compare_raw", "compare_processed")
COMPARE_SCOPES = ("compare_raw", "compare_processed")
#: 对照图里"上面那格"属于哪个作用域。
COMPARE_TOP_SCOPE = "compare_raw"
CURVE_IDS = fixture_data.FTIR_CURVE_IDS
#: 每个作用域实际画出来的曲线（对照图只画 a；声明了却不画 = 未接线，不许有）。
ACTIVE_CURVES = {
    "main": CURVE_IDS,
    "annotated": CURVE_IDS,
    "compare_raw": ("a",),
    "compare_processed": ("a",),
}
BAND_IDS = tuple(fixture_data.ftir_band_limits())
CONFIG_PATH = Path(__file__).with_name("native_ftir.yaml")

XLABEL = "Wavenumber (cm$^{-1}$)"
YLABEL = "Transmittance (a.u.)"

FONT_RANGE = (3.0, 12.0)
#: 单条曲线的显示位移上限（mm）：超过这个数曲线会被坐标框裁掉，那是 QA 阻断。
SHIFT_LIMIT_MM = 6.0
#: `--strict` 每个 scope 必须产出的格式（共享契约：PNG/PDF/SVG/TIFF）。
OUTPUT_FORMATS = ("png", "pdf", "svg", "tiff")

#: 科学**输入**文件：本夹具没有外部输入——载荷由 `fixture_data` 用固定种子现算，
#: 来源是种子 + 生成函数，不是被读进来的数据文件。（`.png/.pdf/.json` 也可能是
#: 科学输入，所以这里按声明逐条认，绝不按扩展名一刀切。）
SCIENCE_INPUTS: tuple[Path, ...] = ()


def science_inputs() -> tuple[Path, ...]:
    """声明的科学输入文件（绝对路径）。生成式夹具返回空元组。"""
    return SCIENCE_INPUTS

#: key → (类型, 下界, 上界)。`band_limits_cm1` 是字典型：**受保护的显示窗口**。
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 60.0, 160.0),
    "canvas_h_mm": (float, 50.0, 160.0),
    "render_dpi": (int, 96, 600),
    "axes_left_mm": (float, 5.0, 60.0),
    "axes_right_mm": (float, 5.0, 60.0),
    "axes_bottom_mm": (float, 5.0, 60.0),
    "axes_top_mm": (float, 5.0, 60.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "label_font_pt": (float, *FONT_RANGE),
    "line_width": (float, 0.2, 3.0),
    "curve_gap_mm": (float, 0.0, 4.0),
    "band_label_lift_mm": (float, 0.0, 3.0),
    "band_limits_cm1": (dict,),
    # 对照图（compare_raw / compare_processed 共用一张两格图）
    "compare_left_mm": (float, 5.0, 60.0),
    "compare_right_mm": (float, 5.0, 60.0),
    "compare_bottom_mm": (float, 5.0, 60.0),
    "compare_top_mm": (float, 5.0, 60.0),
    "compare_panel_h_mm": (float, 10.0, 80.0),
    "compare_gap_mm": (float, 0.0, 20.0),
}
SCHEMA = dict(SCALARS)
SCHEMA["shifts_mm"] = (dict,)

PARAM_GROUPS = {
    "元数据 (Meta)": ("schema_version",),
    "画布 (Canvas)": ("canvas_w_mm", "canvas_h_mm", "render_dpi"),
    "坐标框 (Axes rect)": ("axes_left_mm", "axes_right_mm", "axes_bottom_mm", "axes_top_mm"),
    "字号与线宽 (Type)": ("axis_font_pt", "tick_font_pt", "label_font_pt", "line_width"),
    "堆叠与标签 (Stack)": ("curve_gap_mm", "band_label_lift_mm"),
    "受保护窗口 (Locked)": ("band_limits_cm1",),
    "对照图 (Compare)": ("compare_left_mm", "compare_right_mm", "compare_bottom_mm",
                         "compare_top_mm", "compare_panel_h_mm", "compare_gap_mm"),
}
PARAM_DESC = {
    "schema_version": ("配置契约版本", "—"),
    "canvas_w_mm": ("画布物理宽度", "mm"),
    "canvas_h_mm": ("画布物理高度", "mm"),
    "render_dpi": ("渲染分辨率", "dpi"),
    "axes_left_mm": ("坐标框左外边距", "mm"),
    "axes_right_mm": ("坐标框右外边距", "mm"),
    "axes_bottom_mm": ("坐标框下外边距", "mm"),
    "axes_top_mm": ("坐标框上外边距", "mm"),
    "axis_font_pt": ("轴标题字号", "pt"),
    "tick_font_pt": ("刻度字号", "pt"),
    "label_font_pt": ("带位标签字号", "pt"),
    "line_width": ("谱线线宽", "pt"),
    "curve_gap_mm": ("b/c 两条曲线整体抬升", "mm"),
    "band_label_lift_mm": ("带位标签上抬", "mm"),
    "band_limits_cm1": ("带位窗口（受保护）", "cm-1"),
    "compare_left_mm": ("对照图左外边距", "mm"),
    "compare_right_mm": ("对照图右外边距", "mm"),
    "compare_bottom_mm": ("对照图下外边距", "mm"),
    "compare_top_mm": ("对照图上外边距", "mm"),
    "compare_panel_h_mm": ("对照图每格高度", "mm"),
    "compare_gap_mm": ("对照图两格间距", "mm"),
}

#: 任务语料引用这些名字，测试核对"每个断言的保护项都被夹具声明过"。
SCIENCE_INVARIANTS = {
    "ftir.curve_arrays": "三条曲线的绘图数组逐字节等于受保护数组（同一条严格递减波数网格）",
    "ftir.processing_chain": "「处理后」对照格只有声明的 5 点滑动平均，x 网格与点数不变",
    "ftir.band_windows": "带位窗口（cm⁻¹）与带位文本不变",
    "ftir.view_windows": "xlim/ylim 显示的物理窗口不变",
    "ftir.stack_order": "曲线上下顺序与堆叠台阶的声明一致",
}


# ── 配置 ────────────────────────────────────────────────────────────────────
def load_config(path: Path | str = CONFIG_PATH) -> dict:
    """引擎校验 + `shifts_mm` 归一化 + 带位窗口只读校验。"""
    cfg = _engine_load_config(path, SCHEMA)
    name = Path(path).name

    declared = cfg["band_limits_cm1"]
    if not isinstance(declared, dict):
        raise ConfigError(f"{name}：band_limits_cm1 必须是 `带位id: [下界, 上界]` 映射")
    expected = fixture_data.ftir_band_limits()
    if set(declared) != set(expected):
        raise ConfigError(f"{name}：band_limits_cm1 必须完整列出 {list(expected)}；得到 {sorted(declared)}")
    for bid, value in declared.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ConfigError(f"{name}：band_limits_cm1.{bid} 必须是 [下界, 上界]")
        pair = tuple(float(v) for v in value)
        if pair != expected[bid]:
            # 显示窗口即受保护的科学窗口：改它 = 换了一张图在说什么，不是排版。
            raise ConfigError(f"{name}：band_limits_cm1.{bid} = {pair} 与受保护窗口 {expected[bid]} 不一致")
        if pair[0] >= pair[1] or not all(math.isfinite(v) for v in pair):
            raise ConfigError(f"{name}：band_limits_cm1.{bid} 不是有序有限区间")

    raw = cfg.get("shifts_mm") or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}：shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw) - set(SCOPES)):
        raise ConfigError(f"{name}：shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")
    shifts: dict[str, dict[str, float]] = {
        scope: {sid: 0.0 for sid in ACTIVE_CURVES[scope]} for scope in SCOPES}
    for scope, per_curve in raw.items():
        if per_curve is None:
            continue
        if not isinstance(per_curve, dict):
            raise ConfigError(f"{name}：shifts_mm.{scope} 必须是 `曲线id: 毫米` 映射")
        if unknown := sorted(set(per_curve) - set(ACTIVE_CURVES[scope])):
            raise ConfigError(f"{name}：shifts_mm.{scope} 里有该作用域不画的曲线 {unknown}；"
                              f"可用：{list(ACTIVE_CURVES[scope])}")
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
    _check_compare_geometry(cfg, name)
    return cfg


def _check_compare_geometry(cfg: dict, name: str) -> None:
    """对照图几何的**早退**校验：上格被推出画布不是"排版取舍"，直接拒。

    两格高度 + 中间空隙 + 上下外边距 = 画布高度（默认正好用满）；超过就是
    "没有空间"，在 load_config 就报错，不等到渲染完才发现图被裁了。
    """
    box_w = cfg["canvas_w_mm"] - cfg["compare_left_mm"] - cfg["compare_right_mm"]
    if box_w <= 5.0:
        raise ConfigError(f"{name}：对照图每格只剩 {box_w:.1f} mm 宽（画布 {cfg['canvas_w_mm']} mm）")
    used_h = cfg["compare_bottom_mm"] + 2 * cfg["compare_panel_h_mm"] + cfg["compare_gap_mm"] + cfg["compare_top_mm"]
    if used_h > cfg["canvas_h_mm"] + 1e-9:
        raise ConfigError(f"{name}：对照图下边距 {cfg['compare_bottom_mm']} + 2×格高 "
                          f"{cfg['compare_panel_h_mm']} + 间距 {cfg['compare_gap_mm']} + 上边距 "
                          f"{cfg['compare_top_mm']} = {used_h:g} mm 超过画布高度 {cfg['canvas_h_mm']} mm；"
                          f"上格会被推出画布外")


def list_params(path: Path | str = CONFIG_PATH) -> None:
    """按可见对象分组的参数清单（当前值 / 单位 / 允许范围）。"""
    cfg = load_config(path)
    _native.print_param_table(cfg, SCALARS, PARAM_GROUPS, PARAM_DESC)
    print("=== 位移 (Shifts, mm) ===")
    for scope in SCOPES:
        print(f"  [{scope}] " + "、".join(f"shifts_mm.{scope}.{sid}={cfg['shifts_mm'][scope][sid]:g}"
                                          for sid in CURVE_IDS))


# ── 科学载荷 ────────────────────────────────────────────────────────────────
def load_science() -> dict:
    """受保护的数据与来源声明：不建 Figure，可以被反复调用（结果一致）。"""
    return {
        "curves": fixture_data.ftir_curves(),
        "processed": fixture_data.ftir_processed_curves(),
        "bands": fixture_data.ftir_band_limits(),
        "band_text": dict(fixture_data.FTIR_BAND_TEXT),
        "label_y": float(fixture_data.FTIR_LABEL_Y),
        "xlim": tuple(fixture_data.FTIR_XLIM),
        "ylim": tuple(fixture_data.FTIR_YLIM),
        "source": {
            "kind": "seeded_synthetic",
            "seed": fixture_data.SEED,
            "generator": "tests.fixtures.fixture_data.ftir_curves",
            "note": "no instrument file, no private data",
        },
    }


def science_manifest(science: dict) -> dict:
    """来源/处理/受保护窗口/文本的 JSONable 声明（引擎另会指纹化图的真实内容）。"""
    return {
        "science": {
            "source": science["source"],
            "source_files": [str(p) for p in SCIENCE_INPUTS],
            "processing": [
                "deterministic seeded noise, no smoothing",
                "no normalisation, no resampling, no interpolation of the plotted arrays",
                "y is transmittance-like as generated; no unit conversion",
                f"compare_processed panel = {fixture_data.FTIR_PROCESS_WINDOW}-point moving average "
                "(endpoint-padded) of the SAME protected array; identical x grid, no other step",
            ],
            "protected_windows": {
                "xlim_cm1": list(science["xlim"]),
                "ylim_au": list(science["ylim"]),
                "band_limits_cm1": {bid: list(pair) for bid, pair in science["bands"].items()},
            },
            "protected_text": {
                "band_labels": dict(science["band_text"]),
                "axis_labels": [XLABEL, YLABEL],
            },
            "arrays": [
                {"id": sid, "kind": "curve", "n": int(science["curves"][i][0].size),
                 "units": {"x": "cm-1", "y": "a.u."}, "grid": "strictly descending"}
                for i, sid in enumerate(CURVE_IDS)
            ],
            "scale_bars": [],
        },
        "nodes": {g: {"science_policy": meta["science_policy"]}
                  for g, meta in _all_policy_nodes().items()},
    }


# ── 绘制 ────────────────────────────────────────────────────────────────────
def gid(scope: str, kind: str, name: str | None = None) -> str:
    """对象身份：`<figure>.<scope>.<kind>[.<name>]`。点号在 gid 里从不被拆开。"""
    return f"{FIGURE_ID}.{scope}.{kind}" + (f".{name}" if name else "")


def _axes_rect(config: dict) -> list[float]:
    """坐标框的精确位置：canvas 毫米 - 四条外边距，直接换成 figure 分数。"""
    width_mm, height_mm = config["canvas_w_mm"], config["canvas_h_mm"]
    left, right = config["axes_left_mm"], config["axes_right_mm"]
    bottom, top = config["axes_bottom_mm"], config["axes_top_mm"]
    box_w = width_mm - left - right
    box_h = height_mm - bottom - top
    if box_w <= 5.0 or box_h <= 5.0:
        raise ValueError(f"坐标框只剩 {box_w:.1f}×{box_h:.1f} mm（画布 {width_mm}×{height_mm} mm）")
    return [left / width_mm, bottom / height_mm, box_w / width_mm, box_h / height_mm]


def build_scene(science: dict, config: dict, scope: str):
    """确定性构建：基线布局完全由 config 决定；(Figure, GidRegistry)。

    `scope` 决定**授权范围**，不决定文件名：`compare_raw` 与 `compare_processed`
    构建的是同一张两格对照图，各自只登记/授权自己那格的 gid 与路径。
    """
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    if scope in COMPARE_SCOPES:
        return _build_compare(science, config)
    return _build_single(science, config, scope)


def _build_single(science: dict, config: dict, scope: str):
    """单格图（main / annotated）。"""
    cfg = config

    fig = plt.figure(figsize=(cfg["canvas_w_mm"] / MM_PER_INCH, cfg["canvas_h_mm"] / MM_PER_INCH),
                     dpi=float(cfg["render_dpi"]))
    ax = fig.add_axes(_axes_rect(cfg))
    reg = GidRegistry()
    reg.register(fig.patch, gid(scope, "canvas"))
    reg.register(ax, gid(scope, "axes"))

    # 带位窗口：受保护的显示窗口（先画，压在曲线下面）。
    for bid, (lo, hi) in science["bands"].items():
        span = ax.axvspan(lo, hi, color="0.45", alpha=0.16, lw=0.0, zorder=1)
        reg.register(span, gid(scope, "band", bid), params=["band_limits_cm1"])

    # 曲线：台阶与逐曲线位移都是**毫米显示位移**，数据坐标不动。
    for index, sid in enumerate(ACTIVE_CURVES[scope]):
        x, y = science["curves"][CURVE_IDS.index(sid)]
        (line,) = ax.plot(x, y, lw=cfg["line_width"], color=f"C{index}", zorder=3)
        reg.register(line, gid(scope, "curve", sid),
                     params=["line_width", "shifts_mm", "curve_gap_mm"])
        stack_mm = cfg["curve_gap_mm"] if index else 0.0
        apply_display_shift(line, dy_mm=stack_mm + cfg["shifts_mm"][scope][sid])

    # 带位标签：数据锚点 + 真实毫米上抬（不许 0.1 data-unit/mm 之类的猜想）。
    for bid, center in fixture_data.ftir_band_centers().items():
        text = ax.text(center, science["label_y"], science["band_text"][bid],
                       fontsize=cfg["label_font_pt"], ha="center", va="bottom", zorder=4)
        reg.register(text, gid(scope, "band_label", bid),
                     params=["label_font_pt", "band_label_lift_mm"])
        apply_display_shift(text, dy_mm=cfg["band_label_lift_mm"])

    _axis_texts(ax, reg, cfg, scope)
    ax.set_xlim(*science["xlim"])
    ax.set_ylim(*science["ylim"])
    return fig, reg


def _build_compare(science: dict, config: dict):
    """两格对照图：**上格 `compare_raw` = 原始**，**下格 `compare_processed` = 处理后**。

    两格共用一张 Figure 与一份产物名；每格有自己的 Axes、曲线、轴标题与 gid，
    所以两个作用域各自只授权自己那格的路径与对象。
    """
    cfg = config
    width_mm, height_mm = cfg["canvas_w_mm"], cfg["canvas_h_mm"]
    left, right = cfg["compare_left_mm"], cfg["compare_right_mm"]
    bottom, top = cfg["compare_bottom_mm"], cfg["compare_top_mm"]
    panel_h, gap = cfg["compare_panel_h_mm"], cfg["compare_gap_mm"]
    box_w = width_mm - left - right
    if box_w <= 5.0 or panel_h <= 5.0:
        raise ValueError(f"对照图每格只剩 {box_w:.1f}×{panel_h:.1f} mm")
    if bottom + 2 * panel_h + gap + top > height_mm + 1e-9:
        raise ValueError(f"两格 {panel_h:.1f} mm + 间距 {gap:.1f} mm + 上下外边距 "
                         f"{bottom + top:.1f} mm 超过画布高度 {height_mm} mm")

    fig = plt.figure(figsize=(width_mm / MM_PER_INCH, height_mm / MM_PER_INCH),
                     dpi=float(cfg["render_dpi"]))
    reg = GidRegistry()
    reg.register(fig.patch, gid(COMPARE_TOP_SCOPE, "canvas"))
    for panel_scope, y_mm in ((COMPARE_TOP_SCOPE, bottom + panel_h + gap),
                              ("compare_processed", bottom)):
        ax = fig.add_axes([left / width_mm, y_mm / height_mm, box_w / width_mm, panel_h / height_mm])
        reg.register(ax, gid(panel_scope, "axes"))
        sid = ACTIVE_CURVES[panel_scope][0]
        series = (science["curves"] if panel_scope == COMPARE_TOP_SCOPE else science["processed"])
        x, y = series[CURVE_IDS.index(sid)]
        (line,) = ax.plot(x, y, lw=cfg["line_width"], zorder=3)
        reg.register(line, gid(panel_scope, "curve", sid),
                     params=["line_width", "shifts_mm"])
        apply_display_shift(line, dy_mm=cfg["shifts_mm"][panel_scope][sid])
        title = ax.set_title("Raw" if panel_scope == COMPARE_TOP_SCOPE else "Processed",
                             fontsize=cfg["label_font_pt"])
        reg.register(title, gid(panel_scope, "title"), params=["label_font_pt"])
        _axis_texts(ax, reg, cfg, panel_scope, with_xlabel=(panel_scope != COMPARE_TOP_SCOPE))
        ax.set_xlim(*science["xlim"])
        ax.set_ylim(*science["ylim"])
    return fig, reg


def _axis_texts(ax, reg: GidRegistry, cfg: dict, scope: str, *, with_xlabel: bool = True) -> None:
    """轴标题/刻度。对照图上格不画 xlabel：两格共用一条横轴说明，上格的
    横轴说明会掉进两格之间的空隙里，和上格的刻度文字打架（QA 会当场抓到）。"""
    if with_xlabel:
        ax.set_xlabel(XLABEL, fontsize=cfg["axis_font_pt"])
        reg.register(ax.xaxis.label, gid(scope, "xlabel"), params=["axis_font_pt"])
    ax.set_ylabel(YLABEL, fontsize=cfg["axis_font_pt"])
    reg.register(ax.yaxis.label, gid(scope, "ylabel"), params=["axis_font_pt"])
    ax.tick_params(labelsize=cfg["tick_font_pt"])


def build_figure_and_registry(scope: str, *, config: dict | None = None):
    """旧接缝保持不变：等价于 build_scene(load_science(), config, scope)。"""
    return build_scene(load_science(), config if config is not None else load_config(), scope)


# ── 布局契约 ────────────────────────────────────────────────────────────────
def _nodes(scope: str) -> dict:
    """节点元数据：type / parent / editable / science_policy。未声明的默认锁死。"""
    root = gid(scope, "root")
    if scope in COMPARE_SCOPES:
        node_map = {
            gid(COMPARE_TOP_SCOPE, "canvas"): _native.node(
                gid(COMPARE_TOP_SCOPE, "canvas"), type_name="Figure", parent=None,
                editable=False, science_policy="LOCKED_SCIENCE", label="对照图画布"),
            gid(scope, "axes"): _native.node(gid(scope, "axes"), type_name="Axes", parent=root,
                                             editable=False, science_policy="LOCKED_SCIENCE",
                                             label="对照图本格坐标框"),
            gid(scope, "ylabel"): _native.node(gid(scope, "ylabel"), type_name="Text", parent=root,
                                               editable=False, science_policy="LOCKED_SCIENCE",
                                               label=YLABEL),
            gid(scope, "title"): _native.node(gid(scope, "title"), type_name="Text", parent=root,
                                              editable=False, science_policy="LOCKED_SCIENCE",
                                              label=_scope_title(scope)),
            gid(scope, "curve", ACTIVE_CURVES[scope][0]): _native.node(
                gid(scope, "curve", ACTIVE_CURVES[scope][0]), type_name="Line2D", parent=root,
                editable=False, science_policy="LOCKED_SCIENCE",
                label=("原始" if scope == COMPARE_TOP_SCOPE else "处理后") + f"曲线 {ACTIVE_CURVES[scope][0]}"),
        }
        if scope != COMPARE_TOP_SCOPE:
            # 上格没有 xlabel：两格共用的横轴说明画在下格（见 _axis_texts）。
            node_map[gid(scope, "xlabel")] = _native.node(
                gid(scope, "xlabel"), type_name="Text", parent=root, editable=False,
                science_policy="LOCKED_SCIENCE", label=XLABEL)
        return node_map
    nodes: dict[str, dict] = {
        gid(scope, "canvas"): _native.node(gid(scope, "canvas"), type_name="Figure", parent=None,
                                           editable=False, science_policy="LOCKED_SCIENCE",
                                           label="画布"),
        gid(scope, "axes"): _native.node(gid(scope, "axes"), type_name="Axes", parent=root,
                                         editable=False, science_policy="LOCKED_SCIENCE",
                                         label="坐标框"),
        gid(scope, "xlabel"): _native.node(gid(scope, "xlabel"), type_name="Text", parent=root,
                                            editable=False, science_policy="LOCKED_SCIENCE",
                                            label=XLABEL),
        gid(scope, "ylabel"): _native.node(gid(scope, "ylabel"), type_name="Text", parent=root,
                                            editable=False, science_policy="LOCKED_SCIENCE",
                                            label=YLABEL),
    }
    for sid in CURVE_IDS:
        nodes[gid(scope, "curve", sid)] = _native.node(
            gid(scope, "curve", sid), type_name="Line2D", parent=root, editable=False,
            science_policy="LOCKED_SCIENCE", label=f"曲线 {sid}")
    for bid in BAND_IDS:
        nodes[gid(scope, "band", bid)] = _native.node(
            gid(scope, "band", bid), type_name="Rectangle", parent=root, editable=False,
            science_policy="LOCKED_SCIENCE", label=f"带位窗口 {bid}")
        nodes[gid(scope, "band_label", bid)] = _native.node(
            gid(scope, "band_label", bid), type_name="Text", parent=root, editable=False,
            science_policy="LOCKED_SCIENCE", label=fixture_data.FTIR_BAND_TEXT[bid])
    return nodes


def _all_policy_nodes() -> dict:
    """全部 scope 的 science_policy 表（science_manifest 与契约共用一份）。"""
    out: dict[str, dict] = {}
    for scope in SCOPES:
        out.update(_nodes(scope))
    return out


def layout_contract(scope: str) -> dict:
    """这张图的可控点：参数 / 节点 / 组 / 关系 / 产物。路径永远是精确段数组。

    `scope` 决定**授权范围**与产物名集合：两个 `compare_*` 作用域共享同一份
    产物名（发布时按名字去重），各自声明自己那格的参数与关系。
    """
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    if scope in COMPARE_SCOPES:
        return _compare_contract(scope)
    return _single_contract(scope)


def _single_contract(scope: str) -> dict:
    """单格图（main / annotated）的契约。"""
    cur = [gid(scope, "curve", sid) for sid in CURVE_IDS]
    labels = [gid(scope, "band_label", bid) for bid in BAND_IDS]
    bands = [gid(scope, "band", bid) for bid in BAND_IDS]
    axes_node = gid(scope, "axes")
    canvas_node = gid(scope, "canvas")
    root = gid(scope, "root")
    keep_arrays = ["ftir.curve_arrays", "ftir.view_windows"]

    parameters = [
        _native.param("canvas_w_mm", ["canvas_w_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas_node], operation="rebuild", axis="x",
                      minimum=SCALARS["canvas_w_mm"][1], maximum=SCALARS["canvas_w_mm"][2],
                      expected=_native.expect("resize", objects=[canvas_node], axis="x",
                                              preserve=keep_arrays + ["ftir.band_windows"])),
        _native.param("canvas_h_mm", ["canvas_h_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas_node], operation="rebuild", axis="y",
                      minimum=SCALARS["canvas_h_mm"][1], maximum=SCALARS["canvas_h_mm"][2],
                      expected=_native.expect("resize", objects=[canvas_node], axis="y",
                                              preserve=keep_arrays + ["ftir.band_windows"])),
        _native.param("render_dpi", ["render_dpi"], unit="dpi", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas_node, axes_node], operation="rebuild",
                      axis=None, minimum=SCALARS["render_dpi"][1], maximum=SCALARS["render_dpi"][2],
                      expected=_native.expect("style", objects=[canvas_node], preserve=["ftir.view_windows"])),
    ]
    for key, axis in (("axes_left_mm", "x"), ("axes_right_mm", "x"),
                      ("axes_bottom_mm", "y"), ("axes_top_mm", "y")):
        parameters.append(_native.param(
            key, [key], unit="mm", mutability="EDITABLE", scopes=list(SCOPES),
            objects=[axes_node], operation="rebuild", axis=axis,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("resize", objects=[axes_node], axis=axis,
                                    preserve=keep_arrays + ["ftir.band_windows"])))
    for key in ("axis_font_pt", "tick_font_pt", "label_font_pt", "line_width"):
        target = [gid(scope, "xlabel"), gid(scope, "ylabel")] if "font_pt" in key else cur
        parameters.append(_native.param(
            key, [key], unit="pt", mutability="FIXED_STYLE", scopes=list(SCOPES),
            objects=target if key != "tick_font_pt" else [], operation="rebuild", axis=None,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("style", objects=target, preserve=keep_arrays)))
    parameters.append(_native.param(
        "curve_gap_mm", ["curve_gap_mm"], unit="mm", mutability="EDITABLE", scopes=list(SCOPES),
        objects=cur[1:], operation="translate", axis="y", scale=1.0,
        minimum=SCALARS["curve_gap_mm"][1], maximum=SCALARS["curve_gap_mm"][2],
        expected=_native.expect("translate", objects=cur[1:], axis="y",
                                preserve=keep_arrays + ["ftir.band_windows"])))
    parameters.append(_native.param(
        "band_label_lift_mm", ["band_label_lift_mm"], unit="mm", mutability="EDITABLE",
        scopes=list(SCOPES), objects=labels, operation="translate", axis="y", scale=1.0,
        minimum=SCALARS["band_label_lift_mm"][1], maximum=SCALARS["band_label_lift_mm"][2],
        expected=_native.expect("translate", objects=labels, axis="y",
                                preserve=keep_arrays + ["ftir.band_windows"])))
    parameters.append(_native.param(
        "band_limits_cm1", ["band_limits_cm1"], unit="cm-1", mutability="LOCKED_SCIENCE",
        scopes=list(SCOPES), objects=bands + labels, operation="rebuild", axis=None,
        expected=_native.expect("style", objects=bands + labels,
                                preserve=["ftir.band_windows", "ftir.view_windows"])))
    for sid in ACTIVE_CURVES[scope]:
        parameters.append(_native.param(
            f"shifts_mm.{scope}.{sid}", ["shifts_mm", scope, sid], unit="mm", mutability="EDITABLE",
            scopes=[scope], objects=[gid(scope, "curve", sid)], operation="translate", axis="y",
            scale=1.0, minimum=-SHIFT_LIMIT_MM, maximum=SHIFT_LIMIT_MM,
            expected=_native.expect("translate", objects=[gid(scope, "curve", sid)], axis="y",
                                    preserve=keep_arrays)))

    relations = [
        _native.relation("ftir.contain_x", "contain", [canvas_node, axes_node], axis="x",
                         controlled_by=[["canvas_w_mm"], ["axes_left_mm"], ["axes_right_mm"]]),
        _native.relation("ftir.contain_y", "contain", [canvas_node, axes_node], axis="y",
                         controlled_by=[["canvas_h_mm"], ["axes_bottom_mm"], ["axes_top_mm"]]),
        _native.relation(f"ftir.margin_left", "gap", [canvas_node, axes_node], axis="x",
                         anchor="left", controlled_by=[["axes_left_mm"]], move=[axes_node]),
        _native.relation("ftir.margin_right", "gap", [canvas_node, axes_node], axis="x",
                         anchor="right", controlled_by=[["axes_right_mm"]], move=[axes_node]),
        _native.relation("ftir.margin_bottom", "gap", [canvas_node, axes_node], axis="y",
                         anchor="bottom", controlled_by=[["axes_bottom_mm"]], move=[axes_node]),
        _native.relation("ftir.margin_top", "gap", [canvas_node, axes_node], axis="y",
                         anchor="top", controlled_by=[["axes_top_mm"]], move=[axes_node]),
        _native.relation("ftir.stack_gap", "gap", [cur[0], cur[1]], axis="y",
                         controlled_by=[["curve_gap_mm"]], move=cur[1:]),
    ]
    for bid in BAND_IDS:
        relations.append(_native.relation(
            f"ftir.band_label_center.{bid}", "align",
            [gid(scope, "band_label", bid), gid(scope, "band", bid)], axis="x", anchor="center_x",
            controlled_by=[["band_limits_cm1"]]))

    return _native.contract_record(
        sys.modules[__name__], scope, parameters=parameters, nodes=_nodes(scope),
        groups=[
            _native.group(root, parent=None, members=[canvas_node, axes_node]),
            _native.group(gid(scope, "curves"), parent=root, members=cur),
            _native.group(gid(scope, "bands"), parent=root, members=bands),
            _native.group(gid(scope, "band_labels"), parent=root, members=labels),
            _native.group(gid(scope, "text"), parent=root,
                          members=[gid(scope, "xlabel"), gid(scope, "ylabel")]),
        ],
        relations=relations,
        outputs=[f"{FIGURE_ID}_{scope}.{ext}" for ext in OUTPUT_FORMATS])


def _compare_contract(scope: str) -> dict:
    """两格对照图的作用域契约（两个作用域共享产物名，各自授权自己那格）。

    `objects` 声明的是**真实受影响集合**：共享外边距一动，两格都会动，所以
    这两条参数在两个作用域的契约里都声明两格的 gid（声明只覆盖一格会制造
    假的 EFFECT_MISMATCH）。授权的是**路径**，不是把受影响集合说小。
    """
    canvas = gid(COMPARE_TOP_SCOPE, "canvas")
    own_axes = gid(scope, "axes")
    other_scope = "compare_processed" if scope == COMPARE_TOP_SCOPE else COMPARE_TOP_SCOPE
    other_axes = gid(other_scope, "axes")
    own_curve = gid(scope, "curve", ACTIVE_CURVES[scope][0])
    both_axes = [gid(COMPARE_TOP_SCOPE, "axes"), gid("compare_processed", "axes")]
    # 文字对象：上格没有 xlabel（两格共用一条横轴说明，画在下格）。
    all_text = [gid(s, k) for s in COMPARE_SCOPES for k in ("ylabel", "title")]
    all_text.append(gid("compare_processed", "xlabel"))
    top_set = [gid(COMPARE_TOP_SCOPE, k) for k in ("axes", "ylabel", "title")]
    top_set.append(gid(COMPARE_TOP_SCOPE, "curve", ACTIVE_CURVES[COMPARE_TOP_SCOPE][0]))
    keep = ["ftir.curve_arrays", "ftir.processing_chain", "ftir.view_windows"]
    root = gid(scope, "root")

    parameters = [
        _native.param("canvas_w_mm", ["canvas_w_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="x",
                      minimum=SCALARS["canvas_w_mm"][1], maximum=SCALARS["canvas_w_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="x", preserve=keep)),
        _native.param("canvas_h_mm", ["canvas_h_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="y",
                      minimum=SCALARS["canvas_h_mm"][1], maximum=SCALARS["canvas_h_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="y", preserve=keep)),
        _native.param("render_dpi", ["render_dpi"], unit="dpi", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis=None,
                      minimum=SCALARS["render_dpi"][1], maximum=SCALARS["render_dpi"][2],
                      expected=_native.expect("style", objects=[canvas], preserve=["ftir.view_windows"])),
    ]
    for key, axis in (("compare_left_mm", "x"), ("compare_right_mm", "x"),
                      ("compare_bottom_mm", "y"), ("compare_top_mm", "y")):
        parameters.append(_native.param(
            key, [key], unit="mm", mutability="EDITABLE", scopes=list(SCOPES),
            objects=both_axes, operation="rebuild", axis=axis,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("resize", objects=both_axes, axis=axis, preserve=keep)))
    parameters.append(_native.param(
        "compare_panel_h_mm", ["compare_panel_h_mm"], unit="mm", mutability="EDITABLE",
        scopes=list(SCOPES), objects=both_axes, operation="rebuild", axis="y",
        minimum=SCALARS["compare_panel_h_mm"][1], maximum=SCALARS["compare_panel_h_mm"][2],
        expected=_native.expect("resize", objects=both_axes, axis="y", preserve=keep)))
    parameters.append(_native.param(
        "compare_gap_mm", ["compare_gap_mm"], unit="mm", mutability="EDITABLE",
        scopes=list(SCOPES), objects=top_set, operation="translate", axis="y", scale=1.0,
        minimum=SCALARS["compare_gap_mm"][1], maximum=SCALARS["compare_gap_mm"][2],
        expected=_native.expect("translate", objects=top_set, axis="y", preserve=keep)))
    for key in ("axis_font_pt", "tick_font_pt", "label_font_pt", "line_width"):
        target = all_text if "font_pt" in key else [gid(s, "curve", ACTIVE_CURVES[s][0]) for s in COMPARE_SCOPES]
        parameters.append(_native.param(
            key, [key], unit="pt", mutability="FIXED_STYLE", scopes=list(SCOPES),
            objects=target if key != "tick_font_pt" else [], operation="rebuild", axis=None,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("style", objects=target, preserve=keep)))
    parameters.append(_native.param(
        "band_limits_cm1", ["band_limits_cm1"], unit="cm-1", mutability="LOCKED_SCIENCE",
        scopes=list(SCOPES), objects=[], operation="rebuild", axis=None,
        expected=_native.expect("style", objects=[],
                                preserve=["ftir.band_windows", "ftir.view_windows"])))
    sid = ACTIVE_CURVES[scope][0]
    parameters.append(_native.param(
        f"shifts_mm.{scope}.{sid}", ["shifts_mm", scope, sid], unit="mm", mutability="EDITABLE",
        scopes=[scope], objects=[own_curve], operation="translate", axis="y", scale=1.0,
        minimum=-SHIFT_LIMIT_MM, maximum=SHIFT_LIMIT_MM,
        expected=_native.expect("translate", objects=[own_curve], axis="y", preserve=keep)))

    relations = [
        _native.relation("compare.contain_x", "contain", [canvas, own_axes], axis="x",
                         controlled_by=[["canvas_w_mm"], ["compare_left_mm"], ["compare_right_mm"]]),
        _native.relation("compare.contain_y", "contain", [canvas, own_axes], axis="y",
                         controlled_by=[["canvas_h_mm"], ["compare_bottom_mm"], ["compare_top_mm"],
                                        ["compare_panel_h_mm"], ["compare_gap_mm"]]),
        _native.relation("compare.margin_left", "gap", [canvas, own_axes], axis="x", anchor="left",
                         controlled_by=[["compare_left_mm"]], move=[own_axes]),
        _native.relation("compare.margin_right", "gap", [canvas, own_axes], axis="x", anchor="right",
                         controlled_by=[["compare_right_mm"]], move=[own_axes]),
        _native.relation("compare.equal_panel_height", "equal_size", both_axes, axis="y",
                         controlled_by=[["compare_panel_h_mm"]]),
        _native.relation("compare.panel_gap", "gap", [gid("compare_processed", "axes"), gid(COMPARE_TOP_SCOPE, "axes")],
                         axis="y", anchor="bottom", controlled_by=[["compare_gap_mm"]], move=top_set),
    ]
    if scope == COMPARE_TOP_SCOPE:
        relations.append(_native.relation(
            "compare.margin_top", "gap", [canvas, own_axes], axis="y", anchor="top",
            controlled_by=[["compare_top_mm"]], move=[own_axes]))
    else:
        relations.append(_native.relation(
            "compare.margin_bottom", "gap", [canvas, own_axes], axis="y", anchor="bottom",
            controlled_by=[["compare_bottom_mm"]], move=[own_axes]))

    return _native.contract_record(
        sys.modules[__name__], scope, parameters=parameters, nodes=_nodes(scope),
        groups=[
            _native.group(root, parent=None, members=[own_axes, own_curve]),
            _native.group(gid(scope, "text"), parent=root,
                          members=[g for g in (gid(scope, "xlabel"), gid(scope, "ylabel"),
                                               gid(scope, "title")) if g in _nodes(scope)]),
        ],
        relations=relations,
        outputs=[f"{FIGURE_ID}_compare.{ext}" for ext in OUTPUT_FORMATS],
        source={"shared_output_scopes": list(COMPARE_SCOPES), "scene_siblings": [other_axes]})


# ── 科学自检（strict 会用它拒绝发布） ───────────────────────────────────────
def _expected_series(science: dict, scope: str, sid: str):
    """某个作用域里 sid 这条曲线应该画成什么：对照图下格是"处理后"。"""
    index = CURVE_IDS.index(sid)
    if scope == "compare_processed":
        return science["processed"][index]
    return science["curves"][index]


def _scope_title(scope: str) -> str:
    return "Raw" if scope == COMPARE_TOP_SCOPE else "Processed"


def science_selfcheck(science: dict, fig=None) -> list[str]:
    """受保护内容的自检：数据、窗口、文本。返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    expected_x = fixture_data.ftir_x()
    if not np.all(np.diff(expected_x) < 0):
        problems.append("SCIENCE_GRID: 波数网格不再严格递减")

    for index, sid in enumerate(CURVE_IDS):
        x, y = science["curves"][index]
        px, py = science["processed"][index]
        if x.shape != expected_x.shape or y.shape != x.shape:
            problems.append(f"SCIENCE_PAYLOAD: 曲线 {sid} 形状 {x.shape}/{y.shape} 与受保护网格 {expected_x.shape} 不符")
            continue
        if not np.array_equal(x, expected_x):
            problems.append(f"SCIENCE_GRID: 曲线 {sid} 的 x 网格与受保护网格不一致")
        if not np.all(np.isfinite(y)) or not np.all(np.isfinite(py)):
            problems.append(f"SCIENCE_PAYLOAD: 曲线 {sid} 含 NaN/Inf")
        if not np.array_equal(px, x):
            problems.append(f"SCIENCE_GRID: 曲线 {sid} 的「处理后」x 网格变了（处理链不许改网格）")
        want = np.convolve(np.concatenate([np.full(fixture_data.FTIR_PROCESS_WINDOW // 2, y[0]), y,
                                           np.full(fixture_data.FTIR_PROCESS_WINDOW // 2, y[-1])]),
                           np.full(fixture_data.FTIR_PROCESS_WINDOW,
                                   1.0 / fixture_data.FTIR_PROCESS_WINDOW), mode="valid")
        if not np.array_equal(py, want):
            problems.append(f"SCIENCE_PROCESSING: 曲线 {sid} 的「处理后」不再是声明的 "
                            f"{fixture_data.FTIR_PROCESS_WINDOW} 点滑动平均")

    if fig is None:
        return problems

    by_gid = _native.artists_by_gid(fig)
    for scope in SCOPES:
        for sid in ACTIVE_CURVES[scope]:
            art = by_gid.get(gid(scope, "curve", sid))
            if art is None:
                continue
            want_x, want_y = _expected_series(science, scope, sid)
            if not (np.array_equal(np.asarray(art.get_xdata(), float), want_x)
                    and np.array_equal(np.asarray(art.get_ydata(), float), want_y)):
                problems.append(f"SCIENCE_PAYLOAD: {scope} 曲线 {sid} 的绘图数组 != 受保护数组")
        ax = by_gid.get(gid(scope, "axes"))
        if ax is not None:
            if not np.allclose(ax.get_xlim(), science["xlim"], atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} xlim 变成了 {tuple(ax.get_xlim())}")
            if not np.allclose(ax.get_ylim(), science["ylim"], atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} ylim 变成了 {tuple(ax.get_ylim())}")
        if scope in COMPARE_SCOPES:
            title = by_gid.get(gid(scope, "title"))
            if title is not None and title.get_text() != _scope_title(scope):
                problems.append(f"SCIENCE_TEXT: {scope} 的格标题被改成了 {title.get_text()!r}")
            continue
        for bid, (lo, hi) in science["bands"].items():
            span = by_gid.get(gid(scope, "band", bid))
            if span is not None:
                # axvspan 返回 Rectangle：窗口范围走 get_x()/get_width()（数据坐标）。
                # 注意 get_verts()/get_xy() 在 mpl 3.10 上给的不是同一件事。
                got = (float(span.get_x()), float(span.get_x() + span.get_width()))
                if not np.allclose(got, (lo, hi), atol=1e-9):
                    problems.append(f"SCIENCE_WINDOW: {scope} 带位 {bid} 的显示窗口变成了 {got}")
            label = by_gid.get(gid(scope, "band_label", bid))
            if label is not None and label.get_text() != science["band_text"][bid]:
                problems.append(f"SCIENCE_TEXT: {scope} 带位 {bid} 的文本被改成了 {label.get_text()!r}")
    return problems


if __name__ == "__main__":
    raise SystemExit(_native.run(sys.modules[__name__]))
