"""python_native 契约：ast 唯一定位 + 只计划不写入 + 未授权拒绝。

只测消费者可见的事实：``LAYOUT_MM`` 声明被深拷贝读回、脚本主块不执行也不产生副作用
文件；定位基于 ``ast``——偏移能在源码文本上直接切片、同名字面量落在别的字典
（可能是科学数据）里时不被误认；plan 只写 G3b journal 与 blob，用户源码一个字节不变；
同一 key 出现多次、字面量不是纯数字 ``[dx, dy]`` 时返回候选 + ``confidence='low'`` 且
零文件变更；未授权 apply 明确拒绝，授权后落盘内容与 before/after blob 完全一致。
全部使用真实临时目录与真实脚本文件，不 mock 文件系统。
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.python_native import (  # noqa: E402
    apply_planned_edit,
    locate_layout_literal,
    plan_layout_edit,
    read_layout_binding,
)

BASE_SCRIPT = '''#!/usr/bin/env python3
"""最小 Python-native 图：一条曲线 + 两个文本标签（无 YAML）。"""

LAYOUT_MM = {
    "intent.main.label.A": [0.0, 0.0],
    "intent.main.label.B": [0.0, 0.0],
}

SCIENCE_MM = {
    "intent.main.label.A": [1.0, 2.0],
}


def build_scene(science, scope, config):
    line, = ax.plot([0.0, 1.0], [0.0, 1.0])
    labels = {gid: ax.text(0.5, 0.5, gid) for gid in LAYOUT_MM}
    return {"line": line, "labels": labels}
'''

SIDE_EFFECT_SCRIPT = '''from pathlib import Path

LAYOUT_MM = {"intent.main.label.A": [0.0, 0.0]}

if __name__ == "__main__":
    Path(__file__).with_name("side-effect.txt").write_text("ran", encoding="utf-8")
'''

MULTILINE_SCRIPT = '''LAYOUT_MM = {
    "intent.main.label.A": [
        0.0,
        -0.15,
    ],
    "intent.main.label.B": [-0.25, 0.5],
}


def build_scene(science, scope, config):
    return dict(LAYOUT_MM)
'''

DUPLICATE_SCRIPT = '''LAYOUT_MM = {
    "intent.main.label.A": [0.0, 0.0],
    "intent.main.label.A": [0.0, 0.15],
}
'''

REPEATED_DEFINITION_SCRIPT = '''LAYOUT_MM = {"intent.main.label.A": [0.0, 0.0]}

LAYOUT_MM = {"intent.main.label.A": [0.0, 0.0]}
'''

NON_NUMERIC_SCRIPT = '''DY = 0.15

LAYOUT_MM = {
    "intent.main.label.A": [0.0, DY],
}
'''


def write_script(directory: Path, text: str, name: str = 'figure.py') -> Path:
    # 字节写入：磁盘上的夹具必须逐字节等于测试源码里的字符串（BASE_SCRIPT 等），
    # 否则文本模式会把 \n 翻译成平台换行，plan 的逐字节保真 blob 就对不上期望。
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(text.encode('utf-8'))
    return path


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def journal_record(home: Path, journal_id: str) -> dict:
    path = home / 'source-journals' / f'{journal_id}.json'
    return json.loads(path.read_text(encoding='utf-8'))


def blob_bytes(home: Path, digest: str) -> bytes:
    return (home / 'blobs' / 'sha256' / digest[:2] / digest).read_bytes()


def listing(directory: Path) -> list[str]:
    return sorted(item.name for item in directory.iterdir())


# ---------------------------------------------------------------- 读取声明

def test_read_layout_binding_returns_only_declared_layout_mapping(tmp_path):
    script = write_script(tmp_path, BASE_SCRIPT)

    declared = read_layout_binding(script)

    assert declared == {'intent.main.label.A': [0.0, 0.0], 'intent.main.label.B': [0.0, 0.0]}
    declared['intent.main.label.A'].append(9.0)
    assert read_layout_binding(script) == {'intent.main.label.A': [0.0, 0.0],
                                           'intent.main.label.B': [0.0, 0.0]}
    assert listing(tmp_path) == ['figure.py']


def test_read_layout_binding_without_declaration_is_empty(tmp_path):
    script = write_script(tmp_path, 'X = 1\n')

    assert read_layout_binding(script) == {}


def test_read_layout_binding_does_not_run_main_guard(tmp_path):
    script = write_script(tmp_path, SIDE_EFFECT_SCRIPT)

    declared = read_layout_binding(script)

    assert declared == {'intent.main.label.A': [0.0, 0.0]}
    assert listing(tmp_path) == ['figure.py']


def test_read_layout_binding_restores_dont_write_bytecode_on_import_error(tmp_path):
    import sys

    script = write_script(tmp_path, 'raise RuntimeError("boom")\n')
    sentinel = object()
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = sentinel
    try:
        try:
            read_layout_binding(script)
        except RuntimeError:
            pass
        else:  # pragma: no cover - 导入期异常必须原样上抛
            raise AssertionError("expected RuntimeError")
        assert sys.dont_write_bytecode is sentinel
    finally:
        sys.dont_write_bytecode = old
    assert listing(tmp_path) == ['figure.py']


# ---------------------------------------------------------------- ast 定位

def test_locate_layout_literal_offsets_slice_the_source(tmp_path):
    write_script(tmp_path, BASE_SCRIPT)

    first = locate_layout_literal(BASE_SCRIPT, 'intent.main.label.A')
    second = locate_layout_literal(BASE_SCRIPT, 'intent.main.label.B')

    assert first is not None and second is not None
    # A 字面量就是全文第一个 [0.0, 0.0]；SCIENCE_MM 里的同名 key（[1.0, 2.0]）不得被认成它。
    assert first['start'] == BASE_SCRIPT.index('[0.0, 0.0]')
    assert first['value'] == [0.0, 0.0]
    assert BASE_SCRIPT.splitlines()[first['line'] - 1] == '    "intent.main.label.A": [0.0, 0.0],'
    assert BASE_SCRIPT.splitlines()[second['line'] - 1] == '    "intent.main.label.B": [0.0, 0.0],'
    segment = BASE_SCRIPT[second['start']:second['end']]
    assert segment == '[0.0, 0.0]'
    assert ast.literal_eval(segment) == second['value'] == [0.0, 0.0]


def test_locate_layout_literal_handles_multiline_and_signs(tmp_path):
    write_script(tmp_path, MULTILINE_SCRIPT)

    located = locate_layout_literal(MULTILINE_SCRIPT, 'intent.main.label.A')

    assert located is not None
    segment = MULTILINE_SCRIPT[located['start']:located['end']]
    assert ast.literal_eval(segment) == [0.0, -0.15]
    assert located['value'] == [0.0, -0.15]
    assert MULTILINE_SCRIPT.splitlines()[located['line'] - 1] == '    "intent.main.label.A": ['
    assert segment.count('\n') == 3
    other = locate_layout_literal(MULTILINE_SCRIPT, 'intent.main.label.B')
    assert other is not None and other['value'] == [-0.25, 0.5]


def test_locate_layout_literal_is_none_when_missing_or_repeated():
    assert locate_layout_literal(BASE_SCRIPT, 'intent.main.label.C') is None
    assert locate_layout_literal(DUPLICATE_SCRIPT, 'intent.main.label.A') is None
    assert locate_layout_literal(REPEATED_DEFINITION_SCRIPT, 'intent.main.label.A') is None
    assert locate_layout_literal(NON_NUMERIC_SCRIPT, 'intent.main.label.A') is None


# -------------------------------------------------------------------- 计划

def test_plan_produces_journal_without_touching_source(tmp_path):
    script = write_script(tmp_path, BASE_SCRIPT)
    before = script.read_bytes()
    home = tmp_path / 'state'

    result = plan_layout_edit(script, 'intent.main.label.B', [0.0, 0.15],
                              state_home=home, reason='G4 单元测试')

    assert result['status'] == 'OK'
    assert script.read_bytes() == before
    assert result['before_sha256'] == sha256_hex(before)
    assert listing(tmp_path) == ['figure.py', 'state']
    journal = result['journal']
    assert journal['status'] == 'PREPARED'
    assert journal['reason'] == 'G4 单元测试'
    entry = journal['files'][0]
    assert Path(entry['path']) == script
    assert entry['before_sha256'] == result['before_sha256']
    assert entry['after_sha256'] == result['after_sha256']
    assert '-    "intent.main.label.B": [0.0, 0.0],' in entry['diff']
    assert '+    "intent.main.label.B": [0.0, 0.15],' in entry['diff']
    expected = BASE_SCRIPT.replace('"intent.main.label.B": [0.0, 0.0]',
                                   '"intent.main.label.B": [0.0, 0.15]')
    assert blob_bytes(home, result['after_sha256']) == expected.encode('utf-8')
    assert blob_bytes(home, result['before_sha256']) == before
    assert journal_record(home, journal['id'])['status'] == 'PREPARED'


def test_plan_duplicate_key_is_ambiguous_and_writes_nothing(tmp_path):
    script = write_script(tmp_path, DUPLICATE_SCRIPT)
    before = script.read_bytes()
    home = tmp_path / 'state'

    result = plan_layout_edit(script, 'intent.main.label.A', [0.0, 0.15],
                              state_home=home, reason='G4 单元测试')

    assert result['status'] == 'AMBIGUOUS'
    assert result['confidence'] == 'low'
    assert [candidate['value'] for candidate in result['candidates']] == [[0.0, 0.0], [0.0, 0.15]]
    assert all(candidate['key'] == 'intent.main.label.A' for candidate in result['candidates'])
    assert script.read_bytes() == before
    assert listing(tmp_path) == ['figure.py']


def test_plan_repeated_definition_is_ambiguous(tmp_path):
    script = write_script(tmp_path, REPEATED_DEFINITION_SCRIPT)
    home = tmp_path / 'state'

    result = plan_layout_edit(script, 'intent.main.label.A', [0.0, 0.15],
                              state_home=home, reason='G4 单元测试')

    assert result['status'] == 'AMBIGUOUS'
    assert result['confidence'] == 'low'
    assert len(result['candidates']) == 2
    assert not home.exists()


def test_plan_missing_binding_needs_authoring(tmp_path):
    script = write_script(tmp_path, BASE_SCRIPT)
    before = script.read_bytes()
    home = tmp_path / 'state'

    result = plan_layout_edit(script, 'intent.main.label.C', [0.0, 0.15],
                              state_home=home, reason='G4 单元测试')

    assert result['status'] == 'NEEDS_AUTHORING'
    assert result['confidence'] == 'low'
    assert result['candidates'] == []
    assert script.read_bytes() == before
    assert not home.exists()


def test_plan_non_numeric_literal_is_ambiguous(tmp_path):
    script = write_script(tmp_path, NON_NUMERIC_SCRIPT)
    home = tmp_path / 'state'

    result = plan_layout_edit(script, 'intent.main.label.A', [0.0, 0.15],
                              state_home=home, reason='G4 单元测试')

    assert result['status'] == 'AMBIGUOUS'
    assert result['confidence'] == 'low'
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['value'] is None
    assert result['candidates'][0]['text'] == '[0.0, DY]'
    assert not home.exists()


def test_plan_rejects_invalid_target_value(tmp_path):
    script = write_script(tmp_path, BASE_SCRIPT)
    before = script.read_bytes()
    home = tmp_path / 'state'

    for bad in ([0.0], [0.0, float('nan')], 'not-a-pair'):
        result = plan_layout_edit(script, 'intent.main.label.A', bad,
                                  state_home=home, reason='G4 单元测试')
        assert result['status'] == 'INVALID'
        assert result['candidates'] == []

    assert script.read_bytes() == before
    assert not home.exists()


# ------------------------------------------------------------------ 应用

def test_apply_requires_authorization(tmp_path):
    script = write_script(tmp_path, BASE_SCRIPT)
    before = script.read_bytes()
    home = tmp_path / 'state'
    plan = plan_layout_edit(script, 'intent.main.label.A', [-0.15, 0.0],
                            state_home=home, reason='G4 单元测试')
    journal_id = plan['journal']['id']

    refused = apply_planned_edit(journal_id, state_home=home, authorized=False)

    assert refused['status'] == 'UNAUTHORIZED'
    assert refused['journal_id'] == journal_id
    assert script.read_bytes() == before
    record = journal_record(home, journal_id)
    assert record['status'] == 'PREPARED'
    assert record['files'][0]['status'] == 'PENDING'


def test_apply_after_authorization_matches_before_and_after_blobs(tmp_path):
    script = write_script(tmp_path, BASE_SCRIPT)
    before = script.read_bytes()
    home = tmp_path / 'state'
    plan = plan_layout_edit(script, 'intent.main.label.A', [-0.15, 0.0],
                            state_home=home, reason='G4 单元测试')
    journal_id = plan['journal']['id']

    applied = apply_planned_edit(journal_id, state_home=home, authorized=True)

    assert applied['status'] == 'COMMITTED'
    assert applied['journal']['files'][0]['status'] == 'APPLIED'
    after = blob_bytes(home, plan['after_sha256'])
    assert after == BASE_SCRIPT.replace('"intent.main.label.A": [0.0, 0.0]',
                                        '"intent.main.label.A": [-0.15, 0.0]').encode('utf-8')
    assert blob_bytes(home, plan['before_sha256']) == before
    assert script.read_bytes() == after
    assert sha256_hex(script.read_bytes()) == plan['after_sha256']
    assert listing(tmp_path) == ['figure.py', 'state']
    assert locate_layout_literal(script.read_text(encoding='utf-8'),
                                 'intent.main.label.A')['value'] == [-0.15, 0.0]
    assert journal_record(home, journal_id)['status'] == 'COMMITTED'
