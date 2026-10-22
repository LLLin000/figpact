"""Fixed-layout spatial + space-budget report (G3-B, read-only).

``spatial_report`` validates the layout snapshot, reuses ``precheck_layout``
per target, and reads already G2-projected geometry from caller-supplied
observations. It never moves panels, never runs the renderer, and never
re-projects scenes: ``observations[panel]["projection"]`` is used as-is.

Evidence levels: measured clipping/outside-page and missing required ids are
PROVEN violations; text-envelope/curve-bbox overlap with fixed neighbour
rects is POTENTIAL (conservative ink, never occlusion); unmeasurable geometry
is UNKNOWN, never assumed zero/safe.
"""
from __future__ import annotations

import math
from typing import Any, TypeGuard

from .render_contract import UNMEASURED_STATUSES, precheck_layout, validate_layout

SCHEMA = "figpact.spatial-report/1"
_TOL = 1e-9


def _is_num(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _intersect(a: list[float], b: list[float]) -> list[float] | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


def _outside(rect: list[float], page: list[float]) -> str | None:
    # Scene baselines/points may have zero extent; panel intersection's
    # positive-area rule must not turn an on-page line into OUTSIDE_PAGE.
    x, y, w, h = rect
    if x + w < 0 or y + h < 0 or x > page[0] or y > page[1]:
        return "OUTSIDE_PAGE"
    if x < -_TOL or y < -_TOL or x + w > page[0] + _TOL or y + h > page[1] + _TOL:
        return "PARTIAL_OUTSIDE"
    return None


def _short(ids: list[str], cap: int = 20) -> str:
    if len(ids) <= cap:
        return str(ids)
    return str(ids[:cap]) + f" (+{len(ids) - cap} more)"


def _required_reason(source: Any, item: Any) -> tuple[str, str] | None:
    """Distinguish proved missing identity/clipping from unmeasured content."""
    if not isinstance(source, dict):
        return "PROVEN", "required identity absent from captured scene"
    if source.get("visible") is False:
        return "PROVEN", "invisible in captured scene"
    if source.get("fully_clipped") is True:
        return "PROVEN", "fully clipped in captured scene"
    if source.get("visible") is not True or not source.get("measured"):
        return "UNKNOWN", "visibility or geometry unmeasured in captured scene"
    if not isinstance(item, dict):
        return "UNKNOWN", "absent from supplied projection"
    if item.get("reason") == "CROPPED_OUT":
        return "PROVEN", "measured envelope is outside the panel crop"
    if not item.get("measurable"):
        return "UNKNOWN", "unmeasurable in supplied projection"
    raw_source = item.get("source")
    psrc = raw_source if isinstance(raw_source, dict) else {}
    bounds, canvas, crop = psrc.get("scene_bounds_mm"), psrc.get("canvas_mm"), psrc.get("crop_mm")
    if not (isinstance(bounds, (list, tuple)) and len(bounds) == 4
            and isinstance(canvas, (list, tuple)) and len(canvas) == 2
            and isinstance(crop, (list, tuple)) and len(crop) == 4):
        return "UNKNOWN", "projection lacks scene-bounds/canvas/crop evidence"
    if not all(_is_num(v) for values in (bounds, canvas, crop) for v in values):
        return "UNKNOWN", "projection carries non-finite or non-numeric bounds"
    x0, y0, x1, y1 = bounds
    left, top, width, height = crop
    node_rect = [x0, canvas[1] - y1, x1 - x0, y1 - y0]
    if not (node_rect[0] >= left - _TOL and node_rect[1] >= top - _TOL
            and node_rect[0] + node_rect[2] <= left + width + _TOL
            and node_rect[1] + node_rect[3] <= top + height + _TOL):
        return "PROVEN", "measured envelope extends outside the panel crop"
    return None


def _required_facts(raw_nodes: Any, required: list[str], projection: Any
                    ) -> tuple[list[str], list[str], list[str], dict[str, str]]:
    by_id: dict[str, Any] = {}
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            if not isinstance(node, dict):
                continue
            if node.get("id"):
                by_id[node["id"]] = node
            if node.get("gid"):
                by_id[node["gid"]] = node
    pnodes: dict[str, Any] = {}
    if isinstance(projection, dict) and isinstance(projection.get("nodes"), list):
        for node in projection["nodes"]:
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                pnodes[node["id"]] = node
    checked, missing, unknown, reasons = [], [], [], {}
    for gid in required:
        source = by_id.get(gid)
        source_id = source.get("id") if isinstance(source, dict) else None
        item = pnodes.get(source_id) if isinstance(source_id, str) else None
        why = _required_reason(source, item)
        if why is None:
            checked.append(gid)
        else:
            (missing if why[0] == "PROVEN" else unknown).append(gid)
            reasons[gid] = why[1]
    return checked, missing, unknown, reasons


def _scene_nodes_of(frame: Any) -> Any:
    if not isinstance(frame, dict) or not isinstance(frame.get("scene_json"), str):
        return None
    try:
        import json
        raw = json.loads(frame["scene_json"])
    except (ValueError, TypeError):
        return None
    nodes = raw.get("nodes") if isinstance(raw, dict) else None
    return nodes if isinstance(nodes, list) else None


def _validate_targets(target_ids: Any, by_id: dict[str, Any]) -> list[str]:
    if not isinstance(target_ids, (list, tuple)) or not target_ids:
        raise ValueError("target_ids must be a non-empty list of panel ids")
    out = list(target_ids)
    if any(not isinstance(t, str) or not t for t in out):
        raise ValueError("target_ids must hold non-empty strings")
    if len(set(out)) != len(out):
        raise ValueError(f"duplicate target ids: {sorted(i for i in set(out) if out.count(i) > 1)}")
    unknown = [t for t in out if t not in by_id]
    if unknown:
        raise ValueError(f"unknown target panels: {unknown}; have {sorted(by_id)}")
    return out


def _validate_required(required_content: Any, by_id: dict[str, Any]) -> dict[str, list[str]]:
    if required_content is None:
        return {}
    if not isinstance(required_content, dict):
        raise ValueError("required_content must be None or a mapping panel_id -> [node/gid ids]")
    out: dict[str, list[str]] = {}
    for panel, gids in required_content.items():
        if not isinstance(panel, str) or not panel or panel not in by_id:
            raise ValueError(f"required_content panel {panel!r} is not a layout object")
        if not isinstance(gids, list) or any(not isinstance(g, str) or not g for g in gids):
            raise ValueError(f"required_content[{panel!r}] must be a list of non-empty strings")
        if len(set(gids)) != len(gids):
            raise ValueError(f"duplicate required_content ids for {panel!r}")
        out[panel] = list(gids)
    return out


def _validate_regions(regions: Any, target_set: set[str], page: list[float]) -> list[dict[str, Any]]:
    if regions is None:
        return []
    if not isinstance(regions, (list, tuple)):
        raise ValueError("regions must be a list of region declarations")
    out, seen = [], set()
    for reg in regions:
        if not isinstance(reg, dict):
            raise ValueError("region declaration must be a dict")
        rid = reg.get("id")
        members = reg.get("member_ids")
        axis = reg.get("axis")
        box = reg.get("region_mm")
        gap = reg.get("gap_mm")
        if not isinstance(rid, str) or not rid or rid in seen:
            raise ValueError(f"region id {rid!r} must be a unique non-empty string")
        if not isinstance(members, (list, tuple)) or not members \
                or any(not isinstance(m, str) or not m for m in members):
            raise ValueError(f"region {rid!r} member_ids must be a non-empty string list")
        if len(set(members)) != len(members):
            raise ValueError(f"region {rid!r} member_ids must be unique")
        outside = [m for m in members if m not in target_set]
        if outside:
            raise ValueError(f"region {rid!r} members {outside} are not in the target set")
        if axis not in ("x", "y"):
            raise ValueError(f"region {rid!r} axis must be 'x' or 'y'")
        if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(_is_num(v) for v in box):
            raise ValueError(f"region {rid!r} region_mm must be [x, y, w, h] finite numbers")
        x, y, w, h = (float(v) for v in box)
        if w <= 0 or h <= 0:
            raise ValueError(f"region {rid!r} region_mm width/height must be > 0")
        if x < -_TOL or y < -_TOL or x + w > page[0] + _TOL or y + h > page[1] + _TOL:
            raise ValueError(f"region {rid!r} region_mm {list(box)} is not inside page {page}")
        if not _is_num(gap) or float(gap) < 0:
            raise ValueError(f"region {rid!r} gap_mm must be a finite nonnegative number")
        seen.add(rid)
        out.append({"id": rid, "member_ids": list(members), "axis": axis,
                    "region_mm": [x, y, w, h], "gap_mm": float(gap)})
    if len(seen) != len(out):
        raise ValueError("duplicate region ids")
    return out


def spatial_report(layout: dict[str, Any], target_ids: Any, observations: Any,
                   *, regions: Any = (), required_content: Any = None) -> dict[str, Any]:
    """Read-only fixed-layout spatial + space-budget report.

    ``observations`` maps panel_id -> ``{frame, controls, projection, binding,
    editable}`` where ``projection`` is already G2-transformed; panels without
    an observation keep their page geometry and are reported UNKNOWN for
    content. ``required_content`` maps panel_id -> confirmed node/gid ids.
    Never moves panels, never runs the renderer, never re-projects.
    """
    canonical = validate_layout(layout)
    by_id = {o["id"]: o for o in canonical["objects"]}
    page = canonical["page_mm"]
    targets = _validate_targets(target_ids, by_id)
    target_set = set(targets)
    if observations is None:
        observations = {}
    if not isinstance(observations, dict):
        raise ValueError("observations must be a mapping panel_id -> observation")
    required = _validate_required(required_content, by_id)
    regs = _validate_regions(regions, target_set, page)

    findings: list[dict[str, Any]] = []
    target_info: dict[str, Any] = {}
    unmeasurable_targets: list[str] = []

    for pid in targets:
        obj = by_id[pid]
        pre = precheck_layout(canonical, pid)
        obs = observations.get(pid)
        obs = obs if isinstance(obs, dict) else None
        frame = obs.get("frame") if obs else None
        frame = frame if isinstance(frame, dict) else None
        projection = obs.get("projection") if obs else None
        projection = projection if isinstance(projection, dict) else None
        editable = bool(obs.get("editable")) if obs else False

        if obj["rect_mm"] is None or obj["measurement_status"] in UNMEASURED_STATUSES \
                or obj["rotation_deg"] is None:
            unmeasurable_targets.append(pid)

        if pre["target_outside"] is not None and obj["measurement_status"] not in UNMEASURED_STATUSES:
            findings.append({
                "certainty": "PROVEN", "kind": pre["target_outside"], "violation": True,
                "panels": [pid], "objects": [pid],
                "detail": f"target rect {obj['rect_mm']} lies {pre['target_outside']} page {page}",
            })
        for risk in pre["risks"]:
            if risk["kind"] == "POTENTIAL_OVERLAP":
                findings.append({
                    "certainty": "POTENTIAL", "kind": "POTENTIAL_OVERLAP", "violation": False,
                    "panels": [pid], "objects": list(risk["object_ids"]),
                    "detail": risk["detail"] + "; conservative rects only, not occlusion",
                })
            elif risk["kind"] == "MEASUREMENT_LIMITED":
                findings.append({
                    "certainty": "UNKNOWN", "kind": "MEASUREMENT_LIMITED", "violation": False,
                    "panels": [pid], "objects": list(risk["object_ids"]),
                    "detail": risk["detail"],
                })
        for neigh in pre["neighbors"]:
            if neigh["outside_page"] is not None and neigh["measurement_status"] not in UNMEASURED_STATUSES:
                findings.append({
                    "certainty": "PROVEN", "kind": "NEIGHBOUR_OUTSIDE_PAGE", "violation": False,
                    "panels": [pid], "objects": [pid, neigh["id"]],
                    "detail": f"fixed neighbour {neigh['id']!r} rect {neigh['rect_mm']} is "
                              f"{neigh['outside_page']} page {page}; reported separately, "
                              f"target {pid!r} was not moved",
                })

        science = frame.get("science") if frame else None
        verified = science.get("verified") if isinstance(science, dict) else None
        if verified is not True:
            findings.append({
                "certainty": "UNKNOWN", "kind": "SCIENCE_UNVERIFIED", "violation": False,
                "panels": [pid], "objects": [pid],
                "detail": f"candidate science evidence verified={verified!r} "
                          f"({'no frame observation' if frame is None else 'frame present'}); "
                          f"geometry alone is not export QA",
            })

        nodes = projection.get("nodes") if projection and isinstance(projection.get("nodes"), list) else None
        raw_evidence = projection.get("evidence") if projection else None
        evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
        scale_xy = evidence.get("scale_xy")
        scale_xy = [float(scale_xy[0]), float(scale_xy[1])] \
            if isinstance(scale_xy, (list, tuple)) and len(scale_xy) == 2 \
            and all(_is_num(v) for v in scale_xy) else None
        raw_anisotropic = evidence.get("anisotropic")
        anisotropic = raw_anisotropic if isinstance(raw_anisotropic, bool) else None
        if nodes is None:
            findings.append({
                "certainty": "UNKNOWN", "kind": "MEASUREMENT_MISSING", "violation": False,
                "panels": [pid], "objects": [pid],
                "detail": f"no usable supplied projection for target {pid!r} "
                          f"(opaque/unmigrated or missing observation); page geometry retained, "
                          f"content unassessed",
            })
            node_counts = {"total": 0, "measurable": 0, "unmeasured": 0, "cropped_out": 0}
            node_echo: dict[str, Any] = {}
        else:
            fixed_rects = [(o["id"], o["rect_mm"]) for o in canonical["objects"]
                           if o["id"] not in target_set and o["rect_mm"] is not None
                           and o["measurement_status"] not in UNMEASURED_STATUSES and not o["hidden"]]
            raw_by_id = {n.get("id"): n for n in (_scene_nodes_of(frame) or []) if isinstance(n, dict)}
            clipped, outside_pg, unmeasured = [], [], []
            overlap: dict[str, list[str]] = {}
            node_echo = {}
            for node in nodes:
                if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                    unmeasured.append("<malformed-node>")
                    continue
                nid = node["id"]
                rect = node.get("rect_mm")
                rect_f = ([float(v) for v in rect]
                          if isinstance(rect, (list, tuple)) and len(rect) == 4
                          and all(_is_num(v) for v in rect) else None)
                node_echo[nid] = {"rect_mm": rect_f,
                                  "measurable": bool(node.get("measurable")),
                                  "reason": node.get("reason")}
                source = raw_by_id.get(nid)
                if source is not None and (source.get("structural") or source.get("visible") is False):
                    node_echo[nid]["content_status"] = "STRUCTURAL" if source.get("structural") else "HIDDEN"
                    continue
                if source is not None and source.get("visible") is not True:
                    unmeasured.append(nid)
                    continue
                crop_fact = _required_reason(source, node) if source is not None else None
                if crop_fact is not None and crop_fact[0] == "PROVEN" and node.get("measurable"):
                    clipped.append(nid)
                if node.get("measurable") and rect_f is not None:
                    kind = _outside(rect_f, page)
                    if kind is not None:
                        outside_pg.append(nid)
                    for fid, frect in fixed_rects:
                        if _intersect(rect_f, frect) is not None:
                            overlap.setdefault(fid, []).append(nid)
                elif not node.get("measurable") and node.get("reason") == "CROPPED_OUT":
                    clipped.append(nid)
                else:
                    unmeasured.append(nid)
            if clipped:
                findings.append({
                    "certainty": "PROVEN", "kind": "CONTENT_CLIPPED", "violation": True,
                    "panels": [pid], "objects": [pid], "nodes": list(clipped),
                    "detail": f"measured content envelopes extend beyond the known panel crop "
                              f"(envelope geometry, not an exact-ink claim): {_short(clipped)}",
                })
            if outside_pg:
                findings.append({
                    "certainty": "PROVEN", "kind": "CONTENT_OUTSIDE_PAGE", "violation": True,
                    "panels": [pid], "objects": [pid], "nodes": list(outside_pg),
                    "detail": f"measured projected content outside page {page}: {_short(outside_pg)}",
                })
            if unmeasured:
                findings.append({
                    "certainty": "UNKNOWN", "kind": "UNMEASURED_CONTENT", "violation": False,
                    "panels": [pid], "objects": [pid], "nodes": list(unmeasured),
                    "detail": f"{len(unmeasured)} supplied node(s) unmeasurable "
                              f"(envelope/bbox unknown, never assumed ink): {_short(unmeasured)}",
                })
            for fid, nids in sorted(overlap.items()):
                findings.append({
                    "certainty": "POTENTIAL", "kind": "POTENTIAL_NEIGHBOUR_ENVELOPE_OVERLAP",
                    "violation": False, "panels": [pid], "objects": [pid, fid], "nodes": list(nids),
                    "detail": f"conservative projected envelopes {_short(nids)} intersect fixed "
                              f"neighbour {fid!r} rect; POTENTIAL only, not occlusion",
                })
            node_counts = {"total": len(node_echo),
                           "measurable": sum(1 for v in node_echo.values() if v["measurable"]),
                           "unmeasured": len(unmeasured), "cropped_out": len(clipped)}

        req_ids = required.get(pid, [])
        raw_nodes = _scene_nodes_of(frame)
        if req_ids and raw_nodes is None:
            checked, missing, unknown = [], [], list(req_ids)
            req_reasons = {g: "no readable captured scene for this panel" for g in req_ids}
        elif req_ids:
            checked, missing, unknown, req_reasons = _required_facts(raw_nodes, req_ids, projection)
        else:
            checked, missing, unknown, req_reasons = [], [], [], {}
        if missing:
            findings.append({
                "certainty": "PROVEN", "kind": "REQUIRED_CONTENT_MISSING", "violation": True,
                "panels": [pid], "objects": [pid], "nodes": list(missing),
                "detail": "required identity absent, invisible or outside the measured crop: "
                          + "; ".join(f"{g} ({req_reasons.get(g)})" for g in missing),
            })
        if unknown:
            unmeasurable_targets.append(pid)
            findings.append({
                "certainty": "UNKNOWN", "kind": "REQUIRED_CONTENT_UNVERIFIED", "violation": False,
                "panels": [pid], "objects": [pid], "nodes": list(unknown),
                "detail": "; ".join(f"{g} ({req_reasons[g]})" for g in unknown),
            })

        target_info[pid] = {
            "id": pid, "rect_mm": list(obj["rect_mm"]) if obj["rect_mm"] is not None else None,
            "measurement_status": obj["measurement_status"], "rotation_deg": obj["rotation_deg"],
            "hidden": obj["hidden"], "locked": obj["locked"],
            "outside_page": pre["target_outside"],
            "has_observation": obs is not None, "editable": editable,
            "native_scale_xy": scale_xy, "anisotropic": anisotropic,
            "frame_science_verified": verified if verified is True else (False if verified is False else None),
            "required": {"requested": list(req_ids), "checked": checked, "missing": missing,
                         "unknown": unknown, "reasons": dict(req_reasons)},
            "precheck": pre,
            "projected": {**node_counts, "nodes": node_echo},
        }

    budgets = []
    for reg in regs:
        extents: dict[str, Any] = {}
        unknown_member = False
        for mid in reg["member_ids"]:
            rect = by_id[mid]["rect_mm"]
            if by_id[mid]["hidden"]:
                raise ValueError(f"region {reg['id']!r} includes hidden member {mid!r}")
            if rect is None or by_id[mid]["measurement_status"] in UNMEASURED_STATUSES:
                extents[mid] = None
                unknown_member = True
            else:
                extents[mid] = float(rect[2] if reg["axis"] == "x" else rect[3])
        region_extent = float(reg["region_mm"][2] if reg["axis"] == "x" else reg["region_mm"][3])
        if unknown_member:
            occupied = excess = current_span = None
            certainty = "UNKNOWN"
            detail = (f"region {reg['id']!r} axis {reg['axis']}: member geometry unknown "
                      f"({[m for m, v in extents.items() if v is None]}); budget unknown, never 0")
            findings.append({"certainty": "UNKNOWN", "kind": "BUDGET_UNKNOWN", "violation": False,
                             "panels": list(reg["member_ids"]), "objects": list(reg["member_ids"]),
                             "region_id": reg["id"], "detail": detail})
        else:
            occupied = math.fsum(extents.values()) + reg["gap_mm"] * (len(reg["member_ids"]) - 1)
            excess = occupied - region_extent
            offset = 0 if reg["axis"] == "x" else 1
            boxes = [by_id[mid]["rect_mm"] for mid in reg["member_ids"]]
            current_span = max(b[offset] + b[offset + 2] for b in boxes) - min(b[offset] for b in boxes)
            certainty = "PROVEN"
            if excess > _TOL:
                detail = (f"region {reg['id']!r} axis {reg['axis']}: current occupied {occupied}mm "
                          f"vs available {region_extent}mm => CURRENT_BUDGET_EXCESS {excess}mm "
                          f"(information only; not proof no solution; internal margin/canvas "
                          f"changes could alter demand)")
                findings.append({"certainty": "POTENTIAL", "kind": "CURRENT_BUDGET_EXCESS",
                                 "violation": False, "panels": list(reg["member_ids"]),
                                 "objects": list(reg["member_ids"]), "region_id": reg["id"],
                                 "excess_mm": excess, "detail": detail})
            else:
                detail = (f"region {reg['id']!r} axis {reg['axis']}: current occupied {occupied}mm "
                          f"within available {region_extent}mm (spare {round(region_extent - occupied, 6)}mm)")
        budgets.append({"region_id": reg["id"], "axis": reg["axis"],
                        "region_mm": list(reg["region_mm"]), "gap_mm": reg["gap_mm"],
                        "available_mm": region_extent, "occupied_mm": occupied, "excess_mm": excess,
                        "current_span_mm": current_span,
                        "certainty": certainty, "member_ids": list(reg["member_ids"]),
                        "member_extents_mm": dict(extents), "detail": detail})

    if any(f["violation"] for f in findings):
        status = "CONSTRAINT_VIOLATION"
    elif unmeasurable_targets:
        status = "UNSUPPORTED"
    else:
        status = "READY"

    return {
        "schema": SCHEMA, "status": status, "layout_revision": canonical["revision"],
        "page_mm": list(page), "target_ids": list(targets),
        "targets": target_info, "budgets": budgets, "findings": findings,
        "limits": [
            f"SNAPSHOT_BOUND: layout revision {canonical['revision']}; observations are as-of "
            f"inputs, not a continuous lock on the active page.",
            "Fixed neighbours and targets were not moved; no solver, search, save, or renderer ran.",
            "Text envelopes/curve bboxes are conservative: intersecting envelopes vs fixed "
            "neighbour rects is POTENTIAL, never occlusion; disjoint known rects do not prove "
            "the entire page safe.",
            "CURRENT_BUDGET_EXCESS reports current rects only, not proof of no solution; "
            "internal margin/canvas changes could alter demand. Unknown geometry yields "
            "unknown budgets, never 0.",
            "Read-only report, not final export QA; science/view protections unchanged; "
            "no edit grants issued.",
        ],
    }
