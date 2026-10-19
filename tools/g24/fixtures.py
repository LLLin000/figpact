"""Synthetic overlay-only fixture for the G24 blind set: one errorbar series + legend.

Trusted minimal plotting script (no YAML knobs, no product controls): deterministic
seeded data, one Axes, one connected errorbar data line, caps, and a legend.
It exposes the standard build entry points so the overlay route can discover it,
but declares NO native layout contract (no ``layout_contract``): native route is
absent by design. Errorbar caps and legend texts are never overlay targets
(matching ``figpact.style_identity`` semantics), which is exactly what the
unauthorized-attempt cases exercise.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np

import matplotlib.pyplot as plt

from figpact import GidRegistry

FIGURE_ID = "fig_synth_errlegend"
SCOPES = ("main",)
SCOPE = "main"
CONFIG_PATH = None
SCIENCE_INPUTS: tuple[Path, ...] = ()

N_POINTS = 12
SEED = 20261019
DATA_LABEL = "run A"
XLABEL = "Dose (a.u.)"
YLABEL = "Response (a.u.)"


def load_science() -> dict:
    """Deterministic载荷: fixed-seed dose-response with symmetric y errors."""
    rng = np.random.default_rng(SEED)
    x = np.linspace(0.5, 6.0, N_POINTS, dtype=float)
    y = 1.5 * x + 0.3 * rng.standard_normal(N_POINTS)
    yerr = 0.25 + 0.05 * rng.random(N_POINTS)
    return {"x": x, "y": y, "yerr": yerr, "label": DATA_LABEL}


def science_inputs() -> tuple[Path, ...]:
    return SCIENCE_INPUTS


def build_scene(science: dict, config: dict, scope: str):
    """Build the figure; ``config`` is accepted and ignored (no tunable product)."""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope!r}；可用：{list(SCOPES)}")
    fig = plt.figure(figsize=(80.0 / 25.4, 60.0 / 25.4), dpi=300)
    ax = fig.add_subplot(111)
    reg = GidRegistry(scope=scope)
    container = ax.errorbar(
        science["x"], science["y"], yerr=science["yerr"],
        fmt="-", color="#1f77b4", ecolor="#555555",
        elinewidth=1.0, capsize=3.0, label=science["label"],
    )
    data_line = container.lines[0]
    data_line.set_gid(f"{FIGURE_ID}.{scope}.curve.a")
    reg.register(data_line, f"{FIGURE_ID}.{scope}.curve.a")
    ax.set_xlabel(XLABEL, fontsize=8.0)
    ax.set_ylabel(YLABEL, fontsize=8.0)
    ax.tick_params(labelsize=7.0)
    ax.legend(fontsize=7.0, loc="upper left")
    return fig, reg


def build_figure_and_registry(scope: str = SCOPE):
    return build_scene(load_science(), {}, scope)
