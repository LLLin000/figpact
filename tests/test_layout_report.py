"""G3 report consumers: snapshot drift and renderer authority, no save route."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from figpact.cli import main
from figpact.layout_report import LayoutReportError, report_layout
from figpact.render_contract import validate_layout
from figpact.tavotto_saved import SavedLayoutError, managed_report_source, read_saved_layout


def _layout():
    return validate_layout({
        "schema": "figpact.layout/1", "source_mode": "standalone", "page_mm": [180, 150],
        "objects": [{"id": "nmr", "kind": "panel", "render_owner": "figpact",
                     "measurement_status": "measured", "rect_mm": [10, 20, 24, 24]},
                    {"id": "photo", "kind": "panel", "render_owner": "asset",
                     "measurement_status": "conservative", "rect_mm": [100, 20, 30, 40]}]})


def test_report_rejects_drift_in_fixed_neighbour_from_same_page_producer():
    layout = _layout()
    changed = copy.deepcopy(layout)
    changed.pop("revision")
    changed["objects"][1]["rect_mm"][0] = 20
    changed = validate_layout(changed)
    captures = iter([layout, changed])
    with pytest.raises(LayoutReportError) as caught:
        report_layout(layout, ["nmr"], expected_revision=layout["revision"],
                      refresh_layout=lambda: next(captures))
    assert caught.value.status == "STALE"
    assert layout["objects"][1]["rect_mm"] == [100, 20, 30, 40]


def test_historical_snapshot_cannot_be_promoted_by_a_new_expected_revision():
    layout = _layout()
    changed = copy.deepcopy(layout)
    changed.pop("revision")
    changed["objects"][0]["rect_mm"][2] = 48
    newer = validate_layout(changed)
    with pytest.raises(LayoutReportError) as caught:
        report_layout(layout, ["nmr"], expected_revision=newer["revision"])
    assert caught.value.status == "STALE"


def _saved_managed(root: Path, **changes):
    script = root / "trusted.py"
    script.write_text("raise RuntimeError('adapter must not execute a script')\n", encoding="utf-8")
    (root / "trusted.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    record = {"id": "figure", "type": "panel", "fileKind": "runtime",
              "fileId": "runtime:trusted.py#main", "renderOwner": "figpact",
              "script": "trusted.py", "figpact": {"config": "trusted.yaml", "scope": "main"},
              "nativeW": 48, "nativeH": 48, "x": 10, "y": 10, "w": 48, "h": 48,
              "overrides": [], **changes}
    document = {"schema": 3, "project": {"id": "project", "name": "Project"},
                "activeCanvasId": "page", "canvases": [{"id": "page", "name": "Page",
                "page": {"w": 180, "h": 150}, "objects": [record], "layoutGroups": []}]}
    path = root / "saved.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, read_saved_layout(path, base=root, canvas="page")


def test_managed_source_uses_explicit_owner_and_rejects_unreplayed_overrides(tmp_path):
    _, snapshot = _saved_managed(tmp_path)
    source = managed_report_source(snapshot, "figure", base=tmp_path)
    assert source["script"] == str((tmp_path / "trusted.py").resolve())
    assert source["config"] == str((tmp_path / "trusted.yaml").resolve())
    assert source["scope"] == "main"
    _, overridden = _saved_managed(tmp_path, overrides=[{"gid": "axis", "prop": "fontsize", "value": 20}])
    with pytest.raises(SavedLayoutError):
        managed_report_source(overridden, "figure", base=tmp_path)
    _, legacy = _saved_managed(tmp_path, renderOwner="tavotto")
    with pytest.raises(SavedLayoutError):
        managed_report_source(legacy, "figure", base=tmp_path)


def test_cli_refuses_a_different_script_before_execution(tmp_path, capsys):
    path, snapshot = _saved_managed(tmp_path)
    marker = tmp_path / "executed.txt"
    other = tmp_path / "unrelated.py"
    other.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('wrong renderer')\n",
                     encoding="utf-8")
    assert main(["layout-report", "--layout", str(path), "--base", str(tmp_path),
                 "--canvas", "page", "--expected-revision", snapshot["revision"], "--target", "figure",
                 "--managed", "figure", str(other), str(tmp_path / "trusted.yaml"), "main"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "STALE"
    assert not marker.exists()


def test_real_nmr_reports_effective_fonts_coupling_readonly_and_source_drift(tmp_path):
    import yaml
    from figpact.render_api import RenderSession

    root = Path(__file__).resolve().parents[1]
    script = root / "examples" / "nmr" / "08 NMR.py"
    original_config = root / "examples" / "nmr" / "nmr.yaml"
    config = tmp_path / "nmr.yaml"
    original_bytes = original_config.read_bytes()
    config.write_bytes(original_bytes)
    layout = _layout()
    before_layout = copy.deepcopy(layout)
    sources = {"nmr": {"script": str(script), "config": str(config),
                       "scope": "main", "overrides_present": False}}
    session = RenderSession(script, config, "main", output_dir=tmp_path)
    try:
        baseline = session.snapshot()
        report = report_layout(layout, ["nmr"], {"nmr": session},
                               expected_revision=layout["revision"], source_bindings=sources)
        assert report["currentness"] == "SNAPSHOT_BOUND"
        assert report["targets"][0]["binding"]["frame_revision"] == baseline["frame"]["frame_revision"]
        capabilities = report["targets"][0]["capabilities"]
        titles = [row for row in capabilities["roles"] if row["semantic_role"] == "axis.title"]
        assert {row["axis"] for row in titles} == {"x", "y"}
        raw = {node["id"]: node for node in json.loads(baseline["frame"]["scene_json"])["nodes"]}
        for row in titles:
            assert row["source_font_pt"] == raw[row["id"]]["font_size_pt"]
            assert row["effective_font_pt"] == pytest.approx(row["source_font_pt"] * 0.5)
            assert any(control["editable"] for control in row["font_controls"])
        coupling = next(c for c in capabilities["coupling"] if c["path"] == ["axis_font_pt"])
        assert {group["axis"] for group in coupling["affected_role_groups"]} == {"x", "y"}
        assert set(coupling["affected_ids"]) == {row["id"] for row in titles}
        assert layout == before_layout and config.read_bytes() == original_bytes
        assert session.snapshot()["pending"] is None

        altered = copy.deepcopy(layout)
        altered.pop("revision")
        altered["objects"][0]["rect_mm"][2] = 48
        altered = validate_layout(altered)
        anisotropic = report_layout(altered, ["nmr"], {"nmr": session},
                                    expected_revision=altered["revision"], source_bindings=sources)
        title_rows = [r for r in anisotropic["targets"][0]["capabilities"]["roles"]
                      if r["semantic_role"] == "axis.title"]
        assert all(r["effective_font_pt"] is None for r in title_rows)
        assert all(not c["editable"] for r in title_rows for c in r["font_controls"])

        locked = copy.deepcopy(layout)
        locked.pop("revision")
        locked["objects"][0]["locked"] = True
        locked = validate_layout(locked)
        reference = report_layout(locked, ["nmr"], {"nmr": session},
                                  expected_revision=locked["revision"], source_bindings=sources)
        assert reference["targets"][0]["access"] == "MEASUREMENT_ONLY"
        assert all(not c["editable"] for r in reference["targets"][0]["capabilities"]["roles"]
                   for c in r["font_controls"])

        changed = yaml.safe_load(config.read_text(encoding="utf-8"))
        changed["axis_font_pt"] += 0.5
        config.write_text(yaml.safe_dump(changed, allow_unicode=True), encoding="utf-8")
        with pytest.raises(LayoutReportError) as caught:
            report_layout(layout, ["nmr"], {"nmr": session},
                          expected_revision=layout["revision"], source_bindings=sources)
        assert caught.value.status == "STALE"
        assert original_config.read_bytes() == original_bytes
    finally:
        session.close()
