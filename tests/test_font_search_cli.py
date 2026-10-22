"""Public layout-search argv trust-boundary behavior."""
from __future__ import annotations

import json

from figpact.cli import main
from figpact.render_contract import snapshot_revision, validate_layout


def _layout():
    return validate_layout({
        "schema": "figpact.layout/1", "source_mode": "standalone", "page_mm": [180, 150],
        "objects": [
            {"id": "nmr", "kind": "panel", "render_owner": "figpact",
             "measurement_status": "measured", "rect_mm": [10, 20, 24, 24],
             "source": {"script": "trusted.py", "config": "trusted.yaml", "scope": "main"}},
            {"id": "ftir", "kind": "panel", "render_owner": "figpact",
             "measurement_status": "measured", "rect_mm": [60, 20, 24, 24],
             "source": {"script": "other.py", "config": "other.yaml", "scope": "main"}},
        ],
    })


def _argv(tmp_path, *, intent, managed):
    layout = _layout()
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout), encoding="utf-8")
    argv = ["layout-search", "--snapshot", str(path), "--base", str(tmp_path),
            "--expected-revision", layout["revision"], "--target", "nmr", "--target", "ftir"]
    for row in managed:
        argv += ["--managed", *row]
    return argv + ["--intent", intent]


def test_search_refuses_unmanaged_target_before_any_source_execution(tmp_path, capsys):
    marker = tmp_path / "ran.txt"
    managed_script = tmp_path / "trusted.py"
    managed_script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    managed_config = tmp_path / "trusted.yaml"
    managed_config.write_text("schema_version: 1\n", encoding="utf-8")
    argv = _argv(tmp_path, intent='{"schema":"figpact.font-search/1"}',
                 managed=[["nmr", str(managed_script), str(managed_config), "main"]])
    assert main(argv) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == "figpact.font-search-result/1"
    assert result["status"] == "INVALID"
    assert not marker.exists()


def test_search_refuses_source_mismatch_before_running_untrusted_script(tmp_path, capsys):
    layout = _layout()
    revision = snapshot_revision(layout)
    marker = tmp_path / "ran.txt"
    untrusted = tmp_path / "wrong.py"
    untrusted.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    config_a = tmp_path / "trusted.yaml"
    config_b = tmp_path / "other.yaml"
    config_a.write_text("schema_version: 1\n", encoding="utf-8")
    config_b.write_text("schema_version: 1\n", encoding="utf-8")
    argv = ["layout-search", "--snapshot", str(tmp_path / "layout.json"), "--base", str(tmp_path),
            "--expected-revision", revision, "--target", "nmr", "--target", "ftir",
            "--managed", "nmr", str(untrusted), str(config_a), "main",
            "--managed", "ftir", str(tmp_path / "other.py"), str(config_b), "main",
            "--intent", json.dumps({"schema": "figpact.font-search/1", "role": "axis.title",
                                    "candidate_pt": [6, 5]})]
    (tmp_path / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    assert main(argv) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == "figpact.font-search-result/1"
    assert result["status"] == "STALE"
    assert not marker.exists()
