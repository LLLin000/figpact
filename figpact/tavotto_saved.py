"""Read-only capture adapters: saved files and live host envelopes (no renderer)."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .render_contract import LAYOUT_SCHEMA, validate_layout


class SavedLayoutError(ValueError):
    """Saved layout is ambiguous, malformed, or changed during capture."""

class LiveLayoutError(SavedLayoutError):
    """Live in-memory layout is ambiguous, malformed, or changed during capture."""


def _strict_json(data: bytes) -> Any:
    def bad_constant(value: str) -> None:
        raise SavedLayoutError(f"non-finite JSON number {value!r} is not supported")
    try:
        return json.loads(data.decode("utf-8-sig"), parse_constant=bad_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SavedLayoutError(f"invalid saved-layout JSON: {exc}") from exc


def _finite_json(value: Any, what: str = "saved layout", *,
                 error: type[SavedLayoutError] = SavedLayoutError) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise error(f"{what} contains NaN or Infinity")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise error(f"{what} JSON object keys must be strings")
            _finite_json(item, what, error=error)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item, what, error=error)


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _signature(path: Path) -> tuple[Any, ...]:
    try:
        info = path.stat()
        return ("present", info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                info.st_ino, info.st_mode)
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("unreadable",)


def _hash_file(path: Path, observed: dict[Path, tuple[Any, ...]], *,
               error: type[SavedLayoutError] = SavedLayoutError) -> tuple[str | None, str]:
    before = _signature(path)
    observed[path] = before
    if before[0] == "missing":
        return None, "missing"
    if before[0] != "present":
        return None, "unreadable"
    try:
        if not path.is_file():
            return None, "not_regular_file"
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = _signature(path)
        if before != after:
            raise error(f"resource changed while hashing: {path}")
        return digest.hexdigest(), "present"
    except OSError as exc:
        raise error(f"cannot hash referenced resource {path}: {exc}") from exc

def _rect(obj: dict[str, Any]) -> list[float] | None:
    vals = [obj.get(k) for k in ("x", "y", "w", "h")]
    if not all(_num(v) for v in vals):
        return None
    x, y, width, height = (cast(float, v) for v in vals)
    if width <= 0 or height <= 0:
        return None
    return [float(x), float(y), float(width), float(height)]

def _crop(obj: dict[str, Any]) -> tuple[list[float] | None, str | None]:
    crop = obj.get("crop")
    if crop is None:
        return None, None
    if not isinstance(crop, dict) or not all(_num(crop.get(k)) for k in ("x", "y", "w", "h")):
        return None, "malformed_crop"
    x, y, w, h = (float(cast(float, crop[k])) for k in ("x", "y", "w", "h"))
    nw, nh = obj.get("nativeW"), obj.get("nativeH")
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
        return None, "unsupported_crop_bounds"
    if not (_num(nw) and _num(nh)):
        return None, "missing_native_crop_basis"
    native_w, native_h = cast(float, nw), cast(float, nh)
    if native_w <= 0 or native_h <= 0:
        return None, "missing_native_crop_basis"
    return [x * native_w, y * native_h, w * native_w, h * native_h], None


def _resource(obj: dict[str, Any], base: Path,
              observed: dict[Path, tuple[Any, ...]], *,
              error: type[SavedLayoutError] = SavedLayoutError) -> dict[str, Any]:
    raw_id = obj.get("fileId")
    kind = obj.get("fileKind")
    evidence: dict[str, Any] = {"file_id": raw_id, "file_kind": kind}
    script = obj.get("script")
    if kind == "runtime" or (isinstance(raw_id, str) and raw_id.startswith("runtime:")):
        evidence.update(status="runtime_descriptor", declared_fingerprint=(obj.get("source") or {}).get("fingerprint")
                        if isinstance(obj.get("source"), dict) else None,
                        script_path=script if isinstance(script, str) else None,
                        script_sha256=None)
        if kind != "runtime" or not (isinstance(raw_id, str) and raw_id.startswith("runtime:")):
            evidence["status"] = "kind_conflict_runtime_reference"
        elif isinstance(script, str) and script:
            candidate = (base / Path(script.replace("\\", "/"))).resolve()
            try:
                candidate.relative_to(base)
                sha, status = _hash_file(candidate, observed, error=error)
            except ValueError:
                sha, status = None, "outside_base"
            evidence["script_sha256"] = sha
            evidence["script_status"] = status
        return evidence
    if kind not in ("pdf", "raster"):
        evidence["status"] = "unknown_resource_kind"
        return evidence
    if not isinstance(raw_id, str) or not raw_id.strip():
        evidence["status"] = "missing_resource_id"
        return evidence
    candidate = (base / Path(raw_id.replace("\\", "/"))).resolve()
    evidence["path"] = str(candidate)
    try:
        candidate.relative_to(base)
    except ValueError:
        evidence["status"] = "outside_base"
        return evidence
    sha, status = _hash_file(candidate, observed, error=error)
    evidence["status"] = status
    if sha is not None:
        evidence["sha256"] = sha
    # The panel-level script path is a separate saved fact from source.script.
    if isinstance(script, str) and script:
        script_path = (base / Path(script.replace("\\", "/"))).resolve()
        evidence["script_path"] = script
        try:
            script_path.relative_to(base)
            script_sha, script_status = _hash_file(script_path, observed, error=error)
        except ValueError:
            script_sha, script_status = None, "outside_base"
        evidence["script_sha256"] = script_sha
        evidence["script_status"] = script_status
    return evidence


def _canvas_index(canvases: list[Any], selector: str | None) -> tuple[int, dict[str, Any]]:
    if not canvases:
        raise SavedLayoutError("schema 3 saved layout has no canvases")
    if not all(isinstance(c, dict) for c in canvases):
        raise SavedLayoutError("saved canvases must be objects")
    ids = [c.get("id") for c in canvases]
    names = [c.get("name") for c in canvases]
    if any(not isinstance(v, str) or not v.strip() for v in ids + names):
        raise SavedLayoutError("every saved canvas requires non-empty id and name")
    if len(set(ids)) != len(ids):
        raise SavedLayoutError("duplicate canvas ids")
    if selector is None:
        if len(canvases) != 1:
            raise SavedLayoutError("canvas selector required when saved layout has multiple canvases")
        return 0, canvases[0]
    matches = [(i, c) for i, c in enumerate(canvases)
               if selector == c["id"] or selector == c["name"]]
    if len(matches) != 1:
        raise SavedLayoutError(f"canvas selector {selector!r} matched {len(matches)} canvases")
    return matches[0]


def _selected_page(selected: dict[str, Any], *, error: type[SavedLayoutError],
                   what: str) -> dict[str, Any]:
    page = selected.get("page")
    if not isinstance(page, dict) or not _num(page.get("w")) or not _num(page.get("h")) \
            or page["w"] <= 0 or page["h"] <= 0:
        raise error(f"{what} requires finite positive page.w and page.h")
    return page


def _selected_records(selected: dict[str, Any], *, error: type[SavedLayoutError],
                      what: str) -> list[dict[str, Any]]:
    records = selected.get("objects")
    if not isinstance(records, list):
        raise error(f"{what} objects must be a list")
    ids = []
    for record in records:
        if not isinstance(record, dict):
            raise error("every selected object record must be an object")
        oid = record.get("id")
        if not isinstance(oid, str) or not oid.strip():
            raise error("every selected object requires a non-empty id")
        ids.append(oid)
    if len(set(ids)) != len(ids):
        raise error("duplicate selected object ids")
    return cast(list[dict[str, Any]], records)


def _convert_records(records: list[dict[str, Any]], root: Path,
                     observed: dict[Path, tuple[Any, ...]], *,
                     error: type[SavedLayoutError], what: str) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    evidence_objects: dict[str, Any] = {}
    by_type: dict[str, int] = {}
    by_file_kind: dict[str, int] = {}
    groups: set[str] = set()
    panels = visible = 0

    for z, record in enumerate(records):
        oid = record["id"]
        typ = record.get("type")
        is_panel = typ == "panel"
        if isinstance(typ, str):
            by_type[typ] = by_type.get(typ, 0) + 1
        if is_panel:
            panels += 1
            fk = record.get("fileKind")
            if isinstance(fk, str):
                by_file_kind[fk] = by_file_kind.get(fk, 0) + 1
        group = record.get("groupId")
        if group is not None:
            if not isinstance(group, str) or not group.strip():
                raise error(f"object {oid!r} groupId must be non-empty string or absent")
            groups.add(group)
        hidden = record.get("hidden", False)
        locked = record.get("locked", False)
        if not isinstance(hidden, bool) or not isinstance(locked, bool):
            raise error(f"object {oid!r} hidden/locked must be bool")
        if not hidden:
            visible += 1
        rect = _rect(record)
        status = "conservative" if rect is not None else "unknown"
        reason: str | None = None
        rotation: float | None = 0.0
        if is_panel:
            raw_rotation = record.get("rotation", 0)
            if not _num(raw_rotation):
                status, rotation, reason = "unsupported", None, "invalid_panel_rotation"
            elif not math.isclose(float(raw_rotation) / 90, round(float(raw_rotation) / 90), abs_tol=1e-9):
                status, rotation, reason = "unsupported", None, "unsupported_panel_rotation"
            else:
                rotation = float(int(round(float(raw_rotation) / 90)) % 4 * 90)
            crop, crop_reason = _crop(record)
            if crop_reason:
                crop = None
                if crop_reason == "missing_native_crop_basis":
                    status, reason = "unknown", crop_reason
                else:
                    status, reason = "unsupported", crop_reason
        else:
            raw_rotation = record.get("rotationDeg", 0)
            if not _num(raw_rotation):
                status, rotation, reason = "unsupported", None, "invalid_rotation"
            elif not math.isclose(float(raw_rotation) / 90, round(float(raw_rotation) / 90), abs_tol=1e-9):
                status, rotation, reason = "unsupported", None, "unsupported_arbitrary_rotation"
            else:
                rotation = float(int(round(float(raw_rotation) / 90)) % 4 * 90)
            crop = None
        if typ not in ("panel", "text", "shape", "arrow"):
            status, reason = "unsupported", "unknown_object_type"
            rotation = None
        if typ == "panel" and record.get("figureFrame") is None:
            status, reason = "unsupported", "missing_figure_frame_semantics"
        resource = (_resource(record, root, observed, error=error)
                    if is_panel or record.get("fileId") is not None
                    else {"status": "not_applicable"})
        overrides = record.get("overrides", []) if is_panel else []
        if not isinstance(overrides, list):
            raise error(f"object {oid!r} overrides must be a list")
        _finite_json(overrides, what, error=error)
        overrides_rev = _digest(overrides)
        native = None
        if is_panel and _num(record.get("nativeW")) and _num(record.get("nativeH")) \
                and record["nativeW"] > 0 and record["nativeH"] > 0:
            native = [float(record["nativeW"]), float(record["nativeH"])]
        opacity = record.get("opacity")
        if opacity is not None and (not _num(opacity) or opacity < 0 or opacity > 1):
            raise error(f"object {oid!r} opacity must be finite in [0, 1]")
        explicit_owner = record.get("renderOwner")
        owner = explicit_owner if isinstance(explicit_owner, str) and explicit_owner.strip() else (
            "tavotto" if is_panel and record.get("fileKind") == "runtime" else
            "asset" if is_panel and record.get("fileKind") in ("pdf", "raster") else
            "host" if typ in ("text", "shape", "arrow") else None)
        obj: dict[str, Any] = {
            "id": oid, "rect_mm": rect, "measurement_status": status,
            "hidden": hidden, "locked": locked, "rotation_deg": rotation,
            "crop": crop,
            "flip_h": record.get("flipH", False) if is_panel else False,
            "flip_v": record.get("flipV", False) if is_panel else False,
            "kind": typ if isinstance(typ, str) else None,
            "resource": record.get("fileId") if isinstance(record.get("fileId"), str) else None,
            "source": None, "z_index": z, "capabilities": None,
            "group_id": group, "render_owner": owner, "native_size_mm": native,
            "resource_revision": _digest(resource), "overrides_revision": overrides_rev,
            "opacity": float(opacity) if opacity is not None else None,
        }
        if obj["flip_h"] is not True and obj["flip_h"] is not False or \
                obj["flip_v"] is not True and obj["flip_v"] is not False:
            raise error(f"object {oid!r} flipH/flipV must be bool")
        objects.append(obj)
        evidence_objects[oid] = {
            "record": record,
            "geometry_status": status,
            "geometry_reason": reason,
            "resource": resource,
            "overrides": {"owner": "tavotto", "revision": overrides_rev,
                          "present": bool(overrides),
                          "replay_status": "not_replayed"},
        }
    return {"objects": objects, "evidence_objects": evidence_objects,
            "by_type": by_type, "by_file_kind": by_file_kind,
            "groups": groups, "panels": panels, "visible": visible}

def read_saved_layout(layout: str | Path, *, base: str | Path,
                      canvas: str | None = None) -> dict[str, Any]:
    """Convert one explicit schema-2/3 saved layout to a canonical snapshot."""
    path = Path(layout).expanduser().resolve()
    root = Path(base).expanduser().resolve()
    if not root.is_dir():
        raise SavedLayoutError(f"base is not a directory: {root}")
    try:
        before = path.stat()
        raw_bytes = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise SavedLayoutError(f"cannot read saved layout {path}: {exc}") from exc
    if (before.st_size, before.st_mtime_ns, before.st_ino) != \
            (after.st_size, after.st_mtime_ns, after.st_ino) or len(raw_bytes) != after.st_size:
        raise SavedLayoutError("saved layout changed while being read")
    data = _strict_json(raw_bytes)
    _finite_json(data)
    if not isinstance(data, dict):
        raise SavedLayoutError("saved layout root must be an object")
    schema = data.get("schema")
    if schema not in (2, 3):
        raise SavedLayoutError(f"unsupported saved-layout schema: {schema!r}")
    if schema == 2:
        if canvas is not None:
            raise SavedLayoutError("schema 2 is a single saved document; --canvas is not applicable")
        selected = data
        canvas_index: int | None = None
        canvas_id = None
        canvas_name = data.get("name")
        project_id = None
    else:
        project = data.get("project")
        if not isinstance(project, dict):
            raise SavedLayoutError("schema 3 project must be an object")
        canvases = data.get("canvases")
        if not isinstance(canvases, list):
            raise SavedLayoutError("schema 3 canvases must be a list")
        canvas_index, selected = _canvas_index(canvases, canvas)
        canvas_id, canvas_name = selected["id"], selected["name"]
        project_id = project.get("id")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise SavedLayoutError("project id must be a non-empty string when present")
    page = _selected_page(selected, error=SavedLayoutError,
                          what="selected saved canvas")
    records = _selected_records(selected, error=SavedLayoutError,
                                what="selected saved canvas")
    observed_files: dict[Path, tuple[Any, ...]] = {}
    states = _convert_records(records, root, observed_files,
                              error=SavedLayoutError, what="saved layout")
    objects = states["objects"]
    evidence_objects = states["evidence_objects"]
    by_type = states["by_type"]
    by_file_kind = states["by_file_kind"]
    groups = states["groups"]
    panels = states["panels"]
    visible = states["visible"]
    style = selected.get("style")
    saved_canvas_metadata = {k: v for k, v in selected.items()
                             if k not in {"objects", "style"}}
    saved_document_metadata = {k: v for k, v in data.items()
                               if k not in {"canvases", "objects"}}
    evidence = {
        "layout_path": str(path), "base_path": str(root),
        "layout_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "canvas_index": canvas_index, "canvas_name": canvas_name,
        "counts": {"objects": len(records), "panels": panels, "visible": visible,
                   "by_type": by_type, "by_file_kind": by_file_kind,
                   "groups": len(groups)},
        "objects": evidence_objects,
        "layout_groups": selected.get("layoutGroups", []),
        "style": style,
        "saved_metadata": {"document": saved_document_metadata,
                           "canvas": saved_canvas_metadata},
        "limits": ["saved state only; not live", "no renderer or host display proof",
                   "no QA proof", "runtime descriptors and fingerprints are declarations only",
                   "overrides were not replayed",
                   "resource hashes are byte facts only; metadata descriptors are declarations"],
    }
    snapshot = {
        "schema": LAYOUT_SCHEMA, "source_mode": "saved",
        "page_mm": [float(page["w"]), float(page["h"])], "objects": objects,
        "project_id": project_id, "page_id": canvas_id,
        "host_revision": hashlib.sha256(raw_bytes).hexdigest(),
        "extensions": {"tavotto_saved": evidence},
    }
    try:
        canonical = validate_layout(snapshot)
    except (TypeError, ValueError) as exc:
        raise SavedLayoutError(f"saved layout cannot be represented by render contract: {exc}") from exc
    if _signature(path) != ("present", after.st_size, after.st_mtime_ns,
                            after.st_ctime_ns, after.st_ino, after.st_mode):
        raise SavedLayoutError("saved layout changed during capture")
    try:
        final_bytes = path.read_bytes()
    except OSError as exc:
        raise SavedLayoutError(f"cannot recheck saved layout {path}: {exc}") from exc
    if hashlib.sha256(final_bytes).digest() != hashlib.sha256(raw_bytes).digest():
        raise SavedLayoutError("saved layout bytes changed during capture")
    changed = [p for p, signature in observed_files.items()
               if _signature(p) != signature]
    if changed:
        raise SavedLayoutError(f"referenced resources changed during capture: {changed}")
    return canonical


def _live_captured_at(document: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Split the host read-time ``updatedAt`` stamp off the live document facts.

    The host rebuilds ``buildProject()`` with ``updatedAt: Date.now()`` on every
    read, so the stamp is capture metadata, not owned page state: it becomes the
    informational ``captured_at`` snapshot field (excluded from the content hash)
    and is excluded from ``live_metadata.document``. Millisecond numbers become
    UTC ISO-8601; other present values stay as their honest raw string.
    """
    facts = {k: v for k, v in document.items() if k not in {"canvases", "objects"}}
    if "updatedAt" not in facts:
        return None, facts
    stamp = facts.pop("updatedAt")
    if isinstance(stamp, bool):
        raise LiveLayoutError("live document updatedAt must be a non-bool number or string")
    if isinstance(stamp, (int, float)) and math.isfinite(stamp):
        moment = datetime.fromtimestamp(float(stamp) / 1000.0, tz=timezone.utc)
        return moment.isoformat().replace("+00:00", "Z"), facts
    if isinstance(stamp, str) and stamp.strip():
        return stamp, facts
    raise LiveLayoutError("live document updatedAt must be a finite non-bool number or string")


def _live_envelope(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LiveLayoutError("live payload must be an object")
    instance_id = payload.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.strip():
        raise LiveLayoutError("live payload requires a non-empty instance_id string")
    generation = payload.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        raise LiveLayoutError("live payload generation must be a non-negative integer")
    document_id = payload.get("document_id")
    if not isinstance(document_id, str) or not document_id.strip():
        raise LiveLayoutError("live payload requires a non-empty document_id string")
    canvas_id = payload.get("canvas_id")
    if not isinstance(canvas_id, str) or not canvas_id.strip():
        raise LiveLayoutError("live payload requires an exact active canvas_id string")
    project_root = payload.get("project_root")
    if not isinstance(project_root, str) or not project_root.strip():
        raise LiveLayoutError("live payload requires a non-empty project_root string")
    document = payload.get("document")
    if not isinstance(document, dict):
        raise LiveLayoutError("live payload document must be an object")
    unknown = set(payload) - {"instance_id", "generation", "document_id", "canvas_id",
                              "project_root", "document"}
    if unknown:
        raise LiveLayoutError(f"live payload has unknown keys: {sorted(unknown)}")
    return {"instance_id": instance_id, "generation": generation,
            "document_id": document_id, "canvas_id": canvas_id,
            "project_root": project_root, "document": document}


def read_live_layout(payload: dict[str, Any], *, base: str | Path) -> dict[str, Any]:
    """Convert one explicit in-memory live host envelope to a canonical snapshot."""
    root = Path(base).expanduser().resolve()
    if not root.is_dir():
        raise LiveLayoutError(f"base is not a directory: {root}")
    envelope = _live_envelope(payload)
    offered = Path(envelope["project_root"]).expanduser().resolve()
    if offered != root:
        raise LiveLayoutError("live payload project_root must resolve exactly to base")
    _finite_json(envelope["document"], "live document", error=LiveLayoutError)
    data = envelope["document"]
    if data.get("schema") != 3:
        raise LiveLayoutError(f"unsupported live document schema: {data.get('schema')!r}")
    project = data.get("project")
    if not isinstance(project, dict):
        raise LiveLayoutError("live document project must be an object")
    canvases = data.get("canvases")
    if not isinstance(canvases, list):
        raise LiveLayoutError("live document canvases must be a list")
    if not all(isinstance(c, dict) for c in canvases):
        raise LiveLayoutError("live canvases must be objects")
    ids = [c.get("id") for c in canvases]
    names = [c.get("name") for c in canvases]
    if any(not isinstance(v, str) or not v.strip() for v in ids + names):
        raise LiveLayoutError("every live canvas requires non-empty id and name")
    if len(set(ids)) != len(ids):
        raise LiveLayoutError("duplicate live canvas ids")
    matches = [c for c in canvases if c["id"] == envelope["canvas_id"]]
    if len(matches) != 1:
        raise LiveLayoutError(
            f"live canvas_id {envelope['canvas_id']!r} matched {len(matches)} live canvases")
    selected = matches[0]
    canvas_index = next(i for i, c in enumerate(canvases) if c["id"] == envelope["canvas_id"])
    page = _selected_page(selected, error=LiveLayoutError, what="selected live canvas")
    records = _selected_records(selected, error=LiveLayoutError, what="selected live canvas")
    observed_files: dict[Path, tuple[Any, ...]] = {}
    states = _convert_records(records, root, observed_files,
                              error=LiveLayoutError, what="live document")
    captured_at, document_facts = _live_captured_at(data)
    evidence = {
        "base_path": str(root),
        "canvas_index": canvas_index, "canvas_name": selected["name"],
        "counts": {"objects": len(records), "panels": states["panels"],
                   "visible": states["visible"], "by_type": states["by_type"],
                   "by_file_kind": states["by_file_kind"], "groups": len(states["groups"])},
        "objects": states["evidence_objects"],
        "layout_groups": selected.get("layoutGroups", []),
        "style": selected.get("style"),
        "live_metadata": {
            "document": document_facts,
            "canvas": {k: v for k, v in selected.items() if k not in {"objects", "style"}},
        },
        "instance_id": envelope["instance_id"], "generation": envelope["generation"],
        "document_id": envelope["document_id"], "project_root": str(offered),
        "limits": ["live capture only; no saved-path claim", "no renderer or host display proof",
                   "no QA proof", "runtime descriptors and fingerprints are declarations only",
                   "overrides were not replayed",
                   "resource hashes are byte facts only; metadata descriptors are declarations"],
    }
    snapshot = {
        "schema": LAYOUT_SCHEMA, "source_mode": "live",
        "page_mm": [float(page["w"]), float(page["h"])], "objects": states["objects"],
        "project_id": envelope["document_id"], "page_id": envelope["canvas_id"],
        "host_revision": f"{envelope['instance_id']}:{envelope['generation']}",
        "extensions": {"tavotto_live": evidence},
    }
    if captured_at is not None:
        snapshot["captured_at"] = captured_at
    try:
        canonical = validate_layout(snapshot)
    except (TypeError, ValueError) as exc:
        raise LiveLayoutError(f"live layout cannot be represented by render contract: {exc}") from exc
    changed = [p for p, signature in observed_files.items()
               if _signature(p) != signature]
    if changed:
        raise LiveLayoutError(f"referenced resources changed during capture: {changed}")
    return canonical
