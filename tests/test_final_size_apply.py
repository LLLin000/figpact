import shutil
from pathlib import Path

from figpact.final_size import apply_final_size, audit_figure


ROOT = Path("D:/L/AI/figpact")


def _cfg_copy(src, tmp_path):
    dst = tmp_path / src.name
    shutil.copy(src, dst)
    return dst


def _nmr(tmp_path):
    return ROOT / "examples" / "nmr" / "08 NMR.py", _cfg_copy(ROOT / "examples" / "nmr" / "nmr.yaml", tmp_path)


def _ftir(tmp_path):
    return ROOT / "examples" / "ftir" / "plot_ftir.py", _cfg_copy(ROOT / "examples" / "ftir" / "ftir.yaml", tmp_path)


def test_three_roles_written_reach_target(tmp_path):
    script, cfg = _nmr(tmp_path)
    r = apply_final_size(str(script), config=str(cfg), target_width_mm=42.0)
    assert r["source_commit_state"] == "COMMITTED"
    after = audit_figure(str(script), config=str(cfg), target_width_mm=42.0)
    assert abs(after["k"] - 1.0) < 0.01
    assert after["source_canvas_mm"][0] == 42.0


def test_reported_only_roles_unchanged(tmp_path):
    script, cfg = _ftir(tmp_path)
    apply_final_size(str(script), config=str(cfg), target_width_mm=38.0)
    after = cfg.read_text(encoding="utf-8")
    assert "label_font_pt: 4.7" in after
    assert "legend_font_pt: 4.7" in after
    assert "note_font_pt: 6.5" in after


def test_no_safe_entry_refused(tmp_path):
    # Refusal path: remove the three target roles from the contract so
    # apply_final_size has no safe entry and must refuse without writing.
    script, cfg = _nmr(tmp_path)
    original = cfg.read_bytes()

    from figpact import final_size as fs_mod

    orig_import = fs_mod._import_script

    def patched(script_path):
        mod = orig_import(script_path)
        orig_contract = mod.layout_contract

        def contract(scope):
            c = orig_contract(scope)
            c["parameters"] = [
                p for p in c.get("parameters", [])
                if p.get("key") not in ("axis_font_pt", "tick_font_pt", "line_width")
            ]
            return c

        mod.layout_contract = contract
        return mod

    fs_mod._import_script = patched
    try:
        r = fs_mod.apply_final_size(str(script), config=str(cfg), target_width_mm=42.0)
    finally:
        fs_mod._import_script = orig_import

    assert r.get("source_commit_state") == "NOT_WRITTEN"
    assert r.get("figure_verification_state") == "NOT_RUN"
    assert "tick_font_pt" in (r.get("refused_roles") or [])
    assert r.get("refusal_reasons", {}).get("tick_font_pt")
    assert cfg.read_bytes() == original


def test_space_insufficient_report_contains_gid_and_excess(tmp_path):
    script, cfg = _ftir(tmp_path)
    r = apply_final_size(str(script), config=str(cfg), target_width_mm=38.0)
    rep = r.get("infeasible_report", "")
    assert rep
    assert "overflow" in rep.lower() or "gid" in rep.lower() or "object" in rep.lower() or "infeasible" in rep.lower()


def test_no_mode_stacking(tmp_path):
    script, cfg = _nmr(tmp_path)
    original = cfg.read_text(encoding="utf-8")
    r = apply_final_size(str(script), config=str(cfg), target_width_mm=42.0, mode="A")
    assert r["source_commit_state"] == "NOT_WRITTEN"
    assert cfg.read_text(encoding="utf-8") == original
    apply_final_size(str(script), config=str(cfg), target_width_mm=42.0, mode="B")
    assert "canvas_w_mm: 42.0" in cfg.read_text(encoding="utf-8")