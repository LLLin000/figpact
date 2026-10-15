#!/usr/bin/env python3
"""G7-B 保存闭环：权限保持 + 漂移拒绝 + 多文件回执语义回归。"""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact import source_writes


def test_permission_preserved(tmp_path=None):
    d = Path(tempfile.mkdtemp())
    p = d / 'target.txt'
    p.write_text('hello', encoding='utf-8')
    os.chmod(p, 0o644)
    before = stat.S_IMODE(os.stat(p).st_mode)
    home = d / 'state'
    changes = [source_writes.FileChange(str(p), hashlib.sha256(b'hello').hexdigest(), b'world')]
    jr = source_writes.plan_source_change(changes, state_home=home, reason='perm')
    source_writes.apply_source_change(jr['id'], state_home=home)
    after = stat.S_IMODE(os.stat(p).st_mode)
    assert before == after, (oct(before), oct(after))
    assert p.read_text(encoding='utf-8') == 'world'


def test_drift_refusal():
    d = Path(tempfile.mkdtemp())
    p = d / 'target.txt'
    p.write_text('hello', encoding='utf-8')
    home = d / 'state'
    original = p.read_bytes()
    changes = [source_writes.FileChange(str(p), hashlib.sha256(b'hello').hexdigest(), b'world')]
    jr = source_writes.plan_source_change(changes, state_home=home, reason='drift')
    p.write_text('external-change', encoding='utf-8')
    try:
        source_writes.apply_source_change(jr['id'], state_home=home)
    except source_writes.SourceWriteError as e:
        assert 'STALE_SOURCE' in str(e)
    else:
        raise AssertionError('应拒绝漂移')
    assert p.read_bytes() == b'external-change'
    # restore for cleanliness
    p.write_bytes(original)


def test_multi_file_receipt_is_per_file():
    d = Path(tempfile.mkdtemp())
    a = d / 'a.txt'
    b = d / 'b.txt'
    a.write_text('a', encoding='utf-8')
    b.write_text('b', encoding='utf-8')
    home = d / 'state'
    changes = [
        source_writes.FileChange(str(a), hashlib.sha256(b'a').hexdigest(), b'A'),
        source_writes.FileChange(str(b), hashlib.sha256(b'b').hexdigest(), b'B'),
    ]
    jr = source_writes.plan_source_change(changes, state_home=home, reason='multi')
    applied = source_writes.apply_source_change(jr['id'], state_home=home)
    assert applied['status'] == 'COMMITTED'
    assert all(e['status'] == 'APPLIED' for e in applied['files'])


if __name__ == '__main__':
    test_permission_preserved()
    test_drift_refusal()
    test_multi_file_receipt_is_per_file()
    print('save_loop: ok')