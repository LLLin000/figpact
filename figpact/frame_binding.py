"""Generic same-capture frame and page binding; no host-specific imports."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import math
from typing import Any

from PIL import Image

from .render_contract import precheck_layout, validate_layout


class FrameBindingError(ValueError):
    """A frame cannot be safely bound to the supplied layout."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _finite_scene(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("scene contains a non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _finite_scene(item)
    elif isinstance(value, list):
        for item in value:
            _finite_scene(item)


def _frame_scene(frame: dict[str, Any]) -> tuple[dict[str, Any], list[float]]:
    if not isinstance(frame, dict) or frame.get("schema") != "figpact.inspector/1":
        raise FrameBindingError("INVALID_FRAME", "unsupported frame schema")
    try:
        png = base64.b64decode(frame["png_base64"], validate=True)
        scene_json = frame["scene_json"]
        if not isinstance(scene_json, str):
            raise ValueError("scene_json must be text")
        scene_bytes = scene_json.encode("utf-8")
        scene = json.loads(scene_json, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
        _finite_scene(scene)
        png_hash = hashlib.sha256(png).hexdigest()
        scene_hash = hashlib.sha256(scene_bytes).hexdigest()
        revision = hashlib.sha256(f"{png_hash}\n{scene_hash}".encode("ascii")).hexdigest()
        if (frame.get("png_sha256") != png_hash or frame.get("scene_sha256") != scene_hash
                or any(frame.get(k) != revision for k in ("frame_revision", "image_revision", "geometry_revision"))):
            raise ValueError("frame digest or revision chain mismatch")
        with Image.open(io.BytesIO(png)) as decoded:
            if decoded.format != "PNG":
                raise ValueError("frame image is not PNG")
            decoded.load()
            width_px, height_px = decoded.size
        bounds = scene["canvas_bounds_mm"]
        if (scene.get("schema") != "figpact.inspector.scene/1" or scene.get("unit") != "mm"
                or scene.get("coordinate_reference") != "canvas_bottom_left"
                or not isinstance(bounds, list) or len(bounds) != 4):
            raise ValueError("invalid scene schema or coordinates")
        x0, y0, x1, y1 = map(float, bounds)
        width, height = x1 - x0, y1 - y0
        image = scene["image"]
        if (not all(math.isfinite(v) for v in (x0, y0, width, height)) or width <= 0 or height <= 0
                or image.get("width_px") != width_px or image.get("height_px") != height_px):
            raise ValueError("invalid measured extent or image dimensions")
        if (not isinstance(frame.get("source_revision"), str) or not frame["source_revision"]
                or not isinstance(frame.get("candidate_revision"), str) or not frame["candidate_revision"]
                or not isinstance(frame.get("base_config_revision"), str) or not frame["base_config_revision"]
                or frame.get("revision") != frame.get("candidate_revision")
                or not isinstance(frame.get("scope"), str) or not frame["scope"]
                or scene.get("scope") != frame["scope"]
                or scene.get("source_revision") != frame["source_revision"]):
            raise ValueError("frame provenance mismatch")
        return scene, [width, height]
    except (KeyError, TypeError, ValueError, UnicodeError, binascii.Error,
            OverflowError, OSError, AttributeError) as exc:
        raise FrameBindingError("INVALID_FRAME", f"invalid same-capture frame: {exc}") from exc


def bind_frame(layout: dict[str, Any], panel_id: str, frame: dict[str, Any], request_id: int) -> dict[str, Any]:
    """Validate one actual frame and project it onto one immutable layout snapshot."""
    try:
        canonical = validate_layout(layout)
    except (TypeError, ValueError) as exc:
        raise FrameBindingError("INVALID_LAYOUT", str(exc)) from exc
    if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
        raise FrameBindingError("INVALID", "request_id must be a nonnegative integer")
    panel = next((obj for obj in canonical["objects"] if obj["id"] == panel_id), None)
    if panel is None:
        raise FrameBindingError("UNKNOWN_PANEL", f"panel {panel_id!r} is absent")
    if panel.get("kind") != "panel" or panel.get("render_owner") != "figpact" or panel.get("hidden"):
        raise FrameBindingError("PANEL_NOT_MANAGED", "target must be a visible figpact-owned panel")
    if panel.get("measurement_status") in ("unknown", "unsupported") or panel.get("rect_mm") is None:
        raise FrameBindingError("UNSUPPORTED_GEOMETRY", "target panel geometry is not projectable")
    scene, extent = _frame_scene(frame)
    stored = panel.get("native_size_mm")
    changed = None if stored is None else any(not math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
                                               for a, b in zip(stored, extent))
    projection_panel = dict(panel)
    if changed and panel.get("crop") is not None:
        if stored is None:
            raise FrameBindingError("UNSUPPORTED_GEOMETRY", "crop has no stored native-size basis")
        crop = panel["crop"]
        projection_panel["crop"] = [crop[0] / stored[0] * extent[0], crop[1] / stored[1] * extent[1],
                                     crop[2] / stored[0] * extent[0], crop[3] / stored[1] * extent[1]]
    from .render_api import project_frame_scene
    try:
        projection = project_frame_scene(frame, projection_panel, canonical["page_mm"])
        precheck = precheck_layout(canonical, panel_id)
    except (TypeError, ValueError) as exc:
        raise FrameBindingError("UNSUPPORTED_GEOMETRY", str(exc)) from exc
    binding = {
        "schema": "figpact.frame-binding/1", "snapshot_revision": canonical["revision"],
        "project_id": canonical.get("project_id"), "page_id": canonical.get("page_id"),
        "panel_id": panel_id, "resource_revision": panel.get("resource_revision"),
        "overrides_revision": panel.get("overrides_revision"),
        "source_revision": frame["source_revision"], "base_config_revision": frame["base_config_revision"],
        "frame_revision": frame["frame_revision"], "native_size_mm": extent,
        "preview_ref": "sha256:" + frame["png_sha256"], "scene_ref": "sha256:" + frame["scene_sha256"],
        "request_id": request_id, "display_status": "offered", "native_size_changed": changed,
        "limits": ["client-reported image load is not host acceptance or QA",
                   "no page or native-size mutation",
                   "frame and scene references identify captured bytes, not a final export"],
    }
    return {"binding": binding, "projection": projection, "precheck": precheck}


_BINDING_KEYS = frozenset({
    "schema", "snapshot_revision", "project_id", "page_id", "panel_id",
    "resource_revision", "overrides_revision", "source_revision", "base_config_revision",
    "frame_revision", "native_size_mm", "preview_ref", "scene_ref", "request_id",
    "display_status", "native_size_changed", "limits",
})


def _validate_binding(value: dict[str, Any], status: str) -> None:
    if set(value) != _BINDING_KEYS or value.get("schema") != "figpact.frame-binding/1":
        raise FrameBindingError("BINDING_MISMATCH", "invalid FrameBinding schema or fields")
    for key in ("snapshot_revision", "panel_id", "source_revision", "base_config_revision", "frame_revision"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise FrameBindingError("BINDING_MISMATCH", f"{key} must be a non-empty string")
    if len(value["snapshot_revision"]) != 64 or any(c not in "0123456789abcdef" for c in value["snapshot_revision"]):
        raise FrameBindingError("BINDING_MISMATCH", "snapshot_revision must be lowercase SHA-256")
    for key in ("project_id", "page_id", "resource_revision", "overrides_revision"):
        item = value.get(key)
        if item is not None and (not isinstance(item, str) or not item):
            raise FrameBindingError("BINDING_MISMATCH", f"{key} must be a non-empty string or null")
    extent = value.get("native_size_mm")
    if (not isinstance(extent, list) or len(extent) != 2
            or any(isinstance(n, bool) or not isinstance(n, (int, float))
                   or not math.isfinite(n) or n <= 0 for n in extent)):
        raise FrameBindingError("BINDING_MISMATCH", "native_size_mm must contain two finite positive numbers")
    for key in ("preview_ref", "scene_ref"):
        ref = value.get(key)
        if not isinstance(ref, str) or len(ref) != 71 or not ref.startswith("sha256:") \
                or any(c not in "0123456789abcdef" for c in ref[7:]):
            raise FrameBindingError("BINDING_MISMATCH", f"{key} must be a sha256 content reference")
    request_id = value.get("request_id")
    if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
        raise FrameBindingError("BINDING_MISMATCH", "request_id must be a nonnegative integer")
    if value.get("display_status") != status:
        raise FrameBindingError("BINDING_MISMATCH", f"display_status must be {status!r}")
    changed = value.get("native_size_changed")
    if changed is not None and not isinstance(changed, bool):
        raise FrameBindingError("BINDING_MISMATCH", "native_size_changed must be bool or null")
    limits = value.get("limits")
    if not isinstance(limits, list) or not all(isinstance(item, str) for item in limits):
        raise FrameBindingError("BINDING_MISMATCH", "limits must be a string list")

def validate_display(binding: dict[str, Any], offered: dict[str, Any]) -> dict[str, Any]:
    """Return a client-reported displayed binding only for the exact current offer."""
    if not isinstance(binding, dict) or not isinstance(offered, dict):
        raise FrameBindingError("BINDING_MISMATCH", "binding must be an object")
    _validate_binding(offered, "offered")
    _validate_binding(binding, "displayed")
    expected = {**offered, "display_status": "displayed"}
    if binding != expected:
        raise FrameBindingError("BINDING_MISMATCH", "display receipt does not match the current offer")
    return {**binding}
