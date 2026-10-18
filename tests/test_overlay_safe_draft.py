"""Safe-draft workspace gating (Core owner): real-figure draft tests.

Covers: old-defect unchanged draft accepted + reopen/edit, new/worse floor
rejected, new overlap rejected, source drift refused, strict load/render
refuse fig on drafts, empty clear path. Runner/parent owns execution.
"""
import hashlib

import matplotlib
import pytest

from figpact import style_overlay


def _h(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    path.write_text(WRAPPER.replace("{extra}", extra).replace("{body}", body),
                    encoding="utf-8")
    return path


def _title_id(script):
    return next(t for t in style_overlay.inventory(script, scope="main")
                if t["role"] == "axis.title")["id"]


def _curve_id(script):
    return next(t for t in style_overlay.inventory(script, scope="main")
                if t["role"] == "curve.linewidth")["id"]


def test_old_defect_unchanged_draft_accepted_and_reopens(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose", fontsize=4)')
    overlay = tmp_path / "style.json"
    tid = _curve_id(script)
    r = style_overlay.apply(script, scope="main",
                            edits=[{"target_id": tid, "value": 0.8}],
                            overlay=overlay, allow_draft=True)
    assert r["local_edit_state"] == "PASS", r
    assert r["source_commit_state"] == "COMMITTED_DRAFT", r
    assert r["figure_verification_state"] == "FAIL", r
    assert r["qa_delta"]["eligible"] is True, r["qa_delta"]
    assert r["qa_delta"]["inherited"], r["qa_delta"]
    saved = overlay.read_bytes()
    fig, _, loaded = style_overlay.load_workspace(overlay)
    try:
        assert fig is not None
        assert loaded["figure_verification_state"] == "FAIL", loaded
        assert loaded["local_edit_state"] == "PASS", loaded
        assert loaded["qa_delta"]["eligible"] is True, loaded["qa_delta"]
    finally:
        import matplotlib.pyplot as _plt
        try:
            _plt.close(fig)
        except Exception:
            pass
    strict_fig, _, strict_loaded = style_overlay.load(overlay)
    assert strict_fig is None
    assert strict_loaded["figure_verification_state"] == "FAIL", strict_loaded
    # reopen + edit curing the baseline defect: whole figure PASSES -> COMMITTED clean
    tid2 = _title_id(script)
    r2 = style_overlay.apply(script, scope="main",
                             edits=[{"target_id": tid2, "value": 9.0}],
                             overlay=overlay,
                             expected_before_sha256=_h(overlay),
                             allow_draft=True)
    assert r2["source_commit_state"] == "COMMITTED", r2
    assert r2["figure_verification_state"] == "PASS", r2
    assert overlay.read_bytes() != saved
    ws2, _, wsloaded2 = style_overlay.load_workspace(overlay)
    try:
        assert ws2 is not None
        assert wsloaded2["figure_verification_state"] == "PASS", wsloaded2
    finally:
        import matplotlib.pyplot as _plt2
        try:
            _plt2.close(ws2)
        except Exception:
            pass
    fig2, _, loaded2 = style_overlay.load(overlay)
    try:
        assert fig2 is not None
        assert loaded2["figure_verification_state"] == "PASS", loaded2
    finally:
        import matplotlib.pyplot as _plt3
        try:
            _plt3.close(fig2)
        except Exception:
            pass


def test_worse_floor_rejected(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose", fontsize=4.7)')
    overlay = tmp_path / "worsened.json"
    tid = _title_id(script)
    r = style_overlay.apply(script, scope="main",
                            edits=[{"target_id": tid, "value": 3.7}],
                            overlay=overlay, allow_draft=True)
    assert r["source_commit_state"] == "NOT_WRITTEN", r
    assert r["figure_verification_state"] == "FAIL", r
    assert r["qa_delta"]["eligible"] is False, r["qa_delta"]
    assert r["qa_delta"]["worsened"], r["qa_delta"]
    assert not overlay.exists()


def test_new_floor_rejected(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "new.json"
    tid = _title_id(script)
    r = style_overlay.apply(script, scope="main",
                            edits=[{"target_id": tid, "value": 4.0}],
                            overlay=overlay, allow_draft=True)
    assert r["source_commit_state"] == "NOT_WRITTEN", r
    assert r["qa_delta"]["eligible"] is False, r["qa_delta"]
    assert r["qa_delta"]["new"], r["qa_delta"]
    assert not overlay.exists()


def test_new_overlap_rejected_via_records(tmp_path):
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from figpact import qa as qa_mod
    fig, _ax = plt.subplots()
    try:
        base = qa_mod.measure(fig)["records"]
        fig.text(0.5, 0.5, "alpha overlap probe")
        fig.text(0.5, 0.5, "beta overlap probe")
        cand = qa_mod.measure(fig)["records"]
    finally:
        plt.close(fig)
    delta = style_overlay._delta_of({"records": base}, {"records": cand})
    assert delta["eligible"] is False, delta
    assert delta["new"], delta


def test_allow_draft_must_be_bool(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose")')
    overlay = tmp_path / "bool.json"
    tid = _curve_id(script)
    r = style_overlay.apply(script, scope="main",
                            edits=[{"target_id": tid, "value": 0.8}],
                            overlay=overlay, allow_draft="yes")
    assert r["local_edit_state"] == "ERROR", r
    assert r["source_commit_state"] == "NOT_WRITTEN", r
    assert not overlay.exists()


def test_source_drift_refused_and_bytes_preserved(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose", fontsize=4)')
    overlay = tmp_path / "style.json"
    tid = _curve_id(script)
    r = style_overlay.apply(script, scope="main",
                            edits=[{"target_id": tid, "value": 0.8}],
                            overlay=overlay, allow_draft=True)
    assert r["source_commit_state"] == "COMMITTED_DRAFT", r
    saved = overlay.read_bytes()
    with script.open("a", encoding="utf-8") as handle:
        handle.write("\n# drift marker\n")
    fig, _, loaded = style_overlay.load_workspace(overlay)
    assert fig is None
    assert loaded["local_edit_state"] == "ERROR", loaded
    assert overlay.read_bytes() == saved


def test_strict_render_never_renders_draft(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose", fontsize=4)')
    overlay = tmp_path / "style.json"
    tid = _curve_id(script)
    r = style_overlay.apply(script, scope="main",
                            edits=[{"target_id": tid, "value": 0.8}],
                            overlay=overlay, allow_draft=True)
    assert r["source_commit_state"] == "COMMITTED_DRAFT", r
    out = tmp_path / "out.png"
    rendered = style_overlay.render(overlay, out)
    assert rendered["figure_verification_state"] == "FAIL", rendered
    assert rendered["source_commit_state"] == "NOT_WRITTEN", rendered
    assert not out.exists()
    assert overlay.read_bytes()


def test_empty_clear_path_draft(tmp_path):
    script = _write(tmp_path / "w.py", 'ax.set_ylabel("dose", fontsize=4)')
    overlay = tmp_path / "style.json"
    tid = _curve_id(script)
    first = style_overlay.apply(script, scope="main",
                                edits=[{"target_id": tid, "value": 0.8}],
                                overlay=overlay, allow_draft=True)
    assert first["source_commit_state"] == "COMMITTED_DRAFT", first
    cleared = style_overlay.apply(script, scope="main", edits=[],
                                  overlay=overlay,
                                  expected_before_sha256=_h(overlay),
                                  remove=[tid], allow_draft=True)
    assert cleared["source_commit_state"] == "COMMITTED_DRAFT", cleared
    assert cleared["audit_summary"].get("cleared") is True, cleared
    import json
    assert json.loads(overlay.read_text(encoding="utf-8"))["targets"] == []
    fig, _, loaded = style_overlay.load(overlay)
    assert fig is None
    assert loaded["figure_verification_state"] == "FAIL", loaded
def test_live_dependency_set_mismatch_refused_without_build(tmp_path):
    """Live-only drift (pre-paths match, module declares extra file): no build.

    Strict and workspace loads must both refuse without executing the
    drifted source (marker file never created).
    """
    script = tmp_path / "w.py"
    script.write_text(
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\nfrom figpact import GidRegistry\n"
        "SCOPES = ('main',)\nCONFIG = {}\n"
        "def build_figure_and_registry(scope='main'):\n"
        "    fig, ax = plt.subplots()\n"
        "    ax.plot([0, 1], [0, 1])\n"
        "    ax.set_ylabel('dose')\n"
        "    return fig, GidRegistry(scope=scope)\n",
        encoding="utf-8")
    tid = _curve_id(script)
    overlay = tmp_path / "style.json"
    first = style_overlay.apply(script, scope="main",
                                edits=[{"target_id": tid, "value": 0.8}],
                                overlay=overlay)
    assert first["source_commit_state"] == "COMMITTED", first
    saved = overlay.read_bytes()
    marker = tmp_path / "drifted-source-executed"
    assert not marker.exists()
    script.write_text(
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\nfrom figpact import GidRegistry\n"
        "from pathlib import Path\nSCOPES = ('main',)\nCONFIG = {}\n"
        "RAW = str(Path(__file__).resolve().parent / 'extra.dat')\n"
        "def build_figure_and_registry(scope='main'):\n"
        "    Path(str(Path(__file__).resolve().parent / 'drifted-source-executed')).touch()\n"
        "    fig, ax = plt.subplots()\n"
        "    ax.plot([0, 1], [0, 1])\n"
        "    ax.set_ylabel('dose')\n"
        "    return fig, GidRegistry(scope=scope)\n",
        encoding="utf-8")
    (tmp_path / "extra.dat").write_bytes(b"new dependency")
    for opener in (style_overlay.load, style_overlay.load_workspace):
        fig, _, receipt = opener(overlay)
        assert fig is None
        assert receipt["local_edit_state"] == "ERROR", receipt
        assert "DRIFT" in str(receipt.get("drift") or ""), receipt
    assert not marker.exists(), "drifted source ran before live drift gate"
    assert overlay.read_bytes() == saved
