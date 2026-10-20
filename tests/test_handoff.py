"""figpact ↔ Tavotto handoff: real PDF measurement, hashes and panel scale."""
from __future__ import annotations

import json
from pathlib import Path
import hashlib

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from figpact import handoff  # noqa: E402

pypdf = pytest.importorskip("pypdf")


def _pdf(path: Path, width_mm: float, height_mm: float) -> Path:
    fig = plt.figure(figsize=(width_mm / 25.4, height_mm / 25.4))
    fig.text(0.5, 0.5, "handoff")
    fig.savefig(path, format="pdf")
    plt.close(fig)
    return path


def _layout(path: Path, width: float, height: float) -> Path:
    path.write_text(json.dumps({
        "schema": 3,
        "canvases": [{"id": "c1", "name": "Figure 2", "page": {"w": 180, "h": 254.4},
                      "objects": [{"id": "p1", "type": "panel", "fileId": "Fig.pdf",
                                   "nativeW": 48.0, "nativeH": 48.0,
                                   "w": width, "h": height}]}],
    }), encoding="utf-8")
    return path


def _spec(asset: Path, source: Path, font_pt: float = 6.0) -> dict:
    return {
        "schema": handoff.SCHEMA,
        "figures": [{
            "id": "NMR", "asset": str(asset), "sources": [str(source)],
            "target_width_mm": 48.0, "target_height_mm": 48.0,
            "min_effective_font_pt": 5.0,
            "font_roles": [{"role": "axis", "source_pt": 8.5},
                           {"role": "label", "source_pt": font_pt}],
        }],
    }


def test_pdf_page_is_measured_from_the_real_file(tmp_path):
    page = handoff.measure_pdf_page_mm(_pdf(tmp_path / "a.pdf", 48.0, 30.0))
    assert page["measured_page_mm"][0] == pytest.approx(48.0, abs=0.01)
    assert page["measured_page_mm"][1] == pytest.approx(30.0, abs=0.01)


def test_build_then_verify_passes_only_at_real_scale(tmp_path):
    asset = _pdf(tmp_path / "Fig.pdf", 48.0, 48.0)
    source = tmp_path / "plot.py"
    source.write_text("print('x')\n", encoding="utf-8")
    built = handoff.build(_spec(asset, source), base=tmp_path)
    assert built["figures"][0]["asset_sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
    good = handoff.verify(built, base=tmp_path, layout=_layout(tmp_path / "good.json", 48.0, 48.0),
                          canvas="Figure 2")
    assert good["status"] == "PASS", good["findings"]
    assert good["layout"]["panels"][0]["scale_x"] == pytest.approx(1.0)


def test_nonuniform_layout_and_font_floor_fail_closed(tmp_path):
    asset = _pdf(tmp_path / "Fig.pdf", 48.0, 48.0)
    source = tmp_path / "plot.py"
    source.write_text("print('x')\n", encoding="utf-8")
    built = handoff.build(_spec(asset, source, font_pt=4.7), base=tmp_path)
    report = handoff.verify(built, base=tmp_path,
                            layout=_layout(tmp_path / "bad.json", 52.639, 49.968),
                            canvas="Figure 2")
    codes = {item["code"] for item in report["findings"]}
    assert report["status"] == "FAIL"
    assert {"LAYOUT_NON_UNIFORM", "LAYOUT_SCALED", "FONT_BELOW_FLOOR"} <= codes


def test_scan_uses_the_tavotto_canvas_as_the_only_layout_source(tmp_path):
    asset = _pdf(tmp_path / "Fig.pdf", 48.0, 48.0)
    source = tmp_path / "plot.py"
    source.write_text("print('x')\n", encoding="utf-8")
    layout = _layout(tmp_path / "A.json", 48.0, 48.0)
    layout.write_text(json.dumps({
        "schema": 3,
        "canvases": [{"id": "c1", "name": "Figure 2", "page": {"w": 180, "h": 254.4},
                      "objects": [{"id": "p1", "type": "panel", "fileId": "Fig.pdf",
                                   "script": "plot.py", "nativeW": 48.0, "nativeH": 48.0,
                                   "w": 48.0, "h": 48.0},
                                  {"id": "p2", "type": "panel", "fileId": "photo.jpg",
                                   "nativeW": 100, "nativeH": 100, "w": 40, "h": 40}]}],
    }), encoding="utf-8")
    manifest = handoff.scan_layout(layout, base=tmp_path, canvas="Figure 2")
    assert len(manifest["figures"]) == 1
    assert manifest["figures"][0]["target_width_mm"] == 48.0
    report = handoff.verify(manifest, base=tmp_path, layout=layout, canvas="Figure 2")
    assert report["status"] == "PASS", report["findings"]
    bad = _layout(tmp_path / "B.json", 52.0, 48.0)
    report = handoff.verify(manifest, base=tmp_path, layout=bad, canvas="Figure 2")
    assert {"LAYOUT_NON_UNIFORM", "LAYOUT_SCALED"} <= {f["code"] for f in report["findings"]}


def test_changed_asset_or_source_is_not_silently_latest(tmp_path):
    asset = _pdf(tmp_path / "Fig.pdf", 48.0, 48.0)
    source = tmp_path / "plot.py"
    source.write_text("print('x')\n", encoding="utf-8")
    built = handoff.build(_spec(asset, source), base=tmp_path)
    _pdf(asset, 48.0, 48.0)  # same page size
    asset.write_bytes(asset.read_bytes() + b"\n% changed\n")
    source.write_text("print('changed')\n", encoding="utf-8")
    report = handoff.verify(built, base=tmp_path)
    codes = {item["code"] for item in report["findings"]}
    assert {"ASSET_CHANGED", "STALE_SOURCE"} <= codes
