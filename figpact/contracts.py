"""Author-declared geometry controls. YAML paths are arrays, never dotted strings.

Fail-closed: unknown mutability, record keys or science policies are errors.
Reconstruction fields may be inspected, but must never be editable.
"""
import copy
import math
from pathlib import PurePosixPath

MUTABILITIES = {'EDITABLE', 'DERIVED', 'FIXED_STYLE', 'LOCKED_SCIENCE'}
RELATIONS = {'align', 'gap', 'clearance', 'contain', 'equal_size', 'distribute'}
OPERATIONS = {'translate', 'rebuild', 'resize'}
ANCHORS = {'left', 'right', 'top', 'bottom', 'center_x', 'center_y', 'baseline'}
POLICIES = {'LAYOUT', 'LOCKED_SCIENCE'}
EXPECTED_KINDS = {'translate', 'resize', 'style'}
READ_ONLY_ROOTS = ('schema_version', 'layout_reference')
# 'source', 'validation_error' and 'out_of_scope' are envelope keys the runtime adds around
# the author's raw contract; they are accepted here and never trusted for editability.
CONTRACT_KEYS = {'scope', 'version', 'source', 'validation_error', 'out_of_scope',
                 'parameters', 'relations', 'groups', 'nodes', 'outputs'}
PARAMETER_KEYS = {'key', 'path', 'unit', 'mutability', 'scopes', 'objects', 'operation',
                  'axis', 'scale', 'min', 'max', 'type', 'expected'}
RELATION_KEYS = {'id', 'kind', 'objects', 'axis', 'anchor', 'method', 'controlled_by', 'move', 'target_mm'}
GROUP_KEYS = {'id', 'parent', 'members'}
NODE_KEYS = {'type', 'parent', 'editable', 'science_policy'}


def _path(path, what='An exact nonempty YAML path array'):
    if not isinstance(path, (list, tuple)) or not path or any(not isinstance(p, str) or not p for p in path):
        raise ValueError(f'{what} is required')
    return tuple(path)


def _unknown_keys(record, allowed, what):
    extra = sorted(set(record) - allowed)
    if extra:
        raise ValueError(f'Unknown {what} keys (fail closed): {extra}')


def _finite(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{what} must be a finite number')
    return value


def get_path(data, path):
    value = data
    for part in _path(path):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f'Unknown YAML path: {list(path)}')
        value = value[part]
    return value


def set_path(data, path, value):
    parts = _path(path)
    target = data
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        if not isinstance(target[part], dict):
            raise ValueError(f'Non-mapping YAML parent: {list(path)}')
        target = target[part]
    target[parts[-1]] = value


def _validate_expected(record, path):
    expected = record.get('expected')
    if expected is None:
        return
    if not isinstance(expected, dict):
        raise ValueError(f'expected must be a mapping: {list(path)}')
    _unknown_keys(expected, {'kind', 'objects', 'axis', 'preserve'}, 'expected')
    kind = expected.get('kind')
    if kind not in EXPECTED_KINDS:
        raise ValueError(f'expected.kind must be one of {sorted(EXPECTED_KINDS)}: {list(path)}')
    if any(not isinstance(v, str) for v in expected.get('objects', [])):
        raise ValueError(f'expected.objects must be stable object IDs: {list(path)}')
    # Only a real translate target has a direction that must be named: without an axis the
    # declared rigid movement cannot be checked. style/resize effects have no direction, so
    # an absent (or explicitly null) axis means "not declared" rather than a defect.
    axis = expected.get('axis')
    if kind == 'translate':
        if axis not in ('x', 'y'):
            raise ValueError(f'expected.axis must be x or y for a translate target: {list(path)}')
    elif axis is not None and axis not in ('x', 'y'):
        raise ValueError(f'expected.axis must be x or y: {list(path)}')
    if any(not isinstance(v, str) for v in expected.get('preserve', [])):
        raise ValueError(f'expected.preserve must be named invariants: {list(path)}')


def _validate_parameter(record, *, scope, known, paths):
    if not isinstance(record, dict):
        raise ValueError('Every parameter must be a mapping')
    _unknown_keys(record, PARAMETER_KEYS, 'parameter')
    mutability = record.get('mutability')
    if mutability not in MUTABILITIES:
        raise ValueError(f'UNCLASSIFIED parameter (explicit mutability required): {record.get("key") or record.get("path")}')
    path = _path(record.get('path'), 'Parameter path')
    if path in paths:
        raise ValueError(f'Duplicate parameter path: {list(path)}')
    paths.add(path)
    if path[0] in READ_ONLY_ROOTS and mutability == 'EDITABLE':
        raise ValueError(f'Reconstruction fields are read-only: {list(path)}')
    if 'key' in record and (not isinstance(record['key'], str) or not record['key']):
        raise ValueError(f'Parameter key must be a nonempty string: {list(path)}')
    scopes = record.get('scopes')
    if scopes is not None and (not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes)):
        raise ValueError(f'Parameter scopes must be scope names: {list(path)}')
    objects = record.get('objects', [])
    if not isinstance(objects, list) or any(not isinstance(v, str) for v in objects):
        raise ValueError(f'Parameter objects must be stable object IDs: {list(path)}')
    if known is not None and set(objects) - known:
        raise ValueError(f'Dangling parameter objects: {list(path)}')
    if mutability == 'EDITABLE':
        if record.get('operation') not in OPERATIONS or not isinstance(record.get('unit'), str) or not record['unit']:
            raise ValueError(f'Editable parameter lacks an operation/unit: {list(path)}')
        if not objects:
            raise ValueError(f'Editable parameter lacks affected objects: {list(path)}')
        if scope is not None and scope not in record.get('scopes', [scope]):
            raise ValueError(f'Parameter belongs to another scope: {list(path)}')
        if record['operation'] == 'translate' and (record['unit'] != 'mm' or record.get('axis') not in ('x', 'y')):
            raise ValueError('Translation requires an explicitly declared physical mm axis')
        # Explicit null axis is only meaningful for a full rebuild of the affected set.
        if 'axis' in record and record['axis'] is None and record.get('operation') != 'rebuild':
            raise ValueError(f'Null parameter axis is only allowed on a rebuild: {list(path)}')
        if record.get('axis') is not None and record.get('axis') not in ('x', 'y'):
            raise ValueError(f'Parameter axis must be x or y: {list(path)}')
    for bound in ('min', 'max', 'scale'):
        if bound in record:
            _finite(record[bound], f'Parameter {bound}: {list(path)}')
    if record.get('min', -math.inf) > record.get('max', math.inf):
        raise ValueError('Inverted parameter range')
    _validate_expected(record, path)


def _validate_relation(record, *, known, paths):
    if not isinstance(record, dict):
        raise ValueError('Every relation must be a mapping')
    _unknown_keys(record, RELATION_KEYS, 'relation')
    if not isinstance(record.get('id'), str) or not record['id']:
        raise ValueError('Relation IDs must be nonempty strings')
    rid = record['id']
    if record.get('kind') not in RELATIONS:
        raise ValueError(f'UNCLASSIFIED relation kind: {rid}')
    if not isinstance(record.get('objects'), list) or len(record['objects']) < 2 \
            or any(not isinstance(v, str) for v in record['objects']):
        raise ValueError(f'Invalid relation objects: {rid}')
    if known is not None and set(record['objects']) - known:
        raise ValueError(f'Dangling relation objects: {rid}')
    if 'axis' in record and record['axis'] not in ('x', 'y'):
        raise ValueError(f'Relation axis must be x or y: {rid}')
    if 'anchor' in record and record['anchor'] not in ANCHORS:
        raise ValueError(f'Unknown relation anchor: {rid}')
    move = record.get('move', [])
    if not isinstance(move, list) or any(not isinstance(v, str) for v in move):
        raise ValueError(f'Relation move must be object IDs: {rid}')
    if known is not None and set(move) - known:
        raise ValueError(f'Dangling moving objects: {rid}')
    controlled = record.get('controlled_by', [])
    if not isinstance(controlled, list):
        raise ValueError(f'controlled_by must be a list of exact path arrays: {rid}')
    for entry in controlled:
        if _path(entry, 'controlled_by entry') not in paths:
            raise ValueError(f'Dangling relation parameter: {rid}')
    if 'target_mm' in record:
        _finite(record['target_mm'], f'Relation target_mm: {rid}')


def _validate_group(record, known):
    if not isinstance(record, dict):
        raise ValueError('Every group must be a mapping')
    _unknown_keys(record, GROUP_KEYS, 'group')
    if not isinstance(record.get('id'), str) or not record['id']:
        raise ValueError('Group IDs must be nonempty strings')
    members = record.get('members')
    if not isinstance(members, list) or any(not isinstance(v, str) for v in members):
        raise ValueError(f'Group members must be object IDs: {record["id"]}')
    if known is not None and set(members) - known:
        raise ValueError(f'Dangling group members: {record["id"]}')
    if 'parent' in record and record['parent'] is not None and not isinstance(record['parent'], str):
        raise ValueError(f'Group parent must be a group id: {record["id"]}')


def _validate_node(gid, record):
    if not isinstance(record, dict):
        raise ValueError(f'Node metadata must be a mapping: {gid}')
    _unknown_keys(record, NODE_KEYS, 'node')
    if 'science_policy' in record and record['science_policy'] not in POLICIES:
        raise ValueError(f'Unknown science policy (fail closed): {gid}')
    if 'editable' in record and not isinstance(record['editable'], bool):
        raise ValueError(f'Node editable must be a boolean: {gid}')
    for key in ('type', 'parent'):
        if key in record and record[key] is not None and not isinstance(record[key], str):
            raise ValueError(f'Node {key} must be a string: {gid}')


def _validate_outputs(outputs):
    if not isinstance(outputs, list):
        raise ValueError('Contract outputs must be a list of relative artifact paths')
    for output in outputs:
        path = PurePosixPath(output.replace('\\', '/')) if isinstance(output, str) and output else None
        if path is None or path.is_absolute() or '..' in path.parts or ':' in (output or '') or not path.parts:
            raise ValueError('Publication outputs must be safe relative paths')


def validate_contract(contract, *, scope=None, object_ids=None):
    """Return a deep-copied contract or raise ValueError. Never returns a half-checked record."""
    if not isinstance(contract, dict):
        raise ValueError('Layout contract must be a mapping')
    _unknown_keys(contract, CONTRACT_KEYS, 'contract')
    result = copy.deepcopy(contract)
    params = result.setdefault('parameters', [])
    relations = result.setdefault('relations', [])
    if not isinstance(params, list) or not isinstance(relations, list):
        raise ValueError('Contract parameters and relations must be lists')
    known = None if object_ids is None else set(object_ids)
    paths = set()
    for record in params:
        _validate_parameter(record, scope=scope, known=known, paths=paths)
    ids = set()
    for record in relations:
        _validate_relation(record, known=known, paths=paths)
        rid = record.get('id')
        if rid in ids:
            raise ValueError(f'Duplicate relation id: {rid}')
        ids.add(rid)
    for record in result.get('groups', []):
        _validate_group(record, known)
    nodes = result.get('nodes', {})
    if not isinstance(nodes, dict):
        raise ValueError('Contract nodes must be a mapping of gid to metadata')
    for gid, record in nodes.items():
        if not isinstance(gid, str) or not gid:
            raise ValueError('Node ids must be nonempty strings and are never split on dots')
        _validate_node(gid, record)
    _validate_outputs(result.get('outputs', []))
    return result


def parameter_catalog(contract):
    """Adapt explicit editable controls to the existing comment-preserving save gate.

    Shape stays {scopes: {scope: {groups: [{name, params: [...]}]}}} because
    figpact.patch.validate_patch consumes exactly that. Non-editable mutabilities
    are deliberately absent: the T4 gate can only refuse what it cannot see.
    """
    contract = validate_contract(contract)
    scopes = {}
    for record in contract['parameters']:
        if record['mutability'] != 'EDITABLE':
            continue
        entry = {'path': list(record['path']), 'key': record.get('key', '/'.join(record['path'])),
                 '类型': record.get('type', 'float'), 'min': record.get('min', -math.inf),
                 'max': record.get('max', math.inf), 'unit': record['unit'],
                 'operation': record.get('operation'), 'axis': record.get('axis'),
                 'scale': record.get('scale', 1.0), 'objects': list(record.get('objects', []))}
        for scope in record.get('scopes', ['main']):
            group = scopes.setdefault(scope, {'groups': [{'name': 'Layout', 'params': []}]})
            group['groups'][0]['params'].append(entry)
    return {'scopes': scopes}
