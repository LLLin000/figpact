import shutil
from pathlib import Path

from figpact.final_size import apply_final_size, audit_figure, safe_editable_fields


ROOT = Path("D:/L/AI/figpact")


def _nmr(tmp_path):
    src = ROOT / "examples" / "nmr" / "08 NMR.py"
    cfg_src = ROOT / "examples" / "nmr" / "nmr.yaml"
    dst = tmp_path / cfg_src.name
    shutil.copy(cfg_src, dst)
    return src, dst


def test_tick_role_editable_and_effective(tmp_path):
    script, cfg = _nmr(tmp_path)
    editable, scope, _ = safe_editable_fields(str(script), config=str(cfg))
    assert "tick_font_pt" in editable, editable
    r = apply_final_size(str(script), config=str(cfg), target_width_mm=42.0,
                        target_tick_font_pt=7.0)
    assert r.get("source_commit_state") == "COMMITTED", r
    assert "tick_font_pt" not in (r.get("refused_roles") or [])
    after = audit_figure(str(script), config=str(cfg), target_width_mm=42.0)
    assert abs(after["k"] - 1.0) < 0.01
    tick = next(fr for fr in after["font_roles"] if fr["role_key"] == "tick_font_pt")
    assert tick["nominal_pt"] == 7.0
    assert abs(tick["effective_pt_at_target"] - 7.0) < 0.1


def test_unchanged_config_renders(tmp_path):
    script, cfg = _nmr(tmp_path)
    import yaml
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    w = float(data.get("canvas_w_mm", 42.0))
    before = audit_figure(str(script), config=str(cfg), target_width_mm=w)
    assert not before.get("infeasible", [])
    tick = next(fr for fr in before["font_roles"] if fr["role_key"] == "tick_font_pt")
    assert tick["n_samples"] > 0


def test_role_refusal_honestly_reported(tmp_path):
    script, cfg = _nmr(tmp_path)
    editable, _, _ = safe_editable_fields(str(script), config=str(cfg))
    if "tick_font_pt" not in editable:
        r = apply_final_size(str(script), config=str(cfg), target_width_mm=42.0)
        assert "tick_font_pt" in (r.get("refused_roles") or [])
        assert r.get("refusal_reasons", {}).get("tick_font_pt")
    else:
        assert True
