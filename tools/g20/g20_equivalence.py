#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G20-B equivalence: UNMODIFIED original __main__ vs pure build_figure_and_registry.

Required inputs (no hardcoded private defaults; missing -> hard error):
  --orig-dir | G20_ORIG_DIR : dir with the BYTE-EXACT original
    plot_cck8_viability.py (sha 59a2f958…) + figure_style.py + 数据1.csv
  --clone-dir | G20_CLONE_DIR: dir with the seam clone (same names + _prepare/
    construct/build_figure_and_registry; draw wraps construct+export+qa)
  --fullrun-dir  | G20_FULLRUN_DIR : fresh isolated workdir for the full run
  --purerun-dir  | G20_PURERUN_DIR : fresh isolated workdir for the pure run
  --evidence     | G20_EQUIVALENCE_JSON   (private full evidence)
  --summary      | G20_EQUIVALENCE_SUMMARY (public sanitized summary)

Fresh isolated dirs per run: outputs/exports must be CREATED DURING the run
(mtime comparison), never pre-existing; stale freezes refused. Every
subprocess returncode is gated into the verdict; any nonzero/missing freeze
key FAILs. Full path: runpy __main__ of the unmodified original (real
fs.export + qa_report, report stdout frozen live). Pure path: seam
build_figure_and_registry(scope='main'), construct only, zero export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCOPE = "main"
PROBE = "g20_equivalence_probe.py"
ORIG_SCRIPT_SHA = "59a2f9586ed62edcd2d10afa5f35b325728d2ef80ffc015129db0164163fbad2"
ARCHIVE_FILES = ("plot_cck8_viability.py", "figure_style.py", "数据1.csv")


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _req(name: str, cli: str, env: str) -> Path:
    val = cli or os.environ.get(env, "")
    if not val:
        raise SystemExit(f"missing required {name}: pass CLI flag or set ${env}")
    return Path(val)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig-dir", default="")
    ap.add_argument("--clone-dir", default="")
    ap.add_argument("--fullrun-dir", default="")
    ap.add_argument("--purerun-dir", default="")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--summary", default="")
    args = ap.parse_args(argv)
    orig = _req("orig dir", args.orig_dir, "G20_ORIG_DIR")
    clone = _req("clone dir", args.clone_dir, "G20_CLONE_DIR")
    fullrun = _req("full workdir", args.fullrun_dir, "G20_FULLRUN_DIR")
    purerun = _req("pure workdir", args.purerun_dir, "G20_PURERUN_DIR")
    evidence_path = _req("evidence", args.evidence, "G20_EQUIVALENCE_JSON")
    summary_path = _req("summary", args.summary, "G20_EQUIVALENCE_SUMMARY")
    for d in (orig, clone):
        if not d.is_dir():
            raise SystemExit(f"missing dir: {d}")
    for n in ARCHIVE_FILES:
        if not (orig / n).is_file():
            raise SystemExit(f"orig missing (refuse stale): {orig / n}")
        if not (clone / n).is_file():
            raise SystemExit(f"clone missing (refuse stale): {clone / n}")
    orig_sha = _sha(orig / "plot_cck8_viability.py")
    if orig_sha != ORIG_SCRIPT_SHA:
        raise SystemExit(f"orig script NOT byte-exact original: {orig_sha}")
    if _sha(orig / "figure_style.py") != _sha(clone / "figure_style.py"):
        raise SystemExit("style dependency differs between orig and clone")
    if _sha(orig / "数据1.csv") != _sha(clone / "数据1.csv"):
        raise SystemExit("instrument CSV differs between orig and clone")
    root = Path(__file__).resolve().parents[2]
    probe = Path(__file__).resolve().parent / PROBE


    # fresh isolated workdirs stocked with VERIFIED copies: full workdir gets
    for wd in (fullrun, purerun):
        if wd.exists():
            shutil.rmtree(wd)
        wd.mkdir(parents=True, exist_ok=True)
    for n in ARCHIVE_FILES:
        shutil.copy2(orig / n, fullrun / n)
        shutil.copy2(clone / n, purerun / n)
    if _sha(fullrun / "plot_cck8_viability.py") != ORIG_SCRIPT_SHA:
        raise SystemExit("full workdir script copy failed hash gate")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    env["MPLBACKEND"] = "Agg"
    full_env = dict(env); full_env["G20_PROBE_MODE"] = "full"
    pure_env = dict(env); pure_env["G20_PROBE_MODE"] = "pure"

    full_cli = subprocess.run(
        [sys.executable, str(fullrun / "plot_cck8_viability.py")],
        capture_output=True, text=True, cwd=str(fullrun), env=full_env, timeout=300)
    full_probe = subprocess.run(
        [sys.executable, str(probe), str(fullrun)], env=full_env,
        capture_output=True, text=True, cwd=str(fullrun), timeout=300)
    pure_probe = subprocess.run(
        [sys.executable, str(probe), str(purerun)],
        capture_output=True, text=True, cwd=str(purerun), env=pure_env, timeout=300)

    runs = {"full_cli": full_cli, "full_probe": full_probe, "pure_probe": pure_probe}
    for k, r in runs.items():
        (fullrun if k != "pure_probe" else purerun).joinpath(
            f"g20_{k}_log.txt").write_text(
            f"returncode={r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}",
            encoding="utf-8")

    def _load(wd: Path, name: str) -> dict:
        p = wd / name
        if not p.is_file():
            return {"error": f"missing freeze (refuse stale): {name}"}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"error": f"unreadable freeze {name}: {exc}"}

    ff = _load(fullrun, "g20_full_freeze.json")
    pf = _load(purerun, "g20_pure_freeze.json")


    evidence = {
        "scope": SCOPE,
        "orig_sha256": {n: {"sha256": _sha(orig / n), "bytes": (orig / n).stat().st_size}
                        for n in ARCHIVE_FILES},
        "clone_sha256": {n: {"sha256": _sha(clone / n), "bytes": (clone / n).stat().st_size}
                         for n in ARCHIVE_FILES},
        "orig_byte_exact": orig_sha == ORIG_SCRIPT_SHA,
        "runs": {k: {"returncode": r.returncode,
                     "stdout_tail": r.stdout[-1500:], "stderr_tail": r.stderr[-1500:]}
                 for k, r in runs.items()},
        "full": {"freeze": ff}, "pure": {"freeze": pf},
    }
    dims: dict = {}
    dims["all_runs_returncode_zero"] = all(r.returncode == 0 for r in runs.values())
    dims["freezes_present"] = all("error" not in f for f in (ff, pf))
    if dims["freezes_present"]:
        dims["science_numeric"] = ff.get("science") == pf.get("science")
        dims["stats_stdout_report_block"] = ff.get("report_block") == pf.get("report_block")
        dims["figure_geometry"] = ff.get("figure") == pf.get("figure")
        dims["artists"] = ff.get("artists") == pf.get("artists")
        dims["styles"] = ff.get("styles") == pf.get("styles")
        dims["view"] = ff.get("view") == pf.get("view")
        dims["ownership_registry"] = (
            ff.get("ownership") == pf.get("ownership")
            and pf.get("ownership", {}).get("registry_scope") == SCOPE)
        dims["export_counts_expected"] = (
            ff.get("counts", {}).get("fs_export") == 1
            and ff.get("counts", {}).get("savefig") == 3
            and pf.get("counts", {}).get("fs_export") == 0
            and pf.get("counts", {}).get("savefig") == 0)
        exported = sorted(fullrun.glob("Fig3_CCK8_viability.*"))
        created = [p for p in exported if p.suffix.lower() in (".svg", ".pdf", ".png", ".tiff")]
        dims["full_cli_exports_created_during_run"] = (
            full_cli.returncode == 0 and len(created) == 4
            and all(p.stat().st_size > 0 for p in created))
        dims["pure_zero_new_files"] = pf.get("new_files") == []
    evidence["dimensions"] = dims
    evidence["verdict"] = "PASS" if dims and all(dims.values()) else "FAIL"

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    summary = {
        "scope": SCOPE, "verdict": evidence["verdict"], "dimensions": dims,
        "orig_script_sha256": orig_sha, "orig_byte_exact": evidence["orig_byte_exact"],
        "export_counts": {
            "full": (ff.get("counts") if isinstance(ff, dict) else None),
            "pure": (pf.get("counts") if isinstance(pf, dict) else None)},
        "run_returncodes": {k: r.returncode for k, r in runs.items()},
        "note": "sanitized: sha + PASS/FAIL + counts + returncodes only",
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(json.dumps({"verdict": evidence["verdict"], "dimensions": dims},
                     ensure_ascii=False, indent=2))
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
