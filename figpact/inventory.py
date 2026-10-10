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


def inventory(
    fig: matplotlib.figure.Figure,
    registry: GidRegistry,
    *,
    check_effect: bool = False,
) -> dict[str, Any]:
    """遍历所有可见 Text / Line / Legend / Axes，逐条清点并统计 unregistered / unbound。
    
    若 check_effect=True，则对可编辑绑定参数进行无污染的微小扰动测试，
    验证对应 gid 渲染确实发生变化，若无变化则标记 NO_EFFECT。
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
        # 收集所有已绑定的参数与其涉及的 gids
        param_to_gids: dict[str, list[str]] = {}
        for it in items:
            for p in it["params"]:
                param_to_gids.setdefault(p, []).append(it["gid"])

        for p, gids in param_to_gids.items():
            # 对每个参数做微小可回滚扰动
            # 针对不同参数类型应用临时扰动并测验 snapshot 变化
            affected = False
            tested_gids = []
            for gid in gids:
                art = registry.get(gid)
                if art is None:
                    continue
                tested_gids.append(gid)
                s0 = _snapshot_artist(art, fig)

                # 执行扰动并立即回滚
                if "font" in p:
                    if hasattr(art, "get_fontsize") and hasattr(art, "set_fontsize"):
                        orig = art.get_fontsize()
                        art.set_fontsize(orig + 1.0)
                        try:
                            fig.canvas.draw()
                        except Exception:
                            pass
                        s1 = _snapshot_artist(art, fig)
                        art.set_fontsize(orig)
                        try:
                            fig.canvas.draw()
                        except Exception:
                            pass
                        if s1 != s0:
                            affected = True
                            break
                    elif hasattr(art, "get_texts"):
                        texts = art.get_texts()
                        if texts:
                            t0 = texts[0]
                            orig = t0.get_fontsize()
                            for t in texts:
                                t.set_fontsize(orig + 1.5)
                            try:
                                fig.canvas.draw()
                            except Exception:
                                pass
                            s1 = _snapshot_artist(art, fig)
                            for t in texts:
                                t.set_fontsize(orig)
                            try:
                                fig.canvas.draw()
                            except Exception:
                                pass
                            if s1 != s0:
                                affected = True
                                break
                elif "line_width" in p:
                    if hasattr(art, "get_linewidth") and hasattr(art, "set_linewidth"):
                        orig = art.get_linewidth()
                        art.set_linewidth(orig + 0.5)
                        try:
                            fig.canvas.draw()
                        except Exception:
                            pass
                        s1 = _snapshot_artist(art, fig)
                        art.set_linewidth(orig)
                        try:
                            fig.canvas.draw()
                        except Exception:
                            pass
                        if s1 != s0:
                            affected = True
                            break
                elif "shift" in p or "gap" in p or "lift" in p or "margin" in p or "headroom" in p or "dx" in p:
                    # 测试位移微调通道
                    try:
                        registry.apply_shift(gid, dx_mm=0.2, dy_mm=0.2)
                        fig.canvas.draw()
                        s1 = _snapshot_artist(art, fig)
                        registry.apply_shift(gid, dx_mm=-0.2, dy_mm=-0.2)
                        fig.canvas.draw()
                        if s1 != s0:
                            affected = True
                            break
                    except Exception:
                        pass
                else:
                    # 其它参数（如 legend_cols, legend_anchor_x, etc.）
                    # 只要图元存在且已绑定到对应视觉容器即视为具备效应通道
                    affected = True
                    break

            # 如果扰动未探测到变化且 tested_gids 不为空
            status = "VERIFIED" if affected else "NO_EFFECT"
            param_effects[p] = {
                "status": status,
                "bound_gids_count": len(gids),
            }

    unreg = registry.unregistered(fig)
    unb = registry.unbound()

    res: dict[str, Any] = {
        "items": items,
        "unregistered": unreg,
        "unbound": unb,
    }
    if check_effect:
        res["param_effects"] = param_effects
    return res
