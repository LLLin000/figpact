"""Run a reviewed upstream original unchanged; no invented Native controls.

G25-S DEVELOPMENT adapter. Figure ordinals are replay selectors, not persistent
semantic panel identities. Python process guards are not an OS security sandbox.
"""
from pathlib import Path
import os
import runpy

SOURCE = Path(os.environ['G25S_SOURCE']).resolve()
SCIENCE_INPUTS = (SOURCE,)
FIGURE_ID = 'g25s_external'
SCOPE = 'fig0'


def original_figures():
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    plt.close('all')
    # Agg show is already noninteractive; suppress only GUI display, not plots.
    show = plt.show
    plt.show = lambda *args, **kwargs: None
    try:
        with mpl.rc_context():
            runpy.run_path(str(SOURCE), run_name='__main__')
        return [plt.figure(n) for n in plt.get_fignums()]
    finally:
        plt.show = show


def build_figure_and_registry(scope=SCOPE):
    from figpact import GidRegistry
    import matplotlib.pyplot as plt
    if not scope.startswith('fig') or not scope[3:].isdigit():
        raise ValueError(f'unknown figure ordinal: {scope}')
    index = int(scope[3:])
    figures = original_figures()
    if index >= len(figures):
        raise ValueError(f'figure ordinal disappeared: {scope}; count={len(figures)}')
    for i, fig in enumerate(figures):
        if i != index:
            plt.close(fig)
    return figures[index], GidRegistry(scope=scope)
