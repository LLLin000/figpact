#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fig.2 XRD —— 五样品叠谱（Rigaku SmartLab .txt 导出，2theta/cps）。

科学路径与原始脚本 `fig2/10 XRD/plot_xrd.py` 同一条管线（函数逐段移植，
数值常量逐字锁定）：读 Rigaku 文本 → 网格 QA（validate）→ ALS 基线扣除 →
Savitzky-Golay 平滑 → 截零 → 10–80° 窗内逐谱归一 → 等距叠放。主图只标 ZnO
参考谱的五个晶面 (100)/(101)/(102)/(110)/(103)（源 ZNO_HKL_LABELS，位置
[31.77, 36.25, 47.54, 56.60, 62.86]，稳定 id .100/.101/.102/.110/.103）。
峰位窗口、显示窗、处理常数全部锁死，不进 YAML。

Native 契约（与 FTIR/NMR 同一套接缝，不新造机制）：
`FIGURE_ID / SCOPES / load_science / build_scene / build_figure_and_registry /
layout_contract / science_manifest / science_inputs / prepare_config /
load_config_xrd`。导入本模块：不解析 argv、不建 Figure、不渲染、不写文件、
不读 YAML、不引入随机/时间。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import math
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents
                             if (p / "figpact").is_dir())))
import figure_style as fs
from figpact import GidRegistry
from figpact.config import ConfigError, load_config

ROOT = Path(__file__).parent

#: 对象身份前缀。**不是配置项**：gid 是外部引用认的名字。
FIGURE_ID = "fig2_xrd"
#: 本图只出处理后主图一张（原始审计图是原始脚本的 QC 产物，不进 Native 作用域）。
SCOPE = "main"
SCOPES = (SCOPE,)

#: 五样品顺序与 FTIR 伴随工作流一致（源 SAMPLES，色值取统一色表同 token）。
SAMPLES = [
    (1, "HA", "HA"),
    (2, "ZnO", "ZnO"),
    (3, "HAMA", "MOD_HA"),
    (4, r"HAMA/Cu$^{2+}$/ZnO", "COMPOSITE_MICROSPHERE"),
    (5, r"HA + HAMA/Cu$^{2+}$/ZnO", "COMPOSITE_GEL"),
]
CURVE_IDS = tuple(str(n) for n, _, _ in SAMPLES)

#: ZnO 六方纤锌矿主峰（源 ZNO_HKL / ZNO_HKL_LABELS，逐字锁定；绝不增删改）。
ZNO_HKL = [31.77, 36.25, 47.54, 56.60, 62.86]
ZNO_HKL_LABELS = ["(100)", "(101)", "(102)", "(110)", "(103)"]
#: (hkl) 文字的稳定 id 段：小数点不能进 gid（按点切分的读取方会切错）。
HKL_TAGS = ["100", "101", "102", "110", "103"]

#: 科学常量（源逐字锁定；改任一值 = 改科学，不是排版）。
DISPLAY_X_MIN = 10.0
DISPLAY_X_MAX = 80.0
BASELINE_LAMBDA = 2.0e7
BASELINE_ASYMMETRY = 0.01
BASELINE_ITERATIONS = 15
SMOOTHING_WINDOW = 7
SMOOTHING_POLYORDER = 2
WAVELENGTH_A = 1.540593
#: 叠放等距（源 draw_stacked：processed + show_hkl 分支）。
OFFSET_STEP = 2.40
#: ZnO 参考谱在 SAMPLES 中的下标（源 annotate_zno_on_curve：HA, ZnO, ...）。
ZNO_INDEX = 1
#: 峰顶搜索半窗（源 ±0.7°）。
PEAK_HALF_WINDOW_DEG = 0.7

FONT_RANGE = (3.0, 12.0)

#: key → (类型, 下界, 上界)。只有安全排版旋钮：画布、轴/刻度字号、线宽、
#: 图例、hkl 标注字号与标注抬升。科学量（窗口/基线/平滑/归一/叠距/峰位）无一在内。
SCALARS = {
    "schema_version": (int, 2, 2),
    "canvas_w_mm": (float, 20.0, 200.0),
    "canvas_h_mm": (float, 20.0, 200.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "legend_font_pt": (float, *FONT_RANGE),
    "hkl_font_pt": (float, *FONT_RANGE),
    "hkl_lift_mm": (float, 0.0, 10.0),
    "line_width": (float, 0.2, 3.0),
    "legend_cols": (int, 1, 3),
    "legend_anchor_x": (float, 0.0, 1.0),
}

SCHEMA = {**SCALARS, "data_dir": (str,), "offsets_mm": (dict,),
          "group_y_mm": (dict,), "layout_reference": (dict,)}

#: 单条曲线的显示位移上限（mm）。再大就不是排版微调，是画错了。
SHIFT_LIMIT_MM = 10.0

#: 基线 data_dir：便携 YAML 默认必须为空/缺席 → load_science 明确报错，
#: 不猜路径、不回退、不读 repo 内数据。临时 config 由调用方显式指向真实外部路径。
DATA_DIR_DEFAULT = ""


def _cli(argv: list[str]) -> argparse.Namespace:
    """命令行严格解析（只在 __main__ 时解析，不碰 native runtime 的 argv）。"""
    ap = argparse.ArgumentParser(
        prog=Path(__file__).name, add_help=True, allow_abbrev=False,
        description="Fig.2 XRD 面板 Native 提供者；排版参数在 xrd.yaml")
    ap.add_argument("--config", default=None,
                    help="配置文件路径（默认：脚本旁边的 xrd.yaml）")
    ap.add_argument("--list-params", action="store_true",
                    help="打印全部参数（当前值 / 允许范围）与所有可位移 gid，然后退出")
    ap.add_argument("--inventory", action="store_true",
                    help="打印当前图表可见图元清单 (JSON 格式)，供 figpact inventory 消费")
    ap.add_argument("--inspect", default=None, help="检查指定 gid 的图元信息")
    # 兼容旧调用：native runtime 隔离导入时 argv 带 --inventory；其余保留参数防误拒。
    ap.add_argument("--strict", action="store_true", help="兼容旧调用：本提供者无阻断门")
    ap.add_argument("--probe", default=None, help="兼容旧调用：本提供者不写正式产物")
    ap.add_argument("--reason", default="", help="兼容旧调用：保留参数")
    ap.add_argument("--exempt-current", action="store_true", help="兼容旧调用：保留参数")
    ap.add_argument("--migrate-config", default=None, help="兼容旧调用：保留参数")
    ap.add_argument("--check-effect", action="store_true", help="兼容旧调用：保留参数")
    return ap.parse_args(argv)


ARGS = _cli(sys.argv[1:]) if __name__ == "__main__" else _cli([])
CONFIG_PATH = Path(ARGS.config).expanduser() if ARGS.config else ROOT / "xrd.yaml"

def prepare_config(config: dict, *, label: str | None = None) -> dict:
    """映射标准化（纯变换：不读 YAML、不碰数据、不画图，不修改输入）。

    作用域或曲线一律补 0.0（「不写 = 不动」）。`data_dir` 原样保留（字符串，
    可缺席——缺席只在 load_science 时报错，不在这里报错，以便离线检查契约；
    显式给出的非空 data_dir 会记在 `_EXPLICIT_DATA_DIR`（无参 loader 接缝的桥接））。
    """
    global _EXPLICIT_DATA_DIR
    name = label or CONFIG_PATH.name
    cfg = dict(config)
    raw_dir = cfg.get("data_dir", "")
    if isinstance(raw_dir, str) and raw_dir.strip():
        _EXPLICIT_DATA_DIR = raw_dir
    raw_shifts = cfg.get("offsets_mm") or {}
    if not isinstance(raw_shifts, dict):
        raise ConfigError(f"{name}：offsets_mm 必须是字典映射")
    if unknown := sorted(set(raw_shifts) - set(SCOPES)):
        raise ConfigError(f"{name}：offsets_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")
    normalized = {scope: {sid: 0.0 for sid in CURVE_IDS} for scope in SCOPES}
    for scope, per_curve in raw_shifts.items():
        if per_curve is None:
            continue
        if not isinstance(per_curve, dict):
            raise ConfigError(f"{name}：offsets_mm.{scope} 必须是 `曲线id: 毫米` 映射")
        if unknown := sorted(set(per_curve) - set(CURVE_IDS)):
            raise ConfigError(f"{name}：offsets_mm.{scope} 里有未知曲线 {unknown}；可用：{list(CURVE_IDS)}")
        for sid, value in per_curve.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name}：offsets_mm.{scope}.{sid} 必须是数字")
            val_f = float(value)
            if not math.isfinite(val_f):
                raise ConfigError(f"{name}：offsets_mm.{scope}.{sid} 不能是 NaN 或 Inf")
            if abs(val_f) > SHIFT_LIMIT_MM:
                sug = min(max(val_f, -SHIFT_LIMIT_MM), SHIFT_LIMIT_MM)
                raise ConfigError(
                    f"{name}：offsets_mm.{scope}.{sid} = {val_f} 超出 ±{SHIFT_LIMIT_MM} mm；"
                    f"建议改成 {sug}")
            normalized[scope][sid] = val_f
    cfg["offsets_mm"] = normalized
    if "group_y_mm" not in cfg or cfg["group_y_mm"] is None:
        cfg["group_y_mm"] = {s: 0.0 for s in SCOPES}
    return cfg


def load_config_xrd(path: Path) -> dict:
    """读 YAML（含 schema 校验）→ `prepare_config` 标准化位移映射。"""
    cfg = load_config(path, SCHEMA)
    return prepare_config(cfg, label=path.name)


try:
    CONFIG = load_config_xrd(CONFIG_PATH)
except Exception:
    #: 便携默认（data_dir 缺席）下导入仍成功：报错只发生在 load_science。
    #: 此处给一份内存基线，保证模块级 _apply_config / layout_contract 可用。
    CONFIG = prepare_config({"data_dir": DATA_DIR_DEFAULT,
                             "schema_version": 2, "canvas_w_mm": 41.0,
                             "canvas_h_mm": 46.13444575910199, "axis_font_pt": 8.5,
                             "tick_font_pt": 8.0, "legend_font_pt": 6.0,
                             "hkl_font_pt": 6.0, "hkl_lift_mm": 0.5,
                             "line_width": 0.82, "legend_cols": 2,
                             "legend_anchor_x": 0.98, "offsets_mm": {},
                             "group_y_mm": {s: 0.0 for s in SCOPES},
                             "layout_reference": {s: {} for s in SCOPES}})


def list_params() -> None:
    """人类与模型调参专用的结构化清单。"""
    print(f"配置：{CONFIG_PATH.name}（改这张图只改这里，不要改 plot_xrd.py）")
    for key, spec in SCALARS.items():
        print(f"  {key}: 当前 {CONFIG.get(key)!r}，范围 [{spec[1]}, {spec[2]}]")
    print(f"  data_dir: 当前 {CONFIG.get('data_dir')!r}（LOCKED_SCIENCE 输入，非排版）")
    print("  可位移曲线 gid（offsets_mm.main.<id>，mm，正值向上）：")
    for sid in CURVE_IDS:
        print(f"    {FIGURE_ID}.main.curve.{sid}")


#: 本次构图的工作副本（legacy = xrd.yaml；native = build_scene 收到的候选配置）。
_CFG: dict = {}
#: `prepare_config` 最近见过的显式 data_dir（无参 loader 接缝的唯一桥接；见
#: `_resolve_data_dir`）。它是"调用方这次给了什么"，不是默认值——空即缺席。
_EXPLICIT_DATA_DIR: str = ""
#: 受保护的科研载荷缓存（load_science 只算一次；warm 布局不再读 .txt）。
_SCIENCE: dict | None = None
#: 缓存命中的数据指纹（目录变更即失效，不复用旧载荷）。
_SCIENCE_KEY: str | None = None


def _apply_config(cfg: dict) -> None:
    """布局全局量的唯一初始化路径（legacy 与 native 都只走这里）。"""
    global _CFG, XRD_CANVAS, AXIS_FS, TICK_FS, LEGEND_FS, HKL_FS, HKL_LIFT_MM
    global LINE_WIDTH, LEGEND_COLS, LEGEND_ANCHOR_X, SHIFTS_MM
    fs.apply()
    _CFG = copy.deepcopy(cfg)
    XRD_CANVAS = (float(_CFG["canvas_w_mm"]), float(_CFG["canvas_h_mm"]))
    AXIS_FS = float(_CFG["axis_font_pt"])
    TICK_FS = float(_CFG["tick_font_pt"])
    LEGEND_FS = float(_CFG["legend_font_pt"])
    HKL_FS = float(_CFG["hkl_font_pt"])
    HKL_LIFT_MM = float(_CFG["hkl_lift_mm"])
    LINE_WIDTH = float(_CFG["line_width"])
    LEGEND_COLS = int(_CFG["legend_cols"])
    LEGEND_ANCHOR_X = float(_CFG["legend_anchor_x"])
    SHIFTS_MM = _CFG["offsets_mm"]


_apply_config(CONFIG)


def _resolve_data_dir() -> Path:
    """解析外部 Rigaku .txt 目录（LOCKED_SCIENCE 输入，非排版）。

    决议顺序：当前 `_CFG` 的 data_dir → `prepare_config` 最近见过的显式
    data_dir（native 会话总是在 load_science 之前 prepare 真实 config，
    而 loader 接缝是无参的，这是唯一的桥接）→ 明确报错。便携默认（两处皆空）
    直接报 ConfigError，不猜路径、不回退、不读 repo 内数据。
    """
    raw = _CFG.get("data_dir", "")
    if (not isinstance(raw, str) or not raw.strip()) and _EXPLICIT_DATA_DIR:
        raw = _EXPLICIT_DATA_DIR
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(
            f"{CONFIG_PATH.name}：data_dir 未设置——便携默认不带数据；"
            "请在临时 config 里把 data_dir 指向真实外部 Rigaku .txt 目录（1.txt..5.txt）")
    resolved = Path(raw).expanduser()
    if not resolved.is_dir():
        raise ConfigError(f"data_dir 不是可用目录：{resolved}")
    missing = [f"{n}.txt" for n, _, _ in SAMPLES if not (resolved / f"{n}.txt").is_file()]
    if missing:
        raise ConfigError(f"data_dir 缺少输入文件 {missing}：{resolved}")
    return resolved


def _hkl_gid(tag: str) -> str:
    """hkl 标注的稳定 id（`fig2_xrd.main.hkl.100` …），只此一处构造。"""
    return f"{FIGURE_ID}.{SCOPE}.hkl.{tag}"


def _curve_gid(number: int) -> str:
    return f"{FIGURE_ID}.{SCOPE}.curve.{number}"


def _panel_gid() -> str:
    return f"{FIGURE_ID}.{SCOPE}.panel"


# ──────────────────────────────────────────────────────────────────────────────
# 科学管线（源 plot_xrd.py 逐段移植；数值/常量逐字锁定）
# ──────────────────────────────────────────────────────────────────────────────
def read_rigaku_txt(path: Path) -> tuple[dict[str, str], np.ndarray, np.ndarray]:
    """Read a SmartLab text export after its ``#Intensity_unit`` marker."""
    metadata: dict[str, str] = {}
    rows: list[tuple[float, float]] = []
    in_data = False
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("#Intensity_unit="):
            metadata["intensity_unit"] = line.split("=", 1)[1].strip()
            in_data = True
            continue
        if not in_data:
            for key in (
                "*MEAS_SCAN_START",
                "*MEAS_SCAN_STOP",
                "*MEAS_SCAN_STEP",
                "*MEAS_SCAN_UNIT_X",
                "*MEAS_SCAN_UNIT_Y",
                "*MEAS_SCAN_SPEED",
                "*MEAS_SCAN_SPEED_UNIT",
                "*MEAS_SCAN_MODE",
                "*MEAS_XG_WAVE_TYPE",
                "*HW_XG_WAVE_LENGTH_ALPHA1",
                "*HW_XG_WAVE_LENGTH_ALPHA2",
                "*HW_XG_WAVE_LENGTH_BETA",
                "*MEAS_DATA_COUNT",
            ):
                prefix = key + " "
                if line.startswith(prefix):
                    metadata[key.lstrip("*").lower()] = line[len(prefix):].strip().strip('"')
                    break
            continue
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"No two-column data found after #Intensity_unit in {path}")
    data = np.asarray(rows, dtype=float)
    return metadata, data[:, 0], data[:, 1]


def load_scans(data_dir: Path) -> tuple[list[dict], dict[str, str]]:
    scans: list[dict] = []
    shared_metadata: dict[str, str] | None = None
    for number, label, token in SAMPLES:
        path = data_dir / f"{number}.txt"
        metadata, x, y = read_rigaku_txt(path)
        scans.append({"number": number, "label": label, "token": token,
                      "path": path, "metadata": metadata, "x": x, "y": y,
                      "resolved": str(path.resolve()),
                      "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if shared_metadata is None:
            shared_metadata = metadata
    return scans, shared_metadata or {}


def validate_scans(scans: list[dict]) -> dict:
    """源 validate_scans 逐字移植：只做数值 QA，不改源迹线。"""
    if not scans:
        raise ValueError("No scans supplied")
    reference_x = scans[0]["x"]
    if len(reference_x) < 2:
        raise ValueError("The reference scan has fewer than two points")
    reference_step = float(np.median(np.diff(reference_x)))
    if reference_step <= 0:
        raise ValueError("The 2theta axis is not increasing")
    summaries = []
    for scan in scans:
        x, y = scan["x"], scan["y"]
        if len(x) != len(y):
            raise ValueError(f"Mismatched columns in {scan['path']}")
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError(f"Non-finite values in {scan['path']}")
        if np.any(np.diff(x) <= 0):
            raise ValueError(f"2theta is not strictly increasing in {scan['path']}")
        if not np.allclose(x, reference_x, rtol=0, atol=1e-10):
            raise ValueError("The five scans do not share one common 2theta grid")
        steps = np.diff(x)
        if not np.allclose(steps, reference_step, rtol=0, atol=1e-10):
            raise ValueError(f"Non-uniform step in {scan['path']}")
        y_max_index = int(np.argmax(y))
        summaries.append({
            "sample_number": scan["number"], "label": scan["label"],
            "source_file": Path(scan["path"]).name, "n_points": int(len(x)),
            "two_theta_start_deg": float(x[0]), "two_theta_stop_deg": float(x[-1]),
            "step_deg": reference_step,
            "intensity_unit": scan["metadata"].get("intensity_unit", "unknown"),
            "intensity_min": float(np.min(y)), "intensity_max": float(np.max(y)),
            "intensity_median": float(np.median(y)), "intensity_mean": float(np.mean(y)),
            "maximum_two_theta_deg": float(x[y_max_index])})
    return {"status": "pass",
            "grid": {"n_points": int(len(reference_x)),
                     "start_deg": float(reference_x[0]),
                     "stop_deg": float(reference_x[-1]), "step_deg": reference_step},
            "scans": summaries, "exclusions": [],
            "notes": ["All five .txt scans were retained.",
                      "The plotted traces are laboratory exports in cps."]}


def als_baseline(y: np.ndarray, *, lam: float = BASELINE_LAMBDA,
                 asymmetry: float = BASELINE_ASYMMETRY,
                 iterations: int = BASELINE_ITERATIONS) -> np.ndarray:
    """源 als_baseline 逐字移植：只供展示图估计慢变背景，不改源数据。"""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    if y.size < 3:
        raise ValueError("At least three points are required for baseline estimation")
    if not 0 < asymmetry < 1:
        raise ValueError("Baseline asymmetry must be between 0 and 1")
    second_difference = sparse.diags([1.0, -2.0, 1.0], [0, 1, 2],
                                     shape=(y.size - 2, y.size), format="csc")
    penalty = second_difference.T @ second_difference
    weights = np.ones(y.size, dtype=float)
    baseline = np.zeros_like(y, dtype=float)
    for _ in range(iterations):
        system = sparse.diags(weights, offsets=0, format="csc") + lam * penalty
        baseline = spsolve(system, weights * y)
        weights = np.where(y > baseline, asymmetry, 1.0 - asymmetry)
    return baseline


def prepare_display_scans(scans: list[dict]) -> list[dict]:
    """源 prepare_display_scans 逐字移植：基线→SG 平滑→截零→窗内逐谱归一。"""
    from scipy.signal import savgol_filter
    prepared: list[dict] = []
    for scan in scans:
        y = scan["y"].astype(float)
        baseline = als_baseline(y)
        corrected = y - baseline
        smoothed = savgol_filter(corrected, window_length=SMOOTHING_WINDOW,
                                 polyorder=SMOOTHING_POLYORDER, mode="interp")
        display_y = np.clip(smoothed, 0.0, None)
        display_window = (scan["x"] >= DISPLAY_X_MIN) & (scan["x"] <= DISPLAY_X_MAX)
        scale = float(np.max(display_y[display_window]))
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError(f"Invalid display scale for {scan['path']}")
        prepared.append({**scan, "display_y": display_y / scale,
                         "display_scale_cps": scale})
    return prepared


def _science_key(data_dir: Path) -> str:
    h = hashlib.sha256()
    for number, _, _ in SAMPLES:
        p = data_dir / f"{number}.txt"
        with open(p, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                h.update(chunk)
    h.update(repr([BASELINE_LAMBDA, BASELINE_ASYMMETRY, BASELINE_ITERATIONS,
                   SMOOTHING_WINDOW, SMOOTHING_POLYORDER,
                   DISPLAY_X_MIN, DISPLAY_X_MAX, OFFSET_STEP]).encode())
    return h.hexdigest()


def load_science(*, verbose: bool = False) -> dict:
    """受保护的科研载荷：读 Rigaku .txt → QA → 展示校正（只算一次并缓存）。

    `data_dir` 经 `_resolve_data_dir` 决议（当前 `_CFG` → 最近显式值）：
    便携默认缺席时明确报错，不猜路径、不回退。`verbose=True` 时（legacy）
    打印可追溯核对行；native 静默。
    """
    global _SCIENCE, _SCIENCE_KEY
    data_dir = _resolve_data_dir()
    key = str(data_dir.resolve()) + "|" + _science_key(data_dir)
    if _SCIENCE is not None and _SCIENCE_KEY == key:
        return _SCIENCE
    scans, metadata = load_scans(data_dir)
    qa = validate_scans(scans)
    display = prepare_display_scans(scans)
    if verbose:
        for s in qa["scans"]:
            print(f'[DATA] {s["label"]}: {s["source_file"]} '
                  f'{s["n_points"]} 点 {s["two_theta_start_deg"]}–{s["two_theta_stop_deg"]}°')
    _SCIENCE = {"scans": scans, "metadata": metadata, "qa": qa,
                "display": display, "data_dir": str(data_dir)}
    _SCIENCE_KEY = key
    return _SCIENCE


def science_inputs() -> list[str]:
    """本图实际读取的科研输入文件（native worker 据此算进输入 revision）。"""
    data_dir = _resolve_data_dir()
    return [str((data_dir / f"{n}.txt").resolve()) for n, _, _ in SAMPLES]


SCIENCE_INPUTS: list[str] = []


# ──────────────────────────────────────────────────────────────────────────────
# 绘制（源 draw_stacked / annotate_zno_on_curve / add_legend 移植到单 scope）
# ──────────────────────────────────────────────────────────────────────────────
def _detect_hkl_anchors(display: list[dict], offsets: list[float]
                        ) -> list[tuple[float, str, str, float]]:
    """五个 (hkl) 在 ZnO 展示迹线上的数据锚点：±0.7° 窗内取极大（源逻辑）。

    返回 [(x, 文本, tag, y)]；x 是窗内极大处的**实测 2θ**（声明与绘制共用同一值）。
    """
    z_scan = display[ZNO_INDEX]
    z_off = offsets[ZNO_INDEX]
    z_curve = np.asarray(z_scan["display_y"], dtype=float) + z_off
    x = np.asarray(z_scan["x"], dtype=float)
    items = []
    for tt, hkl, tag in zip(ZNO_HKL, ZNO_HKL_LABELS, HKL_TAGS):
        m = np.abs(x - tt) <= PEAK_HALF_WINDOW_DEG
        if not m.any():
            continue
        j = np.where(m)[0][int(np.argmax(z_curve[m]))]
        items.append((float(x[j]), hkl, tag, float(z_curve[j])))
    return items


def _build(science: dict, scope_target: str, *, _owned: list | None = None):
    """按 scope 建图。**legacy 与 native 共用这一份构建路径**（不存在第二套约定）。"""
    if scope_target != SCOPE:
        raise ValueError(f"未知 scope_target: {scope_target!r}；可用：{list(SCOPES)}")
    fs.apply()
    reg = GidRegistry()
    display = science["display"]
    fig = None
    try:
        fig, ax = plt.subplots(figsize=fs.canvas_mm(*XRD_CANVAS))
        if _owned is not None:
            _owned.append(fig)
        fig.subplots_adjust(left=0.25, right=0.96, top=0.94, bottom=0.21)
        ax.set_gid(_panel_gid())
        reg.register(ax, _panel_gid(), params=["canvas_w_mm", "canvas_h_mm"])
        offsets = [index * OFFSET_STEP for index in range(len(display))]
        for scan, offset in zip(display, offsets):
            line, = ax.plot(scan["x"], np.asarray(scan["display_y"], dtype=float) + offset,
                            color=fs.c(scan["token"]), lw=LINE_WIDTH, solid_capstyle="round",
                            zorder=2)
            gid = _curve_gid(scan["number"])
            line.set_gid(gid)
            reg.register(line, gid, params=["line_width", "offsets_mm", "group_y_mm"])
        ax.set_xlim(DISPLAY_X_MIN, DISPLAY_X_MAX)
        top_data = offsets[-1] + 1.0
        y_bottom = -0.18
        r_data = top_data - y_bottom
        handles = [Line2D([], [], color=fs.c(s["token"]), lw=1.2,
                           solid_capstyle="round", label=s["label"])
                   for s in reversed(display)]
        legend = ax.legend(handles=handles, loc="upper right",
                           bbox_to_anchor=(LEGEND_ANCHOR_X, 0.98),
                           frameon=False, fontsize=LEGEND_FS, ncol=LEGEND_COLS,
                           columnspacing=0.3, handlelength=0.5, handletextpad=0.2,
                           labelspacing=0.20, borderaxespad=0.2)
        for t in legend.get_texts():
            t.set_color(fs.c("TEXT"))
        legend.set_zorder(6)
        leg_gid = f"{FIGURE_ID}.{SCOPE}.legend"
        legend.set_gid(leg_gid)
        reg.register(legend, leg_gid, params=["legend_font_pt", "legend_cols",
                                              "legend_anchor_x"])
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        axes_h_mm = ax.get_window_extent().height * 25.4 / fig.dpi
        legend_h_mm = legend.get_window_extent(renderer).height * 25.4 / fig.dpi
        # 坐标范围必须先定下来（源 draw_stacked 的顺序）：图例留白后的 ylim 是
        # 标注求解器换算 mm/数据单位与下上界的依据；先放标注再设 ylim 会用
        # 默认 0–1 的坐标范围，标签必被判"放不下"。
        reserved_mm = legend_h_mm + 1.5
        if reserved_mm >= axes_h_mm:
            raise RuntimeError("XRD 方形面板放不下右上角图例")
        y_span = r_data / (1.0 - reserved_mm / axes_h_mm)
        ax.set_ylim(y_bottom, y_bottom + y_span)
        # hkl 标注带：用源 place_trace_labels 同款求解器定位（fs.place_trace_labels），
        # 下界=ZnO 本层曲线、上界=上一条谱线；抬升旋钮 hkl_lift_mm 只整体上移基线。
        items = _detect_hkl_anchors(display, offsets)
        if len(items) != 5:
            raise RuntimeError(f"hkl 锚点缺失：期望 5 个，实得 {len(items)}（峰位/窗口被改过？）")
        px_per_mm = fig.dpi / 25.4
        bb = ax.get_window_extent()
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        mm_per_unit = bb.width / px_per_mm / max(abs(x1 - x0), 1e-9)
        mm_per_yunit = bb.height / px_per_mm / max(abs(y1 - y0), 1e-9)
        _w_mm, _h_mm = fs.measure_text_boxes_mm(ax, [t for _, t, _, _ in items], HKL_FS)
        text_h = _h_mm / mm_per_yunit
        lift_units = HKL_LIFT_MM * (r_data / axes_h_mm)
        z_scan = display[ZNO_INDEX]
        x = np.asarray(z_scan["x"], dtype=float)

        def curve_of(scan, offset):
            return np.asarray(scan["display_y"], dtype=float) + offset

        z_curve = curve_of(z_scan, offsets[ZNO_INDEX])
        upper = display[ZNO_INDEX + 1]
        upper_curve = curve_of(upper, offsets[ZNO_INDEX + 1])

        def floor_of(xc, half_w):
            m = (x >= xc - half_w) & (x <= xc + half_w)
            return float(np.max(z_curve[m])) + 0.08 if m.any() else float(np.max(z_curve)) + 0.08

        def ceil_of(xc, half_w):
            xu = np.asarray(upper["x"], dtype=float)
            m = (xu >= xc - half_w) & (xu <= xc + half_w)
            return float(np.min(upper_curve[m])) - 0.08 if m.any() else float(np.min(upper_curve)) - 0.08

        before = set(ax.texts)
        placed, dropped = fs.place_trace_labels(
            ax, [(xx, tt, yy) for xx, tt, _, yy in items],
            base_y=offsets[ZNO_INDEX] + 0.12 + lift_units, text_h=text_h,
            tier_step=text_h + 0.10, mm_per_unit=mm_per_unit,
            floor_of=floor_of, ceil_of=ceil_of,
            color=fs.c("ANNOT"), fontsize=HKL_FS)
        # 源行为：place_trace_labels 的返回值被直接丢弃，放不下的标签**静默不画**
        # （原脚本在 41×46.13 mm 画布上同样只画出 (100)(102)(103)，(101)/(110)
        # 从未出现在导出的 SVG 里）。这里不崩溃，但把"没画出来的标注"如实
        # 记进科学声明与诊断，不假装五个都画上了。
        # 求解器按 items 顺序逐条尝试，但**只为放得下的画图元**：ax.texts/引线按
        # 创建顺序（即绘制顺序）追加，所以必须按绘制顺序配对——把 items 里 dropped
        # 的名字按"先画先配"跳过，不能按 items 原序 zip（那样 (102)/(103) 的图元
        # 会错挂 (101)/(110) 的 gid，浮现为 (100)(101)(102)）。
        dropped_names = {d.rsplit(" @ ", 1)[0] for d in dropped}
        drawn_items = [it for it in items if it[1] not in dropped_names]
        drawn_texts = [t for t in ax.texts if t not in before]
        if len(drawn_texts) != len(drawn_items):
            raise RuntimeError(f"hkl 标注数量异常：画出 {len(drawn_texts)} "
                               f"≠ 求解器放置 {len(drawn_items)}")
        for txt, (_, _, tag, _) in zip(drawn_texts, drawn_items):
            gid = _hkl_gid(tag)
            txt.set_gid(gid)
            reg.register(txt, gid, params=["hkl_font_pt", "hkl_lift_mm"])
        # 引线是 place_trace_labels 画的 Line2D（2 点竖线），同样按创建顺序与
        # 绘制顺序对应。注册为 guide（science_manifest 的 nodes 豁免）。
        n_lines_before = len(display)
        _guide_lines = [line for line in ax.lines[n_lines_before:]
                        if len(line.get_xydata()) == 2
                        and abs(line.get_xydata()[0][0] - line.get_xydata()[1][0]) < 1e-9]
        if len(_guide_lines) != len(drawn_texts):
            raise RuntimeError(f"hkl 引线数量异常：期望 {len(drawn_texts)}，实得 {len(_guide_lines)}")
        for line, (_, _, tag, _) in zip(_guide_lines, drawn_items):
            gid = f"{FIGURE_ID}.{SCOPE}.guide.{tag}"
            line.set_gid(gid)
            reg.register(line, gid, params=["hkl_font_pt"])
        fs.strip_yticks(ax)
        ax.set_xticks(np.arange(20, 81, 20))
        ax.tick_params(axis="x", labelsize=TICK_FS, pad=2, top=False, right=False)
        _labels = ax.get_xticklabels()
        if _labels:
            _labels[-1].set_horizontalalignment("right")
        for _tk in _labels:
            _tk.set_gid(f"{FIGURE_ID}.{SCOPE}.xtick.{_tk.get_text()}")
            reg.register(_tk, _tk.get_gid(), params=["tick_font_pt"])
        ax.set_xlabel("2θ (°)", fontsize=AXIS_FS, weight="bold", labelpad=3)
        ax.set_ylabel("Intensity (a.u.)", fontsize=AXIS_FS, weight="bold", labelpad=3)
        for lbl, name in ((ax.xaxis.label, "xaxis"), (ax.yaxis.label, "yaxis")):
            gid = f"{FIGURE_ID}.{SCOPE}.{name}"
            lbl.set_gid(gid)
            reg.register(lbl, gid, params=["axis_font_pt"])
        ax.grid(False)
        # 显示位移（纯显示，不动数据、不参与坐标范围求解）：逐曲线 + 整组。
        by_number = {_curve_gid(s["number"]): s["number"] for s in display}
        for gid, art in reg.all().items():
            if gid in by_number:
                sid = str(by_number[gid])
                dy = SHIFTS_MM[SCOPE][sid] + float(_CFG["group_y_mm"].get(SCOPE, 0.0))
                if dy:
                    from figpact import apply_display_shift
                    apply_display_shift(art, dy_mm=dy)
        return fig, reg
    except BaseException:
        if fig is not None:
            if _owned is not None:
                try:
                    _owned.remove(fig)
                except ValueError:
                    pass
            try:
                plt.close(fig)
            except Exception:
                pass
        raise


def build_figure_and_registry(scope_target: str = "main"):
    """legacy 入口：用模块基线配置建图（CLI / 清点继续走这里）。"""
    _apply_config(CONFIG)
    return _build(load_science(), scope_target)


def build_scene(science: dict, config: dict, scope: str):
    """native 入口：候选配置 + 已缓存科研载荷 → (Figure, GidRegistry)。

    候选配置先过 `prepare_config`（与 legacy 同一份标准化），再由
    `_apply_config` 装成工作副本；**传入的 config 不被修改、也不被记住**。
    """
    _apply_config(prepare_config(config))
    return _build(science, scope)


# ──────────────────────────────────────────────────────────────────────────────
# native 契约
# ──────────────────────────────────────────────────────────────────────────────
_OUTPUT_BASE = "Fig2_XRD_stacked"
_EXPORT_FORMATS = ("png", "pdf", "svg", "tiff")

_BASELINE_SCENES: dict[str, tuple] = {}
_BASELINE_DEPTH = 0
_BASELINE_OWNED: list = []


def _baseline_scene(scope: str):
    """该 scope 的基线 (Figure, GidRegistry)，同一次顶层调用内按 scope 缓存。"""
    if scope not in _BASELINE_SCENES:
        _apply_config(CONFIG)
        _BASELINE_SCENES[scope] = _build(load_science(), scope, _owned=_BASELINE_OWNED)
    return _BASELINE_SCENES[scope]


def _placed_hkl_tags(scope: str) -> tuple[list[str], list[str]]:
    """该 scope 基线里**真的画出来了**的 hkl tag 与没画出来的 tag。

    源脚本丢弃放不下的标注；本提供者同样不画，但必须如实区分"科学上存在的
    五个晶面"与"这一版版面画出来的几个"，不把没画的当已画。
    """
    _fig, reg = _baseline_scene(scope)
    placed = sorted(tag for tag in HKL_TAGS if _hkl_gid(tag) in reg.all())
    return placed, [tag for tag in HKL_TAGS if tag not in placed]


def _baseline_call(func, *args, **kwargs):
    """顶层基线调用：嵌套复用基线，退出时只关本次新建的基线 Figure。"""
    global _BASELINE_DEPTH
    _BASELINE_DEPTH += 1
    owned_before = len(_BASELINE_OWNED)
    try:
        return func(*args, **kwargs)
    finally:
        _BASELINE_DEPTH -= 1
        if _BASELINE_DEPTH == 0:
            while len(_BASELINE_OWNED) > owned_before:
                _fig = _BASELINE_OWNED.pop()
                try:
                    plt.close(_fig)
                except Exception:
                    pass
            for _key in [k for k in _BASELINE_SCENES]:
                _BASELINE_SCENES.pop(_key, None)


def _science_policy(gid: str) -> str:
    """引线是纯布局几何（guide 豁免）；谱线、标注文字、轴文字、图例受保护。"""
    if ".guide." in gid:
        return "LAYOUT"
    return "LOCKED_SCIENCE"


def _panel_id(ax, index: int) -> str:
    """panel 身份：builder 设的 Axes gid；没有时才退回引擎的位置编号约定。"""
    return ax.get_gid() or f"panel.{index}"


def _scene_roles(fig, reg) -> tuple[dict[str, list[str]], dict[int, str]]:
    """按语义角色分组注册图元，并给出「图元 → 所属 panel」的映射。"""
    roles = {"curves": [], "guides": [], "hkl_labels": [], "tick_texts": [],
             "axis_texts": [], "legends": [], "legend_texts": []}
    owner: dict[int, str] = {}
    role: dict[int, str] = {}
    for i, ax in enumerate(fig.axes):
        pid = _panel_id(ax, i)
        for txt, name in ((ax.xaxis.label, "axis_texts"), (ax.yaxis.label, "axis_texts"),
                          (ax.title, "axis_texts"), (ax._left_title, "axis_texts"),
                          (ax._right_title, "axis_texts")):
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
        if kind == "Line2D" and ".guide." in gid:
            roles["guides"].append(gid)
        elif kind == "Line2D":
            roles["curves"].append(gid)
        elif kind == "Legend":
            roles["legends"].append(gid)
        elif kind == "Text":
            roles[role.get(id(art), "hkl_labels" if ".hkl." in gid
                           else "tick_texts" if ".xtick." in gid else "hkl_labels")].append(gid)
    return roles, owner


def _decl_param(scope, key, path, unit, mutability, objects, *, operation=None, axis=None,
                bounds=None, expected=None) -> dict:
    """契约参数记录。`bounds` = (min, max)，取自 SCALARS，不另抄一份数字。"""
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
    """`{gid: panel_id}`：轴标签/图例走 owner 规则，其余按 artist 的 Axes 归属。"""
    result = {}
    for gid, art in reg.all().items():
        if id(art) in owner:
            result[gid] = owner[id(art)]
        else:
            ax = getattr(art, "axes", None)
            result[gid] = _panel_id(ax, fig.axes.index(ax)) if ax in fig.axes else "figure"
    return result


def layout_contract(scope: str) -> dict:
    """该 scope 的显式布局契约：精确 YAML 路径、语义节点/分组、受影响集合、产物名。"""
    return _baseline_call(_layout_contract_inner, scope)


def _layout_contract_inner(scope: str) -> dict:
    """内层：基线复用，生命周期由外层 `_baseline_call` 拥有。"""
    if scope not in SCOPES:
        raise ValueError(f"未知作用域 {scope!r}；可用：{list(SCOPES)}")
    fig, reg = _baseline_scene(scope)
    registered = reg.all()
    gids = sorted(registered)
    roles, owner = _scene_roles(fig, reg)
    panel_of = _panel_map(fig, reg, owner)
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
                               ("tick_font_pt", "pt", roles["tick_texts"]),
                               ("hkl_font_pt", "pt", roles["hkl_labels"] + roles["guides"]),
                               ("line_width", "pt", roles["curves"])):
        _editable(params, scope, key, [key], unit, objects, operation="rebuild",
                  bounds=SCALARS[key][1:],
                  expected={"kind": "style", "objects": objects})
    _editable(params, scope, "hkl_lift_mm", ["hkl_lift_mm"], "mm",
              roles["hkl_labels"], operation="rebuild",
              bounds=SCALARS["hkl_lift_mm"][1:],
              expected={"kind": "style", "objects": roles["hkl_labels"]})
    for sid in CURVE_IDS:
        gid = _curve_gid(int(sid))
        if gid in registered:
            _editable(params, scope, f"offsets_mm.{scope}.{sid}",
                      ["offsets_mm", scope, sid], "mm", [gid],
                      operation="translate", axis="y",
                      bounds=(-SHIFT_LIMIT_MM, SHIFT_LIMIT_MM),
                      expected={"kind": "translate", "objects": [gid], "axis": "y"})
    group_objects = roles["curves"] + roles["hkl_labels"] + roles["guides"]
    _editable(params, scope, f"group_y_mm.{scope}", ["group_y_mm", scope], "mm",
              group_objects, operation="translate", axis="y", bounds=(-100.0, 100.0),
              expected={"kind": "translate", "objects": group_objects, "axis": "y"})
    params.append(_decl_param(scope, "schema_version", ["schema_version"], "int", "FIXED_STYLE", []))
    params.append(_decl_param(scope, "data_dir", ["data_dir"], "path", "LOCKED_SCIENCE", []))
    params.append(_decl_param(scope, f"layout_reference.{scope}", ["layout_reference", scope],
                              "record", "DERIVED", []))
    editable = {gid for p in params if p["mutability"] == "EDITABLE" for gid in p["objects"]}
    nodes = {gid: {"type": type(registered[gid]).__name__, "parent": panel_of[gid],
                   "editable": gid in editable, "science_policy": _science_policy(gid)}
             for gid in gids}
    root = f"{FIGURE_ID}.{scope}"
    groups = [{"id": root, "parent": None, "members": gids}]
    for pid in sorted(set(panel_of.values())):
        groups.append({"id": pid, "parent": root,
                       "members": sorted(g for g in gids if panel_of[g] == pid)})
    groups.append({"id": f"{root}.group.curves", "parent": _panel_gid(),
                   "members": sorted(roles["curves"])})
    groups.append({"id": f"{root}.group.hkl", "parent": _panel_gid(),
                   "members": sorted(roles["hkl_labels"])})
    return {"parameters": params, "nodes": nodes, "groups": groups, "relations": [],
            "outputs": [f"{_OUTPUT_BASE}.{ext}" for ext in _EXPORT_FORMATS]}


def science_manifest(science: dict) -> dict:
    """JSONable 的科研来源 / 处理 / 受保护锚点声明（native runtime 与 capture_science 用）。

    `nodes` 只列点名豁免的装饰几何（引线 guides，`type: "guide"`）；谱线、hkl
    标注文字、轴文字、图例一律 LOCKED_SCIENCE。引擎对原始 Line2D 的 x/y 一律
    保护，曲线载荷永远不能靠 LAYOUT 豁免。
    """
    return _baseline_call(_science_manifest_inner, science)


def _science_manifest_inner(science: dict) -> dict:
    """内层：基线复用，生命周期由外层 `_baseline_call` 拥有。"""
    _apply_config(CONFIG)
    _baseline_scene(SCOPE)
    placed_hkl, unplaced_hkl = _placed_hkl_tags(SCOPE)
    anchors = {}
    display = science["display"]
    offsets = [i * OFFSET_STEP for i in range(len(display))]
    for x, hkl, tag, y in _detect_hkl_anchors(display, offsets):
        anchors[tag] = {"hkl": hkl, "two_theta_deg": x, "display_y": y,
                        "gid": _hkl_gid(tag)}
    input_files = [{"sample_number": scan["number"], "label": scan["label"],
                    "file": f"{scan['number']}.txt", "path": scan["resolved"],
                    "sha256": scan["file_sha256"],
                    "n_points": int(len(scan["x"])),
                    "x_start_deg": float(scan["x"][0]),
                    "x_stop_deg": float(scan["x"][-1]),
                    "intensity_min_cps": float(np.min(scan["y"])),
                    "intensity_max_cps": float(np.max(scan["y"]))}
                   for scan in science["scans"]]
    raw = {}
    for scan, entry in zip(science["scans"], input_files):
        raw[str(scan["number"])] = {
            "n_points": entry["n_points"],
            "x_start_deg": entry["x_start_deg"], "x_stop_deg": entry["x_stop_deg"],
            "intensity_min_cps": entry["intensity_min_cps"],
            "intensity_max_cps": entry["intensity_max_cps"],
            "sha256": hashlib.sha256(np.ascontiguousarray(
                scan["x"]).tobytes() + np.ascontiguousarray(
                scan["y"]).tobytes()).hexdigest()}
    scales = {str(s["number"]): float(s["display_scale_cps"]) for s in display}
    nodes = {gid: {"type": "guide", "science_policy": "LAYOUT"}
             for gid in _baseline_scene(SCOPE)[1].all() if ".guide." in gid}
    return {
        "nodes": nodes,
        "input_files": input_files,
        "science": {
            "figure_id": FIGURE_ID,
            "source": {
                "instrument": "Rigaku SmartLab text export (2theta, cps)",
                "files": [f"{n}.txt" for n, _, _ in SAMPLES],
                "input_files": input_files,
                "wavelength_alpha1_A": WAVELENGTH_A,
                "display_window_deg": [DISPLAY_X_MIN, DISPLAY_X_MAX],
            },
            "processing": [
                "asymmetric least-squares baseline "
                f"(lambda={BASELINE_LAMBDA:g}, asymmetry={BASELINE_ASYMMETRY}, "
                f"iterations={BASELINE_ITERATIONS})",
                f"Savitzky-Golay smoothing (window={SMOOTHING_WINDOW}, "
                f"polyorder={SMOOTHING_POLYORDER}), clip negatives at zero",
                f"per-trace normalization by own max within "
                f"{DISPLAY_X_MIN:g}-{DISPLAY_X_MAX:g} deg, offset step {OFFSET_STEP}",
                "not applied: K-alpha2 stripping, deconvolution, phase fitting, "
                "FWHM or crystallite-size fitting",
            ],
            "normalization": {"window_deg": [DISPLAY_X_MIN, DISPLAY_X_MAX],
                              "display_scale_cps": scales},
            "protected": {
                "display_window_deg": [DISPLAY_X_MIN, DISPLAY_X_MAX],
                "hkl_positions_deg": list(ZNO_HKL),
                "hkl_labels": list(ZNO_HKL_LABELS),
                "hkl_anchors": anchors,
                "hkl_labels_drawn": placed_hkl,
                "hkl_labels_not_drawn": unplaced_hkl,
                "hkl_not_drawn_note": (
                    "source script drops labels that do not fit the band; those "
                    "crystal faces stay scientific anchors but have no drawn text"),
            },
            "raw": raw,
        },
    }


if ARGS.list_params:
    list_params()
    raise SystemExit(0)

if __name__ == "__main__":
    import json as _json
    if ARGS.inventory:
        fig, reg = build_figure_and_registry(SCOPE)
        print(_json.dumps(sorted(reg.all()), ensure_ascii=False, indent=2))
        plt.close(fig)
    elif ARGS.inspect:
        fig, reg = build_figure_and_registry(SCOPE)
        art = reg.get(ARGS.inspect)
        print(ARGS.inspect if art is None else
              f"{ARGS.inspect}: {type(art).__name__} params={reg.params_of(ARGS.inspect)}")
        plt.close(fig)
    else:
        list_params()
