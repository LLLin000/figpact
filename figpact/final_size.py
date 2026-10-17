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
    if parent not in sys.path:
        sys.path.insert(0, parent)
    sys.modules[name] = module
    from figpact.session import exec_module_isolated
    exec_module_isolated(spec, module, argv=[str(script)])
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


def _ambient(module):
    """构建/contract 期望的 rc 环境：调用时全局 + 脚本导入期声明的样式叠加。"""
    import copy
    from figpact.session import pristine_rc
    ambient = pristine_rc()
    overlay = getattr(module, '__figpact_import_rc__', None)
    if overlay:
        ambient.update(copy.deepcopy(overlay))
    return ambient


def _contract_isolated(module, scope):
    """`layout_contract` 可能建基线图并重套全局样式（`fs.apply()`）：隔离执行。

    构建必须在样式下跑（文字实测宽度决定避让），跑完全局原样还原。
    """
    import matplotlib as _mpl
    with _mpl.rc_context(rc=_ambient(module)):
        return module.layout_contract(scope)


def _apply_config(module, cfg):
    if hasattr(module, '_apply_config'):
        module._apply_config(cfg)
    # refresh module-level alias if present
    if hasattr(module, "CONFIG"):
        try:
            module.CONFIG = cfg
        except Exception:
            pass


def _build_figure(module, cfg, scope: Optional[str]):
    import copy
    import matplotlib as _mpl
    with _mpl.rc_context(rc=_ambient(module)):
        _apply_config(module, copy.deepcopy(cfg))
        science = module.load_science() if hasattr(module, "load_science") else {}
        if scope is None:
            scopes = getattr(module, 'SCOPES', None)
            scope = (scopes[0] if scopes else 'main')
        if hasattr(module, 'build_figure_and_registry'):
            try:
                return module.build_figure_and_registry(scope), scope
            except TypeError:
                return module.build_figure_and_registry(), scope
        if hasattr(module, '_build'):
            return module._build(science, scope), scope
        raise RuntimeError('script exposes no build entry')


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
        import matplotlib as _mpl
        # attempt import figure_style from script dir
        fs_path = script.parent / 'figure_style.py'
        if fs_path.is_file():
            spec2 = importlib.util.spec_from_file_location('figure_style_audit', fs_path)
            m2 = importlib.util.module_from_spec(spec2)
            with _mpl.rc_context():
                with io.StringIO() as _:
                    import contextlib
                    with contextlib.redirect_stdout(_):
                        spec2.loader.exec_module(m2)
            if hasattr(m2, 'find_text_overlaps'):
                try:
                    r = m2.find_text_overlaps(fig)
                    if r:
                        overlap_notes.append(str(r))
                except Exception as e:
                    overlap_notes.append(f'overlap check error: {e}')
    except Exception:
        pass

    if overlap_notes:
        risks.append({"object": "text-overlap", "issue": overlap_notes})

    # editable fields from contract
    editable_fields = []
    if hasattr(module, "layout_contract"):
        try:
            contract = _contract_isolated(module, scope)
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


ROLE_TARGETS = {
    "axis_font_pt": "target_axis_font_pt",
    "tick_font_pt": "target_tick_font_pt",
    "line_width": "target_line_pt",
}


def _contract_catalog(module, scope):
    contract = _contract_isolated(module, scope)
    params = []
    for p in contract.get("parameters", []):
        typ = "int" if p.get("unit") in ("col", "lane") else "float"
        if p.get("type") == "[dx,dy]":
            typ = "[dx,dy]"
        spec = {
            "key": p.get("key"),
            "path": list(p.get("path", [])),
            "unit": p.get("unit"),
            "类型": typ,
            "min": p.get("min", float("-inf")),
            "max": p.get("max", float("inf")),
        }
        params.append(spec)
    return {"scopes": {scope: {"groups": [{"params": params}]}}, "raw": contract}, contract


def _catalog_with_verified(module, scope, verified_params):
    """layout catalog + 已验证 contract 键（人工确认+扰动验证过的 YAML 顶层键）。

    只允许 SCALARS 有声明区间的顶层数值键；区间取自脚本 SCALARS，不另抄数字。
    画布键（canvas_w_mm/canvas_h_mm）是"统一最终宽度"的既有机制，随 verified
    写入一并放行（沿用 layout contract 同键的声明；无声明则沿 SCALARS 区间）。
    """
    catalog, contract = _contract_catalog(module, scope)
    have = {tuple(p["path"]) for s in catalog["scopes"].values()
            for g in s["groups"] for p in g["params"]}
    scalars = getattr(module, "SCALARS", {}) or {}
    layout_by_path = {tuple(p.get("path", [])): p
                      for p in (contract.get("parameters") or [])}
    extra = []
    for key in sorted({str(v) for v in (verified_params or [])}
                      | ({"canvas_w_mm", "canvas_h_mm"} if verified_params else set())):
        if (key,) in have:
            continue
        lp = layout_by_path.get((key,))
        if isinstance(lp, dict) and lp.get("mutability") == "EDITABLE":
            extra.append({"key": key, "path": [key], "unit": lp.get("unit", "mm"),
                          "类型": "float",
                          "min": lp.get("min", float("-inf")),
                          "max": lp.get("max", float("inf"))})
            continue
        spec = scalars.get(key)
        if not (isinstance(spec, tuple) and len(spec) == 3
                and spec[0] in (float, int)):
            continue
        extra.append({"key": key, "path": [key], "unit": "mm",
                      "类型": ("int" if spec[0] is int else "float"),
                      "min": spec[1], "max": spec[2]})
    if extra:
        catalog["scopes"][scope]["groups"][0]["params"].extend(extra)
    return catalog


def safe_editable_fields(script, config=None, scope=None, target_width_mm=None):
    script = Path(script)
    module = _import_script(script)
    cfg = _load_config(module, script, config)
    if scope is None:
        scopes = getattr(module, "SCOPES", None)
        scope = (scopes[0] if scopes else "main")
    contract = _contract_isolated(module, scope)
    editable = []
    for p in contract.get("parameters", []):
        if p.get("mutability") == "EDITABLE":
            editable.append(p.get("key"))
    return sorted(set(editable)), scope, cfg

def apply_final_size(script, config=None, *, target_width_mm=None, target_axis_font_pt=8.0,
                    target_tick_font_pt=7.0, target_line_pt=0.8, mode="B",
                    scope=None, state_home=None,
                    dry_run=False, verified_params=None) -> dict:
    """Controlled final-size style application (mode B only implements; mode A diagnostic).

    G11: ``verified_params`` 为清单已验证 contract 的参数键集合（人工确认+扰动验证）；
    给出时与 layout_contract 的 EDITABLE 取并集作为安全入口。不给保持原语义。
    """
    script = Path(script)
    module = _import_script(script)
    cfg_before = _load_config(module, script, config)

    if scope is None:
        scopes = getattr(module, "SCOPES", None)
        scope = (scopes[0] if scopes else "main")

    if target_width_mm is None:
        target_width_mm = float(cfg_before.get("canvas_w_mm", 42.0))

    catalog, contract = _contract_catalog(module, scope)
    if verified_params:
        catalog = _catalog_with_verified(module, scope, verified_params)
    editable, _, _ = safe_editable_fields(script, config, scope, target_width_mm)
    editable_set = set(editable) | {str(v) for v in (verified_params or [])}

    targets = {
        "axis_font_pt": target_axis_font_pt,
        "tick_font_pt": target_tick_font_pt,
        "line_width": target_line_pt,
    }

    # refusal: no safe entry
    missing = [k for k in targets if k not in editable_set]
    applied_targets = {k: v for k, v in targets.items() if k in editable_set}
    if not applied_targets:
        reasons = {k: "no safe modification entry in layout_contract (not EDITABLE)" for k in missing}
        return {
            "source_commit_state": "NOT_WRITTEN",
            "figure_verification_state": "NOT_RUN",
            "message": "无安全修改入口: " + ", ".join(missing),
            "refused_roles": missing,
            "refusal_reasons": reasons,
            "editable_fields": sorted(editable_set),
        }

    # mode guard: A is diagnostic only; B is implementation
    if mode not in ("A", "B"):
        return {"status": "REFUSED", "source_commit_state": "NOT_WRITTEN",
                "figure_verification_state": "NOT_RUN", "message": "unknown mode"}
    if mode == "A":
        # diagnostic only: report scale formula, do not write
        before = audit_figure(script, config=config, target_width_mm=target_width_mm,
                              scope=scope)
        return {"status": "DIAGNOSTIC_ONLY", "source_commit_state": "NOT_WRITTEN",
                "figure_verification_state": "NOT_RUN", "mode": "A",
                "message": "mode A is diagnostic only; no write performed",
                "diagnostic": before}

    before = audit_figure(script, config=config, target_width_mm=target_width_mm,
                          scope=scope)

    # mode B: scale canvas width to target, preserve aspect ratio
    old_w = float(cfg_before.get("canvas_w_mm", target_width_mm))
    old_h = float(cfg_before.get("canvas_h_mm", old_w))
    scale = target_width_mm / old_w if old_w else 1.0
    new_w = float(target_width_mm)
    new_h = float(old_h * scale)

    patch_dict = {"canvas_w_mm": new_w, "canvas_h_mm": new_h}
    for key, val in applied_targets.items():
        patch_dict[key] = float(val)

    # no stacking: target values are absolute, not multiplied by old width ratio again.

    if dry_run:
        return {"status": "DRY_RUN", "source_commit_state": "NOT_WRITTEN",
                "figure_verification_state": "NOT_RUN", "planned": patch_dict}

    if config is None:
        # module default CONFIG only; use script's yaml? require config path for write
        # try sibling .yaml
        cand = script.with_suffix(".yaml")
        if not cand.is_file():
            cand = None
        config = cand
    if config is None:
        return {"status": "REFUSED", "source_commit_state": "NOT_WRITTEN",
                "figure_verification_state": "NOT_RUN",
                "message": "no config path available for write"}
    config = Path(config)

    before_bytes = config.read_bytes()
    cfg_text = config.read_text(encoding="utf-8")
    from figpact import patch as patch_mod
    patched_text = patch_mod.apply_patch_text(cfg_text, patch_dict, catalog)
    after_bytes = patched_text.encode("utf-8")

    if state_home is None:
        state_home = config.parent / ".figpact-state"
    home = Path(state_home)

    from figpact import source_writes
    change = source_writes.FileChange(str(config), __import__("hashlib").sha256(before_bytes).hexdigest(), after_bytes)
    journal = source_writes.plan_source_change([change], state_home=home, reason="final-size-apply")
    applied = source_writes.apply_source_change(journal["id"], state_home=home)
    committed = applied.get("status") == "COMMITTED"
    src_state = "COMMITTED" if committed else "NOT_WRITTEN"

    after = None
    ver_state = "NOT_RUN"
    message = "write failed"
    if committed:
        try:
            after = audit_figure(script, config=config, target_width_mm=target_width_mm,
                                 scope=scope)
            spatial = after.get("spatial_risk", [])
            if after.get("infeasible"):
                ver_state = "FAIL"
                message = "源码已写入，但规格/空间仍不可行: " + "; ".join(after.get("infeasible", []))
            elif spatial:
                ver_state = "FAIL"
                gids = [r.get("object") for r in spatial if isinstance(r, dict)]
                excess = []
                for r in spatial:
                    if isinstance(r, dict) and "overflow" in r:
                        excess.append(r["overflow"])
                message = ("源码已写入，但空间不足: objects=" + repr(gids) +
                           " overflow=" + repr(excess))
            else:
                ver_state = "PASS"
                message = "保存完成并通过验证（重新运行确认）"
        except Exception as e:
            ver_state = "ERROR"
            message = f"源码已写入，但图形验证失败：{type(e).__name__}: {e}"

    result = {
        "refused_roles": missing if 'missing' in locals() else [],
        "status": ("OK" if committed else applied.get("status", "FAILED")),
        "source_commit_state": src_state,
        "figure_verification_state": ver_state,
        "message": message,
        "script": str(script),
        "config": str(config),
        "mode": "B",
        "before": before,
        "after": after,
        "changes": {"canvas_w_mm": [old_w, new_w], "canvas_h_mm": [old_h, new_h],
                    **{k: [cfg_before.get(k), targets[k]] for k in targets}},
        "journal": applied if committed else None,
    }
    # infeasible report text
    if after is not None:
        report_bits = []
        if after.get("infeasible"):
            report_bits.append("infeasible: " + "; ".join(after["infeasible"]))
        if after.get("spatial_risk"):
            report_bits.append("spatial_risk: " + repr(after["spatial_risk"]))
        result["infeasible_report"] = "\n".join(report_bits)
    return result
