"""Bounded common effective-font search (G3-C, read-only + previews, no save)."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any, TypeGuard

from .frame_binding import FrameBindingError, bind_frame
from .layout_report import LayoutReportError, report_layout
from .render_api import RenderError, RenderSession
from .render_contract import validate_layout
from .spatial_report import spatial_report

SCHEMA = "figpact.font-search/1"
RESULT_SCHEMA = "figpact.font-search-result/1"

SUPPORTED_ROLES = ("axis.title", "axis.tick", "legend")
SUPPORTED_CONTEXTS = ("root", "inset")

MAX_POINTS = 128
MAX_VARIANTS = 64
MAX_RENDERS = 512

def _is_num(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _fail_invalid(message: str) -> LayoutReportError:
    return LayoutReportError("INVALID", message)


def _validate_intent(intent: Any, targets: list[str]) -> dict[str, Any]:
    if not isinstance(intent, dict):
        raise _fail_invalid("intent must be a dict")
    allowed = {"schema", "role", "axis", "axes_context", "candidate_pt",
               "tolerance_pt", "max_renders", "allow_coupled", "variants", "required_content"}
    extra = set(intent) - allowed
    if extra:
        raise _fail_invalid(f"intent has unknown keys: {sorted(extra)}")
    if intent.get("schema") != SCHEMA:
        raise _fail_invalid(f"intent schema must be {SCHEMA!r}")
    role = intent.get("role")
    if not isinstance(role, str) or role not in SUPPORTED_ROLES:
        raise _fail_invalid(f"intent role must be one of {list(SUPPORTED_ROLES)}")
    axis = intent.get("axis", None)
    if axis is not None and axis not in ("x", "y"):
        raise _fail_invalid("intent axis must be 'x', 'y' or null")
    if role == "legend" and axis is not None:
        raise _fail_invalid("legend search axis must be null")
    context = intent.get("axes_context", "root")
    if context not in SUPPORTED_CONTEXTS:
        raise _fail_invalid("intent axes_context must be 'root' or 'inset'; unknown cannot be guessed")
    raw_grid = intent.get("candidate_pt")
    if (not isinstance(raw_grid, (list, tuple)) or not raw_grid or len(raw_grid) > MAX_POINTS
            or any(not _is_num(v) or float(v) <= 0 for v in raw_grid)):
        raise _fail_invalid(
            f"candidate_pt must be a non-empty list of finite positive numbers (<= {MAX_POINTS})")
    grid = [float(v) for v in raw_grid]
    if len(set(grid)) != len(grid):
        raise _fail_invalid("candidate_pt values must be unique; no dense implicit grid is built")
    grid.sort(reverse=True)
    tolerance = intent.get("tolerance_pt", 0.02)
    if not _is_num(tolerance) or float(tolerance) <= 0:
        raise _fail_invalid("tolerance_pt must be a finite number > 0")
    tolerance = float(tolerance)
    max_renders = intent.get("max_renders", 24)
    if isinstance(max_renders, bool) or not isinstance(max_renders, int):
        raise _fail_invalid("max_renders must be an int")
    if not 1 <= max_renders <= MAX_RENDERS:
        raise _fail_invalid(f"max_renders must be 1..{MAX_RENDERS}")
    allow = intent.get("allow_coupled", False)
    if not isinstance(allow, bool):
        raise _fail_invalid("allow_coupled must be bool")
    raw_variants = intent.get("variants", [{}])
    if (not isinstance(raw_variants, (list, tuple)) or not raw_variants
            or len(raw_variants) > MAX_VARIANTS):
        raise _fail_invalid(f"variants must be a non-empty list (<= {MAX_VARIANTS}) of panel->edits maps")
    variants: list[dict[str, list[dict[str, Any]]]] = []
    for variant in raw_variants:
        if not isinstance(variant, dict):
            raise _fail_invalid("each variant must be a dict panel_id -> [edits]")
        clean: dict[str, list[dict[str, Any]]] = {}
        for panel_id, edits in variant.items():
            if not isinstance(panel_id, str) or not panel_id or panel_id not in targets:
                raise _fail_invalid(f"variant panel {panel_id!r} is not a search target")
            if not isinstance(edits, (list, tuple)) or not edits:
                raise _fail_invalid(f"variant[{panel_id!r}] must be a non-empty edit list")
            seen: set[str] = set()
            clean_edits = []
            for edit in edits:
                if not isinstance(edit, dict) or set(edit) != {"control_id", "value"}:
                    raise _fail_invalid(f"variant[{panel_id!r}] edits need control_id/value only")
                cid, value = edit.get("control_id"), edit.get("value")
                if not isinstance(cid, str) or not cid.strip():
                    raise _fail_invalid(f"variant[{panel_id!r}] control_id must be a non-empty str")
                if cid in seen:
                    raise _fail_invalid(f"variant[{panel_id!r}] has duplicate control {cid!r}")
                seen.add(cid)
                if not _is_num(value):
                    raise _fail_invalid(f"variant[{panel_id!r}] value for {cid!r} must be finite non-bool")
                clean_edits.append({"control_id": cid, "value": value})
            clean[panel_id] = clean_edits
        variants.append(clean)
    raw_required = intent.get("required_content", {})
    if not isinstance(raw_required, dict):
        raise _fail_invalid("required_content must map panel_id -> [confirmed ids]")
    required: dict[str, list[str]] = {}
    for panel_id, ids in raw_required.items():
        if not isinstance(panel_id, str) or panel_id not in targets:
            raise _fail_invalid(f"required_content panel {panel_id!r} is not a search target")
        if (not isinstance(ids, (list, tuple)) or not ids
                or any(not isinstance(g, str) or not g for g in ids)
                or len(set(ids)) != len(ids)):
            raise _fail_invalid(f"required_content[{panel_id!r}] must hold unique nonempty strings")
        required[panel_id] = list(ids)
    return {"role": role, "axis": axis, "axes_context": context, "candidate_pt": grid,
            "tolerance_pt": tolerance, "max_renders": max_renders, "allow_coupled": allow,
            "variants": variants, "required_content": required}


def _result(status: str, reason: str, *, canonical: dict[str, Any] | None,
            objective: dict[str, Any] | None, grid: list[float], tolerance: float,
            max_renders: int, render_count: int, attempts: list[dict[str, Any]],
            panels: dict[str, dict[str, str]], candidates: dict[str, Any],
            winner: dict[str, Any] | None, searched: int, complete: bool,
            max_evidence: str, baseline: dict[str, Any], active: bool,
            producer_rechecked: bool) -> dict[str, Any]:
    revision = canonical["revision"] if canonical else ""
    mode = canonical["source_mode"] if canonical else ""
    return {
        "schema": RESULT_SCHEMA, "status": status, "reason": reason,
        "snapshot_revision": revision, "source_mode": mode, "currentness": "SNAPSHOT_BOUND",
        "producer_rechecked": producer_rechecked,
        "objective": objective or {},
        "candidate_grid_pt": list(grid), "tolerance_pt": tolerance, "max_renders": max_renders,
        "render_count": render_count, "attempts": attempts, "panels": panels,
        "candidates": candidates, "winner": winner,
        "completeness": {"declared_grid_complete": complete, "searched": searched,
                         "maximum_evidence": max_evidence},
        "baseline": baseline, "active_candidates": active,
        "persistence": "NOT_WRITTEN", "host": "NOT_VERIFIED", "export_page": "NOT_RUN",
        "limits": ["SNAPSHOT_BOUND only; no page lock, save, commit, export or host acceptance",
                   "first feasible descending grid point is best among checked declared "
                   "candidates, NOT a global optimum",
                   "effective point sizes are measured from actual frames, never from "
                   "parameter names or config fallbacks",
                   "render_count counts every real session.preview call, including "
                   "variant probes and the winning replay; Matplotlib draw count is not claimed"],
    }


def _is_stale_error(error: Exception) -> bool:
    status = getattr(error, "status", "")
    return status in ("STALE_REVISION", "REFRESH_REQUIRED", "STALE", "SUPERSEDED")


def _cancel_own(sessions: Mapping[str, RenderSession], owned: dict[str, str]) -> list[str]:
    issues = []
    for panel_id, candidate_id in list(owned.items()):
        try:
            sessions[panel_id].cancel(candidate_id)
        except RenderError as error:
            if not _is_stale_error(error) and error.status not in (
                    "CANDIDATE_UNKNOWN", "SUPERSEDED", "CANCELLED"):
                issues.append(f"{panel_id}:{error.status}:{error}")
    owned.clear()
    return issues


def _scene_by_id(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        nodes = json.loads(frame["scene_json"])["nodes"]
    except (KeyError, TypeError, ValueError):
        return {}
    out = {}
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            out[node["id"]] = node
            if isinstance(node.get("gid"), str):
                out.setdefault(node["gid"], node)
    return out


def _projection_by_id(projection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = (projection or {}).get("nodes")
    out = {}
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            out[node["id"]] = node
    return out


def _is_text_node(raw: dict[str, Any] | None) -> bool:
    if not isinstance(raw, dict):
        return False
    if raw.get("is_text") is True:
        return True
    if raw.get("type") == "text":
        return True
    return raw.get("artist_type") == "Text"


def _select_panel(capability: dict[str, Any], raw_by_id: dict[str, dict[str, Any]],
                  *, role: str, axis: str | None, context: str) -> tuple[dict[str, Any] | None, str]:
    roles = capability.get("roles") or []
    couplings = {c.get("control_id"): c for c in (capability.get("coupling") or [])
                 if isinstance(c, dict)}
    shortlisted = []
    for item in roles:
        if not isinstance(item, dict):
            continue
        if item.get("semantic_role") != role or item.get("evidence") != "artist_identity":
            continue
        if axis is not None and item.get("axis") != axis:
            continue
        if item.get("axes_context") != context:
            continue
        if item.get("visible") is False:
            continue
        if item.get("identity_stability") != "stable" or item.get("gid") != item.get("id"):
            return None, f"UNMIGRATED_IDENTITY:{item.get('id')}"
        shortlisted.append(item)
    if not shortlisted:
        return None, "NO_GROUP_MEMBERS"
    # Visible measured uniform-scale text members only; Legend container is not text.
    members = []
    for item in shortlisted:
        raw = raw_by_id.get(item.get("id"))
        if not _is_text_node(raw):
            continue
        if not (item.get("visible") is True and item.get("measured") is True):
            return None, f"UNMEASURED_MEMBER:{item.get('id')}"
        if item.get("final_rect_mm") is None or item.get("font_reason") is not None:
            reason = item.get("font_reason") or "SCALE_UNAVAILABLE"
            return None, f"{reason}:{item.get('id')}"
        controls = item.get("font_controls") or []
        usable = [c for c in controls if isinstance(c, dict) and c.get("editable") is True]
        if len(usable) != 1 or len(controls) != 1:
            return None, f"UNBOUND_FONT_CONTROL:{item.get('id')}"
        members.append((item, usable[0]))
    if not members:
        return None, "LEGEND_CONTAINER_ONLY"
    control_ids = {control["control_id"] for _, control in members}
    if len(control_ids) != 1:
        return None, "MULTIPLE_FONT_CONTROLS"
    control_id = next(iter(control_ids))
    coupling = couplings.get(control_id)
    if not isinstance(coupling, dict):
        return None, f"UNBOUND_FONT_CONTROL:{control_id}"
    if coupling.get("unmatched_ids"):
        return None, f"UNMIGRATED_COUPLING:{control_id}"
    affected = list(coupling.get("affected_ids") or [])
    selected_ids = sorted(item["id"] for item, _ in members)
    return {"member_ids": selected_ids, "control_id": control_id,
            "control_min": members[0][1].get("min"), "control_max": members[0][1].get("max"),
            "affected_ids": affected,
            "coupling_groups": coupling.get("affected_role_groups") or []}, ""


def _coupled_extras(selection: dict[str, Any],
                    raw_by_id: dict[str, dict[str, Any]]) -> tuple[list[str], str]:
    selected = set(selection["member_ids"])
    extras = []
    for other in selection["affected_ids"]:
        if other in selected:
            continue
        raw = raw_by_id.get(other)
        if raw is None:
            return [], f"UNMEASURED_COUPLING:{other}"
        if not _is_text_node(raw):
            continue  # known non-text group container (e.g. Legend box) is fine
        if raw.get("visible") is False:
            continue
        if raw.get("visible") is not True:
            return [], f"UNMEASURED_COUPLING:{other}"
        extras.append(other)
    return sorted(extras), ""


def _spatial_bottleneck(spatial: dict[str, Any], panel_id: str,
                        relevant: set[str]) -> str | None:
    # Broad POTENTIAL_OVERLAP of full panel rects is informational (white
    # canvas can overlap); only relevant measured content envelopes, proven
    # clipping/outside/required failures, or unknown relevant geometry block.
    for finding in spatial.get("findings") or []:
        if not isinstance(finding, dict) or panel_id not in (finding.get("panels") or []):
            continue
        kind = finding.get("kind")
        if finding.get("violation") is True:
            return str(kind)
        if kind == "POTENTIAL_NEIGHBOUR_ENVELOPE_OVERLAP":
            nodes = set(finding.get("nodes") or [])
            if nodes & relevant:
                return str(kind)
        if kind in ("REQUIRED_CONTENT_UNVERIFIED", "UNMEASURED_CONTENT",
                    "MEASUREMENT_MISSING", "SCIENCE_UNVERIFIED"):
            nodes = set(finding.get("nodes") or finding.get("objects") or [])
            if (nodes & relevant) or panel_id in (finding.get("objects") or []):
                return str(kind)
    return None




def search_common_font(layout: dict[str, Any], sessions: Mapping[str, RenderSession],
                       intent: dict[str, Any], *, expected_revision: str,
                       source_bindings: Mapping[str, dict[str, Any]] | None = None,
                       refresh_layout: Any = None) -> dict[str, Any]:
    """Search an explicit finite grid using caller-exclusive hot sessions.

    All edits are absolute Native previews. Only the final replay remains
    pending; no save, export or host-page lock is performed.
    """
    if (not isinstance(sessions, Mapping) or len(sessions) < 2
            or any(not isinstance(pid, str) or not pid for pid in sessions)):
        raise _fail_invalid("sessions must map 2+ nonempty panel ids to RenderSessions")
    targets = sorted(sessions)
    if (len({id(s) for s in sessions.values()}) != len(targets)
            or any(not isinstance(s, RenderSession) for s in sessions.values())):
        raise _fail_invalid("sessions must hold different RenderSession instances")
    spec = _validate_intent(intent, targets)
    canonical = validate_layout(layout)
    grid, tolerance, budget = spec["candidate_pt"], spec["tolerance_pt"], spec["max_renders"]
    objective = {key: spec[key] for key in ("role", "axis", "axes_context")}
    attempts: list[dict[str, Any]] = []
    baseline: dict[str, Any] = {}
    owned: dict[str, str] = {}
    cleanup_issues: list[str] = []
    render_count = searched = 0
    keep_winner = False
    n = len(targets)

    def finish(status, reason, candidates=None, winner=None):
        return _result(
            status, reason, canonical=canonical, objective=objective, grid=grid,
            tolerance=tolerance, max_renders=budget, render_count=render_count,
            attempts=attempts, panels={pid: {"status": status, "bottleneck": reason} for pid in targets},
            candidates=candidates or {}, winner=winner, searched=searched,
            complete=searched == len(grid) * len(spec["variants"]),
            max_evidence="descending explicit grid only; no mathematical global optimum",
            baseline=baseline, active=status == "FEASIBLE",
            producer_rechecked=refresh_layout is not None) | {"cleanup_issues": cleanup_issues}

    def check_page():
        if refresh_layout is not None:
            try:
                current = validate_layout(refresh_layout())
            except (ValueError, OSError) as error:
                raise LayoutReportError("STALE", f"page producer cannot revalidate: {error}") from error
            if current["revision"] != expected_revision:
                raise LayoutReportError("STALE", "page or referenced resource facts changed")

    def check_sessions(expected=None):
        for pid in targets:
            view = sessions[pid].snapshot()
            frame = view["frame"]
            if pid in baseline:
                for key in ("source_revision", "base_config_revision"):
                    if frame.get(key) != baseline[pid][key]:
                        raise LayoutReportError("STALE", f"{pid}:{key} changed")
            pending = view.get("pending") or {}
            if pending.get("candidate_id") != owned.get(pid):
                raise LayoutReportError("STALE", f"{pid}:pending candidate ownership changed")
            if expected is not None and (
                    pending.get("candidate_id") != expected[pid]["candidate_id"]
                    or frame["frame_revision"] != expected[pid]["frame"]["frame_revision"]):
                raise LayoutReportError("STALE", f"{pid}:winning frame was superseded")

    def preview(pid, edits, content, *, replay=False):
        nonlocal render_count
        # Reserve a whole winning replay; failed preview calls also consume budget.
        if render_count + 1 + (0 if replay else n) > budget:
            raise LayoutReportError("NO_CANDIDATE", "preview budget exhausted; replay was reserved")
        check_page()
        # preview validates this session's live source; all sessions are checked
        # at batch boundaries and after replay, not redundantly before each draw.
        render_count += 1
        result = sessions[pid].preview(canonical, {
            "schema": "figpact.intent/1", "panel_id": pid, "edits": edits,
            "fit_canvas": False, "required_content": content, "preserve": ["science", "view"]},
            f"font-search-{render_count}")
        owned[pid] = result["candidate_id"]
        return result

    def measure(results, point):
        bounds, measured = {}, {}
        for pid, result in results.items():
            frame = result["frame"]
            science = frame.get("science") or {}
            if science.get("verified") is not True or science.get("digest") != baseline[pid]["science_digest"]:
                raise RenderError("SCIENCE_VIOLATION", f"{pid}:scientific payload changed")
            if any(frame.get(key) != baseline[pid][key] for key in ("source_revision", "base_config_revision")):
                raise LayoutReportError("STALE", f"{pid}:source changed during preview")
            bound = bind_frame(canonical, pid, frame, render_count)
            bounds[pid] = bound
            raw, projected = _scene_by_id(frame), _projection_by_id(bound["projection"])
            rows = []
            for member in selections[pid]["member_ids"]:
                node, placed = raw.get(member), projected.get(member)
                if node is None or placed is None or node.get("visible") is not True:
                    raise RenderError("CONSTRAINT_VIOLATION", f"{pid}:selection disappeared:{member}")
                scale, font = placed.get("scale_xy"), node.get("font_size_pt")
                if (not _is_num(font) or not isinstance(scale, list) or len(scale) != 2
                        or any(not _is_num(v) or v <= 0 for v in scale)
                        or placed.get("anisotropic") is not False):
                    raise RenderError("CONSTRAINT_VIOLATION", f"{pid}:font scale unavailable:{member}")
                effective = float(font) * float(scale[0])
                if not placed.get("measurable") or abs(effective - point) > tolerance:
                    raise RenderError("CONSTRAINT_VIOLATION", f"{pid}:effective font mismatch:{member}:{effective}")
                rows.append({"id": member, "source_font_pt": float(font), "effective_font_pt": effective})
            measured[pid] = rows
            spatial = spatial_report(canonical, [pid], {pid: {
                "frame": frame, "projection": bound["projection"], "binding": bound["binding"],
                "editable": True}}, required_content={pid: required[pid]})
            relevant = {key for key, node in raw.items()
                        if node.get("visible") is True and not node.get("structural")}
            blocker = _spatial_bottleneck(spatial, pid, relevant)
            if blocker:
                raise RenderError("CONSTRAINT_VIOLATION", f"{pid}:{blocker}")
            unknown = [o["id"] for o in spatial["targets"][pid]["precheck"]["neighbors"]
                       if not o["hidden"] and o["relation"] == "unknown"]
            if unknown:
                raise LayoutReportError("UNSUPPORTED", f"{pid}:unknown neighbour geometry:{unknown}")
        return bounds, measured

    def expected_rejection(error):
        if _is_stale_error(error):
            raise LayoutReportError("STALE", str(error)) from error
        if error.status in ("SCIENCE_VIOLATION", "QA_BLOCKED", "REQUIRED_CONTENT_MISSING",
                            "OUT_OF_RANGE", "CONSTRAINT_VIOLATION"):
            return True
        # Structured trial refusals are candidate results; unexplained renderer
        # or program failures are not evidence of layout infeasibility.
        receipt = error.data.get("receipt") or {}
        return error.status == "NATIVE_REJECTED" and receipt.get("status") in (
            "REJECTED", "BLOCKED", "REFUSED", "CONSTRAINT_VIOLATION")

    try:
        if expected_revision != canonical["revision"]:
            raise LayoutReportError("STALE", "requested revision differs from the snapshot")
        for pid in targets:
            if sessions[pid].snapshot().get("pending"):
                raise _fail_invalid(f"{pid}:session already has a pending candidate")
        report = report_layout(canonical, targets, sessions, expected_revision=expected_revision,
                               source_bindings=source_bindings, refresh_layout=refresh_layout)
        entries = {entry["panel_id"]: entry for entry in report["targets"]}
        selections, controls, scales, required = {}, {}, {}, {}
        for pid in targets:
            entry, view = entries[pid], sessions[pid].snapshot()
            frame = view["frame"]
            if frame["frame_revision"] != entry.get("binding", {}).get("frame_revision"):
                raise LayoutReportError("UNSUPPORTED", f"{pid}:no stable managed frame")
            raw = _scene_by_id(frame)
            selection, problem = _select_panel(entry.get("capabilities", {}), raw,
                                              role=spec["role"], axis=spec["axis"], context=spec["axes_context"])
            if selection is None:
                raise LayoutReportError("UNSUPPORTED", f"{pid}:{problem}")
            extras, problem = _coupled_extras(selection, raw)
            if problem or (extras and not spec["allow_coupled"]):
                raise LayoutReportError("UNSUPPORTED", f"{pid}:{problem or 'COUPLING_REFUSED'}:{extras}")
            selections[pid] = selection
            controls[pid] = {c["control_id"]: c for c in view["controls"]}
            bound = bind_frame(canonical, pid, frame, 0)
            scale = bound["projection"]["evidence"]["scale_xy"]
            if (not isinstance(scale, list) or len(scale) != 2
                    or any(not _is_num(v) or v <= 0 for v in scale)
                    or abs(scale[0] - scale[1]) > 1e-9):
                raise LayoutReportError("UNSUPPORTED", f"{pid}:nonuniform native/page scale")
            scales[pid] = scale[0]
            required[pid] = sorted(set(spec["required_content"].get(pid, []))
                                   | set(selection["member_ids"]) | set(extras))
            baseline[pid] = {key: frame[key] for key in (
                "frame_revision", "source_revision", "base_config_revision", "candidate_revision")}
            baseline[pid].update(science_digest=(frame.get("science") or {}).get("digest"),
                                 control_id=selection["control_id"], member_ids=selection["member_ids"],
                                 affected_ids=selection["affected_ids"], coupled_extra_ids=extras,
                                 coupling_groups=selection["coupling_groups"], scale_xy=scale)
        for variant in spec["variants"]:
            for pid, edits in variant.items():
                for edit in edits:
                    control = controls[pid].get(edit["control_id"])
                    if control is None or edit["control_id"] == selections[pid]["control_id"]:
                        raise _fail_invalid(f"{pid}:variant uses unknown or automatic font control")
                    if any(control.get(key) is not None and
                           (edit["value"] < control[key] if key == "min" else edit["value"] > control[key])
                           for key in ("min", "max")):
                        raise _fail_invalid(f"{pid}:variant edit is outside its declared range")
        for point in grid:
            for index, variant in enumerate(spec["variants"]):
                check_page()
                check_sessions()
                attempt = {"candidate_pt": point, "variant_index": index, "status": "INFEASIBLE", "panels": {}}
                plans, trials = {}, {}
                try:
                    for pid in targets:
                        control = controls[pid][selections[pid]["control_id"]]
                        value = point / scales[pid]
                        lo, hi = control.get("min"), control.get("max")
                        if not variant and ((lo is not None and value < lo - 1e-9)
                                            or (hi is not None and value > hi + 1e-9)):
                            raise RenderError("OUT_OF_RANGE", f"{pid}:source font outside declared bounds")
                        # An internal variant may change native extent. Seed a
                        # complete preview, measure, then correct from that frame.
                        if lo is not None:
                            value = max(value, lo)
                        if hi is not None:
                            value = min(value, hi)
                        edits = [dict(e) for e in variant.get(pid, [])]
                        edits.append({"control_id": selections[pid]["control_id"], "value": value})
                        seed_required = spec["required_content"].get(pid, []) if variant else required[pid]
                        trial = preview(pid, edits, seed_required)
                        if variant:
                            bound = bind_frame(canonical, pid, trial["frame"], render_count)
                            actual_scale = bound["projection"]["evidence"]["scale_xy"]
                            if abs(actual_scale[0] - actual_scale[1]) > 1e-9:
                                raise RenderError("CONSTRAINT_VIOLATION", f"{pid}:variant is anisotropic")
                            value = point / actual_scale[0]
                            if abs(value - edits[-1]["value"]) > 1e-9:
                                edits[-1]["value"] = value
                                trial = preview(pid, edits, required[pid])
                        plans[pid], trials[pid] = edits, trial
                    bounds, measured = measure(trials, point)
                    check_page()
                    check_sessions(trials)
                    replay = {pid: preview(pid, plans[pid], required[pid], replay=True) for pid in targets}
                    rebound, actual = measure(replay, point)
                    for pid in targets:
                        if replay[pid]["frame"]["frame_revision"] != trials[pid]["frame"]["frame_revision"]:
                            raise RenderError("CONSTRAINT_VIOLATION", f"{pid}:NONDETERMINISTIC_REPLAY")
                    check_page()
                    check_sessions(replay)
                    check_page()
                    attempt.update(status="FEASIBLE", panels={pid: {"status": "FEASIBLE",
                                                                   "bottleneck": "OK"} for pid in targets})
                    attempts.append(attempt)
                    searched += 1
                    candidates = {pid: {
                        **{key: replay[pid][key] for key in ("candidate_id", "frame_revision", "layout_revision",
                                                           "candidate_revision", "source_revision", "base_config_revision")},
                        "frame": replay[pid]["frame"], "projection": rebound[pid]["projection"],
                        "binding": rebound[pid]["binding"], "edits": plans[pid], "measured_fonts": actual[pid]}
                        for pid in targets}
                    keep_winner = True
                    return finish("FEASIBLE", "common effective font verified; winning replay remains pending",
                                  candidates, {"candidate_pt": point, "variant_index": index, "measured": actual})
                except RenderError as error:
                    if not expected_rejection(error):
                        raise
                    attempt["panels"] = {pid: {"status": "CONSTRAINT_VIOLATION",
                                               "bottleneck": str(error), "code": error.status} for pid in targets}
                    attempts.append(attempt)
                    searched += 1
                    cleanup_issues.extend(_cancel_own(sessions, owned))
                    if cleanup_issues:
                        raise LayoutReportError("STALE", "owned candidate cleanup requires session close")
        check_page()
        check_sessions()
        return finish("NO_CANDIDATE", "no feasible candidate in the checked finite grid")
    except LayoutReportError as error:
        if error.status == "INVALID":
            raise
        return finish(error.status, str(error))
    except RenderError as error:
        if _is_stale_error(error):
            return finish("STALE", str(error))
        raise
    finally:
        if not keep_winner:
            cleanup_issues.extend(_cancel_own(sessions, owned))
