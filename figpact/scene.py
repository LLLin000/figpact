"""输出作用域快照：节点树、毫米几何、锚点、可编辑与受控路径、关系测量。

坐标参考是画布**左下角**、单位毫米 —— 直接就是 matplotlib 的显示坐标（y 轴向上）
乘 `25.4 / renderer_dpi`，不做任何翻转或猜测。

诚实性约束：
  - 渲染器/字体环境不可用时**不测量**：`bounds_mm = None`、`measured = False`、
    `measured: false` 的节点进 diagnostics，绝不填 0；
  - 可见但未注册的图元（文字/曲线/图片/Patch/**集合**）依然是节点（`registered=False`），
    并单独进 diagnostics —— 未注册不是「不存在」；
  - 集合（LineCollection / PathCollection …）的显示几何按 `polylines_mm` 逐段给出（段与段
    绝不连成一条假折线）；标记字形/设备坐标等不可测集合如实报 UNSUPPORTED/UNMEASURED。
  - 裁剪把一条折线断成几段可见段时同样逐段给出（`polyline_mm=None` + `polylines_mm` +
    `polyline_runs`）；NaN 断口（渲染器在那里断开笔迹）也一样。两段之间本来没有连线，
    绝不合成一条假折线。
  - 文字一侧是渲染器栅格包围盒；旋转文字得到的是旋转墨迹的轴对齐包围盒，如实标注。
  - 节点的 `type` 是**语义**分类（figure / panel / group / curve / text / image / legend /
    shape / collection / artist），实际 matplotlib 具体类在 `artist_type` 里；作者声明的
    className 描述符（"Line2D"/"Axes"/"Rectangle"…）在这里归一，显式声明的 canonical 类型
    （guide 等）原样接受。
  - **不做物理标定**：几何量是渲染器栅格量与显示变换的数学结果，换 dpi/渲染器就可能变，
    关系结果的 `calibrated` 恒为 `False`、`uncertainty_mm` 恒为 `None`，`measurement`
    只声明来源（`basis`），不声称已标定。
"""
from typing import Any, Iterable, Optional, Sequence

import matplotlib.axes
import matplotlib.collections
import matplotlib.figure
import matplotlib.image
import matplotlib.legend
import matplotlib.lines
import matplotlib.patches
import matplotlib.text
import matplotlib.transforms
import numpy as np
from matplotlib.path import Path as _MplPath

from figpact import geometry
from figpact.registry import GidRegistry
from figpact.units import MM_PER_INCH, PT_TO_MM

_FONT_ENV_KEYS = ('font.family', 'font.sans-serif', 'font.serif', 'mathtext.fontset',
                  'font.size', 'axes.unicode_minus')

# 真正的图像图元（栅格墨迹）。集合虽然也有 get_array()（那是**颜色**），但不是图像。
_IMAGE_ARTIST_TYPES = tuple(
    cls for cls in (getattr(matplotlib.image, name, None)
                    for name in ('AxesImage', 'BboxImage', 'FigureImage', 'NonUniformImage',
                                 'PcolorImage'))
    if isinstance(cls, type))

# 公开的节点 `type` 是**语义**分类；实际 matplotlib 具体类在 `artist_type` 里，
# 谁也不许把 "Line2D" 这类类名当语义类型名使。
_SEMANTIC_TYPES = frozenset({'figure', 'panel', 'group', 'curve', 'text', 'image',
                             'legend', 'shape', 'collection', 'artist'})

# 顺序即优先级：具体类归属第一个匹配的语义桶，没匹配到就诚实报 `artist`。
_ARTIST_KINDS = (
    ('figure', (matplotlib.figure.Figure,)),
    ('panel', (matplotlib.axes.Axes,)),
    ('legend', (matplotlib.legend.Legend,)),
    ('text', (matplotlib.text.Text,)),
    ('image', _IMAGE_ARTIST_TYPES),
    ('curve', (matplotlib.lines.Line2D,)),
    ('collection', (matplotlib.collections.Collection,)),
    ('shape', (matplotlib.patches.Patch,)),
)


def _all_subclasses(cls: type) -> list[type]:
    found: list[type] = []
    for sub in cls.__subclasses__():
        found.append(sub)
        found.extend(_all_subclasses(sub))
    return found


def _descriptor_kinds() -> dict[str, str]:
    """matplotlib 具体类名（小写）→ 语义类型。

    注册表/契约里声明的是 **className 描述符**（原生脚本声明的就是 "Line2D" / "Axes" /
    "Text" / "Rectangle" / "AxesImage"）：按真实类名归一成语义 `type`，而不是把类名留在
    `type` 里再挂一个语义别名。
    """
    table: dict[str, str] = {}
    for kind, roots in _ARTIST_KINDS:
        for root in roots:
            for cls in (root, *_all_subclasses(root)):
                table.setdefault(cls.__name__.lower(), kind)
    table.setdefault('axespatch', 'shape')          # 旧参数清单里的描述符
    return table


_DESCRIPTOR_KIND = _descriptor_kinds()


def _artist_kind(artist: Any) -> str:
    """按图元**本身**判语义类型：任意新图元诚实落到 artist / collection / shape。"""
    if artist is None:
        return 'artist'
    for kind, classes in _ARTIST_KINDS:
        if isinstance(artist, classes):
            return kind
    return 'artist'


def _semantic_type(declared: Any, artist: Any = None) -> str:
    """声明的节点类型 → 语义 `type`。

    - 已经是语义类型（curve / panel / …）→ 原样；
    - className 描述符（"Line2D"、"Line2D (Guide)"、"AxesImage"、"Rectangle"…）→ 归一；
    - 其它**显式**作者声明（guide 等 canonical 类型）→ 原样接受，不猜也不吞；
    - 没声明 → 按图元本身判（诚实落到 artist/collection/shape）。
    """
    token = str(declared or '').strip()
    if token:
        parts = token.replace('(', ' ').replace('（', ' ').split()
        head = parts[0].lower() if parts else ''
        if not head:
            return _artist_kind(artist)
        if head in _SEMANTIC_TYPES:
            return head
        return _DESCRIPTOR_KIND.get(head, head)
    return _artist_kind(artist)


def _font_environment() -> dict[str, Any]:
    try:
        from matplotlib import rcParams
    except Exception:  # pragma: no cover - matplotlib 必须在场，这里只是兜底
        return {'available': False}
    env: dict[str, Any] = {'available': True}
    for key in _FONT_ENV_KEYS:
        value = rcParams.get(key)
        if isinstance(value, (list, tuple)):
            value = [str(v) for v in value]
        env[key] = value
    return env


def _resolve_renderer(fig: matplotlib.figure.Figure) -> tuple[Any, Optional[str]]:
    canvas = getattr(fig, 'canvas', None)
    if canvas is None:
        return None, 'Figure 没有 canvas，渲染器不可用'
    get_renderer = getattr(canvas, 'get_renderer', None)
    if get_renderer is None:
        return None, f'{type(canvas).__name__} 没有 get_renderer，渲染器不可用'
    try:
        return get_renderer(), None
    except Exception as exc:
        return None, f'{type(canvas).__name__}.get_renderer() 失败：{exc!r}'


def _mm_per_px(dpi: float) -> float:
    return MM_PER_INCH / float(dpi)


def _to_mm(box: Any, mm_per_px: float) -> Optional[list[float]]:
    bounds = [float(box.x0) * mm_per_px, float(box.y0) * mm_per_px,
              float(box.x1) * mm_per_px, float(box.y1) * mm_per_px]
    if not all(np.isfinite(bounds)) or bounds[0] > bounds[2] or bounds[1] > bounds[3]:
        return None
    return bounds


def _points_mm(points: Any, mm_per_px: float) -> list[list[float]]:
    return [[float(p[0]) * mm_per_px, float(p[1]) * mm_per_px] for p in points]


def _anchors_from_bounds(bounds: Sequence[float], *, baseline: Optional[float] = None) -> dict[str, float]:
    x0, y0, x1, y1 = bounds
    anchors = {'left': float(x0), 'right': float(x1), 'bottom': float(y0), 'top': float(y1),
               'center_x': float(x0 / 2.0 + x1 / 2.0), 'center_y': float(y0 / 2.0 + y1 / 2.0)}
    if baseline is not None:
        anchors['baseline'] = float(baseline)
    return anchors


def _union(boxes: Iterable[Sequence[float]]) -> Optional[list[float]]:
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _clip_segment_t(bounds: Sequence[float], p0: np.ndarray, p1: np.ndarray):
    """Liang–Barsky：单条线段对矩形的参数区间。返回 (t0, t1, visible)。"""
    x0, y0, x1, y1 = bounds
    d = p1 - p0
    t0, t1 = 0.0, 1.0
    for p, q in ((-d[0], p0[0] - x0), (d[0], x1 - p0[0]),
                 (-d[1], p0[1] - y0), (d[1], y1 - p0[1])):
        if p == 0.0:
            if q < 0.0:
                return 0.0, 1.0, False
            continue
        r = q / p
        if p < 0.0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return 0.0, 1.0, False
    return t0, t1, True


def _same_point(a: Any, b: Any) -> bool:
    """两个显示坐标点是否同一点（容差按坐标量级缩放，浮点减法误差不会被当成新点）。"""
    tol = 1e-12 * max(1.0, abs(float(a[0])), abs(float(a[1])),
                      abs(float(b[0])), abs(float(b[1])))
    return abs(float(a[0]) - float(b[0])) <= tol and abs(float(a[1]) - float(b[1])) <= tol


_CLIP_INSIDE_MARGIN = 2.0 ** -45


def _clip_is_inside(points: Any, bounds: Sequence[float]) -> bool:
    """整条折线是否**可证明**落在框内，且框内线段裁剪参数恰好是 0.0/1.0。

    框内线段只有一处会被浮点舍入翻掉：终点贴在**右/上**边、位移又朝那边时，
    `x1 - p0[0]` 与 `p1[0] - p0[0]` 的被减数不同，两个减法的舍入差（量级 2**-53 × B）
    可能让 `r = q / p` 掉到 1 以下，t1 就不再是 1.0。左/下边没有这个问题：
    `p0[0] - x0` 与 `p0[0] - p1[0]` 共用被减数，减法对减数单调，框内必然 `q >= p`。
    所以离右/上边留出 2**-45 倍量级的空隙就够（比所需上界 2**-51 倍宽 64 倍）；
    与边**逐位相等**时两个减法字面同式，同样安全。NaN/Inf 一律不算框内。
    """
    if len(points) < 2:                         # 单点/空折线没有线段可裁
        return False
    arr = np.asarray(points, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        return False
    if not bool(np.isfinite(arr).all()):
        return False
    x0, y0 = float(bounds[0]), float(bounds[1])
    x1, y1 = float(bounds[2]), float(bounds[3])
    x, y = arr[:, 0], arr[:, 1]
    if not bool(((x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)).all()):
        return False
    margin = max(1.0, abs(x0), abs(y0), abs(x1), abs(y1)) * _CLIP_INSIDE_MARGIN
    right, top = x1 - x, y1 - y
    return not bool((((right != 0.0) & (right < margin))
                     | ((top != 0.0) & (top < margin))).any())


def _clip_inside_runs(points: np.ndarray) -> list[np.ndarray]:
    """框内折线的快路径：与逐段 Liang–Barsky 的旧结果**逐位一致**，只是不再真去裁剪。

    框内线段的 t 恒为 0.0/1.0，`start + t * (end - start)` 就退化成一个 0.0 乘、一个
    1.0 乘（两者都精确），这里用 Python float 照算同一串 IEEE 双精度运算；段链语义
    （连链、`_same_point` 去重、`>= 2` 个点才算一段）与默认路径逐字相同。
    """
    runs: list[list[list[float]]] = []
    for start, end in zip(points[:-1], points[1:]):
        sx, sy = float(start[0]), float(start[1])
        dx, dy = float(end[0]) - sx, float(end[1]) - sy
        head = [sx + 0.0 * dx, sy + 0.0 * dy]
        tail = [sx + 1.0 * dx, sy + 1.0 * dy]
        if runs and _same_point(runs[-1][-1], head):
            chain = runs[-1]
        else:
            chain = []
            runs.append(chain)
            chain.append([head[0], head[1]])
        if not _same_point(chain[-1], tail):
            chain.append([tail[0], tail[1]])
    return [np.asarray(run, dtype=float) for run in runs if len(run) >= 2]


def _clip_polyline_runs(points: np.ndarray, bounds: Sequence[float]) -> list[np.ndarray]:
    """把折线裁进矩形，返回**互不相连**的可见段链。

    一条折线离开坐标框再回来时，两段可见部分之间本来没有连线；把它们拼成一条折线
    会凭空多出一条根本不存在的连线，净空/碰撞测量就会对着鬼影说话。所以每段可见链
    单独返回（`>= 2` 个点的段才有几何意义）。

    整条（有限）折线都在框内时走 `_clip_inside_runs`：结果与逐段裁剪逐位相同，
    省掉每个线段的 Liang–Barsky（真实 NMR 图上是 10 万次）。部分裁剪、NaN 断口、
    退化线段、非有限点仍走下面的逐段默认路径。
    """
    if _clip_is_inside(points, bounds):
        return _clip_inside_runs(points)
    runs: list[list[list[float]]] = []
    for start, end in zip(points[:-1], points[1:]):
        t0, t1, visible = _clip_segment_t(bounds, start, end)
        if not visible:
            continue
        piece = [start + t0 * (end - start), start + t1 * (end - start)]
        if runs and _same_point(runs[-1][-1], piece[0]):
            chain = runs[-1]
        else:
            chain = []
            runs.append(chain)
            chain.append([float(piece[0][0]), float(piece[0][1])])
        for point in piece[1:]:
            if not _same_point(chain[-1], point):
                chain.append([float(point[0]), float(point[1])])
    return [np.asarray(run, dtype=float) for run in runs if len(run) >= 2]


def _finite_runs(points: np.ndarray) -> list[np.ndarray]:
    """把显示折线在非有限点（NaN/Inf）处切成互不相连的段。

    渲染器在 NaN 处**断开**笔迹；把断口两侧接成一条折线同样是凭空连线（净空/碰撞
    会对着一根并不存在的连线说话），而且 NaN 会污染整条折线的距离计算。
    """
    runs: list[list[list[float]]] = []
    current: list[list[float]] = []
    for point in points:
        if bool(np.all(np.isfinite(point))):
            current.append([float(point[0]), float(point[1])])
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)
    return [np.asarray(run, dtype=float) for run in runs]


def _display_runs(points: np.ndarray) -> list[np.ndarray]:
    """显示折线 → 互不相连的可见段（NaN/Inf 处断开，渲染器在那里断笔迹）。"""
    if bool(np.all(np.isfinite(points))):
        return [np.asarray(points, dtype=float)]
    return _finite_runs(points)


def _path_subpolylines(path: Any) -> list[np.ndarray]:
    """把一条 Path 拆成互不相连的子折线（MOVETO 断开，曲线转直线段）。

    段与段**绝不**连成一条假折线 —— 两条独立笔迹被连起来会让净空/碰撞测量对着
    一条根本不存在的连线说话。返回顶点在 path 自身坐标系里。
    """
    try:
        cleaned = path.cleaned(curves=False, simplify=False)
    except Exception:
        return []
    verts = np.asarray(cleaned.vertices, dtype=float)
    if verts.size == 0:
        return []
    codes = cleaned.codes
    if codes is None:
        return [verts] if len(verts) >= 2 else []
    out: list[np.ndarray] = []
    current: list[Any] = []
    start: Optional[np.ndarray] = None
    for vertex, code in zip(verts, codes):
        if code == _MplPath.MOVETO:
            if len(current) >= 2:
                out.append(np.asarray(current, dtype=float))
            current = [vertex]
            start = vertex
        elif code == _MplPath.LINETO:
            current.append(vertex)
        elif code == _MplPath.CLOSEPOLY:
            if len(current) >= 2 and start is not None:
                current.append(start)
    if len(current) >= 2:
        out.append(np.asarray(current, dtype=float))
    return out


_OFFSET_POLYLINE_LIMIT = 4096   # path×offset 组合上限：超过就如实报不可测，不爆炸也不假装测全


def _marker_stroke_px(coll: Any, mm_per_px: float) -> float:
    """标记描边带来的可见墨迹外扩（px）= 最大线宽的一半。

    线宽逐元素不同时取最大值（保守上界），绝不拿平均值冒充「这个标记的半径」。
    """
    getter = getattr(coll, 'get_linewidth', None)
    if not callable(getter) or not mm_per_px:
        return 0.0
    try:
        widths = np.asarray(getter(), dtype=float).reshape(-1)
    except Exception:
        return 0.0
    widths = widths[np.isfinite(widths)]
    if widths.size == 0:
        return 0.0
    return float(widths.max()) * PT_TO_MM / 2.0 / mm_per_px


def _affine_bbox(matrix: np.ndarray, box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """矩形过仿射后的轴对齐包围盒（四角变换取 min/max：对仿射精确、对任意形状保守）。"""
    corners = np.array([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]])
    moved = corners @ matrix[:2, :2].T + matrix[:2, 2]
    return (float(moved[:, 0].min()), float(moved[:, 1].min()),
            float(moved[:, 0].max()), float(moved[:, 1].max()))


def _marker_envelope(coll: Any, paths: Sequence[Any], offset_trf: Any, offsets: Any,
                     mm_per_px: float, clip_rect: Optional[tuple]) -> dict[str, Any]:
    """标记字形集合的**保守可见包围盒**（mm），拿不到就如实说明原因。

    渲染器画的是「逐标记 3×3 源矩阵 × 字形 path，再加上该标记的渲染器坐标」；这里只算
    这些字形外接框的并集 + 半线宽外扩，再裁进坐标框 —— 是**保守包络**，不是精确轮廓，
    更不是中心线几何（绝不把 offset 连成折线）。字形并集先算、再按位置平移，所以组合
    规模是 字形×矩阵 + 位置，不是三者的笛卡尔积。矩阵/变换不可用时报不可测，不编假框。
    """
    get_transforms = getattr(coll, 'get_transforms', None)
    if not callable(get_transforms):
        return {'envelope_bounds_mm': None,
                'envelope_reason': '集合没有 get_transforms，标记字形不可测'}
    try:
        matrices = np.asarray(get_transforms(), dtype=float)
    except Exception as exc:
        return {'envelope_bounds_mm': None, 'envelope_reason': f'标记源矩阵不可用：{exc!r}'}
    if matrices.size == 0:
        matrices = np.eye(3)[None, :, :]      # 没有逐标记矩阵：字形按原样绘制
    if matrices.ndim != 3 or matrices.shape[1:] != (3, 3):
        return {'envelope_bounds_mm': None,
                'envelope_reason': f'标记源矩阵不是 3×3 仿射矩阵（shape={matrices.shape}）'}
    if len(paths) * len(matrices) > _OFFSET_POLYLINE_LIMIT:
        return {'envelope_bounds_mm': None,
                'envelope_reason': f'字形×矩阵组合 {len(paths) * len(matrices)} 超过上限 '
                                    f'{_OFFSET_POLYLINE_LIMIT}，不假装测全'}
    try:
        placed = np.asarray(offset_trf.transform(np.asarray(offsets, dtype=float)), dtype=float)
    except Exception as exc:
        return {'envelope_bounds_mm': None, 'envelope_reason': f'标记位置变换失败：{exc!r}'}
    if placed.ndim != 2 or placed.shape[1] != 2:
        return {'envelope_bounds_mm': None, 'envelope_reason': '标记位置不是 N×2 坐标'}
    placed = placed[np.all(np.isfinite(placed), axis=-1)]
    if len(placed) == 0:
        return {'envelope_bounds_mm': None, 'envelope_reason': '标记位置为空/非有限'}

    boxes: list[tuple[float, float, float, float]] = []
    for path in paths:
        try:
            ext = path.get_extents()
            box = (float(ext.x0), float(ext.y0), float(ext.x1), float(ext.y1))
        except Exception as exc:
            return {'envelope_bounds_mm': None, 'envelope_reason': f'字形外接框失败：{exc!r}'}
        if not all(np.isfinite(box)):
            return {'envelope_bounds_mm': None, 'envelope_reason': '字形外接框非有限'}
        boxes.extend(_affine_bbox(matrix, box) for matrix in matrices)

    note = ('标记字形外接框的并集 + 半线宽外扩，再裁进坐标框：**保守可见包络**，'
            '不是精确轮廓、也不是中心线几何（用集合当前的标记源矩阵 —— matplotlib 在每次'
            '绘制时按图形 dpi 刷新它）')
    stroke = _marker_stroke_px(coll, mm_per_px)
    x0 = min(b[0] for b in boxes) + float(placed[:, 0].min()) - stroke
    x1 = max(b[2] for b in boxes) + float(placed[:, 0].max()) + stroke
    y0 = min(b[1] for b in boxes) + float(placed[:, 1].min()) - stroke
    y1 = max(b[3] for b in boxes) + float(placed[:, 1].max()) + stroke
    if clip_rect is not None:
        x0, y0 = max(x0, float(clip_rect[0])), max(y0, float(clip_rect[1]))
        x1, y1 = min(x1, float(clip_rect[2])), min(y1, float(clip_rect[3]))
        if x1 < x0 or y1 < y0:
            return {'envelope_bounds_mm': None, 'envelope_reason': '标记字形全部落在坐标框外',
                    'envelope_note': note}
    return {'envelope_bounds_mm': [x0 * mm_per_px, y0 * mm_per_px, x1 * mm_per_px, y1 * mm_per_px],
            'envelope_basis': 'marker_glyph_bbox_union_plus_half_stroke_clipped',
            'envelope_note': note, 'marker_count': int(len(placed))}


def _collection_geometry(coll: Any, mm_per_px: float, clip_rect: Optional[tuple] = None) -> dict[str, Any]:
    """集合的显示几何：多段折线（段不连）+ 诚实状态。

    数据空间的 path（LineCollection / 数据坐标的 PathCollection / PolyCollection）用
    `get_transform()`（= 数据→显示）逐段变换；offset 在数据空间时逐份平移。标记字形
    （scatter：path 在设备单位、transform=Identity）不是数据显示几何 —— 报 UNSUPPORTED，
    不拿字形冒充数据曲线。
    """
    get_paths = getattr(coll, 'get_paths', None)
    if not callable(get_paths):
        return {'collection_geometry': 'UNSUPPORTED',
                'collection_geometry_reason': '集合没有 get_paths，无法取显示几何'}
    try:
        paths = [p for p in (get_paths() or ()) if p is not None]
    except Exception as exc:
        return {'collection_geometry': 'UNSUPPORTED',
                'collection_geometry_reason': f'get_paths() 失败：{exc!r}'}
    if not paths:
        if type(coll) is matplotlib.collections.LineCollection:
            # A plain empty LineCollection (e.g. colorbar dividers) draws no paths.
            # Unknown subclasses may draw independently and remain unsupported.
            return {'collection_geometry': 'MEASURED', 'polylines_mm': [],
                    'collection_segments': 0, 'geometry_bounds_mm': None,
                    'collection_geometry_basis': 'empty LineCollection paths'}
        return {'collection_geometry': 'UNSUPPORTED',
                'collection_geometry_reason': '集合没有 path'}
    try:
        transform = coll.get_transform()
        offset_trf = coll.get_offset_transform()
        offsets = coll.get_offsets() if hasattr(coll, 'get_offsets') else None
    except Exception as exc:
        return {'collection_geometry': 'UNSUPPORTED',
                'collection_geometry_reason': f'取变换失败：{exc!r}'}
    if isinstance(transform, matplotlib.transforms.IdentityTransform):
        # 标记字形在标记单位里（scatter 的 master transform 就是 Identity），不是数据显示
        # 几何：中心线几何如实 UNSUPPORTED，但渲染器真会画出来的字形给一个保守可见包络。
        envelope = _marker_envelope(coll, paths, offset_trf, offsets, mm_per_px, clip_rect)
        reason = 'path 不在数据坐标系（标记字形/设备单位），不作为数据显示几何'
        if envelope.get('envelope_bounds_mm') is None and envelope.get('envelope_reason'):
            reason = f'{reason}；{envelope["envelope_reason"]}'
        return {'collection_geometry': 'UNSUPPORTED', 'collection_geometry_reason': reason,
                **envelope}

    polylines: list[np.ndarray] = []
    for path in paths:
        for poly in _path_subpolylines(path):
            polylines.append(np.asarray(transform.transform(poly), dtype=float))

    offsets_arr = None
    if offsets is not None:
        try:
            offsets_arr = np.asarray(offsets, dtype=float)
        except Exception:
            offsets_arr = None
    if (offsets_arr is not None and offsets_arr.size > 0
            and not isinstance(offset_trf, matplotlib.transforms.IdentityTransform)):
        try:
            off_disp = np.asarray(offset_trf.transform(offsets_arr), dtype=float)
        except Exception as exc:
            return {'collection_geometry': 'UNSUPPORTED',
                    'collection_geometry_reason': f'offset 变换失败：{exc!r}'}
        if len(off_disp) == 0:
            return {'collection_geometry': 'UNSUPPORTED',
                    'collection_geometry_reason': 'offset 变换为空'}
        if len(polylines) * len(off_disp) > _OFFSET_POLYLINE_LIMIT:
            return {'collection_geometry': 'UNSUPPORTED',
                    'collection_geometry_reason': f'path×offset 组合 {len(polylines) * len(off_disp)} '
                                                  f'超过上限 {_OFFSET_POLYLINE_LIMIT}，不假装测全'}
        polylines = [poly + off for poly in polylines for off in off_disp]

    if any(not bool(np.isfinite(poly).all()) for poly in polylines):
        return {'collection_geometry': 'UNMEASURED',
                'collection_geometry_reason': 'non-finite display geometry; cannot prove visible bounds'}

    if clip_rect is not None:
        clipped = []
        for poly in polylines:
            clipped.extend(_clip_polyline_runs(poly, clip_rect))
        polylines = clipped

    if not polylines:
        return {'collection_geometry': 'MEASURED', 'polylines_mm': [], 'collection_segments': 0,
                'geometry_bounds_mm': None,
                'collection_geometry_reason': '可见几何为空（全部落在坐标框外）'}
    # 显示几何先在 px 里做（变换/裁剪/offset 都在 px），最后**恰好换算一次**成 mm：
    # polylines_mm 与 geometry_bounds_mm 必须来自同一份 mm 折线，不能一个 mm 一个 px。
    polys_mm = [_points_mm(poly, mm_per_px) for poly in polylines]
    bounds = _union([[min(p[0] for p in poly), min(p[1] for p in poly),
                      max(p[0] for p in poly), max(p[1] for p in poly)] for poly in polys_mm])
    return {'collection_geometry': 'MEASURED', 'polylines_mm': polys_mm,
            'collection_segments': len(polys_mm), 'geometry_bounds_mm': bounds,
            'collection_geometry_basis': 'display_transform_of_paths（中心线；段与段不相连）'}


def _baseline_mm(artist: Any, bbox: Any, renderer: Any, mm_per_px: float) -> tuple[Optional[float], Optional[str]]:
    """文字的 baseline 锚点（毫米）。只在字体度量可测且未旋转时给出。"""
    if not isinstance(artist, matplotlib.text.Text):
        return None, None
    try:
        if abs(float(artist.get_rotation() or 0.0)) > 0.0:
            return None, None
        from matplotlib.text import Text as _Text
        text = artist.get_text()
        try:
            is_math = _Text.is_math_text(text)
        except Exception:
            is_math = '$' in text
        width, height, descent = renderer.get_text_width_height_descent(
            text, artist.get_fontproperties(), is_math)
    except Exception:
        return None, None
    if not descent or not all(isinstance(v, (int, float)) for v in (width, height, descent)):
        return None, None
    baseline = (float(bbox.y0) + float(descent)) * mm_per_px
    return (baseline, 'font_metrics_descent') if np.isfinite(baseline) else (None, None)


def _image_payload(artist: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {'scientific': True}
    try:
        payload['shape'] = [int(n) for n in artist.get_array().shape]
    except Exception:
        payload['shape'] = None
    figure_image = isinstance(artist, matplotlib.image.FigureImage)
    extent_key = 'extent_figure_pixels' if figure_image else 'extent_data'
    payload['coordinate_reference'] = 'figure_dpi_pixels' if figure_image else 'axes_data'
    try:
        payload[extent_key] = [float(v) for v in artist.get_extent()]
    except Exception:
        payload[extent_key] = None
    try:
        payload['interpolation'] = str(artist.get_interpolation())
    except Exception:
        pass
    return payload


def _axis_draw_visibility(fig: matplotlib.figure.Figure,
                          axes: Sequence[matplotlib.axes.Axes]) -> dict[int, bool]:
    """Use the renderer's axis draw eligibility, not Text.get_visible alone.

    AutoLocator retains off-view tick Text with visible=True. Axis.draw skips
    those ticks through _update_ticks; measuring their extents as displayed
    content would invent clipping/obstacles that are absent from the PNG.
    """
    parents = {id(child): parent for parent in axes for child in parent.child_axes}
    visibility: dict[int, bool] = {}
    for ax in axes:
        shown = bool(fig.get_visible())
        ancestor: matplotlib.axes.Axes | None = ax
        while ancestor is not None:
            shown = shown and bool(ancestor.get_visible())
            ancestor = parents.get(id(ancestor))
        for axis in (ax.xaxis, ax.yaxis):
            enabled = shown and bool(ax.axison) and bool(axis.get_visible())
            visibility[id(axis.label)] = enabled and bool(axis.label.get_visible())
            # Same selector used by Matplotlib Axis.draw, including nonlinear
            # transforms and its native view-boundary tolerance. No extra draw.
            drawn = {id(tick) for tick in getattr(axis, '_update_ticks')()} if enabled else set()
            for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                tick_drawn = enabled and id(tick) in drawn and bool(tick.get_visible())
                for label in (tick.label1, tick.label2):
                    visibility[id(label)] = tick_drawn and bool(label.get_visible())
    return visibility


def _semantic_facts(artist: Any, axes: Sequence[matplotlib.axes.Axes],
                    axes_ids: dict[int, str]) -> dict[str, Any]:
    """Same-capture role facts from Matplotlib membership, never labels or gids."""
    owner = next((ax for ax in axes
                  if artist is ax.xaxis.label or artist is ax.yaxis.label
                  or any(artist is title for title in
                         (ax.title, getattr(ax, '_left_title', None),
                          getattr(ax, '_right_title', None)))), None)
    role, axis = None, None
    if owner is not None:
        if artist is owner.xaxis.label:
            role, axis = 'axis.title', 'x'
        elif artist is owner.yaxis.label:
            role, axis = 'axis.title', 'y'
        else:
            role = 'axes.title'
    else:
        for ax in axes:
            if artist is ax.get_legend():
                owner, role = ax, 'legend'
                break
            legend = ax.get_legend()
            if legend is not None and any(artist is text for text in legend.get_texts()):
                owner, role = ax, 'legend'
                break
            for name, axis_obj in (('x', ax.xaxis), ('y', ax.yaxis)):
                ticks = (list(axis_obj.get_major_ticks()) + list(axis_obj.get_minor_ticks()))
                if any(artist is label for tick in ticks for label in (tick.label1, tick.label2)):
                    owner, role, axis = ax, 'axis.tick', name
                    break
            if owner is not None:
                break
    axes_id = axes_ids.get(id(owner)) if owner is not None else None
    if owner is None:
        context = 'unknown'
    elif any(owner in getattr(parent, 'child_axes', ()) for parent in axes):
        context = 'inset'
    elif getattr(owner, 'get_subplotspec', lambda: None)() is not None:
        context = 'root'
    else:
        context = 'unknown'
    return {'role': role, 'axis': axis, 'axes_id': axes_id,
            'axes_context': context, 'evidence': 'artist_identity' if role else 'unknown'}


def _artist_node(artist: Any, *, node_id: Optional[str], gid: Optional[str], scope: str, registered: bool,
                 renderer: Any, mm_per_px: Optional[float], registry: Optional[GidRegistry] = None,
                 descriptor: Optional[str] = None) -> dict[str, Any]:
    node: dict[str, Any] = {
        'id': node_id,
        'gid': gid,
        'registered': bool(registered),
        'type': _artist_kind(artist),
        'artist_type': type(artist).__name__,
        'scope': scope,
        'parent': None,
        'measured': False,
        'bounds_mm': None,
        'envelope_mm': None,
        'envelope_source': 'renderer_window_extent',
        'anchors': None,
        'polyline_mm': None,
        'editable': False,
        'editable_paths': [],
        'controlled_by': [],
        'path_source': None,
        'science_policy': 'UNCLASSIFIED',
    }
    if descriptor is not None:
        node['descriptor'] = descriptor
    if registered and registry is not None:
        meta = registry.meta_of(gid)
        if meta.get('type'):
            node['type'] = _semantic_type(meta['type'], artist)
        node['params'] = registry.params_of(gid)
    if hasattr(artist, 'get_visible'):
        node['visible'] = bool(artist.get_visible())
    if hasattr(artist, 'get_clip_on'):
        try:
            node['clip_on'] = bool(artist.get_clip_on())
        except Exception:
            pass

    text = None
    if isinstance(artist, matplotlib.text.Text):
        text = str(artist.get_text())
        node['text'] = text
        node['is_text'] = True
        try:
            node['rotation_deg'] = float(artist.get_rotation() or 0.0)
        except Exception:
            pass
        if hasattr(artist, 'get_fontsize'):
            try:
                node['font_size_pt'] = float(artist.get_fontsize())
            except Exception:
                pass
        node['precise'] = False
    elif hasattr(artist, 'get_xydata'):
        node['is_text'] = False
        node['precise'] = True
        try:
            node['point_count'] = int(len(artist.get_xdata()))
        except Exception:
            pass
    else:
        node['is_text'] = False
        node['precise'] = True
        # 只有真正的图像图元才是「非精确的栅格包围盒」；集合的 get_array() 是**颜色**数组，
        # 不是图像像素 —— 集合的精确性由它自己的显示几何（中心线/多段）决定。
        if isinstance(artist, _IMAGE_ARTIST_TYPES):
            node['image'] = _image_payload(artist)
            node['precise'] = False

    # 集合（LineCollection / PathCollection / PatchCollection …）：几何是多段折线，段与段
    # 绝不连接。渲染器不在场时如实标未测量，不填 0、不静默跳过。
    is_collection = callable(getattr(artist, 'get_paths', None))
    if is_collection:
        node['collection_geometry'] = 'UNMEASURED'
        node['polylines_mm'] = None

    # 可见笔迹的出处：中心线折线 + 实测线宽/端点帽/折角/标记。
    # 精确「中心线距离」不等于「可见笔迹净空」，消费方需要这些字段自己判断。
    # 集合的线宽可能是**逐元素数组**：常量就给单值，逐个不同就原样携带、不猜平均值
    # （没有统一的半径外扩模型，geometry 的描边模型会据此拒绝）。
    if hasattr(artist, 'get_linewidth'):
        try:
            widths = np.asarray(artist.get_linewidth(), dtype=float).reshape(-1)
        except Exception:
            widths = None
        if widths is not None and widths.size:
            if widths.min() == widths.max():
                node['linewidth_pt'] = float(widths[0])
                node['linewidth_mm'] = node['linewidth_pt'] * PT_TO_MM
                node['stroke_radius_mm'] = node['linewidth_mm'] / 2.0
            else:
                node['linewidth_pt_per_element'] = [float(v) for v in widths]
    for attr, key in (('get_solid_capstyle', 'solid_capstyle'),
                      ('get_solid_joinstyle', 'solid_joinstyle'),
                      ('get_marker', 'marker'),
                      ('get_linestyle', 'linestyle')):
        getter = getattr(artist, attr, None)
        if getter is None:
            continue
        try:
            value = getter()
        except Exception:
            continue
        if isinstance(value, (list, tuple)):
            # 自定义 dash 序列不是实线：只留类型标记，交给 geometry 拒绝，不猜具体墨迹
            value = 'custom'
        node[key] = str(value)

    if renderer is None or mm_per_px is None:
        return node

    clip_box = None
    if node.get('clip_on') and getattr(artist, 'axes', None) is not None:
        try:
            clip_box = artist.axes.get_window_extent(renderer)
        except Exception:
            clip_box = None
    clip_rect = None
    if clip_box is not None:
        clip_rect = (float(clip_box.x0), float(clip_box.y0),
                     float(clip_box.x1), float(clip_box.y1))

    bbox = None
    if isinstance(artist, matplotlib.image.FigureImage):
        # FigureImage inherits a zero bbox: use its uncropped figure-pixel footprint.
        if float(getattr(renderer, 'dpi', artist.figure.dpi)) == float(artist.figure.dpi):
            bbox = geometry.figure_image_bbox(artist)
        node['envelope_source'] = 'figure_image_pixels'
    elif hasattr(artist, 'get_window_extent'):
        try:
            bbox = artist.get_window_extent(renderer)
        except Exception:
            bbox = None
    if bbox is not None and _to_mm(bbox, mm_per_px) is not None:
        visible = bbox
        if clip_box is not None:
            ix0 = max(float(bbox.x0), float(clip_box.x0))
            iy0 = max(float(bbox.y0), float(clip_box.y0))
            ix1 = min(float(bbox.x1), float(clip_box.x1))
            iy1 = min(float(bbox.y1), float(clip_box.y1))
            node['clipped_to_axes'] = True
            if ix1 < ix0 or iy1 < iy0:
                node['fully_clipped'] = True
                visible = None
            else:
                class _Box:
                    x0, y0, x1, y1 = ix0, iy0, ix1, iy1
                    width = ix1 - ix0
                    height = iy1 - iy0
                visible = _Box()
        node['measured'] = True
        if visible is not None:
            bounds = _to_mm(visible, mm_per_px)
            baseline, baseline_source = _baseline_mm(artist, visible, renderer, mm_per_px)
            node['bounds_mm'] = bounds
            node['envelope_mm'] = list(bounds)
            node['anchors'] = _anchors_from_bounds(bounds, baseline=baseline)
            if baseline_source:
                node['baseline_source'] = baseline_source

    if hasattr(artist, 'get_xydata') and hasattr(artist, 'get_transform'):
        try:
            xy = artist.get_xydata()
            if xy is not None and len(xy) > 0:
                displayed = artist.get_transform().transform(xy)
                finite = _display_runs(displayed)         # NaN 断口先断开，再谈裁剪
                if clip_rect is None:
                    runs = finite
                else:
                    node['polyline_clipped'] = True
                    runs = [piece for run in finite
                            for piece in _clip_polyline_runs(run, clip_rect)]
                    node['polyline_runs'] = len(runs)
                if len(runs) == 1:
                    node['polyline_mm'] = _points_mm(runs[0], mm_per_px)
                elif runs:
                    # 裁剪撕开或 NaN 断开的可见几何：绝不合成一条假折线，多段单独给出
                    node['polyline_mm'] = None
                    node['polylines_mm'] = [_points_mm(run, mm_per_px) for run in runs]
                node['polyline_basis'] = 'centerline'
        except Exception:
            node['polyline_mm'] = None

    if is_collection:
        geo = _collection_geometry(artist, mm_per_px, clip_rect)
        node.update(geo)
        if geo.get('collection_geometry') == 'MEASURED':
            # Collection.get_window_extent 对 LineCollection 会返回 inf 空框，不可用；
            # 显示几何的并集才是数据真值（中心线；线宽单独由 linewidth_mm 报出）。
            bounds = geo.get('geometry_bounds_mm')
            node['bounds_mm'] = list(bounds) if bounds is not None else None
            node['envelope_mm'] = list(bounds) if bounds is not None else None
            node['envelope_source'] = 'collection_display_geometry'
            node['anchors'] = _anchors_from_bounds(bounds) if bounds is not None else None
            node['measured'] = True
            if bounds is None:
                node['fully_clipped'] = True
            else:
                node.pop('fully_clipped', None)
        else:
            node['precise'] = False
            # 标记字形等没有中心线几何的集合：包围盒仍然实测（保守可见包络），
            # 但精确轮廓几何如实保持 UNSUPPORTED。
            bounds = geo.get('envelope_bounds_mm')
            if bounds is not None:
                node['measured'] = True
                node['bounds_mm'] = list(bounds)
                node['envelope_mm'] = list(bounds)
                node['envelope_source'] = geo.get('envelope_basis') or 'collection_conservative_envelope'
                node['envelope_note'] = geo.get('envelope_note')
                node['anchors'] = _anchors_from_bounds(bounds)
    if not node['measured'] or node.get('collection_geometry') == 'UNMEASURED':
        node['measured'] = False
        node['bounds_mm'] = None
        node['envelope_mm'] = None
        node['anchors'] = None
        node['geometry_reason'] = (node.get('collection_geometry_reason')
                                   or 'renderer extent is unavailable or non-finite')
    return node


def _infer_scope_from_gid(gid: str) -> Optional[str]:
    """按仓库既有 gid 约定取作用域：`fig<name>.<scope>.<kind>.<id>` 的第二段。

    只认 `fig…` 开头的 gid（与 `figpact.qa._scope_from_objects` 同一约定）。
    一个注册表跨多个作用域（compare 图的两格）时，靠它才不会把两格标成同一个
    作用域 —— gid 里的点在这里只用来取作用域，**绝不**用于精确路径映射。
    """
    parts = str(gid).split('.')
    if len(parts) >= 3 and parts[0].lower().startswith('fig') and parts[1] and not parts[1][0].isdigit():
        return parts[1]
    return None


def _contract_meta(contract: Optional[dict], gid: str) -> dict[str, Any]:
    if not contract:
        return {}
    nodes_meta = contract.get('nodes') or {}
    if isinstance(nodes_meta, dict):
        meta = nodes_meta.get(gid)
        return dict(meta) if isinstance(meta, dict) else {}
    return {}


def _contract_groups(contract: Optional[dict]) -> list[dict[str, Any]]:
    groups = (contract or {}).get('groups') or []
    return [g for g in groups if isinstance(g, dict) and g.get('id')]


def _contract_records(contract: Optional[dict]) -> list[dict[str, Any]]:
    recs = (contract or {}).get('parameters') or []
    return [r for r in recs if isinstance(r, dict)]


def _contract_path_map(records: Sequence[dict[str, Any]], known: set[str]) -> dict[str, list[list[str]]]:
    """契约参数记录 → {gid: [精确路径数组]}，只收已注册对象。"""
    out: dict[str, list[list[str]]] = {}
    for rec in records:
        path = [str(seg) for seg in (rec.get('path') or ())]
        if not path:
            continue
        for gid in rec.get('objects') or ():
            if gid not in known:
                continue
            paths = out.setdefault(gid, [])
            if path not in paths:
                paths.append(path)
    return out


def _node_paths(gid: str, registry: GidRegistry, contract_paths: dict[str, list[list[str]]]) \
        -> tuple[list[list[str]], str]:
    """节点的受控路径与来源：契约与注册表**显式声明**的精确路径取并集。

    只有参数名（`params`）时返回空路径 + 'unresolved_params' —— 名字不是路径，
    可能来自 dict 控件或本身带点，编一条出来就等于向查询声称了一个没建立的映射。
    """
    paths: list[list[str]] = []
    sources: list[str] = []
    for path in contract_paths.get(gid) or ():
        if list(path) not in paths:
            paths.append(list(path))
    if paths:
        sources.append('contract')
    declared = registry.declared_paths_of(gid)
    if declared:
        sources.append('registry')
    for path in declared:
        if list(path) not in paths:
            paths.append(list(path))
    if not paths:
        # 参数名不是已验证的精确 YAML 路径：宁可留空并上报未解析，也不编一条映射出来
        return [], 'unresolved_params'
    return paths, '+'.join(sources)


def snapshot(fig: matplotlib.figure.Figure, registry: GidRegistry, *, scope: str, revision: str = '',
             contract: Optional[dict] = None, draw: bool = True) -> dict[str, Any]:
    """对一个输出作用域取快照（一个作用域可以有多个 Axes，别按 Axes 数推作用域数）。

    返回 {revision, scope, unit, coordinate_reference, measurement, nodes, relations,
    parameter_index, containment, diagnostics}。`draw=False` 时不重绘，只用当前渲染器。
    """
    scope = str(scope)
    diagnostics: list[dict[str, Any]] = []

    def diag(kind: str, message: str, ids: Optional[Sequence[Any]] = None,
             severity: str = 'warning') -> None:
        diagnostics.append({'kind': kind, 'severity': severity, 'message': message,
                            'ids': [i for i in (ids or ()) if i is not None]})

    def collection_diag(node: dict[str, Any]) -> None:
        """集合几何不可测就如实上报（UNMEASURED/UNSUPPORTED），不静默跳过、不填 0。"""
        status = node.get('collection_geometry')
        if status == 'UNSUPPORTED':
            extra = '（只有保守包络，没有中心线/轮廓几何）' if node.get('measured') else '未测量'
            diag('COLLECTION_GEOMETRY_UNSUPPORTED',
                 f'{node["id"]}（{node["type"]}）集合显示几何{extra}：'
                 f'{node.get("collection_geometry_reason") or "无可测几何"}', [node.get('id')])
        elif status == 'UNMEASURED':
            diag('COLLECTION_GEOMETRY_UNMEASURED',
                 f'{node["id"]}（{node["type"]}）集合几何未测量（渲染器/变换不可用），不填占位数值',
                 [node.get('id')])

    if draw:
        try:
            fig.canvas.draw()
        except Exception as exc:
            diag('RENDER_FAILED', f'绘制失败，几何可能不完整：{exc!r}', severity='blocking')

    renderer, renderer_error = _resolve_renderer(fig)
    dpi = float(getattr(renderer, 'dpi', None) or fig.dpi)
    mm_per_px = _mm_per_px(dpi) if renderer is not None else None
    if renderer is None:
        diag('UNMEASURED_GEOMETRY', f'{renderer_error}：节点只报告未测量状态，不填占位数值',
             severity='blocking')

    measurement: dict[str, Any] = {
        'unit': 'mm',
        'coordinate_reference': 'canvas_bottom_left',
        'dpi': dpi,
        'figure_dpi': float(fig.dpi),
        'renderer': type(renderer).__name__ if renderer is not None else None,
        'renderer_available': renderer is not None,
        'font_environment': _font_environment(),
        # 本引擎不做任何物理标定：envelope/baseline 是渲染器栅格量（换 dpi/渲染器就可能变），
        # polyline 是显示变换上的数学结果。这里只声明每个量的**来源**，不声称已标定。
        'calibrated': False,
        'basis': {
            'envelope': 'renderer_window_extent（轴对齐包围盒，旋转文字更保守）',
            'figure_image': 'figure_dpi_pixels（未裁切；renderer DPI 必须与 Figure 一致）',
            'baseline': 'font_metrics_descent（仅未旋转文字）',
            'polyline': 'display_transform_of_data（中心线，数学精确；裁剪断成多段时逐段给出、'
                        '段间无连线；不含线宽/端点帽，可见笔迹更粗）',
            'marker_envelope': 'marker_glyph_bbox_union_plus_half_stroke_clipped（标记字形的'
                               '保守可见包络；不是精确轮廓，也不是中心线几何）',
            'stroke': 'linewidth_mm / linestyle / 端点帽 / 折角实测；method=stroke_segment '
                      '给出的是**数学模型**（中心线 ⊖ 半径和，圆头圆角实线）的精确值，'
                      '不是标定过的渲染墨迹（虚线/标记/非圆头一律拒绝，不猜）',
        },
    }

    nodes: list[dict[str, Any]] = []
    node_by_id: dict[str, dict[str, Any]] = {}
    canvas_id = f'{scope}::canvas'

    canvas_bounds = None
    if renderer is not None:
        canvas_bounds = _to_mm(fig.bbox, mm_per_px)
    canvas_node = {
        'id': canvas_id, 'gid': None, 'registered': False, 'type': 'figure',
        'artist_type': 'Figure', 'scope': scope, 'parent': None, 'measured': canvas_bounds is not None,
        'bounds_mm': canvas_bounds, 'envelope_mm': canvas_bounds,
        'envelope_source': 'figure_bbox', 'anchors': _anchors_from_bounds(canvas_bounds) if canvas_bounds else None,
        'polyline_mm': None, 'editable': False, 'editable_paths': [], 'controlled_by': [],
        'path_source': 'structural', 'science_policy': 'UNCLASSIFIED', 'structural': True,
    }
    nodes.append(canvas_node)
    node_by_id[canvas_id] = canvas_node

    panel_ids: dict[int, str] = {}
    panel_bounds: list[dict[str, Any]] = []
    registered_axes = {id(artist): gid for gid, artist in registry.all().items()
                       if isinstance(artist, matplotlib.axes.Axes)}
    all_axes = list(fig.axes)
    index = 0
    while index < len(all_axes):
        for child in getattr(all_axes[index], 'child_axes', ()):
            if all(id(child) != id(ax) for ax in all_axes):
                all_axes.append(child)
        index += 1
    axes_ids = {id(ax): registered_axes.get(id(ax), f'{scope}::panel.{i}')
                for i, ax in enumerate(all_axes)}
    axis_visibility = _axis_draw_visibility(fig, all_axes)
    for index, ax in enumerate(all_axes):
        panel_id = axes_ids[id(ax)]
        panel_ids[id(ax)] = panel_id
        if id(ax) in registered_axes:
            continue
        bounds = None
        if renderer is not None:
            try:
                bounds = _to_mm(ax.get_window_extent(renderer), mm_per_px)
            except Exception:
                bounds = None
        panel = {
            'id': panel_id, 'gid': ax.get_gid(), 'registered': bool(ax.get_gid()), 'type': 'panel',
            'artist_type': type(ax).__name__,
            'scope': scope, 'parent': canvas_id, 'measured': bounds is not None,
            'bounds_mm': bounds, 'envelope_mm': bounds, 'envelope_source': 'axes_window_extent',
            'anchors': _anchors_from_bounds(bounds) if bounds else None, 'polyline_mm': None,
            'editable': False, 'editable_paths': [], 'controlled_by': [], 'path_source': 'structural',
            'science_policy': 'UNCLASSIFIED', 'structural': True,
        }
        nodes.append(panel)
        node_by_id[panel_id] = panel
        panel_bounds.append(panel)

    groups = _contract_groups(contract)
    group_of: dict[str, str] = {}
    group_parent: dict[str, Optional[str]] = {}
    for group in groups:
        for member in group.get('members') or ():
            if member in group_of:
                diag('MULTIPLE_GROUP_MEMBERSHIP',
                     f'{member} 同时属于 {group_of[member]!r} 与 {group["id"]!r}，按先声明的分组归属',
                     [member])
                continue
            group_of[member] = str(group['id'])
        group_parent[str(group['id'])] = group.get('parent')

    # 已注册图元节点
    records = _contract_records(contract)
    contract_paths = _contract_path_map(records, set(registry.all()))
    editable_paths = {tuple(r.get('path') or ()) for r in records
                      if str(r.get('mutability') or '').upper() == 'EDITABLE' and r.get('path')}
    for gid, artist in registry.all().items():
        meta = registry.meta_of(gid)
        cmeta = _contract_meta(contract, gid)
        node_scope = (cmeta.get('scope') or meta.get('scope') or _infer_scope_from_gid(gid)
                      or registry.scope or scope)
        node = _artist_node(artist, node_id=gid, gid=gid, scope=str(node_scope),
                            registered=True, renderer=renderer, mm_per_px=mm_per_px,
                            registry=registry)
        node['semantic'] = _semantic_facts(artist, all_axes, axes_ids)
        if id(artist) in axis_visibility:
            node['artist_visible'] = node.get('visible')
            node['visible'] = axis_visibility[id(artist)]
            node['visibility_source'] = 'matplotlib_native_axis_draw_filter'
        node['controlled_by'], node['path_source'] = _node_paths(gid, registry, contract_paths)
        if node['path_source'] == 'unresolved_params' and node['params']:
            node['unresolved_bindings'] = list(node['params'])
            diag('UNRESOLVED_PARAMETER_BINDING',
                 f'{gid} 只有参数名 {node["params"]}，不是已验证的精确 YAML 路径：'
                 f'controlled_by 留空、editable=false，需用 contract/register 显式绑定',
                 [gid])
        parent = cmeta.get('parent') or meta.get('parent')
        if parent is None:
            parent = group_of.get(gid)
        if parent is None and not isinstance(artist, matplotlib.axes.Axes) \
                and getattr(artist, 'axes', None) is not None:
            parent = panel_ids.get(id(artist.axes))
        node['parent'] = parent or canvas_id
        policy = cmeta.get('science_policy') or meta.get('science_policy')
        node['science_policy'] = str(policy) if policy else 'UNCLASSIFIED'
        declared_editable = cmeta.get('editable', meta.get('editable'))
        node['editable_paths'] = [list(p) for p in node['controlled_by'] if tuple(p) in editable_paths]
        if declared_editable is None:
            node['editable'] = bool(node['editable_paths'])
        else:
            node['editable'] = bool(declared_editable)
        if cmeta.get('type'):
            node['type'] = _semantic_type(cmeta['type'], artist)
        if not node['measured']:
            diag('UNMEASURED_GEOMETRY', f'{gid} 的几何未测量：{node.get("geometry_reason") or "渲染器/字体环境不可用"}',
                 [gid], severity='blocking')
        collection_diag(node)
        if isinstance(artist, matplotlib.axes.Axes):
            node['structural'] = True
            node['envelope_source'] = 'axes_window_extent'
            panel_bounds.append(node)
        nodes.append(node)
        node_by_id[gid] = node

    # 可见但未注册的图元：仍然是节点，仍然进 QA 风险清单
    for index, entry in enumerate(registry.unregistered_artists(fig)):
        unreg_id = f'{scope}::unregistered.{index}'
        node = _artist_node(entry['artist'], node_id=unreg_id, gid=None, scope=scope, registered=False,
                            renderer=renderer, mm_per_px=mm_per_px, descriptor=entry['descriptor'])
        node['semantic'] = _semantic_facts(entry['artist'], all_axes, axes_ids)
        if id(entry['artist']) in axis_visibility:
            node['artist_visible'] = node.get('visible')
            node['visible'] = axis_visibility[id(entry['artist'])]
            node['visibility_source'] = 'matplotlib_native_axis_draw_filter'
        if not node['measured']:
            diag('UNMEASURED_GEOMETRY', f'{unreg_id} 的几何无法测量', [unreg_id],
                 severity='blocking')
        node['parent'] = panel_ids.get(id(getattr(entry['artist'], 'axes', None))) or canvas_id
        collection_diag(node)
        nodes.append(node)
        node_by_id[unreg_id] = node
        diag('UNREGISTERED_VISIBLE',
             f'可见但未注册：{entry["descriptor"]}（QA 仍需检查，注册表未覆盖）', [unreg_id])

    # 分组节点（成员包围盒的并集**只是结构包络**，不是可见轮廓）
    for group in groups:
        group_id = str(group['id'])
        members = [m for m in (group.get('members') or ()) if m in node_by_id]
        bounds = _union([node_by_id[m]['bounds_mm'] for m in members])
        parent = group_parent.get(group_id) or canvas_id
        node = {
            'id': group_id, 'gid': None, 'registered': False, 'type': 'group',
            'artist_type': None, 'scope': scope,
            'parent': parent, 'measured': bounds is not None, 'bounds_mm': bounds,
            'envelope_mm': bounds, 'envelope_source': 'union_of_members',
            'anchors': _anchors_from_bounds(bounds) if bounds else None, 'polyline_mm': None,
            'editable': False, 'editable_paths': [], 'controlled_by': [], 'path_source': 'structural',
            'science_policy': 'UNCLASSIFIED', 'structural': True,
            'group': {'members': members, 'missing': [m for m in (group.get('members') or ()) if m not in node_by_id]},
        }
        nodes.append(node)
        node_by_id[group_id] = node
        for missing in node['group']['missing']:
            diag('DANGLING_REFERENCE', f'分组 {group_id!r} 的成员 {missing!r} 未注册', [missing])

    # 两向精确路径映射：节点路径 → 对象（注册顺序）。关系映射与本索引共用同一份，
    # 所以 objects_of_path(path) 与 node['controlled_by'] 必然互为逆映射。
    path_objects: dict[tuple[str, ...], list[str]] = {}
    for gid in registry.all():
        for path in node_by_id[gid]['controlled_by']:
            path_objects.setdefault(tuple(path), []).append(gid)
    parameter_index = [{'path': list(key), 'objects': list(path_objects[key])} for key in path_objects]

    # 关系
    relations: list[dict[str, Any]] = []
    for rec in (contract or {}).get('relations') or ():
        if not isinstance(rec, dict):
            continue
        rel_id = rec.get('id')
        kind = str(rec.get('kind') or '')
        objects = list(rec.get('objects') or ())
        missing = [g for g in objects if g not in node_by_id]
        if missing:
            for gid in missing:
                diag('DANGLING_REFERENCE', f'关系 {rel_id!r} 引用了未注册对象 {gid!r}', [gid])
        selected = [node_by_id[g] for g in objects if g in node_by_id]
        axis = rec.get('axis')
        if axis is not None and axis not in ('x', 'y', 'both'):
            diag('INVALID_RELATION', f'关系 {rel_id!r} 的 axis 非法：{axis!r}', [rel_id])
            axis = None
        tolerance = rec.get('tolerance_mm')
        if missing:
            measured = {'relation': kind, 'objects': objects, 'unit': 'mm',
                        'coordinate_reference': 'canvas_bottom_left', 'axis': axis, 'anchor': rec.get('anchor'),
                        'method': rec.get('method'), 'status': 'UNSUPPORTED', 'value_mm': None,
                        'precision': 'envelope', 'calibrated': False, 'uncertainty_mm': None,
                        'tolerance_mm': tolerance, 'within_tolerance': None,
                        'notes': [f'引用对象未注册：{missing}']}
        else:
            try:
                measured = geometry.measure_relation(kind, selected, axis=axis, anchor=rec.get('anchor'),
                                                     method=rec.get('method'), tolerance_mm=tolerance)
            except Exception as exc:
                measured = {'relation': kind, 'objects': objects, 'unit': 'mm',
                            'coordinate_reference': 'canvas_bottom_left', 'axis': axis,
                            'anchor': rec.get('anchor'), 'method': rec.get('method'),
                            'status': 'UNSUPPORTED', 'value_mm': None, 'precision': 'envelope',
                            'calibrated': False, 'uncertainty_mm': None, 'tolerance_mm': tolerance,
                            'within_tolerance': None, 'notes': [f'测量异常：{exc!r}']}

        controlled = [list(p) for p in (rec.get('controlled_by') or ())]
        move = list(rec.get('move') or ())
        for moved in move:
            if moved not in node_by_id:
                diag('DANGLING_REFERENCE', f'关系 {rel_id!r} 的 move 含未注册对象 {moved!r}', [moved])
        options = []
        for path in controlled:
            resolved = path_objects.get(tuple(path))
            if resolved:
                options.append({'path': list(path), 'objects': list(resolved)})
            else:
                diag('DANGLING_REFERENCE', f'关系 {rel_id!r} 的受控路径 {path!r} 没有解析到任何已注册对象',
                     [rel_id])
        if not controlled:
            mapping = {'status': 'UNSUPPORTED', 'reason': '关系未声明 controlled_by 精确路径', 'options': []}
        elif not options:
            mapping = {'status': 'UNSUPPORTED', 'reason': 'controlled_by 路径未解析到已注册对象', 'options': []}
        elif len(options) > 1:
            mapping = {'status': 'AMBIGUOUS', 'reason': '多条受控路径映射到不同对象，不做任意选择',
                       'options': options}
        else:
            mapping = {'status': 'EDITABLE', 'path': options[0]['path'], 'objects': options[0]['objects'],
                       'options': options}
        if mapping['status'] != 'EDITABLE':
            diag('UNSUPPORTED_RELATION' if mapping['status'] == 'UNSUPPORTED' else 'AMBIGUOUS_RELATION',
                 f'关系 {rel_id!r}：{mapping["reason"]}', [rel_id])
        if measured['status'] != 'OK':
            diag('UNSUPPORTED_MEASUREMENT',
                 f'关系 {rel_id!r} ({kind})：{"; ".join(measured.get("notes") or ["未测量"])}',
                 [rel_id] + [g for g in objects])

        relation = dict(measured)
        relation['id'] = rel_id
        relation['target_mm'] = rec.get('target_mm')
        relation['move'] = move
        relation['controlled_by'] = controlled
        relation['mapping'] = mapping
        if rec.get('target_mm') is not None and measured.get('value_mm') is not None:
            relation['delta_mm'] = float(measured['value_mm']) - float(rec['target_mm'])
        relations.append(relation)

    # 契约声明的对象必须真的注册过，否则如实上报悬空引用
    registered_ids = set(registry.gids())
    for rec in records:
        for gid in rec.get('objects') or ():
            if gid not in registered_ids:
                diag('DANGLING_REFERENCE',
                     f'契约参数 {rec.get("key")!r} 声明了未注册对象 {gid!r}', [gid])

    # 一个注册表可能跨多个作用域（compare 图两格共用一个 registry）：如实标出不属于
    # 本次请求作用域的节点，让调用方按作用域授权，而不是被静默混进来。
    out_of_scope = [node['id'] for node in nodes
                    if node['registered'] and node['scope'] != scope]
    for node_id in out_of_scope:
        owner = [n['scope'] for n in nodes if n['id'] == node_id][0]
        diag('OUT_OF_SCOPE_NODE',
             f'{node_id} 属于作用域 {owner!r}，不属于本次请求的 {scope!r}', [node_id])

    # 作用域包含性：以画布为容器，多 Axes（compare 图）也只是一格套一格
    containment: dict[str, Any] = {'canvas': canvas_id, 'overflow_mm': {}, 'outside': []}
    if canvas_bounds is not None:
        cx0, cy0, cx1, cy1 = canvas_bounds
        for node in nodes:
            if node['id'] == canvas_id or not node['measured'] or node['bounds_mm'] is None:
                continue
            x0, y0, x1, y1 = node['bounds_mm']
            overflow = max(x1 - cx1, cx0 - x0, y1 - cy1, cy0 - y0)
            containment['overflow_mm'][node['id']] = float(overflow)
            if overflow > 0.0:
                containment['outside'].append(node['id'])
        for node_id in containment['outside']:
            diag('OUTSIDE_CANVAS', f'{node_id} 超出画布 {containment["overflow_mm"][node_id]:.3f} mm',
                 [node_id])

    return {
        'revision': str(revision),
        'scope': scope,
        'unit': 'mm',
        'coordinate_reference': 'canvas_bottom_left',
        'measurement': measurement,
        'nodes': nodes,
        'relations': relations,
        'parameter_index': parameter_index,
        'containment': containment,
        'out_of_scope': out_of_scope,
        'diagnostics': diagnostics,
    }


def inspect(snapshot: dict[str, Any], *, ids: Optional[Sequence[str]] = None, name: Optional[str] = None,
            type: Optional[str] = None, scope: Optional[str] = None) -> dict[str, Any]:
    """按 id/名字/类型/作用域过滤快照，并给出邻居、关系、参数与测量环境。"""
    nodes = snapshot.get('nodes') or []
    wanted = set(ids) if ids is not None else None

    def matches(node: dict[str, Any]) -> bool:
        if wanted is not None and node.get('id') not in wanted:
            return False
        if scope is not None and node.get('scope') != scope:
            return False
        if type is not None and str(node.get('type')) != type:
            return False
        if name is not None:
            haystack = ' '.join(str(node.get(key) or '') for key in ('id', 'text', 'descriptor'))
            if name not in haystack:
                return False
        return True

    selected = [n for n in nodes if matches(n)]
    by_id = {n.get('id'): n for n in nodes}
    selected_ids = {n.get('id') for n in selected}

    children: dict[Any, list[Any]] = {}
    for node in nodes:
        if node.get('parent') is not None:
            children.setdefault(node['parent'], []).append(node.get('id'))

    neighbors = {}
    for node in selected:
        neighbors[node.get('id')] = {
            'parent': by_id.get(node.get('parent'), {}).get('id') if node.get('parent') in by_id else node.get('parent'),
            'children': list(children.get(node.get('id'), ())),
            'siblings': [n for n in children.get(node.get('parent'), ()) if n != node.get('id')]
            if node.get('parent') in children else [],
        }

    relations = [r for r in snapshot.get('relations') or ()
                 if selected_ids & {o for o in (r.get('objects') or ()) if o is not None}]
    parameters = [p for p in snapshot.get('parameter_index') or ()
                  if selected_ids & {o for o in (p.get('objects') or ()) if o is not None}]
    diagnostics = [d for d in snapshot.get('diagnostics') or ()
                   if selected_ids & set(d.get('ids') or ())]

    return {
        'count': len(selected),
        'nodes': selected,
        'neighbors': neighbors,
        'relations': relations,
        'parameters': parameters,
        'diagnostics': diagnostics,
        'measurement': snapshot.get('measurement'),
        'scope': snapshot.get('scope'),
        'revision': snapshot.get('revision'),
    }
