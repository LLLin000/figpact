#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G15-A R1 wrapper: subplots_demo (13 figures, shared axes + curves).

R1 rule: frozen upstream bytes (tools/g15/A/raw/subplots_demo.py) executed
unmodified via runpy. This file only appends protocol hooks: stable SCOPES
(one per Figure the raw source creates), generic config load, figure build
+ extant-artist registry enumeration. No cfg rewiring, no post-build
fontsize/linewidth setters, no per-sample role mappings, no edits to the
original plotting statements.
"""
from __future__ import annotations

import argparse
import copy
import json
import runpy
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from figpact import GidRegistry  # noqa: E402

RAW = Path(__file__).parent / "raw" / "subplots_demo.py"
FIGURE_ID = "g15a-subplots-demo"
N_FIGS = 13
SCOPES = tuple(f"fig{i:02d}" for i in range(N_FIGS))
CONFIG: dict = {}
SCHEMA: dict = {}
CLI_ARGS = None


def _load_config(path=None):
    if path is None:
        return copy.deepcopy(CONFIG)
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config top level must be a mapping")
    return data


load_config = _load_config


def load_science():
    return {}


def _run_raw():
    plt.close("all")
    runpy.run_path(str(RAW), run_name="__mp_main__")
    return [plt.figure(n) for n in plt.get_fignums()]


def build_figure_and_registry(scope: str = "fig00", config=None):
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; declared {list(SCOPES)}")
    idx = int(scope[3:])
    figs = _run_raw()
    try:
        if not (0 <= idx < len(figs)):
            raise ValueError(f"scope {scope} out of range (raw made {len(figs)} figs)")
        fig = figs[idx]
        reg = GidRegistry(scope=scope)
        for ai, ax in enumerate(fig.axes):
            for li, ln in enumerate(ax.lines):
                reg.register(ln, f"{FIGURE_ID}.{scope}.ax{ai}.curve{li}",
                             params=[], parent=None, editable=False,
                             science_policy="LOCKED_SCIENCE")
            # extant text artists enumerated, no params fabricated
            for ti, t in enumerate(list(ax.texts)):
                reg.register(t, f"{FIGURE_ID}.{scope}.ax{ai}.text{ti}",
                             params=[], parent=None, editable=False,
                             science_policy=None)
        for li, leg in enumerate(fig.legends):
            try:
                reg.register(leg, f"{FIGURE_ID}.{scope}.legend{li}",
                             params=[], parent=None, editable=False,
                             science_policy=None)
            except ValueError:
                pass
        for other in figs[:idx] + figs[idx + 1:]:
            plt.close(other)
        return fig, reg
    except Exception:
        for f in figs:
            try:
                plt.close(f)
            except Exception:
                pass
        raise


def layout_contract(scope: str = "fig00"):
    """Metadata-only protocol declaration (no bindings, no setters).

    parameters=[] (nothing EDITABLE: literal raw calls have no YAML source
    binding); nodes enumerates the REAL gids/types from a true
    build_figure_and_registry(scope) run (closed immediately, no caching).
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; declared {list(SCOPES)}")
    fig, reg = build_figure_and_registry(scope)
    try:
        nodes = {}
        for gid, art in reg.all().items():
            meta = reg.meta_of(gid)
            pol = meta.get("science_policy") or "LAYOUT"
            if pol not in ("LAYOUT", "LOCKED_SCIENCE"):
                pol = "LAYOUT"
            nodes[gid] = {"type": type(art).__name__, "parent": None,
                          "editable": False, "science_policy": pol}
        return {"parameters": [], "nodes": nodes, "groups": [], "relations": [],
                "outputs": []}
    finally:
        plt.close(fig)


def _cli(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--list-params", action="store_true")
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--check-effect", action="store_true")
    ap.add_argument("--inspect", default=None)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--scope", default=None)
    ap.add_argument("--probe", default=None)
    return ap.parse_args(argv)


ARGS = _cli(sys.argv[1:]) if __name__ == "__main__" else _cli([])


def _inventory(scope: str):
    fig, reg = build_figure_and_registry(scope)
    try:
        items = [{"gid": g, "type": type(a).__name__,
                  "summary": f"{type(a).__name__}",
                  "params": reg.params_of(g)} for g, a in reg.all().items()]
        return {"items": items, "unregistered": [], "unbound": list(reg.all()),
                "scopes": {s: {} for s in SCOPES}, "scope": scope}
    finally:
        plt.close(fig)


if __name__ == "__main__":
    if ARGS.list_params:
        print(json.dumps({"figure": FIGURE_ID, "scopes": list(SCOPES),
                          "params": []}, ensure_ascii=False, indent=2))
    elif ARGS.inventory:
        scope = ARGS.scope or SCOPES[0]
        print(json.dumps(_inventory(scope), ensure_ascii=False, indent=2))
    elif ARGS.inspect:
        scope = ARGS.scope or SCOPES[0]
        fig, reg = build_figure_and_registry(scope)
        art = reg.get(ARGS.inspect)
        print(json.dumps({"gid": ARGS.inspect, "found": art is not None,
                          "type": type(art).__name__ if art is not None else None},
                         ensure_ascii=False, indent=2))
        plt.close(fig)
    else:
        scope = ARGS.scope or SCOPES[0]
        fig, reg = build_figure_and_registry(scope)
        print(f"{FIGURE_ID} {scope}: {len(reg.all())} artists, "
              f"{len(fig.axes)} axes")
        plt.close(fig)
