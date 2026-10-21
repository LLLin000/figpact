"""Worker-owned frames: real NMR/FTIR worker capture + export invariants.

Consumer-visible only: frame identity (candidate_revision/source/base),
same-capture PNG+Scene, absolute science/QA evidence, immutable export
provenance, stale rejection, and hash-coherent frame caching.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg", force=True)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.native_parameters import NativeParameterSession  # noqa: E402
from figpact.runtime import FigureWorker  # noqa: E402

NMR_SCRIPT = ROOT / "examples" / "nmr" / "08 NMR.py"
NMR_YAML = ROOT / "examples" / "nmr" / "nmr.yaml"
FTIR_SCRIPT = ROOT / "examples" / "ftir" / "plot_ftir.py"
FTIR_YAML = ROOT / "examples" / "ftir" / "ftir.yaml"
FTIR_SCOPE = "annotated"
PEAK = json.dumps(["peak_font_pt"])
CANW = json.dumps(["canvas_w_mm"])
CANH = json.dumps(["canvas_h_mm"])


def _copy(src: Path, tmp_path: Path, name: str) -> Path:
    dst = tmp_path / name
    shutil.copyfile(src, dst)
    return dst


def _check_frame(frame: dict, worker_state: dict) -> dict:
    scene = json.loads(frame["scene_json"])
    png = base64.b64decode(frame["png_base64"])
    assert png[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10])
    assert hashlib.sha256(png).hexdigest() == frame["png_sha256"]
    assert hashlib.sha256(frame["scene_json"].encode()).hexdigest() == frame["scene_sha256"]
    assert hashlib.sha256(
        f"{frame['png_sha256']}\n{frame['scene_sha256']}".encode()
    ).hexdigest() == frame["frame_revision"]
    assert frame["frame_revision"] == frame["image_revision"] == frame["geometry_revision"]
    assert frame["candidate_revision"] == worker_state["revision"] == frame["revision"]
    assert frame["source_revision"] == worker_state["source_revision"]
    assert frame["base_config_revision"] == worker_state["base_config_revision"]
    assert isinstance(frame["science"], dict) and isinstance(frame["science"].get("digest"), str)
    assert isinstance(frame["qa"], list) and isinstance(frame["qa_kind"], str)
    assert frame["evidence"]["host"] == "NOT_CONNECTED"
    assert frame["evidence"]["export_page"] == "NOT_RUN"
    assert scene["source_revision"] == worker_state["source_revision"]
    # Verbatim visibility: every Inspector node carries the raw Scene fact
    # (never a measured proxy); absent visibility is fail-closed downstream.
    for node in scene.get("nodes", []):
        assert "visible" in node
    return scene


def test_renderer_fingerprint_changes_with_actual_renderer_dpi(tmp_path):
    """Durable renderer identity: same candidate at a different real DPI
    yields a differing renderer digest (no version-field echo asserted)."""
    import matplotlib

    from figpact.inspector import _renderer_fingerprint

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(dpi=100)
    try:
        canvas = fig.canvas
        canvas.draw()
        small = _renderer_fingerprint(
            canvas.get_renderer(), canvas, 100, *canvas.get_width_height())
    finally:
        plt.close(fig)
    fig, ax = plt.subplots(dpi=200)
    try:
        canvas = fig.canvas
        canvas.draw()
        large = _renderer_fingerprint(
            canvas.get_renderer(), canvas, 200, *canvas.get_width_height())
    finally:
        plt.close(fig)
    assert small["digest"] != large["digest"]
    assert small["dpi"] != large["dpi"]


def _worker(script: Path, cfg: Path, scope: str) -> FigureWorker:
    worker = FigureWorker(str(script), str(cfg), scope)
    worker.open()
    return worker


def test_nmr_worker_capture_matches_exact_candidate(tmp_path):
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    worker = _worker(NMR_SCRIPT, cfg, "main")
    try:
        state = worker.state()
        frame = worker.capture_frame()
        _check_frame(frame, state)
        frame_again = worker.capture_frame()
        # Worker holds the exact candidate figure: repeated capture on the
        # unchanged figure is the same frame (hash-coherent, no silent rebuild).
        assert frame_again["frame_revision"] == frame["frame_revision"]
        assert frame_again["png_sha256"] == frame["png_sha256"]
        assert frame_again["scene_sha256"] == frame["scene_sha256"]
        assert frame_again["science"] == frame["science"]
        # Positive NMR edit: declared scientific-preserving resize+font combo.
        trial = worker.try_layout(
            [{"operation": "set_parameter", "path": ["peak_font_pt"], "value": 7.2},
             {"operation": "set_parameter", "path": ["legend_font_pt"], "value": 7.2},
             {"operation": "set_parameter", "path": ["canvas_w_mm"], "value": 68.0}],
            revision=state["revision"])
        assert trial["status"] == "OK", trial
        state2 = worker.state()
        frame2 = worker.capture_frame()
        _check_frame(frame2, state2)
        assert frame2["candidate_revision"] == state2["revision"] != state["revision"]
        assert frame2["frame_revision"] != frame["frame_revision"]
        # Honest rejection regression: peak-only resize is refused as a science
        # violation on this figure (never weakened to pass).
        worker.try_layout([{"operation": "reset"}], revision=state2["revision"])
        live = worker.state()
        refused = worker.try_layout(
            [{"operation": "set_parameter", "path": ["peak_font_pt"], "value": 7.2}],
            revision=live["revision"])
        assert refused["status"] == "SCIENCE_VIOLATION"
        assert worker.state()["revision"] == live["revision"]
        worker.try_layout([{"operation": "reset"}], revision=live["revision"])
    finally:
        worker.close()


def test_capture_refuses_post_qa_geometry_drift_without_science_change(tmp_path):
    """Post-QA draw drift must refuse, not publish a stale frame.

    Real NMR FigureSession with a QA hook that actually repositions a live
    Text artist (display geometry only: same string, same axes view, so the
    science digest is unchanged). capture_frame must refuse via the
    same-Figure recapture hash check and publish no frame; restoring the
    hook yields a valid frame again.
    """
    from figpact.session import FigureSession, StaleRevision

    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    session = FigureSession(str(NMR_SCRIPT), str(cfg), "main")
    try:
        mod = session._module
        original = getattr(mod, "preview_qa", None)

        def drifting_qa(fig, scope):
            target = None
            for ax in fig.axes:
                if ax.texts:
                    target = ax.texts[0]
                    break
            if target is None:  # pragma: no cover - NMR always has peak labels
                raise AssertionError("no live Text artist to reposition")
            x, y = target.get_position()
            target.set_position((x + 2.0, y + 2.0))
            fig.canvas.draw()
            return []

        mod.preview_qa = drifting_qa
        try:
            with pytest.raises(StaleRevision):
                session.capture_frame()
            assert session._frame_cache is None
        finally:
            if original is None:
                try:
                    delattr(mod, "preview_qa")
                except AttributeError:
                    pass
            else:
                mod.preview_qa = original
        frame = session.capture_frame()
        _check_frame(frame, session.state())
    finally:
        session.close()


def test_ftir_worker_capture_absolute_qa(tmp_path):
    cfg = _copy(FTIR_YAML, tmp_path, "ftir.yaml")
    worker = _worker(FTIR_SCRIPT, cfg, FTIR_SCOPE)
    try:
        state = worker.state()
        frame = worker.capture_frame()
        scene = _check_frame(frame, state)
        assert scene["scope"] == FTIR_SCOPE
        assert frame["scope"] == FTIR_SCOPE
        assert isinstance(frame["qa"], list)
        # canvas_w_mm 68 honestly refuses on this figure (QA_BLOCKED: new
        # COO/C=C vs COO 9px overlap); refusal yields no accepted frame.
        trial = worker.try_layout(
            [{"operation": "set_parameter", "path": ["canvas_w_mm"], "value": 68.0}],
            revision=state["revision"])
        assert trial["status"] == "QA_BLOCKED", trial
        assert worker.state()["revision"] == state["revision"]
        assert worker.capture_frame()["frame_revision"] == frame["frame_revision"]
    finally:
        worker.close()


def test_export_exact_frame_immutable_and_no_source_mutation(tmp_path):
    try:
        from pypdf import PdfReader  # noqa: F401
    except ImportError:
        pytest.skip("PDF measurement needs optional pypdf")
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    before = cfg.read_bytes()
    worker = _worker(NMR_SCRIPT, cfg, "main")
    try:
        state = worker.state()
        trial = worker.try_layout(
            [{"operation": "set_parameter", "path": ["canvas_w_mm"], "value": 68.0}],
            revision=state["revision"])
        assert trial["status"] == "OK"
        live = worker.state()
        frame = worker.capture_frame()
        out = tmp_path / "exports"
        out.mkdir()
        bundle = worker.export_frame(
            str(out), revision=live["revision"],
            frame_revision=frame["frame_revision"])
        assert bundle["candidate_revision"] == live["revision"]
        assert bundle["frame_revision"] == frame["frame_revision"]
        assert bundle["png_sha256"] == frame["png_sha256"]
        assert Path(bundle["png_path"]).read_bytes() == base64.b64decode(frame["png_base64"])
        assert Path(bundle["pdf_path"]).stat().st_size > 0
        assert len(bundle["page_mm"]) == 2 and all(v > 0 for v in bundle["page_mm"])
        assert bundle["evidence"]["host"] == "NOT_CONNECTED"
        assert bundle["evidence"]["export_page"] == "NOT_RUN"
        assert cfg.read_bytes() == before
        # Immutable: second export of the same frame refuses to overwrite.
        with pytest.raises(Exception):
            worker.export_frame(
                str(out), revision=live["revision"],
                frame_revision=frame["frame_revision"])
        assert cfg.read_bytes() == before
        worker.try_layout([{"operation": "reset"}], revision=live["revision"])
    finally:
        worker.close()


def test_stale_export_rejected(tmp_path):
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    out = tmp_path / "exports"
    out.mkdir()
    worker = _worker(NMR_SCRIPT, cfg, "main")
    try:
        state = worker.state()
        frame = worker.capture_frame()
        trial = worker.try_layout(
            [{"operation": "set_parameter", "path": ["peak_font_pt"], "value": 7.2},
             {"operation": "set_parameter", "path": ["legend_font_pt"], "value": 7.2},
             {"operation": "set_parameter", "path": ["canvas_w_mm"], "value": 68.0}],
            revision=state["revision"])
        assert trial["status"] == "OK", trial
        with pytest.raises(Exception):
            worker.export_frame(
                str(out), revision=state["revision"],
                frame_revision=frame["frame_revision"])
        assert list(out.iterdir()) == []
        live = worker.state()
        with pytest.raises(Exception):
            worker.export_frame(
                str(out), revision=live["revision"],
                frame_revision="0" * 64)
        assert list(out.iterdir()) == []
        worker.try_layout([{"operation": "reset"}], revision=live["revision"])
    finally:
        worker.close()


def test_native_session_frame_matches_worker_render_authority(tmp_path):
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    handle = NativeParameterSession(str(NMR_SCRIPT), str(cfg), "main")
    try:
        snap = handle.snapshot()
        state = handle._agent._call(handle._agent._worker.state)
        assert snap["candidate_revision"] == state["revision"]
        assert snap["source_revision"] == state["source_revision"]
        assert snap["base_config_revision"] == state["base_config_revision"]
        assert snap["session"]["scene_revision"] == snap["frame_revision"]
        assert snap["session"]["source_revision"] == state["source_revision"]
        assert snap["session"]["can_evaluate"] is False
        # Render authority: the Native frame is the worker's exact captured
        # figure (same PNG bytes, same Scene bytes, same revision chain).
        direct = handle._agent._call(handle._agent._worker.capture_frame)
        assert snap["frame_revision"] == direct["frame_revision"]
        assert snap["png_sha256"] == direct["png_sha256"]
        assert snap["scene_sha256"] == direct["scene_sha256"]
        assert snap["science"]["digest"] == direct["science"]["digest"]
        # Positive NMR edit through Native preview (declared canvas resize).
        out, code = handle.preview(
            {"frame_revision": snap["frame_revision"],
             "edits": [{"control_id": CANW, "value": 68.0}]})
        assert code == 200 and out["status"] == "OK", out
        assert out["frame"]["candidate_revision"] == out["native"]["revision"]
        assert out["frame"]["frame_revision"] != snap["frame_revision"]
    finally:
        handle.close()


def test_worker_frame_validates_against_public_wire_json_schema(tmp_path):
    """Real worker frame must validate against the public wire JSON schema.

    Catches schema/frame drift (e.g. a missing ``scope`` property making
    every frame invalid). Uses the actual captured frame output, not
    property-list assertions or mock echoes.
    """
    jsonschema = pytest.importorskip("jsonschema")

    schema = json.loads(
        (ROOT / "docs" / "schema" / "render.schema.json").read_text(
            encoding="utf-8"))
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    worker = _worker(NMR_SCRIPT, cfg, "main")
    try:
        frame = worker.capture_frame()
    finally:
        worker.close()
    validator = jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/FigureFrame", "$defs": schema["$defs"]})
    validator.validate(frame)

def test_nmr_canvas_authorized_both_axes(tmp_path):
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    handle = NativeParameterSession(str(NMR_SCRIPT), str(cfg), "main")
    try:
        ids = {c["control_id"] for c in handle.snapshot()["native"]["controls"]}
        assert CANW in ids and CANH in ids
    finally:
        handle.close()
