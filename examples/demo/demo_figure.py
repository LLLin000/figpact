#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成演示图：不包含任何用户/真实科研数据；全部由公式生成。

构造一个"推文/论文"风格的堆叠 1H NMR-like 示意图，包含多条曲线、
多个峰标注，其中两簇标注挨得非常近，用来制造需要微移的真实痛点。
"""

import argparse
import json
import math
import pathlib
import shutil
import sys
import tempfile

import numpy as np
import yaml
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.transforms import ScaledTranslation

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# no figure_style dependency below; use hex colors.

# figpact import
import sys as _sys
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from figpact import load_config as fp_load_config, apply_display_shift, GidRegistry, qa as fp_qa
from figpact.config import ConfigError

FIGURE_ID = "figdemo"
SCOPE = "main"
SCOPES = (SCOPE,)

def _gid_tag(ppm: float) -> str:
    return f"{ppm:.2f}".replace(".", "p")

def _gid(kind: str, sid: str = "", tag: str = "") -> str:
    parts = [FIGURE_ID, SCOPE, kind]
    if sid:
        parts.append(sid)
    if tag:
        parts.append(tag)
    return ".".join(parts)

# samples: path, label, color, solvent, ref, search, window, sid
SAMPLES_CONFIG = [
    (0, "Sample A\n(synthetic)", "#1f77b4", "synth", 0.0, 0.0, 0.1, "alpha"),
    (1, "Sample B\n(synthetic)", "#d62728", "synth", 0.0, 0.0, 0.1, "beta"),
    (2, "Sample C\n(synthetic)", "#2ca02c", "synth", 0.0, 0.0, 0.1, "gamma"),
]
SAMPLE_IDS = tuple(sid for *_, sid in SAMPLES_CONFIG)

# peak labels with two clusters
PEAK_LABELS_TEMPLATE = [
    (2.00, 0, "Cluster I-a", 0, "center", True, 0.10),
    (2.06, 0, "Cluster I-b", 0, "center", True, 0.10),
    (5.00, 1, "Peak B", 0, "center", True, 0.10),
    (7.40, 2, "Cluster II-a", 0, "center", True, 0.10),
    (7.46, 2, "Cluster II-b", 0, "center", True, 0.10),
]

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
BOOL_KEYS = ()
SCHEMA = {**SCALARS, "show_ppm": (bool,), "shifts_mm": (dict,), "peak_label_shifts_mm": (dict,),
          "pitch_mm": (dict,), "group_y_mm": (dict,), "layout_reference": (dict,)}

CLI_ARGS = None
import argparse
def _cli(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--list-params", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--exempt-current", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--check-effect", action="store_true")
    ap.add_argument("--inspect", default=None)
    ap.add_argument("--probe", default=None)
    ap.add_argument("--migrate-config", default=None)
    return ap.parse_args(argv)

ARGS = _cli(sys.argv[1:]) if __name__ == "__main__" else _cli([])
CONFIG_PATH = pathlib.Path(ARGS.config).expanduser() if ARGS.config else pathlib.Path(__file__).parent / "demo.yaml"

def _label_pair(name, scope, label, pair):
    if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
        raise ConfigError(f"{name}: bad pair")
    dx, dy = pair
    if isinstance(dx, bool) or not isinstance(dx, (int, float)) or not math.isfinite(dx):
        raise
    if isinstance(dy, bool) or not isinstance(dy, (int, float)) or not math.isfinite(dy):
        raise
    dx_f, dy_f = float(dx), float(dy)
    if abs(dx_f) > SHIFT_LIMIT_MM or abs(dy_f) > SHIFT_LIMIT_MM:
        raise
    return [dx_f, dy_f]

def _load_label_shifts(name, raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}: must dict")
    out = {}
    for key, value in raw.items():
        if key in SCOPES:
            if value is None: continue
            if not isinstance(value, dict): raise
            for label, pair in value.items():
                out.setdefault(key, {})[label.removeprefix(f"{FIGURE_ID}.{key}.")] = _label_pair(name, key, label, pair)
        else:
            raise ConfigError(f"{name}: unknown scope {key}")
    return out

def _peak_shifts_by_gid(per_scope):
    return {f"{FIGURE_ID}.{scope}.{label}": pair
            for scope, per_label in per_scope.items()
            for label, pair in per_label.items()}

def _peak_label_keys():
    return [gid.removeprefix(f"{FIGURE_ID}.{SCOPE}.") for gid in _peak_label_gids()]

def _peak_label_gids():
    return [_gid("peak", SAMPLES_CONFIG[idx][7], _gid_tag(ppm))
            for ppm, idx, *_ in PEAK_LABELS_TEMPLATE]

def prepare_config(config, *, label=None):
    name = label or CONFIG_PATH.name
    cfg = dict(config)
    raw_labels = cfg.get("peak_label_shifts_mm")
    raw_shifts = cfg.get("shifts_mm") or {}
    if not isinstance(raw_shifts, dict):
        raise ConfigError(f"{name}: shifts must dict")
    cfg["peak_label_shifts_mm"] = {scope: {key: [0.0, 0.0] for key in _peak_label_keys()} for scope in SCOPES}
    for scope, per_label in _load_label_shifts(name, raw_labels).items():
        cfg["peak_label_shifts_mm"].setdefault(scope, {}).update(per_label)
    cfg["shifts_mm"] = {scope: {sid: 0.0 for sid in SAMPLE_IDS} for scope in SCOPES}
    for scope, per_sample in raw_shifts.items():
        if per_sample is None: continue
        if not isinstance(per_sample, dict): raise
        for sid, value in per_sample.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value): raise
            mm = float(value)
            if abs(mm) > SHIFT_LIMIT_MM:
                raise
            cfg["shifts_mm"][scope][sid] = mm
    return cfg

def load_config_demo(path):
    cfg = fp_load_config(path, SCHEMA)
    return prepare_config(cfg, label=path.name)

CONFIG = load_config_demo(CONFIG_PATH)

PEAK_LABEL_SHIFTS = {}
SHIFTS_MM = {}
CANVAS = (60.0, 45.0)

def _apply_config(cfg):
    global PEAK_LABEL_SHIFTS, SHIFTS_MM, CANVAS
    PEAK_LABEL_SHIFTS = _peak_shifts_by_gid(cfg["peak_label_shifts_mm"])
    SHIFTS_MM = cfg["shifts_mm"]
    CANVAS = (cfg["canvas_w_mm"], cfg["canvas_h_mm"])

rng = np.random.default_rng(42)

def load_science():
    x = np.linspace(0, 10, 1000)
    spectra = []
    for i, sc in enumerate(SAMPLES_CONFIG):
        y = np.zeros_like(x)
        for ppm, idx, *_ in PEAK_LABELS_TEMPLATE:
            if idx == i:
                y += 3.0*np.exp(-((x-ppm)**2)/(2*0.02**2))
        y += 0.05*rng.standard_normal(x.size)
        spectra.append((x, y))
    # also add second synthetic curve sets for other samples? keep
    return {"spectra": spectra, "x": x}

def build_figure_and_registry(scope_target="main"):
    cfg = prepare_config(CONFIG, label="x")
    _apply_config(cfg)
    return _build_fig(load_science(), scope_target, cfg)

def build_scene(science, config, scope):
    cfg = prepare_config(config)
    _apply_config(cfg)
    return _build_fig(science, scope, cfg)

def _build_fig(science, scope_target, cfg):
    w, h = cfg["canvas_w_mm"], cfg["canvas_h_mm"]
    fig, ax = plt.subplots(figsize=(w/25.4, h/25.4), dpi=120)
    spectra = science["spectra"]
    x = science["x"]
    for i, (x_i, y) in enumerate(spectra):
        sid = SAMPLES_CONFIG[i][7]
        curve_gid = _gid("curve", sid, "")
        line, = ax.plot(x_i, y + i*0.5, color=SAMPLES_CONFIG[i][2], linewidth=1.0, label=SAMPLES_CONFIG[i][1])
        reg_dummy = None
        line.set_gid(curve_gid)
    ax.set_xlim(10, 0)
    ax.set_xlabel("ppm")
    ax.set_ylabel("Intensity (a.u.)")
    reg = GidRegistry(scope=scope_target if scope_target in SCOPES else SCOPE)
    # register curves with params
    for i in range(len(spectra)):
        sid = SAMPLES_CONFIG[i][7]
        curve_gid = _gid("curve", sid, "")
        # find line
    # re-register properly by iterating axes lines
    for i, line in enumerate(ax.lines):
        sid = SAMPLES_CONFIG[i][7]
        curve_gid = _gid("curve", sid, "")
        line.set_gid(curve_gid)
        shift = SHIFTS_MM.get(SCOPE, {}).get(sid, 0.0) if isinstance(SHIFTS_MM, dict) else 0.0
        apply_display_shift(line, dy_mm=float(shift))
        reg.register(line, curve_gid, params=["line_width", "shifts_mm"])
    for ppm, idx, grp, *_ in PEAK_LABELS_TEMPLATE:
        sid = SAMPLES_CONFIG[idx][7]
        tag = _gid_tag(ppm)
        peak_gid = _gid("peak", sid, tag)
        # height at peak
        arr = spectra[idx][1]
        xi = spectra[idx][0]
        yi = np.interp(ppm, xi[::-1], arr[::-1]) + idx*0.5
        dx, dy = PEAK_LABEL_SHIFTS.get(peak_gid, [0.0, 0.0])
        txt = ax.annotate(f"{grp}", xy=(ppm, yi), xytext=(0, 4), textcoords="offset points",
                          ha="center", va="bottom", fontsize=8.0, color="#333")
        txt.set_gid(peak_gid)
        apply_display_shift(txt, dx_mm=float(dx), dy_mm=float(dy))
        reg.register(txt, peak_gid, params=["peak_font_pt", "peak_label_shifts_mm"], science_policy="LAYOUT", editable=True)
    guide = None
    ax.legend()
    ax.invert_xaxis()
    return fig, reg

if __name__ == "__main__":
    fig, reg = build_figure_and_registry("main")
    out = pathlib.Path(__file__).parent / "demo_figure.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"{out} ({len(reg.gids())} gids)")

def science_manifest(science: dict) -> dict:
    """合成演示图的科学基线：锚点全部来自自造峰表（**不含任何真实测量数据**）。

    没有这一步，会话拿不到 science manifest，引擎会认为"可以示范但无法重新绘图验证"
    （`can_evaluate=false`），于是接受/保存被正确禁用。这里声明的是**编造**的峰位，
    与 `load_science()` 的公式数据同源。
    """
    anchors = {}
    for ppm, idx, group_name, *_ in PEAK_LABELS_TEMPLATE:
        sid = SAMPLES_CONFIG[idx][7]
        arr, xi = science["spectra"][idx][1], science["spectra"][idx][0]
        yi = float(np.interp(ppm, xi[::-1], arr[::-1])) + idx * 0.5
        anchors[_gid("peak", sid, _gid_tag(ppm))] = {
            "assignment": group_name,
            "exact_ppm": float(ppm),
            "guide_anchor_data": [float(ppm), yi],
        }
    return {
        "nodes": {},
        "science": {
            "figure_id": FIGURE_ID,
            "source": {
                "format": "synthetic (formula generated, fixed seed)",
                "samples": [{"id": sc[7], "label": sc[1]} for sc in SAMPLES_CONFIG],
            },
            "peaks": anchors,
        },
    }


def layout_contract(scope: str = SCOPE) -> dict:
    if scope not in SCOPES:
        raise ValueError(f"未知作用域 {scope!r}")
    fig, reg = build_figure_and_registry(scope)
    registered = reg.all()
    gids = sorted(registered)
    prefix = f"{FIGURE_ID}.{scope}."
    params = []
    for gid in gids:
        if ".peak." in gid:
            label = gid.removeprefix(prefix)
            guide = gid.replace(".peak.", ".guide.")
            objects=[g for g in (gid, guide) if g in registered]
            params.append({"key": f"peak_label_shifts_mm.{scope}.{label}",
                           "path": ["peak_label_shifts_mm", scope, label],
                           "unit": "mm",
                           "mutability": "EDITABLE",
                           "scopes": [scope],
                           "objects": objects,
                           "scale": 1.0,
                           "operation": "rebuild",
                           "min": -10.0,
                           "max": 10.0,
                           "expected": {"kind": "style", "objects": objects},
                           "type": "[dx,dy]"})
    nodes = {gid: {"type": type(registered[gid]).__name__,
                    "parent": None, "editable": gid in {g for p in params for g in p["objects"]},
                    "science_policy": "LAYOUT"} for gid in gids}
    return {"parameters": params, "nodes": nodes, "groups": [{"id": prefix.rstrip("."), "parent": None, "members": gids}],
            "relations": [], "outputs": ["demo_figure.png"]}
