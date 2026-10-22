from __future__ import annotations

import base64
import hashlib
import io
import json

import pytest
from PIL import Image

from figpact.frame_binding import FrameBindingError, bind_frame, validate_display
from figpact.render_contract import validate_layout


def _layout(**panel_changes):
    panel = {"id": "panel", "kind": "panel", "render_owner": "figpact",
             "measurement_status": "measured", "rect_mm": [10, 20, 40, 50],
             "rotation_deg": 90, "flip_h": True, "crop": [25, 10, 50, 40],
             "native_size_mm": [100, 80], "resource_revision": "r1", "overrides_revision": "o1"}
    panel.update(panel_changes)
    return validate_layout({"schema": "figpact.layout/1", "source_mode": "live", "page_mm": [180, 150],
                            "project_id": "doc", "page_id": "canvas", "objects": [panel]})


def _frame(extent=(200, 160), source="source-1"):
    image = Image.new("RGB", (20, 16), "white")
    data = io.BytesIO()
    image.save(data, format="PNG")
    png = data.getvalue()
    scene = {"schema": "figpact.inspector.scene/1", "scope": "main", "source_revision": source,
             "unit": "mm", "coordinate_reference": "canvas_bottom_left",
             "canvas_bounds_mm": [0, 0, *extent],
             "image": {"width_px": 20, "height_px": 16},
             "nodes": [{"id": "label", "gid": "label", "visible": True, "measured": True,
                        "bounds_mm": [50, 100, 70, 120]}]}
    scene_json = json.dumps(scene, sort_keys=True, separators=(",", ":"))
    png_sha = hashlib.sha256(png).hexdigest()
    scene_sha = hashlib.sha256(scene_json.encode()).hexdigest()
    revision = hashlib.sha256(f"{png_sha}\n{scene_sha}".encode("ascii")).hexdigest()
    return {"schema": "figpact.inspector/1", "frame_revision": revision, "image_revision": revision,
            "geometry_revision": revision, "png_base64": base64.b64encode(png).decode(),
            "png_sha256": png_sha, "scene_json": scene_json, "scene_sha256": scene_sha,
            "candidate_revision": "candidate", "revision": "candidate", "source_revision": source,
            "base_config_revision": "config", "scope": "main"}


def test_binding_projects_normalized_crop_on_changed_native_extent_with_rotation_and_flip():
    layout = _layout()
    result = bind_frame(layout, "panel", _frame(), 4)
    assert result["binding"]["native_size_mm"] == [200, 160]
    assert result["binding"]["native_size_changed"] is True
    assert result["binding"]["preview_ref"].startswith("sha256:")
    assert result["projection"]["evidence"]["crop_mm"] == [50, 20, 100, 80]
    assert result["projection"]["evidence"]["rotation_deg"] == 90
    assert result["projection"]["evidence"]["panel_rect_mm"] == [10, 20, 40, 50]
    assert layout["objects"][0]["crop"] == [25, 10, 50, 40]
    assert layout["objects"][0]["native_size_mm"] == [100, 80]


def test_binding_rejects_stale_source_revision_canvas_and_frame():
    stale_frame = _frame()
    stale_frame["source_revision"] = "different"
    with pytest.raises(FrameBindingError):
        bind_frame(_layout(), "panel", stale_frame, 0)
    bad_frame = _frame()
    bad_frame["scene_json"] = bad_frame["scene_json"].replace('"width_px":20', '"width_px":21')
    with pytest.raises(FrameBindingError):
        bind_frame(_layout(), "panel", bad_frame, 0)
    changed_canvas = _layout()
    changed_canvas["page_id"] = "other-canvas"
    changed_canvas.pop("revision")
    changed_canvas = validate_layout(changed_canvas)
    assert changed_canvas["revision"] != _layout()["revision"]
    old_offer = bind_frame(_layout(), "panel", _frame(), 1)["binding"]
    current_offer = bind_frame(changed_canvas, "panel", _frame(), 2)["binding"]
    with pytest.raises(FrameBindingError):
        validate_display({**old_offer, "display_status": "displayed"}, current_offer)
    bad_frame = _frame()
    bad_frame["frame_revision"] = "0" * 64
    with pytest.raises(FrameBindingError):
        bind_frame(_layout(), "panel", bad_frame, 0)
    with pytest.raises(FrameBindingError):
        bind_frame(_layout(render_owner="tavotto"), "panel", _frame(), 0)


def test_request_id_and_display_receipt_are_exactly_bound():
    with pytest.raises(FrameBindingError):
        bind_frame(_layout(), "panel", _frame(), True)
    offered = bind_frame(_layout(crop=None), "panel", _frame(), 2)["binding"]
    displayed = {**offered, "display_status": "displayed"}
    assert validate_display(displayed, offered) == displayed
    with pytest.raises(FrameBindingError):
        validate_display({**displayed, "request_id": 1}, offered)
    with pytest.raises(FrameBindingError):
        validate_display({**displayed, "extra": True}, offered)
