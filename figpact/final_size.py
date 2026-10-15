"""Final-size read-only audit (G7-C1): measure, never mutate.

Purely read-only: builds one figure in memory, renders to TEMP, measures
the artists there, and returns a structured report.  No source/YAML/output
directories are written.
"""
from __future__ import annotations

import importlib.util
import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import matplotlib.pyplot as plt

FONT_KEYS = ("axis_font_pt", "tick_font_pt", "peak_font_pt", "label_font_pt",
             "legend_font_pt", "note_font_pt")
LINE_KEYS = ("line_width",)


def _import_script(script: Path):
    script = Path(script).resolve()
    if not script.is_file():
        raise FileNotFoundError(f"script not found: {script}")
    _PROBE = [0]
    _PROBE[0] += 1
    name = f"figpact_finalsize_{_PROBE[0]}"
    project_root = next((p for p in script.parents if (p / "figpact").is_dir()), None)
    if project_root is not None and str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot create loader for {script}")
    module = importlib.util.module_from_spec(spec)
    parent = str(script.parent)
    argv = sys.argv
    sys.modules[name] = module
    if parent not in sys.path:
        sys.path.insert(0, parent)
    try:
        with io.StringIO() as _:
            import contextlib
            with contextlib.redirect_stdout(_):
                spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    return module


def _load_config(module, script: Path, config_path: Optional[Path]):
    if config_path is not None:
        config_path = Path(config_path).resolve()
        if hasattr(module, "load_config_nmr"):
            return module.load_config_nmr(config_path)
        if hasattr(module, "load_config_ftir"):
            return module.load_config_ftir(config_path)
        if hasattr(module, "load_config"):
            return module.load_config(config_path)
    # fall back to module-level default CONFIG loaded at import
    cfg = getattr(module, "CONFIG", None)
    if cfg is not None:
        import copy
        return copy.deepcopy(cfg)
    # last resort: empty
    return {}


def _apply_config(module, cfg):
    if hasattr(module, "_apply_config"):
        module._apply_config(cfg)
    # refresh module-level alias if present
    if hasattr(module, "CONFIG"):
        try:
            module.CONFIG = cfg
        except Exception:
            pass


def _build_figure(module, cfg, scope: Optional[str]):
    import copy
    _apply_config(module, copy.deepcopy(cfg))
    science = module.load_science() if hasattr(module, "load_science") else {}
    if scope is None:
        scopes = getattr(module, "SCOPES", None)
        scope = (scopes[0] if scopes else "main")
    if hasattr(module, "build_figure_and_registry"):
        try:
            return module.build_figure_and_registry(scope), scope
        except TypeError:
            return module.build_figure_and_registry(), scope
    if hasattr(module, "_build"):
        return module._build(science, scope), scope
    raise RuntimeError("script exposes no build entry")


def _gid_of_artists(reg) -> dict[int, str]:
    out = {}
    try:
        for gid, art in (reg.all() if hasattr(reg, "all") else {}).items():
            out[id(art)] = gid
    except Exception:
        pass
    return out


def _measure_export_mm(fig, tmp_dir: Path) -> tuple[float, float]:
    png = tmp_dir / "final_size_probe.png"
    fig.savefig(png, dpi=600, facecolor="white")
    try:
        from PIL import Image
        with Image.open(png) as im:
            w_px, h_px = im.size
    except Exception:
        # fallback: figure size
        w_px = int(fig.get_figwidth() * 600)
        h_px = int(fig.get_figheight() * 600)
    mm_per_px = 25.4 / 600.0
    return (w_px * mm_per_px, h_px * mm_per_px)


def audit_figure(script, config=None, target_width_mm=None, target_axis_font_pt=None,
                 target_tick_font_pt=None, target_line_pt=None, scope=None,
                 output=None) -> dict:
    script = Path(script)
    module = _import_script(script)
    cfg = _load_config(module, script, config)

    if target_width_mm is None:
        target_width_mm = float(cfg.get("canvas_w_mm", 42.0))

    (fig, reg), scope = _build_figure(module, cfg, scope)

    # baseline draw at figure dpi before any save
    fig.draw_without_rendering()
    renderer = fig.canvas.get_renderer()
    base_dpi = fig.dpi

    gid_map = _gid_of_artists(reg)

    declared_w = float(cfg.get("canvas_w_mm", fig.get_figwidth() * 25.4))
    declared_h = float(cfg.get("canvas_h_mm", fig.get_figheight() * 25.4))

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        measured_w, measured_h = _measure_export_mm(fig, td_path)

    k = target_width_mm / measured_w if measured_w else float("nan")

    # font role measurement (controlled renderer already restored? after savefig renderer dpi=600)
    # re-draw to baseline to avoid unit trap
    fig.draw_without_rendering()
    renderer = fig.canvas.get_renderer()
    mm_per_px = 25.4 / base_dpi

    # role aggregation by fontsize
    role_samples: dict[str, list[tuple[float, float]]] = {}
    for art in list(fig.findobj(plt.Text)):
        try:
            fsz = float(art.get_fontsize())
        except Exception:
            continue
        try:
            bb = art.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        wmm = bb.width * mm_per_px
        hmm = bb.height * mm_per_px
        # find role key matching fontsize
        for key in FONT_KEYS:
            if key in cfg and abs(float(cfg[key]) - fsz) < 1e-9:
                role_samples.setdefault(key, []).append((wmm, hmm, art))
                break

    font_roles = []
    for key in FONT_KEYS:
        if key not in cfg:
            continue
        samples = role_samples.get(key, [])
        width_max = max((s[0] for s in samples), default=None)
        height_max = max((s[1] for s in samples), default=None)
        gid_examples = []
        for s in samples:
            g = gid_map.get(id(s[2]))
            if g:
                gid_examples.append(g)
        effective_pt = float(cfg[key]) * k
        infeasible = effective_pt < 5.0
        font_roles.append({
            "role_key": key,
            "nominal_pt": float(cfg[key]),
            "measured_glyph_width_mm_max": (None if width_max is None else round(width_max, 3)),
            "measured_glyph_height_mm_max": (None if height_max is None else round(height_max, 3)),
            "n_samples": len(samples),
            "example_gids": sorted(set(gid_examples))[:5],
            "effective_pt_at_target": round(effective_pt, 3),
            "infeasible": infeasible,
        })

    # line widths
    line_nominal = float(cfg.get("line_width", float("nan"))) if "line_width" in cfg else None
    measured_lws = set()
    for art in list(fig.findobj(plt.Line2D)):
        try:
            measured_lws.add(round(float(art.get_linewidth()), 4))
        except Exception:
            pass
    line_diff = (line_nominal - (sorted(measured_lws)[0] if measured_lws else line_nominal)) if line_nominal is not None else None

    # spatial risks: artists outside page bbox
    risks = []
    page_w, page_h = declared_w, declared_h
    eps = 0.05  # mm
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
        x0 = bb.x0 * mm_per_px
        y0 = bb.y0 * mm_per_px
        x1 = bb.x1 * mm_per_px
        y1 = bb.y1 * mm_per_px
        overflow = []
        if x0 < -eps:
            overflow.append(("left", round(-x0, 3)))
        if x1 > page_w + eps:
            overflow.append(("right", round(x1 - page_w, 3)))
        if y0 < -eps:
            overflow.append(("bottom", round(-y0, 3)))
        if y1 > page_h + eps:
            overflow.append(("top", round(y1 - page_h, 3)))
        if not overflow:
            continue
        key = id(art)
        if key in seen:
            continue
        seen.add(key)
        gid = gid_map.get(id(art))
        label = gid or type(art).__name__
        risks.append({
            "object": label,
            "artist_type": type(art).__name__,
            "overflow": overflow,
        })

    # overlap check using figure_style if available
    overlap_notes = []
    try:
        import sys as _sys
        # attempt import figure_style from script dir
        fs_path = script.parent / "figure_style.py"
        if fs_path.is_file():
            spec2 = importlib.util.spec_from_file_location("figure_style_audit", fs_path)
            m2 = importlib.util.module_from_spec(spec2)
            with io.StringIO() as _:
                import contextlib
                with contextlib.redirect_stdout(_):
                    spec2.loader.exec_module(m2)
            if hasattr(m2, "find_text_overlaps"):
                try:
                    r = m2.find_text_overlaps(fig)
                    if r:
                        overlap_notes.append(str(r))
                except Exception as e:
                    overlap_notes.append(f"overlap check error: {e}")
    except Exception:
        pass

    if overlap_notes:
        risks.append({"object": "text-overlap", "issue": overlap_notes})

    # editable fields from contract
    editable_fields = []
    if hasattr(module, "layout_contract"):
        try:
            contract = module.layout_contract(scope)
            for p in contract.get("parameters", []):
                if p.get("mutability") == "EDITABLE":
                    editable_fields.append(p.get("key"))
            editable_fields = sorted(set(editable_fields))
        except Exception as e:
            editable_fields = [f"contract error: {e}"]

    # infeasible list
    infeasible = []
    for fr in font_roles:
        if fr["infeasible"]:
            infeasible.append(f"{fr['role_key']} effective {fr['effective_pt_at_target']}pt < 5pt")
    if line_nominal is not None and target_line_pt is not None:
        eff_line = line_nominal * k
        if eff_line < 0.2:
            infeasible.append(f"line width effective {eff_line:.3f}pt < 0.2pt")
        line_info = {"nominal_pt": line_nominal, "measured_pt_values": sorted(measured_lws),
                     "diff_pt": round(line_nominal - (sorted(measured_lws)[0] if measured_lws else line_nominal), 4),
                     "effective_pt_at_target": round(eff_line, 3)}
    else:
        line_info = {"nominal_pt": line_nominal, "measured_pt_values": sorted(measured_lws),
                     "diff_pt": line_diff}

    if target_axis_font_pt is not None:
        infeasible.append("axis target specified but no auto-rescale applied (read-only audit)")
    plt.close(fig)

    result = {
        "script": str(script),
        "config": (str(config) if config else None),
        "scope": scope,
        "target_width_mm": target_width_mm,
        "source_canvas_mm": [declared_w, declared_h],
        "measured_export_mm": [round(measured_w, 3), round(measured_h, 3)],
        "k": round(k, 6),
        "font_roles": font_roles,
        "line_width": line_info,
        "spatial_risk": risks,
        "infeasible": infeasible,
        "editable_fields": editable_fields,
    }
    if output:
        Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def render_report(result: dict) -> str:
    lines = []
    lines.append(f"# Final-size audit: {Path(result['script']).name}")
    lines.append(f"scope: {result['scope']}  target_width_mm: {result['target_width_mm']}")
    lines.append(f"source_canvas_mm: {result['source_canvas_mm']}")
    lines.append(f"measured_export_mm: {result['measured_export_mm']}")
    lines.append(f"k = {result['k']}")
    lines.append("")
    lines.append("| role | nominal pt | measured glyph w mm | measured glyph h mm | effective pt @target | infeasible |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for r in result["font_roles"]:
        lines.append(f"| {r['role_key']} | {r['nominal_pt']} | {r['measured_glyph_width_mm_max']} | "
                     f"{r['measured_glyph_height_mm_max']} | {r['effective_pt_at_target']} | {r['infeasible']} |")
    lines.append("")
    lines.append(f"line_width: {result['line_width']}")
    lines.append(f"spatial_risk: {result['spatial_risk']}")
    lines.append(f"infeasible: {result['infeasible']}")
    lines.append(f"editable_fields: {result['editable_fields']}")
    return "\n".join(lines)
