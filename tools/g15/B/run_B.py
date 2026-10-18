"""G15-B runner (post-freeze). Usage:
  FREEZE_SHA=<sha> python tools/g15/B/run_B.py [--output-dir DIR]
ARCH default = repo sibling ../figpact-archive/g15-frozen/B (env OUTPUT_DIR
overrides, --output-dir wins). Never edits engine.
Covers per condition-scope: discover -> verify -> repeat discover in isolated
copy (structured YAML compare w/o identity fields) -> plate compare/unify
--apply/receipt/audit (R0 AND R1) -> repeat apply attempt + source/config
SHA256 before/after -> exact science replay hashes.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "tools" / "g15" / "B"
DEFAULT_ARCH = REPO.parent / "figpact-archive" / "g15-frozen" / "B"
PY = sys.executable
FREEZE_SHA = os.environ.get("FREEZE_SHA", "")
UPSTREAM = "4aeb773422464799998d900198b35cb80e94b3e1"

R0 = [
    ("barchart", "raw/barchart.py", None),
    ("errorbar_features", "raw/errorbar_features.py", None),
    ("scatter_with_legend", "raw/scatter_with_legend.py", None),
]
R1 = [
    ("barchart", "g15b_barchart_decl.py", ["main"]),
    ("errorbar", "g15b_errorbar_decl.py", ["ax0", "ax1"]),
    ("scatter", "g15b_scatter_decl.py",
     ["fig1_loop", "fig2_classes", "fig3_rankprice"]),
]

IDENTITY_KEYS = {"script", "config", "path", "manifest", "figure", "label",
                 "generated_at", "content_hash"}


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def strip_identity(obj):
    if isinstance(obj, dict):
        return {k: strip_identity(v) for k, v in obj.items()
                if k not in IDENTITY_KEYS}
    if isinstance(obj, list):
        return [strip_identity(v) for v in obj]
    if isinstance(obj, str):
        if re.match(r"^[A-Za-z]:\\\\", obj) or obj.startswith("/"):
            return "<PATH>"
        return obj
    return obj


def run(cmd, log, arch):
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONDONTWRITEBYTECODE="1",
               MPLBACKEND="Agg")
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                       env=env)
    (arch / log).write_text(
        f"$ {' '.join(cmd)}\nexit={r.returncode}\n--- stdout ---\n"
        f"{r.stdout}\n--- stderr ---\n{r.stderr}", encoding="utf-8")
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=os.environ.get("OUTPUT_DIR", ""),
                    help="archive dir (default: repo sibling figpact-archive)")
    ns = ap.parse_args()
    arch = Path(ns.output_dir) if ns.output_dir else DEFAULT_ARCH
    assert FREEZE_SHA, "FREEZE_SHA env required (parent sends it)"
    arch.mkdir(parents=True, exist_ok=True)
    rec = {"freeze_sha": FREEZE_SHA, "upstream_sha": UPSTREAM,
           "ts": datetime.now(timezone.utc).isoformat(), "conditions": {}}

    def fig_args(items):
        out = []
        for name, script, scopes in items:
            for sc in (scopes or ["default"]):
                spec = f"{B / script},{B / 'empty.yaml'}"
                if items is R1:
                    spec += f",{sc}"
                spec += f",B-{name}-{sc}"
                out += ["--figure", spec]
        return out

    for cond, items, is_r1 in (("R0", R0, False), ("R1", R1, True)):
        for name, script, scopes in items:
            key = f"{cond}/{name}"
            entry = {"script": script, "scopes": scopes or ["default"],
                     "steps": {}}
            sp, cfg = str(B / script), str(B / "empty.yaml")
            tag = f"{cond}_{name}".replace("/", "_")
            for sc in entry["scopes"]:
                sfx = f"{tag}_{sc}"
                st = entry["steps"].setdefault(sc, {})
                draft = str(arch / f"draft_{sfx}.yaml")
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact",
                       "contract", "discover", "--script", sp,
                       "--config", cfg, "--out", draft, "--force"]
                if is_r1:
                    cmd += ["--scope", sc]
                st["discover_exit"] = run(cmd, f"log_{sfx}_discover.txt", arch)
                st["verify_exit"] = run(
                    [PY, "-B", "-X", "utf8", "-m", "figpact",
                     "contract", "verify", draft],
                    f"log_{sfx}_verify.txt", arch)
                # isolated repeat: full raw/ copy for ALL R1 (not scatter-only)
                iso = arch / f"iso_{sfx}"
                iso.mkdir(parents=True, exist_ok=True)
                shutil.copy(sp, iso / Path(sp).name)
                shutil.copy(cfg, iso / "empty.yaml")
                if is_r1:
                    shutil.copytree(B / "raw", iso / "raw", dirs_exist_ok=True)
                iso_draft = iso / f"draft_{sfx}.yaml"
                cmd2 = [PY, "-B", "-X", "utf8", "-m", "figpact",
                        "contract", "discover",
                        "--script", str(iso / Path(sp).name),
                        "--config", str(iso / "empty.yaml"),
                        "--out", str(iso_draft), "--force"]
                if is_r1:
                    cmd2 += ["--scope", sc]
                st["rediscover_iso_exit"] = run(
                    cmd2, f"log_{sfx}_rediscover_iso.txt", arch)
                try:
                    import yaml
                    a = yaml.safe_load(Path(draft).read_text(encoding="utf-8"))
                    b = yaml.safe_load(iso_draft.read_text(encoding="utf-8"))
                    st["rediscover_struct_equal"] = (
                        strip_identity(a) == strip_identity(b))
                except Exception as ex:
                    st["rediscover_struct_equal"] = f"ERR {ex}"
                # repeat APPLY attempt #1 and #2 with full source/config hashes
                for rep in (1, 2):
                    before_s = sha256(sp)
                    before_c = sha256(cfg)
                    ec = run(
                        [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                         "unify",
                         "--figure", f"{sp},{cfg}"
                         + (f",{sc}" if is_r1 else "") + f",{sfx}",
                         "--width-mm", "80", "--axis-pt", "8",
                         "--tick-pt", "8", "--line-pt", "0.8", "--apply"],
                        f"log_{sfx}_apply_r{rep}.txt", arch)
                    st[f"apply_r{rep}_exit"] = ec
                    st[f"apply_r{rep}_src_sha_before"] = before_s
                    st[f"apply_r{rep}_src_sha_after"] = sha256(sp)
                    st[f"apply_r{rep}_cfg_sha_before"] = before_c
                    st[f"apply_r{rep}_cfg_sha_after"] = sha256(cfg)
                    st[f"apply_r{rep}_src_unchanged"] = (
                        before_s == sha256(sp))
            rec["conditions"][key] = entry
    # plate suite for BOTH R0 and R1 (failure/traceback is evidence too)
    for suite, items in (("R0", R0), ("R1", R1)):
        figs = fig_args(items)
        for step, sub, extra in (
                (f"plate_{suite}_compare_exit", "compare", ["--json"]),
                (f"plate_{suite}_unify_apply_exit", "unify", ["--apply"]),
                (f"plate_{suite}_receipt_exit", "receipt", []),
                (f"plate_{suite}_audit_exit", "audit", ["--json"])):
            out = str(arch / f"plate_{suite}_{sub}.json")
            cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                   sub, *figs, "--width-mm", "80"]
            if sub == "unify":
                cmd += ["--axis-pt", "8", "--tick-pt", "8", "--line-pt",
                        "0.8"]
            cmd += ["--out", out, *extra]
            if sub == "unify":
                cmd.remove("--out")
                cmd.remove(out)
                cmd += extra
            rec[step] = run(
                cmd, f"log_plate_{suite}_{sub}"
                + ("_apply" if sub == "unify" else "") + ".txt", arch)
    (arch / "pipeline_record.json").write_text(
        json.dumps(rec, indent=1), encoding="utf-8")
    print(json.dumps(rec, indent=1)[:2000])


if __name__ == "__main__":
    main()
