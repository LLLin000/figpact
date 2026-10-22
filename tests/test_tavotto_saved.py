"""G2-A: public saved-page capture, without running scripts or mutating layout."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from figpact.render_contract import project_scene, validate_layout
from figpact.tavotto_saved import LiveLayoutError, SavedLayoutError, read_live_layout, read_saved_layout


def _panel(oid: str, **changes: Any) -> dict[str, Any]:
    return {"id": oid, "type": "panel", "fileId": "photo.png", "fileKind": "raster",
            "nativeW": 100.0, "nativeH": 80.0, "x": 10.0, "y": 20.0,
            "w": 40.0, "h": 32.0, "figureFrame": 1, "overrides": [], **changes}


def _save(root: Path, objects: list[dict[str, Any]], **canvas_changes: Any) -> tuple[Path, dict[str, Any]]:
    canvas = {"id": "page", "name": "Page", "page": {"w": 180.0, "h": 150.0},
              "objects": objects, "layoutGroups": [], **canvas_changes}
    document: dict[str, Any] = {"schema": 3, "project": {"id": "project", "name": "Project"},
                "activeCanvasId": "page", "canvases": [canvas]}
    path = root / "saved.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path, document


def _photo(root: Path, color: str = "red") -> None:
    Image.new("RGB", (8, 6), color).save(root / "photo.png")


def test_all_31_panels_and_two_texts_are_captured_without_execution(tmp_path):
    _photo(tmp_path)
    script = tmp_path / "plot.py"
    script.write_text("raise RuntimeError('saved capture must not execute me')\n", encoding="utf-8")
    runtime = [_panel(f"runtime-{i}", fileId=f"runtime:plot.py#figure-{i}", fileKind="runtime",
                      script="plot.py", source={"script": "plot.py", "entry": "main",
                      "stem": f"figure-{i}", "fingerprint": "declared-capture", "sizeMm": [100, 80]})
               for i in range(3)]
    pdfs = [_panel(f"pdf-{i}", fileId=f"missing-{i}.pdf", fileKind="pdf") for i in range(2)]
    photos = [_panel(f"photo-{i}", groupId="photos" if i < 2 else None) for i in range(26)]
    texts = [{"id": f"text-{i}", "type": "text", "text": "Page heading", "sizePt": 10,
              "x": 2, "y": 3 + i * 8, "w": 80, "h": 6} for i in range(2)]
    objects = runtime + pdfs + photos + texts
    objects[3]["overrides"] = [{"gid": "axis.title", "prop": "fontsize", "value": 9}]
    groups = [{"id": "photos", "kind": "row", "order": ["photo-0", "photo-1"],
               "gap": 2, "align": "start"}]
    path, _ = _save(tmp_path, objects, layoutGroups=groups)
    original = path.read_bytes()
    result = read_saved_layout(path, base=tmp_path, canvas="page")
    facts = result["extensions"]["tavotto_saved"]
    assert [o["id"] for o in result["objects"]] == [o["id"] for o in objects]
    assert [o["z_index"] for o in result["objects"]] == list(range(33))
    assert facts["counts"]["objects"] == 33 and facts["counts"]["panels"] == 31
    assert facts["counts"]["by_file_kind"] == {"runtime": 3, "pdf": 2, "raster": 26}
    assert facts["layout_groups"] == groups
    assert result["objects"][5]["group_id"] == "photos"
    assert all(o["render_owner"] == "tavotto" for o in result["objects"][:3])
    assert all(o["render_owner"] == "asset" for o in result["objects"][3:31])
    assert all(o["render_owner"] == "host" for o in result["objects"][31:])
    assert all(o["measurement_status"] == "conservative" for o in result["objects"])
    assert facts["objects"]["photo-0"]["overrides"]["present"] is False
    assert facts["objects"]["pdf-0"]["overrides"]["owner"] == "tavotto"
    assert facts["objects"]["pdf-0"]["overrides"]["replay_status"] == "not_replayed"
    assert facts["objects"]["runtime-0"]["record"]["fileId"].startswith("runtime:")
    assert facts["objects"]["pdf-0"]["resource"]["status"] == "missing"
    assert result["source_mode"] == "saved" and result["page_id"] == "page"
    assert result["host_revision"] == hashlib.sha256(original).hexdigest()
    assert validate_layout(result) == result
    assert read_saved_layout(path, base=tmp_path, canvas="page") == result
    assert path.read_bytes() == original
    assert not (tmp_path / "__pycache__").exists()


def test_resource_and_override_changes_invalidate_snapshot_without_resizing(tmp_path):
    _photo(tmp_path)
    path, document = _save(tmp_path, [_panel("photo")])
    before_bytes = path.read_bytes()
    first = read_saved_layout(path, base=tmp_path)
    _photo(tmp_path, "blue")
    second = read_saved_layout(path, base=tmp_path)
    assert first["revision"] != second["revision"]
    assert first["objects"][0]["resource_revision"] != second["objects"][0]["resource_revision"]
    assert first["objects"][0]["rect_mm"] == second["objects"][0]["rect_mm"] == [10, 20, 40, 32]
    assert path.read_bytes() == before_bytes
    document["canvases"][0]["objects"][0]["overrides"] = [
        {"gid": "axis.title", "prop": "fontsize", "value": 9}]
    path.write_text(json.dumps(document), encoding="utf-8")
    edited_bytes = path.read_bytes()
    third = read_saved_layout(path, base=tmp_path)
    assert third["revision"] != second["revision"]
    assert third["objects"][0]["overrides_revision"] != second["objects"][0]["overrides_revision"]
    assert third["objects"][0]["rect_mm"] == second["objects"][0]["rect_mm"]
    assert path.read_bytes() == edited_bytes


def test_crop_flip_and_quarter_rotation_use_placed_not_native_extent(tmp_path):
    _photo(tmp_path)
    raw = _panel("rotated", w=40, h=50, rotation=90, flipH=True,
                 crop={"x": .25, "y": .125, "w": .5, "h": .5})
    path, _ = _save(tmp_path, [raw])
    result = read_saved_layout(path, base=tmp_path)
    panel = result["objects"][0]
    assert panel["rect_mm"] == [10, 20, 40, 50]
    assert panel["native_size_mm"] == [100, 80]
    assert panel["crop"] == [25, 10, 50, 40]
    assert panel["rotation_deg"] == 90 and panel["flip_h"] is True
    scene = {"coordinate_reference": "canvas_bottom_left", "canvas_mm": [100, 80],
             "nodes": [{"id": "label", "bounds_mm": [25, 30, 35, 40], "measured": True}]}
    projected = project_scene(scene, panel, result["page_mm"])
    assert projected["nodes"][0]["rect_mm"] == pytest.approx([10, 60, 10, 10])


def test_unsupported_objects_and_missing_crop_basis_stay_visible_as_unknown(tmp_path):
    objects = [
        {"id": "future", "type": "future-kind", "payload": {"x": "opaque"}},
        {"id": "turned", "type": "shape", "rotationDeg": 33, "x": 1, "y": 2, "w": 10, "h": 8},
        _panel("crop-without-native", nativeW=None, nativeH=None,
               crop={"x": .2, "y": .1, "w": .5, "h": .5}),
    ]
    path, _ = _save(tmp_path, objects)
    result = read_saved_layout(path, base=tmp_path)
    assert len(result["objects"]) == 3
    for obj in result["objects"]:
        assert obj["measurement_status"] in {"unknown", "unsupported"}
    facts = result["extensions"]["tavotto_saved"]["objects"]
    assert facts["future"]["record"] == objects[0]
    assert facts["turned"]["record"]["rotationDeg"] == 33
    assert result["objects"][1]["rotation_deg"] is None
    assert facts["crop-without-native"]["record"]["crop"] == objects[2]["crop"]
    assert result["objects"][2]["crop"] is None


def test_canvas_selection_never_uses_saved_active_canvas_as_live_authority(tmp_path):
    path, document = _save(tmp_path, [])
    second = copy.deepcopy(document["canvases"][0])
    second["id"] = "other"
    document["canvases"].append(second)
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SavedLayoutError):
        read_saved_layout(path, base=tmp_path)
    with pytest.raises(SavedLayoutError):
        read_saved_layout(path, base=tmp_path, canvas="Page")
    with pytest.raises(SavedLayoutError):
        read_saved_layout(path, base=tmp_path, canvas="not-found")
    chosen = read_saved_layout(path, base=tmp_path, canvas="other")
    assert chosen["page_id"] == "other" and chosen["source_mode"] == "saved"
    assert chosen["objects"] == []


@pytest.mark.parametrize("case", ["duplicate-id", "future-schema", "nonfinite"])
def test_ambiguous_or_nonfinite_saved_data_is_refused(tmp_path, case):
    objects = [_panel("same"), _panel("same")] if case == "duplicate-id" else []
    path, document = _save(tmp_path, objects)
    if case == "future-schema":
        document["schema"] = 999
        path.write_text(json.dumps(document), encoding="utf-8")
    elif case == "nonfinite":
        document["canvases"][0]["page"]["w"] = float("nan")
        path.write_text(json.dumps(document), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(SavedLayoutError):
        read_saved_layout(path, base=tmp_path)
    assert path.read_bytes() == original


def test_legacy_single_saved_canvas_and_cli_are_still_explicitly_saved(tmp_path, capsys):
    from figpact.cli import main

    path = tmp_path / "schema2.json"
    data = {"schema": 2, "name": "Single", "page": {"w": 180, "h": 150}, "objects": []}
    path.write_text(json.dumps(data), encoding="utf-8")
    original = path.read_bytes()
    assert main(["layout-snapshot", "--layout", str(path), "--base", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source_mode"] == "saved" and result["objects"] == []
    assert result["host_revision"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original


def test_actual_adapter_snapshot_validates_shared_wire_contract(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    _photo(tmp_path)
    path, _ = _save(tmp_path, [_panel("photo", groupId="group", opacity=.5, renderOwner="figpact",
                                   overrides=[{"gid": "title", "prop": "fontsize", "value": 8}])])
    snapshot = read_saved_layout(path, base=tmp_path)
    assert snapshot["objects"][0]["render_owner"] == "figpact"
    assert snapshot["extensions"]["tavotto_saved"]["objects"]["photo"]["overrides"]["present"] is True
    schema = json.loads((Path(__file__).resolve().parents[1] /
                         "docs/schema/render.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator({
        "$schema": schema["$schema"], "$defs": schema["$defs"],
        "$ref": "#/$defs/LayoutSnapshot",
    }).validate(snapshot)


@pytest.mark.parametrize("changed", ["layout", "resource"])
def test_changes_during_multi_resource_capture_are_refused(tmp_path, monkeypatch, changed):
    _photo(tmp_path)
    second_photo = tmp_path / "second.png"
    Image.new("RGB", (8, 6), "green").save(second_photo)
    path, document = _save(tmp_path, [_panel("first"), _panel("second", fileId="second.png")])
    original_open = Path.open
    triggered = False

    def open_with_external_edit(self, mode="r", *args, **kwargs):
        nonlocal triggered
        stream = original_open(self, mode, *args, **kwargs)
        if self.resolve() == second_photo.resolve() and mode == "rb" and not triggered:
            triggered = True
            if changed == "layout":
                document["canvases"][0]["objects"][0]["x"] = 90
                path.write_text(json.dumps(document), encoding="utf-8")
            else:
                _photo(tmp_path, "blue")
        return stream

    monkeypatch.setattr(Path, "open", open_with_external_edit)
    with pytest.raises(SavedLayoutError):
        read_saved_layout(path, base=tmp_path)
    assert triggered is True

def _live_document(objects: list[dict[str, Any]], **canvas_changes: Any) -> dict[str, Any]:
    canvas = {"id": "page", "name": "Page", "page": {"w": 180.0, "h": 150.0},
              "objects": objects, "layoutGroups": [], **canvas_changes}
    return {"schema": 3, "project": {"id": "project", "name": "Project"},
            "activeCanvasId": "other", "canvases": [canvas]}


def _live_payload(document: dict[str, Any], root: Path, **changes: Any) -> dict[str, Any]:
    payload = {"instance_id": "browser-1", "generation": 7, "document_id": "doc-9",
               "canvas_id": "page", "project_root": str(root), "document": document}
    payload.update(changes)
    return payload


def test_live_capture_uses_exact_active_canvas_with_full_object_fidelity(tmp_path):
    _photo(tmp_path)
    groups = [{"id": "photos", "kind": "row", "order": ["kept"], "gap": 2, "align": "start"}]
    moved = _panel("kept", x=30.0, renderOwner="figpact",
                   **{"figpact": {"scope": "demo", "config": "fig.yaml"},
                      "overrides": [{"gid": "title", "prop": "fontsize", "value": 8}]})
    document = _live_document(
        [moved, {"id": "note", "type": "text", "text": "hi",
                "x": 2, "y": 3, "w": 80, "h": 6}],
        layoutGroups=groups, style={"theme": "light"})
    result = read_live_layout(_live_payload(document, tmp_path), base=tmp_path)
    assert result["source_mode"] == "live"
    assert result["project_id"] == "doc-9" and result["page_id"] == "page"
    assert result["host_revision"] == "browser-1:7"
    live = result["extensions"]["tavotto_live"]
    assert live["instance_id"] == "browser-1" and live["generation"] == 7
    assert live["document_id"] == "doc-9" and live["project_root"] == str(tmp_path.resolve())
    assert "layout_sha256" not in live and "layout_path" not in live
    assert live["counts"]["objects"] == 2 and live["layout_groups"] == groups
    assert live["style"] == {"theme": "light"}
    assert [o["id"] for o in result["objects"]] == ["kept", "note"]
    assert result["objects"][0]["rect_mm"] == [30.0, 20.0, 40.0, 32.0]
    assert result["objects"][0]["render_owner"] == "figpact"
    assert live["objects"]["kept"]["record"]["figpact"] == {"scope": "demo", "config": "fig.yaml"}
    assert live["objects"]["kept"]["overrides"]["present"] is True
    assert live["objects"]["kept"]["resource"]["status"] == "present"
    assert live["objects"]["note"]["record"]["text"] == "hi"
    assert validate_layout(result) == result


def test_live_move_invalidates_saved_snapshot_but_repeat_capture_is_stable(tmp_path):
    _photo(tmp_path)
    path, document = _save(tmp_path, [_panel("photo")])
    saved = read_saved_layout(path, base=tmp_path)
    live_document = _live_document([_panel("photo", x=90.0)])
    moved = read_live_layout(_live_payload(live_document, tmp_path), base=tmp_path)
    assert moved["objects"][0]["rect_mm"] == [90.0, 20.0, 40.0, 32.0]
    assert moved["revision"] != saved["revision"]
    assert moved["objects"][0]["rect_mm"] != saved["objects"][0]["rect_mm"]
    assert read_live_layout(_live_payload(live_document, tmp_path),
                            base=tmp_path) == moved


def test_live_canvas_project_root_switches_and_revisions_change(tmp_path):
    _photo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _photo(other)
    first = _live_document([_panel("photo")])
    second = copy.deepcopy(first)
    second["canvases"].append({"id": "other", "name": "Other",
                               "page": {"w": 100.0, "h": 90.0}, "objects": []})
    canvas_switched = read_live_layout(_live_payload(second, tmp_path, canvas_id="other"),
                                       base=tmp_path)
    assert canvas_switched["page_id"] == "other"
    assert canvas_switched["objects"] == [] and canvas_switched["page_mm"] == [100.0, 90.0]
    canvas_same = read_live_layout(_live_payload(first, tmp_path), base=tmp_path)
    assert canvas_same["page_id"] == "page" and len(canvas_same["objects"]) == 1
    assert canvas_same["revision"] != canvas_switched["revision"]
    root_switched = read_live_layout(_live_payload(first, other), base=other)
    assert root_switched["revision"] != canvas_same["revision"]
    assert root_switched["extensions"]["tavotto_live"]["project_root"] == str(other.resolve())
    resource_changed = copy.deepcopy(first)
    resource_changed["canvases"][0]["objects"][0]["overrides"] = [
        {"gid": "title", "prop": "fontsize", "value": 8}]
    assert read_live_layout(_live_payload(resource_changed, tmp_path),
                            base=tmp_path)["revision"] != canvas_same["revision"]
    _photo(tmp_path, "blue")
    assert read_live_layout(_live_payload(first, tmp_path),
                            base=tmp_path)["revision"] != canvas_same["revision"]


@pytest.mark.parametrize("case", ["bool-generation", "name-selector", "root-mismatch",
                                  "malformed-id", "duplicate-id", "future-schema",
                                  "nonfinite", "unknown-key"])
def test_malformed_or_ambiguous_live_payload_is_refused(tmp_path, case):
    _photo(tmp_path)
    document = _live_document([_panel("same"), _panel("same")] if case == "duplicate-id" else [])
    if case == "future-schema":
        document["schema"] = 999
    elif case == "nonfinite":
        document["canvases"][0]["page"]["w"] = float("nan")
    payload = _live_payload(document, tmp_path)
    if case == "bool-generation":
        payload["generation"] = True
    elif case == "name-selector":
        payload["canvas_id"] = "Page"
    elif case == "root-mismatch":
        payload["project_root"] = str(tmp_path / "elsewhere")
    elif case == "malformed-id":
        payload["canvas_id"] = "   "
    elif case == "unknown-key":
        payload["extra"] = 1
    with pytest.raises(LiveLayoutError):
        read_live_layout(payload, base=tmp_path)
    assert isinstance(LiveLayoutError("x"), SavedLayoutError)


def test_live_retains_all_raw_objects_resources_groups_and_style(tmp_path):
    _photo(tmp_path)
    script = tmp_path / "plot.py"
    script.write_text("raise RuntimeError('live capture must not execute me')\n", encoding="utf-8")
    objects = [
        _panel("runtime", fileId="runtime:plot.py#figure-0", fileKind="runtime",
               script="plot.py", source={"script": "plot.py", "entry": "main",
               "stem": "figure-0", "fingerprint": "declared-live", "sizeMm": [100, 80]}),
        _panel("missing-pdf", fileId="missing.pdf", fileKind="pdf"),
        _panel("kept", groupId="photos"),
        {"id": "future", "type": "future-kind", "payload": {"x": "opaque"},
         "x": 1, "y": 2, "w": 10, "h": 8},
    ]
    groups = [{"id": "photos", "kind": "row", "order": ["kept"], "gap": 1, "align": "start"}]
    document = _live_document(objects, layoutGroups=groups, style={"theme": "dark"})
    result = read_live_layout(_live_payload(document, tmp_path), base=tmp_path)
    live = result["extensions"]["tavotto_live"]
    assert [o["id"] for o in result["objects"]] == [o["id"] for o in objects]
    assert live["objects"]["runtime"]["record"]["fileId"] == "runtime:plot.py#figure-0"
    assert live["objects"]["missing-pdf"]["resource"]["status"] == "missing"
    assert result["objects"][2]["group_id"] == "photos"
    assert result["objects"][3]["measurement_status"] == "unsupported"
    assert live["layout_groups"] == groups and live["style"] == {"theme": "dark"}
    assert not (tmp_path / "__pycache__").exists()
    assert result["extensions"].keys() == {"tavotto_live"}


def test_live_read_time_stamp_does_not_change_revision(tmp_path):
    _photo(tmp_path)
    first = _live_document([_panel("photo")])
    first["updatedAt"] = 1760000000000
    second = copy.deepcopy(first)
    second["updatedAt"] = 1760000001000
    before = read_live_layout(_live_payload(first, tmp_path), base=tmp_path)
    after = read_live_layout(_live_payload(second, tmp_path), base=tmp_path)
    assert before["revision"] == after["revision"]
    assert "updatedAt" not in before["extensions"]["tavotto_live"]["live_metadata"]["document"]
    assert before["captured_at"] == "2025-10-09T08:53:20Z"
    assert after["captured_at"] == "2025-10-09T08:53:21Z"
    assert validate_layout(after) == after
    assert before["captured_at"] != after["captured_at"]
    edited = copy.deepcopy(second)
    edited["canvases"][0]["objects"][0]["x"] = 90.0
    assert read_live_layout(_live_payload(edited, tmp_path),
                            base=tmp_path)["revision"] != before["revision"]
