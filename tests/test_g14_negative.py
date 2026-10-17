"""G14 Phase 5 负向证明：只新建本文件，不碰产品代码。"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
import pytest
import yaml

from figpact import change_audit, roles
from figpact.change_audit import ChangeAuditError
from figpact.init_contract import DRAFT_SCHEMA, load_verified
from figpact.roles import RoleBindingError


def _pair(before_styles, after_styles, allowed, view=True):
    before = {"styles": dict(before_styles), "shapes": {}}
    after = {"styles": dict(after_styles), "shapes": {}}
    if view:
        before["view"] = {}
        after["view"] = {}
    return change_audit.audit_pair(before, after, allowed)


def test_non_target_semantic_change_is_unauthorized_with_gid_and_property():
    res = _pair({"g1": {"fontsize": 8.0}}, {"g1": {"fontsize": 9.0}},
                {"styles": {}, "shapes": {}})
    hit = [u for u in res["unauthorized"]
           if u.get("gid") == "g1" and u.get("property") == "fontsize"]
    assert hit and hit[0]["class"] == "semantic"
    assert res["within_allowed"] is False


def test_view_in_allowed_is_rejected():
    before = {"styles": {}, "shapes": {}, "view": {}}
    after = {"styles": {}, "shapes": {}, "view": {}}
    with pytest.raises(ChangeAuditError):
        change_audit.audit_pair(before, after, {"styles": {}, "view": {}})


def test_legacy_confirmed_verified_pair_rejected_under_current_registry(tmp_path):
    draft = {"schema_version": DRAFT_SCHEMA, "scope": "main",
             "script": "s.py", "config": "c.yaml",
             "candidates": [{"role": "panel.label", "param": "peak_font_pt",
                             "confirmed": True, "verified": True}]}
    p = tmp_path / "draft.yaml"
    p.write_text(yaml.safe_dump(draft), encoding="utf-8")
    res = load_verified(p)
    assert res["entries"] == []
    assert {"role": "panel.label", "param": "peak_font_pt",
            "reason": "role_binding_invalid_under_current_registry"} in res["rejected"]


def test_required_target_unchanged_is_not_effective():
    res = _pair({"g1": {"fontsize": 8.0}}, {"g1": {"fontsize": 8.0}},
                {"styles": {"g1": {"fontsize"}}, "shapes": {},
                 "required_targets": [{"gid": "g1", "property": "fontsize"}]})
    assert res["all_required_changed"] is False


def test_non_letter_text_must_not_pose_as_panel_label():
    fig, ax = plt.subplots()
    try:
        t = ax.text(0.5, 0.5, "hello world", transform=ax.transAxes)
        with pytest.raises(RoleBindingError):
            roles.check_binding("panel.label", t, fig)
    finally:
        plt.close(fig)


def test_missing_view_is_audit_incomplete():
    res = _pair({"g1": {"fontsize": 8.0}}, {"g1": {"fontsize": 8.0}},
                {"styles": {"g1": {"fontsize"}}, "shapes": {}}, view=False)
    assert any(u.get("class") == "AUDIT_INCOMPLETE" for u in res["unauthorized"])
    assert res["within_allowed"] is False


def test_svg_png_have_no_editable_binding():
    for bogus in ("svg", "png", "SVG", "PNG"):
        with pytest.raises(RoleBindingError):
            roles.resolve(bogus)
    assert "svg" not in roles.ROLE_REGISTRY and "png" not in roles.ROLE_REGISTRY
    assert "svg" not in roles.COMPARE_ROLES and "png" not in roles.COMPARE_ROLES
    for rid, entry in roles.ROLE_REGISTRY.items():
        assert "svg" not in (entry.get("artist_kinds") or ())
        assert "png" not in (entry.get("artist_kinds") or ())
