"""只读 Inspector：同一帧的真实 PNG 缓冲 + Scene 几何投影 + 安全导出。

契约锁定（G1）：
  - 捕获复用现有 `scene.snapshot(..., draw=False)`：只让**一个** Agg 渲染器真实 draw 一次，
    PNG 取自该渲染器的像素缓冲（Pillow 编码），绝不 savefig/print_png 重绘可变的 Artist；
  - 临时挂到 Figure 上的 Agg canvas 在成功与失败两条路径上都归还原始 canvas；
  - 渲染器错误 / 阻塞级未测量是显式失败，绝不用 0 几何充数；
  - 科学载荷守卫复用 `science.capture_science`（它不 draw）：捕获前后受保护图元载荷
    变化即拒绝出帧 —— 这是 artist 载荷守卫，不宣称 STRICT 验证；
  - `identity_stability`：注册 gid = `stable`（登记声明），其余一律 `ephemeral`（帧内临时）；
  - 导出自建只读目录，拒绝任何已存在路径（含符号链接）与源码/前端/测试目录内的目标，
    失败只清理自己新建的文件；`frame.js` 只是数据，标题/标签文本永不拼进 HTML。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import pathlib
import shutil
from typing import Any, Optional

from matplotlib.backends.backend_agg import FigureCanvasAgg
from PIL import Image

from figpact import scene, science
from figpact.registry import GidRegistry
from figpact.units import MM_PER_INCH

FRAME_SCHEMA = 'figpact.inspector/1'
SCENE_SCHEMA = 'figpact.inspector.scene/1'
EDITABLE_CAPABILITY = 'READ_ONLY'

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent
_FRONTEND_DIR = _PACKAGE_DIR / '_inspector'
_FALLBACK_FRONTEND = _REPO_ROOT / 'tools' / 'inspector'
if not _FRONTEND_DIR.is_dir() and _FALLBACK_FRONTEND.is_dir():
    _FRONTEND_DIR = _FALLBACK_FRONTEND
# 导出目标落在这些源码/前端/测试目录内一律拒绝：绝不让导出写坏仓库文件。
_GUARDED_DIRS = (_PACKAGE_DIR, _REPO_ROOT / 'tools', _REPO_ROOT / 'tests')

# 可建模的连接线型：其余（None/自定义序列）一律不当连接线，绝不给幽灵中心线命中。
_STANDARD_LINESTYLES = frozenset({'-', '--', '-.', ':'})
_NO_MARKERS = frozenset({'', 'none', 'nonetype'})
# 渲染器包络才允许命中：文字/图例/图像/面板/figure/group；shape/artist/collection 一律不猜。
_ENVELOPE_TYPES = frozenset({'text', 'legend', 'image', 'panel', 'figure', 'group'})
# 确定性命中优先级：结构 figure/group 沉底，面板是背景，曲线/引线最前。其它按候选顺序轮换。
_HIT_PRIORITY = {'curve': 0, 'guide': 0, 'collection': 0,
                 'text': 10, 'legend': 10, 'image': 10,
                 'panel': 50, 'figure': 100, 'group': 100}


class InspectorError(RuntimeError):
    """Inspector 捕获/导出的显式失败（渲染器错误、科学载荷变化、不安全导出目标等）。"""


def _scope_of(scope: Any) -> str:
    text = str(scope or '').strip()
    if not text:
        raise InspectorError('scope 不能为空：输出作用域是快照的身份，不允许省略')
    return text


def _source_revision_of(source_revision: Any) -> Optional[str]:
    if source_revision is None:
        return None
    text = str(source_revision)
    return text or None


def _canvas_bounds_mm(scene_snapshot: dict, scope: str) -> list[float]:
    canvas_id = f'{scope}::canvas'
    for node in scene_snapshot.get('nodes') or ():
        if node.get('id') == canvas_id:
            bounds = node.get('bounds_mm')
            if bounds is not None:
                return [float(v) for v in bounds]
    raise InspectorError(f'{canvas_id} 的逻辑画布边界未测量：没有渲染器就不能定位 PNG')


def _runs_mm(node: dict) -> Optional[list[list[list[float]]]]:
    """scene 的单折线/多折线统一成 runs_mm：段与段保持互不相连。"""
    polyline = node.get('polyline_mm')
    if polyline is not None:
        return [polyline]
    polylines = node.get('polylines_mm')
    if polylines:
        return [list(run) for run in polylines]
    return None


def _connecting_linestyle(node: dict) -> bool:
    value = node.get('linestyle')
    return isinstance(value, str) and value.strip() in _STANDARD_LINESTYLES


def _marker_drawn(node: dict) -> bool:
    marker = node.get('marker')
    return isinstance(marker, str) and marker.strip().lower() not in _NO_MARKERS


def _stroke_of(node: dict) -> dict:
    """命中用的描边事实：中心线 ± 半径的**保守**模型，从不声称实测墨迹。"""
    stroke = {
        'linewidth_mm': node.get('linewidth_mm'),
        'linestyle': node.get('linestyle'),
        'solid_capstyle': node.get('solid_capstyle'),
        'ink_model': 'conservative_centerline_plus_radius',
        'exact_ink': False,
    }
    limits: list[str] = []
    if node.get('linestyle') != '-':
        limits.append('虚线段落之间没有墨迹：命中区域比可见墨迹大（保守）')
    if _marker_drawn(node):
        limits.append('标记墨迹超出「中心线 ± 半径」模型，未建模')
    capstyle = node.get('solid_capstyle')
    if isinstance(capstyle, str) and capstyle != 'butt':
        limits.append('端点帽墨迹超出线段端点，未建模')
    if limits:
        stroke['limitation'] = '；'.join(limits)
    return stroke


def _hit_mode_of(node: dict, runs) -> str:
    if not node.get('measured') or node.get('fully_clipped'):
        return 'none'
    if node.get('collection_geometry') in ('UNMEASURED', 'UNSUPPORTED'):
        return 'none'
    if runs and _connecting_linestyle(node):
        return 'stroke'
    if runs is None and node.get('bounds_mm') is not None \
            and node.get('type') in _ENVELOPE_TYPES:
        return 'envelope'
    return 'none'


def _hit_note_of(node: dict, runs) -> Optional[str]:
    geometry = node.get('collection_geometry')
    if geometry == 'UNSUPPORTED':
        return node.get('collection_geometry_reason') or '集合显示几何不可测'
    if geometry == 'UNMEASURED':
        return '集合几何未测量：不填占位数值，命中不可用'
    if node.get('fully_clipped'):
        return '完全裁掉：没有可见几何'
    if not node.get('measured'):
        return '未测量：没有几何'
    if runs and not _connecting_linestyle(node):
        return '没有连接线（marker-only / 自定义线型）：只能列表选择，不做中心线命中'
    if runs is None and node.get('measured') and node.get('type') not in _ENVELOPE_TYPES:
        return '没有可命中的线段或渲染器包络：只能列表选择'
    return None


def _project_node(node: dict) -> dict:
    """scene 节点 → Inspector 投影：身份命名、运行段、命中模式，事实原样、不补几何。"""
    runs = _runs_mm(node)
    node_type = node.get('type')
    hit_mode = _hit_mode_of(node, runs)
    projected = {
        'id': node.get('id'),
        'gid': node.get('gid'),
        'registered': bool(node.get('registered')),
        'identity_stability': 'stable' if node.get('registered') else 'ephemeral',
        'type': node_type,
        'artist_type': node.get('artist_type'),
        'text': node.get('text'),
        'descriptor': node.get('descriptor'),
        'scope': node.get('scope'),
        'parent': node.get('parent'),
        'measured': bool(node.get('measured')),
        'fully_clipped': bool(node.get('fully_clipped')),
        'bounds_mm': node.get('bounds_mm'),
        'anchors': node.get('anchors'),
        'runs_mm': runs,
        'stroke': _stroke_of(node) if hit_mode == 'stroke' else None,
        'hit_mode': hit_mode,
        'hit_priority': _HIT_PRIORITY.get(node_type, 30),
        'linewidth_mm': node.get('linewidth_mm'),
        'linestyle': node.get('linestyle'),
        'marker': node.get('marker'),
        'solid_capstyle': node.get('solid_capstyle'),
        'controlled_by': [list(path) for path in (node.get('controlled_by') or ())],
        'science_policy': node.get('science_policy'),
        'editable_capability': EDITABLE_CAPABILITY,
        'structural': bool(node.get('structural')),
    }
    note = _hit_note_of(node, runs)
    if note:
        projected['hit_note'] = note
    for key in ('envelope_source', 'rotation_deg'):
        if key in node:
            projected[key] = node[key]
    return projected


def _png_bytes(canvas, renderer) -> tuple[bytes, int, int]:
    """从**这一个**渲染器的像素缓冲编码 PNG（Pillow），不做第二次绘制。"""
    width_px, height_px = canvas.get_width_height()
    raw = bytes(renderer.buffer_rgba())
    if width_px <= 0 or height_px <= 0 or len(raw) != width_px * height_px * 4:
        raise InspectorError(
            f'Agg 像素缓冲与画布尺寸不一致：{width_px}x{height_px} px 需要 '
            f'{width_px * height_px * 4} 字节，实际 {len(raw)} 字节')
    image = Image.frombytes('RGBA', (width_px, height_px), raw)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue(), width_px, height_px


def _peak_anchors(science_manifest) -> dict:
    """清单里显式声明的 label→guide 峰锚点；没有就空，绝不从 gid 字符串猜。"""
    if not isinstance(science_manifest, dict):
        return {}
    science_part = science_manifest.get('science')
    if not isinstance(science_part, dict):
        return {}
    protected = science_part.get('protected')
    if not isinstance(protected, dict):
        return {}
    peak_anchors = protected.get('peak_anchors')
    return peak_anchors if isinstance(peak_anchors, dict) else {}


def _displayed_endpoints(guide: dict):
    """本帧实测的引线首末端点（mm，canvas_bottom_left）。"""
    runs = guide.get('runs_mm')
    if not runs or not runs[0] or not runs[-1]:
        return None
    return [list(runs[0][0]), list(runs[-1][-1])]


def _apply_manifest_links(scene_dict: dict, science_manifest) -> None:
    """按清单声明把 label ↔ guide 连起来；声明的科学锚点与本帧显示端点分开标注。"""
    anchors = _peak_anchors(science_manifest)
    if not anchors:
        return
    nodes = {node['id']: node for node in scene_dict['nodes']}
    diagnostics = scene_dict['diagnostics']
    for label_gid, record in anchors.items():
        if not isinstance(record, dict):
            continue
        guide_gid = record.get('guide_gid')
        if not isinstance(guide_gid, str) or not guide_gid:
            diagnostics.append({
                'kind': 'INSPECTOR_ANNOTATION_UNRESOLVED', 'severity': 'warning',
                'message': f'清单记录 {label_gid!r} 没有 guide_gid：不做任何推断',
                'ids': [label_gid]})
            continue
        label = nodes.get(label_gid)
        guide = nodes.get(guide_gid)
        missing = [gid for gid, node in ((label_gid, label), (guide_gid, guide)) if node is None]
        if missing:
            diagnostics.append({
                'kind': 'INSPECTOR_ANNOTATION_UNRESOLVED', 'severity': 'warning',
                'message': f'清单声明的引线/标签 {missing} 不在本帧：联动只按真实测量对象给出',
                'ids': missing})
        if guide is not None:
            endpoints = _displayed_endpoints(guide)
            guide['annotation'] = {
                'kind': 'guide_relationship',
                'linked_label_gid': label_gid,
                'assignment': record.get('assignment'),
                'declared_exact_ppm': record.get('exact_ppm'),
                'declared_guide_anchor_data': record.get('guide_anchor_data'),
                'displayed_first_run_endpoint_mm': endpoints[0] if endpoints else None,
                'displayed_last_run_endpoint_mm': endpoints[1] if endpoints else None,
                'independent_endpoint_editable': False,
                'note': '声明锚点是原始科学量（ppm / a.u.），displayed 端点是本帧实测毫米；'
                        '两者不是一回事，分别标注；只读界面不能独立拖端点',
            }
        if label is not None:
            label['linked_guide_gid'] = guide_gid


def _settle_native_aspect(fig, registry, science_manifest) -> None:
    """Settle the native equal-aspect view window before the science baseline.
    Sankey-style axes (``aspect=1.0``, ``adjustable='datalim'``) leave a pre-aspect
    window after ``finish()``; the first ``draw()`` rewrites ``xlim``/``ylim`` through
    the native ``Axes.apply_aspect`` lifecycle step (renderer-independent, no draw) and
    the window is then stable. Settling that one step up front lets the guard compare
    settled science against settled science. Narrow by construction:
    - only axes whose ``apply_aspect`` is the unoverridden native implementation run;
      an overridden/custom ``apply_aspect`` (3D, user subclass, monkeypatch) is left
      alone and the figure keeps the old fail-closed behavior below;
    - settlement failures raise ``InspectorError`` with cause, never swallowed;
    - only ``panel.*:view`` records may move during settlement: any other protected
      record changing (e.g. an ``xlim_changed`` callback mutating line/wedge data)
      raises ``InspectorError`` instead of being laundered into the baseline.
    """
    import matplotlib.axes as _mpl_axes

    native = _mpl_axes.Axes.apply_aspect
    # Instance-dict monkeypatches count as overridden too: the instance attribute is
    # read off the instance (instance dict shadows the class), so a per-figure test
    # double can never slip past this check into the settle call below.
    targets = [axes for axes in (getattr(fig, 'axes', None) or [])
               if axes.get_aspect() != 'auto' and axes.get_adjustable() == 'datalim'
               and getattr(getattr(axes, 'apply_aspect', None), '__func__', None) is native]
    if not targets:
        return
    presettle = science.capture_science(fig, registry, declarations=science_manifest)
    for axes in targets:
        try:
            native(axes)
        except Exception as exc:
            raise InspectorError(f'等比坐标结算失败，拒绝出帧：{exc!r}') from exc
    settled = science.capture_science(fig, registry, declarations=science_manifest)
    before_objects = presettle.get('objects', {})
    after_objects = settled.get('objects', {})
    intruders = sorted(key for key in set(before_objects) | set(after_objects)
                       if before_objects.get(key) != after_objects.get(key)
                       and not key.endswith(':view'))
    if intruders:
        raise InspectorError('等比坐标结算改变了视图窗口之外的受保护科学载荷，拒绝出帧：'
                             + ','.join(intruders))
    if presettle.get('declarations') != settled.get('declarations'):
        raise InspectorError('等比坐标结算改变了科学声明，拒绝出帧：science_manifest')


def capture_figure(fig, registry=None, *, scope='measurement', contract=None,
                   science_manifest=None, source_revision=None) -> dict:
    """对一个真实 Matplotlib Figure 取只读帧：一次 draw 的 PNG + 同一帧 Scene 几何。

    返回 bundle（schema 'figpact.inspector/1'）：`png_base64`/`png_sha256` 是这一次渲染
    的像素，`scene_json`/`scene_sha256` 是同一状态的 canonical JSON，三处 revision 一致。
    """
    registry = registry if registry is not None else GidRegistry()
    scope = _scope_of(scope)
    _settle_native_aspect(fig, registry, science_manifest)
    before = science.capture_science(fig, registry, declarations=science_manifest)

    original_canvas = getattr(fig, 'canvas', None)
    canvas = FigureCanvasAgg(fig)
    try:
        try:
            canvas.draw()                            # 唯一一次真实绘制
        except Exception as exc:
            raise InspectorError(f'渲染器 draw 失败：{exc!r}') from exc
        renderer = canvas.get_renderer()
        snapshot = scene.snapshot(fig, registry, scope=scope, draw=False, contract=contract)
        png_bytes, width_px, height_px = _png_bytes(canvas, renderer)
    finally:
        # 临时挂上的 Agg canvas 在成功与失败两条路径上都归还
        fig.canvas = original_canvas

    after = science.capture_science(fig, registry, declarations=science_manifest)
    changed = science.compare_science(before, after, label='（capture_figure）')
    if changed:
        raise InspectorError('受保护科学载荷在捕获过程中变化，拒绝出帧：'
                             + '；'.join(str(item.get('message')) for item in changed))
    blocking = [d for d in (snapshot.get('diagnostics') or ()) if d.get('severity') == 'blocking']
    if blocking:
        raise InspectorError('快照存在阻塞级未测量数据，拒绝出帧：'
                             + '；'.join(str(d.get('message')) for d in blocking))

    dpi = float(getattr(renderer, 'dpi', None) or fig.dpi)
    scene_dict: dict[str, Any] = {
        'schema': SCENE_SCHEMA,
        'scope': scope,
        'source_revision': _source_revision_of(source_revision),
        'unit': 'mm',
        'coordinate_reference': 'canvas_bottom_left',
        'canvas_bounds_mm': _canvas_bounds_mm(snapshot, scope),
        # 物理像素位置：真实缓冲尺寸与 renderer dpi，非整数字节时的取整与逻辑画布边界无关
        'image': {
            'width_px': width_px,
            'height_px': height_px,
            'bounds_mm': [0.0, 0.0, width_px * MM_PER_INCH / dpi, height_px * MM_PER_INCH / dpi],
        },
        'measurement': snapshot.get('measurement'),
        'nodes': [_project_node(node) for node in (snapshot.get('nodes') or ())],
        'diagnostics': list(snapshot.get('diagnostics') or ()),
    }
    _apply_manifest_links(scene_dict, science_manifest)
    try:
        scene_json = json.dumps(scene_dict, sort_keys=True, ensure_ascii=True,
                                separators=(',', ':'), allow_nan=False)
    except ValueError as exc:
        raise InspectorError(f'canonical scene JSON 需要有限数值，拒绝出帧：{exc}') from exc
    scene_sha256 = hashlib.sha256(scene_json.encode('utf-8')).hexdigest()
    png_sha256 = hashlib.sha256(png_bytes).hexdigest()
    frame_revision = hashlib.sha256(f'{png_sha256}\n{scene_sha256}'.encode('ascii')).hexdigest()
    return {
        'schema': FRAME_SCHEMA,
        'frame_revision': frame_revision,
        'image_revision': frame_revision,
        'geometry_revision': frame_revision,
        'png_base64': base64.b64encode(png_bytes).decode('ascii'),
        'png_sha256': png_sha256,
        'scene_json': scene_json,
        'scene_sha256': scene_sha256,
    }


def _refuse_unsafe_target(target: pathlib.Path) -> None:
    absolute = pathlib.Path(os.path.abspath(target))
    if os.path.lexists(absolute):
        raise InspectorError(
            f'导出目录已存在（含符号链接）：{target} —— Inspector 只写自己新建的目录，'
            f'绝不覆盖任何已有文件或科学产物')
    absolute = absolute.resolve()
    for guarded in _GUARDED_DIRS:
        if absolute == guarded or guarded in absolute.parents:
            raise InspectorError(
                f'拒绝把导出目标放在源码/前端/测试目录内：{target}（{guarded} 之下）')


def _frontend_assets() -> list[pathlib.Path]:
    directory = _FRONTEND_DIR
    if not directory.is_dir():
        raise InspectorError(f'前端资源目录不存在：{directory}（包内 figpact/_inspector 未提供）')
    assets = [directory / name for name in ('index.html', 'inspector.js', 'inspector.css')]
    missing = [path.name for path in assets if not path.is_file()]
    if missing:
        raise InspectorError(f'前端资源不完整：{missing}')
    return assets


def export_inspector(fig, output_dir, registry=None, *, scope='measurement', contract=None,
                     science_manifest=None, source_revision=None) -> pathlib.Path:
    """导出只读 Inspector 站点到**全新**目录，返回 index.html 路径。

    顺序是先拒绝不安全目标、先取帧，再 mkdir 写文件；中途失败只删自己新建的文件，
    已存在的用户路径一个字节都不动。`frame.js` 是纯数据（JSON.parse 的 bundle），
    index.html 等前端资源原样复制，标题/标签文本绝不拼进 HTML。
    """
    target = pathlib.Path(os.path.abspath(output_dir))
    _refuse_unsafe_target(target)

    assets = _frontend_assets()
    names = [asset.name for asset in assets]
    if 'index.html' not in names:
        raise InspectorError(f'前端资源缺少 index.html：{sorted(names)}')
    if 'frame.js' in names:
        raise InspectorError('前端资源里不得自带 frame.js：该文件由导出的帧数据独占')

    bundle = capture_figure(fig, registry, scope=scope, contract=contract,
                            science_manifest=science_manifest, source_revision=source_revision)
    payload = json.dumps(bundle, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    # frame.js 只是数据：JSON.parse 的参数是 JSON 字符串字面量；`<`/`>`/`&` 一律转义，
    # 这样即使有人把 frame.js 内联进 HTML，标签文本也不会咬断 script 元素。
    literal = json.dumps(payload)
    for char in ('&', '<', '>'):
        literal = literal.replace(char, f'\\u{ord(char):04x}')
    frame_js = f'window.FIGPACT_INSPECTOR_FRAME = JSON.parse({literal});\n'

    created: list[pathlib.Path] = []
    owns_directory = False
    try:
        target.mkdir(parents=True)
        owns_directory = True
        frame_path = target / 'frame.js'
        with frame_path.open('xb') as stream:
            created.append(frame_path)
            stream.write(frame_js.encode('utf-8'))
        for asset in assets:
            destination = target / asset.name
            with asset.open('rb') as source, destination.open('xb') as stream:
                created.append(destination)
                shutil.copyfileobj(source, stream)
    except BaseException:
        if owns_directory:
            for path in created:
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                target.rmdir()
            except OSError:
                pass
        raise
    return target / 'index.html'
