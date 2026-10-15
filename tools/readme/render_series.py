#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
from figpact.final_size import audit_figure
STAGES = [
    ("series-01-ugly", "stage-01-ugly", "starting config"),
    ("series-02-spacing", "stage-02-spacing", "widen sample pitch"),
    ("series-03-canvas", "stage-03-canvas", "larger canvas/margins"),
    ("series-04-labels", "stage-04-labels", "label lanes + min gap + shifts"),
    ("series-05-typography", "stage-05-typography", "unify fonts and line width"),
    ("series-06-final", "stage-06-final", "legend settled, no overflow"),
]
STAGE_META = {
    "series-01-ugly": {"intent": "基线：记录默认参数下的问题", "change": "—", "expected": "仅记录基线，不修"},
    "series-02-spacing": {"intent": "拉开样品间距", "change": "pitch_mm 0.32→0.78", "expected": "曲线净距拉开"},
    "series-03-canvas": {"intent": "放大画布与边距", "change": "canvas_w 66→96, canvas_h 40→62", "expected": "字号≥5 pt"},
    "series-04-labels": {"intent": "解决近峰标签互叠", "change": "label_min_gap_mm 0→1.8 + peak_label_shifts_mm 分道", "expected": "标签分道互不重叠"},
    "series-05-typography": {"intent": "统一字号档位与线宽", "change": "font_pt & line_width 统一", "expected": "各角色一档≥5 pt"},
    "series-06-final": {"intent": "图例移出数据区并收尾", "change": "legend_anchor_x 0.5→0.98", "expected": "无裁切/空白/遮挡"},
}
OUT_DIR = ROOT / "docs" / "readme"
OUT_DIR.mkdir(parents=True, exist_ok=True)
def stage_config_path(name):
    return ROOT / "examples" / "demo" / f"{name}.yaml"

def _text_bbox_overlaps(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    items = []
    for ax in fig.axes:
        for t in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            items.append(t)
        cands = [ax.title, ax.xaxis.label, ax.yaxis.label] + list(ax.texts)
        leg = ax.get_legend()
        if leg is not None:
            cands += list(leg.get_texts())
        for t in cands:
            if t is not None:
                items.append(t)
    for t in fig.texts:
        items.append(t)
    for leg in getattr(fig, "legends", []):
        for t in leg.get_texts():
            items.append(t)
        # legend frame vertices not text
    for ax in fig.axes:
        leg = ax.get_legend()
        if leg is not None and leg not in [getattr(a,'get_legend',lambda:None)() for a in []]:
            pass
    boxes = []
    for t in items:
        try:
            txt = t.get_text() if hasattr(t, "get_text") else str(t)
        except Exception:
            txt = str(t)
        if not str(txt).strip():
            continue
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        boxes.append((str(txt), t, bb))
    problems = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            la, ta, ba = boxes[i]
            lb, tb, bb_ = boxes[j]
            if la == lb and ba.bounds == bb_.bounds:
                continue
            dx = min(ba.x1, bb_.x1) - max(ba.x0, bb_.x0)
            dy = min(ba.y1, bb_.y1) - max(ba.y0, bb_.y0)
            if dx > 0 and dy > 0 and (dx * dy) > 4.0:
                problems.append({"pair": [la, lb], "area_px2": round(float(dx * dy), 2),
                                "gid_a": getattr(ta, "get_gid", lambda: None)(),
                                "gid_b": getattr(tb, "get_gid", lambda: None)()})
    return problems

def _legend_data_intersection(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    legends = []
    for ax in fig.axes:
        if ax.get_legend() is not None:
            legends.append(ax.get_legend())
    legends += list(getattr(fig, "legends", []))
    if not legends:
        return False
    for legend in legends:
        lbb = legend.get_window_extent(renderer)
        for ax in fig.axes:
            for line in ax.lines:
                try:
                    lne = line.get_window_extent(renderer)
                except Exception:
                    continue
                dx = min(lbb.x1, lne.x1) - max(lbb.x0, lne.x0)
                dy = min(lbb.y1, lne.y1) - max(lbb.y0, lne.y0)
                if dx > 0 and dy > 0:
                    return True
    return False

def _clipped_artists(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    dpi = fig.dpi
    mm_per_px = 25.4 / dpi
    w_mm, h_mm = fig.get_figwidth() * 25.4, fig.get_figheight() * 25.4
    eps = 0.05
    count = 0
    gids = []
    seen = set()
    for art in list(fig.findobj()):
        if art is fig:
            continue
        try:
            bb = art.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        if id(art) in seen:
            continue
        seen.add(id(art))
        x0 = bb.x0 * mm_per_px
        y0 = bb.y0 * mm_per_px
        x1 = bb.x1 * mm_per_px
        y1 = bb.y1 * mm_per_px
        if x0 < -eps or x1 > w_mm + eps or y0 < -eps or y1 > h_mm + eps:
            count += 1
            gids.append(art.get_gid() if hasattr(art, "get_gid") else None)
    return count, [g for g in gids if g]
def _seg_rect_intersect(a, b, bb):
    # Liang-Barsky segment vs axis-aligned rectangle
    dx = b[0]-a[0]; dy = b[1]-a[1]
    p = [-dx, dx, -dy, dy]
    q = [a[0]-bb.x0, bb.x1-a[0], a[1]-bb.y0, bb.y1-a[1]]
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False
        else:
            t = qi/pi
            if pi < 0:
                if t > u2: return False
                if t > u1: u1 = t
            else:
                if t < u1: return False
                if t < u2: u2 = t
    return u1 <= u2

def _text_curve_overlaps(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    items = []
    for ax in fig.axes:
        for t in list(ax.texts) + [ax.title, ax.xaxis.label, ax.yaxis.label]:
            if t is not None and str(getattr(t, "get_text", lambda: "")()).strip():
                items.append((t, ax))
    for t in fig.texts:
        if str(getattr(t, "get_text", lambda: "")()).strip():
            items.append((t, None))
    for ax in fig.axes:
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                items.append((t, ax))
    probs = []
    seen = set()
    for t, tax in items:
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        axes_list = [tax] if tax is not None else list(fig.axes)
        for ax in axes_list:
            for line in ax.lines:
                try:
                    xy = line.get_xydata()
                except Exception:
                    continue
                if xy is None or len(xy) < 2:
                    continue
                try:
                    disp = line.get_transform().transform(xy)
                except Exception:
                    continue
                hit = False
                for i in range(len(disp)-1):
                    if _seg_rect_intersect((float(disp[i,0]), float(disp[i,1])),
                                            (float(disp[i+1,0]), float(disp[i+1,1])), bb):
                        hit = True; break
                if hit:
                    key = (id(t), id(line))
                    if key in seen: continue
                    seen.add(key)
                    probs.append({"text": str(t.get_text()), "text_gid": t.get_gid() if hasattr(t,"get_gid") else None,
                                  "curve_gid": line.get_gid() if hasattr(line,"get_gid") else None})
    return probs

def _text_outside_canvas(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    count = 0
    gids = []
    items = []
    for ax in fig.axes:
        for t in list(ax.texts) + [ax.title, ax.xaxis.label, ax.yaxis.label]:
            if t is not None: items.append((t, ax))
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts(): items.append((t, ax))
    for t in fig.texts: items.append((t, None))
    for t, ax in items:
        try:
            txt = t.get_text()
        except Exception:
            txt = ""
        if not str(txt).strip(): continue
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        ref = fig.get_window_extent(renderer)
        if bb.x0 < ref.x0 - 1e-6 or bb.x1 > ref.x1 + 1e-6 or bb.y0 < ref.y0 - 1e-6 or bb.y1 > ref.y1 + 1e-6:
            count += 1
            gids.append(t.get_gid() if hasattr(t, "get_gid") else None)
    return count, [g for g in gids if g]

def _label_peak_offsets(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax = fig.axes[0]
    targets = {}
    for ppm, idx, *_ in demo.PEAK_LABELS_TEMPLATE:
        sid = demo.SAMPLES_CONFIG[idx][4]
        gid = f"{demo.FIGURE_ID}.main.peak.{sid}.{demo._gid_tag(ppm)}"
        targets[gid] = float(ppm)
    out = []
    for t in fig.findobj(match=lambda a: hasattr(a, "get_text")):
        try:
            txt = t.get_text()
        except Exception:
            txt = ""
        if not str(txt).strip(): continue
        gid = t.get_gid() if hasattr(t, "get_gid") else None
        if gid not in targets: continue
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        cx = (bb.x0 + bb.x1) / 2.0
        cy = (bb.y0 + bb.y1) / 2.0
        xdata = ax.transData.inverted().transform((cx, cy))[0]
        out.append({"gid": gid, "label_peak_offset_ppm": round(float(abs(xdata - targets[gid])), 6)})
    return out


def _rendered_labels(fig, cfg):
    out = []
    expected = list(demo.PEAK_LABELS_TEMPLATE)
    inv = None
    for ax in fig.axes:
        inv = ax.transData.inverted()
        for tmpl in expected:
            ppm, idx, name = tmpl
            # find text matching either exact template name or combined suffix
            match = None
            for t in ax.texts:
                try:
                    if t.get_text() == name:
                        match = t
                        break
                except Exception:
                    pass
            if match is None:
                out.append({"gid": None, "text": name, "present": False, "center_px": None, "center_ppm": None, "offset_ppm": None})
                continue
            bb = match.get_window_extent(fig.canvas.get_renderer())
            renderer = fig.canvas.get_renderer()
            bb = match.get_window_extent(renderer)
            cx = (bb.x0 + bb.x1) / 2.0
            cy = (bb.y0 + bb.y1) / 2.0
            xdata, _ = inv.transform((cx, cy))
            out.append({"gid": match.get_gid(), "text": match.get_text(), "present": True,
                        "center_px": round(float(cx), 3), "center_ppm": round(float(xdata), 4),
                        "offset_ppm": round(abs(float(xdata) - float(ppm)), 4)})
    return out

def render_one(stage_slug, cfg_name):
    t0 = time.perf_counter()
    cfg = demo.load_config_demo(stage_config_path(cfg_name))
    demo._apply_config(cfg)
    science = demo.load_science()
    fig, reg = demo.build_scene(science, cfg, "main")
    overlaps = _text_bbox_overlaps(fig)
    rendered = _rendered_labels(fig, cfg)
    curve_overlaps = _text_curve_overlaps(fig)
    outside_n, outside_gids = _text_outside_canvas(fig)
    leg_int = _legend_data_intersection(fig)
    clipped_n, clipped_gids = _clipped_artists(fig)
    label_offsets = _label_peak_offsets(fig)
    w_mm = float(cfg["canvas_w_mm"])
    dpi = 1600.0 / (w_mm / 25.4)
    out = OUT_DIR / f"{stage_slug}.png"
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    elapsed = time.perf_counter() - t0
    audit_t0 = time.perf_counter()
    res = audit_figure(ROOT / "examples" / "demo" / "demo_figure.py", config=stage_config_path(cfg_name), target_width_mm=w_mm)
    audit_elapsed = time.perf_counter() - audit_t0
    fonts_pt = {fr["role_key"]: fr["nominal_pt"] for fr in res["font_roles"]}
    line_widths = res.get("line_width", {}).get("measured_pt_values", [])
    return out, res, elapsed, audit_elapsed, overlaps, curve_overlaps, outside_n, outside_gids, leg_int, clipped_n, clipped_gids, label_offsets, fonts_pt, line_widths, rendered

def main():
    report = {"stages": []}
    for slug, cfg_name, action in STAGES:
        out, res, el, ael, overlaps, curve_overlaps, outside_n, outside_gids, leg_int, clipped_n, clipped_gids, label_offsets, fonts_pt, line_widths, rendered = render_one(slug, cfg_name)
        print(f"=== {slug}.png ===")
        print(f"  action: {action}")
        print(f"  render_elapsed_s: {el:.3f}  audit_elapsed_s: {ael:.3f}")
        print(f"  canvas_mm: {res['source_canvas_mm']}  measured_export_mm: {res['measured_export_mm']}  k: {res['k']}")
        print(f"  infeasible: {res['infeasible']}")
        print(f"  text_bbox_overlaps: {len(overlaps)}")
        print(f"  legend_data_intersection: {leg_int}")
        print(f"  clipped_artists: {clipped_n}")
        print(f"  rendered_labels: {len([r for r in rendered if r['present']])}/{len(rendered)}")
        print(f"  file: {out} bytes={out.stat().st_size}")
        report["stages"].append({
            "slug": slug,
            "file": str(out.relative_to(ROOT)),
            "bytes": out.stat().st_size,
            "action": action,
            "elapsed_s": round(el, 3),
            "audit_elapsed_s": round(ael, 3),
            "canvas_mm": res["source_canvas_mm"],
            "measured_export_mm": res["measured_export_mm"],
            "k": res["k"],
            "infeasible": res["infeasible"],
            "text_bbox_overlaps": len(overlaps),
            "text_bbox_overlap_pairs": overlaps,
            "text_curve_overlaps": len(curve_overlaps),
            "text_curve_overlap_pairs": curve_overlaps,
            "text_outside_canvas": outside_n,
            "text_outside_canvas_gids": outside_gids,
            "legend_data_intersection": leg_int,
            "clipped_texts": 0,
            "clipped_artists": clipped_n,
            "clipped_artist_gids": clipped_gids,
            "label_peak_offset_ppm": label_offsets,
            "fonts_pt": fonts_pt,
            "line_widths": line_widths,
            "spatial_risk_count": len(res.get("spatial_risk", [])),
            "intent": STAGE_META.get(slug, {}).get("intent", ""),
            "change": STAGE_META.get(slug, {}).get("change", ""),
            "expected": STAGE_META.get(slug, {}).get("expected", ""),
            "actual": (f"text_bbox_overlaps={len(overlaps)}, text_curve_overlaps={len(curve_overlaps)}, "
                      f"clipped_artists={clipped_n}, rendered_labels={len([r for r in rendered if r['present']])}/{len(rendered)}, "
                      f"infeasible={res['infeasible']}"),
        })
    rep = OUT_DIR / "series_report.json"
    rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {rep}")

if __name__ == "__main__":
    main()
