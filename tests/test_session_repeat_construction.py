"""P0 regression: repeated in-process `IntentSession` construction is deterministic.

Root cause guarded here: the NMR example installed its matplotlib rcParams (font
family, mathtext, ``figure.dpi``) only at *import* time. When a session imports
the plotting module inside its own ``matplotlib.rc_context()``, the style is
rolled back on context exit; the *next* in-process construction then lays the
figure out with matplotlib's default fonts. Text measurement changes, the 3.68 ppm
label (``fig2_nmr.main.peak.vancho.3p68``) and its guide no longer fit the lanes
(29 objects instead of 31) and the declared contract fails closed with
``Dangling parameter objects: ['canvas_w_mm']``.

The build path now installs those rcParams itself (`_apply_config`), so the same
``(science, config, scope)`` always renders the same figure, whatever ambient
matplotlib state the caller is in.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg', force=True)
import pytest

from figpact import intents as intents_module
from figpact import session as session_module
from figpact.history import HistoryStore
from figpact.intents import IntentSession

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / 'examples' / 'nmr' / '08 NMR.py'
CONFIG = SCRIPT.with_name('nmr.yaml')
DPI = 600

#: The 3.68 ppm methyl-ester label: the object whose placement flips when the
#: figure is laid out with matplotlib's default font instead of the project style.
LABEL = 'fig2_nmr.main.peak.vancho.3p68'
GUIDE = 'fig2_nmr.main.guide.vancho.3p68'
#: Registered objects of this figure: 35 with the four x-tick labels registered by G7 C2b
#: (dropping the 3.68 ppm label + guide would leave 33).
REGISTERED_OBJECTS = 35
#: Declared scientific anchor of the 3.68 ppm peak (ppm), read from the public scene frame.
DECLARED_PPM = 3.681735495251253
OPERATION_ID = 'p0-repeat-3p68'

REOPEN_FAILURE = 'injected reopen failure'


@pytest.fixture
def cold_process():
    """Make the next session import the plotting module itself.

    A warm module cache means the example's import-time style was applied outside
    any rc_context, which alone hides this defect: the regression has to start the
    way the failure was reported — a fresh process whose first construction owns
    the import. Both caches are process-wide memos of *identical* content, so
    clearing them only re-does the same work.
    """
    session_module._MODULE_CACHE.clear()
    session_module._SCIENCE_CACHE.clear()
    yield
    session_module._MODULE_CACHE.clear()
    session_module._SCIENCE_CACHE.clear()


def _open(history, state_home):
    return IntentSession(script=SCRIPT, config=CONFIG, scope='main', dpi=DPI,
                         history=history, state_home=state_home)


def _nodes(frame):
    return {node['id']: node for node in json.loads(frame['scene_json'])['nodes']}


def _inventory(frame):
    """Everything a caller can observe about one *successfully built* frame.

    ``objects`` is the invariant the defect broke (31 down to 29); ``science`` is
    the protected payload as this frame exposes it — the declared 3.68 ppm anchor
    from the manifest plus the canonical scene and rendered pixels, which differ
    the moment a curve, a label text, a viewport or a font changes.
    """
    nodes = _nodes(frame)
    registered = sorted(gid for gid, node in nodes.items() if node.get('registered'))
    return {
        'all_gids': sorted(nodes),
        # `main::*` are engine-synthetic frame nodes, not registered figure objects.
        'objects': [gid for gid in registered if not gid.startswith('main::')],
        'science': {
            'declared_ppm': nodes[GUIDE]['annotation']['declared_exact_ppm'],
            'scene_sha256': frame['scene_sha256'],
            'png_sha256': frame['png_sha256'],
        },
        'label_bounds_mm': nodes[LABEL]['bounds_mm'],
        'guide_runs_mm': nodes[GUIDE]['runs_mm'],
        'frame_revision': frame['frame_revision'],
    }


def _request(frame, operation_id=OPERATION_ID):
    follow = [gid for gid in (_nodes(frame)[LABEL].get('linked_guide_gid'),) if gid]
    return {'operation_id': operation_id, **frame['session'], 'scope': 'main',
            'target_gid': LABEL, 'operation': 'translate', 'delta_mm': [0.0, 0.15],
            'tolerance_mm': 0.01,
            'preserve': {'science': True, 'follow_gids': follow, 'fixed_gids': []},
            'demonstration': {'display_only': True}}


def _store_state(state_home):
    """On-disk history truth: the chain of checkpoint ids and their head payload."""
    with HistoryStore(SCRIPT, CONFIG, 'main', state_home=state_home) as store:
        records = store.checkpoints()
        head = store.head()
        payload = records[-1]['payload'] if records else {}
        return {
            'ids': [record['id'] for record in records],
            'kinds': [record.get('kind') for record in records],
            'head': head['id'] if head is not None else None,
            'accepted': sorted(op.get('id') for op in (payload.get('accepted') or [])),
            'scene_sha256': (payload.get('frame') or {}).get('scene_sha256'),
        }


@pytest.mark.parametrize('history', [False, True])
def test_repeated_construction_yields_identical_figures(cold_process, tmp_path, history):
    """Three construct→close rounds in one process: same GIDs, geometry and science."""
    state_home = tmp_path / 'state'
    runs = []
    for _ in range(3):
        session = _open(history, state_home)
        try:
            runs.append(_inventory(session.snapshot()))
        finally:
            session.close()

    for index, run in enumerate(runs):
        # The hard fact: 31 objects, including the 3.68 ppm label and its guide.
        assert len(run['objects']) == REGISTERED_OBJECTS, (index, run['objects'])
        assert len(set(run['objects'])) == REGISTERED_OBJECTS
        assert LABEL in run['objects'] and GUIDE in run['objects'], (index, run['objects'])
        assert run['label_bounds_mm'] is not None
        assert run['guide_runs_mm'], (index, run['guide_runs_mm'])
        assert run['science']['declared_ppm'] == pytest.approx(DECLARED_PPM, abs=1e-9)

    for index, run in enumerate(runs[1:], start=1):
        assert run['all_gids'] == runs[0]['all_gids'], index
        assert run['objects'] == runs[0]['objects'], index
        assert run['science'] == runs[0]['science'], index
        assert run['frame_revision'] == runs[0]['frame_revision'], index
        assert run['label_bounds_mm'] == runs[0]['label_bounds_mm'], index
        assert run['guide_runs_mm'] == runs[0]['guide_runs_mm'], index


def test_failed_reopen_leaves_saved_history_intact(cold_process, tmp_path, monkeypatch):
    """A failed reopen must neither damage the checkpoint chain nor block recovery."""
    state_home = tmp_path / 'state'
    session = _open(True, state_home)
    try:
        frame = session.snapshot()
        evaluate = session.evaluate(_request(frame))
        assert evaluate['status'] == 'OK', evaluate
        accept = session.decide({'operation_id': OPERATION_ID, 'decision': 'accept',
                                 **frame['session']})
        assert accept['status'] == 'OK', accept
        accepted = session.snapshot()
        assert accepted['session']['accepted_operation_ids'] == [OPERATION_ID]
        head = accepted['session']['history']['head']
        assert head is not None
    finally:
        session.close()

    before = _store_state(state_home)
    assert before['head'] == head
    assert before['kinds'] == ['operation']
    assert before['accepted'] == [OPERATION_ID]

    def _explode(*args, **kwargs):
        raise RuntimeError(REOPEN_FAILURE)

    # The live core is built, then dies on the first state read: the session must
    # clean up and re-raise with the saved history untouched.
    monkeypatch.setattr(intents_module.FigureSession, 'state', _explode)
    with pytest.raises(RuntimeError, match=REOPEN_FAILURE):
        _open(True, state_home)
    monkeypatch.undo()

    # The failed reopen wrote nothing and rewrote nothing.
    assert _store_state(state_home) == before

    reopened = _open(True, state_home)
    try:
        history = reopened.snapshot()['session']['history']
        assert history['status'] == 'ACTIVE', history
        assert history['head'] is not None
        # The accepted operation survived the failure and was replay-verified.
        assert reopened.snapshot()['session']['accepted_operation_ids'] == [OPERATION_ID]
    finally:
        reopened.close()

    after = _store_state(state_home)
    assert after['ids'][:len(before['ids'])] == before['ids']
    assert after['kinds'][:len(before['kinds'])] == before['kinds']
    assert after['kinds'][-1] == 'restart'
    assert after['accepted'] == [OPERATION_ID]
    assert after['scene_sha256'] == before['scene_sha256']
