"""G11 init-contract 最小闭环测试：discover/verify/已验证契约门控 + 三条反例。"""
import shutil
import yaml
from pathlib import Path

import pytest

from figpact import init_contract as ic
from figpact import plate

ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = ROOT / "examples" / "demo" / "demo_figure.py"
DEMO_YAML = ROOT / "examples" / "demo" / "demo.yaml"


def _draft(tmp_path, **kw):
    out = tmp_path / "t.contract.yaml"
    draft = ic.discover(str(DEMO_SCRIPT), str(DEMO_YAML))
    if kw.get("confirm"):
        for c in draft["candidates"]:
            c["confirmed"] = True
    out.write_text(yaml.safe_dump(draft, sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    return out


def test_discover_finds_three_entries_with_evidence(tmp_path):
    d = ic.discover(str(DEMO_SCRIPT), str(DEMO_YAML))
    by_param = {c["param"]: c for c in d["candidates"]}
    assert set(by_param) == {"axis_font_pt", "tick_font_pt", "line_width"}
    assert all(c["confirmed"] is False and c["verified"] is False
               for c in d["candidates"])
    axis = by_param["axis_font_pt"]
    assert any(s["line"] == 244 for s in axis["source"])
    assert 'axis_font_pt' in axis["source"][0]["call"]
    line = by_param["line_width"]
    assert line["artist"]["registered"] is True
    assert "figdemo.main.curve.alpha" in line["artist"]["gids"]
    # 歧义不猜：direction-only 的 tick_params 进 unresolved。
    assert any(u.get("kind") == "entry" and "tick_params" in (u.get("location") or {}).get("call", "")
               for u in d["unresolved"])
    cov = d["coverage"]
    assert cov["denominator_roles"] == ["axis.title", "axis.tick", "curve.linewidth",
                                        "panel.label", "legend", "scalebar"]
    assert set(cov["candidate"]) == {"axis.title", "axis.tick", "curve.linewidth"}
    assert "panel.label" in cov["unresolved"] and "legend" in cov["unresolved"]
    assert "scalebar" in cov["unsupported"]


def test_verify_three_roles_with_nonzero_perturbation(tmp_path):
    p = _draft(tmp_path, confirm=True)
    res = ic.verify(str(p), width_mm=80.0)
    assert res["failed"] == [] and sorted(res["verified"]) == [
        "axis_font_pt", "line_width", "tick_font_pt"]
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    for c in d["candidates"]:
        assert c["verified"] is True
        ev = c["evidence"]
        assert ev["perturbation"]["nonzero"] is True
        assert ev["perturbation"]["from"] != ev["perturbation"]["to"]
        assert ev["target_before"] != ev["target_after"]
        for _role, vals in ev["nontarget_unchanged"].items():
            assert vals  # 非目标角色有实测值且前后一致（不一致 verify 已失败）
        assert ev["science"]["unchanged"] is True
        assert ev["science"]["digest_before"] == ev["science"]["digest_after"]
        assert ev["qa_added"] == []
        assert ev["object_identity"]["gids_stable"] is True
    assert sorted(d["coverage"]["verified_editable"]) == [
        "axis.tick", "axis.title", "curve.linewidth"]


def test_unconfirmed_never_takes_effect(tmp_path):
    """反例1：未确认不得生效（verify 跳过；清单加载为空）。"""
    p = _draft(tmp_path)  # confirmed 全 False
    res = ic.verify(str(p), width_mm=80.0)
    assert res["verified"] == [] and res["failed"] == []
    assert res["skipped_unconfirmed"] == 3
    assert ic.load_verified(str(p))["params"] == []


def test_ambiguous_never_guessed(tmp_path):
    """反例2：歧义不得猜（direction-only 调用在 unresolved，不在 candidates）。"""
    d = ic.discover(str(DEMO_SCRIPT), str(DEMO_YAML))
    cands = [c["param"] for c in d["candidates"]]
    assert "direction" not in " ".join(cands)
    tick_unres = [u for u in d["unresolved"]
                  if (u.get("location") or {}).get("line") == 250]
    assert tick_unres and tick_unres[0]["kind"] == "entry"


def test_failed_perturbation_never_upgrades(tmp_path):
    """反例3：扰动失败不得升 E✓（候选绑定被破坏 → 验证失败 → 不升级）。"""
    p = _draft(tmp_path, confirm=True)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    tick = next(c for c in data["candidates"] if c["param"] == "tick_font_pt")
    tick["param"] = "tick_font_pt_bogus"  # 绑定断裂：YAML 里无此键，扰动无从谈起
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                 encoding="utf-8")
    res = ic.verify(str(p), width_mm=80.0)
    assert "tick_font_pt_bogus" in res["failed"]
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    bad = next(c for c in d["candidates"] if c["param"] == "tick_font_pt_bogus")
    assert bad["verified"] is False and bad["evidence"].get("failure")
    assert "axis.tick" not in d["coverage"]["verified_editable"]
    good = [c["param"] for c in d["candidates"] if c.get("verified")]
    assert sorted(good) == ["axis_font_pt", "line_width"]


def test_plate_compare_marks_demo_editable_via_contract(tmp_path):
    p = _draft(tmp_path, confirm=True)
    ic.verify(str(p), width_mm=80.0)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["script"] = str(DEMO_SCRIPT)
    data["config"] = str(DEMO_YAML)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                 encoding="utf-8")
    manifest = {"contracts": {"demo": ic.load_verified(str(p))}}
    spec = {"label": "demo", "path": str(DEMO_SCRIPT),
            "config": str(DEMO_YAML), "scope": "main"}
    audit = plate.audit([spec], [80.0])
    compare = plate.compare_roles(audit, manifest)
    cells = compare["cells"]["demo"]
    assert cells["axis.title"]["editable"] is True
    assert cells["axis.tick"]["editable"] is True
    assert cells["curve.linewidth"]["editable"] is True
    assert cells["axis.title"].get("editable_via") == "verified-contract"
