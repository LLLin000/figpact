"""Real-engine tests for the standalone RenderSession API."""
from __future__ import annotations

import concurrent.futures
import json
import shutil
import threading
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg", force=True)

ROOT = Path(__file__).resolve().parents[1]
NMR_SCRIPT = ROOT / "examples" / "nmr" / "08 NMR.py"
NMR_YAML = ROOT / "examples" / "nmr" / "nmr.yaml"
CANVAS_W = json.dumps(["canvas_w_mm"], separators=(",", ":"))
CANVAS_H = json.dumps(["canvas_h_mm"], separators=(",", ":"))

from figpact.render_api import RenderError, RenderSession  # noqa: E402


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "nmr.yaml"
    shutil.copyfile(NMR_YAML, path)
    return path


def _layout():
    return {"schema": "figpact.layout/1", "source_mode": "standalone",
            "page_mm": [210.0, 297.0],
            "objects": [{"id": "nmr_main", "kind": "panel",
                         "measurement_status": "measured", "rect_mm": [15.0, 20.0, 68.0, 68.0],
                         "resource": "nmr_trace", "source": {"origin": "test"}}]}


def _intent():
    return {"schema": "figpact.intent/1", "panel_id": "nmr_main",
            "edits": [{"control_id": CANVAS_W, "value": 68.0},
                      {"control_id": CANVAS_H, "value": 68.0}],
            "fit_canvas": True,
            "required_content": ["fig2_nmr.main.peak.vancho.9p83",
                                 "fig2_nmr.main.peak.hama.6p18"],
            "preserve": ["science", "view"]}


def _preview(session, request_id="test"):
    return session.preview(_layout(), _intent(), request_id)


def test_open_preview_projects_measured_frame_and_authorized_controls(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    try:
        opened = session.open()
        assert opened["frame"]["schema"] == "figpact.inspector/1"
        assert opened["frame"]["science"]["verified"] is True
        assert opened["frame"]["evidence"]["host"] == "NOT_CONNECTED"
        assert {CANVAS_W, CANVAS_H} <= {c["control_id"] for c in opened["controls"]}
        result = _preview(session)
        assert result["status"] == "OK"
        assert result["receipt"]["candidate_revision"] == result["frame"]["candidate_revision"]
        assert result["receipt"]["layout_revision"] == result["layout_revision"]
        assert result["required_content"] == {
            "checked": ["fig2_nmr.main.peak.vancho.9p83",
                        "fig2_nmr.main.peak.hama.6p18"], "missing": []}
        scene_nodes = {node.get("gid"): node
                       for node in json.loads(result["frame"]["scene_json"])["nodes"]}
        for gid in result["required_content"]["checked"]:
            assert scene_nodes[gid]["visible"] is True
            assert scene_nodes[gid]["measured"] is True
        assert result["projection"]["evidence"]["canvas_mm"] == pytest.approx([68.0, 68.0], abs=1e-3)
        assert result["evidence"] == {"render": "SAME_CAPTURE_PNG_SCENE",
                                      "persistence": "NOT_WRITTEN", "host": "NOT_CONNECTED",
                                      "export_page": "NOT_RUN"}
        assert session.snapshot()["pending"]["candidate_id"] == result["candidate_id"]
    finally:
        session.close()


@pytest.mark.parametrize("status,hidden", [("unknown", False), ("unsupported", False),
                                           ("measured", True)])
def test_preview_rejects_unmeasured_or_hidden_target_before_edit(tmp_path, status, hidden):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    try:
        session.open()
        layout = _layout()
        layout["objects"][0]["measurement_status"] = status
        layout["objects"][0]["hidden"] = hidden
        with pytest.raises(RenderError) as caught:
            session.preview(layout, _intent(), "invalid-target")
        assert caught.value.status == "UNSUPPORTED_GEOMETRY"
        assert session.snapshot()["pending"] is None
    finally:
        session.close()


def test_font_metrics_scale_uniformly_and_refuse_anisotropic_scalar(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    try:
        session.open()
        layout = _layout()
        layout["objects"][0]["rect_mm"] = [15.0, 20.0, 34.0, 34.0]
        intent = _intent()
        intent["fit_canvas"] = False
        uniform = session.preview(layout, intent, "uniform-scale")
        values = uniform["fonts"]["measured"]
        known = [item for item in values if item["source_font_pt"] is not None]
        assert known
        assert all(item["source"] == "captured_font_size" for item in known)
        scene_nodes = {node.get("gid"): node
                       for node in json.loads(uniform["frame"]["scene_json"])["nodes"]}
        assert all(scene_nodes[item["id"]].get("font_size_pt") == item["source_font_pt"]
                   for item in known)
        assert all(item["effective_font_pt"] == pytest.approx(item["source_font_pt"] * 0.5)
                   for item in known)
        layout["objects"][0]["rect_mm"] = [15.0, 20.0, 34.0, 17.0]
        anisotropic = session.preview(layout, intent, "anisotropic-scale")
        values = anisotropic["fonts"]["measured"]
        assert any(item["anisotropic"] is True and item["effective_font_pt"] is None
                   and item["reason"] == "ANISOTROPIC_SCALE" for item in values)
    finally:
        session.close()


def test_font_metrics_missing_actual_never_falls_back_to_config():
    from figpact.render_api import RenderSession as RenderSessionCls
    projection = {"nodes": [{"id": "peak-label", "rect_mm": [1.0, 2.0, 3.0, 4.0],
                             "measurable": True, "scale_xy": [0.5, 0.5], "anisotropic": False}]}
    nodes = [{"id": "peak-label", "gid": "peak-label", "type": "text", "artist_type": "Text",
              "measured": True, "controlled_by": [["peak_font_pt"]]}]
    fonts = RenderSessionCls._font_metrics(nodes, projection)
    assert fonts["measured"][0]["source_font_pt"] is None
    assert fonts["measured"][0]["effective_font_pt"] is None
    assert fonts["measured"][0]["reason"] == "FONT_SIZE_UNAVAILABLE"


def test_science_changing_font_candidate_is_refused(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    layout = _layout()
    layout["objects"][0]["rect_mm"] = [15.0, 20.0, 48.0, 48.0]
    intent = _intent()
    intent["edits"] = [{"control_id": json.dumps(["peak_font_pt"]), "value": 7.2}]
    intent["fit_canvas"] = False
    try:
        session.open()
        with pytest.raises(RenderError) as caught:
            session.preview(layout, intent, "science-violation")
        assert caught.value.status == "SCIENCE_VIOLATION"
    finally:
        session.close()


def test_fit_canvas_requires_both_authorized_axes_and_rejects_conflict(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    try:
        session.open()
        bad = _intent()
        bad["edits"] = [{"control_id": CANVAS_W, "value": 67.0}]
        with pytest.raises(RenderError) as caught:
            session.preview(_layout(), bad, "conflict")
        assert caught.value.status == "FIT_CONFLICT"
        cropped = _layout()
        cropped["objects"][0]["crop"] = [0.0, 0.0, 30.0, 30.0]
        with pytest.raises(RenderError) as caught:
            session.preview(cropped, _intent(), "crop")
        assert caught.value.status == "CROP_FIT_UNSUPPORTED"
    finally:
        session.close()


def test_required_content_and_authorization_are_fail_closed(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    try:
        session.open()
        missing = _intent()
        missing["required_content"] = ["fig2_nmr.main.missing"]
        with pytest.raises(RenderError) as caught:
            session.preview(_layout(), missing, "missing-gid")
        assert caught.value.status == "REQUIRED_CONTENT_MISSING"
        unauthorized = _intent()
        unauthorized["edits"].append({"control_id": json.dumps(["show_ppm"]), "value": 1})
        with pytest.raises(RenderError) as caught:
            session.preview(_layout(), unauthorized, "locked")
        assert caught.value.status == "INVALID"
    finally:
        session.close()


def test_required_content_partial_crop_fails_closed(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    try:
        opened = session.open()
        scene = json.loads(opened["frame"]["scene_json"])
        gid = "fig2_nmr.main.peak.vancho.9p83"
        node = next(item for item in scene["nodes"] if item.get("gid") == gid)
        canvas_x0, canvas_y0, canvas_x1, canvas_y1 = scene["canvas_bounds_mm"]
        x0, _, x1, _ = node["bounds_mm"]
        crop_right = (x0 - canvas_x0) + (x1 - x0) / 2
        layout = _layout()
        layout["objects"][0]["crop"] = [0.0, 0.0, crop_right, canvas_y1 - canvas_y0]
        intent = _intent()
        intent["fit_canvas"] = False
        intent["required_content"] = [gid]
        with pytest.raises(RenderError) as caught:
            session.preview(layout, intent, "partial-crop")
        assert caught.value.status == "REQUIRED_CONTENT_MISSING"
    finally:
        session.close()


def test_commit_requires_confirm_without_writing_and_reopens_fresh_session(tmp_path):
    cfg = _config(tmp_path)
    before = cfg.read_bytes()
    session = RenderSession(NMR_SCRIPT, cfg, "main")
    try:
        session.open()
        result = _preview(session, "commit-test")
        with pytest.raises(RenderError) as caught:
            session.commit(result["candidate_id"], result["frame_revision"],
                           result["layout_revision"], False, kind="draft")
        assert caught.value.status == "CONFIRM_REQUIRED"
        assert cfg.read_bytes() == before
        committed = session.commit(result["candidate_id"], result["frame_revision"],
                                   result["layout_revision"], True, kind="draft")
        assert committed["status"] == "committed"
        assert committed["verification"] == "DRAFT_SAVED"
        assert "canvas_w_mm: 68.0" in cfg.read_text(encoding="utf-8")
    finally:
        session.close()
    fresh = RenderSession(NMR_SCRIPT, cfg, "main")
    try:
        reopened = fresh.open()
        controls = {c["control_id"]: c["current"] for c in reopened["controls"]}
        assert controls[CANVAS_W] == 68.0 and controls[CANVAS_H] == 68.0
        assert reopened["frame"]["science"]["verified"] is True
    finally:
        fresh.close()


def test_commit_saved_but_refresh_failed_reports_written_frame_null(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    session = RenderSession(NMR_SCRIPT, cfg, "main")
    real_rebuild = session._native._rebuild
    calls = {"count": 0}

    def _fail_rebuild_once():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return real_rebuild()

    session.open()

    try:
        result = _preview(session, "saved-refresh-failed")
        monkeypatch.setattr(session._native, "_rebuild", _fail_rebuild_once)
        committed = session.commit(result["candidate_id"], result["frame_revision"],
                                   result["layout_revision"], True, kind="draft")
        assert committed["status"] == "committed"
        assert committed["frame"] is None
        assert committed["refresh_required"] is True
        assert committed["evidence"] == {"render": "NOT_RUN", "persistence": "WRITTEN",
                                         "host": "NOT_CONNECTED", "export_page": "NOT_RUN"}
        assert "canvas_w_mm: 68.0" in cfg.read_text(encoding="utf-8")
        assert committed["refresh_error"]
        with pytest.raises(RenderError) as caught:
            session.snapshot()
        assert caught.value.status == "REFRESH_REQUIRED"
        with pytest.raises(RenderError) as caught:
            session.export(tmp_path / "exports", result["frame_revision"])
        assert caught.value.status == "REFRESH_REQUIRED"
        with pytest.raises(RenderError) as caught:
            session.commit(result["candidate_id"], result["frame_revision"],
                           result["layout_revision"], True)
        assert caught.value.status == "REFRESH_REQUIRED"
    finally:
        session.close()


def test_source_drift_invalidates_candidate_before_commit(tmp_path):
    cfg = _config(tmp_path)
    session = RenderSession(NMR_SCRIPT, cfg, "main")
    try:
        session.open()
        result = _preview(session, "drift")
        cfg.write_text(cfg.read_text(encoding="utf-8") + "\n# external edit\n", encoding="utf-8")
        before = cfg.read_bytes()
        with pytest.raises(RenderError) as caught:
            session.snapshot()
        assert caught.value.status == "STALE_REVISION"
        with pytest.raises(RenderError) as caught:
            session.commit(result["candidate_id"], result["frame_revision"],
                           result["layout_revision"], True)
        assert caught.value.status == "STALE_REVISION"
        assert cfg.read_bytes() == before
    finally:
        session.close()


def test_cancelled_candidate_cannot_commit_or_export(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    out = tmp_path / "exports"
    out.mkdir()
    try:
        session.open()
        result = _preview(session, "cancel")
        session.cancel(result["candidate_id"])
        with pytest.raises(RenderError) as caught:
            session.commit(result["candidate_id"], result["frame_revision"],
                           result["layout_revision"], True)
        assert caught.value.status == "CANCELLED"
        with pytest.raises(RenderError) as caught:
            session.export(out, result["frame_revision"], candidate_id=result["candidate_id"])
        assert caught.value.status == "EXPORT_STALE"
        assert list(out.iterdir()) == []
    finally:
        session.close()


def test_latest_preview_supersedes_inflight_real_engine_preview(tmp_path):
    session = RenderSession(NMR_SCRIPT, _config(tmp_path), "main")
    entered, release = threading.Event(), threading.Event()
    original = session._native.preview
    first = True

    def gated(body):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(60)
        return original(body)

    session._native.preview = gated
    try:
        session.open()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(_preview, session, "old")
            assert entered.wait(60)
            latest = pool.submit(_preview, session, "latest")
            release.set()
            with pytest.raises(RenderError) as caught:
                old.result(timeout=180)
            assert caught.value.status == "SUPERSEDED"
            current = latest.result(timeout=180)
            assert current["status"] == "OK" and current["request_id"] == "latest"
            with pytest.raises(RenderError) as caught:
                session.commit("obsolete", current["frame_revision"], current["layout_revision"], True)
            assert caught.value.status in {"CANDIDATE_UNKNOWN", "SUPERSEDED"}
    finally:
        release.set()
        session.close()


def test_export_is_exact_immutable_worker_bundle_and_fresh_replay(tmp_path):
    pytest.importorskip("pypdf")
    cfg = _config(tmp_path)
    before = cfg.read_bytes()
    session = RenderSession(NMR_SCRIPT, cfg, "main")
    out = tmp_path / "exports"
    out.mkdir()
    try:
        session.open()
        result = _preview(session, "export")
        exported = session.export(out, result["frame_revision"], result["candidate_id"])
        bundle = exported["bundle"]
        assert bundle["frame_revision"] == result["frame_revision"]
        assert bundle["candidate_revision"] == result["frame"]["candidate_revision"]
        assert bundle["png_sha256"] == result["frame"]["png_sha256"]
        assert Path(bundle["png_path"]).is_file() and Path(bundle["pdf_path"]).is_file()
        assert bundle["evidence"]["host"] == "NOT_CONNECTED"
        assert exported["evidence"]["export_page"] == "NOT_RUN"
        with pytest.raises(RenderError):
            session.export(out, result["frame_revision"], result["candidate_id"])
        assert len(list(out.iterdir())) == 1
        assert cfg.read_bytes() == before
        committed = session.commit(result["candidate_id"], result["frame_revision"],
                                   result["layout_revision"], True, kind="draft")
        assert committed["status"] == "committed"
    finally:
        session.close()
    fresh = RenderSession(NMR_SCRIPT, cfg, "main")
    try:
        replay = fresh.open()
        assert replay["frame"]["science"]["verified"] is True
        assert replay["frame"]["candidate_revision"] == result["frame"]["candidate_revision"]
    finally:
        fresh.close()
