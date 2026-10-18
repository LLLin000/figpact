"""R1 wrapper-only declaration for eventcollection_demo (FROZEN SOURCE, NO EDITS).

Protocol: reruns the immutable raw script bytes via runpy (same interpreter,
Agg backend) inside build_scene; exposes only enumeration + identity hooks.
No cfg rewiring, no parameter injection, no post-build fontsize/linewidth
setters. Single scope (raw creates exactly 1 figure). Nodes derive from the
real registry of the returned figure only.
"""
import hashlib
import runpy
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from figpact import GidRegistry  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "raw" / "eventcollection_demo.py"
RAW_SHA256 = "12f9facb541a25ca8702d44dcbd1f17ad7cf51bd9155c180200ed4d14b88d88a"
FIGURE_ID = "g15c_ev"
SCOPE = "main"
SCOPES = (SCOPE,)

__all__ = ["load_science", "build_scene", "build_figure_and_registry",
           "layout_contract", "science_manifest", "science_inputs",
           "SCOPES", "RAW_SHA256"]


def _check_bytes():
    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    if digest != RAW_SHA256:
        raise RuntimeError(f"upstream bytes changed: {digest}")


def load_science():
    """Deterministic science payload: RNG-seeded curve data (seed fixed in source)."""
    import numpy as np
    _check_bytes()
    rng = np.random.RandomState(19680801)
    xdata = rng.random([2, 10])
    xdata1 = np.sort(xdata[0, :])
    xdata2 = np.sort(xdata[1, :])
    return {"xdata1": xdata1, "xdata2": xdata2,
            "ydata1": xdata1 ** 2, "ydata2": 1 - xdata2 ** 3}


def science_inputs():
    return []


def _run_raw():
    _check_bytes()
    plt.close("all")
    import unittest.mock as _mock
    with _mock.patch.object(plt, "show", lambda *a, **k: None):
        runpy.run_path(str(RAW), run_name="__mp_main__")
    figs = [plt.figure(n) for n in plt.get_fignums()]
    if len(figs) != 1:
        raise RuntimeError(f"expected 1 figure, got {len(figs)}")
    return figs


def _gid(kind, idx):
    return f"{FIGURE_ID}.{SCOPE}.{kind}.{idx}"


def _register(fig, reg):
    ax = fig.axes[0]
    for i, ln in enumerate(ax.lines):
        reg.register(ln, _gid("curve", i), params=[],
                     controlled_by=[], science_policy="LOCKED_SCIENCE",
                     artist_type="curve", scope=SCOPE)
    for i, coll in enumerate(ax.collections):
        reg.register(coll, _gid("eventcollection", i), params=[],
                     controlled_by=[], science_policy="LOCKED_SCIENCE",
                     artist_type="collection", scope=SCOPE)
    for i, tx in enumerate([ax.xaxis.label, ax.yaxis.label, ax.title,
                            *ax.texts]):
        try:
            if not tx.get_text():
                continue
        except Exception:
            continue
        reg.register(tx, _gid("text", i), params=[],
                     controlled_by=[], science_policy="LOCKED_SCIENCE",
                     artist_type="text", scope=SCOPE)


def build_scene(science, config, scope):
    if scope != SCOPE:
        raise ValueError(f"unknown scope {scope!r}")
    figs = _run_raw()
    reg = GidRegistry(scope=scope)
    _register(figs[0], reg)
    return figs[0], reg


def build_figure_and_registry(scope=SCOPE):
    return build_scene(load_science(), {}, scope)


def layout_contract(scope=SCOPE):
    if scope != SCOPE:
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
            "groups": [], "nodes": nodes, "outputs": ["ev_after.png"]}


def science_manifest(science):
    return {"source": "numpy RandomState(19680801) curve data per raw script",
            "processing": "sort + y=x^2 / y=1-x^3, EventCollection marks, no fitting",
            "anchors": {},
            "nodes": {}}
