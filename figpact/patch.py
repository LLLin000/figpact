"""Comment-preserving editable YAML patches and reversible file replacement."""
import copy
import hashlib
import math
import os
import tempfile
from pathlib import Path
import yaml
from figpact.cli import _deep_merge_dict


class RevisionConflict(ValueError):
    pass


def config_revision(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_patch(patch, catalog):
    if not isinstance(patch, dict):
        raise ValueError('Patch 必须是映射')
    allowed = {tuple(p['path']): p for s in catalog['scopes'].values()
               for g in s['groups'] for p in g['params']}

    def visit(mapping, path=()):
        for key, value in mapping.items():
            if not isinstance(key, str):
                raise ValueError('参数路径必须使用字符串键')
            here = (*path, key)
            if isinstance(value, dict):
                if not value:
                    raise ValueError(f'空参数映射：{here}')
                visit(value, here)
                continue
            spec = allowed.get(here)
            if spec is None or here[0] in ('schema_version', 'layout_reference'):
                raise ValueError(f'非法键或科学/只读字段：{here}')
            kind = spec['类型']
            if kind == 'bool':
                if not isinstance(value, bool):
                    raise ValueError(f'{here} 必须是 true/false')
                continue
            values = value if kind == '[dx,dy]' else [value]
            if kind == '[dx,dy]' and (not isinstance(value, list) or len(value) != 2):
                raise ValueError(f'{here} 必须是 [dx,dy]')
            if kind not in ('float', 'int', '[dx,dy]'):
                raise ValueError(f'不可编辑的参数类型：{kind}')
            for number in values:
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                    raise ValueError(f'{here} 必须是有限数字')
                if not spec['min'] <= number <= spec['max'] or (kind == 'int' and int(number) != number):
                    raise ValueError(f'{here} 超出范围或不是整数')
    visit(patch)


def _flow(value):
    return yaml.safe_dump(value, default_flow_style=True, sort_keys=False,
                          allow_unicode=True, width=100000).split('\n...')[0].strip()


def apply_patch_text(source, patch, catalog):
    validate_patch(patch, catalog)
    # ponytail: reject aliases; shared nodes cannot safely preserve locked fields with point edits.
    if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(source)):
        raise ValueError('带 YAML 引用的配置不能定点保存，请先展开引用')
    root = yaml.compose(source)
    edits = []
    newline = '\r\n' if '\r\n' in source else '\n'

    def visit(node, updates):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError('参数父节点必须是映射')
        children = {key.value: value for key, value in node.value}
        added = {}
        for key, value in updates.items():
            child = children.get(key)
            if child is None:
                added[key] = value
            elif isinstance(value, dict):
                visit(child, value)
            else:
                edits.append((child.start_mark.index, child.end_mark.index, _flow(value)))
        if not added:
            return
        if node.flow_style:
            index = node.end_mark.index-1
            text = (', ' if node.value else '') + _flow(added)[1:-1]
        else:
            index = node.end_mark.index
            line_start = source.rfind('\n', 0, index)+1
            if not source[line_start:index].strip():
                index = line_start
            indent = ' ' * node.start_mark.column
            lines = yaml.safe_dump(added, sort_keys=False, allow_unicode=True).splitlines()
            text = newline.join(indent+line for line in lines)+newline
            if index and source[index-1] not in '\r\n':
                text = newline+text
        edits.append((index, index, text))
    visit(root, patch)
    result = source
    for start, end, text in sorted(edits, reverse=True):
        result = result[:start]+text+result[end:]
    expected = copy.deepcopy(yaml.safe_load(source))
    _deep_merge_dict(expected, patch)
    if yaml.safe_load(result) != expected:
        raise ValueError('定点保存未能保留配置语义；原文件未修改')
    return result


def _prepare_file(path, content):
    fd, name = tempfile.mkstemp(prefix='.figpact-save-', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return temp
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _fingerprint(content):
    return None if content is None else hashlib.sha256(content).hexdigest()


def _read_optional(path):
    return path.read_bytes() if path.exists() else None


def commit_changes(config, expected_revision, changes):
    """Prepare every file first; replace one by one, rolling back a failed batch."""
    config = Path(config)
    if config_revision(config) != expected_revision:
        raise RevisionConflict('配置已被其他程序修改，请重新加载，未覆盖磁盘改动')
    before = {path: _read_optional(path) for path in changes}
    prepared, applied = {}, []
    try:
        for path, content in changes.items():
            if content is not None:
                prepared[path] = _prepare_file(path, content)
        if config_revision(config) != expected_revision:
            raise RevisionConflict('保存期间配置发生变化，未覆盖磁盘改动')
        for path, content in changes.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(prepared[path], path)
            applied.append(path)
    except BaseException:
        rollback_errors = []
        for path in reversed(applied):
            try:
                content = before[path]
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    temp = _prepare_file(path, content)
                    try:
                        os.replace(temp, path)
                    finally:
                        temp.unlink(missing_ok=True)
            except OSError as error:
                rollback_errors.append(f'{path}: {error}')
        if rollback_errors:
            raise RuntimeError('回滚失败，请保留现场：'+'; '.join(rollback_errors))
        raise
    finally:
        for temp in prepared.values():
            temp.unlink(missing_ok=True)
    return {'before': before, 'after': {p: _fingerprint(v) for p, v in changes.items()}}


def undo_changes(config, expected_revision, record):
    for path, fingerprint in record['after'].items():
        if _fingerprint(_read_optional(path)) != fingerprint:
            raise RevisionConflict(f'{path.name} 已发生新改动，拒绝覆盖或撤销')
    return commit_changes(config, expected_revision, record['before'])
