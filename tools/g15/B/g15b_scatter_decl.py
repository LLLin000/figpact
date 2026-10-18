"""G15-B scatter R1 declaration (VALID, 2026-10-18 rev2): replays the FULL
frozen upstream source on every build, then returns the figure at the
original file-order index for the requested scope. No seed injection, no
plotting-statement edits, no style changes. Agg backend: plt.show() is a
natural no-op.

Upstream: galleries/examples/lines_bars_and_markers/scatter_with_legend.py
@ 4aeb7734. License: tools/g15/LICENSE.matplotlib.txt + NOTICE.txt.
Raw: tools/g15/B/raw/scatter_with_legend.py (sha256 e128daaa...).
Blind spot: wrapper cannot see into frozen plotting statements.

VALIDITY ERRATUM rev1 (harness-invalid, excluded from main tables): rev1
split RAW on '# %%' and exec'd each block standalone, dropping the
np.random.seed(19680801) + prior-block RNG consumption for fig2/fig3 scopes.
That changed science inputs (not protocol-only). All rev1 scatter R1
evidence is retained but flagged harness-invalid; only rev2 (this file)
counts. Engine nondeterminism was never the cause.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from figpact import GidRegistry

FIGURE_ID = "g15b_scatter"
SCOPES = ("fig1_loop", "fig2_classes", "fig3_rankprice")
_SCOPE_INDEX = {"fig1_loop": 0, "fig2_classes": 1, "fig3_rankprice": 2}
CONFIG = {}
RAW = Path(__file__).parent / "raw" / "scatter_with_legend.py"


def load_config(path):
    import yaml
    p = Path(path)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def load_science():
    return {"source": "upstream full-file replay: seed 19680801 + "
            "in-order RNG consumption; fig index selects 0/1/2",
            "note": "fig2/fig3 deterministic given full replay, verified vs truth"}


def science_manifest(science):
    return {"nodes": {}, "science": science}


def _build_full():
    # Full RAW replay every time: preserves seed + RNG consumption order.
    # Agg show() is a natural no-op; close prior figs for host isolation.
    import matplotlib.pyplot as _plt
    _plt.close("all")
    g = {"__name__": "__g15b_frozen__"}
    exec(compile(RAW.read_bytes(), str(RAW), "exec"), g)
    figs = [_plt.figure(n) for n in _plt.get_fignums()]
    assert len(figs) == 3, f"expected 3 figures, got {len(figs)}"
    return figs


def build_scene(science, cfg, scope):
    figs = _build_full()
    fig = figs[_SCOPE_INDEX[scope]]
    ax = fig.axes[0]
    reg = GidRegistry(scope=scope)
    for cj, coll in enumerate(ax.collections):
        reg.register(coll, f"g15b_scatter.{scope}.pathcoll.c{cj}",
                     artist_type="PathCollection",
                     science_policy="LOCKED_SCIENCE")
    return fig, reg


def build_figure_and_registry(scope="fig1_loop"):
    return build_scene(load_science(), CONFIG, scope)


def layout_contract(scope="fig1_loop"):
    _fig, reg = build_figure_and_registry(scope)
    return {"parameters": [],
            "nodes": {gid: {"type": type(reg.all()[gid]).__name__,
                             "parent": None,
                             "editable": False,
                             "science_policy": "LOCKED_SCIENCE"}
                      for gid in reg.all()},
            "groups": [], "relations": [], "outputs": ["g15b_scatter.png"]}


if __name__ == "__main__":
    import sys
    scope = sys.argv[1] if len(sys.argv) > 1 else "fig1_loop"
    fig, _ = build_scene(load_science(), CONFIG, scope)
    fig.savefig(Path(__file__).parent / f"g15b_scatter_{scope}.png")
