#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fig.2 FTIR —— 五样品透过率叠图
设计规范：../DESIGN.md ｜ 统一样式：../figure_style.py
"""
from pathlib import Path
import argparse
import copy
import json
import math
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
from figpact.relations import measure_relation, set_relation_target, remaining_space, validate_layout

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
    "schema_version": (int, 2, 2),
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
}
#: 单条曲线的显示位移上限（mm）。再大就不是排版微调，是画错了。
SHIFT_LIMIT_MM = 10.0

#: 输出版本作用域。**一次 `draw_panel()` 调用 = 一个作用域**：
#: gid 里带它（对象才能跨 Axes 唯一）、`shifts_mm` 按它分档（改论文主图
#: 不该顺手改掉 SI 对照图）。第三张图上下两格是两个不同的 Axes，必须分开，
#: 否则 SVG/PDF 里会出现重复 id。
SCOPES = ("main", "annotated", "compare_raw", "compare_processed")
RELATION_PARAMS = {"clearance_mm": ("vertical_clearance", CURVE_IDS[1:])}


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
    ap.add_argument("--probe", default=None,
                    help="试算沙箱目录：给定时产物只写这里，正式输出目录一个字节都不动")
    ap.add_argument("--migrate-config", help="把旧 YAML 的实测布局迁移到新文件（不发布图件）")
    return ap.parse_args(argv)


#: CLI 只在 `python plot_ftir.py …` 时解析。作为模块被 native runtime 导入时
#: **不碰调用方的 argv**（否则 worker 的协议参数会被 argparse 当场拒掉），
#: 也不输出、不落盘——import 只建立函数与基线配置。
ARGS = _cli(sys.argv[1:]) if __name__ == "__main__" else _cli([])
CONFIG_PATH = Path(ARGS.config).expanduser() if ARGS.config else ROOT / "ftir.yaml"


SCHEMA = {**SCALARS, "shifts_mm": (dict,), "clearance_mm": (dict,),
          "group_y_mm": (dict,), "layout_reference": (dict,)}


def prepare_config(config: dict, *, label: str | None = None) -> dict:
    """把任意来源的配置映射标准化成**构建路径能直接消费**的形态。

    **纯映射变换**：不读 YAML、不碰科研数据、不画图，输入映射不被修改（返回新字典）。
    legacy 装载（`load_config_ftir`）与 native 构建（`build_scene` 收到的候选配置）
    **共用这一份**，不存在第二套约定：YAML 里 `shifts_mm` 缺失 / 为 `{}` / 只写了部分
    作用域或曲线，一律补 0.0——这就是「不写 = 不动」的定义，而不是让 draw_panel 里
    的 `SHIFTS_MM[scope][sid]` 抛 KeyError。对已标准化的映射幂等（作用域与曲线齐全时
    输出与输入等价），所以 native 恒等重建与「基线已标准化、候选再标准化一次」都成立。
    """
    name = label or CONFIG_PATH.name
    cfg = dict(config)
    raw_shifts = cfg.get("shifts_mm") or {}
    if not isinstance(raw_shifts, dict):
        raise ConfigError(f"{name}：shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw_shifts) - set(SCOPES)):
        raise ConfigError(f"{name}：shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")

    normalized_shifts = {scope: {sid: 0.0 for sid in CURVE_IDS} for scope in SCOPES}
    for scope, per_curve in raw_shifts.items():
        if per_curve is None:
            continue
        if not isinstance(per_curve, dict):
            raise ConfigError(f"{name}：shifts_mm.{scope} 必须是 `曲线id: 毫米` 映射")
        if unknown := sorted(set(per_curve) - set(CURVE_IDS)):
            raise ConfigError(f"{name}：shifts_mm.{scope} 里有未知曲线 {unknown}；可用：{list(CURVE_IDS)}")
        for sid, value in per_curve.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} 必须是数字")
            val_f = float(value)
            if not math.isfinite(val_f):
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} 不能是 NaN 或 Inf")
            if abs(val_f) > SHIFT_LIMIT_MM:
                sug = min(max(val_f, -SHIFT_LIMIT_MM), SHIFT_LIMIT_MM)
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} = {val_f} 超出 ±{SHIFT_LIMIT_MM} mm；建议改成 {sug}")
            normalized_shifts[scope][sid] = val_f

    cfg["shifts_mm"] = normalized_shifts
    return cfg


def load_config_ftir(path: Path) -> dict:
    """读 YAML（含 schema 1 迁移与布局校验）→ `prepare_config` 标准化 shifts_mm。"""
    if ARGS.migrate_config:
        legacy = {**SCALARS, "schema_version": (int, 1, 1), "shifts_mm": (dict,),
                  "stack_gap": (float, 0, 80), "stack_gap_annotated": (float, 0, 80),
                  "stack_lift_annotated_mm": (float, -5, 5)}
        cfg = load_config(path, legacy)
        gap, annotated, lift = (cfg.pop(k) for k in
                                ("stack_gap", "stack_gap_annotated", "stack_lift_annotated_mm"))
        cfg.update(schema_version=2, clearance_mm={s: {} for s in SCOPES},
                   group_y_mm={s: 0.0 for s in SCOPES},
                   layout_reference={s: {"gap_data": annotated if s == "annotated" else gap,
                                        "lift_mm": lift if s == "annotated" else 0.0,
                                        "axis_bottom_data": None, "units_per_mm": None} for s in SCOPES})
    else:
        cfg = load_config(path, SCHEMA)
        validate_layout(cfg, scopes=SCOPES, ids=CURVE_IDS[1:], parameter="clearance_mm",
                        reference_fields=("gap_data", "lift_mm", "axis_bottom_data", "units_per_mm"))

    return prepare_config(cfg, label=path.name)


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
            ("legend_font_pt", "图例字号", "pt", SCALARS["legend_font_pt"][1:], "图例框变高，顶部占用增加；谱线不会自动缩小"),
            ("legend_cols", "图例列数", "列", SCALARS["legend_cols"][1:], "列数变多则图例变宽变扁，纵向占用高度减小"),
            ("legend_anchor_x", "图例水平锚点", "比率", SCALARS["legend_anchor_x"][1:], "图例向右靠（1.0最右，太小向左靠会压住y轴标题）"),
        ]),
        ("系列/谱线 (Curves/Series)", [
            ("line_width", "谱线线宽", "pt", SCALARS["line_width"][1:], "所有谱线变粗，仅影响观感不改布局"),
        ]),
        ("标注 (Annotations)", [
            ("label_font_pt", "官能团标签字号", "pt", SCALARS["label_font_pt"][1:], "标签块变大、可能多一层；谱线显示标尺固定，挤不下时报超限"),
            ("curve_gap_mm", "标签布局候选净空", "mm", SCALARS["curve_gap_mm"][1:], "改变归属标签布局候选位置；不自动缩小谱线"),
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

    print("=== 实测毫米距离与整组位置 ===")
    for scope in SCOPES:
        print(f"  clearance_mm.{scope}: {CONFIG['clearance_mm'][scope]} mm（相邻包络净距）")
        print(f"  group_y_mm.{scope}: {CONFIG['group_y_mm'][scope]} mm（整组平移）")
    print("  调大间距只平移上方谱线；空间不足报超限，不缩放。独立 shifts_mm 在其后叠加。")

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


#: 本次构图的配置**工作副本**。legacy 导入 = ftir.yaml；native = build_scene 收到的
#: 候选配置；两者都由 `_apply_config()` **深拷**进来（不是调用方的字典）。
_CFG: dict = {}
#: 本次构图的**派生布局量**：实测冻结视口 + 实测净距，按 scope 分档。与 `_CFG`
#: （用户声明参数）生命周期分开——每次构图开始时清空、只活在这一次构图里、**不回写
#: `_CFG`**。唯一读它的地方是 `--migrate-config`（迁移产出的 YAML 要固化实测视口）。
_DERIVED: dict = {"layout_reference": {}, "clearance_mm": {}}
#: 受保护的科研载荷缓存（load_science 只算一次；warm 布局不再读 CSV）。
_SCIENCE: dict | None = None


def _apply_config(cfg: dict) -> None:
    """把配置里的排版全局量装进模块。

    **这是布局全局量的唯一初始化路径**：legacy 导入与 native
    `build_scene(science, config, scope)` 都只走这里，不存在第二处
    「又把 YAML 读进另一套全局」的分歧约定。

    **装进来的是独立工作副本，不是调用方的字典**：构图过程对配置**只读**，
    同 (science, config, scope) 因此恒等重建，同进程连续构图也不会互相串味。
    """
    global _CFG, LABEL_FS, LEGEND_FS, EDGE_MARGIN_MM, LABEL_GAP_TOP_MM, CURVE_GAP_MM
    global SHIFTS_MM, AXIS_FS, TICK_FS, NOTE_FS, LINE_WIDTH, LEGEND_COLS, LEGEND_ANCHOR_X
    global FTIR_CANVAS
    # 以前这里是 `_CFG = cfg`（直接绑上调用方的字典）。`draw_panel()` 会把实测视口与
    # 实测净距写回 `_CFG`，于是「构图」顺手改掉了调用方的 config，同进程第二次构图
    # 读到的还是上一次写进去的中间结果。深拷一份之后，下面所有全局量都从副本取，
    # 不存在「一半读调用方、一半读副本」。
    _CFG = copy.deepcopy(cfg)
    cfg = _CFG
    # 归属标签与图例的字号是**同一份**：测量（_tier_geometry）与实际落字
    # （draw_bands）分开写死两个数，字号一改就会「量出来三层、画出来两层」。
    LABEL_FS = cfg["label_font_pt"]
    LEGEND_FS = cfg["legend_font_pt"]
    # 贴边框的归属标签（Zn–O 在 400–560，本来就挤在右框上）至少离框这么多；
    # QA 的“贴边”红线是 1.0 mm，取 1.5 留出余量。
    EDGE_MARGIN_MM = cfg["label_edge_margin_mm"]
    # 图例底 → 标签块顶的净空（mm）。标签块本身贴不到图例里，这个值只能小幅调。
    LABEL_GAP_TOP_MM = cfg["label_gap_top_mm"]
    # 标签块底（无标注版：图例底）→ 谱线顶的净空（mm）。**这里就是纵向空间的总闸**：
    # 它每收 1 mm，谱线组就长高 1 mm、整体上移 1 mm。下限 0.5 是因为
    # draw_bands 要求标签必须落在 ymax + 0.5 mm 之上。
    CURVE_GAP_MM = cfg["curve_gap_mm"]
    # 逐曲线显示位移（mm）：`{作用域: {曲线id: 毫米}}`，布局冻结后生效，见 apply_display_shift()
    SHIFTS_MM = cfg["shifts_mm"]
    # 图上每一类**可见文字与线**都要有入口：轴标题 / 刻度数字 / 小注 / 谱线线宽 / 图例列数与水平锚点。
    # 没进 YAML 的两类，理由写在这里，免得下一个人以为是漏了：
    #   * 坐标框与刻度线的线宽 → 由 `figure_style.apply()` 的全局 rcParams 定，
    #     必须与 NMR/XRD 一致，**按图暴露就等于允许三张图长不一样**；
    #   * 图例的**纵向**位置 → 纵向空间是按"图例占顶部 legend_h_mm"算的
    #     （reserved = legend_h + 净空 + 标签块 + 净空）。图例挪到下面，
    #     这套预留就跟实际不符，标签会被放到没有图例的地方。要支持得先改预留模型。
    AXIS_FS = cfg["axis_font_pt"]
    TICK_FS = cfg["tick_font_pt"]
    NOTE_FS = cfg["note_font_pt"]
    LINE_WIDTH = cfg["line_width"]
    LEGEND_COLS = cfg["legend_cols"]
    LEGEND_ANCHOR_X = cfg["legend_anchor_x"]
    FTIR_CANVAS = (cfg["canvas_w_mm"], cfg["canvas_h_mm"])


_apply_config(CONFIG)
# `--strict`：存在**阻断项**时退出码非零，且**不覆盖**已存在的正式输出。
# 默认不加 = 预览模式：照常发布，但把阻断项打在 stdout 上。
STRICT = ARGS.strict
#: 出图先写 STAGING，最后一步才发布到 OUT_DIR。
#: **试算隔离**：`--probe <dir>` 或环境变量 `FIGPACT_PROBE_DIR`（`figpact try` 会设）
#: 一旦生效，OUT_DIR 就是一次性的沙箱，正式输出目录没人碰。
PROBE_DIR = (Path(ARGS.probe).expanduser().resolve() if ARGS.probe
             else fp_publish.probe_dir())
OUT_DIR = PROBE_DIR or ROOT
#: 人工豁免。**阻断项不许记进豁免**——那是"违规却报告成功"。
#: 豁免是人签的字：每条必须带非空 reason，strict 输出会逐条列出理由，
#: 并且**永远不会**在存在阻断项时打印「无阻断项 ✓」。
EXEMPT_PATH = OUT_DIR / "qa_exemptions.json"


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


def compute_offsets(spectra, gap: float) -> list[float]:
    offsets, previous_top = [], 0.0
    for _, y in spectra:
        lower, upper = float(np.nanmin(y)), float(np.nanmax(y))
        offset = max(0.0, previous_top + gap - lower)
        offsets.append(offset)
        previous_top = offset + upper
    return offsets


def load_science() -> dict:
    """受保护的科研载荷：读 CSV → 吸光度转透过率 → 逐谱等高归一化。

    只算一次并缓存：warm 的纯布局试算**不再碰磁盘**。不建 Figure、不输出。
    """
    global _SCIENCE
    if _SCIENCE is None:
        _SCIENCE = {
            "raw": normalize_spectra(absorbance_to_transmittance(load_spectra(processed=False))),
            "processed": normalize_spectra(absorbance_to_transmittance(load_spectra(processed=True))),
        }
    return _SCIENCE


def science_inputs() -> list[str]:
    """本图**实际读取**的科研输入文件（native worker 据此把源文件算进输入 revision）。

    这些是数据源，不是产物：即使扩展名与产物相同，也不该被「.png/.json 一律当输出」
    的规则排除。
    """
    names = [f"{n}.CSV" for n, _, _, _ in SAMPLES] + [f"{n}-处理后.CSV" for n, _, _, _ in SAMPLES]
    return [str(DATA_DIR / name) for name in names]


# ──────────────────────────────────────────────────────────────────────────────
# 绘制
# ──────────────────────────────────────────────────────────────────────────────
def add_legend(fig, ax, scope: str, reg: GidRegistry | None = None):
    """框内右上角；长样品名仅换行，不删文字。"""
    entries = [(sid, label, color) for _, label, color, sid in reversed(SAMPLES)]
    handles = [Line2D([], [], color=color, lw=1.2, solid_capstyle="round", label=label)
               for _, label, color in entries]
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
    for (sid, _, _), t in zip(entries, legend.get_texts()):
        t.set_color(fs.c("TEXT"))
        if reg is not None:
            # 图例里每行样品名也是**可见文字**，给它稳定身份（否则科学指纹只能按位置编号）。
            text_gid = f"{FIGURE_ID}.{scope}.legend.text.{sid}"
            reg.register(t, text_gid, params=["legend_font_pt"])
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
            raise RuntimeError(f"归属标签带超限 {(y_top-y)/units_per_mm:.3f} mm；不会压缩标签层间距")
        label = ax.text(center, y, text, ha="center", va="bottom",
                        fontsize=LABEL_FS, color=fs.c("ANNOT"), zorder=5)
        band_gid = f"{FIGURE_ID}.{scope}.band.{bid}"
        label.set_gid(band_gid)
        if reg is not None:
            reg.register(label, band_gid, params=["label_font_pt", "label_gap_top_mm", "label_edge_margin_mm", "group_y_mm"])
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


def preview_qa(fig, scope):
    if scope.startswith("compare"):
        from types import SimpleNamespace
        ax = fig.axes[0 if scope == "compare_raw" else 1]
        view = SimpleNamespace(axes=[ax], canvas=fig.canvas, dpi=fig.dpi,
                               texts=fig.texts, images=fig.images, bbox=fig.bbox)
        return blocking_problems(view)
    return blocking_problems(fig)

def draw_panel(ax, spectra, *, scope: str, processed: bool, annotate=False, reg: GidRegistry | None = None):
    """画一格。`scope` 是输出版本作用域（见 SCOPES），gid 与显示位移都按它隔离。"""
    if scope not in SCOPES:
        raise ValueError(f"未知作用域 {scope!r}；可用：{list(SCOPES)}")
    reference = _CFG["layout_reference"][scope]
    offsets = compute_offsets(spectra, gap=reference["gap_data"])
    lines: list[tuple] = []
    for (x, y), (_, _, color, sid), offset in zip(spectra, SAMPLES, offsets):
        line, = ax.plot(x, y + offset, color=color, lw=LINE_WIDTH)
        curve_gid = f"{FIGURE_ID}.{scope}.curve.{sid}"
        line.set_gid(curve_gid)
        lines.append((line, sid))
        if reg is not None:
            reg.register(line, curve_gid, params=["line_width", "clearance_mm", "group_y_mm", "shifts_mm"])

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
        raise RuntimeError(f"图例与归属标签超限 {reserved_mm-axes_h_mm:.3f} mm；不会缩放谱线")
    y_span = R / (1.0 - reserved_mm / axes_h_mm)
    ax.set_ylim(y_bottom, y_bottom + y_span)
    if annotate:
        units_per_mm = y_span / axes_h_mm
        top_limit = y_bottom + y_span - (legend_h_mm + LABEL_GAP_TOP_MM) * units_per_mm
        draw_bands(ax, ymax + 0.5 * units_per_mm, top_limit=top_limit, scope=scope, reg=reg)
        lift = reference["lift_mm"] * units_per_mm
        ax.set_ylim(y_bottom - lift, y_bottom + y_span - lift)


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
        # `loc="left"` 的可见文字挂在 `ax._left_title` 上；`ax.title` 是空的中心标题。
        # 注册 `set_title()` 的返回值，才不会出现「gid 绑着一个看不见的空 Text，
        # 真正画出来的那行字却没人认领」。
        title = ax.set_title("Vendor-processed spectra · qualitative reference only",
                             loc="left", fontsize=NOTE_FS, weight="bold", pad=4)
        if reg is not None:
            t_gid = f"{FIGURE_ID}.{scope}.title"
            title.set_gid(t_gid)
            reg.register(title, t_gid, params=["note_font_pt"])
    ax.grid(False)
    # 冻结视口与相邻曲线净距：配置里**声明**的是用户参数，直接用；没声明（`units_per_mm`
    # 为 None）时，本次构图的**实测值**就是这一次的值——它是派生量，进 `_DERIVED`，
    # **不写回 `_CFG`**：写回去等于把这一次的中间结果留给下一次构图（D-5 伪位移的来源），
    # 也等于构图顺手改掉了调用方的配置。
    if reference["units_per_mm"] is None:
        _DERIVED["layout_reference"][scope] = {
            "axis_bottom_data": float(ax.get_ylim()[0]),
            "units_per_mm": float(np.diff(ax.get_ylim())[0] / axes_h_mm)}
        clearance_mm = _DERIVED["clearance_mm"][scope] = {
            sid: measure_relation("vertical_clearance", lines[i-1][0], line)
            for i, (line, sid) in enumerate(lines) if i}
    else:
        clearance_mm = _CFG["clearance_mm"][scope]
        bottom = reference["axis_bottom_data"]
        ax.set_ylim(bottom, bottom + reference["units_per_mm"] * axes_h_mm)
    for i in range(1, len(lines)):
        set_relation_target(kind="vertical_clearance", object_a=lines[i-1][0], object_b=lines[i][0],
                            target_mm=clearance_mm[lines[i][1]],
                            move=[line for line, _ in lines[i:]])
    for line, sid in lines:
        apply_display_shift(line, dy_mm=SHIFTS_MM[scope][sid])
    group = [line for line, _ in lines] + [t for t in ax.texts if ".band." in (t.get_gid() or "")]
    for art in group:
        apply_display_shift(art, dy_mm=_CFG["group_y_mm"][scope])
    relations = getattr(fig, "_figpact_relations", [])
    relations.extend({"scope": scope, "kind": "vertical_clearance", "upper": lines[i][1],
                      "value_mm": measure_relation("vertical_clearance", lines[i-1][0], lines[i][0])}
                     for i in range(1, len(lines)))
    fig._figpact_relations = relations
    spaces = getattr(fig, "_figpact_space", [])
    spaces.extend(dict(scope=scope, **v) for v in remaining_space(fig, group))
    fig._figpact_space = spaces
    return offsets


def add_xlabel(ax, scope: str | None = None, reg: GidRegistry | None = None):
    ax.set_xlabel(r"Wavenumber (cm$^{-1}$)", fontsize=AXIS_FS,
                  weight="bold", labelpad=2)
    if scope is not None and reg is not None:
        lbl = ax.xaxis.label
        gid = f"{FIGURE_ID}.{scope}.xlabel"
        lbl.set_gid(gid)
        reg.register(lbl, gid, params=["axis_font_pt"])


def _panel_gid(scope: str) -> str:
    """panel（Axes）的身份：作用域限定，`panel.0` 这类位置编号在多作用域下会撞名。"""
    return f"{FIGURE_ID}.{scope}.panel"


def _build(science: dict, scope_target: str):
    """按 scope 建图。**legacy 与 native 共用这一份构建路径**（不存在第二套约定）。"""
    # 样式是**这张图**的属性，不是导入的副作用：每次构图都重新套一遍。native runtime
    # 装载脚本时把 rcParams 恢复成导入前的值（`figpact.intents` 的 `rc_context()`），
    # 而模块导入只会 apply 一次——于是同一个进程里的第二次构图会掉回 matplotlib
    # 默认样式（figure.dpi 100、DejaVu 字体、默认线宽），整张图的几何随之改变。
    # D-5 在 FTIR annotated 上报出的「两份字节相同的配置，却有 0.36 mm 位移」就是这个：
    # 判分工具同进程里 baseline 先建（Arial/120 dpi）、candidate 后建（默认样式）。
    fs.apply()
    # 派生量跟着构图走：上一次的实测视口/净距不带进这一次（同进程连续构图的隔离点）。
    _DERIVED["layout_reference"].clear()
    _DERIVED["clearance_mm"].clear()
    reg = GidRegistry()
    raw, proc = science["raw"], science["processed"]

    if scope_target == "main":
        fig, ax = plt.subplots(figsize=fs.canvas_mm(*FTIR_CANVAS))
        fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
        ax.set_gid(_panel_gid("main"))
        draw_panel(ax, raw, scope="main", processed=False, annotate=False, reg=reg)
        add_xlabel(ax, scope="main", reg=reg)
        return fig, reg
    elif scope_target == "annotated":
        fig, ax = plt.subplots(figsize=fs.canvas_mm(*FTIR_CANVAS))
        fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
        ax.set_gid(_panel_gid("annotated"))
        draw_panel(ax, raw, scope="annotated", processed=False, annotate=True, reg=reg)
        add_xlabel(ax, scope="annotated", reg=reg)
        return fig, reg
    elif scope_target.startswith("compare"):
        fig, axes = plt.subplots(2, 1, figsize=fs.canvas("SQ2"), sharex=True,
                                 gridspec_kw={"hspace": 0.20})
        fig.subplots_adjust(left=0.135, right=0.985, top=0.975, bottom=0.075)
        axes[0].set_gid(_panel_gid("compare_raw"))
        axes[1].set_gid(_panel_gid("compare_processed"))
        draw_panel(axes[0], raw, scope="compare_raw", processed=False, annotate=False, reg=reg)
        draw_panel(axes[1], proc, scope="compare_processed", processed=True, annotate=False, reg=reg)
        add_xlabel(axes[1], scope="compare_processed", reg=reg)
        return fig, reg
    else:
        raise ValueError(f"未知 scope_target: {scope_target}")


def build_figure_and_registry(scope_target: str = "annotated"):
    """legacy 入口：用模块基线配置建图（CLI / GUI / 清点继续走这里）。"""
    _apply_config(CONFIG)
    return _build(load_science(), scope_target)


def build_scene(science: dict, config: dict, scope: str):
    """native 入口：候选配置 + 已缓存科研载荷 → (Figure, GidRegistry)。

    候选配置先过 `prepare_config`（与 legacy 同一份标准化：缺 shifts_mm 补 0），
    再由 `_apply_config` 把**副本**装成全部排版全局量（样式也由 `_build` 重新套一遍），
    因此同一 (science, config, scope) 永远得到同一张图；纯布局试算不重读 CSV、不重算谱线。
    **传入的 config 不被修改、也不被记住**：构图对配置只读，实测出来的派生量（冻结视口、
    实测净距）只属于这一次调用。
    """
    _apply_config(prepare_config(config))
    return _build(science, scope)


# ──────────────────────────────────────────────────────────────────────────────
# native 契约：给 agent / runtime 的显式声明（不改 legacy CLI 行为）
# ──────────────────────────────────────────────────────────────────────────────
#: 每个 scope 的产物基名。compare_raw / compare_processed 是**两个独立作用域共享
#: 同一张两格对照图**——作用域是布局/校验的归属范围，不是文件名。
_OUTPUT_BASE = {
    "main": "Fig2_FTIR_transmittance_stacked",
    "annotated": "Fig2_FTIR_transmittance_stacked_annotated",
    "compare_raw": "Fig2_FTIR_transmittance_raw_processed",
    "compare_processed": "Fig2_FTIR_transmittance_raw_processed",
}
_EXPORT_FORMATS = ("png", "pdf", "svg", "tiff")


#: 基线场景缓存：契约里的节点、类型、所属 panel 全部取自**真正建出来的一张图**，
#: 不另抄一份「应该有哪些 gid」的清单——那种清单必然与绘图代码漂移。
_BASELINE_SCENES: dict[str, tuple] = {}


def _baseline_scene(scope: str):
    """该 scope 的基线 (Figure, GidRegistry)，按 scope 缓存、只建一次。"""
    if scope not in _BASELINE_SCENES:
        _apply_config(CONFIG)
        _BASELINE_SCENES[scope] = _build(load_science(), scope)
    return _BASELINE_SCENES[scope]


def _science_policy(gid: str) -> str:
    """FTIR 没有纯布局图元：谱线、归属文字、轴文字、图例全部参与科学指纹。

    `layout_contract` 与 `science_manifest` 共用这一个判据，避免两处各写一套。
    """
    return "LOCKED_SCIENCE"


def _panel_id(ax, index: int) -> str:
    """panel 身份：builder 设的 Axes gid；没有时才退回引擎的位置编号约定。"""
    return ax.get_gid() or f"panel.{index}"


def _scene_roles(fig, reg) -> tuple[dict[str, list[str]], dict[int, str]]:
    """按语义角色分组注册图元，并给出「图元 → 所属 panel」的映射。

    角色与归属都按 **artist 身份**判定，不靠切 gid 字符串：轴标题/轴标签的
    `.axes` 是 None、`loc="left"` 的标题挂在 `_left_title` 上，按 `.axes` 猜会猜错。
    """
    roles = {"lines": [], "legends": [], "legend_texts": [], "axis_texts": [], "titles": [],
             "band_labels": []}
    owner: dict[int, str] = {}
    role: dict[int, str] = {}
    for i, ax in enumerate(fig.axes):
        pid = _panel_id(ax, i)
        for txt, name in ((ax.xaxis.label, "axis_texts"), (ax.yaxis.label, "axis_texts"),
                          (ax.title, "titles"), (ax._left_title, "titles"),
                          (ax._right_title, "titles")):
            if txt is None:
                continue
            owner[id(txt)] = pid
            role[id(txt)] = name
        legend = ax.get_legend()
        if legend is not None:
            owner[id(legend)] = pid
            for txt in legend.get_texts():
                owner[id(txt)] = pid
                role[id(txt)] = "legend_texts"
    for gid, art in reg.all().items():
        kind = type(art).__name__
        if kind == "Line2D":
            roles["lines"].append(gid)
        elif kind == "Legend":
            roles["legends"].append(gid)
        elif kind == "Text":
            roles[role.get(id(art), "band_labels")].append(gid)
    return roles, owner


def _decl_param(scope, key, path, unit, mutability, objects, *, operation=None, axis=None,
                bounds=None, expected=None) -> dict:
    """契约参数记录。`bounds` = (min, max)，取自 SCALARS / 关系上限，不另抄一份数字。"""
    rec = {"key": key, "path": list(path), "unit": unit, "mutability": mutability,
           "scopes": [scope], "objects": list(objects), "scale": 1.0}
    if operation is not None:
        rec["operation"] = operation
    if axis is not None:
        rec["axis"] = axis
    if bounds is not None:
        rec["min"], rec["max"] = bounds
    if expected is not None:
        rec["expected"] = expected
    return rec


def _editable(params: list, scope, key, path, unit, objects, **kw) -> None:
    """只登记**在该 scope 真的有受影响图元**的可编辑参数；否则不声明（= 不支持）。"""
    if objects:
        params.append(_decl_param(scope, key, path, unit, "EDITABLE", objects, **kw))


def _panel_map(fig, reg, owner: dict[int, str]) -> dict[str, str]:
    """`{gid: panel_id}`：轴标签/图例/标题走 owner 规则，其余按 artist 的 Axes 归属。"""
    result = {}
    for gid, art in reg.all().items():
        if id(art) in owner:
            result[gid] = owner[id(art)]
        else:
            ax = getattr(art, "axes", None)
            result[gid] = _panel_id(ax, fig.axes.index(ax)) if ax in fig.axes else "figure"
    return result


def _panel_scopes(scope: str, panel_of: dict[str, str]) -> dict[str, str]:
    """`{panel_id: 该 panel 所属作用域}`：从配置里逐作用域的曲线 gid 反查，不切 gid 字符串。"""
    registered = _baseline_scene(scope)[1].all()
    result: dict[str, str] = {}
    for s in SCOPES:
        for sid in CONFIG["shifts_mm"][s]:
            gid = f"{FIGURE_ID}.{s}.curve.{sid}"
            if gid in registered:
                result.setdefault(panel_of[gid], s)
    return result


def layout_contract(scope: str) -> dict:
    """该 scope 的显式布局契约：精确 YAML 路径、语义节点/分组、受影响集合、产物名。

    节点 / 类型 / 所属 panel 取自基线场景（`_baseline_scene`）；全局样式参数声明为
    **该 scene 内全部实际受影响的节点**，逐作用域参数只声明本作用域 panel 的节点——
    对照版两格同图，但改 `compare_raw` 的路径不会动 `compare_processed`。
    """
    if scope not in SCOPES:
        raise ValueError(f"未知作用域 {scope!r}；可用：{list(SCOPES)}")
    fig, reg = _baseline_scene(scope)
    registered = reg.all()
    gids = sorted(registered)
    roles, owner = _scene_roles(fig, reg)
    panel_of = _panel_map(fig, reg, owner)
    # 本作用域的曲线 id 取自**配置**（load_config 已归一化成 {scope: {sid: 0.0}}），
    # 再按注册表过滤——不猜字符串，也不会声明不存在的 gid。
    curve_ids = list(CONFIG["shifts_mm"][scope])
    own = [(sid, f"{FIGURE_ID}.{scope}.curve.{sid}") for sid in curve_ids
           if f"{FIGURE_ID}.{scope}.curve.{sid}" in registered]
    own_panel = panel_of.get(own[0][1]) if own else _panel_gid(scope)
    own_bands = sorted(g for g in roles["band_labels"] if panel_of[g] == own_panel)

    params: list[dict] = []
    for key in ("canvas_w_mm", "canvas_h_mm"):
        _editable(params, scope, key, [key], "mm", gids, operation="resize",
                  bounds=SCALARS[key][1:], expected={"kind": "resize", "objects": gids})
    legend_objects = roles["legends"] + roles["legend_texts"]
    for key, unit in (("legend_font_pt", "pt"), ("legend_cols", "col"),
                      ("legend_anchor_x", "ratio")):
        _editable(params, scope, key, [key], unit, legend_objects, operation="rebuild",
                  bounds=SCALARS[key][1:], expected={"kind": "style", "objects": legend_objects})
    for key in ("axis_font_pt", "line_width", "label_font_pt", "note_font_pt"):
        objects = {"axis_font_pt": roles["axis_texts"], "line_width": roles["lines"],
                   "label_font_pt": roles["band_labels"],
                   "note_font_pt": roles["titles"]}[key]
        _editable(params, scope, key, [key], "pt", objects, operation="rebuild",
                  bounds=SCALARS[key][1:], expected={"kind": "style", "objects": objects})
    for key in ("label_edge_margin_mm", "label_gap_top_mm", "curve_gap_mm"):
        _editable(params, scope, key, [key], "mm", roles["band_labels"], operation="rebuild",
                  bounds=SCALARS[key][1:],
                  expected={"kind": "style", "objects": roles["band_labels"]})
    # 逐作用域的毫米操作：路径精确到曲线 id，受影响集合是**实际会动的那些曲线**。
    relations: list[dict] = []
    for i in range(1, len(own)):
        sid = own[i][0]
        moved = [gid for _, gid in own[i:]]
        _editable(params, scope, f"clearance_mm.{scope}.{sid}", ["clearance_mm", scope, sid],
                  "mm", moved, operation="translate", axis="y", bounds=(0.0, 100.0),
                  expected={"kind": "translate", "objects": moved, "axis": "y",
                            "preserve": [f"{scope}.clearance.{own[k][0]}" for k in range(1, i)]})
        relations.append({
            "id": f"{scope}.clearance.{sid}",
            "kind": "gap",
            "objects": [own[i - 1][1], own[i][1]],
            "axis": "y",
            "method": "envelope_edge",
            "controlled_by": [["clearance_mm", scope, sid]],
            "move": moved,
        })
    group_objects = [gid for _, gid in own] + own_bands
    _editable(params, scope, f"group_y_mm.{scope}", ["group_y_mm", scope], "mm",
              group_objects, operation="translate", axis="y", bounds=(-100.0, 100.0),
              expected={"kind": "translate", "objects": group_objects, "axis": "y",
                        "preserve": [r["id"] for r in relations]})
    for sid, gid in own:
        _editable(params, scope, f"shifts_mm.{scope}.{sid}", ["shifts_mm", scope, sid], "mm",
                  [gid], operation="translate", axis="y",
                  bounds=(-SHIFT_LIMIT_MM, SHIFT_LIMIT_MM),
                  expected={"kind": "translate", "objects": [gid], "axis": "y"})
    # 只读重建字段：声明出来是为了它们**不被当成可编辑**（缺声明 = UNCLASSIFIED 失败关闭）。
    params.append(_decl_param(scope, "schema_version", ["schema_version"], "int", "FIXED_STYLE", []))
    params.append(_decl_param(scope, f"layout_reference.{scope}", ["layout_reference", scope],
                              "record", "DERIVED", []))

    editable = {gid for p in params if p["mutability"] == "EDITABLE" for gid in p["objects"]}
    nodes = {gid: {"type": type(registered[gid]).__name__, "parent": panel_of[gid],
                   "editable": gid in editable, "science_policy": _science_policy(gid)}
             for gid in gids}
    panel_scope = _panel_scopes(scope, panel_of)
    root = f"{FIGURE_ID}.{scope}"
    groups = [{"id": root, "parent": None, "members": gids}]
    for pid in sorted(set(panel_of.values())):
        groups.append({"id": pid, "parent": root,
                       "members": sorted(g for g in gids if panel_of[g] == pid)})
    for pid, ps in sorted(panel_scope.items()):
        groups.append({"id": f"{FIGURE_ID}.{ps}.group.curves", "parent": pid,
                       "members": [f"{FIGURE_ID}.{ps}.curve.{sid}" for sid in CONFIG["shifts_mm"][ps]
                                   if f"{FIGURE_ID}.{ps}.curve.{sid}" in registered]})
    for pid in sorted({panel_of[g] for g in roles["band_labels"]}):
        groups.append({"id": f"{FIGURE_ID}.{panel_scope.get(pid, pid)}.group.bands",
                       "parent": pid,
                       "members": sorted(g for g in roles["band_labels"] if panel_of[g] == pid)})
    return {"parameters": params, "nodes": nodes, "groups": groups, "relations": relations,
            "outputs": [f"{_OUTPUT_BASE[scope]}.{ext}" for ext in _EXPORT_FORMATS]}


def science_manifest(science: dict) -> dict:
    """JSONable 的科研来源 / 处理 / 受保护锚点声明（native runtime 与 capture_science 用）。

    `nodes` 只列**点名豁免**的装饰几何，且必须写 `type: "guide"`：引擎对原始 Line2D 的
    x/y 一律保护，科研谱线、图像像素、集合段**永远**不能靠 `LAYOUT` 豁免。
    FTIR 这张图没有任何引导线/基线这类装饰线（谱线、归属文字、轴文字、图例全部参与
    科学指纹），所以这里是空表；未列出的 gid 默认 LOCKED_SCIENCE，与 `_science_policy` 一致。
    """
    troughs = {}
    for (_, _, _, sid), (x, y) in zip(SAMPLES, science["raw"]):
        troughs[sid] = {"deepest_trough_cm1": float(x[int(np.argmin(y))]),
                        "display_scale": {"baseline": 100.0, "trough_depth": 55.0}}
    # 定性 y 轴的**冻结视口**：原点与「数据单位/mm」都来自只读的 layout_reference，
    # 因此画布变高只加余量、不改信号物理标尺。x 窗口不在其中（它锁死在 4000→400 cm⁻¹）。
    viewports = {}
    for s in SCOPES:
        fig_s, reg_s = _baseline_scene(s)
        _roles_s, owner_s = _scene_roles(fig_s, reg_s)
        for panel_id, panel_scope in _panel_scopes(s, _panel_map(fig_s, reg_s, owner_s)).items():
            ref = CONFIG["layout_reference"][panel_scope]
            viewports[panel_id] = {"axis": "y", "origin": ref["axis_bottom_data"],
                                   "units_per_mm": ref["units_per_mm"]}
    return {
        "nodes": {},
        "layout_viewports": viewports,
        "science": {
            "figure_id": FIGURE_ID,
            "source": {
                "instrument_output": "absorbance CSV",
                "files": [f"{n}.CSV" for n, _, _, _ in SAMPLES],
                "processed_files": [f"{n}-处理后.CSV" for n, _, _, _ in SAMPLES],
                "wavenumber_window_cm1": [400, 4000],
            },
            "processing": ["T(%) = 100 × 10^(−A)",
                           "per-spectrum equal-depth normalization: baseline 100, trough 100−55"],
            "scale_bars": [],
            "protected": {
                "display_window_cm1": [4000, 400],
                "assignment_windows_cm1": [[lo, hi, text] for lo, hi, text, _ in BANDS],
                "troughs": troughs,
            },
        },
    }


def _adopt_measured_layout(config: dict) -> None:
    """把本次构图的**实测**视口与实测净距固化进配置（`--migrate-config` 专用）。

    构图本身不再写配置：派生量先落在 `_DERIVED`，由这里显式取走。迁移要用「构图顺手
    改全局」那种隐式副作用——那正是 D-5 的根因，不能留。一次构图可能同时测出两个
    scope（对照图的上下两格），所以这里按 `_DERIVED` 里实际有的记录逐条固化。
    """
    for scope, reference in _DERIVED["layout_reference"].items():
        config["layout_reference"][scope].update(reference)
    for scope, clearance in _DERIVED["clearance_mm"].items():
        config["clearance_mm"][scope] = dict(clearance)


def make_figure():
    if ARGS.migrate_config:
        for scope in ("main", "annotated", "compare_raw"):
            fig, _ = build_figure_and_registry(scope)
            plt.close(fig)
            _adopt_measured_layout(CONFIG)
        validate_layout(CONFIG, scopes=SCOPES, ids=CURVE_IDS[1:], parameter="clearance_mm",
                        reference_fields=("gap_data", "lift_mm", "axis_bottom_data", "units_per_mm"))
        output = Path(ARGS.migrate_config).resolve()
        if output == CONFIG_PATH.resolve():
            raise ValueError("迁移输出必须是新文件")
        output.write_text(yaml.safe_dump(CONFIG, allow_unicode=True, sort_keys=False), encoding="utf8")
        print(f"已迁移到 {output}；正式图未改动")
        return
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

    STAGING = Path(tempfile.mkdtemp(prefix="ftir-stage-"))
    active = {s: {k: v for k, v in per.items() if v}
              for s, per in SHIFTS_MM.items() if any(per.values())}
    print(f"[配置] {CONFIG_PATH.name}: 画布 {FTIR_CANVAS[0]}×{FTIR_CANVAS[1]} mm · "
          f"标签 {LABEL_FS} pt · 图例 {LEGEND_FS} pt · 间距见 clearance_mm"
          + (f" · 位移 {active}" if active else ""))
    blockers: list[str] = []

    # ① 主图（干净版）
    fig, _reg = build_figure_and_registry("main")
    fs.export(fig, STAGING / "Fig2_FTIR_transmittance_stacked")
    fs.qa_report(fig, "FTIR 主图")
    report_shift_bounds(fig, "FTIR 主图")
    blockers += blocking_problems(fig)
    plt.close(fig)

    # ② 归属标注版
    fig, _reg = build_figure_and_registry("annotated")
    fs.export(fig, STAGING / "Fig2_FTIR_transmittance_stacked_annotated")
    fs.qa_report(fig, "FTIR 归属标注版")
    report_shift_bounds(fig, "FTIR 归属标注版")
    blockers += blocking_problems(fig)
    plt.close(fig)

    # ③ 原始 / 供应商处理 对照版：SQ2（上下两格，SI 用）
    fig, _reg = build_figure_and_registry("compare_raw")
    fs.export(fig, STAGING / "Fig2_FTIR_transmittance_raw_processed")
    fs.qa_report(fig, "FTIR 原始/处理对照")
    report_shift_bounds(fig, "FTIR 原始/处理对照")
    blockers += blocking_problems(fig)
    plt.close(fig)

    exemptions_mgr = fp_publish.Exemptions(EXEMPT_PATH)
    if ARGS.exempt_current:
        exemptions_mgr.write(blockers, ARGS.reason)
        print(f"[豁免] 写入 {len(blockers)} 条 → {EXEMPT_PATH.name}；理由：{ARGS.reason.strip()}")

    # 豁免键 = 规则 + 作用域 + 对象 id（结构化诊断 key）：豁免一个峰不会连带豁免别的峰。
    exempt_dict = exemptions_mgr.load()
    exempted = [(b, exempt_dict[qa.diagnostic_key_of(b)]) for b in blockers if qa.diagnostic_key_of(b) in exempt_dict]
    new_blockers = [b for b in blockers if qa.diagnostic_key_of(b) not in exempt_dict]
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
    written = fp_publish.publish(STAGING, OUT_DIR)
    shutil.rmtree(STAGING, ignore_errors=True)
    where = f"试算沙箱 {OUT_DIR}" if PROBE_DIR else f"正式输出 {OUT_DIR}"
    print(f"已写出 {len(written)} 个文件到{where}")


if __name__ == "__main__":
    make_figure()
