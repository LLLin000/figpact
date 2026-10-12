"""G4：`AuthoringRepairSpec` 的字段契约 —— 假会话、ast 静态取证、零文件写入。

只测消费者可见的事实：必填字段与设计包 schema 的关键约束一致；信息不足时如实留空或标
`unknown` 而**不编造**；构造规格的过程不写任何文件（临时目录逐文件哈希前后一致）。
不建图、不装载科学数据、不执行用户脚本。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.authoring import (  # noqa: E402
    LAYOUT_BINDING_NAME,
    MAX_CANDIDATE_BUILDS,
    SCHEMA_VERSION,
    UNKNOWN,
    build_repair_spec,
)

SCHEMA = json.loads(
    (ROOT / 'docs' / 'figpact-vnext-kit' / 'schemas' /
     'authoring-repair-spec.schema.json').read_text(encoding='utf8'))

TARGET = 'intent.main.label.A'

LEGACY = """\
import matplotlib.pyplot as plt


def draw_labels(ax):
    ax.text(0.5, 2.0, 'A', gid='intent.main.label.A')
    ax.text(1.5, 3.0, 'B', gid='intent.main.label.B')
"""

BOUND = """\
import matplotlib.pyplot as plt

LAYOUT_MM = {
    'intent.main.label.A': [0.0, 0.0],
    'intent.main.label.B': [0.0, 0.0],
}


def build_scene(science, config, scope):
    fig = plt.figure()
    return fig
"""

COMPUTED_BINDING = """\
import matplotlib.pyplot as plt

DEFAULT_MM = [0.0, 0.0]
LAYOUT_MM = {
    'intent.main.label.A': DEFAULT_MM,
}
"""

OPAQUE_BINDING = """\
import matplotlib.pyplot as plt


def build_bindings():
    return {'intent.main.label.A': [0.0, 0.0]}


LAYOUT_MM = build_bindings()
"""

CONTRACT = {
    'parameters': [
        {'key': 'offsets_mm/A', 'path': ['offsets_mm', 'A'], 'unit': 'mm',
         'mutability': 'EDITABLE', 'scopes': ['main'], 'operation': 'translate',
         'axis': 'y', 'objects': [TARGET]},
        {'key': 'peak_anchor', 'path': ['science', 'peak'], 'unit': 'ppm',
         'mutability': 'LOCKED_SCIENCE', 'objects': ['intent.main.peak.vancho']},
    ],
    'nodes': {'intent.main.label.B': {'science_policy': 'LOCKED_SCIENCE'}},
}
LOCKED = ['intent.main.label.B', 'intent.main.peak.vancho']


def write_script(tmp_path: Path, text: str) -> Path:
    path = tmp_path / 'skeleton.py'
    path.write_text(text, encoding='utf8')
    return path


def snapshot(root: Path) -> dict:
    """目录内容的逐文件哈希（含空目录），用来证明「什么也没写」。"""
    out = {}
    for path in sorted(root.rglob('*')):
        key = path.relative_to(root).as_posix()
        out[key] = 'dir' if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class FakeSession:
    """假会话：只提供真实会话里**已声明**的事实，不建图、不装载科学数据。"""

    def __init__(self, *, contract=None, science_manifest=None, intent_id=None,
                 desired_delta_mm=None, closure=None):
        self.contract = contract
        self.science_manifest = science_manifest
        self.intent_id = intent_id
        self.desired_delta_mm = desired_delta_mm
        self._closure = closure
        self.state_calls = 0

    def owned_closure(self, gids):
        if self._closure is None:
            return []
        return list(self._closure(gids))

    def state(self):
        self.state_calls += 1
        return {'contract': self.contract, 'science_manifest': self.science_manifest,
                'intent_id': self.intent_id, 'desired_delta_mm': self.desired_delta_mm}


def check(value, definition, where):
    if 'const' in definition:
        assert value == definition['const'], where
    if 'enum' in definition:
        assert value in definition['enum'], where
    kind = definition.get('type')
    if kind == 'string':
        assert isinstance(value, str), where
        assert len(value) >= definition.get('minLength', 0), where
        if 'pattern' in definition:
            assert re.fullmatch(definition['pattern'], value), where
    elif kind == 'integer':
        assert isinstance(value, int) and not isinstance(value, bool), where
        assert value >= definition.get('minimum', value), where
    elif kind == 'number':
        assert isinstance(value, (int, float)) and not isinstance(value, bool), where
    elif kind == 'array':
        assert isinstance(value, list), where
        assert len(value) >= definition.get('minItems', 0), where
        if 'maxItems' in definition:
            assert len(value) <= definition['maxItems'], where
        for index, item in enumerate(value):
            check(item, definition['items'], f'{where}[{index}]')
    elif kind == 'object':
        assert isinstance(value, dict), where
        for key in definition.get('required', []):
            assert key in value, f'{where}.{key}'
        if definition.get('additionalProperties') is False:
            assert set(value) <= set(definition['properties']), where
        for key, sub in definition.get('properties', {}).items():
            if key in value:
                check(value[key], sub, f'{where}.{key}')


def check_spec(spec: dict) -> None:
    """按设计包 schema 校对关键字段（不引入 jsonschema 依赖，也不改 schema 一字）。"""
    assert set(spec) == set(SCHEMA['required'])
    assert set(spec) <= set(SCHEMA['properties'])                       # additionalProperties: false
    for name in SCHEMA['required']:
        check(spec[name], SCHEMA['properties'][name], name)


# --------------------------------------------------------------------------- #

def test_legacy_script_matches_schema_key_fields(tmp_path):
    script = write_script(tmp_path, LEGACY)
    spec = build_repair_spec(script=script, target_gid=TARGET, session=object())

    check_spec(spec)
    assert spec['schema_version'] == SCHEMA_VERSION
    assert spec['target_gid'] == TARGET
    assert spec['base_source_sha256'] == hashlib.sha256(script.read_bytes()).hexdigest()
    assert spec['goal']['kind'] == 'new_edit_binding'
    assert 'desired_delta_mm' not in spec['goal']                       # 没这个信息就不编
    assert LAYOUT_BINDING_NAME in spec['goal']['explanation']
    assert spec['allowed_paths'] == ['skeleton.py']
    assert spec['source_candidates'] == [
        {'relative_path': 'skeleton.py', 'symbol': 'draw_labels', 'certainty': 'candidate'}]
    assert spec['max_candidate_builds'] == MAX_CANDIDATE_BUILDS


def test_declared_binding_is_confirmed_candidate(tmp_path):
    script = write_script(tmp_path, BOUND)
    session = FakeSession(contract=CONTRACT, science_manifest={'science': {}, 'nodes': {}},
                          intent_id='intent-0042', desired_delta_mm=[0.0, 0.15],
                          closure=lambda gids: gids + ['intent.main.guide', 'intent.main.label.B',
                                                       'intent.main.peak.vancho'])
    spec = build_repair_spec(script=script, target_gid=TARGET, session=session)

    check_spec(spec)
    assert spec['intent_id'] == 'intent-0042'
    assert spec['goal']['kind'] == 'adjust_existing_binding'
    assert spec['goal']['desired_delta_mm'] == [0.0, 0.15]
    assert spec['source_candidates'][0] == {'relative_path': 'skeleton.py',
                                            'symbol': LAYOUT_BINDING_NAME, 'certainty': 'confirmed'}
    assert spec['fixed_gids'] == LOCKED
    assert spec['allowed_follow_gids'] == ['intent.main.guide']
    assert 'science_manifest 已声明' in spec['goal']['explanation']


def test_non_literal_binding_is_only_a_candidate(tmp_path):
    script = write_script(tmp_path, COMPUTED_BINDING)
    session = FakeSession(contract=CONTRACT, science_manifest={'science': {}})
    spec = build_repair_spec(script=script, target_gid=TARGET, session=session)

    check_spec(spec)
    assert spec['goal']['kind'] == 'adjust_existing_binding'
    assert spec['source_candidates'] == [
        {'relative_path': 'skeleton.py', 'symbol': LAYOUT_BINDING_NAME, 'certainty': 'candidate'}]

    opaque = write_script(tmp_path, OPAQUE_BINDING)
    unreadable = build_repair_spec(script=opaque, target_gid=TARGET, session=session)
    check_spec(unreadable)
    assert '静态读不出键' in unreadable['goal']['explanation']
    assert unreadable['source_candidates'] == [
        {'relative_path': 'skeleton.py', 'symbol': LAYOUT_BINDING_NAME, 'certainty': 'candidate'},
        {'relative_path': 'skeleton.py', 'symbol': 'build_bindings', 'certainty': 'candidate'}]


def test_missing_information_stays_unknown(tmp_path):
    script = write_script(tmp_path, 'import matplotlib.pyplot as plt\nCURVE = None\n')
    spec = build_repair_spec(script=script, target_gid=TARGET, session=None)

    check_spec(spec)
    assert spec['intent_id'] == UNKNOWN
    assert spec['goal']['kind'] == 'new_edit_binding'
    assert 'desired_delta_mm' not in spec['goal']
    assert spec['fixed_gids'] == []                                     # 不知道就是空，不猜
    assert spec['allowed_follow_gids'] == []
    assert spec['source_candidates'] == []
    assert 'unknown' in spec['goal']['explanation']
    assert 'EDITABLE 契约路径' not in spec['goal']['explanation']        # 没有契约 ≠ 说它有契约

    declared_but_locked = FakeSession(contract={'parameters': []})
    other = build_repair_spec(script=script, target_gid=TARGET, session=declared_but_locked)
    check_spec(other)
    assert '不在任何 EDITABLE 契约路径' in other['goal']['explanation']
    assert other['intent_id'] == UNKNOWN
    assert declared_but_locked.state_calls >= 1


def test_broken_and_binary_source_is_honest(tmp_path):
    broken = write_script(tmp_path, 'def oops(:\n')
    spec = build_repair_spec(script=broken, target_gid=TARGET, session=object())
    check_spec(spec)
    assert spec['source_candidates'] == []
    assert 'LAYOUT_MM' in spec['goal']['explanation']

    binary = tmp_path / 'binary.py'
    binary.write_bytes(b'\x00\x01LAYOUT_MM = {}\x00')
    raw = build_repair_spec(script=binary, target_gid=TARGET, session=object())
    check_spec(raw)
    assert raw['base_source_sha256'] == hashlib.sha256(binary.read_bytes()).hexdigest()
    assert raw['source_candidates'] == []


def test_sibling_module_is_the_only_extra_allowed_path(tmp_path):
    (tmp_path / 'helpers.py').write_text('VALUE = 1\n', encoding='utf8')
    (tmp_path / 'unrelated.py').write_text('VALUE = 2\n', encoding='utf8')
    script = write_script(tmp_path, 'import helpers\nfrom matplotlib import pyplot\n')

    spec = build_repair_spec(script=script, target_gid=TARGET, session=object())

    check_spec(spec)
    assert spec['allowed_paths'] == ['helpers.py', 'skeleton.py']
    assert all(not Path(p).is_absolute() and '..' not in Path(p).parts
               for p in spec['allowed_paths'])


def test_specs_validate_against_the_design_schema(tmp_path):
    """有 jsonschema 时用真 schema 收口；没有就跳过（不因此加依赖）。"""
    jsonschema = pytest.importorskip('jsonschema')
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    validator = jsonschema.Draft202012Validator(SCHEMA)
    legacy = build_repair_spec(script=write_script(tmp_path, LEGACY), target_gid=TARGET,
                               session=object())
    bound = build_repair_spec(
        script=write_script(tmp_path, BOUND), target_gid=TARGET,
        session=FakeSession(contract=CONTRACT, science_manifest={'science': {}},
                            desired_delta_mm=[0, 0.15]))
    for spec in (legacy, bound):
        validator.validate(spec)


def test_invalid_target_gid_is_rejected(tmp_path):
    script = write_script(tmp_path, LEGACY)
    for bad in ('', None, 7):
        with pytest.raises(ValueError):
            build_repair_spec(script=script, target_gid=bad, session=object())


def test_building_the_spec_writes_nothing(tmp_path):
    write_script(tmp_path, LEGACY)
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested' / 'data.bin').write_bytes(b'\x00\xff')
    before = snapshot(tmp_path)

    for session in (object(), None, FakeSession(contract=CONTRACT, science_manifest={},
                                               closure=lambda gids: list(gids))):
        check_spec(build_repair_spec(script=tmp_path / 'skeleton.py', target_gid=TARGET,
                                     session=session))

    assert snapshot(tmp_path) == before
