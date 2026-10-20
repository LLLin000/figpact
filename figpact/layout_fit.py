"""Layout-aware parameter fitting: Tavotto target mm -> authorized Native edits.

The fitter only proposes edits and proves them by real rebuilds. It never
saves. Existing Inspector Native preview/commit remains the confirmation path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FONT_RE = re.compile(r"(font.*pt$|fontsize)", re.IGNORECASE)


def _norm(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("./")


def read_target(layout: Path | None, *, panel: str | None = None,
                canvas: str | None = None, target_mm: tuple[float, float] | None = None):
    """Return (width_mm, height_mm, panel_record) from a Tavotto canvas or explicit mm."""
    if target_mm is not None:
        return float(target_mm[0]), float(target_mm[1]), None
    if layout is None:
        raise ValueError("需要 --layout + --panel，或 --target-mm WxH")
    data = json.loads(Path(layout).read_text(encoding="utf-8"))
    canvases = data.get("canvases") or []
    chosen = None
    for item in canvases:
        if canvas and canvas in (item.get("id"), item.get("name")):
            chosen = item
            break
    if chosen is None and len(canvases) == 1:
        chosen = canvases[0]
    if chosen is None:
        raise ValueError("布局有多个 canvas；请用 --canvas 指定")
    hits = []
    for obj in chosen.get("objects") or []:
        if not isinstance(obj, dict) or obj.get("type") != "panel":
            continue
        values = {str(obj.get("id") or ""), _norm(obj.get("fileId")),
                  Path(_norm(obj.get("fileId"))).stem, Path(_norm(obj.get("fileId"))).name}
        if panel in values or (panel and panel in _norm(obj.get("fileId"))):
            hits.append(obj)
    if len(hits) != 1:
        raise ValueError(f"面板 {panel!r} 匹配到 {len(hits)} 个；必须唯一")
    obj = hits[0]
    return float(obj.get("w") or 0), float(obj.get("h") or 0), obj


def _font_controls(native: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for control in native.get("controls") or []:
        if not isinstance(control, dict):
            continue
        label = str(control.get("label") or "")
        if not FONT_RE.search(label):
            continue
        if not isinstance(control.get("current"), (int, float)):
            continue
        out.append(control)
    return out


def _edits_for_fonts(fonts: list[dict[str, Any]], target: float, bump: float = 0.0):
    edits = []
    for control in fonts:
        value = max(float(control["current"]), target + bump)
        value = min(value, float(control.get("max", value)))
        if value != float(control["current"]):
            edits.append({"control_id": control["control_id"], "value": round(value, 4)})
    return edits


def _score(edits: list[dict[str, Any]], controls: dict[str, dict[str, Any]], current: dict[str, float]) -> float:
    score = 0.0
    for edit in edits:
        control = controls.get(edit["control_id"], {})
        delta = abs(float(edit["value"]) - current.get(edit["control_id"], 0.0))
        weight = 1.0 if FONT_RE.search(str(control.get("label") or "")) else 2.0
        score += delta * weight
    return round(score, 6)


def _variant_layouts(fonts: list[dict[str, Any]], target: float,
                     controls: dict[str, dict[str, Any]], current: dict[str, float]):
    """Only used when font-only candidates fail: a few legend alternatives."""
    base = _edits_for_fonts(fonts, target)
    cols = controls.get(json.dumps(["legend_cols"]))
    anchor = controls.get(json.dumps(["legend_anchor_x"]))
    variants = [base]
    if cols:
        for value in (1, 2, 3):
            if value != current.get(cols["control_id"]):
                variants.append(base + [{"control_id": cols["control_id"], "value": value}])
    if anchor:
        for value in (0.5, 0.98):
            if value != current.get(anchor["control_id"]):
                variants.append(base + [{"control_id": anchor["control_id"], "value": value}])
    return variants


def fit(session, *, target_w_mm: float, min_font_pt: float = 5.0,
        max_candidates: int = 12) -> dict[str, Any]:
    """Search authorized controls with real previews; no save, no source writes."""
    snapshot = session.snapshot()
    native = snapshot.get("native") or {}
    controls = {c["control_id"]: c for c in native.get("controls") or [] if c.get("control_id")}
    current = {cid: float(c["current"]) for cid, c in controls.items()
               if isinstance(c.get("current"), (int, float))}
    fonts = _font_controls(native)
    if not fonts:
        return {"status": "INFEASIBLE", "reason": "没有授权的字号控制",
                "target_width_mm": target_w_mm, "candidates": []}
    current_min = min(float(c["current"]) for c in fonts)
    if current_min + 1e-9 >= float(min_font_pt):
        return {"status": "ALREADY_OK", "target_width_mm": target_w_mm,
                "min_font_pt": current_min, "candidates": [],
                "note": "当前字号已不低于下限；未生成改动"}
    variants = [_edits_for_fonts(fonts, min_font_pt, bump) for bump in (0.0, 0.5, 1.0)]
    seen = {tuple(sorted((e["control_id"], e["value"]) for e in v)) for v in variants}
    for extra in _variant_layouts(fonts, min_font_pt, controls, current):
        key = tuple(sorted((e["control_id"], e["value"]) for e in extra))
        if key not in seen:
            seen.add(key); variants.append(extra)
    current_min = min(float(c["current"]) for c in fonts)
    if all(not v for v in variants):
        return {"status": "ALREADY_OK", "target_width_mm": target_w_mm,
                "min_font_pt": current_min, "candidates": [],
                "note": "当前字号已不低于下限；未生成改动"}
    trials = []
    for edits in variants[:max_candidates]:
        if not edits:
            continue
        frame_revision = session.snapshot().get("frame_revision")
        try:
            out, code = session.preview({"frame_revision": frame_revision, "edits": edits})
        except Exception as error:  # engine refusal is a candidate result, not a crash
            trials.append({"edits": edits, "status": "ERROR", "message": str(error)})
            continue
        trial = out.get("receipt") or {}
        new_qa = trial.get("new_qa") or []
        font_values = [float(c["current"]) for c in fonts]
        for edit in edits:
            if any(edit["control_id"] == c["control_id"] for c in fonts):
                idx = next(i for i, c in enumerate(fonts) if c["control_id"] == edit["control_id"])
                font_values[idx] = float(edit["value"])
        effective_min = min(font_values) if font_values else current_min
        record = {
            "edits": edits,
            "http": code,
            "status": out.get("status"),
            "verification": trial.get("verification"),
            "new_qa": new_qa,
            "message": out.get("message") or trial.get("message"),
            "min_font_pt": effective_min,
            "score": _score(edits, controls, current),
            "feasible": bool(code == 200 and out.get("status") == "OK" and not new_qa
                             and effective_min + 1e-9 >= float(min_font_pt)),
        }
        trials.append(record)
        if record["feasible"]:
            break
    feasible = [t for t in trials if t.get("feasible")]
    feasible.sort(key=lambda t: (t["score"], len(t["edits"])))
    selected = feasible[0] if feasible else None
    status = "FEASIBLE" if selected else "INFEASIBLE"
    result = {"status": status, "target_width_mm": target_w_mm,
              "min_font_pt": min_font_pt, "current_min_font_pt": current_min,
              "selected": selected, "candidates": trials,
              "note": "仅真实 preview；未保存。请在 Inspector Native 面板复查并确认保存。"}
    if not selected:
        result["reason"] = "在授权字号/图例参数内没有通过真实重建的候选；需要更多版面或改图内容"
        if current_min:
            result["estimate_width_for_floor_mm"] = round(target_w_mm * float(min_font_pt) / current_min, 3)
            result["estimate_note"] = "仅当允许等比放大整图时成立；1:1 契约下不能靠放大占位提高源字号"
    return result
