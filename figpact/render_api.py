"""Public standalone rendering API (R14 G0+G1); no host integration."""
from __future__ import annotations

import copy
import json
import math
import secrets
import threading
from pathlib import Path
from typing import Any, NoReturn

from .native_parameters import NativeParameterSession
from .render_contract import (RenderContractError, precheck_layout, project_scene,
                              validate_intent, validate_layout)

# Measured canvas-bound extent tolerance; no pixel/font tolerance is inferred.
CANVAS_TOLERANCE_MM = 1e-3


class RenderError(ValueError):
    """A failed render operation with a stable status and optional evidence."""

    def __init__(self, status: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.data = data or {}


def _error(status: str, message: str, **data: Any) -> NoReturn:
    raise RenderError(status, message, data)


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _scene_for_projection(frame: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        raw = json.loads(frame["scene_json"])
        bounds = raw["canvas_bounds_mm"]
        if len(bounds) != 4:
            raise ValueError("canvas bounds are not four coordinates")
        x0, y0, x1, y1 = map(float, bounds)
        width, height = x1 - x0, y1 - y0
        if not all(math.isfinite(v) for v in (x0, y0, width, height)) or width <= 0 or height <= 0:
            raise ValueError("canvas bounds have no positive measured extent")
        nodes = []
        for node in raw.get("nodes", []):
            box = node.get("bounds_mm")
            measured = bool(node.get("measured") and box is not None
                            and node.get("fully_clipped") is not True
                            and node.get("visible") is True)
            # Inspector bounds are [x0,y0,x1,y1] in canvas-bottom-left mm.
            rect = [float(box[0]) - x0, float(box[1]) - y0,
                    float(box[2]) - x0, float(box[3]) - y0] if measured else None
            nodes.append({"id": str(node.get("id") or node.get("gid") or ""),
                          "bounds_mm": rect, "measured": measured})
        return ({"coordinate_reference": "canvas_bottom_left",
                 "canvas_mm": [width, height], "nodes": nodes}, raw.get("nodes", []))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        _error("FIT_UNAVAILABLE", f"Inspector scene cannot be projected without measured bounds: {error}")


def project_frame_scene(frame: dict[str, Any], panel: dict[str, Any],
                        page_mm: Any) -> dict[str, Any]:
    """Project a captured frame without running the renderer or changing its layout."""
    scene, _ = _scene_for_projection(frame)
    return project_scene(scene, panel, page_mm)


class RenderSession:
    """One worker-backed (script, config, scope) session with explicit receipts."""

    def __init__(self, script: object, config: object, scope: str, output_dir: str | Path | None = None) -> None:
        self._native = NativeParameterSession(script, config, scope, output_dir=output_dir)
        self.script, self.config, self.scope = self._native.script, self._native.config, scope
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else self.script.parent
        self._closed = False
        self._op_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._generation: int = 0
        self._pending: dict[str, Any] | None = None
        self._cancelled: set[str] = set()
        self._superseded: set[str] = set()
        self._retired_frames: set[str] = set()
        self._stale_candidates: set[str] = set()
        self._refresh_required = False
        self._refresh_error: str | None = None

    def _ensure_open(self) -> None:
        if self._closed:
            _error("SESSION_CLOSED", "render session is closed")

    @staticmethod
    def _controls(frame: dict[str, Any]) -> list[dict[str, Any]]:
        return _copy((frame.get("native") or {}).get("controls") or [])

    def _public_frame(self, frame: dict[str, Any]) -> dict[str, Any]:
        return {key: _copy(value) for key, value in frame.items() if key != "native"}

    def _view(self, status: str = "OK") -> dict[str, Any]:
        if self._refresh_required:
            _error("REFRESH_REQUIRED", "saved bytes are newer than the cached frame; reopen before reading",
                   refresh_required=True, refresh_error=self._refresh_error)
        self._check_live_freshness()
        native = self._native.snapshot()
        self._check_drift(native)
        view = {"status": status, "frame": self._public_frame(native),
                "controls": self._controls(native), "source": _copy(native["native"].get("source") or {}),
                "revision": native.get("candidate_revision"), "scope": self.scope}
        native_state = native.get("native") or {}
        if native_state.get("refresh_required"):
            view["refresh_required"] = True
            view["refresh_error"] = self._refresh_error or native_state.get("refresh_error")
        return view

    def open(self) -> dict[str, Any]:
        with self._state_lock:
            self._ensure_open()
            return self._view("open")

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            self._ensure_open()
            result = self._view()
            result["pending"] = _copy(self._pending)
            return result

    def _live_triple(self) -> tuple[tuple[Any, Any, Any], dict[str, Any]]:
        """Read-only live source/config triple; never syncs or hides external edits."""
        live = self._native._live_context()
        source = live.get("source") or {}
        return ((live.get("revision"), source.get("base_config_revision"),
                 source.get("source_revision")), live)

    def _check_live_freshness(self, expected: dict[str, Any] | None = None) -> tuple[Any, Any, Any] | None:
        """Live source/config triple check; external edits invalidate pending first."""
        if self._refresh_required:
            return None
        try:
            current, _ = self._live_triple()
        except Exception as error:
            self._invalidate_pending(stale=True)
            _error("STALE_REVISION", f"live source context is unreadable: {type(error).__name__}: {error}")
        if expected is None:
            cached = self._native.snapshot()
            native = cached.get("native") or {}
            source = native.get("source") or {}
            seen = (native.get("revision"), source.get("base_config_revision"),
                    source.get("source_revision"))
            if current != seen:
                self._invalidate_pending(stale=True)
                _error("STALE_REVISION", "source/config changed after the cached frame; candidate invalidated",
                       differing_source_fields=["unknown"],
                       diagnostics=["live triple differs from cached frame"])
            return current
        bound = (expected.get("candidate_revision"), expected.get("base_config_revision"),
                 expected.get("source_revision"))
        if current != bound:
            names = ("revision", "base_config_revision", "source_revision")
            differing = [name for name, old, new in zip(names, bound, current) if old != new]
            self._invalidate_pending(stale=True)
            _error("STALE_REVISION", "source/config changed after preview; candidate invalidated",
                   differing_source_fields=differing or ["unknown"],
                   diagnostics=[f"live triple differs in: {differing or ['unknown']}"])
        return current

    def _check_drift(self, frame: dict[str, Any], pending: dict[str, Any] | None = None) -> None:
        native = frame.get("native") or {}
        source = native.get("source") or {}
        expected = pending or (self._pending or {})
        if expected:
            current = (frame.get("candidate_revision"), frame.get("source_revision"),
                       frame.get("base_config_revision"))
            bound = (expected.get("candidate_revision"), expected.get("source_revision"),
                     expected.get("base_config_revision"))
            if current != bound:
                self._invalidate_pending(stale=True)
                _error("STALE_REVISION", "source/config/candidate drift invalidated the render receipt",
                       bound=bound, current=current)
        if source and frame.get("candidate_revision") != native.get("revision"):
            _error("STALE_REVISION", "candidate revision changed during frame capture")
    def _invalidate_pending(self, *, stale: bool = False) -> None:
        if self._pending:
            self._superseded.add(self._pending["candidate_id"])
            self._retired_frames.add(self._pending["frame_revision"])
            if stale:
                self._stale_candidates.add(self._pending["candidate_id"])
        self._pending = None

    def _discard_native_pending(self) -> None:
        failed = self._native.snapshot()
        pending = (failed.get("native", {}).get("pending") or {})
        if not pending.get("candidate_id"):
            return
        self._retired_frames.add(failed["frame_revision"])
        result, code = self._native.cancel({"candidate_id": pending["candidate_id"]})
        if code != 200:
            _error("NATIVE_REJECTED", result.get("message") or "Native reset refused")

    def _validate_fit(self, panel: dict[str, Any], intent: dict[str, Any],
                      controls: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float] | None]:
        if not intent["fit_canvas"]:
            return [], None
        if panel.get("crop") is not None:
            _error("CROP_FIT_UNSUPPORTED", "fit_canvas with an explicit crop is unsupported; no crop mapping was guessed")
        edits = {edit["control_id"]: edit["value"] for edit in intent["edits"]}
        rotation = panel["rotation_deg"]
        target = panel["rect_mm"][2:4]
        if rotation in (90.0, 270.0):
            target.reverse()
        expected = {"canvas_w_mm": target[0], "canvas_h_mm": target[1]}
        generated = []
        for name, value in expected.items():
            cid = json.dumps([name], separators=(",", ":"))
            if cid not in controls:
                _error("FIT_UNAVAILABLE", f"fit_canvas requires authorized {name} control")
            if cid in edits and not math.isclose(float(edits[cid]), value,
                                                 abs_tol=CANVAS_TOLERANCE_MM, rel_tol=0):
                _error("FIT_CONFLICT", f"explicit {name} edit conflicts with target panel dimension",
                       requested=edits[cid], target=value)
            if cid not in edits:
                generated.append({"control_id": cid, "value": value})
        return generated, expected

    @staticmethod
    def _required_content(scene_nodes: list[dict[str, Any]], required: list[str],
                          projected: dict[str, Any]) -> dict[str, Any]:
        by_id = {}
        for node in scene_nodes:
            by_id[node.get("id")] = node
            if node.get("gid"):
                by_id[node["gid"]] = node
        projected_by_id = {node["id"]: node for node in projected.get("nodes", [])}
        missing = []
        checked = []
        for gid in required:
            source = by_id.get(gid)
            item = projected_by_id.get(gid)
            projected_source = item.get("source") if item else None
            bounds = projected_source.get("scene_bounds_mm") if projected_source else None
            canvas = projected_source.get("canvas_mm") if projected_source else None
            crop = projected_source.get("crop_mm") if projected_source else None
            fully_in_crop = False
            if (isinstance(bounds, list) and len(bounds) == 4
                    and isinstance(canvas, list) and len(canvas) == 2
                    and isinstance(crop, list) and len(crop) == 4):
                x0, y0, x1, y1 = map(float, bounds)
                left, top, width, height = crop
                node_rect = [x0, canvas[1] - y1, x1 - x0, y1 - y0]
                fully_in_crop = (node_rect[0] >= left - 1e-9
                                 and node_rect[1] >= top - 1e-9
                                 and node_rect[0] + node_rect[2] <= left + width + 1e-9
                                 and node_rect[1] + node_rect[3] <= top + height + 1e-9)
            if (source is None or source.get("visible") is not True or not source.get("measured")
                    or source.get("fully_clipped") is True or item is None
                    or not item.get("measurable") or not fully_in_crop):
                missing.append(gid)
            else:
                checked.append(gid)
        return {"checked": checked, "missing": missing}

    @staticmethod
    def _font_metrics(scene_nodes: list[dict[str, Any]], projected: dict[str, Any]) -> dict[str, Any]:
        projected_nodes = {node["id"]: node for node in projected.get("nodes", [])}
        measured, unmeasured = [], []
        for node in scene_nodes:
            if node.get("type") != "text" and node.get("artist_type") != "Text":
                continue
            gid = node.get("gid") or node.get("id")
            pnode = projected_nodes.get(node.get("id"))
            rect = pnode.get("rect_mm") if pnode else None
            source_font_pt = node.get("font_size_pt")
            source = "captured_font_size" if source_font_pt is not None else None
            if (isinstance(source_font_pt, bool) or not isinstance(source_font_pt, (int, float))
                    or not math.isfinite(float(source_font_pt)) or float(source_font_pt) <= 0):
                source_font_pt = None
                source = None
            scale_xy = pnode.get("scale_xy") if pnode else None
            anisotropic = pnode.get("anisotropic") if pnode else None
            effective_font_pt, reason = None, None
            if source_font_pt is None:
                reason = "FONT_SIZE_UNAVAILABLE"
            elif not isinstance(scale_xy, list) or len(scale_xy) != 2:
                reason = "SCALE_UNAVAILABLE"
            elif anisotropic is not False:
                reason = "ANISOTROPIC_SCALE"
            else:
                effective_font_pt = float(source_font_pt) * float(scale_xy[0])
            metrics = {"id": gid, "rect_mm": rect, "source_font_pt": source_font_pt,
                       "source": source, "effective_font_pt": effective_font_pt,
                       "scale_xy": scale_xy, "anisotropic": anisotropic}
            if reason:
                metrics["reason"] = reason
            if node.get("measured") and rect is not None:
                measured.append(metrics)
            else:
                unmeasured.append(gid)
        return {"measured": measured, "unmeasured": unmeasured,
                "note": "Effective point size uses only the captured artist font size; missing actuals stay FONT_SIZE_UNAVAILABLE."}


    def preview(self, layout: dict[str, Any], intent: dict[str, Any], request_id: str | int) -> dict[str, Any]:
        with self._state_lock:
            self._ensure_open()
            if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
                _error("INVALID", "request_id must be a string or integer")
            if self._refresh_required:
                _error("REFRESH_REQUIRED", "saved bytes are newer than the cached frame; reopen before editing",
                       refresh_required=True, refresh_error=self._refresh_error)
            self._generation += 1
            generation = self._generation
            self._invalidate_pending()
        # Only one worker transaction may run; lock waiters re-check the epoch so
        # bursts coalesce to the newest request instead of running stale previews.
        with self._op_lock:
            with self._state_lock:
                self._ensure_open()
                if generation != self._generation:
                    _error("SUPERSEDED", "preview was superseded before execution", generation=generation)
            try:
                canonical_layout = validate_layout(layout)
                self._check_live_freshness()
                current = self._native.snapshot()
                self._check_drift(current)
                controls_list = self._controls(current)
                controls = {control["control_id"]: control for control in controls_list}
                canonical_intent = validate_intent(intent, authorized=controls)
                if canonical_intent["panel_id"] not in {o["id"] for o in canonical_layout["objects"]}:
                    _error("INVALID", f"target panel {canonical_intent['panel_id']!r} is absent from layout")
                panel = next(o for o in canonical_layout["objects"] if o["id"] == canonical_intent["panel_id"])
                if panel["measurement_status"] in {"unknown", "unsupported"} or panel.get("hidden"):
                    _error("UNSUPPORTED_GEOMETRY",
                           "target panel must be visible and measured or conservative before editing",
                           measurement_status=panel["measurement_status"], hidden=panel.get("hidden", False))
                generated, expected_canvas = self._validate_fit(panel, canonical_intent, controls)
                supplied_ids = {edit["control_id"] for edit in canonical_intent["edits"]}
                edits = [{"control_id": item["control_id"], "value": item["value"]}
                         for item in canonical_intent["edits"]]
                edits.extend(item for item in generated if item["control_id"] not in supplied_ids)
                # Numeric roles are intent metadata, never Native authorization inputs.
                request = {"frame_revision": current["frame_revision"], "edits": edits}
                native_result, code = self._native.preview(request)
                if code != 200 or native_result.get("status") != "OK":
                    receipt = native_result.get("receipt") or {}
                    status = receipt.get("status") or native_result.get("status") or "NATIVE_REJECTED"
                    status_map = {"SCIENCE_VIOLATION": "SCIENCE_VIOLATION", "QA_BLOCKED": "QA_BLOCKED",
                                  "STALE_REVISION": "STALE_REVISION", "UNKNOWN_ID": "UNKNOWN_ID",
                                  "OUT_OF_RANGE": "OUT_OF_RANGE"}
                    _error(status_map.get(status, "NATIVE_REJECTED"), native_result.get("message") or str(status),
                           receipt=receipt, diagnostics=native_result.get("diagnostics"))
                frame = native_result["frame"]
                self._check_drift(frame)
                if not (frame.get("science") or {}).get("verified"):
                    _error("SCIENCE_VIOLATION", "candidate science evidence is not verified")
                if expected_canvas is not None:
                    scene, _ = _scene_for_projection(frame)
                    actual = scene["canvas_mm"]
                    if any(abs(actual[i] - expected_canvas[key]) > CANVAS_TOLERANCE_MM
                           for i, key in enumerate(("canvas_w_mm", "canvas_h_mm"))):
                        _error("FIT_UNAVAILABLE", "measured canvas bounds do not match requested target",
                               expected=expected_canvas, actual=actual,
                               tolerance_mm=CANVAS_TOLERANCE_MM)
                scene, scene_nodes = _scene_for_projection(frame)
                projection = project_scene(scene, panel, canonical_layout["page_mm"])
                page_w, page_h = canonical_layout["page_mm"]
                geometry_risks = []
                for node in projection["nodes"]:
                    rect = node.get("rect_mm")
                    if rect is None:
                        geometry_risks.append({"kind": "MEASUREMENT_LIMITED",
                                               "object_id": node["id"],
                                               "reason": node.get("reason")})
                        continue
                    x, y, width, height = rect
                    if x < 0 or y < 0 or x + width > page_w or y + height > page_h:
                        geometry_risks.append({"kind": "PROJECTED_OUTSIDE_PAGE",
                                               "object_id": node["id"], "rect_mm": rect,
                                               "page_mm": [page_w, page_h]})
                required = self._required_content(scene_nodes, canonical_intent["required_content"], projection)
                if required["missing"]:
                    _error("REQUIRED_CONTENT_MISSING", "required content is absent, invisible, cropped, or unmeasured",
                           required_content=required)
                precheck = precheck_layout(canonical_layout, canonical_intent["panel_id"])
                trial = _copy(native_result.get("receipt") or {})
                receipt = {**trial, "candidate_revision": frame.get("candidate_revision"),
                           "source_revision": frame.get("source_revision"),
                           "base_config_revision": frame.get("base_config_revision"),
                           "layout_revision": canonical_layout["revision"], "request_id": request_id,
                           "epoch": generation}
                absolute_qa = trial.get("qa") or []
                baseline_qa = next((check.get("baseline_count") for check in trial.get("checks", [])
                                    if check.get("check") == "render_qa"), None)
                warnings = [risk["kind"] for risk in precheck["risks"] + geometry_risks]
                warnings.append(f"absolute candidate QA reports {len(absolute_qa)} issue(s); "
                                f"{baseline_qa if baseline_qa is not None else 'unknown'} baseline issue(s)")
                limits = ["preview acceptance is not complete layout safety clearance",
                          "host acceptance is NOT_CONNECTED", "export page has not been measured"]
                fonts = self._font_metrics(scene_nodes, projection)
                evidence = {"render": frame.get("evidence", {}).get("render"),
                            "persistence": "NOT_WRITTEN", "host": "NOT_CONNECTED",
                            "export_page": "NOT_RUN"}
                candidate_id = secrets.token_urlsafe(18)
                pending = {"candidate_id": candidate_id, "frame_revision": frame["frame_revision"],
                           "layout_revision": canonical_layout["revision"], "request_id": request_id,
                           "epoch": generation, "candidate_revision": frame.get("candidate_revision"),
                           "source_revision": frame.get("source_revision"),
                           "base_config_revision": frame.get("base_config_revision"),
                           "generation": generation}
                with self._state_lock:
                    if generation != self._generation:
                        self._superseded.add(candidate_id)
                        self._native.cancel({"candidate_id": (self._native.snapshot().get("native", {}).get("pending") or {}).get("candidate_id")})
                        _error("SUPERSEDED", "preview result was superseded", generation=generation)
                    self._pending = pending
                return {"status": "OK", **pending, "frame": self._public_frame(frame),
                        "receipt": receipt, "projection": projection, "precheck": precheck,
                        "geometry_risks": geometry_risks,
                        "required_content": required, "fonts": fonts, "warnings": warnings,
                        "limits": limits, "evidence": evidence}
            except RenderError as error:
                try:
                    self._discard_native_pending()
                except Exception as cleanup_error:
                    raise RenderError(error.status, error.message,
                                      {**error.data, "candidate_discard_error": str(cleanup_error)}) from error
                raise
            except RenderContractError as error:
                mapped = RenderError("INVALID", str(error))
                try:
                    self._discard_native_pending()
                except Exception as cleanup_error:
                    mapped.data["candidate_discard_error"] = str(cleanup_error)
                raise mapped from error
            except Exception as error:
                mapped = RenderError("NATIVE_REJECTED",
                                     f"render preview failed: {type(error).__name__}: {error}")
                try:
                    self._discard_native_pending()
                except Exception as cleanup_error:
                    mapped.data["candidate_discard_error"] = str(cleanup_error)
                raise mapped from error

    def _require_pending(self, candidate_id: str, frame_revision: str,
                         layout_revision: str) -> dict[str, Any]:
        self._ensure_open()
        pending = self._pending
        if pending is None or candidate_id != pending["candidate_id"]:
            if candidate_id in self._stale_candidates:
                _error("STALE_REVISION", "source/config changed; candidate was invalidated")
            status = "CANCELLED" if candidate_id in self._cancelled else (
                "SUPERSEDED" if candidate_id in self._superseded else "CANDIDATE_UNKNOWN")
            _error(status, "candidate is no longer active")
        assert pending is not None
        if (pending["frame_revision"] != frame_revision or pending["layout_revision"] != layout_revision
                or pending["generation"] != self._generation):
            _error("STALE_REVISION", "candidate/frame/layout binding mismatch")
        self._check_live_freshness(pending)
        self._check_drift(self._native.snapshot(), pending)
        return pending

    def cancel(self, candidate_id: str | None = None) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                self._ensure_open()
                if self._refresh_required:
                    _error("REFRESH_REQUIRED", "saved bytes are newer than the cached frame; reopen before editing",
                           refresh_required=True, refresh_error=self._refresh_error)
                pending = self._pending
                if pending is None:
                    if candidate_id is None:
                        view = self._view()
                        return {"status": "cancelled", "frame": view["frame"],
                                "controls": view["controls"], "cancelled": None}
                    _error("CANDIDATE_UNKNOWN", "candidate is not active")
                assert pending is not None
                if candidate_id is not None and candidate_id != pending["candidate_id"]:
                    _error("CANDIDATE_UNKNOWN", "candidate is not active")
                native_pending = (self._native.snapshot().get("native", {}).get("pending") or {})
                self._generation += 1
                self._cancelled.add(pending["candidate_id"])
                self._retired_frames.add(pending["frame_revision"])
                self._pending = None
            native_result, code = self._native.cancel({"candidate_id": native_pending.get("candidate_id")})
            if code != 200:
                live_status = (native_result.get("receipt") or {}).get("status") or native_result.get("status")
                if live_status == "STALE_REVISION":
                    _error("STALE_REVISION", native_result.get("message") or "live source changed; candidate invalidated",
                           receipt=native_result.get("receipt"), diagnostics=native_result.get("diagnostics"))
                _error("NATIVE_REJECTED", native_result.get("message") or "candidate cancellation failed")
            view = self._view()
            return {"status": "cancelled", "frame": view["frame"],
                    "controls": view["controls"], "cancelled": pending["candidate_id"]}

    def commit(self, candidate_id: str, frame_revision: str, layout_revision: str, confirm: bool,
               kind: str = "draft") -> dict[str, Any]:
        with self._op_lock, self._state_lock:
            if confirm is not True:
                _error("CONFIRM_REQUIRED", "commit requires explicit confirm=true; no files were written")
            if kind not in ("draft", "publication"):
                _error("INVALID", "kind must be draft or publication")
            if self._refresh_required:
                _error("REFRESH_REQUIRED", "saved bytes are newer than the cached frame; reopen before editing",
                       refresh_required=True, refresh_error=self._refresh_error)
            pending = self._require_pending(candidate_id, frame_revision, layout_revision)
            native_pending = self._native.snapshot().get("native", {}).get("pending") or {}
            if pending["generation"] != self._generation:
                _error("SUPERSEDED", "candidate was superseded")
            native_result, code = self._native.commit({"candidate_id": native_pending.get("candidate_id"),
                                                       "frame_revision": pending["frame_revision"],
                                                       "kind": kind})
            if code != 200 or native_result.get("status") != "committed":
                if self._pending is pending:
                    self._superseded.add(candidate_id)
                    self._retired_frames.add(pending["frame_revision"])
                    self._pending = None
                    self._generation += 1
                live_status = (native_result.get("receipt") or {}).get("status") or native_result.get("status")
                if live_status == "STALE_REVISION":
                    _error("STALE_REVISION", native_result.get("message") or "live source changed; candidate invalidated",
                           receipt=native_result.get("receipt"), diagnostics=native_result.get("diagnostics"))
                _error("COMMIT_REJECTED", native_result.get("message") or "existing commit chain rejected candidate",
                       receipt=native_result.get("receipt"), diagnostics=native_result.get("diagnostics"))
            self._pending = None
            self._generation += 1
            native_state = native_result.get("native") or {}
            if native_result.get("frame") is None or native_state.get("refresh_required"):
                # Bytes were saved but no fresh accepted frame exists: report the
                # save honestly, do not rebuild from this stale view, and require
                # reopen before export so no bundle is cut from an old frame.
                self._refresh_required = True
                self._refresh_error = native_state.get("refresh_error")
                return {"status": "committed", "kind": kind,
                        "verification": native_result.get("verification"),
                        "frame": None, "receipt": _copy(native_result.get("receipt")),
                        "controls": [], "refresh_required": True,
                        "refresh_error": native_state.get("refresh_error"),
                        "evidence": {"render": "NOT_RUN", "persistence": "WRITTEN",
                                     "host": "NOT_CONNECTED", "export_page": "NOT_RUN"}}
            try:
                view = self._view()
            except Exception as error:
                self._refresh_required = True
                self._refresh_error = f"{type(error).__name__}: {error}"
                return {"status": "committed", "kind": kind,
                        "verification": native_result.get("verification"),
                        "frame": None, "receipt": _copy(native_result.get("receipt")),
                        "controls": [], "refresh_required": True,
                        "refresh_error": self._refresh_error,
                        "evidence": {"render": "NOT_RUN", "persistence": "WRITTEN",
                                     "host": "NOT_CONNECTED", "export_page": "NOT_RUN"}}
            frame = view["frame"] if native_result.get("frame") is not None else None
            assert frame is None or isinstance(frame, dict)
            render_evidence = frame.get("evidence", {}).get("render") if isinstance(frame, dict) else "NOT_RUN"
            return {"status": "committed", "kind": kind,
                    "verification": native_result.get("verification"),
                    "frame": frame, "receipt": _copy(native_result.get("receipt")),
                    "controls": view["controls"],
                    "evidence": {"render": render_evidence,
                                 "persistence": "WRITTEN", "host": "NOT_CONNECTED",
                                 "export_page": "NOT_RUN"}}
    def export(self, output_dir: str | Path, frame_revision: str,
               candidate_id: str | None = None) -> dict[str, Any]:
        with self._op_lock, self._state_lock:
            self._ensure_open()
            if not isinstance(output_dir, (str, Path)) or not str(output_dir):
                _error("INVALID", "export output_dir is required")
            pending = self._pending
            if candidate_id is not None:
                if pending is None or pending["candidate_id"] != candidate_id:
                    if candidate_id in self._stale_candidates:
                        _error("STALE_REVISION", "source/config changed; candidate was invalidated")
                    _error("EXPORT_STALE", "candidate is cancelled, superseded, or unknown")
            if pending is not None:
                if pending["frame_revision"] != frame_revision or pending["generation"] != self._generation:
                    _error("EXPORT_STALE", "export must name the exact active candidate frame")
                self._check_live_freshness(pending)
                self._check_drift(self._native.snapshot(), pending)
                revision = pending["candidate_revision"]
            else:
                self._check_live_freshness()
                if frame_revision in self._retired_frames:
                    _error("EXPORT_STALE", "cancelled or superseded frame cannot be exported")
                frame = self._native.snapshot()
                if frame.get("frame_revision") != frame_revision:
                    _error("EXPORT_STALE", "export frame is not the current accepted frame")
                revision = frame.get("candidate_revision")
            if candidate_id is not None and candidate_id in self._cancelled | self._superseded:
                if candidate_id in self._stale_candidates:
                    _error("STALE_REVISION", "source/config changed; candidate was invalidated")
                _error("EXPORT_STALE", "candidate is cancelled or superseded")
            if self._refresh_required:
                _error("REFRESH_REQUIRED", "saved bytes are newer than the cached frame; reopen before export",
                       refresh_required=True, refresh_error=self._refresh_error)
            try:
                bundle: dict[str, Any] = self._native.export_frame(output_dir, str(revision), frame_revision)
            except Exception as error:
                _error("EXPORT_STALE", f"worker rejected exact-frame export: {error}")
            evidence = {"render": bundle.get("evidence", {}).get("render"),
                        "persistence": bundle.get("evidence", {}).get("persistence"),
                        "host": "NOT_CONNECTED", "export_page": "NOT_RUN"}
            return {"status": "exported", "bundle": bundle, "evidence": evidence}
    def close(self) -> dict[str, Any]:
        with self._op_lock:
            with self._state_lock:
                if self._closed:
                    return {"status": "closed", "already_closed": True}
                self._generation += 1
                self._invalidate_pending()
                self._stale_candidates.clear()
                self._closed = True
            self._native.close()
            return {"status": "closed", "already_closed": False}

    def __enter__(self) -> RenderSession:
        self.open()
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False
