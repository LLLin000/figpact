def find_text_overlaps(fig, min_area_px: float = 4.0) -> list[str]:
    """
    渲染后检查所有文字对象（轴标题、刻度、图例、标注、分图字母）的包围盒，
    返回互相重叠的文本对列表。空列表 = 通过。

    只报告“真实重叠”（交叠面积 > min_area_px），忽略刻度数字之间的正常邻接。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    items: list[tuple[str, object, bool]] = []
    for ax in fig.axes:
        tick_ids = set()
        for t in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            tick_ids.add(id(t))
            items.append((t.get_text(), t, True))
        cands = [ax.title, ax.xaxis.label, ax.yaxis.label]
        cands += list(ax.texts)
        leg = ax.get_legend()
        if leg is not None:
            cands += list(leg.get_texts())
        for t in cands:
            if t is not None:
                items.append((t.get_text(), t, id(t) in tick_ids))
    for t in fig.texts:
        items.append((t.get_text(), t, False))

    boxes = []
    for label, t, is_tick in items:
        if not str(label).strip():
            continue
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        boxes.append((label, bb, is_tick))

    problems = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            la, ba, ta = boxes[i]
            lb, bb_, tb = boxes[j]
            if ta and tb:          # 两个刻度数字之间不判
                continue
            if la == lb and ba.bounds == bb_.bounds:
                continue
            dx = min(ba.x1, bb_.x1) - max(ba.x0, bb_.x0)
            dy = min(ba.y1, bb_.y1) - max(ba.y0, bb_.y0)
            if dx > 0 and dy > 0 and dx * dy > min_area_px:
                problems.append(
                    f"重叠 {dx * dy:6.1f}px²  «{la}»  ×  «{lb}»"
                )
    return problems


