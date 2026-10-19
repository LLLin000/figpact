"""G24 plan adapters: live discovery + engine-only trial. Never commit.

:func:`discover_native` / :func:`discover_overlay` expose the live authorized
controls of an existing session (exact bindings, role, scope, current, range,
impact, source/revision). :func:`validate_candidate` trials one READY plan
through the existing candidate engines only:

- native: ``try_layout`` + ``render_preview`` (existing gates, untouched);
- overlay: existing atomic ``inspect_candidate`` for one or multiple targets.

Trust boundary: :func:`validate_candidate` runs ``edit_plan.check_plan`` first,
so direct callers get the same exact-field / route / scope / revision / ID /
finite-numeric / duplicate / preserve checks as the CLI path. The engines then
judge every edit (unknown paths, ranges, science locks, impact mismatches);
this module invents no controls and parses no natural language.

No official writes: a native trial mutates only in-memory candidate goals;
the caller closes its session. Overlay inspection owns and removes its private
clone in finally; it neither commits nor leaves a pending Inspector candidate.

Honest Native distinction: a trial ``OK`` (even ``GEOMETRY_CHECKED`` /
``RENDER_CHECKED``) is candidate validation only, never publication and never
saved. Publication needs the separate independent strict gate (``commit``
kind=``publication``), which is never invoked here; every receipt carries
``saved=False`` / ``publication_verified=False``.

Revisions are content-bound and deterministic (no timings, PIDs, or randomness):
native uses the candidate hash (stable across freshly rediscovered sessions with
identical inputs, so an offline packet trials cleanly against a fresh CLI
session); overlay uses the rendered ``frame_revision`` plus the official
overlay sha. Stale plans are rejected, never retried.
"""

from __future__ import annotations

import json
import math
from typing import Any

__all__ = ["discover_native", "discover_overlay", "validate_candidate"]

NATIVE_ROUTE = "native"
OVERLAY_ROUTE = "overlay"


def _clean(value: Any) -> Any:
    """JSON-native copy; non-finite floats become None so packets stay hashable."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    return value


def _native_live(session):
    """Live scope/contract/config/revision/snapshot via existing paths only."""
    scope = session.scope
    if hasattr(session, "_worker"):
        # AgentSession exposes no public full-contract record; the existing
        # worker-state channel is used read-only (no try_layout/commit here).
        state = session._call(session._worker.state)
        contract = state.get("contract") or {}
        candidate = state.get("candidate_config") or {}
        revision = state.get("revision")
        base = state.get("base_config_revision")
        source = state.get("source_revision")
    else:
        # FigureSession / FigureWorker duck-typed public surface.
        contract = session.contract or {}
        candidate = session.candidate_config or {}
        revision = session.revision
        base = getattr(session, "base_config_revision", None)
        try:
            source = (session.state() or {}).get("source_revision")
        except Exception:
            source = None
    snapshot = session.snapshot()
    if isinstance(snapshot, dict) and snapshot.get("revision"):
        # Snapshot syncs before reading; its revision is the freshest live
        # value, from the same inputs as the state/config copies above.
        revision = snapshot["revision"]
    return scope, revision, contract, candidate, base, source, snapshot


def discover_native(session) -> dict:
    """Read-only native context: live EDITABLE controls, including declared styles.

    Control ``id`` is the exact config path serialized as compact JSON
    (reversible via ``json.loads``); locks (``LOCKED_SCIENCE`` /
    ``FIXED_STYLE`` / ``DERIVED`` / unclassified) and out-of-scope records are
    never offered. Impact judgement stays with the engine at trial time.
    """
    from figpact.session import get_path

    scope, revision, contract, candidate, base, source, snapshot = _native_live(session)
    if not isinstance(snapshot, dict):
        raise ValueError("native snapshot unavailable")
    controls = []
    for rec in contract.get("parameters") or []:
        if not isinstance(rec, dict) or rec.get("mutability") != "EDITABLE":
            continue
        scopes = rec.get("scopes")
        if scopes is not None and scope not in list(scopes):
            continue
        raw_path = rec.get("path") or []
        if not isinstance(raw_path, (list, tuple)) or not raw_path:
            continue
        path = list(raw_path)
        if any(not isinstance(seg, str) or not seg for seg in path):
            continue
        try:
            current = get_path(candidate, tuple(path))
            unresolved = False
        except (KeyError, ValueError, TypeError):
            current, unresolved = None, True
        expected = rec.get("expected") if isinstance(rec.get("expected"), dict) else {}
        role = expected.get("kind") or rec.get("operation") or "unknown"
        key = rec.get("key") or "/".join(path)
        controls.append({
            "id": json.dumps(path, separators=(",", ":"), ensure_ascii=False),
            "path": path,
            "target_id": None,
            "role": str(role),
            "unit": rec.get("unit"),
            "current": _clean(current),
            "current_unresolved": unresolved,
            "value_shape": "pair" if isinstance(current, (list, tuple)) else "scalar",
            "objects": list(rec.get("objects") or []),
            "scope": scope,
            "key": rec.get("key"),
            "operation": rec.get("operation"),
            "axis": rec.get("axis"),
            "scale": _clean(rec.get("scale", 1.0)),
            "min": _clean(rec.get("min")),
            "max": _clean(rec.get("max")),
            "expected": _clean(expected),
            "description": f"{key} [{rec.get('unit')}] ({role})",
        })
    controls.sort(key=lambda item: item["id"])
    nodes = []
    for node in snapshot.get("nodes") or []:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        nodes.append({"id": node.get("id"), "type": node.get("type"),
                      "parent": node.get("parent"), "scope": node.get("scope"),
                      "bounds_mm": _clean(node.get("bounds_mm"))})
    nodes.sort(key=lambda item: str(item["id"]))
    measurement = snapshot.get("measurement") or {}
    return {
        "route": NATIVE_ROUTE,
        "scope": scope,
        "revision": revision,
        "controls": controls,
        "source": {
            "script": str(getattr(session, "script", "")),
            "config": str(getattr(session, "config", "")),
            "contract_source": (contract or {}).get("source"),
            "base_config_revision": base,
            "source_revision": source,
        },
        "session_context": {
            "nodes": nodes,
            "parameter_index": snapshot.get("parameter_index") or [],
            "measurement": {
                "unit": measurement.get("unit"),
                "dpi": _clean(measurement.get("dpi")),
                "renderer_available": measurement.get("renderer_available"),
                "calibrated": measurement.get("calibrated"),
            },
        },
    }


def _file_sha(path) -> str:
    import hashlib
    from pathlib import Path

    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def discover_overlay(session) -> dict:
    """Read-only overlay context: live session targets joined to identity roles.

    Control ``id`` is the existing target ID. Roles come from the real
    ``style_overlay.inventory`` descriptors (never guessed from the property);
    ranges are the module's declared ``FONTSIZE_RANGE`` / ``LINEWIDTH_RANGE``.
    """
    scope = session.scope
    frame = session.snapshot()
    if not isinstance(frame, dict):
        raise ValueError("overlay snapshot unavailable")
    style = frame.get("style") or {}
    revision = frame.get("frame_revision")
    overlay = getattr(session, "overlay", None)
    sha = _file_sha(overlay) if overlay is not None else ""
    script = getattr(session, "script", None)
    config = getattr(session, "config", None)
    descs: dict = {}
    ranges: dict = {}
    from figpact import style_overlay as ov
    descs = {d["id"]: d for d in ov.inventory(script, config, scope)
             if isinstance(d, dict) and d.get("id")}
    ranges = {"fontsize": ov.FONTSIZE_RANGE, "linewidth": ov.LINEWIDTH_RANGE}
    dependencies = ov._live_dependencies(ov._import_only(script), script, config)
    controls = []
    for target in style.get("targets") or []:
        if not isinstance(target, dict) or not target.get("target_id"):
            continue
        tid = target["target_id"]
        desc = descs.get(tid) or {}
        prop = target.get("property") or desc.get("property")
        bounds = ranges.get(prop, (None, None))
        label = target.get("label") or tid
        controls.append({
            "id": tid,
            "path": None,
            "target_id": tid,
            "role": desc.get("role") or prop,
            "property": prop,
            "unit": "pt",
            "current": _clean(target.get("current_pt")),
            "saved": _clean(target.get("saved_pt")),
            "value_shape": "scalar",
            "objects": list(target.get("scene_ids") or []),
            "scope": scope,
            "min": _clean(bounds[0]),
            "max": _clean(bounds[1]),
            "label": label,
            "display": _clean(desc.get("display")),
            "selector": _clean(desc.get("selector")),
            "description": str(label),
        })
    controls.sort(key=lambda item: item["id"])
    nodes = []
    try:
        scene = json.loads(frame.get("scene_json") or "{}")
        for node in scene.get("nodes") or []:
            if isinstance(node, dict) and node.get("id"):
                nodes.append({"id": node.get("id"), "type": node.get("type"),
                              "bounds_mm": _clean(node.get("bounds_mm"))})
    except ValueError:
        nodes = []
    nodes.sort(key=lambda item: str(item["id"]))
    return {
        "route": OVERLAY_ROUTE,
        "scope": scope,
        "revision": revision,
        "controls": controls,
        "source": {
            "script": str(script),
            "config": str(config) if config is not None else None,
            "overlay": str(overlay),
            "overlay_sha256": sha,
            "dependencies": {name: [str(path), digest]
                             for name, (path, digest) in dependencies.items()},
        },
        "session_context": {
            "frame_revision": revision,
            "overlay_sha256": style.get("overlay_sha256") or sha,
            "issue_count": style.get("issue_count"),
            "nodes": nodes,
        },
    }


def _live_native_revision(session) -> str:
    # Freshest live value via the read-only snapshot path (syncs before reading).
    _scope, revision, _contract, _candidate, _base, _source, _snapshot = _native_live(session)
    if isinstance(revision, str) and revision:
        return revision
    raise ValueError("live native revision unavailable")


def _validate_native(session, context, plan) -> dict:
    live = _live_native_revision(session)
    if context.get("revision") != live or plan.get("revision") != live:
        raise ValueError(
            f"stale revision: context/plan {context.get('revision')!r}/"
            f"{plan.get('revision')!r} != live {live!r}")
    operations = []
    for edit in plan.get("edits") or []:
        try:
            path = json.loads(edit["control_id"])
        except ValueError:
            raise ValueError(f"bad native control id {edit.get('control_id')!r}")
        if not isinstance(path, list) or not path \
                or any(not isinstance(seg, str) for seg in path):
            raise ValueError(f"bad native control id {edit.get('control_id')!r}")
        operations.append({"operation": "set_parameter", "path": path,
                           "value": edit["value"]})
    # Existing gate: failures leave session state untouched; stale races surface
    # as the engine's own STALE verdict/error and are preserved below.
    trial = session.try_layout(operations, revision=plan.get("revision"))
    preview = None
    if isinstance(trial, dict) and trial.get("status") == "OK":
        preview = session.render_preview()
    return {
        "route": NATIVE_ROUTE,
        "status": trial.get("status") if isinstance(trial, dict) else None,
        "verification": trial.get("verification") if isinstance(trial, dict) else None,
        "revision": trial.get("revision") if isinstance(trial, dict) else None,
        "trial": trial,
        "preview": preview,
        "saved": False,
        "publication_verified": False,
        "note": ("candidate trial only: success is not publication and nothing was "
                 "saved; Native publication needs the separate independent strict gate "
                 "(commit kind=publication), never called here; no writes performed; "
                 "caller cleans up with session.close()"),
    }


def _validate_overlay(session, context, plan) -> dict:
    from figpact import style_overlay as ov
    from figpact.inspector_style import _draft_eligible
    if session.snapshot().get("frame_revision") != context["revision"]:
        raise ValueError("stale overlay frame")
    dependencies = ov._live_dependencies(
        ov._import_only(session.script), session.script, session.config)
    live = {name: [str(path), digest] for name, (path, digest) in dependencies.items()}
    if live != context["source"]["dependencies"]:
        raise ValueError("stale source dependencies")
    if _file_sha(session.overlay) != context["source"]["overlay_sha256"]:
        raise ValueError("stale official overlay")
    receipt = ov.inspect_candidate(
        session.script, session.config, session.scope,
        edits=[{"target_id": e["control_id"], "value": e["value"]} for e in plan["edits"]],
        overlay=session.overlay,
        expected_before_sha256=context["source"]["overlay_sha256"] or None)
    whole = receipt.get("figure_verification_state")
    draft, _reason = _draft_eligible(receipt)
    accepted = receipt.get("local_edit_state") == "PASS" and (whole == "PASS" or draft)
    return {"route": OVERLAY_ROUTE, "status": "OK" if accepted else "REFUSED",
            "accepted": accepted, "whole_qa": whole,
            "draft_eligible": bool(draft), "trial": receipt,
            "saved": False, "publication_verified": False,
            "note": "existing read-only batch inspection; no official save or publication"}


def validate_candidate(session, context, plan):
    """Trial one plan through the existing candidate engine; CLARIFY/REFUSE skip.

    Runs ``edit_plan.check_plan`` first (direct-caller trust boundary), returns
    ``None`` without side effects for non-READY plans, and never commits.
    """
    from .edit_plan import check_plan

    check_plan(plan, context)
    if plan.get("status") != "READY":
        return None
    route = plan.get("route")
    if not isinstance(context, dict) or route != context.get("route"):
        raise ValueError("plan route does not match adapter context route")
    if route == NATIVE_ROUTE:
        return _validate_native(session, context, plan)
    if route == OVERLAY_ROUTE:
        return _validate_overlay(session, context, plan)
    raise ValueError(f"unknown route {route!r}")
