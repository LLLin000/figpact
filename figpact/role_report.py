"""Read-only semantic font-role and edit-capability report for a captured frame."""
from __future__ import annotations

import json
import math
from typing import Any

from figpact.roles import VERIFIABLE_PARAM_ROLE

_FONT_KEYS = {key: role for key, role in VERIFIABLE_PARAM_ROLE.items()
              if role in {'axis.title', 'axis.tick', 'legend'}}


def capability_report(frame: dict[str, Any], controls: list[dict[str, Any]],
                      projection: dict[str, Any], *, editable: bool = False) -> dict[str, Any]:
    """Report measured font roles and exact, coupled native font controls; never edits."""
    try:
        scene = json.loads(frame['scene_json'])
        if not isinstance(scene, dict) or not isinstance(scene.get('nodes'), list):
            raise ValueError('frame scene nodes must be a list')
        source_nodes = scene['nodes']
    except (KeyError, TypeError, ValueError):
        return {'status': 'UNSUPPORTED', 'roles': [], 'coupling': [],
                'reason': 'INVALID_OR_MISSING_FRAME_SCENE'}
    projected = {item.get('id'): item for item in (projection or {}).get('nodes', [])
                 if isinstance(item, dict)}
    role_nodes = []
    source_by_id = {}
    for node in source_nodes:
        if not isinstance(node, dict):
            continue
        raw_semantic = node.get('semantic')
        semantic = raw_semantic if isinstance(raw_semantic, dict) else {}
        role = semantic.get('role')
        if (role is None and node.get('type') != 'text'
                and node.get('artist_type') != 'Text' and not node.get('is_text')):
            continue
        identity = node.get('id')
        source_by_id[identity] = node
        pnode = projected.get(identity) or {}
        font = node.get('font_size_pt')
        if isinstance(font, bool) or not isinstance(font, (int, float)) or not math.isfinite(float(font)) or font <= 0:
            font, effective, reason = None, None, 'FONT_SIZE_UNAVAILABLE'
        else:
            scale = pnode.get('scale_xy')
            if not isinstance(scale, list) or len(scale) != 2:
                effective, reason = None, 'SCALE_UNAVAILABLE'
            elif pnode.get('anisotropic') is not False:
                effective, reason = None, 'ANISOTROPIC_SCALE'
            elif any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in scale):
                effective, reason = None, 'SCALE_UNAVAILABLE'
            else:
                effective, reason = float(font) * float(scale[0]), None
        role_nodes.append({'id': identity, 'gid': node.get('gid'),
                           'identity_stability': 'stable' if node.get('registered') is True else 'ephemeral',
                           'semantic_role': role, 'axis': semantic.get('axis'),
                           'axes_id': semantic.get('axes_id'),
                           'axes_context': semantic.get('axes_context', 'unknown'),
                           'evidence': semantic.get('evidence', 'unknown'),
                           'source_font_pt': font, 'effective_font_pt': effective,
                           'font_reason': reason, 'visible': node.get('visible'),
                           'measured': node.get('measured') is True,
                           'visible_state': ('hidden' if node.get('visible') is False
                                             else 'cropped' if pnode.get('reason') == 'CROPPED_OUT'
                                             else 'visible' if pnode.get('measurable') is True
                                             else 'unmeasured'),
                           'final_rect_mm': pnode.get('rect_mm'), 'font_controls': []})

    by_id = {item['id']: item for item in role_nodes}
    couplings = []
    status = 'READY'
    for control in controls or []:
        if not isinstance(control, dict):
            continue
        path = control.get('path')
        if not isinstance(path, list) or not path or any(not isinstance(part, str) for part in path):
            continue
        if len(path) != 1:
            continue
        key = path[0]
        expected_role = _FONT_KEYS.get(key)
        # Policy keys are canonical root parameters, not matching path suffixes.
        if expected_role is None or control.get('unit') != 'pt':
            continue
        cid = control.get('control_id')
        if not isinstance(cid, str) or cid != json.dumps(path, separators=(',', ':'), ensure_ascii=False):
            continue
        objects = control.get('objects')
        if not isinstance(objects, list):
            continue
        affected = [by_id[oid] for oid in objects if oid in by_id]
        exact = [item for item in affected
                 if item['semantic_role'] == expected_role and item['evidence'] == 'artist_identity'
                 and item['identity_stability'] == 'stable' and item['gid'] == item['id']]
        unmatched = [oid for oid in objects if oid not in {item['id'] for item in exact}]
        ranges = {'min': control.get('min'), 'max': control.get('max')}
        binding_valid = bool(exact) and not unmatched and all(
            path in (source_by_id[item['id']].get('controlled_by') or []) for item in exact)
        can_edit = (editable is True and control.get('value_shape', 'scalar') == 'scalar'
                    and binding_valid and all(item['semantic_role'] == expected_role for item in affected))
        groups = sorted({(item['semantic_role'], item['axis'], item['axes_id'], item['axes_context'])
                         for item in affected}, key=lambda values: tuple(str(v) for v in values))
        coupling = {'control_id': cid, 'path': list(path), 'role': expected_role,
                    'affected_ids': list(objects),
                    'affected_role_groups': [{'role': r, 'axis': a, 'axes_id': ax, 'axes_context': ctx}
                                             for r, a, ax, ctx in groups],
                    'unmatched_ids': unmatched}
        couplings.append(coupling)
        for item in exact:
            measured_target = (item['visible'] is True and item['measured']
                               and item['final_rect_mm'] is not None and item['font_reason'] is None)
            item['font_controls'].append({'control_id': cid, 'path': list(path),
                                          'min': ranges['min'], 'max': ranges['max'],
                                          'affected_ids': list(objects), 'editable': can_edit and measured_target})
        if objects and not binding_valid:
            status = 'UNSUPPORTED'
    if not any(item['evidence'] == 'artist_identity' and item['semantic_role'] is not None
               and item['effective_font_pt'] is not None for item in role_nodes):
        status = 'UNSUPPORTED'
    if editable is not True:
        for item in role_nodes:
            for control in item['font_controls']:
                control['editable'] = False
    return {'status': status, 'roles': role_nodes, 'coupling': couplings,
            'editability': 'EDITABLE_OBSERVATION' if editable is True else 'READ_ONLY'}
