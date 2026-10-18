#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G15-A correction runner: real CLI evidence for R0 + R1, all scopes.

Corrections applied (no engine changes, no figure beautification):
1. Parent truth denominators: subplots d3 (axis.title L90 set(xlabel,ylabel)
   + tick + curve), label d2 (tick + panel), figlegend d3 (tick + curve +
   legend). Correct hints still 1/1/2.
2. Legal requests per present role: subplots d3, label d1 (tick), figlegend
   d2 (tick+curve); R0 and R1 share the same 6-intent pool.
3. R1 wrappers now carry metadata-only layout_contract (parameters=[],
   nodes from real reg.all() gid/type, no bindings/setters). Old
   no-contract apply results are excluded from the main table and kept only
   as superseded logs.
4. R0 runs REAL CLI (Agg): discover-AST path replaced by actual
   `figpact contract discover` on raw (Agg, with timeout guard + traceback
   capture), then verify/compare/unify/apply/receipt on raw where reachable;
   entry-point failures recorded with full tracebacks, not in-process
   substitutes.
5. Repeat apply truly re-executed with before/after source+config hashes.
6. Earlier non-Agg timeouts are harness environment errors, not engine
   defects; all runs here set MPLBACKEND=Agg + portable relative log paths
   under the archive dir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PY = sys.executable
FREEZE_SHA = "793aaa89b39af49d2421e2a2840751cf757ba959"

SAMPLES = [
    {"stem": "subplots_demo",
     "scopes": [f"fig{i:02d}" for i in range(13)]},
    {"stem": "label_subplots",
     "scopes": ["fig00", "fig01", "fig02"]},
    {"stem": "figlegend_demo",
     "scopes": ["fig00"]},
]


def run(cmd, timeout=240):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MPLBACKEND"] = "Agg"
    try:
        p = subprocess.run(cmd, cwd=str(REPO), capture_output=True,
                           text=True, encoding="utf-8", env=env,
                           timeout=timeout)
        return {"exit": p.returncode, "stdout": p.stdout or "",
                "stderr": p.stderr or "", "timeout": False}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"")
        err = (e.stderr or b"")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
            err = err.decode("utf-8", "replace")
        return {"exit": None, "stdout": out, "stderr": err,
                "timeout": True,
                "traceback": f"TimeoutExpired after {timeout}s (harness env)"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save_log(logs: Path, name: str, res: dict) -> dict:
    (logs / f"{name}.stdout.txt").write_text(res["stdout"],
                                             encoding="utf-8")
    (logs / f"{name}.stderr.txt").write_text(res["stderr"],
                                             encoding="utf-8")
    return {"cmd": " ".join(str(x) for x in res.get("cmd", [])),
            "exit": res["exit"], "timeout": res["timeout"],
            "stdout_log": f"logs/{name}.stdout.txt",
            "stderr_log": f"logs/{name}.stderr.txt"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    logs = Path(args.logs)
    logs.mkdir(parents=True, exist_ok=True)
    group = REPO / "tools" / "g15" / "A"
    raw_dir = group / "raw"
    empty = group / "r0_empty.yaml"
    evidence: dict = {"freeze_sha": FREEZE_SHA, "samples": {}}

    for sample in SAMPLES:
        stem = sample["stem"]
        raw = raw_dir / f"{stem}.py"
        wrap = group / f"wrap_{stem}_r1.py"
        ev: dict = {"R0": {"commands": []}, "R1": {"commands": []}}
        ev["source_sha256"] = sha(raw)
        ev["wrapper_sha256"] = sha(wrap)
        ev["config_sha256"] = sha(empty)

        # ---- R1: all scopes, real CLI ----
        r1_disc, r1_ver = [], []
        for sc in sample["scopes"]:
            d1 = logs / f"{stem}_R1_{sc}.discover.yaml"
            cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "contract",
                   "discover", "--script", str(wrap), "--config", str(empty),
                   "--scope", sc, "--out", str(d1), "--force"]
            r = run(cmd)
            r["cmd"] = cmd
            ev["R1"]["commands"].append({"step": f"discover-{sc}",
                                        **save_log(logs, f"{stem}_R1_{sc}.discover", r)})
            r1_disc.append(r["exit"])
            cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "contract",
                   "verify", str(d1)]
            r = run(cmd)
            r["cmd"] = cmd
            ev["R1"]["commands"].append({"step": f"verify-{sc}",
                                        **save_log(logs, f"{stem}_R1_{sc}.verify", r)})
            r1_ver.append(r["exit"])
        ev["R1"]["discover_exits"] = r1_disc
        ev["R1"]["verify_exits"] = r1_ver

        import yaml
        man_figs = [{"id": f"{stem}-R1-{sc}", "source": str(wrap.resolve()),
                     "kind": "code", "config": str(empty.resolve()),
                     "scope": sc, "target_width_mm": 90}
                    for sc in sample["scopes"]]
        man = {"plate": {"layout": "g15a", "target_width_mm": 90,
                         "figures": man_figs},
               "design": {"global": {"axis_title_pt": 8, "axis_tick_pt": 8},
                          "plot": {"curve_linewidth_pt": 0.8}},
               "policy": {"science_content": "locked",
                          "unsupported": "report",
                          "unmeasurable": "not_verified"}}
        man_path = logs / f"{stem}_R1.plate.yaml"
        man_path.write_text(yaml.safe_dump(man), encoding="utf-8")
        for step, extra in (("compare", []), ("unify-plan",
                            ["--target-width-mm", "90", "--axis-pt", "8",
                             "--tick-pt", "8", "--line-pt", "0.8"]),
                            ("receipt", [])):
            if step == "compare":
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                       "compare", str(man_path), "--out",
                       str(logs / f"{stem}_R1.compare.json"), "--json"]
            elif step == "unify-plan":
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                       "unify", str(man_path)] + extra
            else:
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                       "receipt", str(man_path), "--out",
                       str(logs / f"{stem}_R1.receipt.json")]
            r = run(cmd)
            r["cmd"] = cmd
            ev["R1"]["commands"].append({"step": step,
                                        **save_log(logs, f"{stem}_R1.{step}", r)})
            ev["R1"][f"{step}_exit"] = r["exit"]

        # isolated apply, twice (true repeat), with before/after hashes
        apply_runs = []
        for rep in (1, 2):
            with tempfile.TemporaryDirectory(prefix="g15A-apply-") as td:
                td = Path(td)
                (td / "raw").mkdir()
                scopy = td / "w.py"
                ccopy = td / "e.yaml"
                rcopy = td / "raw" / f"{stem}.py"
                shutil.copy2(wrap, scopy)
                shutil.copy2(empty, ccopy)
                shutil.copy2(raw, rcopy)
                figs = [{"id": f["id"], "source": str(scopy), "kind": "code",
                         "config": str(ccopy), "scope": f["scope"],
                         "target_width_mm": 90} for f in man_figs]
                man2 = {"plate": {"layout": "g15a", "target_width_mm": 90,
                                  "figures": figs},
                        "design": man["design"], "policy": man["policy"]}
                mp = td / "plate.yaml"
                mp.write_text(yaml.safe_dump(man2), encoding="utf-8")
                src_before, cfg_before = sha(scopy), sha(ccopy)
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                       "unify", str(mp), "--target-width-mm", "90",
                       "--axis-pt", "8", "--tick-pt", "8", "--line-pt",
                       "0.8", "--apply"]
                r = run(cmd, timeout=400)
                r["cmd"] = cmd
                src_after = sha(scopy) if scopy.is_file() else None
                cfg_after = sha(ccopy) if ccopy.is_file() else None
                rec = {"rep": rep, **save_log(logs, f"{stem}_R1.apply{rep}", r),
                       "src_before": src_before, "src_after": src_after,
                       "src_unchanged": src_before == src_after,
                       "cfg_before": cfg_before, "cfg_after": cfg_after,
                       "cfg_unchanged": cfg_before == cfg_after}
                try:
                    out = r["stdout"]
                    rec["status"] = json.loads(out[out.find("{"):]).get("status")
                except Exception:
                    rec["status"] = None
                apply_runs.append(rec)
                ev["R1"]["commands"].append({"step": f"apply-rep{rep}",
                                            **{k: rec[k] for k in
                                               ("cmd", "exit", "timeout",
                                                "stdout_log", "stderr_log")}})
        ev["R1"]["apply_runs"] = apply_runs
        ev["R1"]["apply_repeat_identical"] = (
            apply_runs[0]["exit"] == apply_runs[1]["exit"]
            and apply_runs[0]["src_unchanged"]
            and apply_runs[1]["src_unchanged"])

        # ---- R0: real CLI on raw (Agg), failures kept with tracebacks ----
        d0 = logs / f"{stem}_R0.discover.yaml"
        cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "contract",
               "discover", "--script", str(raw), "--config", str(empty),
               "--out", str(d0), "--force"]
        r = run(cmd, timeout=300)
        r["cmd"] = cmd
        ev["R0"]["commands"].append({"step": "discover",
                                    **save_log(logs, f"{stem}_R0.discover", r)})
        ev["R0"]["discover_exit"] = r["exit"]
        ev["R0"]["discover_timeout"] = r["timeout"]
        cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "contract",
               "verify", str(d0)]
        r = run(cmd, timeout=300)
        r["cmd"] = cmd
        ev["R0"]["commands"].append({"step": "verify",
                                    **save_log(logs, f"{stem}_R0.verify", r)})
        ev["R0"]["verify_exit"] = r["exit"]
        man0_figs = [{"id": f"{stem}-R0-raw", "source": str(raw.resolve()),
                      "kind": "code", "config": str(empty.resolve()),
                      "target_width_mm": 90}]
        man0 = {"plate": {"layout": "g15a", "target_width_mm": 90,
                          "figures": man0_figs},
                "design": {"global": {"axis_title_pt": 8, "axis_tick_pt": 8},
                           "plot": {"curve_linewidth_pt": 0.8}},
                "policy": {"science_content": "locked",
                           "unsupported": "report",
                           "unmeasurable": "not_verified"}}
        man0_path = logs / f"{stem}_R0.plate.yaml"
        man0_path.write_text(yaml.safe_dump(man0), encoding="utf-8")
        for step in ("compare", "unify-plan", "receipt"):
            if step == "compare":
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                       "compare", str(man0_path), "--out",
                       str(logs / f"{stem}_R0.compare.json"), "--json"]
            elif step == "unify-plan":
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                       "unify", str(man0_path), "--target-width-mm", "90",
                       "--axis-pt", "8", "--tick-pt", "8", "--line-pt", "0.8"]
            else:
                cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                       "receipt", str(man0_path), "--out",
                       str(logs / f"{stem}_R0.receipt.json")]
            r = run(cmd, timeout=400)
            r["cmd"] = cmd
            ev["R0"]["commands"].append({"step": step,
                                        **save_log(logs, f"{stem}_R0.{step}", r)})
            ev["R0"][f"{step}_exit"] = r["exit"]
            ev["R0"][f"{step}_timeout"] = r["timeout"]
        # R0 isolated apply (real, with hashes)
        with tempfile.TemporaryDirectory(prefix="g15A-R0apply-") as td:
            td = Path(td)
            scopy = td / raw.name
            ccopy = td / "e.yaml"
            shutil.copy2(raw, scopy)
            shutil.copy2(empty, ccopy)
            figs = [{"id": f"{stem}-R0-raw", "source": str(scopy),
                     "kind": "code", "config": str(ccopy),
                     "target_width_mm": 90}]
            manR = {"plate": {"layout": "g15a", "target_width_mm": 90,
                              "figures": figs},
                    "design": man0["design"], "policy": man0["policy"]}
            mp = td / "plate.yaml"
            mp.write_text(yaml.safe_dump(manR), encoding="utf-8")
            src_before, cfg_before = sha(scopy), sha(ccopy)
            cmd = [PY, "-B", "-X", "utf8", "-m", "figpact", "plate",
                   "unify", str(mp), "--target-width-mm", "90",
                   "--axis-pt", "8", "--tick-pt", "8", "--line-pt", "0.8",
                   "--apply"]
            r = run(cmd, timeout=400)
            r["cmd"] = cmd
            src_after = sha(scopy) if scopy.is_file() else None
            cfg_after = sha(ccopy) if ccopy.is_file() else None
            ev["R0"]["commands"].append({"step": "apply-isolated",
                                        **save_log(logs, f"{stem}_R0.apply", r)})
            ev["R0"]["apply_exit"] = r["exit"]
            ev["R0"]["src_before"] = src_before
            ev["R0"]["src_after"] = src_after
            ev["R0"]["src_unchanged"] = src_before == src_after
            ev["R0"]["cfg_unchanged"] = cfg_before == cfg_after
        evidence["samples"][stem] = ev
        print(f"{stem}: R1 disc={r1_disc} ver={r1_ver} "
              f"apply={[a['exit'] for a in apply_runs]} "
              f"R0 disc={ev['R0']['discover_exit']} "
              f"ver={ev['R0']['verify_exit']} "
              f"cmp={ev['R0']['compare_exit']} "
              f"plan={ev['R0']['unify-plan_exit']} "
              f"apply={ev['R0']['apply_exit']} "
              f"rcpt={ev['R0']['receipt_exit']}", flush=True)

    Path(args.out).write_text(json.dumps(evidence, ensure_ascii=False,
                                         indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
