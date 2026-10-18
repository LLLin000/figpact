#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G20-B freeze probe (generic): freeze ONE path without touching its source.

argv[1] = script dir (byte-exact ORIGINAL for full, seam clone for pure).
MODE env: full | pure.

full: runpy.run_path(<script>, run_name="__main__") — the UNMODIFIED original
  __main__ (draw = inline build + fs.export + qa_report). Take data/modes from
  the run globals + plt.gcf(). report() stdout is captured live like the CLI.
  fs.export/Figure.savefig wrapped with counting DELEGATES (no suppression):
  full must show fs_export=1 / savefig=3.
pure: import seam module, build_figure_and_registry(scope='main') — construct
  only, zero export. fs_export/savefig must be 0 and no new files.
"""
from __future__ import annotations

import functools
import io
import json
import os
import runpy
import sys
from contextlib import redirect_stdout
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

scriptdir = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(scriptdir))
root = next(p for p in Path(__file__).resolve().parents if (p / "figpact").is_dir())
sys.path.insert(0, str(root))

MODE = os.environ.get("G20_PROBE_MODE", "pure")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

OUT = Path.cwd() / ("g20_full_freeze.json" if MODE == "full" else "g20_pure_freeze.json")
before_files = {p.name: p.stat().st_mtime_ns for p in Path.cwd().iterdir() if p.is_file()}

counts = {"fs_export": 0, "savefig": 0}
import figure_style as fs

_orig_export = fs.export
_orig_savefig = Figure.savefig


@functools.wraps(_orig_export)
def _count_export(fig, *a, **k):
    counts["fs_export"] += 1
    return _orig_export(fig, *a, **k)


@functools.wraps(_orig_savefig)
def _count_savefig(self, *a, **k):
    counts["savefig"] += 1
    return _orig_savefig(self, *a, **k)


fs.export = _count_export
Figure.savefig = _count_savefig

buf = io.StringIO()
plt.close("all")
old_argv, old_cwd = sys.argv, os.getcwd()
os.chdir(scriptdir)
try:
    with redirect_stdout(buf):
        if MODE == "full":
            sys.argv = ["plot_cck8_viability.py"]
            g = runpy.run_path(str(scriptdir / "plot_cck8_viability.py"),
                               run_name="__main__")
            data, modes = g["data"], g["modes"]
            reg_scope, reg_gids = "main", []
            figs = [plt.figure(n) for n in plt.get_fignums()]
            fig = figs[-1]
            for extra in figs[:-1]:
                plt.close(extra)
        else:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "g20_clone_plot", str(scriptdir / "plot_cck8_viability.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fig, reg = mod.build_figure_and_registry(scope="main")
            data, modes, _tp, _out, _labels = mod._prepare([])
            reg_scope, reg_gids = reg.scope, sorted(reg.gids())
except Exception as exc:  # honest failure freeze, never fake PASS
    OUT.write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}",
                               "counts": counts}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    raise
finally:
    sys.argv = old_argv
    os.chdir(old_cwd)
    fs.export = _orig_export
    Figure.savefig = _orig_savefig

stdout = buf.getvalue()
rep_start = stdout.find("CCK-8")
tail_marker = "统计要素"
tail_at = stdout.find(tail_marker, rep_start)
if rep_start >= 0 and tail_at >= 0:
    tail_end = stdout.find("\n", tail_at)
    report_block = stdout[rep_start:tail_end].strip()
elif rep_start >= 0:
    report_block = stdout[rep_start:].strip()
else:
    report_block = ""

science = {}
for d in data:
    if d is None:
        continue
    per = {}
    for gcol, vals in d["viability"].items():
        per[gcol] = {"n": int(d["n"][gcol]), "mean": float(vals.mean()),
                     "sd": float(vals.std(ddof=1)),
                     "values": [float(v) for v in vals]}
    science[d["sheet"]] = {"n": {k: int(v) for k, v in d["n"].items()},
                           "groups": per, "anova_p": float(d["anova_p"]),
                           "p_vs_ctrl": {k: float(v) for k, v in d["p_vs_ctrl"].items()},
                           "dropped": {k: [[int(i), float(v)] for i, v in lst]
                                       for k, lst in d["dropped"].items()}}

fig.canvas.draw()
renderer = fig.canvas.get_renderer()
artists, styles = [], {}
for axi, ax in enumerate(fig.axes):
    for b in list(ax.patches)[:40]:
        bb = b.get_window_extent(renderer)
        artists.append({"kind": "bar", "x": round(float(b.get_x()), 9),
                        "h": round(float(b.get_height()), 9),
                        "w": round(float(b.get_width()), 9),
                        "fc": str(b.get_facecolor()),
                        "bbox": [round(v, 3) for v in bb.bounds]})
    for t in list(ax.texts):
        bb = t.get_window_extent(renderer)
        artists.append({"kind": "text", "s": t.get_text(),
                        "fontsize": float(t.get_fontsize()),
                        "bbox": [round(v, 3) for v in bb.bounds]})
    styles[f"axes{axi}"] = {"xlim": [float(v) for v in ax.get_xlim()],
                            "ylim": [float(v) for v in ax.get_ylim()]}
ax0 = fig.axes[0]
leg = ax0.get_legend()
view = {"xlim": [float(v) for v in ax0.get_xlim()],
        "ylim": [float(v) for v in ax0.get_ylim()],
        "xticks": [float(v) for v in ax0.get_xticks()],
        "xticklabels": [t.get_text() for t in ax0.get_xticklabels()],
        "xlabel": ax0.get_xlabel(), "ylabel": ax0.get_ylabel(),
        "legend": ([t.get_text() for t in leg.get_texts()] if leg is not None else None)}
ownership = {"figure_type": type(fig).__name__,
             "is_figure": isinstance(fig, Figure),
             "n_axes": len(fig.axes),
             "axes_types": [type(a).__name__ for a in fig.axes],
             "registry_scope": reg_scope, "registry_gids": reg_gids}

after_files = {p.name: p.stat().st_mtime_ns for p in Path.cwd().iterdir() if p.is_file()}
new_files = sorted(n for n, m in after_files.items()
                   if (n not in before_files or before_files[n] != m)
                   and not n.startswith("g20_"))

OUT.write_text(json.dumps({
    "mode": MODE, "scope": "main", "science": science,
    "report_block": report_block,
    "figure": {"size_in": [float(v) for v in fig.get_size_inches()],
               "dpi": float(fig.get_dpi()), "n_axes": len(fig.axes)},
    "artists": artists, "styles": styles, "view": view,
    "ownership": ownership, "counts": counts, "new_files": new_files,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[probe:{MODE}] artists={len(artists)} export={counts['fs_export']} "
      f"savefig={counts['savefig']} new={new_files}")
