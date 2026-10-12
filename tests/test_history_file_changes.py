"""HistoryStore 的源码写入记录契约：``append_source_change`` / ``source_changes`` /
``file_changes``。

只测消费者可见的事实：source_change 检查点按时间顺序可读、payload 原样归档（含
blob 引用与 diff）、磁盘前置状态不符或 payload 形状非法时**拒绝**且 head 不动、
CAS 与 ``append`` 同一套（陈旧 ``expected_head`` => ``HistoryConflict``）、历史
从不写用户源码。全部文件落在 pytest 临时目录内。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.history import (  # noqa: E402
    HistoryConflict,
    HistoryError,
    HistoryStore,
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_workspace(tmp_path, name='figure'):
    """真实脚本/配置（仅作工作区身份）+ 一个被记录的源码文件与独立 state_home。"""
    source = tmp_path / f'{name}-src'
    source.mkdir()
    script = source / 'plot.py'
    script.write_text('# never executed by the store\n', encoding='utf-8')
    config = source / 'figure.yaml'
    config.write_text('dpi: 600\n', encoding='utf-8')
    target = source / 'theme.py'
    target.write_bytes(b'value = 1\n')
    return script, config, target, tmp_path / 'state'


def change_for(path: Path, before: bytes, after: bytes) -> dict:
    return {'path': str(path), 'before_sha256': sha256_hex(before),
            'after_sha256': sha256_hex(after), 'is_binary': False,
            'before_blob': 'blobs/sha256/' + sha256_hex(before)[:2] + '/' + sha256_hex(before),
            'after_blob': 'blobs/sha256/' + sha256_hex(after)[:2] + '/' + sha256_hex(after),
            'diff': f'--- a/{path.name}\n+++ b/{path.name}\n'}


def source_payload(*changes: dict) -> dict:
    return {'kind': 'source_change', 'file_changes': list(changes), 'reason': 'test'}


def expected_map(*pairs) -> dict:
    return {str(path): sha for path, sha in pairs}


def test_source_change_checkpoint_round_trips_and_reads_back(tmp_path):
    script, config, target, home = make_workspace(tmp_path)
    before, after = target.read_bytes(), b'value = 2\n'
    payload = source_payload(change_for(target, before, after))
    head_sha = sha256_hex(before)

    with HistoryStore(script, config, 'main', state_home=home) as store:
        record = store.append_source_change(
            payload, expected_head=None, expected_file_sha256=expected_map((target, head_sha)))
        assert record['kind'] == 'source_change'
        assert record['payload'] == payload  # blob 引用与 diff 原样归档
        assert record['parent_id'] is None
        assert [item['id'] for item in store.source_changes()] == [record['id']]
        assert store.file_changes(record['id']) == payload['file_changes']
        assert target.read_bytes() == before  # 历史记录源码，从不写源码

        second = store.append_source_change(
            source_payload(change_for(target, before, b'value = 3\n')),
            expected_head=record['id'], expected_file_sha256=expected_map((target, head_sha)))
        assert [item['id'] for item in store.source_changes()] == [record['id'], second['id']]
        assert store.head()['id'] == second['id']

    # 重启后证据逐字节可读
    with HistoryStore(script, config, 'main', state_home=home, read_only=True) as reopened:
        assert reopened.file_changes(second['id']) == second['payload']['file_changes']
        assert reopened.head()['id'] == second['id']


def test_source_change_stale_disk_is_rejected_and_head_unchanged(tmp_path):
    script, config, target, home = make_workspace(tmp_path)
    payload = source_payload(change_for(target, target.read_bytes(), b'value = 2\n'))
    with HistoryStore(script, config, 'main', state_home=home) as store:
        with pytest.raises(HistoryError) as error:
            store.append_source_change(
                payload, expected_head=None,
                expected_file_sha256=expected_map((target, sha256_hex(b'stale bytes'))))
        assert 'expected_file_sha256' in str(error.value)
        assert store.head() is None and store.source_changes() == []


def test_source_change_stale_expected_head_conflicts(tmp_path):
    script, config, target, home = make_workspace(tmp_path)
    payload = source_payload(change_for(target, target.read_bytes(), b'value = 2\n'))
    expected = expected_map((target, sha256_hex(target.read_bytes())))
    with HistoryStore(script, config, 'main', state_home=home) as store:
        store.append_source_change(payload, expected_head=None, expected_file_sha256=expected)
        with pytest.raises(HistoryConflict):
            store.append_source_change(payload, expected_head=None, expected_file_sha256=expected)


def test_source_change_rejects_bad_payload_without_writing(tmp_path):
    script, config, target, home = make_workspace(tmp_path)
    raw = target.read_bytes()
    good = change_for(target, raw, b'value = 2\n')
    digest = sha256_hex(raw)

    def mutate(**overrides) -> dict:
        item = dict(good)
        item.update(overrides)
        return item

    bad_shas = [dict(good, before_sha256='abc'), dict(good, after_sha256=None),
                dict(good, before_sha256='A' * 64)]
    cases = [
        ('kind 不符', {'kind': 'accept', 'file_changes': [good]}),
        ('缺 kind', {'file_changes': [good]}),
        ('file_changes 非列表', {'kind': 'source_change', 'file_changes': good}),
        ('file_changes 为空', {'kind': 'source_change', 'file_changes': []}),
        ('条目非对象', {'kind': 'source_change', 'file_changes': ['nope']}),
        ('缺 path', {'kind': 'source_change', 'file_changes': [mutate(path='')]}),
        ('缺 before_sha256', {'kind': 'source_change', 'file_changes': [mutate(before_sha256='')]}),
        ('before SHA 非 hex', {'kind': 'source_change', 'file_changes': [bad_shas[0]]}),
        ('after SHA 为 None', {'kind': 'source_change', 'file_changes': [bad_shas[1]]}),
        ('SHA 大写', {'kind': 'source_change', 'file_changes': [bad_shas[2]]}),
    ]
    with HistoryStore(script, config, 'main', state_home=home) as store:
        for label, payload in cases:
            with pytest.raises(HistoryError):
                store.append_source_change(payload, expected_head=None,
                                           expected_file_sha256=expected_map((target, digest)))
        for label, expected in [('非映射', [('k', digest)]),
                                ('缺覆盖', {}),
                                ('未知路径', expected_map((target, digest), (target.parent / 'x.py', digest))),
                                ('摘要非法', expected_map((target, 'not-a-sha'))),
                                ('键非法', {1: digest})]:
            with pytest.raises(HistoryError):
                store.append_source_change(source_payload(good), expected_head=None,
                                           expected_file_sha256=expected)
        assert store.head() is None and store.source_changes() == []
        assert target.read_bytes() == raw


def test_source_changes_excludes_other_kinds_and_file_changes_defaults_empty(tmp_path):
    script, config, target, home = make_workspace(tmp_path)
    with HistoryStore(script, config, 'main', state_home=home) as store:
        plain = store.append({'schema': 'test', 'kind': 'accept'}, expected_head=None,
                             kind='accept')
        change = store.append_source_change(
            source_payload(change_for(target, target.read_bytes(), b'value = 2\n')),
            expected_head=plain['id'],
            expected_file_sha256=expected_map((target, sha256_hex(target.read_bytes()))))
        assert [item['id'] for item in store.source_changes()] == [change['id']]
        assert store.file_changes(plain['id']) == []
        with pytest.raises(HistoryError):
            store.file_changes('not-a-checkpoint-id')
        with pytest.raises(HistoryError):
            store.file_changes('0' * 32)  # 合法形状但不存在
