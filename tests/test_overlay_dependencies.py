"""Strict overlay dependency behavior (StrictDependencies owner).

Real tmp-file tests, no monkeypatching: helpers raise (never silent
None/[]/``missing``/skip) on declared-but-bad inputs, and apply/load
return structured refusals without writing.
"""
from pathlib import Path
import types

import matplotlib.pyplot as plt
import pytest

from figpact import style_overlay
from figpact.session import SessionError

WRAPPER = """import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from figpact import GidRegistry
SCOPES = ("main",)
CONFIG = {}
{extra}
def build_figure_and_registry(scope="main"):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.set_xlabel("dose")
    ax.set_ylabel("resp")
    return fig, GidRegistry(scope=scope)
"""


def _write_wrapper(path, extra=""):
    path.write_text(WRAPPER.replace("{extra}", extra), encoding="utf-8")
    return path


def _title_edit(script):
    target = next(t for t in style_overlay.inventory(script, scope="main")
                  if t["role"] == "axis.title")
    return [{"target_id": target["id"], "value": 14.0}]


def test_no_deps_apply_and_load_roundtrip(tmp_path):
    script = _write_wrapper(tmp_path / "w.py")
    overlay = tmp_path / "style.json"
    try:
        receipt = style_overlay.apply(script, scope="main", edits=_title_edit(script),
                                      overlay=overlay, allow_draft=True)
        assert receipt["local_edit_state"] == "PASS", receipt
        assert overlay.is_file()
        fig, _, loaded = style_overlay.load(overlay)
        try:
            assert loaded["local_edit_state"] == "PASS", loaded
        finally:
            plt.close(fig)
    finally:
        plt.close("all")


def test_raw_absent_is_legal_none():
    module = types.SimpleNamespace(__file__=str(Path("x.py").resolve()))
    assert style_overlay._raw_path_of(module) is None


def test_missing_raw_refused(tmp_path):
    script = _write_wrapper(tmp_path / "w.py", extra="RAW = 'gone.py'")
    module = types.SimpleNamespace(RAW="gone.py", __file__=str(script))
    with pytest.raises((FileNotFoundError, ValueError), match="REFUSED"):
        style_overlay._raw_path_of(module)
    with pytest.raises((FileNotFoundError, ValueError), match="REFUSED"):
        style_overlay._live_dependencies(module, script, None)
    overlay = tmp_path / "refused.json"
    receipt = style_overlay.apply(script, scope="main", edits=_title_edit(script),
                                  overlay=overlay, allow_draft=True)
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert not overlay.exists()


def test_raw_directory_refused(tmp_path):
    module = types.SimpleNamespace(RAW=str(tmp_path), __file__=str(tmp_path / "w.py"))
    with pytest.raises((FileNotFoundError, ValueError, PermissionError), match="REFUSED"):
        style_overlay._raw_path_of(module)


def test_missing_science_inputs_refused(tmp_path):
    script = _write_wrapper(tmp_path / "w.py", extra="SCIENCE_INPUTS = ['gone.csv']")
    module = types.SimpleNamespace(SCIENCE_INPUTS=["gone.csv"], __file__=str(script))
    with pytest.raises(SessionError):
        style_overlay._science_input_paths(module)
    overlay = tmp_path / "refused.json"
    receipt = style_overlay.apply(script, scope="main", edits=_title_edit(script),
                                  overlay=overlay, allow_draft=True)
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert not overlay.exists()


def test_hook_raises_refused(tmp_path):
    script = _write_wrapper(tmp_path / "w.py",
                            extra="def science_inputs():\n    raise RuntimeError('boom')")
    module = types.SimpleNamespace(__file__=str(script),
                                   science_inputs=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="REFUSED"):
        style_overlay._science_input_paths(module)
    overlay = tmp_path / "refused.json"
    receipt = style_overlay.apply(script, scope="main", edits=_title_edit(script),
                                  overlay=overlay, allow_draft=True)
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert not overlay.exists()


def test_deleted_persisted_dependency_load_errors_no_write(tmp_path):
    raw = tmp_path / "raw.py"
    raw.write_text("x = 1\n", encoding="utf-8")
    data = tmp_path / "data.csv"
    data.write_text("a,b\n1,2\n", encoding="utf-8")
    script = _write_wrapper(tmp_path / "w.py",
                            extra="RAW = 'raw.py'\nSCIENCE_INPUTS = ['data.csv']")
    overlay = tmp_path / "style.json"
    try:
        receipt = style_overlay.apply(script, scope="main", edits=_title_edit(script),
                                      overlay=overlay, allow_draft=True)
        assert receipt["local_edit_state"] == "PASS", receipt
        saved = overlay.read_bytes()
        data.unlink()
        fig, _, loaded = style_overlay.load(overlay)
        assert fig is None
        assert loaded["local_edit_state"] == "ERROR", loaded
        assert overlay.read_bytes() == saved
    finally:
        plt.close("all")
