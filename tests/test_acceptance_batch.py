from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path

from figpact.acceptance_batch import build_batch_acceptance_plan
from figpact.render_api import RenderSession

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "nmr" / "08 NMR.py"
CONFIG = ROOT / "examples" / "nmr" / "nmr.yaml"


def _managed_candidate(tmp_path, workdir, config_name, panel_id):
    config = tmp_path / config_name
    shutil.copyfile(CONFIG, config)
    session = RenderSession(SCRIPT, config, "main", output_dir=tmp_path / workdir)
    opened = session.open()
    frame = opened["frame"]
    record = {"id": panel_id, "type": "panel", "fileId": f"old-{panel_id}.pdf",
              "fileKind": "pdf", "renderOwner": "figpact", "script": str(SCRIPT),
              "figpact": {"config": str(config), "scope": "main"}, "overrides": [],
              "nativeW": 48.0, "nativeH": 48.0, "x": 0.0, "y": 0.0,
              "w": 48.0, "h": 48.0, "rotation": 0,
              "flipH": False, "flipV": False, "figureFrame": 1}
    placement = {key: record.get(key) for key in
                 ("nativeW", "nativeH", "crop", "rotation", "flipH",
                  "flipV", "x", "y", "w", "h")}
    facts = {key: frame.get(key) for key in
             ("frame_revision", "candidate_revision", "source_revision",
              "base_config_revision")}
    facts["science_digest"] = frame["science"]["digest"]
    facts.update(script=str(SCRIPT), config=str(config), scope="main")
    state = session._native._agent._call(session._native._agent._worker.state)
    facts["science_inputs"] = list(state.get("science_inputs") or [])
    facts["module_revision"] = state.get("module_revision")
    candidate = {"panel_id": panel_id, **facts, "session": session,
                 "session_facts": facts, "script": str(SCRIPT),
                 "config": str(config), "scope": "main",
                 "contract": state.get("contract"),
                 "config_patch": state["candidate_patch"],
                 "config_source": config.read_text(encoding="utf-8"),
                 "placement": placement, "required_content": [],
                 "measured_fonts": []}
    return session, frame, candidate, record


def _two_panel_host(tmp_path):
    sessions, frames, candidates, records = [], [], [], []
    for tag in ("a", "b"):
        session, frame, candidate, record = _managed_candidate(
            tmp_path, f"work-{tag}", f"nmr-{tag}.yaml", f"panel-{tag}")
        sessions.append(session)
        frames.append(frame)
        candidates.append(candidate)
        records.append(record)
    doc = {"schema": 3, "project": {"id": "project", "name": "Project"},
           "activeCanvasId": "canvas",
           "canvases": [{"id": "canvas", "name": "Page",
                         "page": {"w": 180, "h": 150}, "objects": records,
                         "layoutGroups": []}]}
    host = {"document": doc, "document_id": "doc",
            "path": str(tmp_path / "layout.json"), "revision": "rev",
            "project_root": str(tmp_path)}
    return sessions, frames, candidates, host


def _close(sessions):
    for session in sessions:
        session.close()


def test_two_candidates_produce_one_next_document(tmp_path):
    sessions, frames, candidates, host = _two_panel_host(tmp_path)
    try:
        original = copy.deepcopy(host["document"])
        batch = build_batch_acceptance_plan(
            candidates, host_document=host, base_revision="rev",
            resources_dir=tmp_path / "owned")
        assert batch["status"] == "READY"
        assert batch["state"] == "PREPARED"
        assert len(batch["batch_id"]) == 64
        assert batch["failures"] == []
        # ONE combined patch covering both panels.
        patch = batch["document_patch"]
        assert patch["canvas_id"] == "canvas"
        assert {u["panel_id"] for u in patch["updates"]} == {"panel-a", "panel-b"}
        assert len(patch["updates"]) == 2
        # ONE next document in which both panels changed.
        assert batch["next_document"] is not None
        changed = {}
        for obj in batch["next_document"]["canvases"][0]["objects"]:
            before = next(o for o in original["canvases"][0]["objects"]
                          if o["id"] == obj["id"])
            changed[obj["id"]] = {k for k in before if before[k] != obj[k]}
        assert set(changed) == {"panel-a", "panel-b"}
        assert all(diff == {"fileId", "figpact"} for diff in changed.values())
        # Manifest carries every batch fact per candidate.
        assert len(batch["manifest"]) == 2
        for entry, frame in zip(sorted(batch["manifest"],
                                       key=lambda e: e["panel_id"]), frames):
            assert entry["pdf_path"] and entry["pdf_sha256"]
            assert entry["config_path"] and entry["config_sha256"]
            assert entry["config_rebuild_verified"] is True
            assert entry["scope"] == "main"
            assert entry["measured_fonts"] == []
            assert entry["frame_revision"] == frame["frame_revision"]
            pdf_bytes = (Path(host["project_root"]) / entry["pdf_path"]).read_bytes()
            assert hashlib.sha256(pdf_bytes).hexdigest() == entry["pdf_sha256"]
            config_bytes = (Path(host["project_root"]) / entry["config_path"]).read_bytes()
            assert hashlib.sha256(config_bytes).hexdigest() == entry["config_sha256"]
            staged = next(o for o in batch["next_document"]["canvases"][0]["objects"]
                          if o["id"] == entry["panel_id"])
            assert staged["fileId"] == entry["pdf_path"]
            assert staged["figpact"] == {"config": entry["config_path"], "scope": "main"}
        assert host["document"] == original
    finally:
        _close(sessions)


def test_failing_candidate_refuses_the_whole_batch_and_stages_nothing(tmp_path):
    sessions, _, candidates, host = _two_panel_host(tmp_path)
    try:
        candidates[1]["config_source"] = candidates[1]["config_source"].replace(
            "peak_font_pt: 6.0", "peak_font_pt: 7.0")
        staging = tmp_path / "owned"
        batch = build_batch_acceptance_plan(
            candidates, host_document=host, base_revision="rev",
            resources_dir=staging)
        assert batch["status"] == "REFUSED"
        assert batch["state"] == "REFUSED"
        assert batch["evidence"]["first_failure"] == "config_persisted"
        assert batch["failures"] == [{"panel_id": "panel-b",
                                      "reason": "config_persisted"}]
        assert batch["resources"] == []
        assert batch["manifest"] == []
        assert batch["document_patch"]["updates"] == []
        assert batch["next_document"] is None
        assert list(staging.rglob("*.pdf")) == []
        assert list(staging.rglob("*.yaml")) == []
        for cleaned in batch["evidence"]["cleaned_up"]:
            assert not Path(cleaned).exists()
        assert host["document"]["canvases"][0]["objects"][0]["fileId"] == "old-panel-a.pdf"
        assert host["document"]["canvases"][0]["objects"][1]["fileId"] == "old-panel-b.pdf"
    finally:
        _close(sessions)


def test_duplicate_panel_id_refuses(tmp_path):
    sessions, _, candidates, host = _two_panel_host(tmp_path)
    try:
        candidates[1]["panel_id"] = "panel-a"
        staging = tmp_path / "owned"
        batch = build_batch_acceptance_plan(
            candidates, host_document=host, base_revision="rev",
            resources_dir=staging)
        assert batch["status"] == "REFUSED"
        assert batch["evidence"]["first_failure"] == "duplicate_panel_id"
        assert {f["panel_id"] for f in batch["failures"]} == {"panel-a"}
        assert all(f["reason"] == "duplicate_panel_id" for f in batch["failures"])
        assert batch["next_document"] is None
        assert not staging.exists()
    finally:
        _close(sessions)


def test_batch_id_stable_for_same_inputs_and_sensitive_to_changes(tmp_path):
    sessions, _, candidates, host = _two_panel_host(tmp_path)
    try:
        first = build_batch_acceptance_plan(
            candidates, host_document=host, base_revision="rev",
            resources_dir=tmp_path / "owned")
        assert first["status"] == "READY"
        retry = build_batch_acceptance_plan(
            candidates, host_document=host, base_revision="rev",
            resources_dir=tmp_path / "owned")
        assert retry["status"] == "READY"
        assert retry["batch_id"] == first["batch_id"]
        other_revision = build_batch_acceptance_plan(
            candidates, host_document=host, base_revision="rev2",
            resources_dir=tmp_path / "owned")
        assert other_revision["batch_id"] != first["batch_id"]
        subset = build_batch_acceptance_plan(
            candidates[:1], host_document=host, base_revision="rev",
            resources_dir=tmp_path / "owned")
        assert subset["batch_id"] != first["batch_id"]
    finally:
        _close(sessions)
