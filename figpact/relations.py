"""Measure and adjust physical relations without touching scientific coordinates."""
import math
from figpact.transform import apply_display_shift
from figpact.units import MM_PER_INCH


def measure_relation(kind, object_a, object_b, unit='mm'):
    if unit != 'mm':
        raise ValueError('Only physical millimeters are supported')
    if object_a.figure is not object_b.figure:
        raise ValueError('Objects must belong to the same Figure')
    fig = object_a.figure
    renderer = fig.canvas.get_renderer()
    if kind == 'vertical_clearance':
        a = object_a.get_window_extent(renderer)
        b = object_b.get_window_extent(renderer)
        value = b.y0 - a.y1
    elif kind == 'baseline_pitch':
        value = (object_b.get_transform().transform(object_b.get_xydata())[0, 1]
                 - object_a.get_transform().transform(object_a.get_xydata())[0, 1])
    else:
        raise ValueError(f'Unknown relation: {kind}')
    return float(value * MM_PER_INCH / fig.dpi)


def set_relation_target(*, kind, object_a, object_b, target_mm, move):
    if isinstance(target_mm, bool) or not isinstance(target_mm, (int, float)) or not math.isfinite(target_mm) or target_mm < 0:
        raise ValueError('target_mm must be a finite nonnegative number')
    move = tuple(move)
    if not any(a is object_b for a in move) or any(a is object_a for a in move):
        raise ValueError('Move the upper object and keep the lower object fixed')
    if any(a.figure is not object_a.figure for a in move):
        raise ValueError('Moved objects must belong to the same Figure')
    delta = target_mm - measure_relation(kind, object_a, object_b)
    moved = set()
    for artist in move:
        if id(artist) not in moved:
            apply_display_shift(artist, dy_mm=delta)
            moved.add(id(artist))
    return measure_relation(kind, object_a, object_b)


def remaining_space(fig, artists):
    """Signed space at each Axes edge. Negative values report overflow, not rescaling."""
    renderer = fig.canvas.get_renderer()
    result = []
    for ax in fig.axes:
        boxes = [a.get_window_extent(renderer) for a in artists if a.axes is ax]
        if not boxes:
            continue
        frame = ax.get_window_extent(renderer)
        scale = MM_PER_INCH / fig.dpi
        bottom = (min(b.y0 for b in boxes)-frame.y0)*scale
        top = (frame.y1-max(b.y1 for b in boxes))*scale
        result.append({'bottom_mm': float(bottom), 'top_mm': float(top),
                       'canvas_bottom_mm': float(min(b.y0 for b in boxes)*scale),
                       'canvas_top_mm': float((fig.bbox.y1-max(b.y1 for b in boxes))*scale),
                       'overflow_mm': float(max(0, -bottom, -top))})
    return result


def validate_layout(config, *, scopes, ids, parameter, reference_fields):
    from figpact.config import ConfigError
    for key in (parameter, 'group_y_mm', 'layout_reference'):
        values = config[key]
        if not isinstance(values, dict) or set(values) != set(scopes):
            raise ConfigError(f'{key} 必须完整列出作用域 {list(scopes)}')
    for scope in scopes:
        pairs = config[parameter][scope]
        reference = config['layout_reference'][scope]
        if not isinstance(pairs, dict) or set(pairs) != set(ids):
            raise ConfigError(f'{parameter}.{scope} 必须列出 {list(ids)}')
        if not isinstance(reference, dict) or set(reference) != set(reference_fields):
            raise ConfigError(f'layout_reference.{scope} 的只读几何记录无效')
        numbers = list(pairs.values()) + [config['group_y_mm'][scope]] + list(reference.values())
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in numbers):
            raise ConfigError('毫米间距和几何记录必须是有限数字')
        if any(n < 0 or n > 100 for n in pairs.values()):
            raise ConfigError('相邻间距必须在 0–100 mm')
        if abs(config['group_y_mm'][scope]) > 100 or reference['units_per_mm'] <= 0:
            raise ConfigError('整体位移超出 ±100 mm 或只读显示标尺无效')
