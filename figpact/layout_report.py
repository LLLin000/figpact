"""Read-only G3-A/B reports over measured figures and one explicit page snapshot.

The caller owns the sessions and supplies source bindings from its host adapter.
A report is about the named snapshot, never proof of an actively locked page.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .frame_binding import FrameBindingError, bind_frame
from .render_api import RenderError, RenderSession
from .render_contract import validate_layout
from .role_report import capability_report
from .spatial_report import spatial_report


class LayoutReportError(ValueError):
    """A refused report; no figure or page changes have been requested."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def _ids(values: Any, known: set[str], what: str) -> list[str]:
    if (not isinstance(values, (list, tuple)) or not values
            or any(not isinstance(value, str) or value not in known for value in values)
            or len(set(values)) != len(values)):
        raise LayoutReportError("INVALID", f"{what} must be nonempty, unique existing object ids")
    return list(values)


def _source_binding(session: RenderSession, source: Any) -> None:
    if not isinstance(source, Mapping):
        raise LayoutReportError("UNSUPPORTED", "no adapter-confirmed source binding for managed session")
    if source.get("overrides_present") is not False:
        raise LayoutReportError("UNSUPPORTED", "host overrides are present or unknown; no replay was proved")
    for key in ("script", "config"):
        value = source.get(key)
        if not isinstance(value, str) or not value.strip():
            raise LayoutReportError("UNSUPPORTED", f"adapter source binding lacks {key}")
        if Path(value).expanduser().resolve() != Path(getattr(session, key)).resolve():
            raise LayoutReportError("STALE", f"managed {key} does not match the adapter source binding")
    if not isinstance(source.get("scope"), str) or source["scope"] != session.scope:
        raise LayoutReportError("STALE", "managed scope does not match the adapter source binding")


def _view_identity(view: dict[str, Any], session: RenderSession) -> tuple[Any, ...]:
    frame, source = view.get("frame"), view.get("source")
    if not isinstance(frame, dict) or not isinstance(source, dict):
        raise LayoutReportError("UNSUPPORTED", "renderer did not supply a measured frame and source")
    if view.get("pending"):
        raise LayoutReportError("UNSUPPORTED", "a pending candidate is not the accepted figure baseline")
    if (view.get("revision") != frame.get("candidate_revision")
            or source.get("source_revision") != frame.get("source_revision")
            or source.get("base_config_revision") != frame.get("base_config_revision")
            or view.get("scope") != session.scope or frame.get("scope") != session.scope):
        raise LayoutReportError("STALE", "source/config/scope and measured frame belong to different revisions")
    for key in ("script", "config"):
        value = source.get(key)
        if not isinstance(value, str) or Path(value).resolve() != Path(getattr(session, key)).resolve():
            raise LayoutReportError("STALE", f"renderer {key} provenance differs from its session")
    if not isinstance(view.get("controls"), list):
        raise LayoutReportError("UNSUPPORTED", "renderer did not supply authorized scalar controls")
    return tuple(frame.get(key) for key in (
        "frame_revision", "candidate_revision", "source_revision", "base_config_revision"))


def report_layout(
    layout: dict[str, Any], target_ids: Sequence[str],
    sessions: Mapping[str, RenderSession] | None = None, *,
    expected_revision: str,
    source_bindings: Mapping[str, dict[str, Any]] | None = None,
    regions: Sequence[dict[str, Any]] = (),
    required_content: Mapping[str, list[str]] | None = None,
    refresh_layout: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Measure authorized managed figures without previewing, saving or moving them.

    ``source_bindings`` are trusted host-adapter facts (script/config/scope and
    explicit overrides_present=False), not paths discovered from a stale asset.
    ``refresh_layout`` re-reads the caller's SAME producer before and after the
    measurements. A saved producer remains saved; a cached live capture remains
    a capture. Neither callback availability nor READY implies host acceptance.
    Caller-owned sessions are left open, with no candidate or source edits.
    """
    canonical = validate_layout(layout)
    if not isinstance(expected_revision, str) or expected_revision != canonical["revision"]:
        raise LayoutReportError("STALE", "requested page revision does not match this snapshot")
    objects = {item["id"]: item for item in canonical["objects"]}
    targets = _ids(target_ids, set(objects), "target_ids")
    sessions = {} if sessions is None else sessions
    source_bindings = {} if source_bindings is None else source_bindings
    if not isinstance(sessions, Mapping) or set(sessions) - set(targets):
        raise LayoutReportError("INVALID", "sessions must map selected target ids only")
    if not isinstance(source_bindings, Mapping) or set(source_bindings) - set(sessions):
        raise LayoutReportError("INVALID", "source bindings must map configured sessions only")
    if not isinstance(regions, (list, tuple)):
        raise LayoutReportError("INVALID", "regions must be a list of explicit region declarations")
    if required_content is not None:
        if not isinstance(required_content, Mapping) or set(required_content) - set(targets):
            raise LayoutReportError("INVALID", "required_content must map selected target ids only")
        for ids in required_content.values():
            if (not isinstance(ids, list) or any(not isinstance(gid, str) or not gid for gid in ids)
                    or len(set(ids)) != len(ids)):
                raise LayoutReportError("INVALID", "required content ids must be unique nonempty strings")
        required_content = {panel_id: list(ids) for panel_id, ids in required_content.items()}

    def recheck_layout() -> None:
        if refresh_layout is not None:
            try:
                fresh = validate_layout(refresh_layout())
            except (ValueError, OSError) as exc:
                raise LayoutReportError("STALE", f"page producer could not revalidate its snapshot: {exc}") from exc
            if fresh["revision"] != expected_revision:
                raise LayoutReportError("STALE", "page or referenced resource facts changed during report")

    recheck_layout()
    observations: dict[str, dict[str, Any]] = {}
    identities: dict[str, tuple[Any, ...]] = {}
    panel_reports: list[dict[str, Any]] = []
    for panel_id in targets:
        panel = objects[panel_id]
        entry: dict[str, Any] = {
            "panel_id": panel_id, "kind": panel.get("kind"),
            "render_owner": panel.get("render_owner"), "rect_mm": copy.deepcopy(panel["rect_mm"]),
            "access": "SPACE_ONLY", "status": "UNSUPPORTED", "reason": "NO_MEASURED_MANAGED_FRAME",
        }
        session = sessions.get(panel_id)
        if session is not None:
            if panel.get("render_owner") != "figpact" or panel.get("kind") != "panel":
                raise LayoutReportError("UNSUPPORTED", f"{panel_id}: legacy/opaque objects cannot use a second renderer")
            _source_binding(session, source_bindings.get(panel_id))
            if (panel["hidden"] or panel["rect_mm"] is None
                    or panel["measurement_status"] in ("unknown", "unsupported")
                    or panel["rotation_deg"] is None):
                entry["reason"] = "HIDDEN_OR_UNPROJECTABLE_TARGET"
                panel_reports.append(entry)
                continue
            try:
                view = session.snapshot()
                identities[panel_id] = _view_identity(view, session)
                bound = bind_frame(canonical, panel_id, view["frame"], request_id=0)
            except RenderError as exc:
                status = "STALE" if exc.status in ("STALE_REVISION", "REFRESH_REQUIRED") else exc.status
                raise LayoutReportError(status, f"{panel_id}: {exc}") from exc
            except FrameBindingError as exc:
                raise LayoutReportError("UNSUPPORTED", f"{panel_id}: {exc}") from exc
            science = view["frame"].get("science") or {}
            editable = not panel["locked"] and science.get("verified") is True
            observation = {
                "frame": view["frame"], "controls": view["controls"],
                "binding": bound["binding"], "projection": bound["projection"], "editable": editable,
            }
            observations[panel_id] = observation
            capability = capability_report(view["frame"], view["controls"], bound["projection"], editable=editable)
            entry.update(status=capability["status"], capabilities=capability,
                         binding=bound["binding"], science=copy.deepcopy(science),
                         access="MEASURED_MANAGED" if editable else "MEASUREMENT_ONLY")
            entry.pop("reason", None)
        panel_reports.append(entry)

    spatial = spatial_report(canonical, targets, observations, regions=regions,
                             required_content=required_content)
    # Re-read all source/config/frame identities after every measured target has
    # completed. Source guards stay in RenderSession; no refresh/retry hides drift.
    for panel_id, identity in identities.items():
        try:
            fresh_view = sessions[panel_id].snapshot()
            if _view_identity(fresh_view, sessions[panel_id]) != identity:
                raise LayoutReportError("STALE", f"{panel_id}: measured frame changed during report")
        except RenderError as exc:
            status = "STALE" if exc.status in ("STALE_REVISION", "REFRESH_REQUIRED") else exc.status
            raise LayoutReportError(status, f"{panel_id}: {exc}") from exc
    recheck_layout()
    statuses = {entry["status"] for entry in panel_reports} | {spatial["status"]}
    status = ("CONSTRAINT_VIOLATION" if "CONSTRAINT_VIOLATION" in statuses else
              "UNSUPPORTED" if "UNSUPPORTED" in statuses else "READY")
    return {
        "schema": "figpact.layout-report/1", "status": status,
        "snapshot": {key: canonical.get(key) for key in (
            "revision", "source_mode", "project_id", "page_id", "host_revision", "page_mm")},
        "currentness": "SNAPSHOT_BOUND",
        "producer_rechecked": refresh_layout is not None,
        "counts": {"objects": len(objects), "panels": sum(o.get("kind") == "panel" for o in objects.values()),
                   "targets": len(targets), "measured_frames": len(observations)},
        "targets": panel_reports, "spatial": spatial,
        "evidence": {"render": "RENDER_CHECKED" if observations else "NOT_RUN",
                     "persistence": "NOT_WRITTEN", "page": "NOT_CHANGED",
                     "host": "NOT_VERIFIED", "export_page": "NOT_RUN"},
        "limits": ["READY means a report was measured, not an optimized or accepted layout",
                   "as-of snapshot only; saved files and cached handoffs are not active-page locks",
                   "source bindings are host-adapter facts; unmanaged runtime execution is not supported",
                   "no candidate search, scientific/view edits, page changes or final export verification"],
    }
