#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G21 FTIR publication runner (public, generic, FTIR-only).

Re-runs the exact G21 FTIR controlled proof against a private archive copy:
baseline QA measure -> native config transaction (existing YAML-path API only)
-> candidate strict probe -> PDF audit. No product/API edits, no lowered
thresholds, no automation layout solver. Writes JSON evidence only.

Usage:
  PYTHONPATH=<repo> python tools/g21/ftir_publication.py --stage <private-copy> --out <evidence-dir>
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="G21 FTIR controlled-proof runner")
    ap.add_argument("--stage", required=True, help="private FTIR copy dir (plot_ftir.py+ftir.yaml)")
    ap.add_argument("--out", required=True, help="evidence output dir (outside repo)")
    ap.add_argument("--scope", default="annotated")
    args = ap.parse_args(argv)

    stage = pathlib.Path(args.stage).resolve()
    out = pathlib.Path(args.out).resolve()
    if out.exists():
        ap.error("evidence output must be fresh; existing files are never removed")
    out.mkdir(parents=True)
    script = stage / "plot_ftir.py"
    config = stage / "ftir.yaml"

    import importlib.util

    spec = importlib.util.spec_from_file_location("ftir_g21_runner", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    from figpact import qa as qa_mod
    from figpact.agent_api import AgentSession

    evidence: dict = {
        "script_sha256": _sha(script),
        "config_sha256": _sha(config),
        "scope": args.scope,
    }

    # 1. Baseline: actual QA measure on the real built figure.
    fig0, _ = module.build_figure_and_registry(args.scope)
    ax0 = fig0.axes[0]
    meas0 = qa_mod.measure(fig0)
    evidence["baseline"] = {
        "xlim": [float(v) for v in ax0.get_xlim()],
        "ylim": [float(v) for v in ax0.get_ylim()],
        "glyph_floor_n": sum(1 for r in meas0["records"] if r["rule"] == "GLYPH_FLOOR"),
        "blocking_n": len(list(module.preview_qa(fig0, args.scope))),
        "glyph_records": [
            {"key": r["key"], "value": r["value"], "text": r["text"]} for r in meas0["records"]
            if r["rule"] == "GLYPH_FLOOR"
        ],
    }
    import matplotlib.pyplot as plt

    plt.close(fig0)

    # 2. Native transaction on existing YAML-path controls (no overlay roles for
    # legend/band text; overlay refuses UNKNOWN_ID — verified separately).
    ops = [
        {"operation": "set_parameter", "path": ["legend_font_pt"], "value": 7.2},
        {"operation": "set_parameter", "path": ["label_font_pt"], "value": 7.2},
        {"operation": "set_parameter", "path": ["canvas_h_mm"], "value": 57.5},
    ]
    session = AgentSession(str(script), str(config), args.scope)
    try:
        receipt = session.try_layout(copy.deepcopy(ops))
        preview = session.render_preview() if receipt.get("status") == "OK" else None
    finally:
        session.close()
    evidence["native_try"] = {
        "operations": ops,
        "status": receipt.get("status"),
        "verification": receipt.get("verification"),
        "message": receipt.get("message"),
        "science_unchanged": receipt.get("science_unchanged"),
        "affected_objects": receipt.get("affected_objects"),
        "checks": receipt.get("checks"),
        "new_qa": receipt.get("new_qa"),
        "preview_qa": (preview or {}).get("qa"),
        "preview_qa_kind": (preview or {}).get("qa_kind"),
        "revision": receipt.get("revision"),
    }

    # 3. Fresh strict probe of the candidate YAML in a sandbox (never originals).
    import yaml

    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    cfg["legend_font_pt"] = 7.2
    cfg["label_font_pt"] = 7.2
    cfg["canvas_h_mm"] = 57.5
    sandbox = out / "strict-sandbox"
    sandbox.mkdir()
    cand = sandbox / "candidate.yaml"
    cand.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    cmd = [sys.executable, "-X", "utf8", str(script), "--config", str(cand),
           "--strict", "--probe", str(sandbox)]
    import os

    env = {**os.environ, "FIGPACT_PROBE_DIR": str(sandbox), "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(cmd, cwd=str(stage), capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=600)
    qa_lines = [ln.strip() for ln in (proc.stdout + "\n" + proc.stderr).splitlines() if "[QA]" in ln or "字形审计" in ln or "验收" in ln]
    evidence["strict_probe"] = {
        "returncode": proc.returncode,
        "qa_lines": qa_lines[-25:],
        "artifacts": sorted(p.name for p in sandbox.iterdir() if p.is_file())[:16],
    }

    # 4. PDF audit (>=5pt real glyphs) on the candidate annotated PDF if produced.
    pdf = sandbox / "Fig2_FTIR_transmittance_stacked_annotated.pdf"
    evidence["pdf_audit"] = qa_mod.audit_pdf(pdf) if pdf.is_file() else {"pdf": None, "note": "not produced (strict refused)"}

    (out / "ftir_publication_evidence.json").write_text(
        # Collection success is distinct from publication success.
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: evidence[k] for k in ("baseline", "native_try", "strict_probe")}, ensure_ascii=False, indent=2)[:3000])
    print("wrote", out / "ftir_publication_evidence.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
