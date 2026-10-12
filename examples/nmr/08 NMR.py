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
from figpact.relations import measure_relation, set_relation_target, remaining_space, validate_layout

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


def _gid(kind: str, sid: str = "", tag: str = "") -> str:
    """对象身份的唯一构造点：`fig2_nmr.main.<kind>[.<sid>[.<tag>]]`。

    末段不带点（`3p91`），否则按点切分的读取方会切错。
    """
    parts = [FIGURE_ID, SCOPE, kind]
    if sid:
        parts.append(sid)
    if tag:
        parts.append(tag)
    return ".".join(parts)


def _guide_gid(peak_gid: str) -> str:
    """引线 gid 由标注 gid 派生——身份规则只此一处。"""
    return peak_gid.replace(".peak.", ".guide.")


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
RELATION_PARAMS = {"pitch_mm": ("baseline_pitch", SAMPLE_IDS[1:])}

# ===== 特征峰标注模板 (ppm 动态由算法检测填入，杜绝手写偏差！) =====
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


def _peak_label_gids() -> list[str]:
    """模板里每个诊断峰在本样品上的**完整稳定 id**（`fig2_nmr.main.peak.<sid>.<tag>`）。

    它是作者已知的峰模板，不是"新建的科研标注"：`new scientific label` 永远不在这里面。
    """
    return [_gid("peak", SAMPLES_CONFIG[idx][7], _gid_tag(ppm))
            for ppm, idx, *_ in PEAK_LABELS_TEMPLATE]


def _peak_label_keys() -> list[str]:
    """同样的峰在**配置里**的键：作用域内的短名 `peak.<sid>.<tag>` 一串。

    `nmr.yaml` 的 `peak_label_shifts_mm.main` 下就是这么写的，JSON 操作面的路径段也是它。
    完整 gid 只在 `_apply_config` 那一处派生给图元消费方（身份拼法只此一处）。
    """
    return [gid.removeprefix(f"{FIGURE_ID}.{SCOPE}.") for gid in _peak_label_gids()]


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
    "schema_version": (int, 2, 2),
    "canvas_w_mm": (float, 20.0, 200.0),
    "canvas_h_mm": (float, 20.0, 200.0),
    "label_lift_mm": (float, 0.0, 15.0),
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
    ap.add_argument("--check-effect", action="store_true",
                    help="在清点中执行参数生效扰动检查")
    ap.add_argument("--inspect", default=None,
                    help="检查指定 gid 的图元信息")
    ap.add_argument("--probe", default=None,
                    help="试算沙箱目录：给定时产物只写这里，正式输出目录一个字节都不动")
    ap.add_argument("--migrate-config", help="把旧 YAML 的实测布局迁移到新文件（不发布图件）")
    return ap.parse_args(argv)


#: CLI 只在 `python "08 NMR.py" …` 时解析。作为模块被 native runtime 导入时
#: **不碰调用方的 argv**（worker 的协议参数不该被 argparse 拒掉），也不输出、不落盘。
ARGS = _cli(sys.argv[1:]) if __name__ == "__main__" else _cli([])
CONFIG_PATH = pathlib.Path(ARGS.config).expanduser() if ARGS.config else ROOT / "nmr.yaml"


SCHEMA = {**SCALARS, "show_ppm": (bool,), "shifts_mm": (dict,), "peak_label_shifts_mm": (dict,),
          "pitch_mm": (dict,), "group_y_mm": (dict,), "layout_reference": (dict,)}


def _label_pair(name: str, scope: str, label: str, pair) -> list:
    """校验一个 `[dx, dy]` 并归一成两个有限数字的列表（`dx` 向右、`dy` 向上，各 ±10 mm）。"""
    if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
        raise ConfigError(f"{name}：peak_label_shifts_mm.{scope}.{label} 必须是 [dx, dy] 两个数字")
    dx, dy = pair[0], pair[1]
    if isinstance(dx, bool) or not isinstance(dx, (int, float)) or not math.isfinite(dx):
        raise ConfigError(f"{name}：peak_label_shifts_mm.{scope}.{label}[0] 必须是有效数字")
    if isinstance(dy, bool) or not isinstance(dy, (int, float)) or not math.isfinite(dy):
        raise ConfigError(f"{name}：peak_label_shifts_mm.{scope}.{label}[1] 必须是有效数字")
    dx_f, dy_f = float(dx), float(dy)
    if abs(dx_f) > SHIFT_LIMIT_MM or abs(dy_f) > SHIFT_LIMIT_MM:
        raise ConfigError(f"{name}：peak_label_shifts_mm.{scope}.{label} 超出 ±{SHIFT_LIMIT_MM} mm")
    return [dx_f, dy_f]


def _scope_of_gid(gid: str) -> str | None:
    """`fig2_nmr.main.peak.vancho.3p91` → `main`；不带本图前缀的一律 None（不猜）。"""
    return next((sc for sc in SCOPES if gid.startswith(f"{FIGURE_ID}.{sc}.")), None)


def _load_label_shifts(name: str, raw) -> dict:
    """把 `peak_label_shifts_mm` 归一成**作用域嵌套的规范形态**：
    `{main: {"peak.<sid>.<tag>": [dx, dy]}}`。

    原始 YAML 和归一化结果都使用同一个作用域嵌套形态，
    所以反复执行 `prepare_config` 不改变配置结构或数值。

    规范形态**保持 YAML 的样子**（作用域 → 短名）：完整 gid 只在 `_apply_config` 一处派生，
    不给同一个量留下两套钥匙。作用域写错、值形不对、越界一律报错，不静默吞掉。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}：peak_label_shifts_mm 必须是字典映射")
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if key in SCOPES:
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ConfigError(f"{name}：peak_label_shifts_mm.{key} 必须是 `标注gid: [dx, dy]` 映射")
            for label, pair in value.items():
                if not isinstance(label, str):
                    raise ConfigError(f"{name}：peak_label_shifts_mm.{key} 的标注键必须是字符串")
                if label.startswith(f"{FIGURE_ID}.") and _scope_of_gid(label) != key:
                    raise ConfigError(f"{name}：peak_label_shifts_mm.{key} 里的 {label!r} "
                                      f"不是本作用域 {key} 下的标注（前缀/作用域对不上）")
                out.setdefault(key, {})[label.removeprefix(f"{FIGURE_ID}.{key}.")] = \
                    _label_pair(name, key, label, pair)
        else:
            raise ConfigError(f"{name}：peak_label_shifts_mm 里有未知作用域 {key!r}；"
                              f"可用：{list(SCOPES)}")
    return out


def _peak_shifts_by_gid(per_scope: dict) -> dict:
    """规范形态 → **图元身份拼法**的扁平视图（`fig2_nmr.main.peak.vancho.9p83` → [dx, dy]）。

    这是「配置键」与「图元 gid」之间唯一的换算点：避让引擎、QA、契约都拿图元 gid 说话，
    配置里存的是短名。换算只此一处，不在别处再拼一次前缀。
    """
    return {f"{FIGURE_ID}.{scope}.{label}": pair
            for scope, per_label in per_scope.items()
            for label, pair in per_label.items()}


def prepare_config(config: dict, *, label: str | None = None) -> dict:
    """把任意来源的配置映射标准化成**构建路径能直接消费**的形态。

    **纯映射变换**：不读 YAML、不碰 Bruker 数据、不画图，输入映射不被修改（返回新字典）。
    legacy 装载（`load_config_nmr`）与 native 构建（`build_scene` 收到的候选配置）
    **共用这一份**：`shifts_mm` 缺失 / 为 `{}` / 只写部分作用域或样品，一律补 0.0
    （「不写 = 不动」，而不是让 `SHIFTS_MM[scope][sid]` 抛 KeyError），
    `peak_label_shifts_mm` 同样补全：**模板里每个诊断峰都带一个 `[0.0, 0.0]`**，
    所以 YAML 写 `{}` 时这些路径依然存在，`set_parameter` 的路径解析不是悬空引用；
    用户写了的条目覆盖默认值。规范形态**保持 YAML 的样子**（`main` → 短名 →
    `[dx, dy]`），完整 gid 只由 `_apply_config` 派生给图元消费方。
    补的是**零值**（不动），不是新增标记、也不改排布：`_requested_peak_shifts` 把
    「零 = 没要求」贯彻到避让引擎，基线（全零）与空映射逐字节同图。
    对已标准化的映射幂等（两种写法都收），所以 `_apply_config(prepare_config(cfg))` 这条
    每次重建的必经之路、以及「API 独立 _build 先 prepare 再交给 build_scene」都成立。
    """
    name = label or CONFIG_PATH.name
    cfg = dict(config)
    raw_labels = cfg.get("peak_label_shifts_mm")
    raw_shifts = cfg.get("shifts_mm") or {}
    if not isinstance(raw_shifts, dict):
        raise ConfigError(f"{name}：shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw_shifts) - set(SCOPES)):
        raise ConfigError(f"{name}：shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")

    cfg["peak_label_shifts_mm"] = {scope: {key: [0.0, 0.0] for key in _peak_label_keys()}
                                   for scope in SCOPES}
    for scope, per_label in _load_label_shifts(name, raw_labels).items():
        cfg["peak_label_shifts_mm"].setdefault(scope, {}).update(per_label)
    cfg["shifts_mm"] = {scope: {sid: 0.0 for sid in SAMPLE_IDS} for scope in SCOPES}
    for scope, per_sample in raw_shifts.items():
        if per_sample is None:
            continue
        if not isinstance(per_sample, dict):
            raise ConfigError(f"{name}：shifts_mm.{scope} 必须是 `样品id: 毫米` 映射")
        if unknown := sorted(set(per_sample) - set(SAMPLE_IDS)):
            raise ConfigError(f"{name}：shifts_mm.{scope} 里有未知样品 {unknown}；可用：{list(SAMPLE_IDS)}")
        for sid, value in per_sample.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} 必须是有效数字")
            mm = float(value)
            if abs(mm) > SHIFT_LIMIT_MM:
                sug = min(max(mm, -SHIFT_LIMIT_MM), SHIFT_LIMIT_MM)
                raise ConfigError(f"{name}：shifts_mm.{scope}.{sid} = {mm} 超出 ±{SHIFT_LIMIT_MM} mm；建议改成 {sug}")
            cfg["shifts_mm"][scope][sid] = mm
    return cfg


def _requested_peak_shifts(shifts: dict) -> dict:
    """挑出**真的要求位移**的条目（任何 `{键: [dx, dy]}` 映射）：`[0, 0]`（含补出来的默认值）=「不动」。

    零值必须与「没写」逐字节等价，否则 `prepare_config` 补出的默认零值会把
    「没有可行避让位置」的标注强行钉回锚点——那是**改排布**，不是补默认值。
    避让引擎、QA 的「图上有这个标注吗」、迁移写出口都用这一份口径。
    """
    return {key: pair for key, pair in shifts.items() if pair[0] or pair[1]}


def load_config_nmr(path: pathlib.Path) -> dict:
    """读 YAML（含 schema 1 迁移与布局校验）→ `prepare_config` 标准化位移映射。"""
    if ARGS.migrate_config:
        legacy = {**SCHEMA, "schema_version": (int, 1, 1), "layer_gap": (float, 0, 200),
                  "top_headroom": (float, 0, 400), "label_lift": (float, 0, 60)}
        for key in ("pitch_mm", "group_y_mm", "layout_reference", "label_lift_mm"):
            legacy.pop(key)
        cfg = fp_load_config(path, legacy)
        pitch, headroom, lift = (cfg.pop(k) for k in ("layer_gap", "top_headroom", "label_lift"))
        scale = (pitch * (len(SAMPLES_CONFIG)-1) + headroom + 6) / (cfg["canvas_h_mm"] * 0.73)
        cfg.update(schema_version=2, label_lift_mm=lift/scale,
                   pitch_mm={"main": {sid: pitch/scale for sid in SAMPLE_IDS[1:]}},
                   group_y_mm={"main": 0.0},
                   layout_reference={"main": {"axis_bottom_data": -6.0, "units_per_mm": scale,
                                              "pitch_data": pitch, "headroom_data": headroom}})
    else:
        cfg = fp_load_config(path, SCHEMA)
    validate_layout(cfg, scopes=SCOPES, ids=SAMPLE_IDS[1:], parameter="pitch_mm",
                    reference_fields=("pitch_data", "headroom_data", "axis_bottom_data", "units_per_mm"))
    return prepare_config(cfg, label=path.name)


CONFIG = load_config_nmr(CONFIG_PATH)

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
            ("tick_font_pt", "刻度数字字号", "pt", SCALARS["tick_font_pt"][1:], "刻度数字变大，刻度行高变大"),
            ("note_font_pt", "溶剂截顶标记字号", "pt", SCALARS["note_font_pt"][1:], "// 溶剂截顶标记变大"),
        ]),
        ("图例 (Legend)", [
            ("legend_font_pt", "图例字号", "pt", SCALARS["legend_font_pt"][1:], "图例框变高变大（NMR顶部空间为常数，不自动压缩谱线）"),
            ("legend_cols", "图例列数", "列", SCALARS["legend_cols"][1:], "列数变多则图例变宽变扁，横向更宽纵向更扁"),
            ("legend_anchor_x", "图例水平锚点", "比率", SCALARS["legend_anchor_x"][1:], "图例向右靠（1.0最右，太小向左靠会压住y轴标题）"),
        ]),
        ("系列/谱线 (Curves/Series)", [
            ("line_width", "谱线线宽", "pt", SCALARS["line_width"][1:], "所有谱线变粗，仅影响观感不改布局"),
        ]),
        ("标注 (Annotations)", [
            ("peak_font_pt", "峰标注字号", "pt", SCALARS["peak_font_pt"][1:], "基团诊断峰文字变大；调小可缓解近峰文字重叠"),
            ("label_lift_mm", "标注离峰顶净空", "mm", SCALARS["label_lift_mm"][1:], "标注基础位置向上移动指定毫米，不改变真实峰位"),
            ("label_min_gap_mm", "标注最小水平净空", "mm", SCALARS["label_min_gap_mm"][1:], "相邻标注横向更稀疏避让，防文字交叠粘连"),
            ("label_max_dx_mm", "标注避让最大横移", "mm", SCALARS["label_max_dx_mm"][1:], "允许标注向两侧平移寻找避让空位的最大窗口"),
            ("label_lanes", "标注避让最大层数", "层", SCALARS["label_lanes"][1:], "允许使用的阶梯避让层数（1-5），调多纵向分层更充裕"),
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

    print("=== 开关 (Booleans) ===")
    print(f"  {'key':<24}{'中文名':<16}{'当前值':>8} 切换效果")
    print(f"  {'show_ppm':<24}{'标注显示ppm后缀':<16}{str(CONFIG['show_ppm']):>8} 设为 true 标注带 ppm 数值（更宽），false 只显示基团名（窄约 40%）\n")

    print("=== 位移 (Shifts) ===")
    print("1. 整层位移 key: shifts_mm.main.<样品id> (单位 mm，范围 [-10.0, 10.0]，正数向上)")
    print("   调大会怎样: 该样品整组图元（谱线+基线+//+标注+引线）纯显示整体上移，不动科研数据")
    print("   可用样品 id: " + "、".join(SAMPLE_IDS))
    print("   使用示例: shifts_mm: { main: { vancho: 1.0 } }")
    print("2. 逐标注微调 key: peak_label_shifts_mm.main.<标注key> (值形 [dx, dy]，单位 mm，各 ±10.0，dx向右，dy向上)")
    print("   调大会怎样: 仅该峰标注独立微移（dx 向右，dy 向上），引线自动跟随重新连接；改完走真实重建+渲染校验")
    print("   可用标注（左列 = YAML 键/路径第三段，整串一个键段；右列 = inspect 用的图元 gid）:")
    for key, gid in zip(_peak_label_keys(), _peak_label_gids()):
        print(f"     {key:<20} (gid: {gid})")
    print("   路径第三段是完整的标注 key（不按点拆开）。JSON 示例：")
    print('     {"operation":"set_parameter","path":["peak_label_shifts_mm","main",'
          f'"{_peak_label_keys()[1]}"],"value":[0.5, 1.0]}}')
    print("=== 实测毫米距离与整组位置 ===")
    print(f"  pitch_mm.main: {CONFIG['pitch_mm']['main']} mm（相邻基线间距）")
    print(f"  group_y_mm.main: {CONFIG['group_y_mm']['main']} mm（所有样品及标注整组平移）")
    print("  调大间距只平移上方样品；空间不足报超限，不缩放。独立 shifts_mm 在其后叠加。")



#: 当前生效的配置。legacy 导入 = nmr.yaml；native = build_scene 收到的候选配置。
_CFG: dict = {}
#: 受保护的科研载荷缓存（load_science 只定标一次；warm 布局不再读 Bruker 数据）。
_SCIENCE: dict | None = None
#: legacy CLI 的定标核对行是否已经打过（native 路径静默，不打）。
_DATA_REPORTED = False
#: 纯布局图元（基线虚线、峰标注引线）：几何是排版，不是科研数据，故不进科学指纹。
#: 谱线、峰标注文字、轴文字、图例仍然受保护。由构建路径**自己登记**，不另抄一份清单。
_LAYOUT_GIDS: set[str] = set()


def _apply_config(cfg: dict) -> None:
    """把配置里的排版全局量装进模块。

    **这是布局全局量的唯一初始化路径**：legacy 导入与 native
    `build_scene(science, config, scope)` 都只走这里，不存在第二处「又把 YAML
    读进另一套全局」的分歧约定。

    排版全局量里还有 matplotlib 的 rcParams（字体族、mathtext、figure.dpi）——
    它们同样决定文字实测宽度与避让结果，所以**在这里一起装**，不能只在导入时
    `fs.apply()` 一次。否则构建结果会偷偷取决于调用方当时的 rcParams：同一个
    `(science, config, scope)` 换个环境（例如宿主用 `rc_context()` 隔离、或第二
    次进程内构造时导入期样式已被回滚）就会排版出另一张图，契约与实图随之对不上。
    """
    global _CFG, CANVAS, Y_OFFSET_STEP, Y_MAX_EXPAND, LABEL_LIFT, LINEWIDTH
    global FONTSIZE_PEAK, FONTSIZE_LEGEND, FONTSIZE_NOTE, FONTSIZE_AXIS, FONTSIZE_TICK
    global LEGEND_COLS, LEGEND_ANCHOR_X, LABEL_MIN_GAP_MM, LABEL_MAX_DX_MM, LABEL_LANES
    global PEAK_LABEL_SHIFTS, SHOW_PPM, SHIFTS_MM
    fs.apply()
    _CFG = cfg
    ref = cfg["layout_reference"]["main"]
    CANVAS = (cfg["canvas_w_mm"], cfg["canvas_h_mm"])
    Y_OFFSET_STEP = ref["pitch_data"]
    Y_MAX_EXPAND = ref["headroom_data"]
    LABEL_LIFT = cfg["label_lift_mm"] * ref["units_per_mm"]
    LINEWIDTH = cfg["line_width"]
    FONTSIZE_PEAK = cfg["peak_font_pt"]
    FONTSIZE_LEGEND = cfg["legend_font_pt"]
    FONTSIZE_NOTE = cfg["note_font_pt"]
    FONTSIZE_AXIS = cfg["axis_font_pt"]
    FONTSIZE_TICK = cfg["tick_font_pt"]
    LEGEND_COLS = cfg["legend_cols"]
    LEGEND_ANCHOR_X = cfg["legend_anchor_x"]
    LABEL_MIN_GAP_MM = cfg["label_min_gap_mm"]
    LABEL_MAX_DX_MM = cfg["label_max_dx_mm"]
    LABEL_LANES = cfg["label_lanes"]
    #: 配置里存的是作用域 → 短名；图元消费方（避让引擎 / QA / 契约）按**完整 gid** 说话。
    #: 换算只在 `_peak_shifts_by_gid` 这一处发生，配置本身保持 YAML 的样子。
    PEAK_LABEL_SHIFTS = _peak_shifts_by_gid(cfg["peak_label_shifts_mm"])
    #: 标注里要不要带 ppm 后缀。**只改显示格式，不改归属文字**——
    #: 归属始终是模板里的 `group_name`（Ar–OCH₃ 等），ppm 是算法检测出来的补充信息。
    SHOW_PPM = cfg["show_ppm"]
    SHIFTS_MM = cfg["shifts_mm"]


_apply_config(CONFIG)

STRICT = ARGS.strict
#: **试算隔离**：`--probe <dir>` 或环境变量 `FIGPACT_PROBE_DIR`（`figpact try` 会设）
#: 一旦生效，OUT_DIR 就是一次性的沙箱，正式输出目录一个字节都不动。
PROBE_DIR = (pathlib.Path(ARGS.probe).expanduser().resolve() if ARGS.probe
             else fp_publish.probe_dir())
OUT_DIR = PROBE_DIR or ROOT
#: 存量缺陷基线。**这是 NMR 逼出来的规范补充**：
#: FTIR 的存量问题（字形下限、贴边）本来就在非阻断集合里，所以不需要基线；
#: NMR 的存量问题恰好落在阻断集合里（标签重叠、文字压线），没有基线的话
#: `--strict` 永远是红的，门就废了。基线让门只对**回归**报警，不对旧账报警。
EXEMPT_PATH = OUT_DIR / "qa_exemptions.json"


#: 存量缺陷基线只该接住**警告类**（字形下限、贴边——出版取舍）；重叠 / 压线 / 出框 /
#: 谱层挤压是阻断项，应该回去改布局，不该靠豁免糊过去。这条边界是**人**的判断；
#: 机器只把每一条诊断的 severity（blocking / warning）标出来，供签字时辨别。
#: 以前这里靠关键词匹配文本判断，现在由 `figpact.qa.diagnose()` 的结构化诊断取代。


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
    for gid in _requested_peak_shifts(PEAK_LABEL_SHIFTS):
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
def load_and_calibrate_spectrum(rel_path, solv_name, ref_ppm, search_ppm, win_w, *, verbose=True):
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
    
    if verbose:
        print(f"[{rel_path}] {solv_name:7s} 校准核对: 观测溶剂峰 = {obs_solv_ppm:.4f} ppm -> 标准参考值 = {ref_ppm:.4f} ppm (Δδ = {delta_shift:+.4f} ppm)")
    return ppm_calib, spec_norm, is_truncated, ref_ppm


def load_science(*, verbose: bool = False) -> dict:
    """受保护的科研载荷：读 Bruker pdata → 溶剂峰严格定标 → 溶质归一化 + 溶剂截顶。

    只定标一次并缓存：warm 的纯布局试算**不再读磁盘**。不建 Figure。
    `verbose=True` 只给 legacy CLI 打印可追溯的定标核对行；native 路径静默。
    """
    global _SCIENCE
    if _SCIENCE is None:
        _SCIENCE = {}
        for rel, _, _, solv_name, ref_ppm, search_ppm, win_w, _ in SAMPLES_CONFIG:
            _SCIENCE[rel] = load_and_calibrate_spectrum(
                rel, solv_name, ref_ppm, search_ppm, win_w, verbose=verbose)
    return _SCIENCE


def science_inputs() -> list[str]:
    """本图**实际读取**的科研输入文件（native worker 据此把源文件算进输入 revision）。

    逐条列出 nmrglue `read_pdata` 真正读的文件：`pdata/1/procs`、`pdata/1/1r`
    （`all_components=False` 时读实部）与样品目录的 `acqus`。同目录里的 `1i` /
    `fid` / `pulseprogram` / `thumb.png` **没有被读**，所以不声明。
    """
    paths = []
    for rel, *_ in SAMPLES_CONFIG:
        sample = DATA_ROOT / pathlib.Path(rel)
        paths.extend([str(sample / "pdata" / "1" / name) for name in ("procs", "1r")])
        paths.append(str(sample / "acqus"))
    return paths


def prepare_data():
    """legacy 入口：定标一次并把可追溯的核对行打出来。"""
    global _DATA_REPORTED
    first = not _DATA_REPORTED
    if first:
        print("=" * 72)
        print("开始执行核磁数据化学位移严格定标 (Chemical Shift Referencing)...")
        _DATA_REPORTED = True
    science = load_science(verbose=True)
    if first:
        print("=" * 72)
    return science


if ARGS.list_params:
    list_params()
    raise SystemExit(0)


def _draw_spectra(science: dict):
    global reg, artists_by_sample
    fig, ax = plt.subplots(figsize=fs.canvas_mm(*CANVAS))
    reg = GidRegistry()
    ax.set_gid(_gid("panel"))
    fig.subplots_adjust(left=0.24, right=0.97, top=0.94, bottom=0.21)
    ax.set_xlim(PPM_LEFT, PPM_RIGHT)
    ref = _CFG["layout_reference"]["main"]
    height_mm = ax.get_window_extent().height * 25.4 / fig.dpi
    ax.set_ylim(ref["axis_bottom_data"], ref["axis_bottom_data"] + ref["units_per_mm"] * height_mm)
    fig.canvas.draw()
    artists_by_sample = {}
    for idx, (rel, _, color, _, _, _, _, sid) in enumerate(SAMPLES_CONFIG):
        ppm, spec, is_trunc, ref_solv_ppm = science[rel]
        offset = idx * Y_OFFSET_STEP
        mask = (ppm >= PPM_RIGHT) & (ppm <= PPM_LEFT)
        line, = ax.plot(ppm[mask], spec[mask] + offset, color=color, lw=LINEWIDTH, zorder=2)
        curve_gid = _gid("curve", sid)
        line.set_gid(curve_gid)
        reg.register(line, curve_gid, params=["line_width", "pitch_mm", "group_y_mm", "shifts_mm"])
        artists_by_sample.setdefault(sid, []).append(line)
        base = ax.axhline(offset, color="#E2E2E2", lw=0.45, ls="--", zorder=1)
        base_gid = _gid("baseline", sid)
        base.set_gid(base_gid)
        reg.register(base, base_gid, params=["pitch_mm", "group_y_mm", "shifts_mm"])
        _LAYOUT_GIDS.add(base_gid)
        artists_by_sample.setdefault(sid, []).append(base)
        if is_trunc:
            brk = ax.text(ref_solv_ppm, offset + PEAK_MAX_NORM * 1.18 + 1.0, "//",
                          fontsize=FONTSIZE_NOTE, color=fs.c("SOLVENT"),
                          ha="center", va="bottom", weight="bold", zorder=5)
            brk_gid = _gid("break", sid)
            brk.set_gid(brk_gid)
            reg.register(brk, brk_gid, params=["note_font_pt", "shifts_mm"])
            artists_by_sample.setdefault(sid, []).append(brk)
    entries = [(s[7], s[1].replace("\n", " "), s[2]) for s in reversed(SAMPLES_CONFIG)]
    handles = [Line2D([], [], color=color, lw=1.2, solid_capstyle="round", label=label)
               for _, label, color in entries]
    legend = ax.legend(handles=handles, loc="upper right",
                       bbox_to_anchor=(LEGEND_ANCHOR_X, 0.98),
                       frameon=False, fontsize=FONTSIZE_LEGEND, ncol=LEGEND_COLS,
                       columnspacing=0.3, handlelength=0.5, handletextpad=0.2,
                       labelspacing=0.20, borderaxespad=0.15)
    for (sid, _, _), text in zip(entries, legend.get_texts()):
        text.set_color(fs.c("TEXT"))
        if reg is not None:
            # 图例里每行样品名也是**可见文字**，给它稳定身份（否则科学指纹只能按位置编号）。
            reg.register(text, _gid("legend.text", sid), params=["legend_font_pt"])
    leg_gid = _gid("legend")
    legend.set_gid(leg_gid)
    legend.set_zorder(7)
    reg.register(legend, leg_gid, params=["legend_font_pt", "legend_cols", "legend_anchor_x"])
    return fig, ax
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

    # ── 阶段 A 补充：邻近同层标注错位避让（错层 / 引线错位） ──
    # 当某标签因与同层相邻标签拥挤而在基础候选范围内找不到可用槽位时，
    # 允许与该邻近标签协同错位：两标签分别向左/向右拉开，引线连回峰位。
    if unplaced_gids:
        still_unplaced = []
        for ugid in unplaced_gids:
            it = next(item for item in all_items if item["gid"] == ugid)
            s_idx = it["sample_idx"]
            resolved = False
            for pl_idx, pl in enumerate(placed_stage_a):
                if pl["item"]["sample_idx"] != s_idx:
                    continue
                prev_it = pl["item"]
                if abs(it["anchor_x_mm"] - prev_it["anchor_x_mm"]) > (it["w_mm"] + prev_it["w_mm"] + min_gap_mm * 2):
                    continue
                cands_it = [
                    round(ax_x1_mm - it["w_mm"] / 2.0 - inset_mm, 4),
                    round(prev_it["anchor_x_mm"] + prev_it["w_mm"] / 2.0 + it["w_mm"] / 2.0 + min_gap_mm, 4),
                ]
                other_boxes = [p["box_mm"] for i, p in enumerate(placed_stage_a) if i != pl_idx]
                for cx2 in cands_it:
                    cx1 = round(cx2 - it["w_mm"] / 2.0 - prev_it["w_mm"] / 2.0 - min_gap_mm, 4)
                    lane_y1 = pl["y_mm"]
                    lane_y2 = pl["y_mm"]
                    box1 = (cx1 - prev_it["w_mm"] / 2.0, cx1 + prev_it["w_mm"] / 2.0, lane_y1, lane_y1 + prev_it["h_mm"])
                    box2 = (cx2 - it["w_mm"] / 2.0, cx2 + it["w_mm"] / 2.0, lane_y2, lane_y2 + it["h_mm"])
                    if box1[0] < ax_x0_mm + inset_mm or box2[1] > ax_x1_mm - inset_mm:
                        continue
                    col1 = any(not (box1[3] <= pb[2] or box1[2] >= pb[3]) and max(pb[0] - box1[1], box1[0] - pb[1]) < min_gap_mm - 1e-9 for pb in other_boxes)
                    if col1:
                        continue
                    col2 = any(not (box2[3] <= pb[2] or box2[2] >= pb[3]) and max(pb[0] - box2[1], box2[0] - pb[1]) < min_gap_mm - 1e-9 for pb in other_boxes)
                    if col2:
                        continue
                    g1_p1, g1_p2 = (prev_it["anchor_x_mm"], prev_it["anchor_y_mm"]), (cx1, lane_y1)
                    g2_p1, g2_p2 = (it["anchor_x_mm"], it["anchor_y_mm"]), (cx2, lane_y2)
                    if _segment_hits_box_mm(g1_p1, g1_p2, box2) or _segment_hits_box_mm(g2_p1, g2_p2, box1):
                        continue
                    if any(_segment_hits_box_mm(g1_p1, g1_p2, pb) for pb in other_boxes):
                        continue
                    if any(_segment_hits_box_mm(g2_p1, g2_p2, pb) for pb in other_boxes):
                        continue
                    pl["x_mm"] = cx1
                    pl["box_mm"] = box1
                    pl["dx_mm"] = cx1 - prev_it["anchor_x_mm"]
                    placed_stage_a.append({
                        "item": it,
                        "x_mm": cx2,
                        "y_mm": lane_y2,
                        "box_mm": box2,
                        "lane": pl["lane"],
                        "dx_mm": cx2 - it["anchor_x_mm"],
                    })
                    resolved = True
                    break
                if resolved:
                    break
            if not resolved:
                still_unplaced.append(ugid)
        unplaced_gids = still_unplaced

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
        guide_gid = _guide_gid(gid)
        guide.set_gid(guide_gid)
        artists_by_sample_dict.setdefault(sid, []).append(guide)

        lbl = ax.text(text_data_x, text_data_y, it["text"],
                      fontsize=FONTSIZE_PEAK, ha="center", va="bottom",
                      color=trace_color, zorder=4)
        lbl.set_gid(gid)
        reg.register(lbl, gid, params=["peak_font_pt", "label_lift_mm", "label_min_gap_mm", "label_max_dx_mm", "pitch_mm", "group_y_mm"])
        reg.register(guide, guide_gid, params=["label_lift_mm", "label_max_dx_mm", "pitch_mm", "group_y_mm"])
        _LAYOUT_GIDS.add(guide_gid)
        artists_by_sample_dict.setdefault(sid, []).append(lbl)

    return final_placed, remaining_unplaced


def _detect_peak(science: dict, sample_idx: int, approx_ppm: float, win_search: float):
    """在定标后的真实谱线上找诊断峰极大值 → (exact_ppm, peak_y)。

    标注文字与引线所指都来自这里；`science_manifest` 也用它声明锚点，
    保证「引线指的」与「声明的」是同一个数。
    """
    rel = SAMPLES_CONFIG[sample_idx][0]
    ppm, spec, _, _ = science[rel]
    win = np.where(np.abs(ppm - approx_ppm) <= win_search)[0]
    j = win[np.argmax(spec[win])] if len(win) else np.argmin(np.abs(ppm - approx_ppm))
    return float(ppm[j]), float(min(spec[j], PEAK_MAX_NORM * 1.15))


def _build(science: dict, scope_target: str):
    """按 scope 建图。**legacy 与 native 共用这一份构建路径**（不存在第二套约定）。"""
    global PLACED_RECORDS, UNPLACED_GIDS
    if scope_target not in SCOPES:
        raise ValueError(f"未知 scope：{scope_target}")
    fig, ax = _draw_spectra(science)
    labels_by_sample = {}
    for approx_ppm, sample_idx, group_name, _, _, auto_ppm, win_search in PEAK_LABELS_TEMPLATE:
        exact_ppm, peak_y = _detect_peak(science, sample_idx, approx_ppm, win_search)
        text = f"{group_name} {exact_ppm:.2f}" if (auto_ppm and SHOW_PPM) else group_name
        sid = SAMPLES_CONFIG[sample_idx][7]
        labels_by_sample.setdefault(sample_idx, []).append(
            (exact_ppm, text, peak_y, _gid("peak", sid, _gid_tag(approx_ppm))))
    PLACED_RECORDS, UNPLACED_GIDS = place_peak_labels(
        ax, labels_by_sample, lanes=LABEL_LANES, min_gap_mm=LABEL_MIN_GAP_MM,
        max_dx_mm=LABEL_MAX_DX_MM, shifts_mm=_requested_peak_shifts(PEAK_LABEL_SHIFTS),
        artists_by_sample_dict=artists_by_sample,
    )
    ax.set_xlabel(r"Chemical Shift $\delta$ (ppm)", fontsize=FONTSIZE_AXIS,
                  labelpad=3.5, weight="bold")
    ax.set_ylabel("Normalized Intensity (a.u.)", fontsize=FONTSIZE_AXIS,
                  labelpad=3.5, weight="bold")
    ax.tick_params(length=2.5, width=0.6, labelsize=FONTSIZE_TICK, pad=2)
    for label, name in ((ax.xaxis.label, "xlabel"), (ax.yaxis.label, "ylabel")):
        gid = _gid(name)
        label.set_gid(gid)
        reg.register(label, gid, params=["axis_font_pt"])
    fs.strip_yticks(ax)
    baselines = [reg.get(_gid("baseline", sid)) for sid in SAMPLE_IDS]
    if ARGS.migrate_config:
        _CFG["pitch_mm"]["main"] = {SAMPLE_IDS[i]: measure_relation("baseline_pitch", baselines[i-1], baselines[i])
                                    for i in range(1, len(baselines))}
    for i in range(1, len(baselines)):
        move = [art for sid in SAMPLE_IDS[i:] for art in artists_by_sample[sid]]
        set_relation_target(kind="baseline_pitch", object_a=baselines[i-1], object_b=baselines[i],
                            target_mm=_CFG["pitch_mm"]["main"][SAMPLE_IDS[i]], move=move)
    for sid, group in artists_by_sample.items():
        for artist in group:
            apply_display_shift(artist, SHIFTS_MM[SCOPE][sid])
    group = [art for arts in artists_by_sample.values() for art in arts]
    for art in group:
        apply_display_shift(art, _CFG["group_y_mm"]["main"])
    fig._figpact_relations = [
        {"scope": "main", "kind": "baseline_pitch", "upper": SAMPLE_IDS[i],
         "value_mm": measure_relation("baseline_pitch", baselines[i-1], baselines[i])}
        for i in range(1, len(baselines))]
    fig._figpact_space = [dict(scope="main", **v) for v in remaining_space(fig, group)]
    return fig, reg


def build_figure_and_registry(scope_target="main"):
    """legacy 入口：用模块基线配置建图（CLI / GUI / 清点继续走这里）。"""
    _apply_config(CONFIG)
    prepare_data()
    return _build(load_science(), scope_target)


def build_scene(science: dict, config: dict, scope: str):
    """native 入口：候选配置 + 已缓存科研载荷 → (Figure, GidRegistry)。

    候选配置先过 `prepare_config`（与 legacy 同一份标准化：缺 shifts_mm 补 0、
    标注短名补全 gid），全部排版全局量再由 `_apply_config` 一次装好，因此同一
    (science, config, scope) 永远得到同一张图；纯布局试算不重读 Bruker 数据、
    不重跑定标。**传入的 config 不被修改**。
    """
    _apply_config(prepare_config(config))
    return _build(science, scope)


# ──────────────────────────────────────────────────────────────────────────────
# native 契约：给 agent / runtime 的显式声明（不改 legacy CLI 行为）
# ──────────────────────────────────────────────────────────────────────────────
#: 本图只出一张叠谱（SI 单谱在 NMR_generate_all.py 里），所以只有一个输出作用域。
_OUTPUT_BASE = "Fig2_NMR_pure_stacked"
_EXPORT_FORMATS = ("png", "pdf", "svg", "tiff")
#: 每个峰标注模板项在本样品上的 gid tag（标注与引线共用同一段）。
_PEAK_TAGS = {sid: tuple(_gid_tag(p) for p, i, *_ in PEAK_LABELS_TEMPLATE
                         if SAMPLES_CONFIG[i][7] == sid)
              for sid in SAMPLE_IDS}
#: 基线场景缓存：契约的节点/角色取自**真正建出来的一张图**，不另抄一份 gid 清单。
_BASELINE_SCENES: dict[str, tuple] = {}


def _baseline_scene(scope: str):
    """该 scope 的基线 (Figure, GidRegistry)，按 scope 缓存、只建一次。"""
    if scope not in _BASELINE_SCENES:
        _apply_config(CONFIG)
        _BASELINE_SCENES[scope] = _build(load_science(), scope)
    return _BASELINE_SCENES[scope]


def _science_policy(gid: str) -> str:
    """基线虚线与峰标注引线是**纯布局几何**；谱线、标注文字、轴文字、图例受保护。

    由构建路径自己登记（`_LAYOUT_GIDS`），`layout_contract` 与 `science_manifest` 共用。
    """
    return "LAYOUT" if gid in _LAYOUT_GIDS else "LOCKED_SCIENCE"


def _sample_gids(registered: dict, sid: str) -> list[str]:
    """一个样品层的全部图元（谱线 + 基线 + 截顶标记 + 标注 + 引线），按注册表过滤。"""
    gids = [_gid(kind, sid) for kind in ("curve", "baseline", "break")]
    gids += [_gid(kind, sid, tag) for tag in _PEAK_TAGS[sid] for kind in ("peak", "guide")]
    return [g for g in gids if g in registered]


def _panel_id(ax, index: int) -> str:
    """panel 身份：builder 设的 Axes gid；没有时才退回引擎的位置编号约定。"""
    return ax.get_gid() or f"panel.{index}"


def _scene_roles(fig, reg) -> tuple[dict[str, list[str]], dict[int, str]]:
    """按语义角色分组注册图元，并给出「图元 → 所属 panel」的映射（按 artist 身份判定）。"""
    roles = {"curves": [], "baselines": [], "guides": [], "peaks": [], "breaks": [],
             "legends": [], "legend_texts": [], "axis_texts": []}
    owner: dict[int, str] = {}
    role: dict[int, str] = {}
    for i, ax in enumerate(fig.axes):
        pid = _panel_id(ax, i)
        for txt in (ax.xaxis.label, ax.yaxis.label):
            owner[id(txt)] = pid
        legend = ax.get_legend()
        if legend is not None:
            owner[id(legend)] = pid
            for txt in legend.get_texts():
                owner[id(txt)] = pid
                role[id(txt)] = "legend_texts"
    for gid, art in reg.all().items():
        kind = type(art).__name__
        params = set(reg.params_of(gid))
        if kind == "Legend":
            roles["legends"].append(gid)
        elif kind == "Text":
            if id(art) in owner:
                roles[role.get(id(art), "axis_texts")].append(gid)
            elif "note_font_pt" in params:
                roles["breaks"].append(gid)
            else:
                roles["peaks"].append(gid)
        elif kind == "Line2D":
            if gid in _LAYOUT_GIDS:
                roles["baselines" if art.get_linestyle() == "--" else "guides"].append(gid)
            else:
                roles["curves"].append(gid)
    return roles, owner


def _decl_param(scope, key, path, unit, mutability, objects, *, operation=None, axis=None,
                bounds=None, expected=None, type=None) -> dict:
    """契约参数记录。`bounds` = (min, max)，取自 SCALARS / 关系上限，不另抄一份数字。

    `type` 只给**非标量**的值形用（`"[dx,dy]"`）：`figpact.patch` 按它决定值是不是
    「两个数字的列表」，并逐分量套同一对 min/max。标量参数不写（缺省 float）。
    """
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
    if type is not None:
        rec["type"] = type
    return rec


def _editable(params: list, scope, key, path, unit, objects, **kw) -> None:
    """只登记**在该 scope 真的有受影响图元**的可编辑参数；否则不声明（= 不支持）。"""
    if objects:
        params.append(_decl_param(scope, key, path, unit, "EDITABLE", objects, **kw))


def layout_contract(scope: str) -> dict:
    """该 scope 的显式布局契约：精确 YAML 路径、语义节点/分组、受影响集合、产物名。

    节点 / 角色 / 所属 panel 取自基线场景（`_baseline_scene`）；逐样品的毫米操作声明为
    **实际会动的那些图元**（整层或上方所有层），不声明不存在的 gid。逐标注微调同样按
    「真的画出来的标注」声明：路径第三段是 `peak.<sid>.<tag>` 整串一段，值形是 `[dx, dy]`。
    """
    if scope not in SCOPES:
        raise ValueError(f"未知作用域 {scope!r}；可用：{list(SCOPES)}")
    fig, reg = _baseline_scene(scope)
    registered = reg.all()
    gids = sorted(registered)
    roles, owner = _scene_roles(fig, reg)
    panel_of = {}
    for gid, art in registered.items():
        if id(art) in owner:
            panel_of[gid] = owner[id(art)]
        else:
            ax = getattr(art, "axes", None)
            panel_of[gid] = (_panel_id(ax, fig.axes.index(ax)) if ax in fig.axes else "figure")

    params: list[dict] = []
    for key in ("canvas_w_mm", "canvas_h_mm"):
        _editable(params, scope, key, [key], "mm", gids, operation="resize",
                  bounds=SCALARS[key][1:], expected={"kind": "resize", "objects": gids})
    legend_objects = roles["legends"] + roles["legend_texts"]
    for key, unit in (("legend_font_pt", "pt"), ("legend_cols", "col"),
                      ("legend_anchor_x", "ratio")):
        _editable(params, scope, key, [key], unit, legend_objects, operation="rebuild",
                  bounds=SCALARS[key][1:], expected={"kind": "style", "objects": legend_objects})
    for key, unit, objects in (("axis_font_pt", "pt", roles["axis_texts"]),
                               ("line_width", "pt", roles["curves"]),
                               ("peak_font_pt", "pt", roles["peaks"]),
                               ("note_font_pt", "pt", roles["breaks"]),
                               ("label_lift_mm", "mm", roles["peaks"] + roles["guides"]),
                               ("label_min_gap_mm", "mm", roles["peaks"] + roles["guides"]),
                               ("label_max_dx_mm", "mm", roles["peaks"] + roles["guides"]),
                               ("label_lanes", "lane", roles["peaks"] + roles["guides"])):
        _editable(params, scope, key, [key], unit, objects, operation="rebuild",
                  bounds=SCALARS[key][1:], expected={"kind": "style", "objects": objects})
    # `show_ppm` 改的是**画出来的化学位移文字**（受保护科学内容），不是排版旋钮：
    # 声明成 LOCKED_SCIENCE，免得它被当成可以随手开关的样式项。
    params.append(_decl_param(scope, "show_ppm", ["show_ppm"], "bool", "LOCKED_SCIENCE", []))
    # 逐样品的毫米操作：受影响集合是**实际会动的那些图元**。
    relations: list[dict] = []
    for i in range(1, len(SAMPLE_IDS)):
        sid = SAMPLE_IDS[i]
        moved = [g for s in SAMPLE_IDS[i:] for g in _sample_gids(registered, s)]
        _editable(params, scope, f"pitch_mm.{scope}.{sid}", ["pitch_mm", scope, sid], "mm",
                  moved, operation="translate", axis="y", bounds=(0.0, 100.0),
                  expected={"kind": "translate", "objects": moved, "axis": "y",
                            "preserve": [f"{scope}.pitch.{SAMPLE_IDS[k]}"
                                         for k in range(1, i)]})
        relations.append({
            "id": f"{scope}.pitch.{sid}",
            "kind": "gap",
            "objects": [_gid("baseline", SAMPLE_IDS[i - 1]), _gid("baseline", sid)],
            "axis": "y",
            "method": "baseline",
            "controlled_by": [["pitch_mm", scope, sid]],
            "move": moved,
        })
    all_layers = [g for s in SAMPLE_IDS for g in _sample_gids(registered, s)]
    _editable(params, scope, f"group_y_mm.{scope}", ["group_y_mm", scope], "mm", all_layers,
              operation="translate", axis="y", bounds=(-100.0, 100.0),
              expected={"kind": "translate", "objects": all_layers, "axis": "y",
                        "preserve": [r["id"] for r in relations]})
    for sid in SAMPLE_IDS:
        own = _sample_gids(registered, sid)
        _editable(params, scope, f"shifts_mm.{scope}.{sid}", ["shifts_mm", scope, sid], "mm",
                  own, operation="translate", axis="y",
                  bounds=(-SHIFT_LIMIT_MM, SHIFT_LIMIT_MM),
                  expected={"kind": "translate", "objects": own, "axis": "y"})
    # 逐标注微调是 [dx, dy] **两轴**毫米偏移并重画引线——不是单轴纯平移，故走 rebuild。
    # 声明的是**真的画出来的**那些标注（角色取自真实建出来的图）：没画出来的峰、图上没有的
    # 名字都不声明 = 不可编辑。路径第三段是 `peak.<sid>.<tag>` 这**一整串**（末段不带点、
    # 也绝不按点拆开）——它同时是规范化配置里的键、`nmr.yaml` 里的键、GUI 目录里的键。
    # 每个都带 `[0.0, 0.0]` 的零基线（`prepare_config` 补的），所以 YAML 写 `{}` 时也能设。
    prefix = f"{FIGURE_ID}.{scope}."
    for gid in sorted(roles["peaks"]):
        label = gid.removeprefix(prefix)
        objects = [g for g in (gid, _guide_gid(gid)) if g in registered]
        _editable(params, scope, f"peak_label_shifts_mm.{scope}.{label}",
                  ["peak_label_shifts_mm", scope, label], "mm", objects, operation="rebuild",
                  type="[dx,dy]", bounds=(-SHIFT_LIMIT_MM, SHIFT_LIMIT_MM),
                  expected={"kind": "style", "objects": objects})
    # 只读重建字段：声明出来是为了它们**不被当成可编辑**（缺声明 = UNCLASSIFIED 失败关闭）。
    params.append(_decl_param(scope, "schema_version", ["schema_version"], "int", "FIXED_STYLE", []))
    params.append(_decl_param(scope, f"layout_reference.{scope}", ["layout_reference", scope],
                              "record", "DERIVED", []))

    editable = {gid for p in params if p["mutability"] == "EDITABLE" for gid in p["objects"]}
    nodes = {gid: {"type": type(registered[gid]).__name__, "parent": panel_of[gid],
                   "editable": gid in editable, "science_policy": _science_policy(gid)}
             for gid in gids}
    root = f"{FIGURE_ID}.{scope}"
    groups = [{"id": root, "parent": None, "members": gids}]
    panel_ids = sorted(set(panel_of.values()))
    for pid in panel_ids:
        groups.append({"id": pid, "parent": root,
                       "members": sorted(g for g in gids if panel_of[g] == pid)})
    parent_panel = panel_ids[0] if panel_ids else root
    for sid in SAMPLE_IDS:
        members = _sample_gids(registered, sid)
        if members:
            groups.append({"id": f"{FIGURE_ID}.{scope}.group.{sid}", "parent": parent_panel,
                           "members": members})
    for name, members in (("curves", roles["curves"]), ("peaks", roles["peaks"])):
        if members:
            groups.append({"id": f"{FIGURE_ID}.{scope}.group.{name}", "parent": parent_panel,
                           "members": sorted(members)})
    return {"parameters": params, "nodes": nodes, "groups": groups, "relations": relations,
            "outputs": [f"{_OUTPUT_BASE}.{ext}" for ext in _EXPORT_FORMATS]}


def science_manifest(science: dict) -> dict:
    """JSONable 的科研来源 / 定标 / 受保护锚点声明（native runtime 与 capture_science 用）。

    `nodes` 只列**点名豁免**的装饰几何：基线虚线与峰标注引线，两者都声明
    `{"science_policy": "LAYOUT", "type": "guide"}`——引擎对原始 Line2D 的 x/y 一律保护，
    只有显式 `type: "guide"` 的装饰线才不进科学指纹。其余默认 LOCKED_SCIENCE
    （谱线、标注文字、轴文字、图例、图像像素永不豁免），与 `_science_policy` 一致。
    峰锚点用与绘图同一个 `_detect_peak`，保证「引线指的」就是「声明的」。
    """
    _apply_config(CONFIG)
    _baseline_scene(SCOPE)          # 纯布局图元的判定来自真实建出来的图
    anchors = {}
    for approx_ppm, sample_idx, group_name, _, _, _, win_search in PEAK_LABELS_TEMPLATE:
        sid = SAMPLES_CONFIG[sample_idx][7]
        ppm, peak_y = _detect_peak(science, sample_idx, approx_ppm, win_search)
        anchors[_gid("peak", sid, _gid_tag(approx_ppm))] = {
            "assignment": group_name, "exact_ppm": ppm,
            "guide_anchor_data": [ppm, peak_y],
            "guide_gid": _gid("guide", sid, _gid_tag(approx_ppm)),
        }
    return {
        "nodes": {gid: {"science_policy": "LAYOUT", "type": "guide"}
                  for gid in sorted(_LAYOUT_GIDS)},
        "layout_viewports": {
            _gid("panel"): {"axis": "y",
                            "origin": CONFIG["layout_reference"]["main"]["axis_bottom_data"],
                            "units_per_mm": CONFIG["layout_reference"]["main"]["units_per_mm"]},
        },
        "science": {
            "figure_id": FIGURE_ID,
            "source": {
                "format": "Bruker pdata (1D 1H)",
                "files": science_inputs(),
                "samples": [{"id": sid, "dir": rel, "solvent": solv}
                            for rel, _, _, solv, *_ in SAMPLES_CONFIG],
            },
            "processing": [
                "narrow-window solvent referencing (CDCl3 7.26±0.03 / DMSO-d6 2.50±0.03 / D2O 4.79±0.05 ppm)",
                "solute peak normalized to 22 a.u. outside the solvent window",
                "solvent peak clipped at 26 a.u. and marked //",
            ],
            "scale_bars": [],
            "protected": {
                "display_window_ppm": [PPM_LEFT, PPM_RIGHT],
                "peak_scale_a.u.": {"solute_max": PEAK_MAX_NORM, "solvent_clip": PEAK_MAX_NORM * 1.18},
                "solvent_references": [{"sample": SAMPLES_CONFIG[i][7], "ref_ppm": ref,
                                        "search_ppm": search, "window_ppm": win}
                                       for i, (_, _, _, _, ref, search, win, _)
                                       in enumerate(SAMPLES_CONFIG)],
                "peak_anchors": anchors,
            },
        },
    }


def make_figure():
    fig, reg = build_figure_and_registry()
    if ARGS.migrate_config:
        output = pathlib.Path(ARGS.migrate_config).resolve()
        if output == CONFIG_PATH.resolve():
            raise ValueError("迁移输出必须是新文件")
        source = dict(CONFIG)
        source["peak_label_shifts_mm"] = {
            SCOPE: {label: list(pair) for label, pair in
                    _requested_peak_shifts(CONFIG["peak_label_shifts_mm"][SCOPE]).items()}}
        output.write_text(yaml.safe_dump(source, allow_unicode=True, sort_keys=False), encoding="utf8")
        plt.close(fig)
        print(f"已迁移到 {output}；正式图未改动")
        return
    if ARGS.inventory:
        print(json.dumps(fp_inventory(fig, reg, check_effect=ARGS.check_effect), ensure_ascii=False, indent=2))
        plt.close(fig)
        return
    if ARGS.inspect:
        art = reg.get(ARGS.inspect)
        print(f"[{ARGS.inspect}] {type(art).__name__} | 绑定参数: {reg.params_of(ARGS.inspect)}"
              if art is not None else f"未找到 gid: {ARGS.inspect}")
        plt.close(fig)
        return
    STAGING = pathlib.Path(tempfile.mkdtemp(prefix="nmr-stage-"))
    fs.export(fig, STAGING / "Fig2_NMR_pure_stacked", dpi=DPI)
    fs.qa_report(fig, "NMR 叠谱")
    report_shift_bounds(fig, "NMR 叠谱")
    blockers = blocking_problems(fig)
    exemptions_mgr = fp_publish.Exemptions(EXEMPT_PATH)
    if ARGS.exempt_current:
        exemptions_mgr.write(blockers, ARGS.reason)
        print(f"[豁免] 写入 {len(blockers)} 条 → {EXEMPT_PATH.name}；理由：{ARGS.reason.strip()}")
    exempt = exemptions_mgr.load()
    exempted = [(b, exempt[fp_qa.diagnostic_key_of(b)]) for b in blockers
                if fp_qa.diagnostic_key_of(b) in exempt]
    new = [b for b in blockers if fp_qa.diagnostic_key_of(b) not in exempt]
    if blockers:
        print(f"[验收] 阻断 {len(blockers)} 条，其中 {len(exempted)} 条人工豁免：")
        for blocker, reason in exempted:
            print(f"      [豁免] {blocker}\n             理由：{reason}")
        for blocker in new:
            print(f"      [未豁免] {blocker}")
    if new and STRICT:
        print(f"[验收] **未豁免**阻断项 {len(new)} 条：**拒绝发布**，{ROOT.name} 里的正式输出未被覆盖")
        shutil.rmtree(STAGING, ignore_errors=True)
        plt.close(fig)
        raise SystemExit(1)
    if not blockers:
        print("[验收] 无阻断项 ✓")
    elif not new:
        print(f"[验收] 无**未豁免**阻断项；但有 {len(exempted)} 条人工豁免——不等于图已经干净")
    written = fp_publish.publish(STAGING, OUT_DIR)
    shutil.rmtree(STAGING, ignore_errors=True)
    plt.close(fig)
    print(f"已写出 {len(written)} 个文件到{'试算沙箱' if PROBE_DIR else '正式输出'} {OUT_DIR}")


if __name__ == "__main__":
    make_figure()
