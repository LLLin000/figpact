"""Actual-page three-figure integration harness (G3-D, DERIVED standalone).

One command consumes the real saved page plus the real NMR / FTIR / XRD
providers and reports a single bounded common-X-title font search.  The
original saved page is only read: legacy figures stay SPACE_ONLY there.
A managed provider re-lays out its own canvas at the page object's stored
native_size_mm, so its PNG is a managed re-render, NEVER a byte-identical
copy of the legacy runtime/PDF asset that occupies that panel.  Managed
binding exists solely inside a DERIVED standalone snapshot with an
identical page size and identical original rectangles/neighbours.

Geometry proof: after the real rebuild the measured native extent must equal
the intended canvas, the stored crop (remapped through the stored native basis
when needed) must lie inside that extent, and the engine's measured projection
scale must match the host's crop-to-rect fill scales. Host anisotropy is
reported, not rejected as a geometry error; the common-font search separately
refuses to claim one scalar effective font where scales differ. Unprovable
geometry refuses with UNSUPPORTED_GEOMETRY and measured numbers; transforms
are never auto-corrected.

Usage:
  python examples/plate/verify_three_figures.py --layout <fig2.json> ^
      --base <tavotto root> --canvas c_48mm_manual ^
      --xrd-data-dir <real XRD data dir> --output-dir <dir>

Status split: evidence.json carries harness_status (OK /
PREREQUISITE_MISSING / HARNESS_ERROR) independent of search_status
(FEASIBLE / NO_CANDIDATE / UNSUPPORTED / UNSUPPORTED_GEOMETRY / STALE /
CONSTRAINT_VIOLATION / NOT_RUN).  Exit 0 only when harness_status is OK; the
search verdict must be read from search_status ("status" echoes it).  Exit 2
means missing prerequisites; exit 1 means harness bug or environment failure.
Parent acceptance checks both fields.

Budget: the grid holds 3 points; each point needs up to 3 figure previews
plus a 3-figure winning replay, so the typical upper bound is 12 renders.
max_renders 18 is a reservation only. The solver's actual render_count is
always reported.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)

import yaml  # noqa: E402

from figpact.frame_binding import FrameBindingError, bind_frame  # noqa: E402
from figpact.font_search import search_common_font  # noqa: E402
from figpact.layout_report import LayoutReportError, report_layout  # noqa: E402
from figpact.render_api import RenderSession  # noqa: E402
from figpact.render_contract import validate_layout  # noqa: E402
from figpact.tavotto_saved import read_saved_layout  # noqa: E402

EVIDENCE_SCHEMA = "figpact.three-figure-evidence/1"
REPO = Path(__file__).resolve().parents[2]

PANEL_NMR = "p_ucklp115"
PANEL_FTIR = "p_ti835i4w"
PANEL_XRD = "p_r9z3p04h"
TARGETS = (PANEL_NMR, PANEL_FTIR, PANEL_XRD)
SHORT = {PANEL_NMR: "nmr", PANEL_FTIR: "ftir", PANEL_XRD: "xrd"}

def nmr_peak_gids(script: Path) -> list[str]:
    """Derive required peak gids from the provider's SAMPLES_CONFIG and template."""
    tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    assignments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {
                        "SAMPLES_CONFIG", "PEAK_LABELS_TEMPLATE"}:
                    assignments[target.id] = node.value
    samples_node = assignments.get("SAMPLES_CONFIG")
    peaks_node = assignments.get("PEAK_LABELS_TEMPLATE")
    if not isinstance(samples_node, ast.List) or not isinstance(peaks_node, ast.List):
        raise ValueError("NMR provider lacks SAMPLES_CONFIG / PEAK_LABELS_TEMPLATE")
    sample_ids = []
    for row in samples_node.elts:
        if not isinstance(row, ast.Tuple) or not isinstance(row.elts[-1], ast.Constant):
            raise ValueError("NMR SAMPLES_CONFIG has an unsupported row shape")
        sample_ids.append(row.elts[-1].value)
    result = []
    for row in peaks_node.elts:
        if not isinstance(row, ast.Tuple) or len(row.elts) < 2:
            continue
        ppm_node, sample_index_node = row.elts[:2]
        if not isinstance(ppm_node, ast.Constant) or not isinstance(ppm_node.value, (int, float)):
            continue
        if not isinstance(sample_index_node, ast.Constant) or not isinstance(sample_index_node.value, int):
            continue
        tag = f"{float(ppm_node.value):.2f}".replace(".", "p")
        result.append(f"fig2_nmr.main.peak.{sample_ids[sample_index_node.value]}.{tag}")
    return result

# XRD 五个晶面都是科学锚点，但**画出来的只有三个**：源脚本在 41×46.13 mm 画布上
# 放不下 (101) 与 (110) 并静默丢弃（其导出的 SVG 里没有这两个标注）。因此必需
# 内容必须按**实际画出来的**标注来要求，否则会把源脚本本来就没画的标签
# 误报成"内容缺失"。下面的清单在运行期按真实捕获的图元核对。
REQUIRED_XRD_HKL = [
    "fig2_xrd.main.hkl.100",
    "fig2_xrd.main.hkl.101",
    "fig2_xrd.main.hkl.102",
    "fig2_xrd.main.hkl.110",
    "fig2_xrd.main.hkl.103",
]
REQUIRED_NMR_PEAKS = nmr_peak_gids(REPO / "examples" / "nmr" / "08 NMR.py")

CANDIDATE_GRID_PT = [8.5, 8.0, 7.5]
# Budget reservation only: 3 grid points, up to 3 figure previews per point
# plus a 3-figure winning replay (typical upper bound 12); the solver's
# actual render_count is the only honest spend figure, always reported.
MAX_RENDERS = 18
EXPECTED_OBJECTS = 33
EXPECTED_PANELS = 31
# Geometry tolerances: measured extent vs intended canvas, and projection
# scale vs the host's crop-to-rect scales. Absolute mm; refused otherwise.
GEOMETRY_TOL_MM = 0.05
SCALE_REL_TOL = 1e-6


def _providers() -> dict[str, dict[str, object]]:
    return {
        PANEL_NMR: {"script": REPO / "examples" / "nmr" / "08 NMR.py",
                    "config": REPO / "examples" / "nmr" / "nmr.yaml",
                    "scope": "main"},
        PANEL_FTIR: {"script": REPO / "examples" / "ftir" / "plot_ftir.py",
                     "config": REPO / "examples" / "ftir" / "ftir.yaml",
                     "scope": "main"},
        PANEL_XRD: {"script": REPO / "examples" / "xrd" / "plot_xrd.py",
                    "config": REPO / "examples" / "xrd" / "xrd.yaml",
                    "scope": "main"},
    }


def _sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_derived_layout(saved: dict, target_ids: list[str], source_sha: str) -> dict:
    """DERIVED standalone snapshot: identical page/rects, targets figpact-owned."""
    canonical = validate_layout(saved)
    known = {obj["id"]: obj for obj in canonical["objects"]}
    for tid in target_ids:
        obj = known.get(tid)
        if obj is None:
            raise ValueError(f"target {tid!r} is absent from the saved page")
        if obj.get("kind") != "panel" or obj.get("rect_mm") is None or obj.get("hidden"):
            raise ValueError(f"target {tid!r} is not a visible projectable panel")
    derived = copy.deepcopy(canonical)
    wanted = set(target_ids)
    for obj in derived["objects"]:
        if obj["id"] in wanted:
            obj["render_owner"] = "figpact"
    derived["source_mode"] = "standalone"
    extensions = dict(derived.get("extensions") or {})
    extensions["figpact_derived_three_figure"] = {
        "scenario": "DERIVED_STANDALONE",
        "source_revision": canonical.get("revision"),
        "source_layout_sha256": source_sha,
        "targets": list(target_ids),
        "note": ("Original saved page stays SPACE_ONLY and untouched; managed "
                 "binding exists only in this derived snapshot, never as the "
                 "active host page."),
    }
    derived["extensions"] = extensions
    derived.pop("revision", None)
    return validate_layout(derived)


def size_config_for_native(config: dict, native_mm: list[float]) -> dict:
    """Copy the page object's stored native canvas dimensions into temp config."""
    out = copy.deepcopy(config)
    out["canvas_w_mm"] = float(native_mm[0])
    out["canvas_h_mm"] = float(native_mm[1])
    return out


def _blocking_label(bottleneck: object) -> str | None:
    """Extract the required-content gid (XRD HKL / NMR peak) from a bottleneck string."""
    if not isinstance(bottleneck, str):
        return None
    for marker in ("fig2_xrd.main.hkl.", "fig2_nmr.main.peak."):
        hit = bottleneck.find(marker)
        if hit >= 0:
            tail = bottleneck[hit:].split(":")[0].split()[0].rstrip(".,;")
            return tail
    return None


def summarize_search(result: dict,
                     candidate_revisions: dict[tuple[str, float], list[str]] | None = None) -> dict:
    """Compact projection of a search result; frame blobs never included.

    Per-candidate failure bottlenecks keep the blocking content identity,
    the violated rule and that candidate's frame revision; they are never
    compressed into a single count/summary. Actual measured font rows and
    required-content facts travel with the winner.
    """
    attempts = []
    for attempt in result.get("attempts", []):
        panels = attempt.get("panels") or {}
        kept = {}
        for pid, info in panels.items():
            if not isinstance(info, dict):
                kept[pid] = {"status": info}
                continue
            revision = info.get("frame_revision")
            if revision is None and candidate_revisions is not None:
                point = float(attempt.get("candidate_pt") or 0)
                choices = [(abs(candidate_point - point), key)
                           for key in candidate_revisions
                           for candidate_pid, candidate_point in [key]
                           if candidate_pid == pid and abs(candidate_point - point) <= 0.02
                           and candidate_revisions[key]]
                if choices:
                    _, key = min(choices)
                    revision = candidate_revisions[key].pop(0)
            entry = {"status": info.get("status"),
                     "bottleneck": info.get("bottleneck"),
                     "blocking_content": (_blocking_label(info.get("bottleneck"))
                                          or _blocking_label(info.get("status"))),
                     "rule": info.get("code") or info.get("rule") or info.get("bottleneck"),
                     "frame_revision": revision}
            kept[pid] = {k: v for k, v in entry.items()
                         if v is not None or k == "frame_revision"}
        attempts.append({
            "candidate_pt": attempt.get("candidate_pt"),
            "variant_index": attempt.get("variant_index"),
            "status": attempt.get("status"),
            "panels": kept,
        })
    completeness = result.get("completeness") or {}
    winner = result.get("winner") or {}
    measured = winner.get("measured") or {}
    return {
        "status": result.get("status"), "reason": result.get("reason"),
        "candidate_grid_pt": result.get("candidate_grid_pt"),
        "max_renders": result.get("max_renders"),
        "render_count": result.get("render_count"),
        "searched": completeness.get("searched"),
        "grid_complete": completeness.get("declared_grid_complete"),
        "winner_pt": winner.get("candidate_pt"),
        "winner_variant": winner.get("variant_index"),
        "winner_measured_fonts": {pid: rows for pid, rows in measured.items()} if measured else {},
        "required_content_basis": (result.get("objective") or {}).get("required_content")
        or {PANEL_XRD: list(REQUIRED_XRD_HKL), PANEL_NMR: list(REQUIRED_NMR_PEAKS)},
        "attempts": attempts,
        "active_candidates": result.get("active_candidates"),
        "currentness": result.get("currentness"),
        "host": result.get("host"), "export_page": result.get("export_page"),
        "persistence": result.get("persistence"),
    }


def prove_geometry(panel: dict, measured_extent: list[float],
                   projection_evidence: dict) -> dict:
    """Prove the placement displays the cropped window at the stated size.

    Checks, from measured Frame/projection facts only: (a) measured extent
    equals the intended native canvas; (b) the stored crop lies inside the
    measured extent (G2 normalized-crop remap when stored native_size_mm
    differs); (c) the engine projection scale equals the host's independent
    crop-to-rect scales; and (d) the placed rect equals the crop window
    filled at those scales (90/270 transpose content dims). Host anisotropy
    is reported faithfully but is not itself a geometry failure; the search
    separately refuses panels whose effective font cannot be scalar.
    Refusal status is UNSUPPORTED_GEOMETRY; transforms are never auto-corrected.
    """
    native = panel.get("native_size_mm")
    rect = panel.get("rect_mm")
    rotation = panel.get("rotation_deg", 0)
    crop_stored = panel.get("crop")
    measured = [float(measured_extent[0]), float(measured_extent[1])]
    verdict: dict[str, object] = {
        "intended_canvas_mm": [float(native[0]), float(native[1])] if native else None,
        "measured_extent_mm": list(measured),
        "measured_canvas_aspect": measured[0] / measured[1] if measured[1] else None,
        "intended_canvas_aspect": (float(native[0]) / float(native[1])
                                  if native and native[1] else None),
        "rotation_deg": rotation,
        "crop_stored_mm": list(crop_stored) if crop_stored else None,
    }
    def refuse(rule: str, detail: str) -> dict:
        verdict.update({"verdict": "UNSUPPORTED_GEOMETRY", "rule": rule, "detail": detail})
        return verdict

    if native is None or rect is None or rotation is None:
        return refuse("UNKNOWN_TRANSFORM",
                     "native_size_mm, rect_mm or rotation_deg is unknown; ratio cannot be proven")
    if rotation not in (0, 0.0, 90, 90.0, 180, 180.0, 270, 270.0):
        return refuse("UNKNOWN_ROTATION", f"rotation_deg={rotation!r} is not a right angle")
    if any(not math.isfinite(v) or v <= 0 for v in
           (native[0], native[1], measured[0], measured[1])):
        return refuse("UNKNOWN_EXTENT", "non-finite or non-positive native/measured extent")
    # (b) stored crop lies inside the measured extent; G2 remaps a stored
    # crop expressed in a differing native basis onto the measured extent.
    stored_basis = list(native)
    crop = list(crop_stored) if crop_stored else [0.0, 0.0, measured[0], measured[1]]
    if crop_stored and any(abs(s - m) > GEOMETRY_TOL_MM for s, m in zip(stored_basis, measured)):
        crop = [crop_stored[0] / stored_basis[0] * measured[0],
                crop_stored[1] / stored_basis[1] * measured[1],
                crop_stored[2] / stored_basis[0] * measured[0],
                crop_stored[3] / stored_basis[1] * measured[1]]
    verdict["crop_effective_mm"] = list(crop)
    if not (crop[0] >= -GEOMETRY_TOL_MM and crop[1] >= -GEOMETRY_TOL_MM
            and crop[0] + crop[2] <= measured[0] + GEOMETRY_TOL_MM
            and crop[1] + crop[3] <= measured[1] + GEOMETRY_TOL_MM):
        return refuse("CROP_OUTSIDE_MEASURED",
                     f"crop {crop} lies outside measured extent {measured}")
    if any(abs(m - n) > GEOMETRY_TOL_MM for m, n in zip(measured, native)):
        return refuse("MEASURED_EXTENT_MISMATCH",
                     f"measured {measured} != intended canvas {list(native)}")
    # (c-d) Independently derive the host's crop-to-rect scales and compare
    # them with the measured G2 projection scales. Host placement fills the
    # crop viewport; anisotropic scale is legitimate host geometry, not a
    # geometry-proof failure. Search may still refuse scalar effective fonts.
    quarter_turn = rotation in (90, 90.0, 270, 270.0)
    content_w, content_h = (float(rect[3]), float(rect[2])) if quarter_turn \
        else (float(rect[2]), float(rect[3]))
    if crop[2] <= 0 or crop[3] <= 0:
        return refuse("UNKNOWN_CROP", f"crop has non-positive size: {crop}")
    host_scale = [content_w / crop[2], content_h / crop[3]]
    host_expected = ([crop[3] * host_scale[1], crop[2] * host_scale[0]]
                     if quarter_turn else
                     [crop[2] * host_scale[0], crop[3] * host_scale[1]])
    placed = [float(rect[2]), float(rect[3])]
    verdict.update({"host_expected_rect_wh_mm": host_expected,
                    "placed_rect_wh_mm": placed,
                    "measured_ratio_wh": [placed[0] / host_expected[0],
                                          placed[1] / host_expected[1]],
                    "placed_aspect": placed[0] / placed[1]})
    scale = (projection_evidence or {}).get("scale_xy")
    anisotropic = (projection_evidence or {}).get("anisotropic")
    host_anisotropic = abs(host_scale[0] - host_scale[1]) > 1e-9
    verdict.update({"host_crop_to_rect_scale_xy": host_scale,
                    "engine_scale_xy": list(scale) if isinstance(scale, (list, tuple)) else None,
                    "host_anisotropic": host_anisotropic,
                    "anisotropic": anisotropic})
    if (not isinstance(scale, (list, tuple)) or len(scale) != 2
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
                   for v in scale)):
        return refuse("UNKNOWN_SCALE", "projection evidence carries no finite positive scale_xy")
    scale_matches = all(abs(float(got) - expected) <= SCALE_REL_TOL * max(1.0, abs(expected))
                        for got, expected in zip(scale, host_scale))
    verdict["engine_scale_matches_host"] = scale_matches
    if not scale_matches:
        return refuse("PROJECTION_SCALE_MISMATCH",
                     f"engine scale {list(scale)} != host crop-fill scale {host_scale}")
    engine_anisotropic = abs(float(scale[0]) - float(scale[1])) > 1e-9
    if anisotropic is not engine_anisotropic:
        return refuse("ANISOTROPY_FLAG_MISMATCH",
                     f"engine anisotropic flag {anisotropic!r} disagrees with scale {list(scale)}")
    # The crop window fills the viewport. For quarter turns the content
    # dimensions are transposed before rotation, while rect_mm is final.
    if quarter_turn:
        expect_w, expect_h = crop[3] * float(scale[1]), crop[2] * float(scale[0])
    else:
        expect_w, expect_h = crop[2] * float(scale[0]), crop[3] * float(scale[1])
    placed_w, placed_h = float(rect[2]), float(rect[3])
    ratio_w = placed_w / expect_w if expect_w > 0 else float("nan")
    ratio_h = placed_h / expect_h if expect_h > 0 else float("nan")
    verdict.update({"expected_rect_wh_mm": [expect_w, expect_h],
                    "placed_rect_wh_mm": [placed_w, placed_h],
                    "measured_ratio_wh": [ratio_w, ratio_h],
                    "placed_aspect": placed_w / placed_h})
    if abs(placed_w - expect_w) > GEOMETRY_TOL_MM or abs(placed_h - expect_h) > GEOMETRY_TOL_MM:
        return refuse("PLACEMENT_RATIO_MISMATCH",
                     f"placed {[placed_w, placed_h]} != crop-window {[expect_w, expect_h]}")
    verdict.update({"verdict": "PROVEN", "rule": "HOST_CROP_FILL_PROVEN",
                    "detail": f"engine scale {list(scale)} matches host crop-fill {host_scale}"})
    return verdict


def _baseline_fonts(report: dict) -> dict:
    out = {}
    for entry in report.get("targets", []):
        roles = ((entry.get("capabilities") or {}).get("roles") or [])
        out[entry["panel_id"]] = {
            role.get("id"): role.get("effective_font_pt") for role in roles
            if isinstance(role, dict) and role.get("semantic_role") == "axis.title"}
    return out


def _baseline_font_rows(report: dict) -> dict:
    return {
        entry["panel_id"]: [dict(role) for role in
                            ((entry.get("capabilities") or {}).get("roles") or [])
                            if isinstance(role, dict) and role.get("semantic_role") == "axis.title"]
        for entry in report.get("targets", [])
    }

def track_candidate_frames(sessions: dict[str, RenderSession],
                           scales: dict[str, float]) -> dict[tuple[str, float], list[str]]:
    """Record real preview Frame revisions for candidate-specific diagnostics."""
    revisions: dict[tuple[str, float], list[str]] = {}
    for pid, session in sessions.items():
        original = session.preview

        def tracked(layout, intent, request_id, *, _pid=pid, _original=original):
            edits = intent.get("edits") or []
            point = (float(edits[-1]["value"]) * scales[_pid]
                     if edits and isinstance(edits[-1].get("value"), (int, float))
                     else None)
            try:
                receipt = _original(layout, intent, request_id)
            except Exception as exc:
                receipt = (getattr(exc, "data", {}) or {}).get("receipt") or {}
                frame_revision = (receipt.get("frame") or {}).get("frame_revision")
                if point is not None and frame_revision:
                    revisions.setdefault((_pid, point), []).append(frame_revision)
                raise
            frame_revision = (receipt.get("frame") or {}).get("frame_revision")
            if point is not None and frame_revision:
                revisions.setdefault((_pid, point), []).append(frame_revision)
            return receipt

        session.preview = tracked
    return revisions


def _measured_extent_mm(view: dict) -> list[float]:
    bounds = json.loads(view["frame"]["scene_json"])["canvas_bounds_mm"]
    return [float(bounds[2] - bounds[0]), float(bounds[3] - bounds[1])]


def harness_exit_code(harness_status: str) -> int:
    """Exit mapping is execution state only; search verdict stays in evidence."""
    return {"OK": 0, "PREREQUISITE_MISSING": 2}.get(harness_status, 1)


def _search_status(status: str) -> str:
    if status in {"FEASIBLE", "NO_CANDIDATE", "UNSUPPORTED", "STALE",
                  "CONSTRAINT_VIOLATION", "UNSUPPORTED_GEOMETRY"}:
        return status
    return "UNSUPPORTED"


def _dump(out_dir: Path, payload: dict) -> Path:
    path = out_dir / "evidence.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derived three-figure integration harness")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--canvas", required=True)
    parser.add_argument("--xrd-data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    def fail_prerequisite(message: str) -> int:
        payload = {"schema": EVIDENCE_SCHEMA, "scenario": "DERIVED_STANDALONE",
                   "harness_status": "PREREQUISITE_MISSING", "search_status": "NOT_RUN",
                   "status": "UNSUPPORTED", "reason": message, "currentness": "NOT_RUN",
                   "host": "NOT_VERIFIED", "export_page": "NOT_RUN"}
        _dump(out_dir, payload)
        print(json.dumps({"harness_status": "PREREQUISITE_MISSING",
                          "search_status": "NOT_RUN", "exit_code": 2,
                          "reason": message, "evidence": str(out_dir / "evidence.json")},
                         ensure_ascii=False), file=sys.stderr)
        return 2

    providers = _providers()
    for pid, prov in providers.items():
        for key in ("script", "config"):
            if not Path(prov[key]).is_file():
                return fail_prerequisite(
                    f"{SHORT[pid]} provider {key} is absent: {prov[key]}; "
                    "sessions are not started until all three providers land")
    xrd_data = Path(args.xrd_data_dir).expanduser().resolve()
    if not xrd_data.is_dir():
        return fail_prerequisite(f"--xrd-data-dir is not a directory: {xrd_data}")

    try:
        layout_path = Path(args.layout).expanduser().resolve()
        layout_sha_before = _sha_file(layout_path)
        saved = read_saved_layout(args.layout, base=args.base, canvas=args.canvas)
        counts = {"objects": len(saved["objects"]),
                  "panels": sum(1 for o in saved["objects"] if o.get("kind") == "panel")}
        if counts != {"objects": EXPECTED_OBJECTS, "panels": EXPECTED_PANELS}:
            payload = {"schema": EVIDENCE_SCHEMA, "scenario": "DERIVED_STANDALONE",
                       "harness_status": "OK", "search_status": "UNSUPPORTED",
                       "status": "UNSUPPORTED",
                       "reason": (f"saved page holds {counts}, not the retained "
                                  f"{EXPECTED_OBJECTS} objects / {EXPECTED_PANELS} panels"),
                       "source": {"layout": str(layout_path), "layout_sha256": layout_sha_before,
                                  "revision": saved.get("revision"),
                                  "host_revision": saved.get("host_revision"), "counts": counts},
                       "currentness": "SNAPSHOT_BOUND", "host": "NOT_VERIFIED",
                       "export_page": "NOT_RUN"}
            _dump(out_dir, payload)
            print(json.dumps({"harness_status": "OK", "search_status": "UNSUPPORTED",
                              "status": "UNSUPPORTED", "exit_code": 0,
                              "reason": payload["reason"],
                              "evidence": str(out_dir / "evidence.json")}, ensure_ascii=False),
                  file=sys.stderr)
            return 0

        official = {SHORT[pid]: _sha_file(Path(prov["config"])) for pid, prov in providers.items()}
        by_id = {obj["id"]: obj for obj in saved["objects"]}
        rects = {pid: list(by_id[pid]["rect_mm"]) for pid in TARGETS}
        natives: dict[str, list[float] | None] = {}
        for pid in TARGETS:
            raw_native = by_id[pid].get("native_size_mm")
            natives[pid] = [float(raw_native[0]), float(raw_native[1])] if raw_native else None

        derived = build_derived_layout(saved, list(TARGETS), layout_sha_before)
        neighbour_ok = all(
            next(o for o in derived["objects"] if o["id"] == obj["id"]) == obj
            for obj in saved["objects"] if obj["id"] not in TARGETS)
        rects_ok = all(
            next(o for o in derived["objects"] if o["id"] == pid)["rect_mm"] == rects[pid]
            for pid in TARGETS)

        cfg_dir = out_dir / "configs"
        cfg_dir.mkdir(exist_ok=True)
        temp_configs: dict[str, Path] = {}
        canvas_set: dict[str, list[float]] = {}
        for pid in TARGETS:
            prov = providers[pid]
            raw = yaml.safe_load(Path(prov["config"]).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return fail_prerequisite(f"{SHORT[pid]} config root is not a mapping")
            if natives[pid] is None:
                return fail_prerequisite(
                    f"{SHORT[pid]} page object stores no native_size_mm; refusing to guess canvas")
            sized = size_config_for_native(raw, natives[pid])
            if pid == PANEL_XRD:
                if "data_dir" not in sized:
                    return fail_prerequisite("xrd.yaml has no data_dir key; refusing to guess schema")
                sized["data_dir"] = str(xrd_data)
            dest = cfg_dir / f"{SHORT[pid]}.yaml"
            dest.write_text(yaml.safe_dump(sized, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
            temp_configs[pid] = dest
            canvas_set[pid] = [sized["canvas_w_mm"], sized["canvas_h_mm"]]

        sessions: dict[str, RenderSession] = {}
        bindings: dict[str, dict[str, object]] = {}
        try:
            for pid in TARGETS:
                prov = providers[pid]
                sessions[pid] = RenderSession(
                    prov["script"], temp_configs[pid], str(prov["scope"]),
                    output_dir=out_dir)
                bindings[pid] = {"script": str(Path(prov["script"]).resolve()),
                                 "config": str(temp_configs[pid].resolve()),
                                 "scope": str(prov["scope"]), "overrides_present": False}
            views = {pid: sessions[pid].snapshot() for pid in TARGETS}
            nmr_scene = json.loads(views[PANEL_NMR]["frame"]["scene_json"])
            captured_nmr = sorted({
                node.get("id") or node.get("gid") for node in nmr_scene.get("nodes", [])
                if (node.get("id") or node.get("gid") or "").startswith("fig2_nmr.main.peak.")
                and node.get("visible") is True
            })
            xrd_scene = json.loads(views[PANEL_XRD]["frame"]["scene_json"])
            captured_xrd = sorted({
                node.get("id") or node.get("gid") for node in xrd_scene.get("nodes", [])
                if (node.get("id") or node.get("gid") or "").startswith("fig2_xrd.main.hkl.")
                and node.get("visible") is True
            })
            required = {PANEL_XRD: captured_xrd,
                        PANEL_NMR: captured_nmr or list(REQUIRED_NMR_PEAKS)}
            report = report_layout(
                derived, list(TARGETS), sessions, expected_revision=derived["revision"],
                source_bindings=bindings, required_content=required,
                refresh_layout=lambda: derived)
            frames = {pid: {"frame_revision": views[pid]["frame"]["frame_revision"],
                            "candidate_revision": views[pid]["frame"]["candidate_revision"],
                            "source_revision": views[pid]["frame"]["source_revision"],
                            "base_config_revision": views[pid]["frame"]["base_config_revision"],
                            "png_sha256": views[pid]["frame"]["png_sha256"],
                            "scene_sha256": views[pid]["frame"]["scene_sha256"],
                            "measured_extent_mm": _measured_extent_mm(views[pid]),
                            "science_verified": (views[pid]["frame"].get("science") or {}).get("verified"),
                            "science_digest": (views[pid]["frame"].get("science") or {}).get("digest")}
                      for pid in TARGETS}
            geometry = {}
            for pid in TARGETS:
                bound = bind_frame(derived, pid, views[pid]["frame"], request_id=0)
                geometry[pid] = prove_geometry(
                    by_id[pid], frames[pid]["measured_extent_mm"],
                    bound["projection"]["evidence"])

            intent = {"schema": "figpact.font-search/1", "role": "axis.title",
                      "axis": "x", "axes_context": "root",
                      "candidate_pt": list(CANDIDATE_GRID_PT), "tolerance_pt": 0.02,
                      "max_renders": MAX_RENDERS, "allow_coupled": True,
                      "variants": [{}], "required_content": required}
            if all(info["verdict"] == "PROVEN" for info in geometry.values()):
                candidate_revisions = track_candidate_frames(
                    sessions, {pid: geometry[pid]["engine_scale_xy"][0] for pid in TARGETS})
                result = search_common_font(
                    derived, sessions, intent, expected_revision=derived["revision"],
                    source_bindings=bindings, refresh_layout=lambda: derived)
                summary = summarize_search(result, candidate_revisions)
            else:
                failed = [pid for pid, info in geometry.items() if info["verdict"] != "PROVEN"]
                reason = "geometry cannot be proven: " + "; ".join(
                    f"{pid} {geometry[pid]['rule']}: {geometry[pid]['detail']}" for pid in failed)
                result = {"candidates": {}}
                summary = {"status": "UNSUPPORTED_GEOMETRY", "reason": reason,
                           "render_count": 0, "winner_pt": None, "winner_variant": None,
                           "attempts": [], "winner_measured_fonts": {},
                           "required_content_basis": required}
            summary["required_content_basis"] = required

            previews: dict[str, str] = {}
            cancelled: dict[str, str | None] = {}
            if summary["status"] == "FEASIBLE":
                prev_dir = out_dir / "previews"
                prev_dir.mkdir(exist_ok=True)
                for pid, receipt in result["candidates"].items():
                    name = f"{SHORT[pid]}.png"
                    (prev_dir / name).write_bytes(
                        base64.b64decode(receipt["frame"]["png_base64"]))
                    previews[pid] = f"previews/{name}"
                for pid, receipt in result["candidates"].items():
                    try:
                        sessions[pid].cancel(receipt["candidate_id"])
                        cancelled[pid] = receipt["candidate_id"]
                    except Exception as exc:  # noqa: BLE001 - recorded, then closed anyway
                        cancelled[pid] = f"CANCEL_ISSUE:{type(exc).__name__}:{exc}"
            pending_clear = {pid: sessions[pid].snapshot().get("pending") is None
                             for pid in TARGETS}
        finally:
            closed = {}
            for pid, session in sessions.items():
                try:
                    closed[pid] = session.close()
                except Exception as exc:  # noqa: BLE001 - close is best-effort
                    closed[pid] = {"status": f"CLOSE_ISSUE:{type(exc).__name__}:{exc}"}

        payload = {"schema": EVIDENCE_SCHEMA, "scenario": "DERIVED_STANDALONE",
            "harness_status": "OK", "search_status": summary["status"],
            "status": summary["status"], "reason": summary["reason"],
            "currentness": "SNAPSHOT_BOUND",
            "source": {"layout": str(layout_path), "layout_sha256": layout_sha_before,
                       "revision": saved.get("revision"),
                       "host_revision": saved.get("host_revision"),
                       "canvas": args.canvas, "counts": counts},
            "derived": {"revision": derived.get("revision"), "targets": list(TARGETS),
                        "marker": "DERIVED_STANDALONE_THREE_FIGURE"},
            "panels": {pid: {"rect_mm": rects[pid], "native_size_mm": natives[pid],
                             "canvas_set_mm": canvas_set[pid],
                             "geometry_proof": geometry[pid],
                             "managed_render_is_legacy_asset_copy": False,
                             "temp_config": str(temp_configs[pid]),
                             "frame": frames[pid]} for pid in TARGETS},
            "baseline_axis_title_fonts": _baseline_fonts(report),
            "baseline_measured_font_rows": _baseline_font_rows(report),
            "required_content_template_ids": {
                PANEL_XRD: list(REQUIRED_XRD_HKL),
                PANEL_NMR: list(REQUIRED_NMR_PEAKS)},
            "captured_nmr_peak_ids": captured_nmr,
            "captured_xrd_hkl_ids": captured_xrd,
            "required_content_note": (
                "required content is the set actually captured as visible text; "
                "source-dropped labels stay scientific anchors without a drawn artist"),
            "search": summary,
            "previews": previews,
            "invariants": {
                "original_rects_identical": bool(rects_ok),
                "untouched_neighbour_objects_identical": bool(neighbour_ok),
                "layout_bytes_unchanged": _sha_file(layout_path) == layout_sha_before,
                "official_configs_unchanged": all(
                    _sha_file(Path(providers[pid]["config"])) == official[SHORT[pid]]
                    for pid in TARGETS),
            },
            "sessions": {pid: {"scope": bindings[pid]["scope"],
                               "cancelled_winner": cancelled.get(pid),
                               "pending_cleared_before_close": pending_clear.get(pid),
                               "close": closed.get(pid)}
                         for pid in TARGETS},
            "report_status": report.get("status"),
            "budget": {"candidate_grid_points": len(CANDIDATE_GRID_PT),
                       "per_point_figure_previews_up_to": len(TARGETS),
                       "winning_replay_figures": len(TARGETS),
                       "typical_upper_bound": len(CANDIDATE_GRID_PT) * len(TARGETS) + len(TARGETS),
                       "reservation_max_renders": MAX_RENDERS,
                       "actual_render_count": summary.get("render_count")},
            "limits": ["SNAPSHOT_BOUND only; derived snapshot is not an active-page lock",
                       "original saved page unchanged; legacy figures remain SPACE_ONLY there",
                       "managed provider output is a re-render, not a byte-identical copy of the legacy runtime/PDF asset",
                       "host acceptance NOT_VERIFIED; official page export NOT_RUN",
                       "no G4 page/save transaction and no G5 export claimed",
                       "winner previews are evidence bytes only, not a published figure"],
        }
        if not (rects_ok and neighbour_ok and payload["invariants"]["layout_bytes_unchanged"]
                and payload["invariants"]["official_configs_unchanged"]):
            payload["search_status"] = payload["status"] = "UNSUPPORTED"
            payload["reason"] = ("post-run invariant failed: "
                                 + json.dumps(payload["invariants"], sort_keys=True))
        _dump(out_dir, payload)
        print(json.dumps({"harness_status": payload["harness_status"],
                          "search_status": payload["search_status"],
                          "status": payload["search_status"], "exit_code": 0,
                          "reason": payload["reason"],
                          "render_count": summary.get("render_count"),
                          "winner_pt": summary.get("winner_pt"),
                          "evidence": str(out_dir / "evidence.json")}, ensure_ascii=False))
        return 0
    except LayoutReportError as exc:
        search_status = _search_status(exc.status)
        reason = str(exc)
        if "nonuniform native/page scale" in reason:
            anisotropic = [pid for pid, proof in locals().get("geometry", {}).items()
                           if proof.get("host_anisotropic")]
            if anisotropic:
                reason = f"ANISOTROPIC_HOST_CROP {anisotropic}: {reason}"
        available = locals()
        report_evidence = available.get("report")
        payload = {"schema": EVIDENCE_SCHEMA, "harness_status": "OK",
                   "search_status": search_status, "status": search_status,
                   "reason": reason,
                   "measured_frames": available.get("frames", {}),
                   "geometry_proofs": available.get("geometry", {}),
                   "baseline_axis_title_fonts": (_baseline_fonts(report_evidence)
                                                 if isinstance(report_evidence, dict) else {}),
                   "baseline_measured_font_rows": (_baseline_font_rows(report_evidence)
                                                   if isinstance(report_evidence, dict) else {}),
                   "required_content": available.get("required"),
                   "search": {"status": search_status, "reason": reason,
                              "render_count": 0, "attempts": [],
                              "winner_measured_fonts": {}},
                   "currentness": "SNAPSHOT_BOUND",
                   "host": "NOT_VERIFIED", "export_page": "NOT_RUN"}
        _dump(out_dir, payload)
        print(json.dumps({"harness_status": "OK", "search_status": search_status,
                          "status": search_status, "reason": reason,
                          "render_count": None,
                          "evidence": str(out_dir / "evidence.json")}, ensure_ascii=False),
              file=sys.stderr)
        return 0
    except FrameBindingError as exc:
        search_status = _search_status(exc.status)
        payload = {"schema": EVIDENCE_SCHEMA, "harness_status": "OK",
                   "search_status": search_status, "status": search_status,
                   "reason": str(exc), "currentness": "SNAPSHOT_BOUND",
                   "host": "NOT_VERIFIED", "export_page": "NOT_RUN"}
        _dump(out_dir, payload)
        print(json.dumps({"harness_status": "OK", "search_status": search_status,
                          "status": search_status, "reason": str(exc),
                          "render_count": None,
                          "evidence": str(out_dir / "evidence.json")}, ensure_ascii=False),
              file=sys.stderr)
        return 0
    except Exception as exc:  # noqa: BLE001 - harness bug or environment failure
        payload = {"schema": EVIDENCE_SCHEMA, "harness_status": "HARNESS_ERROR",
                   "search_status": "NOT_RUN", "status": "NOT_RUN",
                   "reason": f"{type(exc).__name__}: {exc}",
                   "currentness": "SNAPSHOT_BOUND",
                   "host": "NOT_VERIFIED", "export_page": "NOT_RUN"}
        _dump(out_dir, payload)
        print(json.dumps({"harness_status": "HARNESS_ERROR", "search_status": "NOT_RUN",
                          "exit_code": 1, "reason": payload["reason"],
                          "evidence": str(out_dir / "evidence.json")}, ensure_ascii=False),
              file=sys.stderr)
        return harness_exit_code("HARNESS_ERROR")


if __name__ == "__main__":
    sys.exit(main())
