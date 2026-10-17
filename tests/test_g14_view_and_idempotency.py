"""G14 视图安全与幂等：只用 change_audit 公共函数 + FigureSession，不碰产品代码。"""
from __future__ import annotations

import copy
from pathlib import Path

import matplotlib

matplotlib.use('Agg', force=True)

import pytest

from figpact.change_audit import audit_pair, capture_snapshot
from figpact.session import FigureSession

ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = ROOT / 'examples' / 'demo' / 'demo_figure.py'
DEMO_CONFIG = ROOT / 'examples' / 'demo' / 'demo.yaml'
SCOPE = 'main'


def _axes_entry(xlim=(0.0, 5.0), ylim=(0.0, 1.0), xscale='linear',
                yscale='linear', x_inverted=False, y_inverted=False):
    return {'xlim': [float(xlim[0]), float(xlim[1])],
            'ylim': [float(ylim[0]), float(ylim[1])],
            'xscale': xscale, 'yscale': yscale,
            'x_inverted': x_inverted, 'y_inverted': y_inverted}


def _snap(view, styles=None, shapes=None):
    return {'styles': dict(styles or {}), 'shapes': dict(shapes or {}),
            'view': copy.deepcopy(view)}


def _protected(result):
    return [u for u in result['unauthorized'] if u.get('class') == 'protected-view']


def test_identical_view_passes():
    view = {'axes0': _axes_entry()}
    result = audit_pair(_snap(view), _snap(view), {})
    assert result['unauthorized'] == []
    assert result['within_allowed'] is True


def test_xlim_widening_is_protected_view():
    before = _snap({'axes0': _axes_entry(xlim=(0.0, 5.0))})
    after = _snap({'axes0': _axes_entry(xlim=(0.0, 7.0))})
    result = audit_pair(before, after, {})
    hits = _protected(result)
    assert len(hits) == 1
    assert hits[0]['gid'] == 'axes0'
    assert hits[0]['property'] == 'view'
    assert result['within_allowed'] is False


@pytest.mark.parametrize('drop', ['before', 'after'])
def test_missing_view_either_side_is_audit_incomplete(drop):
    view = {'axes0': _axes_entry()}
    before = {'styles': {}, 'shapes': {}, 'view': copy.deepcopy(view)}
    after = {'styles': {}, 'shapes': {}, 'view': copy.deepcopy(view)}
    del (before if drop == 'before' else after)['view']
    result = audit_pair(before, after, {})
    assert any(u.get('class') == 'AUDIT_INCOMPLETE'
               for u in result['unauthorized'])
    assert result['within_allowed'] is False


def test_change_in_second_axes_localizes_axes1():
    before = _snap({'axes0': _axes_entry(),
                    'axes1': _axes_entry(xlim=(0.0, 5.0))})
    after = _snap({'axes0': _axes_entry(),
                   'axes1': _axes_entry(xlim=(0.0, 5.5))})
    result = audit_pair(before, after, {})
    hits = _protected(result)
    assert [h['gid'] for h in hits] == ['axes1']


@pytest.mark.parametrize('kind,old,new', [
    ('xscale', 'linear', 'log'),
    ('yscale', 'linear', 'log'),
    ('x_inverted', False, True),
    ('y_inverted', False, True),
])
def test_scale_and_inversion_changes_are_protected_view(kind, old, new):
    kwargs = {kind: old}
    kwargs2 = {kind: new}
    before = _snap({'axes0': _axes_entry(**kwargs)})
    after = _snap({'axes0': _axes_entry(**kwargs2)})
    result = audit_pair(before, after, {})
    assert len(_protected(result)) == 1
    assert result['within_allowed'] is False


def _first_style_target(styles):
    for gid in sorted(styles):
        for prop in ('fontsize', 'linewidth', 'text'):
            if prop in styles[gid]:
                return gid, prop
    raise AssertionError('快照里没有可用的样式目标')


def _demo_snapshot_pair():
    with FigureSession(str(DEMO_SCRIPT), str(DEMO_CONFIG), SCOPE) as session:
        first = capture_snapshot(session)
        second = capture_snapshot(session)
    return first, second


def test_double_capture_snapshot_view_science_styles_shapes_idempotent():
    first, second = _demo_snapshot_pair()
    assert second['view'] == first['view']
    assert second['science'] == first['science']
    assert second['styles'] == first['styles']
    assert second['shapes'] == first['shapes']
    result = audit_pair(first, second, {})
    assert result['actual_changes']['styles'] == {}
    assert result['actual_changes']['geometry'] == {}
    assert result['actual_changes']['added'] == []
    assert result['actual_changes']['removed'] == []


def test_repeat_audit_pair_grants_nothing_and_reports_target_unchanged():
    first, _ = _demo_snapshot_pair()
    dup = copy.deepcopy(first)
    result = audit_pair(first, dup, {})
    assert result['unauthorized'] == []
    assert result['derived_geometry'] == []
    assert result['within_allowed'] is True
    gid, prop = _first_style_target(first['styles'])
    key = f'{gid}.{prop}'
    result2 = audit_pair(first, dup, {'required_targets': [{'gid': gid,
                                                             'property': prop}]})
    assert result2['required_targets_effectively_changed'][key] is None
    assert result2['all_required_changed'] is False


def test_unchanged_required_target_is_not_effective():
    first, _ = _demo_snapshot_pair()
    dup = copy.deepcopy(first)
    target = {'gid': 'demo.main.ghost', 'property': 'fontsize'}
    result = audit_pair(first, dup, {'required_targets': [target]})
    assert result['required_targets_effectively_changed']['demo.main.ghost.fontsize'] is None
    assert result['all_required_changed'] is False
