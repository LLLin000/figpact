"""G15 stratum C runner: R0 + R1 pipeline using public CLI only.

Usage (from repo root):
  python tools/g15/C/run_c.py [--output-dir <dir>] [--r0-only] [--r1-only]

Generated evidence (logs, workdirs, PNGs) goes to the output dir
(default <repo>/../figpact-archive/g15-frozen/C when present, else D:/
absolute path); the tracked dir keeps only runner/declarations/raw fixtures/
compact truth/results. Old evidence is retained but not committed as repo logs.
Raw sources are never modified. unify --apply runs in an isolated copy dir.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
REPO = Path(__file__).resolve().parents[3]
C = REPO / "tools" / "g15" / "C"
DEFAULT_ARCH = REPO.parent / "figpact-archive" / "g15-frozen" / "C"
FREEZE_SHA = "793aaa89b39af49d2421e2a2840751cf757ba959"
UPSTREAM_SHA = "4aeb773422464799998d900198b35cb80e94b3e1"
PY = sys.executable
ENV = dict(os.environ, PYTHONPATH=str(REPO), PYTHONDONTWRITEBYTECODE="1",
           MPLBACKEND="Agg", PYTHONUTF8="1")
WIDTH = 80.0
TARGETS = {"axis_pt": 8.0, "tick_pt": 8.0, "line_pt": 0.8}
R1_SCOPES = {"eventcollection": ["main"],
             "annotation": ["fig0", "fig1", "fig2", "fig3", "fig4", "fig5"]}

OUT = None
LOGDIR = None


def run(cmd, logname, cwd=None):
    p = subprocess.run(cmd, cwd=str(cwd or REPO), capture_output=True, text=True,
                       env=ENV, timeout=600)
    LOGDIR.mkdir(parents=True, exist_ok=True)
    (LOGDIR / logname).write_text(
        f"$ {' '.join(cmd)}\nexit={p.returncode}\n--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}",
        encoding="utf-8")
    return p


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_sha(p: Path) -> str:
    return sha(p.read_bytes())


def snap_lines(fig):
    out = []
    for ax in fig.axes:
        for ln in ax.lines:
            import numpy as np
            x = np.asanyarray(ln.get_xdata())
            y = np.asanyarray(ln.get_ydata())
            h = hashlib.sha256()
            h.update(np.ascontiguousarray(x).tobytes())
            h.update(np.ascontiguousarray(y).tobytes())
            out.append({"digest": h.hexdigest()[:16], "lw": float(ln.get_linewidth()),
                        "n": int(len(x))})
    return out


def snap_colls(fig):
    import numpy as np
    out = []
    for ax in fig.axes:
        for c in ax.collections:
            segs = list(c.get_segments()) if hasattr(c, "get_segments") else []
            h = hashlib.sha256()
            for s in segs:
                h.update(np.ascontiguousarray(np.asanyarray(s)).tobytes())
            offs = np.asanyarray(c.get_offsets()) if hasattr(c, "get_offsets") else np.zeros(0)
            out.append({"kind": type(c).__name__, "nseg": len(segs),
                        "seg_digest": h.hexdigest()[:16],
                        "off_shape": list(offs.shape)})
    return out


def snap_view(fig):
    out = []
    for ax in fig.axes:
        out.append({"proj": ax.name, "title": ax.get_title(),
                    "xlabel": ax.get_xlabel(), "ylabel": ax.get_ylabel(),
                    "xlim": [float(v) for v in ax.get_xlim()],
                    "ylim": [float(v) for v in ax.get_ylim()],
                    "nlines": len(ax.lines), "ntexts": len(ax.texts),
                    "npatches": len(ax.patches),
                    "tick_fs": float(ax.get_xticklabels()[0].get_fontsize())
                    if ax.get_xticklabels() else None})
    return out


def build_module(path, scope=None):
    from figpact import final_size as fs
    mod = fs._import_script(Path(path))
    cfg = fs._load_config(mod, Path(path), C / "r1_empty.yaml")
    (fig, reg), scope = fs._build_figure(mod, cfg, scope)
    return mod, fig, reg, scope


def discover_verify(label, script, cfg, workdir, scope=None):
    """Run CLI Discover -> confirm-all -> Verify; return structured outcome."""
    out = {}
    cpath = workdir / f"{label}.contract.yaml"
    cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "contract", "discover",
           "--script", str(script), "--config", str(cfg), "--out", str(cpath)]
    if scope:
        cmd += ["--scope", scope]
    p = run(cmd, f"discover_{label}.log")
    out.update({"discover_exit": p.returncode, "draft": str(cpath) if cpath.exists() else None})
    if p.returncode != 0 or not cpath.exists():
        out.update({"verify_exit": None, "candidates": [], "verified": [],
                    "failed": [], "skipped": 0})
        return out
    import yaml
    draft = yaml.safe_load(cpath.read_text(encoding="utf-8"))
    for c in draft.get("candidates", []):
        c["confirmed"] = True
    cpath.write_text(yaml.safe_dump(draft, sort_keys=False, allow_unicode=True), encoding="utf-8")
    p2 = run([PY, "-B", "-X", "utf8", "-m", "figpact", "contract", "verify", str(cpath)],
             f"verify_{label}.log")
    draft2 = yaml.safe_load(cpath.read_text(encoding="utf-8"))
    out.update({"verify_exit": p2.returncode,
                "candidates": draft2.get("candidates", []),
                "unresolved": draft2.get("unresolved", []),
                "unsupported": draft2.get("unsupported", []),
                "coverage": draft2.get("coverage", {}),
                "verified": [c["param"] for c in draft2.get("candidates", []) if c.get("verified")],
                "failed": [c["param"] for c in draft2.get("candidates", []) if c.get("confirmed") and not c.get("verified")]})
    return out


def plate_stage(label, specs_cfg, workdir):
    """audit -> compare -> unify(plan) -> repeat unify --apply -> receipt."""
    out = {}
    manifest = {"plate": {"target_width_mm": WIDTH, "figures": specs_cfg,
                          "design": {"global": {"axis_title_pt": TARGETS["axis_pt"],
                                               "tick_label_pt": TARGETS["tick_pt"],
                                               "line_width_pt": TARGETS["line_pt"]}}}}
    import yaml
    mpath = workdir / f"{label}.plate.yaml"
    mpath.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    audit_cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate", "audit"]
    for s in specs_cfg:
        audit_cmd += ["--figure", ",".join(
            [s["source"], s.get("config") or "", s.get("scope") or "",
             s.get("id") or ""]) + f":{WIDTH}"]
    audit_cmd += ["--json"]
    p = run(audit_cmd, f"audit_{label}.log")
    out["audit_exit"] = p.returncode
    try:
        out["audit"] = json.loads(p.stdout) if p.stdout.strip() else None
    except Exception as e:
        out["audit"] = {"parse_error": f"{type(e).__name__}: {e}"}
    p = run([PY, "-B", "-X", "utf8", "-m", "figpact", "plate", "compare",
             str(mpath), "--json"], f"compare_{label}.log")
    out["compare_exit"] = p.returncode
    try:
        out["compare"] = json.loads(p.stdout) if p.stdout.strip() else None
    except Exception as e:
        out["compare"] = {"parse_error": f"{type(e).__name__}: {e}"}
    p = run([PY, "-B", "-X", "utf8", "-m", "figpact", "plate", "unify",
             str(mpath)], f"plan_{label}.log")
    out["plan_exit"] = p.returncode
    try:
        out["plan"] = json.loads(p.stdout) if p.stdout.strip() else None
    except Exception as e:
        out["plan"] = {"parse_error": f"{type(e).__name__}: {e}"}
    # isolated apply copy (declarations live in dirs with RAW-relative layout:
    # copy whole parent dir so RAW sibling resolves; --apply manifest points at copy)
    iso = workdir / f"{label}_apply_iso"
    if iso.exists():
        shutil.rmtree(iso)
    iso.mkdir(parents=True)
    iso_specs = []
    for s in specs_cfg:
        s = dict(s)
        for k in ("source", "config"):
            if s.get(k):
                src = Path(s[k])
                if src.parent.name in ("decl_ev", "decl_ann"):
                    dst_dir = iso / src.parent.name
                    shutil.copytree(src.parent, dst_dir)
                    s[k] = str(dst_dir / src.name)
                else:
                    dst = iso / src.name
                    shutil.copy2(src, dst)
                    s[k] = str(dst)
        iso_specs.append(s)
    if not (iso / "raw").exists():
        shutil.copytree(C / "raw", iso / "raw")
    imanifest = {"plate": {"target_width_mm": WIDTH, "figures": iso_specs,
                           "design": manifest["plate"]["design"]}}
    ipath = iso / f"{label}.plate.yaml"
    ipath.write_text(yaml.safe_dump(imanifest, sort_keys=False, allow_unicode=True),
                     encoding="utf-8")
    apply_hashes = {}
    for attempt in ("apply1", "apply2"):
        decl_copies = sorted(iso.glob("decl_*/g15c_*.py"))
        before = {str(d): file_sha(d) for d in decl_copies}
        p = run([PY, "-B", "-X", "utf8", "-m", "figpact", "plate", "unify",
                 str(ipath), "--apply"], f"{attempt}_{label}.log")
        after = {str(d): file_sha(d) for d in sorted(iso.glob("decl_*/g15c_*.py"))}
        apply_hashes[attempt] = {"exit": p.returncode,
                                 "source_unchanged": before == after,
                                 "before": before, "after": after}
        try:
            out[attempt] = json.loads(p.stdout) if p.stdout.strip() else None
        except Exception as e:
            out[attempt] = {"parse_error": f"{type(e).__name__}: {e}"}
    out["apply_exit"] = apply_hashes["apply2"]["exit"]
    out["apply_hashes"] = apply_hashes
    out["apply"] = out.get("apply2")
    p = run([PY, "-B", "-X", "utf8", "-m", "figpact", "plate", "receipt",
             str(mpath)], f"receipt_{label}.log")
    out["receipt_exit"] = p.returncode
    try:
        out["receipt"] = json.loads(p.stdout) if p.stdout.strip() else None
    except Exception as e:
        out["receipt"] = {"parse_error": f"{type(e).__name__}: {e}"}
    return out


def main():
    global OUT, LOGDIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--r0-only", action="store_true")
    ap.add_argument("--r1-only", action="store_true")
    args = ap.parse_args()
    OUT = Path(args.output_dir).resolve() if args.output_dir else DEFAULT_ARCH
    LOGDIR = OUT / "logs"
    do_r0 = not (args.r0_only or args.r1_only) or args.r0_only
    do_r1 = not (args.r0_only or args.r1_only) or args.r1_only
    (C / "r1_empty.yaml").write_text("{}\n", encoding="utf-8")
    LOGDIR.mkdir(parents=True, exist_ok=True)
    (OUT / "work").mkdir(parents=True, exist_ok=True)
    res = {"freeze_sha": FREEZE_SHA, "upstream_sha": UPSTREAM_SHA,
           "upstream_urls": {
               "eventcollection": "https://raw.githubusercontent.com/matplotlib/matplotlib/4aeb773422464799998d900198b35cb80e94b3e1/galleries/examples/lines_bars_and_markers/eventcollection_demo.py",
               "annotation": "https://raw.githubusercontent.com/matplotlib/matplotlib/4aeb773422464799998d900198b35cb80e94b3e1/galleries/examples/text_labels_and_annotations/annotation_demo.py"},
           "samples": []}
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    raws = {"eventcollection": C / "raw" / "eventcollection_demo.py",
            "annotation": C / "raw" / "annotation_demo.py"}
    decls = {"eventcollection": C / "decl_ev" / "g15c_ev.py",
             "annotation": C / "decl_ann" / "g15c_ann.py"}

    for key in ("eventcollection", "annotation"):
        smp = {"id": key, "source": {"path": str(raws[key]),
               "sha256": file_sha(raws[key]),
               "url": res["upstream_urls"][key]}, "conditions": {}}
        # ---- R0 ----
        if do_r0:
            r0 = {"config": "external empty YAML (no binding)"}
            r0["source_sha_before"] = file_sha(raws[key])
            work = OUT / "work" / f"r0_{key}"
            work.mkdir(parents=True, exist_ok=True)
            dv = discover_verify(f"r0_{key}", raws[key], C / "r0_empty.yaml", work)
            r0.update(dv)
            r0["source_sha_after"] = file_sha(raws[key])
            r0["source_unchanged"] = r0["source_sha_before"] == r0["source_sha_after"]
            tag = "ev" if key == "eventcollection" else "ann"
            ps = plate_stage(f"r0_{key}",
                             [{"id": tag, "source": str(raws[key]),
                               "config": str(C / "r0_empty.yaml")}], work)
            r0.update(ps)
            smp["conditions"]["R0"] = r0
        # ---- R1: every scope, full-text rerun each build ----
        if do_r1:
            r1 = {"declaration": str(decls[key]),
                  "decl_sha256": file_sha(decls[key]),
                  "scopes": list(R1_SCOPES[key])}
            r1["source_sha_before"] = file_sha(raws[key])
            scope_data = {}
            for scope in R1_SCOPES[key]:
                mod, fig, reg, rs = build_module(decls[key], scope)
                png = OUT / "png" / f"r1_{key}_{scope}_before.png"
                png.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fig.savefig(png, dpi=150)
                except Exception:
                    pass
                work = OUT / "work" / f"r1_{key}_{scope}"
                work.mkdir(parents=True, exist_ok=True)
                dv = discover_verify(f"r1_{key}_{scope}", decls[key],
                                     C / "r1_empty.yaml", work, scope=scope)
                dv.update({"scope": rs, "gids": sorted(reg.all()),
                           "n_gids": len(reg.all()),
                           "view": snap_view(fig),
                           "lines": snap_lines(fig),
                           "collections": snap_colls(fig)})
                plt.close(fig)
                # repeat build: geometry + view equality
                mod2, fig2, reg2, rs2 = build_module(decls[key], scope)
                dv["repeat"] = {"scope": rs2, "gids": sorted(reg2.all()),
                                "view_equal": snap_view(fig2) == dv["view"],
                                "lines_equal": snap_lines(fig2) == dv["lines"],
                                "coll_equal": snap_colls(fig2) == dv["collections"]}
                plt.close(fig2)
                scope_data[scope] = dv
            r1["scope_data"] = scope_data
            # plate per scope (compare/plan/repeat-apply/receipt)
            plate = {}
            for scope in R1_SCOPES[key]:
                work = OUT / "work" / f"r1p_{key}_{scope}"
                work.mkdir(parents=True, exist_ok=True)
                plate[scope] = plate_stage(f"r1_{key}_{scope}",
                                           [{"id": f"{key[:3]}_{scope}",
                                             "source": str(decls[key]),
                                             "config": str(C / "r1_empty.yaml"),
                                             "scope": scope}], work)
            r1["plate"] = plate
            r1["source_sha_after"] = file_sha(raws[key])
            r1["source_unchanged"] = r1["source_sha_before"] == r1["source_sha_after"]
            smp["conditions"]["R1"] = r1
        res["samples"].append(smp)

    (OUT / "results_raw.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"samples": len(res["samples"]), "out": str(OUT)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
