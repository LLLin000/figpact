"""G15-B barchart R1 declaration: replays frozen upstream source, exposes stable
scopes + extant-artist registry. No cfg rewiring, no fontsize/linewidth
resets, no source edits. Wrapper-only AST blind spot documented below.

Upstream: galleries/examples/lines_bars_and_markers/barchart.py @ 4aeb7734
License: see tools/g15/LICENSE.matplotlib.txt + NOTICE.txt (parent-saved).
Raw bytes preserved at tools/g15/B/raw/barchart.py (sha256 f742b277...).

Blind spot: declarations appended below CANNOT see into the frozen script's
plotting statements; discovery observes only wrapper-level build_scene and
this file's AST. Original source AST remains discoverable only in raw file.
"""
from pathlib import Path
import runpy
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from figpact import GidRegistry

FIGURE_ID = "g15b_barchart"
SCOPES = ("main",)
CONFIG = {}
RAW = Path(__file__).parent / "raw" / "barchart.py"


def load_config(path):
    import yaml
    p = Path(path)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def load_science():
    return {"source": "upstream penguin means (Allison Horst palmerpenguins); "
            "Bill Depth/Chinstrap etc fixed arrays in frozen source",
            "note": "heights verified from BarContainer rectangles, not re-typed"}


def science_manifest(science):
    return {"nodes": {}, "science": science}


def _build_frozen():
    import matplotlib.pyplot as _plt
    _old_show = _plt.show
    _plt.show = lambda *a, **k: None
    try:
        _plt.close("all")  # host-side isolation; restored show below (see prereg errata)
        g = {"__name__": "__g15b_frozen__", "plt": _plt}
        exec(compile(RAW.read_bytes(), str(RAW), "exec"), g)
        figs = [_plt.figure(n) for n in _plt.get_fignums()]
        return figs
    finally:
        _plt.show = _old_show


def build_scene(science, cfg, scope):
    figs = _build_frozen()
    fig = figs[0]
    ax = fig.axes[0]
    reg = GidRegistry(scope=scope)
    # Expose extant artists with stable identities. Containers (BarContainer)
    # lack set_gid, so register member Rectangle patches + bar_label Texts.
    i = 0
    for ci, cont in enumerate(
            [c for c in ax.containers if type(c).__name__ == "BarContainer"]):
        for rj, rect in enumerate(cont):
            reg.register(rect, f"g15b_barchart.{scope}.bar.c{ci}.r{rj}",
                         artist_type="Rectangle", science_policy="LOCKED_SCIENCE")
            i += 1
    for tj, txt in enumerate(ax.texts):
        reg.register(txt, f"g15b_barchart.{scope}.barlabel.t{tj}",
                     artist_type="Text", science_policy="LOCKED_SCIENCE")
    if ax.get_ylabel():
        pass  # ylabel Text is findable via fig.findobj; not gid-registered
    # (no existing protocol hooks for ylabel fontsize/legend in frozen source)
    return fig, reg


def build_figure_and_registry(scope="main"):
    return build_scene(load_science(), CONFIG, scope)


def layout_contract(scope="main"):
    fig, reg = build_figure_and_registry(scope)
    return {"parameters": [],
            "nodes": {gid: {"type": type(reg.all()[gid]).__name__,
                             "parent": None,
                             "editable": False,
                             "science_policy": "LOCKED_SCIENCE"}
                      for gid in reg.all()},
            "groups": [], "relations": [], "outputs": ["g15b_barchart.png"]}


if __name__ == "__main__":
    fig, _ = build_scene(load_science(), CONFIG, "main")
    fig.savefig(Path(__file__).with_suffix(".png"))
