#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成演示图：全部由公式生成（固定种子），不含任何真实/用户科研数据。"""

import argparse
import json
import math
import pathlib
import sys

import numpy as np
import yaml
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import sys as _sys
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from figpact import load_config as fp_load_config, apply_display_shift, GidRegistry, qa as fp_qa
from figpact.config import ConfigError

FIGURE_ID = "figdemo"
SCOPE = "main"
SCOPES = (SCOPE,)

SAMPLES_CONFIG = [
    (0, "Sample A\n(synthetic)", "#1f77b4", "synth", "alpha"),
    (1, "Sample B\n(synthetic)", "#d62728", "synth", "beta"),
    (2, "Sample C\n(synthetic)", "#2ca02c", "synth", "gamma"),
]
SAMPLE_IDS = tuple(sc[4] for sc in SAMPLES_CONFIG)

PEAKS = [
    (2.00, 0),
    (2.12, 0),
    (5.00, 1),
    (7.40, 2),
    (7.52, 2),
]
PEAK_LABELS_TEMPLATE = [
    (2.06, 0, "Cluster I (a/b)"),
    (5.00, 1, "Peak B"),
    (7.46, 2, "Cluster II (a/b)"),
]

FONT_RANGE = (3.0, 12.0)
SCALARS = {
    "schema_version": (int, 2, 2),
    "canvas_w_mm": (float, 20.0, 200.0),
    "canvas_h_mm": (float, 20.0, 200.0),
    "label_lift_mm": (float, 0.0, 30.0),
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
SCHEMA = {**SCALARS, "show_ppm": (bool,), "shifts_mm": (dict,), "peak_label_shifts_mm": (dict,),
          "pitch_mm": (dict,), "group_y_mm": (dict,), "layout_reference": (dict,)}

CLI_ARGS = None
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
            if value is None:
                continue
            if not isinstance(value, dict):
                raise
            for label, pair in value.items():
                label_key = label.removeprefix(f"{FIGURE_ID}.{key}.")
                out.setdefault(key, {})[label_key] = _label_pair(name, key, label, pair)
        else:
            raise ConfigError(f"{name}: unknown scope {key}")
    return out

def _peak_shifts_by_gid(per_scope):
    return {f"{FIGURE_ID}.{scope}.{label}": pair
            for scope, per_label in per_scope.items()
            for label, pair in per_label.items()}

def _peak_label_keys():
    return [f"peak.{sc[4]}.{str(ppm).replace('.','p')}" for ppm, idx, *_ in PEAK_LABELS_TEMPLATE for sc in [SAMPLES_CONFIG[idx]]]
def _peak_label_gids():
    return [_gid("peak", SAMPLES_CONFIG[idx][4], _gid_tag(ppm)) for ppm, idx, *_ in PEAK_LABELS_TEMPLATE]

def _gid_tag(ppm):
    return f"{ppm:.2f}".replace(".", "p")

def _gid(kind, sid="", tag=""):
    parts = [FIGURE_ID, SCOPE, kind]
    if sid:
        parts.append(sid)
    if tag:
        parts.append(tag)
    return ".".join(parts)

def prepare_config(config, *, label=None):
    name = label or CONFIG_PATH.name
    cfg = dict(config)
    raw_labels = cfg.get("peak_label_shifts_mm")
    raw_shifts = cfg.get("shifts_mm") or {}
    if not isinstance(raw_shifts, dict):
        raise ConfigError(f"{name}: shifts must dict")
    cfg["peak_label_shifts_mm"] = {scope: {} for scope in SCOPES}
    for scope, per_label in _load_label_shifts(name, raw_labels).items():
        cfg["peak_label_shifts_mm"].setdefault(scope, {}).update(per_label)
    cfg["shifts_mm"] = {scope: {sid: 0.0 for sid in SAMPLE_IDS} for scope in SCOPES}
    for scope, per_sample in raw_shifts.items():
        if per_sample is None:
            continue
        if not isinstance(per_sample, dict):
            raise
        for sid, value in per_sample.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise
            mm = float(value)
            if abs(mm) > SHIFT_LIMIT_MM:
                raise
            cfg["shifts_mm"][scope][sid] = mm
    # ensure label keys
    for scope in SCOPES:
        cfg["peak_label_shifts_mm"].setdefault(scope, {})
    return cfg

def load_config_demo(path):
    cfg = fp_load_config(path, SCHEMA)
    return prepare_config(cfg, label=path.name)

CONFIG = load_config_demo(CONFIG_PATH)

PEAK_LABEL_SHIFTS = {}
SHIFTS_MM = {}
CANVAS = (60.0, 45.0)
SAMPLE_PITCH = 0.5
GROUP_Y_MM = 0.0

def _apply_config(cfg):
    global PEAK_LABEL_SHIFTS, SHIFTS_MM, CANVAS, SAMPLE_PITCH, GROUP_Y_MM
    PEAK_LABEL_SHIFTS = _peak_shifts_by_gid(cfg.get("peak_label_shifts_mm", {}))
    SHIFTS_MM = cfg.get("shifts_mm", {})
    CANVAS = (cfg["canvas_w_mm"], cfg["canvas_h_mm"])
    pitch_raw = cfg.get("pitch_mm", {}) or {}
    pitch_val = pitch_raw.get(SCOPE, None) if isinstance(pitch_raw, dict) else None
    if isinstance(pitch_val, dict):
        nums = [float(v) for v in pitch_val.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        SAMPLE_PITCH = (sum(nums) / len(nums)) if nums else 0.5
    elif isinstance(pitch_val, (int, float)) and not isinstance(pitch_val, bool):
        SAMPLE_PITCH = float(pitch_val)
    else:
        SAMPLE_PITCH = 0.5
    gy_raw = cfg.get("group_y_mm", {}) or {}
    gy_val = gy_raw.get(SCOPE, 0.0) if isinstance(gy_raw, dict) else gy_raw
    GROUP_Y_MM = float(gy_val) if (isinstance(gy_val, (int, float)) and not isinstance(gy_val, bool)) else 0.0

rng = np.random.default_rng(42)

def load_science():
    x = np.linspace(0, 10, 1000)
    spectra = []
    for i, sc in enumerate(SAMPLES_CONFIG):
        y = np.zeros_like(x)
        for ppm, idx, *_ in [(p, ii, None) for p, ii, _ in [(pk[0], pk[1], None) for pk in PEAK_LABELS_TEMPLATE]]:
            pass
        # simpler
        y = np.zeros_like(x)
        for ppm, idx in PEAKS:
            if idx == i:
                y += 3.0 * np.exp(-((x - ppm) ** 2) / (2 * 0.02 ** 2))
        y += 0.04 * rng.standard_normal(x.size)
        spectra.append((x, y))
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
    fig, ax = plt.subplots(figsize=(w / 25.4, h / 25.4), dpi=100)
    spectra = science["spectra"]
    x = science["x"]
    pitch = SAMPLE_PITCH if SAMPLE_PITCH else 0.5
    for i, (xi, y) in enumerate(spectra):
        sid = SAMPLES_CONFIG[i][4]
        curve_gid = _gid("curve", sid, "")
        shift = SHIFTS_MM.get(SCOPE, {}).get(sid, 0.0) if isinstance(SHIFTS_MM, dict) else 0.0
        line, = ax.plot(xi, y + i * pitch + GROUP_Y_MM, color=SAMPLES_CONFIG[i][2],
                        linewidth=float(cfg["line_width"]), label=SAMPLES_CONFIG[i][1])
        line.set_gid(curve_gid)
    ax.set_xlim(10, 0)
    ax.set_xlabel(r"$\delta$ (ppm)", fontsize=float(cfg["axis_font_pt"]))
    ax.set_ylabel("Intensity (a.u.)", fontsize=float(cfg["axis_font_pt"]))
    ax.tick_params(axis="both", labelsize=float(cfg["tick_font_pt"]), pad=2.5)
    # style spines
    for sp in ax.spines.values():
        sp.set_linewidth(0.8)
    ax.tick_params(direction="in")

    reg = GidRegistry(scope=scope_target if scope_target in SCOPES else SCOPE)
    for i, line in enumerate(ax.lines):
        sid = SAMPLES_CONFIG[i][4]
        curve_gid = _gid("curve", sid, "")
        line.set_gid(curve_gid)
        shift = SHIFTS_MM.get(SCOPE, {}).get(sid, 0.0) if isinstance(SHIFTS_MM, dict) else 0.0
        reg.register(line, curve_gid, params=["line_width", "shifts_mm"])

    # peak labels: anchor each label to the highest point of ALL curves within
    # its own x-window, then lift by a fixed clearance (mm -> pt). No
    # guessed per-peak lift, no label moved off its own sample band.
    lift_mm = float(cfg.get("label_lift_mm", 2.0))
    lift_pt = lift_mm * 72.0 / 25.4
    window_ppm = 0.25
    for pidx, (ppm, sidx, name) in enumerate(PEAK_LABELS_TEMPLATE):
        sid = SAMPLES_CONFIG[sidx][4]
        tag = _gid_tag(ppm)
        peak_gid = _gid("peak", sid, tag)
        base_ys = []
        for j, (xi, y) in enumerate(spectra):
            mask = np.abs(xi - float(ppm)) <= window_ppm
            if mask.any():
                base_ys.append(float(np.max(y[mask])) + j * pitch + GROUP_Y_MM)
        yi = max(base_ys) if base_ys else (float(np.interp(ppm, spectra[sidx][0], spectra[sidx][1])) + sidx * pitch + GROUP_Y_MM)
        dx_mm, dy_mm = PEAK_LABEL_SHIFTS.get(peak_gid, [0.0, 0.0])
        dx_pt = float(dx_mm) * 72.0 / 25.4
        dy_pt = float(dy_mm) * 72.0 / 25.4
        txt = ax.annotate(
            name,
            xy=(ppm, yi),
            xytext=(dx_pt, lift_pt + dy_pt),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=float(cfg["peak_font_pt"]),
            color="#222222",
        )
        txt.set_gid(peak_gid)
        reg.register(txt, peak_gid, params=["peak_font_pt", "peak_label_shifts_mm"], science_policy="LAYOUT", editable=True)

    # legend placement: outside when anchor near right edge
    anchor = float(cfg.get("legend_anchor_x", 0.5))
    if anchor >= 0.95:
        fig.subplots_adjust(left=0.10, right=0.92, bottom=0.32, top=0.92)
        fig.subplots_adjust(left=0.10, right=0.74, bottom=0.16, top=0.82)
        leg = ax.legend(fontsize=float(cfg["legend_font_pt"]), ncol=1,
                        loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    else:
        fig.subplots_adjust(left=0.10, right=0.92, bottom=0.16, top=0.92)
        leg = ax.legend(fontsize=float(cfg["legend_font_pt"]), ncol=int(cfg["legend_cols"]),
                        loc="center", bbox_to_anchor=(anchor, 0.5), frameon=True)
    if leg is not None:
        leg.set_gid(_gid("legend", "", ""))

    # 标签必须在**坐标框内可见**：在**最终布局之后**按渲染后的真实 bbox 抬高 ylim。
    # 迭代两次：第一次测量可能基于旧布局，set 之后再测一次才稳定。
    for _pass in range(2):
        if not ax.texts:
            break
        fig.canvas.draw()
        _renderer = fig.canvas.get_renderer()
        _inv = ax.transData.inverted()
        _y0, _y1 = ax.get_ylim()
        _tops = [float(t.get_window_extent(renderer=_renderer).transformed(_inv).y1)
                 for t in ax.texts]
        _need = max(_tops) + max(0.02 * (_y1 - _y0), 0.05) if _tops else _y1
        if _pass == 0:
            print(f"[labels] ylim_before=({_y0:.3f},{_y1:.3f}) bbox_tops={[round(v,3) for v in _tops]}")
        ax.set_ylim(_y0, max(_y1, _need))
    print(f"[labels] ylim_after={tuple(round(v,3) for v in ax.get_ylim())}")

    return fig, reg

    out = pathlib.Path(__file__).parent / "demo_figure.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"{out} ({len(reg.gids())} gids)")

def science_manifest(science):
    anchors = {}
    for ppm, idx in PEAKS:
        sid = SAMPLES_CONFIG[idx][4]
        name = "Cluster I (a/b)" if (idx == 0) else ("Peak B" if idx == 1 else "Cluster II (a/b)")
        arr = science["spectra"][idx][1]
        xi = science["spectra"][idx][0]
        pitch = 0.5
        yi = float(np.interp(ppm, xi, arr)) + idx * pitch
        anchors[_gid("peak", sid, _gid_tag(ppm))] = {
            "assignment": name,
            "exact_ppm": float(ppm),
            "guide_anchor_data": [float(ppm), yi],
        }
    return {
        "nodes": {},
        "science": {
            "figure_id": FIGURE_ID,
            "source": {"format": "synthetic (formula generated, fixed seed)",
                       "samples": [{"id": sc[4], "label": sc[1]} for sc in SAMPLES_CONFIG]},
            "peaks": anchors,
        },
    }

def layout_contract(scope=SCOPE):
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
            objects = [g for g in (gid, guide) if g in registered]
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
    nodes = {gid: {"type": type(registered[gid]).__name__, "parent": None,
                   "editable": gid in {g for p in params for g in p["objects"]},
                   "science_policy": "LAYOUT"} for gid in gids}
    return {"parameters": params, "nodes": nodes, "groups": [{"id": prefix.rstrip("."), "parent": None, "members": gids}],
            "relations": [], "outputs": ["demo_figure.png"]}

load_config = load_config_demo