"""G10 plate manifest + compare + manifest-driven unify tests."""
import json
from pathlib import Path

import pytest

from figpact import plate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "examples" / "plate" / "plate_g10.yaml"


def _svg(tmp_path: Path) -> Path:
    p = tmp_path / "v.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="60mm">'
                 '<text x="10" y="20" font-size="14">hello</text></svg>', encoding="utf-8")
    return p


def _png(tmp_path: Path) -> Path:
    from PIL import Image

    p = tmp_path / "b.png"
    Image.new("RGB", (300, 300), "white").save(p)
    return p


def _manifest(tmp_path: Path, width: float = 80.0) -> dict:
    return {
        "path": str(tmp_path / "plate.yaml"),
        "design": {"global": {"axis_title_pt": 8, "axis_tick_pt": 7, "panel_label_pt": 9},
                   "plot": {"curve_linewidth_pt": 0.8}, "image": {}},
        "policy": {"science_content": "locked"},
        "figures": [
            {"id": "vec", "target_width_mm": width},
            {"id": "bmp", "target_width_mm": width},
        ],
        "manifest_hash": "test",
    }


def test_load_plate_example_schema():
    m = plate.load_plate(MANIFEST)
    assert [f["id"] for f in m["figures"]] == ["nmr", "ftir", "synth_vector", "micro_bitmap"]
    assert all(f["target_width_mm"] == 80 for f in m["figures"])
    assert m["design"]["global"]["axis_title_pt"] == 8
    assert m["design"]["plot"]["curve_linewidth_pt"] == 0.8
    assert m["policy"]["science_content"] == "locked"
    assert len(m["manifest_hash"]) == 64


def test_load_plate_rejects_bad_manifest(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("plate:\n  figures: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        plate.load_plate(bad)
    dup = tmp_path / "dup.yaml"
    dup.write_text("plate:\n  target_width_mm: 80\n  figures:\n"
                   "    - {id: a, source: x.py}\n    - {id: a, source: y.py}\n",
                   encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        plate.load_plate(dup)


def test_manifest_shared_targets_skip_panel_label():
    t = plate.manifest_shared_targets(_manifest(Path(".")))
    assert t == {"axis_font_pt": 8.0, "tick_font_pt": 7.0, "line_width": 0.8,
                 "target_width_mm": 80.0}


def test_compare_marks_vector_bitmap_honestly(tmp_path):
    specs = [{"label": "vec", "path": str(_svg(tmp_path))},
             {"label": "bmp", "path": str(_png(tmp_path))}]
    a = plate.audit(specs, [80.0, 80.0])
    c = plate.compare_roles(a, _manifest(tmp_path))
    vec = c["cells"]["vec"]["axis.title"]
    assert vec["value_kind"] == "measured_unattributed"  # span size read, role not bound
    assert vec["comparable"] is False and vec["editable"] is False
    assert vec["conformant"] == "n/a"  # not_verified, never conformant
    bmp = c["cells"]["bmp"]["axis.title"]
    assert bmp["value"] is None and bmp["comparable"] is False
    assert "MUST NOT" in (bmp.get("conformant_note") or "")
    assert c["infeasible"], "non-code inputs must appear as infeasible"
    text = plate.render_compare_text(a, c)
    assert "C✗ E✗ F–" in text


def test_compare_code_cells_carry_three_marks(tmp_path):
    ftir = {"label": "ftir", "path": str(ROOT / "examples" / "ftir" / "plot_ftir.py"),
            "config": str(ROOT / "examples" / "ftir" / "ftir.yaml")}
    a = plate.audit([ftir], [80.0])
    m = {"design": {"global": {"axis_title_pt": 8, "axis_tick_pt": 7},
                     "plot": {"curve_linewidth_pt": 0.8}},
         "figures": [{"id": "ftir", "target_width_mm": 80.0}]}
    c = plate.compare_roles(a, m)
    cell = c["cells"]["ftir"]["axis.title"]
    assert cell["value_kind"] == "measured" and cell["comparable"] is True
    assert cell["editable"] is True and cell["conformant"] in (True, False)
    assert cell["conformant_target_pt"] == 8
    # code cells report control-glyph measured values, never estimates
    assert cell.get("comparable_basis", "").startswith("control-glyph")


def test_unify_plan_driven_by_tokens_without_writing(tmp_path):
    pytest.importorskip("matplotlib")
    ftir_src = ROOT / "examples" / "ftir" / "plot_ftir.py"
    ftir_cfg = ROOT / "examples" / "ftir" / "ftir.yaml"
    work_cfg = tmp_path / "ftir.yaml"
    work_cfg.write_bytes(ftir_cfg.read_bytes())
    specs = [{"label": "ftir", "path": str(ftir_src), "config": str(work_cfg)}]
    a = plate.audit(specs, [80.0])
    m = {"design": {"global": {"axis_title_pt": 8, "axis_tick_pt": 7},
                     "plot": {"curve_linewidth_pt": 0.8}},
         "figures": [{"id": "ftir", "target_width_mm": 80.0}]}
    plan = plate.plan_unify(a, plate.manifest_shared_targets(m))
    assert plan["targets"]["axis_font_pt"] == 8.0
    before = work_cfg.read_bytes()
    plate.unify(plan, specs=specs, dry_run=True)
    assert work_cfg.read_bytes() == before, "dry run must not write"


def test_receipt_carries_manifest_and_token_sources(tmp_path):
    specs = [{"label": "bmp", "path": str(_png(tmp_path))}]
    a = plate.audit(specs, [80.0])
    m = _manifest(tmp_path)
    c = plate.compare_roles(a, m)
    r = plate.receipt(a, manifest=m, compare=c)
    assert r["manifest_hash"] == "test"
    assert r["design_token_sources"]["axis_title_pt"]["section"] == "design.global"
    assert r["design_token_sources"]["axis_title_pt"]["param"] == "axis_font_pt"
    assert r["compare"]["cells"]["bmp"]["axis.title"]["comparable"] is False
    assert r["schema_version"] == "plate-receipt/1"
