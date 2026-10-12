"""G2: actual rebuild measurements, protected input bytes and isolated decisions."""
from __future__ import annotations

import copy
import json
import uuid

import matplotlib
matplotlib.use('Agg', force=True)
import matplotlib.pyplot as plt
import pytest

from figpact.intents import IntentSession

SCRIPT = '''\
from pathlib import Path
import matplotlib.pyplot as plt
from figpact import GidRegistry, apply_display_shift
FIGURE_ID = 'intent'
SCOPES = ('main',)
CONFIG_PATH = Path(__file__).with_name('intent.yaml')
def load_science():
    return {'x': [0., 1., 2.], 'y': [0., 1., 0.]}
def science_manifest(science):
    return {'nodes': {'intent.main.guide': {'type': 'guide', 'science_policy': 'LAYOUT'}},
            'science': {'protected': {'peak_anchors': {
                'intent.main.A': {'guide_gid': 'intent.main.guide',
                                  'guide_anchor_data': [0.5, 0.5], 'exact_ppm': 0.5}}}}}
def build_scene(science, config, scope):
    fig = plt.figure(figsize=(60/25.4, 40/25.4), dpi=120)
    ax = fig.add_axes((0.15, 0.2, 0.75, 0.6))
    ax.set(xlim=(0, 2), ylim=(-1, 4))
    reg = GidRegistry()
    curve, = ax.plot(science['x'], science['y'], linewidth=0.5)
    reg.register(curve, 'intent.main.curve', params=[])
    for name, xy in [('A', (0.5, 2.0)), ('B', (1.5, 3.0))]:
        label = ax.text(*xy, name, fontsize=7)
        reg.register(label, 'intent.main.' + name, params=['offsets_mm'])
        shift = config['offsets_mm'][name]
        apply_display_shift(label, dx_mm=shift[0], dy_mm=shift[1]*config['response_scale'])
    shift = config['offsets_mm']['A']
    guide, = ax.plot([0.5, 0.5 + shift[0]*2/45],
                     [0.5, 1.8 + shift[1]*config['response_scale']*5/24], linewidth=0.5)
    reg.register(guide, 'intent.main.guide', params=['offsets_mm'])
    if config['spill']:
        apply_display_shift(reg.get('intent.main.B'), dy_mm=shift[1])
    return fig, reg

def layout_contract(scope):
    return {'parameters': [
        {'key': name, 'path': ['offsets_mm', name], 'unit': 'mm',
         'mutability': 'EDITABLE', 'operation': 'rebuild', 'scale': 1.,
         'min': -10., 'max': 10., 'scopes': ['main'],
         'objects': ['intent.main.' + name] + (['intent.main.guide'] if name == 'A' else [])}
        for name in ['A', 'B']],
        'nodes': {'intent.main.' + name: {'type': 'text', 'editable': True,
                                          'science_policy': 'LAYOUT'} for name in ['A', 'B']},
        'relations': [], 'groups': [], 'outputs': ['intent.png']}
'''
CONFIG = 'offsets_mm:\n  A: [0.2, -0.1]\n  B: [0.0, 0.0]\nresponse_scale: 1.0\nspill: false\n'


def make_session(tmp_path, *, scale=1.0, spill=False):
    import yaml
    script = tmp_path / 'intent_plot.py'
    config = tmp_path / 'intent.yaml'
    script.write_text(SCRIPT, encoding='utf8')
    values = yaml.safe_load(CONFIG)
    values['response_scale'], values['spill'] = scale, spill
    config.write_text(yaml.safe_dump(values), encoding='utf8')
    protected = {path: path.read_bytes() for path in (script, config)}
    session = IntentSession(script=script, config=config, scope='main')
    return session, protected


def scene(frame):
    return json.loads(frame['scene_json'])


def node(frame, gid):
    return next(item for item in scene(frame)['nodes'] if item['gid'] == gid)


def intent(session, gid='intent.main.A', delta=(0., 0.15), **changes):
    frame = session.snapshot()
    return {'operation_id': str(uuid.uuid4()), **frame['session'], 'scope': 'main',
            'target_gid': gid, 'operation': 'translate', 'delta_mm': list(delta),
            'tolerance_mm': 0.01, 'preserve': {'science': True,
                'follow_gids': ['intent.main.guide'] if gid.endswith('.A') else [],
                'fixed_gids': []}, 'demonstration': {'display_only': True}, **changes}


def decision(session, operation_id, action):
    return session.decide({'operation_id': operation_id, 'decision': action,
                           **session.snapshot()['session']})


def assert_unchanged(protected):
    assert all(path.read_bytes() == data for path, data in protected.items())


def test_real_rebuild_that_moves_only_point11_cannot_satisfy_point15(tmp_path):
    session, protected = make_session(tmp_path, scale=0.11/0.15)
    with session:
        before = session.snapshot()
        request = intent(session)
        result = session.evaluate(request)
        assert result['status'] == 'TARGET_MISMATCH'
        assert result['measured_delta_mm'] == pytest.approx([0., 0.11], abs=1e-8)
        assert result['error_mm'] == pytest.approx(0.04, abs=1e-8)
        assert session.snapshot()['frame_revision'] == before['frame_revision']
        assert decision(session, request['operation_id'], 'accept')['status'] != 'OK'
    assert_unchanged(protected)


def test_scalar_up_delta_compiles_absolute_pair_and_measures_guide(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        before = session.snapshot()
        request = intent(session, delta_mm=0.15, direction='up')
        result = session.evaluate(request)
        assert result['status'] == 'OK', result
        assert result['verification_level'] == 'RENDER_CHECKED'
        assert result['parameter_changes'][0]['value'] == pytest.approx([0.2, 0.05])
        assert result['measured_delta_mm'] == pytest.approx([0., 0.15], abs=1e-8)
        assert node(result['frame'], 'intent.main.guide')['runs_mm'][0][0] == pytest.approx(
            node(before, 'intent.main.guide')['runs_mm'][0][0], abs=1e-8)
        assert result['guide_checks'][0]['label_endpoint_delta_mm'] == pytest.approx([0., 0.15], abs=1e-8)
        assert session.snapshot()['frame_revision'] == before['frame_revision']
        assert decision(session, request['operation_id'], 'accept')['status'] == 'OK'
    assert_unchanged(protected)


def test_accept_A_cancel_B_and_undo_independent_B_preserve_A(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        request_a = intent(session)
        assert session.evaluate(request_a)['status'] == 'OK'
        assert decision(session, request_a['operation_id'], 'accept')['status'] == 'OK'
        accepted_a = copy.deepcopy(node(session.snapshot(), 'intent.main.A'))
        request_b = intent(session, 'intent.main.B', (0.2, 0.))
        assert session.evaluate(request_b)['status'] == 'OK'
        assert decision(session, request_b['operation_id'], 'cancel')['status'] == 'OK'
        assert node(session.snapshot(), 'intent.main.A') == accepted_a
        request_b = intent(session, 'intent.main.B', (0.2, 0.))
        assert session.evaluate(request_b)['status'] == 'OK'
        assert decision(session, request_b['operation_id'], 'accept')['status'] == 'OK'
        assert decision(session, request_b['operation_id'], 'undo')['status'] == 'OK'
        assert node(session.snapshot(), 'intent.main.A') == accepted_a
    assert_unchanged(protected)


def test_unrequested_other_label_movement_is_blocked(tmp_path):
    session, protected = make_session(tmp_path, spill=True)
    with session:
        before = session.snapshot()['frame_revision']
        result = session.evaluate(intent(session))
        assert result['status'] == 'IMPACT_MISMATCH', result
        assert 'intent.main.B' in result['unapproved_objects']
        assert session.snapshot()['frame_revision'] == before
    assert_unchanged(protected)


def test_out_of_range_retains_desired_delta_without_modifying_accepted_set(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        before = session.snapshot()['frame_revision']
        result = session.evaluate(intent(session, delta=(0., 15.)))
        assert result['status'] == 'OUT_OF_RANGE'
        assert result['target_delta_mm'] == [0., 15.]
        assert session.snapshot()['frame_revision'] == before
    assert_unchanged(protected)


@pytest.mark.parametrize('field,value', [('delta_mm', [True, 0.]),
    ('delta_mm', [0., float('nan')]), ('tolerance_mm', -0.01), ('tolerance_mm', float('inf')),
    ('target_gid', 'intent.main.curve'), ('preserve', {'science': False})])
def test_invalid_or_scientific_rigid_requests_cannot_change_session(tmp_path, field, value):
    session, protected = make_session(tmp_path)
    with session:
        before = session.snapshot()['frame_revision']
        assert session.evaluate(intent(session, **{field: value}))['status'] != 'OK'
        assert session.snapshot()['frame_revision'] == before
    assert_unchanged(protected)


def test_external_config_change_invalidates_pending_accept(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        request = intent(session)
        assert session.evaluate(request)['status'] == 'OK'
        path = next(path for path in protected if path.suffix == '.yaml')
        path.write_bytes(protected[path] + b'\n# external edit\n')
        changed = path.read_bytes()
        assert decision(session, request['operation_id'], 'accept')['status'] == 'STALE_REVISION'
        assert path.read_bytes() == changed


def test_undo_of_operation_with_later_dependent_move_is_refused(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        a = intent(session)
        assert session.evaluate(a)['status'] == 'OK'
        assert decision(session, a['operation_id'], 'accept')['status'] == 'OK'
        b = intent(session, delta=(0., 0.1))
        assert session.evaluate(b)['status'] == 'OK'
        assert decision(session, b['operation_id'], 'accept')['status'] == 'OK'
        before = session.snapshot()['frame_revision']
        assert decision(session, a['operation_id'], 'undo')['status'] == 'UNDO_CONFLICT'
        assert session.snapshot()['frame_revision'] == before
    assert_unchanged(protected)


def test_no_yaml_figure_is_measurement_and_demonstration_only(tmp_path):
    with matplotlib.rc_context():
        fig, ax = plt.subplots()
        text = ax.text(0.5, 0.5, 'ordinary no YAML')
        with IntentSession(figure=fig, scope='main') as session:
            frame = session.snapshot()
            assert frame['session']['can_evaluate'] is False
            selected = next(item for item in scene(frame)['nodes'] if item['text'] == 'ordinary no YAML')
            result = session.evaluate(intent(session, target_gid=selected['id']))
            assert result['status'] == 'NEEDS_AUTHORING'
            assert tuple(text.get_position()) == (0.5, 0.5)
        plt.close(fig)
    assert not list(tmp_path.iterdir())


def test_rebuild_keeps_imported_font_environment_without_leaking_global_rc(tmp_path):
    old, _ = make_session(tmp_path)
    old.close()
    script, config = tmp_path / 'intent_plot.py', tmp_path / 'intent.yaml'
    variant = "import matplotlib\nmatplotlib.rcParams['font.family'] = ['DejaVu Serif']\n" + SCRIPT
    variant = variant.replace("        label = ax.text(*xy, name, fontsize=7)",
        "        if name == 'A' and plt.rcParams['font.family'] != ['DejaVu Serif']:\n"
        "            continue\n"
        "        label = ax.text(*xy, name, fontsize=7)")
    script.write_text(variant, encoding='utf8')
    protected = {path: path.read_bytes() for path in (script, config)}
    family_before = list(matplotlib.rcParams['font.family'])
    with IntentSession(script=script, config=config, scope='main') as session:
        assert list(matplotlib.rcParams['font.family']) == family_before
        result = session.evaluate(intent(session))
        assert result['status'] == 'OK', result
        assert result['measured_delta_mm'] == pytest.approx([0., 0.15], abs=1e-8)
        assert list(matplotlib.rcParams['font.family']) == family_before
    assert_unchanged(protected)


def test_single_label_intent_does_not_choose_binding_that_moves_other_labels(tmp_path):
    from figpact.session import FigureSession
    old, _ = make_session(tmp_path)
    old.close()
    script, config = tmp_path / 'intent_plot.py', tmp_path / 'intent.yaml'
    config.write_bytes(config.read_bytes() + b'\nglobal_y_mm: 0.0\n')
    with FigureSession(script, config, 'main') as core:
        contract = copy.deepcopy(core.contract)
    contract['parameters'].append({'key': 'global_y', 'path': ['global_y_mm'],
        'unit': 'mm', 'mutability': 'EDITABLE', 'operation': 'translate', 'axis': 'y',
        'scale': 1., 'min': -10., 'max': 10., 'scopes': ['main'],
        'objects': ['intent.main.A', 'intent.main.B', 'intent.main.guide']})
    protected = {path: path.read_bytes() for path in (script, config)}
    with IntentSession(script=script, config=config, scope='main', contract=contract) as session:
        result = session.evaluate(intent(session))
        assert result['status'] == 'OK', result
        assert result['parameter_changes'][0]['path'] == ['offsets_mm', 'A']
    assert_unchanged(protected)


def test_unrelated_pending_request_cannot_cancel_another_verified_candidate(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        a = intent(session)
        assert session.evaluate(a)['status'] == 'OK'
        assert session.evaluate(intent(session, 'intent.main.B'))['status'] != 'OK'
        assert decision(session, a['operation_id'], 'accept')['status'] == 'OK'
    assert_unchanged(protected)


def test_failed_reevaluation_cannot_reuse_same_operation_old_evidence(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        request = intent(session)
        assert session.evaluate(request)['status'] == 'OK'
        request['delta_mm'] = [0., 15.]
        assert session.evaluate(request)['status'] == 'OUT_OF_RANGE'
        assert decision(session, request['operation_id'], 'accept')['status'] != 'OK'
    assert_unchanged(protected)


def test_dpi_switch_regenerates_paired_frame_and_preserves_scientific_content(tmp_path):
    session, protected = make_session(tmp_path)
    with session:
        before = session.snapshot()
        result = session.set_quality({**before['session'], 'dpi': 240})
        assert result['status'] == 'OK', result
        new = result['frame']
        assert new['frame_revision'] != before['frame_revision']
        assert new['frame_revision'] == new['image_revision'] == new['geometry_revision']
        assert scene(new)['measurement']['dpi'] == 240
        assert scene(new)['source_revision'] == scene(before)['source_revision']
        request = intent(session)
        assert session.evaluate(request)['status'] == 'OK'
        assert session.set_quality({**session.snapshot()['session'], 'dpi': 120})['status'] == 'QUALITY_LOCKED'
        assert decision(session, request['operation_id'], 'accept')['status'] == 'OK'
    assert_unchanged(protected)


def test_geometry_proof_does_not_bypass_actual_scope_qa(tmp_path):
    from figpact.session import FigureSession
    old, _ = make_session(tmp_path)
    old.close()
    script, config = tmp_path / 'intent_plot.py', tmp_path / 'intent.yaml'
    variant = SCRIPT.replace('    return fig, reg\n',
        "    fig._reserved_dx_mm = config['move_b_mm']\n"
        "    apply_display_shift(reg.get('intent.main.B'), dx_mm=config['move_b_mm'])\n"
        "    return fig, reg\n")
    variant += """
def preview_qa(fig, scope):
    return [{'rule_id': 'RESERVED_NOTE_COLUMN', 'severity': 'blocker',
             'object_ids': ['intent.main.B'], 'message': 'label entered protected note column'}] \
        if fig._reserved_dx_mm > 0.3 else []
"""
    script.write_text(variant, encoding='utf8')
    config.write_bytes(config.read_bytes() + b'\nmove_b_mm: 0.0\n')
    with FigureSession(script, config, 'main') as core:
        contract = copy.deepcopy(core.contract)
    contract['parameters'] = [record for record in contract['parameters'] if record['key'] != 'B']
    contract['parameters'].append({'key': 'move_b', 'path': ['move_b_mm'],
        'unit': 'mm', 'mutability': 'EDITABLE', 'operation': 'translate', 'axis': 'x',
        'scale': 1., 'min': -10., 'max': 10., 'scopes': ['main'],
        'objects': ['intent.main.B'],
        'expected': {'kind': 'translate', 'axis': 'x', 'objects': ['intent.main.B']}})
    protected = {path: path.read_bytes() for path in (script, config)}
    with IntentSession(script=script, config=config, scope='main', contract=contract) as session:
        before = session.snapshot()['frame_revision']
        result = session.evaluate(intent(session, 'intent.main.B', (0.5, 0.)))
        assert result['status'] == 'QA_BLOCKED', result
        assert session.snapshot()['frame_revision'] == before
    assert_unchanged(protected)


def test_requested_tolerance_cannot_allow_scientific_guide_anchor_to_move(tmp_path):
    old, _ = make_session(tmp_path)
    old.close()
    script, config = tmp_path / 'intent_plot.py', tmp_path / 'intent.yaml'
    script.write_text(SCRIPT.replace('[0.5, 1.8 +',
        '[0.5 + (shift[1] + 0.1)*5/24, 1.8 +'), encoding='utf8')
    protected = {path: path.read_bytes() for path in (script, config)}
    with IntentSession(script=script, config=config, scope='main') as session:
        before = session.snapshot()['frame_revision']
        request = intent(session, tolerance_mm=100.)
        result = session.evaluate(request)
        assert result['status'] == 'SCIENCE_CHANGED', result
        assert result['guide_checks'][0]['status'] == 'FAIL'
        assert session.snapshot()['frame_revision'] == before
        assert decision(session, request['operation_id'], 'accept')['status'] != 'OK'
    assert_unchanged(protected)


def test_publication_resolution_keeps_trial_physics_and_quality_lock(tmp_path):
    original, protected = make_session(tmp_path)
    original.close()
    with IntentSession(script=tmp_path / 'intent_plot.py',
                       config=tmp_path / 'intent.yaml', scope='main', dpi=600) as session:
        frame = session.snapshot()
        assert scene(frame)['measurement']['dpi'] == 600
        assert scene(frame)['image']['width_px'] == int(60 * 600 / 25.4)
        assert scene(frame)['image']['height_px'] == int(40 * 600 / 25.4)
        for dpi in (240, 600):
            result = session.set_quality({**session.snapshot()['session'], 'dpi': dpi})
            assert result['status'] == 'OK', result
            assert scene(result['frame'])['measurement']['dpi'] == dpi
            assert result['frame']['frame_revision'] == result['frame']['geometry_revision']
        request = intent(session)
        result = session.evaluate(request)
        assert result['status'] == 'OK', result
        assert result['measured_delta_mm'] == pytest.approx([0., 0.15], abs=1e-8)
        assert result['guide_checks'][0]['scientific_endpoint_error_mm'] <= 1e-8
        assert decision(session, request['operation_id'], 'accept')['status'] == 'OK'
        accepted = session.snapshot()['frame_revision']
        assert session.set_quality({**session.snapshot()['session'], 'dpi': 120})['status'] == 'QUALITY_LOCKED'
        assert session.snapshot()['frame_revision'] == accepted
    assert_unchanged(protected)


def test_display_quality_cannot_change_caller_owned_plain_figure():
    fig = plt.figure(dpi=173)
    try:
        canvas = fig.canvas
        with pytest.raises(ValueError):
            IntentSession(figure=fig, dpi=600)
        assert fig.dpi == 173
        assert fig.canvas is canvas
    finally:
        plt.close(fig)
