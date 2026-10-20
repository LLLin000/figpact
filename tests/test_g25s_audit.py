"""G25-S2 audit-side: contour array comparison never raises, stays strict.

Real downloaded source (matplotlib contour_demo, DEVELOPMENT_EXPOSED) plus
behavioral ndarray/dtype/NaN/unknown-object cases. Public audit surface only
(``style_snapshot`` / ``audit_pair``); no scene/inspector edits. Parent runs
full suites after integration; this module must be green standalone.
"""
import copy
import json
import runpy
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use('Agg', force=True)

import matplotlib.pyplot as plt
import numpy as np

from figpact import change_audit as ca

ROOT = Path(__file__).resolve().parents[1]
CONTOUR = 'tools/g25s/gallery/raw/contour_contour_demo.py'


class _Reg:
    def all(self):
        return {}


def _originals(relative):
    with matplotlib.rc_context(), patch.object(plt, 'show'):
        runpy.run_path(str(ROOT / relative), run_name='__main__')
    return [plt.figure(n) for n in plt.get_fignums()]


def _blank(styles=None, shapes=None):
    return {'styles': dict(styles or {}), 'shapes': dict(shapes or {}),
            'view': {}}


def test_contour_snapshots_audit_identical_without_exception():
    for fig in _originals(CONTOUR):
        try:
            snap = ca.style_snapshot(None, fig, _Reg())
            before = _blank(snap)
            result = ca.audit_pair(before, copy.deepcopy(before), {})
            assert result['actual_changes']['styles'] == {}
            assert result['unauthorized'] == []
            assert result['within_allowed'] is True
            json.dumps(result, allow_nan=False, default=str)
        finally:
            plt.close(fig)


def test_contour_linewidth_array_mutation_is_detected_not_swallowed():
    for fig in _originals(CONTOUR):
        try:
            snap = ca.style_snapshot(None, fig, _Reg())
            gid = 'unregistered.QuadContourSet.0'
            assert gid in snap, [k for k in snap if 'Contour' in k]
            assert isinstance(snap[gid]['linewidth'], list)
            mutated = copy.deepcopy(snap)
            mutated[gid]['linewidth'][0] += 0.5
            result = ca.audit_pair(_blank(snap), _blank(mutated), {})
            assert gid in result['actual_changes']['styles']
            assert any(u['gid'] == gid and u['property'] == 'linewidth'
                       for u in result['unauthorized'])
            assert result['within_allowed'] is False
        finally:
            plt.close(fig)


def test_array_tolerance_shape_and_dtype_are_conservative():
    base = np.array([1.5] * 9)
    cases = [
        (base, base.copy(), False),
        (base, base + 1e-10, False),
        (base, base + 0.5, True),
        (base, base[:3], True),
        (base, base.astype(object), True),
        (np.nan, np.nan, False),
        (np.nan, 1.0, True),
        (float('inf'), float('inf'), False),
        (10.0, 10.0 + 1e-10, False),
        (10.0, 10.5, True),
        (True, 1, True),
        ([1.5], (1.5,), True),
        (np.array([True]), np.array([1]), True),
        (np.array(['red']), np.array(['blue']), True),
    ]
    for before, after, changed in cases:
        result = ca.audit_pair(_blank({'g': {'linewidth': before}}),
                               _blank({'g': {'linewidth': after}}), {})
        assert bool(result['actual_changes']['styles']) is changed
        assert result['within_allowed'] is not changed


def test_incomparable_objects_are_structured_refusal_not_silent():
    class _Weird:
        def __eq__(self, other):
            return [True]
    before = _blank({'g': {'linewidth': _Weird()}})
    after = _blank({'g': {'linewidth': _Weird()}})
    result = ca.audit_pair(before, after, {'styles': {'g': {'linewidth'}}})
    assert result['within_allowed'] is False
    assert any(u.get('class') == 'AUDIT_INCOMPARABLE'
               for u in result['unauthorized'])
    # Allow-listing or exemption must not launder the incomparable.
    assert ca.audit_pair(before, after,
                         {'styles': {'g': {'linewidth'}},
                          'exempt': [{'gid': 'g', 'by': 't', 'reason': 'r'}]}
                         )['within_allowed'] is False
    json.dumps(result, allow_nan=False)
    marker = {'class': 'AUDIT_INCOMPARABLE', 'detail': 'unknown style'}
    assert ca.audit_pair(_blank({'g': {'linewidth': marker}}),
                         _blank({'g': {'linewidth': marker}}),
                         {'styles': {'g': {'linewidth'}}})['within_allowed'] is False
    for other in (np.array([1.5]), [1.5], np.array([1.5], dtype=object)):
        result = ca.audit_pair(_blank({'g': {'linewidth': other}}),
                               _blank({'g': {'linewidth': np.array([1.5], dtype=object)}}),
                               {'styles': {'g': {'linewidth'}},
                                'required_targets': [{'gid': 'g', 'property': 'linewidth'}]})
        assert result['within_allowed'] is False
        assert result['all_required_changed'] is False
        assert result['unauthorized'][0]['class'] == 'AUDIT_INCOMPARABLE'
        json.dumps(result, allow_nan=False)


def test_science_and_permission_gates_stay_strict():
    before = _blank({'g1': {'fontsize': 8.0}})
    after = _blank({'g1': {'fontsize': 8.0}})
    allowed_view = {'styles': {}, 'view': {}}
    try:
        ca.audit_pair(before, after, allowed_view)
        raise AssertionError('allowed[view] must be refused')
    except ca.ChangeAuditError:
        pass
    # Semantic change outside the allow-list is still unauthorized.
    changed = _blank({'g1': {'fontsize': 9.0}})
    result = ca.audit_pair(before, changed, {'styles': {}})
    assert result['within_allowed'] is False
    assert result['unauthorized'] == [{'gid': 'g1', 'property': 'fontsize',
                                       'before': 8.0, 'after': 9.0,
                                       'class': 'semantic'}]
