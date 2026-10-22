"""Behavioral tests for figpact.render_contract (R14 G0+G1 slice)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from figpact.render_contract import (
    MEASUREMENT_LIMITED,
    POTENTIAL_OVERLAP,
    RenderContractError,
    precheck_layout,
    project_scene,
    snapshot_revision,
    validate_intent,
    validate_layout,
)

FIX = Path(__file__).parent / "fixtures" / "render_layouts.json"


def _fixtures():
    return json.loads(FIX.read_text(encoding="utf-8"))


def test_layout_validates_and_normalizes_defaults():
    layout = validate_layout(_fixtures()["a4_two_panel"])
    assert layout["schema"] == "figpact.layout/1"
    assert layout["revision"] == snapshot_revision(layout)
    rot = next(o for o in layout["objects"] if o["id"] == "rot")
    assert rot["rotation_deg"] == 90.0
    plain = next(o for o in layout["objects"] if o["id"] == "ftir")
    assert plain["rotation_deg"] == 0.0 and plain["crop"] is None
    assert plain["hidden"] is False and plain["locked"] is False
    assert plain["kind"] == "panel" and plain["resource"] == "ftir_trace"
    assert plain["source"] == {"origin": "standalone_fixture"}
    ghost = next(o for o in layout["objects"] if o["id"] == "ghost")
    assert ghost["kind"] == "panel" and ghost["resource"] is None and ghost["source"] is None
    # Idempotent: canonical output revalidates to an equal dict.
    assert validate_layout(layout) == layout
    assert validate_layout(json.loads(json.dumps(layout))) == layout


def test_layout_rejects_unknown_keys():
    base = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base["host_ref"] = "h1"
    with pytest.raises(RenderContractError):
        validate_layout(base)
    base2 = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base2["objects"][0]["kind_extra"] = "panel"
    with pytest.raises(RenderContractError):
        validate_layout(base2)
    base3 = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base3["objects"][0]["source"] = {"origin": 1}
    with pytest.raises(RenderContractError):
        validate_layout(base3)


def test_layout_rejects_mismatched_revision():
    base = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    good = validate_layout(base)
    tampered = json.loads(json.dumps(good))
    tampered["revision"] = "0" * 64
    with pytest.raises(RenderContractError):
        validate_layout(tampered)
    stamped = validate_layout({**base, "revision": good["revision"]})
    assert stamped == good


def test_revision_ignores_captured_at_only():
    base = _fixtures()["a4_two_panel"]
    a = validate_layout(base)
    stamped = validate_layout({**base, "captured_at": "2026-10-21T00:00:00Z"})
    assert a["revision"] == stamped["revision"]
    moved = json.loads(json.dumps(base))
    moved["objects"][0]["rect_mm"][0] += 1.0
    assert validate_layout(moved)["revision"] != a["revision"]


def test_rotation_normalizes_right_angles():
    base = _fixtures()["a4_two_panel"]
    for deg, want in ((450, 90.0), (-90, 270.0), (360, 0.0), (180, 180.0)):
        case = json.loads(json.dumps(base))
        case["objects"][0]["rotation_deg"] = deg
        assert validate_layout(case)["objects"][0]["rotation_deg"] == want


@pytest.mark.parametrize("patch, why", [
    ({"page_mm": [0, 297.0]}, "zero width"),
    ({"page_mm": [True, 297.0]}, "bool geometry"),
    ({"page_mm": [float("inf"), 297.0]}, "non-finite"),
    ({"source_mode": "tavotto"}, "bad mode"),
])
def test_layout_rejects_bad_envelope(patch, why):
    base = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base.update(patch)
    with pytest.raises(RenderContractError):
        validate_layout(base)
    assert why


@pytest.mark.parametrize("key, value", [
    ("rect_mm", [0, 0, 0, 10]),
    ("rect_mm", [0, 0, True, 10]),
    ("rect_mm", [0, 0, float("nan"), 10]),
    ("measurement_status", "guess"),
    ("rotation_deg", 45),
    ("crop", [0, 0, -5, 5]),
])
def test_layout_rejects_bad_object(key, value):
    base = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base["objects"][0][key] = value
    with pytest.raises(RenderContractError):
        validate_layout(base)


def test_layout_rejects_duplicate_ids():
    base = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base["objects"].append(dict(base["objects"][0]))
    with pytest.raises(RenderContractError):
        validate_layout(base)


def test_intent_validates_and_checks_authorized_controls():
    intent = {
        "schema": "figpact.intent/1", "panel_id": "ftir",
        "edits": [{"control_id": '["label_font_pt]', "value": 6.0}],
        "fit_canvas": False, "required_content": ["g1"], "preserve": ["science", "view"],
    }
    ok = validate_intent(intent, authorized={'["label_font_pt]'})
    assert ok["edits"] == [{"control_id": '["label_font_pt]', "value": 6.0}]
    with pytest.raises(RenderContractError):
        validate_intent(intent, authorized={"other"})
    bad = json.loads(json.dumps(intent))
    bad["edits"][0]["invented"] = 1.0
    with pytest.raises(RenderContractError):
        validate_intent(bad)
    bad2 = json.loads(json.dumps(intent))
    bad2["preserve"] = ["view", "science", "extra"]
    with pytest.raises(RenderContractError):
        validate_intent(bad2)
    bad3 = json.loads(json.dumps(intent))
    bad3["edits"][0]["value"] = True
    with pytest.raises(RenderContractError):
        validate_intent(bad3)
    # Idempotent canonical output.
    assert validate_intent(ok) == ok


def test_intent_rejects_unknown_keys_and_duplicates():
    intent = {
        "schema": "figpact.intent/1", "panel_id": "ftir",
        "edits": [{"control_id": '["a]', "value": 6.0},
                  {"control_id": '["b]', "value": 7.0}],
        "fit_canvas": False, "required_content": ["g1", "g2"], "preserve": ["science", "view"],
    }
    with pytest.raises(RenderContractError):
        validate_intent({**intent, "extra": 1})
    dup_edits = json.loads(json.dumps(intent))
    dup_edits["edits"].append({"control_id": '["a]', "value": 8.0})
    with pytest.raises(RenderContractError):
        validate_intent(dup_edits)
    dup_req = json.loads(json.dumps(intent))
    dup_req["required_content"].append("g1")
    with pytest.raises(RenderContractError):
        validate_intent(dup_req)


def test_projection_hand_checked_plain_panel():
    fx = _fixtures()
    got = project_scene(fx["scene_small"], fx["panel_plain"], [210.0, 297.0])
    assert got["coordinate_reference"] == "page_top_left"
    n1 = next(n for n in got["nodes"] if n["id"] == "n1")
    # Scene [10,10,30,20] bottom-left on 100x50 canvas -> top-left (10,30,20,10);
    # panel 50x25 -> scale (0.5,0.5) -> [5,15,10,5].
    assert n1["rect_mm"] == pytest.approx([5.0, 15.0, 10.0, 5.0])
    assert n1["measurable"] is True and n1["scale_xy"] == pytest.approx([0.5, 0.5])
    assert n1["anisotropic"] is False
    assert n1["source"]["canvas_mm"] == [100.0, 50.0]
    # Total coverage: unmeasured node stays listed, counted, not measurable.
    assert got["evidence"]["node_count"] == 2
    assert got["evidence"]["measurable_count"] == 1
    n2 = next(n for n in got["nodes"] if n["id"] == "n2")
    assert n2["rect_mm"] is None and n2["measurable"] is False


def test_projection_height_matters_and_anisotropy_is_pair():
    fx = _fixtures()
    tall = dict(fx["panel_plain"], rect_mm=[0.0, 0.0, 50.0, 50.0])
    got = project_scene(fx["scene_small"], tall, [210.0, 297.0])
    n1 = next(n for n in got["nodes"] if n["id"] == "n1")
    assert n1["rect_mm"] == pytest.approx([5.0, 30.0, 10.0, 10.0])
    assert n1["scale_xy"] == pytest.approx([0.5, 1.0])
    assert n1["anisotropic"] is True
    assert "scale_scalar" not in n1


def test_projection_applies_crop_and_rotation_once():
    fx = _fixtures()
    panel = {"id": "pc", "rect_mm": [0.0, 0.0, 40.0, 40.0],
             "measurement_status": "measured",
             "crop": [10.0, 25.0, 20.0, 20.0], "rotation_deg": 90}
    got = project_scene(fx["scene_small"], panel, [210.0, 297.0])
    n1 = next(n for n in got["nodes"] if n["id"] == "n1")
    # Canvas-top (10,30,20,10) ∩ crop (10,25,20,20) -> (10,30,20,10);
    # scale 2 -> local (0,10,40,20); rot90 about centre -> (10,0,20,40).
    assert n1["rect_mm"] == pytest.approx([10.0, 0.0, 20.0, 40.0])
    assert got["evidence"]["scale_xy"] == pytest.approx([2.0, 2.0])


def test_projection_nonsquare_quarter_turn_uses_content_dims():
    scene = {"coordinate_reference": "canvas_bottom_left",
             "canvas_mm": [100.0, 80.0],
             "nodes": [{"id": "spot", "measured": True,
                        "bounds_mm": [25.0, 30.0, 35.0, 40.0]},
                       {"id": "full", "measured": True,
                        "bounds_mm": [25.0, 30.0, 75.0, 70.0]}]}
    panel = {"id": "p90", "rect_mm": [10.0, 20.0, 40.0, 50.0],
             "measurement_status": "measured",
             "crop": [25.0, 10.0, 50.0, 40.0],
             "rotation_deg": 90, "flip_h": True}
    got = project_scene(scene, panel, [210.0, 297.0])
    # Content extent is the transposed final bbox (50x40): scale is uniform
    # (1,1); the cropped spot projects to [10,60,10,10].
    assert got["evidence"]["scale_xy"] == pytest.approx([1.0, 1.0])
    assert got["evidence"]["anisotropic"] is False
    spot = next(n for n in got["nodes"] if n["id"] == "spot")
    assert spot["rect_mm"] == pytest.approx([10.0, 60.0, 10.0, 10.0])
    # Whole cropped extent projects exactly to the final rect.
    full = next(n for n in got["nodes"] if n["id"] == "full")
    assert full["rect_mm"] == pytest.approx([10.0, 20.0, 40.0, 50.0])


def test_projection_rejects_crop_outside_canvas():
    fx = _fixtures()
    panel = dict(fx["panel_plain"])
    panel["crop"] = [90.0, 40.0, 20.0, 20.0]
    with pytest.raises(RenderContractError):
        project_scene(fx["scene_small"], panel, [210.0, 297.0])


def test_measured_flag_without_bounds_is_not_measurable():
    scene = {"coordinate_reference": "canvas_bottom_left", "canvas_mm": [100.0, 50.0],
             "nodes": [{"id": "claim", "measured": True, "bounds_mm": None}]}
    got = project_scene(scene, {"id": "p", "rect_mm": [0, 0, 10, 10],
                                "measurement_status": "measured"}, [50.0, 50.0])
    assert got["nodes"][0]["measurable"] is False
    assert got["nodes"][0]["reason"] == "UNMEASURED_SOURCE"


@pytest.mark.parametrize("bounds, panel, want", [
    # Horizontal baseline (zero height): y=10 bottom-left -> top y=40 on 50-high
    # canvas; panel 50x25 scale (0.5,0.5) -> [5,20,10,0].
    ({"id": "h", "bounds_mm": [10.0, 10.0, 30.0, 10.0], "measured": True},
     {"id": "p", "rect_mm": [0, 0, 50, 25], "measurement_status": "measured"},
     [5.0, 20.0, 10.0, 0.0]),
    # Vertical line (zero width) under crop+rotation: canvas-top (10,30,0,10)
    # inside crop (10,25,20,20) -> clipped (10,30,0,10), local (0,10,0,20);
    # rot90 about centre (x=40-(10+20)=10, y=0) -> [10,0,20,0] on 40x40 panel.
    ({"id": "v", "bounds_mm": [10.0, 10.0, 10.0, 20.0], "measured": True},
     {"id": "pc", "rect_mm": [0, 0, 40, 40], "measurement_status": "measured",
      "crop": [10.0, 25.0, 20.0, 20.0], "rotation_deg": 90},
     [10.0, 0.0, 20.0, 0.0]),
    # Point (zero width+height) passes through unchanged (no fake size).
    ({"id": "pt", "bounds_mm": [10.0, 10.0, 10.0, 10.0], "measured": True},
     {"id": "p", "rect_mm": [0, 0, 50, 25], "measurement_status": "measured"},
     [5.0, 20.0, 0.0, 0.0]),
])
def test_projection_preserves_zero_extent_lines_and_points(bounds, panel, want):
    scene = {"coordinate_reference": "canvas_bottom_left", "canvas_mm": [100.0, 50.0],
             "nodes": [bounds]}
    got = project_scene(scene, panel, [210.0, 297.0])
    node = got["nodes"][0]
    assert node["measurable"] is True
    assert node["rect_mm"] == pytest.approx(want)
    assert got["evidence"]["measurable_count"] == 1


def test_projection_rejects_reversed_scene_bounds():
    scene = {"coordinate_reference": "canvas_bottom_left", "canvas_mm": [100.0, 50.0],
             "nodes": [{"id": "rev", "bounds_mm": [30.0, 10.0, 10.0, 20.0],
                        "measured": True}]}
    with pytest.raises(RenderContractError):
        project_scene(scene, {"id": "p", "rect_mm": [0, 0, 10, 10],
                              "measurement_status": "measured"}, [50.0, 50.0])


@pytest.mark.parametrize("status", ["unknown", "unsupported"])
def test_unknown_rect_none_listed_unknown_overlap_none(status):
    layout = {
        "schema": "figpact.layout/1", "source_mode": "standalone",
        "page_mm": [210.0, 297.0],
        "objects": [
            {"id": "known", "rect_mm": [15.0, 20.0, 85.0, 60.0],
             "measurement_status": "measured"},
            {"id": "myst", "rect_mm": None, "measurement_status": status},
        ],
    }
    got = precheck_layout(layout, "known")
    myst = next(n for n in got["neighbors"] if n["id"] == "myst")
    assert myst["rect_mm"] is None and myst["relation"] == "unknown"
    assert myst["overlap_area_mm2"] is None and myst["outside_page"] is None
    assert got["target_outside"] is None
    kinds = [r["kind"] for r in got["risks"]]
    assert MEASUREMENT_LIMITED in kinds and POTENTIAL_OVERLAP not in kinds
    # Target-unknown: outside None + limited, never a fake position claim.
    tgot = precheck_layout(layout, "myst")
    assert tgot["target_rect_mm"] is None and tgot["target_outside"] is None
    assert MEASUREMENT_LIMITED in [r["kind"] for r in tgot["risks"]]
    assert validate_layout(layout)["objects"][1]["rect_mm"] is None
    # project_scene refuses unknown/None targets outright (no TypeError).
    with pytest.raises(RenderContractError):
        project_scene({"coordinate_reference": "canvas_bottom_left",
                       "canvas_mm": [100.0, 50.0], "nodes": []},
                      {"id": "myst", "rect_mm": None,
                       "measurement_status": status}, [210.0, 297.0])


def test_measured_none_rect_rejected():
    layout = {
        "schema": "figpact.layout/1", "source_mode": "standalone",
        "page_mm": [210.0, 297.0],
        "objects": [
            {"id": "bad", "rect_mm": None, "measurement_status": "measured"},
        ],
    }
    with pytest.raises(RenderContractError):
        validate_layout(layout)

def test_metadata_defaults_unknown_and_roundtrip():
    layout = validate_layout(_fixtures()["a4_two_panel"])
    plain = next(o for o in layout["objects"] if o["id"] == "ftir")
    assert plain["z_index"] is None and plain["capabilities"] is None
    assert layout["project_id"] is None and layout["page_id"] is None
    assert layout["host_revision"] is None
    assert validate_layout(layout) == layout  # no facts dropped
    assert validate_layout(json.loads(json.dumps(layout))) == layout
    ghost = next(o for o in layout["objects"] if o["id"] == "ghost")
    assert ghost["rect_mm"] is None and ghost["measurement_status"] == "unsupported"


@pytest.mark.parametrize("mutate", [
    lambda b: b["objects"][0].update({"z_index": 2}),
    lambda b: b["objects"][0].update({"capabilities": ["raster"]}),

    lambda b: b["objects"][0].update({"capabilities": []}),
    lambda b: b.update({"project_id": "p1"}),
    lambda b: b.update({"page_id": "pg7"}),
    lambda b: b.update({"host_revision": "r42"}),
])
def test_metadata_revision_changes(mutate):
    base = validate_layout(_fixtures()["a4_two_panel"])
    other = json.loads(json.dumps(base))
    del other["revision"]
    mutate(other)
    assert validate_layout(other)["revision"] != base["revision"]


@pytest.mark.parametrize("patch", [
    {"z_index": True},
    {"z_index": 1.5},
    {"capabilities": "raster"},
    {"capabilities": ["ok", 1]},
    {"capabilities": [""]},
])
def test_metadata_rejects_bad_types(patch):
    base = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base["objects"][0].update(patch)
    with pytest.raises(RenderContractError):
        validate_layout(base)
    bad = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    bad.update({"project_id": ""})
    with pytest.raises(RenderContractError):
        validate_layout(bad)

def test_precheck_overlap_risks_and_hidden_never_blocks():
    layout = _fixtures()["overlap_page"]
    got = precheck_layout(layout, "target")
    kinds = [r["kind"] for r in got["risks"]]
    assert POTENTIAL_OVERLAP in kinds
    assert MEASUREMENT_LIMITED not in kinds  # no unknown/unsupported here
    hidden = next(n for n in got["neighbors"] if n["id"] == "hidden_near")
    assert hidden["relation"] == "hidden_non_blocking"
    assert all("hidden_near" not in r["object_ids"] or r["kind"] != POTENTIAL_OVERLAP
               for r in got["risks"])
    locked = next(n for n in got["neighbors"] if n["id"] == "locked_near")
    assert locked["relation"] == "potential_overlap"
    assert math.isclose(locked["overlap_area_mm2"], 600.0)
    # POTENTIAL_OVERLAP wording never claims occlusion.
    for risk in got["risks"]:
        if risk["kind"] == POTENTIAL_OVERLAP:
            assert "potential only" in risk["detail"]
            assert "not occlusion" in risk["detail"]


def test_precheck_unknown_target_is_limited_and_outside_reported():
    base = json.loads(json.dumps(_fixtures()["overlap_page"]))
    base["objects"][0]["measurement_status"] = "unknown"
    base["objects"][0]["rect_mm"] = [200.0, 290.0, 85.0, 60.0]
    got = precheck_layout(base, "target")
    kinds = [r["kind"] for r in got["risks"]]
    assert MEASUREMENT_LIMITED in kinds and got["target_outside"] == "PARTIAL_OUTSIDE"
    assert "PARTIAL_OUTSIDE" in kinds
    # Unknown geometry is never disjoint/zero-claimed: unknown neighbor listed unknown.
    base["objects"][0]["rect_mm"] = None
    got2 = precheck_layout(base, "target")
    assert got2["target_rect_mm"] is None and got2["target_outside"] is None
    assert MEASUREMENT_LIMITED in [r["kind"] for r in got2["risks"]]


def test_precheck_rejects_ambiguous_target():
    with pytest.raises(RenderContractError):
        precheck_layout(_fixtures()["overlap_page"], "missing")
    with pytest.raises(RenderContractError):
        precheck_layout(_fixtures()["overlap_page"], "")


def _saved_base():
    base = json.loads(json.dumps(_fixtures()["a4_two_panel"]))
    base["source_mode"] = "saved"
    return base


def test_empty_page_is_legitimate():
    layout = {
        "schema": "figpact.layout/1", "source_mode": "saved",
        "page_mm": [180.0, 254.4], "objects": [],
    }
    got = validate_layout(layout)
    assert got["objects"] == []
    assert got["revision"] == snapshot_revision(got)
    assert validate_layout(got) == got
    assert validate_layout(json.loads(json.dumps(got))) == got


def test_saved_authority_group_resource_override_facts_change_revision():
    base = validate_layout(_saved_base())

    def with_fact(mut):
        other = json.loads(json.dumps(base))
        del other["revision"]
        mut(other)
        return validate_layout(other)

    variants = [
        lambda b: b["objects"][0].update({"group_id": "g_2f5a0z5m"}),
        lambda b: b["objects"][0].update({"render_owner": "tavotto"}),
        lambda b: b["objects"][0].update({"native_size_mm": [88.9, 63.5]}),
        lambda b: b["objects"][0].update({"resource_revision": "abc123"}),
        lambda b: b["objects"][0].update({"overrides_revision": "ov9"}),
        lambda b: b["objects"][0].update({"opacity": 0.5}),
        lambda b: b.update({"extensions": {"tavotto_saved": {"canvas_index": 3}}}),
    ]
    for mut in variants:
        assert with_fact(mut)["revision"] != base["revision"]
    # Extensions are evidence only: geometry QA is unchanged.
    ext = with_fact(lambda b: b.update(
        {"extensions": {"tavotto_saved": {"counts": {"objects": 33}}}}))
    assert [r["kind"] for r in precheck_layout(ext, "bar")["risks"]] == [
        r["kind"] for r in precheck_layout(base, "bar")["risks"]]


def test_rotation_none_only_for_unknown_geometry():
    for status in ("unknown", "unsupported"):
        base = _saved_base()
        base["objects"][0].update(
            {"measurement_status": status, "rect_mm": None, "rotation_deg": None})
        assert validate_layout(base)["objects"][0]["rotation_deg"] is None
    bad = _saved_base()
    bad["objects"][0].update({"rotation_deg": None})
    with pytest.raises(RenderContractError):
        validate_layout(bad)
    # Opaque unknown rotation is never a projection target.
    target = _saved_base()["objects"][0]
    target.update({"measurement_status": "unknown", "rect_mm": None,
                   "rotation_deg": None})
    with pytest.raises(RenderContractError):
        project_scene({"coordinate_reference": "canvas_bottom_left",
                       "canvas_mm": [100.0, 50.0], "nodes": []},
                      target, [210.0, 297.0])


@pytest.mark.parametrize("mutate", [
    lambda b: b["objects"][0].update({"opacity": 2.0}),
    lambda b: b["objects"][0].update({"opacity": float("nan")}),
    lambda b: b["objects"][0].update({"opacity": True}),
    lambda b: b["objects"][0].update({"native_size_mm": [0.0, 5.0]}),
    lambda b: b["objects"][0].update({"native_size_mm": [True, 5.0]}),
    lambda b: b["objects"][0].update({"group_id": ""}),
    lambda b: b["objects"][0].update({"render_owner": "  "}),
    lambda b: b["objects"][0].update({"rotation_deg": None}),
    lambda b: b.update({"extensions": []}),
    lambda b: b.update({"extensions": {"": {"v": 1}}}),
    lambda b: b.update({"extensions": {"e": float("nan")}}),
    lambda b: b.update({"extensions": {"e": {"v": float("inf")}}}),
    lambda b: b.update({"extensions": {"e": {1: "x"}}}),
    lambda b: b.update({"extensions": {"e": object()}}),
])
def test_rejects_bad_saved_facts(mutate):
    base = _saved_base()
    mutate(base)
    with pytest.raises(RenderContractError):
        validate_layout(base)


def test_extensions_deep_copy_idempotent_and_hash_covered():
    base = _saved_base()
    raw_ext = {"tavotto_saved": {"counts": {"objects": 33}, "tags": ["a", "b"]}}
    base["extensions"] = raw_ext
    got = validate_layout(base)
    raw_ext["tavotto_saved"]["counts"]["objects"] = 0
    raw_ext["tavotto_saved"]["tags"].append("zzz")
    assert got["extensions"] == {
        "tavotto_saved": {"counts": {"objects": 33}, "tags": ["a", "b"]}}
    assert validate_layout(got) == got
    assert validate_layout(json.loads(json.dumps(got))) == got
    again = json.loads(json.dumps(got))
    del again["revision"]
    again["extensions"]["tavotto_saved"]["counts"]["objects"] = 34
    assert validate_layout(again)["revision"] != got["revision"]
