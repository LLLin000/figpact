"""图表图元清点。"""
from typing import Any
import matplotlib.figure
from figpact.registry import GidRegistry


def inventory(fig: matplotlib.figure.Figure, registry: GidRegistry) -> dict[str, Any]:
    """遍历所有可见 Text / Line / Legend / Axes，逐条清点并统计 unregistered / unbound。
    
    返回字典结构：
    {
      "items": [
        {"gid": ..., "type": ..., "params": [...], "summary": ...},
        ...
      ],
      "unregistered": [...],
      "unbound": [...]
    }
    """
    items: list[dict[str, Any]] = []

    # 遍历 registry 中所有已登记对象
    for gid, art in registry.all().items():
        art_type = type(art).__name__
        summary = ""
        if hasattr(art, "get_text"):
            summary = art.get_text()[:40]
        elif hasattr(art, "get_xdata"):
            summary = f"points={len(art.get_xdata())}"
        elif hasattr(art, "get_lines"):
            summary = f"legend_entries={len(art.get_lines())}"
        else:
            summary = repr(art)

        items.append({
            "gid": gid,
            "type": art_type,
            "params": registry.params_of(gid),
            "summary": summary,
        })

    unreg = registry.unregistered(fig)
    unb = registry.unbound()

    return {
        "items": items,
        "unregistered": unreg,
        "unbound": unb,
    }
