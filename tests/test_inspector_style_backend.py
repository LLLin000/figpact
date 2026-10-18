"""G18 style-backend regression (owner: InspectorStyleBackend).

Real StyleSession + HTTP security/regression. No run until parent.
Covers: frame.style in snapshot, preview/commit/cancel, stale gates,
token/origin/path/method refusals, drift refusal, no official write
until commit, restart with saved overlay.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import threading
from contextlib import contextmanager
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pytest

from figpact import style_overlay
from figpact.inspector_server import InspectorServer
from figpact.inspector_style import StyleSession
from figpact.intents import IntentSession

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/g15/B/g15b_barchart_decl.py'

_PINNED_RC = {
    "font.size": 10.0, "axes.labelsize": "medium", "axes.titlesize": "large",
    "xtick.labelsize": "medium", "ytick.labelsize": "medium",
    "legend.fontsize": "medium", "figure.dpi": 100.0, "lines.linewidth": 1.5,
}


@pytest.fixture(autouse=True)
def _pin_rc():
    saved = {k: matplotlib.rcParams[k] for k in _PINNED_RC}
    matplotlib.rcParams.update(_PINNED_RC)
    try:
        yield
    finally:
        matplotlib.rcParams.update(saved)
        plt.close('all')


def _ids():
    inv = style_overlay.inventory(SCRIPT, scope='main')
    a = next(t['id'] for t in inv
             if t['role'] == 'axis.title' and t['selector'].get('axis') == 'y')
    b = next(t['id'] for t in inv
             if t['role'] == 'axis.tick' and t['selector'].get('axis') == 'x')
    return a, b


def _h(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@contextmanager
def _server(tmp_path, overlay):
    from figpact.final_size import _build_figure, _import_script, _load_config
    import copy
    module = _import_script(SCRIPT.resolve())
    cfg = _load_config(module, SCRIPT.resolve(), None)
    (figure, _reg), _resolved = _build_figure(module, copy.deepcopy(cfg), 'main')
    session = IntentSession(figure=figure, scope='main')
    style = StyleSession(script=SCRIPT, config=None, scope='main', overlay=overlay)
    server = InspectorServer(session, ('127.0.0.1', 0), style=style)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, server.server_address[1]
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
        session.close()
        plt.close(figure)


def _req(port, method, path, body=None, **headers):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
    data = None if body is None else json.dumps(body)
    if data is not None:
        headers.setdefault('Content-Type', 'application/json')
    conn.request(method, path, data, headers)
    resp = conn.getresponse()
    out = (resp.status, json.loads(resp.read().decode() or '{}'),
           dict(resp.getheaders()))
    conn.close()
    return out


def _ui(server):
    return {'X-Figpact-Ui': server.ui_token}


def test_frame_carries_style_and_commit_roundtrip(tmp_path):
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    with _server(tmp_path, overlay) as (server, port):
        status, frame, _ = _req(port, 'GET', '/api/frame')
        assert status == 200 and 'style' in frame
        targets = {t['target_id']: t for t in frame['style']['targets']}
        assert set(targets) >= {a, b}
        row = targets[a]
        assert {'target_id', 'label', 'property', 'current_pt', 'saved_pt',
                'scene_ids'} <= set(row)
        assert row['current_pt'] == 10.0 and row['saved_pt'] is None
        assert row['scene_ids'] and all(isinstance(s, str) for s in row['scene_ids'])
        rev = frame['frame_revision']
        # A: ylabel 10 -> 8 preview then commit
        status, prev, _ = _req(port, 'POST', '/api/style/preview',
                               {'frame_revision': rev, 'target_id': a, 'value': 8})
        assert status == 200 and prev['status'] == 'OK', prev
        pending = prev['style']['pending']
        assert pending['candidate_id'] == prev['style']['candidate_id']
        assert (pending['target_id'], pending['old_pt'], pending['new_pt'],
                pending['affected']) == (a, 10.0, 8.0, sorted([a]))
        assert pending['base_frame_revision'] == rev
        assert pending['expected_sha256'] == prev['style']['overlay_sha256'] == ''
        assert not overlay.exists()  # no official write until commit
        cand = prev['style']['candidate_id']
        status, done, _ = _req(port, 'POST', '/api/style/commit',
                               {'candidate_id': cand, 'frame_revision': rev,
                                'expected_sha256': ''}, **_ui(server))
        assert status == 200 and done['status'] == 'COMMITTED', done
        assert done['style']['receipt']['source_commit_state'] == 'COMMITTED'
        assert done['style']['receipt']['figure_verification_state'] == 'PASS'
        assert overlay.exists()
        # stale candidate cannot replay
        status, stale, _ = _req(port, 'POST', '/api/style/commit',
                                {'candidate_id': cand, 'frame_revision': rev,
                                 'expected_sha256': _h(overlay)}, **_ui(server))
        assert status == 409 and stale['status'] == 'CANDIDATE_UNKNOWN'
        # restart with saved overlay keeps A=8
        style2 = StyleSession(script=SCRIPT, config=None, scope='main', overlay=overlay)
        row2 = {t['target_id']: t for t in style2.snapshot()['style']['targets']}[a]
        assert row2['saved_pt'] == 8.0 and row2['current_pt'] == 8.0
        plt.close('all')


def test_stale_and_security_gates(tmp_path):
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    with _server(tmp_path, overlay) as (server, port):
        frame = _req(port, 'GET', '/api/frame')[1]
        rev = frame['frame_revision']
        # strict keys refused
        assert _req(port, 'POST', '/api/style/preview',
                    {'frame_revision': rev, 'target_id': a, 'value': 8,
                     'script': 'x'})[0] == 400
        # stale revision refused
        assert _req(port, 'POST', '/api/style/preview',
                    {'frame_revision': '0' * 64, 'target_id': a,
                     'value': 8})[1]['status'] == 'STALE_REVISION'
        # commit without token refused
        status, prev, _ = _req(port, 'POST', '/api/style/preview',
                               {'frame_revision': rev, 'target_id': a, 'value': 8})
        assert status == 200
        body = {'candidate_id': prev['style']['candidate_id'],
                'frame_revision': rev, 'expected_sha256': ''}
        assert _req(port, 'POST', '/api/style/commit', body)[1]['status'] == 'FORBIDDEN'
        assert _req(port, 'POST', '/api/style/commit', body,
                    **{'X-Figpact-Ui': 'wrong'})[1]['status'] == 'FORBIDDEN'
        # wrong method/path refused
        assert _req(port, 'GET', '/api/style/preview')[0] == 404
        assert _req(port, 'POST', '/api/style/preview',
                    {'frame_revision': rev, 'target_id': a, 'value': 8},
                    **{'Origin': 'https://attacker.invalid'})[0] == 403
        # external overlay change invalidates preview + commit
        status, done, _ = _req(port, 'POST', '/api/style/commit', body,
                               **_ui(server))
        assert status == 200
        sha_now = _h(overlay)
        status, prev2, _ = _req(port, 'POST', '/api/style/preview',
                                {'frame_revision': done['frame']['frame_revision'],
                                 'target_id': b, 'value': 8})
        assert status == 200
        overlay.write_bytes(overlay.read_bytes() + b' ')
        status, conflict, _ = _req(port, 'POST', '/api/style/commit',
                                   {'candidate_id': prev2['style']['candidate_id'],
                                    'frame_revision': done['frame']['frame_revision'],
                                    'expected_sha256': sha_now}, **_ui(server))
        assert status == 409 and conflict['status'] == 'OVERLAY_CONFLICT'
        overlay.write_bytes(overlay.read_bytes()[:-1])  # restore valid bytes
        plt.close('all')


def test_remove_restores_original_and_retains_sibling(tmp_path):
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    with _server(tmp_path, overlay) as (server, port):
        rev = _req(port, 'GET', '/api/frame')[1]['frame_revision']
        for tid, val in ((a, 8), (b, 8), (a, 9)):
            status, prev, _ = _req(port, 'POST', '/api/style/preview',
                                   {'frame_revision': rev, 'target_id': tid, 'value': val})
            assert status == 200
            sha = prev['style']['overlay_sha256']
            status, done, _ = _req(port, 'POST', '/api/style/commit',
                                   {'candidate_id': prev['style']['candidate_id'],
                                    'frame_revision': rev, 'expected_sha256': sha},
                                   **_ui(server))
            assert status == 200
            rev = done['frame']['frame_revision']
        # remove A -> restores 10, retains B=8
        status, prev, _ = _req(port, 'POST', '/api/style/preview',
                               {'frame_revision': rev, 'target_id': a, 'remove': True})
        assert status == 200
        assert prev['style']['pending']['new_pt'] is None
        sha = prev['style']['overlay_sha256']
        status, done, _ = _req(port, 'POST', '/api/style/commit',
                               {'candidate_id': prev['style']['candidate_id'],
                                'frame_revision': rev, 'expected_sha256': sha},
                               **_ui(server))
        assert status == 200
        rows = {t['target_id']: t for t in done['style']['targets']}
        assert rows[a]['current_pt'] == 10.0 and rows[a]['saved_pt'] is None
        assert rows[b]['saved_pt'] == 8.0
        plt.close('all')
