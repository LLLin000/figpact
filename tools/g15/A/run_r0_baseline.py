#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G15-A R0 baseline renderer (pre-run artifact, no figpact calls).

Runs the byte-identical upstream gallery source via runpy under Agg,
saves every Figure the source creates (stable scope ids), records exact
Line2D scientific geometry (x/y data hashes + endpoints) and view state
(shared-axis relations, titles, labels, legends), and stores bulky PNGs
outside the tracked tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _geom_of_line(line):
    x = np.asarray(line.get_xdata(), dtype=float)
    y = np.asarray(line.get_ydata(), dtype=float)
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(x).tobytes())
    h.update(np.ascontiguousarray(y).tobytes())
    return {
        "n": int(x.size),
        "x_first": float(x[0]) if x.size else None,
        "x_last": float(x[-1]) if x.size else None,
        "y_first": float(y[0]) if y.size else None,
        "y_last": float(y[-1]) if y.size else None,
        "sha256_xy": h.hexdigest(),
        "linewidth": float(line.get_linewidth()),
        "marker": str(line.get_marker()),
        "label": str(line.get_label()),
    }


def _dump_raw(source: Path, out_root: Path, tag: str) -> dict:
    plt.close("all")
    runpy.run_path(str(source), run_name="__main__")
    fignums = list(plt.get_fignums())
    scopes = []
    for i, num in enumerate(fignums):
        fig = plt.figure(num)
        fig.draw_without_rendering()
        scope_id = f"{source.stem}#fig{i:02d}"
        png = out_root / f"R0_{tag}_{source.stem}_fig{i:02d}.png"
        fig.savefig(png, dpi=150)
        axes_info = []
        for k, ax in enumerate(fig.axes):
            axes_info.append({
                "index": k,
                "title": ax.get_title(),
                "left_title": ax._left_title.get_text(),
                "right_title": ax._right_title.get_text(),
                "xlabel": ax.get_xlabel(),
                "ylabel": ax.get_ylabel(),
                "shared_x": ax._sharex is not None,
                "shared_y": ax._sharey is not None,
                "projection": ax.name,
                "n_lines": len(ax.lines),
                "n_texts": len(ax.texts),
                "n_xticklabels": len(ax.get_xticklabels()),
                "lines": [_geom_of_line(ln) for ln in ax.lines],
                "texts": [
                    {"text": t.get_text(), "fontsize": float(t.get_fontsize()),
                     "position": [float(v) for v in t.get_position()]}
                    for t in list(ax.texts)
                ],
                "annotations": [
                    {"text": c.get_text(), "fontsize": float(c.get_fontsize())}
                    for c in ax.get_children()
                    if type(c).__name__ == "Annotation"
                ],
            })
        scopes.append({
            "scope": scope_id,
            "png": png.name,
            "png_sha256": _sha256_file(png),
            "n_axes": len(fig.axes),
            "suptitle": fig._suptitle.get_text() if fig._suptitle else None,
            "n_fig_legends": len(fig.legends),
            "fig_legend_texts": [
                [t.get_text() for t in leg.get_texts()] for leg in fig.legends
            ],
            "axes": axes_info,
        })
    plt.close("all")
    return {"source": source.name, "n_figs": len(fignums), "scopes": scopes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args(argv)
    raw_dir = Path(args.raw_dir)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    samples = ["subplots_demo", "label_subplots", "figlegend_demo"]
    manifest = {"condition": "R0", "backend": "Agg", "samples": []}
    for stem in samples:
        src = raw_dir / f"{stem}.py"
        truth = _dump_raw(src, out_root, "raw")
        truth["source_sha256"] = _sha256_file(src)
        truth["source_bytes"] = int(src.stat().st_size)
        manifest["samples"].append(truth)
    Path(args.manifest).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(
        {s["source"]: s["n_figs"] for s in manifest["samples"]},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
