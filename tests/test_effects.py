"""效果验证器的行为回归：真实临时 YAML 扰动 + 真实整图重建。

夹具复用 test_session 里的原生探针脚本（有：正常接线的位移/字号、没接线的旋钮、
声明与实现不一致的错绑定、10× 错标的位移、锁定科学内容）。
断言全部落在可复查的证据上：扰动 YAML 文本、实测几何/样式增量、结论状态。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib
matplotlib.use('Agg', force=True)
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact import effects  # noqa: E402
from figpact.session import ContractError, get_path  # noqa: E402

LEGACY_SCRIPT = ROOT / 'tests' / 'fixtures' / 'synth_plot.py'
LEGACY_CONFIG = ROOT / 'tests' / 'fixtures' / 'synth.yaml'


class EffectsOnNativeProbeTest(unittest.TestCase):
    def setUp(self):
        from tests.test_session import write_native_probe
        self._tmp = tempfile.TemporaryDirectory(prefix='figpact-effects-test-')
        self.root = Path(self._tmp.name)
        self.script, self.config = write_native_probe(self.root)
        self.report = effects.check_effects(self.script, self.config, 'main')

    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')
        self._tmp.cleanup()

    def _record(self, key):
        for entry in self.report['results']:
            if entry['key'] == key:
                return entry
        self.fail(f'结果里没有 {key}：{[e["key"] for e in self.report["results"]]}')

    def test_perturbation_is_a_real_yaml_edit(self):
        baseline = yaml.safe_load(self.config.read_text(encoding='utf8'))
        for entry in self.report['results']:
            if 'yaml_text' not in entry:
                continue
            with self.subTest(key=entry['key']):
                perturbed = yaml.safe_load(entry['yaml_text'])
                self.assertEqual(get_path(perturbed, entry['path']),
                                 entry['perturbation']['to'])
                self.assertEqual(get_path(baseline, entry['path']),
                                 entry['perturbation']['from'])
                for key, value in baseline.items():
                    if key == entry['path'][0]:
                        continue
                    self.assertEqual(perturbed[key], value, '扰动只许碰声明的那个键')

    def test_wired_parameters_are_effect_ok(self):
        declared = {'curve_shift': ['probe.main.curve'],
                    'guide_shift': ['probe.main.guide'],
                    'label_x': ['probe.main.label'],
                    'label_font': ['probe.main.label']}
        for key, objects in declared.items():
            entry = self._record(key)
            with self.subTest(key=key):
                self.assertEqual(entry['status'], effects.EFFECT_OK, entry)
                self.assertEqual(entry['observed']['objects'], objects,
                                 '响应的必须正好是声明的那个对象')
                self.assertEqual(entry['observed']['structure'], {'added': [], 'removed': []})

    def test_translation_direction_and_axis_are_measured(self):
        entry = self._record('curve_shift')
        delta = entry['observed']['geometry']['gid:probe.main.curve']
        self.assertAlmostEqual(delta['dy_mm'], 1.0, delta=0.02)
        self.assertAlmostEqual(delta['dx_mm'], 0.0, delta=0.02)
        self.assertEqual(entry['observed']['axis'], 'y')

    def test_unwired_parameters_report_no_effect(self):
        for key in ('ghost_shift', 'unused_style'):
            entry = self._record(key)
            with self.subTest(key=key):
                self.assertEqual(entry['status'], effects.NO_EFFECT, entry)
                self.assertEqual(entry['observed']['objects'], [])

    def test_wrong_binding_is_reported_as_mismatch(self):
        entry = self._record('font_knob_wrong_binding')
        self.assertEqual(entry['status'], effects.EFFECT_MISMATCH, entry)
        self.assertEqual(entry['observed']['objects'], ['probe.main.badge'],
                         '真实重建里响应的是被错绑定的徽标，不是声明的曲线')
        self.assertNotIn('probe.main.curve', entry['observed']['objects'])

    def test_locked_science_is_not_perturbed(self):
        locked = self._record('locked')
        self.assertEqual(locked['status'], effects.SKIPPED_LOCKED_SCIENCE, locked)
        self.assertNotIn('yaml_text', locked)

    def test_wrong_scale_binding_is_a_mismatch_not_effect_ok(self):
        """声明 scale 1.0、绑定只移动 0.1×：实测物理量与声明不符 → EFFECT_MISMATCH。"""
        from tests.test_session import NATIVE_SCRIPT
        needle = ('"key": "label_x", "path": ["label_x_mm"], "unit": "mm",\n'
                  '             "mutability": "EDITABLE", "operation": "translate", '
                  '"axis": "x", "scale": 1.0,')
        wrong = NATIVE_SCRIPT.replace(
            needle, needle.replace('"scale": 1.0', '"scale": 10.0')).replace(
            'apply_display_shift(label, dx_mm=config["label_x_mm"])',
            'apply_display_shift(label, dx_mm=config["label_x_mm"] * 0.1)')
        self.assertNotEqual(wrong, NATIVE_SCRIPT, '夹具文本替换必须命中')
        script = self.root / 'probe_wrong_scale.py'
        script.write_text(wrong, encoding='utf8')
        report = effects.check_effects(script, self.config, 'main')
        entry = next(e for e in report['results'] if e['key'] == 'label_x')
        self.assertEqual(entry['status'], effects.EFFECT_MISMATCH, entry)
        self.assertEqual(entry['observed']['axis'], 'x')
        self.assertEqual(entry['observed']['objects'], ['probe.main.label'])
        # 独立读数：这次扰动 1.0 实测只走了 0.1 mm，而声明的标尺是 10×（要求 10 mm）。
        delta = entry['observed']['geometry']['gid:probe.main.label']
        self.assertAlmostEqual(delta['dx_mm'], 0.1, delta=0.02,
                               msg='绑定只按 0.1× 生效，声明却要求 10×')
        self.assertAlmostEqual(delta['dy_mm'], 0.0, delta=0.02, msg='只许沿声明轴（x）走')

    def test_direction_flip_is_a_mismatch(self):
        """绑定方向反了：轴对了、量也对不了 —— 必须报不符，不许 EFFECT_OK。"""
        from tests.test_session import NATIVE_SCRIPT
        wrong = NATIVE_SCRIPT.replace(
            'apply_display_shift(curve, dy_mm=config["curve_shift_mm"])',
            'apply_display_shift(curve, dy_mm=-config["curve_shift_mm"])')
        self.assertNotEqual(wrong, NATIVE_SCRIPT, '夹具文本替换必须命中')
        script = self.root / 'probe_flipped.py'
        script.write_text(wrong, encoding='utf8')
        report = effects.check_effects(script, self.config, 'main')
        entry = next(e for e in report['results'] if e['key'] == 'curve_shift')
        self.assertEqual(entry['status'], effects.EFFECT_MISMATCH, entry)
        self.assertLess(entry['observed']['geometry']['gid:probe.main.curve']['dy_mm'], 0.0)

    def test_out_of_scope_parameter_is_not_reported(self):
        keys = [entry['key'] for entry in self.report['results']]
        self.assertNotIn('other_scope_only', keys)

    def test_summary_counts_and_status(self):
        self.assertEqual(self.report['status'], 'DEFECTS_FOUND')
        self.assertEqual(self.report['counts'],
                         {effects.EFFECT_OK: 4, effects.EFFECT_MISMATCH: 1,
                          effects.NO_EFFECT: 2, effects.SKIPPED_LOCKED_SCIENCE: 1},
                         '夹具里的 4 条接线 / 1 条错绑定 / 2 条没接线 / 1 条锁定科学')
        self.assertEqual(sum(self.report['counts'].values()), self.report['parameters'])
        self.assertEqual(self.report['parameters'], len(self.report['results']))

    def test_science_not_touched_by_layout_parameters(self):
        self.assertNotIn(effects.SCIENCE_VIOLATION, self.report['counts'])
        for entry in self.report['results']:
            if entry['status'] == effects.EFFECT_OK:
                self.assertIs(entry['science_unchanged'], True, entry)


class EffectsContractOverrideTest(unittest.TestCase):
    """契约覆盖路径：悬空 YAML 路径要报出来；非法契约在构造时就拒绝。"""

    def setUp(self):
        from tests.test_session import write_native_probe
        self._tmp = tempfile.TemporaryDirectory(prefix='figpact-effects-contract-')
        self.root = Path(self._tmp.name)
        self.script, self.config = write_native_probe(self.root)

    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')
        self._tmp.cleanup()

    @staticmethod
    def _record(**overrides):
        record = {'key': 'gone', 'path': ['does_not_exist'], 'unit': 'mm',
                  'mutability': 'EDITABLE', 'operation': 'translate', 'axis': 'y',
                  'min': -6.0, 'max': 6.0, 'objects': ['probe.main.curve'],
                  'expected': {'kind': 'translate', 'objects': ['probe.main.curve'],
                               'axis': 'y'}}
        record.update(overrides)
        return record

    def test_dangling_path_is_rejected(self):
        contract = {'parameters': [self._record()], 'nodes': {}, 'groups': [],
                    'relations': [], 'outputs': []}
        report = effects.check_effects(self.script, self.config, 'main', contract=contract)
        statuses = {entry['key']: entry['status'] for entry in report['results']}
        self.assertEqual(statuses['gone'], effects.REJECTED_DANGLING_PATH)
        self.assertEqual(report['status'], 'DEFECTS_FOUND')

    def test_dangling_object_is_refused_by_contract_validation(self):
        """悬空对象引用不许降级重试后被接受：契约校验直接拒绝，没有逐条结论。"""
        contract = {'parameters': [self._record(objects=['probe.main.nope'])],
                    'nodes': {}, 'groups': [], 'relations': [], 'outputs': []}
        with self.assertRaises(ContractError):
            effects.check_effects(self.script, self.config, 'main', contract=contract)


@unittest.skipUnless(LEGACY_SCRIPT.is_file(), '旧脚本夹具不在')
class LegacyScriptEffectsTest(unittest.TestCase):
    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')

    def test_legacy_script_without_contract_is_unsupported_not_guessed(self):
        report = effects.check_effects(LEGACY_SCRIPT, LEGACY_CONFIG, 'main')
        self.assertEqual(report['status'], effects.UNSUPPORTED_NO_CONTRACT, report)
        self.assertEqual(report['results'], [])
        self.assertEqual(report['contract_source'], 'absent')


if __name__ == '__main__':
    unittest.main()
