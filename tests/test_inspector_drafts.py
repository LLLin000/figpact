"""WorkspaceDraftUI backend drafts (owner: WorkspaceDraftUI).

Real StyleSession + HTTP, no run until parent. Covers: inherited math/low-text
label change accepted as pending draft (explicit save_draft commit ->
COMMITTED_DRAFT, workspace reload same frame/state), reopen continued edit,
newly-bad text/glyph QA rejected despite explicit draft, commit refresh
failure preserved for draft + normal, geometry route untouched.

Real FTIR draft (G19): axis label 8.5->9.5 local PASS + whole FAIL inherited
4.7pt glyph floor only (qa_delta eligible) -> COMMITTED_DRAFT, reload
continues a second edit; heavier new/worse edits still rejected. Slow:
parent runs finally.
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


def test_normal_pass_acceptance_g15b(tmp_path):
    """G15b normal-PASS acceptance (NOT a draft): label 8→COMMITTED; save_draft key strict."""
    a, _b = _ids()
    overlay = tmp_path / 'style.json'
    with _server(tmp_path, overlay) as (server, port):
        frame = _req(port, 'GET', '/api/frame')[1]
        rev = frame['frame_revision']
        status, prev, _ = _req(port, 'POST', '/api/style/preview',
                               {'frame_revision': rev, 'target_id': a, 'value': 8})
        # G15b 8 keeps whole PASS: this is the normal path, not a draft.
        assert status == 200 and prev['status'] == 'OK', prev
        assert not prev['style']['pending'].get('is_draft'), prev['style']['pending']
        cand = prev['style']['candidate_id']
        sha = prev['style']['overlay_sha256']
        status, done, _ = _req(port, 'POST', '/api/style/commit',
                               {'candidate_id': cand, 'frame_revision': rev,
                                'expected_sha256': sha}, **_ui(server))
        assert status == 200 and done['status'] == 'COMMITTED', done
        # strict keys: save_draft must be bool when present
        status, prev2, _ = _req(port, 'POST', '/api/style/preview',
                                {'frame_revision': done['frame']['frame_revision'],
                                 'target_id': a, 'value': 9})
        assert status == 200, prev2
        bad = _req(port, 'POST', '/api/style/commit',
                   {'candidate_id': prev2['style']['candidate_id'],
                    'frame_revision': prev2['style']['pending']['base_frame_revision'],
                    'expected_sha256': prev2['style']['pending']['expected_sha256'],
                    'save_draft': 'yes'}, **_ui(server))
        assert bad[0] == 400 and bad[1]['status'] == 'INVALID', bad
        plt.close('all')


def test_draft_rejected_new_bad_text_glyph_despite_explicit(tmp_path):
    """A newly-bad glyph/wholeFAIL candidate is rejected; explicit draft no bypass."""
    a, _ = _ids()
    overlay = tmp_path / 'style.json'
    with _server(tmp_path, overlay) as (server, port):
        frame = _req(port, 'GET', '/api/frame')[1]
        status, refused, _ = _req(port, 'POST', '/api/style/preview',
                                  {'frame_revision': frame['frame_revision'],
                                   'target_id': a, 'value': 4})
        assert status == 400, refused
        assert refused['receipt']['local_edit_state'] == 'PASS'
        assert refused['receipt']['figure_verification_state'] == 'FAIL'
        delta = refused['receipt'].get('qa_delta') or {}
        assert delta.get('new') or delta.get('worsened') or not delta.get('eligible', True)
        assert not overlay.exists()
        plt.close('all')


def test_commit_refresh_failure_preserved_for_draft_and_normal(tmp_path):
    """Post-commit rebuild failure keeps COMMITTED truth for draft + normal."""
    a, _b = _ids()
    overlay = tmp_path / 'style.json'
    with _server(tmp_path, overlay) as (server, port):
        rev = _req(port, 'GET', '/api/frame')[1]['frame_revision']
        status, prev, _ = _req(port, 'POST', '/api/style/preview',
                               {'frame_revision': rev, 'target_id': a, 'value': 8})
        assert status == 200, prev
        real_rebuild = server.style._rebuild

        def _boom(overlay_path=None):
            raise RuntimeError('injected post-commit rebuild failure')

        server.style._rebuild = _boom
        try:
            status, done, _ = _req(port, 'POST', '/api/style/commit',
                                   {'candidate_id': prev['style']['candidate_id'],
                                    'frame_revision': rev, 'expected_sha256': ''},
                                   **_ui(server))
        finally:
            server.style._rebuild = real_rebuild
        assert status == 200, done
        assert done['status'] in ('COMMITTED', 'COMMITTED_DRAFT'), done
        assert done['frame'] is None and done['style']['refresh_required'] is True
        plt.close('all')


FTIR_SCRIPT = ROOT / 'examples' / 'ftir' / 'plot_ftir.py'
FTIR_CONFIG = ROOT / 'examples' / 'ftir' / 'ftir.yaml'
FTIR_YL = 'main.ax[gid=fig2_ftir.main.panel+sfaa9659a].ylabel.fontsize'


def test_real_ftir_draft_save_reload_continue(tmp_path):
    """A真实FTIR: label 8.5->9.5 localPASS + wholeFAIL inherited -> draft save + reload."""
    pytest.importorskip('yaml')
    # Serve the repo originals read-only (overlay stays in tmp): plot_ftir.py
    # resolves its figpact import root + data dir from its own ancestors, so a
    # /tmp copy breaks the import (StopIteration). Nothing here writes to the
    # script dir — frozen hashes prove the originals untouched.
    frozen = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
        FTIR_SCRIPT, FTIR_CONFIG, FTIR_SCRIPT.parent / 'figure_style.py')}
    script, config = FTIR_SCRIPT, FTIR_CONFIG
    overlay = tmp_path / 'style.json'
    from figpact.final_size import _build_figure, _import_script, _load_config
    import copy
    module = _import_script(script.resolve())
    cfg = _load_config(module, script.resolve(), config.resolve())
    (figure, _reg), _resolved = _build_figure(module, copy.deepcopy(cfg), 'main')
    session = IntentSession(figure=figure, scope='main')
    style = StyleSession(script=script, config=config, scope='main', overlay=overlay)
    server = InspectorServer(session, ('127.0.0.1', 0), style=style)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        ui = {'X-Figpact-Ui': server.ui_token}
        frame = _req(port, 'GET', '/api/frame')[1]
        rev = frame['frame_revision']
        status, prev, _ = _req(port, 'POST', '/api/style/preview',
                               {'frame_revision': rev, 'target_id': FTIR_YL, 'value': 9.5})
        assert status == 200 and prev['status'] == 'OK', prev
        pend = prev['style']['pending']
        assert pend.get('is_draft') is True, pend
        rec = prev['style']['receipt']
        assert rec['local_edit_state'] == 'PASS'
        assert rec['figure_verification_state'] == 'FAIL'
        assert (rec.get('qa_delta') or {}).get('eligible') is True
        cand = prev['style']['candidate_id']
        status2, noforce, _ = _req(port, 'POST', '/api/style/commit',
                                   {'candidate_id': cand, 'frame_revision': rev,
                                    'expected_sha256': ''}, **ui)
        assert status2 == 409 and noforce['status'] == 'DRAFT_REQUIRES_EXPLICIT_SAVE', noforce
        assert not overlay.exists()
        # explicit-save refusal invalidates the candidate (fail-closed): re-preview then save
        status_re, prev_re, _ = _req(port, 'POST', '/api/style/preview',
                                     {'frame_revision': rev, 'target_id': FTIR_YL, 'value': 9.5})
        assert status_re == 200 and prev_re['status'] == 'OK', prev_re
        assert prev_re['style']['pending'].get('is_draft') is True
        cand = prev_re['style']['candidate_id']
        status3, done, _ = _req(port, 'POST', '/api/style/commit',
                                {'candidate_id': cand, 'frame_revision': rev,
                                 'expected_sha256': '', 'save_draft': True}, **ui)
        assert status3 == 200 and done['status'] == 'COMMITTED_DRAFT', done
        assert done['style']['receipt']['source_commit_state'] == 'COMMITTED_DRAFT'
        assert done['style']['receipt']['figure_verification_state'] == 'FAIL'
        assert overlay.exists()
        style2 = StyleSession(script=script, config=config, scope='main', overlay=overlay)
        try:
            snap = style2.snapshot()
            assert snap['style'].get('workspace_draft') is True
            assert snap['style'].get('issue_count', 0) >= 1
            row = {t['target_id']: t for t in snap['style']['targets']}[FTIR_YL]
            assert row['saved_pt'] == 9.5 and row['current_pt'] == 9.5
        finally:
            style2._drop_pending()
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
        session.close()
        plt.close(figure)
    assert {q: hashlib.sha256(q.read_bytes()).hexdigest() for q in frozen} == frozen, '动了 FTIR 源码原件'
