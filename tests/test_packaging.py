import importlib.resources as resources
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import figpact


def test_license_exists_and_is_mit():
    root = Path(__file__).resolve().parents[1]
    lic = root / "LICENSE"
    assert lic.is_file()
    text = lic.read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "2026" in text
    assert "LLLin000" in text


def test_inspector_resources_present_in_package():
    ref = resources.files("figpact").joinpath("_inspector", "index.html")
    assert ref.is_file()
    assert ref.read_bytes().startswith(b"<!DOCTYPE html") or b"html" in ref.read_bytes()[:200].lower()


def test_cli_help_runs():
    res = subprocess.run([sys.executable, "-m", "figpact", "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "ui" in res.stdout


def test_export_inspector_synthetic_figure(tmp_path):
    from figpact.inspector import export_inspector
    fig = plt.figure(figsize=(4, 2))
    out = tmp_path / "inspect"
    page = export_inspector(fig, out)
    assert page.is_file()
    assert (out / "index.html").is_file()
    plt.close(fig)
