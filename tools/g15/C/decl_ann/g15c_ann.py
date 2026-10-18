"""R1 wrapper-only declaration for annotation_demo (FROZEN SOURCE, NO EDITS).

Protocol-compliant form: one scope per raw figure (SCOPES fig0..fig5).
Every build reruns the FULL immutable raw text in order via runpy (seeds,
shared state, cross-figure references preserved), then selects the scope's
figure and registers ONLY that figure's real artists. Nodes derive from the
real registry of the returned figure only; parameters stay [] (no fabricated
bindings, no post-build setters, no per-sample role mappings). Ordinary
Annotation artists are NOT panel.label truth.
"""
import hashlib
import runpy
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from figpact import GidRegistry  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "raw" / "annotation_demo.py"
RAW_SHA256 = "1073f84b8efa3147271c5171017530f4f190b2ae5f73ece7af1e186d1e0d1d90"
FIGURE_ID = "g15c_ann"
SCOPES = ("fig0", "fig1", "fig2", "fig3", "fig4", "fig5")

__all__ = ["load_science", "build_scene", "build_figure_and_registry",
           "layout_contract", "science_manifest", "science_inputs",
           "SCOPES", "RAW_SHA256"]


def _check_bytes():
    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    if digest != RAW_SHA256:
        raise RuntimeError(f"upstream bytes changed: {digest}")


def load_science():
    import numpy as np
    _check_bytes()
    t = np.arange(0.0, 5.0, 0.01)
    r = np.arange(0, 1, 0.001)
    return {"t": t, "s": np.cos(2 * np.pi * t),
            "r": r, "theta": 2 * 2 * np.pi * r}


def science_inputs():
    return []


def _run_raw():
    _check_bytes()
    plt.close("all")
    import unittest.mock as _mock
    with _mock.patch.object(plt, "show", lambda *a, **k: None):
        runpy.run_path(str(RAW), run_name="__mp_main__")
    figs = [plt.figure(n) for n in plt.get_fignums()]
    if len(figs) != len(SCOPES):
        raise RuntimeError(f"expected {len(SCOPES)} figures, got {len(figs)}")
    return figs


def _gid(scope, axidx, kind, idx):
    return f"{FIGURE_ID}.{scope}.ax{axidx}.{kind}.{idx}"


def build_scene(science, config, scope):
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    figs = _run_raw()
    fig = figs[SCOPES.index(scope)]
    reg = GidRegistry(scope=scope)
    for ai, ax in enumerate(fig.axes):
        for i, ln in enumerate(ax.lines):
            reg.register(ln, _gid(scope, ai, "curve", i), params=[],
                         controlled_by=[], science_policy="LOCKED_SCIENCE",
                         artist_type="curve", scope=scope)
        for i, tx in enumerate([ax.xaxis.label, ax.yaxis.label, ax.title,
                                *ax.texts]):
            try:
                if not tx.get_text():
                    continue
            except Exception:
                continue
            reg.register(tx, _gid(scope, ai, "text", i), params=[],
                         controlled_by=[], science_policy="LOCKED_SCIENCE",
                         artist_type="text", scope=scope)
        for i, p in enumerate(ax.patches):
            reg.register(p, _gid(scope, ai, "patch", i), params=[],
                         controlled_by=[], science_policy="LOCKED_SCIENCE",
                         artist_type="patch", scope=scope)
        for i, c in enumerate(ax.collections):
            reg.register(c, _gid(scope, ai, "collection", i), params=[],
                         controlled_by=[], science_policy="LOCKED_SCIENCE",
                         artist_type="collection", scope=scope)
    return fig, reg


def build_figure_and_registry(scope=SCOPES[0]):
    return build_scene(load_science(), {}, scope)


def layout_contract(scope=SCOPES[0]):
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    fig, reg = build_scene(load_science(), {}, scope)
    try:
        nodes = {}
        for gid in reg.all():
            meta = reg.meta_of(gid)
            nodes[gid] = {"type": meta.get("type"),
                          "science_policy": meta.get("science_policy"),
                          "editable": False}
    finally:
        plt.close(fig)
    return {"scope": scope, "version": 1, "parameters": [], "relations": [],
            "groups": [], "nodes": nodes, "outputs": [f"ann_{scope}_after.png"]}


def science_manifest(science):
    return {"source": "cos(2*pi*t) curve + polar theta/r per raw script",
            "processing": "direct plot + annotate; no fitting",
            "anchors": {},
            "nodes": {}}
