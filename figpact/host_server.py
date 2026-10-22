"""Authenticated loopback service for explicit live-layout capture and display."""
from __future__ import annotations

import hmac
import http.server
import json
import math
import secrets
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .frame_binding import FrameBindingError, bind_frame, validate_display
from .render_contract import validate_layout

MAX_BODY = 8 * 1024 * 1024


class HostServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, base: str | Path, host_origin: str,
                 address: tuple[str, int] = ("127.0.0.1", 0), *,
                 render_session=None, panel_id: str | None = None):
        if address[0] != "127.0.0.1":
            raise ValueError("host server must bind to 127.0.0.1")
        parsed = urlsplit(host_origin)
        if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost")
                or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("host_origin must be an authorized loopback HTTP origin")
        if (render_session is None) != (panel_id is None):
            raise ValueError("render_session and panel_id must be configured together")
        self.base = Path(base).expanduser().resolve(strict=True)
        if not self.base.is_dir():
            raise ValueError("base must be a directory")
        self.host_origin = f"{parsed.scheme}://{parsed.netloc}"
        self.render_session = render_session
        self.panel_id = panel_id
        self.token = secrets.token_urlsafe(32)
        self._state_lock = threading.RLock()
        self._render_lock = threading.Lock()
        self._layout: dict[str, Any] | None = None
        self._capture_payload: dict[str, Any] | None = None
        self._instance_id: str | None = None
        self._generation = -1
        self._invalid_generation = False
        self._capture_rechecking = False
        self._capture_epoch = 0
        self._latest_request = -1
        self._offered: dict[str, Any] | None = None
        self._offered_candidate_revision: str | None = None
        self._offered_layout_revision: str | None = None
        self._frame_cache: dict[str, Any] | None = None
        self._display_receipt: dict[str, Any] | None = None
        super().__init__(address, _Handler)

    def _fresh_frame(self, expected: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.render_session is None:
            raise FrameBindingError("NO_RENDER_SESSION", "no trusted render session is configured")
        current = self.render_session.snapshot()
        frame = current.get("frame") if isinstance(current, dict) else None
        if not isinstance(frame, dict):
            raise FrameBindingError("STALE_REVISION", "trusted render session has no current frame")
        if expected is not None:
            triple = (frame.get("candidate_revision"), frame.get("source_revision"), frame.get("base_config_revision"), frame.get("frame_revision"))
            bound = (expected.get("candidate_revision"), expected.get("source_revision"), expected.get("base_config_revision"), expected.get("frame_revision"))
            if triple != bound:
                raise FrameBindingError("STALE_REVISION", "trusted source/config/frame changed since offer")
        return frame


class _Handler(http.server.BaseHTTPRequestHandler):
    def __init__(self, request: Any, client_address: Any, server: HostServer) -> None:
        self._app = server
        super().__init__(request, client_address, server)

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _send(self, body: dict[str, Any], code: int = 200) -> None:
        raw = json.dumps(body, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.headers.get("Origin") == self._app.host_origin:
            self.send_header("Access-Control-Allow-Origin", self._app.host_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _authorize(self) -> bool:
        expected_host = f"127.0.0.1:{self._app.server_address[1]}"
        origins = self.headers.get_all("Origin", [])
        hosts = self.headers.get_all("Host", [])
        auth = self.headers.get_all("Authorization", [])
        if len(hosts) != 1 or hosts[0] != expected_host:
            self._send({"status": "FORBIDDEN", "message": "Host is not authorized"}, 403)
            return False
        if len(origins) > 1 or (origins and origins[0] != self._app.host_origin):
            self._send({"status": "FORBIDDEN", "message": "Origin is not authorized"}, 403)
            return False
        if len(auth) != 1 or not auth[0].startswith("Bearer ") or not hmac.compare_digest(auth[0][7:], self._app.token):
            self._send({"status": "UNAUTHORIZED", "message": "Bearer token required"}, 401)
            return False
        return True

    def do_OPTIONS(self) -> None:
        if (self.headers.get_all("Host", []) != [f"127.0.0.1:{self._app.server_address[1]}"]
                or self.headers.get_all("Origin", []) != [self._app.host_origin]):
            self._send({"status": "FORBIDDEN", "message": "Host or Origin is not authorized"}, 403)
            return
        self._send({"status": "OK"})
    def _body(self) -> dict[str, Any]:
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise FrameBindingError("INVALID", "Content-Type must be application/json")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit():
            raise FrameBindingError("INVALID", "one valid Content-Length is required")
        length = int(lengths[0])
        if length <= 0:
            raise FrameBindingError("INVALID", "request body is empty")
        if length > MAX_BODY:
            raise FrameBindingError("BODY_TOO_LARGE", "request exceeds 8 MiB")
        raw = self.rfile.read(length)
        def bad_constant(value):
            raise ValueError(f"non-finite JSON number {value}")
        try:
            value = json.loads(raw.decode("utf-8"), parse_constant=bad_constant,
                               object_pairs_hook=_unique_pairs)
            _finite(value)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise FrameBindingError("INVALID", f"invalid strict JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise FrameBindingError("INVALID", "request body must be an object")
        return value

    def _fail(self, error: Exception) -> None:
        status = getattr(error, "status", None)
        status = status if isinstance(status, str) else "INVALID"
        conflicts = {"SUPERSEDED", "INSTANCE_CONFLICT", "BINDING_MISMATCH", "NO_OFFER",
                     "NO_CAPTURE", "AMBIGUOUS_PANEL", "REFRESH_REQUIRED", "SESSION_CLOSED"}
        client_errors = {"INVALID", "INVALID_LAYOUT", "INVALID_FRAME", "UNKNOWN_PANEL",
                         "PANEL_NOT_MANAGED", "NO_MANAGED_PANEL", "OVERRIDE_NOT_SUPPORTED",
                         "PATH_OUTSIDE_BASE", "SCRIPT_MISMATCH", "CONFIG_MISMATCH",
                         "SCOPE_MISMATCH", "UNSUPPORTED_GEOMETRY", "NO_RENDER_SESSION"}
        code = (409 if status.startswith("STALE_") or status in conflicts or status == "ADAPTER_ERROR"
                else 413 if status == "BODY_TOO_LARGE" else 400 if status in client_errors else 500)
        self._send({"status": status, "message": str(error)}, code)

    def do_GET(self) -> None:
        if not self._authorize():
            return
        path = urlsplit(self.path).path
        if path == "/session":
            self._send({"schema": "figpact.host-session/1", "base_path": str(self._app.base), "panel_id": self._app.panel_id})
        elif path == "/snapshot":
            with self._app._state_lock:
                if self._app._capture_rechecking:
                    self._send({"status": "STALE_GENERATION", "message": "resource facts are being rechecked"}, 409)
                elif self._app._layout is None:
                    self._send({"status": "NO_CAPTURE", "message": "capture a layout first"}, 409)
                else:
                    self._send({"layout": self._app._layout, "display": self._app._display_receipt})
        else:
            self._send({"status": "NOT_FOUND", "message": "unknown route"}, 404)

    def do_POST(self) -> None:
        if not self._authorize():
            return
        path = urlsplit(self.path).path
        if path not in ("/capture", "/frame", "/display"):
            self._send({"status": "NOT_FOUND", "message": "unknown route"}, 404)
            return
        try:
            body = self._body()
            if path == "/capture":
                self._capture(body)
            elif path == "/frame":
                self._frame(body)
            else:
                self._display(body)
        except Exception as exc:
            self._fail(exc)

    @staticmethod
    def _capture_facts(payload: dict[str, Any]) -> dict[str, Any]:
        facts = dict(payload)
        document = dict(payload["document"])
        document.pop("updatedAt", None)
        facts["document"] = document
        return facts

    def _read_live_layout(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            root = Path(payload["project_root"]).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise FrameBindingError("PATH_OUTSIDE_BASE", "project_root does not resolve to an existing path") from exc
        if root != self._app.base:
            raise FrameBindingError("PATH_OUTSIDE_BASE", "project_root must resolve exactly to configured base")
        try:
            from .tavotto_saved import read_live_layout
            return validate_layout(read_live_layout(payload, base=self._app.base))
        except FrameBindingError:
            raise
        except Exception as exc:
            raise FrameBindingError("ADAPTER_ERROR", str(exc)) from exc

    def _capture(self, payload: dict[str, Any]) -> None:
        required = {"instance_id", "generation", "document_id", "canvas_id", "project_root", "document"}
        if set(payload) != required:
            raise FrameBindingError("INVALID", "capture requires the exact live-layout envelope fields")
        instance, generation = payload["instance_id"], payload["generation"]
        if (not isinstance(instance, str) or not instance.strip() or isinstance(generation, bool)
                or not isinstance(generation, int) or generation < 0
                or not isinstance(payload["document_id"], str) or not payload["document_id"].strip()
                or not isinstance(payload["canvas_id"], str) or not payload["canvas_id"].strip()
                or not isinstance(payload["project_root"], str) or not payload["project_root"].strip()
                or not isinstance(payload["document"], dict)):
            raise FrameBindingError("INVALID", "invalid browser instance, generation, or live document facts")
        existing_revision: str | None = None
        with self._app._state_lock:
            if self._app._instance_id is not None and instance != self._app._instance_id:
                raise FrameBindingError("INSTANCE_CONFLICT", "a different browser instance is already active")
            if generation < self._app._generation:
                raise FrameBindingError("STALE_GENERATION", "capture generation is older than the latest")
            same_generation = generation == self._app._generation
            if same_generation and self._app._invalid_generation:
                raise FrameBindingError("STALE_GENERATION", "equal generation was invalidated by changed resource facts")
            if same_generation:
                if self._app._capture_rechecking:
                    raise FrameBindingError("STALE_GENERATION", "equal-generation resource check is already in progress")
                if self._capture_facts(payload) != self._app._capture_payload:
                    raise FrameBindingError("STALE_GENERATION", "equal generation contains different facts")
                stored = self._app._layout
                existing_revision = stored["revision"] if isinstance(stored, dict) else None
                if existing_revision is not None:
                    self._app._capture_epoch += 1
                    self._app._capture_rechecking = True
                epoch = self._app._capture_epoch
            else:
                self._app._capture_epoch += 1
                epoch = self._app._capture_epoch
                self._app._generation = generation
                self._app._instance_id = instance
                self._app._capture_payload = self._capture_facts(payload)
                self._app._invalid_generation = False
                self._app._capture_rechecking = False
                self._app._layout = None
                self._app._offered = None
                self._app._offered_candidate_revision = None
                self._app._offered_layout_revision = None
                self._app._display_receipt = None
                self._app._latest_request = -1
        try:
            layout = self._read_live_layout(payload)
        except Exception:
            if same_generation:
                with self._app._state_lock:
                    if epoch == self._app._capture_epoch:
                        self._app._capture_epoch += 1
                        self._app._capture_rechecking = False
                        self._app._invalid_generation = True
                        self._app._layout = None
                        self._app._offered = None
                        self._app._offered_candidate_revision = None
                        self._app._offered_layout_revision = None
                        self._app._display_receipt = None
            raise
        with self._app._state_lock:
            if epoch != self._app._capture_epoch:
                raise FrameBindingError("STALE_GENERATION", "newer capture superseded this result")
            if same_generation:
                if existing_revision is None:
                    current_layout = self._app._layout
                    if current_layout is None:
                        self._app._layout = layout
                    elif layout["revision"] == current_layout["revision"]:
                        layout = current_layout
                    else:
                        self._app._capture_epoch += 1
                        self._app._capture_rechecking = False
                        self._app._invalid_generation = True
                        self._app._layout = None
                        self._app._offered = None
                        self._app._offered_candidate_revision = None
                        self._app._offered_layout_revision = None
                        self._app._display_receipt = None
                        raise FrameBindingError("STALE_GENERATION", "concurrent equal-generation captures disagree")
        try:
            layout = self._read_live_layout(payload)
        except Exception:
            if same_generation:
                with self._app._state_lock:
                    if epoch == self._app._capture_epoch:
                        self._app._capture_epoch += 1
                        self._app._capture_rechecking = False
                        self._app._invalid_generation = True
                        self._app._layout = None
                        self._app._offered = None
                        self._app._offered_candidate_revision = None
                        self._app._offered_layout_revision = None
                        self._app._display_receipt = None
            raise
        with self._app._state_lock:
            if epoch != self._app._capture_epoch:
                raise FrameBindingError("STALE_GENERATION", "newer capture superseded this result")
            if same_generation:
                if existing_revision is None:
                    current_layout = self._app._layout
                    if current_layout is None:
                        self._app._layout = layout
                    elif layout["revision"] == current_layout["revision"]:
                        layout = current_layout
                    else:
                        self._app._capture_epoch += 1
                        self._app._capture_rechecking = False
                        self._app._invalid_generation = True
                        self._app._layout = None
                        self._app._offered = None
                        self._app._offered_candidate_revision = None
                        self._app._offered_layout_revision = None
                        self._app._display_receipt = None
                        raise FrameBindingError("STALE_GENERATION", "concurrent equal-generation captures disagree")
                elif layout["revision"] != existing_revision:
                    self._app._capture_epoch += 1
                    self._app._capture_rechecking = False
                    self._app._invalid_generation = True
                    self._app._layout = None
                    self._app._offered = None
                    self._app._offered_candidate_revision = None
                    self._app._offered_layout_revision = None
                    self._app._display_receipt = None
                    raise FrameBindingError("STALE_GENERATION", "resources or live facts changed at equal generation")
                else:
                    self._app._capture_rechecking = False
                    assert self._app._layout is not None
                    layout = self._app._layout
            else:
                self._app._layout = layout
        self._send({"layout": layout})

    def _managed_record(self, layout: dict[str, Any], panel_id: str) -> dict[str, Any]:
        facts = layout.get("extensions", {}).get("tavotto_live", {})
        records = facts.get("objects", {})
        candidates = [item.get("record") for key, item in records.items() if key == panel_id and isinstance(item, dict)]
        if len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise FrameBindingError("UNKNOWN_PANEL", "managed panel raw record is unavailable")
        record = candidates[0]
        if record.get("renderOwner") != "figpact":
            raise FrameBindingError("PANEL_NOT_MANAGED", "panel is not explicitly figpact-owned")
        if record.get("overrides") not in (None, []):
            raise FrameBindingError("OVERRIDE_NOT_SUPPORTED", "host override replay is not supported")
        session = self._app.render_session
        if session is None:
            raise FrameBindingError("NO_RENDER_SESSION", "no trusted render session is configured")
        value = record.get("script")
        if not isinstance(value, str) or not value.strip():
            raise FrameBindingError("SCRIPT_MISMATCH", "managed record lacks script path")
        candidate = (self._app.base / Path(value.replace("\\", "/"))).resolve()
        try:
            candidate.relative_to(self._app.base)
        except ValueError as exc:
            raise FrameBindingError("PATH_OUTSIDE_BASE", "managed script is outside base") from exc
        if candidate != Path(session.script).resolve():
            raise FrameBindingError("SCRIPT_MISMATCH", "managed script differs from trusted RenderSession")
        metadata = record.get("figpact")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("config"), str):
            raise FrameBindingError("CONFIG_MISMATCH", "managed record lacks figpact config")
        candidate = (self._app.base / Path(metadata["config"].replace("\\", "/"))).resolve()
        try:
            candidate.relative_to(self._app.base)
        except ValueError as exc:
            raise FrameBindingError("PATH_OUTSIDE_BASE", "managed config is outside base") from exc
        if candidate != Path(session.config).resolve():
            raise FrameBindingError("CONFIG_MISMATCH", "managed config differs from trusted RenderSession")
        if metadata.get("scope") != session.scope:
            raise FrameBindingError("SCOPE_MISMATCH", "managed scope differs from trusted RenderSession")
        return record

    def _frame(self, body: dict[str, Any]) -> None:
        if set(body) != {"snapshot_revision", "request_id"}:
            raise FrameBindingError("INVALID", "frame requires snapshot_revision and request_id")
        request_id = body["request_id"]
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
            raise FrameBindingError("INVALID", "request_id must be a nonnegative integer")
        with self._app._state_lock:
            layout = self._app._layout
            epoch = self._app._capture_epoch
            if self._app._capture_rechecking:
                raise FrameBindingError("STALE_GENERATION", "resource facts are being rechecked")
            if layout is None:
                raise FrameBindingError("NO_CAPTURE", "capture a layout first")
            if body["snapshot_revision"] != layout["revision"]:
                raise FrameBindingError("STALE_SNAPSHOT", "requested snapshot is not current")
            if request_id < self._app._latest_request:
                raise FrameBindingError("STALE_REQUEST", "request_id is older than latest frame request")
            repeat = request_id == self._app._latest_request
            panel_id = self._app.panel_id
            if not panel_id:
                raise FrameBindingError("NO_MANAGED_PANEL", "no panel configured for rendering")
            cached_frame = self._app._frame_cache
            if repeat:
                if cached_frame is None:
                    raise FrameBindingError("STALE_REQUEST", "request_id was already used")
            else:
                self._managed_record(layout, panel_id)
                self._app._latest_request = request_id
                self._app._offered = None
                self._app._offered_candidate_revision = None
                self._app._display_receipt = None
        with self._app._render_lock:
            if repeat:
                assert cached_frame is not None
                frame = self._app._fresh_frame(cached_frame)
            elif cached_frame is not None:
                try:
                    frame = self._app._fresh_frame(cached_frame)
                except FrameBindingError:
                    frame = self._app._fresh_frame()
            else:
                frame = self._app._fresh_frame()
        with self._app._state_lock:
            if epoch != self._app._capture_epoch or self._app._layout is None or self._app._layout["revision"] != body["snapshot_revision"]:
                raise FrameBindingError("STALE_SNAPSHOT", "capture changed while frame was read")
            if request_id != self._app._latest_request:
                raise FrameBindingError("STALE_REQUEST", "newer frame request superseded this result")
            frame_layout = self._app._layout
        assert panel_id is not None
        bound = bind_frame(frame_layout, panel_id, frame, request_id)
        response = {"binding": bound["binding"], "frame": frame,
                    "projection": bound["projection"], "precheck": bound["precheck"]}
        with self._app._state_lock:
            if epoch != self._app._capture_epoch or request_id != self._app._latest_request:
                raise FrameBindingError("STALE_SNAPSHOT", "newer capture or request superseded this frame")
            self._app._offered = bound["binding"]
            self._app._offered_candidate_revision = frame.get("candidate_revision")
            self._app._offered_layout_revision = frame_layout["revision"]
            self._app._frame_cache = frame
        self._send(response)

    def _display(self, body: dict[str, Any]) -> None:
        if not isinstance(body, dict):
            raise FrameBindingError("INVALID", "display body must be an object")
        with self._app._state_lock:
            if self._app._capture_rechecking:
                raise FrameBindingError("STALE_GENERATION", "resource facts are being rechecked")
            offered = self._app._offered
            layout = self._app._layout
            if offered is None or layout is None:
                raise FrameBindingError("NO_OFFER", "no current frame offer")
            if layout["revision"] != self._app._offered_layout_revision:
                raise FrameBindingError("STALE_SNAPSHOT", "layout changed after frame offer")
            offered_candidate_revision = self._app._offered_candidate_revision
        displayed = validate_display(body, offered)
        # RenderSession.snapshot() is the authority for source/config freshness and the offered frame.
        current = self._app._fresh_frame()
        if (current.get("frame_revision") != offered["frame_revision"]
                or current.get("candidate_revision") != offered_candidate_revision
                or current.get("source_revision") != offered["source_revision"]
                or current.get("base_config_revision") != offered["base_config_revision"]):
            raise FrameBindingError("STALE_REVISION", "trusted source/config/frame changed before image load")
        with self._app._state_lock:
            if self._app._capture_rechecking:
                raise FrameBindingError("STALE_GENERATION", "resource facts are being rechecked")
            if self._app._offered != offered or self._app._layout is None or self._app._layout["revision"] != offered["snapshot_revision"]:
                raise FrameBindingError("STALE_SNAPSHOT", "offer was invalidated before image load")
            self._app._display_receipt = displayed
        self._send({"status": "displayed", "binding": displayed})


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)
