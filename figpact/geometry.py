"""物理毫米几何：六种与图元类型无关的关系测量。

坐标系：画布**左下角**为原点，单位毫米（`bounds_mm = [x0, y0, x1, y1]`）。
轴对齐矩形是**包围盒**（envelope），不是可见轮廓 —— 关系测量必须区分：
  - `exact`：折线 ↔ 折线的线段最短距离，是数学精确的；
  - `envelope`：包围盒边到边的**带符号**间隙，只在矩形本身是真实形状时精确；
  - `text_rasterization`：文字的一侧是渲染器给出的墨迹包围盒。旋转文字得到的是
    旋转后墨迹的**轴对齐包围盒**，比真实轮廓更保守 —— 如实标注，不假装精确。

不确定度不编造：`uncertainty_mm` 恒为 None —— 本引擎**不做物理标定**，`calibrated` 恒为
False：输入几何（包围盒/折线）本身是渲染器栅格量与显示变换的产物，换 dpi/渲染器就可能变，
「对输入做数学上精确的运算」不是「已标定到真实物理墨迹」。也不使用调用方给的
`tolerance_mm` 冒充精度：那只是**验收界**，结果里原样回显并注明来源。

显示几何可能是**多段互不相连**的折线（`polylines_mm`：集合的多个子路径，或一条折线被
坐标轴裁开后剩下的几段）。测量只对真实存在的段说话，段与段之间绝不合成一条假连线。

可见笔迹：`precision='exact'` 表示对**输入几何**的数学精确运算；`precision='model_exact'`
表示对**数学模型**（如「中心线 ⊖ 半径和」的圆头圆角实线描边）的精确结果 —— 模型不等于
渲染器真正落在画布上的墨迹。
"""
from typing import Any, Optional, Sequence
import math

import numpy as np

_ANCHORS = ('left', 'right', 'top', 'bottom', 'center_x', 'center_y', 'baseline')
_DEVIATION_KINDS = ('align', 'equal_size', 'distribute')


# --------------------------------------------------------------------- helpers
def _bounds(node: dict[str, Any]) -> Optional[tuple[float, float, float, float]]:
    if not node.get('measured', True):
        return None
    b = node.get('bounds_mm')
    if not b or len(b) != 4:
        return None
    if any(v is None or not math.isfinite(float(v)) for v in b):
        return None
    return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))


def _as_polyline(pts: Any) -> Optional[np.ndarray]:
    if pts is None:
        return None
    arr = np.asarray(pts, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 2:
        return None
    if not np.all(np.isfinite(arr)):
        # NaN/Inf 不是可测几何：宁可报 UNSUPPORTED，也绝不把 NaN 当距离返回
        return None
    return arr


def _polylines(node: dict[str, Any]) -> list[np.ndarray]:
    """节点显示几何的**所有**折线段。

    裁剪会把一条折线断成互不相连的可见段（`polylines_mm`）：两段之间的连线在原图上
    根本不存在，测量对着它说话就是对着鬼影说话。单条折线（`polyline_mm`）与多段在这里
    统一成同一个列表。
    """
    found = [arr for arr in (_as_polyline(p) for p in (node.get('polylines_mm') or ()))
             if arr is not None]
    if found:
        return found
    single = _as_polyline(node.get('polyline_mm'))
    return [single] if single is not None else []


def _runs_segments(runs: Sequence[np.ndarray]) -> np.ndarray:
    """多段折线 → 线段集合（段与段之间绝不连线）。"""
    return np.concatenate([_segments(run) for run in runs])


def _runs_points(runs: Sequence[np.ndarray]) -> np.ndarray:
    return np.concatenate(list(runs))


def _segments(pts: np.ndarray) -> np.ndarray:
    return np.stack([pts[:-1], pts[1:]], axis=1)


def _point_seg_dist(points: np.ndarray, q0: np.ndarray, q1: np.ndarray) -> np.ndarray:
    """点到线段距离（可广播）。points/q0/q1 末维为 2。"""
    direction = q1 - q0
    denom = np.einsum('...i,...i->...', direction, direction)
    safe = np.where(denom > 0.0, denom, 1.0)
    t = np.einsum('...i,...i->...', points - q0, direction) / safe
    t = np.where(denom > 0.0, t, 0.0)
    t = np.clip(t, 0.0, 1.0)
    proj = q0 + t[..., None] * direction
    return np.linalg.norm(points - proj, axis=-1)


_SEGMENT_EPS = 1e-12   # **相对**容差：按线段自身尺度缩放，不会大到大坐标下吞掉正净空


def _segments_intersect(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """线段对是否真交叉（非平行情形，含端点接触）。

    容差是相对的（`1e-12 × |r|·|s|`，等价于夹角判据），所以在任意平移/缩放下判断一致，
    也不会把有正净空的线段判成接触。共线重叠、端点接触与零长度退化由距离公式给出 0，
    统一在 `_mesh_distance` 里判「接触」—— 于是 `intersects` 与 `value_mm == 0` 永远一致，
    不存在「距离 0 却报未相交」的误导。
    """
    r = a[:, None, 1] - a[:, None, 0]
    s = b[None, :, 1] - b[None, :, 0]
    qp = b[None, :, 0] - a[:, None, 0]
    rxs = r[..., 0] * s[..., 1] - r[..., 1] * s[..., 0]
    qpxr = qp[..., 0] * r[..., 1] - qp[..., 1] * r[..., 0]
    qpxs = qp[..., 0] * s[..., 1] - qp[..., 1] * s[..., 0]
    rn = np.linalg.norm(r, axis=-1)[:, None]
    sn = np.linalg.norm(s, axis=-1)[None, :]
    parallel = np.abs(rxs) <= _SEGMENT_EPS * rn * sn
    rxs_safe = np.where(parallel, 1.0, rxs)
    t = np.where(parallel, -1.0, qpxs / rxs_safe)
    u = np.where(parallel, -1.0, qpxr / rxs_safe)
    return (~parallel & (t >= -_SEGMENT_EPS) & (t <= 1.0 + _SEGMENT_EPS)
            & (u >= -_SEGMENT_EPS) & (u <= 1.0 + _SEGMENT_EPS))


_MESH_LIMIT = 2_000_000   # 线段对数上限：超过就走剪枝扫描，避免 O(n·m) 网格撑爆内存


def _mesh_distance(a_seg: np.ndarray, b_seg: np.ndarray) -> tuple[float, bool]:
    """网格法的精确最短距离与是否接触（内存 O(n·m)，调用方负责规模）。"""
    if len(a_seg) == 0 or len(b_seg) == 0:
        return math.inf, False
    if bool(_segments_intersect(a_seg, b_seg).any()):
        return 0.0, True
    a0, a1 = a_seg[:, 0], a_seg[:, 1]
    b0, b1 = b_seg[:, 0], b_seg[:, 1]
    A0, A1 = a0[:, None, :], a1[:, None, :]
    B0, B1 = b0[None, :, :], b1[None, :, :]
    dist = np.minimum(
        np.minimum(_point_seg_dist(A0, B0, B1), _point_seg_dist(A1, B0, B1)),
        np.minimum(_point_seg_dist(B0, A0, A1), _point_seg_dist(B1, A0, A1)),
    )
    value = float(dist.min())
    if value <= 0.0:
        # 共线重叠 / 端点接触 / 零长度退化：距离公式给出精确 0，同样算接触
        return 0.0, True
    return value, False


def _segment_set_distance(a_seg: np.ndarray, b_seg: np.ndarray) -> tuple[float, bool]:
    """两组线段的最短距离与是否接触（相交/共线重叠/端点接触，数学精确）。"""
    if len(a_seg) == 0 or len(b_seg) == 0:
        return math.inf, False
    if len(a_seg) * len(b_seg) > _MESH_LIMIT:
        return _segment_set_distance_sweep(a_seg, b_seg)
    return _mesh_distance(a_seg, b_seg)


def _segment_set_distance_sweep(a_seg: np.ndarray, b_seg: np.ndarray) -> tuple[float, bool]:
    """大输入下的精确最短距离：按当前最优值剪枝，只对候选做精确计算。

    剪枝用**完整的轴区间重叠界**：候选必须同时满足
    `a_x0 - x1 <= best`、`x0 - a_x1 <= best`、`a_y0 - y1 <= best`、`y0 - a_y1 <= best`；
    任一条不满足，说明该线段对沿某个轴已经分离得比 best 还远，真实距离必然大于 best。
    按 `a_x0` 排序只能给出**上界**（`a_x0 <= x1 + best` 是一个前缀），左端必须靠 `a_x1`
    判定 —— 起点远在左方、却横跨查询区间的长线段绝不能被丢掉（只按 `a_x0` 二分就会丢）。
    候选与最优值比较用的是同一份 `_mesh_distance`，所以结果与网格法逐位一致；
    内存是每行候选的规模，不是 n·m。
    """
    if len(b_seg) > len(a_seg):
        a_seg, b_seg = b_seg, a_seg
    a_x0 = np.minimum(a_seg[:, 0, 0], a_seg[:, 1, 0])
    a_x1 = np.maximum(a_seg[:, 0, 0], a_seg[:, 1, 0])
    a_y0 = np.minimum(a_seg[:, 0, 1], a_seg[:, 1, 1])
    a_y1 = np.maximum(a_seg[:, 0, 1], a_seg[:, 1, 1])
    order = np.argsort(a_x0, kind='stable')
    a_seg, a_x0, a_x1, a_y0, a_y1 = a_seg[order], a_x0[order], a_x1[order], a_y0[order], a_y1[order]

    best = math.inf
    for seg in b_seg:
        row = seg[None, :, :]
        x0 = min(seg[0, 0], seg[1, 0])
        x1 = max(seg[0, 0], seg[1, 0])
        y0 = min(seg[0, 1], seg[1, 1])
        y1 = max(seg[0, 1], seg[1, 1])
        if math.isinf(best):
            # 还没有任何真实距离，剪枝无从谈起：先整行精确算一次，拿到上界再剪
            cand = a_seg
        else:
            hi = int(np.searchsorted(a_x0, x1 + best, side='right'))
            if hi <= 0:
                continue
            keep = (((x0 - a_x1[:hi]) <= best) & ((a_y0[:hi] - y1) <= best)
                    & ((y0 - a_y1[:hi]) <= best))
            cand = a_seg[:hi][keep]
            if len(cand) == 0:
                continue
        row_best, hit = _mesh_distance(cand, row)
        if hit:
            return 0.0, True
        if row_best < best:
            best = row_best
    return best, False


def _rect_segments(bounds: tuple[float, float, float, float]) -> np.ndarray:
    x0, y0, x1, y1 = bounds
    corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)
    return np.stack([corners, np.roll(corners, -1, axis=0)], axis=1)


def _point_in_rect(pts: np.ndarray, bounds: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = bounds
    inside = (pts[:, 0] > x0) & (pts[:, 0] < x1) & (pts[:, 1] > y0) & (pts[:, 1] < y1)
    return bool(inside.any())


def _anchor_coord(node: dict[str, Any], axis: str, anchor: str) -> Optional[float]:
    b = _bounds(node)
    if b is None:
        return None
    x0, y0, x1, y1 = b
    table = {
        'left': x0, 'right': x1, 'bottom': y0, 'top': y1,
        'center_x': (x0 + x1) / 2.0, 'center_y': (y0 + y1) / 2.0,
        'baseline': (node.get('anchors') or {}).get('baseline'),
    }
    return table.get(anchor)


def _axis_edges(node: dict[str, Any], axis: str) -> tuple[float, float]:
    b = _bounds(node)
    assert b is not None
    x0, y0, x1, y1 = b
    return (x0, x1) if axis == 'x' else (y0, y1)


def _size(node: dict[str, Any], axis: str) -> float:
    lo, hi = _axis_edges(node, axis)
    return hi - lo


def _result(kind: str, nodes: Sequence[dict[str, Any]], *, axis: Optional[str], anchor: Optional[str],
            method: Optional[str], precision: str = 'envelope',
            notes: Sequence[str] = (), tolerance_mm: Optional[float] = None,
            **extra: Any) -> dict[str, Any]:
    res: dict[str, Any] = {
        'relation': kind,
        'objects': [n.get('id') for n in nodes],
        'unit': 'mm',
        'coordinate_reference': 'canvas_bottom_left',
        'axis': axis,
        'anchor': anchor,
        'method': method,
        'status': 'OK',
        'value_mm': None,
        'precision': precision,
        # 恒为 False：输入几何是渲染器栅格量/显示变换的产物，本引擎不做物理标定 ——
        # 数学精确（precision='exact'）不是标定，同一条关系换 dpi 就可能变。
        'calibrated': False,
        'uncertainty_mm': None,
        'tolerance_mm': tolerance_mm,
        'within_tolerance': None,
        'notes': list(notes),
    }
    res.update(extra)
    return res


def _unsupported(kind: str, nodes: Sequence[dict[str, Any]], reason: str, *, axis: Optional[str] = None,
                 anchor: Optional[str] = None, method: Optional[str] = None,
                 status: str = 'UNSUPPORTED', tolerance_mm: Optional[float] = None) -> dict[str, Any]:
    res = _result(kind, nodes, axis=axis, anchor=anchor, method=method, notes=[reason],
                  tolerance_mm=tolerance_mm)
    res['status'] = status
    return res


def _finish(res: dict[str, Any], value: float, *, precision: str,
            notes: Sequence[str] = ()) -> dict[str, Any]:
    res['value_mm'] = float(value)
    res['precision'] = precision
    res['notes'] = list(res.get('notes') or []) + list(notes) + [
        'precision 只描述对**输入几何**的运算（数学精确 ≠ 物理标定）：calibrated=false、'
        'uncertainty_mm=null']
    tol = res.get('tolerance_mm')
    if tol is not None:
        res['tolerance_semantics'] = ('max_deviation_mm' if res['relation'] in _DEVIATION_KINDS
                                      else ('min_%s_mm' % res['relation']))
        res['within_tolerance'] = bool(value <= tol) if res['relation'] in _DEVIATION_KINDS else bool(value >= tol)
        res['notes'].append('tolerance_mm 是调用方给出的验收界（within_tolerance 按它判定），'
                            '不是标定/精度证据')
    return res


# ------------------------------------------------------------------- measuring
def measure_relation(kind: str, nodes: Sequence[dict[str, Any]], *, axis: str = 'x',
                     anchor: Optional[str] = None, method: Optional[str] = None,
                     tolerance_mm: Optional[float] = None) -> dict[str, Any]:
    """测量一条关系。`nodes` 是快照节点（含 bounds_mm / polyline_mm / measured）。

    返回 JSON 可序列化结果：{relation, objects, status, value_mm, method, unit,
    coordinate_reference, precision, calibrated, uncertainty_mm, ...}。
    几何不足以支撑请求的精度时 → status 为 UNSUPPORTED（或 UNMEASURED），不猜。
    `axis=None`/`'both'` 只对容器与尺寸类关系有意义；单轴类关系默认 x，绝不静默当成 y。
    """
    if axis not in ('x', 'y', None, 'both'):
        return _unsupported(kind, list(nodes or ()), f'非法 axis：{axis!r}（只能是 x / y / both / null）',
                           axis=axis, anchor=anchor, method=method, tolerance_mm=tolerance_mm)
    declared_axis = axis
    resolved = axis if axis in ('x', 'y') else ('both' if kind in ('contain', 'equal_size') else 'x')
    result = _measure(kind, nodes, axis=resolved, anchor=anchor, method=method, tolerance_mm=tolerance_mm)
    if declared_axis != resolved:
        result['declared_axis'] = declared_axis
        result['projection'] = resolved
        result['notes'] = list(result.get('notes') or ()) + [
            f'调用方未指定单轴（axis={declared_axis!r}）：结果是 {resolved} 轴投影上的关系，'
            f'不是二维全局重叠/间距；要二维结论请显式给 axis 或改用 contain']
    return result


def _measure(kind: str, nodes: Sequence[dict[str, Any]], *, axis: str = 'x',
             anchor: Optional[str] = None, method: Optional[str] = None,
             tolerance_mm: Optional[float] = None) -> dict[str, Any]:
    nodes = list(nodes or ())
    if tolerance_mm is not None:
        if isinstance(tolerance_mm, bool) or not isinstance(tolerance_mm, (int, float)) \
                or not math.isfinite(float(tolerance_mm)) or tolerance_mm < 0:
            raise ValueError('tolerance_mm 必须是有限非负数')

    if kind not in ('align', 'gap', 'clearance', 'contain', 'equal_size', 'distribute'):
        return _unsupported(kind, nodes, f'未知关系类型：{kind!r}', axis=axis, anchor=anchor,
                            method=method, tolerance_mm=tolerance_mm)
    if len(nodes) < 2:
        return _unsupported(kind, nodes, f'{kind} 至少需要两个对象', axis=axis, anchor=anchor,
                            method=method, tolerance_mm=tolerance_mm)
    if kind == 'clearance' and len(nodes) != 2:
        return _unsupported(kind, nodes, 'clearance 是两两关系，只接受两个对象', axis=axis,
                            anchor=anchor, method=method, tolerance_mm=tolerance_mm)

    missing = [n.get('id') for n in nodes if _bounds(n) is None]
    if missing:
        clipped = [n.get('id') for n in nodes if n.get('fully_clipped')]
        status = 'UNMEASURED' if any(not n.get('measured', True) for n in nodes) else 'UNSUPPORTED'
        reason = ('渲染器/字体环境不可用，几何未测量' if status == 'UNMEASURED'
                  else ('对象被坐标轴完全裁切，无可见几何' if clipped
                        else '包围盒缺失，无法测量'))
        return _unsupported(kind, nodes, f'{reason}：{missing}', axis=axis, anchor=anchor,
                            method=method, status=status, tolerance_mm=tolerance_mm)

    if kind == 'clearance':
        return _measure_clearance(nodes, axis=axis, method=method, tolerance_mm=tolerance_mm)

    if kind == 'align':
        if anchor is None:
            return _unsupported(kind, nodes, 'align 必须给出 anchor（left/right/top/bottom/center_x/center_y/baseline）',
                                axis=axis, method=method, tolerance_mm=tolerance_mm)
        if anchor not in _ANCHORS:
            return _unsupported(kind, nodes, f'未知 anchor：{anchor!r}', axis=axis, anchor=anchor,
                                method=method, tolerance_mm=tolerance_mm)
        coords = [_anchor_coord(n, axis, anchor) for n in nodes]
        if any(c is None for c in coords):
            return _unsupported(kind, nodes, f'anchor {anchor!r} 在部分对象上不可测量', axis=axis,
                                anchor=anchor, method=method, tolerance_mm=tolerance_mm)
        spread = max(coords) - min(coords)
        res = _result(kind, nodes, axis=axis, anchor=anchor, method=method or 'anchor_spread',
                      anchors_mm={n.get('id'): c for n, c in zip(nodes, coords)},
                      tolerance_mm=tolerance_mm)
        res = _finish(res, spread, precision='exact')
        res['aligned'] = bool(spread <= 1e-9)
        return res

    if kind == 'gap':
        if method == 'baseline':
            # 显示几何里「首个折线顶点」的距离（NMR 虚线基线 pitch 的既有语义）。
            # 裁剪成多段时取第一段的首个顶点（它就是这条折线最先被画出来的地方）。
            firsts = []
            for n in nodes:
                runs = _polylines(n)
                if not runs:
                    return _unsupported(kind, nodes,
                                        'gap method=baseline 需要每个对象都有折线几何（displayed polyline_mm）',
                                        axis=axis, anchor=anchor, method=method,
                                        tolerance_mm=tolerance_mm)
                firsts.append(float(runs[0][0][0 if axis == 'x' else 1]))
            order = sorted(range(len(nodes)), key=lambda i: (firsts[i], i))
            ordered = [nodes[i] for i in order]
            value = firsts[order[-1]] - firsts[order[0]]
            res = _result(kind, nodes, axis=axis, anchor=anchor, method=method,
                          first_point_mm={n.get('id'): f for n, f in zip(nodes, firsts)},
                          tolerance_mm=tolerance_mm)
            return _finish(res, value, precision='exact',
                           notes=['首个折线顶点的显示距离，数学精确（不受线宽影响）'])
        ordered = sorted(nodes, key=lambda n: _axis_edges(n, axis)[0])
        gaps = []
        pairs = []
        for lower, upper in zip(ordered, ordered[1:]):
            gap = _axis_edges(upper, axis)[0] - _axis_edges(lower, axis)[1]
            gaps.append(float(gap))
            pairs.append([lower.get('id'), upper.get('id')])
        res = _result(kind, nodes, axis=axis, anchor=anchor, method=method or 'envelope_edge',
                      gaps_mm=gaps, pairs=pairs, tolerance_mm=tolerance_mm)
        return _finish(res, min(gaps), precision='envelope',
                       notes=[f'{axis} 轴投影上的带符号包围盒边到边间隙'
                              f'（负值={axis} 轴投影重叠，不代表二维重叠）'])

    if kind == 'contain':
        parent, children = nodes[0], nodes[1:]
        axes = ('x', 'y') if (axis is None or axis == 'both') else (axis,)
        overflow: dict[str, float] = {}
        for ax in axes:
            p_lo, p_hi = _axis_edges(parent, ax)
            worst = -math.inf
            for child in children:
                c_lo, c_hi = _axis_edges(child, ax)
                worst = max(worst, c_hi - p_hi, p_lo - c_lo)
            overflow[ax] = float(worst)
        value = max(overflow.values())
        res = _result(kind, nodes, axis=axis, anchor=anchor, method=method or 'envelope_overflow',
                      overflow_mm=overflow, slack_mm=float(-value), tolerance_mm=tolerance_mm)
        res = _finish(res, value, precision='envelope',
                      notes=['正溢出=超出容器，负值=净空'])
        res['contained'] = bool(value <= 0.0)
        if tolerance_mm is not None:
            res['within_tolerance'] = bool(value <= tolerance_mm)
        return res

    if kind == 'equal_size':
        axes = ('x', 'y') if (axis is None or axis == 'both') else (axis,)
        sizes = {n.get('id'): {ax: _size(n, ax) for ax in axes} for n in nodes}
        spread = {ax: max(v[ax] for v in sizes.values()) - min(v[ax] for v in sizes.values())
                  for ax in axes}
        res = _result(kind, nodes, axis=axis, anchor=anchor, method=method or 'size_spread',
                      sizes_mm=sizes, deviations_mm={ax: float(v) for ax, v in spread.items()},
                      tolerance_mm=tolerance_mm)
        res = _finish(res, max(spread.values()), precision='exact',
                      notes=['每个轴上尺寸的极差（0=完全相等），多轴时取最大极差'])
        res['equal'] = bool(res['value_mm'] <= 1e-9)
        return res


    # distribute
    use_anchor = anchor or ('left' if axis == 'x' else 'bottom')
    if use_anchor not in _ANCHORS:
        return _unsupported(kind, nodes, f'未知 anchor：{use_anchor!r}', axis=axis, anchor=anchor,
                            method=method, tolerance_mm=tolerance_mm)
    if len(nodes) < 3:
        return _unsupported(kind, nodes, 'distribute 至少需要三个对象', axis=axis, anchor=use_anchor,
                            method=method, tolerance_mm=tolerance_mm)
    coords = [_anchor_coord(n, axis, use_anchor) for n in nodes]
    if any(c is None for c in coords):
        return _unsupported(kind, nodes, f'anchor {use_anchor!r} 在部分对象上不可测量', axis=axis,
                            anchor=use_anchor, method=method, tolerance_mm=tolerance_mm)
    order = sorted(range(len(nodes)), key=lambda i: (coords[i], i))
    ordered = [nodes[i] for i in order]
    gaps = [float(_axis_edges(ordered[i + 1], axis)[0] - _axis_edges(ordered[i], axis)[1])
            for i in range(len(ordered) - 1)]
    deviation = max(gaps) - min(gaps)
    res = _result(kind, nodes, axis=axis, anchor=use_anchor, method=method or 'gap_deviation',
                  gaps_mm=gaps, order=[n.get('id') for n in ordered], tolerance_mm=tolerance_mm)
    return _finish(res, deviation, precision='envelope',
                   notes=['相邻间隙的极差（0=均匀分布）'])


def _stroke_radius(node: dict[str, Any]) -> Optional[float]:
    lw = node.get('linewidth_mm')
    if lw is None or not isinstance(lw, (int, float)) or not math.isfinite(float(lw)):
        return None
    return float(lw) / 2.0


def _round_stroke(node: dict[str, Any]) -> Optional[str]:
    """可见笔迹可否用「中心线 ⊖ 半径」模型精确表示；不行就说明原因。"""
    if node.get('linewidth_pt_per_element'):
        return ('每个元素的线宽不同（linewidth_pt_per_element），没有统一的半径外扩模型，'
                '不拿平均值冒充半径')
    if _stroke_radius(node) is None:
        return '缺少实测线宽 linewidth_mm，无法做可见笔迹净空'
    style = node.get('linestyle')
    if style is None:
        return '缺少实测线型 linestyle，无法确认是实线（虚线段之间有完全没有墨迹的间隙）'
    if str(style).lower() not in ('-', 'solid'):
        return (f'线型 {style!r} 不是实线：虚线段之间有完全没有墨迹的间隙，'
                '没有连续的半径外扩模型')
    if str(node.get('solid_capstyle', '')).lower() != 'round':
        return f"端点帽 {node.get('solid_capstyle')!r} 不是 round，可见笔迹没有精确的半径外扩模型"
    if str(node.get('solid_joinstyle', '')).lower() != 'round':
        return f"折角 {node.get('solid_joinstyle')!r} 不是 round，可见笔迹没有精确的半径外扩模型"
    marker = str(node.get('marker', 'none') or 'none').lower()
    if marker not in ('none', '', ' '):
        return f'带数据点标记 {marker!r}，笔迹不是简单圆头描边'
    return None


def _unusable_runs(node: dict[str, Any]) -> int:
    """声明了却不能当几何用的折线段数（非有限点 / 点数不足）。

    只要有一段声明了却不可测，测量就必须拒绝：报「已测量」而少算一段 = 对着半条几何说话。
    """
    declared = node.get('polylines_mm') or ([node['polyline_mm']] if node.get('polyline_mm') else [])
    return sum(1 for run in declared if _as_polyline(run) is None)


def _measure_clearance(nodes: Sequence[dict[str, Any]], *, axis: str, method: Optional[str],
                       tolerance_mm: Optional[float]) -> dict[str, Any]:
    a, b = nodes
    unusable = [n.get('id') for n in nodes if _unusable_runs(n)]
    if unusable:
        return _unsupported('clearance', nodes,
                            f'{unusable} 声明了折线几何但不是可测几何（非有限点/点数不足）：'
                            '既不拿包围盒冒充它，也不返回 NaN', axis=axis, method=method,
                            tolerance_mm=tolerance_mm)
    runs_a, runs_b = _polylines(a), _polylines(b)
    bounds_a, bounds_b = _bounds(a), _bounds(b)

    if method is None:
        if runs_a and runs_b:
            method = 'segment_segment'
        elif bool(runs_a) != bool(runs_b):
            method = 'centerline_text_envelope'
        else:
            method = 'envelope'

    if method not in ('segment_segment', 'stroke_segment', 'centerline_text_envelope', 'envelope'):
        return _unsupported('clearance', nodes, f'未知 method：{method!r}', axis=axis,
                            method=method, tolerance_mm=tolerance_mm)

    if method in ('segment_segment', 'stroke_segment'):
        if not runs_a or not runs_b:
            return _unsupported('clearance', nodes,
                                f'{method} 需要双方都有折线几何（displayed polyline_mm）',
                                axis=axis, method=method, tolerance_mm=tolerance_mm)
        dist, intersects = _segment_set_distance(_runs_segments(runs_a), _runs_segments(runs_b))
        split = [n.get('id') for n, runs in ((a, runs_a), (b, runs_b)) if len(runs) > 1]
        split_note = ([] if not split else
                      [f'折线被裁成多段互不相连的显示段（{split}）：只对真实存在的段测量，'
                       '段与段之间没有合成连线'])
        if method == 'stroke_segment':
            problems = [f'{n.get("id")}：{reason}' for n in nodes
                        if (reason := _round_stroke(n)) is not None]
            if problems:
                return _unsupported('clearance', nodes,
                                    '可见笔迹净空需要圆头/圆角的**实线**描边：' + '；'.join(problems),
                                    axis=axis, method=method, tolerance_mm=tolerance_mm)
            radius = _stroke_radius(a) + _stroke_radius(b)
            strokes = dist - radius
            res = _result('clearance', nodes, axis=axis, anchor=None, method=method,
                          geometry_basis='centerline_minus_stroke_radii',
                          centerline_mm=float(dist), centerline_intersects=bool(intersects),
                          stroke_radius_mm={'a': _stroke_radius(a), 'b': _stroke_radius(b)},
                          intersects=bool(strokes <= 0.0), tolerance_mm=tolerance_mm)
            return _finish(res, max(0.0, strokes), precision='model_exact',
                           notes=['圆头/圆角的**实线**描边可以写成「中心线 ⊖ 半径和」，'
                                  '值是**数学模型**的精确结果',
                                  '模型 ≠ 渲染墨迹：虚线段间隙、z 序遮挡、折角外扩、'
                                  '抗锯齿都让真实可见墨迹与模型不同，这里没有标定到渲染像素',
                                  'intersects 是**可见笔迹**（半径和外扩后）的重叠，'
                                  '不是中心线相交（centerline_intersects 单独给出）']
                                 + split_note)
        res = _result('clearance', nodes, axis=axis, anchor=None, method=method,
                      geometry_basis='centerline', intersects=intersects, tolerance_mm=tolerance_mm)
        return _finish(res, dist, precision='exact',
                       notes=['折线中心线之间的最短距离：线段数学精确，但**不含线宽/端点帽**，'
                              '可见笔迹比这个值更近'] + split_note)

    if method == 'centerline_text_envelope':
        if runs_a and not runs_b:
            line_runs, text_node, text_bounds = runs_a, b, bounds_b
        elif runs_b and not runs_a:
            line_runs, text_node, text_bounds = runs_b, a, bounds_a
        else:
            return _unsupported('clearance', nodes,
                                'centerline_text_envelope 需要一个折线对象与一个矩形包围盒对象',
                                axis=axis, method=method, tolerance_mm=tolerance_mm)
        if _point_in_rect(_runs_points(line_runs), text_bounds):
            value, intersects = 0.0, True
        else:
            value, intersects = _segment_set_distance(_runs_segments(line_runs),
                                                      _rect_segments(text_bounds))
        rotated = abs(float(text_node.get('rotation_deg') or 0.0)) > 0.0
        notes = ['折线**中心线**到文字**墨迹包围盒**的距离：线段侧数学精确，文字侧是渲染器栅格'
                 '包围盒，且不含曲线线宽 —— 不是可见笔迹到真实字形轮廓的距离'
                 '（旋转文字得到的是旋转后墨迹的轴对齐包围盒，更保守）' if rotated
                 else '折线**中心线**到文字**墨迹包围盒**的距离：线段侧数学精确，文字侧是渲染器'
                      '栅格包围盒，且不含曲线线宽 —— 不是可见笔迹到真实字形轮廓的距离']
        res = _result('clearance', nodes, axis=axis, anchor=None, method=method,
                      geometry_basis='centerline_to_text_ink_envelope',
                      intersects=intersects, text_object=text_node.get('id'),
                      rotated_text=rotated, tolerance_mm=tolerance_mm)
        return _finish(res, value, precision='envelope', notes=notes)

    d_axes = []
    for ax in ('x', 'y'):
        a_lo, a_hi = _axis_edges(a, ax)
        b_lo, b_hi = _axis_edges(b, ax)
        d_axes.append(max(b_lo - a_hi, a_lo - b_hi))
    value = max(d_axes)
    notes = ['包围盒（envelope）带符号分离（负值=重叠）；不是可见轮廓/笔迹距离']
    if any(abs(float(n.get('rotation_deg') or 0.0)) > 0.0 for n in nodes):
        notes.append('含旋转文字：包围盒是其旋转墨迹的轴对齐包围盒，结果更保守')
    res = _result('clearance', nodes, axis=axis, anchor=None, method=method,
                  geometry_basis='envelope',
                  envelope_gaps_mm={'x': float(d_axes[0]), 'y': float(d_axes[1])},
                  tolerance_mm=tolerance_mm)
    return _finish(res, value, precision='envelope', notes=notes)
