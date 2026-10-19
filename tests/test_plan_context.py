"""G24 plan-context consumer regressions (owner: ExistingPlanAdapters).

Real sessions only: live discovery, engine trials, stale gates. No commit, no
model inference, no provider. Parent runs; this module never self-verifies.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from figpact.agent_api import AgentSession
from figpact.inspector_style import StyleSession
from figpact.plan_context import discover_native, discover_overlay, validate_candidate

ROOT = Path(__file__).resolve().parents[1]
NMR_SCRIPT = ROOT / "tests" / "fixtures" / "native_nmr.py"
NMR_CONFIG = ROOT / "tests" / "fixtures" / "native_nmr.yaml"
G15B_SCRIPT = ROOT / "tools" / "g15" / "B" / "g15b_barchart_decl.py"

LIFT_ID = '["peak_label_lift_mm"]'


def _native_session(tmp_path):
    return AgentSession(NMR_SCRIPT, NMR_CONFIG, "main", output_dir=tmp_path)


def _ready(route, scope, revision, edits):
    return {"status": "READY", "route": route, "scope": scope, "revision": revision,
            "edits": edits, "preserve": ["science", "view"], "reason": "regression trial"}


def test_native_discovery_exposes_editable_only_and_stable_revision(tmp_path):
    session = _native_session(tmp_path)
    try:
        context = discover_native(session)
        assert context["route"] == "native" and context["scope"] == "main"
        assert isinstance(context["revision"], str) and context["revision"]
        ids = [c["id"] for c in context["controls"]]
        assert ids and ids == sorted(ids) and len(set(ids)) == len(ids)
        assert not any("peak_windows_ppm" in cid for cid in ids)  # LOCKED never offered
        row = next(c for c in context["controls"] if c["id"] == LIFT_ID)
        assert json.loads(row["id"]) == row["path"] == ["peak_label_lift_mm"]
        assert row["unit"] == "mm" and row["min"] == 0.0 and row["max"] == 6.0
        assert row["current"] == 2.5 and row["objects"]
        assert context["session_context"]["nodes"]  # panels joinable via objects, no guessing
    finally:
        session.close()
    fresh = _native_session(tmp_path)
    try:
        assert discover_native(fresh)["revision"] == context["revision"]
    finally:
        fresh.close()


def test_native_ready_trial_is_candidate_only(tmp_path):
    before = NMR_CONFIG.read_bytes()
    session = _native_session(tmp_path)
    try:
        context = discover_native(session)
        plan = _ready("native", "main", context["revision"],
                      [{"control_id": LIFT_ID, "value": 3.0}])
        out = validate_candidate(session, context, plan)
        assert out["trial"]["status"] == "OK"
        assert out["verification"] in ("GEOMETRY_CHECKED", "RENDER_CHECKED")
        assert out["preview"] is not None
        assert out["preview"]["revision"] == out["revision"]
        assert out["saved"] is False and out["publication_verified"] is False
        assert "publication" in out["note"]
        assert NMR_CONFIG.read_bytes() == before  # no writes
    finally:
        session.close()


def test_native_stale_revision_rejected(tmp_path):
    session = _native_session(tmp_path)
    try:
        context = discover_native(session)
        plan = _ready("native", "main", "0" * 64, [{"control_id": LIFT_ID, "value": 3.0}])
        with pytest.raises(ValueError, match="stale"):
            validate_candidate(session, context, plan)
    finally:
        session.close()


def test_native_nonready_plan_skips_trial(tmp_path):
    session = _native_session(tmp_path)
    try:
        context = discover_native(session)
        plan = {"status": "CLARIFY", "route": "native", "scope": "main",
                "revision": context["revision"], "edits": [],
                "preserve": ["science", "view"], "reason": "need a number"}
        assert validate_candidate(session, context, plan) is None
    finally:
        session.close()


def test_native_unknown_control_judged_by_engine(tmp_path):
    session = _native_session(tmp_path)
    try:
        context = discover_native(session)
        forged = dict(context, controls=[*context["controls"], {"id": '["peak_nope_mm"]'}])
        plan = _ready("native", "main", context["revision"],
                      [{"control_id": '["peak_nope_mm"]', "value": 1.0}])
        out = validate_candidate(session, forged, plan)
        assert out["trial"]["status"] == "UNSUPPORTED_PATH"
        assert out["saved"] is False
    finally:
        session.close()


def test_overlay_discovery_and_single_trial(tmp_path):
    overlay = tmp_path / "style.json"
    style = StyleSession(script=G15B_SCRIPT, config=None, scope="main", overlay=overlay)
    context = discover_overlay(style)
    assert context["route"] == "overlay"
    assert context["revision"] == style.snapshot()["frame_revision"]
    assert context["controls"]
    row = context["controls"][0]
    assert row["id"] == row["target_id"] and row["unit"] == "pt"
    assert row["min"] <= row["current"] <= row["max"] and row["objects"]
    value = float(row["current"]) + 1.0
    if value > float(row["max"]):
        value = float(row["current"]) - 1.0
    plan = _ready("overlay", "main", context["revision"],
                  [{"control_id": row["id"], "value": value}])
    out = validate_candidate(style, context, plan)
    assert out["status"] == "OK" and out["trial"]["local_edit_state"] == "PASS"
    assert out["saved"] is False and out["publication_verified"] is False
    assert not overlay.exists()
    assert style.snapshot()["style"].get("candidate_id") is None


def test_overlay_batch_failure_does_not_stage_a_partial_edit(tmp_path):
    overlay = tmp_path / "style.json"
    style = StyleSession(script=G15B_SCRIPT, config=None, scope="main", overlay=overlay)
    context = discover_overlay(style)
    tids = [c["id"] for c in context["controls"][:2]]
    assert len(tids) == 2
    plan = _ready("overlay", "main", context["revision"],
                  [{"control_id": tids[0], "value": 8.0},
                   {"control_id": tids[1], "value": 500.0}])
    out = validate_candidate(style, context, plan)
    assert out["status"] == "REFUSED" and out["accepted"] is False
    assert style.snapshot()["style"].get("candidate_id") is None  # no partial preview
    assert not overlay.exists()


def test_overlay_stale_surfaced_by_engine(tmp_path):
    overlay = tmp_path / "style.json"
    style = StyleSession(script=G15B_SCRIPT, config=None, scope="main", overlay=overlay)
    context = discover_overlay(style)
    tid = context["controls"][0]["id"]
    forged = dict(context, revision="0" * 64)  # self-consistent but stale vs live frame
    plan = _ready("overlay", "main", forged["revision"], [{"control_id": tid, "value": 8.0}])
    with pytest.raises(ValueError, match="stale"):
        validate_candidate(style, forged, plan)
