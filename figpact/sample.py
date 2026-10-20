"""Bundled v0.1 curve: formula-generated data, no scientific files or Native knobs."""
import numpy as np
import matplotlib.pyplot as plt
from figpact.registry import GidRegistry

FIGURE_ID = 'figpact_demo'
SCOPES = ('main',)
SCIENCE_INPUTS = ()


def build_figure_and_registry(scope='main'):
    if scope != 'main':
        raise ValueError('The bundled curve has only scope main')
    x = np.linspace(0, 6, 121)
    fig, ax = plt.subplots(figsize=(4.8, 3.2), dpi=120)
    fig.subplots_adjust(left=.18, bottom=.18, right=.95, top=.95)
    curve, = ax.plot(x, 1 - np.exp(-x), label='Response', linewidth=1.5)
    ax.set_xlabel('Time (s)', fontsize=10)
    ax.set_ylabel('Response (a.u.)', fontsize=10)
    ax.tick_params(labelsize=9)
    registry = GidRegistry(scope=scope)
    registry.register(curve, 'figpact_demo.main.curve.response')
    return fig, registry
