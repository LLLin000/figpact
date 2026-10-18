"""G15-B errorbar R1 declaration: replays frozen upstream source, exposes stable
scopes + extant-artist registry. No cfg rewiring, no style resets.

Upstream: galleries/examples/statistics/errorbar_features.py @ 4aeb7734
License: see tools/g15/LICENSE.matplotlib.txt + NOTICE.txt (parent-saved).
Raw bytes preserved at tools/g15/B/raw/errorbar_features.py
(sha256 9741f89b...).

ax0 fmt='-o' HAS a connected data Line2D (curve.linewidth present there);
ax1 fmt='o' is marker-only (no connected curve). Both reported separately.
Blind spot: wrapper cannot see into frozen plotting statements.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from figpact import GidRegistry

FIGURE_ID = "g15b_errorbar"
SCOPES = ("ax0", "ax1")
CONFIG = {}
RAW = Path(__file__).parent / "raw" / "errorbar_features.py"


def load_config(path):
    import yaml
    p = Path(path)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def load_science():
    return {"source": "upstream synthetic: x=arange(0.1,4,0.5), y=exp(-x), "
            "symmetric yerr + asymmetric xerr arrays in frozen source",
            "note": "arrays verified from ErrorbarContainer dataLine/segments"}


def science_manifest(science):
    return {"nodes": {}, "science": science,
            "layout_viewports": {}}


def _build_frozen():
    import matplotlib.pyplot as _plt
    _old_show = _plt.show
    _plt.show = lambda *a, **k: None
    try:
        _plt.close("all")  # host-side isolation; restored show below (see prereg errata)
        g = {"__name__": "__g15b_frozen__", "plt": _plt}
        exec(compile(RAW.read_bytes(), str(RAW), "exec"), g)
        return _plt.figure(1)
    finally:
        _plt.show = _old_show

def build_scene(science, cfg, scope):
    fig = _build_frozen()
    idx = {"ax0": 0, "ax1": 1}[scope]
    ax = fig.axes[idx]
    reg = GidRegistry(scope=scope)
    # ErrorbarContainer lacks set_gid; register its data Line2D (Line2D has
    # set_gid) and the LineCollection barcol (Collection has set_gid).
    for ct in ax.containers:
        dl, _cl, bl = ct
        reg.register(dl, f"g15b_errorbar.{scope}.data",
                     artist_type="Line2D", science_policy="LOCKED_SCIENCE")
        for bj, b in enumerate(bl):
            reg.register(b, f"g15b_errorbar.{scope}.errbars.b{bj}",
                         artist_type="LineCollection",
                         science_policy="LOCKED_SCIENCE")
    return fig, reg


def build_figure_and_registry(scope="ax0"):
    return build_scene(load_science(), CONFIG, scope)


def layout_contract(scope="ax0"):
    _fig, reg = build_figure_and_registry(scope)
    return {"parameters": [],
            "nodes": {gid: {"type": type(reg.all()[gid]).__name__,
                             "parent": None,
                             "editable": False,
                             "science_policy": "LOCKED_SCIENCE"}
                      for gid in reg.all()},
            "groups": [], "relations": [], "outputs": ["g15b_errorbar.png"]}


if __name__ == "__main__":
    import sys
    scope = sys.argv[1] if len(sys.argv) > 1 else "ax0"
    fig, _ = build_scene(load_science(), CONFIG, scope)
    fig.savefig(Path(__file__).parent / f"g15b_errorbar_{scope}.png")
