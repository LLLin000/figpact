"""参数效果验证：**真实临时 YAML 扰动 + 真实整图重建**。

绝不通过直接改 Artist 属性来「证明」YAML 生效——那样证明的是 matplotlib，不是配置绑定。
每一步都写出真实的扰动 YAML 文件、跑一次真实构建，再比较前后实测的
显示几何（mm）、样式与科学指纹。

单参数结论：
- `EFFECT_OK`          声明的作用对象/轴/方向/量级与实测一致，未牵连未声明对象，科学指纹不变。
- `NO_EFFECT`          重建后没有任何可测变化（声明了却不生效，或根本没接线）。
- `EFFECT_MISMATCH`    有变化，但与声明不符（对象集合、轴、方向、量级、或牵连了未声明对象）。
- `SCIENCE_VIOLATION`  显示参数的改动改变了科学指纹。
- `REJECTED_*`         声明本身不可用：未分类 / 锁定 / 固定样式 / 派生 / 路径不在 YAML 里 /
                       作用对象不在注册表里 / 扰动量无界 / 脚本拒绝该扰动值。
"""
from __future__ import annotations

import copy
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from figpact.session import (
    DERIVED, EDITABLE, FIXED_STYLE, LOCKED_SCIENCE, STATUS_OK, UNCLASSIFIED,
    FigureSession, _finite, _owned_keys, _pair_of, drawn_shapes, get_path, set_path, shape_delta,
)
from figpact.units import MM_PER_INCH

#: 单参数结论词表。
EFFECT_OK = 'EFFECT_OK'
NO_EFFECT = 'NO_EFFECT'
EFFECT_MISMATCH = 'EFFECT_MISMATCH'
SCIENCE_VIOLATION = 'SCIENCE_VIOLATION'
REJECTED_UNCLASSIFIED = 'REJECTED_UNCLASSIFIED'
SKIPPED_LOCKED_SCIENCE = 'SKIPPED_LOCKED_SCIENCE'
SKIPPED_FIXED_STYLE = 'SKIPPED_FIXED_STYLE'
SKIPPED_DERIVED = 'SKIPPED_DERIVED'
REJECTED_DANGLING_PATH = 'REJECTED_DANGLING_PATH'
REJECTED_DANGLING_OBJECT = 'REJECTED_DANGLING_OBJECT'
REJECTED_UNBOUNDED_PROBE = 'REJECTED_UNBOUNDED_PROBE'
REJECTED_PERTURBATION = 'REJECTED_PERTURBATION'
UNSUPPORTED_NO_CONTRACT = 'UNSUPPORTED_NO_CONTRACT'
UNSUPPORTED_NO_PARAMETERS = 'UNSUPPORTED_NO_PARAMETERS'

REJECTED = {REJECTED_UNCLASSIFIED, REJECTED_DANGLING_PATH, REJECTED_DANGLING_OBJECT,
            REJECTED_UNBOUNDED_PROBE, REJECTED_PERTURBATION}
#: 声明为不可编辑（锁定科学 / 固定样式 / 派生）→ 不做扰动，也不算缺陷。
SKIPPED = {SKIPPED_LOCKED_SCIENCE, SKIPPED_FIXED_STYLE, SKIPPED_DERIVED}

_STYLE_NUMERIC_TOL = 1e-9


# --------------------------------------------------------------------------- #
# 扰动量
# --------------------------------------------------------------------------- #

def probe_value(record, current):
    """给一个**有界**且能测出来的扰动值：优先用声明区间，否则按当前值的 10%。"""
    lo, hi = record.get('min'), record.get('max')
    for step in (1.0, 0.5, 2.0, 5.0, 0.1):
        for candidate in (current + step, current - step):
            if lo is not None and candidate < float(lo):
                continue
            if hi is not None and candidate > float(hi):
                continue
            if candidate != current:
                return float(candidate)
    if current not in (0, 0.0):
        candidate = current * 1.1
        if lo is not None and candidate < float(lo):
            return None
        if hi is not None and candidate > float(hi):
            return None
        return float(candidate)
    return None


def _pair_perturbation(record, pair):
    """2D 参数只扰动**一条轴**：返回 `(probe, axis, delta)`，两轴都扰不动返回三个 None。

    同时改两个分量会把「哪条轴真的接线了」混成一个数，所以这里挑第一条能给出有界
    扰动的轴，另一分量**原样保留**；结论只覆盖被扰动的那条轴（轴与增量都进报告）。
    """
    for index, axis in ((0, 'x'), (1, 'y')):
        moved = probe_value(record, pair[index])
        if moved is not None and moved != pair[index]:
            probe = list(pair)
            probe[index] = moved
            return probe, axis, moved - pair[index]
    return None, None, None


def _style_changes(before, after, gids):
    out = {}
    for gid in gids:
        b, a = before.get(gid) or {}, after.get(gid) or {}
        props = {}
        for prop in sorted(set(b) | set(a)):
            vb, va = b.get(prop), a.get(prop)
            if isinstance(vb, float) and isinstance(va, float):
                if abs(vb - va) <= _STYLE_NUMERIC_TOL:
                    continue
            elif vb == va:
                continue
            props[prop] = [vb, va]
        if props:
            out[gid] = props
    return out


def _geometry_changes(before, after):
    """(改变的显示几何→增量, 新增键, 消失键)，含实际测量的布局容器边界。"""
    changed, added, removed = {}, [], []
    for key in sorted(set(before) - set(after)):
        removed.append(key)
    for key in sorted(set(after) - set(before)):
        added.append(key)
    for key in sorted(set(before) & set(after)):
        b, a = before[key], after[key]
        delta = shape_delta(b, a)
        tol = delta['tol_mm']
        if max(abs(delta['dx_mm']), abs(delta['dy_mm']),
               abs(delta['dw_mm']), abs(delta['dh_mm'])) > tol:
            delta = {k: round(v, 4) if isinstance(v, float) else v for k, v in delta.items()}
            changed[key] = delta
    return changed, added, removed


def _observed_axis(changes):
    """全部增量落在同一条轴上时给出该轴；混合则 'mixed'；无几何变化则 None。"""
    axes = set()
    for delta in changes.values():
        dx, dy = abs(delta['dx_mm']), abs(delta['dy_mm'])
        dw, dh = abs(delta['dw_mm']), abs(delta['dh_mm'])
        if dw > delta['tol_mm'] or dh > delta['tol_mm']:
            axes.add('size')
        if dx > delta['tol_mm']:
            axes.add('x')
        if dy > delta['tol_mm']:
            axes.add('y')
    if not axes:
        return None
    if len(axes) == 1:
        return axes.pop()
    return 'mixed'


def _matches_declaration(record, changes, styles, observed_axis, delta_value=None, closure=(),
                         owned_keys=(), pair_axis=None):
    """逐条对照声明；返回 (status, diagnostics)。

    「响应」既包括毫米几何变化，也包括样式变化；translate 声明还要核对**物理量**
    （`scale` × 单位换算 × 扰动量）与**方向**，不然一个 0.1× 的错绑定或反号绑定
    会被当成「轴对了就算对」。

    `closure` 是声明对象的后代闭包（面板里的图像/比例尺/文字等）：它们跟着父对象动是
    声明的一部分，不算「牵连了未声明对象」；闭包内、声明外的东西同样要跟着动（刚体）。

    `pair_axis` 是**2D 位移对**（`[dx, dy]`，只扰动了一条轴的探针）被扰动的那条轴：
    这时位置变化就是声明本身（不该按 `expected.kind == "style"` 读成「只有位置动了」），
    但被扰动轴的物理量、方向与轴一致性照旧要核对。
    """
    diagnostics = []
    expected = record.get('expected') or {}
    declared = list(expected.get('objects') or record.get('objects') or [])
    closure_set = {gid for gid in closure}
    seen_gids = {key.split(':', 1)[1] if key.startswith('gid:') else key for key in changes}
    seen_gids |= set(styles or {})
    declared_set, seen_set = set(declared), seen_gids
    if not changes and not styles:
        return NO_EFFECT, [f'真实重建后没有任何可测变化（声明作用于 {declared}）']
    missing = sorted(declared_set - seen_set)
    owned_unregistered = {key for key in owned_keys if not key.startswith('gid:')}
    undeclared = sorted(seen_set - declared_set - closure_set - owned_unregistered)
    if undeclared:
        diagnostics.append(f'牵连了未声明对象（也不是声明对象的后代）：{undeclared}')
    preserve = list(expected.get('preserve') or [])
    preserved_changed = sorted(set(preserve) & seen_set)
    if preserved_changed:
        diagnostics.append(f'声明保持不动的对象却动了：{preserved_changed}')
    if missing:
        diagnostics.append(f'声明的作用对象没有全部响应：{missing}')
    kind = expected.get('kind') or record.get('operation')
    declared_axis = pair_axis or expected.get('axis') or record.get('axis')
    if kind == 'resize' and declared_axis in ('x', 'y'):
        cross = ('dy_mm', 'dh_mm') if declared_axis == 'x' else ('dx_mm', 'dw_mm')
        if any(abs(entry[field]) > entry['tol_mm'] for entry in changes.values() for field in cross):
            diagnostics.append(f'尺寸变化牵连了声明轴 {declared_axis} 以外的几何')
    elif declared_axis and observed_axis and observed_axis != declared_axis and observed_axis != 'size':
        diagnostics.append(f'轴不符：声明 {declared_axis}，实测 {observed_axis}')
    if kind == 'translate' and observed_axis == 'size':
        diagnostics.append('声明是平移，实测却是尺寸变化')
    if pair_axis is None and kind in ('resize', 'style') and observed_axis in ('x', 'y') \
            and not styles:
        diagnostics.append(f'声明是 {kind}，实测只有位置平移')
    if styles and kind == 'translate' and not changes:
        diagnostics.append('声明是平移，实测只有样式变化')
    if kind == 'translate' and declared_axis in ('x', 'y') and delta_value:
        diagnostics.extend(_magnitude_checks(record, changes, declared_set | closure_set,
                                            declared_axis, delta_value))
    if kind == 'resize' and declared_axis in ('x', 'y') and delta_value:
        diagnostics.extend(_magnitude_checks(record, changes, declared_set,
                                            declared_axis, delta_value, kind='resize'))
    if pair_axis and delta_value:
        # 2D 位移对：只扰动了一条轴，结论只覆盖那条轴；被扰动轴的物理量（单位 × 标尺）
        # 与轴一致性照旧要核对，`expected.kind` 是 style 也不许把位置变化当成缺陷。
        diagnostics.extend(_magnitude_checks(record, changes, declared_set | closure_set,
                                            pair_axis, delta_value))
    if diagnostics:
        return EFFECT_MISMATCH, diagnostics
    return EFFECT_OK, [f'实测作用于 {sorted(seen_set)}，轴 {observed_axis or "size"}']


def _magnitude_checks(record, changes, declared_set, axis, delta_value, *, kind='translate'):
    """核对已声明对象的实际位移或尺寸变化与单位、标尺、方向一致。"""
    unit = record.get('unit') or 'mm'
    if unit not in ('mm', 'pt'):
        return []
    per_unit_mm = 1.0 if unit == 'mm' else MM_PER_INCH / 72.0
    scale = float(record.get('scale', 1.0) or 1.0)
    expected_mm = delta_value * scale * per_unit_mm
    out = []
    for key, entry in sorted(changes.items()):
        gid = key.split(':', 1)[1] if key.startswith('gid:') else key
        if gid not in declared_set:
            continue
        field = ('dw_mm' if axis == 'x' else 'dh_mm') if kind == 'resize' else (
            'dx_mm' if axis == 'x' else 'dy_mm')
        along = entry[field]
        tol = entry.get('tol_mm') or 0.0
        if abs(along - expected_mm) > tol:
            out.append(f'{gid} 实测位移 {round(along, 4)} mm 与声明的物理量 '
                       f'{round(expected_mm, 4)} mm 不符（容差 {tol} mm）')
    return out


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def check_effects(script, config, scope, *, contract=None):
    """对作用域内每个声明参数做一次真实 YAML 扰动 + 整图重建，逐条给出结论。"""
    session = FigureSession(script, config, scope, contract=contract)
    results = []
    try:
        baseline = session._baseline
        base_config = copy.deepcopy(session._base_config)
        base_shapes = baseline['shapes']
        base_styles = baseline['styles']
        contract_source = session.contract.get('source')
        if contract_source == 'absent':
            return {'status': UNSUPPORTED_NO_CONTRACT, 'script': str(session.script),
                    'config': str(session.config), 'scope': scope, 'contract_source': 'absent',
                    'parameters': 0, 'counts': {}, 'results': [],
                    'message': '脚本没有 layout_contract(scope) 声明；没有安全映射就不猜，'
                               '不跑扰动、也不声称参数有效。',
                    'baseline': {'science': _science_summary(baseline['science']),
                                 'qa_kind': baseline['qa']['qa_kind'],
                                 'qa_count': len(baseline['qa']['qa'])},
                    'notes': []}
        if not session.parameters():
            return {'status': UNSUPPORTED_NO_PARAMETERS, 'script': str(session.script),
                    'config': str(session.config), 'scope': scope,
                    'contract_source': contract_source, 'parameters': 0, 'counts': {}, 'results': [],
                    'message': f'布局契约里没有属于作用域 {scope} 的参数声明。',
                    'baseline': {'science': _science_summary(baseline['science']),
                                 'qa_kind': baseline['qa']['qa_kind'],
                                 'qa_count': len(baseline['qa']['qa'])},
                    'notes': []}
        tmpdir = tempfile.TemporaryDirectory(prefix='figpact-effects-')
        tmp = Path(tmpdir.name)
        for index, record in enumerate(session.parameters()):
            results.append(_check_one(session, record, index, base_config, base_shapes,
                                      base_styles, tmp))
        tmpdir.cleanup()
        counts = {}
        for entry in results:
            counts[entry['status']] = counts.get(entry['status'], 0) + 1
        status = STATUS_OK if all(e['status'] == EFFECT_OK or e['status'] in SKIPPED
                                  for e in results) else 'DEFECTS_FOUND'
        return {'status': status, 'script': str(session.script), 'config': str(session.config),
                'scope': scope, 'contract_source': contract_source,
                'parameters': len(results), 'counts': counts, 'results': results,
                'baseline': {'science': _science_summary(baseline['science']),
                             'qa_kind': baseline['qa']['qa_kind'],
                             'qa_count': len(baseline['qa']['qa'])},
                'notes': ['每一条结论都来自一次真实临时 YAML 扰动 + 真实整图重建；'
                          '没有直接改 Artist 的伪证。',
                          '几何增量按显示几何测量：折线用顶点位移，文本/图像包络用包围盒中心，'
                          '容差随渲染栅格（文本约 1.6 px）。']}
    finally:
        session.close()


def _science_summary(captured):
    return {'verified': captured.get('verified'), 'digest': captured.get('digest'),
            'reason': captured.get('reason')}


def _check_one(session, record, index, base_config, base_shapes, base_styles, tmpdir):
    key = record.get('key')
    entry = {'key': key, 'path': list(record.get('path') or []), 'index': index,
             'unit': record.get('unit'), 'operation': record.get('operation'),
             'mutability': record.get('mutability'), 'declared_objects': list(record.get('objects') or []),
             'declared': record.get('expected') or {}}
    try:
        path = tuple(str(seg) for seg in record.get('path') or [])
    except Exception as error:
        entry.update(status=REJECTED_UNCLASSIFIED, diagnostics=[f'path 不可用：{error}'])
        return entry
    if not path:
        entry.update(status=REJECTED_UNCLASSIFIED, diagnostics=['参数记录缺少 path'])
        return entry
    mutability = record.get('mutability') if record.get('mutability') in (
        EDITABLE, LOCKED_SCIENCE, FIXED_STYLE, DERIVED) else UNCLASSIFIED
    if mutability == UNCLASSIFIED:
        entry.update(status=REJECTED_UNCLASSIFIED, diagnostics=['未声明可变性（缺失即失败）'])
        return entry
    if mutability == LOCKED_SCIENCE:
        entry.update(status=SKIPPED_LOCKED_SCIENCE, diagnostics=['锁定科学内容，不做扰动'])
        return entry
    if mutability in (FIXED_STYLE, DERIVED):
        entry.update(status=SKIPPED_FIXED_STYLE if mutability == FIXED_STYLE else SKIPPED_DERIVED,
                     diagnostics=[f'声明为 {mutability}，不可编辑，不做扰动'])
        return entry
    try:
        raw_current = get_path(base_config, path)
    except KeyError as error:
        entry.update(status=REJECTED_DANGLING_PATH,
                     diagnostics=[f'配置里没有这个精确路径：{error}'])
        return entry
    axis = None
    pair = _pair_of(raw_current)
    if pair is not None:
        # 配置里本来就是一对 [dx, dy]：只有声明为 rebuild（真实重建）才谈这个形状。
        if record.get('operation') != 'rebuild':
            entry.update(status=REJECTED_PERTURBATION,
                         diagnostics=[f'配置里是一对 [dx, dy]，但声明不是 rebuild：序列值只允许'
                                      f'出现在声明为 2D 位移（rebuild）的参数上'])
            return entry
        probe, axis, delta_value = _pair_perturbation(record, pair)
        if probe is None:
            entry.update(status=REJECTED_UNBOUNDED_PROBE,
                         diagnostics=[f'两条轴都得不到有界扰动（当前 {pair}，'
                                      f'区间 [{record.get("min")}, {record.get("max")}]）'])
            return entry
        current = list(pair)
    else:
        try:
            current = _finite(raw_current, f'{list(path)} 的当前值')
        except ValueError as error:
            entry.update(status=REJECTED_DANGLING_PATH,
                         diagnostics=[f'配置里没有这个精确路径：{error}'])
            return entry
        probe = probe_value(record, current)
        if probe is None or probe == current:
            entry.update(status=REJECTED_UNBOUNDED_PROBE,
                         diagnostics=[f'无法在声明区间内给出有界扰动（当前 {current}，'
                                      f'区间 [{record.get("min")}, {record.get("max")}]）'])
            return entry
        delta_value = probe - current
    entry['current'] = current
    candidates = [probe]
    if axis is None:
        opposite = 2.0 * current - probe
        if ((record.get('min') is None or opposite >= float(record['min']))
                and (record.get('max') is None or opposite <= float(record['max']))):
            candidates.append(opposite)
    rejected = []
    yaml_path = Path(tmpdir) / f'perturb-{index:03d}-{str(key).replace("/", "_")[:40]}.yaml'
    for probe in candidates:
        perturbed = copy.deepcopy(base_config)
        set_path(perturbed, path, probe)
        yaml_text = yaml.safe_dump(perturbed, sort_keys=False, allow_unicode=True)
        yaml_path.write_text(yaml_text, encoding='utf8')
        entry.update(perturbation={'from': current, 'to': probe},
                     yaml=str(yaml_path), yaml_text=yaml_text)
        if axis is not None:
            entry['perturbation']['axis'] = axis
        try:
            with redirect_stdout(io.StringIO()):
                fig, reg = session.build_from_yaml(yaml_path)
            break
        except ValueError as error:
            # 在完整布局的边界处，一侧不可行不代表绑定失效；仅试同量、区间内的另一侧。
            rejected.append({'value': probe, 'error': f'{type(error).__name__}: {error}'})
        except Exception as error:
            entry.update(status=REJECTED_PERTURBATION,
                         diagnostics=[f'扰动重建失败：{type(error).__name__}: {error}'])
            return entry
    else:
        entry.update(status=REJECTED_PERTURBATION,
                     diagnostics=['所有可用的有界扰动均被实际布局约束拒绝'],
                     rejected_probes=rejected)
        return entry
    if rejected:
        entry['rejected_probes'] = rejected
    try:
        with redirect_stdout(io.StringIO()):
            after_shapes = drawn_shapes(fig, reg, include_frames=True)
        after_styles = session._styles(fig, reg)
        after_science = session._capture_science(fig, reg)
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)
    geometry, added, removed = _geometry_changes(base_shapes, after_shapes)
    changed_gids = {k.split(':', 1)[1] for k in geometry if k.startswith('gid:')}
    missing_objects = [gid for gid in (record.get('objects') or [])
                       if f'gid:{gid}' not in base_shapes]
    if missing_objects:
        entry.update(status=REJECTED_DANGLING_OBJECT,
                     diagnostics=[f'声明的作用对象不在当前注册/可见几何里：{missing_objects}'])
        return entry
    styles = _style_changes(base_styles, after_styles, sorted(set(base_styles) | set(after_styles)))
    observed_axis = _observed_axis(geometry)
    entry['observed'] = {
        'objects': sorted(changed_gids), 'axis': observed_axis,
        'geometry': geometry, 'styles': styles,
        'structure': {'added': added, 'removed': removed},
        'science': _science_summary(after_science),
    }
    science_ok, science_notes = session._compare_science(
        session._baseline['science'], after_science)
    if science_ok is False:
        entry.update(status=SCIENCE_VIOLATION,
                     diagnostics=['显示参数的扰动改变了科学指纹：' + '; '.join(map(str, science_notes))])
        return entry
    if added or removed:
        entry.update(status=EFFECT_MISMATCH,
                     diagnostics=[f'扰动改变了可见结构：新增 {added}，消失 {removed}'])
        return entry
    closure = session.owned_closure(record.get('objects') or [])
    owned_keys = _owned_keys(base_shapes, closure) | _owned_keys(after_shapes, closure)
    status, notes = _matches_declaration(record, geometry, styles, observed_axis,
                                         delta_value=delta_value,
                                         closure=closure, owned_keys=owned_keys,
                                         pair_axis=axis)
    if axis is not None:
        notes = list(notes) + [f'2D 参数只扰动 {axis} 轴（另一分量保持原值）：'
                               f'本条结论只覆盖被扰动的那条轴']
    entry.update(status=status, diagnostics=notes,
                 science_unchanged=science_ok,
                 science_notes=[] if science_ok else list(map(str, science_notes)))
    return entry
