"""NativeParameterSession focused tests: real session, real YAML copies.

No clinical source is ever modified: every test copies ``nmr.yaml`` into a
tmp dir first. No mocks in product paths; the session runs the real
``AgentSession`` worker. Frame assertions run the actual existing JS
verifier (validateFrame/verifyFrame from figpact/_inspector/inspector.js)
via node --test, not re-implemented checks.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg", force=True)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.native_parameters import NativeParameterSession  # noqa: E402

SCRIPT = ROOT / "examples" / "nmr" / "08 NMR.py"
BASE_YAML = ROOT / "examples" / "nmr" / "nmr.yaml"
HELPER = ROOT / "figpact" / "_inspector" / "inspector.js"
PEAK = json.dumps(["peak_font_pt"])
LEG = json.dumps(["legend_font_pt"])
CAN = json.dumps(["canvas_w_mm"])
FULL_COMBO = [{"control_id": PEAK, "value": 7.2},
              {"control_id": LEG, "value": 7.2},
              {"control_id": CAN, "value": 68.0}]


@pytest.fixture()
def session(tmp_path):
    cfg = tmp_path / "nmr.yaml"
    shutil.copyfile(BASE_YAML, cfg)
    handle = NativeParameterSession(str(SCRIPT), str(cfg), "main")
    yield handle, cfg
    handle.close()


def verify_frame(frame: dict) -> None:
    """Run the actual existing JS verifier on one real frame.

    verifyFrame checks: schema, hex digests, revision chain
    sha256(png_sha256 + scene_sha256) == frame_revision, PNG magic +
    IHDR dimensions == scene.image, and both digests match the bytes.
    Anything fabricated fails here.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tmp:
        json.dump(frame, tmp)
        name = tmp.name
    script = (
        "const fs=require('node:fs');\n"
        "const m=require(process.argv[1]);\n"
        "(async()=>{\n"
        f" const frame=JSON.parse(fs.readFileSync({name!r},'utf8'));\n"
        " const scene=await m.verifyFrame(frame);\n"
        " if(!scene||!Array.isArray(scene.nodes)) throw new Error('no scene');\n"
        " console.log('VERIFY_OK nodes='+scene.nodes.length);\n"
        "})().catch(e=>{console.error('VERIFY_FAIL '+e.message);process.exit(1);});\n"
    )
    try:
        res = subprocess.run(["node", "-e", script, str(HELPER)],
                             capture_output=True, text=True, timeout=120)
    finally:
        Path(name).unlink(missing_ok=True)
    assert res.returncode == 0, f"JS verifyFrame failed: {res.stderr.strip()}"


def check_invariants(frame: dict) -> dict:
    scene = json.loads(frame["scene_json"])
    png = base64.b64decode(frame["png_base64"])
    assert png[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10])
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert (width, height) == (scene["image"]["width_px"], scene["image"]["height_px"])
    assert hashlib.sha256(png).hexdigest() == frame["png_sha256"]
    assert hashlib.sha256(frame["scene_json"].encode()).hexdigest() == frame["scene_sha256"]
    assert hashlib.sha256(f"{frame['png_sha256']}\n{frame['scene_sha256']}".encode()).hexdigest() == frame["frame_revision"]
    assert frame["frame_revision"] == frame["image_revision"] == frame["geometry_revision"]
    assert frame["session"]["scene_revision"] == frame["frame_revision"]
    assert frame["session"]["source_revision"] == scene["source_revision"]
    assert frame["session"]["can_evaluate"] is False
    assert isinstance(frame["session"]["session_id"], str) and frame["session"]["session_id"]
    return scene


def test_exposes_authorized_scalar_controls(session):
    handle, _ = session
    snap = handle.snapshot()
    ids = {c["control_id"] for c in snap["native"]["controls"]}
    assert PEAK in ids and CAN in ids
    verify_frame(snap)


def test_preview_frame_passes_real_verifier(session):
    handle, cfg = session
    before = cfg.read_bytes()
    out, code = handle.preview(
        {"frame_revision": handle.snapshot()["frame_revision"],
         "edits": FULL_COMBO})
    assert code == 200 and out["status"] == "OK"
    assert cfg.read_bytes() == before  # preview writes nothing
    check_invariants(out["frame"])
    verify_frame(out["frame"])
    assert out["native"]["pending"]["candidate_id"]
    # snapshot() after preview exposes the SAME server-bound pending
    snap = handle.snapshot()
    assert snap["native"]["pending"]["candidate_id"] == \
        out["native"]["pending"]["candidate_id"]
    assert snap["frame_revision"] == out["frame"]["frame_revision"]


def test_rejects_locked_source_change(session):
    handle, _ = session
    out, code = handle.preview(
        {"frame_revision": handle.snapshot()["frame_revision"],
         "edits": [{"control_id": json.dumps(["show_ppm"]), "value": 1.0}]})
    assert code == 400 and out["status"] == "UNKNOWN_ID"


def test_rejects_out_of_range(session):
    handle, _ = session
    out, code = handle.preview(
        {"frame_revision": handle.snapshot()["frame_revision"],
         "edits": [{"control_id": PEAK, "value": 99.0}]})
    assert code == 400 and out["status"] == "OUT_OF_RANGE"


def test_stale_frame_rejected(session):
    handle, _ = session
    out, code = handle.preview(
        {"frame_revision": "deadbeef",
         "edits": [{"control_id": PEAK, "value": 7.0}]})
    assert code == 409 and out["status"] == "STALE_REVISION"


def test_preview_snapshot_cancel_restores_original(session):
    handle, cfg = session
    before = cfg.read_bytes()
    base = {c["control_id"]: c["current"]
            for c in handle.snapshot()["native"]["controls"]}
    assert base[PEAK] == 6.0 and base[CAN] == 48.0
    out, code = handle.preview(
        {"frame_revision": handle.snapshot()["frame_revision"],
         "edits": FULL_COMBO})
    assert code == 200
    pending_id = out["native"]["pending"]["candidate_id"]
    snap = handle.snapshot()
    assert snap["native"]["pending"]["candidate_id"] == pending_id
    result, cancel_code = handle.cancel({"candidate_id": pending_id})
    assert cancel_code == 200 and result["status"] == "OK"
    assert cfg.read_bytes() == before  # files untouched
    after = handle.snapshot()
    assert after["native"]["pending"] is None
    restored = {c["control_id"]: c["current"]
                for c in after["native"]["controls"]}
    assert restored[PEAK] == 6.0 and restored[CAN] == 48.0
    verify_frame(after)


def test_commit_persists_receipt_and_reopens(session):
    handle, cfg = session
    out, code = handle.preview(
        {"frame_revision": handle.snapshot()["frame_revision"],
         "edits": FULL_COMBO})
    assert code == 200
    pending = out["native"]["pending"]
    record, commit_code = handle.commit(
        {"candidate_id": pending["candidate_id"],
         # UI commits the displayed accepted base frame, not the candidate
         # digest (loadFrame keeps showing the accepted frame until save).
         "frame_revision": pending["base_frame_revision"],
         "kind": "publication"})
    assert commit_code == 200 and record["status"] == "committed"
    # Only the actual receipt evidence may claim Strict PASS (no fallback).
    assert record["verification"] == "STRICT_VERIFIED"
    assert (record["receipt"] or {}).get("verification") == "STRICT_VERIFIED"
    text = cfg.read_text(encoding="utf-8")
    assert "peak_font_pt: 7.2" in text and "canvas_w_mm: 68.0" in text
    # Last receipt persists on the snapshot so the UI can show the result.
    snap = handle.snapshot()
    assert snap["native"]["pending"] is None
    assert (snap["native"]["receipt"] or {}).get("verification") == "STRICT_VERIFIED"
    verify_frame(snap)
    fresh = NativeParameterSession(str(SCRIPT), str(cfg), "main")
    try:
        current = {c["control_id"]: c["current"]
                   for c in fresh.snapshot()["native"]["controls"]}
        assert current[PEAK] == 7.2 and current[CAN] == 68.0
    finally:
        fresh.close()
