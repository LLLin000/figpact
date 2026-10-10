"""图表图元清点。"""
from typing import Any
import matplotlib.figure
from figpact.registry import GidRegistry


def _snapshot_artist(art: Any, fig: matplotlib.figure.Figure) -> dict[str, Any]:
    """捕获图元在当前渲染状态下的视觉特征快照。"""
    snap: dict[str, Any] = {}
    try:
        renderer = fig.canvas.get_renderer()
    except Exception:
        renderer = None

    if hasattr(art, "get_window_extent") and renderer is not None:
        try:
            bbox = art.get_window_extent(renderer)
            snap["bbox"] = (round(bbox.x0, 2), round(bbox.y0, 2), round(bbox.x1, 2), round(bbox.y1, 2))
        except Exception:
            pass

    if hasattr(art, "get_fontsize"):
        try:
            snap["fontsize"] = float(art.get_fontsize())
        except Exception:
            pass
    if hasattr(art, "get_linewidth"):
        try:
            snap["linewidth"] = float(art.get_linewidth())
        except Exception:
            pass
    if hasattr(art, "get_position"):
        try:
            pos = art.get_position()
            snap["position"] = (round(pos[0], 4), round(pos[1], 4))
        except Exception:
            pass
    if hasattr(art, "get_ydata"):
        try:
            ydata = art.get_ydata()
            if len(ydata) > 0:
                snap["y_mean"] = round(float(sum(ydata[:10])) / min(len(ydata), 10), 4)
        except Exception:
            pass
    return snap


def _unsupported_effects(registry: GidRegistry) -> dict[str, dict[str, Any]]:
    """参数生效性的**如实**结果：这里没有真实的 builder/config 重建上下文。

    以前这里临时改 Artist 属性再比渲染快照 —— 那证明的是「改 Artist 会变」，
    不是「改 YAML 会有这个效果」，对 NO_EFFECT / EFFECT_MISMATCH 都会给出相反的答案。
    真实效果必须走一次真实重建：`figpact.effects.check_effects(script, config, scope)`。
    """
    param_to_gids: dict[str, list[str]] = {}
    for gid in registry.all():
        for key in registry.params_of(gid):
            param_to_gids.setdefault(key, []).append(gid)
    return {
        key: {
            "status": "UNSUPPORTED",
            "bound_gids_count": len(gids),
            "reason": "无真实重建上下文（未用 YAML 扰动 + 完整重建测量），不给出效果结论",
            "validator": "figpact.effects.check_effects(script, config, scope)",
        }
        for key, gids in param_to_gids.items()
    }


def inventory(
    fig: matplotlib.figure.Figure,
    registry: GidRegistry,
    *,
    check_effect: bool = False,
) -> dict[str, Any]:
    """遍历所有可见 Text / Line / Legend / Axes / Image / Patch / Collection / 自定义
    Artist，逐条清点并统计 unregistered / unbound。

    `check_effect=True` 只报告参数绑定的存在性与「未验证」状态 —— 没有真实重建
    上下文就**不给效果结论**（见 `_unsupported_effects`），更不冒充已证实的效应。
    """
    try:
        fig.canvas.draw()
    except Exception:
        pass

    items: list[dict[str, Any]] = []

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

        params = registry.params_of(gid)
        snap = _snapshot_artist(art, fig)
        item_entry: dict[str, Any] = {
            "gid": gid,
            "type": art_type,
            "params": params,
            "summary": summary,
            "snapshot": snap,
        }
        items.append(item_entry)

    param_effects: dict[str, dict[str, Any]] = {}
    if check_effect:
        param_effects = _unsupported_effects(registry)

    unreg = registry.unregistered(fig)
    unb = registry.unbound()

    res: dict[str, Any] = {
        "items": items,
        "unregistered": unreg,
        "unbound": unb,
        # 测量元数据：`items` 里的 bbox 是**当前 renderer 的显示像素**，换算成 mm
        # 必须用这一份 dpi。调用方（try / GUI 后端）以前写死 300 dpi，而图是
        # figure.dpi=120 → 报出来的位移被缩到 40%。别再从别处猜 dpi。
        "figure_dpi": float(fig.dpi),
        "figure_size_mm": [fig.get_figwidth() * 25.4, fig.get_figheight() * 25.4],
    }
    if check_effect:
        res["param_effects"] = param_effects
    return res
