"""figpact 操作/证据历史：内容寻址 blob + SQLite CAS 线性检查点。

只写自己的私有状态目录（``FIGPACT_STATE_HOME`` 或平台数据目录下的
``workspaces/<id[:2]>/<id>``），不读、不写、不删任何用户源码/配置文件，不复制
科学数据。工作区身份 = 解析后的 script/config 路径 + scope（与源码字节无关）。

检查点 = 不可变 blob（SHA256 命名）+ sqlite 行 + meta 中的 head 指针：
blob 先 fsync 落盘，事务内 CAS 校验 head 再插行、移动 head。提交前的任何崩溃
只留下孤儿 blob——旧 head 不变、新检查点不可见。blob/数据库/血缘损坏一律
fail closed：报错，绝不静默初始化、重置或覆盖既有历史。

本模块不了解渲染器或操作语义；``payload`` 的语义由调用方校验。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ['HistoryConflict', 'HistoryCorrupt', 'HistoryError', 'HistoryStore']

SCHEMA_VERSION = '1'
_STATE_HOME_ENV = 'FIGPACT_STATE_HOME'
_APPLICATION_ID = 0x46475048

Checkpoint = dict[str, Any]
_SELECT_ROWS = ('SELECT seq, id, parent_id, kind, created_at, payload_sha256 '
                'FROM checkpoints ORDER BY seq')
_HEX = frozenset('0123456789abcdef')


class HistoryError(RuntimeError):
    """历史存储基错：参数非法、存储已关闭、检查点不存在。"""


class HistoryConflict(HistoryError):
    """head CAS 失败：``expected_head`` 与当前 head 不一致（并发/陈旧写者）。"""


class HistoryCorrupt(HistoryError):
    """历史损坏：blob 校验失败、数据库格式/血缘/head 指针损坏。一律 fail closed。"""


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _is_uuid_hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 32 and _HEX.issuperset(value)


def _is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and _HEX.issuperset(value)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # ponytail: Windows 目录句柄 fsync 不可靠；blob 文件级 fsync 已保证内容
    finally:
        os.close(fd)


def default_state_home() -> Path:
    """优先 ``FIGPACT_STATE_HOME``，否则平台用户数据目录（不建目录、只解析路径）。"""
    env = os.environ.get(_STATE_HOME_ENV)
    if env:
        return Path(env).expanduser()
    if sys.platform.startswith('win'):
        base = (os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
                or str(Path.home() / 'AppData' / 'Local'))
        return Path(base) / 'figpact'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'figpact'
    base = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
    return Path(base) / 'figpact'


def _validated_source_path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise HistoryError(f'{label} 必须是路径，得到 {type(value).__name__}')
    path = Path(value).expanduser()
    try:
        path = path.resolve()
    except OSError as error:
        raise HistoryError(f'{label} 无法解析（链接环？）：{value!r}：{error}') from error
    if path.is_dir():
        raise HistoryError(f'{label} 不能是目录：{path}')
    return path


def _validated_state_home(state_home: Any) -> Path:
    if state_home is None:
        raw = default_state_home()
    elif isinstance(state_home, (str, os.PathLike)):
        raw = Path(state_home).expanduser()
    else:
        raise HistoryError(f'state_home 必须是路径或 None，得到 {type(state_home).__name__}')
    try:
        resolved = raw.resolve()
    except OSError as error:
        raise HistoryError(f'state_home 无法解析：{raw!r}：{error}') from error
    engine_tree = Path(__file__).resolve().parent
    if resolved == engine_tree or engine_tree in resolved.parents:
        raise HistoryError(f'状态目录不能位于引擎目录内：{resolved}')
    return resolved


def _workspace_id(script: Path, config: Path, scope: str) -> str:
    identity = _canonical_payload_bytes({'script': str(script), 'config': str(config),
                                         'scope': scope})
    return hashlib.sha256(identity).hexdigest()


def _validated_rows(conn: sqlite3.Connection) -> list[tuple]:
    """按 seq 读全部行并校验形状与血缘；任何不符 => HistoryCorrupt。"""
    rows = conn.execute(_SELECT_ROWS).fetchall()
    previous: str | None = None
    for index, (_seq, checkpoint_id, parent_id, kind, created_at, payload_sha256) in enumerate(rows):
        if not _is_uuid_hex(checkpoint_id):
            raise HistoryCorrupt(f'检查点 id 非法：{checkpoint_id!r}')
        if not _is_sha256_hex(payload_sha256):
            raise HistoryCorrupt(f'payload_sha256 非法：{payload_sha256!r}')
        if not isinstance(kind, str) or not kind:
            raise HistoryCorrupt(f'kind 非法：{kind!r}')
        if not isinstance(created_at, str):
            raise HistoryCorrupt(f'created_at 非法：{created_at!r}')
        try:
            datetime.fromisoformat(created_at)
        except ValueError as error:
            raise HistoryCorrupt(f'created_at 非法：{created_at!r}') from error
        if index == 0:
            if parent_id is not None:
                raise HistoryCorrupt('首个检查点的 parent_id 必须为 None')
        elif parent_id != previous:
            raise HistoryCorrupt(f'血缘断裂：{checkpoint_id} 的 parent_id 与前一检查点不符')
        previous = checkpoint_id
    return rows


def _validated_head(conn: sqlite3.Connection, rows: list[tuple]) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key='head'").fetchone()
    if rows:
        if row is None:
            raise HistoryCorrupt('检查点存在但 head 指针缺失：拒绝重建')
        if row[0] != rows[-1][1]:
            raise HistoryCorrupt('head 指针与检查点链尾不一致')
        return row[0]
    if row is not None:
        raise HistoryCorrupt('head 指针指向不存在的检查点')
    return None


class HistoryStore:
    """一个工作区（解析后的 script/config 路径 + scope）的持久操作/证据历史。"""

    def __init__(self, script, config, scope, *, state_home=None, read_only=False):
        if not isinstance(scope, str) or not scope:
            raise HistoryError(f'scope 必须是非空字符串，得到 {scope!r}')
        if not isinstance(read_only, bool):
            raise HistoryError('read_only 必须是布尔值')
        script_path = _validated_source_path(script, 'script')
        config_path = _validated_source_path(config, 'config')
        home = _validated_state_home(state_home)
        if any(home.is_relative_to(path.parent) for path in (script_path, config_path)):
            raise HistoryError('历史目录必须位于脚本和配置目录之外')
        self.script = script_path
        self.config = config_path
        self.scope = scope
        self.workspace_id = _workspace_id(script_path, config_path, scope)
        self.directory: Path = home / 'workspaces' / self.workspace_id[:2] / self.workspace_id
        self._blobs = self.directory / 'blobs'
        self._read_only = read_only
        self._db: sqlite3.Connection | None = None
        self._check_storage_paths()
        if not read_only:
            try:
                self._blobs.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise HistoryError(f'无法创建历史状态目录 {self.directory}：{error}') from error
            _fsync_dir(self.directory)
        try:
            self._db = self._open_database()
            rows = _validated_rows(self._db)
            _validated_head(self._db, rows)
        except HistoryCorrupt:
            self.close()
            raise
        except sqlite3.Error as error:
            self.close()
            raise HistoryCorrupt(f'历史状态无法读取：{self.directory}：{error}') from error

    # ------------------------------------------------------------------ 打开

    def _check_storage_paths(self) -> None:
        paths = [self.directory, self._blobs]
        db_path = self.directory / 'history.sqlite3'
        paths.extend(Path(str(db_path) + suffix) for suffix in ('', '-journal', '-wal', '-shm'))
        for path in paths:
            if path.resolve() != path.absolute():
                raise HistoryError(f'历史路径不能重定向到其他位置：{path}')
            if path.exists():
                is_directory = path in (self.directory, self._blobs)
                if is_directory != path.is_dir() or (not is_directory and path.stat().st_nlink > 1):
                    raise HistoryError(f'历史路径不是独立的专用状态文件或目录：{path}')

    def _open_database(self) -> sqlite3.Connection:
        db_path = self.directory / 'history.sqlite3'
        brand_new = not db_path.exists()
        if brand_new:
            conn = sqlite3.connect(':memory:' if self._read_only else db_path,
                                   timeout=30.0, isolation_level=None)
        else:
            conn = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True,
                                   timeout=30.0, isolation_level=None)
        try:
            if brand_new:
                conn.execute('PRAGMA synchronous=FULL')
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('CREATE TABLE checkpoints ('
                             'seq INTEGER PRIMARY KEY AUTOINCREMENT, '
                             'id TEXT NOT NULL UNIQUE, '
                             'parent_id TEXT, '
                             'kind TEXT NOT NULL, '
                             'created_at TEXT NOT NULL, '
                             'payload_sha256 TEXT NOT NULL)')
                conn.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                conn.executemany('INSERT INTO meta(key, value) VALUES(?, ?)',
                                 [('schema_version', SCHEMA_VERSION),
                                  ('workspace_id', self.workspace_id)])
                conn.execute(f'PRAGMA application_id={_APPLICATION_ID}')
                conn.execute('COMMIT')
                if not self._read_only:
                    _fsync_dir(self.directory)
            self._validate_database_identity(conn)
            if not brand_new and not self._read_only:
                conn.close()
                self._check_storage_paths()
                conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
                self._validate_database_identity(conn)
                conn.execute('PRAGMA synchronous=FULL')
            return conn
        except (sqlite3.Error, HistoryError) as error:
            conn.close()
            if isinstance(error, HistoryError):
                raise
            raise HistoryCorrupt(f'历史数据库无法安全读取：{db_path}：{error}') from error

    def _validate_database_identity(self, conn: sqlite3.Connection) -> None:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'checkpoints', 'meta'} <= tables:
            raise HistoryCorrupt('历史数据库缺少所需表，拒绝重建')
        metadata = dict(conn.execute('SELECT key, value FROM meta'))
        if (conn.execute('PRAGMA application_id').fetchone()[0] != _APPLICATION_ID
                or metadata.get('schema_version') != SCHEMA_VERSION
                or metadata.get('workspace_id') != self.workspace_id):
            raise HistoryCorrupt('历史数据库版本或工作区身份不匹配，拒绝写入')

    # ------------------------------------------------------------------ blob

    def _load_blob(self, payload_sha256: str) -> dict[str, Any]:
        path = self._blobs / payload_sha256
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise HistoryCorrupt(f'检查点证据缺失：{path}') from error
        if hashlib.sha256(raw).hexdigest() != payload_sha256:
            raise HistoryCorrupt(f'检查点证据校验失败（内容寻址不匹配）：{path}')
        try:
            payload = json.loads(raw.decode('utf-8'))
            _canonical_payload_bytes(payload)
        except (UnicodeDecodeError, ValueError, TypeError) as error:
            raise HistoryCorrupt(f'检查点证据不是有限严格 JSON：{path}：{error}') from error
        if not isinstance(payload, dict):
            raise HistoryCorrupt(f'检查点证据不是 JSON 对象：{path}')
        return payload

    def _write_blob(self, payload_sha256: str, data: bytes) -> None:
        destination = self._blobs / payload_sha256
        if destination.exists():
            self._load_blob(payload_sha256)  # 不可变：已存在但坏了就报，绝不覆盖
            return
        incoming = self._blobs / f'.incoming-{uuid.uuid4().hex}'
        with open(incoming, 'xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(incoming, destination)
        _fsync_dir(self._blobs)

    # ------------------------------------------------------------------ 记录

    def _record(self, checkpoint_id: str) -> Checkpoint:
        row = self._db.execute(
            'SELECT id, parent_id, kind, created_at, payload_sha256 '
            'FROM checkpoints WHERE id=?', (checkpoint_id,)).fetchone()
        if row is None:
            raise HistoryError(f'检查点不存在：{checkpoint_id}')
        payload = self._load_blob(row[4])
        return {'id': row[0], 'parent_id': row[1], 'kind': row[2],
                'created_at': row[3], 'payload_sha256': row[4], 'payload': payload}

    def head(self) -> Checkpoint | None:
        self._ensure_open()
        head_id = _validated_head(self._db, _validated_rows(self._db))
        return None if head_id is None else self._record(head_id)

    def checkpoints(self) -> list[Checkpoint]:
        self._ensure_open()
        return [self._record(row[1]) for row in _validated_rows(self._db)]

    def get(self, checkpoint_id: str) -> Checkpoint:
        self._ensure_open()
        if not _is_uuid_hex(checkpoint_id):
            raise HistoryError(f'checkpoint_id 非法：{checkpoint_id!r}')
        return self._record(checkpoint_id)

    # ------------------------------------------------------------------ 写入

    def append(self, payload: dict[str, Any], *, expected_head: str | None,
               kind: str) -> Checkpoint:
        self._ensure_open()
        if self._read_only:
            raise HistoryError('只读历史不能新增检查点')
        self._check_storage_paths()
        if not isinstance(payload, dict):
            raise HistoryError(f'payload 必须是 JSON 对象，得到 {type(payload).__name__}')
        if not isinstance(kind, str) or not kind:
            raise HistoryError(f'kind 必须是非空字符串，得到 {kind!r}')
        if expected_head is not None and not _is_uuid_hex(expected_head):
            raise HistoryError(f'expected_head 必须是检查点 id 或 None，得到 {expected_head!r}')
        try:
            data = _canonical_payload_bytes(payload)
        except (TypeError, ValueError) as error:
            raise HistoryError(f'payload 不是有限严格 JSON：{error}') from error
        if json.loads(data) != payload:
            raise HistoryError('payload 必须是严格 JSON 原生数据（字符串键、列表而非元组）')
        payload_sha256 = hashlib.sha256(data).hexdigest()

        conn = self._db
        conn.execute('BEGIN IMMEDIATE')
        try:
            current = _validated_head(conn, _validated_rows(conn))
            if current != expected_head:
                raise HistoryConflict(
                    f'head 已前移：expected_head={expected_head!r}，当前 head={current!r}')
            if current is not None:
                self._record(current)  # 检查点 id 与证据 SHA 是两种不同的身份
            self._write_blob(payload_sha256, data)
            checkpoint_id = uuid.uuid4().hex
            created_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                'INSERT INTO checkpoints(id, parent_id, kind, created_at, payload_sha256) '
                'VALUES(?,?,?,?,?)',
                (checkpoint_id, current, kind, created_at, payload_sha256))
            if current is None:
                conn.execute("INSERT INTO meta(key, value) VALUES('head', ?)", (checkpoint_id,))
            else:
                moved = conn.execute(
                    "UPDATE meta SET value=? WHERE key='head' AND value=?",
                    (checkpoint_id, current)).rowcount
                if moved != 1:
                    raise HistoryConflict(f'head 被并发移动：{current!r}')
            conn.execute('COMMIT')
        except BaseException:
            try:
                conn.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise
        return {'id': checkpoint_id, 'parent_id': current, 'kind': kind,
                'created_at': created_at, 'payload_sha256': payload_sha256,
                'payload': json.loads(data)}

    # ------------------------------------------------------------------ 关闭

    def _ensure_open(self) -> None:
        if self._db is None:
            raise HistoryError('历史存储已关闭')

    def close(self) -> None:
        db, self._db = self._db, None
        if db is not None:
            db.close()

    def __enter__(self) -> 'HistoryStore':
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python -m figpact.history',
        description='只读查看 figpact 操作/证据历史：不渲染、不执行绘图脚本、不改源码')
    sub = parser.add_subparsers(dest='command', required=True)
    for command, help_text in (('list', '按时间顺序列出检查点'),
                               ('show', '输出单个检查点的完整 JSON')):
        child = sub.add_parser(command, help=help_text)
        child.add_argument('--script', required=True,
                           help='绘图脚本路径（仅用于工作区身份，不会执行）')
        child.add_argument('--config', required=True,
                           help='配置文件路径（仅用于工作区身份，不会读取内容）')
        child.add_argument('--scope', required=True, help='布局 scope 名')
        child.add_argument('--state-home', default=None,
                           help='历史状态目录；默认 FIGPACT_STATE_HOME 或平台数据目录')
        if command == 'show':
            child.add_argument('--id', required=True, dest='checkpoint_id', help='检查点 id')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_cli_parser().parse_args(argv)
    try:
        with HistoryStore(args.script, args.config, args.scope,
                          state_home=args.state_home, read_only=True) as store:
            if args.command == 'list':
                records = store.checkpoints()
                if not records:
                    print('（无历史检查点）')
                for record in records:
                    print(f"{record['id']}  kind={record['kind']}  "
                          f"created_at={record['created_at']}  "
                          f"parent={record['parent_id'] or '-'}  "
                          f"payload={record['payload_sha256'][:12]}")
            else:
                print(json.dumps(store.get(args.checkpoint_id),
                                 ensure_ascii=False, indent=2, sort_keys=True))
    except HistoryError as error:
        print(f'figpact.history: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
