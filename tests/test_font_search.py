"""Bounded search policy and real-session candidate lifecycle checks."""
from __future__ import annotations

import pytest

from figpact.font_search import MAX_POINTS, MAX_RENDERS, MAX_VARIANTS, _validate_intent, search_common_font
from figpact.layout_report import LayoutReportError


def _intent(**over):
    base = {"schema": "figpact.font-search/1", "role": "axis.title",
            "candidate_pt": [6.0, 5.5, 5.0]}
    base.update(over)
    return base


def _targets():
    return {"nmr": object(), "ftir": object()}


def test_invalid_intent_keys_types_and_caps_raise_invalid():
    sessions = _targets()
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent({"schema": "figpact.font-search/1"}, list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(extra=1), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(candidate_pt=[6, 6]), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(candidate_pt=[True]), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(role="axis.tick", axis="bogus"), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(role="legend", axis="x"), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(axes_context="unknown"), list(sessions))
    assert caught.value.status == "INVALID"  # never guessed
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(candidate_pt=list(range(MAX_POINTS + 1))), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(variants=[{}] * (MAX_VARIANTS + 1)), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(max_renders=MAX_RENDERS + 1), list(sessions))
    assert caught.value.status == "INVALID"
    with pytest.raises(LayoutReportError) as caught:
        _validate_intent(_intent(variants=[{"nmr": [{"control_id": "c", "value": 5},
                                                   {"control_id": "c", "value": 6}]}]), list(sessions))
    assert caught.value.status == "INVALID"


def test_session_ownership_is_fail_closed():
    with pytest.raises(LayoutReportError) as caught:
        search_common_font({}, {"only": object()}, _intent(),
                           expected_revision="x", source_bindings={})
    assert caught.value.status == "INVALID"
    session = object()
    with pytest.raises(LayoutReportError) as caught:
        search_common_font({}, {"a": session, "b": session}, _intent(),
                           expected_revision="x", source_bindings={})
    assert caught.value.status == "INVALID"




def test_selection_contract_visible_measured_single_control_only():
    from figpact.font_search import _select_panel
    capability = {"roles": [
        {"id": "xlabel", "gid": "xlabel", "identity_stability": "stable",
         "semantic_role": "axis.title", "axis": "x", "axes_context": "root",
         "evidence": "artist_identity", "visible": True, "measured": True,
         "final_rect_mm": [1, 1, 2, 2], "font_reason": None,
         "font_controls": [{"control_id": "c", "editable": True}]}],
        "coupling": [{"control_id": "c", "affected_ids": ["xlabel"],
                      "affected_role_groups": [], "unmatched_ids": []}]}
    raw = {"xlabel": {"is_text": True, "visible": True, "measured": True}}
    selection, bottleneck = _select_panel(capability, raw, role="axis.title",
                                          axis=None, context="root")
    assert bottleneck == "" and selection["member_ids"] == ["xlabel"]
    # Legend container (non-text) is skipped, never selected as a font member.
    capability["roles"].append(
        {"id": "legend", "gid": "legend", "identity_stability": "stable",
         "semantic_role": "legend", "axis": None, "axes_context": "root",
         "evidence": "artist_identity", "visible": True, "measured": True,
         "final_rect_mm": [1, 1, 2, 2], "font_reason": None,
         "font_controls": [{"control_id": "c", "editable": True}]})
    raw["legend"] = {"type": "legend", "visible": True, "measured": True}
    selection, _ = _select_panel(capability, raw, role="axis.title",
                                 axis=None, context="root")
    assert selection["member_ids"] == ["xlabel"]
    # Two usable controls on one member is unbound, never silently picked.
    capability["roles"][0]["font_controls"].append(
        {"control_id": "c2", "editable": True})
    _, bottleneck = _select_panel(capability, raw, role="axis.title",
                                  axis=None, context="root")
    assert bottleneck.startswith("UNBOUND_FONT_CONTROL")
    # Unmigrated axes_context is refused, never inferred.
    capability["roles"][0]["font_controls"] = [{"control_id": "c", "editable": True}]
    capability["roles"][0]["axes_context"] = "unknown"
    _, bottleneck = _select_panel(capability, raw, role="axis.title",
                                  axis=None, context="root")
    assert bottleneck == "NO_GROUP_MEMBERS"


def test_coupling_refusal_contract_without_sessions():
    from figpact.font_search import _coupled_extras
    selection = {"member_ids": ["xlabel"], "control_id": "c", "affected_ids": ["xlabel"]}
    extras, bottleneck = _coupled_extras(selection, {"xlabel": {"is_text": True}})
    assert extras == [] and bottleneck == ""
    selection = {"member_ids": ["xlabel"], "control_id": "c",
                 "affected_ids": ["xlabel", "legend"]}
    extras, bottleneck = _coupled_extras(
        selection, {"xlabel": {"is_text": True},
                    "legend": {"type": "legend", "visible": True}})
    assert extras == [] and bottleneck == ""  # known non-text container is fine
    selection = {"member_ids": ["xlabel"], "control_id": "c",
                 "affected_ids": ["xlabel", "ylabel"]}
    extras, _ = _coupled_extras(
        selection, {"xlabel": {"is_text": True},
                    "ylabel": {"is_text": True, "visible": True}})
    assert extras == ["ylabel"]  # caller must set allow_coupled=true to proceed
    _, bottleneck = _coupled_extras(
        {"member_ids": ["xlabel"], "control_id": "c",
         "affected_ids": ["xlabel", "ghost"]}, {"xlabel": {"is_text": True}})
    assert bottleneck.startswith("UNMEASURED_COUPLING")


def test_spatial_bottleneck_contract_strict_but_not_budget_alarmist():
    from figpact.font_search import _spatial_bottleneck
    spatial = {"findings": [
        {"kind": "CURRENT_BUDGET_EXCESS", "violation": False, "panels": ["p"],
         "objects": ["p"]},
        {"kind": "POTENTIAL_NEIGHBOUR_ENVELOPE_OVERLAP", "violation": False,
         "panels": ["p"], "objects": ["p", "n"], "nodes": ["unrelated"]},
        {"kind": "REQUIRED_CONTENT_MISSING", "violation": True, "panels": ["p"],
         "objects": ["p"]}]}
    assert _spatial_bottleneck(spatial, "p", {"member"}) is not None  # PROVEN violation blocks
    spatial["findings"] = spatial["findings"][:2]
    assert _spatial_bottleneck(spatial, "p", {"member"}) is None  # budget info + unrelated overlap pass
    spatial["findings"] = [
        {"kind": "POTENTIAL_NEIGHBOUR_ENVELOPE_OVERLAP", "violation": False,
         "panels": ["p"], "objects": ["p", "n"], "nodes": ["member"]}]
    assert _spatial_bottleneck(spatial, "p", {"member"}) is not None  # relevant overlap blocks


def test_real_two_figure_search_budget_active_replay_and_stale_page(tmp_path):
    import copy
    from pathlib import Path
    from figpact.render_api import RenderSession
    from figpact.render_contract import validate_layout

    root = Path(__file__).resolve().parents[1]
    sources = {}
    sessions = {}
    originals = {}
    try:
        for pid, filename in (("nmr", "08 NMR.py"), ("ftir", "plot_ftir.py")):
            original = root / "examples" / pid / f"{pid}.yaml"
            originals[original] = original.read_bytes()
            config = tmp_path / f"{pid}.yaml"
            config.write_bytes(originals[original])
            script = root / "examples" / pid / filename
            sources[pid] = {"script": str(script), "config": str(config),
                            "scope": "main", "overrides_present": False}
            sessions[pid] = RenderSession(script, config, "main", output_dir=tmp_path)
        layout = validate_layout({
            "schema": "figpact.layout/1", "source_mode": "standalone", "page_mm": [180, 150],
            "objects": [{"id": "nmr", "kind": "panel", "render_owner": "figpact",
                         "measurement_status": "measured", "rect_mm": [10, 20, 48, 48]},
                        {"id": "ftir", "kind": "panel", "render_owner": "figpact",
                         "measurement_status": "measured", "rect_mm": [70, 20, 36, 36]},
                        {"id": "photo", "kind": "panel", "render_owner": "asset",
                         "measurement_status": "conservative", "rect_mm": [135, 20, 30, 50]}]})
        before = copy.deepcopy(layout)
        kwargs = {"expected_revision": layout["revision"], "source_bindings": sources}
        intent = _intent(axis="x", candidate_pt=[10, 9, 8, 7], allow_coupled=True, max_renders=16)
        refused = search_common_font(layout, sessions, {**intent, "allow_coupled": False}, **kwargs)
        assert refused["status"] == "UNSUPPORTED" and refused["render_count"] == 0

        # Every rejected real preview consumes budget; no orphaned candidates.
        failed = search_common_font(layout, sessions, {
            **intent, "candidate_pt": [8, 7, 6], "max_renders": 4,
            "required_content": {"ftir": ["required-but-absent"]}}, **kwargs)
        assert failed["status"] == "NO_CANDIDATE"
        assert failed["render_count"] == 2
        assert all(s.snapshot()["pending"] is None for s in sessions.values())

        result = search_common_font(layout, sessions, intent, **kwargs)
        assert result["status"] == "FEASIBLE", result
        assert result["render_count"] <= intent["max_renders"]
        point = result["winner"]["candidate_pt"]
        for pid, receipt in result["candidates"].items():
            current = sessions[pid].snapshot()
            assert current["pending"]["candidate_id"] == receipt["candidate_id"]
            assert current["frame"]["frame_revision"] == receipt["frame_revision"]
            assert all(row["effective_font_pt"] == pytest.approx(point, abs=.02)
                       for row in receipt["measured_fonts"])
            sessions[pid].cancel(receipt["candidate_id"])
        assert layout == before

        # The page owner advances its revision during the winning replay.
        changed = copy.deepcopy(layout)
        changed.pop("revision")
        changed["objects"][2]["rect_mm"][0] -= 10
        changed = validate_layout(changed)
        first_pending = None
        moved = False

        def page_owner():
            nonlocal first_pending, moved
            current = sessions["ftir"].snapshot().get("pending") or {}
            cid = current.get("candidate_id")
            if cid is not None:
                if first_pending is None:
                    first_pending = cid
                elif cid != first_pending:
                    moved = True
            return changed if moved else layout

        stale = search_common_font(layout, sessions, {
            **intent, "candidate_pt": [point]}, refresh_layout=page_owner, **kwargs)
        assert moved and stale["status"] == "STALE"
        assert stale["candidates"] == {} and stale["active_candidates"] is False
        assert all(s.snapshot()["pending"] is None for s in sessions.values())
        assert layout == before
        for original, data in originals.items():
            assert original.read_bytes() == data
            assert (tmp_path / original.name).read_bytes() == data
    finally:
        for session in sessions.values():
            session.close()
