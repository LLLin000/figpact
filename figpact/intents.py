"""G2/G3 geometry intents: real YAML rebuilds, independent target checks, no file writes.

Default acceptance is in-memory only. A fresh FigureSession evaluates each absolute goal
set, so failed/cancelled B never resets accepted A or accumulates Artist transformations.

Opt-in `IntentSession(..., history=True, state_home=...)` adds G3: every accepted
operation set is checkpointed with source/science/environment evidence, and a restart
prechecks the saved identity before running anything, then replays the recorded
intents through the same oracle. The legacy UI is NOT wired to that mode; the
`history=False` default keeps the in-memory G2 behaviour untouched.
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import io
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any, cast

import matplotlib
import matplotlib.pyplot as plt
from PIL import Image

from .history import HistoryCorrupt, HistoryError, HistoryStore
from .inspector import FRAME_SCHEMA, SCENE_SCHEMA, capture_figure
from .science import capture_science, compare_science
from .session import (FigureSession, engine_fingerprint, get_path, module_revision,
                      source_revision)

IMPACT_TOL_MM = 1e-3  # Same-renderer numeric comparison, not a calibrated physical error bound.
#: History payload schema of this consumer (the store itself stays schema-agnostic).
HISTORY_SCHEMA = 'figpact.intents.history/1'
#: Render environment compared against a frozen checkpoint before any replay.
_HISTORY_ENV_KEYS = ('font.family', 'font.sans-serif', 'axes.unicode_minus', 'text.usetex',
                     'figure.dpi', 'savefig.dpi', 'lines.linewidth', 'svg.hashsalt')


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


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {'sha256': _file_digest(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def _validate_history_frame(frame, scope):
    """Check saved image/geometry integrity; this is not a fresh render verdict."""
    try:
        if not isinstance(frame, dict) or frame.get('schema') != FRAME_SCHEMA:
            raise ValueError('图帧格式不匹配')
        png = base64.b64decode(frame['png_base64'], validate=True)
        image_digest = hashlib.sha256(png).hexdigest()
        scene_digest = hashlib.sha256(frame['scene_json'].encode('utf8')).hexdigest()
        revision = hashlib.sha256(f'{image_digest}\n{scene_digest}'.encode('ascii')).hexdigest()
        if (frame['png_sha256'] != image_digest or frame['scene_sha256'] != scene_digest
                or any(frame[key] != revision for key in
                       ('frame_revision', 'image_revision', 'geometry_revision'))):
            raise ValueError('图片、几何或图帧校验不匹配')
        saved_scene = json.loads(frame['scene_json'])
        if (saved_scene.get('schema') != SCENE_SCHEMA or saved_scene.get('scope') != scope
                or saved_scene.get('unit') != 'mm'
                or saved_scene.get('coordinate_reference') != 'canvas_bottom_left'):
            raise ValueError('几何坐标或作用域不匹配')
        ids = [node['id'] for node in saved_scene['nodes']]
        if any(not isinstance(node_id, str) or not node_id for node_id in ids) or len(set(ids)) != len(ids):
            raise ValueError('图元身份缺失或重复')
        with Image.open(io.BytesIO(png)) as image:
            if image.format != 'PNG' or image.size != (
                    saved_scene['image']['width_px'], saved_scene['image']['height_px']):
                raise ValueError('图片大小与保存几何不匹配')
            image.verify()
    except (KeyError, TypeError, ValueError, OSError, SyntaxError,
            binascii.Error, Image.DecompressionBombError) as error:
        raise HistoryCorrupt(f'保存的图帧损坏，拒绝加载：{error}') from error


def _source_evidence(script, config, scope, *, exclude=(), required=(), source_revision=None,
                     module_revision=None) -> dict[str, Any]:
    """Canonical source identity from **exact content hashes**, not size/mtime metadata.

    Declared artifacts are excluded, but an explicitly declared scientific input always
    wins over that exclusion, so an input edited to the same size and mtime is refused.
    """
    script_path, config_resolved = Path(script), Path(config).resolve()
    outputs = {Path(item).resolve() for item in exclude}
    inputs = [Path(item) for item in required]
    skip = outputs - {Path(item).resolve() for item in inputs}
    files: dict[str, Any] = {}
    records: dict[str, dict[str, Any]] = {}

    def record(path: Path, resolved: str) -> dict[str, Any]:
        """One read per path **inside this call only**: overlapping walks (script dir vs.
        declared inputs vs. engine dir) and duplicate spellings reuse the same result.
        Never memoised across calls — every fresh evidence check still reads real bytes."""
        known = records.get(resolved)
        if known is None:
            records[resolved] = known = _file_record(path)
        return known

    for path in sorted(script_path.parent.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix.lower() == '.pyc':
            continue
        resolved = path.resolve()
        if resolved in skip or resolved == config_resolved:
            continue
        files[str(resolved)] = record(path, str(resolved))
    for path in inputs:
        if path.is_file():
            resolved = str(path.resolve())
            files[resolved] = record(path, resolved)
    if Path(config).is_file() and config_resolved not in skip:
        files[str(config_resolved)] = record(Path(config), str(config_resolved))
    engine_files: dict[str, Any] = {}
    for path in sorted(Path(__file__).parent.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        resolved = str(path.resolve())
        engine_files[resolved] = record(path, resolved)
    return {'schema': HISTORY_SCHEMA, 'script': str(script_path.resolve()),
            'config': str(config_resolved), 'scope': scope, 'source_revision': source_revision,
            'module_revision': module_revision, 'engine': engine_fingerprint(),
            'engine_files': engine_files,
            'science_inputs': sorted(str(p.resolve()) for p in inputs),
            'artifact_outputs': sorted(str(p) for p in outputs), 'files': files}


class IntentSession:
    """Single-owner, single-pending-candidate Inspector session; never publishes/saves."""

    def __init__(self, *, script=None, config=None, scope='measurement', figure=None,
                 registry=None, contract=None, science_manifest=None, dpi=None,
                 history=False, state_home=None):
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
        self._history = bool(history)
        self._state_home = state_home
        self._store: HistoryStore | None = None
        self._records: list[dict[str, Any]] = []
        self._history_head: str | None = None
        self._source_files: dict[str, Any] | None = None
        self._history_status = 'ACTIVE' if self._history else 'OFF'
        self._history_reason: str | None = None
        self._history_detail: str | None = None
        self._historical_ids: list[str] = []
        self._replaying = False
        if figure is not None:
            if script is not None or config is not None:
                raise ValueError('普通 Figure 测量和 YAML 会话不能混用')
            if self._history:
                raise ValueError('历史记录需要明确 script/config；普通 Figure 测量'
                                 '不获得持久编辑身份')
            self._frame = capture_figure(figure, registry, scope=scope,
                                         contract=contract, science_manifest=science_manifest)
        else:
            if script is None or config is None:
                raise ValueError('编辑候选需要明确 script/config；只读测量可以直接传 Figure')
            stale = self._open_history(script, config, scope, dpi) if self._history else None
            if stale is not None:
                self._enter_historical(stale['reason'], stale.get('detail') or '')
            else:
                with matplotlib.rc_context():
                    self._core = FigureSession(script, config, scope, contract=contract)
                    self._rc_style = matplotlib.rcParams.copy()
                    try:
                        self._source = self._core.state()['source_revision']
                        if self._history:
                            self._source_files = self._live_source()
                        self._frame, self._science = self._capture(self._core)
                        self._baseline = copy.deepcopy(self._frame)
                    except Exception:
                        self._core.close()
                        self._close_store()
                        raise
                if self._history:
                    self._verify_restore()
        self._frame = self._decorate(self._frame)

    # -- persistent history (opt-in; the legacy UI stays on the G2 path) --------- #

    def _open_history(self, script, config, scope, dpi):
        """Open the store and precheck saved identity BEFORE running the changed script.

        Any store problem fails closed (the caller sees a HistoryError, never an editor);
        a changed/missing script, config, input or engine yields history-only mode.
        """
        try:
            self._store = HistoryStore(script, config, scope, state_home=self._state_home)
            self._records = self._store.checkpoints()
        except BaseException:
            self._close_store()
            raise
        if not self._records:
            return None
        head, payload = self._records[-1], self._records[-1]['payload']
        self._history_head = head['id']
        try:
            _validate_history_frame(payload.get('frame'), scope)
            _validate_history_frame(payload.get('baseline_frame'), scope)
        except HistoryCorrupt:
            self._close_store()
            raise
        if not isinstance(payload, dict) or payload.get('schema') != HISTORY_SCHEMA:
            return {'reason': 'EVIDENCE_INCOMPLETE', 'detail': 'payload schema'}
        saved = payload.get('source')
        environment = payload.get('environment')
        if not isinstance(saved, dict) or not isinstance(saved.get('files'), dict) \
                or not saved['files'] or not isinstance(environment, dict):
            return {'reason': 'EVIDENCE_INCOMPLETE', 'detail': 'source evidence'}
        for key in ('frame', 'baseline_frame', 'science', 'accepted'):
            if key not in payload:
                return {'reason': 'EVIDENCE_INCOMPLETE', 'detail': f'missing {key}'}
        if dpi is not None and float(dpi) != environment.get('dpi'):
            return {'reason': 'DISPLAY_MISMATCH',
                    'detail': f'recorded {environment.get("dpi")} DPI != requested {dpi}'}
        self._dpi = environment.get('dpi')
        outputs, inputs = saved.get('artifact_outputs') or [], saved.get('science_inputs') or []
        try:
            live = _source_evidence(script, config, scope, exclude=outputs, required=inputs,
                                    source_revision=source_revision(script, config,
                                                                    exclude=outputs,
                                                                    required=inputs),
                                    module_revision=module_revision(script, config,
                                                                    exclude=outputs,
                                                                    required=inputs))
        except (OSError, ValueError) as error:
            return {'reason': 'SOURCE_CHANGED', 'detail': f'{type(error).__name__}: {error}'}
        if live != saved:
            return {'reason': 'SOURCE_CHANGED', 'detail': 'identity or content hash'}
        return None

    def _enter_historical(self, reason, detail=''):
        """Read-only view of the stored frame: no editor, no fresh renderer claim."""
        if self._core is not None:
            self._core.close()
            self._core = None
        self._accepted = []
        self._pending = None
        self._history_status = 'HISTORICAL_ONLY'
        self._history_reason, self._history_detail = reason, detail
        payload = self._records[-1]['payload'] if self._records else {}
        self._historical_ids = [record.get('id') for record in payload.get('accepted') or []
                                if isinstance(record, dict)]
        self._frame = copy.deepcopy(payload.get('frame') or payload.get('baseline_frame') or {})
        self._frame['historical'] = True
        self._frame['current_verification'] = 'NONE'

    def _live_source(self):
        assert self._core is not None
        state = cast(dict[str, Any], self._core.state())
        return _source_evidence(state['script'], state['config'], state['scope'],
            exclude=[Path(item) for item in state['artifact_outputs']],
            required=[Path(item) for item in state['science_inputs']],
            source_revision=state['source_revision'], module_revision=state['module_revision'])

    def _source_fresh(self):
        if self._source_files is None:
            return True
        try:
            return self._live_source() == self._source_files
        except (OSError, ValueError):
            return False

    def _environment(self):
        style = self._rc_style if self._rc_style is not None else matplotlib.rcParams
        state = self._core.state() if self._core is not None else {}
        return {'matplotlib': matplotlib.__version__, 'dpi': self._dpi, 'scope': self.scope,
                'rc_style': {key: style.get(key) for key in _HISTORY_ENV_KEYS},
                'loaders': dict(state.get('loaders') or {})}

    def _history_state(self):
        return {'status': self._history_status, 'head': self._history_head,
                'reason': self._history_reason, 'detail': self._history_detail,
                'checkpoint_count': len(self._records),
                'directory': str(self._store.directory) if self._store is not None else None}

    def history(self):
        """Chronological store records of this workspace (detached JSON, read-only)."""
        if not self._history:
            raise RuntimeError('未启用历史模式；只有 history=True 的会话有可查看的操作记录')
        if self._store is not None:
            self._records = self._store.checkpoints()
        return copy.deepcopy(self._records)

    def _close_store(self):
        if self._store is not None:
            self._store.close()
            self._store = None

    def _verify_environment(self, saved):
        if not isinstance(saved, dict):
            return 'EVIDENCE_INCOMPLETE'
        live = self._environment()
        if any(saved.get(key) != live.get(key)
               for key in ('matplotlib', 'dpi', 'rc_style', 'scope')):
            return 'ENVIRONMENT_MISMATCH'
        return None

    def _verify_restore(self):
        """Replay the recorded accepted set through the live oracle, then checkpoint it.

        Every unchecked evidence detail rejects the whole restore: no partial A/B, no
        replay of saved writes and no reuse of an old PNG as proof.
        """
        if not self._records:
            return
        payload = self._records[-1]['payload']
        operations = payload.get('accepted')
        if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
            self._enter_historical('EVIDENCE_INCOMPLETE', 'accepted operation records')
            return
        reason = self._verify_environment(payload.get('environment'))
        if reason:
            self._enter_historical(reason, 'render environment')
            return
        saved_baseline, current_baseline = _nodes(payload['baseline_frame']), _nodes(self._baseline)
        if set(saved_baseline) != set(current_baseline):
            self._enter_historical('SCENE_SET_MISMATCH', 'baseline object set')
            return
        if any(_geometry_error(node, current_baseline[gid]) > IMPACT_TOL_MM
               for gid, node in saved_baseline.items()):
            self._enter_historical('BASELINE_GEOMETRY_MISMATCH', 'fresh baseline geometry')
            return
        if (json.loads(payload['baseline_frame']['scene_json']).get('measurement')
                != json.loads(self._baseline['scene_json']).get('measurement')):
            self._enter_historical('ENVIRONMENT_MISMATCH', 'renderer measurement conditions')
            return
        if compare_science(payload.get('science'), self._science):
            self._enter_historical('SCIENCE_MISMATCH', 'frozen scientific payload')
            return
        if not self._source_fresh():
            self._enter_historical('SOURCE_CHANGED', 'declared inputs changed while building')
            return
        verified = []
        self._replaying = True  # only the final verified replay writes a checkpoint
        try:
            for record in operations:
                problem, evidence = self._replay_operation(record)
                if problem:
                    self._enter_historical(problem, str(record.get('id')))
                    return
                verified.append(evidence)
        finally:
            self._replaying = False
        problem = self._verify_final(payload, operations)
        if problem:
            self._enter_historical(problem, 'restored frame')
            return
        checkpoint, failure = self._persist('restart', verified=verified)
        if checkpoint is None:
            self._enter_historical('PERSISTENCE_FAILED', failure)

    def _verify_final(self, payload, operations):
        stored = payload.get('frame') or {}
        if not stored.get('scene_json'):
            return 'EVIDENCE_INCOMPLETE'
        expected, actual = _nodes(stored), _nodes(self._frame)
        if sorted(actual) != sorted(expected):
            return 'SCENE_SET_MISMATCH'
        if any(_geometry_error(expected[gid], actual[gid]) > IMPACT_TOL_MM for gid in expected):
            return 'FINAL_GEOMETRY_MISMATCH'
        return 'SCIENCE_MISMATCH' if compare_science(payload.get('science'), self._science) else None

    def _replay_operation(self, record):
        """One recorded intent through the live oracle with newly measured evidence."""
        geometry = record.get('geometry') if isinstance(record.get('geometry'), dict) else {}
        request = record.get('request')
        measurement = record.get('measurement')
        if not isinstance(request, dict) or not isinstance(measurement, dict) \
                or not isinstance(geometry.get('before'), dict) \
                or not isinstance(geometry.get('after'), dict):
            return 'EVIDENCE_INCOMPLETE', None
        frame = self._frame
        before = _nodes(frame)
        if sorted(before) != list(geometry.get('before_gids') or ()):
            return 'SCENE_SET_MISMATCH', None
        if any(_geometry_error(expected, before.get(node_id)) > IMPACT_TOL_MM
               for node_id, expected in geometry['before'].items()):
            return 'BASELINE_GEOMETRY_MISMATCH', None
        try:
            tolerance = max(_finite(measurement.get('tolerance_mm') or 0.01), IMPACT_TOL_MM)
        except (ValueError, TypeError):
            return 'EVIDENCE_INCOMPLETE', None
        live = {**request, 'session_id': self.session_id,
                'scene_revision': frame['frame_revision'], 'source_revision': self._source}
        response = self.evaluate(live)
        if response['status'] != 'OK':
            return 'REPLAY_' + response['status'], None
        after = _nodes(response['frame'])
        if sorted(after) != list(geometry.get('after_gids') or ()):
            return 'SCENE_SET_MISMATCH', None
        if any(_geometry_error(expected, after.get(node_id)) > IMPACT_TOL_MM
               for node_id, expected in geometry['after'].items()):
            return 'TARGET_GEOMETRY_MISMATCH', None
        if _numeric_error(measurement.get('measured_delta_mm'),
                          response.get('measured_delta_mm')) > IMPACT_TOL_MM:
            return 'MEASUREMENT_MISMATCH', None
        if _numeric_error(measurement.get('error_mm'), response.get('error_mm')) > tolerance:
            return 'MEASUREMENT_MISMATCH', None
        recorded_guide = {item.get('gid'): item for item in record.get('guide_checks') or []
                          if isinstance(item, dict)}
        live_guide = {item.get('gid'): item for item in response.get('guide_checks') or []}
        if set(recorded_guide) != set(live_guide):
            return 'GUIDE_MISMATCH', None
        for gid, item in recorded_guide.items():
            other = live_guide[gid]
            if item.get('status') != other.get('status') or _numeric_error(
                    item.get('scientific_endpoint_error_mm'),
                    other.get('scientific_endpoint_error_mm')) > IMPACT_TOL_MM or _numeric_error(
                    item.get('label_endpoint_delta_mm'),
                    other.get('label_endpoint_delta_mm')) > tolerance:
                return 'GUIDE_MISMATCH', None
        impact = record.get('impact') if isinstance(record.get('impact'), dict) else {}
        if impact.get('unapproved') or sorted(response.get('unapproved_objects') or []) != \
                list(impact.get('unapproved') or ()):
            return 'IMPACT_MISMATCH', None
        qa = response['frame'].get('qa') or {}
        recorded_qa = record.get('qa') if isinstance(record.get('qa'), dict) else {}
        if qa.get('qa_kind') != recorded_qa.get('qa_kind') or \
                FigureSession._qa_keys(qa.get('qa') or []) != \
                FigureSession._qa_keys(recorded_qa.get('qa') or []):
            return 'QA_MISMATCH', None
        decision = self.decide({**live, 'decision': 'accept'})
        if decision['status'] != 'OK':
            return 'REPLAY_ACCEPT_' + decision['status'], None
        return None, {'id': record.get('id'), 'status': 'VERIFIED',
                      'measured_delta_mm': response.get('measured_delta_mm'),
                      'error_mm': response.get('error_mm'),
                      'guide_checks': response.get('guide_checks'),
                      'impact': sorted(response.get('unapproved_objects') or []),
                      'science_digest': (self._science or {}).get('digest'),
                      'frame_revision': response['frame']['frame_revision']}

    def _history_operations(self, operations):
        records = []
        for index, operation in enumerate(operations):
            others = operations[:index] + operations[index + 1:]
            allowed = set(operation['allowed'])
            base_frame = self._baseline if index == 0 else operations[index - 1]['frame']
            before, after = _nodes(base_frame), _nodes(operation['frame'])
            result = operation['result']
            records.append({
                'id': operation['id'], 'target_gid': operation['request'].get('target_gid'),
                'request': copy.deepcopy(operation['request']),
                'scene': {'baseline_revision': self._baseline['frame_revision'],
                          'base_revision': operation['base_revision'],
                          'result_revision': operation['frame']['frame_revision']},
                'parameter': copy.deepcopy(operation['parameter']),
                'writes': [{'path': list(path), 'value': value}
                           for path, value in operation['writes'].items()],
                'impact': {'allowed': sorted(allowed),
                           'unapproved': sorted(result.get('unapproved_objects') or []),
                           'dependent_operations': sorted(
                               other['id'] for other in others
                               if set(other['allowed']) & allowed or
                               set(other['writes']) & set(operation['writes']))},
                'geometry': {'before': {node_id: before[node_id]
                                        for node_id in sorted(allowed) if node_id in before},
                             'after': {gid: after[gid] for gid in sorted(allowed) if gid in after},
                             'before_gids': sorted(before), 'after_gids': sorted(after)},
                'measurement': {'target_delta_mm': result.get('target_delta_mm'),
                                'measured_delta_mm': result.get('measured_delta_mm'),
                                'error_mm': result.get('error_mm'),
                                'tolerance_mm': operation['request'].get('tolerance_mm')},
                'guide_checks': copy.deepcopy(result.get('guide_checks') or []),
                'checks': copy.deepcopy(result.get('checks') or []),
                'science_digest': (self._science or {}).get('digest'),
                'qa': copy.deepcopy(operation['frame'].get('qa') or {}),
                'verification_level': result.get('verification_level'),
                'file_changes': [], 'source_change_ids': []})
        return records

    def _history_payload(self, *, kind, operations, frame, verified=None):
        assert self._core is not None
        source = self._source_files if self._source_files is not None else self._live_source()
        try:
            return json.loads(json.dumps({
                'schema': HISTORY_SCHEMA, 'kind': kind, 'client': 'figpact.intents',
                'session_id': self.session_id, 'scope': self.scope, 'dpi': self._dpi,
                'source': source, 'environment': self._environment(), 'science': self._science,
                'baseline_frame': self._baseline, 'frame': frame,
                'accepted': self._history_operations(operations), 'verified': verified or [],
                'file_changes': [], 'source_change_ids': []},
                allow_nan=False, ensure_ascii=False))
        except (TypeError, ValueError) as error:
            raise HistoryError(f'历史载荷不是有限 JSON：{error}') from error

    def _persist(self, kind, *, operations=None, frame=None, verified=None):
        """Durable checkpoint BEFORE any in-memory state change; failure changes nothing."""
        if self._closed:
            return None, '会话已关闭，不能再写入历史'
        if not self._source_fresh():
            return None, '源文件在写入历史前发生变化'
        try:
            payload = self._history_payload(
                kind=kind, operations=self._accepted if operations is None else operations,
                frame=self._frame if frame is None else frame, verified=verified)
        except HistoryError as error:
            return None, str(error)
        assert self._store is not None
        expected = self._history_head
        try:
            checkpoint = self._store.append(
                payload, expected_head=expected, kind=kind)
        except HistoryError as error:
            return None, f'{type(error).__name__}: {error}'
        self._records.append(checkpoint)
        self._history_head = checkpoint['id']
        return checkpoint, None

    def _decorate(self, frame):
        frame['session'] = {'session_id': self.session_id,
            'scene_revision': frame.get('frame_revision'), 'source_revision': self._source,
            'can_evaluate': bool(self._core and self._core.science_manifest and not self._closed),
            'accepted_operation_ids': self._historical_ids
                if self._history_status == 'HISTORICAL_ONLY'
                else [operation['id'] for operation in self._accepted]}
        if self._history:
            frame['session']['history'] = self._history_state()
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
                if self._current_source() != self._source or not self._source_fresh():
                    return 'STALE_REVISION'
            except OSError:
                return 'STALE_REVISION'
        return None

    def snapshot(self):
        """Paired accepted frame, never the last pending trial."""
        if self._closed:
            raise RuntimeError('会话已经关闭，旧候选不能继续使用')
        return copy.deepcopy(self._frame)

    def _historical(self, request):
        """History-only sessions are read-only: no editing, no fresh renderer claim."""
        if self._history_status != 'HISTORICAL_ONLY':
            return None
        return self._response('HISTORY_ONLY', request,
            f'历史与当前工作区不一致（{self._history_reason}）；只能查看历史，不能继续编辑',
            history_reason=self._history_reason, history_detail=self._history_detail)

    def _response(self, status, request, message, **extra) -> dict[str, Any]:
        result: dict[str, Any] = {'status': status, 'operation_id': request.get('operation_id'),
            'intent_state': 'READY',
            'evaluation_state': 'FEASIBLE' if status == 'OK' else
                'NEEDS_AUTHORING' if status == 'NEEDS_AUTHORING' else
                'CONFLICT' if status in ('STALE_REVISION', 'UNDO_CONFLICT',
                                         'HISTORY_ONLY') else 'FAILED',
            'verification_level': 'NONE', 'persistence_state': 'EPHEMERAL',
            'target_delta_mm': None, 'measured_delta_mm': None, 'error_mm': None,
            'checks': [], 'message': message, 'accepted_frame': copy.deepcopy(self._frame)}
        result.update(extra)
        if self._history and 'history' not in result:
            result['history'] = self._history_state()
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
            candidates.append((path, desired, record, value))
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
        historical = self._historical(request)
        if historical is not None:
            return historical
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
        path, value, parameter, current = plans[0]
        if set(parameter.get('scopes', [self.scope])) - {self.scope}:
            return self._response('NEEDS_AUTHORING', request,
                '此绑定跨输出版本；此单 scope 候选尚不能完成全部版本验收，拒绝应用', target_delta_mm=delta)
        draft = {'id': operation_id, 'writes': {path: value}, 'allowed': allowed,
                 'request': copy.deepcopy(request), 'base_revision': self._frame['frame_revision'],
                 'parameter': {'key': parameter.get('key'), 'path': list(path),
                     'operation': parameter.get('operation'), 'axis': parameter.get('axis'),
                     'scale': parameter.get('scale'), 'before': current, 'after': value}}
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
        historical = self._historical(request)
        if historical is not None:
            return historical
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
            if self._history and not self._replaying:
                checkpoint, failure = self._persist('operation',
                    operations=[*self._accepted, accepted], frame=accepted['frame'])
                if checkpoint is None:
                    return self._response('PERSISTENCE_FAILED', request,
                        f'历史检查点写入失败，已接受集合保持不变：{failure}',
                        persistence_state='REJECTED',
                        measured_delta_mm=accepted['result']['measured_delta_mm'],
                        target_delta_mm=accepted['result']['target_delta_mm'],
                        error_mm=accepted['result']['error_mm'], checks=accepted['result']['checks'])
            self._accepted.append(accepted)
            self._frame = self._decorate(accepted['frame'])
            self._pending = None
            return self._response('OK', request, '仅在当前会话接受；源文件和正式图未写入'
                if not self._history or self._replaying else
                '已写入本地历史检查点；源文件和正式图仍未写入',
                verification_level='RENDER_CHECKED',
                persistence_state='CHECKPOINTED' if self._history and not self._replaying else 'ACCEPTED_IN_SESSION',
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
        if self._history and not self._replaying:
            checkpoint, failure = self._persist('undo', operations=remaining, frame=frame)
            if checkpoint is None:
                return self._response('PERSISTENCE_FAILED', request,
                    f'撤销的历史检查点写入失败，已接受集合保持不变：{failure}',
                    persistence_state='REJECTED')
        self._accepted = remaining
        self._frame = self._decorate(frame)
        return self._response('OK', request, '已独立撤销该操作；其余接受目标保持',
            verification_level='RENDER_CHECKED',
            persistence_state='CHECKPOINTED' if self._history and not self._replaying else 'ACCEPTED_IN_SESSION',
            frame=self.snapshot())

    def set_quality(self, request):
        historical = self._historical(request)
        if historical is not None:
            return historical
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
        self._close_store()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
