"""G2 geometry intents: real YAML rebuilds, independent target checks, no file writes.

Acceptance is in-memory only. A fresh FigureSession evaluates each absolute goal
set, so failed/cancelled B never resets accepted A or accumulates Artist transforms.
"""
from __future__ import annotations

import copy
import json
import math
import re
import uuid
from typing import Any, cast

import matplotlib
import matplotlib.pyplot as plt

from .inspector import capture_figure
from .science import capture_science, compare_science
from .session import FigureSession, get_path, source_revision

IMPACT_TOL_MM = 1e-3  # Same-renderer numeric comparison, not a calibrated physical error bound.


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('位移和容差必须是有限数字，不能使用布尔值')
    return float(value)


def _delta(request):
    value = request.get('delta_mm')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        vectors = {'up': (0., 1.), 'down': (0., -1.), 'left': (-1., 0.), 'right': (1., 0.)}
        direction = request.get('direction')
        if direction not in vectors:
            raise ValueError('标量位移必须明确 up/down/left/right 方向')
        return [_finite(value) * component for component in vectors[direction]]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('delta_mm 必须是 [dx, dy]，或带明确方向的标量')
    return [_finite(component) for component in value]


def _nodes(frame):
    return {node['id']: node for node in json.loads(frame['scene_json'])['nodes']}


def _numeric_error(before, after):
    if isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)):
        if len(before) != len(after):
            return math.inf
        return max((_numeric_error(a, b) for a, b in zip(before, after)), default=0.)
    if isinstance(before, (float, int)) and isinstance(after, (float, int)):
        return abs(float(after) - float(before))
    return 0. if before == after else math.inf


def _geometry_error(before, after):
    if before is None or after is None:
        return math.inf
    keys = ('bounds_mm', 'runs_mm', 'fully_clipped', 'hit_mode', 'stroke', 'linewidth_mm',
            'linestyle', 'marker', 'rotation_deg', 'text', 'type')
    return max((_numeric_error(before.get(key), after.get(key)) for key in keys), default=0.)


def _overflow(node, canvas):
    bounds = node.get('bounds_mm')
    if bounds is None:
        return math.inf
    return max(0., canvas[0] - bounds[0], canvas[1] - bounds[1],
               bounds[2] - canvas[2], bounds[3] - canvas[3])


class IntentSession:
    """Single-owner, single-pending-candidate Inspector session; never publishes/saves."""

    def __init__(self, *, script=None, config=None, scope='measurement', figure=None,
                 registry=None, contract=None, science_manifest=None, dpi=None):
        if dpi is not None and (type(dpi) is not int or dpi not in (120, 240, 600)):
            raise ValueError('显示清晰度只支持 120、240 或 600 DPI')
        if figure is not None and dpi is not None:
            raise ValueError('不能为了显示清晰度修改传入的原始 Figure；请在创建图时设置 DPI')
        self.session_id = str(uuid.uuid4())
        self.scope = scope
        self._core: FigureSession | None = None
        self._accepted: list[dict[str, Any]] = []
        self._pending: dict[str, Any] | None = None
        self._frame: dict[str, Any]
        self._closed = False
        self._dpi = float(dpi) if dpi is not None else None
        self._source = None
        self._contract_override = contract
        self._rc_style = None
        if figure is not None:
            if script is not None or config is not None:
                raise ValueError('普通 Figure 测量和 YAML 会话不能混用')
            self._frame = capture_figure(figure, registry, scope=scope,
                                         contract=contract, science_manifest=science_manifest)
        else:
            if script is None or config is None:
                raise ValueError('编辑候选需要明确 script/config；只读测量可以直接传 Figure')
            with matplotlib.rc_context():
                self._core = FigureSession(script, config, scope, contract=contract)
                self._rc_style = matplotlib.rcParams.copy()
                try:
                    self._source = self._core.state()['source_revision']
                    self._frame, self._science = self._capture(self._core)
                    self._baseline = copy.deepcopy(self._frame)
                except Exception:
                    self._core.close()
                    raise
        self._frame = self._decorate(self._frame)

    def _decorate(self, frame):
        frame['session'] = {'session_id': self.session_id,
            'scene_revision': frame['frame_revision'], 'source_revision': self._source,
            'can_evaluate': bool(self._core and self._core.science_manifest and not self._closed),
            'accepted_operation_ids': [operation['id'] for operation in self._accepted]}
        return frame

    def _capture(self, core):
        fig, registry = core.build_candidate(core.candidate_config)
        try:
            if self._dpi is None:
                self._dpi = float(fig.dpi)
            if fig.images and float(fig.dpi) != self._dpi:
                raise ValueError('图幅像素图像不能在未证明物理尺寸保持时更换 DPI')
            fig.set_dpi(self._dpi)
            scientific = capture_science(fig, registry, declarations=core.science_manifest)
            fig.canvas.draw()
            qa = core._qa(fig)
            if compare_science(scientific, capture_science(fig, registry, declarations=core.science_manifest)):
                raise ValueError('当前图检查改变了科学内容，不能接受')
            frame = capture_figure(fig, registry, scope=self.scope, contract=core.contract,
                science_manifest=core.science_manifest, source_revision=self._source)
            frame['qa'] = qa
            return self._decorate(frame), scientific
        finally:
            plt.close(fig)

    def _current_source(self):
        assert self._core is not None
        state = cast(dict[str, Any], self._core.state())
        return source_revision(state['script'], state['config'],
            exclude=state['artifact_outputs'], required=state['science_inputs'])

    def _guard(self, request):
        if self._closed:
            return 'STALE_REVISION'
        if not isinstance(request, dict):
            return 'INVALID_INTENT'
        if (request.get('session_id') != self.session_id or
                request.get('scene_revision') != self._frame['frame_revision'] or
                request.get('source_revision') != self._source):
            return 'STALE_REVISION'
        if self._core is not None:
            try:
                if self._current_source() != self._source:
                    return 'STALE_REVISION'
            except OSError:
                return 'STALE_REVISION'
        return None

    def snapshot(self):
        """Paired accepted frame, never the last pending trial."""
        if self._closed:
            raise RuntimeError('会话已经关闭，旧候选不能继续使用')
        return copy.deepcopy(self._frame)

    def _response(self, status, request, message, **extra) -> dict[str, Any]:
        result: dict[str, Any] = {'status': status, 'operation_id': request.get('operation_id'),
            'intent_state': 'READY',
            'evaluation_state': 'FEASIBLE' if status == 'OK' else
                'NEEDS_AUTHORING' if status == 'NEEDS_AUTHORING' else
                'CONFLICT' if status in ('STALE_REVISION', 'UNDO_CONFLICT') else 'FAILED',
            'verification_level': 'NONE', 'persistence_state': 'EPHEMERAL',
            'target_delta_mm': None, 'measured_delta_mm': None, 'error_mm': None,
            'checks': [], 'message': message, 'accepted_frame': copy.deepcopy(self._frame)}
        result.update(extra)
        return result

    def _plan(self, target, delta, allowed):
        assert self._core is not None
        controlled = {tuple(path) for path in target.get('controlled_by') or []}
        candidates = []
        for record in cast(list[dict[str, Any]], self._core.parameters()):
            path = tuple(record['path'])
            if path not in controlled or record.get('mutability') != 'EDITABLE' or record.get('unit') != 'mm':
                continue
            if not set(record.get('objects') or ()) <= allowed:
                continue
            value = get_path(self._core.candidate_config, path)
            for operation in self._accepted:
                if path in operation['writes']:
                    value = operation['writes'][path]
            scale = _finite(record.get('scale', 1.))
            if not scale:
                continue
            if record.get('operation') == 'rebuild' and isinstance(value, (list, tuple)) and len(value) == 2:
                desired = [_finite(value[i]) + delta[i] / scale for i in range(2)]
            elif record.get('operation') == 'translate' and record.get('axis') in ('x', 'y'):
                index = 0 if record['axis'] == 'x' else 1
                if abs(delta[1 - index]) > IMPACT_TOL_MM:
                    continue
                desired = _finite(value) + delta[index] / scale
            else:
                continue
            candidates.append((path, desired, record))
        return candidates

    def _rebuild(self, operations):
        assert self._core is not None
        goals = {}
        for operation in operations:
            goals.update(operation['writes'])
        state = self._core.state()
        with matplotlib.rc_context(rc=self._rc_style):
            with FigureSession(state['script'], state['config'], self.scope,
                               contract=self._contract_override) as trial:
                result: dict[str, Any] = trial.try_layout(
                    [{'operation': 'set_parameter', 'path': list(path), 'value': value}
                     for path, value in goals.items()]) if goals else {'status': 'OK', 'checks': []}
                if result['status'] != 'OK':
                    return result, None, None
                frame, scientific = self._capture(trial)
                baseline_keys = set(FigureSession._qa_keys(self._baseline['qa']['qa']))
                current_keys = FigureSession._qa_keys(frame['qa']['qa'])
                new_problems = [problem for problem, key in zip(frame['qa']['qa'], current_keys)
                                if key not in baseline_keys]
                result = {**result, 'checks': [*result.get('checks', []),
                    {'check': 'rendered_scope_qa', 'status': 'FAIL' if new_problems else 'PASS',
                     'qa_kind': frame['qa']['qa_kind'], 'baseline_problem_count': len(baseline_keys),
                     'current_problem_count': len(current_keys), 'new_problems': new_problems}]}
                if new_problems:
                    result.update(status='QA_BLOCKED', message='实际显示图新增当前输出版本 QA 阻断')
                    return result, None, None
                return result, frame, scientific

    def evaluate(self, request):
        if not isinstance(request, dict):
            request = {}
        refusal = self._guard(request)
        if refusal:
            return self._response(refusal, request, '会话、图帧或源文件已过期；请重新载入')
        if self._core is None:
            return self._response('NEEDS_AUTHORING', request, '无 YAML 图可以测量和示范；此阶段不写 Python')
        if not self._core.science_manifest:
            return self._response('UNVERIFIED_SCIENCE', request, '缺少科学清单，不宣称科学保真')
        if self._pending is not None and self._pending['id'] != request.get('operation_id'):
            return self._response('PENDING_OPERATION', request, '已有候选，请先明确接受或取消')
        self._pending = None  # A changed intent invalidates its earlier evidence.
        try:
            delta = _delta(request)
            tolerance = _finite(request.get('tolerance_mm', 0.01))
            if tolerance <= 0:
                raise ValueError('目标容差必须大于零')
            operation_id = request.get('operation_id')
            if not isinstance(operation_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', operation_id):
                raise ValueError('operation_id 必须是唯一短字符串')
            if any(operation['id'] == operation_id for operation in self._accepted):
                raise ValueError('已接受的操作身份不能重复用于新候选')
            if request.get('operation') != 'translate' or request.get('scope') != self.scope:
                raise ValueError('此阶段只接受当前 scope 的明确平移意图')
            preserve = request.get('preserve')
            if not isinstance(preserve, dict) or preserve.get('science') is not True:
                raise ValueError('科学保护不能关闭')
            if request.get('demonstration') != {'display_only': True}:
                raise ValueError('界面示范必须明确 display_only')
            before = _nodes(self._frame)
            target = next((node for node in before.values() if node.get('gid') == request.get('target_gid')), None)
            if target is None or not target['registered'] or not target['measured']:
                raise ValueError('候选只能定位本帧已测量的稳定 GID')
            if target['type'] not in ('text', 'legend', 'image') or target.get('bounds_mm') is None:
                raise ValueError('科学曲线、独立引线端点或非刚体不能伪装成整体平移')
            following = preserve.get('follow_gids', [])
            fixed = preserve.get('fixed_gids', [])
            if not isinstance(following, list) or not isinstance(fixed, list) or \
                    any(not isinstance(gid, str) for gid in following + fixed):
                raise ValueError('follow_gids/fixed_gids 必须是明确 GID 列表')
            expected_follow = [target['linked_guide_gid']] if target.get('linked_guide_gid') else []
            if sorted(following) != sorted(expected_follow):
                raise ValueError('引线跟随仅按科学清单显式关联；不能扩大影响许可')
            allowed = {target['id'], *following}
            if any(gid not in before or gid in allowed for gid in fixed):
                raise ValueError('固定对象必须存在，且不能同时请求移动或跟随')
            plans = self._plan(target, delta, allowed)
        except (ValueError, KeyError, TypeError) as error:
            self._pending = None
            return self._response('INVALID_INTENT', request, str(error))
        if len(plans) != 1:
            return self._response('AMBIGUOUS' if plans else 'NEEDS_AUTHORING', request,
                '存在多条位移绑定，需明确选择' if plans else
                '没有仅作用于许可对象的位移绑定；不自动移动其他对象或修改源码',
                target_delta_mm=delta)
        path, value, parameter = plans[0]
        if set(parameter.get('scopes', [self.scope])) - {self.scope}:
            return self._response('NEEDS_AUTHORING', request,
                '此绑定跨输出版本；此单 scope 候选尚不能完成全部版本验收，拒绝应用', target_delta_mm=delta)
        draft = {'id': operation_id, 'writes': {path: value}, 'allowed': allowed,
                 'request': copy.deepcopy(request), 'base_revision': self._frame['frame_revision']}
        # Re-evaluating one desired operation invalidates its earlier evidence first.
        self._pending = None
        try:
            checked, frame, scientific = self._rebuild([*self._accepted, draft])
        except (ValueError, RuntimeError) as error:
            return self._response('EVALUATION_FAILED', request, str(error), target_delta_mm=delta)
        if self._guard(request):
            return self._response('STALE_REVISION', request, '重建期间源文件发生变化', target_delta_mm=delta)
        if frame is None:
            return self._response(checked['status'], request, checked.get('message', '候选被已有 QA 拒绝'),
                target_delta_mm=delta, checks=checked.get('checks', []))
        differences = compare_science(self._science, scientific)
        if differences:
            return self._response('SCIENCE_CHANGED', request, '实际重建改变了冻结的科学载荷',
                target_delta_mm=delta, checks=[{'check': 'science', 'status': 'FAIL', 'details': differences}])
        after = _nodes(frame)
        measured_target = after.get(target['id'])
        if measured_target is None or measured_target.get('bounds_mm') is None:
            return self._response('TARGET_MISMATCH', request, '重建后目标无法测量', target_delta_mm=delta)
        box0, box1 = target['bounds_mm'], measured_target['bounds_mm']
        measured = [((box1[i] + box1[i + 2]) - (box0[i] + box0[i + 2])) / 2 for i in range(2)]
        error = max(abs(box1[i] - box0[i] - delta[i % 2]) for i in range(4))
        guide_checks = []
        for gid in following:
            old, new = before.get(gid), after.get(gid)
            if not old or not new or not old.get('runs_mm') or not new.get('runs_mm'):
                error = math.inf
                continue
            first_error = _numeric_error(old['runs_mm'][0][0], new['runs_mm'][0][0])
            end_delta = [new['runs_mm'][-1][-1][i] - old['runs_mm'][-1][-1][i] for i in range(2)]
            endpoint_error = max(first_error, max(abs(end_delta[i] - delta[i]) for i in range(2)))
            error = max(error, endpoint_error)
            guide_checks.append({'gid': gid, 'scientific_endpoint_error_mm': first_error,
                'label_endpoint_delta_mm': end_delta,
                'status': 'PASS' if first_error <= IMPACT_TOL_MM and endpoint_error <= tolerance else 'FAIL'})
        if any(check['scientific_endpoint_error_mm'] > IMPACT_TOL_MM for check in guide_checks):
            return self._response('SCIENCE_CHANGED', request,
                '引线科学端发生移动；用户目标容差不能豁免科学锚点固定要求',
                verification_level='RENDER_CHECKED', target_delta_mm=delta,
                measured_delta_mm=measured, error_mm=error, guide_checks=guide_checks,
                checks=[{'check': 'science', 'status': 'FAIL', 'details': guide_checks}])
        checks = [{'check': 'science', 'status': 'PASS'},
                  {'check': 'qa', 'status': 'PASS', 'details': checked.get('checks', [])},
                  {'check': 'target', 'status': 'PASS' if error <= tolerance else 'FAIL'}]
        result = self._response('OK' if error <= tolerance else 'TARGET_MISMATCH', request,
            '实际重建满足目标；尚未保存或出版' if error <= tolerance else '实际毫米变化未满足用户目标',
            verification_level='RENDER_CHECKED', target_delta_mm=delta, measured_delta_mm=measured,
            error_mm=error if math.isfinite(error) else None, guide_checks=guide_checks, checks=checks,
            parameter_changes=[{'path': list(path), 'value': value}], frame=frame)
        if error > tolerance:
            return result
        canvas = json.loads(frame['scene_json'])['canvas_bounds_mm']
        if any(_overflow(after.get(gid, {}), canvas) > _overflow(before.get(gid, {}), canvas) + IMPACT_TOL_MM
               for gid in allowed):
            result.update(status='GEOMETRY_REJECTED', evaluation_state='FAILED', message='目标造成新的画布越界')
            result['checks'].append({'check': 'contain', 'status': 'FAIL'})
            return result
        unapproved = [gid for gid in set(before) | set(after) if gid not in allowed and
            not (before.get(gid, after.get(gid, {})).get('structural')) and
            _geometry_error(before.get(gid), after.get(gid)) > IMPACT_TOL_MM]
        if unapproved:
            result.update(status='IMPACT_MISMATCH', evaluation_state='FAILED',
                          message='出现未经许可的其他对象变化', unapproved_objects=sorted(unapproved))
            result['checks'].append({'check': 'impact', 'status': 'FAIL'})
            return result
        result['checks'].append({'check': 'impact', 'status': 'PASS'})
        draft.update(frame=frame, expected={gid: copy.deepcopy(after[gid]) for gid in allowed}, result=result)
        self._pending = draft
        return copy.deepcopy(result)

    def decide(self, request):
        if not isinstance(request, dict):
            request = {}
        refused = self._guard(request)
        if refused:
            return self._response(refused, request, '图帧或源文件已经改变，旧候选不能接受')
        operation_id = request.get('operation_id')
        action = request.get('decision')
        if action == 'cancel':
            if self._pending is not None and self._pending['id'] != operation_id:
                return self._response('INVALID_INTENT', request, '不能取消另一条候选')
            self._pending = None
            return self._response('OK', request, '只取消当前候选；已接受操作保持', intent_state='CANCELLED')
        if action == 'accept':
            if self._pending is None or self._pending['id'] != operation_id:
                return self._response('INVALID_INTENT', request, '没有对应的验证通过候选')
            accepted = self._pending
            self._accepted.append(accepted)
            self._frame = self._decorate(accepted['frame'])
            self._pending = None
            return self._response('OK', request, '仅在当前会话接受；源文件和正式图未写入',
                verification_level='RENDER_CHECKED', persistence_state='ACCEPTED_IN_SESSION',
                frame=self.snapshot(), measured_delta_mm=accepted['result']['measured_delta_mm'],
                target_delta_mm=accepted['result']['target_delta_mm'], error_mm=accepted['result']['error_mm'],
                checks=accepted['result']['checks'])
        if action != 'undo':
            return self._response('INVALID_INTENT', request, '只支持 accept/cancel/undo，不保存或发布')
        index = next((i for i, operation in enumerate(self._accepted) if operation['id'] == operation_id), None)
        if index is None:
            return self._response('INVALID_INTENT', request, '该操作不在已接受集合中')
        removed = self._accepted[index]
        if self._pending is not None or any(removed['allowed'] & other['allowed'] or
                set(removed['writes']) & set(other['writes']) for other in self._accepted[index + 1:]):
            return self._response('UNDO_CONFLICT', request, '后续操作依赖这次变更；不能静默撤销')
        remaining = [operation for i, operation in enumerate(self._accepted) if i != index]
        checked, frame, scientific = self._rebuild(remaining)
        if self._guard(request):
            return self._response('STALE_REVISION', request, '撤销重建期间源文件发生变化')
        if frame is None or compare_science(self._science, scientific):
            return self._response('UNDO_CONFLICT', request, '剩余操作重建未通过科学/QA 检查')
        expected = _nodes(self._baseline)
        for operation in remaining:
            expected.update(operation['expected'])
        actual = _nodes(frame)
        if any(not node.get('structural') and _geometry_error(node, actual.get(gid)) > IMPACT_TOL_MM
               for gid, node in expected.items()) or set(actual) != set(expected):
            return self._response('UNDO_CONFLICT', request, '撤销会改变保留的目标或其他对象')
        self._accepted = remaining
        self._frame = self._decorate(frame)
        return self._response('OK', request, '已独立撤销该操作；其余接受目标保持',
            verification_level='RENDER_CHECKED', persistence_state='ACCEPTED_IN_SESSION', frame=self.snapshot())

    def set_quality(self, request):
        refused = self._guard(request)
        if refused:
            return self._response(refused, request, '图帧或源文件已经改变')
        dpi = request.get('dpi')
        if type(dpi) is not int or dpi not in (120, 240, 600):
            return self._response('INVALID_INTENT', request, '显示清晰度只支持 120、240 或 600 DPI')
        if self._core is None:
            return self._response('NEEDS_AUTHORING', request, '静态 Figure 没有可信重建入口，不能单独更换 PNG')
        if self._pending is not None or self._accepted:
            return self._response('QUALITY_LOCKED', request, '请在示范/接受操作之前选择 DPI，避免跨渲染器复用目标证据')
        previous_dpi = self._dpi
        self._dpi = float(dpi)
        try:
            with matplotlib.rc_context(rc=self._rc_style):
                frame, scientific = self._capture(self._core)
            if self._guard(request):
                raise ValueError('重建期间源文件发生变化')
            if compare_science(self._science, scientific):
                raise ValueError('更换 DPI 改变了科学内容')
        except (ValueError, RuntimeError) as error:
            self._dpi = previous_dpi
            return self._response('QUALITY_REJECTED', request, str(error))
        self._frame, self._baseline = frame, copy.deepcopy(frame)
        return self._response('OK', request, '图片和几何已按同一次实际绘制更新', frame=self.snapshot())

    def close(self):
        if self._core is not None:
            self._core.close()
        self._pending = None
        self._closed = True
        self._frame['session']['can_evaluate'] = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
