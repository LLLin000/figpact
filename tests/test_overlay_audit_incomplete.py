"""Fail-closed audit-incomplete regression (G22): declared manifest/QA faults.

- Declared ``science_manifest`` callable failure (loader or manifest raises)
  or a declared manifest with missing ``load_science`` refuses with
  AUDIT_INCOMPLETE; nothing is written, no figure opens.
- Absent optional hooks (no ``science_manifest`` at all, or a hook that
  successfully returns ``None`` like the G19 trial wrapper) keep existing
  success semantics.
- ``qa.measure`` raising, or returning a malformed payload without a records
  list, refuses AUDIT_INCOMPLETE with truthful receipts (local ERROR /
  whole ERROR / NOT_WRITTEN) and mutates no official bytes or outputs.
- A successful ``qa.measure`` returning ``records=[]`` stays valid.
"""
import hashlib
import json

import matplotlib
import matplotlib.pyplot as plt
import pytest

from figpact import style_overlay

matplotlib.use("Agg")


WRAPPER = (
    "import matplotlib\nmatplotlib.use(\"Agg\")\n"
    "import matplotlib.pyplot as plt\nfrom figpact import GidRegistry\n"
    'SCOPES = ("main",)\nCONFIG = {}\n{extra}\n'
    "def build_figure_and_registry(scope=\"main\"):\n"
    "    fig, ax = plt.subplots()\n"
    "    ax.plot([0, 1], [0, 1])\n"
    "    {body}\n"
    "    return fig, GidRegistry(scope=scope)\n"
)


def _write(path, body, extra=""):
    path.write_text(
        WRAPPER.replace("{extra}", extra).replace("{body}", body),
        encoding="utf-8",
    )
    return path


def _curve_id(script):
    return next(
        t
        for t in style_overlay.inventory(script, scope="main")
        if t["role"] == "curve.linewidth"
    )["id"]


def _h(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _edits(script):
    return [{"target_id": _curve_id(script), "value": 0.8}]


def _external_open_count():
    return len(plt.get_fignums())


def test_declared_loader_failure_is_audit_incomplete(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    tid = _curve_id(script)
    script.write_text(
        WRAPPER.replace("{extra}", (
            "def load_science():\n"
            "    raise RuntimeError('boom-loader')\n"
            "def science_manifest(science):\n"
            "    return {'nodes': {}}\n"
        )).replace("{body}", 'ax.set_ylabel("dose")'),
        encoding="utf-8",
    )
    overlay = tmp_path / "style.json"
    before_figs = _external_open_count()
    receipt = style_overlay.apply(
        script, scope="main",
        edits=[{"target_id": tid, "value": 0.8}], overlay=overlay
    )
    assert receipt["local_edit_state"] == "ERROR", receipt
    assert receipt["figure_verification_state"] == "ERROR", receipt
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert any("AUDIT_INCOMPLETE" in str(p) for p in receipt["local_problems"]), receipt
    assert not overlay.exists()
    assert _external_open_count() == before_figs


def test_declared_manifest_failure_is_audit_incomplete(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    tid = _curve_id(script)
    script.write_text(
        WRAPPER.replace("{extra}", (
            "def load_science():\n"
            "    return {'x': 1}\n"
            "def science_manifest(science):\n"
            "    raise ValueError('boom-manifest')\n"
        )).replace("{body}", 'ax.set_ylabel("dose")'),
        encoding="utf-8",
    )
    overlay = tmp_path / "style.json"
    receipt = style_overlay.apply(
        script, scope="main",
        edits=[{"target_id": tid, "value": 0.8}], overlay=overlay
    )
    assert receipt["local_edit_state"] == "ERROR", receipt
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert any("AUDIT_INCOMPLETE" in str(p) for p in receipt["local_problems"]), receipt
    assert not overlay.exists()


def test_declared_manifest_without_loader_is_audit_incomplete(tmp_path):
    script = _write(
        tmp_path / "w.py",
        'ax.set_ylabel("dose")',
        extra=(
            "def science_manifest(science):\n"
            "    return {'nodes': {}}\n"
        ),
    )
    overlay = tmp_path / "style.json"
    receipt = style_overlay.apply(
        script, scope="main", edits=_edits(script), overlay=overlay
    )
    assert receipt["local_edit_state"] == "ERROR", receipt
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert any("AUDIT_INCOMPLETE" in str(p) for p in receipt["local_problems"]), receipt
    assert not overlay.exists()


def test_optional_hooks_absent_still_succeeds(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    receipt = style_overlay.apply(
        script, scope="main", edits=_edits(script), overlay=overlay
    )
    assert receipt["source_commit_state"] == "COMMITTED", receipt
    assert receipt["figure_verification_state"] == "PASS", receipt
    assert overlay.exists()
    fig, _, loaded = style_overlay.load(overlay)
    try:
        assert fig is not None
        assert loaded["figure_verification_state"] == "PASS", loaded
    finally:
        plt.close(fig)


def test_manifest_returning_none_stays_success(tmp_path):
    script = _write(
        tmp_path / "w.py",
        'ax.set_ylabel("dose")',
        extra=(
            "def load_science():\n"
            "    return {'csv': 'data.csv'}\n"
            "def science_manifest(_science):\n"
            "    return None\n"
        ),
    )
    overlay = tmp_path / "style.json"
    receipt = style_overlay.apply(
        script, scope="main", edits=_edits(script), overlay=overlay
    )
    assert receipt["source_commit_state"] == "COMMITTED", receipt
    assert overlay.exists()


def test_qa_measure_exception_is_audit_incomplete(tmp_path, monkeypatch):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    import figpact.qa as qa_mod

    def _boom(fig, **kw):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(qa_mod, "measure", _boom)
    source = script.read_bytes()
    receipt = style_overlay.apply(
        script, scope="main", edits=_edits(script), overlay=overlay
    )
    assert receipt["local_edit_state"] == "ERROR", receipt
    assert receipt["figure_verification_state"] == "ERROR", receipt
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert any("AUDIT_INCOMPLETE" in str(p) for p in receipt["local_problems"]), receipt
    assert "qa_delta" in receipt and receipt["qa_delta"]["eligible"] is False
    assert not overlay.exists()
    assert script.read_bytes() == source


def test_qa_measure_malformed_is_audit_incomplete(tmp_path, monkeypatch):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    import figpact.qa as qa_mod

    monkeypatch.setattr(qa_mod, "measure", lambda fig, **kw: {"problems": []})
    receipt = style_overlay.apply(
        script, scope="main", edits=_edits(script), overlay=overlay
    )
    assert receipt["local_edit_state"] == "ERROR", receipt
    assert receipt["source_commit_state"] == "NOT_WRITTEN", receipt
    assert any("AUDIT_INCOMPLETE" in str(p) for p in receipt["local_problems"]), receipt
    assert not overlay.exists()


def test_qa_measure_empty_records_valid(tmp_path, monkeypatch):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    import figpact.qa as qa_mod

    real = qa_mod.measure
    monkeypatch.setattr(
        qa_mod, "measure", lambda fig, **kw: {**real(fig, **kw), "records": []}
    )
    receipt = style_overlay.apply(
        script,
        scope="main",
        edits=_edits(script),
        overlay=overlay,
        allow_draft=True,
    )
    assert receipt["local_edit_state"] == "PASS", receipt
    assert receipt["source_commit_state"] == "COMMITTED", receipt
    assert receipt["figure_verification_state"] == "PASS", receipt
    assert overlay.exists()


def test_manifest_fault_on_second_pair_leaves_first_bytes(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    first = style_overlay.apply(
        script, scope="main", edits=_edits(script), overlay=overlay
    )
    assert first["source_commit_state"] == "COMMITTED", first
    saved = overlay.read_bytes()
    import figpact.style_overlay as ov
    import unittest.mock as mock

    def _late_boom(module):
        raise ov._VerifyFail(["AUDIT_INCOMPLETE: load_science failed (late-boom)"])

    with mock.patch.object(ov, "_manifest_of", side_effect=_late_boom):
        fig, _, receipt = style_overlay.load(overlay)
    assert fig is None
    assert receipt["local_edit_state"] == "ERROR", receipt
    assert any("AUDIT_INCOMPLETE" in str(p) for p in receipt["local_problems"]), receipt
    assert overlay.read_bytes() == saved


def test_manifest_fault_on_render_reopen_refuses_output(tmp_path):
    script = _write(
        tmp_path / "w.py",
        'ax.set_ylabel("dose")',
        extra=(
            "def load_science():\n"
            "    return {'x': 1}\n"
            "def science_manifest(science):\n"
            "    return {'nodes': {}}\n"
        ),
    )
    overlay = tmp_path / "style.json"
    first = style_overlay.apply(
        script, scope="main", edits=_edits(script), overlay=overlay
    )
    assert first["source_commit_state"] == "COMMITTED", first
    import figpact.style_overlay as ov
    import unittest.mock as mock

    def _late_boom(module):
        raise ov._VerifyFail(["AUDIT_INCOMPLETE: science_manifest failed (late)"])

    out = tmp_path / "out.png"
    with mock.patch.object(ov, "_manifest_of", side_effect=_late_boom):
        rendered = style_overlay.render(overlay, out)
    assert rendered["figure_verification_state"] in ("ERROR", "FAIL"), rendered
    assert rendered["local_edit_state"] == "ERROR", rendered
    assert not out.exists()
    assert overlay.read_bytes()


def test_empty_clear_manifest_fault_refuses(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    tid = _curve_id(script)
    first = style_overlay.apply(
        script, scope="main", edits=[{"target_id": tid, "value": 0.8}],
        overlay=overlay,
    )
    assert first["source_commit_state"] == "COMMITTED", first
    saved = overlay.read_bytes()
    import figpact.style_overlay as ov

    real_manifest = ov._manifest_of

    def _flaky_manifest(module):
        raise ov._VerifyFail(["AUDIT_INCOMPLETE: science_manifest failed (clear)"])

    import unittest.mock as mock

    with mock.patch.object(ov, "_manifest_of", side_effect=_flaky_manifest):
        cleared = style_overlay.apply(
            script,
            scope="main",
            edits=[],
            overlay=overlay,
            expected_before_sha256=_h(overlay),
            remove=[tid],
        )
    assert cleared["local_edit_state"] == "ERROR", cleared
    assert cleared["source_commit_state"] == "NOT_WRITTEN", cleared
    assert overlay.read_bytes() == saved


def test_empty_overlay_load_manifest_fault_refuses(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    tid = _curve_id(script)
    first = style_overlay.apply(
        script, scope="main", edits=[{"target_id": tid, "value": 0.8}],
        overlay=overlay,
    )
    assert first["source_commit_state"] == "COMMITTED", first
    cleared = style_overlay.apply(
        script,
        scope="main",
        edits=[],
        overlay=overlay,
        expected_before_sha256=_h(overlay),
        remove=[tid],
    )
    assert json.loads(overlay.read_text(encoding="utf-8"))["targets"] == []
    saved = overlay.read_bytes()
    import figpact.style_overlay as ov
    import unittest.mock as mock

    def _flaky_manifest(module):
        raise ov._VerifyFail(["AUDIT_INCOMPLETE: science_manifest failed (reload)"])

    with mock.patch.object(ov, "_manifest_of", side_effect=_flaky_manifest):
        fig, _, receipt = style_overlay.load(overlay)
    assert fig is None
    assert receipt["local_edit_state"] == "ERROR", receipt
    assert overlay.read_bytes() == saved


def test_external_figure_preserved_on_audit_fault(tmp_path, monkeypatch):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "style.json"
    keeper, _ = plt.subplots()
    n_before = len(plt.get_fignums())
    import figpact.qa as qa_mod

    def _boom(fig, **kw):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(qa_mod, "measure", _boom)
    try:
        receipt = style_overlay.apply(
            script, scope="main", edits=_edits(script), overlay=overlay
        )
        assert receipt["local_edit_state"] == "ERROR", receipt
        assert keeper.number in plt.get_fignums()
        assert len(plt.get_fignums()) == n_before
    finally:
        plt.close(keeper)
    plt.close("all")
