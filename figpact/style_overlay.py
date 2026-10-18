"""Verified style overlay (G16 R2): declarative, no source rewriting.

Only three hardcoded setters: axis xlabel/ylabel fontsize, major tick-label
fontsize, connected data-curve linewidth. Descriptors carry no method.

Every verification runs on two independent source rebuilds (baseline fig +
separately rebuilt styled fig); a second pair must agree before anything
persists. Initial overlay creation stages a complete file with the existing
atomic ``source_writes`` temp-file writer in the same directory, then
installs it with a must-not-exist ``os.link`` (same-volume hardlink):
a rival creator's bytes are refused, a crash before install leaves only an
unlinked temp file, and a link that cannot be created (cross-volume,
unsupported platform) is an explicit REFUSED -- never a silent overwrite.
Updates reuse the existing atomic JSON writer (tmp + fsync + replace + dir
fsync) under the module's single-writer assumption (shared with
source_writes): the expected hash is checked, then the atomic replace runs.
No new transaction module, no source_writes/patch edits. Dependency drift
(script/config/RAW/science-input bytes) is refused before any figure is
constructed. Overlay/render artifacts are never fingerprinted (only the
named dependency files are hashed, never a folder scan). A sidecar overlay
next to its source script is a normal product case; only overwriting
a protected dependency/output path is refused.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OVERLAY_SCHEMA = "figpact.style-overlay/1"
RECEIPT_SCHEMA = "figpact.style-overlay-receipt/1"

FONTSIZE_RANGE = (0.5, 100.0)
LINEWIDTH_RANGE = (0.05, 20.0)

__all__ = ["inventory", "apply", "load", "render",
           "OVERLAY_SCHEMA", "RECEIPT_SCHEMA"]


class _VerifyFail(Exception):
    """Internal: a verification step failed with receipt-ready problems."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


# ------------------------------------------------------------- small helpers

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        return _sha256_bytes(Path(path).read_bytes())
    except (OSError, FileNotFoundError):
        return None


def _native(value: Any) -> Any:
    from figpact.session import _json_native
    try:
        return _json_native(value)
    except Exception:
        return value


def _default_scope(module: Any) -> str:
    scopes = getattr(module, "SCOPES", None)
    try:
        if scopes:
            return str(tuple(scopes)[0])
    except Exception:
        pass
    return "main"


def _store_path(path: Path, base: Path) -> dict:
    """Store a dependency reference: rel when possible, abs across mounts.

    Cross-drive (Windows) overlays cannot be relative-only: when the target
    is not under ``base``, the absolute path is recorded explicitly with
    ``kind: "abs"`` (``portable: false``). Hashes still gate drift.
    """
    target = Path(path).resolve()
    try:
        rel = target.relative_to(Path(base).resolve()).as_posix()
    except ValueError:
        return {"kind": "abs", "path": target.as_posix(), "portable": False}
    return {"kind": "rel", "path": rel, "portable": True}


def _restore_path(ref: Any, base: Path) -> Path:
    if not isinstance(ref, dict) or set(ref) - {"kind", "path", "portable"}:
        raise ValueError(f"INVALID_OVERLAY: bad path reference {ref!r}")
    if ref.get("kind") == "rel":
        if not isinstance(ref.get("path"), str) or not ref["path"]:
            raise ValueError("INVALID_OVERLAY: empty rel path")
        return (Path(base).resolve() / ref["path"]).resolve()
    if ref.get("kind") == "abs":
        candidate = Path(str(ref.get("path") or ""))
        if not candidate.is_absolute():
            raise ValueError(f"INVALID_OVERLAY: abs path not absolute: {ref!r}")
        return candidate.resolve()
    raise ValueError(f"INVALID_OVERLAY: unknown path kind {ref.get('kind')!r}")


# ------------------------------------------------------------- build (trusted)

def _import_only(script: Path):
    """Import the wrapper module without constructing any figure.

    The drift gate needs ``RAW``/science-input locations before frozen
    source is ever executed via a build entry.
    """
    from figpact.final_size import _import_script
    return _import_script(Path(script).resolve())


def _fresh_build(script: Path, config: Path | None, scope: str | None):
    from figpact.final_size import _import_script, _load_config, _build_figure
    script = Path(script).resolve()
    module = _import_script(script)
    cfg_path = Path(config).resolve() if config is not None else None
    cfg = _load_config(module, script, cfg_path)
    use_scope = scope if scope is not None else _default_scope(module)
    (fig, reg), resolved = _build_figure(module, copy.deepcopy(cfg), use_scope)
    return module, cfg, fig, reg, resolved


def _manifest_of(module: Any) -> Any:
    try:
        if callable(getattr(module, "science_manifest", None)) \
                and callable(getattr(module, "load_science", None)):
            return module.science_manifest(module.load_science())
    except Exception:
        return None
    return None


def inventory(script: Any, config: Any = None, scope: str | None = None) -> list[dict]:
    """Fresh-build then list stable style targets (JSON-native, id-sorted)."""
    from figpact import style_identity as ident
    _, _, fig, _, resolved = _fresh_build(Path(script), config, scope)
    try:
        return ident.inventory(fig, scope=resolved)
    finally:
        try:
            import matplotlib.pyplot as plt
            plt.close(fig)
        except Exception:
            pass


# ------------------------------------------------------------- validation

def _validate_edits(edits: Any) -> list[dict]:
    if not isinstance(edits, list):
        raise ValueError("INVALID_EDITS: edits must be a list")
    seen_ids: set[str] = set()
    out: list[dict] = []
    for entry in edits:
        if not isinstance(entry, dict):
            raise ValueError("INVALID_EDIT: each edit must be a dict")
        unknown = set(entry) - {"target_id", "value"}
        if unknown:
            raise ValueError(f"UNKNOWN_FIELD: edit fields {sorted(unknown)}")
        if set(entry) != {"target_id", "value"}:
            raise ValueError("INVALID_EDIT: edit needs exactly target_id+value")
        tid = entry["target_id"]
        if not isinstance(tid, str) or not tid:
            raise ValueError("INVALID_EDIT: target_id must be a nonempty string")
        if tid in seen_ids:
            raise ValueError(f"DUPLICATE_TARGET: {tid!r} requested twice")
        seen_ids.add(tid)
        value = entry["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise ValueError(f"INVALID_VALUE: {tid!r} value {value!r} "
                             "must be a finite number (bool/NaN/Inf rejected)")
        out.append({"target_id": tid, "value": float(value)})
    return out


def _validate_remove(remove: Any) -> list[str]:
    if remove is None:
        return []
    if not isinstance(remove, list):
        raise ValueError("INVALID_REMOVE: remove must be a list of target ids")
    seen: set[str] = set()
    out: list[str] = []
    for tid in remove:
        if not isinstance(tid, str) or not tid:
            raise ValueError(f"INVALID_REMOVE: target id {tid!r} "
                             "must be a nonempty string")
        if tid in seen:
            raise ValueError(f"DUPLICATE_TARGET: {tid!r} requested twice")
        seen.add(tid)
        out.append(tid)
    return out


def _validate_path_ref(ref: Any, name: str) -> None:
    if not isinstance(ref, dict) or set(ref) != {"kind", "path", "portable"}:
        raise ValueError(f"INVALID_OVERLAY: {name} must be a path reference "
                         "{kind, path, portable}")
    if ref.get("kind") not in ("rel", "abs"):
        raise ValueError(f"INVALID_OVERLAY: {name} kind must be rel|abs")
    if not isinstance(ref.get("path"), str) or not ref["path"]:
        raise ValueError(f"INVALID_OVERLAY: {name} path must be nonempty")
    if not isinstance(ref.get("portable"), bool):
        raise ValueError(f"INVALID_OVERLAY: {name} portable must be bool")


def _dep_entry(name: str, ref: Any, sha256: Any) -> None:
    _validate_path_ref(ref, f"dependencies.files[{name}].ref")
    if not isinstance(sha256, str) or not __import__("re").fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ValueError(f"INVALID_OVERLAY: dependencies.files[{name}].sha256 "
                         "must be 64 hex chars")


def _check_value(role: str, prop: str, value: float, target_id: str) -> None:
    from figpact import style_identity as ident
    if (role, prop) not in tuple(ident.ALLOWED_TARGETS):
        raise ValueError(f"UNSUPPORTED_TARGET: {target_id!r} role {role!r} "
                         f"property {prop!r} not editable")
    low, high = (FONTSIZE_RANGE if prop == "fontsize" else LINEWIDTH_RANGE)
    if not (low <= value <= high):
        raise ValueError(f"OUT_OF_RANGE: {target_id!r} value {value!r} "
                         f"outside [{low}, {high}] for {prop!r}")


def _validate_overlay_shape(doc: Any) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("INVALID_OVERLAY: top-level must be a mapping")
    allowed = {"schema", "script", "config", "scope", "targets",
               "dependencies", "created_at", "generator"}
    unknown = set(doc) - allowed
    if unknown:
        raise ValueError(f"UNKNOWN_FIELD: overlay fields {sorted(unknown)}")
    if doc.get("schema") != OVERLAY_SCHEMA:
        raise ValueError(f"INVALID_OVERLAY: schema must be {OVERLAY_SCHEMA!r}")
    _validate_path_ref(doc.get("script"), "script")
    if doc.get("config") is not None:
        _validate_path_ref(doc.get("config"), "config")
    if not isinstance(doc.get("scope"), str) or not doc["scope"]:
        raise ValueError("INVALID_OVERLAY: scope must be a nonempty string")
    targets = doc.get("targets")
    if not isinstance(targets, list):
        raise ValueError("INVALID_OVERLAY: targets must be a list")
    seen: set[str] = set()
    for item in targets:
        if not isinstance(item, dict) or set(item) != {"id", "descriptor", "value"}:
            raise ValueError("INVALID_OVERLAY: each target needs id/descriptor/value")
        if item["id"] in seen:
            raise ValueError(f"INVALID_OVERLAY: duplicate target {item['id']!r}")
        seen.add(item["id"])
        from figpact import style_identity as ident
        ident.match_identity(item["descriptor"])  # validates closed shape/role/prop
        value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise ValueError(f"INVALID_OVERLAY: value for {item['id']!r} nonfinite")
    deps = doc.get("dependencies")
    if not isinstance(deps, dict) or set(deps) != {"files"}:
        raise ValueError("INVALID_OVERLAY: dependencies must be exactly {files}")
    files = deps.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("INVALID_OVERLAY: dependencies.files must be a nonempty mapping")
    allowed_names = {"script", "config", "raw"}
    for name, entry in files.items():
        if name in allowed_names:
            kind = entry
        elif name.startswith("sci:"):
            kind = entry
        else:
            raise ValueError(f"INVALID_OVERLAY: unknown dependency {name!r}")
        if not isinstance(kind, dict) or set(kind) != {"ref", "sha256"}:
            raise ValueError(f"INVALID_OVERLAY: dependencies.files[{name}] "
                             "must be exactly {ref, sha256}")
        _dep_entry(name, kind["ref"], kind["sha256"])
    if "script" not in files:
        raise ValueError("INVALID_OVERLAY: dependencies.files missing 'script'")
    if not isinstance(doc.get("created_at"), str) or not isinstance(doc.get("generator"), str):
        raise ValueError("INVALID_OVERLAY: created_at/generator must be strings")
    return doc


def _dep_refs(doc: dict, base: Path) -> dict:
    """Resolve every stored dependency to a disk path -- no import, no exec.

    Pure path arithmetic from the overlay's own per-name ``ref`` entries.
    No probing, no guessing, no ``raw/*.py`` fallback: a dependency without
    an exact stored path is an invalid overlay. Raises on any bad ref.
    """
    base = Path(base)
    return {name: _restore_path(entry["ref"], base)
            for name, entry in (doc.get("dependencies") or {}).get("files", {}).items()}


def _raw_path_of(module: Any) -> Path | None:
    raw = getattr(module, "RAW", None)
    if raw is None:
        return None
    try:
        candidate = Path(str(raw))
    except Exception as error:
        raise ValueError(f"REFUSED: RAW declaration malformed ({raw!r}): {error}") from error
    if not candidate.is_absolute():
        try:
            base = Path(str(getattr(module, "__file__", "."))).parent
            candidate = (base / candidate).resolve()
        except Exception as error:
            raise ValueError(f"REFUSED: RAW declaration unresolvable ({raw!r}): {error}") from error
    else:
        try:
            candidate = candidate.resolve()
        except Exception as error:
            raise ValueError(f"REFUSED: RAW declaration unresolvable ({raw!r}): {error}") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"REFUSED: RAW declared but not a regular file: {candidate}")
    try:
        with open(candidate, "rb") as handle:
            handle.read(1)
    except OSError as error:
        raise PermissionError(f"REFUSED: RAW declared but unreadable: {candidate} ({error})") from error
    return candidate


def _science_input_paths(module: Any) -> list[Path]:
    from figpact.session import SessionError, declared_science_inputs
    declared = getattr(module, "SCIENCE_INPUTS", None)
    hook = getattr(module, "science_inputs", None)
    has_decl = declared is not None and declared != "" and not (isinstance(declared, (list, tuple, set)) and len(declared) == 0)
    has_hook = callable(hook)
    if not has_decl and not has_hook:
        return []
    try:
        return [Path(p) for p in declared_science_inputs(module)]
    except SessionError:
        raise
    except Exception as error:
        raise RuntimeError(f"REFUSED: science_inputs hook failed ({type(error).__name__}: {error})") from error


def _live_dependencies(module: Any, script: Path, config: Path | None) -> dict:
    """Live dependency inventory for the NAMED inputs only (no import closure).

    Covers ``script``/``config`` build inputs, the module's real ``RAW``
    attribute, and ``sci:<absolute-posix-path>`` per declared science
    input. Transitive imports are NOT tracked: no full closure is claimed.
    Raises (REFUSED/diagnostic) on declared-but-bad paths -- never a
    ``missing`` sentinel or skip.
    """
    out: dict[str, tuple[Path, str]] = {}
    script_hash = _sha256_file(Path(script))
    if script_hash is None:
        raise FileNotFoundError(f"REFUSED: dependency unreadable: script {Path(script)}")
    out["script"] = (Path(script), script_hash)
    if config is not None:
        config_hash = _sha256_file(Path(config))
        if config_hash is None:
            raise FileNotFoundError(f"REFUSED: dependency unreadable: config {Path(config)}")
        out["config"] = (Path(config), config_hash)
    raw = _raw_path_of(module)
    if raw is not None:
        raw_hash = _sha256_file(raw.resolve())
        if raw_hash is None:
            raise FileNotFoundError(f"REFUSED: dependency unreadable: raw {raw}")
        out["raw"] = (raw.resolve(), raw_hash)
    for path in _science_input_paths(module):
        resolved = Path(path).resolve()
        digest = _sha256_file(resolved)
        if digest is None:
            raise FileNotFoundError(f"REFUSED: dependency unreadable: sci {resolved}")
        out[f"sci:{resolved.as_posix()}"] = (resolved, digest)
    return out


def _drift_check(stored_files: dict, paths: dict) -> str | None:
    """Compare stored per-name hashes against live disk bytes."""
    live = {name: (_sha256_file(path) or "missing") for name, path in paths.items()}
    problems = []
    for key in sorted(set(stored_files) | set(live)):
        want = (stored_files.get(key) or {}).get("sha256") \
            if isinstance(stored_files.get(key), dict) else None
        if want != live.get(key):
            problems.append(f"{key}: stored {want} != disk {live.get(key)}")
    if problems:
        return f"DRIFT: dependency changed ({'; '.join(problems[:4])})"
    return None


def _live_drift_check(stored_files: dict, live: dict) -> str | None:
    """Post-import gate: exact name-set match plus per-name hash match.

    A forged live inventory (extra/missing names) is drift, not a pass.
    """
    if set(stored_files) != set(live):
        extra = sorted(set(live) - set(stored_files))
        missing = sorted(set(stored_files) - set(live))
        return (f"DRIFT: dependency set changed (extra {extra[:3]}, "
                f"missing {missing[:3]})")
    problems = []
    for key in sorted(stored_files):
        want = stored_files[key].get("sha256") \
            if isinstance(stored_files[key], dict) else None
        if want != live[key][1]:
            problems.append(f"{key}: stored {want} != disk {live[key][1]}")
    if problems:
        return f"DRIFT: dependency changed ({'; '.join(problems[:4])})"
    return None


def _protected_list(script: Path, config: Path | None, module: Any) -> list[str]:
    out = [str(Path(script).resolve())]
    if config is not None:
        out.append(str(Path(config).resolve()))
    raw = _raw_path_of(module)
    if raw is not None:
        out.append(str(raw.resolve()))
    for path in _science_input_paths(module):
        out.append(str(Path(path).resolve()))
    return out


# ------------------------------------------------------------- snapshots

def _extra_props(art: Any) -> dict:
    """Local extension: exact props the narrow G12 snapshot does not track.

    Without this, a color/alpha/marker/linestyle/visibility change would be
    invisible to audit_pair. Read-only; verdicts still come from
    ``change_audit.audit_pair`` only.
    """
    extra: dict[str, Any] = {}
    for name, getter in (("color", "get_color"), ("alpha", "get_alpha"),
                         ("marker", "get_marker"),
                         ("markersize", "get_markersize"),
                         ("linestyle", "get_linestyle"),
                         ("visible", "get_visible")):
        try:
            fn = getattr(art, getter, None)
            value = fn() if callable(fn) else None
        except Exception:
            continue
        if value is None:
            continue
        try:
            if isinstance(value, bool):
                extra[name] = value
            elif isinstance(value, (int, float)):
                number = float(value)
                extra[name] = number if math.isfinite(number) else str(value)
            elif isinstance(value, str):
                extra[name] = value[:80]
            else:
                extra[name] = str(value)[:80]
        except Exception:
            continue
    try:
        fn = getattr(art, "get_linewidths", None)
        widths = fn() if callable(fn) else None
        if widths is not None:
            flat = [float(v) for v in list(widths)]
            if all(math.isfinite(v) for v in flat):
                extra["linewidths"] = sorted(round(v, 6) for v in flat)
    except Exception:
        pass
    return extra


def _extended_style_snapshot(fig: Any, reg: Any,
                             target_artists: dict | None = None) -> dict:
    """Style snapshot with identity-id aliasing in ONE authoritative pass.

    ``ca.style_snapshot`` keys unregistered labels/ticks structurally
    (``unregistered.N.ylabel`` / ``unregistered.tick.y...``) while the audit
    allow-list names stable identity ids. Each target's live artists are
    mapped to their snapshot key during the same findobj traversal that
    assigns keys (shared ``taken`` set, same order as change_audit), then
    merged under the identity id. Extra tracked props land on the merged
    entry in the same pass -- merged-away keys are never re-added, so a
    wrong-tick duplicate cannot leak back in as an unregistered key.
    """
    from figpact import change_audit as ca
    base = ca.style_snapshot(None, fig, reg)
    try:
        registered = {id(a): gid for gid, a in reg.all().items()}
    except Exception:
        registered = {}
    taken: set[str] = set()
    key_of: dict[int, str] = {}
    try:
        artists = list(fig.findobj())
    except Exception:
        artists = []
    for art in artists:
        if not hasattr(art, "get_visible"):
            continue
        try:
            if not art.get_visible():
                continue
        except Exception:
            continue
        key = registered.get(id(art))
        if key is None:
            try:
                key = ca._stable_key(fig, reg, art, taken)
            except Exception:
                continue
        taken.add(key)
        key_of[id(art)] = key
    try:
        items = list(reg.all().items())
    except Exception:
        items = []
    try:
        seen_ids = set(map(id, artists))
    except Exception:
        seen_ids = set()
    for gid, art in items:  # mirror ca fallback: registered-but-unseen
        if gid in base or id(art) not in seen_ids:
            continue
        try:
            entry = ca._style_entry(fig, art)
        except Exception:
            continue
        if entry:
            base[gid] = entry
    alias_of: dict[int, str] = {}
    for tid, arts in (target_artists or {}).items():
        keys = [key_of.get(id(a)) for a in (arts or [])]
        keys = [k for k in keys if k in base]
        if not keys:
            continue
        merged: dict[str, Any] = {}
        for key in keys:
            merged.update(base[key])
        if tid in base:
            merged.update(base[tid])
        base[tid] = merged
        for key in keys:
            if key != tid:
                del base[key]
        for art in (arts or []):
            if id(art) in key_of:
                alias_of[id(art)] = tid
    for art in artists:
        if not hasattr(art, "get_visible"):
            continue
        extra = _extra_props(art)
        if not extra:
            continue
        key = alias_of.get(id(art), key_of.get(id(art)))
        if key is None or key not in base:
            continue
        merged = dict(base[key])
        merged.update({k: _native(v) for k, v in extra.items()})
        base[key] = merged
    return base


def _min_plain_fontsize(fig: Any) -> list:
    """Whole-figure plain-text floor (new path, existing calibre).

    ``qa.check_glyph_floor`` only audits math sub/superscripts
    (``$..^_..$``); a plain ylabel/tick set below the 5pt publication floor
    would otherwise report figure PASS. This overlay-owned check covers
    every visible non-empty Text (axis labels, tick labels, legends, figure
    texts) and reuses the existing final-size floor calibre (5.0pt). It does
    not modify the existing ``qa`` standard -- it is an additional QA gate.
    """
    from figpact import qa as qa_mod
    floor = list(qa_mod.check_glyph_floor(fig))
    worst: float | None = None
    detail: str | None = None
    try:
        artists = list(fig.findobj())
    except Exception:
        artists = []
    for art in artists:
        try:
            import matplotlib.text as _text
            if not isinstance(art, _text.Text):
                continue
            if not art.get_visible():
                continue
            if not str(art.get_text() or "").strip():
                continue
            size = float(art.get_fontsize())
        except Exception:
            continue
        if worst is None or size < worst:
            worst, detail = size, str(art.get_text() or "")[:34]
    if worst is not None and worst < 5.0 - 1e-9:
        floor = list(floor) + [f"plain {worst:.1f} pt < 5.0 pt floor «{detail}»"]
    return floor


def _snapshots(fig: Any, reg: Any, manifest: Any,
               target_artists: dict | None = None) -> dict:
    from figpact import change_audit as ca
    from figpact import science as sci_mod
    from figpact import qa as qa_mod
    styles = _extended_style_snapshot(fig, reg, target_artists)
    shapes = ca.geometry_snapshot(fig, reg)
    view = ca._view_snapshot(fig)
    try:
        captured = sci_mod.capture_science(fig, reg, declarations=manifest)
    except Exception as error:
        captured = {"digest": None, "objects": {},
                    "error": f"{type(error).__name__}: {error}"}
    return {"styles": styles, "shapes": shapes, "view": view,
            "science": captured,
            "qa_blocking": list(qa_mod.blocking_problems(fig)),
            "qa_glyph": _min_plain_fontsize(fig)}


def _qa_of(snap: dict) -> dict:
    blocking = list(snap.get("qa_blocking") or [])
    glyph = list(snap.get("qa_glyph") or [])
    return {"blocking": blocking, "glyph_floor": glyph,
            "pass": not blocking and not glyph}


def _qa_payload(fig: Any) -> dict:
    """Whole-figure QA: blocking geometry AND the glyph floor both gate PASS."""
    from figpact import qa as qa_mod
    blocking = list(qa_mod.blocking_problems(fig))
    glyph = _min_plain_fontsize(fig)
    return {"blocking": blocking, "glyph_floor": glyph,
            "pass": not blocking and not glyph}


def _figure_state(local_state: str, qa_pass: bool) -> str:
    """Whole-figure verdict: a QA FAIL is never washed into PASS."""
    if local_state == "PASS" and qa_pass:
        return "PASS"
    if local_state in ("PASS", "FAIL"):
        return "FAIL"
    return "ERROR"


# ------------------------------------------------------------- verify core

def _set_absolute(artists: list, role: str, prop: str, value: float) -> None:
    if role == "axis.title" and prop == "fontsize":
        for art in artists:
            art.set_fontsize(float(value))
    elif role == "axis.tick" and prop == "fontsize":
        for art in artists:
            art.set_fontsize(float(value))
    elif role == "curve.linewidth" and prop == "linewidth":
        if len(artists) != 1:
            raise ValueError("AMBIGUOUS: curve target must resolve to one artist")
        artists[0].set_linewidth(float(value))
    else:
        raise ValueError(f"UNSUPPORTED_TARGET: no hardcoded setter "
                         f"for ({role!r}, {prop!r})")


_DATA_KINDS = frozenset({"polyline", "collection_envelope", "image_envelope",
                         "figure_image_envelope"})
_TEXT_FAMILY = ("text", "label", "title", "legend", "tick")
_LAYOUT_REFLOW_KINDS = frozenset({
    "frame", "canvas", "text_envelope", "figure_text_envelope",
    "xlabel_envelope", "ylabel_envelope", "title_envelope", "legend_envelope",
    "xtick_label1_envelope", "xtick_label2_envelope",
    "ytick_label1_envelope", "ytick_label2_envelope"})


def _shape_kind(shape_key: str, shapes: dict) -> str:
    rec = (shapes or {}).get(shape_key) or {}
    kind = rec.get("kind")
    if kind:
        return str(kind)
    parts = str(shape_key).split(":")
    return parts[1] if len(parts) > 2 else (parts[0] if parts else "")


def _snapshot_fingerprint(before: dict, after: dict) -> dict:
    """Whole-snapshot fingerprint for third-build comparison.

    Covers alias-merged styles, shapes, view, science digest and QA -- so a
    nondeterministic third build (different non-target style, geometry,
    science, view or QA) cannot be mistaken for the verified candidate.
    JSON-canonical digests; no renderer state.
    """
    from figpact.session import _json_native
    def _digest(value: Any) -> str:
        import math as _math
        def _finite(obj: Any) -> Any:
            if isinstance(obj, float) and not _math.isfinite(obj):
                return {"__nonfinite__": repr(obj)}
            if isinstance(obj, dict):
                return {str(k): _finite(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_finite(v) for v in obj]
            return obj
        try:
            native = _json_native(value)
        except Exception:
            native = str(value)
        return _sha256_bytes(json.dumps(_finite(native), sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False,
                                        default=str).encode("utf-8"))
    return {
        "before_styles": _digest(before.get("styles")),
        "after_styles": _digest(after.get("styles")),
        "before_shapes": _digest(before.get("shapes")),
        "after_shapes": _digest(after.get("shapes")),
        "before_view": _digest(before.get("view")),
        "after_view": _digest(after.get("view")),
        "before_science": str((before.get("science") or {}).get("digest")),
        "after_science": str((after.get("science") or {}).get("digest")),
        "before_qa": _digest({"blocking": before.get("qa_blocking"),
                              "glyph": before.get("qa_glyph")}),
        "after_qa": _digest({"blocking": after.get("qa_blocking"),
                             "glyph": after.get("qa_glyph")}),
    }


def _verify_pair(before: dict, after: dict, *, allowed_styles: dict,
                 required: list, proven: bool) -> dict:
    """One shared audit verdict for apply and load (no semantic fork).

    Narrow per-entry geometry rule with a stated invariant: proof comes
    from an INDEPENDENT rebuild pair, not from a same-figure set/snapshot.
    A fontsize/linewidth-only restyle may shrink a same-content text box
    (science-identical) or trigger a layout-manager reflow of pure-layout
    envelopes. ``patch_envelope`` (bars/patches) is NOT layout: bars carry
    scientific values, so their display-geometry movement must be proven as
    constrained_layout-coupled rigid reflow (identical science digest,
    identical data view, target-confined style diff, same derived set on
    both rebuild pairs), else it fails closed. Polylines, collections and
    images are never reflow.
    """
    from figpact import change_audit as ca
    from figpact import science as sci_mod
    allowed = {"styles": allowed_styles, "shapes": {},
               "required_targets": required}
    audit = ca.audit_pair({"styles": before["styles"], "shapes": before["shapes"],
                           "view": before["view"]},
                          {"styles": after["styles"], "shapes": after["shapes"],
                           "view": after["view"]}, allowed)
    style_changes = audit.get("actual_changes", {}).get("styles", {})
    confined = all(gid in allowed_styles
                   and set(props) <= allowed_styles[gid]
                   for gid, props in style_changes.items())
    try:
        sci_notes = sci_mod.compare_science(before["science"], after["science"])
        science_ok = not sci_notes
    except Exception as error:
        sci_notes = [f"SCIENCE_UNVERIFIED: {error}"]
        science_ok = False
    view_same = (before["view"] == after["view"])
    derived = list(audit.get("derived_geometry") or [])
    hard = list(audit.get("unauthorized") or [])
    derived_problems: list[str] = []
    if derived and not (science_ok and view_same and confined):
        derived_problems.append("derived geometry requires identical science+view "
                                "and target-confined style diff")
    elif derived:
        for entry in derived:
            raw_key = str(entry.get("property") or "")
            gid = str(entry.get("gid") or "")
            shape_key = raw_key[len("shape:"):] if raw_key.startswith("shape:") \
                else raw_key
            kind = _shape_kind(shape_key, before["shapes"]) \
                or _shape_kind(shape_key, after["shapes"])
            if not kind or kind in _DATA_KINDS:
                derived_problems.append(
                    f"data geometry moved, never reflow: {raw_key} kind={kind!r}")
                continue
            before_rec = (before["shapes"] or {}).get(shape_key) or {}
            after_rec = (after["shapes"] or {}).get(shape_key) or {}
            is_text = any(t in kind for t in _TEXT_FAMILY)
            if is_text and before_rec.get("text") == after_rec.get("text"):
                continue  # font-size box derivation, content proven by science
            delta = (entry.get("delta") or {}) if isinstance(entry, dict) else {}
            dw = abs(float(delta.get("dw_mm", 0.0) or 0.0))
            dh = abs(float(delta.get("dh_mm", 0.0) or 0.0))
            # Pure-layout envelopes (frames, text boxes): proven reflow ok.
            if kind in _LAYOUT_REFLOW_KINDS or kind == "canvas":
                if proven:
                    continue  # recorded + counted, reproduced on rebuild pair
                derived_problems.append(
                    f"unproven reflow {raw_key} gid={gid} kind={kind}")
                continue
            # Patch envelopes (bars): data marks, but constrained_layout
            # re-solves their display boxes when a label shrinks while the
            # data-space rect is proven unchanged (science digest identical,
            # both rebuild pairs reproduce the same derived set). Allowed
            # only as proven layout-coupled reflow; anything unproven, or
            # any polyline/collection/image data path, fails closed.
            if kind == "patch_envelope" and proven:
                continue
            derived_problems.append(
                f"unexplained geometry {raw_key} gid={gid} kind={kind}")
    required_changed = audit.get("required_targets_effectively_changed") or {}
    all_required = bool(audit.get("all_required_changed"))
    problems: list[str] = []
    if hard:
        problems.append(f"unauthorized style/structure: {hard[:4]}")
    if not science_ok:
        problems.append(f"science changed: {[str(n)[:160] for n in sci_notes][:4]}")
    if not view_same:
        problems.append("protected data view changed")
    if not all_required:
        problems.append(f"required targets unchanged: {required_changed}")
    if derived_problems:
        problems.append(f"unexplained geometry: {derived_problems[:4]}")
    return {"ok": not problems, "problems": problems, "hard": hard,
            "derived": derived, "derived_ok": not derived_problems,
            "derived_keys": sorted(str(e.get("property") or "") for e in derived),
            "required_changed": required_changed, "all_required": all_required,
            "science_ok": science_ok, "sci_notes": sci_notes,
            "view_same": view_same, "confined": confined}


def _pair_run(script_p: Path, config_p: Path | None, scope: str | None,
              want: list) -> dict:
    """One independent verification pair: clean baseline + clean styled build.

    ``want`` items are ``(target_id, value, descriptor_or_None)``; a None
    descriptor means "fresh inventory by id" (apply), otherwise the stored
    descriptor is re-resolved (load). Raises ``_VerifyFail`` on any problem;
    closes both figures before returning snapshots. Snapshots carry a full
    fingerprint (style alias-merged + shapes + view + science digest + QA)
    so a third build can be compared whole, not just on target values.
    """
    import matplotlib.pyplot as plt
    from figpact import style_identity as ident
    module, _, fig_base, reg_base, resolved = _fresh_build(script_p, config_p, scope)
    manifest = _manifest_of(module)
    bundle: dict[str, Any] = {"scope": resolved, "module": module}
    try:
        if any(desc is None for _, _, desc in want):
            descs = {d["id"]: d for d in ident.inventory(fig_base, scope=resolved)}
        else:
            descs = {}
        base_pairs: list[tuple] = []
        for tid, value, desc in want:
            use = descs.get(tid) if desc is None else desc
            if use is None:
                raise _VerifyFail([f"UNKNOWN_ID: {tid!r} not inventoried in "
                                   f"scope {resolved!r}"])
            if not use.get("unique") or not use.get("eligible"):
                raise _VerifyFail([f"AMBIGUOUS: {tid!r} not uniquely identifiable "
                                   f"({use.get('reason') or 'ambiguous'})"])
            try:
                _check_value(use["role"], use["property"], value, tid)
            except ValueError as error:
                raise _VerifyFail([str(error)]) from error
            try:
                artists = ident.resolve(fig_base, use, scope=resolved)
            except ValueError as error:
                raise _VerifyFail([str(error)]) from error
            base_pairs.append((tid, value, use, artists))
        tid_artists = {tid: arts for tid, _, _, arts in base_pairs}
        before = _snapshots(fig_base, reg_base, manifest, tid_artists)
        before_vals = {tid: ([float(a.get_fontsize()) for a in arts]
                             if use["role"] != "curve.linewidth"
                             else float(arts[0].get_linewidth()))
                       for tid, _, use, arts in base_pairs}
    finally:
        try:
            plt.close(fig_base)
        except Exception:
            pass
    module2, _, fig_sty, reg_sty, resolved2 = _fresh_build(script_p, config_p, scope)
    try:
        if resolved2 != resolved:
            raise _VerifyFail([f"SCOPE_MISMATCH: {resolved2!r} != {resolved!r}"])
        sty_pairs: list[tuple] = []
        for tid, value, use, _ in base_pairs:
            try:
                artists = ident.resolve(fig_sty, use, scope=resolved)
            except ValueError as error:
                raise _VerifyFail([str(error)]) from error
            sty_pairs.append((tid, value, use, artists))
        sty_artists = {tid: arts for tid, _, _, arts in sty_pairs}
        for tid, value, use, arts in sty_pairs:
            _set_absolute(arts, use["role"], use["property"], value)
        after = _snapshots(fig_sty, reg_sty, manifest, sty_artists)
        after_vals = {tid: ([float(a.get_fontsize()) for a in arts]
                            if use["role"] != "curve.linewidth"
                            else float(arts[0].get_linewidth()))
                      for tid, _, use, arts in sty_pairs}
        try:
            deps = _live_dependencies(module2, script_p, config_p)
            fenced = _protected_list(script_p, config_p, module2)
        except (ValueError, RuntimeError, OSError,
                FileNotFoundError, PermissionError) as error:
            raise _VerifyFail([str(error)]) from error
        bundle.update({"before": before, "after": after,
                       "before_vals": before_vals, "after_vals": after_vals,
                       "deps": deps, "protected": fenced,
                       "pairs": [(tid, value, use) for tid, value, use, _ in sty_pairs]})
        bundle["fingerprint"] = _snapshot_fingerprint(before, after)
        return bundle
    finally:
        try:
            plt.close(fig_sty)
        except Exception:
            pass


def _refuse(problem: str, overlay_p: Path, protected: list) -> dict:
    """One-line structured refusal: prior bytes stay, nothing executed."""
    return _build_receipt(local_edit_state="ERROR", local_problems=[problem],
                          source_commit_state="NOT_WRITTEN",
                          figure_verification_state="ERROR",
                          figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                          qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                          target_effects=[], science_unchanged=False,
                          science_notes=[problem], audit_summary={},
                          overlay_path=str(overlay_p), draft=False,
                          drift=problem, protected_sources=list(protected))


def _check_prior_source(prior: dict, script_p: Path, config_p: Path | None,
                        overlay_p: Path, request_scope: str | None) -> str | None:
    """Pre-import prior gate: source/config/scope + stored-bytes drift.

    Pure path arithmetic + disk hashing from the overlay's own stored refs;
    no import, no figure construction, so a drifted source is never executed
    (the drift marker test proves the changed script body never runs).
    Returns an error string or None.
    """
    if request_scope is not None and prior["scope"] != request_scope:
        return (f"SCOPE_MISMATCH: request scope {request_scope!r} != "
                f"prior overlay scope {prior['scope']!r}")
    try:
        prior_script = _restore_path(prior["script"], overlay_p.parent)
        prior_config_ref = prior.get("config")
        prior_config = (_restore_path(prior_config_ref, overlay_p.parent)
                        if prior_config_ref is not None else None)
    except Exception as error:
        return f"INVALID_OVERLAY: {error}"
    if prior_script != script_p or prior_config != config_p:
        return ("SOURCE_MISMATCH: request script/config differs from "
                "prior overlay source/config")
    stored_files = (prior.get("dependencies") or {}).get("files") or {}
    try:
        pre_paths = _dep_refs(prior, overlay_p.parent)
    except Exception as error:
        return f"INVALID_OVERLAY: {error}"
    return _drift_check(stored_files, pre_paths)


def _verify_clear(script_p: Path, config_p: Path | None, scope: str | None,
                  prior: dict, overlay_p: Path, protected0: list,
                  *, no_change_request: bool, actual_expected: str | None,
                  allow_draft: bool, module0: Any) -> dict | None:
    """Verify clear-to-original: empty targets rebuild, no fake effect."""
    import matplotlib.pyplot as plt
    want_scope = prior["scope"] if scope is None else scope
    try:
        m1, _, b1, r1, s1 = _fresh_build(script_p, config_p, want_scope)
        man1 = _manifest_of(m1)
        snap1 = _snapshots(b1, r1, man1, {})
    finally:
        try:
            plt.close(b1)
        except Exception:
            pass
    try:
        m2, _, b2, r2, s2 = _fresh_build(script_p, config_p, want_scope)
        man2 = _manifest_of(m2)
        snap2 = _snapshots(b2, r2, man2, {})
    finally:
        try:
            plt.close(b2)
        except Exception:
            pass
    if s1 != want_scope or s2 != want_scope:
        raise _VerifyFail([f"SCOPE_MISMATCH: {s1!r}/{s2!r} != {want_scope!r}"])
    audit = _verify_pair(snap1, snap2, allowed_styles={}, required=[],
                         proven=True)
    qa = bool(_qa_of(snap2)["pass"])
    base = {"qa_before": _qa_of(snap1), "figure_qa": _qa_of(snap2),
            "science_unchanged": audit["science_ok"],
            "science_notes": [str(n)[:300] for n in (audit["sci_notes"] or [])],
            "audit_summary": {"hard": len(audit["hard"]),
                              "derived_total": len(audit["derived"]),
                              "derived_allowed": len(audit["derived"])
                              if audit["derived_ok"] else 0,
                              "required_changed": audit["required_changed"],
                              "agreement": True, "pair_runs": 2, "cleared": True},
            "overlay_path": str(overlay_p), "drift": None,
            "protected_sources": list(protected0),
            "local_problems": list(audit["problems"]), "target_effects": []}
    if not audit["ok"]:
        return _build_receipt(local_edit_state="FAIL",
                              source_commit_state="NOT_WRITTEN",
                              figure_verification_state=_figure_state("FAIL", qa),
                              draft=False, **base)
    if not qa and not allow_draft:
        return _build_receipt(local_edit_state="PASS",
                              source_commit_state="NOT_WRITTEN",
                              figure_verification_state="FAIL", draft=False, **base)
    try:
        deps = _live_dependencies(module0, script_p, config_p)
    except (ValueError, RuntimeError, OSError,
            FileNotFoundError, PermissionError) as error:
        failed = dict(base)
        failed.update(local_edit_state="ERROR", local_problems=[str(error)],
                      source_commit_state="NOT_WRITTEN",
                      figure_verification_state="ERROR", draft=False,
                      drift=str(error))
        return _build_receipt(**failed)
    mismatch = _live_drift_check((prior.get("dependencies") or {}).get("files")
                                 or {}, deps)
    if mismatch is not None:
        failed = dict(base)
        failed.update(local_edit_state="ERROR", local_problems=[mismatch],
                      source_commit_state="NOT_WRITTEN",
                      figure_verification_state="ERROR", draft=False,
                      drift=mismatch)
        return _build_receipt(**failed)
    try:
        odir = overlay_p.parent
        sref = _store_path(script_p, odir)
        cref = (_store_path(config_p, odir) if config_p is not None else None)
        files: dict[str, dict] = {}
        for oname, (opath, ohash) in deps.items():
            files[oname] = {"ref": _store_path(Path(opath).resolve(), odir),
                            "sha256": ohash}
    except Exception as error:
        failed = dict(base)
        failed.update(local_edit_state="ERROR",
                      local_problems=[f"REL_PATH: {error}"],
                      source_commit_state="NOT_WRITTEN",
                      figure_verification_state="ERROR", draft=False,
                      drift=f"REL_PATH: {error}")
        return _build_receipt(**failed)
    core = {"schema": OVERLAY_SCHEMA, "script": sref, "config": cref,
            "scope": prior["scope"], "targets": [],
            "dependencies": {"files": files},
            "generator": "figpact.style_overlay/1"}
    _validate_overlay_shape({**core, "created_at": "1970-01-01T00:00:00+00:00"})
    prior_doc = json.loads(overlay_p.read_bytes().decode("utf-8"))
    prior_core = {k: prior_doc.get(k) for k in
                  ("schema", "script", "config", "scope",
                   "targets", "dependencies", "generator")}
    same = (json.dumps(prior_core, sort_keys=True, ensure_ascii=False,
                        separators=(",", ":"), allow_nan=False) == json.dumps(
        core, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False))
    if same:
        draft = not qa
        ok = dict(base)
        ok.update(local_edit_state="PASS", local_problems=[],
                  source_commit_state="COMMITTED_DRAFT" if draft else "COMMITTED",
                  figure_verification_state=_figure_state("PASS", qa), draft=draft)
        return _build_receipt(**ok)
    doc = dict(core)
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    _validate_overlay_shape(doc)
    from figpact import source_writes as _sw
    try:
        _sw._write_json(overlay_p, doc)
    except Exception as error:
        failed = dict(base)
        failed.update(local_edit_state="ERROR",
                      local_problems=[f"WRITE_FAILED: {error}"],
                      source_commit_state="NOT_WRITTEN",
                      figure_verification_state="ERROR", draft=False,
                      drift=f"WRITE_FAILED: {error}")
        return _build_receipt(**failed)
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    if _sha256_file(overlay_p) != _sha256_bytes(payload):
        failed = dict(base)
        failed.update(local_edit_state="ERROR",
                      local_problems=["WRITE_VERIFY: overlay bytes mismatch"],
                      source_commit_state="NOT_WRITTEN",
                      figure_verification_state="ERROR", draft=False,
                      drift="WRITE_VERIFY: overlay bytes mismatch")
        return _build_receipt(**failed)
    draft = not qa
    ok = dict(base)
    ok.update(local_edit_state="PASS", local_problems=[],
              source_commit_state="COMMITTED_DRAFT" if draft else "COMMITTED",
              figure_verification_state=_figure_state("PASS", qa), draft=draft)
    return _build_receipt(**ok)

def _build_receipt(**fields: Any) -> dict:
    """Single receipt constructor: later kwargs win, never duplicate keys.

    Conflict/create branches set ``drift``/``figure_verification_state`` by
    overriding the base dict first (``dict.update`` then one splat) -- no
    call site may pass the same keyword twice.
    """
    doc = {"schema": RECEIPT_SCHEMA}
    doc.update(fields)
    return json.loads(json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                 allow_nan=False, default=str))


def _receipt(base: dict, **overrides: Any) -> dict:
    merged = dict(base)
    merged.update(overrides)
    return _build_receipt(**merged)


def _bundle_receipt_base(bundle: dict, overlay_p: Path) -> dict:
    return dict(qa_before=_qa_of(bundle["before"]),
                figure_qa=_qa_of(bundle["after"]),
                science_unchanged=bundle["verify"]["science_ok"],
                science_notes=[str(n)[:300] for n in
                               (bundle["verify"]["sci_notes"] or [])],
                audit_summary={"hard": len(bundle["verify"]["hard"]),
                               "derived_total": len(bundle["verify"]["derived"]),
                               "derived_allowed": len(bundle["verify"]["derived"])
                               if bundle["verify"]["derived_ok"] else 0,
                               "required_changed": bundle["verify"]["required_changed"],
                               "agreement": bundle.get("agreement"),
                               "pair_runs": 2},
                overlay_path=str(overlay_p), drift=None,
                protected_sources=bundle["protected"])


def _effects_of(bundle: dict, verdict: dict) -> tuple[list[dict], list[str]]:
    effects: list[dict] = []
    problems: list[str] = []
    for tid, value, use in bundle["pairs"]:
        after_v = bundle["after_vals"][tid]
        effects.append({"id": tid, "role": use["role"], "property": use["property"],
                        "before": _native(bundle["before_vals"][tid]),
                        "after": _native(after_v),
                        "requested": _native(value)})
        if verdict["ok"] and after_v != value \
                and not (isinstance(after_v, list)
                         and all(v == value for v in after_v)):
            problems.append(f"target {tid!r} did not take the absolute value")
    return effects, problems


def _write_new_exclusive(path: Path, payload: bytes) -> None:
    """Create-only install: staged temp file + must-not-exist hardlink.

    The full payload is first staged with the existing atomic writer in the
    target directory (complete bytes, fsync, no partial JSON ever installed);
    then ``os.link`` installs it atomically with must-not-exist semantics.
    A rival creator wins the link and we refuse; a crash before the link
    leaves only an unlinked temp file. Cross-volume/unsupported links are an
    explicit ``SourceWriteError`` -- never a fallback overwrite. Uses only
    existing ``source_writes`` primitives (``_write_json`` + ``_fsync_dir``).
    """
    import uuid
    from figpact import source_writes as sw
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise sw.SourceWriteError(
            f'STATE_UNWRITABLE: {path}：状态文件无法写入（{error}）') from error
    staging = path.with_name(f'.overlay-stage-{uuid.uuid4().hex}.json')
    try:
        sw._write_json(staging, json.loads(payload.decode("utf-8")))
    except Exception:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    try:
        try:
            os.link(str(staging), str(path))
        except FileExistsError:
            raise
        except OSError as error:
            raise sw.SourceWriteError(
                f'LINK_UNSUPPORTED: {path}：无法原子安装（{error}）；拒绝覆盖') from error
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        sw._fsync_dir(path.parent)
    except Exception:
        pass


def apply(script: Any, config: Any = None, scope: str | None = None, *,
          edits: list[dict], overlay: Any,
          expected_before_sha256: str | None = None,
          allow_draft: bool = False, remove: list[str] | None = None) -> dict:
    """Verify requested absolute style values and atomically persist overlay.

    G17 composable: ``edits`` is an incremental upsert (unmentioned targets
    are retained), ``remove`` explicitly deletes saved targets. Empty
    ``edits`` with nonempty ``remove`` is valid; ``edits=[]`` + ``remove=[]``
    on an existing overlay is a no-op retaining all targets (still hash
    gated); on a missing overlay it is refused. Only an explicit ``remove``
    of every saved id yields ``targets=[]`` (clear-to-original).
    """
    import matplotlib.pyplot as plt
    script_p = Path(script).resolve()
    config_p = Path(config).resolve() if config is not None else None
    overlay_p = Path(overlay).resolve()
    try:
        clean = _validate_edits(edits)
        doomed = _validate_remove(remove)
    except ValueError as error:
        return _build_receipt(local_edit_state="ERROR", local_problems=[str(error)],
                              source_commit_state="NOT_WRITTEN",
                              figure_verification_state="ERROR",
                              figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                              qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                              target_effects=[], science_unchanged=False,
                              science_notes=[str(error)], audit_summary={},
                              overlay_path=str(overlay_p), draft=False,
                              drift=None, protected_sources=[])
    overlap = {item["target_id"] for item in clean} & set(doomed)
    if overlap:
        problem = (f"CONFLICT: target(s) {sorted(overlap)} requested "
                   "as both upsert and remove")
        return _build_receipt(local_edit_state="ERROR", local_problems=[problem],
                              source_commit_state="NOT_WRITTEN",
                              figure_verification_state="ERROR",
                              figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                              qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                              target_effects=[], science_unchanged=False,
                              science_notes=[problem], audit_summary={},
                              overlay_path=str(overlay_p), draft=False,
                              drift=None, protected_sources=[])
    # Mandatory prior gate FIRST (hash, source/config/scope, stored drift):
    # before reading/importing the script any further, so a drifted source
    # is never executed by a mere update/remove request.
    prior_raw: bytes | None = None
    prior: dict | None = None
    if overlay_p.exists():
        try:
            prior_raw = overlay_p.read_bytes()
            prior = json.loads(prior_raw.decode("utf-8"))
            _validate_overlay_shape(prior)
        except Exception as error:
            return _refuse(f"INVALID_OVERLAY: prior overlay unreadable ({error})",
                           overlay_p, [])
        if expected_before_sha256 is None:
            return _refuse("CREATE_CONFLICT: overlay already exists; pass "
                           "expected_before_sha256 to update", overlay_p, [])
        actual = _sha256_bytes(prior_raw if prior_raw is not None else b"")
        if actual != expected_before_sha256:
            return _refuse(
                f"STALE_SOURCE: overlay before {expected_before_sha256} "
                f"!= disk {actual}", overlay_p, [])
        gated = _check_prior_source(prior, script_p, config_p, overlay_p, scope)
        if gated is not None:
            return _refuse(gated, overlay_p, [])
    # Pre-execution gates: import only (no figure construction), hash the
    # named dependency bytes first, and refuse an overlay output that would
    try:
        module0 = _import_only(script_p)
    except Exception as error:
        return _build_receipt(local_edit_state="ERROR", local_problems=[str(error)],
                              source_commit_state="NOT_WRITTEN",
                              figure_verification_state="ERROR",
                              figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                              qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                              target_effects=[], science_unchanged=False,
                              science_notes=[str(error)], audit_summary={},
                              overlay_path=str(overlay_p), draft=False,
                              drift=str(error), protected_sources=[str(script_p)])
    try:
        protected0 = _protected_list(script_p, config_p, module0)
    except (ValueError, RuntimeError, OSError,
            FileNotFoundError, PermissionError) as error:
        return _build_receipt(local_edit_state="ERROR", local_problems=[str(error)],
                              source_commit_state="NOT_WRITTEN",
                              figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                              qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                              target_effects=[], science_unchanged=False,
                              science_notes=[str(error)], audit_summary={},
                              overlay_path=str(overlay_p), draft=False,
                              drift=str(error), protected_sources=[str(script_p)])
    if str(overlay_p) in {str(Path(p).resolve()) for p in protected0}:
        problem = (f"REFUSED: overlay output {overlay_p} would overwrite "
                   "a protected source/dependency")
        return _build_receipt(local_edit_state="ERROR", local_problems=[problem],
                              source_commit_state="NOT_WRITTEN",
                              figure_verification_state="ERROR",
                              figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                              qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                              target_effects=[], science_unchanged=False,
                              science_notes=[problem], audit_summary={},
                              overlay_path=str(overlay_p), draft=False,
                              drift=problem, protected_sources=protected0)
    if prior is None:
        if doomed:
            missing = sorted(set(doomed))
            problem = (f"REMOVE_MISSING: target(s) {missing} not saved "
                       "(no prior overlay)")
            return _build_receipt(local_edit_state="ERROR",
                                  local_problems=[problem],
                                  source_commit_state="NOT_WRITTEN",
                                  figure_verification_state="ERROR",
                                  figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                                  qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                                  target_effects=[], science_unchanged=False,
                                  science_notes=[problem], audit_summary={},
                                  overlay_path=str(overlay_p), draft=False,
                                  drift=None, protected_sources=protected0)
        if not clean:
            problem = ("INVALID_EDITS: nothing to apply: edits is empty and "
                       "no prior overlay exists")
            return _build_receipt(local_edit_state="ERROR", local_problems=[problem],
                                  source_commit_state="NOT_WRITTEN",
                                  figure_verification_state="ERROR",
                                  figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                                  qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                                  target_effects=[], science_unchanged=False,
                                  science_notes=[problem], audit_summary={},
                                  overlay_path=str(overlay_p), draft=False,
                                  drift=None, protected_sources=protected0)
    if prior is not None:
        saved_ids = [item["id"] for item in prior["targets"]]
        absent = [tid for tid in doomed if tid not in set(saved_ids)]
        if absent:
            problem = (f"REMOVE_MISSING: target(s) {absent} not in "
                       "saved overlay")
            return _build_receipt(local_edit_state="ERROR",
                                  local_problems=[problem],
                                  source_commit_state="NOT_WRITTEN",
                                  figure_verification_state="ERROR",
                                  figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                                  qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                                  target_effects=[], science_unchanged=False,
                                  science_notes=[problem], audit_summary={},
                                  overlay_path=str(overlay_p), draft=False,
                                  drift=None, protected_sources=protected0)
    # Upsert + retained merge. No-op = empty request on existing overlay
    # (retains all targets, still fully verified); removal of every saved id
    # yields targets=[] (verified clear-to-original).
    if prior is not None:
        if not clean and not doomed:
            merged_want: list[tuple] = [
                (item["id"], float(item["value"]), item["descriptor"])
                for item in prior["targets"]]
            no_change_request = True
        else:
            doomed_set = set(doomed)
            upsert = {item["target_id"]: item["value"] for item in clean}
            merged_want = []
            for item in prior["targets"]:
                if item["id"] in doomed_set:
                    continue
                merged_want.append((item["id"], upsert.pop(item["id"], item["value"]),
                                    item["descriptor"]))
            for tid, value in upsert.items():
                merged_want.append((tid, value, None))
            no_change_request = False
    else:
        merged_want = [(item["target_id"], item["value"], None) for item in clean]
        no_change_request = False
    from figpact import style_identity as ident
    try:
        probe_mod, _, probe_fig, _, probe_scope = _fresh_build(
            script_p, config_p, scope)
        try:
            probe_descs = {d["id"]: d for d in ident.inventory(
                probe_fig, scope=probe_scope)}
            if prior is not None and probe_scope != prior["scope"]:
                raise _VerifyFail([f"SCOPE_MISMATCH: live scope {probe_scope!r} "
                                   f"!= prior overlay scope {prior['scope']!r}"])
            seen_ident: set[str] = set()
            # Removal bypass guard: every REMOVED id must still resolve to a
            # structurally identical live target. A disappeared target cannot
            # be laundered through `remove`. Retained ids are rechecked below
            # via merged_want; no double-counting (no fake DUPLICATE on upsert
            # of an already-saved id, since merged dedups prior+new).
            if prior is not None:
                doomed_now = set(doomed)
                for item in prior["targets"]:
                    if item["id"] not in doomed_now:
                        continue
                    probe = probe_descs.get(item["id"])
                    if probe is None:
                        raise _VerifyFail([f"UNKNOWN_ID: {item['id']!r} not inventoried"])
                    if not probe.get("unique") or not probe.get("eligible"):
                        raise _VerifyFail([f"AMBIGUOUS: {item['id']!r} not uniquely identifiable "
                                           f"({probe.get('reason') or 'ambiguous'})"])
                    if (json.dumps(ident.match_identity(item["descriptor"]), sort_keys=True)
                            != json.dumps(ident.match_identity(probe), sort_keys=True)):
                        raise _VerifyFail([f"DRIFT: target {item['id']!r} structural identity "
                                           "changed; refusing nearest match"])
            for tid, _, desc in merged_want:
                probe = None if desc is None else probe_descs.get(tid)
                if desc is not None:
                    # Retained descriptor: still inventoried, structurally
                    # identical, unique/eligible (identity via resolve, not
                    # the stale `current` reading).
                    if probe is None:
                        raise _VerifyFail([f"UNKNOWN_ID: {tid!r} not inventoried"])
                    if not probe.get("unique") or not probe.get("eligible"):
                        raise _VerifyFail([f"AMBIGUOUS: {tid!r} not uniquely identifiable "
                                           f"({probe.get('reason') or 'ambiguous'})"])
                    if (json.dumps(ident.match_identity(desc), sort_keys=True)
                            != json.dumps(ident.match_identity(probe), sort_keys=True)):
                        raise _VerifyFail([f"DRIFT: target {tid!r} structural identity "
                                           "changed; refusing nearest match"])
                    key = json.dumps(ident.match_identity(probe), sort_keys=True)
                else:
                    fresh = probe_descs.get(tid)
                    if fresh is None:
                        raise _VerifyFail([f"UNKNOWN_ID: {tid!r} not inventoried"])
                    if not fresh.get("unique") or not fresh.get("eligible"):
                        raise _VerifyFail([f"AMBIGUOUS: {tid!r} not uniquely identifiable "
                                           f"({fresh.get('reason') or 'ambiguous'})"])
                    key = json.dumps(ident.match_identity(fresh), sort_keys=True)
                if key in seen_ident:
                    raise _VerifyFail([f"DUPLICATE_TARGET: {tid!r} duplicates an "
                                       "already requested identity"])
                seen_ident.add(key)
        finally:
            try:
                plt.close(probe_fig)
            except Exception:
                pass
        if prior is not None and not merged_want:
            cleared = _verify_clear(script_p, config_p, scope, prior,
                                    overlay_p, protected0,
                                    no_change_request=no_change_request,
                                    actual_expected=expected_before_sha256,
                                    allow_draft=allow_draft, module0=module0)
            if cleared is not None:
                return cleared
            raise _VerifyFail(["CLEAR_FAILED: original-baseline rebuild failed"])
        run1 = _pair_run(script_p, config_p, scope, merged_want)
        run2 = _pair_run(script_p, config_p, scope, merged_want)
    except _VerifyFail as failure:
        return _build_receipt(local_edit_state="ERROR",
                              local_problems=failure.problems,
                              source_commit_state="NOT_WRITTEN",
                              figure_verification_state="ERROR",
                              figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                              qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                              target_effects=[], science_unchanged=False,
                              science_notes=failure.problems, audit_summary={},
                              overlay_path=str(overlay_p), draft=False,
                              drift=None, protected_sources=protected0)
    allowed = {tid: {use["property"]} for tid, _, use in run1["pairs"]}
    required = [{"gid": tid, "property": use["property"]}
                for tid, _, use in run1["pairs"]]
    v1 = _verify_pair(run1["before"], run1["after"], allowed_styles=allowed,
                      required=required, proven=False)
    v2 = _verify_pair(run2["before"], run2["after"], allowed_styles=allowed,
                      required=required, proven=False)
    agreement = (v1["derived_keys"] == v2["derived_keys"]
                 and run1["after_vals"] == run2["after_vals"]
                 and run1["before_vals"] == run2["before_vals"]
                 and v1["required_changed"] == v2["required_changed"])
    verdict = _verify_pair(run1["before"], run1["after"], allowed_styles=allowed,
                           required=required, proven=agreement)
    if not agreement:
        verdict = dict(verdict)
        verdict["ok"] = False
        verdict["problems"] = list(verdict["problems"]) + [
            "nondeterministic rebuild: two independent pairs disagree"]
    run1["verify"] = verdict
    run1["agreement"] = agreement
    base_receipt = _bundle_receipt_base(run1, overlay_p)
    base_receipt["local_edit_state"] = "PASS" if verdict["ok"] else "FAIL"
    base_receipt["local_problems"] = list(verdict["problems"])
    effects, effect_problems = _effects_of(run1, verdict)
    base_receipt["target_effects"] = effects
    base_receipt["audit_summary"]["transition"] = {
        "requested_upserts": [item["target_id"] for item in clean],
        "requested_removals": list(doomed),
        "retained": [tid for tid, _, _ in merged_want
                     if tid not in {c["target_id"] for c in clean}
                     and tid not in set(doomed)],
        "no_change_request": bool(no_change_request)}
    if effect_problems:
        base_receipt["local_edit_state"] = "FAIL"
        base_receipt["local_problems"] = list(verdict["problems"]) + effect_problems
        verdict = dict(verdict)
        verdict["ok"] = False
    qa_pass = bool(base_receipt["figure_qa"]["pass"])
    fig_state = _figure_state(base_receipt["local_edit_state"], qa_pass)
    if not verdict["ok"]:
        return _receipt(base_receipt, source_commit_state="NOT_WRITTEN",
                        figure_verification_state=fig_state, draft=False)
    if not qa_pass and not allow_draft:
        return _receipt(base_receipt, source_commit_state="NOT_WRITTEN",
                        figure_verification_state="FAIL", draft=False)
    # Drift between verification and persist refuses to write (exact set).
    # ``_live_drift_check`` takes live ``(path, hash)`` tuples directly.
    try:
        deps_now = _live_dependencies(module0, script_p, config_p)
    except (ValueError, RuntimeError, OSError,
            FileNotFoundError, PermissionError) as error:
        return _receipt(base_receipt, source_commit_state="NOT_WRITTEN",
                        figure_verification_state="ERROR",
                        draft=False, drift=str(error))
    live_named = {k: {"sha256": v[1]} for k, v in run1["deps"].items()}
    drift = _live_drift_check(live_named, deps_now)
    if drift is not None:
        return _receipt(base_receipt, source_commit_state="NOT_WRITTEN",
                        figure_verification_state="ERROR",
                        draft=False, drift=drift)
    try:
        base_dir = overlay_p.parent
        script_ref = _store_path(script_p, base_dir)
        config_ref = (_store_path(config_p, base_dir)
                      if config_p is not None else None)
        dep_files: dict[str, dict] = {}
        for name, (live_path, live_hash) in deps_now.items():
            dep_files[name] = {"ref": _store_path(Path(live_path).resolve(), base_dir),
                               "sha256": live_hash}
    except Exception as error:
        failed = dict(base_receipt)
        failed.update(source_commit_state="NOT_WRITTEN",
                      figure_verification_state="ERROR", draft=False,
                      drift=f"REL_PATH: {error}")
        return _build_receipt(**failed)
    doc_core = {"schema": OVERLAY_SCHEMA, "script": script_ref,
                "config": config_ref, "scope": run1["scope"],
                "targets": [{"id": tid, "descriptor": use, "value": _native(value)}
                            for tid, value, use in run1["pairs"]],
                "dependencies": {"files": dep_files},
                "generator": "figpact.style_overlay/1"}
    _validate_overlay_shape({**doc_core, "created_at": "1970-01-01T00:00:00+00:00"})
    from figpact import source_writes as _sw  # noqa: F401 (single-writer note)
    if prior is not None:
        try:
            prior_raw = overlay_p.read_bytes()
            prior_doc = json.loads(prior_raw.decode("utf-8"))
            prior_core = {k: prior_doc.get(k) for k in
                          ("schema", "script", "config", "scope",
                           "targets", "dependencies", "generator")}
            if json.dumps(prior_core, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False) == json.dumps(
                    doc_core, sort_keys=True, ensure_ascii=False,
                    separators=(",", ":"), allow_nan=False):
                draft = not qa_pass
                state = "COMMITTED_DRAFT" if draft else "COMMITTED"
                return _receipt(base_receipt, source_commit_state=state,
                                figure_verification_state=_figure_state("PASS", qa_pass),
                                draft=draft)
        except (OSError, ValueError):
            pass
    doc = dict(doc_core)
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    _validate_overlay_shape(doc)
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    try:
        if expected_before_sha256 is None:
            _write_new_exclusive(overlay_p, payload)  # create-only transaction
        else:
            _sw._write_json(overlay_p, doc)  # existing atomic writer, no new txn
    except FileExistsError:
        return _receipt(
            base_receipt, source_commit_state="NOT_WRITTEN",
            figure_verification_state="ERROR", draft=False,
            drift="CREATE_CONFLICT: overlay created concurrently; retry "
                  "with expected_before_sha256")
    except Exception as error:
        failed = dict(base_receipt)
        failed.update(source_commit_state="NOT_WRITTEN",
                      figure_verification_state="ERROR", draft=False,
                      drift=f"WRITE_FAILED: {error}")
        return _build_receipt(**failed)
    if _sha256_file(overlay_p) != _sha256_bytes(payload):
        return _receipt(base_receipt, source_commit_state="NOT_WRITTEN",
                        figure_verification_state="ERROR", draft=False,
                        drift="WRITE_VERIFY: overlay bytes mismatch")
    draft = not qa_pass
    return _receipt(base_receipt,
                    source_commit_state="COMMITTED_DRAFT" if draft else "COMMITTED",
                    figure_verification_state=_figure_state("PASS", qa_pass),
                    draft=draft)


def _open_styled(script_p: Path, config_p: Path | None, scope: str,
                 pairs: list, expected: dict) -> tuple:
    """Rebuild the render figure and verify its FULL snapshot fingerprint.

    The third build is compared whole against the verified ``after``
    snapshot (alias-merged styles, shapes, view, science digest, QA) plus
    exact target values -- a nondeterministic third build that drifts in
    any non-target style, geometry, science, view or QA is closed and
    refused, never rendered. Returns the open figure only on full match.
    """
    import matplotlib.pyplot as plt
    from figpact import style_identity as ident
    module, _, fig, reg, resolved = _fresh_build(script_p, config_p, scope)
    try:
        manifest = _manifest_of(module)
        if resolved != scope:
            raise _VerifyFail([f"SCOPE_MISMATCH: {resolved!r} != {scope!r}"])
        live: list[tuple] = []
        for tid, value, use in pairs:
            try:
                artists = ident.resolve(fig, use, scope=scope)
            except ValueError as error:
                raise _VerifyFail([str(error)]) from error
            _set_absolute(artists, use["role"], use["property"], float(value))
            live.append((tid, artists))
        tid_artists = {tid: arts for tid, arts in live}
        got_vals = {tid: ([float(a.get_fontsize()) for a in arts]
                          if next(u for i, _, u in pairs if i == tid)["role"]
                          != "curve.linewidth"
                          else float(arts[0].get_linewidth()))
                    for tid, arts in live}
        if got_vals != expected["after_vals"]:
            bad = [tid for tid in got_vals if got_vals[tid] != expected["after_vals"][tid]]
            raise _VerifyFail([f"REOPEN_MISMATCH: {bad!r} reopened values differ "
                               "from verified candidate"])
        snap = _snapshots(fig, reg, manifest, tid_artists)
        got_fp = _snapshot_fingerprint(expected["before"], snap)
        want_fp = _snapshot_fingerprint(expected["before"], expected["after"])
        if got_fp != want_fp:
            bad = [k for k in want_fp if got_fp.get(k) != want_fp.get(k)]
            raise _VerifyFail([f"REOPEN_FINGERPRINT_MISMATCH: third build differs "
                               f"in {bad!r}; refusing nondeterministic render"])
        qa_now = _qa_of(snap)
        if not qa_now["pass"] and expected["qa"]["pass"]:
            raise _VerifyFail(["REOPEN_QA_REGRESSION: render-time QA differs "
                               "from verified candidate"])
        return fig, reg
    except Exception:
        try:
            plt.close(fig)
        except Exception:
            pass
        raise


def load(overlay_path: Any) -> tuple:
    """Clean rebuild + stored overlay, returning ``(fig, reg, receipt)``.

    Dependency bytes are hashed and compared BEFORE any figure is built.
    Verification uses two independent rebuild pairs; the returned figure is
    a third fresh build whose target values must equal the verified ones.
    The figure stays open only when the local edit verifies; otherwise
    ``(None, None, receipt)`` so the CLI cannot render an unverified figure
    and never reimplements state judgement.
    """
    import matplotlib.pyplot as plt
    overlay_p = Path(overlay_path).resolve()
    try:
        raw = overlay_p.read_bytes()
    except OSError as error:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[f"READ: {error}"],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=str(error), protected_sources=[])
        return None, None, receipt
    try:
        doc = json.loads(raw.decode("utf-8"))
        _validate_overlay_shape(doc)
    except Exception as error:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[f"INVALID_OVERLAY: {error}"],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=str(error), protected_sources=[])
        return None, None, receipt
    base = overlay_p.parent
    try:
        script_p = _restore_path(doc["script"], base)
        config_ref = doc.get("config")
        config_p = _restore_path(config_ref, base) if config_ref is not None else None
    except Exception as error:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[f"INVALID_OVERLAY: {error}"],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=str(error), protected_sources=[])
        return None, None, receipt
    scope = doc["scope"]
    stored_files = (doc.get("dependencies") or {}).get("files") or {}
    # Pre-import drift gate: hash the overlay's OWN stored paths from disk
    # BEFORE importing anything (a wrapper import can execute module code).
    # Post-import, the live inventory (real module.RAW + science inputs) is
    # compared as an exact name-set + per-name hash match to catch forgery.
    try:
        pre_paths = _dep_refs(doc, base)
    except Exception as error:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[f"INVALID_OVERLAY: {error}"],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=str(error), protected_sources=[str(script_p)] +
            ([str(config_p)] if config_p is not None else []))
        return None, None, receipt
    pre_drift = _drift_check(stored_files, pre_paths)
    if pre_drift is not None:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[pre_drift],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[pre_drift],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=pre_drift, protected_sources=[str(script_p)] +
            ([str(config_p)] if config_p is not None else []))
        return None, None, receipt
    protected = [str(script_p)]
    if config_p is not None:
        protected.append(str(config_p))
    try:
        module0 = _import_only(script_p)
    except Exception as error:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[str(error)],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=str(error), protected_sources=protected)
        return None, None, receipt
    try:
        protected = _protected_list(script_p, config_p, module0)
        live = _live_dependencies(module0, script_p, config_p)
    except (ValueError, RuntimeError, OSError,
            FileNotFoundError, PermissionError) as error:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[str(error)],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[str(error)],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=str(error), protected_sources=protected)
        return None, None, receipt
    drift = _live_drift_check(stored_files, live)
    if drift is not None:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=[drift],
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False, science_notes=[drift],
            audit_summary={}, overlay_path=str(overlay_p), draft=False,
            drift=drift, protected_sources=protected)
    if not doc["targets"]:
        import matplotlib.pyplot as _plt
        try:
            _m1, _, _f1, _g1, _s1 = _fresh_build(script_p, config_p, scope)
            _n1 = _manifest_of(_m1)
            _p1 = _snapshots(_f1, _g1, _n1, {})
        finally:
            try:
                _plt.close(_f1)
            except Exception:
                pass
        try:
            _m2, _, _f2, _g2, _s2 = _fresh_build(script_p, config_p, scope)
            _n2 = _manifest_of(_m2)
            _p2 = _snapshots(_f2, _g2, _n2, {})
        finally:
            try:
                _plt.close(_f2)
            except Exception:
                pass
        if _s1 != scope or _s2 != scope:
            _fail = _build_receipt(
                local_edit_state="ERROR",
                local_problems=[f"SCOPE_MISMATCH: {_s1!r}/{_s2!r} != {scope!r}"],
                source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
                figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
                qa_before={"blocking": [], "glyph_floor": [], "pass": False},
                target_effects=[], science_unchanged=False, science_notes=[],
                audit_summary={}, overlay_path=str(overlay_p), draft=False,
                drift=None, protected_sources=protected)
            return None, None, _fail
        _vd = _verify_pair(_p1, _p2, allowed_styles={}, required=[], proven=True)
        _agree = True
        _qa = _qa_of(_p2)
        _qb = _qa_of(_p1)
        _base = {"qa_before": _qb, "figure_qa": _qa,
                 "science_unchanged": _vd["science_ok"],
                 "science_notes": [str(n)[:300] for n in (_vd["sci_notes"] or [])],
                 "audit_summary": {"hard": len(_vd["hard"]),
                                   "derived_total": len(_vd["derived"]),
                                   "derived_allowed": len(_vd["derived"])
                                   if _vd["derived_ok"] else 0,
                                   "required_changed": _vd["required_changed"],
                                   "agreement": _agree, "pair_runs": 2, "cleared": True},
                 "overlay_path": str(overlay_p), "drift": None,
                 "protected_sources": protected,
                 "target_effects": [], "local_problems": list(_vd["problems"])}
        _base["local_edit_state"] = "PASS" if _vd["ok"] else "FAIL"
        _qp = bool(_qa["pass"])
        if not _vd["ok"]:
            _fail = _build_receipt(**_base, source_commit_state="NOT_WRITTEN",
                                   figure_verification_state=_figure_state("FAIL", _qp),
                                   draft=False)
            return None, None, _fail
        try:
            _fig, _reg = _open_styled(script_p, config_p, scope, [],
                                      {"after_vals": {},
                                       "before": _p1, "after": _p2, "qa": _qa})
        except _VerifyFail as _failure:
            _fail = _build_receipt(**_base, source_commit_state="NOT_WRITTEN",
                                   figure_verification_state="ERROR", draft=False,
                                   local_edit_state="ERROR",
                                   local_problems=_failure.problems)
            return None, None, _fail
        _done = _build_receipt(**_base, source_commit_state="NOT_WRITTEN",
                               figure_verification_state=_figure_state("PASS", _qp),
                               draft=bool(not _qp))
        if not _qp:
            try:
                _plt.close(_fig)
            except Exception:
                pass
            return None, None, _done
        return _fig, _reg, _done
    want = [(item["id"], float(item["value"]), item["descriptor"])
            for item in doc["targets"]]
    try:
        run1 = _pair_run(script_p, config_p, scope, want)
        run2 = _pair_run(script_p, config_p, scope, want)
    except _VerifyFail as failure:
        receipt = _build_receipt(
            local_edit_state="ERROR", local_problems=failure.problems,
            source_commit_state="NOT_WRITTEN", figure_verification_state="ERROR",
            figure_qa={"blocking": [], "glyph_floor": [], "pass": False},
            qa_before={"blocking": [], "glyph_floor": [], "pass": False},
            target_effects=[], science_unchanged=False,
            science_notes=failure.problems, audit_summary={},
            overlay_path=str(overlay_p), draft=False,
            drift=None, protected_sources=protected)
        return None, None, receipt
    allowed = {tid: {use["property"]} for tid, _, use in run1["pairs"]}
    required = [{"gid": tid, "property": use["property"]}
                for tid, _, use in run1["pairs"]]
    v1 = _verify_pair(run1["before"], run1["after"], allowed_styles=allowed,
                      required=required, proven=False)
    v2 = _verify_pair(run2["before"], run2["after"], allowed_styles=allowed,
                      required=required, proven=False)
    agreement = (v1["derived_keys"] == v2["derived_keys"]
                 and run1["after_vals"] == run2["after_vals"]
                 and run1["before_vals"] == run2["before_vals"]
                 and v1["required_changed"] == v2["required_changed"])
    verdict = _verify_pair(run1["before"], run1["after"], allowed_styles=allowed,
                           required=required, proven=agreement)
    if not agreement:
        verdict = dict(verdict)
        verdict["ok"] = False
        verdict["problems"] = list(verdict["problems"]) + [
            "nondeterministic rebuild: two independent pairs disagree"]
    run1["verify"] = verdict
    run1["agreement"] = agreement
    run1["protected"] = protected
    base_receipt = _bundle_receipt_base(run1, overlay_p)
    base_receipt["local_edit_state"] = "PASS" if verdict["ok"] else "FAIL"
    base_receipt["local_problems"] = list(verdict["problems"])
    effects, effect_problems = _effects_of(run1, verdict)
    base_receipt["target_effects"] = effects
    if effect_problems:
        base_receipt["local_edit_state"] = "FAIL"
        base_receipt["local_problems"] = list(verdict["problems"]) + effect_problems
        verdict = dict(verdict)
        verdict["ok"] = False
    qa_pass = bool(base_receipt["figure_qa"]["pass"])
    if not verdict["ok"]:
        receipt = _build_receipt(**base_receipt, source_commit_state="NOT_WRITTEN",
                                 figure_verification_state=_figure_state("FAIL", qa_pass),
                                 draft=False)
        return None, None, receipt
    try:
        fig, reg = _open_styled(script_p, config_p, run1["scope"],
                                run1["pairs"], {"after_vals": run1["after_vals"],
                                                "before": run1["before"],
                                                "after": run1["after"],
                                                "qa": base_receipt["figure_qa"]})
    except _VerifyFail as failure:
        receipt = _build_receipt(**base_receipt, source_commit_state="NOT_WRITTEN",
                                 figure_verification_state="ERROR", draft=False,
                                 local_edit_state="ERROR",
                                 local_problems=failure.problems)
        return None, None, receipt
    receipt = _build_receipt(**base_receipt, source_commit_state="NOT_WRITTEN",
                             figure_verification_state=_figure_state("PASS", qa_pass),
                             draft=bool(not qa_pass))
    if not qa_pass:
        try:
            plt.close(fig)
        except Exception:
            pass
        return None, None, receipt
    return fig, reg, receipt


def render(overlay_path: Any, output: Any) -> dict:
    """Replay an overlay from clean source and write one image (core-owned check)."""
    import matplotlib.pyplot as plt
    overlay_p = Path(overlay_path).resolve()
    output_p = Path(output).resolve()
    fig, _, receipt = load(overlay_p)
    if fig is None:
        # Draft/FAIL overlays never render: load already refused the figure.
        # Rendering onto the overlay path itself is always refused even when
        # load passed (it would clobber the verified declaration).
        receipt = dict(receipt)
        if output_p == overlay_p and receipt.get("local_edit_state") == "PASS":
            receipt["local_edit_state"] = "ERROR"
            receipt["local_problems"] = list(
                receipt.get("local_problems") or []) + [
                f"REFUSED: output {output_p} would overwrite the overlay itself"]
        return _build_receipt(**{k: v for k, v in receipt.items() if k != "schema"})
    try:
        blocked = [str(overlay_p)]
        blocked.extend(receipt.get("protected_sources") or [])
        for candidate in blocked:
            try:
                if output_p == Path(str(candidate)).resolve():
                    plt.close(fig)
                    failed = dict(receipt)
                    failed["local_edit_state"] = "ERROR"
                    failed["local_problems"] = list(
                        receipt.get("local_problems") or []) + [
                        f"REFUSED: output {output_p} would overwrite "
                        f"a protected file ({candidate})"]
                    return _build_receipt(**{k: v for k, v in failed.items()
                                             if k != "schema"})
            except Exception:
                continue
        output_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_p), dpi=fig.dpi, facecolor="white")
        done = dict(receipt)
        done["rendered"] = str(output_p)
        return _build_receipt(**{k: v for k, v in done.items() if k != "schema"})
    finally:
        try:
            plt.close(fig)
        except Exception:
            pass
