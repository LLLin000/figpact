#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G23 tick-clip trial: thin orchestration over the G21 runners + G23-only increment.

The complete native/save/restart/strict proof lives in the G21 runners
(`tools/g21/nmr_publication.py`, `tools/g21/ftir_publication.py`) and is
reused by calling them — never reimplemented here. This tool only:

1. runs the G21 NMR runner (`--save`: full native + strict + save/restart/
   continued + overlay proof) and the G21 FTIR controlled proof against
   private G23 clones (paths from flags, never the repo);
2. appends the G23-only increment: candidate tick geometry across actual
   render DPIs (72/120/300/600, same physical mm canvas) plus real
   PDF-page/PNG-pixel geometry from the strict artifacts.

No product changes, no raw-data commits, no exemptions, no 5pt lowering.

Usage:
  PYTHONPATH=<repo> python tools/g23/publication_trial.py \
    --nmr-script <priv>/08\\ NMR.py --nmr-config <priv>/nmr.yaml \
    --ftir-stage <priv-ftir-dir> --out <fresh-evidence-dir>
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

G21_NMR = ROOT / "tools" / "g21" / "nmr_publication.py"
G21_FTIR = ROOT / "tools" / "g21" / "ftir_publication.py"
DPI_SWEEP = (72, 120, 300, 600)


def _load_runner(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pdf_pages_and_spans(pdf: Path) -> dict:
    import fitz

    sizes: list[float] = []
    with fitz.open(pdf) as doc:
        pages = [[round(float(v), 2) for v in page.rect] for page in doc]
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sizes.append(round(float(span["size"]), 2))
    return {"pages": pages, "font_sizes_pt": sorted(set(sizes)),
            "min_pt": min(sizes) if sizes else None, "n_spans": len(sizes)}


def _pdf_tick_bboxes(pdf: Path) -> dict:
    """Word-level text bboxes per PDF page (file geometry, same kind).

    Checks the final bytes carry all words inside the page box — the
    file-level analogue of the renderer tick proof, not a figure re-measure.
    """
    import fitz

    out: dict = {"pages": []}
    with fitz.open(pdf) as doc:
        for page in doc:
            rect = [round(float(v), 2) for v in page.rect]
            words = page.get_text("words")
            inside_flags = [bool(w[0] >= page.rect.x0 and w[1] >= page.rect.y0
                                 and w[2] <= page.rect.x1 and w[3] <= page.rect.y1)
                            for w in words]
            out["pages"].append({"rect": rect, "n_words": len(words),
                                 "n_outside": sum(1 for f in inside_flags if not f)})
    out["all_inside"] = all(p["n_outside"] == 0 for p in out["pages"])
    return out


def _png_pixels(png: Path):
    try:
        from PIL import Image
    except Exception:
        return None
    with Image.open(png) as im:
        return list(im.size)


def _dpi_sweep(nmr_script: Path, nmr_config: Path, candidate_yaml: Path | None) -> dict:
    """G23-only: candidate TICK-CLIP geometry at actual render DPIs.

    Same physical canvas (mm); only the render DPI changes via fig.set_dpi.
    Scope is tick-clip legality ONLY: any TICK_CLIP or UNMEASURED_GEOMETRY at
    any DPI refuses the trial. Other rules (e.g. TEXT_ON_DATA, which is
    resolution-sensitive by construction) are listed per DPI for transparency
    but never counted as all-QA clean — the strict verdict comes from the
    native 120-DPI build and the 600-DPI export PDFs, not from this sweep.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt

    spec = importlib.util.spec_from_file_location("nmr_g23_dpi", str(nmr_script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from figpact import qa as qa_mod

    cfg_path = candidate_yaml if candidate_yaml and candidate_yaml.is_file() else nmr_config
    import yaml

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    # Full config through the module's own legacy loader path.
    base = mod.load_config_nmr(nmr_config)
    merged = dict(base)
    merged.update(cfg)
    out: dict = {"config": "candidate" if candidate_yaml and candidate_yaml.is_file() else "base",
                 "scope": "TICK_CLIP/UNMEASURED_GEOMETRY only; other rules listed, not gated",
                 "dpis": {}}
    for dpi in DPI_SWEEP:
        mod._apply_config(copy.deepcopy(merged))
        fig, _ = mod._build(mod.load_science(), "main")
        try:
            fig.set_dpi(float(dpi))
            measured = qa_mod.measure(fig)
            clips = [{"key": r["key"], "value": r.get("value")}
                     for r in measured["records"] if r["rule"] == "TICK_CLIP"]
            unm = [{"key": r["key"]} for r in measured["records"]
                   if r["rule"] == "UNMEASURED_GEOMETRY"]
            # Non-tick records listed with rule/value only (text redacted);
            # informational, never an all-QA verdict.
            other = [{"rule": r["rule"], "value": r.get("value"), "unit": r.get("unit"),
                      "threshold": r.get("threshold"), "worse": r.get("worse"),
                      "severity": r.get("severity")}
                     for r in measured["records"]
                     if r["rule"] not in ("TICK_CLIP", "UNMEASURED_GEOMETRY")]
            geo = measured.get("tick_geometry") or []
            out["dpis"][str(dpi)] = {
                "n_records": len(measured["records"]),
                "tick_clip": clips, "unmeasured": unm,
                "other_records": other,
                "n_tick_geometry": len(geo),
                "min_clearance_mm": (min(float(g["clearance_mm"]) for g in geo)
                                     if geo else None),
                "env_dpi": (measured.get("env") or {}).get("dpi"),
            }
        finally:
            _plt.close(fig)
    mod._apply_config(mod.load_config_nmr(nmr_config))
    out["refused"] = any(v["tick_clip"] or v["unmeasured"] for v in out["dpis"].values())
    out["note"] = ("72dpi carries resolution-sensitive TEXT_ON_DATA records; "
                   "tick-clip legality holds at all DPIs, strict PASS is the "
                   "native 120-DPI build + 600-DPI export proof, not this sweep")
    return out


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()
                if k not in ("script", "config", "output_dir", "output-dir")}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, str):
        for priv in ("g23-pub", "g22-stage", "核磁原始数据", "2084_"):
            if priv in obj:
                return "<private:" + priv.strip("_") + ">"
        return obj
    return obj


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nmr-script", required=True)
    ap.add_argument("--nmr-config", required=True)
    ap.add_argument("--ftir-stage", required=True)
    ap.add_argument("--out", required=True, help="fresh private dir, never the repo")
    args = ap.parse_args(argv)
    outdir = Path(args.out)
    if outdir.exists():
        ap.error("output dir must be fresh (never overwrite evidence)")
    outdir.mkdir(parents=True)
    nmr_script = Path(args.nmr_script).resolve()
    nmr_config = Path(args.nmr_config).resolve()
    ftir_stage = Path(args.ftir_stage).resolve()

    # 1. G21 NMR full proof (native + strict + save/restart/continued/overlay).
    nmr_out = outdir / "g21-nmr"
    nmr_runner = _load_runner(G21_NMR, "g21_nmr_g23")
    nmr_rc = nmr_runner.main(["--script", str(nmr_script), "--config", str(nmr_config),
                              "--output-dir", str(nmr_out), "--save"])
    # 2. G21 FTIR controlled proof (native try + candidate strict probe).
    ftir_out = outdir / "g21-ftir"
    ftir_runner = _load_runner(G21_FTIR, "g21_ftir_g23")
    ftir_rc = ftir_runner.main(["--stage", str(ftir_stage), "--out", str(ftir_out)])
    ftir_evidence = json.loads((ftir_out / "ftir_publication_evidence.json")
                               .read_text(encoding="utf-8"))
    ftir_strict = (ftir_evidence.get("strict_probe") or {}).get("returncode")

    # 3. G23-only increment: DPI sweep + real file geometry of the FINAL
    # bytes (installed strict set + strict-overlay PDF), not just the first
    # strict-probe candidate.
    sweep = _dpi_sweep(nmr_script, nmr_config, nmr_out / "candidate.yaml")
    file_geo: dict = {}
    final_pdfs = {
        "strict_probe": nmr_out / "strict_probe" / "Fig2_NMR_pure_stacked.pdf",
        "installed": nmr_out / "installed" / "Fig2_NMR_pure_stacked.pdf",
        "strict_overlay": nmr_out / "strict_overlay" / "Fig2_NMR_overlay_strict.pdf",
    }
    for label, pdf in final_pdfs.items():
        if pdf.is_file():
            file_geo[label] = {**_pdf_pages_and_spans(pdf),
                               "tick_bboxes": _pdf_tick_bboxes(pdf)}
    png = nmr_out / "strict_probe" / "Fig2_NMR_pure_stacked.png"
    if png.is_file():
        file_geo["png_pixels"] = _png_pixels(png)
    file_geo["all_tick_bboxes_inside"] = all(
        v.get("tick_bboxes", {}).get("all_inside", False) for v in file_geo.values()
        if isinstance(v, dict) and "tick_bboxes" in v)

    ftir_ok = (ftir_rc == 0 and ftir_strict == 1
               and not (ftir_out / "strict-sandbox"
                        / "Fig2_FTIR_transmittance_stacked_annotated.pdf").is_file())
    probe_min = (file_geo.get("strict_probe") or {}).get("min_pt")
    nmr_ok = (nmr_rc == 0 and not sweep["refused"]
              and probe_min is not None and probe_min >= 5.0 - 1e-9
              and file_geo.get("all_tick_bboxes_inside") is True)
    summary = {"nmr_runner_rc": nmr_rc, "ftir_runner_rc": ftir_rc,
               "ftir_strict_rc": ftir_strict, "ftir_refused_as_expected": ftir_ok,
               "strict_basis": ("native 120-DPI build + 600-DPI export PDFs; "
                                "DPI sweep is tick-clip legality only, never all-QA clean"),
               "dpi_sweep": sweep, "file_geometry": file_geo,
               "outcome": ("G23_TICK_PASS" if (nmr_ok and ftir_ok)
                           else "G23_TICK_REFUSED")}
    (outdir / "g23_tick_summary.json").write_text(
        json.dumps(_sanitize(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(_sanitize(summary), indent=2, ensure_ascii=False))
    return 0 if (nmr_ok and ftir_ok) else 3


if __name__ == "__main__":
    raise SystemExit(main())
