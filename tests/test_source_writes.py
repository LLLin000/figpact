"""SourceWrite journal 契约：可恢复的多文件写入（不是崩溃原子性）。

只测消费者可见的事实：plan 只归档 before/after blob 与 PREPARED journal、绝不碰
目标文件；被外部改写的 before 哈希一律拒绝覆盖且不留任何新内容；apply 中途真实
失败（第二个目标被置只读、replace 报 PermissionError）时受控回滚到 before 字节；
目标在 plan 之后被外部换成目录则读拒绝、一个文件都不写；未完成 journal 的恢复只按磁盘实际
内容判定 before/after/third_party 且绝不自动覆盖第三方；`restore_project` 把历史
after 内容作为**新的前向写入**落盘而不改写原历史 journal；二进制文件只记 blob、
`diff` 为 None。全部使用真实临时目录与真实文件，不 mock 文件系统。
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.source_writes import (  # noqa: E402
    FileChange,
    SourceWriteError,
    apply_source_change,
    plan_source_change,
    recover_pending,
    restore_project,
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_source(tmp_path, name, content: bytes) -> Path:
    root = tmp_path / f'{name}-src'
    root.mkdir(exist_ok=True)
    path = root / name
    path.write_bytes(content)
    return path


def change_for(path: Path, after: bytes) -> FileChange:
    """真实文件当前的字节就是 before（apply 前的世界状态）。"""
    return FileChange(path=path, before_sha256=sha256_hex(path.read_bytes()), after_bytes=after)


def journals_dir(home: Path) -> Path:
    return home / 'source-journals'


def journal_file(home: Path, journal_id: str) -> Path:
    return journals_dir(home) / f'{journal_id}.json'


def read_journal(home: Path, journal_id: str) -> dict:
    return json.loads(journal_file(home, journal_id).read_text(encoding='utf-8'))


def blob_path(home: Path, digest: str) -> Path:
    return home / 'blobs' / 'sha256' / digest[:2] / digest


def entry_for(journal: dict, path: Path) -> dict:
    for entry in journal['files']:
        if Path(entry['path']).resolve() == Path(path).resolve():
            return entry
    raise AssertionError(f'journal has no entry for {path}: {journal["files"]!r}')


def files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob('*') if p.is_file()] if root.exists() else []


def temp_leftovers(roots) -> list[Path]:
    return [p for root in roots for p in root.rglob('*.figpact-tmp-*')]


def _files_list(entry: dict) -> list[dict]:
    for value in entry.values():
        if (isinstance(value, list) and value and all(isinstance(v, dict) for v in value)
                and any('path' in v for v in value)):
            return value
    raise AssertionError(f'recovery entry has no per-file list: {entry!r}')


def _journal_id(entry: dict) -> str:
    for key in ('id', 'journal_id'):
        if isinstance(entry.get(key), str):
            return entry[key]
    raise AssertionError(f'recovery entry has no journal id: {entry!r}')


def _verdict(file_entry: dict) -> str:
    for key in ('verdict', 'status', 'state', 'disk_state', 'result'):
        value = file_entry.get(key)
        if isinstance(value, str) and value.lower() in ('before', 'after', 'third_party'):
            return value.lower()
    for value in file_entry.values():
        if isinstance(value, str) and value.lower() in ('before', 'after', 'third_party'):
            return value.lower()
    raise AssertionError(f'file entry has no before/after/third_party verdict: {file_entry!r}')


def test_plan_then_apply_writes_files_and_commits_journal(tmp_path):
    home = tmp_path / 'state'
    script = make_source(tmp_path, 'plot.py', b'ax.text(0, 0, "a")\n')
    config = make_source(tmp_path, 'figure.yaml', b'dpi: 600\n')
    after = {script: b'ax.text(0, 1, "a")\n', config: b'dpi: 900\n'}
    before = {path: path.read_bytes() for path in (script, config)}

    journal = plan_source_change(
        [change_for(script, after[script]), change_for(config, after[config])],
        state_home=home, reason='nudge label',
    )

    assert set(journal) >= {'id', 'status', 'created_at', 'reason', 'files'}
    assert journal['status'] == 'PREPARED'
    assert journal['reason'] == 'nudge label'
    assert datetime.fromisoformat(journal['created_at']).tzinfo is not None
    assert read_journal(home, journal['id'])['status'] == 'PREPARED'

    for path in (script, config):
        entry = entry_for(journal, path)
        assert entry['status'] == 'PENDING'
        assert entry['is_binary'] is False
        assert entry['before_sha256'] == sha256_hex(before[path])
        assert entry['after_sha256'] == sha256_hex(after[path])
        assert '--- a/' in entry['diff'] and '+++ b/' in entry['diff']
        assert path.name in entry['diff']
        assert entry['before_sha256'] in str(entry['before_blob'])
        assert entry['after_sha256'] in str(entry['after_blob'])
        assert blob_path(home, entry['before_sha256']).read_bytes() == before[path]
        assert blob_path(home, entry['after_sha256']).read_bytes() == after[path]
        assert path.read_bytes() == before[path]  # plan 阶段不碰目标文件

    applied = apply_source_change(journal['id'], state_home=home)

    assert applied['status'] == 'COMMITTED'
    assert read_journal(home, journal['id'])['status'] == 'COMMITTED'
    for path in (script, config):
        assert path.read_bytes() == after[path]
        entry = entry_for(applied, path)
        assert entry['status'] == 'APPLIED'
        assert sha256_hex(path.read_bytes()) == entry['after_sha256']
    assert temp_leftovers([script.parent, config.parent]) == []


def test_stale_before_rejects_without_touching_disk_or_journal(tmp_path):
    home = tmp_path / 'state'
    script = make_source(tmp_path, 'plot.py', b'ax.text(0, 0, "a")\n')
    config = make_source(tmp_path, 'figure.yaml', b'dpi: 600\n')
    before = {path: path.read_bytes() for path in (script, config)}
    stale = FileChange(
        path=script,
        before_sha256=sha256_hex(b'a version that is no longer on disk\n'),
        after_bytes=b'ax.text(0, 1, "a")\n',
    )

    with pytest.raises(SourceWriteError) as excinfo:
        plan_source_change([stale, change_for(config, b'dpi: 900\n')],
                           state_home=home, reason='lost the race with an external edit')

    assert isinstance(excinfo.value, RuntimeError)
    assert 'STALE_SOURCE' in str(excinfo.value)
    for path, data in before.items():
        assert path.read_bytes() == data
    assert not journals_dir(home).exists() or list(journals_dir(home).glob('*.json')) == []
    assert files_under(home / 'blobs') == []
    assert temp_leftovers([script.parent, config.parent]) == []


def test_mid_apply_failure_rolls_back_already_applied_files(tmp_path):
    home = tmp_path / 'state'
    first = make_source(tmp_path, 'a.txt', b'first before\n')
    second = make_source(tmp_path, 'b.txt', b'second before\n')
    first_before, second_before = first.read_bytes(), second.read_bytes()
    journal = plan_source_change(
        [change_for(first, b'first after\n'), change_for(second, b'second after\n')],
        state_home=home, reason='two file write',
    )

    # 真实故障注入：plan 之后把第二个目标置为只读，os.replace 在 Windows 上必然
    # PermissionError —— 失败点落在"第一个文件已 APPLIED、轮到第二个"的中间阶段。
    os.chmod(second, stat.S_IREAD)
    try:
        result = apply_source_change(journal['id'], state_home=home)
    finally:
        os.chmod(second, stat.S_IWRITE)  # 恢复可写，别让只读残留卡住 tmp_path 清理

    assert result['status'] == 'ROLLED_BACK'
    assert read_journal(home, journal['id'])['status'] == 'ROLLED_BACK'
    assert 'b.txt' in result['failure']  # 失败确实发生在第二个文件的写入/替换阶段
    assert first.read_bytes() == first_before
    assert sha256_hex(first.read_bytes()) == entry_for(journal, first)['before_sha256']
    assert second.read_bytes() == second_before  # 第二个既没被改写也没被删除
    assert temp_leftovers([first.parent, second.parent]) == []


def test_target_replaced_by_directory_is_rejected_as_external_rewrite(tmp_path):
    home = tmp_path / 'state'
    first = make_source(tmp_path, 'a.txt', b'first before\n')
    second = make_source(tmp_path, 'b.txt', b'second before\n')
    first_before = first.read_bytes()
    journal = plan_source_change(
        [change_for(first, b'first after\n'), change_for(second, b'second after\n')],
        state_home=home, reason='external rewrite before apply',
    )

    # 外部改写：plan 之后目标被换成了目录（读都读不了），apply 必须先拒绝覆盖。
    second.unlink()
    second.mkdir()
    occupant = second / 'occupant.txt'
    occupant.write_text('blocking\n', encoding='utf-8')

    with pytest.raises(SourceWriteError) as excinfo:
        apply_source_change(journal['id'], state_home=home)

    message = str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)
    # Windows 上读目录直接 PermissionError（Errno 13），走的是读取阶段拒绝覆盖、
    # 到不了哈希比较的 STALE_SOURCE 分支；结果同样是一个文件都不写。
    assert '无法读取磁盘内容' in message
    assert 'b.txt' in message
    assert first.read_bytes() == first_before
    assert second.is_dir()
    assert occupant.read_text(encoding='utf-8') == 'blocking\n'
    assert temp_leftovers([first.parent, second.parent]) == []


def test_recover_pending_classifies_before_after_third_party_without_overwriting(tmp_path):
    home = tmp_path / 'state'
    left = make_source(tmp_path, 'left.txt', b'left before\n')
    middle = make_source(tmp_path, 'middle.txt', b'middle before\n')
    right = make_source(tmp_path, 'right.txt', b'right before\n')
    journal = plan_source_change(
        [change_for(left, b'left after\n'),
         change_for(middle, b'middle after\n'),
         change_for(right, b'right after\n')],
        state_home=home, reason='crash injection',
    )
    journal_text = journal_file(home, journal['id']).read_text(encoding='utf-8')

    # 三种真实磁盘状态：未写 / 已写 / 第三方改写
    middle.write_bytes(b'middle after\n')
    right.write_bytes(b'right third party\n')

    report = recover_pending(home)

    assert len(report) == 1
    entry = report[0]
    assert _journal_id(entry) == journal['id']
    assert entry.get('reason') == 'crash injection'
    verdicts = {Path(f['path']).name: _verdict(f) for f in _files_list(entry)}
    assert verdicts == {'left.txt': 'before', 'middle.txt': 'after', 'right.txt': 'third_party'}
    assert right.read_bytes() == b'right third party\n'  # 第三方内容绝不被覆盖
    assert left.read_bytes() == b'left before\n'
    assert middle.read_bytes() == b'middle after\n'
    report_file = journals_dir(home) / f"{journal['id']}.recovery.json"
    assert report_file.exists()
    assert 'third_party' in report_file.read_text(encoding='utf-8')
    assert journal_file(home, journal['id']).read_text(encoding='utf-8') == journal_text


def test_restore_project_writes_historical_after_bytes_as_new_forward_journal(tmp_path):
    home = tmp_path / 'state'
    script = make_source(tmp_path, 'plot.py', b'ax.text(0, 0, "a")\n')
    historical_after = b'ax.text(0, 1, "a")\n'
    history_journal = plan_source_change([change_for(script, historical_after)],
                                         state_home=home, reason='original edit')
    history_record = dict(entry_for(history_journal, script))
    history_file = journal_file(home, history_journal['id'])
    history_text = history_file.read_text(encoding='utf-8')

    # 历史之后源码被独立推进到第三个版本（与历史 before/after 都不同）
    current = b'ax.text(0, 5, "a")\n'
    script.write_bytes(current)

    journal = restore_project([history_record], state_home=home, reason='restore to commit X')

    assert journal['id'] != history_journal['id']
    assert journal['status'] == 'COMMITTED'
    assert read_journal(home, journal['id'])['status'] == 'COMMITTED'
    assert script.read_bytes() == historical_after
    restored = entry_for(journal, script)
    assert restored['before_sha256'] == sha256_hex(current)  # 以当前磁盘为 before：前向写入
    assert restored['after_sha256'] == sha256_hex(historical_after)
    assert history_file.read_text(encoding='utf-8') == history_text  # 原历史 journal 不被改写
    assert json.loads(history_text)['status'] == 'PREPARED'


def test_binary_change_records_no_diff_and_blobs_round_trip(tmp_path):
    home = tmp_path / 'state'
    before_bytes = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) + b'before'
    after_bytes = b'\x89PNG\r\n\x1a\n' + bytes(range(255, -1, -1)) + b'after'
    image = make_source(tmp_path, 'logo.png', before_bytes)
    text = make_source(tmp_path, 'notes.txt', b'note v1\n')

    journal = plan_source_change(
        [FileChange(path=image, before_sha256=sha256_hex(before_bytes), after_bytes=after_bytes),
         change_for(text, b'note v2\n')],
        state_home=home, reason='binary payload',
    )

    binary = entry_for(journal, image)
    assert binary['is_binary'] is True
    assert binary['diff'] is None
    assert blob_path(home, binary['before_sha256']).read_bytes() == before_bytes
    assert blob_path(home, binary['after_sha256']).read_bytes() == after_bytes
    text_entry = entry_for(journal, text)
    assert text_entry['is_binary'] is False
    assert text_entry['diff'] is not None

    applied = apply_source_change(journal['id'], state_home=home)

    assert applied['status'] == 'COMMITTED'
    assert image.read_bytes() == after_bytes
    assert text.read_bytes() == b'note v2\n'
