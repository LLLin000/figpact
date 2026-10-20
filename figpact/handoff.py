"""figpact ↔ Tavotto handoff: target size, file identity and scale evidence.

This module never edits a Tavotto layout and never edits a figure. A manifest
records the target rectangle Tavotto must honour, the exact asset bytes, the
source hashes and the effective font sizes. ``verify`` re-measures the real
PDF page and, optionally, the real Tavotto panel geometry.

PDF reading uses ``pypdf``; it is an optional dependency for this bridge.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "figpact-tavotto-handoff/1"
MM_PER_PT = 25.4 / 72.0


class HandoffError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canvas(layout: Path, canvas: str | None) -> dict[str, Any]:
    data = json.loads(Path(layout).read_text(encoding="utf-8"))
    canvases = data.get("canvases") or []
    if canvas:
        for item in canvases:
            if canvas in (item.get("id"), item.get("name")):
                return item
        raise HandoffError("找不到指定 canvas；请用 --canvas 指定 id 或 name")
    if len(canvases) == 1:
        return canvases[0]
    raise HandoffError("布局有多个 canvas；请用 --canvas 指定 id 或 name")


def scan_layout(layout: Path, *, base: Path, canvas: str | None = None,
                font_roles: dict[str, list[dict[str, Any]]] | None = None,
                min_effective_font_pt: float | None = None) -> dict[str, Any]:
    """Build the handoff contract from the real Tavotto canvas.

    The canvas supplies the layout facts (which PDF, placed rectangle); the
    native PDF page supplies the target. No YAML, no second target spec: the
    contract is simply "place this file at its native physical size, 1:1".
    """
    selected = _canvas(layout, canvas)
    base = Path(base)
    figures = []
    for obj in selected.get("objects") or []:
        if not isinstance(obj, dict) or obj.get("type") != "panel":
            continue
        raw = str(obj.get("fileId") or "")
        if raw.startswith("runtime:") or not raw:
            continue
        asset_rel = raw.replace("\\", "/")
        if not asset_rel.lower().endswith(".pdf"):
            continue  # 位图面板不是 figpact 生成的矢量图，交给 Tavotto
        asset = _resolve(base, asset_rel)
        if not asset.is_file():
            raise HandoffError(f"布局引用的素材不存在：{asset_rel}")
        page = measure_pdf_page_mm(asset)
        width, height = page["measured_page_mm"]
        source = str(obj.get("script") or "").replace("\\", "/")
        roles = (font_roles or {}).get(Path(asset_rel).stem) or (font_roles or {}).get(str(obj.get("id")))
        entry = {
            "id": Path(asset_rel).stem,
            "asset": asset_rel,
            "sources": [source] if source else [],
            "target_width_mm": width,
            "target_height_mm": height,
            "min_effective_font_pt": min_effective_font_pt,
            "require_uniform_scale": True,
            "require_scale": 1.0,
            "font_roles": roles or [],
        }
        figures.append(entry)
    if not figures:
        raise HandoffError("指定 canvas 里没有可核验的 PDF panel")
    return build({"schema": SCHEMA, "figures": figures}, base=base)


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(base) / path


def measure_pdf_page_mm(path: Path) -> dict[str, Any]:
    """Real page box in millimetres; honours CropBox, /Rotate and /UserUnit."""
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - optional dependency
        raise HandoffError("读取 PDF 需要 pypdf：python -m pip install pypdf") from error
    try:
        reader = PdfReader(str(path))
        if not reader.pages:
            raise HandoffError(f"PDF 没有页面：{path}")
    except HandoffError:
        raise
    except Exception as error:
        raise HandoffError(f"无法读取 PDF 页面：{path}（{error}）") from error
    page = reader.pages[0]

    def box(name: str) -> list[float]:
        value = page.mediabox if name == "/MediaBox" else page.cropbox
        return [float(value.left), float(value.bottom), float(value.right), float(value.top)]

    media = box("/MediaBox")
    crop = box("/CropBox")
    left, bottom, right, top = crop
    width_pt, height_pt = right - left, top - bottom
    rotation = int(page.get("/Rotate", 0) or 0) % 360
    if rotation in (90, 270):
        width_pt, height_pt = height_pt, width_pt
    user_unit = float(page.get("/UserUnit", 1) or 1)
    scale = MM_PER_PT * user_unit
    return {
        "page_count": len(reader.pages),
        "media_mm": [round((media[2] - media[0]) * MM_PER_PT * user_unit, 6),
                     round((media[3] - media[1]) * MM_PER_PT * user_unit, 6)],
        "crop_mm": [round(width_pt * scale, 6), round(height_pt * scale, 6)],
        "rotation": rotation,
        "user_unit": user_unit,
        "box": "CropBox",
        "measured_page_mm": [round(width_pt * scale, 6), round(height_pt * scale, 6)],
    }


def _within(value: float, target: float, tolerance: float) -> bool:
    return abs(value - target) <= tolerance


def _font_roles(entry: dict[str, Any], scale: float) -> list[dict[str, Any]]:
    roles = []
    for role in entry.get("font_roles") or []:
        if not isinstance(role, dict) or not isinstance(role.get("source_pt"), (int, float)):
            raise HandoffError(f"{entry.get('id')}：font_roles 需要 role/source_pt")
        source = float(role["source_pt"])
        effective = source * scale
        roles.append({"role": role.get("role") or "font", "source_pt": source,
                      "effective_pt": round(effective, 4)})
    return roles


def verify(manifest: dict[str, Any], *, base: Path | None = None,
           layout: Path | None = None, canvas: str | None = None) -> dict[str, Any]:
    """Re-measure assets and sources; report real numbers, never a cached verdict."""
    base = Path(base or Path.cwd())
    if manifest.get("schema") != SCHEMA:
        raise HandoffError(f"manifest.schema 必须是 {SCHEMA}")
    figures = manifest.get("figures")
    if not isinstance(figures, list) or not figures:
        raise HandoffError("figures 必须是非空数组")
    findings: list[dict[str, Any]] = []
    results = []
    for entry in figures:
        fid = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(fid, str) or not fid:
            raise HandoffError("每个 figure 需要非空 id")
        asset = _resolve(base, str(entry.get("asset") or ""))
        target_w = float(entry.get("target_width_mm") or 0)
        target_h = entry.get("target_height_mm")
        target_h = float(target_h) if target_h is not None else None
        tolerance = float(entry.get("tolerance_mm", 0.05))
        if not asset.is_file():
            findings.append({"figure": fid, "code": "MISSING_ASSET", "path": str(asset)})
            results.append({"id": fid, "status": "FAIL"})
            continue
        actual_sha = _sha256(asset)
        expected_sha = entry.get("asset_sha256")
        if expected_sha and actual_sha != expected_sha:
            findings.append({"figure": fid, "code": "ASSET_CHANGED",
                             "expected": expected_sha, "actual": actual_sha})
        page = measure_pdf_page_mm(asset)
        width, height = page["measured_page_mm"]
        if target_w <= 0:
            findings.append({"figure": fid, "code": "MISSING_TARGET_WIDTH"})
        scale_x = target_w / width if width else 0.0
        scale_y = (target_h / height) if (target_h and height) else scale_x
        uniform = target_h is None or _within(scale_x, scale_y, 0.002)
        if entry.get("require_uniform_scale", True) and not uniform:
            findings.append({"figure": fid, "code": "NON_UNIFORM_SCALE",
                             "scale_x": round(scale_x, 6), "scale_y": round(scale_y, 6)})
        required = float(entry.get("require_scale", 1.0))
        if not _within(scale_x, required, 0.002) or (target_h and not _within(scale_y, required, 0.002)):
            findings.append({"figure": fid, "code": "SCALE_NOT_ONE",
                             "scale_x": round(scale_x, 6), "scale_y": round(scale_y, 6),
                             "required": required})
        page_ok = abs(width - target_w) <= tolerance and (target_h is None or abs(height - target_h) <= tolerance)
        if not page_ok:
            findings.append({"figure": fid, "code": "PAGE_SIZE_MISMATCH",
                             "target_mm": [target_w, target_h],
                             "actual_mm": [round(width, 4), round(height, 4)]})
        effective_scale = min(scale_x, scale_y) if target_h else scale_x
        roles = _font_roles(entry, effective_scale)
        floor = entry.get("min_effective_font_pt")
        if floor is not None:
            for role in roles:
                if role["effective_pt"] < float(floor):
                    findings.append({"figure": fid, "code": "FONT_BELOW_FLOOR",
                                     "role": role["role"], "effective_pt": role["effective_pt"],
                                     "floor_pt": float(floor)})
        source_hashes = entry.get("source_sha256") or {}
        if not isinstance(source_hashes, dict):
            raise HandoffError(f"{fid}：source_sha256 必须是对象")
        for source, expected in source_hashes.items():
            path = _resolve(base, source)
            if not path.is_file():
                findings.append({"figure": fid, "code": "MISSING_SOURCE", "source": source})
            elif _sha256(path) != expected:
                findings.append({"figure": fid, "code": "STALE_SOURCE", "source": source})
        results.append({"id": fid, "asset": str(entry.get("asset")), "asset_sha256": actual_sha,
                        "page": page, "scale_x": round(scale_x, 6),
                        "scale_y": round(scale_y, 6), "uniform_scale": uniform,
                        "target_mm": [target_w, target_h], "font_roles": roles})
    layout_result = None
    if layout is not None:
        layout_result = verify_layout(layout, manifest, base=base, canvas=canvas)
        findings.extend(layout_result.pop("findings"))
    status = "PASS" if not findings else "FAIL"
    return {"schema": "figpact-tavotto-handoff-report/1", "status": status,
            "findings": findings, "figures": results, "layout": layout_result}


def verify_layout(path: Path, manifest: dict[str, Any], *, base: Path,
                  canvas: str | None = None) -> dict[str, Any]:
    """Read-only panel scale check against the real Tavotto layout JSON.

    Matching is by asset basename and optionally by source script basename.
    A missing panel is reported; nothing is modified.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    canvases = data.get("canvases") or []
    selected = None
    for item in canvases:
        if canvas and canvas in (item.get("id"), item.get("name")):
            selected = item
            break
    if selected is None and len(canvases) == 1:
        selected = canvases[0]
    if selected is None:
        raise HandoffError("找不到指定 canvas；请用 --canvas 指定 id 或 name")
    panels = []
    findings = []
    by_asset = {Path(str(e.get("asset") or "")).name: e for e in manifest.get("figures") or []}

    def by_script(name: str):
        if not name:
            return None
        for entry in manifest.get("figures") or []:
            names = {Path(str(s).replace("\\", "/")).name for s in (entry.get("source_sha256") or {})}
            if name in names:
                return entry
        return None

    for obj in selected.get("objects") or []:
        if not isinstance(obj, dict) or obj.get("type") != "panel":
            continue
        file_name = Path(str(obj.get("fileId") or "").replace("\\", "/")).name
        script_name = Path(str(obj.get("script") or "").replace("\\", "/")).name
        entry = by_asset.get(file_name) or by_script(script_name)
        if entry is None:
            continue
        asset = _resolve(base, str(entry["asset"]))
        page = measure_pdf_page_mm(asset)
        width, height = page["measured_page_mm"]
        w, h = float(obj.get("w") or 0), float(obj.get("h") or 0)
        sx = w / width if width else 0.0
        sy = h / height if height else 0.0
        target = [float(entry["target_width_mm"]),
                  float(entry["target_height_mm"]) if entry.get("target_height_mm") is not None else None]
        recorded_native = [obj.get("nativeW"), obj.get("nativeH")]
        native_ok = (recorded_native[0] is None or _within(float(recorded_native[0]), width, 0.05)) and \
                    (recorded_native[1] is None or _within(float(recorded_native[1]), height, 0.05))
        uniform = _within(sx, sy, 0.002)
        one = _within(sx, 1.0, 0.002) and _within(sy, 1.0, 0.002)
        panel = {"figure": entry["id"], "panel_id": obj.get("id"), "file": obj.get("fileId"),
                 "native_mm": [round(width, 4), round(height, 4)],
                 "placed_mm": [round(w, 4), round(h, 4)],
                 "scale_x": round(sx, 6), "scale_y": round(sy, 6),
                 "uniform_scale": uniform, "scale_one": one,
                 "native_matches_pdf": native_ok}
        panels.append(panel)
        if not native_ok:
            findings.append({"figure": entry["id"], "code": "LAYOUT_NATIVE_MISMATCH",
                             "recorded_mm": recorded_native,
                             "actual_mm": [round(width, 4), round(height, 4)]})
        if entry.get("require_uniform_scale", True) and not uniform:
            findings.append({"figure": entry["id"], "code": "LAYOUT_NON_UNIFORM",
                             "panel_id": obj.get("id"), "scale_x": round(sx, 6),
                             "scale_y": round(sy, 6)})
        if entry.get("require_scale", 1.0) == 1.0 and not one:
            findings.append({"figure": entry["id"], "code": "LAYOUT_SCALED",
                             "panel_id": obj.get("id"),
                             "scale_x": round(sx, 6), "scale_y": round(sy, 6)})
        if target[1] is not None:
            if abs(w - target[0]) > 0.05 or abs(h - target[1]) > 0.05:
                findings.append({"figure": entry["id"], "code": "LAYOUT_TARGET_MISMATCH",
                                 "target_mm": target, "placed_mm": [round(w, 4), round(h, 4)]})
    if not panels:
        findings.append({"code": "LAYOUT_NO_MATCHED_PANELS", "canvas": selected.get("name")})
    return {"canvas": selected.get("name"), "canvas_id": selected.get("id"),
            "page_mm": [(selected.get("page") or {}).get("w"), (selected.get("page") or {}).get("h")],
            "panels": panels, "findings": findings}


def build(spec: dict[str, Any], *, base: Path | None = None) -> dict[str, Any]:
    """Fill a hand-authored spec with real hashes, page sizes and font results."""
    base = Path(base or Path.cwd())
    if spec.get("schema") != SCHEMA:
        raise HandoffError(f"spec.schema 必须是 {SCHEMA}")
    figures = []
    for entry in spec.get("figures") or []:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("asset"):
            raise HandoffError("每个 figure 需要 id 和 asset")
        asset = _resolve(base, str(entry["asset"]))
        if not asset.is_file():
            raise HandoffError(f"资产不存在：{asset}")
        page = measure_pdf_page_mm(asset)
        width, height = page["measured_page_mm"]
        target_w = float(entry.get("target_width_mm") or 0)
        target_h = entry.get("target_height_mm")
        target_h = float(target_h) if target_h is not None else None
        sx = target_w / width if width else 0.0
        sy = target_h / height if (target_h and height) else sx
        roles = _font_roles(entry, min(sx, sy) if target_h else sx)
        sources = {}
        for source in entry.get("sources") or []:
            path = _resolve(base, str(source))
            if not path.is_file():
                raise HandoffError(f"来源不存在：{path}")
            sources[str(source)] = _sha256(path)
        figures.append({
            "id": entry["id"], "asset": entry["asset"],
            "asset_sha256": _sha256(asset), "page": page,
            "target_width_mm": target_w, "target_height_mm": target_h,
            "min_effective_font_pt": entry.get("min_effective_font_pt"),
            "require_uniform_scale": entry.get("require_uniform_scale", True),
            "require_scale": entry.get("require_scale", 1.0),
            "tolerance_mm": entry.get("tolerance_mm", 0.05),
            "source_sha256": sources, "font_roles": roles,
            "figpact_receipt": {
                "kind": "asset-integrity",
                "asset_sha256": _sha256(asset),
                "page_mm": page["measured_page_mm"],
                "status": "MEASURED",
                "note": "只证明文件与页面尺寸；不替代图形科学/Strict PASS 验证",
            },
        })
    out = {"schema": SCHEMA, "created_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(), "figures": figures}
    return out


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
