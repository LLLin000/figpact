#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G20 serial timing runner (public, generic): FTIR + NMR + CCK8-before/after.

Single runner (owner: PerformanceG20). Reuses tools/g19/profile_trial.py
read-only (percentile); extends its phase hooks with qa.measure /
collect_records via own context — G19 file unchanged. Private archive
scripts (G19 integrated copies, G20 CCK8 clone) are used read-only via
figpact.final_size._import_script, which resolves ancestor figpact package
+ script parent on sys.path automatically (verified before full run).
G20_AUTHORIZED=1 gate enforced. plt.close('all') between serial samples;
no caches.
"""
from __future__ import annotations

import argparse
import functools
import gc
import hashlib
import importlib.util
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G19 = ROOT / "tools" / "g19"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "g19_profile_trial", G19 / "profile_trial.py")
_g19 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_g19)
percentile = _g19.percentile
PHASES = ("import", "build", "identity", "audit", "qa", "save", "render")


def _close_all():
    try:
        import matplotlib.pyplot as plt
        plt.close("all")
    except Exception:
        pass
    gc.collect()


@contextmanager
def phases_plus(export_stats=None):
    """G19 phases() + qa.measure/collect_records (own context, G19 file intact).

    export_stats (optional dict): Figure.savefig calls recorded with actual
    args + exclusive seconds by the SAME wrapper doing render-phase accounting
    (single stack, no double count). fs.export wrapped per-script, not phased.
    """
    from figpact import final_size, style_identity, style_overlay, change_audit, qa, source_writes, inspector
    from matplotlib.figure import Figure
    hooks = [(final_size, '_import_script', 'import'), (final_size, '_build_figure', 'build'),
             (style_identity, 'inventory', 'identity'), (style_identity, 'resolve', 'identity'),
             (style_overlay, '_verify_pair', 'audit'), (change_audit, 'geometry_snapshot', 'audit'),
             (style_overlay, '_snapshots', 'audit'), (qa, 'blocking_problems', 'qa'),
             (qa, 'check_glyph_floor', 'qa'), (qa, 'measure', 'qa'),
             (qa, 'collect_records', 'qa'), (style_overlay, '_min_plain_fontsize', 'qa'),
             (source_writes, '_write_json', 'save'), (style_overlay, '_write_new_exclusive', 'save'),
             (inspector, 'capture_figure', 'render'), (Figure, 'savefig', 'render')]
    totals = {n: 0.0 for n in PHASES}
    counts = {n: 0 for n in PHASES}
    stack, originals = [], []
    savefig_orig = Figure.savefig

    def wrap(fn, phase):
        @functools.wraps(fn)
        def measured(*a, **kw):
            start = time.perf_counter()
            entry = [0.0]
            stack.append(entry)
            counts[phase] += 1
            try:
                out = fn(*a, **kw)
                if export_stats is not None and fn is savefig_orig:
                    export_stats["savefig_calls"].append(
                        {"args": [str(x) for x in a[1:3]],
                         "kwargs": {k: str(v) for k, v in kw.items()},
                         "exclusive_s": time.perf_counter() - start - entry[0]})
                return out
            finally:
                elapsed = time.perf_counter() - start
                stack.pop()
                totals[phase] += elapsed - entry[0]
                if stack:
                    stack[-1][0] += elapsed
        return measured
    try:
        for owner, name, phase in hooks:
            if not hasattr(owner, name):
                continue
            fn = getattr(owner, name)
            originals.append((owner, name, fn))
            setattr(owner, name, wrap(fn, phase))
        yield totals, counts
    finally:
        for owner, name, fn in reversed(originals):
            setattr(owner, name, fn)


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _receipt(result: dict) -> dict:
    if isinstance(result.get("receipt"), dict):
        return result["receipt"]
    style = result.get("style")
    if isinstance(style, dict) and isinstance(style.get("receipt"), dict):
        return style["receipt"]
    return {}


def _pick(frame: dict, role: str):
    tgts = [t for t in frame["style"]["targets"]
            if role in t["target_id"]
            or (role == "axis.title" and t["label"] in ("xlabel", "ylabel"))
            or (role == "axis.tick" and "tick" in t["label"])
            or (role == "curve.linewidth" and t["property"] == "linewidth")]
    if not tgts:
        raise ValueError("No exact eligible target for requested role")
    return tgts[0]


@contextmanager
def _fs_wrap(script: Path, stats: dict):
    """Wrap the FULL wrapper's dynamically imported figure_style.export with a
    delegating counter (actual fn args + inclusive seconds, never suppressed).
    Confirms the module location first — a count of 0 must be real, not a miss.
    Yields the module (or None for pure wrappers without the attribute).
    """
    import sys as _sys
    stats["fs_module"] = None
    spec = importlib.util.spec_from_file_location("_g20_fswrap", str(script))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    if not hasattr(probe, "build_figure_and_registry"):
        yield None
        return
    parent = str(Path(script).resolve().parent)
    added = parent not in _sys.path
    if added:
        _sys.path.insert(0, parent)
    try:
        import figure_style as fs_mod
        stats["fs_module"] = str(Path(fs_mod.__file__).resolve())
        orig = fs_mod.export

        @functools.wraps(orig)
        def counting(fig, *a, **k):
            t0 = time.perf_counter()
            try:
                return orig(fig, *a, **k)
            finally:
                stats["fs_export_calls"].append(
                    {"args": [str(x) for x in a[:3]],
                     "kwargs": {kk: str(vv) for kk, vv in k.items()},
                     "inclusive_s": time.perf_counter() - t0})
        fs_mod.export = counting
        try:
            yield fs_mod
        finally:
            fs_mod.export = orig
    finally:
        if added:
            try:
                _sys.path.remove(parent)
            except ValueError:
                pass


def _acceptance_export(script: Path, config: Path | None, scope: str,
                       dest: Path, extra_env: dict | None = None) -> dict:
    """Runner-extra acceptance artifact (listed separately, NOT source exports)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    saved = {k: os.environ.get(k) for k in (extra_env or {})}
    for k, v in (extra_env or {}).items():
        os.environ[k] = v
    try:
        from figpact.final_size import _import_script, _load_config, _build_figure
        import copy
        mod = _import_script(script)
        cfg = _load_config(mod, script, config)
        if hasattr(mod, "build_figure_and_registry"):
            fig, _reg = mod.build_figure_and_registry(scope)
        else:
            (fig, _reg), _r = _build_figure(mod, copy.deepcopy(cfg), scope)
        try:
            fig.savefig(dest, dpi=150)
        finally:
            try:
                plt.close(fig)
            except Exception:
                pass
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _close_all()
    return {"bytes": dest.stat().st_size}


def _run(name, script, config, scope, outdir, rounds, role, extra_env=None):
    from figpact.inspector_style import StyleSession
    _close_all()
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(rounds):
        overlay = outdir / f"round-{i}.json"
        if overlay.exists():
            raise ValueError("Use a fresh output directory")
        row: dict = {"round": i}
        export_stats: dict = {"savefig_calls": [], "fs_export_calls": [], "fs_module": None}
        with _fs_wrap(script, export_stats), phases_plus(export_stats) as (timing, counts):
            start = time.perf_counter()
            saved_env = {k: os.environ.get(k) for k in (extra_env or {})}
            for k, v in (extra_env or {}).items():
                os.environ[k] = v
            try:
                try:
                    sess = StyleSession(script=script, config=config,
                                        scope=scope, overlay=overlay)
                    frame = sess.snapshot()
                    tgt = _pick(frame, role)
                    delta = 1.0 if tgt["property"] == "fontsize" else 0.2
                    value = float(tgt["current_pt"]) + delta
                    row["target_id"] = tgt["target_id"]
                    ps = time.perf_counter()
                    preview, code = sess.preview(
                        {"frame_revision": frame["frame_revision"],
                         "target_id": tgt["target_id"], "value": value})
                    row["preview_s"] = time.perf_counter() - ps
                    row["http"] = code
                    row["status"] = preview.get("status")
                    rec = _receipt(preview)
                    (outdir / f"round-{i}.receipt.json").write_text(
                        json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
                    row["commit_s"] = None
                    if code == 200:
                        pend = preview["style"]["pending"]
                        body = {"candidate_id": pend["candidate_id"],
                                "frame_revision": pend["base_frame_revision"],
                                "expected_sha256": pend["expected_sha256"]}
                        if pend.get("is_draft"):
                            body["save_draft"] = True
                            row["pending_is_draft"] = True
                        else:
                            row["pending_is_draft"] = False
                        cs = time.perf_counter()
                        committed, ccode = sess.commit(body)
                        row["commit_s"] = time.perf_counter() - cs
                        row["http"] = ccode
                        row["status"] = committed.get("status")
                        rec = _receipt(committed) or rec
                        (outdir / f"round-{i}.commit.json").write_text(
                            json.dumps(committed, ensure_ascii=False, indent=2), encoding="utf-8")
                    row["local_edit_state"] = rec.get("local_edit_state")
                    row["source_commit_state"] = rec.get("source_commit_state")
                    row["figure_verification_state"] = rec.get("figure_verification_state")
                    row["draft"] = rec.get("draft")
                    row["figure_qa"] = rec.get("figure_qa")
                    try:
                        sess._drop_pending()
                    except Exception:
                        pass
                    if overlay.exists():
                        sess2 = StyleSession(script=script, config=config,
                                             scope=scope, overlay=overlay)
                        try:
                            fr = sess2.snapshot()
                            saved = {t["target_id"]: t.get("saved_pt")
                                     for t in fr["style"]["targets"]}
                            row["restart_saved_pt"] = saved.get(tgt["target_id"])
                            row["restart_matches_committed"] = (
                                row["restart_saved_pt"] == float(tgt["current_pt"]) + delta)
                            p2, c2 = sess2.preview(
                                {"frame_revision": fr["frame_revision"],
                                 "target_id": tgt["target_id"],
                                 "value": float(tgt["current_pt"]) + delta + 0.5})
                            row["further_edit"] = {"http": c2, "status": p2.get("status")}
                            try:
                                sess2._drop_pending()
                            except Exception:
                                pass
                        finally:
                            try:
                                sess2._drop_pending()
                            except Exception:
                                pass
                    else:
                        row["restart_matches_committed"] = False
                        row["restart_note"] = "no committed overlay; restart skipped"
                    # SAME session created BEFORE external mutate; legitimate-frame
                    # preview -> OVERLAY_CONFLICT; bytes-preservation checked.
                    if overlay.exists():
                        sess_x = StyleSession(script=script, config=config,
                                              scope=scope, overlay=overlay)
                        try:
                            fx = sess_x.snapshot()
                            tx = _pick(fx, role)
                            legit = {"frame_revision": fx["frame_revision"],
                                     "target_id": tx["target_id"],
                                     "value": float(tx["current_pt"]) + 0.3}
                            before = _sha(overlay)
                            raw = overlay.read_bytes()
                            overlay.write_bytes(raw + b" ")
                            try:
                                rx, codex = sess_x.preview(legit)
                                row["external_conflict"] = {
                                    "http": codex, "status": rx.get("status"),
                                    "overlay_conflict": rx.get("status") == "OVERLAY_CONFLICT"}
                            finally:
                                overlay.write_bytes(raw)
                            row["external_conflict_bytes_preserved"] = (_sha(overlay) == before)
                            try:
                                sess_x._drop_pending()
                            except Exception:
                                pass
                        finally:
                            try:
                                sess_x._drop_pending()
                            except Exception:
                                pass
                    else:
                        row["external_conflict"] = {"skipped": "no committed overlay to tamper"}
                except Exception as e:
                    row["status"] = "BLOCKED"
                    row["error"] = f"{type(e).__name__}: {e}"
            finally:
                for k, v in saved_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                _close_all()
            row["total_s"] = time.perf_counter() - start
            row["exclusive_phases_s"] = dict(timing)
            row["phase_calls"] = dict(counts)
            row["other_s"] = max(0.0, row["total_s"] - sum(timing.values()))
        # Source exports = instrumented calls INSIDE the phase window (no extra
        # rebuild). fs_export: delegating wrapper, actual args + inclusive time.
        # savefig: same wrapper as render-phase accounting (exclusive time).
        row["source_exports"] = {
            "fs_export_calls": len(export_stats["fs_export_calls"]),
            "fs_export_s": sum(c["inclusive_s"] for c in export_stats["fs_export_calls"]),
            "fs_export": export_stats["fs_export_calls"],
            "fs_module": export_stats["fs_module"],
            "savefig_calls": len(export_stats["savefig_calls"]),
            "savefig_s": sum(c["exclusive_s"] for c in export_stats["savefig_calls"]),
            "savefig": export_stats["savefig_calls"]}
        try:
            acc = _acceptance_export(
                script, config, scope, outdir / f"round-{i}.acceptance.png", extra_env)
        except Exception as e:
            acc = {"error": f"{type(e).__name__}: {e}"}
        row["acceptance_artifact"] = acc
        rows.append(row)
    _close_all()
    summary: dict = {}
    for m in ("total_s", "preview_s", "commit_s"):
        vals = [r[m] for r in rows if isinstance(r.get(m), (float, int))]
        summary[m] = {"n": len(vals), "p50": percentile(vals, 0.5),
                      "p95": percentile(vals, 0.95)} if vals else {"n": 0, "p50": None, "p95": None}
    fsv = [r["source_exports"]["fs_export_s"] for r in rows
           if isinstance(r.get("source_exports"), dict)]
    sgv = [r["source_exports"]["savefig_s"] for r in rows
           if isinstance(r.get("source_exports"), dict)]
    summary["fs_export_s"] = {"n": len(fsv), "p50": percentile(fsv, 0.5) if fsv else None,
                              "p95": percentile(fsv, 0.95) if fsv else None,
                              "calls": sum(r["source_exports"]["fs_export_calls"] for r in rows
                                           if isinstance(r.get("source_exports"), dict))}
    summary["savefig_s"] = {"n": len(sgv), "p50": percentile(sgv, 0.5) if sgv else None,
                            "p95": percentile(sgv, 0.95) if sgv else None,
                            "calls": sum(r["source_exports"]["savefig_calls"] for r in rows
                                         if isinstance(r.get("source_exports"), dict))}
    for ph in PHASES:
        vals = [r["exclusive_phases_s"][ph] for r in rows]
        calls = sum(r["phase_calls"][ph] for r in rows)
        summary[ph] = {"n": len(vals) if calls else 0, "calls": calls,
                       "p50": percentile(vals, 0.5) if calls else None,
                       "p95": percentile(vals, 0.95) if calls else None}
    last_qa = next((r.get("figure_qa") for r in reversed(rows)
                    if isinstance(r.get("figure_qa"), dict)), {})
    result = {"sample": name, "scope": scope,
              "script": Path(str(script)).name, "config": Path(str(config)).name if config else None,
              "rounds": rows, "summary": summary,
              "round_statuses": [r.get("status") for r in rows],
              "local_edit_state": rows[-1].get("local_edit_state") if rows else None,
              "figure_verification_state": rows[-1].get("figure_verification_state") if rows else None,
              "source_commit_state": rows[-1].get("source_commit_state") if rows else None,
              "qa": last_qa,
              "method": ("exclusive nested monotonic timings incl qa.measure/collect_records; "
                         "serial same-host warm-process; no verifier bypass; real export "
                         "instrumented without suppression")}
    (outdir / "timings.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _sanitize_exports(se: dict) -> dict:
    if not isinstance(se, dict):
        return {}
    def _fmt(call: dict) -> dict:
        args = call.get("args") or []
        suffix = next((str(a)[str(a).rfind("."):] for a in args
                       if isinstance(a, str) and "." in str(a)), None)
        fmt = (call.get("kwargs") or {}).get("format")
        return {"suffix_or_format": fmt or suffix,
                "s": call.get("inclusive_s", call.get("exclusive_s"))}
    return {"fs_export_calls": se.get("fs_export_calls"),
            "fs_export_s": se.get("fs_export_s"),
            "savefig_calls": se.get("savefig_calls"),
            "savefig_s": se.get("savefig_s"),
            "fs_export": [_fmt(c) for c in (se.get("fs_export") or [])],
            "savefig": [_fmt(c) for c in (se.get("savefig") or [])]}


def _sanitize_qa(qa: dict) -> dict:
    if not isinstance(qa, dict):
        return {}
    return {"pass": qa.get("pass"),
            "blocking_count": len(qa.get("blocking") or []),
            "glyph_floor_count": len(qa.get("glyph_floor") or [])}


def _sanitize_error(err) -> str | None:
    if not err:
        return None
    return str(err).split(":")[0]


def _sanitize(result: dict) -> dict:
    out = {k: result.get(k) for k in (
        "sample", "scope", "script", "config", "summary", "round_statuses",
        "local_edit_state", "figure_verification_state", "source_commit_state",
        "method")}
    out["qa"] = _sanitize_qa(result.get("qa"))
    out["rounds_per_sample_note"] = (
        f"n={result.get('summary', {}).get('total_s', {}).get('n')}; "
        "no claim beyond actual n")
    sanitized_rounds = []
    for r in result.get("rounds", []):
        acc = r.get("acceptance_artifact") or {}
        sanitized_rounds.append({
            "round": r.get("round"), "http": r.get("http"), "status": r.get("status"),
            "preview_s": r.get("preview_s"), "commit_s": r.get("commit_s"),
            "total_s": r.get("total_s"), "exclusive_phases_s": r.get("exclusive_phases_s"),
            "phase_calls": r.get("phase_calls"), "other_s": r.get("other_s"),
            "local_edit_state": r.get("local_edit_state"),
            "source_commit_state": r.get("source_commit_state"),
            "figure_verification_state": r.get("figure_verification_state"),
            "draft": r.get("draft"), "pending_is_draft": r.get("pending_is_draft"),
            "restart_matches_committed": r.get("restart_matches_committed"),
            "further_edit": ({"http": (r.get("further_edit") or {}).get("http"),
                             "status": (r.get("further_edit") or {}).get("status")}
                            if isinstance(r.get("further_edit"), dict) else None),
            "external_conflict": ({"http": (r.get("external_conflict") or {}).get("http"),
                                  "status": (r.get("external_conflict") or {}).get("status"),
                                  "overlay_conflict": (r.get("external_conflict") or {}).get("overlay_conflict"),
                                  "skipped": (r.get("external_conflict") or {}).get("skipped")}
                                 if isinstance(r.get("external_conflict"), dict) else None),
            "external_conflict_bytes_preserved": r.get("external_conflict_bytes_preserved"),
            "source_exports": _sanitize_exports(r.get("source_exports")),
            "acceptance_artifact": ({"bytes": acc.get("bytes"),
                                    "exists": acc.get("bytes") is not None}
                                   if isinstance(acc, dict) else {}),
            "error": _sanitize_error(r.get("error")),
        })
    out["rounds"] = sanitized_rounds
    return out


def main(argv=None):
    import matplotlib
    matplotlib.use("Agg")
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=os.environ.get("G20_OUTPUT_DIR", ""))
    ap.add_argument("--sanitized-out", default=str(ROOT / "tools" / "g20" / "timing_results.json"))
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--role", default="axis.title")
    ap.add_argument("--ftir-script", default=os.environ.get("G20_FTIR_SCRIPT", ""))
    ap.add_argument("--ftir-config", default=os.environ.get("G20_FTIR_CONFIG", ""))
    ap.add_argument("--nmr-script", default=os.environ.get("G20_NMR_SCRIPT", ""))
    ap.add_argument("--nmr-config", default=os.environ.get("G20_NMR_CONFIG", ""))
    _orig = os.environ.get("G20_ORIG_DIR", "")
    _clone = os.environ.get("G20_CLONE_DIR", "")
    ap.add_argument("--cck8-full-script", default=os.environ.get(
        "G20_CCK8_FULL_SCRIPT", f"{_orig}/plot_cck8_viability.py" if _orig else ""))
    ap.add_argument("--cck8-pure-script", default=os.environ.get(
        "G20_CCK8_SCRIPT", f"{_clone}/plot_cck8_viability.py" if _clone else ""))
    ap.add_argument("--cck8-full-env", default=os.environ.get("G20_CCK8_FULL_ENV", _orig))
    ap.add_argument("--cck8-pure-env", default=_clone)
    args = ap.parse_args(argv)
    if args.rounds < 3:
        ap.error("at least 3 actual rounds required")
    if os.environ.get("G20_AUTHORIZED") != "1":
        raise SystemExit("refusing to run: parent has not authorized (G20_AUTHORIZED=1 only "
                         "after full regressions complete)")
    if not args.output_dir:
        raise SystemExit("need --output-dir (private archive/g20, never the repo)")
    missing = [k for k in ("ftir-script", "ftir-config", "nmr-script", "nmr-config",
                           "cck8-full-script", "cck8-pure-script")
               if not getattr(args, k.replace("-", "_"))]
    if missing:
        raise SystemExit(f"missing private inputs (env or flags): {missing}")
    outroot = Path(args.output_dir)
    if any((outroot / s / "timings.json").exists()
           for s in ("ftir", "nmr", "cck8-full", "cck8-pure")):
        raise SystemExit("output dir not fresh; use an empty archive/g20 dir")
    samples = {}
    samples["ftir"] = _run("ftir", Path(args.ftir_script), Path(args.ftir_config),
                           "main", outroot / "ftir", args.rounds, args.role)
    _close_all()
    samples["nmr"] = _run("nmr", Path(args.nmr_script), Path(args.nmr_config),
                          "main", outroot / "nmr", args.rounds, args.role)
    _close_all()
    full_env = {"G19_ARCHIVE_COPY": args.cck8_full_env} if args.cck8_full_env else None
    pure_env = {"G20_CLONE_DIR": args.cck8_pure_env} if args.cck8_pure_env else None
    samples["cck8-full"] = _run("cck8-full", Path(args.cck8_full_script), None,
                                "main", outroot / "cck8-full", args.rounds, args.role, full_env)
    _close_all()
    samples["cck8-pure"] = _run("cck8-pure", Path(args.cck8_pure_script), None,
                                "main", outroot / "cck8-pure", args.rounds, args.role, pure_env)
    _close_all()
    full = {"scope": "same G19 targets/changes: FTIR + NMR + CCK8 axis.title +1pt; "
                     "CCK8 before(full original wrapper)/after(pure wrapper) under same G20 verifier",
            "rounds_per_sample": args.rounds,
            "export_accounting": "measured fs.export/savefig counts per rebuild; pure expected 0/0",
            "samples": samples}
    (outroot / "g20_timing.json").write_text(json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8")
    sanitized = {"scope": full["scope"], "rounds_per_sample": args.rounds,
                 "export_accounting": full["export_accounting"],
                 "samples": {k: _sanitize(v) for k, v in samples.items()}}
    Path(args.sanitized_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.sanitized_out).write_text(json.dumps(sanitized, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: {"summary": v["summary"], "round_statuses": v["round_statuses"],
                          "local_edit_state": v["local_edit_state"],
                          "figure_verification_state": v["figure_verification_state"],
                          "source_commit_state": v["source_commit_state"]}
                      for k, v in sanitized["samples"].items()}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
