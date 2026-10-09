#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
堆叠 1H NMR 图（顶级学术期刊投稿终极定稿版 - 严密定标 + 动态峰位读数 + 鲁棒归一化）

方法学与数据真实性规范（完全符合同行评议与审稿标准）：
1. 窄窗口化学位移定标 (Strict Narrow-Window Chemical Shift Referencing)：
   - CDCl3 样品严格以残余 CHCl3 尖峰定标于 δ 7.26 ppm (窄窗口 7.28±0.03 ppm 及 7.19±0.03 ppm，杜绝误抓 7.40 ppm 附近的芳香峰)
   - DMSO-d6 样品以残余溶剂峰定标于 δ 2.50 ppm (窗口 2.50±0.03 ppm)
   - D2O 样品以 HOD 残余水峰定标于 δ 4.79 ppm (窗口 4.70±0.05 ppm)
   - 每次运行终端完整输出各样品的“观测溶剂峰 -> 标准参考值 -> 平移校正量”，确保数据可追溯与人工核对。
2. 动态读取真实峰位 (Dynamic Peak-PPM Formatting)：
   - 标注中的 ppm 数字不再手工硬编码，而是由算法在校准后的真实谱线中找到数学极大值后动态生成 `({exact_ppm:.2f})`，确保引线所指与文字显示的化学位移 100% 数据一致。
3. 鲁棒强度归一化 (Robust Solute Peak Scaling)：
   - 排除溶剂峰后，按非溶剂区真实溶质特征峰归一化到 22 a.u.，溶剂峰截顶并保留 // 标示，层间留出 12 a.u. 绝对安全净空。
4. 纵坐标规范更名：
   - 纵轴标题采用学术规范的 'Normalized Intensity (a.u.)'。
"""

import argparse
import json
import math
import re
import pathlib
import shutil
import sys
import tempfile

import nmrglue as ng
import numpy as np
import yaml
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.transforms import ScaledTranslation

# Windows 上 stdout 不是真控制台时会退回 GBK/cp1252，而 QA 行里有 ✗ / «»：
# 一句 print 就是 UnicodeEncodeError 打死进程，退出码同样是 1，看起来像"拒绝了这张图"。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent.parent))
import figure_style as fs
from figpact import load_config as fp_load_config, apply_display_shift as fp_apply_display_shift, GidRegistry, qa as fp_qa, publish as fp_publish, inventory as fp_inventory
from figpact.config import ConfigError

DATA_ROOT = ROOT / "核磁原始数据"

#: 对象身份前缀。**不是配置项**：gid 是外部引用认的名字。
FIGURE_ID = "fig2_nmr"
#: 本脚本只出一张图（SI 的单谱在 NMR_generate_all.py 里），所以只有一个作用域。
#: 作用域仍在 gid 里留位，是为了跟 FTIR 同一套命名——将来这张图拆成多个输出版本时
#: 不用改名（改名 = 所有外部引用一起失效）。
SCOPE = "main"
SCOPES = (SCOPE,)


def _gid_tag(ppm: float) -> str:
    """3.91 → `3p91`：gid 的最后一段不能带点，否则按点切分的读取方会切错。"""
    return f"{ppm:.2f}".replace(".", "p")

fs.apply()
DPI = 600

# 样品配置：(相对路径, 递进标签, 曲线颜色, 溶剂类型, 标准参考ppm, 搜索初始ppm, 搜索窗口宽ppm, 稳定id)
# 颜色全部取自统一色表（DESIGN.md §3.2）：3 个前体用暖色递进，终产物用材料主色
SAMPLES_CONFIG = [
    ("2/1", "Van-CHO\n(2)",     fs.c("CPD2_VANCHO"), "CDCl3",   7.26, 7.28, 0.03, "vancho"),   # 底层
    ("3/2", "Van-OH\n(3)",      fs.c("CPD3_VANOH"),  "CDCl3",   7.26, 7.19, 0.03, "vanoh"),    # 第二层
    ("4/1", "Van-NH$_2$\n(4)",  fs.c("CPD4_VANNH2"), "DMSO-d6", 2.50, 2.50, 0.03, "vannh2"),   # 第三层
    ("5/1", "HAMA\n(target)",   fs.c("MOD_HA"),      "D2O",     4.79, 4.70, 0.05, "hama"),     # 顶层：接枝产物
]
SAMPLE_IDS = tuple(sid for *_, sid in SAMPLES_CONFIG)

# 谱图显示窗（ppm）。**不进 YAML**：这是"这张图回答什么问题"的一部分，
# 不是排版——改窗宽会藏掉峰。与 FTIR 的 xlim(4000→400) 同一性质。
PPM_LEFT = 10.5
PPM_RIGHT = 0.0
# 归一化标尺：**科学量**，不是排版。它同时决定"溶质最高峰多高"和溶剂峰截顶阈值，
# 所以留在这里、不进 YAML——让 Agent 能调它，就等于让 Agent 能改数据的相对幅度。
PEAK_MAX_NORM = 22


# ──────────────────────────────────────────────────────────────────────────────
# 配置：排版参数唯一入口（与 09 FTIR 同一套约定）
# ──────────────────────────────────────────────────────────────────────────────
FONT_RANGE = (3.0, 12.0)
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 20.0, 200.0),
    "canvas_h_mm": (float, 20.0, 200.0),
    "layer_gap": (float, 0.0, 200.0),
    "top_headroom": (float, 0.0, 400.0),
    "label_lift": (float, 0.0, 60.0),
    "line_width": (float, 0.2, 3.0),
    "peak_font_pt": (float, *FONT_RANGE),
    "legend_font_pt": (float, *FONT_RANGE),
    "note_font_pt": (float, *FONT_RANGE),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "legend_cols": (int, 1, 3),
    "legend_anchor_x": (float, 0.0, 1.0),
    "label_min_gap_mm": (float, 0.0, 15.0),
    "label_max_dx_mm": (float, 0.0, 25.0),
    "label_lanes": (int, 1, 5),
}
SHIFT_LIMIT_MM = 10.0
#: 布尔参数单独一组：`_number` 明确拒 bool（True 会被当 1 吃下去），所以不能混在 SCALARS 里
BOOL_KEYS = ("show_ppm",)


def _cli(argv: list[str]) -> argparse.Namespace:
    """严格解析：拼错的 flag 当场报错，不被静默忽略。"""
    ap = argparse.ArgumentParser(
        prog=pathlib.Path(__file__).name, add_help=True, allow_abbrev=False,
        description="Fig.2 NMR 叠谱；排版参数在 nmr.yaml，命令行只选配置与模式")
    ap.add_argument("--config", default=None, help="配置文件路径（默认：脚本旁边的 nmr.yaml）")
    ap.add_argument("--list-params", action="store_true",
                    help="打印全部参数（当前值 / 允许范围）与所有可位移 gid，然后退出")
    ap.add_argument("--strict", action="store_true",
                    help="有**新增**阻断项时退出码非零，且不覆盖已存在的正式输出")
    ap.add_argument("--exempt-current", action="store_true",
                    help="把当前全部阻断项写成人工豁免（必须同时给 --reason）")
    ap.add_argument("--reason", default="", help="人工豁免的理由（写进 qa_exemptions.json）")
    ap.add_argument("--inventory", action="store_true",
                    help="打印当前图表可见图元清单 (JSON 格式)，供 figpact inventory 消费")
    ap.add_argument("--inspect", default=None,
                    help="检查指定 gid 的图元信息")
    return ap.parse_args(argv)


ARGS = _cli(sys.argv[1:])
CONFIG_PATH = pathlib.Path(ARGS.config).expanduser() if ARGS.config else ROOT / "nmr.yaml"


SCHEMA = {
    "schema_version": (int, 1, 1),
    "show_ppm": (bool,),
    "canvas_w_mm": (float, 20.0, 200.0),
    "canvas_h_mm": (float, 20.0, 200.0),
    "layer_gap": (float, 0.0, 200.0),
    "top_headroom": (float, 0.0, 400.0),
    "label_lift": (float, 0.0, 60.0),
    "line_width": (float, 0.2, 3.0),
    "peak_font_pt": (float, *FONT_RANGE),
    "legend_font_pt": (float, *FONT_RANGE),
    "note_font_pt": (float, *FONT_RANGE),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "legend_cols": (int, 1, 3),
    "legend_anchor_x": (float, 0.0, 1.0),
    "label_min_gap_mm": (float, 0.0, 15.0),
    "label_max_dx_mm": (float, 0.0, 25.0),
    "label_lanes": (int, 1, 5),
    "shifts_mm": (dict,),
    "peak_label_shifts_mm": (dict,),
}


def _load_label_shifts(path, raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}：peak_label_shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw) - set(SCOPES)):
        raise ConfigError(f"{path.name}：peak_label_shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")
    out: dict = {}
    for scope, per_label in raw.items():
        if per_label is None:
            continue
        if not isinstance(per_label, dict):
            raise ConfigError(f"{path.name}：peak_label_shifts_mm.{scope} 必须是 `标注gid: [dx, dy]` 映射")
        for gid, pair in per_label.items():
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                raise ConfigError(f"{path.name}：peak_label_shifts_mm.{scope}.{gid} 必须是 [dx, dy] 两个数字")
            dx, dy = pair[0], pair[1]
            if isinstance(dx, bool) or not isinstance(dx, (int, float)) or not math.isfinite(dx):
                raise ConfigError(f"{path.name}：peak_label_shifts_mm.{scope}.{gid}[0] 必须是有效数字")
            if isinstance(dy, bool) or not isinstance(dy, (int, float)) or not math.isfinite(dy):
                raise ConfigError(f"{path.name}：peak_label_shifts_mm.{scope}.{gid}[1] 必须是有效数字")
            dx_f, dy_f = float(dx), float(dy)
            if abs(dx_f) > SHIFT_LIMIT_MM or abs(dy_f) > SHIFT_LIMIT_MM:
                raise ConfigError(f"{path.name}：peak_label_shifts_mm.{scope}.{gid} 超出 ±{SHIFT_LIMIT_MM} mm")
            out[f"{FIGURE_ID}.{scope}.{gid}"] = (dx_f, dy_f)
    return out


def load_config_nmr(path: pathlib.Path) -> dict:
    cfg = fp_load_config(path, SCHEMA)
    raw_shifts = cfg.get("shifts_mm") or {}
    if not isinstance(raw_shifts, dict):
        raise ConfigError(f"{path.name}：shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw_shifts) - set(SCOPES)):
        raise ConfigError(f"{path.name}：shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")

    cfg["peak_label_shifts_mm"] = _load_label_shifts(path, cfg.get("peak_label_shifts_mm"))
    cfg["shifts_mm"] = {scope: {sid: 0.0 for sid in SAMPLE_IDS} for scope in SCOPES}
    for scope, per_sample in raw_shifts.items():
        if per_sample is None:
            continue
        if not isinstance(per_sample, dict):
            raise ConfigError(f"{path.name}：shifts_mm.{scope} 必须是 `样品id: 毫米` 映射")
        if unknown := sorted(set(per_sample) - set(SAMPLE_IDS)):
            raise ConfigError(f"{path.name}：shifts_mm.{scope} 里有未知样品 {unknown}；可用：{list(SAMPLE_IDS)}")
        for sid, value in per_sample.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ConfigError(f"{path.name}：shifts_mm.{scope}.{sid} 必须是有效数字")
            mm = float(value)
            if abs(mm) > SHIFT_LIMIT_MM:
                sug = min(max(mm, -SHIFT_LIMIT_MM), SHIFT_LIMIT_MM)
                raise ConfigError(f"{path.name}：shifts_mm.{scope}.{sid} = {mm} 超出 ±{SHIFT_LIMIT_MM} mm；建议改成 {sug}")
            cfg["shifts_mm"][scope][sid] = mm
    return cfg


CONFIG = load_config_nmr(CONFIG_PATH)

def list_params() -> None:
    """人类手调用的清单：每个参数当前值 + 允许范围，以及所有可位移 gid。"""
    print(f"配置文件：{CONFIG_PATH}")
    print(f"{'参数':<26}{'当前值':>10}   允许范围")
    for key, (typ, lo, hi) in SCALARS.items():
        print(f"  {key:<24}{CONFIG[key]!s:>10}   [{lo}, {hi}]")
    for key in BOOL_KEYS:
        print(f"  {key:<24}{str(CONFIG[key]):>10}   true / false")
    print("\n可位移 gid —— shifts_mm（整层：谱线+基线+//+该层标注+引线）")
    for sid in SAMPLE_IDS:
        print(f"  {sid:<12} 例：shifts_mm: {{main: {{{sid}: 0.0}}}}")
    print("\n可位移 gid —— peak_label_shifts_mm（单个标注，[dx 向右, dy 向上] mm）")
    for _ppm, _idx, _grp, *_ in PEAK_LABELS_TEMPLATE:
        _sid = SAMPLES_CONFIG[_idx][7]
        print(f"  peak.{_sid}.{_gid_tag(_ppm):<12} {_grp}")
    print("\n把上面任一行取消注释填进 yaml 即可；位移后的位置照样过碰撞检查。")



CANVAS = (CONFIG["canvas_w_mm"], CONFIG["canvas_h_mm"])
Y_OFFSET_STEP = CONFIG["layer_gap"]
Y_MAX_EXPAND = CONFIG["top_headroom"]
LABEL_LIFT = CONFIG["label_lift"]
LINEWIDTH = CONFIG["line_width"]
FONTSIZE_PEAK = CONFIG["peak_font_pt"]
FONTSIZE_LEGEND = CONFIG["legend_font_pt"]
FONTSIZE_NOTE = CONFIG["note_font_pt"]
FONTSIZE_AXIS = CONFIG["axis_font_pt"]
FONTSIZE_TICK = CONFIG["tick_font_pt"]
LEGEND_COLS = CONFIG["legend_cols"]
LEGEND_ANCHOR_X = CONFIG["legend_anchor_x"]
LABEL_MIN_GAP_MM = CONFIG["label_min_gap_mm"]
LABEL_MAX_DX_MM = CONFIG["label_max_dx_mm"]
LABEL_LANES = CONFIG["label_lanes"]
PEAK_LABEL_SHIFTS = CONFIG["peak_label_shifts_mm"]
#: 标注里要不要带 ppm 后缀。**只改显示格式，不改归属文字**——
#: 归属始终是模板里的 `group_name`（Ar–OCH₃ 等），ppm 是算法检测出来的补充信息。
SHOW_PPM = CONFIG["show_ppm"]
SHIFTS_MM = CONFIG["shifts_mm"]
STRICT = ARGS.strict
STAGING = pathlib.Path(tempfile.mkdtemp(prefix="nmr-stage-"))
#: 存量缺陷基线。**这是 NMR 逼出来的规范补充**：
#: FTIR 的存量问题（字形下限、贴边）本来就在非阻断集合里，所以不需要基线；
#: NMR 的存量问题恰好落在阻断集合里（标签重叠、文字压线），没有基线的话
#: `--strict` 永远是红的，门就废了。基线让门只对**回归**报警，不对旧账报警。
EXEMPT_PATH = ROOT / "qa_exemptions.json"


def _signature(problem: str) -> str:
    """把 QA 文本压成稳定签名：面积/点数/毫米都随 dpi 变，一律抹成 #。"""
    return re.sub(r"[-\d.]+", "#", problem).strip()


#: **阻断类**的关键词：这三类（重叠 / 压线 / 出框）+ 谱层糊在一起，一律不准进基线。
#: 基线只用来接住"警告类"（字形下限、贴边）——那些是出版取舍；
#: 把重叠/压线记进基线等于"违规却报告成功"，验收不允许。
BLOCKING_KINDS = ("重叠", "压线", "超出坐标框", "最近处", "引线", "未知标注", "NO_FEASIBLE_SLOT")


def load_exemptions() -> dict:
    """读**人工豁免**：`{签名: 理由}`。每条必须带非空 reason——豁免是人签的字，
    不是"把它藏起来"。没有 reason 的条目直接不认（并说明原因）。"""
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


# ──────────────────────────────────────────────────────────────────────────────
# 验收工具（与 09 FTIR 同一套约定：阻断项只覆盖排版几何）
# ──────────────────────────────────────────────────────────────────────────────
def apply_display_shift(artist, dy_mm: float) -> None:
    """把 artist 的显示位置按毫米平移，使用 figpact.apply_display_shift。"""
    fp_apply_display_shift(artist, dy_mm=dy_mm)
def check_shift_clipping(fig) -> list[str]:
    """谱线与图例有没有被坐标框裁掉——显示坐标实测，不做数据换算。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = 25.4 / fig.dpi
    out: list[str] = []
    for ax in fig.axes:
        axbb = ax.get_window_extent()
        watched = [(a.get_gid(), a) for a in ax.lines if ".curve." in (a.get_gid() or "")]
        legend = ax.get_legend()
        if legend is not None:
            watched.append((legend.get_gid() or "legend", legend))
        for gid, artist in watched:
            bb = artist.get_window_extent(renderer)
            over = max(bb.y1 - axbb.y1, axbb.y0 - bb.y0)
            if over > 0:
                out.append(f"「{gid.rsplit('.', 1)[-1]}」超出坐标框 "
                           f"{over * mm_per_px:.2f} mm（已被裁切）")
    return out


#: 相邻谱层的最小净空（mm）。低于这个值两层在视觉上糊在一起。
MIN_LAYER_GAP_MM = 0.5


def check_curve_separation(fig, min_mm: float = MIN_LAYER_GAP_MM) -> list[str]:
    """位移之后，相邻谱层是否还保持上下顺序与最小净空。

    逐点比较（四层共用同一套 ppm 网格），取每条线**自己的** transform，
    所以位移后的几何才算数。
    """
    fig.canvas.draw()
    mm_per_px = 25.4 / fig.dpi
    out: list[str] = []
    for ax in fig.axes:
        ys: dict[str, np.ndarray] = {}
        for line in ax.lines:
            gid = line.get_gid() or ""
            if ".curve." not in gid:
                continue
            ys[gid.rsplit(".", 1)[-1]] = line.get_transform().transform(
                line.get_xydata())[:, 1]
        order = [sid for sid in SAMPLE_IDS if sid in ys]
        for lower, upper in zip(order, order[1:]):
            if ys[lower].shape != ys[upper].shape:
                continue
            gap_mm = float((ys[upper] - ys[lower]).min()) * mm_per_px
            if gap_mm < min_mm:
                out.append(f"「{lower}」与「{upper}」最近处 {gap_mm:.2f} mm"
                           f"（要求 ≥ {min_mm} mm）")
    return out


UNPLACED_GIDS: list[str] = []


def check_label_geometry(fig) -> list[str]:
    """峰标注出框 / 引线穿图例 / 微调 gid 未命中——三类都是阻断项。

    显示坐标实测：出框判据用渲染后的文字框与坐标框相减；引线用它的**自己的**
    transform 取点（引线是数据坐标，位移后位置才算数）。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = 25.4 / fig.dpi
    out: list[str] = []
    seen: set = set()
    for ax in fig.axes:
        axbb = ax.get_window_extent()
        leg = ax.get_legend()
        legbb = leg.get_window_extent(renderer) if leg is not None else None
        for t in ax.texts:
            gid = t.get_gid() or ""
            if ".peak." not in gid and ".break." not in gid:
                continue
            seen.add(gid)
            bb = t.get_window_extent(renderer)
            over = max(axbb.x0 - bb.x0, bb.x1 - axbb.x1, axbb.y0 - bb.y0, bb.y1 - axbb.y1)
            if over > 0:
                out.append(f"「{gid.rsplit('.', 1)[-1]}」标注超出坐标框 {over * mm_per_px:.2f} mm")
        if legbb is None:
            continue
        for ln in ax.lines:
            gid = ln.get_gid() or ""
            if ".guide." not in gid:
                continue
            xy = ln.get_transform().transform(ln.get_xydata())
            if np.any((xy[:, 0] >= legbb.x0) & (xy[:, 0] <= legbb.x1) &
                      (xy[:, 1] >= legbb.y0) & (xy[:, 1] <= legbb.y1)):
                out.append(f"「{gid.rsplit('.', 1)[-1]}」引线穿过图例")
    for gid in PEAK_LABEL_SHIFTS:
        if gid not in seen:
            out.append(f"未知标注 gid：{gid}（peak_label_shifts_mm 里写了，图上没有）")
    for gid in UNPLACED_GIDS:
        out.append(f"「{gid.rsplit('.', 1)[-1]}」无可行避让位置（NO_FEASIBLE_SLOT）")
    return out


def blocking_problems(fig) -> list[str]:
    """阻断项：调用 figpact.qa 与峰标注几何。"""
    order = list(SAMPLE_IDS)
    return (fp_qa.blocking_problems(fig)
            + fp_qa.check_series_order(fig, order, min_mm=0.5)
            + check_label_geometry(fig))


def report_shift_bounds(fig, name: str) -> None:
    problems = fp_qa.check_out_of_frame(fig)
    if problems:
        print(f"[QA] {name}: {len(problems)} 处显示位移越界 ✗")
        for q in problems:
            print("      ", q)
    elif any(any(v.values()) for v in SHIFTS_MM.values()):
        print(f"[QA] {name}: 显示位移未越界 ✓")


# ===== 1. 数据读取、化学位移严格定标与真实溶质归一化 =====
def load_and_calibrate_spectrum(rel_path, solv_name, ref_ppm, search_ppm, win_w):
    p = DATA_ROOT / pathlib.Path(rel_path) / "pdata" / "1"
    dic, data = ng.bruker.read_pdata(str(p))
    udic = ng.bruker.guess_udic(dic, data)
    uc = ng.fileiobase.uc_from_udic(udic)
    ppm_raw = uc.ppm_scale()
    spec = data.astype(float) - np.median(data)
    
    # 严格窄窗口搜索观测溶剂峰
    w = np.where(np.abs(ppm_raw - search_ppm) <= win_w)[0]
    if len(w) == 0:
        raise ValueError(f"在 {search_ppm} ± {win_w} ppm 窗口内未找到溶剂峰，请检查参数！")
    obs_solv_idx = w[np.argmax(spec[w])]
    obs_solv_ppm = ppm_raw[obs_solv_idx]
    
    # 精确平移定标
    delta_shift = ref_ppm - obs_solv_ppm
    ppm_calib = ppm_raw + delta_shift
    
    # 区分溶剂峰与溶质信号
    solv_mask = (ppm_calib >= (ref_ppm - 0.08)) & (ppm_calib <= (ref_ppm + 0.08))
    valid_range = (ppm_calib >= 0.0) & (ppm_calib <= 11.0)
    
    # 严格按非溶剂区真实溶质最大值归一化
    solute_real_max = np.max(spec[(~solv_mask) & valid_range])
    spec_norm = (spec / solute_real_max) * PEAK_MAX_NORM
    
    # 溶剂峰截顶限制在 26 a.u.（留出 12 a.u. 安全净空，绝不接触上层基线 38 a.u.）
    max_cap = PEAK_MAX_NORM * 1.18
    is_truncated = np.max(spec_norm[solv_mask]) > max_cap
    spec_norm[solv_mask] = np.clip(spec_norm[solv_mask], -5, max_cap)
    
    print(f"[{rel_path}] {solv_name:7s} 校准核对: 观测溶剂峰 = {obs_solv_ppm:.4f} ppm -> 标准参考值 = {ref_ppm:.4f} ppm (Δδ = {delta_shift:+.4f} ppm)")
    return ppm_calib, spec_norm, is_truncated, ref_ppm

print("=" * 72)
print("开始执行核磁数据化学位移严格定标 (Chemical Shift Referencing)...")
CACHED = {}
for rel, label, color, solv_name, ref_ppm, search_ppm, win_w, _sid in SAMPLES_CONFIG:
    CACHED[rel] = load_and_calibrate_spectrum(rel, solv_name, ref_ppm, search_ppm, win_w)
print("=" * 72)

# ===== 2. 特征峰标注模板 (ppm 动态由算法检测填入，杜绝手写偏差！) =====
# 格式: (搜索目标近似ppm, 样品层0~3, 基团名称, dy垂直微调, ha水平对齐, 是否自动附加ppm数字, 局部搜索窗宽)
# 主图只标"能区分合成步骤"的诊断峰；完整归属见 SI 的 Fig_S1–Fig_S4 单谱
# 格式: (搜索目标近似ppm, 样品层 0~3, 基团名称, dy保留位, ha对齐, 自动附加ppm, 局部搜索窗宽)
PEAK_LABELS_TEMPLATE = [
    # --- 第 0 层: Van-CHO (2) ---
    (9.83, 0, "–CHO", 0, "center", True, 0.12),          # 醛基：下一步应消失
    (3.91, 0, "Ar–OCH$_3$", 0, "center", True, 0.08),
    (3.68, 0, "–COOCH$_3$", 0, "center", True, 0.08),    # 甲酯：胺解后应消失

    # --- 第 1 层: Van-OH (3) ---
    (4.62, 1, "–CH$_2$OH", 0, "center", True, 0.12),     # 苄醇：证明选择性还原

    # --- 第 2 层: Van-NH$_2$ (4) ---
    (3.03, 2, "–CH$_2$NH$_2$", 0, "center", True, 0.10), # 端胺：证明胺解成功

    # --- 第 3 层: HAMA（终产物）---
    (6.18, 3, "=CH$_2$ (MA)", 0, "center", True, 0.10),  # 甲基丙烯酰双键
    (2.02, 3, "–COCH$_3$ (HA)", 0, "center", True, 0.10),# HA 骨架乙酰基内标
]

if ARGS.list_params:
    list_params()
    raise SystemExit(0)


# ===== 3. 绘图渲染（画布尺寸来自 nmr.yaml）=====
fig, ax = plt.subplots(figsize=fs.canvas_mm(*CANVAS))
reg = GidRegistry()
# 统一正方形绘图区：left=.24 right=.97 bottom=.21 top=.94 -> .73 × .73
fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
ax.set_xlim(PPM_LEFT, PPM_RIGHT)
ax.set_ylim(-6, Y_OFFSET_STEP * (len(SAMPLES_CONFIG) - 1) + Y_MAX_EXPAND)
fig.canvas.draw()
SPAN_PPM = PPM_LEFT - PPM_RIGHT
PLOT_W_MM = abs(ax.get_window_extent().width) * 25.4 / fig.dpi
MM_PER_PPM = PLOT_W_MM / SPAN_PPM

# —— 第一遍：画谱线 ——
peak_y_of: dict[int, float] = {}
artists_by_sample: dict[str, list] = {}
for idx, (rel, label, color, _, _, _, _, sid) in enumerate(SAMPLES_CONFIG):
    ppm, spec, is_trunc, ref_solv_ppm = CACHED[rel]
    offset = idx * Y_OFFSET_STEP
    mask = (ppm >= PPM_RIGHT) & (ppm <= PPM_LEFT)
    line, = ax.plot(ppm[mask], spec[mask] + offset, color=color, lw=LINEWIDTH, zorder=2)
    curve_gid = f"{FIGURE_ID}.{SCOPE}.curve.{sid}"
    line.set_gid(curve_gid)
    reg.register(line, curve_gid, params=["line_width", "layer_gap", "shifts_mm"])
    artists_by_sample.setdefault(sid, []).append(line)

    base = ax.axhline(offset, color="#E2E2E2", lw=0.45, ls="--", zorder=1)
    base_gid = f"{FIGURE_ID}.{SCOPE}.baseline.{sid}"
    base.set_gid(base_gid)
    reg.register(base, base_gid, params=["layer_gap", "shifts_mm"])
    artists_by_sample.setdefault(sid, []).append(base)

    peak_y_of[idx] = offset + float(np.max(spec[mask]))
    if is_trunc:
        brk = ax.text(ref_solv_ppm, offset + PEAK_MAX_NORM * 1.18 + 1.0, "//",
                      fontsize=FONTSIZE_NOTE, color=fs.c("SOLVENT"),
                      ha="center", va="bottom", weight="bold", zorder=5)
        brk_gid = f"{FIGURE_ID}.{SCOPE}.break.{sid}"
        brk.set_gid(brk_gid)
        reg.register(brk, brk_gid, params=["note_font_pt", "shifts_mm"])
        artists_by_sample.setdefault(sid, []).append(brk)

# —— 图例：框内右上角（与 XRD 同一做法），条目自上而下 = 谱线自上而下 ——
handles = [Line2D([], [], color=color, lw=1.2, solid_capstyle="round",
                  label=label.replace("\n", " "))
           for _, label, color, *_ in reversed(SAMPLES_CONFIG)]
legend = ax.legend(handles=handles, loc="upper right",
                   bbox_to_anchor=(LEGEND_ANCHOR_X, 0.98),
                   frameon=False, fontsize=FONTSIZE_LEGEND, ncol=LEGEND_COLS,
                   columnspacing=0.3, handlelength=0.5, handletextpad=0.2,
                   labelspacing=0.20, borderaxespad=0.15)
for _t in legend.get_texts():
    _t.set_color(fs.c("TEXT"))
leg_gid = f"{FIGURE_ID}.{SCOPE}.legend"
legend.set_gid(leg_gid)
legend.set_zorder(7)
reg.register(legend, leg_gid, params=["legend_font_pt", "legend_cols", "legend_anchor_x"])

# 将图例在数据坐标下的包络框登记进 placed_boxes，杜绝任何诊断标注与图例重叠
renderer = fig.canvas.get_renderer()
leg_bbox = legend.get_window_extent(renderer)
# —— 第二遍：两阶段确定性避让排布峰标注（阶段 A 有界确定性避让 + 阶段 B 人工偏移）——
def _segment_hits_box_mm(p1: tuple[float, float], p2: tuple[float, float],
                         box: tuple[float, float, float, float]) -> bool:
    """线段与矩形在显示空间(mm)是否相交（Liang-Barsky 算法，纯代数零误差零随机）。"""
    bx0, bx1, by0, by1 = box
    x1, y1 = p1
    x2, y2 = p2
    t0, t1 = 0.0, 1.0
    dx = x2 - x1
    dy = y2 - y1
    p = [-dx, dx, -dy, dy]
    q = [x1 - bx0, bx1 - x1, y1 - by0, by1 - y1]
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False
        else:
            t = qi / pi
            if pi < 0:
                if t > t1:
                    return False
                if t > t0:
                    t0 = t
            else:
                if t < t0:
                    return False
                if t < t1:
                    t1 = t
    return t0 <= t1


def place_peak_labels(
    ax,
    labels_by_sample_dict: dict,
    *,
    lanes: int,
    min_gap_mm: float,
    max_dx_mm: float,
    shifts_mm: dict[str, tuple[float, float]],
    artists_by_sample_dict: dict[str, list],
) -> tuple[list[dict], list[str]]:
    """有界确定性两阶段峰标注排布引擎：
    阶段 A：在 mm 显示空间下按固定优先级与候选点进行有界确定性自动避让。
    阶段 B：应用 peak_label_shifts_mm 人工偏移，不重跑避让，重画引线。
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = 25.4 / fig.dpi
    px_per_mm = fig.dpi / 25.4

    axbb = ax.get_window_extent()
    ax_x0_mm = axbb.x0 * mm_per_px
    ax_x1_mm = axbb.x1 * mm_per_px
    ax_y0_mm = axbb.y0 * mm_per_px
    ax_y1_mm = axbb.y1 * mm_per_px

    leg = ax.get_legend()
    legend_box_mm = None
    if leg is not None:
        lbb = leg.get_window_extent(renderer)
        legend_box_mm = (lbb.x0 * mm_per_px, lbb.x1 * mm_per_px,
                         lbb.y0 * mm_per_px, lbb.y1 * mm_per_px)

    break_boxes_mm = []
    for _sid, group in artists_by_sample_dict.items():
        for art in group:
            if isinstance(art, plt.Text) and art.get_text() == "//":
                bb = art.get_window_extent(renderer)
                break_boxes_mm.append((bb.x0 * mm_per_px, bb.x1 * mm_per_px,
                                       bb.y0 * mm_per_px, bb.y1 * mm_per_px))

    curves_mm = {}
    for _sid, group in artists_by_sample_dict.items():
        for line in group:
            gid = line.get_gid() or ""
            if ".curve." in gid:
                xy = line.get_transform().transform(line.get_xydata()) * mm_per_px
                curves_mm[_sid] = xy

    all_items = []
    for s_idx, itms in labels_by_sample_dict.items():
        _sid = SAMPLES_CONFIG[s_idx][7]
        for it in itms:
            exact_ppm, text, peak_y, gid = it
            anchor_disp = ax.transData.transform(
                (exact_ppm, s_idx * Y_OFFSET_STEP + peak_y)) * mm_per_px
            all_items.append({
                "sample_idx": s_idx,
                "sid": _sid,
                "ppm": exact_ppm,
                "peak_y": peak_y,
                "text": text,
                "gid": gid,
                "anchor_x_mm": float(anchor_disp[0]),
                "anchor_y_mm": float(anchor_disp[1]),
            })

    texts = [it["text"] for it in all_items]
    w_mm_list, h_mm = fs.measure_text_boxes_mm(ax, texts, FONTSIZE_PEAK)
    for it, w in zip(all_items, w_mm_list):
        it["w_mm"] = float(w)
        it["h_mm"] = float(h_mm)

    sample_base_y_mm = {}
    for s_idx, itms in labels_by_sample_dict.items():
        max_p = max(it[2] for it in itms)
        base_data = s_idx * Y_OFFSET_STEP + max_p + LABEL_LIFT
        base_disp = ax.transData.transform((0, base_data))[1] * mm_per_px
        sample_base_y_mm[s_idx] = float(base_disp)

    # 固定排序：按 (anchor_x, gid) 确定性单调递增
    all_items.sort(key=lambda it: (it["anchor_x_mm"], it["gid"]))

    lane_step_mm = h_mm + 0.8
    inset_mm = 0.8

    placed_stage_a: list[dict] = []
    unplaced_gids: list[str] = []

    # ── 阶段 A：有界、确定性的自动避让 ──
    for it in all_items:
        s_idx = it["sample_idx"]
        anchor_x = it["anchor_x_mm"]
        anchor_y = it["anchor_y_mm"]
        w = it["w_mm"]
        half_w = w / 2.0
        h = it["h_mm"]
        default_base_y = sample_base_y_mm[s_idx]

        own_curve = curves_mm[it["sid"]]
        upper_curve = (curves_mm[SAMPLES_CONFIG[s_idx + 1][7]]
                       if s_idx + 1 < len(SAMPLES_CONFIG) else None)

        found_slot = None

        for lane in range(lanes):
            cands = [anchor_x, ax_x0_mm + half_w + inset_mm, ax_x1_mm - half_w - inset_mm]
            for pl in placed_stage_a:
                pb = pl["box_mm"]
                cands.append(pb[0] - half_w - min_gap_mm)
                cands.append(pb[1] + half_w + min_gap_mm)
            obstacles = break_boxes_mm + ([legend_box_mm] if legend_box_mm else [])
            for ob in obstacles:
                cands.append(ob[0] - half_w - inset_mm)
                cands.append(ob[1] + half_w + inset_mm)

            valid_cands = []
            for cx in cands:
                if abs(cx - anchor_x) <= max_dx_mm + 1e-9:
                    if ax_x0_mm + half_w + inset_mm - 1e-9 <= cx <= ax_x1_mm - half_w - inset_mm + 1e-9:
                        valid_cands.append(round(cx, 6))
            valid_cands = sorted(set(valid_cands), key=lambda x: (abs(x - anchor_x), x))

            for cx in valid_cands:
                m_own = (own_curve[:, 0] >= cx - half_w) & (own_curve[:, 0] <= cx + half_w)
                fl = float(np.max(own_curve[m_own, 1])) + 0.15 if np.any(m_own) else default_base_y
                base_y = max(default_base_y, fl)
                lane_y = base_y + lane * lane_step_mm

                box = (cx - half_w, cx + half_w, lane_y, lane_y + h)

                if box[2] < ax_y0_mm + inset_mm or box[3] > ax_y1_mm - inset_mm:
                    continue

                collision = False
                for pl in placed_stage_a:
                    pb = pl["box_mm"]
                    if not (box[3] <= pb[2] or box[2] >= pb[3]):
                        h_gap = max(pb[0] - box[1], box[0] - pb[1])
                        if h_gap < min_gap_mm - 1e-9:
                            collision = True
                            break
                if collision:
                    continue

                for ob in obstacles:
                    if not (box[1] <= ob[0] or box[0] >= ob[1] or box[3] <= ob[2] or box[2] >= ob[3]):
                        collision = True
                        break
                if collision:
                    continue

                if np.any(m_own):
                    if float(np.max(own_curve[m_own, 1])) > box[2] - 0.1:
                        continue
                if upper_curve is not None:
                    m_up = (upper_curve[:, 0] >= box[0]) & (upper_curve[:, 0] <= box[1])
                    if np.any(m_up):
                        if float(np.min(upper_curve[m_up, 1])) < box[3] + 0.1:
                            continue

                guide_p1 = (anchor_x, anchor_y)
                guide_p2 = (cx, lane_y)
                if legend_box_mm and _segment_hits_box_mm(guide_p1, guide_p2, legend_box_mm):
                    continue
                hit_other = False
                for pl in placed_stage_a:
                    if _segment_hits_box_mm(guide_p1, guide_p2, pl["box_mm"]):
                        hit_other = True
                        break
                if hit_other:
                    continue

                found_slot = (cx, lane_y, box, lane, cx - anchor_x)
                break

            if found_slot is not None:
                break

        if found_slot is not None:
            cx, lane_y, box, lane, dx = found_slot
            placed_stage_a.append({
                "item": it,
                "x_mm": cx,
                "y_mm": lane_y,
                "box_mm": box,
                "lane": lane,
                "dx_mm": dx,
            })
        else:
            unplaced_gids.append(it["gid"])

    # ── 阶段 B：人工偏移 ──
    # final = base + peak_label_shifts_mm[gid]，不重跑避让，重画引线
    final_placed: list[dict] = []
    for pl in placed_stage_a:
        it = pl["item"]
        gid = it["gid"]
        base_x = pl["x_mm"]
        base_y = pl["y_mm"]
        shift_dx, shift_dy = shifts_mm.get(gid, (0.0, 0.0))
        final_x = base_x + shift_dx
        final_y = base_y + shift_dy
        final_placed.append({
            "item": it,
            "final_x_mm": final_x,
            "final_y_mm": final_y,
            "lane": pl["lane"],
            "dx_mm": pl["dx_mm"] + shift_dx,
            "shift": (shift_dx, shift_dy),
        })

    # 如果阶段 A 无法放入的标签由人工提供了 peak_label_shifts_mm，则按人工指定位置绘制
    remaining_unplaced = []
    for gid in unplaced_gids:
        if gid in shifts_mm:
            it = next(item for item in all_items if item["gid"] == gid)
            shift_dx, shift_dy = shifts_mm[gid]
            final_x = it["anchor_x_mm"] + shift_dx
            final_y = sample_base_y_mm[it["sample_idx"]] + shift_dy
            final_placed.append({
                "item": it,
                "final_x_mm": final_x,
                "final_y_mm": final_y,
                "lane": 0,
                "dx_mm": shift_dx,
                "shift": (shift_dx, shift_dy),
            })
        else:
            remaining_unplaced.append(gid)

    # ── 绘制最终结果（引线 + 文本） ──
    for rec in final_placed:
        it = rec["item"]
        s_idx = it["sample_idx"]
        sid = it["sid"]
        gid = it["gid"]
        trace_color = SAMPLES_CONFIG[s_idx][2]

        # 将显示坐标 (mm) 严格换算回数据坐标
        disp_px_x = rec["final_x_mm"] * px_per_mm
        disp_px_y = rec["final_y_mm"] * px_per_mm
        inv_pt = ax.transData.inverted().transform((disp_px_x, disp_px_y))
        text_data_x, text_data_y = float(inv_pt[0]), float(inv_pt[1])

        offset_y = s_idx * Y_OFFSET_STEP
        anchor_data_y = offset_y + it["peak_y"] + 0.3
        guide_end_y = max(anchor_data_y, text_data_y - 0.6)

        guide, = ax.plot([it["ppm"], text_data_x], [anchor_data_y, guide_end_y],
                         color=fs.c("GUIDE"), lw=0.55, zorder=3)
        guide.set_gid(gid.replace(".peak.", ".guide."))
        artists_by_sample_dict.setdefault(sid, []).append(guide)

        lbl = ax.text(text_data_x, text_data_y, it["text"],
                      fontsize=FONTSIZE_PEAK, ha="center", va="bottom",
                      color=trace_color, zorder=4)
        lbl.set_gid(gid)
        reg.register(lbl, gid, params=["peak_font_pt", "label_lift", "label_min_gap_mm", "label_max_dx_mm"])
        guide_gid = gid.replace(".peak.", ".guide.")
        reg.register(guide, guide_gid, params=["label_lift", "label_max_dx_mm"])
        artists_by_sample_dict.setdefault(sid, []).append(lbl)

    return final_placed, remaining_unplaced


labels_by_sample: dict[int, list[tuple[float, str, float]]] = {}
for approx_ppm, sample_idx, group_name, _dy, ha_align, auto_ppm, win_search in PEAK_LABELS_TEMPLATE:
    rel, _, _, _, _, _, _, _ = SAMPLES_CONFIG[sample_idx]
    ppm, spec, _, _ = CACHED[rel]
    win = np.where(np.abs(ppm - approx_ppm) <= win_search)[0]
    j = win[np.argmax(spec[win])] if len(win) else np.argmin(np.abs(ppm - approx_ppm))
    exact_ppm = ppm[j]
    peak_y = min(spec[j], PEAK_MAX_NORM * 1.15)
    text = f"{group_name} {exact_ppm:.2f}" if (auto_ppm and SHOW_PPM) else group_name
    _sid = SAMPLES_CONFIG[sample_idx][7]
    labels_by_sample.setdefault(sample_idx, []).append(
        (exact_ppm, text, peak_y, f"{FIGURE_ID}.{SCOPE}.peak.{_sid}.{_gid_tag(approx_ppm)}"))

PLACED_RECORDS, UNPLACED_GIDS = place_peak_labels(
    ax,
    labels_by_sample,
    lanes=LABEL_LANES,
    min_gap_mm=LABEL_MIN_GAP_MM,
    max_dx_mm=LABEL_MAX_DX_MM,
    shifts_mm=PEAK_LABEL_SHIFTS,
    artists_by_sample_dict=artists_by_sample,
)
# 坐标轴格式化已在图例/标注计算前预设范围，此处格式化标签与刻度
ax.set_xlabel(r"Chemical Shift $\delta$ (ppm)", fontsize=FONTSIZE_AXIS,
              labelpad=3.5, weight="bold")
ax.set_ylabel("Normalized Intensity (a.u.)", fontsize=FONTSIZE_AXIS,
              labelpad=3.5, weight="bold")
ax.tick_params(length=2.5, width=0.6, labelsize=FONTSIZE_TICK, pad=2)
x_gid = f"{FIGURE_ID}.{SCOPE}.xlabel"
y_gid = f"{FIGURE_ID}.{SCOPE}.ylabel"
ax.xaxis.label.set_gid(x_gid)
ax.yaxis.label.set_gid(y_gid)
reg.register(ax.xaxis.label, x_gid, params=["axis_font_pt"])
reg.register(ax.yaxis.label, y_gid, params=["axis_font_pt"])
fs.strip_yticks(ax)

# ★ 显示位移排在**所有布局求解之后**
for _sid, _group in artists_by_sample.items():
    _dy = SHIFTS_MM[SCOPE][_sid]
    if _dy:
        for _artist in _group:
            apply_display_shift(_artist, _dy)

if ARGS.inventory:
    inv = fp_inventory(fig, reg)
    print(json.dumps(inv, ensure_ascii=False, indent=2))
    plt.close(fig)
    sys.exit(0)

if ARGS.inspect:
    art = reg.get(ARGS.inspect)
    if art is None:
        print(f"未找到 gid: {ARGS.inspect}")
    else:
        print(f"[{ARGS.inspect}] {type(art).__name__} | 绑定参数: {reg.params_of(ARGS.inspect)}")
    plt.close(fig)
    sys.exit(0)

fs.export(fig, STAGING / "Fig2_NMR_pure_stacked", dpi=DPI)
fs.qa_report(fig, "NMR 叠谱")
report_shift_bounds(fig, "NMR 叠谱")
_blockers = blocking_problems(fig)

exemptions_mgr = fp_publish.Exemptions(EXEMPT_PATH)
if ARGS.exempt_current:
    exemptions_mgr.write(_blockers, ARGS.reason)
    print(f"[豁免] 写入 {len(_blockers)} 条 → {EXEMPT_PATH.name}；理由：{ARGS.reason.strip()}")

_exempt = exemptions_mgr.load()
_exempted = [(b, _exempt[fp_qa.signature(b)]) for b in _blockers if fp_qa.signature(b) in _exempt]
_new = [b for b in _blockers if fp_qa.signature(b) not in _exempt]
if _blockers:
    print(f"[验收] 阻断 {len(_blockers)} 条，其中 {len(_exempted)} 条人工豁免：")
    for _b, _why in _exempted:
        print(f"      [豁免] {_b}")
        print(f"             理由：{_why}")
    for _b in _new:
        print(f"      [未豁免] {_b}")
if _new and STRICT:
    print(f"[验收] **未豁免**阻断项 {len(_new)} 条：**拒绝发布**，{ROOT.name} 里的正式输出未被覆盖")
    shutil.rmtree(STAGING, ignore_errors=True)
    sys.exit(1)
if not _blockers:
    print("[验收] 无阻断项 ✓")
elif not _new:
    print("[验收] 无**未豁免**阻断项；但有 "
          f"{len(_exempted)} 条人工豁免（上面逐条列了理由）——不等于图已经干净")
_written = fp_publish.publish(STAGING, ROOT)
shutil.rmtree(STAGING, ignore_errors=True)
print(f"已发布 {len(_written)} 个文件到 {ROOT}")
