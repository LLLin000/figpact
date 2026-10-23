"""G4-C (figpact half): batch acceptance plans over verified candidates.

Composes the G4-B plan (:func:`figpact.acceptance.build_acceptance_plan`) for a
LIST of candidates and adds the batch facts: a deterministic batch id, a
per-candidate manifest, and whole-batch refusal naming every failing
candidate. Like G4-B it never writes a host document, never commits a Native
config, and never imports host code.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from figpact.acceptance import build_acceptance_plan

SCHEMA = "figpact.acceptance-batch-plan/1"

PREPARED = "PREPARED"
REFUSED = "REFUSED"

_LIMITS = ["PREPARED only: the host document was not written and nothing was accepted"]

_IDENTITY_KEYS = ("panel_id", "frame_revision", "candidate_revision", "source_revision")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _candidate_identity(candidate):
    facts = candidate.get("session_facts") or {}
    identity = {}
    for key in _IDENTITY_KEYS:
        value = candidate.get(key)
        if value is None:
            value = facts.get(key)
        identity[key] = value
    return identity


def _derive_batch_id(*, base_revision, candidates, plan_content):
    identities = sorted((_candidate_identity(c) for c in candidates),
                        key=lambda item: json.dumps(item, sort_keys=True, default=str))
    return _digest({"base_revision": base_revision,
                    "candidates": identities, "plan": plan_content})


def _plan_content(plan):
    """Deterministic summary of the prepared plan for batch-id derivation.

    Only deterministic facts go in: the staged PDF bytes are NOT
    byte-reproducible across runs (renderer metadata), so the pdf hash and
    the content-addressed fileId are excluded; everything else that defines
    the batch (panels, revisions, science, config bytes, scopes, patch
    shape) is included.
    """
    staged_scope = {}
    for canvas in (plan.get("next_document") or {}).get("canvases", []):
        for obj in canvas.get("objects", []):
            binding = obj.get("figpact")
            if isinstance(binding, dict):
                staged_scope[obj.get("id")] = binding.get("scope")
    resources = sorted(
        ({"panel_id": resource.get("panel_id"),
          "frame_revision": resource.get("frame_revision"),
          "candidate_revision": resource.get("candidate_revision"),
          "science_digest": resource.get("science_digest"),
          "config_sha256": resource.get("config_sha256"),
          "config_rebuild_verified": bool(resource.get("config_rebuild_verified")),
          "scope": staged_scope.get(resource.get("panel_id")),
          "page_mm": resource.get("page_mm")}
         for resource in plan.get("resources") or []),
        key=lambda item: json.dumps(item, sort_keys=True, default=str),
    )
    patch = plan.get("document_patch") or {}
    updates = sorted(
        ({"panel_id": update.get("panel_id"),
          "fields": sorted((update.get("set") or {}).keys()),
          "scope": ((update.get("set") or {}).get("figpact") or {}).get("scope")}
         for update in patch.get("updates") or []),
        key=lambda item: json.dumps(item, sort_keys=True, default=str),
    )
    return {"resources": resources,
            "patch": {"canvas_id": patch.get("canvas_id"), "updates": updates}}


def _manifest(plan, candidates):
    by_panel = {c.get("panel_id"): c for c in candidates}
    staged = {}
    for canvas in (plan.get("next_document") or {}).get("canvases", []):
        for obj in canvas.get("objects", []):
            if obj.get("id") in by_panel:
                staged[obj["id"]] = obj
    manifest = []
    for resource in plan.get("resources") or []:
        pid = resource.get("panel_id")
        binding = staged.get(pid, {}).get("figpact") or {}
        manifest.append({
            "panel_id": pid,
            "pdf_path": resource.get("path"),
            "pdf_sha256": resource.get("bytes_sha256"),
            "config_path": resource.get("config_path"),
            "config_sha256": resource.get("config_sha256"),
            "config_rebuild_verified": bool(resource.get("config_rebuild_verified")),
            "scope": binding.get("scope"),
            "measured_fonts": (by_panel.get(pid) or {}).get("measured_fonts", []),
            "frame_revision": resource.get("frame_revision"),
        })
    return sorted(manifest, key=lambda item: item["panel_id"])


def _project_root(host_document):
    host_document = host_document or {}
    if host_document.get("project_root"):
        return Path(host_document["project_root"]).expanduser().resolve()
    identity = host_document.get("identity", host_document)
    if isinstance(identity, dict) and identity.get("path"):
        return Path(identity["path"]).parent.resolve()
    return None


def _attribute_failures(candidates, *, host_document, base_revision,
                        expected_document_revision, first_failure):
    """Name every failing candidate via isolated single-candidate probes.

    Probes stage into a throwaway directory inside the project root that is
    always removed, so attribution never leaves files behind.
    """
    root = _project_root(host_document)
    if root is None:
        return ([{"panel_id": c.get("panel_id"), "reason": first_failure}
                 for c in candidates], [])
    probe_root = Path(tempfile.mkdtemp(prefix="batch-diagnostics-", dir=str(root)))
    try:
        failures = []
        for index, candidate in enumerate(candidates):
            probe = probe_root / f"candidate-{index}"
            probe.mkdir(parents=True, exist_ok=True)
            try:
                single = build_acceptance_plan(
                    [candidate], host_document=host_document,
                    base_revision=base_revision, resources_dir=probe,
                    expected_document_revision=expected_document_revision)
            except Exception as exc:  # pragma: no cover - G4-B reports, not raises
                failures.append({"panel_id": candidate.get("panel_id"),
                                 "reason": f"{type(exc).__name__}: {exc}"})
                continue
            if single["status"] == "REFUSED":
                failures.append({"panel_id": candidate.get("panel_id"),
                                 "reason": (single.get("evidence") or {}).get("first_failure")})
        if not failures:
            # Global refusal (e.g. stale base revision): the whole batch fails.
            failures = [{"panel_id": c.get("panel_id"), "reason": first_failure}
                        for c in candidates]
        return failures, [str(probe_root)]
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)


def build_batch_acceptance_plan(candidates, *, host_document, base_revision, resources_dir,
                                expected_document_revision=None, batch_id=None) -> dict:
    """Prepare immutable resources for every candidate and one combined change."""
    ordered = list(candidates or [])
    panel_ids = [c.get("panel_id") for c in ordered]

    def refused(*, first_failure, failures, plan=None, cleaned_up=(), preconditions=None):
        host = (plan or {}).get("host") or {}
        canvas_id = host.get("canvas_id")
        if canvas_id is None:
            doc = (host_document or {}).get("document", host_document or {})
            canvas_ids = [c.get("id") for c in doc.get("canvases", [])]
            canvas_id = doc.get("activeCanvasId") or (canvas_ids[0] if len(canvas_ids) == 1 else None)
        evidence = (plan or {}).get("evidence") or {}
        staging = evidence.get("staging_dir") or str(Path(resources_dir).expanduser().resolve())
        content = {"resources": [], "patch": {"canvas_id": canvas_id, "updates": []}}
        return {
            "schema": SCHEMA, "status": REFUSED, "state": REFUSED,
            "batch_id": batch_id or _derive_batch_id(
                base_revision=base_revision, candidates=ordered, plan_content=content),
            "host": {"document_id": host.get("document_id"), "base_revision": base_revision,
                      "canvas_id": canvas_id, "panel_ids": panel_ids},
            "preconditions": preconditions if preconditions is not None
            else (plan or {}).get("preconditions", []),
            "failures": failures, "resources": [],
            "document_patch": {"canvas_id": canvas_id, "updates": []},
            "manifest": [], "next_document": None, "limits": list(_LIMITS),
            "evidence": {"staging_dir": staging, "prepared_files": [],
                         "first_failure": first_failure,
                         "plan_id": (plan or {}).get("plan_id"),
                         "cleaned_up": list(cleaned_up)},
        }

    if not ordered:
        check = {"name": "empty_batch", "expected": "at least one candidate",
                 "observed": {"candidates": 0}, "ok": False}
        return refused(first_failure="empty_batch", failures=[], preconditions=[check])

    seen, dupes = set(), set()
    for pid in panel_ids:
        if pid in seen:
            dupes.add(pid)
        seen.add(pid)
    if dupes:
        check = {"name": "duplicate_panel_id",
                 "expected": "every candidate targets a distinct panel",
                 "observed": {"duplicate_panel_ids": sorted(dupes, key=str)}, "ok": False}
        return refused(
            first_failure="duplicate_panel_id",
            failures=[{"panel_id": c.get("panel_id"), "reason": "duplicate_panel_id"}
                      for c in ordered if c.get("panel_id") in dupes],
            preconditions=[check])

    plan = build_acceptance_plan(
        ordered, host_document=host_document, base_revision=base_revision,
        resources_dir=resources_dir, expected_document_revision=expected_document_revision)
    if plan["status"] == "READY":
        content = _plan_content(plan)
        return {
            "schema": SCHEMA, "status": "READY", "state": PREPARED,
            "batch_id": batch_id or _derive_batch_id(
                base_revision=base_revision, candidates=ordered, plan_content=content),
            "host": {"document_id": plan["host"].get("document_id"),
                      "base_revision": base_revision,
                      "canvas_id": plan["host"].get("canvas_id"), "panel_ids": panel_ids},
            "preconditions": plan["preconditions"], "failures": [],
            "resources": plan["resources"], "document_patch": plan["document_patch"],
            "manifest": _manifest(plan, ordered), "next_document": plan["next_document"],
            "limits": list(_LIMITS),
            "evidence": {"staging_dir": plan["evidence"]["staging_dir"],
                         "prepared_files": plan["evidence"]["prepared_files"],
                         "first_failure": None, "plan_id": plan["plan_id"],
                         "cleaned_up": []},
        }
    first_failure = plan["evidence"]["first_failure"]
    failures, cleaned_up = _attribute_failures(
        ordered, host_document=host_document, base_revision=base_revision,
        expected_document_revision=expected_document_revision, first_failure=first_failure)
    return refused(first_failure=first_failure, failures=failures,
                   plan=plan, cleaned_up=cleaned_up)
