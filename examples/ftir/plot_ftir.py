#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fig.2 FTIR —— 五样品透过率叠图
设计规范：../DESIGN.md ｜ 统一样式：../figure_style.py
"""
from pathlib import Path
import argparse
import json
import math
import re
import shutil
import sys
import tempfile

import numpy as np
import yaml
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.transforms import ScaledTranslation

# Windows 上 stdout 一旦不是真控制台（被重定向、被别的程序接管管道），
# 就退回系统区域编码（GBK/cp1252）。本脚本的 QA 行里有 ✗ / «» / 上下标字符，
# 一句 print 就是 UnicodeEncodeError 直接打死进程——调用方看到的是「严格模式
# 拒绝了这张图」，其实是编码崩溃，退出码还同样是 1。**在做任何输出之前钉死 UTF-8。**
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):   # pythonw 下是 None，或非 TextIOWrapper
        pass

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents
                             if (p / "figpact").is_dir())))
import figure_style as fs
from figpact import load_config, apply_display_shift, GidRegistry, qa, publish as fp_publish, inventory as fp_inventory
from figpact.config import ConfigError

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "2084_1788253487778_26083154776" / "26083154776"

#: 对象身份的前缀。**不是配置项**：gid 是外部引用（Tavotto、配置、Skill）认的
#: 名字，做成可改的旋钮只会让所有引用悄悄失效。
FIGURE_ID = "fig2_ftir"

# 色值全部来自统一色表（DESIGN.md §3.1）；第 4 项是**稳定 id**：
# YAML 的 shifts_mm 与每个 artist 的 gid 都用它，不用 lines_2 这类自动名。
SAMPLES = [
    (1, "HA",                 fs.c("HA"),                    "ha"),
    (2, "ZnO",                fs.c("ZnO"),                   "zno"),
    (3, "HAMA",               fs.c("MOD_HA"),                "hama"),
    (4, r"HAMA/Cu$^{2+}$/ZnO",         fs.c("COMPOSITE_MICROSPHERE"), "hama_cu_zno"),
    (5, r"HA + HAMA/Cu$^{2+}$/ZnO",    fs.c("COMPOSITE_GEL"),         "gel"),
]

# FTIR 归属窗口：阴影带 + 两层文字标签（第 4 项同样是稳定 id）
BANDS = [
    (3200, 3550, "O–H",            "oh"),
    (1580, 1680, "COO$^{-}$/C=C",  "coo_cc"),
    (1380, 1450, "COO$^{-}$",      "coo"),
    (1000, 1100, "C–O–C",          "coc"),
    (400,  560,  "Zn–O",           "zn_o"),
]

CURVE_IDS = tuple(sid for _, _, _, sid in SAMPLES)


# ──────────────────────────────────────────────────────────────────────────────
# 配置：排版参数唯一入口
# ──────────────────────────────────────────────────────────────────────────────
#: 字号参数的**可接受区间**。下界不是出版下限：出版下限 5 pt（含上下标的文字
#: 母体还要 7.143）由 `fs.qa_report` / `fs.audit_pdf` 报 ✗ ——那是排版取舍。
#: 把出版下限钉在这里，等于让存量违规值搬不进配置，改造就变成了改外观；
#: 这里的下界只挡"排版上说不通"的值。
FONT_RANGE = (3.0, 12.0)

#: key → (类型, 下界, 上界)。
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 20.0, 200.0),
    "canvas_h_mm": (float, 20.0, 200.0),
    "label_font_pt": (float, *FONT_RANGE),
    "legend_font_pt": (float, *FONT_RANGE),
    "label_edge_margin_mm": (float, 0.0, 6.0),
    "label_gap_top_mm": (float, 0.0, 8.0),
    "curve_gap_mm": (float, 0.5, 8.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "note_font_pt": (float, *FONT_RANGE),
    "line_width": (float, 0.2, 3.0),
    "legend_cols": (int, 1, 3),
    "legend_anchor_x": (float, 0.0, 1.0),
    "stack_gap": (float, 0.0, 80.0),
    "stack_gap_annotated": (float, 0.0, 80.0),
    "stack_lift_annotated_mm": (float, -5.0, 5.0),
}
#: 单条曲线的显示位移上限（mm）。再大就不是排版微调，是画错了。
SHIFT_LIMIT_MM = 10.0

#: 输出版本作用域。**一次 `draw_panel()` 调用 = 一个作用域**：
#: gid 里带它（对象才能跨 Axes 唯一）、`shifts_mm` 按它分档（改论文主图
#: 不该顺手改掉 SI 对照图）。第三张图上下两格是两个不同的 Axes，必须分开，
#: 否则 SVG/PDF 里会出现重复 id。
SCOPES = ("main", "annotated", "compare_raw", "compare_processed")


def _number(path: Path, key: str, value) -> float:
    """数字校验的唯一出口。bool 是 int 的子类（`True` 会当 1 吃下去），
    NaN / ±Inf 能穿过所有区间比较（`lo <= nan` 恒为 False），两种都必须在这里挡掉。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path.name}：{key} 必须是数字，得到 {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{path.name}：{key} 必须是有限数，得到 {value!r}")
    return float(value)


def _cli(argv: list[str]) -> argparse.Namespace:
    """命令行严格解析。"""
    ap = argparse.ArgumentParser(
        prog=Path(__file__).name, add_help=True, allow_abbrev=False,
        description="Fig.2 FTIR 面板出图；排版参数在 ftir.yaml，命令行只选配置与模式")
    ap.add_argument("--config", default=None,
                    help="配置文件路径（默认：脚本旁边的 ftir.yaml）")
    ap.add_argument("--list-params", action="store_true",
                    help="打印全部参数（当前值 / 允许范围）与所有可位移 gid，然后退出")
    ap.add_argument("--strict", action="store_true",
                    help="有**未豁免**阻断项时退出码非零，且不覆盖已存在的正式输出")
    ap.add_argument("--exempt-current", action="store_true",
                    help="把当前全部阻断项写成人工豁免（必须同时给 --reason）")
    ap.add_argument("--reason", default="", help="人工豁免的理由（写进 qa_exemptions.json）")
    ap.add_argument("--inventory", action="store_true",
                    help="打印当前图表可见图元清单 (JSON 格式)，供 figpact inventory 消费")
    ap.add_argument("--check-effect", action="store_true",
                    help="在清点中执行参数生效扰动检查")
    ap.add_argument("--inspect", default=None,
                    help="检查指定 gid 的图元信息")
    return ap.parse_args(argv)


ARGS = _cli(sys.argv[1:])
CONFIG_PATH = Path(ARGS.config).expanduser() if ARGS.config else ROOT / "ftir.yaml"


SCHEMA = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 20.0, 200.0),
    "canvas_h_mm": (float, 20.0, 200.0),
    "label_font_pt": (float, *FONT_RANGE),
    "legend_font_pt": (float, *FONT_RANGE),
    "label_edge_margin_mm": (float, 0.0, 6.0),
    "label_gap_top_mm": (float, 0.0, 8.0),
    "curve_gap_mm": (float, 0.5, 8.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "note_font_pt": (float, *FONT_RANGE),
    "line_width": (float, 0.2, 3.0),
    "legend_cols": (int, 1, 3),
    "legend_anchor_x": (float, 0.0, 1.0),
    "stack_gap": (float, 0.0, 80.0),
    "stack_gap_annotated": (float, 0.0, 80.0),
    "stack_lift_annotated_mm": (float, -5.0, 5.0),
    "shifts_mm": (dict,),
}


def load_config_ftir(path: Path) -> dict:
    """使用 figpact 引擎校验配置并标准化 shifts_mm。"""
    cfg = load_config(path, SCHEMA)

    raw_shifts = cfg.get("shifts_mm") or {}
    if not isinstance(raw_shifts, dict):
        raise ConfigError(f"{path.name}：shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw_shifts) - set(SCOPES)):
        raise ConfigError(f"{path.name}：shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")

    normalized_shifts = {scope: {sid: 0.0 for sid in CURVE_IDS} for scope in SCOPES}
    for scope, per_curve in raw_shifts.items():
        if per_curve is None:
            continue
        if not isinstance(per_curve, dict):
            raise ConfigError(f"{path.name}：shifts_mm.{scope} 必须是 `曲线id: 毫米` 映射")
        if unknown := sorted(set(per_curve) - set(CURVE_IDS)):
            raise ConfigError(f"{path.name}：shifts_mm.{scope} 里有未知曲线 {unknown}；可用：{list(CURVE_IDS)}")
        for sid, value in per_curve.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{path.name}：shifts_mm.{scope}.{sid} 必须是数字")
            val_f = float(value)
            if not math.isfinite(val_f):
                raise ConfigError(f"{path.name}：shifts_mm.{scope}.{sid} 不能是 NaN 或 Inf")
            if abs(val_f) > SHIFT_LIMIT_MM:
                sug = min(max(val_f, -SHIFT_LIMIT_MM), SHIFT_LIMIT_MM)
                raise ConfigError(f"{path.name}：shifts_mm.{scope}.{sid} = {val_f} 超出 ±{SHIFT_LIMIT_MM} mm；建议改成 {sug}")
            normalized_shifts[scope][sid] = val_f

    cfg["shifts_mm"] = normalized_shifts
    return cfg


CONFIG = load_config_ftir(CONFIG_PATH)

def list_params() -> None:
    """人类与模型调参专用的结构化清单：按可见对象分组，含单位、范围与调大效果。"""
    print(f"配置文件：{CONFIG_PATH}\n")
    groups = [
        ("画布 (Canvas)", [
            ("canvas_w_mm", "画布物理宽度", "mm", SCALARS["canvas_w_mm"][1:], "面板物理宽度增加，字号保持不变"),
            ("canvas_h_mm", "画布物理高度", "mm", SCALARS["canvas_h_mm"][1:], "面板物理高度增加，垂直排版空间更充裕"),
        ]),
        ("坐标轴与刻度 (Axes & Ticks)", [
            ("axis_font_pt", "坐标轴标题字号", "pt", SCALARS["axis_font_pt"][1:], "轴标题变大；过大可能与刻度数字挤在一起"),
            ("tick_font_pt", "刻度数字字号", "pt", SCALARS["tick_font_pt"][1:], "刻度文字变大，行高变大"),
            ("note_font_pt", "对照版小注字号", "pt", SCALARS["note_font_pt"][1:], "raw/processed 对照版左上角说明文字变大"),
        ]),
        ("图例 (Legend)", [
            ("legend_font_pt", "图例字号", "pt", SCALARS["legend_font_pt"][1:], "图例框变高，顶部预留变多，谱线整体下移"),
            ("legend_cols", "图例列数", "列", SCALARS["legend_cols"][1:], "列数变多则图例变宽变扁，纵向占用高度减小"),
            ("legend_anchor_x", "图例水平锚点", "比率", SCALARS["legend_anchor_x"][1:], "图例向右靠（1.0最右，太小向左靠会压住y轴标题）"),
        ]),
        ("系列/谱线 (Curves/Series)", [
            ("line_width", "谱线线宽", "pt", SCALARS["line_width"][1:], "所有谱线变粗，仅影响观感不改布局"),
            ("stack_gap", "主图谱线间距", "a.u.", SCALARS["stack_gap"][1:], "相邻谱线白缝变大，但曲线幅度相对压缩（跷跷板）"),
            ("stack_gap_annotated", "标注版谱线间距", "a.u.", SCALARS["stack_gap_annotated"][1:], "标注版相邻谱线间距变大，纵向舒展"),
            ("stack_lift_annotated_mm", "标注版整体上移", "mm", SCALARS["stack_lift_annotated_mm"][1:], "标注版曲线和标签一起上移，底部留白变大"),
        ]),
        ("标注 (Annotations)", [
            ("label_font_pt", "官能团标签字号", "pt", SCALARS["label_font_pt"][1:], "标签变大，标签块总高度可能增加并压缩曲线空间"),
            ("curve_gap_mm", "曲线与标签净空(总闸)", "mm", SCALARS["curve_gap_mm"][1:], "标签块底与谱线顶拉开；调小则谱线组长高并整体上移"),
            ("label_gap_top_mm", "图例与标签净空", "mm", SCALARS["label_gap_top_mm"][1:], "图例底与标签块顶拉开，标签块整体下移"),
            ("label_edge_margin_mm", "标签距左右框边距", "mm", SCALARS["label_edge_margin_mm"][1:], "Zn-O 等贴边标签向内缩进避开左右边框"),
        ]),
    ]

    for grp_name, params in groups:
        print(f"=== {grp_name} ===")
        print(f"  {'key':<24}{'中文名':<16}{'当前值':>8} {'单位':<5} {'允许范围':<14} 调大会怎样")
        for key, cname, unit, (lo, hi), desc in params:
            val_str = str(CONFIG[key])
            rng_str = f"[{lo}, {hi}]"
            print(f"  {key:<24}{cname:<16}{val_str:>8} {unit:<5} {rng_str:<14} {desc}")
        print()

    print("=== 位移 (Shifts) ===")
    print("  可位移参数 key: shifts_mm.<作用域>.<曲线id> (单位 mm，范围 [-10.0, 10.0]，正数向上)")
    print("  调大会怎样: 仅该条曲线纯显示向上平移指定毫米，不动科研数据与其他曲线")
    print("  可用作用域与曲线 id:")
    for scope in SCOPES:
        print(f"    [{scope}] " + "、".join(f"{sid}" for sid in CURVE_IDS))
    print("  使用方式: 在 yaml 中配置 shifts_mm: { <scope>: { <sid>: 1.0 } }")


if ARGS.list_params:
    list_params()
    raise SystemExit(0)


# 归属标签与图例的字号是**同一份**：测量（_tier_geometry）与实际落字
# （draw_bands）分开写死两个数，字号一改就会「量出来三层、画出来两层」。
LABEL_FS = CONFIG["label_font_pt"]
LEGEND_FS = CONFIG["legend_font_pt"]
# 贴边框的归属标签（Zn–O 在 400–560，本来就挤在右框上）至少离框这么多；
# QA 的“贴边”红线是 1.0 mm，取 1.5 留出余量。
EDGE_MARGIN_MM = CONFIG["label_edge_margin_mm"]
# 图例底 → 标签块顶的净空（mm）。标签块本身贴不到图例里，这个值只能小幅调。
LABEL_GAP_TOP_MM = CONFIG["label_gap_top_mm"]
# 标签块底（无标注版：图例底）→ 谱线顶的净空（mm）。**这里就是纵向空间的总闸**：
# 它每收 1 mm，谱线组就长高 1 mm、整体上移 1 mm。下限 0.5 是因为
# draw_bands 要求标签必须落在 ymax + 0.5 mm 之上。
CURVE_GAP_MM = CONFIG["curve_gap_mm"]
# 相邻谱线基线的间距（数据单位）。55 是逐谱等高归一化后的谱深，
# 间距越接近谱深，谱线越像贴在一起。
TRACE_GAP = CONFIG["stack_gap"]
# 标注版：增大谱线间距，并在最终坐标范围内整体上移（毫米）。
ANNOTATED_TRACE_GAP = CONFIG["stack_gap_annotated"]
ANNOTATED_TRACE_LIFT_MM = CONFIG["stack_lift_annotated_mm"]
# 逐曲线显示位移（mm）：`{作用域: {曲线id: 毫米}}`，布局冻结后生效，见 apply_display_shift()
SHIFTS_MM = CONFIG["shifts_mm"]
# 图上每一类**可见文字与线**都要有入口：轴标题 / 刻度数字 / 小注 / 谱线线宽 / 图例列数与水平锚点。
# 没进 YAML 的两类，理由写在这里，免得下一个人以为是漏了：
#   * 坐标框与刻度线的线宽 → 由 `figure_style.apply()` 的全局 rcParams 定，
#     必须与 NMR/XRD 一致，**按图暴露就等于允许三张图长不一样**；
#   * 图例的**纵向**位置 → 纵向空间是按"图例占顶部 legend_h_mm"算的
#     （reserved = legend_h + 净空 + 标签块 + 净空）。图例挪到下面，
#     这套预留就跟实际不符，标签会被放到没有图例的地方。要支持得先改预留模型。
AXIS_FS = CONFIG["axis_font_pt"]
TICK_FS = CONFIG["tick_font_pt"]
NOTE_FS = CONFIG["note_font_pt"]
LINE_WIDTH = CONFIG["line_width"]
LEGEND_COLS = CONFIG["legend_cols"]
LEGEND_ANCHOR_X = CONFIG["legend_anchor_x"]
# `--strict`：存在**阻断项**时退出码非零，且**不覆盖**已存在的正式输出。
# 默认不加 = 预览模式：照常发布，但把阻断项打在 stdout 上。
STRICT = ARGS.strict
#: 出图先写这里，最后一步才发布到 ROOT。`--strict` 检出阻断项时，
#: 项目目录里原有的正式输出一个字节都不动。
#: 人工豁免。**阻断项不许记进豁免**——那是"违规却报告成功"。
#: 豁免是人签的字：每条必须带非空 reason，strict 输出会逐条列出理由，
#: 并且**永远不会**在存在阻断项时打印「无阻断项 ✓」。
EXEMPT_PATH = ROOT / "qa_exemptions.json"


def _signature(problem: str) -> str:
    """把 QA 文本压成稳定签名：面积/点数/毫米都随 dpi 变，一律抹成 #。"""
    return re.sub(r"[-\d.]+", "#", problem).strip()


def load_exemptions() -> dict:
    if not EXEMPT_PATH.is_file():
        return {}
    data = json.loads(EXEMPT_PATH.read_text(encoding="utf-8"))
    out = {}
    for item in data.get("exemptions", []):
        sig, reason = str(item.get("signature", "")), str(item.get("reason", "")).strip()
        if sig and reason:
            out[sig] = reason
        elif sig:
            print(f"[豁免] 忽略无 reason 的条目：{sig[:60]}")
    return out


STAGING = Path(tempfile.mkdtemp(prefix="ftir-stage-"))
FTIR_CANVAS = (CONFIG["canvas_w_mm"], CONFIG["canvas_h_mm"])

fs.apply()


# ──────────────────────────────────────────────────────────────────────────────
# 数据
# ──────────────────────────────────────────────────────────────────────────────
def load_spectra(processed: bool) -> list[tuple[np.ndarray, np.ndarray]]:
    suffix = "-处理后" if processed else ""
    spectra = []
    for number, _, _, _ in SAMPLES:
        path = DATA_DIR / f"{number}{suffix}.CSV"
        data = np.loadtxt(path, delimiter=",")
        if data.ndim != 2 or data.shape[1] != 2:
            raise ValueError(f"Unexpected CSV shape: {path} -> {data.shape}")
        x, y = data[:, 0], data[:, 1]
        mask = (x >= 400) & (x <= 4000)
        x, y = x[mask], y[mask]
        if np.any(np.diff(x) <= 0):
            raise ValueError(f"Wavenumber axis is not strictly increasing: {path}")
        spectra.append((x, y))

    reference_x = spectra[0][0]
    if not all(np.array_equal(reference_x, x) for x, _ in spectra[1:]):
        raise ValueError("The five spectra do not share one common wavenumber grid")
    return spectra


def absorbance_to_transmittance(spectra):
    """仪器输出为吸光度 A；按 T(%) = 100 × 10^(−A) 转换。"""
    return [(x, 100.0 * np.power(10.0, -y)) for x, y in spectra]


def normalize_spectra(spectra, target_depth: float = 55.0):
    """逐谱等高归一化：基线=100，最深谷=100−target_depth（保留谱内真实比例）。"""
    out = []
    for x, y in spectra:
        ymin, ymax = float(np.nanmin(y)), float(np.nanmax(y))
        y_norm = (np.full_like(y, 100.0) if ymax == ymin
                  else 100.0 - ((ymax - y) / (ymax - ymin)) * target_depth)
        out.append((x, y_norm))
    return out


def compute_offsets(spectra, gap: float = TRACE_GAP) -> list[float]:
    offsets, previous_top = [], 0.0
    for _, y in spectra:
        lower, upper = float(np.nanmin(y)), float(np.nanmax(y))
        offset = max(0.0, previous_top + gap - lower)
        offsets.append(offset)
        previous_top = offset + upper
    return offsets


# ──────────────────────────────────────────────────────────────────────────────
# 绘制
# ──────────────────────────────────────────────────────────────────────────────
def add_legend(fig, ax, scope: str, reg: GidRegistry | None = None):
    """框内右上角；长样品名仅换行，不删文字。"""
    handles = [Line2D([], [], color=color, lw=1.2, solid_capstyle="round", label=label)
               for _, label, color, _ in reversed(SAMPLES)]
    legend = ax.legend(
        handles=handles,
        loc="upper right",
        bbox_to_anchor=(LEGEND_ANCHOR_X, 0.99),
        frameon=False,
        fontsize=LEGEND_FS,
        ncol=LEGEND_COLS,
        columnspacing=0.25,
        handlelength=0.5,
        handletextpad=0.2,
        labelspacing=0.05,
        borderaxespad=0.1,
        borderpad=0.1,
    )
    for t in legend.get_texts():
        t.set_color(fs.c("TEXT"))
    leg_gid = f"{FIGURE_ID}.{scope}.legend"
    legend.set_gid(leg_gid)
    legend.set_zorder(6)
    if reg is not None:
        reg.register(legend, leg_gid, params=["legend_font_pt", "legend_cols", "legend_anchor_x"])
    return legend


def _tier_geometry(ax):
    """按各标签实测宽度和边框钳制后的区间分层，避免把短标签当作最长标签。"""
    fig = ax.figure
    fig.canvas.draw()
    width_mm = ax.get_window_extent().width * 25.4 / fig.dpi
    x0, x1 = ax.get_xlim()
    mm_per_unit = width_mm / abs(x1 - x0)
    widths, height_mm = fs.measure_text_boxes_mm(
        ax, [t for _, _, t, _ in BANDS], LABEL_FS)
    tiers, positions, occupied = [], [], []
    for (lo, hi, _, _), width in zip(BANDS, widths):
        half = width / (2.0 * mm_per_unit)
        margin = EDGE_MARGIN_MM / mm_per_unit
        center = min(max((lo + hi) / 2.0, min(x0, x1) + half + margin),
                     max(x0, x1) - half - margin)
        left, right = center - half, center + half
        tier = next((i for i, boxes in enumerate(occupied)
                     if all(right + 0.2 / mm_per_unit <= a or
                            b + 0.2 / mm_per_unit <= left for a, b in boxes)),
                    len(occupied))
        if tier == len(occupied):
            occupied.append([])
        occupied[tier].append((left, right))
        positions.append(center)
        tiers.append(tier)
    return positions, tiers, height_mm


def draw_bands(ax, y_top: float, top_limit: float, scope: str, reg: GidRegistry | None = None) -> str:
    """保留整高阴影带，标签按实测宽度分层放在谱线与图例之间。"""
    for lo, hi, _, _ in BANDS:
        fs.shade_band(ax, lo, hi)
    positions, tiers, height_mm = _tier_geometry(ax)
    units_per_mm = abs(ax.get_ylim()[1] - ax.get_ylim()[0]) / (
        ax.get_window_extent().height * 25.4 / ax.figure.dpi)
    text_height = height_mm * units_per_mm
    step = text_height * 1.10
    for center, tier, (_, _, text, bid) in zip(positions, tiers, BANDS):
        y = top_limit - text_height - (max(tiers) - tier) * step
        if y < y_top:
            raise RuntimeError("归属标签带不足，不能压缩标签层间距")
        label = ax.text(center, y, text, ha="center", va="bottom",
                        fontsize=LABEL_FS, color=fs.c("ANNOT"), zorder=5)
        band_gid = f"{FIGURE_ID}.{scope}.band.{bid}"
        label.set_gid(band_gid)
        if reg is not None:
            reg.register(label, band_gid, params=["label_font_pt", "label_gap_top_mm", "label_edge_margin_mm"])
    return "tiered"


def report_shift_bounds(fig, name: str) -> None:
    """把位移越界报成 QA 的一行。**只报不改**：不自动缩字号、不自动改位移。"""
    problems = qa.check_out_of_frame(fig)
    if problems:
        print(f"[QA] {name}: {len(problems)} 处显示位移越界 ✗")
        for p in problems:
            print("      ", p)
    elif any(any(v.values()) for v in SHIFTS_MM.values()):
        print(f"[QA] {name}: 显示位移未越界 ✓")


def blocking_problems(fig) -> list[str]:
    """阻断项：调用 figpact.qa 与谱线净空检查。"""
    order = [sid for _, _, _, sid in SAMPLES]
    return (qa.blocking_problems(fig)
            + qa.check_series_order(fig, order, min_mm=0.5))

def draw_panel(ax, spectra, *, scope: str, processed: bool, annotate=False, reg: GidRegistry | None = None):
    """画一格。`scope` 是输出版本作用域（见 SCOPES），gid 与显示位移都按它隔离。"""
    global CURVES
    if scope not in SCOPES:
        raise ValueError(f"未知作用域 {scope!r}；可用：{list(SCOPES)}")
    offsets = compute_offsets(
        spectra, gap=ANNOTATED_TRACE_GAP if annotate else TRACE_GAP)
    CURVES = [(np.asarray(x, dtype=float), np.asarray(y + o, dtype=float))
              for (x, y), o in zip(spectra, offsets)]
    lines: list[tuple] = []
    for (x, y), (_, _, color, sid), offset in zip(spectra, SAMPLES, offsets):
        line, = ax.plot(x, y + offset, color=color, lw=LINE_WIDTH)
        curve_gid = f"{FIGURE_ID}.{scope}.curve.{sid}"
        line.set_gid(curve_gid)
        lines.append((line, sid))
        if reg is not None:
            reg.register(line, curve_gid, params=["line_width", "stack_gap", "shifts_mm"])

    ymax = max(offset + float(np.nanmax(y)) for (_, y), offset in zip(spectra, offsets))
    ymin = min(offset + float(np.nanmin(y)) for (_, y), offset in zip(spectra, offsets))
    y_bottom = ymin - 2.5
    R = ymax - y_bottom

    ax.set_xlim(4000, 400)
    ax.set_ylim(y_bottom, ymax + 1.0)
    fig = ax.figure
    legend = add_legend(fig, ax, scope, reg=reg)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_h_mm = ax.get_window_extent().height * 25.4 / fig.dpi
    legend_h_mm = legend.get_window_extent(renderer).height * 25.4 / fig.dpi
    band_h_mm = CURVE_GAP_MM
    if annotate:
        _, tiers, h_mm = _tier_geometry(ax)
        block_mm = h_mm * (1.0 + 1.10 * max(tiers))
        band_h_mm = LABEL_GAP_TOP_MM + block_mm + CURVE_GAP_MM
    reserved_mm = legend_h_mm + band_h_mm
    if reserved_mm >= axes_h_mm:
        raise RuntimeError("当前方形面板放不下图例与归属标签")
    y_span = R / (1.0 - reserved_mm / axes_h_mm)
    ax.set_ylim(y_bottom, y_bottom + y_span)
    if annotate:
        units_per_mm = y_span / axes_h_mm
        top_limit = y_bottom + y_span - (legend_h_mm + LABEL_GAP_TOP_MM) * units_per_mm
        draw_bands(ax, ymax + 0.5 * units_per_mm, top_limit=top_limit, scope=scope, reg=reg)
        lift = ANNOTATED_TRACE_LIFT_MM * units_per_mm
        ax.set_ylim(y_bottom - lift, y_bottom + y_span - lift)

    for line, sid in lines:
        apply_display_shift(line, dy_mm=SHIFTS_MM[scope][sid])

    fs.strip_yticks(ax)
    ax.set_xticks([4000, 3000, 2000, 1000])
    ax.tick_params(axis="x", labelsize=TICK_FS, pad=1)
    ax.set_ylabel("Transmittance (a.u.)", fontsize=AXIS_FS,
                  weight="bold", labelpad=3)
    if reg is not None:
        y_gid = f"{FIGURE_ID}.{scope}.ylabel"
        ax.yaxis.label.set_gid(y_gid)
        reg.register(ax.yaxis.label, y_gid, params=["axis_font_pt"])
    if processed:
        ax.set_title("Vendor-processed spectra · qualitative reference only",
                     loc="left", fontsize=NOTE_FS, weight="bold", pad=4)
        if reg is not None:
            t_gid = f"{FIGURE_ID}.{scope}.title"
            ax.title.set_gid(t_gid)
            reg.register(ax.title, t_gid, params=["note_font_pt"])
    ax.grid(False)
    return offsets


def add_xlabel(ax, scope: str | None = None, reg: GidRegistry | None = None):
    ax.set_xlabel(r"Wavenumber (cm$^{-1}$)", fontsize=AXIS_FS,
                  weight="bold", labelpad=2)
    if scope is not None and reg is not None:
        lbl = ax.xaxis.label
        gid = f"{FIGURE_ID}.{scope}.xlabel"
        lbl.set_gid(gid)
        reg.register(lbl, gid, params=["axis_font_pt"])


def build_figure_and_registry(scope_target: str = "annotated"):
    """构造 Figure 与 GidRegistry，用于绘图或清点。"""
    reg = GidRegistry()
    raw = normalize_spectra(absorbance_to_transmittance(load_spectra(processed=False)))
    proc = normalize_spectra(absorbance_to_transmittance(load_spectra(processed=True)))

    if scope_target == "main":
        fig, ax = plt.subplots(figsize=fs.canvas_mm(*FTIR_CANVAS))
        fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
        draw_panel(ax, raw, scope="main", processed=False, annotate=False, reg=reg)
        add_xlabel(ax, scope="main", reg=reg)
        return fig, reg
    elif scope_target == "annotated":
        fig, ax = plt.subplots(figsize=fs.canvas_mm(*FTIR_CANVAS))
        fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
        draw_panel(ax, raw, scope="annotated", processed=False, annotate=True, reg=reg)
        add_xlabel(ax, scope="annotated", reg=reg)
        return fig, reg
    elif scope_target.startswith("compare"):
        fig, axes = plt.subplots(2, 1, figsize=fs.canvas("SQ2"), sharex=True,
                                 gridspec_kw={"hspace": 0.20})
        fig.subplots_adjust(left=0.135, right=0.985, top=0.975, bottom=0.075)
        draw_panel(axes[0], raw, scope="compare_raw", processed=False, annotate=False, reg=reg)
        draw_panel(axes[1], proc, scope="compare_processed", processed=True, annotate=False, reg=reg)
        add_xlabel(axes[1], scope="compare_processed", reg=reg)
        return fig, reg
    else:
        raise ValueError(f"未知 scope_target: {scope_target}")


def make_figure():
    # 如果是 --inventory，构建代表性主图 (annotated 版)，清点并以 JSON 输出
    if ARGS.inventory:
        fig, reg = build_figure_and_registry("annotated")
        inv = fp_inventory(fig, reg, check_effect=ARGS.check_effect)
        print(json.dumps(inv, ensure_ascii=False, indent=2))
        plt.close(fig)
        return

    if ARGS.inspect:
        fig, reg = build_figure_and_registry("annotated")
        art = reg.get(ARGS.inspect)
        if art is None:
            print(f"未找到 gid: {ARGS.inspect}")
        else:
            print(f"[{ARGS.inspect}] {type(art).__name__} | 绑定参数: {reg.params_of(ARGS.inspect)}")
        plt.close(fig)
        return

    active = {s: {k: v for k, v in per.items() if v}
              for s, per in SHIFTS_MM.items() if any(per.values())}
    print(f"[配置] {CONFIG_PATH.name}: 画布 {FTIR_CANVAS[0]}×{FTIR_CANVAS[1]} mm · "
          f"标签 {LABEL_FS} pt · 图例 {LEGEND_FS} pt · 间距 {TRACE_GAP}/{ANNOTATED_TRACE_GAP}"
          + (f" · 位移 {active}" if active else ""))
    raw = normalize_spectra(absorbance_to_transmittance(load_spectra(processed=False)))
    proc = normalize_spectra(absorbance_to_transmittance(load_spectra(processed=True)))
    blockers: list[str] = []

    # ① 主图（干净版）
    fig, ax = plt.subplots(figsize=fs.canvas_mm(*FTIR_CANVAS))
    fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
    draw_panel(ax, raw, scope="main", processed=False, annotate=False)
    add_xlabel(ax, scope="main")
    fs.export(fig, STAGING / "Fig2_FTIR_transmittance_stacked")
    fs.qa_report(fig, "FTIR 主图")
    report_shift_bounds(fig, "FTIR 主图")
    blockers += blocking_problems(fig)
    plt.close(fig)

    # ② 归属标注版
    fig, ax = plt.subplots(figsize=fs.canvas_mm(*FTIR_CANVAS))
    fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
    draw_panel(ax, raw, scope="annotated", processed=False, annotate=True)
    add_xlabel(ax, scope="annotated")
    fs.export(fig, STAGING / "Fig2_FTIR_transmittance_stacked_annotated")
    fs.qa_report(fig, "FTIR 归属标注版")
    report_shift_bounds(fig, "FTIR 归属标注版")
    blockers += blocking_problems(fig)
    plt.close(fig)

    # ③ 原始 / 供应商处理 对照版：SQ2（上下两格，SI 用）
    fig, axes = plt.subplots(2, 1, figsize=fs.canvas("SQ2"), sharex=True,
                             gridspec_kw={"hspace": 0.20})
    fig.subplots_adjust(left=0.135, right=0.985, top=0.975, bottom=0.075)
    draw_panel(axes[0], raw, scope="compare_raw", processed=False, annotate=False)
    draw_panel(axes[1], proc, scope="compare_processed", processed=True, annotate=False)
    add_xlabel(axes[1], scope="compare_processed")
    fs.export(fig, STAGING / "Fig2_FTIR_transmittance_raw_processed")
    fs.qa_report(fig, "FTIR 原始/处理对照")
    report_shift_bounds(fig, "FTIR 原始/处理对照")
    blockers += blocking_problems(fig)
    plt.close(fig)

    exemptions_mgr = fp_publish.Exemptions(EXEMPT_PATH)
    if ARGS.exempt_current:
        exemptions_mgr.write(blockers, ARGS.reason)
        print(f"[豁免] 写入 {len(blockers)} 条 → {EXEMPT_PATH.name}；理由：{ARGS.reason.strip()}")

    exempt_dict = exemptions_mgr.load()
    exempted = [(b, exempt_dict[qa.signature(b)]) for b in blockers if qa.signature(b) in exempt_dict]
    new_blockers = [b for b in blockers if qa.signature(b) not in exempt_dict]
    if blockers:
        print(f"[验收] 阻断 {len(blockers)} 条，其中 {len(exempted)} 条人工豁免：")
        for _b, _why in exempted:
            print(f"      [豁免] {_b}")
            print(f"             理由：{_why}")
        for _b in new_blockers:
            print(f"      [未豁免] {_b}")
    if new_blockers and STRICT:
        print(f"[验收] **未豁免**阻断项 {len(new_blockers)} 条：**拒绝发布**，{ROOT.name} 里的正式输出未被覆盖")
        shutil.rmtree(STAGING, ignore_errors=True)
        sys.exit(1)
    if not blockers:
        print("[验收] 无阻断项 ✓")
    elif not new_blockers:
        print(f"[验收] 无**未豁免**阻断项；但有 {len(exempted)} 条人工豁免"
              f"（上面逐条列了理由）——不等于图已经干净")
    written = fp_publish.publish(STAGING, ROOT)
    shutil.rmtree(STAGING, ignore_errors=True)
    print(f"已发布 {len(written)} 个文件到 {ROOT}")


if __name__ == "__main__":
    make_figure()
