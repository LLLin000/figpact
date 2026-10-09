"""图表图元清点。"""
from typing import Any
import matplotlib.figure
from figpact.registry import GidRegistry


def inventory(fig: matplotlib.figure.Figure, registry: GidRegistry) -> dict[str, Any]:
    """遍历所有可见 Text / Line / Legend / Axes，逐条清点并统计 unregistered / unbound。"""
    pass
