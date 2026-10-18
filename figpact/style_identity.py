"""Stable style identity for verified overlays (G16).

Only three editable targets exist; everything else is not inventoried and can
never resolve:

  role              property    artist
  axis.title        fontsize    ax.xaxis.label / ax.yaxis.label (nonempty Text)
  axis.tick         fontsize    major tick label group, per x/y axis
  curve.linewidth   linewidth   connected data Line2D (errorbar data line ok)

Not editable (never emitted, resolve rejects): LineCollection/caps, scatter,
bars/rectangles, legend bodies/handles/texts, titles, annotations, grids,
spines, minor ticks. No per-gallery special cases: errorbar caps are excluded
generically via ErrorbarContainer membership, legend handles via legend
handle identity, marker-only lines via linestyle.

Identity rules:

- Axes identity = gid (only when nonempty and unique across the figure) PLUS
  a structural fingerprint (SubplotSpec gridspec geometry/rowspan/colspan —
  or the add_axes original rect when there is no spec — plus projection,
  exact data view, label/title text, tick counts, connected-curve data
  digests). Float bboxes (drawn or original=True, both rewritten by
  constrained_layout) never enter authority; no rounding or tolerance.
  Ordinal axes index is a display hint only, never authority.
- Curve identity = exact data digest (raw bytes + shape + dtype + mask) plus
  exact label, gid, linestyle, marker, drawstyle and transform shape.
  Enumeration order never distinguishes curves.
- Tick group identity = axes identity + axis + per-member
  (side, exact text, tick location). A side is included only when its
  tick label Text is visible after draw and its text is nonempty; hidden
  shared-axis labels never become targets.
- The edited style property (fontsize/linewidth) is NEVER part of selector
  or fingerprint, so a descriptor still resolves after it is applied.
- Duplicate identity (shared gid, shared axes key, shared curve base id)
  yields descriptors with unique=False/eligible=False; resolve rejects them
  as AMBIGUOUS. Missing targets are simply absent -> UNKNOWN_ID.

Error model: every failure is ValueError with a machine-readable CODE prefix:
INVALID_SCOPE, INVALID_FIGURE, INVALID_DESCRIPTOR, UNKNOWN_FIELD,
UNSUPPORTED_ROLE, UNSUPPORTED_PROPERTY, SCOPE_MISMATCH, UNKNOWN_ID, DRIFT,
AMBIGUOUS, MISSING_TARGET.

No setters live here and none are returned: resolve() returns bare Artists.
The overlay must map (role, property) to a hardcoded setter internally and
MUST NEVER take a method name from a descriptor.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

__all__ = ["inventory", "resolve", "match_identity", "ALLOWED_TARGETS",
           "ROLE_PROPERTY"]

#: The only editable (role, property) pairs. Closed set.
ALLOWED_TARGETS = (("axis.title", "fontsize"),
                   ("axis.tick", "fontsize"),
                   ("curve.linewidth", "linewidth"))

ROLE_PROPERTY = {"axis.title": "fontsize",
                 "axis.tick": "fontsize",
                 "curve.linewidth": "linewidth"}

_ROLES = frozenset(ROLE_PROPERTY)
_REQUIRED_FIELDS = frozenset(("id", "role", "property", "scope",
                              "selector", "fingerprint"))
_ALLOWED_FIELDS = frozenset(("id", "role", "property", "scope", "selector",
                             "fingerprint", "current", "unique", "eligible",
                             "reason", "display"))


# ------------------------------------------------------------------ primitives

def _num(value: Any) -> float | None:
    """Finite float or None (non-finite/ unparseable never enters identity)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return ""


def _gid_of(artist: Any) -> str | None:
    try:
        gid = artist.get_gid()
    except Exception:
        return None
    if isinstance(gid, str) and gid != "":
        return gid
    return None


def _safe_get(obj: Any, name: str) -> str:
    try:
        fn = getattr(obj, name)
    except Exception:
        return ""
    try:
        return _text(fn())
    except Exception:
        return ""


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _hash_canonical(obj: Any, length: int = 12) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()[:length]


def _digest_array(values: Any) -> dict:
    """Exact content digest of one data vector (raw bytes, shape, dtype)."""
    raw = np.asanyarray(values)
    if raw.dtype.hasobject:
        payload = json.dumps(raw.tolist(), ensure_ascii=False,
                             default=str).encode("utf-8")
        record: dict[str, Any] = {"shape": list(raw.shape),
                                  "dtype": "object",
                                  "digest": hashlib.sha256(payload).hexdigest()}
    else:
        cont = np.ascontiguousarray(raw)
        record = {"shape": list(raw.shape), "dtype": str(raw.dtype),
                  "digest": hashlib.sha256(cont.tobytes()).hexdigest()}
    if np.ma.isMaskedArray(raw):
        mask = np.ma.getmaskarray(raw)
        record["mask_digest"] = hashlib.sha256(
            np.ascontiguousarray(mask).tobytes()).hexdigest()
    return record


def _data_digest(xdata: Any, ydata: Any) -> str:
    return _hash_canonical([_digest_array(xdata), _digest_array(ydata)],
                           length=16)


def _line_style_token(line: Any) -> str:
    try:
        return str(line.get_linestyle())
    except Exception:
        return "None"


def _marker_token(line: Any) -> str:
    try:
        return str(line.get_marker())
    except Exception:
        return ""


def _is_connected(line: Any) -> bool:
    """A data curve: visible Line2D with a drawn linestyle and >= 2 points."""
    try:
        if not bool(line.get_visible()):
            return False
    except Exception:
        return False
    if _line_style_token(line).strip().lower() in ("none", "", " "):
        return False
    try:
        xs = np.asanyarray(line.get_xdata()).ravel()
        ys = np.asanyarray(line.get_ydata()).ravel()
    except Exception:
        return False
    return bool(min(len(xs), len(ys)) >= 2)


# ------------------------------------------------------------- figure census

def _legend_handle_ids(fig: Any) -> set[int]:
    out: set[int] = set()
    legends: list[Any] = list(getattr(fig, "legends", None) or [])
    for ax in (getattr(fig, "axes", None) or []):
        try:
            leg = ax.get_legend()
        except Exception:
            leg = None
        if leg is not None:
            legends.append(leg)
    for leg in legends:
        try:
            handles = list(getattr(leg, "legend_handles", None) or [])
        except Exception:
            handles = []
        for handle in handles:
            out.add(id(handle))
    return out


def _cap_ids(ax: Any) -> set[int]:
    """Line2D ids that are errorbar caps (generic container membership)."""
    out: set[int] = set()
    try:
        from matplotlib.container import ErrorbarContainer
    except Exception:
        return out
    for container in (getattr(ax, "containers", None) or []):
        if not isinstance(container, ErrorbarContainer):
            continue
        caplines: Any = None
        try:
            parts = list(container)
            if len(parts) == 3:
                caplines = parts[1]
            else:
                caplines = container.lines[1]
        except Exception:
            caplines = None
        if caplines is None:
            continue
        try:
            members = list(caplines)
        except TypeError:
            members = [caplines]
        for member in members:
            try:
                import matplotlib.lines as _lines
                if isinstance(member, _lines.Line2D):
                    out.add(id(member))
            except Exception:
                continue
    return out


def _candidate_lines(ax: Any, excluded: set[int]) -> list[Any]:
    """Connected data lines on ax.lines, minus caps/handles/marker-only."""
    import matplotlib.lines as _lines
    out = []
    for line in (getattr(ax, "lines", None) or []):
        if not isinstance(line, _lines.Line2D):
            continue
        if id(line) in excluded:
            continue
        if not _is_connected(line):
            continue
        out.append(line)
    # Errorbar data lines already live in ax.lines; pick up any that do not.
    for container in (getattr(ax, "containers", None) or []):
        try:
            data_line = container.lines[0]
        except Exception:
            continue
        if not isinstance(data_line, _lines.Line2D):
            continue
        if id(data_line) in excluded or any(data_line is ln for ln in out):
            continue
        if _is_connected(data_line):
            out.append(data_line)
    return out


def _structural_slot(ax: Any) -> dict:
    """Layout-stable position authority: spec geometry, never float bboxes.

    With a SubplotSpec: GridSpec geometry + rowspan/colspan + spacing —
    plain ints/floats-or-None, untouched by constrained_layout iteration.
    add_axes (no spec): original=True rect (no layout engine rewrites it).
    """
    try:
        spec = ax.get_subplotspec()
    except Exception:
        spec = None
    if spec is not None:
        try:
            grid = spec.get_gridspec()
        except Exception:
            grid = None
        try:
            nrows, ncols = grid.get_geometry() if grid is not None else (None, None)
        except Exception:
            nrows = ncols = None
        def _span(values, name):
            try:
                return [int(values.start), int(values.stop)]
            except Exception:
                return None
        def _opt_float(name):
            try:
                value = getattr(grid, name) if grid is not None else None
            except Exception:
                return None
            return None if value is None else _num(value)
        def _ratios(name):
            try:
                values = getattr(grid, 'get_' + name)() if grid is not None else None
            except Exception:
                return None
            if values is None:
                return None
            try:
                return [_num(v) for v in values]
            except Exception:
                return None
        return {"kind": "subplot_spec",
                "geometry": [nrows, ncols],
                "rowspan": _span(getattr(spec, 'rowspan', None), 'rowspan'),
                "colspan": _span(getattr(spec, 'colspan', None), 'colspan'),
                "wspace": _opt_float('wspace'), "hspace": _opt_float('hspace'),
                "left": _opt_float('left'), "right": _opt_float('right'),
                "top": _opt_float('top'), "bottom": _opt_float('bottom'),
                "width_ratios": _ratios('width_ratios'),
                "height_ratios": _ratios('height_ratios')}
    try:
        return {"kind": "rect",
                "rect": [_num(v) for v in ax.get_position(original=True).bounds]}
    except Exception:
        return {"kind": "rect", "rect": [None, None, None, None]}


def _axes_fingerprint(ax: Any, candidates: list[Any]) -> dict:
    # Authority is layout-stable structure + exact data/label semantics.
    # Float bboxes (current or original=True) are rewritten by
    # constrained_layout iteration, so they never enter authority.
    try:
        view = {"xlim": [_num(v) for v in ax.get_xlim()],
                "ylim": [_num(v) for v in ax.get_ylim()],
                "xscale": str(ax.get_xscale()), "yscale": str(ax.get_yscale()),
                "xinv": bool(ax.xaxis_inverted()),
                "yinv": bool(ax.yaxis_inverted())}
    except Exception:
        view = {"xlim": [None, None], "ylim": [None, None],
                "xscale": "?", "yscale": "?", "xinv": False, "yinv": False}
    try:
        n_major_x = len(ax.xaxis.get_major_ticks())
        n_major_y = len(ax.yaxis.get_major_ticks())
    except Exception:
        n_major_x = n_major_y = -1
    curve_keys = []
    for line in candidates:
        try:
            digest = _data_digest(line.get_xdata(), line.get_ydata())
        except Exception:
            digest = "?"
        curve_keys.append(f"{digest}:{_safe_get(line, 'get_label')}")
    try:
        projection = str(ax.name)
    except Exception:
        projection = "?"
    return {"slot": _structural_slot(ax), "projection": projection,
            "view": view,
            "xlabel": _safe_get(ax, "get_xlabel"),
            "ylabel": _safe_get(ax, "get_ylabel"),
            "title": _safe_get(ax, "get_title"),
            "counts": {"lines": len(getattr(ax, "lines", None) or []),
                       "containers": len(getattr(ax, "containers", None) or []),
                       "major_xticks": n_major_x, "major_yticks": n_major_y},
            "curves": sorted(curve_keys)}


def _axes_infos(fig: Any) -> list[dict]:
    axes = list(getattr(fig, "axes", None) or [])
    handle_ids = _legend_handle_ids(fig)
    infos = []
    for index, ax in enumerate(axes):
        excluded = set(handle_ids) | _cap_ids(ax)
        candidates = _candidate_lines(ax, excluded)
        infos.append({"index": index, "ax": ax, "gid": _gid_of(ax),
                      "candidates": candidates,
                      "fp": _axes_fingerprint(ax, candidates)})
    gid_counts: dict[str, int] = {}
    for info in infos:
        if info["gid"] is not None:
            gid_counts[info["gid"]] = gid_counts.get(info["gid"], 0) + 1
    for info in infos:
        struct = _hash_canonical(info["fp"])
        if info["gid"] is not None and gid_counts[info["gid"]] == 1:
            info["key"] = f"gid={info['gid']}+s{struct[:8]}"
        else:
            info["key"] = f"s{struct}"
        info["gid_dup"] = (info["gid"] is not None
                           and gid_counts.get(info["gid"], 0) > 1)
    key_counts: dict[str, int] = {}
    for info in infos:
        key_counts[info["key"]] = key_counts.get(info["key"], 0) + 1
    for info in infos:
        info["unique"] = (not info["gid_dup"]
                          and key_counts[info["key"]] == 1)
    return infos


# ------------------------------------------------------------------ builders

def _claim_id(used: set[str], base: str) -> tuple[str, bool]:
    """Unique id within one inventory; suffixed ids are always ambiguous."""
    if base not in used:
        used.add(base)
        return base, True
    suffix = 2
    while f"{base}#{suffix}" in used:
        suffix += 1
    claimed = f"{base}#{suffix}"
    used.add(claimed)
    return claimed, False


def _display(axes_info: dict, **extra: Any) -> dict:
    hint: dict[str, Any] = {"axes_index": axes_info["index"],
                            "axes_key": axes_info["key"]}
    hint.update(extra)
    return hint


def _build(fig: Any, scope: str) -> tuple[list[dict], dict[str, list[Any]]]:
    """Fresh descriptors plus live artists per id (single inventory pass)."""
    try:
        fig.canvas.draw()
    except Exception as exc:
        raise ValueError(f"INVALID_FIGURE: cannot draw figure for stable "
                         f"tick identity ({exc})") from exc
    infos = _axes_infos(fig)
    used: set[str] = set()
    descs: list[dict] = []
    artists: dict[str, list[Any]] = {}

    curve_gid_counts: dict[str, int] = {}
    for info in infos:
        for line in info["candidates"]:
            gid = _gid_of(line)
            if gid is not None:
                curve_gid_counts[gid] = curve_gid_counts.get(gid, 0) + 1
    label_gid_counts: dict[str, int] = {}
    for info in infos:
        for axis_name in ("x", "y"):
            label = (info["ax"].xaxis.label if axis_name == "x"
                     else info["ax"].yaxis.label)
            gid = _gid_of(label)
            if gid is not None:
                label_gid_counts[gid] = label_gid_counts.get(gid, 0) + 1

    def axes_ok(info: dict) -> tuple[bool, str]:
        if not info["unique"]:
            if info["gid_dup"]:
                return False, "DUPLICATE_AXES_GID"
            return False, "AMBIGUOUS_AXES"
        return True, ""

    for info in infos:
        ax, key = info["ax"], info["key"]
        ok, reason = axes_ok(info)
        for axis_name in ("x", "y"):
            label = (ax.xaxis.label if axis_name == "x" else ax.yaxis.label)
            text = _safe_get(label, "get_text")
            if text == "":
                continue
            gid = _gid_of(label)
            gid_dup = gid is not None and label_gid_counts.get(gid, 0) > 1
            unique = bool(ok and not gid_dup)
            eligible = unique
            why = "" if eligible else (reason if not ok else "DUPLICATE_GID")
            base = (f"{scope}.ax[{key}]."
                    f"{'xlabel' if axis_name == 'x' else 'ylabel'}.fontsize")
            claimed, first = _claim_id(used, base)
            if not first:
                unique, eligible, why = False, False, "AMBIGUOUS_AXES"
            try:
                current: dict[str, Any] = {"fontsize": float(label.get_fontsize())}
                if not math.isfinite(current["fontsize"]):
                    raise ValueError("nonfinite")
            except Exception:
                current = {"fontsize": None}
                unique, eligible, why = False, False, "NONFINITE_CURRENT"
            selector = {"kind": "axis_label", "axes": key,
                        "axis": axis_name, "gid": gid, "text": text}
            fingerprint = {"axes": info["fp"], "text": text, "gid": gid}
            descs.append({"id": claimed, "role": "axis.title",
                          "property": "fontsize", "scope": scope,
                          "selector": selector, "fingerprint": fingerprint,
                          "current": current, "unique": unique,
                          "eligible": eligible, "reason": why,
                          "display": _display(info, axis=axis_name)})
            artists[claimed] = [label]

        for axis_name in ("x", "y"):
            try:
                ticks = (ax.xaxis.get_major_ticks() if axis_name == "x"
                         else ax.yaxis.get_major_ticks())
            except Exception:
                continue
            members: list[tuple[int, str, Any]] = []
            for tick_index, tick in enumerate(ticks):
                for side in ("label1", "label2"):
                    lbl = getattr(tick, side, None)
                    if lbl is None:
                        continue
                    try:
                        if not bool(lbl.get_visible()):
                            continue
                    except Exception:
                        continue
                    if _safe_get(lbl, "get_text") == "":
                        continue
                    members.append((tick_index, side, lbl))
            if not members:
                continue
            member_recs = []
            sizes = []
            for tick_index, side, lbl in members:
                try:
                    loc = _num(ticks[tick_index].get_loc())
                except Exception:
                    loc = None
                member_recs.append({"tick": tick_index, "side": side,
                                    "text": _safe_get(lbl, "get_text"),
                                    "loc": loc})
                try:
                    size = float(lbl.get_fontsize())
                    sizes.append(size if math.isfinite(size) else None)
                except Exception:
                    sizes.append(None)
            unique = bool(ok)
            eligible = unique
            why = "" if eligible else reason
            base = f"{scope}.ax[{key}].tick.{axis_name}.fontsize"
            claimed, first = _claim_id(used, base)
            if not first:
                unique, eligible, why = False, False, "AMBIGUOUS_AXES"
            if any(size is None for size in sizes):
                unique, eligible, why = False, False, "NONFINITE_CURRENT"
            uniform = sizes[0] if sizes and all(
                size == sizes[0] for size in sizes) else None
            current_tick = {"fontsizes": list(sizes), "uniform": uniform}
            selector = {"kind": "tick_labels", "axes": key, "axis": axis_name}
            fingerprint = {"axes": info["fp"], "axis": axis_name,
                           "count": len(members), "members": member_recs}
            descs.append({"id": claimed, "role": "axis.tick",
                          "property": "fontsize", "scope": scope,
                          "selector": selector, "fingerprint": fingerprint,
                          "current": current_tick, "unique": unique,
                          "eligible": eligible, "reason": why,
                          "display": _display(info, axis=axis_name,
                                              count=len(members))})
            artists[claimed] = [lbl for _, _, lbl in members]

        seen_bases: dict[str, int] = {}
        for line in info["candidates"]:
            try:
                digest = _data_digest(line.get_xdata(), line.get_ydata())
            except Exception:
                continue
            try:
                n_points = int(min(len(np.asanyarray(line.get_xdata()).ravel()),
                                   len(np.asanyarray(line.get_ydata()).ravel())))
            except Exception:
                continue
            label_text = _safe_get(line, "get_label")
            gid = _gid_of(line)
            try:
                drawstyle = str(line.get_drawstyle())
            except Exception:
                drawstyle = "?"
            try:
                transform = line.get_transform()
                transform_name = type(transform).__name__
                is_data = bool(transform is ax.transData)
            except Exception:
                transform_name, is_data = "?", False
            line_fp = {"linestyle": _line_style_token(line),
                       "marker": _marker_token(line),
                       "drawstyle": drawstyle,
                       "transform": transform_name,
                       "is_ax_transData": is_data}
            base = (f"{scope}.ax[{key}].curve.d{digest[:12]}."
                    f"l{_hash_canonical(label_text, 8)}")
            if gid is not None:
                base += f".g{gid}"
            base += ".linewidth"
            seen_bases[base] = seen_bases.get(base, 0) + 1
            gid_dup = gid is not None and curve_gid_counts.get(gid, 0) > 1
            unique = bool(ok and not gid_dup and seen_bases[base] == 1)
            eligible = unique
            if not ok:
                why = reason
            elif gid_dup:
                why = "DUPLICATE_GID"
            elif seen_bases[base] > 1:
                why = "AMBIGUOUS_CURVE"
            else:
                why = ""
            claimed, first = _claim_id(used, base)
            if not first:
                unique, eligible, why = False, False, "AMBIGUOUS_CURVE"
            try:
                width = float(line.get_linewidth())
                if not math.isfinite(width):
                    raise ValueError("nonfinite")
                current_line: dict[str, Any] = {"linewidth": width}
            except Exception:
                current_line = {"linewidth": None}
                unique, eligible, why = False, False, "NONFINITE_CURRENT"
            selector = {"kind": "curve", "axes": key, "data": digest,
                        "label": label_text, "gid": gid, "line": line_fp}
            fingerprint = {"axes": info["fp"], "data": digest,
                           "label": label_text, "gid": gid, "n": n_points,
                           "line": line_fp}
            descs.append({"id": claimed, "role": "curve.linewidth",
                          "property": "linewidth", "scope": scope,
                          "selector": selector, "fingerprint": fingerprint,
                          "current": current_line, "unique": unique,
                          "eligible": eligible, "reason": why,
                          "display": _display(info, n_points=n_points,
                                              label=label_text)})
            artists[claimed] = [line]

    # Late duplicate pass: identical curve bases share one base id; every
    # claimant (including the unsuffixed first) is demoted to ineligible.
    base_of: dict[str, list[str]] = {}
    for desc in descs:
        if desc["role"] != "curve.linewidth":
            continue
        head, sep, tail = desc["id"].rpartition("#")
        base = head if sep and tail.isdigit() else desc["id"]
        base_of.setdefault(base, []).append(desc["id"])
    for base, ids in base_of.items():
        if len(ids) > 1:
            for claimed in ids:
                for desc in descs:
                    if desc["id"] == claimed:
                        desc["unique"] = False
                        desc["eligible"] = False
                        desc["reason"] = "AMBIGUOUS_CURVE"

    descs.sort(key=lambda desc: desc["id"])
    return descs, artists


# ------------------------------------------------------------------ public API

def inventory(fig: Any, scope: str = "main") -> list[dict]:
    """All uniquely identifiable style targets on an existing Figure.

    Returns JSON-native, finite, deterministically id-sorted descriptors.
    Missing targets are absent; ambiguous ones are present but ineligible.
    Draws the figure first so tick visibility/texts are stable; a draw
    failure is fail-closed (INVALID_FIGURE), never a silent eligible set.
    """
    if not isinstance(scope, str) or scope == "":
        raise ValueError(f"INVALID_SCOPE: scope must be a nonempty string, "
                         f"got {scope!r}")
    if not hasattr(fig, "axes"):
        raise ValueError("INVALID_FIGURE: figure has no axes")
    descs, _ = _build(fig, scope)
    return descs


def _validate_descriptor(descriptor: Any) -> dict:
    if not isinstance(descriptor, dict):
        raise ValueError("INVALID_DESCRIPTOR: descriptor must be a dict, "
                         f"got {type(descriptor).__name__}")
    unknown = set(descriptor) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"UNKNOWN_FIELD: unexpected descriptor fields "
                         f"{sorted(unknown)}")
    missing = _REQUIRED_FIELDS - set(descriptor)
    if missing:
        raise ValueError(f"INVALID_DESCRIPTOR: missing fields "
                         f"{sorted(missing)}")
    role = descriptor.get("role")
    if role not in _ROLES:
        raise ValueError(f"UNSUPPORTED_ROLE: role {role!r} not in "
                         f"{sorted(_ROLES)}")
    prop = descriptor.get("property")
    if prop != ROLE_PROPERTY[role]:
        raise ValueError(f"UNSUPPORTED_PROPERTY: property {prop!r} is not "
                         f"editable for role {role!r}; only "
                         f"{ROLE_PROPERTY[role]!r} is")
    if not isinstance(descriptor.get("selector"), dict):
        raise ValueError("INVALID_DESCRIPTOR: selector must be a dict")
    if not isinstance(descriptor.get("fingerprint"), dict):
        raise ValueError("INVALID_DESCRIPTOR: fingerprint must be a dict")
    if not isinstance(descriptor.get("scope"), str):
        raise ValueError("INVALID_DESCRIPTOR: scope must be a string")
    if not isinstance(descriptor.get("id"), str) or not descriptor["id"]:
        raise ValueError("INVALID_DESCRIPTOR: id must be a nonempty string")
    return descriptor


def match_identity(descriptor: dict) -> dict:
    """Canonical identity used for matching (style values excluded).

    Small helper for the overlay/tests: the exact subset resolve() compares
    against the fresh inventory descriptor.
    """
    _validate_descriptor(descriptor)
    return {"role": descriptor["role"], "property": descriptor["property"],
            "scope": descriptor["scope"],
            "selector": json.loads(_canon(descriptor["selector"])),
            "fingerprint": json.loads(_canon(descriptor["fingerprint"]))}


def resolve(fig: Any, descriptor: dict, scope: str = "main") -> list[Any]:
    """Resolve one descriptor to live Artists on an existing Figure.

    Rebuilds the authoritative fresh inventory from ``fig``, requires exact
    selector+fingerprint equality (style values ignored), then requires the
    fresh target to be unique and eligible. Tick groups return their member
    Text list; label/curve targets return a singleton list.
    """
    _validate_descriptor(descriptor)
    if descriptor.get("scope") != scope:
        raise ValueError(f"SCOPE_MISMATCH: descriptor scope "
                         f"{descriptor.get('scope')!r} != resolve scope "
                         f"{scope!r}")
    if not hasattr(fig, "axes"):
        raise ValueError("INVALID_FIGURE: figure has no axes")
    descs, artists = _build(fig, scope)
    by_id = {desc["id"]: desc for desc in descs}
    target_id = descriptor["id"]
    fresh = by_id.get(target_id)
    if fresh is None:
        raise ValueError(f"UNKNOWN_ID: no target {target_id!r} in scope "
                         f"{scope!r}; missing targets are rejected, never "
                         f"guessed")
    if (_canon(descriptor["selector"]) != _canon(fresh["selector"])
            or _canon(descriptor["fingerprint"])
            != _canon(fresh["fingerprint"])):
        raise ValueError(f"DRIFT: target {target_id!r} structural identity "
                         f"changed (data/label/geometry/count/text); refusing "
                         f"nearest match")
    if not fresh.get("unique") or not fresh.get("eligible"):
        raise ValueError(f"AMBIGUOUS: target {target_id!r} is not uniquely "
                         f"identifiable ({fresh.get('reason') or 'ambiguous'})")
    live = artists.get(target_id) or []
    if not live:
        raise ValueError(f"MISSING_TARGET: target {target_id!r} has no live "
                         f"artist on this figure")
    expected = fresh["role"]
    if expected == "axis.tick":
        count = fresh["fingerprint"].get("count")
        if count is not None and len(live) != int(count):
            raise ValueError(f"DRIFT: tick group {target_id!r} member count "
                             f"changed ({len(live)} != {count})")
    elif len(live) != 1:
        raise ValueError(f"AMBIGUOUS: target {target_id!r} resolves to "
                         f"{len(live)} artists, expected exactly one")
    return list(live)
