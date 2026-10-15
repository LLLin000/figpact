#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the "ugly -> perfect" series for the README (all data self-generated)."""
import argparse, json, math, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples" / "demo"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import demo_figure as demo
from figpact.final_size import audit_figure, render_report

STAGES = [
    ("series-01-ugly", "stage-01-ugly", "starting config"),
    ("series-02-spacing", "stage-02-spacing", "widen sample pitch"),
    ("series-03-canvas", "stage-03-canvas", "larger canvas/margins"),
    ("series-04-labels", "stage-04-labels", "label lanes + min gap + shifts"),
    ("series-05-typography", "stage-05-typography", "unify fonts and line width"),
    ("series-06-perfect", "stage-06-perfect", "legend settled, no overflow"),
]

OUT_DIR = ROOT / "docs" / "readme"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def stage_config_path(name):
    return ROOT / "examples" / "demo" / f"{name}.yaml"

def render_one(stage_slug, cfg_name):
    t0 = time.perf_counter()
    cfg = demo.load_config_demo(stage_config_path(cfg_name))
    demo._apply_config(cfg)
    science = demo.load_science()
    fig, reg = demo.build_scene(science, cfg, "main") if hasattr(demo,"build_scene") else demo.build_figure_and_registry("main")
    # width target 1600 px
    w_mm = float(cfg["canvas_w_mm"])
    dpi = 1600.0 / (w_mm / 25.4)
    out = OUT_DIR / f"{stage_slug}.png"
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    elapsed = time.perf_counter() - t0
    # audit numbers
    audit_t0 = time.perf_counter()
    res = audit_figure(ROOT / "examples" / "demo" / "demo_figure.py", config=stage_config_path(cfg_name), target_width_mm=w_mm)
    audit_elapsed = time.perf_counter() - audit_t0
    return out, res, elapsed, audit_elapsed

def main():
    report = {"stages": []}
    for slug, cfg_name, action in STAGES:
        out, res, el, ael = render_one(slug, cfg_name)
        risks = res.get("spatial_risk", [])
        overlaps = []
        for r in risks:
            if r.get("object") == "text-overlap":
                overlaps.append(r)
        print(f"=== {slug}.png ===")
        print(f"  action: {action}")
        print(f"  render_elapsed_s: {el:.3f}  audit_elapsed_s: {ael:.3f}")
        print(f"  canvas_mm: {res['source_canvas_mm']}  measured_export_mm: {res['measured_export_mm']}  k: {res['k']}")
        print(f"  infeasible: {res['infeasible']}")
        print(f"  spatial_risk_count: {len(risks)}  text_overlap_entries: {len(overlaps)}")
        for fr in res["font_roles"]:
            print(f"  font {fr['role_key']}: nominal {fr['nominal_pt']} effective {fr['effective_pt_at_target']} infeasible={fr['infeasible']}")
        print(f"  file: {out} bytes={out.stat().st_size}")
        report["stages"].append({
            "slug": slug, "file": str(out.relative_to(ROOT)), "bytes": out.stat().st_size,
            "action": action, "elapsed_s": round(el,3), "audit_elapsed_s": round(ael,3),
            "canvas_mm": res["source_canvas_mm"], "measured_export_mm": res["measured_export_mm"],
            "k": res["k"], "infeasible": res["infeasible"],
            "spatial_risk_count": len(risks), "text_overlap_entries": len(overlaps),
            "font_roles": [{"role":fr["role_key"],"nominal":fr["nominal_pt"],"effective":fr["effective_pt_at_target"],"infeasible":fr["infeasible"]} for fr in res["font_roles"]],
        })
    # write json report
    rep = OUT_DIR / "series_report.json"
    rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {rep}")

if __name__ == "__main__":
    main()
