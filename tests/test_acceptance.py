from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path

import pytest


from figpact.acceptance import build_acceptance_plan
from figpact.render_api import RenderSession

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "nmr" / "08 NMR.py"
CONFIG = ROOT / "examples" / "nmr" / "nmr.yaml"


def _case(tmp_path, *, legacy=False, crop=None, overrides=None, geometry=None):
    config = tmp_path / "nmr.yaml"
    shutil.copyfile(CONFIG, config)
    session = RenderSession(SCRIPT, config, "main", output_dir=tmp_path)
    opened = session.open()
    frame = opened["frame"]
    rec = {"id": "panel", "type": "panel", "fileId": "old.pdf", "fileKind": "pdf",
           "renderOwner": "tavotto" if legacy else "figpact", "script": str(SCRIPT),
           "figpact": {"config": str(config), "scope": "main"}, "overrides": overrides or [],
           "nativeW": 48.0, "nativeH": 48.0, "x": 0.0, "y": 0.0, "w": 48.0, "h": 48.0,
           "rotation": 0, "flipH": False, "flipV": False, "figureFrame": 1}
    if crop is not None:
        rec["crop"] = crop
    placement = {key: rec.get(key) for key in
                 ("nativeW", "nativeH", "crop", "rotation", "flipH", "flipV", "x", "y", "w", "h")}
    rec.update(geometry or {})
    doc = {"schema": 3, "project": {"id": "project", "name": "Project"},
           "activeCanvasId": "canvas", "canvases": [{"id": "canvas", "name": "Page",
           "page": {"w": 180, "h": 150}, "objects": [rec], "layoutGroups": []}]}
    facts = {key: frame.get(key) for key in ("frame_revision", "candidate_revision", "source_revision", "base_config_revision")}
    facts["science_digest"] = frame["science"]["digest"]
    facts.update(script=str(SCRIPT), config=str(config), scope="main")
    candidate = {"panel_id": "panel", **facts, "session": session, "session_facts": facts,
                 "script": str(SCRIPT), "config": str(config), "scope": "main",
                 "placement": placement,
                 "required_content": [], "measured_fonts": []}
    host = {"document": doc, "document_id": "doc", "path": str(tmp_path / "layout.json"),
            "revision": "rev", "project_root": str(tmp_path)}
    return session, frame, candidate, host


def test_ready_prepares_exact_frame_and_minimal_next_document(tmp_path):
    session, frame, candidate, host = _case(tmp_path)
    try:
        original = copy.deepcopy(host["document"])
        plan = build_acceptance_plan([candidate], host_document=host, base_revision="rev",
                                     resources_dir=tmp_path / "owned")
        assert plan["status"] == "READY"
        assert plan["stage"] == "PLANNED"
        assert [p["name"] for p in plan["preconditions"]] == [
            "document_identity", "candidate_freshness", "panel_identity_ownership",
            "panel_placement", "uniform_scale", "required_content",
            "resource_preparation", "document_patch_minimality"]
        assert all({"expected", "observed", "ok"} <= p.keys() for p in plan["preconditions"])
        resource = plan["resources"][0]
        staged = Path(resource["staging_path"])
        assert staged.read_bytes()
        assert hashlib.sha256(staged.read_bytes()).hexdigest() == resource["bytes_sha256"]
        assert resource["frame_revision"] == frame["frame_revision"]
        assert Path(resource["path"]).is_absolute() is False
        # The host resolves fileId from the project root: the reference must
        # point at bytes that actually exist there.
        assert (Path(host["project_root"]) / resource["path"]).is_file()
        assert (Path(host["project_root"]) / resource["path"]).read_bytes() == staged.read_bytes()
        assert host["document"] == original
        assert plan["next_document"]["schema"] == 3
        assert plan["next_document"]["canvases"][0]["objects"][0]["fileId"] == resource["path"]
        old = original["canvases"][0]["objects"][0]
        new = plan["next_document"]["canvases"][0]["objects"][0]
        changed = {k for k in old if old[k] != new[k]}
        assert changed == {"fileId"}
    finally:
        session.close()


@pytest.mark.parametrize("changes,failed", [
    ({"legacy": True}, "panel_identity_ownership"),
    ({"overrides": [{"gid": "x"}]}, "panel_identity_ownership"),
    ({"geometry": {"x": 2}}, "panel_placement"),
    ({"crop": {"x": 0.0, "y": 0.0, "w": 0.8, "h": 1.0}}, "uniform_scale"),
])
def test_invalid_host_facts_refuse_before_staging(tmp_path, changes, failed):
    session, _, candidate, host = _case(tmp_path, **changes)
    try:
        staging = tmp_path / "owned"
        plan = build_acceptance_plan([candidate], host_document=host, base_revision="rev", resources_dir=staging)
        assert plan["status"] == "REFUSED"
        assert plan["evidence"]["first_failure"] == failed
        assert not staging.exists()
        assert host["document"]["canvases"][0]["objects"][0]["fileId"] == "old.pdf"
    finally:
        session.close()


def test_stale_revision_refuses_without_host_write(tmp_path):
    session, _, candidate, host = _case(tmp_path)
    try:
        plan = build_acceptance_plan([candidate], host_document=host, base_revision="wrong",
                                     resources_dir=tmp_path / "owned")
        assert plan["status"] == "REFUSED"
        assert plan["evidence"]["first_failure"] == "document_identity"
        assert host["document"]["canvases"][0]["objects"][0]["fileId"] == "old.pdf"
    finally:
        session.close()


def test_missing_required_content_refuses_without_host_write(tmp_path):
    session, _, candidate, host = _case(tmp_path)
    candidate["required_content"] = ["not-in-scene"]
    try:
        plan = build_acceptance_plan([candidate], host_document=host, base_revision="rev",
                                     resources_dir=tmp_path / "owned")
        assert plan["status"] == "REFUSED"
        assert plan["evidence"]["first_failure"] == "required_content"
        assert host["document"]["canvases"][0]["objects"][0]["fileId"] == "old.pdf"
    finally:
        session.close()


def test_staging_outside_the_project_root_is_refused(tmp_path):
    session, _, candidate, host = _case(tmp_path)
    try:
        outside = tmp_path.parent / "outside-staging"
        plan = build_acceptance_plan([candidate], host_document=host, base_revision="rev",
                                     resources_dir=outside)
        assert plan["status"] == "REFUSED"
        assert plan["evidence"]["first_failure"] == "resource_preparation"
        assert not outside.exists()
    finally:
        session.close()


def test_prepared_pdf_must_match_the_panel_stored_native_size(tmp_path):
    session, _, candidate, host = _case(tmp_path)
    try:
        host["document"]["canvases"][0]["objects"][0]["nativeW"] = 12.0
        host["document"]["canvases"][0]["objects"][0]["nativeH"] = 12.0
        candidate["placement"]["nativeW"] = 12.0
        candidate["placement"]["nativeH"] = 12.0
        plan = build_acceptance_plan([candidate], host_document=host, base_revision="rev",
                                     resources_dir=tmp_path / "owned")
        assert plan["status"] == "REFUSED"
        assert plan["evidence"]["first_failure"] == "resource_preparation"
        assert plan["resources"] == []
        assert host["document"]["canvases"][0]["objects"][0]["fileId"] == "old.pdf"
    finally:
        session.close()
