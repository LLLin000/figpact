"""R14 G0+G1 standalone render contract (no Tavotto dependency).

Pure stdlib. No Tavotto imports. Layout uses final-page top-left mm;
Scene stays canvas-bottom-left and projection explicitly converts.

Exact shapes
------------
LayoutSnapshot (``figpact.layout/1``)::

    {schema: 'figpact.layout/1', source_mode: 'standalone'|'saved'|'live',
     page_mm: [W, H],                       # final-page size, top-left origin
     objects: [{id, rect_mm: [x, y, w, h]|None,  # page top-left mm; None allowed
                measurement_status: 'measured'|'conservative'|'unknown'|'unsupported',
                hidden?: bool, locked?: bool,
                rotation_deg?: number,      # right angles only, default 0
                crop?: [x, y, w, h],        # canvas top-left mm, default None
                flip_h?: bool, flip_v?: bool,
                kind?: str,                 # generic object kind, e.g. 'panel'
                resource?: str,             # generic resource identity
                source?: {str: str},        # generic provenance map, no host names
                z_index?: int|None,         # stacking order; None = unknown, bool rejected
                capabilities?: [str]|None}, ...],  # None = unknown vs [] = known-no-caps
     project_id?: str|None, page_id?: str|None, host_revision?: str|None,
     captured_at?: str,                     # informational only, excluded from hash
     revision?: str}                        # must match computed hash when supplied

``rect_mm=None`` is allowed ONLY for unknown/unsupported statuses (unknown
geometry is explicit, never a fake rect); measured/conservative still require
positive rects. precheck reports unknown neighbours as relation='unknown'
with overlap None; target-unknown yields target_outside None plus
MEASUREMENT_LIMITED; project_scene refuses unknown targets outright.

Scene node ``bounds_mm`` is [x0, y0, x1, y1] with x1>=x0, y1>=y0: honest
horizontal/vertical baselines and points carry zero height/width and pass
through projection with their true coordinates (never inflated). Positive
area is still required for panel/canvas/crop/page rects, and page/panel
overlap checks keep positive-area semantics (zero-extent touches are not
overlaps).

EditIntent (``figpact.intent/1``)::

    {schema: 'figpact.intent/1', panel_id: str,
     edits: [{control_id: str, value: number, role?: str}],  # control_ids unique
     fit_canvas: bool, required_content: [gid],              # gids unique
     preserve: ['science', 'view']}

Projection order per node: crop (canvas space) -> anisotropic scale to panel
-> flip -> right-angle rotation about the panel centre. Scale is always the
pair ``scale_xy`` plus an ``anisotropic`` flag; never a fake scalar.
Unmeasured/unknown nodes stay listed with ``rect_mm: None`` and are counted,
never dropped and never passed off as measurable.

``validate_layout``/``validate_intent`` outputs are idempotent: feeding a
canonical dict back in returns an equal dict. ``snapshot_revision`` applies
the same canonical normalization as ``validate_layout`` (minus the
revision-match check), so a raw snapshot and its canonical form hash equally.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

LAYOUT_SCHEMA = "figpact.layout/1"
INTENT_SCHEMA = "figpact.intent/1"
SOURCE_MODES = frozenset({"standalone", "saved", "live"})
MEASUREMENT_STATUSES = frozenset({"measured", "conservative", "unknown", "unsupported"})
# Statuses whose rect is a placeholder basis, never a measured bound.
UNMEASURED_STATUSES = frozenset({"unknown", "unsupported"})
PRESERVE_REQUIRED = ["science", "view"]
LAYOUT_ORIGIN = "page_top_left"
SCENE_ORIGIN = "canvas_bottom_left"

# Risk kinds emitted by precheck_layout.
POTENTIAL_OVERLAP = "POTENTIAL_OVERLAP"  # conservative rect overlap, NOT occlusion
OUTSIDE_PAGE = "OUTSIDE_PAGE"
PARTIAL_OUTSIDE = "PARTIAL_OUTSIDE"
MEASUREMENT_LIMITED = "MEASUREMENT_LIMITED"


class RenderContractError(ValueError):
    """Invalid layout/intent/scene input or unresolvable precheck target."""


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _req(condition: bool, message: str) -> None:
    if not condition:
        raise RenderContractError(message)


def _rect4(rect: Any, *, what: str, allow_negative_xy: bool) -> list[float]:
    _req(isinstance(rect, (list, tuple)) and len(rect) == 4,
         f"{what} must be [x, y, w, h]")
    vals = [float(v) for v in rect] if all(_is_num(v) for v in rect) else None
    _req(vals is not None, f"{what} must hold finite non-bool numbers")
    assert vals is not None
    x, y, w, h = vals
    if not allow_negative_xy:
        _req(x >= 0.0 and y >= 0.0, f"{what} origin must be >= 0")
    _req(w > 0.0 and h > 0.0, f"{what} width/height must be > 0")
    return [x, y, w, h]


def _page_mm(page: Any) -> list[float]:
    _req(isinstance(page, (list, tuple)) and len(page) == 2
         and all(_is_num(v) for v in page), "page_mm must be [W, H] numbers")
    w, h = float(page[0]), float(page[1])
    _req(w > 0.0 and h > 0.0, "page_mm width/height must be > 0")
    return [w, h]


def _norm_rotation(deg: Any, *, what: str) -> float:
    _req(_is_num(deg), f"{what} must be a finite non-bool number")
    quarters = float(deg) / 90.0
    _req(math.isclose(quarters, round(quarters), abs_tol=1e-9),
         f"{what}={deg!r} unsupported: only right angles (multiples of 90)")
    return float(int(round(quarters)) % 4 * 90)


def _flag(mapping: dict[str, Any], key: str, *, what: str) -> bool:
    value = mapping.get(key, False)
    _req(isinstance(value, bool), f"{what}.{key} must be bool")
    return value


def _text(mapping: dict[str, Any], key: str, *, what: str, required: bool) -> str | None:
    value = mapping.get(key)
    if value is None:
        _req(not required, f"{what}.{key} must be a non-empty str")
        return None
    _req(bool(isinstance(value, str) and value.strip()), f"{what}.{key} must be a non-empty str")
    return value


OBJECT_KEYS = frozenset({"id", "rect_mm", "measurement_status", "hidden", "locked",
                         "rotation_deg", "crop", "flip_h", "flip_v", "kind",
                         "resource", "source", "z_index", "capabilities"})
LAYOUT_KEYS = frozenset({"schema", "source_mode", "page_mm", "objects",
                         "project_id", "page_id", "host_revision",
                         "captured_at", "revision"})
INTENT_KEYS = frozenset({"schema", "panel_id", "edits", "fit_canvas",
                         "required_content", "preserve"})


def _validate_object(obj: dict[str, Any]) -> dict[str, Any]:
    _req(isinstance(obj, dict), "layout object must be a dict")
    oid_raw = obj.get("id")
    if not isinstance(oid_raw, str) or not oid_raw.strip():
        raise RenderContractError("layout object id must be a non-empty str")
    oid: str = oid_raw
    extra = set(obj) - OBJECT_KEYS
    _req(not extra, f"object {oid!r} has unknown keys: {sorted(extra)}")
    status = obj.get("measurement_status")
    _req(status in MEASUREMENT_STATUSES,
         f"object {oid!r} measurement_status must be one of {sorted(MEASUREMENT_STATUSES)}")
    rect_raw = obj.get("rect_mm")
    rect: list[float] | None = None
    if rect_raw is None:
        if status not in UNMEASURED_STATUSES:
            raise RenderContractError(
                f"object {oid!r} rect_mm=None allowed only for unknown/unsupported statuses")
    else:
        rect = _rect4(rect_raw, what=f"object {oid!r} rect_mm",
                      allow_negative_xy=True)
    crop = obj.get("crop")
    crop_out = None
    if crop is not None:
        crop_out = _rect4(crop, what=f"object {oid!r} crop", allow_negative_xy=False)
    rotation = _norm_rotation(obj.get("rotation_deg", 0),
                              what=f"object {oid!r} rotation_deg")
    kind = _text(obj, "kind", what=f"object {oid!r}", required=False)
    resource = _text(obj, "resource", what=f"object {oid!r}", required=False)
    source = obj.get("source")
    source_out: dict[str, str] | None = None
    if source is not None:
        if not isinstance(source, dict):
            raise RenderContractError(f"object {oid!r} source must be a str->str map")
        for k, v in source.items():
            _req(bool(isinstance(k, str) and k.strip()), f"object {oid!r} source key must be non-empty str")
            _req(isinstance(v, str), f"object {oid!r} source[{k!r}] must be str")
        source_out = dict(source)
    z_raw = obj.get("z_index")
    z_index: int | None = None
    if z_raw is not None:
        if isinstance(z_raw, bool) or not isinstance(z_raw, int):
            raise RenderContractError(f"object {oid!r} z_index must be int|None (unknown default None)")
        z_index = z_raw
    caps_raw = obj.get("capabilities")
    caps: list[str] | None = None
    if caps_raw is not None:
        if not isinstance(caps_raw, list) \
                or not all(bool(isinstance(c, str) and c) for c in caps_raw):
            raise RenderContractError(f"object {oid!r} capabilities must be list[str]|None (unknown vs [])")
        caps = list(caps_raw)
    return {
        "id": oid,
        "rect_mm": rect,
        "measurement_status": status,
        "hidden": _flag(obj, "hidden", what=f"object {oid!r}"),
        "locked": _flag(obj, "locked", what=f"object {oid!r}"),
        "rotation_deg": rotation,
        "crop": crop_out,
        "flip_h": _flag(obj, "flip_h", what=f"object {oid!r}"),
        "flip_v": _flag(obj, "flip_v", what=f"object {oid!r}"),
        "kind": kind,
        "resource": resource,
        "source": source_out,
        "z_index": z_index,
        "capabilities": caps,
    }


def _canonical_layout_body(snapshot: dict[str, Any]) -> dict[str, Any]:
    _req(isinstance(snapshot, dict), "layout snapshot must be a dict")
    extra = set(snapshot) - LAYOUT_KEYS
    _req(not extra, f"layout snapshot has unknown keys: {sorted(extra)}")
    _req(snapshot.get("schema") == LAYOUT_SCHEMA,
         f"layout schema must be {LAYOUT_SCHEMA!r}")
    mode = snapshot.get("source_mode")
    _req(mode in SOURCE_MODES,
         f"source_mode must be one of {sorted(SOURCE_MODES)}")
    page = _page_mm(snapshot.get("page_mm"))
    objects = snapshot.get("objects")
    if not isinstance(objects, list) or not objects:
        raise RenderContractError("layout objects must be a non-empty list")
    canonical_objects = [_validate_object(o) for o in objects]
    ids = [o["id"] for o in canonical_objects]
    _req(len(set(ids)) == len(ids),
         f"duplicate layout object ids: {sorted(i for i in set(ids) if ids.count(i) > 1)}")
    captured_at = snapshot.get("captured_at")
    if captured_at is not None:
        _req(isinstance(captured_at, str), "captured_at must be a str")
    canonical: dict[str, Any] = {
        "schema": LAYOUT_SCHEMA,
        "source_mode": mode,
        "page_mm": page,
        "objects": canonical_objects,
        "project_id": _text(snapshot, "project_id", what="layout", required=False),
        "page_id": _text(snapshot, "page_id", what="layout", required=False),
        "host_revision": _text(snapshot, "host_revision", what="layout", required=False),
    }
    if captured_at is not None:
        canonical["captured_at"] = captured_at
    return canonical


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def snapshot_revision(snapshot: dict[str, Any]) -> str:
    """Content hash (sha256 hex) over canonical JSON excluding ``captured_at``.

    Accepts a raw or canonical layout-shaped input and first applies the same
    canonical normalization as ``validate_layout`` (minus the revision-match
    check); only ``captured_at`` (informational wall-clock) and ``revision``
    (the hash itself) are excluded, so a raw snapshot and its canonical form
    hash identically and every other validated fact is covered.
    """
    if not isinstance(snapshot, dict):
        raise RenderContractError("snapshot must be a dict")
    body = _canonical_layout_body(snapshot)
    body = {k: v for k, v in body.items() if k not in ("captured_at", "revision")}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def validate_layout(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate a layout snapshot; return the idempotent canonical dict.

    A supplied ``revision``, when present, must equal the computed content
    hash; otherwise the snapshot is rejected as stale/tampered.
    """
    canonical = _canonical_layout_body(snapshot)
    computed = snapshot_revision(canonical)
    supplied = snapshot.get("revision")
    if supplied is not None:
        _req(bool(isinstance(supplied, str) and supplied == computed),
             f"layout revision mismatch: supplied {supplied!r} != computed {computed!r}")
    canonical["revision"] = computed
    return canonical

def validate_intent(intent: dict[str, Any], authorized: Any = None) -> dict[str, Any]:
    """Validate an edit intent; return the idempotent canonical dict.

    Numeric edits must cite authorized controls discovered by the existing
    Native engine (``authorized`` set/list of control_id strings, when given);
    ``control_id`` and ``required_content`` entries must each be unique.
    No parameters are invented here.
    """
    _req(isinstance(intent, dict), "intent must be a dict")
    extra_intent = set(intent) - INTENT_KEYS
    _req(not extra_intent, f"intent has unknown keys: {sorted(extra_intent)}")
    _req(bool(intent.get("schema") == INTENT_SCHEMA),
         f"intent schema must be {INTENT_SCHEMA!r}")
    panel_raw = intent.get("panel_id")
    if not isinstance(panel_raw, str) or not panel_raw.strip():
        raise RenderContractError("intent panel_id must be a non-empty str")
    panel_id: str = panel_raw
    edits_raw = intent.get("edits")
    if not isinstance(edits_raw, list) or not edits_raw:
        raise RenderContractError("intent edits must be a non-empty list")
    edits: list[Any] = edits_raw
    allowed = set(authorized) if authorized is not None else None
    canonical_edits: list[dict[str, Any]] = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise RenderContractError("intent edit must be a dict")
        cid_raw: Any = edit.get("control_id")
        if not isinstance(cid_raw, str) or not cid_raw.strip():
            raise RenderContractError("intent edit control_id must be a non-empty str")
        cid: str = cid_raw
        value = edit.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise RenderContractError(f"intent edit {cid!r} value must be a finite non-bool number")
        num_value: int | float = value
        if allowed is not None:
            _req(cid in allowed, f"intent edit {cid!r} is not an authorized control")
        extra = set(edit) - {"control_id", "value", "role"}
        _req(not extra, f"intent edit {cid!r} invents parameters: {sorted(extra)}")
        item: dict[str, Any] = {"control_id": cid, "value": float(num_value)}
        if "role" in edit:
            _req(isinstance(edit["role"], str), f"intent edit {cid!r} role must be str")
            item["role"] = edit["role"]
        canonical_edits.append(item)
    cids = [e["control_id"] for e in canonical_edits]
    _req(len(set(cids)) == len(cids),
         f"duplicate intent control_ids: {sorted(i for i in set(cids) if cids.count(i) > 1)}")
    fit_canvas = intent.get("fit_canvas")
    _req(isinstance(fit_canvas, bool), "intent fit_canvas must be bool")
    required_raw = intent.get("required_content")
    if not isinstance(required_raw, list) \
            or not all(bool(isinstance(g, str) and g) for g in required_raw):
        raise RenderContractError("intent required_content must be a list of gid strings")
    required: list[Any] = required_raw
    _req(len(set(required)) == len(required),
         f"duplicate intent required_content: {sorted(i for i in set(required) if required.count(i) > 1)}")
    preserve = intent.get("preserve")
    _req(bool(isinstance(preserve, list) and sorted(preserve) == PRESERVE_REQUIRED),
         "intent preserve must be exactly ['science', 'view']")
    return {
        "schema": INTENT_SCHEMA,
        "panel_id": panel_id,
        "edits": canonical_edits,
        "fit_canvas": fit_canvas,
        "required_content": list(required),
        "preserve": list(PRESERVE_REQUIRED),
    }


def _scene_node(node: dict[str, Any]) -> dict[str, Any]:
    _req(isinstance(node, dict), "scene node must be a dict")
    nid_raw = node.get("id")
    if not isinstance(nid_raw, str) or not nid_raw.strip():
        raise RenderContractError("scene node id must be non-empty str")
    nid: str = nid_raw
    measured = node.get("measured", False)
    _req(isinstance(measured, bool), f"scene node {nid!r} measured must be bool")
    bounds = node.get("bounds_mm")
    box: list[float] | None = None
    if bounds is not None:
        _req(bool(isinstance(bounds, (list, tuple)) and len(bounds) == 4
             and all(_is_num(v) for v in bounds)),
             f"scene node {nid!r} bounds_mm must be [x0, y0, x1, y1] or None")
        assert isinstance(bounds, (list, tuple))
        x0, y0, x1, y1 = (float(v) for v in bounds)
        _req(x1 >= x0 and y1 >= y0, f"scene node {nid!r} bounds_mm must have x1>=x0, y1>=y0")
        box = [x0, y0, x1, y1]
    return {"id": nid, "bounds_mm": box, "measured": measured}


def _intersect(a: list[float], b: list[float]) -> list[float] | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


def _project_clip(line: list[float], crop: list[float]) -> list[float] | None:
    """Boundary-aware clip for scene projection: zero-extent lines/points survive.

    ``line`` is [x, y, w, h] with w,h >= 0 (lines/points allowed); ``crop`` is a
    positive-area [x, y, w, h]. Returns the clipped [x, y, w, h] preserving
    zero extents when the line/point touches or lies inside the crop, else None.
    Panel/page overlap checks keep positive-area semantics via ``_intersect``.
    """
    x0, y0 = max(line[0], crop[0]), max(line[1], crop[1])
    x1, y1 = min(line[0] + line[2], crop[0] + crop[2]), min(line[1] + line[3], crop[1] + crop[3])
    if x1 < x0 or y1 < y0:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


def _rotate_local(lx: float, ly: float, lw: float, lh: float,
                  pw: float, ph: float, rotation: float) -> tuple[float, float, float, float]:
    if rotation == 90.0:
        return ph - (ly + lh), lx, lh, lw
    if rotation == 180.0:
        return pw - (lx + lw), ph - (ly + lh), lw, lh
    if rotation == 270.0:
        return ly, pw - (lx + lw), lh, lw
    return lx, ly, lw, lh


def project_scene(scene: dict[str, Any], panel: dict[str, Any], page_mm: Any) -> dict[str, Any]:
    """Project scene nodes (canvas bottom-left) onto a panel (page top-left).

    Returns ``{panel_id, page_mm, coordinate_reference: 'page_top_left',
    nodes: [{id, rect_mm | None, measurable, scale_xy | None, anisotropic,
    source, reason?}], evidence}``. ``source`` carries the evidence chain
    (scene bounds, canvas, crop, flips, rotation); ``evidence`` the panel-wide
    constants. Anisotropy is reported as the ``scale_xy`` pair, never scalar.
    """
    if not isinstance(scene, dict):
        raise RenderContractError("scene must be a dict")
    _req(bool(scene.get("coordinate_reference", SCENE_ORIGIN) == SCENE_ORIGIN),
         f"scene coordinate_reference must be {SCENE_ORIGIN!r}")
    canvas = scene.get("canvas_mm")
    _req(bool(isinstance(canvas, (list, tuple)) and len(canvas) == 2
         and all(_is_num(v) for v in canvas)
         and float(canvas[0]) > 0 and float(canvas[1]) > 0),
         "scene canvas_mm must be [W, H] positive numbers")
    assert isinstance(canvas, (list, tuple))
    cw, ch = float(canvas[0]), float(canvas[1])
    nodes_raw = scene.get("nodes")
    if not isinstance(nodes_raw, list):
        raise RenderContractError("scene nodes must be a list")
    for n in nodes_raw:
        if not isinstance(n, dict):
            raise RenderContractError("scene node must be a dict")
    nodes: list[Any] = nodes_raw
    clean = [_scene_node(n) for n in nodes]
    obj = _validate_object(panel)
    if obj["rect_mm"] is None or obj["measurement_status"] in UNMEASURED_STATUSES:
        raise RenderContractError(
            f"panel {obj['id']!r} cannot be a projection target: "
            f"status={obj['measurement_status']!r} rect={obj['rect_mm']!r} "
            "(unknown/unsupported geometry is never projected)")
    page = _page_mm(page_mm)
    assert obj["rect_mm"] is not None
    px, py, pw, ph = obj["rect_mm"]
    crop: list[float] = obj["crop"] or [0.0, 0.0, cw, ch]
    _req(bool(crop[0] + crop[2] <= cw + 1e-9 and crop[1] + crop[3] <= ch + 1e-9),
         f"panel {obj['id']!r} crop exceeds canvas {cw}x{ch}mm")
    sx, sy = pw / crop[2], ph / crop[3]
    out_nodes = []
    measurable_count = 0
    for node in clean:
        if not node["measured"] or node["bounds_mm"] is None:
            out_nodes.append({
                "id": node["id"], "rect_mm": None, "measurable": False,
                "scale_xy": None, "anisotropic": None,
                "source": {"scene_bounds_mm": node["bounds_mm"],
                           "canvas_mm": [cw, ch], "crop_mm": list(crop),
                           "flip_h": obj["flip_h"], "flip_v": obj["flip_v"],
                           "rotation_deg": obj["rotation_deg"]},
                "reason": "UNMEASURED_SOURCE",
            })
            continue
        x0, y0, x1, y1 = node["bounds_mm"]
        # Canvas bottom-left -> canvas top-left, then crop once.
        clipped = _project_clip([x0, ch - y1, x1 - x0, y1 - y0], crop)
        if clipped is None:
            out_nodes.append({
                "id": node["id"], "rect_mm": None, "measurable": False,
                "scale_xy": [sx, sy], "anisotropic": abs(sx - sy) > 1e-9,
                "source": {"scene_bounds_mm": node["bounds_mm"],
                           "canvas_mm": [cw, ch], "crop_mm": list(crop),
                           "flip_h": obj["flip_h"], "flip_v": obj["flip_v"],
                           "rotation_deg": obj["rotation_deg"]},
                "reason": "CROPPED_OUT",
            })
            continue
        lx = px + (clipped[0] - crop[0]) * sx
        ly = py + (clipped[1] - crop[1]) * sy
        lw, lh = clipped[2] * sx, clipped[3] * sy
        if obj["flip_h"]:
            lx = px + (pw - (lx - px + lw))
        if obj["flip_v"]:
            ly = py + (ph - (ly - py + lh))
        rx, ry, rw, rh = _rotate_local(lx - px, ly - py, lw, lh, pw, ph,
                                       obj["rotation_deg"])
        measurable_count += 1
        out_nodes.append({
            "id": node["id"],
            "rect_mm": [px + rx, py + ry, rw, rh],
            "measurable": True,
            "scale_xy": [sx, sy],
            "anisotropic": abs(sx - sy) > 1e-9,
            "source": {"scene_bounds_mm": node["bounds_mm"],
                       "canvas_mm": [cw, ch], "crop_mm": list(crop),
                       "flip_h": obj["flip_h"], "flip_v": obj["flip_v"],
                       "rotation_deg": obj["rotation_deg"]},
        })
    return {
        "panel_id": obj["id"],
        "page_mm": page,
        "coordinate_reference": LAYOUT_ORIGIN,
        "nodes": out_nodes,
        "evidence": {
            "canvas_mm": [cw, ch],
            "panel_rect_mm": [px, py, pw, ph],
            "crop_mm": list(crop),
            "scale_xy": [sx, sy],
            "anisotropic": abs(sx - sy) > 1e-9,
            "rotation_deg": obj["rotation_deg"],
            "node_count": len(out_nodes),
            "measurable_count": measurable_count,
        },
    }


def _overlap_area(a: list[float], b: list[float]) -> float:
    box = _intersect(a, b)
    return box[2] * box[3] if box else 0.0


def _outside_kind(rect: list[float], page: list[float]) -> str | None:
    inside = _intersect(rect, [0.0, 0.0, page[0], page[1]])
    if inside is None:
        return OUTSIDE_PAGE
    if abs(inside[2] - rect[2]) > 1e-9 or abs(inside[3] - rect[3]) > 1e-9:
        return PARTIAL_OUTSIDE
    return None


def precheck_layout(layout: dict[str, Any], target_panel_id: str) -> dict[str, Any]:
    """Pre-place QA for one panel: neighbor/outside risks over every object.

    Overlap of conservative rectangles is reported as POTENTIAL_OVERLAP, never
    as actual occlusion. Hidden neighbours never block; locked never hides.
    Returns ``{target_id, target_rect_mm, page_mm, coordinate_reference,
    target_outside, neighbors: [...], risks: [{kind, object_ids, detail}]}``.
    """
    canonical = validate_layout(layout)
    _req(bool(isinstance(target_panel_id, str) and target_panel_id),
         "target_panel_id must be a non-empty str")
    by_id = {o["id"]: o for o in canonical["objects"]}
    _req(target_panel_id in by_id,
         f"target {target_panel_id!r} not found; have {sorted(by_id)}")
    target = by_id[target_panel_id]
    page = canonical["page_mm"]
    neighbors: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    limited = [target["id"]] if target["measurement_status"] in UNMEASURED_STATUSES else []
    outside = _outside_kind(target["rect_mm"], page) if target["rect_mm"] is not None else None
    for obj in canonical["objects"]:
        if obj["id"] == target_panel_id:
            continue
        unknown_side = (
            obj["measurement_status"] in UNMEASURED_STATUSES
            or obj["rect_mm"] is None
            or target["rect_mm"] is None
        )
        area: float | None = None
        if not unknown_side:
            assert target["rect_mm"] is not None and obj["rect_mm"] is not None
            area = _overlap_area(target["rect_mm"], obj["rect_mm"])
        if unknown_side:
            relation = "unknown"
        elif obj["hidden"]:
            relation = "hidden_non_blocking"
        elif area is not None and area > 0.0:
            relation = "potential_overlap"
        else:
            relation = "disjoint"
        neighbors.append({
            "id": obj["id"],
            "rect_mm": list(obj["rect_mm"]) if obj["rect_mm"] is not None else None,
            "measurement_status": obj["measurement_status"],
            "hidden": obj["hidden"],
            "locked": obj["locked"],
            "relation": relation,
            "overlap_area_mm2": area,
            "outside_page": _outside_kind(obj["rect_mm"], page) if obj["rect_mm"] is not None else None,
        })
        if relation == "potential_overlap":
            assert area is not None
            risks.append({
                "kind": POTENTIAL_OVERLAP,
                "object_ids": [target["id"], obj["id"]],
                "detail": (
                    f"conservative rects overlap by {area:.3f}mm2 "
                    f"(target {target['measurement_status']} vs "
                    f"neighbour {obj['measurement_status']}); potential only, "
                    "not occlusion; locked does not hide" if obj["locked"] else
                    f"conservative rects overlap by {area:.3f}mm2 "
                    f"(target {target['measurement_status']} vs "
                    f"neighbour {obj['measurement_status']}); potential only, "
                    "not occlusion"),
            })
        if obj["measurement_status"] in UNMEASURED_STATUSES:
            limited.append(obj["id"])
    if outside is not None:
        risks.append({
            "kind": outside,
            "object_ids": [target["id"]],
            "detail": f"target rect {target['rect_mm']} vs page {page}",
        })
    if limited:
        risks.append({
            "kind": MEASUREMENT_LIMITED,
            "object_ids": sorted(set(limited)),
            "detail": "unknown/unsupported status or rect None: no measured bound "
                      "is claimed; known positive rects are placeholder bases only",
        })
    return {
        "target_id": target["id"],
        "target_rect_mm": list(target["rect_mm"]) if target["rect_mm"] is not None else None,
        "page_mm": list(page),
        "coordinate_reference": LAYOUT_ORIGIN,
        "target_outside": outside,
        "neighbors": neighbors,
        "risks": risks,
    }
