"""Deterministic invariant regression for the derived three-figure harness.

Uses synthetic standalone layouts only; it never touches the real saved page,
never starts a RenderSession, and never imports provider scripts. The live
run (real page + three real providers) is for the parent smoke only.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "verify_three_figures",
        ROOT / "examples" / "plate" / "verify_three_figures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_harness = _load_harness()
PANEL_FTIR = _harness.PANEL_FTIR
PANEL_NMR = _harness.PANEL_NMR
PANEL_XRD = _harness.PANEL_XRD
REQUIRED_NMR_PEAKS = _harness.REQUIRED_NMR_PEAKS
REQUIRED_XRD_HKL = _harness.REQUIRED_XRD_HKL
TARGETS = _harness.TARGETS
build_derived_layout = _harness.build_derived_layout
size_config_for_native = _harness.size_config_for_native
summarize_search = _harness.summarize_search
prove_geometry = _harness.prove_geometry
harness_exit_code = _harness.harness_exit_code
from figpact.render_contract import validate_layout  # noqa: E402


def _base_layout():
    return {
        "schema": "figpact.layout/1", "source_mode": "saved", "page_mm": [180.0, 254.4],
        "objects": [
            {"id": PANEL_NMR, "kind": "panel", "measurement_status": "conservative",
             "rect_mm": [1.0, 29.0, 40.0, 45.0]},
            {"id": PANEL_FTIR, "kind": "panel", "measurement_status": "conservative",
             "rect_mm": [47.0, 29.0, 36.0, 43.0]},
            {"id": PANEL_XRD, "kind": "panel", "measurement_status": "conservative",
             "rect_mm": [81.0, 29.0, 41.0, 46.0]},
            {"id": "p_photo", "kind": "panel", "measurement_status": "conservative",
             "rect_mm": [5.0, 78.0, 55.0, 41.0]},
            {"id": "p_text", "kind": "text", "measurement_status": "conservative",
             "rect_mm": [2.0, 200.0, 10.0, 5.0]},
        ],
    }


def test_derived_scenario_marks_owners_and_keeps_geometry():
    saved = validate_layout(_base_layout())
    before = copy.deepcopy(saved)
    derived = build_derived_layout(saved, list(TARGETS), "sha256:" + "0" * 64)
    assert saved == before  # source snapshot never mutated
    assert derived["source_mode"] == "standalone"
    marker = derived["extensions"]["figpact_derived_three_figure"]
    assert marker["scenario"] == "DERIVED_STANDALONE"
    assert marker["source_revision"] == saved["revision"]
    by_id = {obj["id"]: obj for obj in derived["objects"]}
    for tid in TARGETS:
        assert by_id[tid]["render_owner"] == "figpact"
        source = next(obj for obj in saved["objects"] if obj["id"] == tid)
        assert by_id[tid]["rect_mm"] == source["rect_mm"]
    others = [obj for obj in derived["objects"] if obj["id"] not in TARGETS]
    assert others == [obj for obj in saved["objects"] if obj["id"] not in TARGETS]


def test_derived_rejects_absent_or_hidden_targets():
    saved = validate_layout(_base_layout())
    with pytest.raises(ValueError):
        build_derived_layout(saved, ["p_ghost"], "sha")
    hidden = _base_layout()
    hidden["objects"][0]["hidden"] = True
    with pytest.raises(ValueError):
        build_derived_layout(validate_layout(hidden), list(TARGETS), "sha")


def test_required_label_facts_are_complete_and_stable():
    assert REQUIRED_XRD_HKL == [
        "fig2_xrd.main.hkl.100", "fig2_xrd.main.hkl.101", "fig2_xrd.main.hkl.102",
        "fig2_xrd.main.hkl.110", "fig2_xrd.main.hkl.103",
    ]  # source order, never (002), none dropped
    assert [gid.split(".")[-3:] for gid in REQUIRED_NMR_PEAKS] == [
        ["peak", "vancho", "9p83"], ["peak", "vancho", "3p91"], ["peak", "vancho", "3p68"],
        ["peak", "vanoh", "4p62"], ["peak", "vannh2", "3p03"],
        ["peak", "hama", "6p18"], ["peak", "hama", "2p02"]]


def test_sizing_copies_page_native_dimensions_without_scale_math():
    config = {"canvas_w_mm": 48.0, "canvas_h_mm": 48.0, "axis_font_pt": 8.5}
    sized = size_config_for_native(config, [41.0, 46.13444575910199])
    assert config == {"canvas_w_mm": 48.0, "canvas_h_mm": 48.0, "axis_font_pt": 8.5}
    assert (sized["canvas_w_mm"], sized["canvas_h_mm"]) == (41.0, 46.13444575910199)


def test_search_summary_never_carries_frames():
    result = {"status": "FEASIBLE", "reason": "ok", "candidate_grid_pt": [8.5],
              "max_renders": 18, "render_count": 6,
              "completeness": {"searched": 1, "declared_grid_complete": False},
              "winner": {"candidate_pt": 8.5, "variant_index": 0},
              "attempts": [{"candidate_pt": 8.5, "variant_index": 0, "status": "FEASIBLE",
                            "panels": {PANEL_NMR: {"status": "FEASIBLE", "bottleneck": "OK"}}}],
              "active_candidates": True, "currentness": "SNAPSHOT_BOUND",
              "host": "NOT_VERIFIED", "export_page": "NOT_RUN",
              "persistence": "NOT_WRITTEN"}
    summary = summarize_search(result)
    blob = repr(summary)
    assert "png_base64" not in blob and "scene_json" not in blob
    assert summary["winner_pt"] == 8.5 and summary["render_count"] == 6


def test_geometry_guard_refuses_unreconciled_projection_with_measured_ratios():
    panel = {"id": PANEL_FTIR, "native_size_mm": [38.87653876460224, 46.13444575910199],
             "rect_mm": [47.0, 29.0, 36.6460, 43.4875], "rotation_deg": 0,
             "crop": [6.0914, 0.0, 32.7851, 43.8066]}
    proof = prove_geometry(
        panel, [38.87653876460224, 46.13444575910199],
        {"scale_xy": [1.0, 1.0], "anisotropic": False})
    assert proof["verdict"] == "UNSUPPORTED_GEOMETRY"
    assert proof["rule"] == "PROJECTION_SCALE_MISMATCH"
    assert proof["measured_extent_mm"] == panel["native_size_mm"]
    assert proof["engine_scale_xy"] == [1.0, 1.0]
    assert proof["host_anisotropic"] is True
    assert len(proof["measured_ratio_wh"]) == 2


def test_exit_code_tracks_harness_state_not_search_verdict():
    assert harness_exit_code("OK") == 0
    assert harness_exit_code("PREREQUISITE_MISSING") == 2
    assert harness_exit_code("HARNESS_ERROR") == 1


def test_failure_diagnostics_preserve_label_rule_and_frame_revision():
    revision = "f" * 64
    result = {"status": "NO_CANDIDATE", "attempts": [{
        "candidate_pt": 8.0, "variant_index": 0, "status": "INFEASIBLE",
        "panels": {PANEL_XRD: {
            "status": "CONSTRAINT_VIOLATION",
            "bottleneck": f"{PANEL_XRD}:CONSTRAINT_VIOLATION:fig2_xrd.main.hkl.100",
            "code": "CONSTRAINT_VIOLATION", "frame_revision": revision}}}],
        "completeness": {}, "winner": {}}
    attempt = summarize_search(result)["attempts"][0]["panels"][PANEL_XRD]
    assert attempt["blocking_content"] == "fig2_xrd.main.hkl.100"
    assert attempt["rule"] == "CONSTRAINT_VIOLATION"
    assert attempt["frame_revision"] == revision
