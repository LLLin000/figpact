"""Native scalar-parameter session (figpact v0.1): preview/commit over YAML.

One figure ``(script, config, scope)``, one :class:`AgentSession`, no overlay
mixing. All discovery comes from :mod:`figpact.plan_context` (live EDITABLE
contract records); every candidate goes through the existing
``try_layout``/``render_preview`` engine; every save goes through the existing
:class:`AgentSession` commit transaction (draft gate or independent strict
gate). This module never writes YAML itself and never invents controls.
"""

from __future__ import annotations

import copy
import json
import math
import secrets
from pathlib import Path
from typing import Any

from .agent_api import (
    COMMIT_REJECTED,
    INVALID_PARAMS,
    NO_CANDIDATE,
    SESSION_CLOSED,
    STALE_REVISION,
    AgentError,
    AgentSession,
)
from . import plan_context


def _fail(status: str, message: str, code: int, **extra: Any):
    return {"status": status, "message": message, **extra}, code


def _copy(obj: Any) -> Any:
    return copy.deepcopy(obj)


def _scalar_controls(context: dict) -> list[dict]:
    """Truly authorized scalar EDITABLE controls only.

    ``discover_native`` already excludes LOCKED_SCIENCE / FIXED_STYLE / DERIVED
    records; here we additionally keep only scalar numerics (no ``[dx, dy]``
    pairs, no dicts, no bools, no non-finite floats). ``control_id`` is the
    exact config path serialized as compact JSON, reversible via ``json.loads``.
    """
    out = []
    for rec in context.get("controls") or []:
        if not isinstance(rec, dict) or rec.get("value_shape") != "scalar":
            continue
        value = rec.get("current")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not math.isfinite(float(value)):
            continue
        out.append({
            "control_id": rec["id"],
            "path": list(rec["path"]),
            "label": str(rec.get("key") or "/".join(rec["path"])),
            "unit": rec.get("unit"),
            "current": value,
            "min": rec.get("min"),
            "max": rec.get("max"),
            "objects": list(rec.get("objects") or []),
        })
    out.sort(key=lambda item: item["control_id"])
    return out


def _triple(context: dict) -> tuple[Any, Any, Any]:
    source = context.get("source") or {}
    return (context.get("revision"), source.get("base_config_revision"),
            source.get("source_revision"))


class NativeParameterSession:
    """Bound native session for one trusted ``(script, config, scope)``."""

    def __init__(self, script, config, scope: str, *, output_dir=None):
        self.script = Path(script).expanduser().resolve()
        self.config = Path(config).expanduser().resolve()
        self.scope = scope
        self._agent = AgentSession(str(self.script), str(self.config), scope,
                                   output_dir=output_dir)
        # In-process mirror: builds candidate figures from the worker's own
        # candidate_config via the existing FigureSession.build_candidate
        # path. The worker (subprocess) owns goals/truth; the mirror only
        # renders. Framing reuses inspector.capture_figure -- the exact
        # producer of figpact.inspector/1 bundles the existing JS
        # validateFrame/verifyFrame accept. Never invented frame metadata.
        from .session import FigureSession
        self._local = FigureSession(str(self.script), str(self.config), scope)
        self._session_id: str | None = None
        self._pending: dict | None = None
        self._last_receipt: dict | None = None
        self._refresh_failed = False
        self._refresh_error: str | None = None
        self._frame, self._native = self._rebuild()
        # Base (accepted, no-goals) frame digest: cancel/commit restore the
        # worker to empty goals, and preview pins base_frame_revision so the
        # UI commit path can bind to the accepted frame it actually shows.
        self._base_frame: str | None = self._frame.get("frame_revision")

    def _capture_frame(self) -> dict:
        """Real Inspector frame of the actual same candidate.

        ``session`` block mirrors the ``IntentSession._decorate`` convention
        (``session_id`` / ``scene_revision`` / ``source_revision``) with
        ``can_evaluate`` forced False so legacy drag never claims
        authorization in this mode.
        """
        import uuid

        from .inspector import capture_figure

        state = self._agent._call(self._agent._worker.state) or {}
        self._local._sync()  # same-package reload gate: drift rebuilds, never stale-builds
        fig, reg = self._local.build_candidate(state.get("candidate_config") or {})
        try:
            frame = capture_figure(
                fig, reg, scope=self.scope,
                contract=state.get("contract"),
                science_manifest=state.get("science_manifest"),
                source_revision=state.get("source_revision"))
        finally:
            try:
                import matplotlib.pyplot as plt
                plt.close(fig)
            except Exception:
                pass
        if self._session_id is None:
            self._session_id = str(uuid.uuid4())
        scene = json.loads(frame["scene_json"])
        frame["session"] = {"session_id": self._session_id,
                            "scene_revision": frame.get("frame_revision"),
                            "source_revision": scene.get("source_revision"),
                            "can_evaluate": False}
        return frame

    def _rebuild(self) -> tuple[dict, dict]:
        """Frame + native state for the actual same candidate."""
        plan_context.discover_native(self._agent)  # settle lazy science load first
        frame = self._capture_frame()
        # Re-read the context AFTER capture: _sync() inside the worker path
        # reloads on drift, and a reload clears goals (candidate gone). The
        # post-capture discovery reflects the true current worker state.
        context = plan_context.discover_native(self._agent)
        state = self._agent._call(self._agent._worker.state) or {}
        native = {
            "controls": _scalar_controls(context),
            "pending": _copy(self._pending["public"]) if self._pending else None,
            "receipt": _copy(self._last_receipt),
            "source": _copy(context.get("source") or {}),
            "scope": context.get("scope"),
            "revision": state.get("revision"),
        }
        if self._refresh_failed:
            native["refresh_required"] = True
            if self._refresh_error:
                native["refresh_error"] = self._refresh_error
        frame["native"] = native
        actual = frame.pop("native")
        return frame, actual

    def snapshot(self) -> dict:
        """Cached frame plus live server-bound pending (never a stale copy).

        The cached ``native`` holds ``pending: None`` by construction; the
        pending created by ``preview`` lives server-side in ``self._pending``
        and is attached here on every read, so GET /api/frame or a page
        refresh after preview still sees the same candidate id. ``refresh``
        state rides along coherently even with the cached old frame.
        """
        frame = _copy(self._frame)
        native = _copy(self._native)
        native["pending"] = _copy(self._pending["public"]) if self._pending else None
        native["receipt"] = _copy(self._last_receipt)
        if self._refresh_failed:
            native["refresh_required"] = True
            if self._refresh_error:
                native["refresh_error"] = self._refresh_error
        frame["native"] = native
        return frame

    def _live_context(self) -> dict:
        try:
            return plan_context.discover_native(self._agent)
        except AgentError as error:
            raise
        except Exception as error:
            raise AgentError(SESSION_CLOSED,
                             f'native 上下文不可读：{error}') from error

    def _drop_pending(self) -> None:
        self._pending = None

    def _stale(self, context: dict) -> str | None:
        """Live source triple vs the frame the caller sees; drift invalidates.

        The frame's ``frame_revision`` is the Inspector image+scene digest
        (render-dependent), while the context ``revision`` is the candidate
        config hash -- they are different chains by design. Only the source
        triple (candidate revision + config + source fingerprints) gates
        staleness here; the trial itself re-checks candidate freshness via
        ``try_layout(..., revision=...)``.
        """
        live = _triple(context)
        seen = _triple({"revision": self._native.get("revision"),
                        "source": self._native.get("source")})
        if live != seen:
            return ("脚本、配置或输入在候选生成后发生变化，候选已失效，请刷新后重试")
        return None

    # -- preview / commit / cancel ------------------------------------
    def preview(self, body: Any) -> tuple[dict, int]:
        if not isinstance(body, dict):
            return _fail("INVALID", "请求必须是 JSON 对象", 400)
        if set(body) != {"frame_revision", "edits"}:
            return _fail("INVALID", "preview 只要 frame_revision/edits 字段", 400)
        if body.get("frame_revision") != self._frame.get("frame_revision"):
            self._drop_pending()
            return _fail("STALE_REVISION", "frame 已更新，请刷新后重试", 409)
        try:
            live = self._live_context()
        except AgentError as error:
            return _fail("STALE_REVISION", error.message, 409,
                         diagnostics=[str(error)])
        problem = self._stale(live)
        if problem:
            self._drop_pending()
            return _fail("STALE_REVISION", problem, 409)
        edits = body.get("edits")
        if not isinstance(edits, list) or not edits:
            return _fail("INVALID", "edits 必须是非空列表", 400)
        authorized = {c["control_id"]: c for c in _scalar_controls(live)}
        operations: list[dict] = [{"operation": "reset"}]
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {"control_id", "value"}:
                return _fail("INVALID", "每个 edit 只要 control_id/value 字段", 400)
            cid = edit.get("control_id")
            control = authorized.get(cid) if isinstance(cid, str) else None
            if control is None:
                return _fail("UNKNOWN_ID", f"不可编辑的控制：{cid!r}", 400)
            value = edit.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return _fail("INVALID", f"{control['label']} 的值必须是数字", 400)
            if not math.isfinite(float(value)):
                return _fail("INVALID", f"{control['label']} 的值不是有限数", 400)
            lo, hi = control.get("min"), control.get("max")
            if (lo is not None and float(value) < float(lo)) or \
                    (hi is not None and float(value) > float(hi)):
                return _fail("OUT_OF_RANGE",
                             f"{control['label']} = {value} 超出声明范围 [{lo}, {hi}]",
                             400)
            try:
                path = json.loads(cid)
            except ValueError:
                return _fail("UNKNOWN_ID", f"不可编辑的控制：{cid!r}", 400)
            operations.append({"operation": "set_parameter", "path": path,
                               "value": value})
        try:
            trial = self._agent.try_layout(operations, revision=live.get("revision"))
        except AgentError as error:
            self._drop_pending()
            code = 409 if error.code in (STALE_REVISION,) else 400
            status = "STALE_REVISION" if error.code == STALE_REVISION else "NATIVE_REJECTED"
            return _fail(status, error.message, code,
                         diagnostics=[str(error)], data=error.data)
        except Exception as error:
            self._drop_pending()
            return _fail("NATIVE_REJECTED", f"候选试算失败：{error}", 400,
                         diagnostics=[f"{type(error).__name__}: {error}"])
        if not isinstance(trial, dict) or trial.get("status") != "OK":
            self._drop_pending()
            message = (trial or {}).get("message") if isinstance(trial, dict) \
                else "候选试算未通过"
            return _fail("NATIVE_REJECTED", str(message or "候选试算未通过"), 400,
                         receipt=_copy(trial))
        self._drop_pending()
        try:
            self._frame, self._native = self._rebuild()
        except AgentError as error:
            return _fail("STALE_REVISION", error.message, 409,
                         diagnostics=[str(error)], receipt=_copy(trial))
        except Exception as error:
            return _fail("NATIVE_REJECTED", f"候选预览渲染失败，正式文件未改动：{error}",
                         400, diagnostics=[f"{type(error).__name__}: {error}"],
                         receipt=_copy(trial))
        state = self._agent._call(self._agent._worker.state) or {}
        if not state.get("has_candidate"):
            return _fail("STALE_REVISION", "预览渲染时检测到来源变化，候选已作废，请刷新后重试",
                         409, receipt=_copy(trial))
        candidate_id = secrets.token_urlsafe(16)
        revision = self._frame.get("frame_revision")
        public = {"candidate_id": candidate_id,
                  "frame_revision": revision,
                  "base_frame_revision": self._base_frame,
                  "edits": _copy([{"control_id": e["control_id"], "value": e["value"]}
                                   for e in edits if isinstance(e, dict)]),
                  "issue_count": len((trial or {}).get("new_qa") or [])}
        self._pending = {"candidate_id": candidate_id, "public": public,
                         "revision": state.get("revision"),
                         "frame_revision": revision,
                         "base_frame_revision": self._base_frame,
                         "bound": _triple({"revision": state.get("revision"),
                                           "source": self._native.get("source")})}
        self._refresh_failed = False
        self._refresh_error = None
        return {"status": "OK", "frame": self.snapshot(),
                "native": self.snapshot()["native"],
                "receipt": _copy(trial),
                "message": f"候选已生成（{trial.get('verification') or 'trial'}），"
                           f"确认后才写入"}, 200

    def commit(self, body: Any) -> tuple[dict, int]:
        if not isinstance(body, dict):
            return _fail("INVALID", "请求必须是 JSON 对象", 400)
        if set(body) != {"candidate_id", "frame_revision", "kind"}:
            return _fail("INVALID", "commit 只要 candidate_id/frame_revision/kind 字段",
                         400)
        kind = body.get("kind")
        if kind not in ("draft", "publication"):
            return _fail("INVALID", "kind 只支持 'draft'/'publication'", 400)
        if self._pending is None or \
                body.get("candidate_id") != self._pending["candidate_id"]:
            self._drop_pending()
            return _fail("CANDIDATE_UNKNOWN", "候选已失效，请重新 preview", 409)
        if body.get("frame_revision") not in (
                self._pending.get("frame_revision"),
                self._pending.get("base_frame_revision")):
            self._drop_pending()
            return _fail("STALE_REVISION", "frame 已更新，候选已作废", 409)
        try:
            live = self._live_context()
        except AgentError as error:
            self._drop_pending()
            return _fail("STALE_REVISION", error.message, 409,
                         diagnostics=[str(error)])
        if _triple(live) != self._pending["bound"]:
            bound = self._pending["bound"]
            self._drop_pending()
            current = _triple(live)
            names = ("revision", "base_config_revision", "source_revision")
            differing = [name for name, old, new in zip(names, bound, current)
                         if old != new]
            return _fail("STALE_REVISION", "来源或配置在预览后发生变化，候选已作废", 409,
                         differing_source_fields=differing,
                         diagnostics=[f"变化字段：{differing or ['unknown']}"])
        try:
            record = self._agent.commit(
                kind, revision=self._pending["revision"],
                confirm=(kind == "publication"))
        except AgentError as error:
            self._drop_pending()
            if error.code == STALE_REVISION:
                return _fail("STALE_REVISION", error.message, 409,
                             diagnostics=[str(error)], data=error.data)
            if error.code == NO_CANDIDATE:
                return _fail("CANDIDATE_UNKNOWN", error.message, 409,
                             diagnostics=[str(error)], data=error.data)
            if error.code == COMMIT_REJECTED:
                return _fail("COMMIT_REJECTED", error.message, 409,
                             receipt=_copy(error.data),
                             diagnostics=[str(error)])
            code = 400 if error.code == INVALID_PARAMS else 409
            return _fail("COMMIT_REJECTED", error.message, code,
                         diagnostics=[str(error)], data=error.data)
        except Exception as error:
            self._drop_pending()
            return _fail("COMMIT_FAILED",
                         f"提交失败，正式文件状态未知；请刷新后核对：{error}", 500,
                         diagnostics=[f"{type(error).__name__}: {error}"])
        self._drop_pending()
        # No inferred proof: only the actual commit receipt's verification
        # may claim Strict PASS. A receipt without verification is reported
        # with verification None -- never fabricated from kind.
        verification = (record or {}).get("verification")
        self._last_receipt = _copy({"status": "committed", "kind": kind,
                                    "verification": verification,
                                    "receipt": record})
        try:
            self._frame, self._native = self._rebuild()
            self._refresh_failed = False
            self._refresh_error = None
            # Commit installed the candidate as the new accepted baseline.
            self._base_frame = self._frame.get("frame_revision")
        except Exception as error:
            # Bytes on disk are the fact: report the save truthfully with no
            # fresh frame, never rewrite the fact into a save failure.
            # Receipt persists so the UI can still show the actual result.
            self._refresh_failed = True
            self._refresh_error = str(error)
            native = {"controls": [], "pending": None,
                      "receipt": _copy(self._last_receipt),
                      "refresh_required": True, "refresh_error": str(error)}
            return {"status": "committed", "kind": kind,
                    "verification": verification, "frame": None,
                    "native": native, "receipt": _copy(record),
                    "message": "文件已保存，但界面刷新失败；请重新打开后再编辑"}, 200
        strict = verification == "STRICT_VERIFIED"
        return {"status": "committed", "kind": kind, "verification": verification,
                "frame": self.snapshot(), "native": self.snapshot()["native"],
                "receipt": _copy(record),
                "message": "已发布（STRICT_VERIFIED）" if strict else "已保存"}, 200

    def cancel(self, body: Any) -> tuple[dict, int]:
        if not isinstance(body, dict):
            return _fail("INVALID", "请求必须是 JSON 对象", 400)
        if set(body) != {"candidate_id"}:
            return _fail("INVALID", "cancel 只要 candidate_id 字段", 400)
        if self._pending is None or \
                body.get("candidate_id") != self._pending["candidate_id"]:
            return _fail("CANDIDATE_UNKNOWN", "候选不存在或已失效", 409)
        self._drop_pending()
        # Goals live only in the worker; files are never touched by preview.
        # The reset IS the existing discard API (try_layout reset clears
        # goals); a failed reset leaves the worker state unknown, so cancel
        # must not claim success -- report, keep pending dropped, force reopen.
        try:
            reset = self._agent.try_layout([{"operation": "reset"}])
        except AgentError as error:
            return _fail("CANCEL_FAILED", f"取消失败，候选状态未知；请重新打开：{error.message}",
                         409, diagnostics=[str(error)], data=error.data)
        except Exception as error:
            return _fail("CANCEL_FAILED", f"取消失败，候选状态未知；请重新打开：{error}",
                         500, diagnostics=[f"{type(error).__name__}: {error}"])
        if not isinstance(reset, dict) or reset.get("status") not in ("OK",):
            return _fail("CANCEL_FAILED",
                         f"取消失败（reset 未通过：{(reset or {}).get('message') or reset}）；请重新打开",
                         409, receipt=_copy(reset))
        try:
            self._frame, self._native = self._rebuild()
            # Cancel restored empty goals: re-pin the accepted base digest.
            self._base_frame = self._frame.get("frame_revision")
        except Exception as error:
            return _fail("STALE_REVISION", f"取消后刷新失败，请重新打开：{error}", 409,
                         diagnostics=[f"{type(error).__name__}: {error}"])
        return {"status": "OK", "frame": self.snapshot(),
                "native": self.snapshot()["native"],
                "message": "候选已取消，文件未改动"}, 200

    def close(self):
        try:
            return self._agent.close()
        except Exception as error:
            return {"status": "closed", "error": str(error)}
