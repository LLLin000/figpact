"""R14 standalone render JSON-RPC surface (no Tavotto dependency).

Transport: one JSON-RPC 2.0 object per line on stdin, one reply per line on
stdout; the process stays alive and holds exactly one ``RenderSession`` for
the (script, config, scope) triple given on the command line. Scripts are
trusted local files named explicitly via ``figpact render-session --script``;
nothing here accepts a remote upload or an arbitrary path over the wire.

This module owns only the protocol lifecycle: parse errors, request ids, the
explicit method allowlist, and mapping ``RenderError`` onto JSON-RPC errors.
Every figure fact (frames, controls, receipts, bundles) comes straight from
``figpact.render_api.RenderSession``; nothing is re-derived or echoed here.
Late failures therefore surface as errors -- a failed commit never returns a
fabricated success.

stdout carries the protocol only. Anything the engine prints while handling a
request is redirected to stderr so a stray script line can never corrupt the
next JSON reply.
"""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout

def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")



METHODS = ("open", "snapshot", "preview", "cancel", "commit", "export", "close")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SESSION_CLOSED = -32002
STALE_REVISION = -32003
NO_CANDIDATE = -32004
COMMIT_REJECTED = -32005

#: RenderError.status -> JSON-RPC code. Clients should match on
#: ``error.data.status`` (the exact RenderSession status string); the numeric
#: code only separates request-shape problems from state conflicts.
_STATUS_CODES = {
    "INVALID": INVALID_PARAMS,
    "UNKNOWN_ID": INVALID_PARAMS,
    "OUT_OF_RANGE": INVALID_PARAMS,
    "CONFIRM_REQUIRED": INVALID_PARAMS,
    "NATIVE_REJECTED": INVALID_PARAMS,
    "REQUIRED_CONTENT_MISSING": INVALID_PARAMS,
    "FIT_UNAVAILABLE": INVALID_PARAMS,
    "FIT_CONFLICT": INVALID_PARAMS,
    "CROP_FIT_UNSUPPORTED": INVALID_PARAMS,
    "UNSUPPORTED_GEOMETRY": INVALID_PARAMS,
    "STALE_REVISION": STALE_REVISION,
    "SUPERSEDED": STALE_REVISION,
    "EXPORT_STALE": STALE_REVISION,
    "REFRESH_REQUIRED": STALE_REVISION,
    "CANDIDATE_UNKNOWN": NO_CANDIDATE,
    "CANCELLED": NO_CANDIDATE,
    "SESSION_CLOSED": SESSION_CLOSED,
    "COMMIT_REJECTED": COMMIT_REJECTED,
    "SCIENCE_VIOLATION": COMMIT_REJECTED,
    "QA_BLOCKED": COMMIT_REJECTED,
}

_PREVIEW_REQUIRED = ("layout", "intent", "request_id")
_COMMIT_REQUIRED = ("candidate_id", "frame_revision", "layout_revision", "confirm")
_EXPORT_REQUIRED = ("frame_revision",)


def _response(request_id, payload):
    return {"jsonrpc": "2.0", "id": request_id, **payload}

def _valid_id(value):
    return value is None or (type(value) in (str, int))




def _error_of(error, render_error_cls=None):
    """Map a session failure onto a JSON-RPC error object (never a success)."""
    if render_error_cls is not None and isinstance(error, render_error_cls):
        status = getattr(error, "status", "ERROR") or "ERROR"
        data = {"status": status}
        extra = getattr(error, "data", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                data.setdefault(key, value)
        return {"code": _STATUS_CODES.get(status, INTERNAL_ERROR),
                "message": getattr(error, "message", str(error)) or str(error),
                "data": data}
    return {"code": INTERNAL_ERROR, "message": f"{type(error).__name__}: {error}",
            "data": {"status": "INTERNAL_ERROR"}}


def _dispatch(session, method, params, *, default_output_dir=None):
    """Explicit method allowlist; no arbitrary getattr dispatch."""
    if method in ("open", "snapshot", "close"):
        if params:
            raise ValueError(f"{method} takes no params")
        if method == "open":
            return session.open()
        if method == "snapshot":
            return session.snapshot()
        return session.close()
    if method == "preview":
        missing = [k for k in _PREVIEW_REQUIRED if k not in params]
        if missing:
            raise ValueError(f"preview params 缺少：{missing}")
        extra = sorted(set(params) - set(_PREVIEW_REQUIRED))
        if extra:
            raise ValueError(f"preview params 未知：{extra}")
        return session.preview(params["layout"], params["intent"], params["request_id"])
    if method == "cancel":
        extra = sorted(set(params) - {"candidate_id"})
        if extra:
            raise ValueError(f"cancel params 未知：{extra}")
        return session.cancel(params.get("candidate_id"))
    if method == "commit":
        missing = [k for k in _COMMIT_REQUIRED if k not in params]
        if missing:
            raise ValueError(f"commit params 缺少：{missing}")
        extra = sorted(set(params) - set(_COMMIT_REQUIRED) - {"kind"})
        if extra:
            raise ValueError(f"commit params 未知：{extra}")
        return session.commit(params["candidate_id"], params["frame_revision"],
                              params["layout_revision"], params["confirm"],
                              kind=params.get("kind", "draft"))
    if method == "export":
        missing = [k for k in _EXPORT_REQUIRED if k not in params]
        if missing:
            raise ValueError(f"export params 缺少：{missing}")
        extra = sorted(set(params) - set(_EXPORT_REQUIRED) - {"output_dir", "candidate_id"})
        if extra:
            raise ValueError(f"export params 未知：{extra}")
        output_dir = params.get("output_dir", default_output_dir)
        if not isinstance(output_dir, str) or not output_dir:
            raise ValueError("export requires --output-dir or params.output_dir; source directory is never an implicit export destination")
        return session.export(output_dir, params["frame_revision"],
                              candidate_id=params.get("candidate_id"))
    raise ValueError(f"unknown method: {method}")  # unreachable; allowlist checked first


def _notification(request):
    return (isinstance(request, dict) and request.get("jsonrpc") == "2.0"
            and isinstance(request.get("method"), str) and "id" not in request)


def _startup_reply(request, startup_error):
    if _notification(request):
        return None
    if not isinstance(request, dict) or "id" not in request:
        return _response(None, {"error": {"code": INVALID_REQUEST,
                                          "message": "invalid JSON-RPC request"}})
    return _response(request.get("id"), {"error": startup_error})

def _handle(session, request, render_error_cls, *, default_output_dir=None):

    if not isinstance(request, dict):
        return _response(None, {"error": {"code": INVALID_REQUEST,
                                          "message": "request must be an object"}})
    request_id = request.get("id")
    if request.get("jsonrpc") != "2.0" or not _valid_id(request_id) \
            or "method" not in request or \
            set(request) - {"jsonrpc", "id", "method", "params"}:
        return _response(None, {"error": {"code": INVALID_REQUEST,
                                          "message": "invalid JSON-RPC request"}})
    method = request.get("method")
    if not isinstance(method, str) or not method:
        return _response(request_id, {"error": {"code": INVALID_REQUEST,
                                                "message": "method must be a non-empty string"}})
    if method not in METHODS:
        return _response(request_id, {"error": {"code": METHOD_NOT_FOUND,
                                                "message": f"unknown method: {method}"}})
    params = request.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _response(request_id, {"error": {"code": INVALID_PARAMS,
                                                "message": "params must be an object"}})
    try:
        with redirect_stdout(sys.stderr):
            result = _dispatch(session, method, params,
                               default_output_dir=default_output_dir)
        return _response(request_id, {"result": result})
    except Exception as error:
        if render_error_cls is not None and isinstance(error, render_error_cls):
            return _response(request_id, {"error": _error_of(error, render_error_cls)})
        if isinstance(error, ValueError):
            return _response(request_id, {"error": {"code": INVALID_PARAMS,
                                                    "message": str(error) or "invalid params"}})
        return _response(request_id, {"error": _error_of(error)})


def serve(script, config, scope, output_dir=None, *, stdin=None, stdout=None):
    """Run the persistent render session loop until stdin EOF. Returns 0."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        from figpact.render_api import RenderError, RenderSession
    except Exception as error:
        sys.stderr.write(f"[render-session] unavailable: {error}\n")
        return 2
    try:
        with redirect_stdout(sys.stderr):
            session = RenderSession(script, config, scope, output_dir=output_dir)
    except RenderError as error:
        session = None
        startup_error = _error_of(error, RenderError)
    except Exception as error:
        session = None
        startup_error = _error_of(error)
    else:
        startup_error = None
    default_output_dir = output_dir
    try:
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line, parse_constant=_reject_json_constant)
            except ValueError:
                _emit(stdout, _response(None, {"error": {"code": PARSE_ERROR,
                                                         "message": "parse error"}}))
                continue
            requests = payload if isinstance(payload, list) else [payload]
            if isinstance(payload, list) and not payload:
                _emit(stdout, [_response(None, {"error": {"code": INVALID_REQUEST,
                                                        "message": "empty batch"}})])
                continue
            replies = []
            for request in requests:
                if session is None:
                    reply = _startup_reply(request, startup_error)
                    if reply is not None:
                        replies.append(reply)
                    continue
                reply = _handle(session, request, RenderError,
                                default_output_dir=default_output_dir)
                if not _notification(request):
                    replies.append(reply)
            if replies:
                _emit(stdout, replies if isinstance(payload, list) else replies[0])
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    return 0


def _emit(stdout, message):
    try:
        text = json.dumps(message, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        fallback = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": INTERNAL_ERROR,
                              "message": f"response is not JSON-serializable: {error}"}}
        try:
            text = json.dumps(fallback, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            text = ('{"jsonrpc": "2.0", "id": null, "error": {"code": -32603, '
                    '"message": "response is not JSON-serializable"}}')
    stdout.write(text + "\n")
    stdout.flush()
