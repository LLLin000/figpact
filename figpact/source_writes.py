"""figpact 源码/配置的可恢复多文件写入（G3b）。

正式表述是**可恢复的多文件写入**，不是"进程崩溃时多个源文件原子提交"：
PREPARED journal + before/after 内容寻址 blob 让任意时刻的中断都能从磁盘实际
SHA 判定每个文件处在 before / after / 第三方状态，并据此恢复或拒绝覆盖。

状态与 blob 一律落在 ``state_home``（在源码目录之外，D-10）：blob 写
``<state_home>/blobs/sha256/<digest[:2]>/<digest>``，事务 journal 写
``<state_home>/source-journals/<id>.json``。本模块只写这些私有状态文件和被点名
的源文件本身：不复制科学数据、不碰 git、不加锁、不加依赖、不执行用户脚本。

外部改写检测优先于写入：任何 ``before_sha256`` 与磁盘不符都拒绝覆盖；
``recover_pending`` 只读磁盘并只写报告，绝不自动覆盖第三方状态。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

__all__ = ['FileChange', 'SourceWriteError', 'apply_source_change',
           'plan_source_change', 'recover_pending', 'restore_project']

_TMP_SUFFIX = 'figpact-tmp'
_BLOBS = ('blobs', 'sha256')
_JOURNALS = 'source-journals'


class SourceWriteError(RuntimeError):
    """可恢复写入失败。

    错误信息以固定前缀说明类别，并带上关键路径/哈希：``STALE_SOURCE``（磁盘内容
    与 before 不符，拒绝覆盖）、``MISSING_BLOB``（journal 指向的不可变内容缺失）、
    ``BLOB_MISMATCH``（blob 内容与内容地址不符）、``JOURNAL_MISSING``（journal
    缺失或形状非法）、``STATE_UNWRITABLE``（状态目录不可写）。journal 自身的
    ``RECOVERY_REQUIRED`` 是状态而非错误：无法判定文件状态时停在那里，不猜测、
    不覆盖。
    """


@dataclass(frozen=True)
class FileChange:
    """一个待写入文件：期望的当前内容哈希 + 目标字节（bytes，不走换行转换）。"""

    path: Path
    before_sha256: str
    after_bytes: bytes


# --------------------------------------------------------------------- 基础

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SourceWriteError(f'{path}：无法读取磁盘内容（{error}）') from error


def _sha256_file(path: Path) -> str | None:
    data = _read(path)
    return None if data is None else _sha256(data)


def _validated_home(state_home: Any) -> Path:
    if not isinstance(state_home, (str, os.PathLike)):
        raise SourceWriteError(f'state_home 必须是路径，得到 {type(state_home).__name__}')
    try:
        return Path(state_home).expanduser().resolve()
    except OSError as error:
        raise SourceWriteError(f'state_home 无法解析：{state_home!r}：{error}') from error


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # ponytail: Windows 目录 fsync 不可靠；文件级 fsync + replace 已保住内容
    finally:
        os.close(fd)


def _fsync_file(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def _blob_path(state_home: Path, ref: Any, sha256: str) -> Path:
    text = '' if ref is None else str(ref)
    if '/' in text or '\\' in text:
        path = Path(text)
        return path if path.is_absolute() else state_home / path
    return state_home.joinpath(*_BLOBS, sha256[:2], sha256)


def _store_blob(state_home: Path, data: bytes) -> tuple[str, Path]:
    """内容寻址落盘（已存在则复用且校验），返回 (digest, 相对 state_home 的路径)。"""
    digest = _sha256(data)
    path = state_home.joinpath(*_BLOBS, digest[:2], digest)
    if path.exists():
        _load_blob(state_home, path, digest)
        return digest, path.relative_to(state_home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SourceWriteError(f'MISSING_BLOB: {path}：无法创建 blob 目录（{error}）') from error
    incoming = path.with_name(f'.incoming-{uuid.uuid4().hex}')
    try:
        with open(incoming, 'xb') as handle:
            handle.write(data)
            _fsync_file(handle)
        os.replace(incoming, path)
    except OSError as error:
        incoming.unlink(missing_ok=True)
        raise SourceWriteError(f'MISSING_BLOB: {path}：blob 无法落盘（{error}）') from error
    _fsync_dir(path.parent)
    return digest, path.relative_to(state_home)


def _load_blob(state_home: Path, ref: Any, sha256: str) -> bytes:
    path = _blob_path(state_home, ref, sha256)
    data = _read(path)
    if data is None:
        raise SourceWriteError(f'MISSING_BLOB: {path}：期望内容 {sha256}')
    actual = _sha256(data)
    if actual != sha256:
        raise SourceWriteError(f'BLOB_MISMATCH: {path}：期望内容 {sha256}，实际 {actual}')
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """不可变快照式落地：临时文件 fsync 后 replace，再 fsync 目录。"""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        incoming = path.with_name(f'.incoming-{uuid.uuid4().hex}')
        with open(incoming, 'xb') as handle:
            handle.write(data)
            _fsync_file(handle)
        os.replace(incoming, path)
    except OSError as error:
        raise SourceWriteError(f'STATE_UNWRITABLE: {path}：状态文件无法写入（{error}）') from error
    _fsync_dir(path.parent)


def _journal_path(state_home: Path, journal_id: str) -> Path:
    return state_home.joinpath(_JOURNALS, f'{journal_id}.json')


def _load_journal(state_home: Path, journal_id: str) -> dict[str, Any]:
    if not isinstance(journal_id, str) or not journal_id:
        raise SourceWriteError(f'JOURNAL_MISSING: {journal_id!r}：journal id 非法')
    path = _journal_path(state_home, journal_id)
    data = _read(path)
    if data is None:
        raise SourceWriteError(f'JOURNAL_MISSING: {path}')
    try:
        journal = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise SourceWriteError(f'JOURNAL_MISSING: {path}：内容不是 JSON（{error}）') from error
    if not isinstance(journal, dict) or not isinstance(journal.get('files'), list):
        raise SourceWriteError(f'JOURNAL_MISSING: {path}：journal 形状非法')
    return journal


def _decode_text(data: bytes) -> str | None:
    if b'\0' in data:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _unified_diff(path: Any, before: bytes, after: bytes) -> str | None:
    before_text = _decode_text(before)
    after_text = _decode_text(after)
    if before_text is None or after_text is None:
        return None
    lines = difflib.unified_diff(before_text.splitlines(keepends=True),
                                 after_text.splitlines(keepends=True),
                                 fromfile=f'a/{path}', tofile=f'b/{path}')
    return ''.join(lines)

def _unlink_tmp(tmp: Path) -> None:
    """删除写入临时文件；Windows 上只读位会拦 unlink，先放行再删（尽力而为）。"""
    try:
        os.chmod(tmp, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        Path(tmp).unlink(missing_ok=True)
    except OSError:
        pass

def _write_target(target: Path, data: bytes, journal_id: str) -> None:
    """临时文件 fsync 后受控 replace，绝不直接截断用户文件。

    单文件原子替换不是多文件整体原子性；权限尽量保持到被替换文件的能力范围内。
    """
    tmp = Path(f'{target}.{_TMP_SUFFIX}-{journal_id}')
    before_mode = None
    try:
        before_mode = os.stat(target).st_mode
    except FileNotFoundError:
        before_mode = None
    try:
        with open(tmp, 'wb') as handle:
            handle.write(data)
            _fsync_file(handle)
        if before_mode is not None:
            try:
                os.chmod(tmp, stat.S_IMODE(before_mode))
            except OSError:
                pass
        # 只读目标不临时放行：Windows replace 只读目标本就该失败，
        # 失败即走调用方回滚；放行会把"中途失败"变成静默成功。
        os.replace(tmp, target)
        if before_mode is not None:
            try:
                os.chmod(target, stat.S_IMODE(before_mode))
            except OSError:
                pass
    except (OSError, ValueError):
        _unlink_tmp(tmp)
        raise


# --------------------------------------------------------------------- 计划

def plan_source_change(changes: Iterable[FileChange], *, state_home: Any, reason: str) -> dict:
    """校验 before 一致 → 落 before/after blob → 写 PREPARED journal，返回 journal。

    任何一个文件的 ``before_sha256`` 与磁盘不符都立即 ``STALE_SOURCE``：此时尚未写
    任何 blob、也不写 journal。
    """
    home = _validated_home(state_home)
    if not isinstance(reason, str):
        raise SourceWriteError(f'reason 必须是字符串，得到 {type(reason).__name__}')
    planned: list[tuple[FileChange, bytes]] = []
    for change in changes:
        if not isinstance(change, FileChange):
            raise SourceWriteError(f'changes 必须是 FileChange，得到 {type(change).__name__}')
        target = Path(change.path)
        before = _read(target)
        if before is None:
            raise SourceWriteError(f'STALE_SOURCE: {target}：目标文件不存在，期望内容 {change.before_sha256}')
        actual = _sha256(before)
        if actual != change.before_sha256:
            raise SourceWriteError(
                f'STALE_SOURCE: {target}：期望 before {change.before_sha256}，磁盘实际 {actual}')
        if not isinstance(change.after_bytes, (bytes, bytearray)):
            raise SourceWriteError(f'{target}：after_bytes 必须是 bytes')
        planned.append((change, before))

    journal_id = uuid.uuid4().hex
    files = []
    for change, before in planned:
        after = bytes(change.after_bytes)
        text_before = _decode_text(before)
        text_after = _decode_text(after)
        binary = text_before is None or text_after is None
        before_sha256, before_blob = _store_blob(home, before)
        after_sha256, after_blob = _store_blob(home, after)
        files.append({'path': str(Path(change.path)),
                      'before_sha256': before_sha256,
                      'after_sha256': after_sha256,
                      'is_binary': binary,
                      'diff': None if binary else _unified_diff(change.path, before, after),
                      'before_blob': before_blob.as_posix(),
                      'after_blob': after_blob.as_posix(),
                      'status': 'PENDING'})
    journal = {'id': journal_id,
               'status': 'PREPARED',
               'created_at': datetime.now(timezone.utc).isoformat(),
               'reason': reason,
               'files': files}
    _write_json(_journal_path(home, journal_id), journal)
    return journal


# ----------------------------------------------------------------- 应用/回滚

def _rollback(home: Path, journal: dict) -> None:
    """按磁盘实际状态回到 before；判定不了的文件标 RECOVERY_REQUIRED，不猜。

    ``MISMATCH`` 表示本轮确实 replace 过该文件、内容却对不上 after：这是我们自己
    写坏的，直接用 before blob 恢复。除此之外只恢复"磁盘正好等于 after"的文件，
    既不是 before 也不是 after 的内容视为第三方，绝不覆盖。
    """
    for entry in journal['files']:
        target = Path(entry['path'])
        _unlink_tmp(Path(f"{target}.{_TMP_SUFFIX}-{journal['id']}"))
        actual = _sha256_file(target)
        ours = entry['status'] == 'MISMATCH'
        certified = actual == entry['before_sha256']
        if not certified and (ours or actual == entry['after_sha256']):
            try:
                before = _load_blob(home, entry.get('before_blob'), entry['before_sha256'])
                _write_target(target, before, journal['id'])
                certified = _sha256_file(target) == entry['before_sha256']
            except (SourceWriteError, OSError, ValueError):
                certified = False
        if not certified:
            entry['status'] = 'RECOVERY_REQUIRED'
        elif not ours:
            entry['status'] = 'ROLLED_BACK'


def apply_source_change(journal_id: str, *, state_home: Any) -> dict:
    """逐文件 tmp→fsync→replace，全部完成后复核 after；返回更新后的 journal。

    写入前逐一复核 before：任何文件被外部改写都 ``STALE_SOURCE`` 且此时尚未动过
    任何一个文件（检测优先于写入）；写入/落盘阶段的可捕获异常则受控回滚。
    """
    home = _validated_home(state_home)
    journal = _load_journal(home, journal_id)
    if journal.get('status') == 'COMMITTED':
        return journal
    for entry in journal['files']:
        target = Path(entry['path'])
        actual = _sha256_file(target)
        if actual != entry['before_sha256']:
            raise SourceWriteError(
                f"STALE_SOURCE: {target}：期望 before {entry['before_sha256']}，"
                f'磁盘实际 {actual}，拒绝覆盖')
    try:
        for entry in journal['files']:
            target = Path(entry['path'])
            after = _load_blob(home, entry.get('after_blob'), entry['after_sha256'])
            _write_target(target, after, journal['id'])
            entry['status'] = 'APPLIED'
            _write_json(_journal_path(home, journal['id']), journal)
        mismatched = False
        for entry in journal['files']:
            if _sha256_file(Path(entry['path'])) != entry['after_sha256']:
                entry['status'] = 'MISMATCH'
                mismatched = True
        if mismatched:
            journal['status'] = 'ROLLED_BACK'
            _rollback(home, journal)
        else:
            journal['status'] = 'COMMITTED'
    except (OSError, ValueError, SourceWriteError) as error:
        journal['status'] = 'ROLLED_BACK'
        journal['failure'] = str(error)
        _rollback(home, journal)
    if any(entry.get('status') == 'RECOVERY_REQUIRED' for entry in journal['files']):
        journal['status'] = 'RECOVERY_REQUIRED'
    _write_json(_journal_path(home, journal['id']), journal)
    return journal


# ------------------------------------------------------------------- 恢复扫描

def _verdict(entry: dict, actual: str | None) -> str:
    if actual is not None and actual == entry.get('before_sha256'):
        return 'before'
    if actual is not None and actual == entry.get('after_sha256'):
        return 'after'
    return 'third_party'


def _blob_ok(home: Path, entry: dict, key: str, sha_key: str) -> bool:
    try:
        _load_blob(home, entry.get(key), entry[sha_key])
    except SourceWriteError:
        return False
    return True


def recover_pending(state_home: Any) -> list[dict]:
    """只读扫描未提交 journal，逐文件判定 before/after/third_party，只写报告文件。"""
    home = _validated_home(state_home)
    directory = home.joinpath(_JOURNALS)
    if not directory.is_dir():
        return []
    reports = []
    for path in sorted(directory.glob('*.json')):
        stem = path.name[:-len('.json')]
        if len(stem) != 32 or not all(char in '0123456789abcdef' for char in stem):
            continue  # 报告文件（<id>.recovery.json）与无关文件不当作 journal
        try:
            journal = _load_journal(home, stem)
        except SourceWriteError as error:
            reports.append({'journal_id': stem, 'status': 'RECOVERY_REQUIRED',
                            'reason': None, 'error': str(error), 'files': []})
            _write_json(directory / f'{stem}.recovery.json', reports[-1])
            continue
        if journal.get('status') == 'COMMITTED':
            continue
        report = {'journal_id': stem, 'status': journal.get('status'),
                  'reason': journal.get('reason'), 'created_at': journal.get('created_at'),
                  'files': []}
        for entry in journal['files']:
            target = Path(entry['path'])
            actual = _sha256_file(target)
            report['files'].append({
                'path': entry['path'],
                'verdict': _verdict(entry, actual),
                'exists': actual is not None,
                'journal_status': entry.get('status'),
                'before_sha256': entry.get('before_sha256'),
                'after_sha256': entry.get('after_sha256'),
                'disk_sha256': actual,
                'before_blob_ok': _blob_ok(home, entry, 'before_blob', 'before_sha256'),
                'after_blob_ok': _blob_ok(home, entry, 'after_blob', 'after_sha256')})
        _write_json(directory / f'{stem}.recovery.json', report)
        reports.append(report)
    return reports


def restore_project(changes: Iterable[dict], *, state_home: Any, reason: str) -> dict:
    """把历史 ``file_changes[]`` 记录的 **after** 内容作为目标、当前磁盘作为 before，
    走 plan + apply 完成一次新的前向写入，返回新 journal（不覆盖任何历史记录）。"""
    home = _validated_home(state_home)
    wanted: list[FileChange] = []
    for record in changes:
        if not isinstance(record, dict) or 'path' not in record:
            raise SourceWriteError(f'file_changes 项必须是含 path 的字典，得到 {record!r}')
        target = Path(record['path'])
        after = _load_blob(home, record.get('after_blob'), record['after_sha256'])
        before_sha256 = _sha256_file(target)
        if before_sha256 is None:
            raise SourceWriteError(
                f'STALE_SOURCE: {target}：目标文件不存在，无法恢复为 {record["after_sha256"]}')
        wanted.append(FileChange(path=target, before_sha256=before_sha256, after_bytes=after))
    journal = plan_source_change(wanted, state_home=home, reason=reason)
    return apply_source_change(journal['id'], state_home=home)
