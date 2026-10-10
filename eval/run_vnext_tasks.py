#!/usr/bin/env python
"""P0–P3 验收运行器：真实执行 30 条任务语料，独立重建 Figure 并测量物理量。

用法（父进程在集成后跑一条命令即可）：

    python -X utf8 eval/run_vnext_tasks.py \
        --tasks eval/vnext_tasks.json \
        --report eval/vnext_acceptance_report.json

退出码：任何未达成的期望目标 / 被破坏的科学不变量 / 静默状态改动 / 伪造的验证等级
       / 新增 QA 阻断项 / 观察不到的必需量 → 非零。

设计铁律
--------
* **不预置结果**：每条记录的状态、实际验证等级、测量值、退出码全部来自真实运行。
  执行器自己不会“模拟”；任何拿不到的量就写 null（并在 verdict 里算失败），绝不填占位数。
* **独立重建**：候选图由探针子进程从落盘的候选 YAML 通过 `build_scene` 全量重建，
  与 B 的 warm 会话是完全不同的进程/代码路径。测量取真实 Artist 的 `bounds_mm` /
  折线 / 文本锚点，不采信会话内部的验证回执。
* **判定权在验收器**：探针只交原始观测（x0/y0/x1/y1、锚点、关系测量），
  期望值、容差、数量语义由本文件的 `evaluate_task` 施加。探针自报的 match 不被采信。
* **不是 Agent 基准**：这里的 "backend" 是确定性 YAML/进程重跑路径，
  没有 solver、没有逐题预演；普通 Agent 的实测结果只能通过 `--agent-trials`
  的外部记录进入报告：按 A/B/C 臂归组、带真实计时与请求原文，且每条都要被
  本验收器独立重建/渲染/QA/科学复核（负例则由原始夹具独立证明被拒）才计入。
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 允许直接以脚本方式运行
    sys.path.insert(0, str(ROOT))

SCHEMA = 'figpact.vnext.acceptance/1'
AGENT_SCHEMA = 'figpact.vnext.agent-trials/2'

#: 三条工作流臂。父代理必须逐条显式声明臂；本验收器不替记录猜臂。
ARMS = ('A', 'B', 'C')
#: 一条外部尝试要成为「可归属的实测记录」必须带的字段（缺一个就按不可用处理，绝不补默认值）。
TRIAL_REQUIRED_FIELDS = ('task_id', 'arm', 'agent', 'attempt', 'started_at', 'finished_at',
                         'wall_seconds', 'raw_request', 'raw_response')
#: 完整字段词典（原样出现在报告的 `field_spec` 里，供父代理按形状喂记录）。
TRIAL_FIELD_SPEC = {
    'task_id': '语料记录 id，必须能在 --tasks 里找到对应记录',
    'arm': f'工作流臂，显式取 {ARMS} 之一；正向候选 A 必须真的改了 Python，B/C 必须不动 Python',
    'agent': '执行这条尝试的 Agent 标识（原样记录，不做映射）',
    'attempt': '同一 (arm, task) 内的尝试序号，1 = 首次尝试，>1 计入 redo',
    'started_at': 'ISO-8601 真实开始时间（带时区）',
    'finished_at': 'ISO-8601 真实结束时间',
    'wall_seconds': '真实墙钟秒数，必须与两个时间戳一致（不一致 → 该臂不给效率说法）',
    'raw_request': 'Agent 实际发出的请求原文（字符串，或 {"path": "..."} 指向原始文件）',
    'raw_response': 'Agent 实际收到的应答原文（同上）',
    'candidate_config': '候选/诊断 YAML 路径；正向必给（要能独立重建），CONFIG_ERROR 负例给携带请求改动的'
                        '诊断 YAML 且必须落在仓库之外（不许碰可发布文件）；期望拒绝/无生效改动的任务可以不给',
    'candidate_script': '被 Agent 改过的 Python 脚本路径；A 的正向必给且必须与原始夹具不同，'
                        'B/C 与全部负例留空或与原始夹具一致',
    'source_fingerprint': '可选：记录声明的源码指纹，必须与独立重建实测一致',
    'diagnostic_only': 'CONFIG_ERROR 负例必须为 true：该 YAML 只是喂给守卫的诊断输入，不是可发布产物',
    'subject_decision': '真实回执 JSON 的 decision（CANDIDATE/REFUSED/DIAGNOSED/FAILED）；'
                        '必须与 raw_response 一致，不能用后端重放替 Agent 作答',
}

#: 与 figpact.session 的状态字面量同词表（这里写成字面量，验收器不依赖引擎可导入）。
STATUS_OK = 'OK'
STATUS_STALE = 'STALE_REVISION'
STATUS_CONFIG_ERROR = 'CONFIG_ERROR'
STATUS_REFUSED = 'REFUSED'
STATUS_DIAGNOSED = 'DIAGNOSED'
STATUS_ERROR = 'ERROR'

REFUSAL_STATUSES = (
    'LOCKED', 'UNCLASSIFIED', 'NOT_IN_SCOPE', 'FIXED_STYLE', 'DERIVED', 'OUT_OF_RANGE',
    'INVALID_VALUE', 'CONTRADICTORY', 'AMBIGUOUS', 'UNKNOWN_RELATION', 'UNSUPPORTED_RELATION',
    'UNSUPPORTED_PATH', 'GEOMETRY_REJECTED', 'SCIENCE_VIOLATION', 'QA_BLOCKED',
    'UNDECLARED_PARAMETER',
)

VERIFICATION_GEOMETRY = 'GEOMETRY_CHECKED'
VERIFICATION_RENDER = 'RENDER_CHECKED'
VERIFICATION_EFFECTS = 'EFFECTS_CHECKED'
#: 证据强度：渲染/重建级 → 强于几何快车道。期望 GEOMETRY 时 OBSERVED RENDER 是升级；
#: 期望 RENDER 时只报 GEOMETRY 属于「未经证明的快验证」，判失败。
VERIFICATION_STRENGTH = {None: 0, VERIFICATION_GEOMETRY: 1, VERIFICATION_RENDER: 2}

EXACT_TOL_MM = 1e-9     # 未声明容差时按精确相等（向量几何是数学精确的）

#: 每个不变量用哪些真实 Artist 载荷判定。未登记的不变量 **fail closed**（比全部载荷）。
INVARIANT_PAYLOAD_GROUPS = {
    'ftir.curve_arrays': ('lines',),
    'ftir.processing_chain': ('lines',),
    'ftir.band_windows': ('band_windows', 'texts', 'axis_windows'),
    'ftir.view_windows': ('axis_windows',),
    'ftir.stack_order': ('stack_order',),
    'nmr.spectrum_arrays': ('lines',),
    'nmr.peak_ppm_guides': ('peak_guides', 'texts'),
    'nmr.windows_unchanged': ('axis_windows',),
    'nmr.assignments_unchanged': ('texts',),
    'nmr.view_windows': ('axis_windows',),
    'panels.pixels_unchanged': ('images',),
    'panels.crop_window_unchanged': ('axis_windows', 'images'),
    'panels.aspect_unchanged': ('aspect',),
    'panels.scale_bar_meaning': ('scale_bars',),
    'panels.panel_order': ('panel_order',),
    'mixed.curve_arrays': ('lines',),
    'mixed.view_windows': ('axis_windows',),
    'mixed.image_pixels': ('images',),
    'mixed.image_crop': ('axis_windows', 'images'),
    'mixed.scale_bar_meaning': ('scale_bars',),
    'mixed.panel_gap_order': ('panel_order',),
}
#: 探针会采集的全部载荷组（供报告与 fail-closed 使用）。
PAYLOAD_GROUPS = ('lines', 'texts', 'axis_windows', 'images', 'aspect', 'scale_bars', 'rectangles',
                  'panel_order', 'stack_order', 'band_windows', 'peak_guides')

BOUNDS_QUANTITIES = ('size', 'min', 'max', 'center')


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def read_json(path) -> object:
    return json.loads(Path(path).read_text(encoding='utf8'))


def dump_json(path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + '\n',
                    encoding='utf8')


def quantile(samples, q: float):
    """真实样本的分位（无样本 → None，绝不外推）。"""
    values = sorted(float(s) for s in samples)
    if not values:
        return None
    if q <= 0:
        return values[0]
    if q >= 1:
        return values[-1]
    index = min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))
    return values[index]


def summarize_timings(samples):
    values = [float(s) for s in samples]
    if not values:
        return {'n': 0, 'min_s': None, 'median_s': None, 'p95_s': None, 'max_s': None, 'total_s': None}
    return {'n': len(values), 'min_s': min(values),
            'median_s': quantile(values, 0.5), 'p95_s': quantile(values, 0.95),
            'max_s': max(values), 'total_s': sum(values)}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _inside_repo(path) -> bool:
    try:
        Path(path).resolve().relative_to(ROOT)
    except (ValueError, OSError):
        return False
    return True


def _iso_seconds(text):
    """ISO-8601 → epoch 秒；解析不了就返回 None（绝不猜时间）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return datetime.datetime.fromisoformat(text.strip().replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _raw_evidence(value) -> dict:
    """Agent 请求/应答原文的证据摘要：inline 字符串，或 {"path": ...} 指向的原始文件。"""
    if isinstance(value, dict) and value.get('path') is not None:
        path = Path(value['path'])
        try:
            if not path.is_file():
                return {'present': False, 'source': 'path', 'path': str(path), 'reason': '原文文件不存在'}
            data = path.read_bytes()
        except OSError as error:
            return {'present': False, 'source': 'path', 'path': str(path),
                    'reason': f'{type(error).__name__}: {error}'}
        return {'present': bool(data.strip()), 'source': 'path', 'path': str(path),
                'sha256': sha256_bytes(data), 'bytes': len(data)}
    if isinstance(value, str):
        return {'present': bool(value.strip()), 'source': 'inline', 'chars': len(value),
                'sha256': sha256_bytes(value.encode('utf8'))}
    return {'present': False, 'source': None, 'reason': f'不支持的原文类型 {type(value).__name__}'}


def _wall_metadata(trial: dict) -> dict:
    """真实计时元数据：时间戳与声明的秒数必须互相印证，否则整条按「计时不可用」处理。"""
    started_raw = trial.get('started_at')
    finished_raw = trial.get('finished_at')
    wall = trial.get('wall_seconds')
    started = _iso_seconds(started_raw)
    finished = _iso_seconds(finished_raw)
    out = {'started_at': started_raw, 'finished_at': finished_raw, 'declared_seconds': wall,
           'derived_seconds': (finished - started) if (started is not None and finished is not None) else None,
           'available': False, 'reason': None}
    missing = [name for name, value in (('started_at', started_raw), ('finished_at', finished_raw),
                                        ('wall_seconds', wall)) if value in (None, '')]
    if missing:
        out['reason'] = f'缺少 {missing}'
        return out
    if not _finite(wall) or float(wall) <= 0:
        out['reason'] = 'wall_seconds 不是正的有限数'
        return out
    if out['derived_seconds'] is None:
        out['reason'] = '时间戳不是可解析的 ISO-8601'
        return out
    if out['derived_seconds'] < 0:
        out['reason'] = 'finished_at 早于 started_at'
        return out
    if abs(out['derived_seconds'] - float(wall)) > max(1.0, 0.01 * float(wall)):
        out['reason'] = f"wall_seconds 与时间戳不一致（声明 {wall}s，时间戳 {out['derived_seconds']}s）"
        return out
    out['available'] = True
    return out


# --------------------------------------------------------------------------- #
# 探针（同一文件以子进程运行：全新解释器、全新导入、从磁盘 YAML 全量重建）
# --------------------------------------------------------------------------- #

def _probe_load_module(script: Path):
    import importlib.util
    name = f'figpact_probe_{script.stem}'
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'无法从 {script} 载入探针模块')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _probe_node_view(node: dict) -> dict:
    polyline = node.get('polyline_mm')
    points = None
    if polyline is not None:
        try:
            points = int(len(polyline))
        except TypeError:
            points = None
    return {'id': node.get('id'), 'gid': node.get('gid'), 'type': node.get('type'),
            'parent': node.get('parent'), 'measured': bool(node.get('measured')),
            'bounds_mm': node.get('bounds_mm'), 'anchors': node.get('anchors'),
            'science_policy': node.get('science_policy'), 'editable': node.get('editable'),
            'polyline_points': points, 'registered': node.get('registered')}


def _probe_text_anchor_mm(artist, mm_per_px: float):
    import numpy as np
    try:
        position = artist.get_position()
        transform = artist.get_transform()
        display = transform.transform([position[0], position[1]])
        return [float(display[0]) * mm_per_px, float(display[1]) * mm_per_px]
    except Exception:
        return None


def _probe_payload(fig, reg, scope: str, contract: dict, *, counts: dict) -> dict:
    """真实 Artist 载荷（不变量判定）＋ 快照测量。"""
    import numpy as np
    from figpact import scene

    snap = scene.snapshot(fig, reg, scope=scope, contract=contract, draw=True)
    counts['snapshots'] = counts.get('snapshots', 0) + 1
    mm_per_px = 25.4 / float(snap['measurement'].get('dpi') or fig.dpi)

    nodes = {}
    for node in snap['nodes']:
        gid = node.get('gid')
        if gid:
            nodes[str(gid)] = node
    view = {gid: _probe_node_view(node) for gid, node in nodes.items()}

    lines, texts, images, scale_bars, text_anchors, aspects = {}, {}, {}, {}, {}, {}
    rectangles = {}
    for gid, artist in (reg.all() or {}).items():
        kind = type(artist).__name__
        if kind == 'Line2D':
            try:
                xs = np.asarray(artist.get_xdata(), dtype=float)
                ys = np.asarray(artist.get_ydata(), dtype=float)
                lines[gid] = {'n': int(xs.size), 'x': sha256_bytes(xs.tobytes()),
                              'y': sha256_bytes(ys.tobytes())}
            except Exception as error:
                lines[gid] = {'error': str(error)}
        elif kind == 'Text':
            try:
                texts[gid] = artist.get_text()
            except Exception as error:
                texts[gid] = f'<unreadable: {error}>'
            anchor = _probe_text_anchor_mm(artist, mm_per_px)
            if anchor is not None:
                text_anchors[gid] = anchor
        elif kind == 'LineCollection':
            try:
                segments = np.asarray(artist.get_segments(), dtype=float)
                lines[gid] = {'n': int(segments.shape[0]),
                              'segments': sha256_bytes(np.ascontiguousarray(segments).tobytes())}
            except Exception as error:
                lines[gid] = {'error': str(error)}
        elif kind in ('AxesImage', 'FigureImage') or hasattr(artist, 'get_array'):
            try:
                data = np.asarray(artist.get_array())
                images[gid] = {'shape': list(data.shape), 'pixels': sha256_bytes(np.ascontiguousarray(data).tobytes()),
                               'extent': [float(v) for v in (artist.get_extent() or [])],
                               'clim': [float(v) for v in artist.get_clim()]}
            except Exception as error:
                images[gid] = {'error': str(error)}
        elif kind in ('Rectangle', 'Polygon'):
            bb = view.get(gid, {}).get('bounds_mm')
            if bb:
                entry = {'dx_mm': float(bb[2]) - float(bb[0]),
                         'dy_mm': float(bb[3]) - float(bb[1])}
                rectangles[gid] = entry
                if 'scale_bar' in gid or 'scalebar' in gid:
                    scale_bars[gid] = dict(entry)
        elif kind == 'Axes':
            try:
                aspects[gid] = {'aspect': str(artist.get_aspect()),
                                'box_aspect': None if artist.get_box_aspect() is None
                                else float(artist.get_box_aspect())}
            except Exception:
                aspects[gid] = {'aspect': None, 'box_aspect': None}

    axis_windows = {}
    for index, ax in enumerate(fig.axes):
        key = ax.get_gid() or f'{scope}::panel.{index}'
        axis_windows[str(key)] = {'xlim': [float(v) for v in ax.get_xlim()],
                                  'ylim': [float(v) for v in ax.get_ylim()]}
    aspects.setdefault(f'{scope}::panels',
                       {'axes': [{'gid': ax.get_gid(), 'aspect': str(ax.get_aspect())}
                                 for ax in fig.axes]})

    band_windows = {}
    for gid, artist in (reg.all() or {}).items():
        if '.band.' not in f'.{gid}.':
            continue
        bb = view.get(gid, {}).get('bounds_mm')
        if bb:
            band_windows[gid] = [float(v) for v in bb]

    peak_guides = {}
    for gid, entry in lines.items():
        if 'guide' in gid or 'peak' in gid:
            peak_guides[gid] = entry

    measured = [(gid, node) for gid, node in nodes.items() if node.get('measured') and node.get('bounds_mm')]
    # 曲线堆叠顺序只看真实曲线（文本位移不该改「上下顺序」）。
    curves = [(gid, node) for gid, node in measured if '.curve.' in f'.{gid}.']
    stack_order = [gid for gid, _ in sorted(curves, key=lambda item: item[1]['bounds_mm'][1])]
    # 面板顺序只按面板（Axes）的行/列量化位置，不看绝对毫米。
    panels = [(gid, node) for gid, node in measured if node.get('type') == 'Axes']
    panel_order = [gid for gid, _ in sorted(
        panels, key=lambda item: (round(item[1]['bounds_mm'][1], 0), round(item[1]['bounds_mm'][0], 0)))]

    return {
        'nodes': view,
        'node_objects': nodes,
        'measurement': snap.get('measurement'),
        'snapshot_diagnostics': snap.get('diagnostics'),
        'payload': {'lines': lines, 'texts': texts, 'axis_windows': axis_windows, 'images': images,
                    'aspect': aspects, 'scale_bars': scale_bars, 'rectangles': rectangles,
                    'panel_order': panel_order,
                    'stack_order': stack_order, 'band_windows': band_windows, 'peak_guides': peak_guides},
        'text_anchors_mm': text_anchors,
    }


def _probe_measure_relations(facts, relations, requests):
    from figpact import geometry
    results = []
    for request in requests:
        if request.get('kind') != 'relation':
            results.append(None)
            continue
        rid = request.get('relation_id')
        rel = next((r for r in relations if r.get('id') == rid), None)
        if rel is None:
            results.append({'status': 'UNKNOWN_RELATION', 'value_mm': None,
                            'note': f'契约里没有关系 {rid!r}'})
            continue
        nodes = [facts['node_objects'].get(gid) for gid in (rel.get('objects') or [])]
        if any(node is None for node in nodes):
            results.append({'status': 'UNMEASURED', 'value_mm': None,
                            'note': f'关系 {rid} 的对象未在快照里出现'})
            continue
        ordered = [facts['node_objects'][gid] for gid in (rel.get('objects') or [])]
        outcome = geometry.measure_relation(
            rel.get('kind'), ordered, axis=rel.get('axis') or 'x',
            anchor=rel.get('anchor'), method=rel.get('method'))
        results.append({key: outcome.get(key) for key in
                        ('status', 'value_mm', 'relation', 'axis', 'anchor', 'method', 'precision',
                         'calibrated', 'uncertainty_mm', 'within_tolerance', 'notes')})
    return results


def probe_main(request_path: Path, response_path: Path) -> int:
    """探针入口：一次请求一个全新进程。异常一律落到应答里，绝不静默成功。"""
    counts = {'builds': 0, 'snapshots': 0, 'pngs': 0}
    payload = {'ok': False, 'error': None, 'traceback': None}
    try:
        os.environ.setdefault('MPLBACKEND', 'Agg')
        import matplotlib
        matplotlib.use('Agg')
        request = read_json(request_path)
        payload.update(probe_execute(request, counts))
        payload['ok'] = True
    except Exception as error:  # 探针自身的失败也是一种观测结果
        payload['error'] = f'{type(error).__name__}: {error}'
        payload['traceback'] = traceback.format_exc()
    payload['counts'] = counts
    dump_json(response_path, payload)
    return 0 if payload.get('ok') else 2


def probe_execute(request: dict, counts: dict) -> dict:
    import time
    import matplotlib.pyplot as plt

    script = Path(request['script'])
    scope = request['scope']
    mode = request.get('mode') or 'measure'
    module = _probe_load_module(script)
    baseline_module = module
    baseline_script = request.get('baseline_script')
    if baseline_script and Path(baseline_script).resolve() != script.resolve():
        baseline_module = _probe_load_module(Path(baseline_script).resolve())
    # 契约与关系解析一律取**基线（原始夹具）**的地面真值：Agent 改过的脚本不能
    # 顺手改掉关系定义来「满足」期望。
    contract = baseline_module.layout_contract(scope) if hasattr(baseline_module, 'layout_contract') else {}

    if mode == 'config_error':
        # 装载一律用**原始不可变夹具**（baseline_module），绝不加载候选脚本：候选 Python
        # 自己抛的 ConfigError 不是独立证明。基线本身也必须用同一个原始模块装载。
        loader = baseline_module
        out = {'mode': mode, 'config_error': {'raised': False, 'stage': None, 'error': None,
                                              'error_type': None,
                                              'loader_script': str(Path(getattr(
                                                  loader, '__file__', script)).resolve()),
                                              'config': str(request['config']) if request.get('config') else None,
                                              'baseline_ok': None, 'baseline_error': None,
                                              'baseline_error_type': None}}
        baseline = request.get('baseline_config')
        if baseline:
            # 归因前提：原始基线本身必须装得下，否则「拒绝」可能来自别的原因。
            try:
                loader.load_config(baseline)
            except Exception as error:
                out['config_error'].update(baseline_ok=False,
                                           baseline_error=f'{type(error).__name__}: {error}',
                                           baseline_error_type=type(error).__name__)
            else:
                out['config_error']['baseline_ok'] = True
        try:
            loader.load_config(request['config'])
        except Exception as error:
            out['config_error'].update(raised=True, stage='load_config',
                                       error=f'{type(error).__name__}: {error}',
                                       error_type=type(error).__name__)
        else:
            try:
                counts['builds'] += 1
                loader.build_scene(loader.load_science(), loader.load_config(request['config']), scope)
            except Exception as error:
                out['config_error'].update(raised=True, stage='build',
                                           error=f'{type(error).__name__}: {error}',
                                           error_type=type(error).__name__)
        return out

    if mode == 'effects':
        from figpact import effects
        outcome = effects.check_effects(script, request['config'], scope)
        return {'mode': mode, 'effects': {key: outcome.get(key) for key in
                                          ('status', 'counts', 'parameters', 'results', 'notes')}}

    if mode == 'cold':
        phase = time.perf_counter()
        config = module.load_config(request['config'])
        load_config_s = time.perf_counter() - phase
        phase = time.perf_counter()
        science = module.load_science()
        load_science_s = time.perf_counter() - phase
        phase = time.perf_counter()
        counts['builds'] += 1
        fig, reg = module.build_scene(science, config, scope)
        build_scene_s = time.perf_counter() - phase
        plt.close(fig)
        return {'mode': mode, 'cold': {'timings': {'load_config_s': load_config_s,
                                                   'load_science_s': load_science_s,
                                                   'build_scene_s': build_scene_s},
                                       'gids': len(reg.gids())}}
    staging = Path(request['staging'])
    staging.mkdir(parents=True, exist_ok=True)
    png_dir = Path(request.get('png_dir') or staging)
    png_dir.mkdir(parents=True, exist_ok=True)

    def build(build_module, config_path):
        counts['builds'] += 1
        config = build_module.load_config(config_path)
        science = build_module.load_science()
        fig, reg = build_module.build_scene(science, config, scope)
        return config, science, fig, reg

    from figpact import qa

    def qa_problems(build_module, fig, science, config):
        problems = [str(p) for p in qa.blocking_problems(fig, config=config)]
        hook = getattr(build_module, 'science_selfcheck', None)
        if callable(hook):
            for problem in hook(science, fig=fig) or []:
                text = str(problem)
                if text not in problems:
                    problems.append(text)
        return problems

    builds = {}
    for tag, config_path, build_module in (
            ('baseline', request['baseline_config'], baseline_module),
            ('candidate', request.get('candidate_config'), module)):
        if not config_path:
            continue
        config, science, fig, reg = build(build_module, config_path)
        try:
            facts = _probe_payload(fig, reg, scope, contract, counts=counts)
            facts['qa'] = qa_problems(build_module, fig, science, config)
            facts['staging_png'] = None
            if tag == 'candidate' or not request.get('candidate_config'):
                target = png_dir / f"{request.get('task_id', 'task')}-{tag}.png"
                fig.savefig(target, dpi=fig.dpi)
                counts['pngs'] += 1
                facts['staging_png'] = {'name': target.name, 'bytes': target.stat().st_size,
                                        'sha256': sha256_file(target)}
            manifest_hook = getattr(build_module, 'science_manifest', None)
            facts['science_manifest'] = manifest_hook(science) if callable(manifest_hook) else None
            facts['science_manifest_jsonable'] = True
            try:
                json.dumps(facts['science_manifest'])
            except Exception as error:
                facts['science_manifest_jsonable'] = False
                facts['science_manifest_error'] = str(error)
            facts['science_inputs'] = _probe_science_inputs(build_module)
            facts['source_fingerprint'] = _probe_source_fingerprint(build_module, config_path)
            builds[tag] = facts
        finally:
            plt.close(fig)

    measurements = _probe_raw_measurements(builds, contract, request)
    invariants = _compare_invariants(builds.get('baseline'), builds.get('candidate'),
                                     request.get('invariants') or [], request)
    return {'mode': mode, 'invariants': invariants, 'measurements': measurements,
            'baseline': _probe_public(builds.get('baseline')),
            'candidate': _probe_public(builds.get('candidate'))}


def _probe_science_inputs(module) -> dict:
    hook = getattr(module, 'science_inputs', None)
    declared = None
    try:
        declared = hook() if callable(hook) else getattr(module, 'SCIENCE_INPUTS', None)
    except Exception as error:
        return {'declared': None, 'error': str(error), 'missing': None}
    if declared is None:
        return {'declared': None, 'error': None, 'missing': None}
    base = Path(getattr(module, '__file__', '.')).resolve().parent
    paths = []
    for item in declared:
        path = Path(item)
        paths.append(str((path if path.is_absolute() else base / path).resolve()))
    missing = [p for p in paths if not Path(p).is_file()]
    return {'declared': paths, 'error': None, 'missing': missing}


def _probe_source_fingerprint(build_module, config_path) -> dict:
    """源码/输入指纹（B 的 script_fingerprint 是这套接口的地面真值）。"""
    try:
        from figpact.session import script_fingerprint
        value = script_fingerprint(Path(getattr(build_module, '__file__')).resolve(),
                                   Path(config_path).resolve())
        return {'available': True, 'value': value, 'script': str(Path(build_module.__file__).resolve())}
    except Exception as error:
        return {'available': False, 'value': None, 'error': f'{type(error).__name__}: {error}'}

def _probe_public(facts):
    if facts is None:
        return None
    return {'nodes': facts['nodes'], 'measurement': facts['measurement'],
            'snapshot_diagnostics': facts['snapshot_diagnostics'], 'qa': facts['qa'],
            'payload': facts['payload'] if 'payload' in facts else None,
            'text_anchors_mm': facts['text_anchors_mm'],
            'staging_png': facts['staging_png'],
            'science_manifest': facts['science_manifest'],
            'science_manifest_jsonable': facts['science_manifest_jsonable'],
            'science_inputs': facts['science_inputs'],
            'source_fingerprint': facts['source_fingerprint']}


def _probe_raw_measurements(builds, contract, request) -> list:
    """原始观测：不施加期望/容差（判定权在 evaluate_task）。"""
    base = builds.get('baseline')
    cand = builds.get('candidate')
    reference = cand or base
    relations = contract.get('relations') or []
    relation_values = _probe_measure_relations(reference, relations, request.get('expected_measurements') or [])
    results = []
    for index, expected in enumerate(request.get('expected_measurements') or []):
        entry = {'kind': expected.get('kind'), 'objects': list(expected.get('objects') or []),
                 'axis': expected.get('axis'), 'quantity': expected.get('quantity'),
                 'relation_id': expected.get('relation_id'), 'basis': expected.get('basis'),
                 'tolerance_mm': expected.get('tolerance_mm')}
        kind = expected.get('kind')
        objects = list(expected.get('objects') or [])
        if kind == 'relation':
            entry['raw'] = relation_values[index] if index < len(relation_values) else None
        elif kind in ('translate', 'text'):
            if base is None or cand is None:
                entry['raw'] = {'unavailable': '需要基线 + 候选两次独立重建'}
            else:
                entry['raw'] = _probe_pair(base, cand, objects, kind)
        elif kind == 'bounds':
            entry['raw'] = {gid: (reference or {}).get('nodes', {}).get(gid, {}).get('bounds_mm')
                            for gid in objects}
        else:
            entry['raw'] = {'unavailable': f'未知测量类型 {kind!r}'}
        results.append(entry)
    return results


def _probe_pair(base, cand, objects, kind) -> dict:
    out = {'baseline': {}, 'candidate': {}}
    for gid in objects:
        base_node = base['nodes'].get(gid)
        cand_node = cand['nodes'].get(gid)
        out['baseline'][gid] = (base_node or {}).get('bounds_mm')
        out['candidate'][gid] = (cand_node or {}).get('bounds_mm')
        if kind == 'text':
            out.setdefault('anchor_baseline', {})[gid] = base['text_anchors_mm'].get(gid)
            out.setdefault('anchor_candidate', {})[gid] = cand['text_anchors_mm'].get(gid)
    return out


def _compare_invariants(base, cand, ids, request) -> dict:
    out = {}
    if cand is None:
        return {inv: {'ok': None, 'reason': '没有候选重建（拒绝/报错任务无需比较）'} for inv in ids}
    if base is None:
        return {inv: {'ok': None, 'reason': '没有基线重建'} for inv in ids}
    for inv in ids:
        groups = INVARIANT_PAYLOAD_GROUPS.get(inv)
        basis = 'registered_payload_map'
        if groups is None:
            groups = PAYLOAD_GROUPS
            basis = 'fail_closed_all_groups（未登记的不变量按全部载荷比较）'
        changed = []
        for group in groups:
            before = base['payload'].get(group)
            after = cand['payload'].get(group)
            if before != after:
                changed.append(group)
        out[inv] = {'ok': not changed, 'groups': list(groups), 'basis': basis,
                    'changed_groups': changed,
                    'reason': None if not changed else f'载荷变化：{changed}'}
    return out


# --------------------------------------------------------------------------- #
# 判定（纯函数：验收器是唯一裁判；测试直接喂观测，不需要运行引擎）
# --------------------------------------------------------------------------- #

def _bounds_quantity(bounds, axis: str, quantity: str):
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return None
    index = 1 if axis == 'y' else 0
    low, high = float(bounds[index]), float(bounds[index + 2])
    if quantity == 'min':
        return low
    if quantity == 'max':
        return high
    if quantity == 'center':
        return (low + high) / 2.0
    return high - low


def judge_measurement(expected: dict, raw: dict) -> dict:
    """把探针的原始观测变成判定：value_mm / matched_quantity / ok / reason。

    未声明 tolerance_mm 时按精确相等（1e-9）并标注，不擅自放宽。
    """
    kind = expected.get('kind')
    axis = expected.get('axis') or 'x'
    target = expected.get('value_mm')
    tol = expected.get('tolerance_mm')
    declared_tol = tol is not None
    if not _finite(tol):
        tol = EXACT_TOL_MM
    outcome = {'kind': kind, 'axis': axis, 'expected_value_mm': target,
               'tolerance_mm': float(tol), 'tolerance_declared': declared_tol,
               'value_mm': None, 'per_object': {}, 'quantity': expected.get('quantity') or 'size',
               'ok': False, 'reason': None, 'raw': raw}
    if raw is None:
        outcome['reason'] = '没有原始观测'
        return outcome
    if raw.get('unavailable'):
        outcome['reason'] = str(raw['unavailable'])
        return outcome
    if not _finite(target):
        outcome['reason'] = '记录没有给出期望值'
        return outcome
    objects = list(expected.get('objects') or [])

    if kind == 'relation':
        status = raw.get('status')
        value = raw.get('value_mm')
        outcome['value_mm'] = value if _finite(value) else None
        outcome['status'] = status
        outcome['method'] = raw.get('method')
        outcome['precision'] = raw.get('precision')
        outcome['calibrated'] = raw.get('calibrated')
        if status != STATUS_OK or not _finite(value):
            outcome['reason'] = f'关系测量未完成（status={status}）'
            return outcome
        outcome['relation'] = raw.get('relation')
        # contain 的观测值是**最大溢出**（负值 = 净空），所以目标 0 是上限而不是「贴边」：
        # 装得下（溢出 <= 0）就满足包含，实测净空 -10 mm 如实报 -10，绝不伪造成 0。
        if raw.get('relation') == 'contain' and float(target) == 0.0:
            overflow = float(value)
            outcome['semantics'] = 'upper_bound'
            outcome['overflow_mm'] = overflow
            outcome['deviation_mm'] = max(0.0, overflow)
            outcome['ok'] = overflow <= float(tol)
            if not outcome['ok']:
                outcome['reason'] = (f'contain 实测溢出 {overflow} mm，超过上限 {target} mm'
                                     f'（容差 {tol}）：对象超出容器')
            return outcome
        deviation = abs(float(value) - float(target))
        outcome['deviation_mm'] = deviation
        outcome['ok'] = deviation <= float(tol)
        if not outcome['ok']:
            outcome['reason'] = f'关系测得 {value} mm，期望 {target} mm（容差 {tol}）'
        return outcome

    if kind == 'bounds':
        if outcome['quantity'] not in BOUNDS_QUANTITIES:
            outcome['reason'] = f'未知的 bounds quantity {outcome["quantity"]!r}（只能是 {BOUNDS_QUANTITIES}）'
            return outcome
        values = {}
        for gid in objects:
            quantity = _bounds_quantity(raw.get(gid), axis, outcome['quantity'])
            if quantity is not None:
                values[gid] = quantity
        outcome['per_object'] = values
        if not values:
            outcome['reason'] = '对象没有可测的 bounds_mm'
            return outcome
        outcome['value_mm'] = next(iter(values.values())) if len(values) == 1 else None
        worst = max(abs(float(v) - float(target)) for v in values.values())
        outcome['worst_deviation_mm'] = worst
        outcome['ok'] = worst <= float(tol)
        if not outcome['ok']:
            outcome['reason'] = (f'{outcome["quantity"]}@{axis} 实测 {values}，期望 {target} mm'
                                 f'（最大偏差 {worst}）')
        return outcome

    if kind == 'translate':
        base_bounds = raw.get('baseline') or {}
        cand_bounds = raw.get('candidate') or {}
        deltas = {}
        for gid in objects:
            before, after = base_bounds.get(gid), cand_bounds.get(gid)
            if not (isinstance(before, (list, tuple)) and isinstance(after, (list, tuple))):
                continue
            index = 1 if axis == 'y' else 0
            deltas[gid] = float(after[index]) - float(before[index])
        outcome['per_object'] = deltas
        if not deltas:
            outcome['reason'] = '缺少基线/候选的下边缘观测'
            return outcome
        outcome['value_mm'] = next(iter(deltas.values())) if len(deltas) == 1 else None
        worst = max(abs(float(v) - float(target)) for v in deltas.values())
        outcome['worst_deviation_mm'] = worst
        outcome['ok'] = worst <= float(tol)
        if not outcome['ok']:
            outcome['reason'] = f'{axis} 位移实测 {deltas}，期望 {target} mm（最大偏差 {worst}）'
        return outcome

    if kind == 'text':
        quantity = expected.get('quantity') or 'delta'
        if quantity == 'anchor':
            anchors = raw.get('anchor_candidate') or {}
            values = {gid: anchor[1 if axis == 'y' else 0] for gid, anchor in anchors.items() if anchor}
            outcome['quantity'] = 'anchor'
        else:
            deltas = {}
            for gid in objects:
                before = (raw.get('anchor_baseline') or {}).get(gid)
                after = (raw.get('anchor_candidate') or {}).get(gid)
                if before and after:
                    deltas[gid] = float(after[1 if axis == 'y' else 0]) - float(before[1 if axis == 'y' else 0])
            values = deltas
            outcome['quantity'] = 'delta'
        outcome['per_object'] = values
        if not values:
            outcome['reason'] = '文本锚点不可测（transform 不可用）'
            return outcome
        outcome['value_mm'] = next(iter(values.values())) if len(values) == 1 else None
        worst = max(abs(float(v) - float(target)) for v in values.values())
        outcome['worst_deviation_mm'] = worst
        outcome['ok'] = worst <= float(tol)
        if not outcome['ok']:
            outcome['reason'] = f'文本锚点 {outcome["quantity"]}@{axis} 实测 {values}，期望 {target} mm'
        return outcome

    outcome['reason'] = f'未知测量类型 {kind!r}'
    return outcome


def judge_verification(expected, observed) -> dict:
    """证据强度判定：期望 GEOMETRY 时实测 RENDER 是升级；期望 RENDER 时实测 GEOMETRY 失败。"""
    want = expected
    got = observed
    if want is None:
        return {'ok': True, 'expected': None, 'observed': got, 'upgraded': False,
                'reason': '记录未要求验证等级，如实记录实测值'}
    if got == want:
        return {'ok': True, 'expected': want, 'observed': got, 'upgraded': False, 'reason': None}
    want_strength = VERIFICATION_STRENGTH.get(want)
    got_strength = VERIFICATION_STRENGTH.get(got)
    if want_strength is None or got_strength is None:
        return {'ok': False, 'expected': want, 'observed': got, 'upgraded': False,
                'reason': f'验证等级 {got!r} 不是可比较的等级（期望 {want!r}）'}
    if got_strength > want_strength:
        return {'ok': True, 'expected': want, 'observed': got, 'upgraded': True,
                'reason': f'实测 {got} 强于期望 {want}，如实记录为升级'}
    return {'ok': False, 'expected': want, 'observed': got, 'upgraded': False,
            'reason': f'实测 {got} 弱于期望 {want}：未经证明的快验证不可接受'}


def judge_arm_fit(arm, script_changed: bool, config_changed: bool, failures: list, notes: list) -> str:
    """臂与真实产物的匹配判定（纯函数）：'replay' / 'arm_violation' / 'ok'。

    重放 = 脚本与候选 YAML 都还是原始科学权威；它既不是 Agent 改动，也不能被当成成功。
    """
    if not script_changed and not config_changed:
        notes.append('候选脚本与候选 YAML 都还是原始科学权威：重放不是 Agent 改动')
        return 'replay'
    if arm == 'A' and not script_changed:
        failures.append('A 臂的正向候选必须真的改了 Python（candidate_script 与原始夹具一致）')
        return 'arm_violation'
    if arm in ('B', 'C') and script_changed:
        failures.append(f'{arm} 臂不许改 Python（candidate_script 与原始夹具不同）')
        return 'arm_violation'
    return 'ok'


def judge_config_error_refusal(refusal: dict, failures: list, notes: list) -> None:
    """CONFIG_ERROR 负例的拒绝证据判定（纯函数）。

    只有「原始夹具 load_config 对恰好携带请求改动的诊断 YAML 抛出真实 ConfigError」才算独立证明；
    候选脚本自报的 ConfigError、没改动的基线、无关坏键、构建期异常一律不算。
    """
    if refusal.get('loader_script') != refusal.get('pristine_script'):
        failures.append('装载用的不是原始不可变夹具：候选脚本自报的 ConfigError 不是独立证明')
    if not refusal.get('diagnostic_only'):
        failures.append('负例必须显式声明 diagnostic_only=true：诊断 YAML 不是可发布产物')
    if refusal.get('intended_change') is False:
        failures.append('诊断 YAML 不等于「基线 + 请求的改动」：含无关坏键或缺少请求取值，拒绝无法归因')
    if refusal.get('candidate_differs_from_baseline') is False:
        failures.append('诊断 YAML 与基线字节相同：没有把请求的取值喂给守卫')
    if refusal.get('baseline_ok') is not True:
        failures.append(f'原始基线本身装不下：拒绝无法归因（{refusal.get("baseline_error")}）')
    if not refusal.get('raised'):
        failures.append('原始夹具 load_config 接受了该诊断配置：请求并非不可接受，拒绝不成立')
    elif 'ConfigError' not in str(refusal.get('error_type') or ''):
        failures.append(f'拒绝不是真实 ConfigError（{refusal.get("error_type")}）：独立证明不成立')
    if refusal.get('stage') and refusal.get('stage') != 'load_config':
        notes.append(f'拒绝发生在 {refusal["stage"]} 阶段（语料只声明 load_config 守卫）')
    if refusal.get('builds'):
        failures.append('拒绝路径发生了构建：诊断不纯（可能是构建期异常而不是守卫拒绝）')
    if refusal.get('baseline_sha256_unchanged') is False:
        failures.append('物化/装载过程改动了基线副本的字节')


def judge_refusal_replay(record: dict, replay: dict, failures: list, notes: list) -> None:
    """期望「被拒」的任务：原始夹具重放出来的拒绝证据判定（纯函数）。"""
    declared = ((record.get('expected') or {}).get('refusal') or {}).get('rule')
    if replay.get('status') not in REFUSAL_STATUSES:
        failures.append(f"原始夹具实测状态 {replay.get('status')!r} 不是拒绝状态，受阻不成立")
    if replay.get('state_mutated'):
        failures.append(f"拒绝路径改动了状态：{replay.get('mutation_detail')}")
    if replay.get('artifacts'):
        failures.append(f'拒绝路径写下了产物：{replay.get("artifacts")}')
    if replay.get('publishable_candidate'):
        failures.append('期望拒绝的任务提交了改动过的候选 YAML：可发布文件被改动')
    if declared in REFUSAL_STATUSES and replay.get('status') != declared:
        failures.append(f'语料声明拒绝规则 {declared}，原始夹具实测 {replay.get("status")}')
    elif declared and declared not in REFUSAL_STATUSES:
        notes.append(f'语料声明拒绝规则 {declared} 不在引擎状态词表里，只核对「确实是拒绝」')


def evaluate_task(record: dict, observed: dict) -> dict:
    """把一条任务的真实观测与记录期望对判。返回 {passed, failures, notes}。"""
    failures, notes = [], []
    expected = record.get('expected') or {}
    want_status = expected.get('status')
    got_status = observed.get('status')
    verdict = {'task_id': record.get('id'), 'expected_status': want_status, 'observed_status': got_status,
               'expected_verification': expected.get('verification'),
               'observed_verification': observed.get('verification'),
               'passed': False, 'failures': failures, 'notes': notes}

    for error in observed.get('errors') or []:
        failures.append(f'执行错误：{error}')
    if observed.get('stale') is True:
        failures.append('会话 revision 过期（拒绝改状态）')

    if want_status == STATUS_CONFIG_ERROR:
        info = observed.get('config_error') or {}
        request_evidence = observed.get('config_error_request') or {}
        if not info.get('config'):
            failures.append('没有把请求的取值物化成候选 YAML：load_config 从未见过这些改动')
        if info.get('baseline_ok') is not True:
            failures.append(f'原始基线配置本身就无法装载，拒绝无法归因到请求的改动'
                            f'（baseline_error={info.get("baseline_error")}）')
        if not info.get('raised'):
            failures.append('期望 load_config 拒绝该值，实际没有抛错')
        if info.get('stage') and info.get('stage') != 'load_config':
            notes.append(f'拒绝发生在 {info["stage"]} 阶段（记录只声明 load_config 守卫）')
        if request_evidence.get('baseline_unchanged') is False:
            failures.append('物化候选时改动了基线副本的字节（基线必须原样保留）')
        if not request_evidence.get('candidate_sha256'):
            failures.append('没有候选 YAML 的字节证据：无法证明请求的取值真的喂给了 load_config')
        elif request_evidence['candidate_sha256'] == request_evidence.get('baseline_sha256_before'):
            failures.append('候选 YAML 与基线字节相同：等于没有把请求的取值喂给 load_config')
        if info.get('artifacts'):
            failures.append(f'拒绝路径产生了产物：{info["artifacts"]}')
        _judge_qa(observed, failures, notes)
        verdict['config_error'] = info.get('error')
        verdict['passed'] = not failures
        return verdict

    if want_status == STATUS_DIAGNOSED:
        effects = observed.get('effects') or {}
        declared = list(expected.get('effects') or [])
        # 逐条结论按 `figpact.effects.check_effects` 的实际记录字段 `path` 建索引；
        # 语料侧用它自己的字段名 `parameter` 声明期望路径。
        rules = {tuple(entry.get('path') or []): entry.get('status')
                 for entry in (effects.get('results') or [])}
        for item in declared:
            path = tuple(item.get('parameter') or [])
            want_rule = item.get('rule')
            got_rule = rules.get(path)
            if got_rule is None:
                failures.append(f'负效应夹具没有产出路径 {list(path)} 的结论')
            elif got_rule != want_rule:
                failures.append(f'路径 {list(path)} 判定为 {got_rule}，期望 {want_rule}')
        if not declared:
            failures.append('DIAGNOSED 记录没有声明 expected.effects')
        _judge_verification(record, observed, failures, notes)
        _judge_qa(observed, failures, notes)
        _judge_invariants(record, observed, failures, notes)
        verdict['effects_status'] = effects.get('status')
        verdict['passed'] = not failures
        return verdict

    if want_status == STATUS_REFUSED:
        if got_status == STATUS_OK:
            failures.append('期望拒绝，实际接受了改动')
        elif got_status not in REFUSAL_STATUSES:
            failures.append(f'期望拒绝，实测状态 {got_status!r} 不是拒绝状态')
        refusal = observed.get('refusal') or {}
        if refusal.get('state_mutated'):
            failures.append(f'拒绝路径改动了状态：{refusal.get("mutation_detail")}')
        if refusal.get('has_candidate'):
            failures.append('拒绝路径留下了候选目标（has_candidate=True）')
        if refusal.get('goals'):
            failures.append(f'拒绝路径累积了 {refusal["goals"]} 个目标')
        if refusal.get('candidate_config_differs'):
            failures.append('拒绝路径的 candidate_config 与基线不同')
        if refusal.get('artifacts'):
            failures.append(f'拒绝路径写下了产物：{refusal["artifacts"]}')
        if refusal.get('qa_candidate') or refusal.get('qa_new'):
            failures.append(f'拒绝路径的候选 QA 不干净：{refusal.get("qa_new")}')
        rule = (expected.get('refusal') or {}).get('rule')
        if rule in REFUSAL_STATUSES and got_status != rule:
            failures.append(f'记录声明拒绝规则 {rule}，实测 {got_status}')
        _judge_verification(record, observed, failures, notes)
        _judge_invariants(record, observed, failures, notes)
        verdict['passed'] = not failures
        return verdict

    if want_status != STATUS_OK:
        failures.append(f'未知的期望状态 {want_status!r}')
        verdict['passed'] = False
        return verdict

    if got_status != STATUS_OK:
        failures.append(f'期望 OK，实测 {got_status!r}：{observed.get("message")}')
    _judge_verification(record, observed, failures, notes)
    _judge_measurements(record, observed, failures, notes)
    _judge_invariants(record, observed, failures, notes)
    _judge_qa(observed, failures, notes)
    _judge_manifest(record, observed, failures, notes)
    verdict['passed'] = not failures
    return verdict


def _judge_verification(record, observed, failures, notes):
    outcome = judge_verification((record.get('expected') or {}).get('verification'),
                                 observed.get('verification'))
    if outcome.get('upgraded'):
        notes.append(outcome['reason'])
    if not outcome['ok']:
        failures.append(outcome['reason'])


def _judge_measurements(record, observed, failures, notes):
    expected = (record.get('expected') or {}).get('measurements') or []
    results = observed.get('measurements') or []
    if len(results) != len(expected):
        failures.append(f'期望测量 {len(expected)} 项，实测 {len(results)} 项（缺项按失败处理）')
    for index, item in enumerate(expected):
        if index >= len(results):
            failures.append(f'第 {index + 1} 项测量（{item.get("kind")}）没有观测')
            continue
        outcome = results[index].get('outcome') if isinstance(results[index], dict) else None
        if not outcome:
            failures.append(f'第 {index + 1} 项测量（{item.get("kind")}）没有判定')
            continue
        if not outcome.get('ok'):
            failures.append(f'测量未达成 [{item.get("kind")} {item.get("objects")}]：{outcome.get("reason")}')
        if not outcome.get('tolerance_declared'):
            notes.append(f'测量 {item.get("kind")} 未声明容差，按精确相等 {EXACT_TOL_MM} 判定')


def _judge_invariants(record, observed, failures, notes):
    ids = (record.get('expected') or {}).get('science_invariants') or []
    observed_invariants = observed.get('invariants') or {}
    for inv in ids:
        entry = observed_invariants.get(inv)
        if entry is None:
            failures.append(f'科学不变量 {inv} 没有观测')
            continue
        if entry.get('ok') is None:
            if observed.get('status') == STATUS_OK:
                failures.append(f'科学不变量 {inv} 未被观测（{entry.get("reason")}）')
            else:
                notes.append(f'不变量 {inv} 未比较：{entry.get("reason")}')
            continue
        if not entry.get('ok'):
            failures.append(f'科学不变量 {inv} 被破坏：{entry.get("reason")}')
        if entry.get('basis') and 'fail_closed' in str(entry.get('basis')):
            notes.append(f'不变量 {inv} 未登记载荷组，按全部载荷 fail-closed 比较')


def _judge_qa(observed, failures, notes):
    qa = observed.get('qa') or {}
    new = qa.get('new')
    if new is None:
        notes.append('QA 未观测（null）')
        return
    if new:
        failures.append(f'候选新增 QA 阻断项 {len(new)} 条：{new[:5]}')


def _judge_manifest(record, observed, failures, notes):
    manifest = observed.get('manifest') or {}
    if manifest.get('jsonable') is False:
        failures.append(f'science_manifest 不是 JSONable：{manifest.get("error")}')
    if manifest.get('missing_inputs'):
        failures.append(f'声明的科学输入文件不存在：{manifest["missing_inputs"]}')
    if manifest.get('declared') is False:
        notes.append('夹具没有声明 science_manifest（可选钩子）；科学保护只剩载荷对比与 QA')


# --------------------------------------------------------------------------- #
# 执行器
# --------------------------------------------------------------------------- #

class WorkerHandle:
    """一个 warm 工作进程 + 归属统计。"""

    def __init__(self, worker, script, spawned: bool):
        self.worker = worker
        self.script = script
        self.spawns = 1 if spawned else 0
        self.opens = 0
        self.restarts_before = 0

    def mark_restarts(self):
        self.restarts_before = getattr(self.worker, 'restarts', 0)

    def restarts_since(self) -> int:
        return max(0, getattr(self.worker, 'restarts', 0) - self.restarts_before)


class AcceptanceRunner:
    def __init__(self, corpus_path: Path, *, python=None, keep_temp=False, only=None,
                 agent_trials=None, backend_samples=0, probe_timeout=420.0):
        self.corpus_path = Path(corpus_path)
        self.python = python or sys.executable
        self.keep_temp = keep_temp
        self.only = set(only or [])
        self.agent_trials_path = Path(agent_trials) if agent_trials else None
        self.backend_samples = int(backend_samples or 0)
        self.probe_timeout = float(probe_timeout)
        self.temp_root = Path(tempfile.mkdtemp(prefix='figpact-vnext-acceptance-'))
        self.workers: dict[str, WorkerHandle] = {}
        self.artifacts: dict[str, dict] = {}
        self.unsupported: list[dict] = []
        self.mismatches: list[dict] = []

    # -- 语料 -------------------------------------------------------------- #

    def load_corpus(self) -> dict:
        corpus = read_json(self.corpus_path)
        if not isinstance(corpus, dict):
            raise ValueError('任务语料顶层必须是映射')
        records = corpus.get('tasks') or corpus.get('records') or []
        if not isinstance(records, list) or not records:
            raise ValueError('任务语料没有 tasks 列表')
        return corpus

    def guard_hashes(self, corpus) -> dict:
        """跑之前先钉死夹具目录里被引用的源码/配置哈希：跑完必须一字不差。"""
        guarded = {}
        for record in corpus.get('tasks') or corpus.get('records') or []:
            for key in ('fixture', 'config'):
                rel = record.get(key)
                if not rel:
                    continue
                path = (ROOT / rel).resolve()
                if path.is_file():
                    guarded[str(path)] = sha256_file(path)
        return guarded

    # -- warm 工作进程 ------------------------------------------------------ #

    def worker_for(self, script: Path):
        key = str(script.resolve())
        handle = self.workers.get(key)
        if handle is not None and handle.worker.alive:
            return handle, False
        from figpact.runtime import FigureWorker
        worker = FigureWorker(script, script, 'main', python=self.python, cwd=str(ROOT),
                              timeout=self.probe_timeout)
        handle = WorkerHandle(worker, key, spawned=True)
        if key in self.workers:
            handle.spawns += self.workers[key].spawns
        self.workers[key] = handle
        return handle, True

    def close_workers(self):
        for handle in self.workers.values():
            try:
                handle.worker.close()
            except Exception:
                pass

    # -- 探针 -------------------------------------------------------------- #

    def probe(self, request: dict, tag: str) -> dict:
        request = dict(request)
        request['staging'] = str(self.temp_root / 'staging' / tag)
        request['png_dir'] = str(self.temp_root / 'evidence' / tag)
        request_path = self.temp_root / f'probe-{tag}-request.json'
        response_path = self.temp_root / f'probe-{tag}-response.json'
        dump_json(request_path, request)
        started = time.perf_counter()
        completed = subprocess.run(
            [self.python, '-X', 'utf8', str(Path(__file__).resolve()),
             '--probe', str(request_path), str(response_path)],
            cwd=str(ROOT), capture_output=True, text=True, encoding='utf8',
            env={**os.environ, 'MPLBACKEND': 'Agg'}, timeout=self.probe_timeout)
        wall = time.perf_counter() - started
        payload = {}
        if response_path.is_file():
            payload = read_json(response_path)
        payload.setdefault('ok', False)
        payload['probe_wall_s'] = wall
        payload['probe_returncode'] = completed.returncode
        if not payload.get('ok'):
            payload.setdefault('error', f'探针退出码 {completed.returncode}')
            payload.setdefault('probe_stderr_tail', (completed.stderr or '')[-2000:])
        return payload

    # -- 单条任务 ---------------------------------------------------------- #

    def run_task(self, record: dict) -> dict:
        task_id = record.get('id') or 'unnamed'
        task_dir = self.temp_root / 'tasks' / str(task_id).replace('/', '_')
        task_dir.mkdir(parents=True, exist_ok=True)
        fixture = (ROOT / record['fixture']).resolve()
        config = (ROOT / record['config']).resolve()
        baseline_copy = task_dir / Path(record['config']).name
        shutil.copy2(config, baseline_copy)
        scope = record['scope']
        observed = {'task_id': task_id, 'status': None, 'verification': None, 'errors': [],
                    'measurements': [], 'invariants': {}, 'qa': {'baseline': None, 'candidate': None, 'new': None},
                    'refusal': None, 'manifest': {'jsonable': None}, 'config_error': None,
                    'config_error_request': None, 'effects': None}
        timing, counts = {}, {'worker_spawned': False, 'worker_reused': False, 'worker_opens': 0,
                              'worker_restarts': 0, 'independent_rebuilds': None, 'pngs': None,
                              'session_rendered': None, 'session_rebuilds': None,
                              'session_rebuilds_basis': 'unavailable（会话不暴露重建计数器）'}
        want = (record.get('expected') or {}).get('status')
        before_artifacts = self._artifact_listing()

        probe_request = {
            'task_id': task_id, 'fixture': record['fixture'], 'script': str(fixture),
            'scope': scope, 'baseline_config': str(baseline_copy), 'candidate_config': None,
            'expected_measurements': (record.get('expected') or {}).get('measurements') or [],
            'invariants': (record.get('expected') or {}).get('science_invariants') or [],
            'mode': 'measure',
        }

        if want == STATUS_CONFIG_ERROR:
            # 记录声明的是「改动后的配置必须被 load_config 拒」。所以先按记录里逐条
            # set_parameter 把**请求的取值**物化成一个新 YAML（基线副本一个字节都不动），
            # 再让独立探针进程去装载它——绝不像以前那样把未改动的基线端上去。
            candidate_path, materialise_error = self._config_error_candidate(record, baseline_copy, task_id)
            observed['config_error_request'] = {
                'operations': record.get('operations') or [],
                'baseline_config': str(baseline_copy),
                'baseline_sha256_before': sha256_file(baseline_copy),
                'candidate_config': str(candidate_path) if candidate_path else None,
                'materialise_error': materialise_error,
            }
            if candidate_path is None:
                observed['errors'].append(f'无法把请求的取值物化成候选配置：{materialise_error}')
                observed['config_error'] = {'raised': False, 'stage': None, 'error': None, 'config': None,
                                            'artifacts': sorted(self._artifact_diff(before_artifacts))}
                observed['status'] = STATUS_ERROR
                verdict = evaluate_task(record, observed)
                return self._task_report(record, observed, verdict, timing, counts)
            observed['config_error_request'].update({
                'candidate_sha256': sha256_file(candidate_path),
                'baseline_sha256_after': None,
                'baseline_unchanged': None,
            })
            probe_request['config'] = str(candidate_path)
            probe_request['mode'] = 'config_error'
            result = self.probe(probe_request, f'{task_id}-config-error')
            timing['probe_wall_s'] = result.get('probe_wall_s')
            observed['config_error'] = dict(result.get('config_error') or {})
            observed['status'] = STATUS_CONFIG_ERROR if observed['config_error'].get('raised') else STATUS_OK
            observed['config_error']['artifacts'] = sorted(self._artifact_diff(before_artifacts))
            observed['config_error_request']['baseline_sha256_after'] = sha256_file(baseline_copy)
            observed['config_error_request']['baseline_unchanged'] = (
                observed['config_error_request']['baseline_sha256_after']
                == observed['config_error_request']['baseline_sha256_before'])
            counts['pngs'] = result.get('counts', {}).get('pngs')
            counts['independent_rebuilds'] = result.get('counts', {}).get('builds')
            if not result.get('ok'):
                observed['errors'].append(result.get('error'))
            verdict = evaluate_task(record, observed)
            return self._task_report(record, observed, verdict, timing, counts)

        # 1) warm 会话：每条任务一份独立基线 YAML 副本 → 重置目标 → 施加真实目标
        handle, spawned = self.worker_for(fixture)
        counts['worker_spawned'] = bool(spawned)
        counts['worker_reused'] = not spawned
        handle.mark_restarts()
        session_state = {}
        try:
            handle.worker.open(config=str(baseline_copy), scope=scope)
            handle.opens += 1
            counts['worker_opens'] = handle.opens
            handle.worker.try_layout([{'operation': 'reset'}])
            state_after_reset = handle.worker.state()
            observed['baseline_reset'] = {'status': STATUS_OK,
                                         'goals': state_after_reset.get('goals'),
                                         'has_candidate': state_after_reset.get('has_candidate')}
            if state_after_reset.get('goals'):
                observed['errors'].append(f'重置后仍有 {state_after_reset["goals"]} 个目标')
            operations = record.get('operations') or []
            started = time.perf_counter()
            if want == STATUS_DIAGNOSED:
                # 负效应校验由 B 的 effects 校验器负责（它自己起会话）；这里只在
                # 探针里跑一次真实扰动，避免同一份重活跑两遍。
                timing['effects_session_wall_s'] = None
            else:
                outcome = handle.worker.try_layout(operations)
                timing['session_wall_s'] = time.perf_counter() - started
                observed['status'] = outcome.get('status')
                observed['verification'] = outcome.get('verification')
                observed['message'] = outcome.get('message')
                counts['session_rendered'] = outcome.get('verification') == VERIFICATION_RENDER
                if outcome.get('verification') == VERIFICATION_RENDER:
                    counts['session_rebuilds'] = 1
                    counts['session_rebuilds_basis'] = 'inferred_from_verification=RENDER_CHECKED'
                elif outcome.get('verification') == VERIFICATION_GEOMETRY:
                    counts['session_rebuilds'] = 0
                    counts['session_rebuilds_basis'] = 'inferred_from_verification=GEOMETRY_CHECKED'
                if outcome.get('status') == STATUS_STALE:
                    observed['stale'] = True
            counts['worker_restarts'] = handle.restarts_since()
            session_state = handle.worker.state()
            observed['session'] = {
                'status': observed['status'],
                'verification': observed['verification'],
                'goals': session_state.get('goals'),
                'has_candidate': session_state.get('has_candidate'),
                'candidate_patch': session_state.get('candidate_patch'),
                'base_config_revision': session_state.get('base_config_revision'),
                'revisions_match': session_state.get('base_config_revision') == sha256_file(baseline_copy),
            }
            if not observed['session']['revisions_match']:
                observed['errors'].append('会话记录的基线指纹与磁盘副本不一致')
            if session_state.get('has_candidate'):
                candidate_config = task_dir / 'candidate.yaml'
                candidate_config.write_text(_yaml_dump(session_state['candidate_config']), encoding='utf8')
                probe_request['candidate_config'] = str(candidate_config)
        except Exception as error:
            observed['errors'].append(f'{type(error).__name__}: {error}')
            counts['worker_restarts'] = handle.restarts_since()

        if want == STATUS_DIAGNOSED:
            probe_request['config'] = str(baseline_copy)
            probe_request['mode'] = 'effects'
        elif want == STATUS_REFUSED:
            probe_request['mode'] = 'measure'
            probe_request['candidate_config'] = None

        # 2) 独立全量重建：探针从落盘 YAML 重跑 build_scene 并测物理量
        result = self.probe(probe_request, f'{task_id}-measure')
        timing['probe_wall_s'] = result.get('probe_wall_s')
        counts['independent_rebuilds'] = result.get('counts', {}).get('builds')
        counts['pngs'] = result.get('counts', {}).get('pngs')
        if not result.get('ok'):
            observed['errors'].append(f'独立重建探针失败：{result.get("error")}')
            observed['errors'].extend(result.get('probe_stderr_tail', '').splitlines()[-3:])
        base = result.get('baseline')
        cand = result.get('candidate')
        observed['invariants'] = result.get('invariants') or {}
        observed['measurements'] = []
        for index, entry in enumerate(result.get('measurements') or []):
            expected = ((record.get('expected') or {}).get('measurements') or [])[index] \
                if index < len((record.get('expected') or {}).get('measurements') or []) else {}
            observed['measurements'].append({
                'kind': entry.get('kind'), 'objects': entry.get('objects'), 'axis': entry.get('axis'),
                'outcome': judge_measurement(expected, entry.get('raw')),
                'raw': entry.get('raw'),
            })
        qa_base = (base or {}).get('qa')
        qa_cand = (cand or {}).get('qa')
        new = None
        if qa_cand is not None:
            new = [p for p in qa_cand if p not in (qa_base or [])]
        observed['qa'] = {'baseline': qa_base, 'candidate': qa_cand, 'new': new}
        manifest = (cand or base or {}).get('science_manifest')
        observed['manifest'] = {'declared': manifest is not None,
                                'jsonable': (cand or base or {}).get('science_manifest_jsonable'),
                                'error': (cand or base or {}).get('science_manifest_error'),
                                'missing_inputs': ((cand or base or {}).get('science_inputs') or {}).get('missing')}
        observed['probe'] = {
            'baseline_png': (base or {}).get('staging_png'),
            'candidate_png': (cand or {}).get('staging_png'),
            'measurement_env': (cand or base or {}).get('measurement') or {},
            'snapshot_diagnostics': (cand or base or {}).get('snapshot_diagnostics'),
            'science_inputs': (cand or base or {}).get('science_inputs'),
            'baseline_source_fingerprint': (base or {}).get('source_fingerprint'),
            'candidate_source_fingerprint': (cand or {}).get('source_fingerprint'),
            'candidate_manifest': (cand or base or {}).get('science_manifest'),
        }

        if want == STATUS_DIAGNOSED:
            observed['effects'] = result.get('effects')
            observed['verification'] = VERIFICATION_EFFECTS if observed.get('effects') else None
            observed['status'] = self._classify_effects(record, observed.get('effects'))
            # 负效应夹具：不变量证据 = 每条扰动下的科学载荷对比（B 的逐条结论）
            observed['invariants'] = self._effects_invariants(
                record, observed.get('effects'), observed.get('invariants') or {})
            effects_baseline = (observed.get('effects') or {}).get('baseline') or {}
            observed['qa'] = {'baseline': None, 'candidate': None, 'new': [],
                              'effects_baseline': effects_baseline,
                              'basis': '负效应校验的基线 QA 计数（每次扰动内部已比对，无新增即无泄漏）'}
        if want == STATUS_REFUSED:
            observed['refusal'] = self._refusal_evidence(session_state, baseline_copy)
            observed['refusal']['baseline_qa'] = qa_base
            observed['refusal']['probe_rebuilds'] = (base or {}).get('qa') is not None
            observed['refusal']['pngs'] = (base or {}).get('staging_png') is not None

        observed['artifacts'] = sorted(self._artifact_diff(before_artifacts))
        if want == STATUS_REFUSED and observed.get('refusal') is not None:
            observed['refusal']['artifacts'] = list(observed['artifacts'])
        verdict = evaluate_task(record, observed)
        return self._task_report(record, observed, verdict, timing, counts)

    # -- 证据收集 ---------------------------------------------------------- #

    def _classify_effects(self, record, effects) -> str:
        if not effects:
            return STATUS_ERROR
        declared = list((record.get('expected') or {}).get('effects') or [])
        rules = {tuple(entry.get('path') or []): entry.get('status')
                 for entry in (effects.get('results') or [])}
        if not declared:
            return effects.get('status') or STATUS_ERROR
        if all(rules.get(tuple(item.get('parameter') or [])) == item.get('rule') for item in declared):
            return STATUS_DIAGNOSED
        return 'EFFECTS_MISMATCH'

    def _config_error_candidate(self, record, baseline_copy: Path, task_id: str):
        """把 record.operations 原样物化成**新的**候选 YAML；基线副本字节不动。

        只搬运 `set_parameter` 的精确键段（与 session.set_path 同语义：路径/键段不存在
        即报错）。物化不了就返回 (None, 原因)，绝不替记录猜一个值、也绝不预置期望。
        产物落在 probe-inputs/ 下：那是验收器自己的输入，不是引擎产物。
        """
        try:
            candidate = _apply_operations_to_config(_load_yaml(baseline_copy),
                                                    record.get('operations') or [])
        except (KeyError, ValueError, TypeError) as error:
            return None, f'{type(error).__name__}: {error}'
        target = (self.temp_root / 'probe-inputs' / str(task_id).replace('/', '_')
                  / 'candidate.yaml')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_yaml_dump(candidate), encoding='utf8')
        return target, None

    def _refusal_evidence(self, session_state: dict, baseline_copy) -> dict:
        """拒绝路径的「状态未被改动」证据：全部取自会话自身状态 + 磁盘基线字节对比。"""
        state = session_state or {}
        baseline_config = _load_yaml(baseline_copy)
        candidate = state.get('candidate_config')
        differs = candidate is not None and candidate != baseline_config
        goals = state.get('goals') or 0
        has_candidate = bool(state.get('has_candidate'))
        return {
            'state_mutated': bool(goals) or has_candidate or differs,
            'mutation_detail': (None if not (goals or has_candidate or differs)
                                else f'goals={goals} has_candidate={has_candidate} candidate_differs={differs}'),
            'has_candidate': has_candidate,
            'goals': goals,
            'candidate_config_differs': differs,
            'candidate_config': candidate,
            'candidate_patch': state.get('candidate_patch'),
            'session_observed': bool(state),
            'qa_candidate': None,
            'qa_new': None,
        }

    def _effects_invariants(self, record, effects, fallback) -> dict:
        """负效应任务的科学不变量：每次真实扰动后的载荷等值结论。"""
        ids = (record.get('expected') or {}).get('science_invariants') or []
        if not ids:
            return fallback
        entries = (effects or {}).get('results') or []
        if not entries:
            return {inv: {'ok': None, 'basis': 'effects_perturbation_science',
                          'reason': '负效应校验没有产出任何条目'} for inv in ids}
        violations = [entry.get('key') for entry in entries
                      if entry.get('science_unchanged') is False
                      or entry.get('status') == 'SCIENCE_VIOLATION']
        unverified = [entry.get('key') for entry in entries
                      if entry.get('science_unchanged') is None]
        return {inv: {'ok': not violations, 'basis': 'effects_perturbation_science',
                      'entries': len(entries), 'unverified_entries': unverified,
                      'changed_groups': [],
                      'reason': None if not violations else f'扰动改变了科学载荷：{violations}'}
                for inv in ids}

    def _artifact_listing(self) -> dict:
        """只数引擎产物（tasks/ 下的候选 YAML、staging/ 下的 PNG）。

        验收器自己的探针请求/应答 JSON 是记账文件，不算产物；否则「拒绝路径无产物」
        这类断言会被记账文件污染。
        """
        listing = {}
        for sub in ('tasks', 'staging'):
            root = self.temp_root / sub
            if not root.exists():
                continue
            for path in root.rglob('*'):
                if path.is_file():
                    listing[str(path)] = path.stat().st_size
        return listing

    def _artifact_diff(self, before: dict) -> list[str]:
        after = self._artifact_listing()
        return [path for path in after if path not in before]

    def _task_report(self, record, observed, verdict, timing, counts) -> dict:
        report = {
            'id': record.get('id'), 'group': record.get('group'), 'intent': record.get('intent'),
            'fixture': record.get('fixture'), 'config': record.get('config'), 'scope': record.get('scope'),
            'operations': record.get('operations'),
            'expected': record.get('expected'),
            'observed': observed,
            'verdict': verdict,
            'timing': timing,
            'counts': counts,
        }
        if observed.get('status') in REFUSAL_STATUSES:
            self.unsupported.append({'id': record.get('id'), 'status': observed.get('status'),
                                     'verification': observed.get('verification'),
                                     'message': observed.get('message')})
        for item in observed.get('measurements') or []:
            outcome = item.get('outcome') or {}
            if outcome and outcome.get('ok') is False:
                self.mismatches.append({'id': record.get('id'), 'kind': item.get('kind'),
                                        'objects': item.get('objects'),
                                        'expected': outcome.get('expected_value_mm'),
                                        'measured': outcome.get('value_mm'),
                                        'per_object': outcome.get('per_object'),
                                        'reason': outcome.get('reason')})
        return report

    # -- 对照：当前预览后端 vs 本运行时的候选验收 ----------------------------- #
    #
    # 对照铁律（父代理指出并已修正）：
    #  * 可比对象 = **每次候选** 的当前预览路径（figpact.preview：重建 + 渲染 + QA +
    #    科学指纹 + JSON 解析），不是全 scope/全格式的严格出版（那是 final strict，
    #    单独计时，绝不拿它的 5s 去对比几何快车道的毫秒级并声称省了 50%）。
    #  * 两条通道都必须包含**同样的最终代价**：最终渲染器 + QA + 科学指纹。
    #    因此 warm 系列在 try_layout 之后必然再跑一次真实的 render_preview 取证。
    #  * 冷导入/初始化单独成列（每夹具一次），不混进单次候选对照。
    #  * 全部为**外部墙钟**，包含进程启动、IPC 往返与 JSON 解析。
    #  * warm QA 不是 Agent 试验：这里只有 backend 数据，报告不给任何 Agent 成功率。

    def backend_comparison(self, records) -> dict:
        from figpact.runtime import FigureWorker
        wanted = [record for record in records
                  if (record.get('expected') or {}).get('status') == STATUS_OK]
        if self.backend_samples and self.backend_samples < len(wanted):
            wanted = wanted[:self.backend_samples]
        samples = []
        for record in wanted:
            try:
                samples.append(self._backend_sample(record, FigureWorker))
            except Exception as error:
                samples.append({'task_id': record.get('id'),
                                'error': f'{type(error).__name__}: {error}'})
        cold = self._cold_init_samples(wanted)
        series = {
            'warm_accept_plus_proof_incl_init_s': [s.get('warm_total_incl_init_s') for s in samples],
            'warm_accept_plus_proof_excl_init_s': [s.get('warm_total_excl_init_s') for s in samples],
            'warm_accept_only_s': [s.get('warm_accept_s') for s in samples],
            'legacy_preview_process_s': [s.get('legacy_preview_wall_s') for s in samples],
            'final_strict_publication_s': [s.get('final_strict_wall_s') for s in samples],
        }
        summary = {name: summarize_timings([v for v in values if _finite(v)])
                   for name, values in series.items()}
        warm_p95 = summary['warm_accept_plus_proof_incl_init_s']['p95_s']
        legacy_p95 = summary['legacy_preview_process_s']['p95_s']
        return {
            'label': ('backend 对照：同样包含「最终渲染 + QA + 科学指纹」的两条候选通道；'
                      '本数据不是普通 Agent 试验，不含 solver'),
            'samples': samples,
            'cold_init': cold,
            'series': series,
            'summary': summary,
            'p95_ratio_preview_over_warm': (legacy_p95 / warm_p95) if warm_p95 and legacy_p95 else None,
            'comparability': {
                'compared': ['warm_accept_plus_proof_incl_init_s', 'legacy_preview_process_s'],
                'final_costs_in_both': ['full rebuild of the candidate', 'renderer pass producing the PNG',
                                        'existing QA verdict', 'science fingerprint capture',
                                        'JSON parse of the payload'],
                'external_elapsed_includes': ['process start', 'module import', 'IPC round trips'],
                'not_compared': ['final_strict_publication_s（全 scope/全格式严格出版，单独一列）',
                                 'warm_accept_only_s（快车道只看协议往返，单独一列；不与预览路径比倍数）'],
                'init_separation': 'warm 系列的 *_incl_init 与 *_excl_init 并列，冷导入另有 cold_init 一列',
                'cached_proof_note': ('warm 的取证渲染若命中会话内的同 revision 缓存（proof_cached_from_accept=true），'
                                      '说明渲染/QA/科学代价已经计在 accept_s 里，总时长仍然可比'),
                'yaml_write_excluded_from_both': '候选 YAML 落盘时间（candidate_yaml_write_s）两条通道都不计入，单独列出',
            },
            'basis': ('每个样本一条 OK 候选：warm = 新 worker 进程 open（导入/科学装载）+ try_layout + '
                      'render_preview 取证；legacy = 把候选 YAML 落盘后走当前 figpact.preview 子进程一次；'
                      '两者都外部计时、都含最终渲染/QA/科学代价，倍数只在两列都有样本时给出'),
        }

    def _cold_init_samples(self, records) -> dict:
        """冷导入/初始化：每夹具一次（不参与候选倍数的对照）。"""
        seen, samples = set(), []
        for record in records:
            fixture = str((ROOT / record['fixture']).resolve())
            if fixture in seen:
                continue
            seen.add(fixture)
            config = (ROOT / record['config']).resolve()
            task_dir = self.temp_root / 'backend' / 'cold'
            task_dir.mkdir(parents=True, exist_ok=True)
            copy = task_dir / f'{Path(record["config"]).stem}.yaml'
            if not copy.is_file():
                shutil.copy2(config, copy)
            result = self.probe({'mode': 'cold', 'task_id': f'cold-{Path(fixture).stem}',
                                 'fixture': record['fixture'], 'script': fixture,
                                 'scope': record['scope'], 'config': str(copy),
                                 'baseline_config': str(copy), 'expected_measurements': [],
                                 'invariants': []}, f'cold-{Path(fixture).stem}')
            samples.append({'fixture': record['fixture'], 'scope': record['scope'],
                            'external_wall_s': result.get('probe_wall_s'),
                            'internal': (result.get('cold') or {}).get('timings'),
                            'ok': bool(result.get('ok')), 'error': result.get('error')})
        values = [s.get('external_wall_s') for s in samples if _finite(s.get('external_wall_s'))]
        return {'samples': samples, 'summary': summarize_timings(values),
                'basis': '全新进程：解释器启动 + matplotlib 导入 + 夹具模块导入 + 配置/科学装载 + 一次 build_scene'}

    def _backend_sample(self, record, figure_worker_cls) -> dict:
        task_id = record.get('id')
        script = (ROOT / record['fixture']).resolve()
        config = (ROOT / record['config']).resolve()
        task_dir = self.temp_root / 'backend' / str(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        baseline_copy = task_dir / 'baseline.yaml'
        shutil.copy2(config, baseline_copy)
        operations = record.get('operations') or []
        sample = {'task_id': task_id, 'scope': record['scope'], 'fixture': record['fixture']}

        # 我们的通道：全新 warm worker（导入=一次）→ try_layout → 真实 render_preview 取证
        worker = figure_worker_cls(script, baseline_copy, record['scope'], python=self.python,
                                   cwd=str(ROOT), timeout=self.probe_timeout)
        try:
            phase = time.perf_counter()
            worker.open()
            open_s = time.perf_counter() - phase
            phase = time.perf_counter()
            outcome = worker.try_layout(operations)
            accept_s = time.perf_counter() - phase
            phase = time.perf_counter()
            preview = worker.render_preview()
            proof_s = time.perf_counter() - phase
            state = worker.state()
            candidate_config = state.get('candidate_config') if state.get('has_candidate') else None
        finally:
            worker.close()
        sample.update({
            'status': outcome.get('status'), 'verification': outcome.get('verification'),
            'worker_open_s': open_s, 'warm_accept_s': accept_s, 'warm_proof_s': proof_s,
            'warm_total_incl_init_s': open_s + accept_s + proof_s,
            'warm_total_excl_init_s': accept_s + proof_s,
            'proof_qa_kind': (preview or {}).get('qa_kind'),
            'proof_png_bytes': len((preview or {}).get('png') or ''),
            'proof_cached_from_accept': bool((preview or {}).get('cached')),
        })
        if candidate_config is None:
            sample['note'] = '会话未产出候选，跳过老后端对照'
            return sample
        candidate_path = task_dir / 'candidate.yaml'
        write_start = time.perf_counter()
        candidate_path.write_text(_yaml_dump(candidate_config), encoding='utf8')
        sample['candidate_yaml_write_s'] = time.perf_counter() - write_start

        # 当前预览后端：写 YAML 后一次全新 figpact.preview 子进程（重建 + 渲染 + QA + 科学）
        request = json.dumps({'script': str(script), 'config': str(candidate_path),
                              'scope': record['scope']}, ensure_ascii=False)
        legacy_start = time.perf_counter()
        completed = subprocess.run(
            [self.python, '-X', 'utf8', '-m', 'figpact.preview'],
            input=request, text=True, encoding='utf8', capture_output=True,
            cwd=str(ROOT), env={**os.environ, 'MPLBACKEND': 'Agg'}, timeout=self.probe_timeout)
        legacy_wall = time.perf_counter() - legacy_start
        qa_kind = None
        png_bytes = None
        if completed.returncode == 0:
            try:
                payload = json.loads(completed.stdout)
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                qa_kind = payload.get('qa_kind')
                png_bytes = len(payload.get('png') or '')
        sample.update({
            'legacy_preview_wall_s': legacy_wall, 'legacy_preview_returncode': completed.returncode,
            'legacy_preview_qa_kind': qa_kind, 'legacy_preview_png_bytes': png_bytes,
            'legacy_preview_stderr_tail': (completed.stderr or '')[-400:],
            'legacy_preview_json_parsed': qa_kind is not None,
        })

        # 严格出版：单独一列（全 scope/全格式），不参与倍数对照
        strict_start = time.perf_counter()
        strict = subprocess.run(
            [self.python, '-X', 'utf8', '-m', 'figpact', 'render', '--script', str(script),
             '--config', str(candidate_path), '--strict'],
            cwd=str(ROOT), capture_output=True, text=True, encoding='utf8',
            env={**os.environ, 'MPLBACKEND': 'Agg'}, timeout=self.probe_timeout)
        sample.update({'final_strict_wall_s': time.perf_counter() - strict_start,
                       'final_strict_returncode': strict.returncode,
                       'final_strict_stderr_tail': (strict.stderr or '')[-300:]})
        return sample

    def _agent_baseline(self, record) -> Path:
        """Agent 复核用的基线副本：绝不把探针指向仓库里的默认 YAML。"""
        target = self.temp_root / 'agent' / str(record.get('id')) / 'baseline.yaml'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            shutil.copy2((ROOT / record['config']).resolve(), target)
        return target

    # -- Agent 外部记录 ----------------------------------------------------- #

    @staticmethod
    def _empty_arm(arm: str, tasks_total: int) -> dict:
        return {'arm': arm, 'attempts': 0, 'attributed_attempts': 0,
                'verified': 0, 'successes': 0, 'failures': 0, 'unverified': 0,
                'verified_refusals': 0, 'verified_diagnostics': 0, 'replay_only': 0,
                'redo_attempts': 0, 'first_attempt_attempts': 0,
                'tasks_covered': 0, 'tasks_total': tasks_total, 'coverage': None, 'complete': False,
                'first_attempt_successes': 0, 'first_attempt_success_rate': None,
                'full_render_successes': 0,
                'wall_seconds_total': None, 'wall_seconds_observed_total': 0.0,
                'wall_seconds_missing': 0, 'raw_evidence_missing': 0, 'median_wall_seconds': None,
                'timing_complete': False, 'efficiency_claim_allowed': False}

    @staticmethod
    def _trial_entry(trial) -> dict:
        timing = _wall_metadata(trial)
        arm = str(trial.get('arm')).strip().upper() if isinstance(trial.get('arm'), str) else None
        if arm not in ARMS:
            arm = None
        attempt = trial.get('attempt')
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            attempt = None
        agent = trial.get('agent')
        agent = agent.strip() if isinstance(agent, str) and agent.strip() else None
        missing = [name for name, value in (('task_id', trial.get('task_id')), ('arm', arm),
                                            ('agent', agent), ('attempt', attempt))
                   if value in (None, '')]
        return {
            'task_id': trial.get('task_id'), 'arm': arm, 'declared_arm': trial.get('arm'),
            'agent': agent, 'attempt': attempt,
            'started_at': trial.get('started_at'), 'finished_at': trial.get('finished_at'),
            'wall_seconds': float(trial.get('wall_seconds')) if timing['available'] else None,
            'timing': timing,
            'raw': {'request': _raw_evidence(trial.get('raw_request')),
                    'response': _raw_evidence(trial.get('raw_response'))},
            'attributed': not missing, 'missing': missing,
            'candidate_config': trial.get('candidate_config'),
            'candidate_script': trial.get('candidate_script'),
            'declared_source_fingerprint': trial.get('source_fingerprint'),
            'diagnostic_only': trial.get('diagnostic_only') is True,
            'status': None, 'verified': False, 'success': False, 'evidence_kind': None,
            'full_render': False, 'failures': [], 'notes': [],
        }

    def agent_evidence(self, records) -> dict:
        """外部记录的普通 Agent 尝试：按 A/B/C 臂归组，只有被本验收器独立复核过的才算数。

        记录形状（父代理必须按这个喂；缺字段按「不可用」处理，绝不补默认值）见
        `TRIAL_FIELD_SPEC`（原样出现在报告的 `field_spec` 里）。

        证据规则：
        * 臂必须显式声明。正向候选一律由本验收器重新全量重建 + 渲染 + 跑 QA + 比对科学载荷；
          A 臂必须真的交了与原始夹具不同的 candidate_script，B/C 必须不动 Python。
        * 期望 CONFIG_ERROR 的负例：只接受「真实诊断 YAML + 原始不可变夹具 load_config 独立拒绝」。
          诊断 YAML 必须恰好等于「基线 + 请求的改动」（无关坏键不算），原始基线必须先证明装得下，
          再由原始夹具抛出真实 ConfigError；拒绝路径不许构建/留产物，也不许有可发布候选。
          拒绝不需要改 Python（保护科学、无操作拒绝同样成立）。
        * 期望 REFUSED / DIAGNOSED 的任务按「真实受阻」计：本验收器把请求原样重放到原始夹具上
          （原子会话拒绝 / 负效应校验），独立证明该请求确实不可接受才计入覆盖。
        * 记录自报的 status/success/源码指纹一律不采信；没有真实诊断路径 → 未验证的拒绝，不是成功。
        * 计时/请求原文缺失、臂缺失或尝试序号缺失 → 该条不可归属/不可用于效率结论，如实报不可用。
        * 覆盖门：每个臂都要在全部语料任务上有独立复核过的结论，否则不给任何总体成功率结论。
          速率的分母是全部真实尝试（失败/受阻/重放都在分母里），没有被丢掉。
        """
        total_tasks = len(records)
        arms = {arm: self._empty_arm(arm, total_tasks) for arm in ARMS}
        covered = {arm: set() for arm in ARMS}
        first_success = {arm: set() for arm in ARMS}
        wall_samples = {arm: [] for arm in ARMS}
        evidence = {
            'provided': False, 'source': None, 'source_sha256': None, 'schema': None,
            'status': 'unavailable', 'claim_allowed': False, 'success_rate': None,
            'verified_success_rate': None, 'tasks_total': total_tasks,
            'required_trial_fields': list(TRIAL_REQUIRED_FIELDS), 'field_spec': dict(TRIAL_FIELD_SPEC),
            'arms': arms,
            'coverage_gate': {
                'tasks_total': total_tasks, 'arms_required': list(ARMS),
                'arms_present': [], 'missing_arms': list(ARMS), 'per_arm': {},
                'all_arms_complete': False, 'complete': False,
                'basis': '每个臂都要在全部语料任务上给出独立复核过的结论'
                         '（正向候选重建，或独立证明的拒绝/受阻），缺一条就不算全覆盖'},
            'counts': {'records': 0, 'attributed': 0, 'unattributed': 0, 'verified': 0,
                       'successes': 0, 'failed_judged': 0, 'unverified': 0,
                       'verified_refusals': 0, 'verified_diagnostics': 0, 'replay_only': 0,
                       'unknown_tasks': 0, 'timing_unavailable': 0, 'raw_unavailable': 0},
            'verified_trials': 0, 'unverified_trials': 0, 'replay_trials': 0, 'successes': 0,
            'attempts': 0, 'trials': [], 'notes': [],
        }
        if self.agent_trials_path is None:
            evidence['notes'].append('本次运行没有提供 --agent-trials：普通 Agent 试验状态=未运行，'
                                     '不报告任何 Agent 成功率；本文件里的 backend 计时与 warm QA '
                                     '都不是 Agent 证据')
            return evidence
        payload = read_json(self.agent_trials_path)
        evidence.update(provided=True, status='provided', source=str(self.agent_trials_path),
                        source_sha256=sha256_file(self.agent_trials_path),
                        schema=payload.get('schema') if isinstance(payload, dict) else None)
        if evidence['schema'] != AGENT_SCHEMA:
            evidence['status'] = 'schema_mismatch'
            evidence['notes'].append(f'外部记录 schema 不是 {AGENT_SCHEMA}（实测 {evidence["schema"]!r}），'
                                     '按未验证处理；字段形状见 field_spec')
            return evidence
        index = {record.get('id'): record for record in records}
        counts = evidence['counts']
        for trial in payload.get('trials') or []:
            entry = self._trial_entry(trial)
            counts['records'] += 1
            arm = entry['arm']
            stats = arms.get(arm) if arm in arms else None
            if stats is not None:
                # 声明了臂的记录一律留在该臂的分母里；计时/原文缺失只影响效率结论。
                stats['attempts'] += 1
                if entry['timing']['available']:
                    stats['wall_seconds_observed_total'] += entry['wall_seconds']
                    wall_samples[arm].append(entry['wall_seconds'])
                else:
                    counts['timing_unavailable'] += 1
                    stats['wall_seconds_missing'] += 1
                if not (entry['raw']['request']['present'] and entry['raw']['response']['present']):
                    counts['raw_unavailable'] += 1
                    stats['raw_evidence_missing'] += 1
            if not entry['attributed']:
                counts['unattributed'] += 1
                entry.update(status='MISSING_METADATA', verified=False, success=False,
                             failures=[f"缺少可归属字段 {entry['missing']}"])
                if stats is not None:
                    stats['unverified'] += 1
                evidence['unverified_trials'] += 1
                evidence['trials'].append(entry)
                continue
            counts['attributed'] += 1
            evidence['attempts'] += 1
            stats['attributed_attempts'] += 1
            if entry['attempt'] == 1:
                stats['first_attempt_attempts'] += 1
            else:
                stats['redo_attempts'] += 1
            record = index.get(entry['task_id'])
            if record is None:
                counts['unknown_tasks'] += 1
                entry.update(status='UNKNOWN_TASK', verified=False, success=False,
                             failures=[f"语料里没有任务 {entry['task_id']!r}"])
                stats['unverified'] += 1
                evidence['unverified_trials'] += 1
                evidence['trials'].append(entry)
                continue
            try:
                self._judge_agent_trial(record, trial, entry)
            except Exception as error:
                # 单条坏记录不能掀翻整份报告：状态如实落在失败上，绝不当成成功。
                entry.update(status='TRIAL_ERROR', verified=False, success=False,
                             failures=[f'独立复核崩了：{type(error).__name__}: {error}'])
            if entry['success']:
                evidence['successes'] += 1
                stats['successes'] += 1
                covered[arm].add(entry['task_id'])
                if entry['attempt'] == 1:
                    first_success[arm].add(entry['task_id'])
                if entry['full_render']:
                    stats['full_render_successes'] += 1
            if entry['verified']:
                evidence['verified_trials'] += 1
                if not entry['success']:
                    counts['failed_judged'] += 1
                    stats['failures'] += 1
            else:
                evidence['unverified_trials'] += 1
                stats['unverified'] += 1
            kind = entry.get('evidence_kind')
            if kind == 'verified-refusal':
                counts['verified_refusals'] += 1
                stats['verified_refusals'] += 1
            elif kind == 'verified-diagnostic':
                counts['verified_diagnostics'] += 1
                stats['verified_diagnostics'] += 1
            if entry['status'] == 'REPLAY_ONLY':
                evidence['replay_trials'] += 1
                counts['replay_only'] += 1
                stats['replay_only'] += 1
            evidence['trials'].append(entry)

        gate = evidence['coverage_gate']
        gate['arms_present'] = [arm for arm in ARMS if arms[arm]['attempts']]
        gate['missing_arms'] = [arm for arm in ARMS if not arms[arm]['attempts']]
        for arm in ARMS:
            stats = arms[arm]
            stats['verified'] = stats['successes'] + stats['failures']
            stats['tasks_covered'] = len(covered[arm])
            stats['first_attempt_successes'] = len(first_success[arm])
            stats['coverage'] = (stats['tasks_covered'] / total_tasks) if total_tasks else None
            stats['complete'] = bool(total_tasks) and stats['tasks_covered'] == total_tasks
            attempts = stats['attempts']
            stats['attempt_success_rate'] = (stats['successes'] / attempts) if attempts else None
            stats['verified_rate'] = (stats['verified'] / attempts) if attempts else None
            stats['first_attempt_success_rate'] = (stats['first_attempt_successes'] / total_tasks
                                                   if total_tasks else None)
            stats['median_wall_seconds'] = quantile(wall_samples[arm], 0.5)
            stats['timing_complete'] = bool(attempts and not stats['wall_seconds_missing']
                                            and not stats['raw_evidence_missing'])
            stats['wall_seconds_total'] = (stats['wall_seconds_observed_total']
                                           if stats['timing_complete'] else None)
            stats['efficiency_claim_allowed'] = stats['timing_complete']
            if attempts and not stats['timing_complete']:
                evidence['notes'].append(
                    f"{arm} 臂计时/请求原文不完整（缺 {stats['wall_seconds_missing']} 条计时、"
                    f"{stats['raw_evidence_missing']} 条请求原文）：该臂不给任何效率说法")
            gate['per_arm'][arm] = {'tasks_covered': stats['tasks_covered'], 'tasks_total': total_tasks,
                                    'coverage': stats['coverage'], 'complete': stats['complete']}
        gate['all_arms_complete'] = bool(total_tasks) and all(arms[arm]['complete'] for arm in ARMS)
        gate['complete'] = bool(gate['all_arms_complete'] and not gate['missing_arms'])
        counts['verified'] = evidence['verified_trials']
        counts['unverified'] = evidence['unverified_trials']
        counts['successes'] = evidence['successes']
        evidence['success_rate'] = (evidence['successes'] / evidence['attempts']) if evidence['attempts'] else None
        evidence['verified_success_rate'] = (evidence['successes'] / evidence['verified_trials']) \
            if evidence['verified_trials'] else None
        evidence['first_attempt_successes'] = sum(len(first_success[arm]) for arm in ARMS)
        evidence['claim_allowed'] = bool(gate['complete'] and counts['successes']
                                         and not counts['unattributed'])
        if gate['missing_arms']:
            evidence['notes'].append(f"记录里缺少臂 {gate['missing_arms']}：没有三条工作流的实测，"
                                     '不给任何总体说法')
        if not gate['all_arms_complete']:
            evidence['notes'].append(
                f"覆盖门未过：需要每个臂都在全部 {total_tasks} 条任务上有独立复核过的结论，实测 "
                + str({arm: gate['per_arm'][arm]['tasks_covered'] for arm in ARMS}))
        if not evidence['claim_allowed'] and counts['successes']:
            evidence['notes'].append('没有全覆盖：成功率只是实测样本的比值，不能当作工作流成功率结论')
        if counts['failed_judged']:
            evidence['notes'].append(f"{counts['failed_judged']} 条被判失败的尝试仍留在分母里"
                                     '（没有丢掉坏样本）')
        return evidence

    # -- Agent 单条尝试的独立复核 ------------------------------------------ #

    def _judge_agent_trial(self, record, trial, entry) -> None:
        want = (record.get('expected') or {}).get('status')
        if want != STATUS_OK or trial.get('subject_decision') is not None:
            raw = trial.get('raw_response')
            try:
                if isinstance(raw, dict) and raw.get('path'):
                    raw = Path(raw['path']).read_text(encoding='utf8')
                answer = json.loads(raw) if isinstance(raw, str) else None
            except (ValueError, OSError):
                answer = None
            decision = answer.get('decision') if isinstance(answer, dict) else None
            expected_decision = ('CANDIDATE' if want == STATUS_OK else
                                 'DIAGNOSED' if want == STATUS_DIAGNOSED else 'REFUSED')
            if decision != expected_decision:
                entry['failures'].append(
                    f'真实 Agent 回执 {decision!r} 不符合 {expected_decision}；'
                    '不能把独立后端拒绝/诊断当成 Agent 正确作答')
            if trial.get('subject_decision') not in (None, decision):
                entry['failures'].append('subject_decision 与真实 raw_response 不一致')
        if want == STATUS_OK:
            self._judge_positive_trial(record, trial, entry)
        elif want == STATUS_CONFIG_ERROR:
            self._judge_config_error_trial(record, trial, entry)
        elif want in REFUSAL_STATUSES or want == STATUS_REFUSED:
            self._judge_blocked_trial(record, trial, entry)
        elif want == STATUS_DIAGNOSED:
            self._judge_diagnosed_trial(record, trial, entry)
        else:
            entry.update(status='UNSUPPORTED_EXPECTATION', verified=False, success=False,
                         failures=[f'语料期望状态 {want!r} 没有可独立复核的通道'])

    @staticmethod
    def _pristine_script(record):
        return (ROOT / record['fixture']).resolve()

    def _negative_guard(self, record, trial, entry, *, require_unchanged_config: bool) -> None:
        """负例的共同守卫：不许改 Python；期望「无生效改动」的任务不许交改动过的候选 YAML。"""
        pristine = self._pristine_script(record)
        script_raw = trial.get('candidate_script')
        if script_raw:
            script_path = Path(script_raw).resolve()
            if not script_path.is_file() or sha256_file(script_path) != sha256_file(pristine):
                entry['failures'].append('负例不许改 Python（科学保护）：candidate_script 与原始夹具不一致')
        candidate = trial.get('candidate_config')
        if not candidate:
            return
        candidate_path = Path(candidate)
        if not candidate_path.is_file():
            entry['failures'].append(f'候选 YAML 不存在：{candidate}')
            return
        entry['publishable_candidate'] = (
            candidate_path.read_bytes() != self._agent_baseline(record).read_bytes())
        if require_unchanged_config and entry['publishable_candidate']:
            entry['failures'].append('期望「无生效改动」的任务提交了改动过的候选 YAML：可发布文件被改动')

    def _judge_positive_trial(self, record, trial, entry) -> None:
        """正向候选：候选 YAML/脚本一律由本验收器重新全量重建 + 渲染 + QA + 科学载荷比对。"""
        failures, notes = entry['failures'], entry['notes']
        task_id = record.get('id')
        candidate = trial.get('candidate_config')
        if not candidate or not Path(candidate).is_file():
            entry.update(status='UNVERIFIED', verified=False, success=False,
                         failures=['没有可重建的候选 YAML：无法独立复核'])
            return
        pristine_script = self._pristine_script(record)
        candidate_script = pristine_script
        script_changed = False
        script_raw = trial.get('candidate_script')
        if script_raw:
            candidate_script = Path(script_raw).resolve()
            if not candidate_script.is_file():
                entry.update(status='UNVERIFIED', verified=False, success=False,
                             failures=[f'candidate_script 不存在：{candidate_script}'])
                return
            script_changed = sha256_file(candidate_script) != sha256_file(pristine_script)
        baseline_copy = self._agent_baseline(record)
        candidate_path = Path(candidate).resolve()
        config_changed = _load_yaml(candidate_path) != _load_yaml(baseline_copy)
        entry.update({'candidate_script_used': str(candidate_script), 'python_changed': script_changed,
                      'config_changed': config_changed})
        fit = judge_arm_fit(entry['arm'], script_changed, config_changed, failures, notes)
        if fit == 'replay':
            entry.update(status='REPLAY_ONLY', verified=False, success=False)
            return
        if fit == 'arm_violation':
            entry.update(status='ARM_VIOLATION', verified=False, success=False)
            return
        entry['evidence_kind'] = 'python-source' if script_changed else 'yaml-config'
        declared_fp = trial.get('source_fingerprint')
        request = {
            'task_id': f"agent-{task_id}-a{entry['attempt']}",
            'script': str(candidate_script),
            'baseline_script': str(pristine_script),
            'fixture': record['fixture'],
            'scope': record['scope'], 'baseline_config': str(baseline_copy),
            'candidate_config': str(candidate_path),
            'expected_measurements': (record.get('expected') or {}).get('measurements') or [],
            'invariants': (record.get('expected') or {}).get('science_invariants') or [],
            'mode': 'measure',
        }
        result = self.probe(request, f"agent-{task_id}-a{entry['attempt']}")
        candidate_facts = result.get('candidate') or {}
        baseline_facts = result.get('baseline') or {}
        fingerprint_value = (candidate_facts.get('source_fingerprint') or {}).get('value')
        entry.update({'candidate_source_fingerprint': candidate_facts.get('source_fingerprint'),
                      'baseline_source_fingerprint': baseline_facts.get('source_fingerprint'),
                      'candidate_manifest': candidate_facts.get('science_manifest'),
                      'declared_source_fingerprint': declared_fp,
                      'fingerprint_match': (None if declared_fp is None
                                            else declared_fp == fingerprint_value)})
        if entry['fingerprint_match'] is False:
            failures.append('记录声明的源码指纹与实测不一致')
        if not result.get('ok') or not candidate_facts:
            # 重建没跑完就没有「已验证」：状态如实落在失败上，也不计入 Agent 成功率。
            failures.append(f'重建失败：{result.get("error")}')
            entry.update(status='REBUILD_FAILED', verified=False, success=False)
            return
        for index_in, expected in enumerate(request['expected_measurements']):
            raw = (result.get('measurements') or [{}])[index_in].get('raw') if index_in < len(
                result.get('measurements') or []) else None
            outcome = judge_measurement(expected, raw)
            if not outcome.get('ok'):
                failures.append(f'测量 {expected.get("kind")} {expected.get("objects")}: {outcome.get("reason")}')
        for inv, verdict in (result.get('invariants') or {}).items():
            if verdict.get('ok') is False:
                failures.append(f'不变量 {inv} 被破坏：{verdict.get("reason")}')
        new_qa = [p for p in (candidate_facts.get('qa') or []) if p not in (baseline_facts.get('qa') or [])]
        if new_qa:
            failures.append(f'候选新增 QA 阻断项：{new_qa[:3]}')
        # 「全量渲染」只认真实重建证据：候选 PNG 真的写出来了、QA 真的跑过了。
        entry['full_render'] = bool(candidate_facts.get('staging_png')) and candidate_facts.get('qa') is not None
        entry['independent_rebuild'] = {
            'ok': bool(result.get('ok')),
            'measurements': len(result.get('measurements') or []),
            'invariants': {name: (verdict or {}).get('ok')
                           for name, verdict in (result.get('invariants') or {}).items()},
            'new_qa': new_qa, 'png': bool(candidate_facts.get('staging_png')),
            'source_fingerprint_matched': entry['fingerprint_match'],
        }
        entry.update(status='VERIFIED', verified=True, success=not failures)

    def _judge_config_error_trial(self, record, trial, entry) -> None:
        """期望 CONFIG_ERROR：只接受「真实诊断 YAML + 原始夹具 load_config 独立拒绝」。"""
        failures, notes = entry['failures'], entry['notes']
        task_id = record.get('id')
        pristine_script = self._pristine_script(record)
        baseline_copy = self._agent_baseline(record)
        entry['evidence_kind'] = 'unverified-refusal'
        self._negative_guard(record, trial, entry, require_unchanged_config=False)
        candidate = trial.get('candidate_config')
        if not candidate or not Path(candidate).is_file():
            failures.append('没有真实诊断候选 YAML：拒绝无法独立复核（未验证的拒绝不是成功）')
            entry.update(status='REFUSAL_UNVERIFIED', verified=False, success=False)
            return
        candidate_path = Path(candidate).resolve()
        if _inside_repo(candidate_path):
            failures.append(f'诊断 YAML 落在仓库内（{candidate_path}）：可发布文件不得被改动')
        try:
            requested = _apply_operations_to_config(_load_yaml(baseline_copy),
                                                    record.get('operations') or [])
        except (KeyError, ValueError, TypeError) as error:
            failures.append(f'请求的改动无法物化，拒绝无法归因：{type(error).__name__}: {error}')
            entry.update(status='REFUSAL_UNVERIFIED', verified=False, success=False)
            return
        baseline_before = sha256_file(baseline_copy)
        refusal = {'basis': 'pristine_load_config', 'pristine_script': str(pristine_script),
                   'diagnostic_only': entry['diagnostic_only'],
                   'intended_change': _load_yaml(candidate_path) == requested,
                   'candidate_differs_from_baseline': sha256_file(candidate_path) != baseline_before,
                   'loader_script': None, 'raised': None, 'stage': None, 'error_type': None,
                   'error': None, 'baseline_ok': None, 'baseline_error': None, 'probe_ok': None,
                   'builds': None, 'pngs': None, 'baseline_sha256_unchanged': None, 'config': None}
        result = self.probe({
            'task_id': f"agent-{task_id}-a{entry['attempt']}-config-error",
            'script': str(pristine_script), 'baseline_script': str(pristine_script),
            'fixture': record['fixture'], 'scope': record['scope'],
            'baseline_config': str(baseline_copy), 'config': str(candidate_path),
            'expected_measurements': [], 'invariants': [], 'mode': 'config_error',
        }, f"agent-{task_id}-a{entry['attempt']}-config-error")
        info = result.get('config_error') or {}
        probe_counts = result.get('counts') or {}
        refusal.update({'loader_script': info.get('loader_script'), 'raised': info.get('raised'),
                        'stage': info.get('stage'), 'error_type': info.get('error_type'),
                        'error': info.get('error'), 'baseline_ok': info.get('baseline_ok'),
                        'baseline_error': info.get('baseline_error'), 'config': info.get('config'),
                        'probe_ok': bool(result.get('ok')), 'builds': probe_counts.get('builds'),
                        'pngs': probe_counts.get('pngs'),
                        'baseline_sha256_unchanged': sha256_file(baseline_copy) == baseline_before})
        entry['refusal'] = refusal
        if not result.get('ok'):
            failures.append(f'独立装载探针失败：{result.get("error")}')
        judge_config_error_refusal(refusal, failures, notes)
        entry.update(status='VERIFIED_REFUSAL' if not failures else 'REFUSAL_UNVERIFIED',
                     verified=not failures, success=not failures,
                     evidence_kind='verified-refusal' if not failures else 'unverified-refusal')

    def _judge_blocked_trial(self, record, trial, entry) -> None:
        """期望 REFUSED：把请求原样重放到原始夹具的原子会话上，独立证明该批次确实被拒。"""
        failures, notes = entry['failures'], entry['notes']
        pristine_script = self._pristine_script(record)
        baseline_copy = self._agent_baseline(record)
        entry['evidence_kind'] = 'unverified-refusal'
        self._negative_guard(record, trial, entry, require_unchanged_config=False)
        before = self._artifact_listing()
        outcome, state, replay_error = {}, {}, None
        try:
            handle, _ = self.worker_for(pristine_script)
            handle.worker.open(config=str(baseline_copy), scope=record.get('scope'))
            handle.worker.try_layout([{'operation': 'reset'}])
            outcome = handle.worker.try_layout(record.get('operations') or []) or {}
            state = handle.worker.state() or {}
        except Exception as error:
            replay_error = f'{type(error).__name__}: {error}'
        refusal = self._refusal_evidence(state, baseline_copy)
        replay = {'basis': 'pristine_session_replay', 'error': replay_error,
                  'status': outcome.get('status'), 'verification': outcome.get('verification'),
                  'message': outcome.get('message'),
                  'state_mutated': refusal.get('state_mutated'),
                  'mutation_detail': refusal.get('mutation_detail'),
                  'has_candidate': refusal.get('has_candidate'), 'goals': refusal.get('goals'),
                  'session_observed': refusal.get('session_observed'),
                  'publishable_candidate': bool(entry.get('publishable_candidate')),
                  'artifacts': sorted(self._artifact_diff(before))}
        entry['refusal'] = replay
        if replay_error:
            failures.append(f'原始夹具会话重放失败：{replay_error}')
        else:
            judge_refusal_replay(record, replay, failures, notes)
        entry.update(status='BLOCKED_VERIFIED' if not failures else 'BLOCKED_UNVERIFIED',
                     verified=not failures, success=not failures,
                     evidence_kind='verified-refusal' if not failures else 'unverified-refusal')

    def _judge_diagnosed_trial(self, record, trial, entry) -> None:
        """期望 DIAGNOSED：独立跑原始夹具的负效应校验，逐条核对规则结论。"""
        failures = entry['failures']
        task_id = record.get('id')
        pristine_script = self._pristine_script(record)
        baseline_copy = self._agent_baseline(record)
        entry['evidence_kind'] = 'unverified-diagnostic'
        self._negative_guard(record, trial, entry, require_unchanged_config=True)
        tag = f"agent-{task_id}-a{entry['attempt']}-effects"
        result = self.probe({'task_id': tag, 'script': str(pristine_script),
                             'baseline_script': str(pristine_script), 'fixture': record['fixture'],
                             'scope': record.get('scope'), 'config': str(baseline_copy),
                             'baseline_config': str(baseline_copy), 'expected_measurements': [],
                             'invariants': [], 'mode': 'effects'}, tag)
        effects = result.get('effects')
        classified = self._classify_effects(record, effects)
        rules = {'|'.join(str(part) for part in (item.get('path') or [])): item.get('status')
                 for item in ((effects or {}).get('results') or [])}
        entry['diagnostic'] = {'basis': 'pristine_effects_check', 'classified': classified,
                               'effects_status': (effects or {}).get('status'), 'rules': rules,
                               'declared': list((record.get('expected') or {}).get('effects') or [])}
        if not result.get('ok'):
            failures.append(f'负效应探针失败：{result.get("error")}')
        if classified != STATUS_DIAGNOSED:
            failures.append(f'原始夹具的负效应校验判定为 {classified!r}，不是 DIAGNOSED：诊断不成立')
        entry.update(status='DIAGNOSED_VERIFIED' if not failures else 'DIAGNOSED_UNVERIFIED',
                     verified=not failures, success=not failures,
                     evidence_kind='verified-diagnostic' if not failures else 'unverified-diagnostic')

    # -- 主流程 ------------------------------------------------------------ #

    def run(self) -> dict:
        corpus = self.load_corpus()
        records = corpus.get('tasks') or corpus.get('records') or []
        if self.only:
            records = [r for r in records if r.get('id') in self.only]
        invariants_index = corpus.get('invariants') or {}
        guards_before = self.guard_hashes(corpus)
        started = time.time()
        reports = []
        for record in records:
            try:
                reports.append(self.run_task(record))
            except Exception as error:
                reports.append({'id': record.get('id'), 'verdict': {
                    'task_id': record.get('id'), 'passed': False,
                    'failures': [f'任务执行崩溃：{type(error).__name__}: {error}'],
                    'notes': [], 'traceback': traceback.format_exc()}, 'observed': {'errors': []}})
        guards_after = self.guard_hashes(corpus)
        guard_drift = {path: {'before': guards_before[path], 'after': guards_after.get(path)}
                       for path in guards_before if guards_after.get(path) != guards_before[path]}
        self.artifacts['repo_guard_drift'] = guard_drift

        task_walls = [r.get('timing', {}).get('session_wall_s') for r in reports]
        sample_series = [w for w in task_walls if _finite(w)]
        session_calls = [r.get('timing', {}).get('session_wall_s') for r in reports if _finite(r.get('timing', {}).get('session_wall_s'))]
        probe_calls = [r.get('timing', {}).get('probe_wall_s') for r in reports if _finite(r.get('timing', {}).get('probe_wall_s'))]
        totals = [((r.get('timing', {}).get('session_wall_s') or 0)
                   + (r.get('timing', {}).get('probe_wall_s') or 0)) for r in reports]
        count_totals = {
            'worker_process_spawns': sum(int(((r.get('counts') or {}).get('worker_spawned') or 0)) for r in reports),
            'worker_restarts': sum(int(((r.get('counts') or {}).get('worker_restarts') or 0)) for r in reports),
            'worker_opens_reused': sum(int(((r.get('counts') or {}).get('worker_opens') or 0)) for r in reports),
            'session_rebuilds_inferred': sum(int(((r.get('counts') or {}).get('session_rebuilds') or 0)) for r in reports),
            'session_renders': sum(1 for r in reports if (r.get('counts') or {}).get('session_rendered')),
            'independent_probe_rebuilds': sum(int(((r.get('counts') or {}).get('independent_rebuilds') or 0)) for r in reports),
            'pngs_written': sum(int(((r.get('counts') or {}).get('pngs') or 0)) for r in reports),
            'basis': ('spawns/restarts/pngs/opens 是可观察计数；session 内部重建数只在'
                      'RENDER_CHECKED 时按验证等级推断（basis 字段随任务记录），'
                      '几何快车道的 0 次重建同样是推断值，不是引擎计数器'),
        }

        backend = self.backend_comparison(records)
        agent = self.agent_evidence(records)
        passed = [r for r in reports if (r.get('verdict') or {}).get('passed')]
        ok = bool(reports) and len(passed) == len(reports) and not guard_drift and not self.mismatches

        report = {
            'schema': SCHEMA,
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'corpus': {'path': str(self.corpus_path), 'sha256': sha256_file(self.corpus_path),
                       'schema': corpus.get('schema'), 'fixture_root': corpus.get('fixture_root'),
                       'records': len(records), 'declared_groups': corpus.get('groups')},
            'environment': {
                'python': sys.version, 'executable': self.python, 'platform': platform.platform(),
                'cwd': str(ROOT),
            },
            'runner': {'executed': len(reports), 'passed': len(passed), 'failed': len(reports) - len(passed),
                       'wall_s': time.time() - started, 'temp_root': str(self.temp_root),
                       'temp_kept': bool(self.keep_temp)},
            'tasks': reports,
            'unsupported_statuses': self.unsupported,
            'measurement_mismatches': self.mismatches,
            'repo_guard': {'hashes': guards_before, 'drift': guard_drift},
            'timings': {
                'per_task': {r.get('id'): {'session_wall_s': r.get('timing', {}).get('session_wall_s'),
                                           'probe_wall_s': r.get('timing', {}).get('probe_wall_s')}
                             for r in reports},
                'session_call': summarize_timings(session_calls),
                'independent_probe_call': summarize_timings(probe_calls),
                'task_total': summarize_timings(totals),
                'session_series': summarize_timings(sample_series),
                'p95_task_wall_s': quantile(sample_series, 0.95),
                'basis': '真实样本；没有样本时为 null，不做外推',
            },
            'counts': count_totals,
            'backend_comparison': backend,
            'agent_evidence': agent,
            'claims': {
                'tasks': 'backend 执行：确定性运行器真实跑 runtime + 独立重建，不含 solver，也不是 Agent 试验',
                'backend_timing': ('backend_comparison 只对照「含最终渲染/QA/科学代价」的两条候选通道；'
                                   '冷导入另列，严格出版另列，不混算'),
                'warm_qa_is_not_agent_evidence': 'warm 预检/QA 通过只是 backend 证据，不能当作 Agent 成功',
                'agent_trials_status': agent.get('status'),
                'agent_success_rate': agent.get('success_rate') if agent.get('claim_allowed') else None,
                'agent_claim_allowed': bool(agent.get('claim_allowed')),
                'agent_coverage_gate': agent.get('coverage_gate'),
                'agent_trial_counts': agent.get('counts'),
                'note': ('普通 Agent 试验由父代理单独跑；本运行器在没有 --agent-trials 时明确报告'
                         '「未运行」并拒绝给出任何成功率。任何 ≥80% 的说法都必须来自真实 Agent '
                         '记录：每个臂都要在全部 30 条任务上有独立重建/渲染/QA/科学复核过的结论，'
                         '速率的分母是全部真实尝试（失败、拒绝、重放都留在分母里），'
                         '缺计时/请求原文的臂不给任何效率说法。'),
            },
            'invariants_index': invariants_index,
            'ok': ok,
        }
        return report


def _yaml_dump(data) -> str:
    import yaml
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _load_yaml(path):
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding='utf8'))
    return data if isinstance(data, dict) else {}


def _set_config_path(config, path, value) -> None:
    """按精确键段写值（与 session.set_path 同语义）：父节点/键段必须已存在。"""
    segments = list(path)
    if not segments:
        raise ValueError('路径不能为空')
    current = config
    for segment in segments[:-1]:
        match = [key for key in current if str(key) == str(segment)] if isinstance(current, dict) else []
        if len(match) != 1:
            raise KeyError(f'配置里没有路径 {segments}')
        current = current[match[0]]
    last = segments[-1]
    if isinstance(current, dict):
        match = [key for key in current if str(key) == str(last)]
        if not match:
            raise KeyError(f'配置里没有路径 {segments}')
        current[match[0]] = value
        return
    if isinstance(current, list) and isinstance(last, int):
        current[last] = value
        return
    raise KeyError(f'路径不可写 {segments}')


def _apply_operations_to_config(config, operations) -> dict:
    """候选配置 = 基线深拷贝 + 记录里逐条 `set_parameter`（原样取值、精确键段）。

    记录里的取值直接抄进去：验收器不解释「这是不是合理值」，那是 load_config 的活。
    任何非 set_parameter 的操作 / 不存在的路径都直接报错——物化不了就说物化不了，
    绝不造中间层、不跳过、也不退回未改动的基线。
    """
    candidate = copy.deepcopy(config)
    for raw in operations or []:
        if not isinstance(raw, dict) or raw.get('operation') != 'set_parameter':
            raise ValueError(f'无法物化候选配置：只接受 set_parameter，收到 {raw!r}')
        _set_config_path(candidate, raw.get('path') or [], raw.get('value'))
    return candidate


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='figpact vnext 30 任务验收运行器')
    parser.add_argument('--tasks', default=str(ROOT / 'eval' / 'vnext_tasks.json'),
                        help='任务语料 JSON（C 拥有）')
    parser.add_argument('--report', default=str(ROOT / 'eval' / 'vnext_acceptance_report.json'),
                        help='机器可读报告输出路径')
    parser.add_argument('--python', default=None, help='子进程解释器（默认当前解释器）')
    parser.add_argument('--only', action='append', default=[], help='只跑指定任务 id（可重复）')
    parser.add_argument('--backend-samples', type=int, default=0,
                        help='老 YAML 后端对照的样本任务数（0=全部 OK 任务）')
    parser.add_argument('--agent-trials', default=None,
                        help=f'外部记录的普通 Agent 尝试（schema {AGENT_SCHEMA}，字段见报告 field_spec），可选')
    parser.add_argument('--keep-temp', action='store_true', help='保留临时目录（含 PNG 证据）')
    parser.add_argument('--no-backend', action='store_true', help='跳过老后端对照（省时间）')
    parser.add_argument('--probe-timeout', type=float, default=420.0,
                        help='单个探针/工作进程请求的超时秒数')
    parser.add_argument('--probe', nargs=2, metavar=('REQUEST', 'RESPONSE'),
                        help='内部探针模式（子进程用；不要手写请求）')
    args = parser.parse_args(argv)

    if args.probe:
        return probe_main(Path(args.probe[0]), Path(args.probe[1]))

    corpus_path = Path(args.tasks)
    if not corpus_path.is_file():
        print(f'任务语料不存在：{corpus_path}', file=sys.stderr)
        return 2
    runner = AcceptanceRunner(corpus_path, python=args.python, keep_temp=args.keep_temp,
                              only=args.only, agent_trials=args.agent_trials,
                              backend_samples=0 if args.no_backend else args.backend_samples,
                              probe_timeout=args.probe_timeout)
    try:
        report = runner.run()
    finally:
        runner.close_workers()
    if not args.keep_temp:
        shutil.rmtree(runner.temp_root, ignore_errors=True)
    dump_json(Path(args.report), report)
    runner_summary = report['runner']
    print(f"任务 {runner_summary['executed']} 条：通过 {runner_summary['passed']}，"
          f"失败 {runner_summary['failed']}；报告 {args.report}")
    for task in report['tasks']:
        verdict = task.get('verdict') or {}
        if not verdict.get('passed'):
            print(f"  FAIL {task.get('id')}: {'; '.join(verdict.get('failures') or [])}")
    if report['repo_guard']['drift']:
        print(f"  仓库文件被改动：{sorted(report['repo_guard']['drift'])}")
    return 0 if report.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
