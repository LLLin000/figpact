"""HistoryStore 持久化契约：内容寻址 blob + SQLite CAS 线性检查点。

只测消费者可见的事实：工作区身份（路径+scope，非内容）、head CAS 冲突、真实
子进程在 blob 持久化后、元数据提交前被硬杀（孤儿 blob 不授权任何变更）、blob
篡改/缺失/数据库与血缘损坏一律 fail closed 且不静默重建、重启后旧证据逐字节
可读、源码目录一字节不改。全部文件落在 pytest 临时目录内，不渲染、不执行绘图
脚本。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.history import (  # noqa: E402
    HistoryConflict,
    HistoryCorrupt,
    HistoryError,
    HistoryStore,
)

def make_workspace(tmp_path, name='figure'):
    """真实脚本/配置（内容会主动终止进程，证明存储从不执行它们）+ 一个 scope 名。"""
    source = tmp_path / f'{name}-src'
    source.mkdir()
    script = source / 'plot.py'
    script.write_text('raise SystemExit("plot script must never be executed by the store")\n',
                      encoding='utf-8')
    config = source / 'figure.yaml'
    config.write_text('dpi: 600\n', encoding='utf-8')
    return script, config, 'main'


def canonical(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_store(script, config, scope, home):
    return HistoryStore(script, config, scope, state_home=home)


def blob_path(store, record) -> Path:
    return store.directory / 'blobs' / record['payload_sha256']


def run_child(runner: Path, args):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT)
    env['MPLBACKEND'] = 'Agg'
    return subprocess.run([sys.executable, str(runner), *[str(a) for a in args]],
                          capture_output=True, text=True, env=env,
                          cwd=str(ROOT), timeout=180)


def run_cli(*args):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT)
    env['MPLBACKEND'] = 'Agg'
    return subprocess.run([sys.executable, '-m', 'figpact.history', *args],
                          capture_output=True, text=True, env=env,
                          cwd=str(ROOT), timeout=180)


def write_runner(tmp_path, name, body) -> Path:
    runner = tmp_path / name
    runner.write_text(body, encoding='utf-8')
    return runner


CRASH_APPEND_RUNNER = '''
import json
import os
import signal
import sys
from pathlib import Path

from figpact.history import HistoryStore

script, config, scope, home, expected, payload_text = sys.argv[1:7]
original_replace = os.replace
def stop_after_blob_replace(source, destination):
    original_replace(source, destination)
    if Path(destination).parent.name == 'blobs':
        os.kill(os.getpid(), getattr(signal, 'SIGKILL', signal.SIGTERM))
os.replace = stop_after_blob_replace
store = HistoryStore(script, config, scope, state_home=home)
store.append(json.loads(payload_text),
             expected_head=None if expected == 'None' else expected,
             kind='killed-writer')
store.close()
'''

PLAIN_APPEND_RUNNER = '''
import json
import sys

from figpact.history import HistoryStore

script, config, scope, home, payload_text = sys.argv[1:6]
store = HistoryStore(script, config, scope, state_home=home)
record = store.append(json.loads(payload_text), expected_head=None, kind='accept')
store.close()
print(record['id'])
'''


def test_workspace_identity_uses_paths_and_scope_not_source_bytes(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    store = open_store(script, config, scope, home)
    first_id, first_dir = store.workspace_id, store.directory
    assert first_dir == home.resolve() / 'workspaces' / first_id[:2] / first_id
    config_bytes = config.read_bytes()
    store.close()

    # 源码字节变化不改变工作区身份（身份来自路径+scope，不是源码版本）
    script.write_text('# rewritten in place, same identity\n', encoding='utf-8')
    rewritten = open_store(script, config, scope, home)
    assert rewritten.workspace_id == first_id
    assert rewritten.directory == first_dir
    rewritten.close()

    other_scope = open_store(script, config, 'annotation', home)
    assert other_scope.workspace_id != first_id
    other_scope.close()

    other_script, other_config, _ = make_workspace(tmp_path, name='other')
    other_source = open_store(other_script, other_config, scope, home)
    assert other_source.workspace_id != first_id
    other_source.close()

    same_config = open_store(other_script, config, scope, home)
    assert same_config.workspace_id != first_id
    same_config.close()

    assert config.read_bytes() == config_bytes


def test_source_directories_and_engine_tree_state_are_rejected_before_mkdir(tmp_path):
    home = tmp_path / 'state'
    script, config, scope = make_workspace(tmp_path)
    with pytest.raises(HistoryError):
        HistoryStore(tmp_path, config, scope, state_home=home)
    with pytest.raises(HistoryError):
        HistoryStore(script, tmp_path, scope, state_home=home)
    engine_state = ROOT / 'figpact' / 'state-home'
    with pytest.raises(HistoryError):
        HistoryStore(script, config, scope, state_home=engine_state)
    assert not home.exists()
    assert not engine_state.exists()


def test_default_state_home_honors_figpact_state_home(monkeypatch, tmp_path):
    monkeypatch.delenv('FIGPACT_STATE_HOME', raising=False)
    script, config, scope = make_workspace(tmp_path)
    env_home = tmp_path / 'env-home'
    monkeypatch.setenv('FIGPACT_STATE_HOME', str(env_home))
    store = HistoryStore(str(script), str(config), scope)
    assert env_home.resolve() in store.directory.parents
    record = store.append({'operation': 'accept-1'}, expected_head=None, kind='accept')
    store.close()
    reopened = HistoryStore(str(script), str(config), scope)
    assert reopened.head() == record
    reopened.close()


def test_append_chain_cas_and_stale_head_conflict(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    store = open_store(script, config, scope, tmp_path / 'state')
    payload = {'operation': 'op-1', 'delta_mm': [0.0, 2.5], 'scene_revision': 'rev-1'}
    first = store.append(payload, expected_head=None, kind='accept')
    assert set(first) == {'id', 'parent_id', 'kind', 'created_at', 'payload_sha256', 'payload'}
    assert first['parent_id'] is None
    assert first['kind'] == 'accept'
    assert first['payload'] == payload
    assert first['payload_sha256'] == sha256_hex(canonical(payload))
    assert blob_path(store, first).read_bytes() == canonical(payload)
    assert store.head() == first
    assert store.get(first['id']) == first
    assert store.checkpoints() == [first]

    second = store.append({'operation': 'op-2'}, expected_head=first['id'], kind='undo')
    assert second['parent_id'] == first['id']
    assert store.checkpoints() == [first, second]
    assert store.head() == second

    with pytest.raises(HistoryConflict):
        store.append({'operation': 'stale'}, expected_head=first['id'], kind='accept')
    assert store.head() == second
    assert store.checkpoints() == [first, second]
    assert store.get(second['id']) == second
    store.close()


def test_empty_store_head_is_none_and_writes_fail_closed(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    store = open_store(script, config, scope, tmp_path / 'state')
    assert store.head() is None
    assert store.checkpoints() == []
    with pytest.raises(HistoryConflict):
        store.append({'n': 1}, expected_head='0' * 32, kind='accept')
    with pytest.raises(HistoryError):
        store.get('0' * 32)
    assert store.head() is None
    assert store.checkpoints() == []
    assert list((store.directory / 'blobs').iterdir()) == []
    store.close()


def test_two_sessions_of_same_identity_conflict_and_chain(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    writer = open_store(script, config, scope, home)
    first = writer.append({'n': 1}, expected_head=None, kind='accept')

    other = open_store(script, config, scope, home)
    with pytest.raises(HistoryConflict):
        other.append({'n': 2}, expected_head=None, kind='accept')
    assert other.head() == first
    assert other.checkpoints() == [first]

    chained = other.append({'n': 3}, expected_head=first['id'], kind='accept')
    assert chained['parent_id'] == first['id']
    assert writer.head() == chained
    writer.close()
    other.close()


def test_multi_process_stale_head_conflict(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    runner = write_runner(tmp_path, 'append_once.py', PLAIN_APPEND_RUNNER)

    first_run = run_child(runner, [script, config, scope, home, json.dumps({'writer': 'a'})])
    assert first_run.returncode == 0, first_run.stderr
    first_id = first_run.stdout.strip().splitlines()[-1]
    assert len(first_id) == 32

    second_run = run_child(runner, [script, config, scope, home, json.dumps({'writer': 'b'})])
    assert second_run.returncode != 0
    assert 'conflict' in (second_run.stderr + second_run.stdout).lower()

    store = open_store(script, config, scope, home)
    assert store.head()['id'] == first_id
    assert len(store.checkpoints()) == 1

    recovered = run_child(runner, [script, config, scope, home, json.dumps({'writer': 'c'})])
    assert recovered.returncode != 0  # still expected_head=None

    chained = store.append({'writer': 'in-process'}, expected_head=first_id, kind='accept')
    assert chained['parent_id'] == first_id
    assert store.head() == chained
    store.close()


def test_killed_writer_before_head_commit_keeps_old_state(tmp_path):
    """真正硬杀：blob 已 fsync、head 未提交；孤儿 blob 不授权、也不阻断后续写者。"""
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    runner = write_runner(tmp_path, 'crash_append.py', CRASH_APPEND_RUNNER)

    killed = run_child(runner, [script, config, scope, home, 'None', json.dumps({'trial': 'first'})])
    assert killed.returncode != 0

    store = open_store(script, config, scope, home)
    assert store.head() is None
    assert store.checkpoints() == []
    orphan = store.directory / 'blobs' / sha256_hex(canonical({'trial': 'first'}))
    assert orphan.read_bytes() == canonical({'trial': 'first'})
    assert list((store.directory / 'blobs').iterdir()) == [orphan]
    store.close()

    recovered = open_store(script, config, scope, home)
    good = recovered.append({'trial': 'after-crash'}, expected_head=None, kind='accept')
    assert recovered.head() == good
    assert len(recovered.checkpoints()) == 1

    killed_again = run_child(runner, [script, config, scope, home, good['id'],
                                     json.dumps({'trial': 'second'})])
    assert killed_again.returncode != 0
    assert recovered.head() == good
    assert len(recovered.checkpoints()) == 1
    orphan_two = recovered.directory / 'blobs' / sha256_hex(canonical({'trial': 'second'}))
    assert orphan_two.read_bytes() == canonical({'trial': 'second'})
    recovered.close()


def test_corrupt_blob_fails_closed_without_resetting_history(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    store = open_store(script, config, scope, tmp_path / 'state')
    first = store.append({'v': 1}, expected_head=None, kind='accept')
    second = store.append({'v': 2}, expected_head=first['id'], kind='accept')
    store.close()

    tampered = blob_path(store, second)
    tampered.write_bytes(tampered.read_bytes()[:-1] + b'X')

    reopened = open_store(script, config, scope, tmp_path / 'state')
    with pytest.raises(HistoryCorrupt):
        reopened.head()
    with pytest.raises(HistoryCorrupt):
        reopened.checkpoints()
    with pytest.raises(HistoryCorrupt):
        reopened.get(second['id'])
    with pytest.raises(HistoryCorrupt):
        reopened.append({'v': 3}, expected_head=second['id'], kind='accept')
    rows = sqlite3.connect(reopened.directory / 'history.sqlite3').execute(
        'SELECT COUNT(*) FROM checkpoints').fetchone()[0]
    assert rows == 2
    assert tampered.read_bytes().endswith(b'X')
    reopened.close()

    tampered.unlink()
    missing = open_store(script, config, scope, tmp_path / 'state')
    with pytest.raises(HistoryCorrupt):
        missing.get(second['id'])
    with pytest.raises(HistoryCorrupt):
        missing.head()
    missing.close()


def test_broken_lineage_fails_closed(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    store = open_store(script, config, scope, home)
    first = store.append({'n': 1}, expected_head=None, kind='accept')
    second = store.append({'n': 2}, expected_head=first['id'], kind='accept')
    store.close()

    conn = sqlite3.connect(store.directory / 'history.sqlite3')
    conn.execute('UPDATE checkpoints SET parent_id=? WHERE id=?', ('ab' * 16, second['id']))
    conn.commit()
    conn.close()
    with pytest.raises(HistoryCorrupt):
        open_store(script, config, scope, home)


def test_head_pointer_tamper_fails_closed(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    store = open_store(script, config, scope, home)
    store.append({'n': 1}, expected_head=None, kind='accept')
    store.close()

    conn = sqlite3.connect(store.directory / 'history.sqlite3')
    conn.execute("UPDATE meta SET value=? WHERE key='head'", ('cd' * 16,))
    conn.commit()
    conn.close()
    with pytest.raises(HistoryCorrupt):
        open_store(script, config, scope, home)


def test_deleted_head_pointer_fails_closed(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    store = open_store(script, config, scope, home)
    store.append({'n': 1}, expected_head=None, kind='accept')
    store.close()

    conn = sqlite3.connect(store.directory / 'history.sqlite3')
    conn.execute("DELETE FROM meta WHERE key='head'")
    conn.commit()
    conn.close()
    with pytest.raises(HistoryCorrupt):
        open_store(script, config, scope, home)


def test_garbage_or_foreign_database_never_silently_reinitializes(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    store = open_store(script, config, scope, home)
    store.append({'v': 1}, expected_head=None, kind='accept')
    db = store.directory / 'history.sqlite3'
    store.close()

    db.write_bytes(b'this is definitely not a sqlite database')
    with pytest.raises(HistoryCorrupt):
        open_store(script, config, scope, home)
    assert db.read_bytes().startswith(b'this is definitely not')

    foreign = tmp_path / 'foreign.sqlite3'
    conn = sqlite3.connect(foreign)
    conn.execute('CREATE TABLE other(x)')
    conn.commit()
    conn.close()
    home_two = tmp_path / 'state-two'
    other = open_store(script, config, scope, home_two)
    other.close()
    other.directory.joinpath('history.sqlite3').write_bytes(foreign.read_bytes())
    with pytest.raises(HistoryCorrupt):
        open_store(script, config, scope, home_two)


def test_payload_and_kind_validation_reject_non_strict_json(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    store = open_store(script, config, scope, tmp_path / 'state')
    for bad in ([1, 2], 'text', None, 5, True,
                {'a': (1, 2)}, {'a': float('nan')}, {'a': float('inf')},
                {1: 'int-key'}, {'a': {0: 'nested-int-key'}}, {'a': {1, 2}}):
        with pytest.raises(HistoryError):
            store.append(bad, expected_head=None, kind='accept')
    for bad_kind in ('', None, 7):
        with pytest.raises(HistoryError):
            store.append({'ok': 1}, expected_head=None, kind=bad_kind)
    for bad_head in ('', 7, [], 'not-hex'):
        with pytest.raises(HistoryError):
            store.append({'ok': 1}, expected_head=bad_head, kind='accept')
    assert store.head() is None
    assert list((store.directory / 'blobs').iterdir()) == []
    store.close()


def test_payload_round_trip_is_exact_strict_json(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    store = open_store(script, config, scope, tmp_path / 'state')
    payload = {'scene': {'gid': 'fig1.main.curve', 'delta_mm': [0.0, -1.25]},
               'science': {'sha256': 'ab' * 32, 'label': '中文 °C',
                           'kept': True, 'dropped': None},
               'nested': [[1, 2], {'deep': [0.5]}]}
    record = store.append(payload, expected_head=None, kind='evidence')
    assert record['payload'] == payload
    assert blob_path(store, record).read_bytes() == canonical(payload)
    assert record['payload_sha256'] == sha256_hex(canonical(payload))
    store.close()

    reopened = open_store(script, config, scope, tmp_path / 'state')
    assert reopened.get(record['id']) == record
    assert reopened.head() == record
    reopened.close()


def test_identical_payload_shares_one_immutable_blob(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    store = open_store(script, config, scope, tmp_path / 'state')
    first = store.append({'same': True}, expected_head=None, kind='accept')
    digest = blob_path(store, first).read_bytes()
    second = store.append({'same': True}, expected_head=first['id'], kind='accept')
    assert second['payload_sha256'] == first['payload_sha256']
    blobs = sorted((store.directory / 'blobs').iterdir())
    assert [path.name for path in blobs] == [first['payload_sha256']]
    assert blobs[0].read_bytes() == digest
    assert [record['id'] for record in store.checkpoints()] == [first['id'], second['id']]
    store.close()


def test_restart_reads_exact_records_and_close_is_idempotent(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    store = open_store(script, config, scope, home)
    first = store.append({'step': 1}, expected_head=None, kind='accept')
    second = store.append({'step': 2}, expected_head=first['id'], kind='accept')
    third = store.append({'step': 3}, expected_head=second['id'], kind='undo')
    store.close()
    store.close()
    with pytest.raises(HistoryError):
        store.head()

    reopened = open_store(script, config, scope, home)
    assert reopened.checkpoints() == [first, second, third]
    assert reopened.head() == third
    assert reopened.get(second['id']) == second
    assert [record['parent_id'] for record in reopened.checkpoints()] == [None, first['id'], second['id']]
    reopened.close()

    with open_store(script, config, scope, home) as context:
        fourth = context.append({'step': 4}, expected_head=third['id'], kind='accept')
        assert fourth['parent_id'] == third['id']
        assert context.head() == fourth
    with pytest.raises(HistoryError):
        context.checkpoints()


def test_store_never_modifies_source_tree(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    before = {path.name: path.read_bytes() for path in script.parent.iterdir()}
    script_bytes, config_bytes = script.read_bytes(), config.read_bytes()

    store = open_store(script, config, scope, home)
    store.append({'x': 1}, expected_head=None, kind='accept')
    store.append({'x': 2}, expected_head=store.head()['id'], kind='accept')
    store.close()

    after = {path.name: path.read_bytes() for path in script.parent.iterdir()}
    assert after == before
    assert script.read_bytes() == script_bytes
    assert config.read_bytes() == config_bytes
    assert home.resolve() in store.directory.parents


def test_module_cli_lists_and_shows_without_executing_plot_script(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    store = open_store(script, config, scope, home)
    first = store.append({'op': 'accept-1'}, expected_head=None, kind='accept')
    store.append({'op': 'undo-1'}, expected_head=first['id'], kind='undo')
    store.close()

    base = ['--script', str(script), '--config', str(config),
            '--scope', scope, '--state-home', str(home)]

    listed = run_cli('list', *base)
    assert listed.returncode == 0, listed.stderr
    assert first['id'] in listed.stdout
    assert 'accept' in listed.stdout and 'undo' in listed.stdout

    shown = run_cli('show', *base, '--id', first['id'])
    assert shown.returncode == 0, shown.stderr
    record = json.loads(shown.stdout)
    assert record['id'] == first['id']
    assert record['payload'] == {'op': 'accept-1'}

    missing = run_cli('show', *base, '--id', 'ff' * 32)
    assert missing.returncode != 0
    assert missing.stderr.strip()

    empty = run_cli('list', '--script', str(script), '--config', str(config),
                    '--scope', 'annotation', '--state-home', str(home))
    assert empty.returncode == 0, empty.stderr


def test_state_home_inside_either_source_directory_is_refused_before_writing(tmp_path):
    script, _, scope = make_workspace(tmp_path)
    other = tmp_path / 'separate-config'
    other.mkdir()
    config = other / 'config.yaml'
    config.write_text('protected: true\n', encoding='utf8')
    before = {p: p.read_bytes() for p in (script, config)}
    for directory in (script.parent, config.parent):
        home = directory / 'history-state'
        with pytest.raises(HistoryError):
            HistoryStore(script, config, scope, state_home=home)
        assert not home.exists()
    assert all(p.read_bytes() == data for p, data in before.items())


def test_existing_history_database_hardlink_never_modifies_protected_file(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    with open_store(script, config, scope, home) as store:
        directory = store.directory
        first = store.append({'protected': 1}, expected_head=None, kind='accept')
    db = directory / 'history.sqlite3'
    protected = script.parent / 'protected_snapshot.sqlite3'
    protected.write_bytes(db.read_bytes())
    original = protected.read_bytes()
    db.unlink()
    os.link(protected, db)
    with pytest.raises(HistoryError):
        open_store(script, config, scope, home)
    assert protected.read_bytes() == original


def test_read_only_cli_missing_history_creates_no_state_files(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'never-created'
    outcome = run_cli('list', '--script', str(script), '--config', str(config),
                      '--scope', scope, '--state-home', str(home))
    assert outcome.returncode == 0, outcome.stderr
    assert not home.exists()


def test_unsupported_existing_schema_is_not_silently_opened(tmp_path):
    script, config, scope = make_workspace(tmp_path)
    home = tmp_path / 'state'
    with open_store(script, config, scope, home) as store:
        directory = store.directory
        store.append({'accepted': True}, expected_head=None, kind='accept')
    db = directory / 'history.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE meta SET value='unsupported' WHERE key='schema_version'")
    before = db.read_bytes()
    with pytest.raises(HistoryCorrupt):
        open_store(script, config, scope, home)
    assert db.read_bytes() == before
