"""G9 plate audit tests (includes mixed code + vector + bitmap inputs)."""
import json
from pathlib import Path

from figpact import plate

ROOT = Path(__file__).resolve().parents[1]
FTIR_SCRIPT = ROOT / "examples" / "ftir" / "plot_ftir.py"
FTIR_YAML = ROOT / "examples" / "ftir" / "ftir.yaml"


def _make_vector(path: Path) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=150)
    page.insert_text((20, 50), "vector label", fontsize=9)
    doc.save(path)
    doc.close()
    return path


def _make_bitmap(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (800, 600), "white").save(path)
    return path


def _mixed_specs(tmp_path):
    vec = _make_vector(tmp_path / "v.pdf")
    bmp = _make_bitmap(tmp_path / "b.png")
    specs = [
        {"label": "ftir", "path": str(FTIR_SCRIPT), "config": str(FTIR_YAML)},
        {"label": "vec", "path": str(vec)},
        {"label": "bmp", "path": str(bmp)},
    ]
    return specs, [42.0, 42.0, 42.0]


def test_code_audit_rows_comparable(tmp_path):
    specs, widths = _mixed_specs(tmp_path)
    a = plate.audit([specs[0]], [widths[0]])
    (fig,) = a["figures"]
    assert fig["kind"] == "code"
    assert 0.5 < fig["k"] < 1.5  # measured export ratio, not declared
    assert fig["role_eff_pt"], "per-nominal measured eff_pt required"
    assert fig["artist_fonts"], "per-gid rows required"
    assert "control" in json.dumps(fig["measurement_basis"], ensure_ascii=False).lower() \
        or "Ag" in json.dumps(fig["measurement_basis"], ensure_ascii=False)
    assert fig["unmeasurable_specs"] == []


def test_mixed_audit_marks_unmeasurable(tmp_path):
    specs, widths = _mixed_specs(tmp_path)
    a = plate.audit(specs, widths)
    by_label = {f["label"]: f for f in a["figures"]}

    vec = by_label["vec"]
    assert vec["page_size_mm"] == [round(200 * 25.4 / 72, 3), round(150 * 25.4 / 72, 3)]
    assert any("page" in s for s in vec["measurable_specs"])
    assert vec["unmeasurable_specs"], "vector must disclose outlined/missing-font limits"

    bmp = by_label["bmp"]
    assert bmp["pixels"] == [800, 600]
    assert bmp["dpi_assumed"] is True
    assert bmp["physical_size_mm"] == [round(800 * 25.4 / 300, 3), round(600 * 25.4 / 300, 3)]
    joined = " ".join(bmp["unmeasurable_specs"])
    assert "font_size_pt" in joined and "linewidth_pt" in joined
    assert "MUST NOT" in joined, "bitmap must never report spec compliance"


def test_plan_refuses_non_code_and_uneditable(tmp_path):
    specs, widths = _mixed_specs(tmp_path)
    a = plate.audit(specs, widths)
    plan = plate.plan_unify(a, {"axis_font_pt": 8.0, "tick_font_pt": 7.0,
                                "line_width": 0.8, "target_width_mm": 42.0})
    kinds = {(i.get("kind"), i.get("figure")) for i in plan["infeasible"]}
    assert any(k == "vector" for k, _ in kinds) and any(k == "bitmap" for k, _ in kinds)
    # ftir contract declares no tick_font_pt -> blocked, never auto-shrunk
    assert any(i.get("key") == "tick_font_pt" for i in plan["infeasible"])
    assert plan["status"] in ("infeasible", "partially_feasible")


def test_receipt_byte_stable(tmp_path):
    specs, widths = _mixed_specs(tmp_path)
    a = plate.audit(specs, widths)
    r1 = plate.receipt(a)
    r2 = plate.receipt(a)
    blob1 = json.dumps({k: v for k, v in r1.items() if k != "generated_at"},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    blob2 = json.dumps({k: v for k, v in r2.items() if k != "generated_at"},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert blob1 == blob2, "receipt must be byte-identical across reruns (timestamp excluded)"
    assert r1["content_hash"] == r2["content_hash"]
    assert r1["schema_version"] == "plate-receipt/1"
