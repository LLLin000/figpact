"""G3: persistent intent history, verified replay and dependency-aware undo.

Every test drives the public SDK with a deterministic synthetic builder inside
pytest `tmp_path`; no private instrument fixtures are read.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg', force=True)
import matplotlib.pyplot as plt
import pytest
import yaml

from figpact.history import HistoryConflict, HistoryCorrupt, HistoryError, HistoryStore
from figpact.intents import IntentSession

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = 'intent.main.A'
OTHER = 'intent.main.B'
GUIDE = 'intent.main.guide'

SCRIPT = '''\
from pathlib import Path
import os
import matplotlib.pyplot as plt
from figpact import GidRegistry, apply_display_shift
FIGURE_ID = 'intent'
SCOPES = ('main',)
TARGET = 'intent.main.A'
GUIDE = 'intent.main.guide'
SCIENCE_INPUTS = ['science_input.csv']
CONFIG_PATH = Path(__file__).with_name('history.yaml')
POISON_MARKER = os.environ.get('FIGPACT_TEST_POISON_MARKER')
if POISON_MARKER:
    Path(POISON_MARKER).write_text('script-imported', encoding='utf8')
def load_science():
    weights = [float(item) for item in
               CONFIG_PATH.with_name('science_input.csv').read_text(encoding='utf8').split()]
    return {'x': [0., 1., 2.], 'y': [0., 1., 0.], 'weights': weights}
def science_manifest(science):
    return {'nodes': {GUIDE: {'type': 'guide', 'science_policy': 'LAYOUT'}},
            'science': {'protected': {'peak_anchors': {
                TARGET: {'guide_gid': GUIDE, 'guide_anchor_data': [0.5, 0.5],
                         'exact_ppm': 0.5}}}}}
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
    reg.register(guide, GUIDE, params=['offsets_mm'])
    if config['spill']:
        apply_display_shift(reg.get(OTHER), dy_mm=shift[1])
    return fig, reg

def layout_contract(scope):
    return {'parameters': [
        {'key': name, 'path': ['offsets_mm', name], 'unit': 'mm',
         'mutability': 'EDITABLE', 'operation': 'rebuild', 'scale': 1.,
         'min': -10., 'max': 10., 'scopes': ['main'],
         'objects': ['intent.main.' + name] + ([GUIDE] if name == 'A' else [])}
        for name in ['A', 'B']],
        'nodes': {'intent.main.' + name: {'type': 'text', 'editable': True,
                                          'science_policy': 'LAYOUT'} for name in ['A', 'B']},
        'relations': [], 'groups': [], 'outputs': ['history.png']}
'''
CONFIG = 'offsets_mm:\n  A: [0.2, -0.1]\n  B: [0.0, 0.0]\nresponse_scale: 1.0\nspill: false\n'

CHILD = '''\
import json, os, sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg', force=True)
from figpact.intents import IntentSession

state_home, script, config, operation_id, delta, done = sys.argv[1:7]
session = IntentSession(script=script, config=config, scope='main',
                        history=True, state_home=state_home)
frame = session.snapshot()
request = {'operation_id': operation_id, **frame['session'], 'scope': 'main',
           'target_gid': 'intent.main.A', 'operation': 'translate',
           'delta_mm': json.loads(delta), 'tolerance_mm': 0.01,
           'preserve': {'science': True, 'follow_gids': ['intent.main.guide'],
                        'fixed_gids': []},
           'demonstration': {'display_only': True}}
result = session.evaluate(request)
assert result['status'] == 'OK', result
decision = session.decide({'operation_id': operation_id, 'decision': 'accept',
                           **frame['session']})
assert decision['status'] == 'OK', decision
accepted = session.snapshot()
scene = json.loads(accepted['scene_json'])
target = next(node for node in scene['nodes'] if node['gid'] == 'intent.main.A')
Path(done).write_text(json.dumps({'head': accepted['session']['history']['head'],
                                  'bounds_mm': target['bounds_mm'],
                                  'scene_sha256': accepted['scene_sha256'],
                                  'guide_anchor': next(
                                      node for node in scene['nodes']
                                      if node['gid'] == 'intent.main.guide')['runs_mm'][0][0]}),
                      encoding='utf8')
os._exit(9)
'''


def make_workspace(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    script, config = root / 'history_plot.py', root / 'history.yaml'
    (root / 'science_input.csv').write_text('0.000 1.000 0.000\n', encoding='utf8')
    script.write_text(SCRIPT, encoding='utf8')
    config.write_text(yaml.safe_dump(yaml.safe_load(CONFIG), sort_keys=False), encoding='utf8')
    protected = {path: path.read_bytes() for path in sorted(root.iterdir())}
    return {'root': root, 'script': script, 'config': config,
            'input': root / 'science_input.csv', 'state': tmp_path / 'state',
            'protected': protected}


def open_history(workspace, **changes):
    changes.setdefault('state_home', workspace['state'])
    return IntentSession(script=workspace['script'], config=workspace['config'], scope='main',
                         history=True, **changes)


def request(session, operation_id, *, gid=TARGET, delta=(0., 0.15), tolerance_mm=0.01, **changes):
    frame = session.snapshot()
    return {'operation_id': operation_id, **frame['session'], 'scope': 'main', 'target_gid': gid,
            'operation': 'translate', 'delta_mm': list(delta), 'tolerance_mm': tolerance_mm,
            'preserve': {'science': True,
                         'follow_gids': [GUIDE] if gid == TARGET else [], 'fixed_gids': []},
            'demonstration': {'display_only': True}, **changes}


def decide(session, operation_id, action):
    return session.decide({'operation_id': operation_id, 'decision': action,
                           **session.snapshot()['session']})


def accept(session, operation_id, **changes):
    result = session.evaluate(request(session, operation_id, **changes))
    assert result['status'] == 'OK', result
    return decide(session, operation_id, 'accept')


def scene(frame):
    return json.loads(frame['scene_json'])


def node(frame, gid):
    return next(item for item in scene(frame)['nodes'] if item['gid'] == gid)


def bounds(frame, gid):
    return node(frame, gid)['bounds_mm']


def assert_unchanged(workspace):
    names = sorted(path.name for path in workspace['root'].iterdir()
                   if path.name != '__pycache__')
    assert names == sorted(path.name for path in workspace['protected'])
    assert all(path.read_bytes() == data for path, data in workspace['protected'].items())


def poison(tmp_path, monkeypatch, name):
    path = tmp_path / name
    monkeypatch.setenv('FIGPACT_TEST_POISON_MARKER', str(path))
    return path


def store_of(workspace):
    return HistoryStore(workspace['script'], workspace['config'], 'main',
                        state_home=workspace['state'])


def head_payload(workspace):
    with store_of(workspace) as store:
        assert store.head() is not None
        return copy.deepcopy(store.head()['payload'])


def append_payload(workspace, payload, kind='tampered'):
    with store_of(workspace) as store:
        head = store.head()
        return store.append(payload, expected_head=head['id'] if head else None, kind=kind)


def rewrite_same_size(path, old, new):
    data = path.read_bytes()
    assert data.count(old) == 1
    assert len(old) == len(new)
    stat = path.stat()
    path.write_bytes(data.replace(old, new, 1))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    assert path.stat().st_mtime_ns == stat.st_mtime_ns


# --------------------------------------------------------------------------- #
# negative evidence: stale sources, evidence corruption, rejected replay
# --------------------------------------------------------------------------- #

def test_changed_source_is_refused_before_the_changed_script_runs(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path)
    first = poison(tmp_path, monkeypatch, 'marker-trusted.txt')
    with open_history(workspace) as session:
        assert accept(session, 'A1')['persistence_state'] == 'CHECKPOINTED'
    assert first.exists()  # the trusted session really imported the builder

    stat = workspace['script'].stat()
    rewrite_same_size(workspace['script'], b'FIGURE_ID = ', b'FIGURE_ID  =')
    assert workspace['script'].stat().st_size == stat.st_size
    workspace['protected'][workspace['script']] = workspace['script'].read_bytes()

    changed = poison(tmp_path, monkeypatch, 'marker-changed.txt')
    with open_history(workspace) as session:
        stored = session.snapshot()
        history = stored['session']['history']
        assert history['status'] == 'HISTORICAL_ONLY'
        assert history['reason'] == 'SOURCE_CHANGED'
        assert stored['session']['can_evaluate'] is False
        assert stored['session']['accepted_operation_ids'] == ['A1']
        assert session.evaluate(request(session, 'X1'))['status'] == 'HISTORY_ONLY'
        assert session.evaluate(request(session, 'X1'))['history_reason'] == 'SOURCE_CHANGED'
        assert decide(session, 'A1', 'undo')['status'] == 'HISTORY_ONLY'
        assert [record['kind'] for record in session.history()] == ['operation']
    assert not changed.exists()
    assert_unchanged(workspace)


def test_science_input_edited_with_same_size_and_mtime_is_refused(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path)
    first = poison(tmp_path, monkeypatch, 'marker-input-trusted.txt')
    with open_history(workspace) as session:
        assert accept(session, 'A1')['persistence_state'] == 'CHECKPOINTED'
    assert first.exists()
    with store_of(workspace) as store:
        head_before = store.head()['id']

    stat = workspace['input'].stat()
    data = workspace['input'].read_bytes()
    workspace['input'].write_bytes(data[:2] + b'1' + data[3:])
    os.utime(workspace['input'], ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert workspace['input'].stat().st_size == stat.st_size
    assert workspace['input'].stat().st_mtime_ns == stat.st_mtime_ns
    workspace['protected'][workspace['input']] = workspace['input'].read_bytes()

    changed = poison(tmp_path, monkeypatch, 'marker-input.txt')
    with open_history(workspace) as session:
        stored = session.snapshot()
        assert stored['session']['history']['reason'] == 'SOURCE_CHANGED'
        assert stored['session']['history']['status'] == 'HISTORICAL_ONLY'
        assert stored['session']['can_evaluate'] is False
        assert [record['kind'] for record in session.history()] == ['operation']
    assert not changed.exists()
    with store_of(workspace) as store:
        assert store.head()['id'] == head_before
    assert_unchanged(workspace)


def test_corrupt_evidence_denies_replay_and_never_resets_history(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        assert accept(session, 'A1')['persistence_state'] == 'CHECKPOINTED'
        accepted = copy.deepcopy(session.snapshot())
    store = store_of(workspace)
    directory = store.directory
    head = store.head()
    blobs = [directory / 'blobs' / head['payload_sha256']]
    store.close()
    kept = blobs[0].read_bytes()
    blobs[0].write_bytes(b'{"schema": "figpact.intents.history/1", "tampered": true}')

    opened = poison(tmp_path, monkeypatch, 'marker-corrupt.txt')
    try:
        with pytest.raises(HistoryCorrupt):
            open_history(workspace)
        with pytest.raises(HistoryCorrupt):
            with store_of(workspace) as store:
                store.checkpoints()
        assert not opened.exists()
    finally:
        blobs[0].write_bytes(kept)

    with open_history(workspace) as restored:
        stored = restored.snapshot()
        assert stored['session']['history']['status'] == 'ACTIVE'
        assert stored['session']['can_evaluate'] is True
        assert [record['kind'] for record in restored.history()] == ['operation', 'restart']
        assert bounds(stored, TARGET) == pytest.approx(bounds(accepted, TARGET), abs=1e-9)
        with store_of(workspace) as finder:
            later = [finder.directory / 'blobs' / finder.head()['payload_sha256']]
        later[0].write_bytes(b'{"schema": "figpact.intents.history/1", "tampered": true}')
        assert restored.snapshot()['frame_revision'] == stored['frame_revision']
        with pytest.raises(HistoryCorrupt):
            restored.history()
    assert_unchanged(workspace)


def test_falsified_target_geometry_leaves_no_accepted_partial_state(tmp_path):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
        accepted = copy.deepcopy(session.snapshot())
    payload = head_payload(workspace)
    node_id, recorded = next(iter(payload['accepted'][0]['geometry']['after'].items()))
    assert recorded['gid'] == TARGET
    recorded['bounds_mm'] = [value + 5. for value in recorded['bounds_mm']]
    append_payload(workspace, payload)

    with open_history(workspace) as session:
        stored = session.snapshot()
        history = stored['session']['history']
        assert history['status'] == 'HISTORICAL_ONLY'
        assert history['reason'] == 'TARGET_GEOMETRY_MISMATCH'
        assert stored['session']['can_evaluate'] is False
        assert session.evaluate(request(session, 'A2'))['status'] == 'HISTORY_ONLY'
        assert session.decide({'operation_id': 'A1', 'decision': 'accept',
                               **stored['session']})['status'] == 'HISTORY_ONLY'
        assert [record['kind'] for record in session.history()] == ['operation', 'tampered']
        assert stored['frame_revision'] == accepted['frame_revision']
    assert_unchanged(workspace)


def test_missing_evidence_does_not_open_the_editor(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
    payload = head_payload(workspace)
    del payload['science']
    append_payload(workspace, payload, kind='incomplete')

    opened = poison(tmp_path, monkeypatch, 'marker-missing.txt')
    with open_history(workspace) as session:
        stored = session.snapshot()
        assert stored['session']['history']['status'] == 'HISTORICAL_ONLY'
        assert stored['session']['history']['reason'] == 'EVIDENCE_INCOMPLETE'
        assert stored['session']['can_evaluate'] is False
        assert session.evaluate(request(session, 'A2'))['status'] == 'HISTORY_ONLY'
    assert not opened.exists()
    assert_unchanged(workspace)


def test_source_change_between_evaluation_and_accept_writes_no_checkpoint(tmp_path):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        before = session.snapshot()
        result = session.evaluate(request(session, 'A1'))
        assert result['status'] == 'OK'
        workspace['script'].write_bytes(workspace['protected'][workspace['script']] + b'\n# edit\n')
        outcome = decide(session, 'A1', 'accept')
        assert outcome['status'] == 'STALE_REVISION'
        assert outcome['persistence_state'] == 'EPHEMERAL'
        assert session.snapshot()['frame_revision'] == before['frame_revision']
        assert session.history() == []


# --------------------------------------------------------------------------- #
# durable acceptance, restart replay and dependency-aware undo
# --------------------------------------------------------------------------- #

def test_restart_replays_accepted_operation_with_fresh_evidence(tmp_path):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
        accepted = copy.deepcopy(session.snapshot())
        first_head = accepted['session']['history']['head']
        recorded = copy.deepcopy(accepted['session']['history'])
    with open_history(workspace) as restored:
        stored = restored.snapshot()
        history = stored['session']['history']
        assert history['status'] == 'ACTIVE'
        assert history['head'] != first_head
        assert stored['session']['can_evaluate'] is True
        assert stored['session']['accepted_operation_ids'] == ['A1']
        assert bounds(stored, TARGET) == pytest.approx(bounds(accepted, TARGET), abs=1e-9)
        assert node(stored, GUIDE)['runs_mm'][0][0] == pytest.approx(
            node(accepted, GUIDE)['runs_mm'][0][0], abs=1e-9)
        records = restored.history()
        assert [record['kind'] for record in records] == ['operation', 'restart']
        assert records[-1]['payload']['schema'] == 'figpact.intents.history/1'
        assert [item['id'] for item in records[-1]['payload']['verified']] == ['A1']
        assert records[-1]['payload']['source']['files'][str(workspace['script'])]['sha256'] == \
            hashlib.sha256(workspace['protected'][workspace['script']]).hexdigest()
        assert records[-1]['payload']['accepted'][0]['file_changes'] == []
        assert records[-1]['payload']['accepted'][0]['source_change_ids'] == []
        assert restored.evaluate(request(restored, 'A2'))['status'] == 'OK'
        assert decide(restored, 'A2', 'accept')['persistence_state'] == 'CHECKPOINTED'
        assert decide(restored, 'A2', 'undo')['persistence_state'] == 'CHECKPOINTED'
        final = restored.snapshot()
        assert final['session']['accepted_operation_ids'] == ['A1']
        assert bounds(final, TARGET) == pytest.approx(bounds(accepted, TARGET), abs=1e-9)
        assert [record['kind'] for record in restored.history()] == [
            'operation', 'restart', 'operation', 'undo']
    assert [record['kind'] for record in records] == ['operation', 'restart']
    assert accepted['session']['history']['head'] == first_head
    assert recorded['status'] == 'ACTIVE'


def test_undo_and_shared_target_dependency_refusal_survive_restart(tmp_path):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        rest = bounds(session.snapshot(), OTHER)
        accept(session, 'A1')
        accept(session, 'B1', gid=OTHER, delta=(0.2, 0.))
        accept(session, 'A2')
        settled = copy.deepcopy(session.snapshot())
        moved = bounds(settled, TARGET)
        assert decide(session, 'A1', 'undo')['status'] == 'UNDO_CONFLICT'
        assert session.snapshot()['frame_revision'] == settled['frame_revision']
        assert decide(session, 'B1', 'undo')['persistence_state'] == 'CHECKPOINTED'
        assert bounds(session.snapshot(), TARGET) == pytest.approx(moved, abs=1e-9)
    with open_history(workspace) as restored:
        stored = restored.snapshot()
        assert stored['session']['accepted_operation_ids'] == ['A1', 'A2']
        assert bounds(stored, TARGET) == pytest.approx(moved, abs=1e-9)
        assert bounds(stored, OTHER) == pytest.approx(rest, abs=1e-9)
        assert decide(restored, 'A1', 'undo')['status'] == 'UNDO_CONFLICT'
        assert restored.snapshot()['frame_revision'] == stored['frame_revision']
        assert [record['kind'] for record in restored.history()] == [
            'operation', 'operation', 'operation', 'undo', 'restart']
    assert_unchanged(workspace)


def test_repeated_restarts_do_not_accumulate_transforms_or_scientific_drift(tmp_path):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
        accept(session, 'A2')
        recorded = copy.deepcopy(session.snapshot())
        digest = session.history()[-1]['payload']['science']['digest']
    for _ in range(3):
        with open_history(workspace) as restored:
            stored = restored.snapshot()
            assert stored['session']['accepted_operation_ids'] == ['A1', 'A2']
            assert bounds(stored, TARGET) == pytest.approx(bounds(recorded, TARGET), abs=1e-9)
            assert node(stored, GUIDE)['runs_mm'][0][0] == pytest.approx(
                node(recorded, GUIDE)['runs_mm'][0][0], abs=1e-9)
            assert restored.history()[-1]['payload']['science']['digest'] == digest
    assert_unchanged(workspace)


def test_concurrent_append_conflict_preserves_frame_pending_and_history(tmp_path):
    workspace = make_workspace(tmp_path)
    first, second = open_history(workspace), open_history(workspace)
    try:
        before = copy.deepcopy(second.snapshot())
        assert second.evaluate(request(second, 'B1', gid=OTHER, delta=(0.2, 0.)))['status'] == 'OK'
        assert accept(first, 'A1')['persistence_state'] == 'CHECKPOINTED'
        first_head = first.snapshot()['session']['history']['head']
        outcome = decide(second, 'B1', 'accept')
        assert outcome['status'] == 'PERSISTENCE_FAILED'
        assert 'HistoryConflict' in outcome['message']
        assert second.snapshot()['frame_revision'] == before['frame_revision']
        assert second.snapshot()['session']['accepted_operation_ids'] == []
        assert second.snapshot()['session']['history']['head'] is None
        records = second.history()
        assert records[-1]['id'] == first_head
        assert [op['id'] for op in records[-1]['payload']['accepted']] == ['A1']
    finally:
        first.close()
        second.close()
    with open_history(workspace) as current:
        assert current.snapshot()['session']['accepted_operation_ids'] == ['A1']
        assert accept(current, 'B1', gid=OTHER, delta=(0.2, 0.))['persistence_state'] == 'CHECKPOINTED'
        assert current.snapshot()['session']['accepted_operation_ids'] == ['A1', 'B1']
    assert_unchanged(workspace)


def test_store_failure_keeps_live_frame_pending_and_recorded_history(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
    with open_history(workspace) as session:
        assert session.snapshot()['session']['history']['status'] == 'ACTIVE'
        before = copy.deepcopy(session.snapshot())
        assert session.evaluate(request(session, 'B1', gid=OTHER, delta=(0.2, 0.)))['status'] == 'OK'

        def broken(self, payload, *, expected_head, kind):
            raise HistoryError('simulated durable blob failure')

        monkeypatch.setattr(HistoryStore, 'append', broken)
        outcome = decide(session, 'B1', 'accept')
        monkeypatch.undo()
        assert outcome['status'] == 'PERSISTENCE_FAILED'
        assert 'durable blob failure' in outcome['message']
        assert outcome['persistence_state'] == 'REJECTED'
        assert session.snapshot()['frame_revision'] == before['frame_revision']
        assert session.snapshot()['session']['accepted_operation_ids'] == ['A1']
        assert [record['kind'] for record in session.history()] == ['operation', 'restart']
        assert decide(session, 'B1', 'accept')['persistence_state'] == 'CHECKPOINTED'
        assert session.snapshot()['session']['accepted_operation_ids'] == ['A1', 'B1']
    assert_unchanged(workspace)


def test_killed_process_still_replays_the_accepted_operation(tmp_path):
    """A process that dies after a durable accept must reopen with no phantom state."""
    workspace = make_workspace(tmp_path)
    child, done = tmp_path / 'child_intent.py', tmp_path / 'child-done.json'
    child.write_text(CHILD, encoding='utf8')
    environment = dict(os.environ, MPLBACKEND='Agg',
                       PYTHONPATH=str(REPO_ROOT) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    completed = subprocess.run([sys.executable, str(child), str(workspace['state']),
                                str(workspace['script']), str(workspace['config']), 'A1',
                                '[0.0, 0.15]', str(done)],
                               capture_output=True, text=True, env=environment,
                               cwd=str(REPO_ROOT), timeout=600)
    assert completed.returncode == 9, completed.stderr
    recorded = json.loads(done.read_text(encoding='utf8'))

    with open_history(workspace) as restored:
        stored = restored.snapshot()
        assert stored['session']['history']['status'] == 'ACTIVE'
        assert stored['session']['history']['head'] != recorded['head']
        assert stored['session']['accepted_operation_ids'] == ['A1']
        assert stored['session']['can_evaluate'] is True
        assert bounds(stored, TARGET) == pytest.approx(recorded['bounds_mm'], abs=1e-9)
        assert node(stored, GUIDE)['runs_mm'][0][0] == pytest.approx(
            recorded['guide_anchor'], abs=1e-9)
        records = restored.history()
        assert [record['kind'] for record in records] == ['operation', 'restart']
        assert [operation['id'] for operation in
                records[-1]['payload']['accepted']] == ['A1']
    with open_history(workspace) as again:
        assert again.snapshot()['session']['accepted_operation_ids'] == ['A1']
    assert_unchanged(workspace)


def test_history_never_copies_or_rewrites_source_bytes(tmp_path):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
        assert decide(session, 'A1', 'undo')['persistence_state'] == 'CHECKPOINTED'
    assert_unchanged(workspace)
    for path in sorted(workspace['state'].rglob('*')):
        if path.is_file():
            assert workspace['protected'][workspace['script']] not in path.read_bytes()
            assert workspace['protected'][workspace['config']] not in path.read_bytes()


# --------------------------------------------------------------------------- #
# opt-in only: G2 default behaviour is untouched
# --------------------------------------------------------------------------- #

def test_history_mode_is_opt_in_and_g2_sessions_stay_ephemeral(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path)
    with IntentSession(script=workspace['script'], config=workspace['config'],
                       scope='main') as session:
        assert 'history' not in session.snapshot()['session']
        assert accept(session, 'A1')['persistence_state'] == 'ACCEPTED_IN_SESSION'
        with pytest.raises(RuntimeError):
            session.history()
    assert not workspace['state'].exists()
    figure = plt.figure()
    try:
        with pytest.raises(ValueError):
            IntentSession(figure=figure, history=True, state_home=workspace['state'])
    finally:
        plt.close(figure)
    assert not workspace['state'].exists()
    assert_unchanged(workspace)

    default_home = tmp_path / 'default-state'
    monkeypatch.setenv('FIGPACT_STATE_HOME', str(default_home))
    with open_history(workspace, state_home=None) as session:
        assert accept(session, 'A1')['persistence_state'] == 'CHECKPOINTED'
        with HistoryStore(workspace['script'], workspace['config'], 'main',
                          state_home=None) as store:
            assert session.snapshot()['session']['history']['directory'] == str(store.directory)
    assert default_home.exists() and not workspace['state'].exists()
    assert_unchanged(workspace)


def test_invalid_stored_frame_is_refused_before_loading_current_source(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
    payload = head_payload(workspace)
    payload['frame']['png_sha256'] = '0' * 64
    append_payload(workspace, payload, kind='invalid-frame')
    marker = poison(tmp_path, monkeypatch, 'frame-rejected.txt')
    with pytest.raises(HistoryCorrupt):
        open_history(workspace)
    assert not marker.exists()
    assert_unchanged(workspace)


def test_restoration_checks_geometry_outside_the_accepted_operation(tmp_path):
    workspace = make_workspace(tmp_path)
    with open_history(workspace) as session:
        accept(session, 'A1')
    payload = head_payload(workspace)
    frame = payload['frame']
    saved_scene = json.loads(frame['scene_json'])
    other = next(node for node in saved_scene['nodes'] if node['gid'] == OTHER)
    other['bounds_mm'][0] += 0.5
    other['bounds_mm'][2] += 0.5
    frame['scene_json'] = json.dumps(saved_scene, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':'), allow_nan=False)
    frame['scene_sha256'] = hashlib.sha256(frame['scene_json'].encode('utf8')).hexdigest()
    revision = hashlib.sha256(f"{frame['png_sha256']}\n{frame['scene_sha256']}".encode('ascii')).hexdigest()
    frame.update(frame_revision=revision, image_revision=revision, geometry_revision=revision)
    append_payload(workspace, payload, kind='altered-unrelated-geometry')
    with open_history(workspace) as restored:
        result = restored.snapshot()
        assert result['session']['can_evaluate'] is False
        assert result['session']['history']['reason'] == 'FINAL_GEOMETRY_MISMATCH'
        assert [record['kind'] for record in restored.history()] == ['operation', 'altered-unrelated-geometry']
    assert_unchanged(workspace)
