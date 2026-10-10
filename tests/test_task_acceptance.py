"""验收运行的判定边界：伪造验证、静默状态改动、科学/QA 泄漏都必须被判失败。

这些测试不跑引擎、不建图：只喂 `eval/run_vnext_tasks.py` 里的纯判定函数
（`evaluate_task` / `judge_measurement` / `judge_verification` / 载荷比较 / 分位），
所以它们校验的是「验收器会不会放过错的东西」，而不是记录的形状或文案。
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SPEC = importlib.util.spec_from_file_location(
    'figpact_vnext_acceptance_runner', ROOT / 'eval' / 'run_vnext_tasks.py')
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


def record(**expected) -> dict:
    expected.setdefault('status', 'OK')
    return {'id': 'T1', 'fixture': 'tests/fixtures/native_ftir.py',
            'config': 'tests/fixtures/native_ftir.yaml', 'scope': 'main',
            'operations': [], 'expected': expected}


def observed(**overrides) -> dict:
    base = {
        'task_id': 'T1', 'status': 'OK', 'verification': 'GEOMETRY_CHECKED',
        'errors': [], 'measurements': [], 'invariants': {}, 'qa': {'baseline': [], 'candidate': [], 'new': []},
        'refusal': None, 'manifest': {'jsonable': True, 'missing_inputs': []},
        'config_error': None, 'config_error_request': None,
    }
    base.update(overrides)
    return base


def config_error_observed(*, raised, stage=None, baseline_ok=True, config='/tmp/probe-inputs/candidate.yaml',
                          baseline_error=None, artifacts=None, baseline_unchanged=True,
                          baseline_sha256='a' * 64, candidate_sha256='b' * 64) -> dict:
    """一条 CONFIG_ERROR 观测：候选 YAML 真的被喂进去、基线字节没动。"""
    return observed(
        status='CONFIG_ERROR' if raised else 'OK',
        config_error={'raised': raised, 'stage': stage, 'error': None, 'config': config,
                      'baseline_ok': baseline_ok, 'baseline_error': baseline_error,
                      'artifacts': list(artifacts or [])},
        config_error_request={'operations': [{'operation': 'set_parameter', 'path': ['x'], 'value': 1.0}],
                              'baseline_config': '/tmp/tasks/T1/baseline.yaml',
                              'baseline_sha256_before': baseline_sha256,
                              'baseline_sha256_after': baseline_sha256,
                              'candidate_config': config, 'materialise_error': None,
                              'candidate_sha256': candidate_sha256,
                              'baseline_unchanged': baseline_unchanged})


def agent_record(fixture, config, *, name='T1', status='OK', operations=None, scope='main') -> dict:
    """一条语料记录：真实存在的夹具/配置路径，期望状态由调用方指定。"""
    return {'id': name, 'fixture': str(fixture), 'config': str(config), 'scope': scope,
            'operations': list(operations or []), 'expected': {'status': status}}


def trial(**overrides) -> dict:
    """一条形状完整的外部 Agent 尝试（默认可归属 + 计时/原文齐全）。"""
    base = {'task_id': 'T1', 'arm': 'A', 'agent': 'agent-x', 'attempt': 1,
            'started_at': '2026-10-10T12:00:00+08:00', 'finished_at': '2026-10-10T12:00:20+08:00',
            'wall_seconds': 20.0, 'raw_request': 'REQUEST', 'raw_response': 'RESPONSE'}
    base.update(overrides)
    return base


def agent_runner(tmp, trials) -> 'runner.AcceptanceRunner':
    """没有引擎也能跑的 agent_evidence 宿主：只给记录路径与临时目录。"""
    path = Path(tmp) / 'trials.json'
    path.write_text(json.dumps({'schema': runner.AGENT_SCHEMA, 'trials': trials}), encoding='utf8')
    instance = runner.AcceptanceRunner.__new__(runner.AcceptanceRunner)
    instance.agent_trials_path = path
    instance.temp_root = Path(tmp) / 'temp'
    instance.temp_root.mkdir(parents=True, exist_ok=True)
    instance.python = sys.executable
    instance.probe_timeout = 120.0
    instance.workers = {}
    instance.mismatches = []
    instance.unsupported = []
    instance.artifacts = {}
    return instance


#: 独立重建成功的探针应答（形状与真实 --probe 应答一致；断言只看门/计数，不看文案）。
REBUILD_OK = {'ok': True, 'measurements': [], 'invariants': {}, 'counts': {'builds': 1, 'pngs': 1},
              'baseline': {'qa': [], 'source_fingerprint': {'available': True, 'value': 'fp'}},
              'candidate': {'qa': [], 'staging_png': {'name': 'candidate.png', 'bytes': 12},
                            'source_fingerprint': {'available': True, 'value': 'fp'},
                            'science_manifest': None}}


def measurement(kind, objects, axis, expected_value, *, tolerance=None, quantity=None,
                raw=None, expected=None) -> tuple:
    expected_record = {'kind': kind, 'objects': objects, 'axis': axis, 'value_mm': expected_value,
                       'quantity': quantity}
    if tolerance is not None:
        expected_record['tolerance_mm'] = tolerance
    if expected is not None:
        expected_record.update(expected)
    return expected_record, raw


class MeasurementJudgeTests(unittest.TestCase):
    def test_translate_delta_uses_signed_lower_edge(self):
        expected = {'kind': 'translate', 'objects': ['g'], 'axis': 'y', 'value_mm': 2.0,
                    'tolerance_mm': 1e-6}
        raw = {'baseline': {'g': [0.0, 10.0, 5.0, 12.0]}, 'candidate': {'g': [0.0, 12.0, 5.0, 14.0]}}
        outcome = runner.judge_measurement(expected, raw)
        self.assertTrue(outcome['ok'], outcome)
        self.assertAlmostEqual(outcome['value_mm'], 2.0, places=9)

    def test_translate_beyond_tolerance_fails(self):
        expected = {'kind': 'translate', 'objects': ['g'], 'axis': 'y', 'value_mm': 2.0,
                    'tolerance_mm': 1e-6}
        raw = {'baseline': {'g': [0.0, 10.0, 5.0, 12.0]}, 'candidate': {'g': [0.0, 11.0, 5.0, 13.0]}}
        outcome = runner.judge_measurement(expected, raw)
        self.assertFalse(outcome['ok'])

    def test_bounds_size_is_extent_not_edge(self):
        raw = {'g': [1.0, 2.0, 6.0, 9.0]}
        size = runner.judge_measurement(
            {'kind': 'bounds', 'objects': ['g'], 'axis': 'x', 'value_mm': 5.0,
             'quantity': 'size', 'tolerance_mm': 1e-9}, raw)
        edge = runner.judge_measurement(
            {'kind': 'bounds', 'objects': ['g'], 'axis': 'x', 'value_mm': 6.0,
             'quantity': 'max', 'tolerance_mm': 1e-9}, raw)
        wrong = runner.judge_measurement(
            {'kind': 'bounds', 'objects': ['g'], 'axis': 'x', 'value_mm': 6.0,
             'quantity': 'size', 'tolerance_mm': 1e-9}, raw)
        self.assertTrue(size['ok'] and edge['ok'])
        self.assertFalse(wrong['ok'], '把尺寸当成上边缘必须判失败')

    def test_bounds_unknown_quantity_fails_closed(self):
        outcome = runner.judge_measurement(
            {'kind': 'bounds', 'objects': ['g'], 'axis': 'x', 'value_mm': 5.0,
             'quantity': 'diameter', 'tolerance_mm': 1.0}, {'g': [1.0, 2.0, 6.0, 9.0]})
        self.assertFalse(outcome['ok'])

    def test_relation_measure_requires_ok_status(self):
        expected = {'kind': 'relation', 'objects': ['a', 'b'], 'value_mm': 8.0,
                    'tolerance_mm': 0.05, 'relation_id': 'r'}
        failed = runner.judge_measurement(expected, {'status': 'UNSUPPORTED', 'value_mm': 8.0})
        ok = runner.judge_measurement(expected, {'status': 'OK', 'value_mm': 8.02})
        self.assertFalse(failed['ok'])
        self.assertTrue(ok['ok'], ok)

    def test_missing_observation_is_failure_not_zero(self):
        outcome = runner.judge_measurement(
            {'kind': 'translate', 'objects': ['g'], 'axis': 'y', 'value_mm': 1.0, 'tolerance_mm': 1e-6},
            {'unavailable': '需要基线 + 候选两次独立重建'})
        self.assertFalse(outcome['ok'])
        self.assertIsNone(outcome['value_mm'])

    def test_contain_target_is_an_upper_bound_not_a_flush_edge(self):
        expected = {'kind': 'relation', 'relation_id': 'panels.contain_x',
                    'objects': ['canvas', 'a', 'b', 'c', 'd'], 'axis': 'x', 'value_mm': 0.0,
                    'tolerance_mm': 1e-6}
        slack = runner.judge_measurement(
            expected, {'status': 'OK', 'value_mm': -10.0, 'relation': 'contain'})
        overflow = runner.judge_measurement(
            expected, {'status': 'OK', 'value_mm': 2.5, 'relation': 'contain'})
        self.assertTrue(slack['ok'], slack)
        self.assertEqual(slack['semantics'], 'upper_bound')
        self.assertEqual(slack['value_mm'], -10.0, '净空如实报 -10 mm，不许伪造成 0')
        self.assertEqual(slack['overflow_mm'], -10.0)
        self.assertFalse(overflow['ok'])
        self.assertEqual(overflow['value_mm'], 2.5)

    def test_exact_zero_still_required_for_non_contain_relations(self):
        """equal_size / gap / align 的 0 是精确值：极差 0.5 mm 必须判失败。"""
        expected = {'kind': 'relation', 'relation_id': 'panels.equal_width', 'objects': ['a', 'b'],
                    'axis': 'x', 'value_mm': 0.0, 'tolerance_mm': 1e-6}
        spread = runner.judge_measurement(
            expected, {'status': 'OK', 'value_mm': 0.5, 'relation': 'equal_size'})
        zero = runner.judge_measurement(
            expected, {'status': 'OK', 'value_mm': 0.0, 'relation': 'equal_size'})
        self.assertFalse(spread['ok'])
        self.assertTrue(zero['ok'])
        self.assertNotEqual(spread.get('semantics'), 'upper_bound')


class VerificationJudgeTests(unittest.TestCase):
    def test_render_upgrade_over_expected_geometry_is_allowed(self):
        outcome = runner.judge_verification('GEOMETRY_CHECKED', 'RENDER_CHECKED')
        self.assertTrue(outcome['ok'])
        self.assertTrue(outcome['upgraded'])

    def test_invented_geometry_fast_path_is_rejected(self):
        outcome = runner.judge_verification('RENDER_CHECKED', 'GEOMETRY_CHECKED')
        self.assertFalse(outcome['ok'])

    def test_unspecified_expected_verification_records_actual(self):
        outcome = runner.judge_verification(None, None)
        self.assertTrue(outcome['ok'])


class TaskVerdictTests(unittest.TestCase):
    def test_clean_task_passes(self):
        expected_record = record(verification='GEOMETRY_CHECKED')
        verdict = runner.evaluate_task(expected_record, observed())
        self.assertTrue(verdict['passed'], verdict['failures'])

    def test_expected_ok_but_refused_fails(self):
        verdict = runner.evaluate_task(record(), observed(status='LOCKED', message='locked'))
        self.assertFalse(verdict['passed'])

    def test_measurement_mismatch_fails_the_task(self):
        expected_record = record(measurements=[{'kind': 'translate', 'objects': ['g'], 'axis': 'y',
                                                'value_mm': 2.0, 'tolerance_mm': 1e-6}])
        raw = {'baseline': {'g': [0, 10, 5, 12]}, 'candidate': {'g': [0, 10, 5, 12]}}
        outcome = runner.judge_measurement(expected_record['expected']['measurements'][0], raw)
        verdict = runner.evaluate_task(expected_record, observed(measurements=[
            {'kind': 'translate', 'objects': ['g'], 'outcome': outcome}]))
        self.assertFalse(verdict['passed'])

    def test_missing_measurement_fails_the_task(self):
        expected_record = record(measurements=[{'kind': 'bounds', 'objects': ['g'], 'axis': 'x',
                                                'value_mm': 1.0, 'quantity': 'size'}])
        verdict = runner.evaluate_task(expected_record, observed(measurements=[]))
        self.assertFalse(verdict['passed'])

    def test_science_invariant_violation_fails(self):
        expected_record = record(science_invariants=['ftir.curve_arrays'])
        verdict = runner.evaluate_task(expected_record, observed(invariants={
            'ftir.curve_arrays': {'ok': False, 'reason': '载荷变化：[lines]'}}))
        self.assertFalse(verdict['passed'])

    def test_unobserved_invariant_fails_an_ok_task(self):
        expected_record = record(science_invariants=['ftir.curve_arrays'])
        verdict = runner.evaluate_task(expected_record, observed(invariants={
            'ftir.curve_arrays': {'ok': None, 'reason': '没有候选重建'}}))
        self.assertFalse(verdict['passed'])

    def test_new_qa_blocker_fails(self):
        verdict = runner.evaluate_task(record(), observed(
            qa={'baseline': [], 'candidate': ['TEXT_OVERLAP: x'], 'new': ['TEXT_OVERLAP: x']}))
        self.assertFalse(verdict['passed'])

    def test_refusal_with_state_mutation_fails(self):
        expected_record = record(status='REFUSED')
        verdict = runner.evaluate_task(expected_record, observed(
            status='LOCKED', refusal={'state_mutated': True, 'mutation_detail': 'goals=1',
                                      'has_candidate': False, 'goals': 1}))
        self.assertFalse(verdict['passed'])

    def test_clean_refusal_passes(self):
        expected_record = record(status='REFUSED', verification=None)
        verdict = runner.evaluate_task(expected_record, observed(status='LOCKED', verification=None,
                                                                refusal={'state_mutated': False,
                                                                         'has_candidate': False,
                                                                         'goals': 0}))
        self.assertTrue(verdict['passed'], verdict['failures'])

    def test_config_error_requires_load_config_failure(self):
        expected_record = record(status='CONFIG_ERROR')
        missed = runner.evaluate_task(expected_record, config_error_observed(raised=False))
        raised = runner.evaluate_task(expected_record, config_error_observed(raised=True,
                                                                            stage='load_config'))
        late = runner.evaluate_task(expected_record, config_error_observed(raised=True, stage='build'))
        self.assertFalse(missed['passed'])
        self.assertTrue(raised['passed'], raised['failures'])
        self.assertTrue(late['passed'])

    def test_config_error_needs_the_requested_values_not_the_untouched_baseline(self):
        expected_record = record(status='CONFIG_ERROR')
        no_candidate = runner.evaluate_task(expected_record, config_error_observed(
            raised=True, stage='load_config', config=None))
        same_bytes = runner.evaluate_task(expected_record, config_error_observed(
            raised=True, stage='load_config', candidate_sha256='a' * 64))
        self.assertFalse(no_candidate['passed'], '没物化候选就不算把坏值喂给了 load_config')
        self.assertFalse(same_bytes['passed'], '候选字节等于基线 = 拿未改动的配置去撞守卫')

    def test_config_error_must_be_attributable_to_the_requested_change(self):
        expected_record = record(status='CONFIG_ERROR')
        broken_baseline = runner.evaluate_task(expected_record, config_error_observed(
            raised=True, stage='load_config', baseline_ok=False, baseline_error='ConfigError: bad'))
        mutated = runner.evaluate_task(expected_record, config_error_observed(
            raised=True, stage='load_config', baseline_unchanged=False))
        self.assertFalse(broken_baseline['passed'], '基线本身就装不下时，拒绝无法归因')
        self.assertFalse(mutated['passed'], '物化候选不得改动基线副本')

    def test_config_error_rejection_must_not_leave_artifacts(self):
        expected_record = record(status='CONFIG_ERROR')
        verdict = runner.evaluate_task(expected_record, config_error_observed(
            raised=True, stage='load_config', artifacts=['/tmp/staging/candidate.png']))
        self.assertFalse(verdict['passed'])


class ConfigMaterialisationTests(unittest.TestCase):
    """候选 YAML 由记录里的精确键段物化：取值原样搬运，基线对象与键段都不许被造出来。"""

    def test_operations_are_copied_verbatim_onto_a_copy(self):
        baseline = {'peak_shifts_mm': {'main': {'3.91': 0.0}}, 'canvas_w_mm': 88.4}
        candidate = runner._apply_operations_to_config(
            baseline, [{'operation': 'set_parameter', 'path': ['peak_shifts_mm', 'main', '3.91'],
                        'value': 9.0}])
        self.assertEqual(candidate['peak_shifts_mm']['main']['3.91'], 9.0)
        self.assertEqual(baseline['peak_shifts_mm']['main']['3.91'], 0.0, '基线对象必须原样不动')
        self.assertIsNot(candidate['peak_shifts_mm'], baseline['peak_shifts_mm'])

    def test_missing_path_or_foreign_operation_cannot_produce_a_candidate(self):
        baseline = {'canvas_w_mm': 88.4}
        for operations in ([{'operation': 'set_parameter', 'path': ['nope'], 'value': 1.0}],
                          [{'operation': 'set_parameter', 'path': ['canvas_w_mm', 'deep'], 'value': 1.0}],
                          [{'operation': 'set_relation', 'relation_id': 'r', 'target_mm': 1.0}],
                          [{'operation': 'set_parameter', 'path': [], 'value': 1.0}]):
            with self.assertRaises((KeyError, ValueError)):
                runner._apply_operations_to_config(baseline, operations)
        self.assertEqual(baseline, {'canvas_w_mm': 88.4}, '失败的物化不许留下改动')


class InvariantComparisonTests(unittest.TestCase):
    def _facts(self, payload):
        return {'payload': payload, 'nodes': {}, 'qa': [], 'staging_png': None,
                'text_anchors_mm': {}, 'science_manifest': None, 'science_manifest_jsonable': True,
                'science_inputs': {'missing': []}}

    def test_unknown_invariant_fails_closed_on_any_payload_change(self):
        base = self._facts({'lines': {'a': 1}, 'texts': {'t': 'x'}})
        cand = self._facts({'lines': {'a': 1}, 'texts': {'t': 'y'}})
        outcome = runner._compare_invariants(base, cand, ['mixed.unregistered_thing'], {})
        self.assertFalse(outcome['mixed.unregistered_thing']['ok'])
        self.assertIn('fail_closed', outcome['mixed.unregistered_thing']['basis'])

    def test_known_invariant_ignores_groups_it_does_not_cover(self):
        base = self._facts({'lines': {'a': 1}, 'texts': {'t': 'x'}})
        cand = self._facts({'lines': {'a': 1}, 'texts': {'t': 'y'}})
        outcome = runner._compare_invariants(base, cand, ['ftir.curve_arrays'], {})
        self.assertTrue(outcome['ftir.curve_arrays']['ok'])

    def test_known_invariant_catches_its_own_group(self):
        base = self._facts({'lines': {'a': 1}})
        cand = self._facts({'lines': {'a': 2}})
        outcome = runner._compare_invariants(base, cand, ['ftir.curve_arrays'], {})
        self.assertFalse(outcome['ftir.curve_arrays']['ok'])


class TimingAndEvidenceTests(unittest.TestCase):
    def test_p95_uses_real_samples_only(self):
        self.assertIsNone(runner.summarize_timings([])['p95_s'])
        summary = runner.summarize_timings([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(summary['n'], 4)
        self.assertEqual(summary['p95_s'], 4.0)
        self.assertIsNone(runner.quantile([], 0.95))

    def test_agent_rate_withheld_without_external_trials(self):
        instance = runner.AcceptanceRunner.__new__(runner.AcceptanceRunner)
        instance.agent_trials_path = None
        evidence = instance.agent_evidence([])
        self.assertFalse(evidence['provided'])
        self.assertEqual(evidence['status'], 'unavailable')
        self.assertFalse(evidence['claim_allowed'])
        self.assertIsNone(evidence['success_rate'])
        self.assertFalse(evidence['coverage_gate']['complete'])
        for arm in runner.ARMS:
            self.assertIsNone(evidence['arms'][arm]['coverage'])

    def test_trial_replaying_the_pristine_authority_is_not_agent_evidence(self):
        """脚本与 YAML 都没改 = 确定性重放，不是 Agent 改动，不计入证据。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / 'fixture.py'
            fixture.write_text('def build():\n    return 1\n', encoding='utf8')
            config = root / 'fixture.yaml'
            config.write_text('canvas_w_mm: 88.4\n', encoding='utf8')
            candidate_yaml = root / 'candidate.yaml'
            candidate_yaml.write_text('canvas_w_mm: 88.4\n', encoding='utf8')
            trials = [trial(task_id='T1', arm='B', candidate_script=str(fixture),
                            candidate_config=str(candidate_yaml))]
            instance = agent_runner(tmp, trials)
            evidence = instance.agent_evidence([agent_record(fixture, config)])
        entry = evidence['trials'][0]
        self.assertEqual(entry['status'], 'REPLAY_ONLY')
        self.assertFalse(entry['success'])
        self.assertEqual(evidence['replay_trials'], 1)
        self.assertEqual(evidence['verified_trials'], 0)
        self.assertEqual(evidence['successes'], 0)
        self.assertEqual(evidence['arms']['B']['tasks_covered'], 0)
        self.assertFalse(evidence['claim_allowed'])

    def test_recorded_success_cannot_survive_a_failed_independent_rebuild(self):
        """记录自称 VERIFIED/success=True，但独立重建跑不起来 → 状态如实落在失败上。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / 'fixture.py'
            fixture.write_text('raise RuntimeError("pristine fixture cannot stand in here")\n',
                               encoding='utf8')
            candidate_script = root / 'candidate.py'
            candidate_script.write_text('raise RuntimeError("broken candidate")\n', encoding='utf8')
            config = root / 'fixture.yaml'
            config.write_text('canvas_w_mm: 88.4\n', encoding='utf8')
            candidate_yaml = root / 'candidate.yaml'
            candidate_yaml.write_text('canvas_w_mm: 100.0\n', encoding='utf8')
            trials = [trial(task_id='T1', arm='A', candidate_script=str(candidate_script),
                            candidate_config=str(candidate_yaml), status='VERIFIED', success=True)]
            instance = agent_runner(tmp, trials)
            instance.probe = lambda request, tag: {'ok': False, 'error': 'boom'}
            evidence = instance.agent_evidence([agent_record(fixture, config)])
        entry = evidence['trials'][0]
        self.assertEqual(entry['status'], 'REBUILD_FAILED')
        self.assertFalse(entry['verified'])
        self.assertFalse(entry['success'])
        self.assertEqual(evidence['verified_trials'], 0)
        self.assertEqual(evidence['successes'], 0)
        self.assertEqual(evidence['arms']['A']['tasks_covered'], 0)
        self.assertFalse(evidence['claim_allowed'])


class ArmFitTests(unittest.TestCase):
    """臂与真实产物的匹配：A 必须改 Python，B/C 不许改，两者都没改就是重放。"""

    def _fit(self, arm, script_changed, config_changed):
        failures, notes = [], []
        verdict = runner.judge_arm_fit(arm, script_changed, config_changed, failures, notes)
        return verdict, failures, notes

    def test_arm_a_needs_a_real_python_change(self):
        verdict, failures, _ = self._fit('A', False, True)
        self.assertEqual(verdict, 'arm_violation')
        self.assertTrue(failures)

    def test_arm_b_or_c_may_not_change_python(self):
        for arm in ('B', 'C'):
            verdict, failures, _ = self._fit(arm, True, True)
            self.assertEqual(verdict, 'arm_violation', arm)
            self.assertTrue(failures, arm)

    def test_unchanged_script_and_config_is_a_replay_not_a_success(self):
        verdict, failures, notes = self._fit('A', False, False)
        self.assertEqual(verdict, 'replay')
        self.assertEqual(failures, [])
        self.assertTrue(notes)

    def test_arm_a_python_change_passes(self):
        verdict, failures, _ = self._fit('A', True, False)
        self.assertEqual(verdict, 'ok')
        self.assertEqual(failures, [])


class RefusalEvidenceTests(unittest.TestCase):
    """负例的独立拒绝证据：只有原始夹具真的抛 ConfigError / 真的原子拒绝才算数。"""

    def base_refusal(self, **overrides) -> dict:
        refusal = {'basis': 'pristine_load_config', 'pristine_script': '/repo/fixture.py',
                   'loader_script': '/repo/fixture.py', 'diagnostic_only': True,
                   'intended_change': True, 'candidate_differs_from_baseline': True,
                   'raised': True, 'stage': 'load_config', 'error_type': 'ConfigError',
                   'error': 'ConfigError: out of range', 'baseline_ok': True, 'baseline_error': None,
                   'builds': 0, 'baseline_sha256_unchanged': True}
        refusal.update(overrides)
        return refusal

    def test_clean_refusal_evidence_passes(self):
        failures, notes = [], []
        runner.judge_config_error_refusal(self.base_refusal(), failures, notes)
        self.assertEqual(failures, [])

    def test_forged_or_unattributable_refusals_fail(self):
        for override in ({'error_type': 'ValueError'}, {'error_type': None},
                         {'loader_script': '/tmp/candidate.py'}, {'raised': False},
                         {'builds': 1}, {'intended_change': False},
                         {'candidate_differs_from_baseline': False}, {'diagnostic_only': False},
                         {'baseline_ok': False}, {'baseline_sha256_unchanged': False}):
            failures, notes = [], []
            runner.judge_config_error_refusal(self.base_refusal(**override), failures, notes)
            self.assertTrue(failures, f'必须判失败：{override}')

    def test_late_stage_refusal_is_noted_not_failed(self):
        failures, notes = [], []
        runner.judge_config_error_refusal(self.base_refusal(stage='build'), failures, notes)
        self.assertEqual(failures, [])
        self.assertTrue(notes)

    def test_refusal_replay_needs_a_real_refusal_without_mutation_or_artifacts(self):
        record = {'id': 'T1', 'expected': {'status': 'REFUSED', 'refusal': {'rule': 'CONTRADICTORY'}}}
        clean = {'basis': 'pristine_session_replay', 'status': 'CONTRADICTORY', 'state_mutated': False,
                 'mutation_detail': None, 'artifacts': [], 'publishable_candidate': False}
        failures, notes = [], []
        runner.judge_refusal_replay(record, clean, failures, notes)
        self.assertEqual(failures, [])
        for override in ({'status': 'OK'}, {'status': None}, {'state_mutated': True},
                         {'artifacts': ['/tmp/staging/candidate.png']},
                         {'publishable_candidate': True}, {'status': 'NOT_IN_SCOPE'}):
            failures, notes = [], []
            runner.judge_refusal_replay(record, {**clean, **override}, failures, notes)
            self.assertTrue(failures, f'必须判失败：{override}')

    def test_declared_rule_outside_the_status_vocabulary_is_only_noted(self):
        record = {'id': 'T1',
                  'expected': {'status': 'REFUSED', 'refusal': {'rule': 'CONTRADICTORY_REQUESTS'}}}
        failures, notes = [], []
        runner.judge_refusal_replay(record, {'status': 'CONTRADICTORY', 'state_mutated': False,
                                             'artifacts': [], 'publishable_candidate': False},
                                    failures, notes)
        self.assertEqual(failures, [])
        self.assertTrue(notes)


class TimingMetadataTests(unittest.TestCase):
    """真实计时元数据：时间戳与秒数必须互相印证，missing metadata 一律如实报不可用。"""

    def test_consistent_timing_is_available(self):
        timing = runner._wall_metadata({'started_at': '2026-10-10T12:00:00+08:00',
                                        'finished_at': '2026-10-10T12:00:20+08:00',
                                        'wall_seconds': 20.0})
        self.assertTrue(timing['available'])
        self.assertEqual(timing['reason'], None)

    def test_inconsistent_or_missing_timing_is_unavailable(self):
        mismatch = runner._wall_metadata({'started_at': '2026-10-10T12:00:00+08:00',
                                          'finished_at': '2026-10-10T12:00:20+08:00',
                                          'wall_seconds': 5.0})
        missing = runner._wall_metadata({'started_at': '2026-10-10T12:00:00+08:00'})
        unparsable = runner._wall_metadata({'started_at': 'morning', 'finished_at': 'noon',
                                            'wall_seconds': 1.0})
        for timing in (mismatch, missing, unparsable):
            self.assertFalse(timing['available'])
            self.assertTrue(timing['reason'])

    def test_raw_evidence_needs_real_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(runner._raw_evidence({'path': str(Path(tmp) / 'nope.txt')})['present'])
        self.assertTrue(runner._raw_evidence('REQUEST')['present'])
        self.assertFalse(runner._raw_evidence('   ')['present'])
        self.assertFalse(runner._raw_evidence(None)['present'])

    def test_diagnostic_yaml_outside_the_repo_boundary(self):
        self.assertTrue(runner._inside_repo(ROOT / 'eval' / 'run_vnext_tasks.py'))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(runner._inside_repo(Path(tmp) / 'candidate.yaml'))


class ArmEvidenceTests(unittest.TestCase):
    """按臂归组的实测覆盖：缺臂/缺任务不给结论，坏样本留在分母里。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.root = root
        (root / 'fixture.py').write_text('def build():\n    return 1\n', encoding='utf8')
        (root / 'baseline.yaml').write_text('canvas_w_mm: 88.4\n', encoding='utf8')
        (root / 'candidate.yaml').write_text('canvas_w_mm: 100.0\n', encoding='utf8')
        (root / 'candidate.py').write_text('def build():\n    return 2\n', encoding='utf8')

    def corpus(self):
        return [self.record('T1'), self.record('T2')]

    def record(self, name, status='OK', operations=None):
        return agent_record(self.root / 'fixture.py', self.root / 'baseline.yaml', name=name,
                            status=status, operations=operations)

    def positive_trials(self, arms, *, task_ids=('T1', 'T2'), config=None, script=True):
        trials = []
        for arm in arms:
            for name in task_ids:
                fields = {'task_id': name, 'arm': arm,
                          'candidate_config': str(config or self.root / 'candidate.yaml')}
                if script:
                    fields['candidate_script'] = str(self.root / 'candidate.py' if arm == 'A'
                                                     else self.root / 'fixture.py')
                trials.append(trial(**fields))
        return trials

    def test_one_arm_can_never_claim_full_coverage(self):
        instance = agent_runner(self._tmp.name, self.positive_trials(('A',)))
        instance.probe = lambda request, tag: copy.deepcopy(REBUILD_OK)
        evidence = instance.agent_evidence(self.corpus())
        self.assertEqual(evidence['arms']['A']['tasks_covered'], 2)
        self.assertTrue(evidence['arms']['A']['complete'])
        self.assertEqual(evidence['arms']['B']['tasks_covered'], 0)
        self.assertFalse(evidence['coverage_gate']['complete'])
        self.assertEqual(evidence['coverage_gate']['missing_arms'], ['B', 'C'])
        self.assertFalse(evidence['claim_allowed'])

    def test_all_arms_full_coverage_unlocks_the_claim(self):
        instance = agent_runner(self._tmp.name, self.positive_trials(('A', 'B', 'C')))
        instance.probe = lambda request, tag: copy.deepcopy(REBUILD_OK)
        evidence = instance.agent_evidence(self.corpus())
        self.assertTrue(evidence['coverage_gate']['complete'])
        self.assertTrue(evidence['claim_allowed'])
        self.assertTrue(all(evidence['arms'][arm]['complete'] for arm in runner.ARMS))
        arm = evidence['arms']['A']
        self.assertEqual(arm['attempts'], 2)
        self.assertEqual(arm['successes'], 2)
        self.assertEqual(arm['first_attempt_successes'], 2)
        self.assertEqual(arm['first_attempt_success_rate'], 1.0)
        self.assertEqual(arm['full_render_successes'], 2)
        self.assertEqual(arm['wall_seconds_total'], 40.0)
        self.assertTrue(arm['efficiency_claim_allowed'])
        self.assertEqual(evidence['counts']['failed_judged'], 0)

    def test_failed_judged_attempt_stays_in_the_denominator(self):
        trials = [
            trial(task_id='T1', arm='A', candidate_script=str(self.root / 'candidate.py'),
                  candidate_config=str(self.root / 'candidate.yaml')),
            trial(task_id='T1', arm='A', attempt=2, started_at='2026-10-10T12:05:00+08:00',
                  finished_at='2026-10-10T12:05:30+08:00', wall_seconds=30.0,
                  candidate_script=str(self.root / 'candidate.py'),
                  candidate_config=str(self.root / 'candidate.yaml')),
        ]
        instance = agent_runner(self._tmp.name, trials)
        calls = {'n': 0}

        def probe(request, tag):
            calls['n'] += 1
            payload = copy.deepcopy(REBUILD_OK)
            if calls['n'] == 1:
                payload['candidate']['qa'] = ['TEXT_OVERLAP: x']  # 首次尝试引入 QA 阻断项
            return payload

        instance.probe = probe
        evidence = instance.agent_evidence([self.record('T1')])
        arm = evidence['arms']['A']
        self.assertEqual(arm['attempts'], 2)
        self.assertEqual(arm['successes'], 1)
        self.assertEqual(arm['redo_attempts'], 1)
        self.assertEqual(arm['first_attempt_successes'], 0)
        self.assertEqual(arm['attempt_success_rate'], 0.5)
        self.assertEqual(arm['tasks_covered'], 1)
        self.assertEqual(evidence['counts']['failed_judged'], 1)

    def test_missing_timing_blocks_efficiency_but_keeps_the_coverage(self):
        trials = []
        for item in self.positive_trials(('A', 'B', 'C')):
            for key in ('started_at', 'finished_at', 'wall_seconds', 'raw_request', 'raw_response'):
                item.pop(key)
            trials.append(item)
        instance = agent_runner(self._tmp.name, trials)
        instance.probe = lambda request, tag: copy.deepcopy(REBUILD_OK)
        evidence = instance.agent_evidence(self.corpus())
        self.assertTrue(evidence['coverage_gate']['complete'])
        self.assertTrue(evidence['claim_allowed'])
        for arm in runner.ARMS:
            stats = evidence['arms'][arm]
            self.assertFalse(stats['timing_complete'])
            self.assertFalse(stats['efficiency_claim_allowed'])
            self.assertIsNone(stats['wall_seconds_total'])
        self.assertEqual(evidence['counts']['timing_unavailable'], 6)
        self.assertEqual(evidence['counts']['raw_unavailable'], 6)

    def test_unattributable_record_blocks_the_claim(self):
        trials = self.positive_trials(('A', 'B', 'C'))
        trials.append(trial(task_id='T1', arm=None, agent=None, attempt=None,
                            candidate_config=str(self.root / 'candidate.yaml')))
        instance = agent_runner(self._tmp.name, trials)
        instance.probe = lambda request, tag: copy.deepcopy(REBUILD_OK)
        evidence = instance.agent_evidence(self.corpus())
        self.assertEqual(evidence['trials'][-1]['status'], 'MISSING_METADATA')
        self.assertEqual(evidence['counts']['unattributed'], 1)
        self.assertFalse(evidence['claim_allowed'])

    def test_config_error_trial_without_diagnostic_yaml_is_not_a_success(self):
        operations = [{'operation': 'set_parameter', 'path': ['canvas_w_mm'], 'value': 120.0}]
        instance = agent_runner(self._tmp.name, [trial(task_id='T1', arm='A', diagnostic_only=True)])
        evidence = instance.agent_evidence([self.record('T1', status='CONFIG_ERROR',
                                                        operations=operations)])
        entry = evidence['trials'][0]
        self.assertEqual(entry['status'], 'REFUSAL_UNVERIFIED')
        self.assertFalse(entry['verified'])
        self.assertFalse(entry['success'])
        self.assertEqual(evidence['arms']['A']['tasks_covered'], 0)
        self.assertFalse(evidence['claim_allowed'])

    def test_broken_candidate_yaml_is_a_failed_trial_not_a_crash(self):
        (self.root / 'broken.yaml').write_text('canvas_w_mm: [unclosed\n', encoding='utf8')
        trials = [trial(task_id='T1', arm='A', candidate_script=str(self.root / 'candidate.py'),
                        candidate_config=str(self.root / 'broken.yaml'))]
        instance = agent_runner(self._tmp.name, trials)
        instance.probe = lambda request, tag: copy.deepcopy(REBUILD_OK)
        evidence = instance.agent_evidence([self.record('T1')])
        entry = evidence['trials'][0]
        self.assertEqual(entry['status'], 'TRIAL_ERROR')
        self.assertFalse(entry['verified'])
        self.assertFalse(entry['success'])
        self.assertEqual(evidence['arms']['A']['tasks_covered'], 0)
        self.assertFalse(evidence['claim_allowed'])

    def test_replayed_positive_trial_cannot_unlock_the_claim(self):
        trials = self.positive_trials(('A', 'B', 'C'), script=False)
        for item in trials:
            item['candidate_config'] = str(self.root / 'baseline.yaml')  # 未改动的可发布配置
        instance = agent_runner(self._tmp.name, trials)
        instance.probe = lambda request, tag: copy.deepcopy(REBUILD_OK)
        evidence = instance.agent_evidence(self.corpus())
        self.assertEqual(evidence['replay_trials'], 6)
        self.assertEqual(evidence['verified_trials'], 0)
        self.assertFalse(evidence['claim_allowed'])
        self.assertEqual(evidence['success_rate'], 0.0, '重放仍留在分母里，成功率是 0 而不是被丢掉')


if __name__ == '__main__':
    unittest.main()
