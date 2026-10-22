"""G4-A: prepared acceptance plans for VERIFIED panel candidates (never applied).

figpact proves "this figure may be changed this way"; the host proves "this
current page has actually adopted the result". This module is the figpact
half: it turns verified candidates into immutable, hashed resources plus the
minimal document change, and it checks every stale precondition BEFORE
anything is staged.

It never writes a host document, never commits a Native config, never mutates
a page, and never imports host code. The host applies the page reference
itself, in one whole-document operation, and confirms the save.

Resource order is the whole point: resources are prepared and hashed first,
so the page can never point at bytes that were not fully produced. The
prepared reference is relative to the project root, because that is how the
host resolves a panel's file.

Status vocabulary for the whole of G4: PREPARED -> HOST_APPLIED ->
HOST_PERSISTED -> REOPEN_VERIFIED -> FINAL_EXPORT_VERIFIED (G5). This
module only ever produces PREPARED.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import uuid

_PRECONDITIONS = (
    "document_identity", "candidate_freshness", "panel_identity_ownership",
    "panel_placement", "uniform_scale", "required_content",
    "resource_preparation", "document_patch_minimality",
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode()).hexdigest()


NATIVE_TOL_MM = 0.05


def _eq(a, b):
    return a == b


def _placement(record):
    return {k: record.get(k) for k in ("nativeW", "nativeH", "crop", "rotation", "flipH", "flipV", "x", "y", "w", "h")}


def _same_placement(candidate, host):
    expected = candidate.get("placement") or candidate.get("bound_panel")
    if expected is None:
        expected = {k: candidate[k] for k in _placement(host) if k in candidate}
        native = candidate.get("native_size_mm")
        rect = candidate.get("rect_mm")
        if native is not None and len(native) == 2:
            expected.update(nativeW=native[0], nativeH=native[1])
        if rect is not None and len(rect) == 4:
            expected.update(zip(("x", "y", "w", "h"), rect))
        for source, target in (("rotation_deg", "rotation"), ("flip_h", "flipH"), ("flip_v", "flipV")):
            if source in candidate:
                expected[target] = candidate[source]
    observed = _placement(host)
    expected = {k: expected.get(k) for k in observed}
    return expected, observed, all(_eq(expected[k], observed[k]) for k in observed)


def _find_record(doc, panel_id):
    for canvas in doc.get("canvases", []):
        for obj in canvas.get("objects", []):
            if obj.get("id") == panel_id:
                return canvas, obj
    return None, None


def _diff_paths(a, b, path=()):
    if type(a) is not type(b):
        return {path}
    if isinstance(a, dict):
        out = set()
        for key in a.keys() | b.keys():
            if key not in a or key not in b:
                out.add(path + (key,))
            else:
                out |= _diff_paths(a[key], b[key], path + (key,))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return {path}
        return set().union(*(_diff_paths(x, y, path + (i,)) for i, (x, y) in enumerate(zip(a, b))), set())
    return set() if a == b else {path}


def _scene_ids(frame):
    try:
        scene = json.loads(frame["scene_json"])
        return {str(node.get("gid") or node.get("id")) for node in scene.get("nodes", [])}
    except (KeyError, TypeError, ValueError):
        return set()


def build_acceptance_plan(candidates, *, host_document, base_revision, resources_dir,
                          expected_document_revision=None) -> dict:
    """Prepare (never apply) exact-frame resources and a minimal schema-3 document."""
    doc = host_document.get("document", host_document)
    identity = host_document.get("identity", host_document)
    project_root = Path(host_document.get("project_root", Path(identity.get("path", ".")).parent)).resolve()
    staging = Path(resources_dir).expanduser().resolve()
    plan_id = _digest({"base_revision": base_revision, "candidates": [
        {k: c.get(k) for k in ("panel_id", "frame_revision", "candidate_revision", "source_revision")}
        for c in candidates]})[:32]
    host_revision = identity.get("revision", host_document.get("revision"))
    canvas_ids = [c.get("id") for c in doc.get("canvases", [])]
    canvas_id = doc.get("activeCanvasId") or (canvas_ids[0] if len(canvas_ids) == 1 else None)
    expected_identity = {"revision": base_revision, "expected_document_revision": expected_document_revision}
    observed_identity = {"revision": host_revision, "expected_document_revision": expected_document_revision}
    checks = [{"name": _PRECONDITIONS[0], "expected": expected_identity,
               "observed": observed_identity,
               "ok": host_revision == base_revision and (expected_document_revision is None or host_revision == expected_document_revision)}]
    facts_by_panel = {}
    for c in candidates:
        session = c.get("session")
        supplied = c.get("session_facts") or {}
        try:
            current = session.snapshot()["frame"] if session is not None else None
        except Exception:
            current = None
        expected = {k: c.get(k) for k in ("frame_revision", "candidate_revision", "source_revision", "base_config_revision")}
        expected["science_digest"] = c.get("science_digest")
        observed = {k: (current or {}).get(k) for k in ("frame_revision", "candidate_revision", "source_revision", "base_config_revision")}
        observed["science_digest"] = ((current or {}).get("science") or {}).get("digest")
        # The caller's captured accepted-frame facts must bind the receipt; session snapshot is the live authority.
        facts_ok = bool(session is not None and supplied and all(
            supplied.get(k) == v for k, v in expected.items() if v is not None))
        live_ok = bool(current and all(observed[k] == v for k, v in expected.items() if v is not None)
                       and (current.get("science") or {}).get("verified") is True)
        facts_by_panel[c.get("panel_id")] = {"current": current, "expected": expected}
        if not facts_ok or not live_ok:
            checks.append({"name": _PRECONDITIONS[1], "expected": expected,
                           "observed": {"supplied_session_facts": supplied, "live_session": observed,
                                        "science_verified": bool((current or {}).get("science", {}).get("verified"))},
                           "ok": False})
            break
    if not any(x["name"] == _PRECONDITIONS[1] for x in checks):
        checks.append({"name": _PRECONDITIONS[1], "expected": {c["panel_id"]: facts_by_panel[c["panel_id"]]["expected"] for c in candidates},
                       "observed": {c["panel_id"]: facts_by_panel[c["panel_id"]]["expected"] for c in candidates}, "ok": True})
    panel_data = {}
    for c in candidates:
        pid = c.get("panel_id")
        canvas, record = _find_record(doc, pid)
        binding = record.get("figpact") if record else None
        script = c.get("script") or (c.get("session_facts") or {}).get("script")
        config = c.get("config") or (c.get("session_facts") or {}).get("config")
        scope = c.get("scope") or (c.get("session_facts") or {}).get("scope")
        facts = facts_by_panel.get(pid, {}).get("current") or {}
        scale = c.get("scale_xy") or (c.get("binding") or {}).get("scale_xy")
        if not scale:
            crop = (record or {}).get("crop")
            nw, nh = (record or {}).get("nativeW"), (record or {}).get("nativeH")
            rotation = (record or {}).get("rotation", 0)
            if crop and nw and nh:
                cw, ch = crop["w"] * nw, crop["h"] * nh
            else:
                cw, ch = nw, nh
            w, h = (record or {}).get("w"), (record or {}).get("h")
            scale = [((h / cw) if rotation in (90, 270) else (w / cw)),
                     ((w / ch) if rotation in (90, 270) else (h / ch))] if cw and ch and w and h else None
        required = c.get("required_content", [])
        scene_ids = _scene_ids(facts) if facts else set()
        identity_ok = bool(record and record.get("type") == "panel" and not record.get("hidden", False)
                           and record.get("renderOwner") == "figpact" and isinstance(binding, dict)
                           and binding.get("config") == config and binding.get("scope") == scope
                           and record.get("script") == script and not record.get("overrides"))
        panel_data[pid] = (canvas, record, c, scale, required, scene_ids)
        # each category gets one report row aggregating all candidates
    checks.extend([
        {"name": _PRECONDITIONS[2], "expected": {pid: {"type": "panel", "visible": True, "renderOwner": "figpact", "figpact": {"script": c.get("script"), "config": c.get("config"), "scope": c.get("scope")}, "overrides": []} for pid, (_, _, c, _, _, _) in panel_data.items()},
         "observed": {pid: ({"type": r.get("type"), "visible": not r.get("hidden", False), "renderOwner": r.get("renderOwner"), "figpact": r.get("figpact"), "script": r.get("script"), "overrides": r.get("overrides", [])} if r else None) for pid, (_, r, *_rest) in panel_data.items()}, "ok": all(bool(r and r.get("type") == "panel" and not r.get("hidden", False) and r.get("renderOwner") == "figpact" and isinstance(r.get("figpact"), dict) and r["figpact"].get("config") == (c.get("config") or (c.get("session_facts") or {}).get("config")) and r["figpact"].get("scope") == (c.get("scope") or (c.get("session_facts") or {}).get("scope")) and r.get("script") == (c.get("script") or (c.get("session_facts") or {}).get("script")) and not r.get("overrides", [])) for pid, (_, r, c, *_rest) in panel_data.items())},
        {"name": _PRECONDITIONS[3], "expected": {pid: (c.get("placement") or c.get("bound_panel")) for pid, (_, _, c, *_rest) in panel_data.items()}, "observed": {pid: _placement(r) if r else None for pid, (_, r, *_rest) in panel_data.items()}, "ok": all(_same_placement(c, r or {})[2] for _, r, c, *_rest in panel_data.values())},
        {"name": _PRECONDITIONS[4], "expected": {pid: "equal positive scales" for pid in panel_data}, "observed": {pid: scale for pid, (_, _, _, scale, *_rest) in panel_data.items()}, "ok": all(scale and len(scale) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in scale) and math.isclose(scale[0], scale[1], rel_tol=1e-9, abs_tol=1e-9) for _, _, _, scale, *_rest in panel_data.values())},
        {"name": _PRECONDITIONS[5], "expected": {pid: required for pid, (_, _, _, _, required, _) in panel_data.items()}, "observed": {pid: sorted(set(ids) & scene) for pid, (_, _, _, _, ids, scene) in panel_data.items()}, "ok": all(set(required) <= scene for _, _, _, _, required, scene in panel_data.values())},
    ])
    first_failure = next((row["name"] for row in checks if not row["ok"]), None)
    # 资源必须**先于**页面引用存在且可被宿主解析：宿主按项目根解析 fileId，
    # 所以暂存目录必须在项目根内，引用路径才真的指向那份字节。
    staging_inside_project = False
    try:
        staging_inside_project = staging.is_relative_to(project_root)
    except (AttributeError, ValueError):
        staging_inside_project = False
    resource_failure: str | None = None
    if not staging_inside_project:
        resource_failure = ("staging dir is outside the project root: the host resolves "
                            "fileId from there, so the reference would not point at the bytes")
    resources, updates, prepared = [], [], []
    next_doc = copy.deepcopy(doc)
    if first_failure is None and resource_failure is None:
        try:
            staging.mkdir(parents=True, exist_ok=True)
            for c in candidates:
                pid = c["panel_id"]
                session = c["session"]
                export_root = staging / f"export-{uuid.uuid4().hex}"
                export_root.mkdir()
                exported = session.export(export_root, c["frame_revision"], c.get("candidate_id"))
                bundle = exported["bundle"]
                # 页面几何依赖面板存的 nativeW/nativeH：新资源的实测页尺寸必须与之一致，
                # 否则换资源后页面展示的版面变了，候选的实测有效字号不再描述这页。
                _, record = _find_record(next_doc, pid)
                stored_native = ((record or {}).get("nativeW"), (record or {}).get("nativeH"))
                page_mm = bundle.get("page_mm") or []
                if (isinstance(stored_native[0], (int, float)) and isinstance(stored_native[1], (int, float))
                        and stored_native[0] > 0 and stored_native[1] > 0):
                    if (not isinstance(page_mm, list) or len(page_mm) != 2
                            or any(not isinstance(v, (int, float)) or v <= 0 for v in page_mm)):
                        raise ValueError(f"{pid}: prepared PDF has no measured page size")
                    if (abs(float(page_mm[0]) - float(stored_native[0])) > NATIVE_TOL_MM
                            or abs(float(page_mm[1]) - float(stored_native[1])) > NATIVE_TOL_MM):
                        raise ValueError(
                            f"{pid}: prepared PDF page {list(page_mm)} mm differs from the panel's "
                            f"stored native size {list(stored_native)} mm; the measured candidate "
                            "does not describe this placement")
                src = Path(bundle["pdf_path"])
                data = src.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                dest_dir = staging / "figpact-resources" / plan_id
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f"{digest}.pdf"
                relative = dest.relative_to(project_root).as_posix()
                if dest.exists():
                    if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                        raise OSError("existing staged resource hash mismatch")
                else:
                    with dest.open("xb") as stream:
                        stream.write(data)
                if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                    raise OSError("staged resource hash mismatch")
                prepared.append(str(dest))
                resources.append({"panel_id": pid, "kind": "pdf", "path": relative,
                                  "staging_path": str(dest), "bytes_sha256": digest,
                                  "page_mm": bundle["page_mm"], "frame_revision": bundle["frame_revision"],
                                  "candidate_revision": bundle["candidate_revision"],
                                  "science_digest": bundle["science_digest"],
                                  "measured_fonts": c.get("measured_fonts", [])})
                _, record = _find_record(next_doc, pid)
                set_fields = {"fileId": relative}
                if record.get("fileKind") != "pdf":
                    set_fields["fileKind"] = "pdf"
                record.update(set_fields)
                updates.append({"panel_id": pid, "set": set_fields})
        except Exception as exc:
            resource_failure = f"{type(exc).__name__}: {exc}"
            for path in prepared:
                try:
                    Path(path).unlink()
                except OSError:
                    pass
            prepared.clear()
            resources.clear()
            updates.clear()
            next_doc = copy.deepcopy(doc)
    checks.append({"name": _PRECONDITIONS[6],
                   "expected": "all exact-frame PDF resources staged and hashed inside the project root",
                   "observed": ({"prepared_files": prepared} if resource_failure is None
                                else {"error": resource_failure,
                                      "staging_dir": str(staging),
                                      "project_root": str(project_root)}),
                   "ok": resource_failure is None})
    if first_failure is None and resource_failure is not None:
        first_failure = _PRECONDITIONS[6]
    allowed = {("canvases", i, "objects", j, key) for pid, update in ((u["panel_id"], u) for u in updates)
               for i, canvas in enumerate(doc.get("canvases", [])) for j, obj in enumerate(canvas.get("objects", []))
               if obj.get("id") == pid for key in update["set"]}
    diffs = _diff_paths(doc, next_doc)
    minimal = all(path in allowed for path in diffs)
    # 补丁最小性只回答"这份补丁是否只改了点名的字段"。计划被**别的前置条件**
    # 拒绝时没有补丁可言，那不是最小性失败，而是"没走到这一步"。
    checks.append({"name": _PRECONDITIONS[7],
                   "expected": sorted("/".join(map(str, p)) for p in allowed),
                   "observed": sorted("/".join(map(str, p)) for p in diffs),
                   "ok": (minimal and len(updates) == len(candidates)) if first_failure is None else True,
                   "state": "CHECKED" if first_failure is None else "NOT_REACHED"})
    if first_failure is None and not (minimal and len(updates) == len(candidates)):
        first_failure = _PRECONDITIONS[7]
    if first_failure is None:
        try:
            if next_doc.get("schema") != 3:
                raise ValueError("ProjectDocument schema must be 3")
            # Host ProjectDocument is validated structurally here without host-specific dependencies.
            if not isinstance(next_doc.get("canvases"), list) or not next_doc.get("canvases"):
                raise ValueError("ProjectDocument requires canvases")
            status = "READY"
        except Exception as exc:
            status = "REFUSED"
            first_failure = _PRECONDITIONS[7]
            checks[-1]["ok"] = False
            checks[-1]["observed"] = {"diffs": checks[-1]["observed"], "schema_error": str(exc)}
    else:
        status = "REFUSED"
    return {"schema": "figpact.acceptance-plan/1", "status": status, "stage": "PLANNED",
            "state": "PREPARED" if status == "READY" else "REFUSED",
            "plan_id": plan_id, "host": {"document_id": identity.get("document_id"),
                "path": identity.get("path"), "base_revision": base_revision,
                "document_schema": doc.get("schema"), "canvas_id": canvas_id,
                "panel_ids": [c.get("panel_id") for c in candidates]},
            "preconditions": checks, "resources": resources,
            "document_patch": {"canvas_id": canvas_id, "updates": updates},
            "next_document": next_doc if status == "READY" else None,
            "limits": ["PREPARED only: the host document was not written and nothing was accepted",
                       "the host's content-hash revision is the save authority, not updatedAt",
                       "resources are staged and hashed; the host applies the page reference itself",
                       "a refused plan names the failing precondition and staged nothing"],
            "evidence": {"staging_dir": str(staging), "prepared_files": prepared,
                         "first_failure": first_failure}}
