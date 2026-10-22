"""G4-A: prepared acceptance plans for VERIFIED panel candidates (never applied).

figpact proves "this figure may be changed this way"; the host proves "this
current page has actually adopted the result". This module is the figpact
half: it turns verified candidates into immutable, hashed resources plus the
minimal document change, and it checks every stale precondition BEFORE
anything is staged.

It never writes a host document, never commits a Native config, never mutates
a page, and never imports host code. The host applies the page reference
itself, in one whole-document operation, and confirms the save.

Resource order is the whole point: resources are produced and hashed first,
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
import os
from pathlib import Path
import tempfile
import uuid

_PRECONDITIONS = (
    "document_identity", "candidate_freshness", "panel_identity_ownership",
    "panel_placement", "uniform_scale", "required_content",
    "config_persisted", "panel_binding_update",
    "resource_preparation", "document_patch_minimality",
)

#: Native-canvas equality tolerance when the prepared PDF is checked against
#: the panel's stored native size. The values come from a measured pypdf page
#: box versus the host's stored floats, so this absorbs serialization noise.
NATIVE_TOL_MM = 0.05

#: Rebuilt-config equality tolerance for effective point size.
FONT_TOL_PT = 0.01


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode()).hexdigest()


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
    return expected, observed, all(expected[k] == observed[k] for k in observed)


def _find_records(doc, panel_id):
    return [(canvas, obj) for canvas in doc.get("canvases", [])
            for obj in canvas.get("objects", []) if obj.get("id") == panel_id]


def _find_record(doc, panel_id):
    found = _find_records(doc, panel_id)
    return found[0] if len(found) == 1 else (None, None)


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


def _projection_panel(pid, record):
    native_w, native_h = record.get("nativeW"), record.get("nativeH")
    crop = record.get("crop")
    if isinstance(crop, dict) and native_w and native_h:
        crop = [crop.get("x", 0) * native_w, crop.get("y", 0) * native_h,
                crop.get("w", 1) * native_w, crop.get("h", 1) * native_h]
    return {"id": pid, "rect_mm": [record[k] for k in ("x", "y", "w", "h")],
            "measurement_status": "measured", "rotation_deg": record.get("rotation", 0),
            "crop": crop, "flip_h": record.get("flipH", False),
            "flip_v": record.get("flipV", False), "kind": "panel"}


def _durable_immutable(path: Path, data: bytes, digest: str):
    """Durably write immutable bytes; never overwrite a different file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise OSError("existing staged resource hash mismatch")
        return False
    fd, name = tempfile.mkstemp(prefix=".figpact-stage-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        created = False
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise OSError("existing staged resource hash mismatch")
        else:
            os.replace(temp, path)
            created = True
        if os.name != "nt":
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        return created
    finally:
        temp.unlink(missing_ok=True)


def _persist_config(session, candidate):
    """Derive the candidate config text and prove it rebuilds the candidate.

    The patch and the source arrive on the candidate, exactly as the trial
    engine produced them. The catalog is the candidate's own contract, and
    the rebuild must reproduce the candidate's verified figure before
    anything is staged. Returns (data, digest, rebuilt_frame)."""
    from figpact.contracts import parameter_catalog
    from figpact.patch import apply_patch_text
    from figpact.render_api import RenderSession
    patch, source = candidate.get("config_patch"), candidate.get("config_source")
    if not isinstance(patch, dict) or source is None:
        raise ValueError("managed panel needs config_patch and config_source")
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    current = Path(session.config).read_text(encoding="utf-8")
    # The patch only makes sense against the file it was produced from; a
    # bare accepted frame carries an empty patch and any source is harmless.
    if patch and source != current:
        raise ValueError("config_source differs from the session's current config")
    contract = candidate.get("contract")
    if not isinstance(contract, dict) or contract.get("validation_error"):
        raise ValueError("candidate contract is unavailable or invalid")
    text = apply_patch_text(source, patch, parameter_catalog(contract))
    data = text.encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="figpact-config-verify-") as directory:
        path = Path(directory) / "candidate.yaml"
        path.write_bytes(data)
        fresh = RenderSession(session.script, str(path), session.scope,
                              output_dir=session.output_dir)
        try:
            rebuilt = fresh.snapshot()["frame"]
        finally:
            fresh.close()
    return data, hashlib.sha256(data).hexdigest(), rebuilt


def _science_basis(session, state):
    """Science basis that must be identical between candidate and rebuild.

    Declared science-input paths must exist and hash identically; the module
    revision binds script/assets/engine. The session's own config path is
    deliberately excluded: the rebuild must NOT depend on it, because the
    rebuild runs over a staged copy at a different path by design.
    """
    state = state or {}
    h = hashlib.sha256()
    h.update(str(state.get("module_revision") or "").encode())
    for name in sorted(state.get("science_inputs") or []):
        data = Path(name).read_bytes()
        h.update(str(Path(name).resolve()).encode())
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


def _rebuilt_matches(rebuilt, candidate, record, page_w, page_h):
    """The staged config must reproduce the verified candidate's figure."""
    from figpact.render_api import RenderSession, project_frame_scene
    original = candidate["frame"]
    if (rebuilt.get("science") or {}).get("digest") != (original.get("science") or {}).get("digest"):
        raise ValueError("science digest differs")
    if (rebuilt.get("science") or {}).get("verified") is not True:
        raise ValueError("rebuilt science evidence is not verified")
    projection_panel = _projection_panel(candidate["panel_id"], record)
    page = [page_w, page_h]
    rebuilt_projection = project_frame_scene(rebuilt, projection_panel, page)
    original_projection = project_frame_scene(original, projection_panel, page)
    items = (rebuilt_projection.get("evidence") or {}, original_projection.get("evidence") or {})
    for key in ("canvas_mm", "panel_rect_mm", "crop_mm", "rotation_deg", "scale_xy", "anisotropic"):
        if items[0].get(key) != items[1].get(key):
            raise ValueError(f"projection {key} differs")
    original_fonts = RenderSession._font_metrics(
        json.loads(original["scene_json"])["nodes"], original_projection)["measured"]
    rebuilt_fonts = RenderSession._font_metrics(
        json.loads(rebuilt["scene_json"])["nodes"], rebuilt_projection)["measured"]
    original_effective = {f["id"]: f["effective_font_pt"] for f in original_fonts
                          if f.get("effective_font_pt") is not None}
    rebuilt_effective = {f["id"]: f["effective_font_pt"] for f in rebuilt_fonts
                         if f.get("effective_font_pt") is not None}
    if set(original_effective) != set(rebuilt_effective) or any(
            abs(original_effective[gid] - rebuilt_effective[gid]) > FONT_TOL_PT
            for gid in original_effective):
        raise ValueError("measured effective fonts differ")
    required = RenderSession._required_content(
        json.loads(rebuilt["scene_json"])["nodes"],
        candidate.get("required_content", []), rebuilt_projection)
    if required["missing"]:
        raise ValueError(f"required content not visible/measured/in crop: {required['missing']}")


def build_acceptance_plan(candidates, *, host_document, base_revision, resources_dir,
                          expected_document_revision=None, persist_config=True) -> dict:
    """Prepare immutable PDF/config resources and a minimal schema-3 document."""
    from figpact.render_api import RenderSession, project_frame_scene

    doc = host_document.get("document", host_document)
    identity = host_document.get("identity", host_document)
    project_root = Path(host_document.get("project_root")).resolve() \
        if host_document.get("project_root") \
        else (Path(identity.get("path")).parent.resolve() if identity.get("path") else Path(".").resolve())
    staging = Path(resources_dir).expanduser().resolve()
    plan_id = _digest({"base_revision": base_revision, "candidates": [
        {k: c.get(k) for k in ("panel_id", "frame_revision", "candidate_revision", "source_revision")}
        for c in candidates]})[:32]
    host_revision = identity.get("revision", host_document.get("revision"))
    canvas_ids = [c.get("id") for c in doc.get("canvases", [])]
    canvas_id = doc.get("activeCanvasId") or (canvas_ids[0] if len(canvas_ids) == 1 else None)
    canvas = next((c for c in doc.get("canvases", []) if c.get("id") == canvas_id), None)
    page = (canvas.get("page") or {}) if canvas else {}
    page_mm = [page.get("w"), page.get("h")]
    checks = [{"name": _PRECONDITIONS[0],
               "expected": {"revision": base_revision, "expected_document_revision": expected_document_revision},
               "observed": {"revision": host_revision, "expected_document_revision": expected_document_revision},
               "ok": host_revision == base_revision and (expected_document_revision is None or host_revision == expected_document_revision)}]
    facts_by_panel = {}
    for c in candidates:
        session = c.get("session")
        supplied = c.get("session_facts") or {}
        try:
            current = session.snapshot()["frame"] if session is not None else None
        except Exception:
            current = None
        keys = ("frame_revision", "candidate_revision", "source_revision", "base_config_revision")
        expected = {k: supplied.get(k) for k in keys}
        expected["science_digest"] = supplied.get("science_digest")
        observed = {k: (current or {}).get(k) for k in keys}
        observed["science_digest"] = ((current or {}).get("science") or {}).get("digest")
        # The supplied facts must bind the receipt AND match the live frame;
        # a receipt that omits a field never verifies that field.
        ok = bool(session is not None and current
                  and all(expected[k] for k in expected)
                  and all(observed[k] == expected[k] for k in expected)
                  and (current.get("science") or {}).get("verified") is True
                  and all(supplied.get(k) == c.get(k) for k in expected if c.get(k) is not None))
        if pid := c.get("panel_id"):
            facts_by_panel[pid] = {"current": current, "facts": supplied}
        if not ok:
            checks.append({"name": _PRECONDITIONS[1], "expected": expected,
                           "observed": {"supplied_session_facts": supplied, "live_session": observed,
                                        "science_verified": bool((current or {}).get("science", {}).get("verified"))},
                           "ok": False})
            break
    if not any(x["name"] == _PRECONDITIONS[1] for x in checks):
        checks.append({"name": _PRECONDITIONS[1], "expected": True, "observed": True, "ok": True})
    panel_data, uniqueness = {}, {}
    for c in candidates:
        pid = c.get("panel_id")
        matches = _find_records(doc, pid)
        # Exactly one match on exactly the plan canvas: any panel id that
        # appears anywhere else (or not on our canvas) is refused, not guessed.
        unique = len(matches) == 1 and matches[0][0].get("id") == canvas_id
        canvas, record = matches[0] if unique else (None, None)
        binding = record.get("figpact") if record else None
        script = c.get("script") or (c.get("session_facts") or {}).get("script")
        config_val = c.get("config") or (c.get("session_facts") or {}).get("config")
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
        session = c.get("session")
        managed_binding = isinstance(binding, dict)
        actual_script = str(session.script) if session is not None else None
        actual_config = str(session.config) if session is not None else None
        actual_scope = session.scope if session is not None else None
        expected_binding = {"script": str(Path(script).expanduser().resolve()) if script else None,
                            "config": str(Path(config_val).expanduser().resolve()) if config_val else None,
                            "scope": scope}
        if record is None:
            uniqueness[pid] = {"count": len(matches),
                               "canvas_ids": sorted({cv.get("id") for cv, _ in matches if cv.get("id")}),
                               "expected_canvas_id": canvas_id, "ok": False}
            panel_data[pid] = (canvas, record, c, None, required, facts, False)
            continue
        current_binding = {"script": (str(Path(record.get("script")).expanduser().resolve()) if record.get("script") else None),
                           "config": (str(Path((binding or {}).get("config")).expanduser().resolve()) if (binding or {}).get("config") else None),
                           "scope": (binding or {}).get("scope")}
        # Session paths are resolved; host records may carry either form.
        identity_ok = bool(record and record.get("type") == "panel" and not record.get("hidden", False)
                           and actual_script and actual_config and actual_scope
                           and expected_binding["script"] == actual_script
                           and expected_binding["config"] == actual_config
                           and expected_binding["scope"] == actual_scope
                           and ((managed_binding and record.get("renderOwner") == "figpact"
                                 and current_binding == expected_binding
                                 and not record.get("overrides"))
                                or (not managed_binding and record.get("renderOwner") != "figpact")))
        uniqueness[pid] = {"count": len(matches),
                           "canvas_ids": sorted({canvas.get("id") for canvas, _ in matches if canvas.get("id")}),
                           "expected_canvas_id": canvas_id,
                           "ok": unique}
        panel_data[pid] = (canvas, record, c, scale, required, facts, identity_ok)
    checks.extend([
        {"name": _PRECONDITIONS[2], "expected": "target panel unique on the plan canvas",
         "observed": uniqueness, "ok": all(x["ok"] for x in uniqueness.values()) and
         all(item[6] for item in panel_data.values())},
        {"name": _PRECONDITIONS[3],
         "expected": {pid: (c.get("placement") or c.get("bound_panel")) for pid, (_, _, c, *_rest) in panel_data.items()},
         "observed": {pid: _placement(r) if r else None for pid, (_, r, *_rest) in panel_data.items()},
         "ok": all(_same_placement(c, r or {})[2] for _, r, c, *_rest in panel_data.values())},
        {"name": _PRECONDITIONS[4], "expected": "equal positive scales",
         "observed": {pid: scale for pid, (_, _, _, scale, *_rest) in panel_data.items()},
         "ok": all(scale and len(scale) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in scale)
                   and math.isclose(scale[0], scale[1], rel_tol=1e-9, abs_tol=1e-9)
                   for _, _, _, scale, *_rest in panel_data.values())},
    ])
    required_report = {}
    for pid, (_, record, c, _, required, facts, _) in panel_data.items():
        try:
            scene_nodes = json.loads(facts["scene_json"])["nodes"]
            panel = _projection_panel(pid, record)
            projection = project_frame_scene(facts, panel, page_mm)
            result = RenderSession._required_content(scene_nodes, required, projection)
        except Exception as exc:
            result = {"checked": [], "missing": list(required), "reason": f"{type(exc).__name__}: {exc}"}
        required_report[pid] = result
    checks.append({"name": _PRECONDITIONS[5],
                   "expected": {pid: ids for pid, (_, _, _, _, ids, *_rest) in panel_data.items()},
                   "observed": required_report, "ok": all(not v["missing"] for v in required_report.values())})
    managed = {pid: bool(record and isinstance(record.get("figpact"), dict))
               for pid, (_, record, *_rest) in panel_data.items()}
    check_persist = {"name": _PRECONDITIONS[6], "expected": "managed config patch rebuild matches candidate",
                     "observed": {}, "ok": True}
    check_binding = {"name": _PRECONDITIONS[7], "expected": "managed config path updates without scope change",
                     "observed": {}, "ok": True}
    first_failure = next((row["name"] for row in checks if not row["ok"]), None)
    try:
        staging_inside_project = staging.is_relative_to(project_root)
    except (AttributeError, ValueError):
        staging_inside_project = False
    resource_failure = None if staging_inside_project else (
        "staging dir is outside the project root: the host resolves fileId from there, "
        "so the reference would not point at the bytes")
    config_candidates = {}
    if first_failure is None and resource_failure is None:
        try:
            for pid, is_managed in managed.items():
                if not is_managed:
                    continue
                if not persist_config:
                    raise ValueError(f"{pid}: persist_config=False cannot update managed panel")
                _, record, candidate, _, _, _, _ = panel_data[pid]
                session = candidate["session"]
                data, digest, rebuilt = _persist_config(session, candidate)
                origin = session._native._agent._call(session._native._agent._worker.state)
                rebuilt_state = {"science_inputs": origin.get("science_inputs"),
                                 "module_revision": origin.get("module_revision")}
                supplied = candidate.get("session_facts") or {}
                if supplied.get("science_inputs") is None or supplied.get("module_revision") is None:
                    raise ValueError(f"{pid}: session_facts must carry science_inputs and module_revision")
                original_state = {"science_inputs": supplied.get("science_inputs"),
                                  "module_revision": supplied.get("module_revision")}
                if _science_basis(session, original_state) != _science_basis(session, rebuilt_state):
                    raise ValueError(f"{pid}: science input basis differs")
                _rebuilt_matches(rebuilt, {"frame": facts_by_panel[pid]["current"],
                                           "panel_id": pid,
                                           "required_content": candidate.get("required_content", [])},
                                 record, page_mm[0], page_mm[1])
                config_candidates[pid] = (data, digest, rebuilt.get("frame_revision"))
            check_persist["observed"] = {pid: {"sha256": values[1], "rebuild_verified": True}
                                         for pid, values in config_candidates.items()}
            check_binding["observed"] = {pid: {"scope": record["figpact"]["scope"]}
                                         for pid, (_, record, *_rest) in panel_data.items() if managed[pid]}
        except Exception as exc:
            check_persist["ok"] = False
            check_persist["observed"] = {"error": f"{type(exc).__name__}: {exc}"}
            first_failure = _PRECONDITIONS[6]
    resources, updates, prepared, created_resources = [], [], [], []
    next_doc = copy.deepcopy(doc)
    if first_failure is None and resource_failure is None:
        try:
            staging.mkdir(parents=True, exist_ok=True)
            for c in candidates:
                pid, session = c["panel_id"], c["session"]
                _, record, *_ = panel_data[pid]
                export_root = staging / f"export-{uuid.uuid4().hex}"
                export_root.mkdir()
                bundle = session.export(export_root, c["frame_revision"], c.get("candidate_id"))["bundle"]
                native = (record.get("nativeW"), record.get("nativeH"))
                page_box = bundle.get("page_mm") or []
                if all(isinstance(v, (int, float)) and v > 0 for v in native):
                    if len(page_box) != 2 or any(not isinstance(v, (int, float)) or v <= 0 for v in page_box):
                        raise ValueError(f"{pid}: prepared PDF has no measured page size")
                    if any(abs(float(page_box[i]) - float(native[i])) > NATIVE_TOL_MM for i in range(2)):
                        raise ValueError(f"{pid}: PDF page differs from stored native size")
                dest_dir = staging / "figpact-resources" / plan_id
                dest_dir.mkdir(parents=True, exist_ok=True)
                pdf_data = Path(bundle["pdf_path"]).read_bytes()
                pdf_hash = hashlib.sha256(pdf_data).hexdigest()
                pdf_path = dest_dir / f"{pdf_hash}.pdf"
                relative = pdf_path.relative_to(project_root).as_posix()
                set_fields = {"fileId": relative}
                config_path = config_hash = rebuilt_revision = None
                rebuild_verified = False
                if managed[pid]:
                    config_data, config_hash, rebuilt_revision = config_candidates[pid]
                    config_path_obj = dest_dir / f"{config_hash}.yaml"
                    if _durable_immutable(config_path_obj, config_data, config_hash):
                        created_resources.append(config_path_obj)
                    prepared.append(str(config_path_obj))
                    config_path = config_path_obj.relative_to(project_root).as_posix()
                    rebuild_verified = True
                    set_fields["figpact"] = {"config": config_path, "scope": record["figpact"]["scope"]}
                if _durable_immutable(pdf_path, pdf_data, pdf_hash):
                    created_resources.append(pdf_path)
                prepared.append(str(pdf_path))
                _, staged_record = _find_record(next_doc, pid)
                staged_record.update(set_fields)
                updates.append({"panel_id": pid, "set": set_fields})
                resources.append({"panel_id": pid, "kind": "pdf", "path": relative,
                    "staging_path": str(pdf_path), "bytes_sha256": pdf_hash, "page_mm": bundle["page_mm"],
                    "frame_revision": bundle["frame_revision"], "candidate_revision": bundle["candidate_revision"],
                    "science_digest": bundle["science_digest"], "measured_fonts": c.get("measured_fonts", []),
                    "config_path": config_path, "config_sha256": config_hash,
                    "config_rebuild_verified": rebuild_verified,
                    "config_rebuild_frame_revision": rebuilt_revision})
        except Exception as exc:
            resource_failure = f"{type(exc).__name__}: {exc}"
            for path in created_resources:
                Path(path).unlink(missing_ok=True)
            prepared.clear()
            resources.clear()
            updates.clear()
            next_doc = copy.deepcopy(doc)
            check_persist["observed"] = {"error": resource_failure}
            check_binding["observed"] = {"error": resource_failure}
    checks.extend([check_persist, check_binding])
    for row in (check_persist, check_binding):
        if first_failure is None and not row["ok"]:
            first_failure = row["name"]
    checks.append({"name": _PRECONDITIONS[8], "expected": "durably staged hashed PDF/config resources",
                   "observed": {"prepared_files": prepared, "error": resource_failure},
                   "ok": resource_failure is None})
    if first_failure is None and resource_failure is not None:
        first_failure = _PRECONDITIONS[8]
    allowed = {("canvases", i, "objects", j, key) for u in updates
               for i, canvas in enumerate(doc.get("canvases", [])) for j, obj in enumerate(canvas.get("objects", []))
               if obj.get("id") == u["panel_id"] for key in u["set"] if key != "figpact"}
    allowed |= {("canvases", i, "objects", j, "figpact", "config") for u in updates
                if "figpact" in u["set"] for i, canvas in enumerate(doc.get("canvases", []))
                for j, obj in enumerate(canvas.get("objects", [])) if obj.get("id") == u["panel_id"]}
    diffs = _diff_paths(doc, next_doc)
    minimal = all(path in allowed for path in diffs)
    checks.append({"name": _PRECONDITIONS[9], "expected": sorted("/".join(map(str, p)) for p in allowed),
                   "observed": sorted("/".join(map(str, p)) for p in diffs),
                   "ok": (minimal and len(updates) == len(candidates)) if first_failure is None else True,
                   "state": "CHECKED" if first_failure is None else "NOT_REACHED"})
    if first_failure is None and not (minimal and len(updates) == len(candidates)):
        first_failure = _PRECONDITIONS[9]
    status = "REFUSED" if first_failure else "READY"
    if status == "READY" and (next_doc.get("schema") != 3 or not isinstance(next_doc.get("canvases"), list)):
        status, first_failure = "REFUSED", _PRECONDITIONS[9]
        checks[-1]["ok"] = False
    return {"schema": "figpact.acceptance-plan/1", "status": status, "stage": "PLANNED",
        "state": "PREPARED" if status == "READY" else "REFUSED", "plan_id": plan_id,
        "host": {"document_id": identity.get("document_id"), "path": identity.get("path"),
                 "base_revision": base_revision, "document_schema": doc.get("schema"),
                 "canvas_id": canvas_id, "panel_ids": [c.get("panel_id") for c in candidates]},
        "preconditions": checks, "resources": resources,
        "document_patch": {"canvas_id": canvas_id, "updates": updates},
        "next_document": next_doc if status == "READY" else None,
        "limits": ["PREPARED only: the host document was not written and nothing was accepted"],
        "evidence": {"staging_dir": str(staging), "prepared_files": prepared, "first_failure": first_failure}}
