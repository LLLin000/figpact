"""Standalone render JSON-RPC over a real `figpact render-session` process.

Every test here talks to a live CLI subprocess on stdin/stdout and asserts
only what a client sees: JSON-RPC results and error codes, YAML bytes on
disk, exported bundles, process lifetime. No API echo mocks, no source-text
assertions. Large PNG/PDF bytes stay in tmp dirs, never in the repo.
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REQUEST_TIMEOUT = 300

NMR_SCRIPT = ROOT / "examples" / "nmr" / "08 NMR.py"
NMR_YAML = ROOT / "examples" / "nmr" / "nmr.yaml"
FTIR_SCRIPT = ROOT / "examples" / "ftir" / "plot_ftir.py"
FTIR_YAML = ROOT / "examples" / "ftir" / "ftir.yaml"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
#: Minimal passing standalone layout/intent for stock NMR main (canvas-only
#: edit previews OK; peak_font_pt alone is a science violation, not used).
LAYOUT = {
    "schema": "figpact.layout/1",
    "source_mode": "standalone",
    "page_mm": [210.0, 297.0],
    "objects": [{
        "id": "nmr_main",
        "kind": "panel",
        "measurement_status": "measured",
        "rect_mm": [15.0, 20.0, 68.0, 68.0],
        "resource": "nmr_trace",
        "source": {"origin": "standalone_rpc"},
    }],
}
INTENT = {
    "schema": "figpact.intent/1",
    "panel_id": "nmr_main",
    "edits": [
        {"control_id": '["canvas_w_mm"]', "value": 68.0},
        {"control_id": '["canvas_h_mm"]', "value": 68.0},
    ],
    "fit_canvas": True,
    "required_content": ["fig2_nmr.main.peak.vancho.9p83",
                         "fig2_nmr.main.peak.hama.6p18"],
    "preserve": ["science", "view"],
}


class RenderAgent:
    """A live `figpact render-session` with a line-protocol client."""

    def __init__(self, script, config, scope, output_dir):
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "figpact.cli", "render-session",
             "--script", str(script), "--config", str(config), "--scope", scope,
             "--output-dir", str(output_dir)],
            cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self._out, self._err = queue.Queue(), queue.Queue()
        for stream, sink in ((self.proc.stdout, self._out), (self.proc.stderr, self._err)):
            threading.Thread(target=self._pump, args=(stream, sink), daemon=True).start()
        self._id = 0

    @staticmethod
    def _pump(stream, sink):
        try:
            for line in stream:
                sink.put(line)
        except (ValueError, OSError):
            pass

    def _read(self):
        try:
            return self._out.get(timeout=REQUEST_TIMEOUT)
        except queue.Empty:
            raise AssertionError(f"render-session 未在 {REQUEST_TIMEOUT}s 内应答；stderr：\n{self.stderr_tail()}")

    def _send(self, payload):
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self._read()
        assert line, f"render-session 进程提前退出；stderr：\n{self.stderr_tail()}"
        return json.loads(line)

    def frame(self, method, params=None):
        self._id += 1
        return self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                           "params": params or {}})

    def call(self, method, params=None):
        frame = self.frame(method, params)
        assert frame.get("jsonrpc") == "2.0" and "error" not in frame, \
            f"{method} 意外报错：{frame.get('error')}"
        assert frame.get("id") == self._id, frame
        return frame["result"]

    def error(self, method, params=None):
        frame = self.frame(method, params)
        assert "error" in frame, f"{method} 本应报错，却返回：{frame}"
        return frame["error"]

    def stderr_tail(self, limit=25):
        lines = []
        while True:
            try:
                lines.append(self._err.get_nowait())
            except queue.Empty:
                return "".join(lines[-limit:])

    def close(self):
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise AssertionError(f"render-session 在 stdin 关闭后未退出；stderr：\n{self.stderr_tail()}")


def _copy(src: Path, tmp_path: Path, name: str) -> Path:
    dst = tmp_path / name
    shutil.copyfile(src, dst)
    return dst


def _check_evidence(evidence: dict) -> None:
    assert evidence["host"] == "NOT_CONNECTED"
    assert evidence["export_page"] == "NOT_RUN"


def test_nmr_open_preview_commit_draft_journey(tmp_path):
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    out_dir = tmp_path / "published"
    out_dir.mkdir()
    before = cfg.read_bytes()
    agent = RenderAgent(NMR_SCRIPT, cfg, "main", out_dir)
    try:
        opened = agent.call("open")
        assert opened["status"] == "open"
        assert opened["scope"] == "main"
        ids = {c["control_id"] for c in opened["controls"]}
        assert '["canvas_w_mm"]' in ids and '["canvas_h_mm"]' in ids
        assert opened["frame"]["png_base64"]

        snap = agent.call("snapshot")
        assert snap["status"] == "OK" and snap["pending"] is None

        preview = agent.call("preview", {"layout": LAYOUT, "intent": INTENT,
                                         "request_id": "rpc-test-1"})
        assert preview["status"] == "OK"
        assert preview["candidate_id"] and preview["layout_revision"]
        assert preview["request_id"] == "rpc-test-1"
        _check_evidence(preview["evidence"])
        assert preview["evidence"]["persistence"] == "NOT_WRITTEN"
        assert cfg.read_bytes() == before  # preview writes nothing

        committed = agent.call(
            "commit", {"candidate_id": preview["candidate_id"],
                       "frame_revision": preview["frame_revision"],
                       "layout_revision": preview["layout_revision"],
                       "confirm": True, "kind": "draft"})
        assert committed["status"] == "committed" and committed["kind"] == "draft"
        assert committed["evidence"]["persistence"] == "WRITTEN"
        _check_evidence(committed["evidence"])

        closed = agent.call("close")
        assert closed["status"] == "closed"
    finally:
        agent.close()
    # Fresh process replays the saved baseline.
    agent2 = RenderAgent(NMR_SCRIPT, cfg, "main", out_dir)
    try:
        reopened = agent2.call("open")
        current = {c["control_id"]: c["current"] for c in reopened["controls"]}
        assert current['["canvas_w_mm"]'] == 68.0
        assert current['["canvas_h_mm"]'] == 68.0
    finally:
        agent2.close()


def test_same_frame_export_then_stale_refused(tmp_path):
    pytest.importorskip("pypdf")
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    out_dir = tmp_path / "published"
    out_dir.mkdir()
    agent = RenderAgent(NMR_SCRIPT, cfg, "main", out_dir)
    try:
        agent.call("open")
        preview = agent.call("preview", {"layout": LAYOUT, "intent": INTENT,
                                         "request_id": "rpc-test-2"})
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        exported = agent.call("export", {"output_dir": str(bundle_dir),
                                         "frame_revision": preview["frame_revision"]})
        assert exported["status"] == "exported"
        bundle = exported["bundle"]
        assert Path(bundle["png_path"]).is_file()
        assert Path(bundle["pdf_path"]).is_file()
        assert len(bundle["page_mm"]) == 2 and all(v > 0 for v in bundle["page_mm"])
        _check_evidence(exported["evidence"])
        # Immutable: the same frame is never overwritten.
        agent.error("export", {"output_dir": str(bundle_dir),
                               "frame_revision": preview["frame_revision"]})
        # Stale frames are refused and leave the config untouched.
        before = cfg.read_bytes()
        agent.error("export", {"output_dir": str(bundle_dir),
                               "frame_revision": "0" * 64})
        assert cfg.read_bytes() == before
    finally:
        agent.close()


def test_ftir_snapshot_real_copy(tmp_path):
    cfg = _copy(FTIR_YAML, tmp_path, "ftir.yaml")
    out_dir = tmp_path / "published-ftir"
    out_dir.mkdir()
    agent = RenderAgent(FTIR_SCRIPT, cfg, "annotated", out_dir)
    try:
        opened = agent.call("open")
        assert opened["status"] == "open" and opened["scope"] == "annotated"
        assert opened["controls"]
        snap = agent.call("snapshot")
        assert snap["status"] == "OK" and snap["pending"] is None
    finally:
        agent.close()


def test_startup_invalid_request_never_hangs(tmp_path):
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    out_dir = tmp_path / "published"
    out_dir.mkdir()
    proc = RenderAgent("does-not-exist.py", cfg, "main", out_dir)
    try:
        for raw in ("null\n", "1\n", '"x"\n', '{"oops": 1}\n',
                    '{"jsonrpc": "2.0", "method": "close"}\n'):
            proc.proc.stdin.write(raw)
            proc.proc.stdin.flush()
        # Malformed non-notifications each get INVALID_REQUEST with id null;
        # the final valid notification gets no reply, and the session still
        # answers a live request afterwards.
        for _ in range(4):
            reply = json.loads(proc._read())
            assert reply["jsonrpc"] == "2.0"
            assert reply["error"]["code"] == INVALID_REQUEST
            assert reply.get("id") is None
        opened = proc.frame("open")
        assert "error" in opened and opened["id"] == 1
        assert opened["error"]["code"] == -32603
        assert opened["error"]["data"]["status"] == "INTERNAL_ERROR"
    finally:
        proc.close()


def test_protocol_errors_preserve_working_config(tmp_path):
    cfg = _copy(NMR_YAML, tmp_path, "nmr.yaml")
    out_dir = tmp_path / "published"
    out_dir.mkdir()
    before = cfg.read_bytes()
    agent = RenderAgent(NMR_SCRIPT, cfg, "main", out_dir)
    try:
        agent.call("open")
        # Malformed/non-finite JSON is a parse error, not a silent drop.
        agent.proc.stdin.write("not json\n")
        agent.proc.stdin.flush()
        raw = agent._read()
        reply = json.loads(raw)
        assert reply["error"]["code"] == PARSE_ERROR and reply.get("id") is None
        agent.proc.stdin.write('{"jsonrpc":"2.0","id":99,"method":"open","params":{"x":NaN}}\n')
        agent.proc.stdin.flush()
        reply = json.loads(agent._read())
        assert reply["error"]["code"] == PARSE_ERROR and reply.get("id") is None
        # Unknown methods are rejected by the explicit allowlist.
        assert agent.error("nope", {})["code"] == METHOD_NOT_FOUND
        # Missing preview params are invalid, not guessed.
        assert agent.error("preview", {"layout": LAYOUT})["code"] == INVALID_PARAMS
        # Cancel of an unknown candidate never pretends success.
        err = agent.error("cancel", {"candidate_id": "does-not-exist"})
        assert err["data"]["status"] == "CANDIDATE_UNKNOWN"
        # confirm:false writes nothing, even with valid ids.
        preview = agent.call("preview", {"layout": LAYOUT, "intent": INTENT,
                                         "request_id": "rpc-test-3"})
        err = agent.error("commit", {"candidate_id": preview["candidate_id"],
                                     "frame_revision": preview["frame_revision"],
                                     "layout_revision": preview["layout_revision"],
                                     "confirm": False, "kind": "draft"})
        assert err["data"]["status"] == "CONFIRM_REQUIRED"
        assert cfg.read_bytes() == before
    finally:
        agent.close()
