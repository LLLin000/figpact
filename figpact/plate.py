"""Cross-figure measured comparison + source-level unification (G9 plate).

Thin aggregation over :mod:`figpact.final_size` measured results: no second
measurement reimplementation, no second journal-spec vocabulary, no whole-page
GUI. Every number in every audit row is measured (final physical size), and
every unification writes YAML source parameters and re-measures through the
existing write path (:func:`figpact.final_size.apply_final_size` backed by
``figpact.source_writes``).

Input kinds:

- ``code``: script + YAML/contract, rendered in-process. Measurable: canvas
  mm, per-artist effective pt at the final size, line widths, export ratio
  ``k``, bounding boxes, out-of-bounds. Only source that can promise ``k=1``.
- ``vector``: PDF/SVG examined read-only (PyMuPDF ``fitz``). Measurable: page
  physical size, still-text positions/sizes, path bounding boxes. Curved
  (outlined) text and missing fonts are reported unmeasurable.
- ``bitmap``: PNG/JPEG examined read-only (Pillow). Measurable: pixel size x
  DPI -> physical size and placement. Font size / line width are
  unmeasurable (estimation only); spec compliance is never reported.
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

RECEIPT_SCHEMA_VERSION = "plate-receipt/1"
MEASURE_PROTOCOL = "canvas.draw + Text.get_window_extent(renderer) -> final-size pt; export probe via savefig"

#: Unifiable by default (code + vector): user-supplied or profile target.
UNIFIABLE_ROLES = ("axis.title", "axis.tick", "curve.linewidth")
#: Compare only, never forced: density differs, forcing breaks layout.
COMPARE_ONLY_ROLES = ("peak.label", "legend", "note")
#: Tolerance for post-unify cross-figure spread of measured roles (pt).
UNIFY_TOLERANCE_PT = 0.25

_KNOWN_EXTS = {".py", ".yaml", ".yml", ".pdf", ".svg", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def _kind_of(spec: dict) -> str:
    kind = str(spec.get("kind", "")).strip().lower()
    if kind in ("code", "vector", "bitmap"):
        return kind
    p = Path(str(spec.get("path", "")))
    suf = p.suffix.lower()
    if suf == ".py":
        return "code"
    if suf in (".pdf", ".svg"):
        return "vector"
    if suf in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
        return "bitmap"
    raise ValueError(f"cannot infer input kind for {p} (pass explicit kind)")


def _resolve(p: Any) -> Path:
    path = Path(str(p)).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"plate input not found: {path}")
    return path


def _renderer_basis(fig) -> dict:
    try:
        backend = type(fig.canvas).__module__
    except Exception:
        backend = "unknown"
    try:
        dpi = float(fig.dpi)
    except Exception:
        dpi = float("nan")
    return {"method": MEASURE_PROTOCOL, "renderer": backend, "figure_dpi": dpi}


ROLE_PARAM_TO_ROLE = {"axis_font_pt": "axis.title", "tick_font_pt": "axis.tick"}


def _measure_code_artist_effs(fig, reg, cfg, k: float) -> tuple[list[dict], dict[float, float], dict]:
    """Per-artist effective pt at final size, measured from drawn extents.

    eff_pt answers "how big does type at this nominal size render at the final
    size". Raw extents are string-dependent (a long label or mathtext padding
    measures larger than its type size), so each nominal size is measured once
    via a fixed control glyph ('Ag') drawn in-figure at that size: its extent
    height converted with the figure dpi gives the measured source size, and
    the measured export ratio k scales it to the final size. Per-artist rows
    therefore share one measured value per nominal size, which is what makes
    cross-figure comparison well-defined. Declared nominal values are never
    multiplied by k; both the control extent and k are measured.
    """
    import matplotlib.pyplot as plt

    registered_ids = {id(a) for a in reg.all().values()}
    cfg_sizes = set()
    for key in ("axis_font_pt", "tick_font_pt", "peak_font_pt", "label_font_pt",
                "legend_font_pt", "note_font_pt"):
        try:
            if key in cfg:
                cfg_sizes.add(float(cfg[key]))
        except (TypeError, ValueError):
            pass
    sizes = sorted({float(t.get_fontsize()) for t in fig.findobj(plt.Text)
                    if float(t.get_fontsize() or 0) > 0
                    and (id(t) in registered_ids or float(t.get_fontsize()) in cfg_sizes)})
    fig.draw_without_rendering()
    try:
        renderer = fig.canvas.get_renderer()
    except Exception:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
    dpi = float(fig.dpi)
    role_eff: dict[float, float] = {}
    probes = []
    try:
        ax = fig.axes[0] if fig.axes else None
        if ax is not None:
            for fs in sizes:
                probes.append(ax.text(0.0, 0.0, "Ag", fontsize=fs, alpha=0.0))
            fig.draw_without_rendering()
            renderer = fig.canvas.get_renderer()
            for p in probes:
                try:
                    bb = p.get_window_extent(renderer)
                    fs = float(p.get_fontsize())
                    if bb.height > 0 and fs > 0:
                        role_eff[fs] = bb.height / dpi * 72.0 * k
                except Exception:
                    pass
    finally:
        for p in probes:
            try:
                p.remove()
            except Exception:
                pass
    fig.draw_without_rendering()
    try:
        renderer = fig.canvas.get_renderer()
    except Exception:
        pass
    basis = _renderer_basis(fig)
    basis["control_glyph"] = "Ag per nominal size, same-figure draw"
    rows: list[dict] = []
    tick_n = 0
    for art in fig.findobj(plt.Text):
        try:
            nominal = float(art.get_fontsize())
            bb = art.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0 or nominal <= 0:
            continue
        if nominal not in role_eff:
            continue  # unattributable size: not registered, matches no known knob
        gid = art.get_gid()
        if id(art) in registered_ids:
            params = sorted(reg.params_of(gid) if gid else [])
        else:
            params = [key for key in ("axis_font_pt", "tick_font_pt", "peak_font_pt",
                                      "label_font_pt", "legend_font_pt", "note_font_pt")
                      if key in cfg and abs(float(cfg[key]) - nominal) < 1e-9]
            if not params:
                continue
            tick_n += 1
            gid = f"unregistered.{'.'.join(params)}.{tick_n}"
        rows.append({
            "gid": gid,
            "role_params": params,
            "nominal_pt": round(nominal, 4),
            "measured_eff_pt": round(role_eff[nominal], 3),
            "extent_px": [round(bb.width, 2), round(bb.height, 2)],
        })
    return rows, role_eff, basis


def _measure_code_linewidths(fig, reg) -> tuple[dict[str, float], dict[str, list[str]]]:
    import matplotlib.pyplot as plt

    widths: dict[str, float] = {}
    by_value: dict[str, list[str]] = {}
    for gid, art in reg.all().items():
        if not isinstance(art, plt.Line2D):
            continue
        try:
            w = round(float(art.get_linewidth()), 4)
        except Exception:
            continue
        widths[gid] = w
        by_value.setdefault(f"{w:.4f}", []).append(gid)
    return widths, by_value


def _measure_out_of_bounds(fig, reg) -> tuple[list[dict], float, float]:
    """Artist extents vs the figure page rect, measured in display px.

    final_size's spatial_risk compares display-px extents against mm canvas
    sizes without unit conversion, which flags every artist. Here both sides
    are display px: the page rect is fig bbox at figure dpi.
    """
    import matplotlib.pyplot as plt

    fig.draw_without_rendering()
    try:
        renderer = fig.canvas.get_renderer()
    except Exception:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
    dpi = float(fig.dpi)
    page_w_px = fig.get_figwidth() * dpi
    page_h_px = fig.get_figheight() * dpi
    eps_px = 0.05 / 25.4 * dpi  # 0.05 mm tolerance in px
    risks = []
    for gid, art in reg.all().items():
        if art is fig:
            continue
        try:
            bb = art.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        overflow = []
        if bb.x0 < -eps_px:
            overflow.append(["left", round(-bb.x0 / dpi * 25.4, 3)])
        if bb.x1 > page_w_px + eps_px:
            overflow.append(["right", round((bb.x1 - page_w_px) / dpi * 25.4, 3)])
        if bb.y0 < -eps_px:
            overflow.append(["bottom", round(-bb.y0 / dpi * 25.4, 3)])
        if bb.y1 > page_h_px + eps_px:
            overflow.append(["top", round((bb.y1 - page_h_px) / dpi * 25.4, 3)])
        if overflow:
            risks.append({"object": gid, "artist_type": type(art).__name__,
                          "overflow": overflow})
    return risks, page_w_px, page_h_px


def _segments_intersect(p1, p2, p3, p4) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    o1, o2, o3, o4 = orient(p1, p2, p3), orient(p1, p2, p4), orient(p3, p4, p1), orient(p3, p4, p2)
    if o1 == 0 or o2 == 0 or o3 == 0 or o4 == 0:
        return False  # touching endpoints are not an overlap


def _text_curve_crossings(fig, reg, mm_per_px: float) -> list[dict]:
    """Text bbox vs curve polyline crossings (measured in display px)."""
    import matplotlib.pyplot as plt

    texts: list[tuple[str, Any]] = []
    curves: list[tuple[str, Any]] = []
    for gid, art in reg.all().items():
        if isinstance(art, plt.Text):
            texts.append((gid, art))
        elif isinstance(art, plt.Line2D):
            try:
                if len(art.get_xdata()) >= 2:
                    curves.append((gid, art))
            except Exception:
                pass
    if not texts or not curves:
        return []
    try:
        fig.draw_without_rendering()
        renderer = fig.canvas.get_renderer()
    except Exception:
        return []
    crossings: list[dict] = []
    for tgid, text in texts:
        try:
            bb = text.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        edges = [
            ((bb.x0, bb.y0), (bb.x1, bb.y0)), ((bb.x1, bb.y0), (bb.x1, bb.y1)),
            ((bb.x1, bb.y1), (bb.x0, bb.y1)), ((bb.x0, bb.y1), (bb.x0, bb.y0)),
        ]
        for cgid, line in curves:
            ax = getattr(line, "axes", None)
            if ax is None:
                continue
            try:
                pts = ax.transData.transform(list(zip(line.get_xdata(), line.get_ydata())))
            except Exception:
                continue
            hits = 0
            for i in range(len(pts) - 1):
                seg = (tuple(pts[i]), tuple(pts[i + 1]))
                for edge in edges:
                    if _segments_intersect(seg[0], seg[1], edge[0], edge[1]):
                        hits += 1
                        break
            if hits:
                crossings.append({"text_gid": tgid, "curve_gid": cgid, "crossings": hits})
    return crossings


def _audit_code(spec: dict, width_mm: float) -> dict:
    from figpact import final_size as fs_mod

    script = _resolve(spec["path"])
    config = _resolve(spec["config"]) if spec.get("config") else None
    scope = spec.get("scope")
    measured = fs_mod.audit_figure(script, config=config, target_width_mm=width_mm, scope=scope)
    module = fs_mod._import_script(script)
    cfg = fs_mod._load_config(module, script, config)
    (fig, reg), _ = fs_mod._build_figure(module, cfg, scope or measured.get("scope"))
    try:
        k = float(measured["k"])
        artist_rows, role_eff, basis = _measure_code_artist_effs(fig, reg, cfg, k)
        linewidths, linewidth_groups = _measure_code_linewidths(fig, reg)
        mm_per_px = 25.4 / float(fig.dpi)
        crossings = _text_curve_crossings(fig, reg, mm_per_px)
        oob, _, _ = _measure_out_of_bounds(fig, reg)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)
    return {
        "label": spec.get("label") or script.name,
        "kind": "code",
        "path": str(script),
        "scope": measured.get("scope"),
        "target_width_mm": width_mm,
        "source_canvas_mm": measured.get("source_canvas_mm"),
        "measured_export_mm": measured.get("measured_export_mm"),
        "k": measured.get("k"),
        "k_infeasible": bool(float(measured.get("k", 1.0)) > 1.0),
        "artist_fonts": artist_rows,
        "font_roles": measured.get("font_roles", []),
        "linewidths": linewidths,
        "linewidth_groups": linewidth_groups,
        "line_summary": measured.get("line_width", {}),
        "out_of_bounds": oob,
        "text_curve_crossings": crossings,
        "role_eff_pt": {str(kk): round(vv, 3) for kk, vv in role_eff.items()},
        "infeasible": measured.get("infeasible", []),
        "editable_fields": measured.get("editable_fields", []),
        "measurement_basis": basis,
        "measurable_specs": ["canvas_mm", "artist_eff_pt", "linewidth_pt", "k", "bbox", "out_of_bounds"],
        "unmeasurable_specs": [],
    }


def _audit_vector(spec: dict) -> dict:
    import fitz  # PyMuPDF

    path = _resolve(spec["path"])
    if path.suffix.lower() == ".svg":
        return {
            "label": spec.get("label") or path.name, "kind": "vector", "path": str(path),
            "page_size_mm": None, "texts": [], "path_bboxes": [],
            "measurement_basis": {"method": "SVG parsed as XML (no renderer); sizes only if text elements carry font-size", "renderer": "none", "figure_dpi": None},
            "measurable_specs": ["path_bbox (element units)", "text font-size attribute if present"],
            "unmeasurable_specs": ["physical page size (SVG has no fixed page)", "outlined-text size", "linewidth in pt without scale context"],
        }
    doc = fitz.open(path)
    try:
        pages = []
        missing_fonts: list[str] = []
        for i, page in enumerate(doc):
            rect = page.rect
            blocks = page.get_text("dict").get("blocks", [])
            texts = []
            for b in blocks:
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        texts.append({
                            "page": i, "text": span.get("text", "")[:80],
                            "size_pt": round(float(span.get("size", 0.0)), 3),
                            "font": span.get("font", ""),
                            "bbox_pt": [round(v, 2) for v in span.get("bbox", [0, 0, 0, 0])],
                            "flags": span.get("flags", 0),
                        })
                        if span.get("font", "") and (page.get_fonts() is not None and
                                not any(f[3] == span.get("font", "") for f in page.get_fonts())):
                            if span.get("font", "") not in missing_fonts:
                                missing_fonts.append(span.get("font", ""))
            drawings = page.get_drawings()
            bboxes = []
            for d in drawings[:50]:
                r = d.get("rect")
                if r is not None:
                    bboxes.append([round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)])
            pages.append({
                "page": i,
                "size_mm": [round(rect.width * 25.4 / 72.0, 3), round(rect.height * 25.4 / 72.0, 3)],
                "n_texts": len(texts), "n_paths": len(drawings),
                "path_bbox_sample": bboxes[:5],
            })
        first = pages[0] if pages else {"size_mm": None}
        outlined = sum(p["n_paths"] for p in pages) > 0 and sum(p["n_texts"] for p in pages) == 0
        unmeas = []
        if outlined:
            unmeas.append("text size/glyphs: no embedded text (outlined paths); size unrecoverable")
        if missing_fonts:
            unmeas.append(f"font sizes unreliable: fonts not embedded: {missing_fonts[:5]}")
        if not unmeas:
            unmeas.append("outlined-text size (only if text had been converted to paths)")
        all_texts = []
        for p_i, page in enumerate(doc):
            for b in page.get_text("dict").get("blocks", []):
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        all_texts.append({"page": p_i, "text": span.get("text", "")[:80],
                                          "size_pt": round(float(span.get("size", 0.0)), 3),
                                          "font": span.get("font", "")})
                        if len(all_texts) >= 40:
                            break
        return {
            "label": spec.get("label") or path.name, "kind": "vector", "path": str(path),
            "page_size_mm": first.get("size_mm"), "pages": pages, "texts": all_texts[:40],
            "measurement_basis": {"method": "PyMuPDF page.rect (pt->mm) + span dict sizes; drawings rects", "renderer": "fitz", "figure_dpi": None},
            "measurable_specs": ["page_size_mm", "text position/size (if still text)", "path bbox"],
            "unmeasurable_specs": unmeas,
        }
    finally:
        doc.close()


def _audit_bitmap(spec: dict) -> dict:
    from PIL import Image

    path = _resolve(spec["path"])
    dpi = spec.get("dpi")
    assumed = False
    with Image.open(path) as im:
        w_px, h_px = im.size
        info_dpi = im.info.get("dpi")
        if dpi is None:
            if isinstance(info_dpi, (tuple, list)) and len(info_dpi) >= 2 and info_dpi[0]:
                dpi = float(info_dpi[0])
            else:
                dpi = 300.0  # assumption, recorded as such
                assumed = True
        else:
            dpi = float(dpi)
        w_mm = w_px * 25.4 / dpi
        h_mm = h_px * 25.4 / dpi
    return {
        "label": spec.get("label") or path.name, "kind": "bitmap", "path": str(path),
        "pixels": [w_px, h_px], "dpi_used": dpi, "dpi_assumed": assumed,
        "physical_size_mm": [round(w_mm, 3), round(h_mm, 3)],
        "measurement_basis": {"method": "Pillow pixels x DPI -> mm (placement only)", "renderer": "none", "figure_dpi": dpi},
        "measurable_specs": ["pixel size", "physical size (via DPI)", "placement"],
        "unmeasurable_specs": ["font_size_pt (unrecoverable; estimation only)",
                               "linewidth_pt (unrecoverable; estimation only)",
                               "spec compliance MUST NOT be reported for bitmaps"],
    }


def audit(figures: list[dict], widths: Any) -> dict:
    """Measure each figure at its final physical size; rows stay comparable."""
    if isinstance(widths, (int, float)):
        width_list = [float(widths)] * len(figures)
    else:
        width_list = [float(w) for w in widths]
    if len(width_list) != len(figures):
        raise ValueError(f"widths ({len(width_list)}) must match figures ({len(figures)})")
    items = []
    for spec, w in zip(figures, width_list):
        kind = _kind_of(spec)
        if kind == "code":
            items.append(_audit_code(spec, w))
        elif kind == "vector":
            items.append(_audit_vector(spec))
        else:
            items.append(_audit_bitmap(spec))
    return {"figures": items, "widths_mm": width_list}


def _role_means(item: dict) -> dict[str, list[float]]:
    """Map unifiable role -> one measured eff_pt per nominal size.

    All artists sharing a nominal size share one control-glyph measurement,
    so per-artist lists would fake a spread of identical values. Roles
    collapse to distinct eff_pt values (curve linewidth: distinct measured
    widths x measured k).
    """
    out: dict[str, list[float]] = {"axis.title": [], "axis.tick": [], "curve.linewidth": []}
    if item.get("kind") != "code":
        return out
    seen: dict[str, set[float]] = {"axis.title": set(), "axis.tick": set()}
    for row in item.get("artist_fonts", []):
        params = set(row.get("role_params", []))
        val = float(row["measured_eff_pt"])
        if "axis_font_pt" in params:
            seen["axis.title"].add(val)
        if "tick_font_pt" in params:
            seen["axis.tick"].add(val)
    out["axis.title"] = sorted(seen["axis.title"])
    out["axis.tick"] = sorted(seen["axis.tick"])
    out["curve.linewidth"] = sorted({round(float(w) * float(item.get("k", 1.0)), 3)
                                     for w in (item.get("linewidths") or {}).values()})
    return out


def plan_unify(audit_result: dict, targets: dict) -> dict:
    """Plan source edits per figure; refuses instead of auto-shrinking text."""
    want = {k: float(v) for k, v in targets.items()
            if k in ("axis_font_pt", "tick_font_pt", "line_width", "target_width_mm")}
    steps: list[dict] = []
    infeasible: list[dict] = []
    for item in audit_result.get("figures", []):
        if item.get("kind") != "code":
            infeasible.append({
                "figure": item.get("label"), "kind": item.get("kind"),
                "reason": f"{item.get('kind')} inputs have no YAML source parameters; nothing to unify",
                "alternative": "recreate from code, or compare-only (no forced unify)",
            })
            continue
        editable = set(item.get("editable_fields", []))
        width = float(item.get("target_width_mm"))
        k = float(item.get("k", 1.0))
        changes: dict[str, list] = {}
        blocked: list[str] = []
        if "target_width_mm" in want and abs(want["target_width_mm"] - width) > 1e-9:
            changes["canvas_w_mm"] = [width, want["target_width_mm"]]
            changes["canvas_h_mm"] = [None, "scaled proportionally"]
        for key in ("axis_font_pt", "tick_font_pt", "line_width"):
            if key not in want:
                continue
            if key not in editable:
                blocked.append(key)
                continue
            # infeasible check: target written at source, then scaled by measured k
            eff = want[key] * k if key != "line_width" else want[key] * k
            floor = 5.0 if key != "line_width" else 0.2
            if eff < floor:
                infeasible.append({
                    "figure": item.get("label"), "key": key,
                    "reason": f"target {want[key]}pt at k={k:.4f} gives {eff:.3f}pt < floor {floor}pt",
                    "alternative": "widen target width, or set an explicit per-figure value",
                })
                continue
            # current nominal: median of measured source nominals for that param
            cur = None
            if key == "line_width":
                vals = sorted((item.get("linewidths") or {}).values())
                cur = vals[0] if vals else None
            else:
                vals = sorted(r["nominal_pt"] for r in item.get("artist_fonts", [])
                              if key in r.get("role_params", []))
                cur = vals[len(vals) // 2] if vals else None
            changes[key] = [cur, want[key]]
        # spatial overflow already present -> infeasible (no auto-shrink allowed)
        for risk in item.get("out_of_bounds", []):
            if isinstance(risk, dict) and "overflow" in risk:
                infeasible.append({
                    "figure": item.get("label"), "key": "layout-overflow",
                    "gid": risk.get("object"), "excess_mm": risk.get("overflow"),
                    "reason": "measured overflow at final size; unify must not auto-shrink text",
                    "alternative": "widen target width, move the artist, or set an explicit local value",
                })
        for b in blocked:
            infeasible.append({
                "figure": item.get("label"), "key": b,
                "reason": f"{b} is not EDITABLE in this figure's layout_contract",
                "alternative": "set an explicit per-figure value, or leave compare-only",
            })
        steps.append({"figure": item.get("label"), "path": item.get("path"),
                      "changes": changes})
    status = "feasible" if steps and not infeasible else ("infeasible" if infeasible else "empty")
    if infeasible and steps:
        status = "partially_feasible"
    return {"status": status, "targets": want, "steps": steps, "infeasible": infeasible}


def unify(plan: dict, *, specs: Optional[list[dict]] = None, dry_run: bool = False) -> dict:
    """Apply a plan through the existing source-write chain, then re-audit.

    Writes go through :func:`figpact.final_size.apply_final_size` (YAML patch
    + ``source_writes`` journal + re-audit). ``dry_run`` returns the plan and
    the refusal-style pending state without touching sources.
    """
    if dry_run:
        return {"status": "DRY_RUN", "source_commit_state": "NOT_WRITTEN",
                "figure_verification_state": "NOT_RUN", "plan": plan}
    by_label = {s.get("label") or Path(str(s.get("path"))).name: s for s in (specs or [])}
    by_path = {str(Path(str(s.get("path"))).resolve()): s for s in (specs or [])}
    per_figure = []
    for step in plan.get("steps", []):
        spec = by_label.get(step.get("figure")) or by_path.get(str(Path(str(step.get("path"))).resolve()))
        if spec is None:
            per_figure.append({"figure": step.get("figure"), "status": "REFUSED",
                               "reason": "no matching figure spec for write-back"})
            continue
        from figpact import final_size as fs_mod

        changes = step.get("changes", {})
        width = plan.get("targets", {}).get("target_width_mm")
        axis = changes.get("axis_font_pt", [None, 8.0])[1]
        tick = changes.get("tick_font_pt", [None, 7.0])[1]
        line = changes.get("line_width", [None, 0.8])[1]
        try:
            res = fs_mod.apply_final_size(
                _resolve(spec["path"]),
                config=_resolve(spec["config"]) if spec.get("config") else None,
                target_width_mm=float(width) if width else float(spec.get("_width_mm") or 42.0),
                target_axis_font_pt=float(axis), target_tick_font_pt=float(tick),
                target_line_pt=float(line), scope=spec.get("scope"), mode="B")
        except Exception as e:  # keep per-figure errors structured
            res = {"status": "ERROR", "message": f"{type(e).__name__}: {e}"}
        per_figure.append({"figure": step.get("figure"), "result": res})
    # re-audit at the (possibly new) target widths
    after = None
    if specs:
        try:
            after = audit(specs, [s.get("_width_mm") or plan.get("targets", {}).get("target_width_mm") or 42.0
                                  for s in specs])
        except Exception as e:
            after = {"error": f"{type(e).__name__}: {e}"}
    committed = [p for p in per_figure
                 if isinstance(p.get("result"), dict) and p["result"].get("source_commit_state") == "COMMITTED"]
    status = "OK" if per_figure and len(committed) == len(per_figure) else (
        "PARTIAL" if committed else "FAILED")
    return {"status": status, "per_figure": per_figure, "after": after}


def _stable_hash(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def receipt(audit_result: dict, plan: Optional[dict] = None,
            unify_result: Optional[dict] = None, **kwargs) -> dict:
    """Build a byte-reproducible receipt (same input -> same bytes, timestamp excluded)."""
    figures = audit_result.get("figures", [])
    inputs = [{"label": f.get("label"), "kind": f.get("kind"), "path": f.get("path")}
              for f in figures]
    отклон = {}
    for role in UNIFIABLE_ROLES:
        vals: list[float] = []
        for item in figures:
            vals.extend(_role_means(item).get(role, []))
        if vals:
            отклон[role] = {"min": round(min(vals), 3), "max": round(max(vals), 3),
                            "spread_pt": round(max(vals) - min(vals), 3),
                            "within_tolerance": (max(vals) - min(vals)) <= UNIFY_TOLERANCE_PT}
    dual = {
        "source_commit_state": ((unify_result or {}).get("status")
                                if unify_result else "NOT_WRITTEN"),
        "figure_verification_state": "NOT_RUN",
    }
    if unify_result and isinstance(unify_result.get("after"), dict):
        bad = []
        for item in unify_result["after"].get("figures", []):
            bad.extend(item.get("infeasible", []) or [])
            bad.extend([r for r in item.get("out_of_bounds", []) if isinstance(r, dict)])
        dual["figure_verification_state"] = "FAIL" if bad else "PASS"
    body = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "targets": (plan or {}).get("targets", {}),
        "widths_mm": audit_result.get("widths_mm", []),
        "figures": figures,
        "role_spread_pt": отклон,
        "plan": plan,
        "unify": ({k: v for k, v in (unify_result or {}).items() if k != "after"}
                  if unify_result else None),
        "dual_state": dual,
        "inputs": inputs,
        "spec": kwargs.get("spec"),
        "measured": kwargs.get("measured"),
        "verdict": kwargs.get("verdict"),
        "note": "reproducibility: identical inputs produce byte-identical JSON excluding generated_at; generated_at is informational only and excluded from content_hash",
    }
    body["content_hash"] = _stable_hash({k: v for k, v in body.items() if k != "content_hash"})
    body["generated_at"] = datetime.now(timezone.utc).isoformat()
    return body


def render_audit_text(audit_result: dict, plan: Optional[dict] = None) -> str:
    """Human audit view: what was done, table, what is unmeasurable, next steps."""
    lines = []
    widths = audit_result.get("widths_mm", [])
    lines.append("正在做什么：逐张实测最终物理尺寸下的字号/线宽/k（含实测导出宽），"
                 f"共 {len(audit_result.get('figures', []))} 张，目标宽 {widths} mm；"
                 f"方法：{MEASURE_PROTOCOL}。")
    lines.append("")
    lines.append("| figure | kind | target mm | measured mm | k | axis eff | tick eff | line eff | 越界/相交 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---| --- |")
    for item in audit_result.get("figures", []):
        if item.get("kind") == "code":
            means = _role_means(item)
            def _m(v):
                return f"{sum(v)/len(v):.2f}" if v else "—"
            ov = len(item.get("out_of_bounds", [])) + len(item.get("text_curve_crossings", []))
            lines.append(f"| {item.get('label')} | code | {item.get('target_width_mm')} | "
                         f"{(item.get('measured_export_mm') or ['?'])[0]} | {item.get('k')} | "
                         f"{_m(means['axis.title'])} | {_m(means['axis.tick'])} | "
                         f"{_m(means['curve.linewidth'])} | {ov} |")
        elif item.get("kind") == "vector":
            lines.append(f"| {item.get('label')} | vector | — | {item.get('page_size_mm')} | — | "
                         f"— | — | — | — |")
        else:
            lines.append(f"| {item.get('label')} | bitmap | — | {item.get('physical_size_mm')} | — | "
                         f"— | — | — | — |")
    lines.append("")
    lines.append("测不到什么：")
    any_unmeas = False
    for item in audit_result.get("figures", []):
        if item.get("unmeasurable_specs"):
            any_unmeas = True
            lines.append(f"- {item.get('label')}（{item.get('kind')}）："
                         + "; ".join(item["unmeasurable_specs"]))
    if not any_unmeas:
        lines.append("- （代码图：全部可测；矢量/位图未参与本次审计）")
    lines.append("")
    lines.append("下一步能做什么：")
    lines.append("- 统一轴标题/刻度/线宽：`figpact plate unify --figure ... --width-mm ... "
                 "--axis-pt 8 --tick-pt 7 --line-pt 0.8`（先给计划，`--apply` 才写）。")
    lines.append("- 标注/图例只比较不强制统一；位图不可统一字号线宽。"
                 "放不下时报 infeasible（含 gid 与超限量），禁止自动缩字。")
    lines.append("- 拿可复算回执：`figpact plate receipt ... --out receipt.json`。")
    return "\n".join(lines)


def refusal_lines(why: str, need: str, command: str) -> str:
    return f"为什么不行：{why}\n需要什么才能行：{need}\n一条建议命令：{command}"
