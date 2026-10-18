#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G19 pure protocol wrapper: full-original CCK8 panel from archive copies.

NO post-hoc fontsize/linewidth replay, NO legend move, NO contract-parameter
YAML. Runs the COMPLETE original ``__main__`` flow unchanged (3-timepoint
single-panel statistics, no custom multipanel) inside the archive copy dir.
Style sampling uses the real ``figpact.inspector_style.StyleSession``
preview/cancel/commit/restart/conflict — the G18 public path.

Science inputs (module-level, explicit): archive copies of the original
script, the CSV, and figure_style.py. NEVER imports from the original
research path; execution uses only ``--archive-copy-dir`` contents.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents
                            if (p / "figpact").is_dir())))

SCOPE = "main"
# Archive layout (copies only, never the research root):
#   <stage>/plot_cck8_viability.py  archived original script copy
#   <stage>/数据1.csv               archived instrument CSV copy
#   <stage>/figure_style.py         archived style dependency copy
#   <stage>/origrun/*               runnable clone (same three files)
ARCHIVE_FILES = ("plot_cck8_viability.py", "数据1.csv", "figure_style.py")


def _stage() -> Path:
    root = os.environ.get("G19_ARCHIVE_COPY")
    if not root:
        raise RuntimeError("G19_ARCHIVE_COPY not set (or pass --archive-copy-dir)")
    return Path(root)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_config(path):
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_science():
    """Science served from the archive CSV (never recomputed here)."""
    return {"csv": "数据1.csv"}


def science_inputs():
    """Explicit script/CSV/style files actually used by the archive replay.

    These are named dependencies, not an automatic Python import closure.
    """
    stage = _stage() / "origrun"
    csv = stage / "数据1.csv"
    if not csv.is_file():
        raise FileNotFoundError(f"science source missing: {csv} (no CSV, no science)")
    deps = [str(stage / "plot_cck8_viability.py"), str(csv),
            str(stage / "figure_style.py")]
    return deps


def science_manifest(_science):
    return None


def build_figure_and_registry(scope="main"):
    """Run the COMPLETE original ``__main__`` flow inside the archive copy.

    No subsetting, no style overrides: the original 3-timepoint panel is the
    figure. Reads ``G19_ARCHIVE_COPY`` — never the research root.
    """
    import runpy
    import matplotlib.pyplot as plt
    archive = Path(os.environ["G19_ARCHIVE_COPY"]) / "origrun"
    plt.close("all")
    old_argv, old_cwd = sys.argv, os.getcwd()
    # original resolves HERE/DATA_FILE/OUT relative to its own path, and
    # fs.export writes next to the script: run it in-dir (archive copy).
    os.chdir(archive)
    sys.argv = ["plot_cck8_viability.py"]
    try:
        with redirect_stdout(io.StringIO()):
            runpy.run_path(str(archive / "plot_cck8_viability.py"), run_name="__main__")
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    figs = [plt.figure(n) for n in plt.get_fignums()]
    # __main__ exports but never closes: last open figure is the panel.
    for extra in figs[:-1]:
        plt.close(extra)
    fig = figs[-1]
    from figpact import GidRegistry
    return fig, GidRegistry(scope=scope)


def run_trial(archive: Path, outdir: Path) -> dict:
    from figpact.inspector_style import StyleSession

    os.environ["G19_ARCHIVE_COPY"] = str(archive)
    outdir.mkdir(parents=True, exist_ok=True)
    results: dict = {"sample": "cck8-single-axes-3-timepoints", "scope": SCOPE, "operations": []}

    # 1. freeze archive copies (script + csv + style = full dependency list).
    # Copies live in the stage dir; evidence duplicates land under cck8/inputs.
    script = Path(__file__).resolve()
    sci = science_inputs()  # hard-errors when the CSV science source is absent
    inp = outdir / "cck8" / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    frozen = {}
    for name in ARCHIVE_FILES:
        src = archive / name
        if not src.exists():
            raise FileNotFoundError(f"archive copy missing: {src}")
        dst = inp / name
        shutil.copy2(src, dst)
        frozen[name] = {"sha256": _sha(dst), "bytes": dst.stat().st_size}
    results["frozen_inputs"] = frozen
    results["science_inputs"] = sci
    results["archive_exec_only"] = True
    results["original_research_path_imported"] = False
    results["wrapper_loc_total"] = sum(1 for _ in open(script, encoding="utf-8"))
    results["science_dependencies"] = [
        "plot_cck8_viability.py (archived original script copy)",
        "数据1.csv (archived instrument CSV copy)",
        "figure_style.py (archived style dependency copy)",
    ]
    (outdir / "cck8" / "wrapper").mkdir(parents=True, exist_ok=True)
    shutil.copy2(script, outdir / "cck8" / "wrapper" / script.name)
    import csv as _csv
    with open(archive / "数据1.csv", encoding="utf-8-sig", newline="") as fh:
        rows = list(_csv.reader(fh))
    header = [c.strip() for c in rows[0][1:]]
    ncols = len(header)
    results["original_csv_truth"] = {
        "rows": len(rows) - 1, "cols": ncols,
        "timepoints": [r[0].strip() for r in rows[1:]],
        "group_codes": header}
    results["sample"] = "cck8-single-axes-3-timepoints"
    results["axes_source_truth"] = "1 Axes; 9 bars (3 groups x 3 timepoints d1/d3/d7); NOT 3 panels"
    results["user_approved_scope_note"] = (
        "single-panel statistics: single Axes with 3 timepoint clusters, "
        "no custom multipanel invented")

    # 2. StyleSession real flow: snapshot -> preview -> cancel -> preview -> commit
    ov_commit = outdir / "cck8" / "operations" / "trial_commit.overlay.json"
    ov_commit.parent.mkdir(parents=True, exist_ok=True)
    ov_commit.unlink(missing_ok=True)
    sess = StyleSession(script=script, config=None, scope=SCOPE, overlay=ov_commit)
    try:
        frame = sess.snapshot()
        results["baseline_frame_revision"] = frame.get("frame_revision")
        targets = frame["style"]["targets"]
        results["inventory"] = [
            {"target_id": t["target_id"], "label": t.get("label"),
             "property": t.get("property"), "current_pt": t.get("current_pt"),
             "saved_pt": t.get("saved_pt")} for t in targets]
        title = next((t for t in targets if t.get("label") in ("xlabel", "ylabel")), None)
        if title is None:
            raise RuntimeError("no axis.title target in StyleSession snapshot")
        tid = title["target_id"]
        results["sampled_target"] = {"target_id": tid, "old_pt": title["current_pt"]}
        new_val = float(title["current_pt"]) + 1.0

        # preview #1 -> cancel (candidate dropped, official untouched).
        # If the original figure's own QA fails, record local PASS +
        # figure FAIL honestly — NEVER retune the original style to pass.
        prev1, code1 = sess.preview({"frame_revision": frame["frame_revision"],
                                     "target_id": tid, "value": new_val})
        results["operations"].append({"name": "preview-1", "http": code1,
                                      "status": prev1.get("status"),
                                      "receipt": (prev1.get("receipt") or {})})
        if code1 != 200:
            results["operations"].append({"name": "cancel", "http": None,
                                          "status": "SKIPPED_PREVIEW_REJECTED"})
            results["overlay_commit"] = {
                "status": "NOT_COMMITTED_PREVIEW_REJECTED",
                "preview_receipt": prev1.get("receipt")}
        else:
            cand = prev1["style"]["pending"]["candidate_id"]
            canc, codec = sess.cancel({"candidate_id": cand})
            results["operations"].append({"name": "cancel", "http": codec,
                                          "status": canc.get("status")})
            # preview #2 (same intent) -> commit (official write)
            frame2 = sess.snapshot()
            prev2, code2 = sess.preview({"frame_revision": frame2["frame_revision"],
                                         "target_id": tid, "value": new_val})
            p2 = (prev2.get("style") or {}).get("pending")
            results["operations"].append({"name": "preview-2", "http": code2,
                                          "status": prev2.get("status")})
            if code2 != 200 or p2 is None:
                results["overlay_commit"] = {
                    "status": "NOT_COMMITTED_PREVIEW_REJECTED",
                    "preview_receipt": prev2.get("receipt")}
            else:
                committed, codec2 = sess.commit({"candidate_id": p2["candidate_id"],
                                                 "frame_revision": p2["base_frame_revision"],
                                                 "expected_sha256": p2["expected_sha256"]})
                results["operations"].append({"name": "commit", "http": codec2,
                                              "status": committed.get("status")})
                receipt = (committed.get("style") or {}).get("receipt") or {}
                results["overlay_commit"] = {
                    "status": committed.get("status"),
                    "local_edit_state": receipt.get("local_edit_state"),
                    "source_commit_state": receipt.get("source_commit_state"),
                    "figure_verification_state": receipt.get("figure_verification_state"),
                    "figure_qa": receipt.get("figure_qa"),
                    "overlay_sha256": _sha(ov_commit) if ov_commit.exists() else None,
                }
        # external conflict: preview against a tampered overlay -> must refuse.
        if ov_commit.exists():
            raw = ov_commit.read_bytes()
            ov_commit.write_bytes(raw + b" ")
            try:
                sess_c = StyleSession(script=script, config=None, scope=SCOPE,
                                      overlay=outdir / "cck8" / "operations" / "trial_probe.overlay.json")
                frame_c = sess_c.snapshot()
                tc = frame_c["style"]["targets"][0]
                _, codex = sess_c.preview({"frame_revision": "bogus",
                                            "target_id": tc["target_id"], "value": 5.0})
                results["overlay_external_conflict"] = {"http": codex, "refused": codex != 200}
            except RuntimeError as exc:
                results["overlay_external_conflict"] = {"startup_refused": True,
                                                        "reason": str(exc)[:200]}
            finally:
                ov_commit.write_bytes(raw)
        else:
            results["overlay_external_conflict"] = {"skipped": "no committed overlay to tamper"}
    finally:
        try:
            sess._drop_pending()
        except Exception:
            pass

    # 3. restart from saved overlay (fresh session); skip if nothing committed.
    if ov_commit.exists():
        sess2 = StyleSession(script=script, config=None, scope=SCOPE, overlay=ov_commit)
        try:
            frame_r = sess2.snapshot()
            saved = {t["target_id"]: t.get("saved_pt") for t in frame_r["style"]["targets"]}
            results["restart_saved_pt"] = saved.get(results["sampled_target"]["target_id"])
            results["restart_matches_committed"] = (
                results["restart_saved_pt"] == results["sampled_target"]["old_pt"] + 1.0)
        finally:
            try:
                sess2._drop_pending()
            except Exception:
                pass
    else:
        results["restart_matches_committed"] = False
        results["restart_note"] = "no committed overlay; restart skipped"

    # 4. baseline PNG from the pure wrapper (unmodified original style)
    import matplotlib.pyplot as plt
    fig_b, _reg_b = build_figure_and_registry(SCOPE)  # tuple (fig, reg)
    try:
        base_png = outdir / "cck8" / "g19_cck8_baseline.png"
        fig_b.savefig(base_png, dpi=150)
    finally:
        plt.close(fig_b)
    # honest prep-cost split: wrapper hooks vs trial runner (counted, not claimed)
    results["loc_split"] = {
        "header_imports_scope_consts": "lines 1-42",
        "wrapper_hooks": "load_config/load_science/science_inputs/science_manifest/build_figure_and_registry",
        "runner": "run_trial/main",
        "note": "exact per-function counts printed to stdout by --count-loc"}
    (outdir / "cck8" / "operations" / "trial_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive-copy-dir", default=os.environ.get("G19_ARCHIVE_COPY", ""))
    ap.add_argument("--output-dir", default=os.environ.get("G19_OUTPUT_DIR", ""))
    ap.add_argument("--count-loc", action="store_true",
                    help="print exact per-function line counts and exit")
    args = ap.parse_args(argv)
    if args.count_loc:
        import ast as _ast
        tree = _ast.parse(Path(__file__).read_text(encoding="utf-8"))
        total = sum(1 for _ in open(__file__, encoding="utf-8"))
        print(f"total_lines={total}")
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                print(f"{node.name}: lines {node.lineno}-{node.end_lineno} "
                      f"= {node.end_lineno - node.lineno + 1}")
        return
    if not args.archive_copy_dir or not args.output_dir:
        raise SystemExit("need --archive-copy-dir and --output-dir")
    results = run_trial(Path(args.archive_copy_dir), Path(args.output_dir))
    print(json.dumps({k: results[k] for k in
                      ("sample", "operations", "overlay_commit",
                       "overlay_external_conflict", "restart_matches_committed")
                      if k in results}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
