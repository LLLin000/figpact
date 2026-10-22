"""G3-B spatial_report behavioral tests (deterministic, no renderer)."""
from __future__ import annotations

import json
import pytest


from figpact.spatial_report import spatial_report


def _layout(objects, page=(200.0, 200.0)):
    return {"schema": "figpact.layout/1", "source_mode": "standalone",
            "page_mm": list(page), "objects": objects}


def _obj(pid, rect, status="measured", **kw):
    d = {"id": pid, "rect_mm": list(rect) if rect is not None else None,
         "measurement_status": status}
    d.update(kw)
    return d


def _proj(nodes, scale=(1.0, 1.0)):
    return {"nodes": nodes, "evidence": {"scale_xy": list(scale), "anisotropic": False}}


def _node(nid, rect=None, measurable=True, reason=None, src=None):
    d = {"id": nid, "rect_mm": list(rect) if rect else None,
         "measurable": measurable, "scale_xy": [1.0, 1.0], "anisotropic": False,
         "source": src or {}}
    if reason:
        d["reason"] = reason
    return d


def _frame(nodes, verified=True):
    return {"scene_json": json.dumps({"nodes": nodes}),
            "science": {"verified": verified}}


def test_budget_derives_134_7_vs_126_yields_8_7():
    layout = _layout([_obj("a", [0, 0, 70.2, 40]), _obj("b", [75, 0, 64.5, 40])])
    rep = spatial_report(layout, ["a", "b"], {},
                         regions=[{"id": "row", "member_ids": ["a", "b"], "axis": "x",
                                   "region_mm": [0, 0, 126.0, 50.0], "gap_mm": 0.0}])
    (b,) = rep["budgets"]
    assert b["available_mm"] == 126.0
    assert b["occupied_mm"] == pytest.approx(134.7)
    assert b["excess_mm"] == pytest.approx(8.7)
    assert b["current_span_mm"] == pytest.approx(139.5)
    assert any(f["kind"] == "CURRENT_BUDGET_EXCESS" and f["certainty"] == "POTENTIAL"
               for f in rep["findings"])
    assert rep["status"] != "CONSTRAINT_VIOLATION"  # information only, not a violation


def test_rotated_cropped_observation_uses_projected_geometry_verbatim():
    layout = _layout([_obj("p", [10, 10, 40, 60], rotation_deg=90, crop=[0, 0, 50, 50])])
    given = [15.0, 15.0, 5.0, 5.0]
    rep = spatial_report(layout, ["p"], {"p": {"projection": _proj([_node("t", given)]),
                                               "frame": _frame([]), "editable": False}})
    assert rep["targets"]["p"]["projected"]["nodes"]["t"]["rect_mm"] == given
    assert rep["targets"]["p"]["rect_mm"] == [10, 10, 40, 60]
    assert not any(f["certainty"] == "PROVEN" and f["violation"] for f in rep["findings"])


def test_required_labels_missing_or_cropped_cannot_pass():
    layout = _layout([_obj("p", [10, 10, 60, 40])])
    frame = _frame([{"id": "lbl", "gid": "lbl", "visible": True, "measured": True}])
    proj = _proj([{"id": "lbl", "rect_mm": None, "measurable": False,
                   "reason": "CROPPED_OUT", "scale_xy": [1, 1], "anisotropic": False,
                   "source": {"scene_bounds_mm": [200, 200, 210, 205],
                              "canvas_mm": [100, 100], "crop_mm": [0, 0, 100, 100]}}])
    rep = spatial_report(layout, ["p"], {"p": {"projection": proj, "frame": frame}},
                         required_content={"p": ["lbl", "ghost"]})
    assert rep["status"] == "CONSTRAINT_VIOLATION"
    rc = [f for f in rep["findings"] if f["kind"] == "REQUIRED_CONTENT_MISSING"]
    assert rc and rc[0]["certainty"] == "PROVEN" and set(rc[0]["nodes"]) == {"lbl", "ghost"}


def test_opaque_unmeasured_targets_stay_unknown_never_pass_qa():
    layout = _layout([_obj("known", [10, 10, 60, 40]),
                      _obj("ghost", None, status="unknown")])
    rep = spatial_report(layout, ["known", "ghost"], {})
    assert rep["status"] == "UNSUPPORTED"
    kinds = {f["kind"] for f in rep["findings"]}
    assert "MEASUREMENT_MISSING" in kinds and "MEASUREMENT_LIMITED" in kinds
    assert not any(f["certainty"] == "PROVEN" and f["violation"] for f in rep["findings"]
                   if f["kind"].startswith("CONTENT_"))


def test_fixed_photo_and_page_rects_unchanged_envelope_is_potential_only():
    photo = [80, 10, 40, 40]
    layout = _layout([_obj("p", [10, 10, 60, 40]),
                      _obj("photo", photo, kind="photo", locked=True)])
    proj = _proj([_node("ink", [75, 15, 20, 20],
                        src={"scene_bounds_mm": [0, 0, 10, 10],
                             "canvas_mm": [100, 100], "crop_mm": [0, 0, 100, 100]})])
    rep = spatial_report(layout, ["p"], {"p": {"projection": proj, "frame": _frame([])}})
    assert rep["targets"]["p"]["rect_mm"] == [10, 10, 60, 40]
    assert rep["page_mm"] == [200.0, 200.0]
    pot = [f for f in rep["findings"] if f["kind"] == "POTENTIAL_NEIGHBOUR_ENVELOPE_OVERLAP"]
    assert pot and all(f["certainty"] == "POTENTIAL" and not f["violation"] for f in pot)


def test_unmeasured_required_label_is_unknown_not_proved_lost():
    layout = _layout([_obj("p", [10, 10, 60, 40])])
    frame = _frame([{"id": "needed", "visible": True, "measured": False}])
    projection = _proj([_node("needed", measurable=False, reason="UNMEASURED_SOURCE")])
    result = spatial_report(layout, ["p"], {"p": {"frame": frame, "projection": projection}},
                            required_content={"p": ["needed"]})
    assert result["status"] == "UNSUPPORTED"
    assert result["targets"]["p"]["required"]["unknown"] == ["needed"]
    assert result["targets"]["p"]["required"]["missing"] == []
    assert not any(f["kind"] == "REQUIRED_CONTENT_MISSING" for f in result["findings"])


def test_page_baseline_is_not_outside_and_unknown_neighbour_rect_is_not_overlap_evidence():
    layout = _layout([_obj("p", [10, 10, 60, 40]),
                      _obj("unknown-photo", [20, 20, 10, 10], status="unknown")])
    projection = _proj([_node("baseline", [25, 20, 0, 5]), _node("text", [20, 20, 5, 5])])
    result = spatial_report(layout, ["p"], {"p": {"projection": projection, "frame": _frame([])}})
    assert not any(f["kind"] == "CONTENT_OUTSIDE_PAGE" for f in result["findings"])
    assert not any(f["kind"] == "POTENTIAL_NEIGHBOUR_ENVELOPE_OVERLAP" for f in result["findings"])
    assert any(f["kind"] == "MEASUREMENT_LIMITED" and f["certainty"] == "UNKNOWN"
               for f in result["findings"])


def test_partial_text_crop_is_reported_but_structural_and_hidden_nodes_are_not_content():
    layout = _layout([_obj("p", [10, 10, 60, 40])])
    facts = {"scene_bounds_mm": [-2, 40, 4, 45], "canvas_mm": [100, 100],
             "crop_mm": [0, 0, 100, 100]}
    projection = _proj([_node("label-id", [10, 30, 4, 5], src=facts),
                        _node("canvas", [10, 10, 60, 40], src=facts),
                        _node("hidden", measurable=False, reason="UNMEASURED_SOURCE")])
    frame = _frame([{"id": "label-id", "gid": "label-alias", "visible": True, "measured": True},
                    {"id": "canvas", "visible": True, "measured": True, "structural": True},
                    {"id": "hidden", "visible": False, "measured": False}])
    result = spatial_report(layout, ["p"], {"p": {"projection": projection, "frame": frame}},
                            required_content={"p": ["label-alias"]})
    clipped = next(f for f in result["findings"] if f["kind"] == "CONTENT_CLIPPED")
    assert clipped["nodes"] == ["label-id"]
    assert result["targets"]["p"]["required"]["missing"] == ["label-alias"]
    assert not any(f["kind"] == "UNMEASURED_CONTENT" for f in result["findings"])
