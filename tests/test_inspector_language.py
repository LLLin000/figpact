"""Selected-language HTTP authority uses real frames/preview, no live model dependency."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
from typing import Any
import threading
from unittest.mock import patch
from urllib import error, request

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from figpact.inspector_server import InspectorServer
from figpact.inspector_style import StyleSession
from figpact.intents import IntentSession
from figpact import sample


@contextmanager
def opened(directory):
    script = directory / 'curve.py'
    shutil.copyfile(Path(sample.__file__), script)
    style = StyleSession(script=script, config=None, scope='main', overlay=directory / 'style.json')
    fig, reg = sample.build_figure_and_registry()
    session = IntentSession(figure=fig, registry=reg, scope='main')
    server = InspectorServer(session, style=style)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, style, script
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        style._drop_pending()
        session.close()
        plt.close(fig)


def post(server, body, token=True):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-Figpact-Ui'] = server.ui_token
    req = request.Request(f'http://127.0.0.1:{server.server_port}/api/language/preview',
                          data=json.dumps(body).encode(), headers=headers)
    try:
        response = request.urlopen(req)
    except error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.load(response)


def selected(style):
    frame = style.snapshot()
    target = next(t for t in frame['style']['targets'] if t['label'] == 'ylabel')
    return {'frame_revision': frame['frame_revision'], 'scene_id': target['scene_ids'][0],
            'target_id': target['target_id'], 'request': '改为9pt'}


def response_plan(packet, config, control) -> dict[str, Any]:
    context = packet['input']['context']
    return {'status': 'READY', 'route': 'overlay', 'scope': context['scope'],
            'revision': context['revision'], 'edits': [{'control_id': control['id'], 'value': 9.0}],
            'preserve': ['science', 'view'], 'reason': 'Selected label, 9 pt'}


def test_language_preview_requires_page_token_and_exact_selected_scene(tmp_path):
    with opened(tmp_path) as (server, style, _):
        body = selected(style)
        assert post(server, body, token=False)[0] == 403
        bad = {**body, 'scene_id': 'not-selected'}
        assert post(server, bad)[0] == 400
        assert style.snapshot()['style'].get('pending') is None
        assert not style.overlay.exists()


def test_selected_language_real_candidate_does_not_save_before_confirmation(tmp_path):
    with opened(tmp_path) as (server, style, _):
        with patch('figpact.language_edit.model_plan', response_plan):
            code, reply = post(server, selected(style))
        assert code == 200
        assert reply['style']['pending']['new_pt'] == 9.0
        assert reply['style']['pending']['target_id'] == reply['language']['selected_target']['target_id']
        assert reply['style']['receipt']['science_unchanged'] is True
        assert not style.overlay.exists()
        assert post(server, selected(style))[0] == 409  # cannot overwrite unconfirmed candidate


def test_model_cannot_edit_another_target_or_use_boolean_values(tmp_path):
    with opened(tmp_path) as (server, style, _):
        for invalid in ('other-control', True):
            def malformed(packet, config, control):
                plan = response_plan(packet, config, control)
                if invalid == 'other-control':
                    plan['edits'][0]['control_id'] = 'other-control'
                else:
                    plan['edits'][0]['value'] = invalid
                return plan
            with patch('figpact.language_edit.model_plan', malformed):
                assert post(server, selected(style))[0] == 422
            assert not style.overlay.exists()
            assert style.snapshot()['style'].get('pending') is None


def test_source_drift_is_refused_even_if_rendered_pixels_would_not_change(tmp_path):
    with opened(tmp_path) as (server, style, script):
        body = selected(style)
        script.write_bytes(script.read_bytes() + b'\n# source changed\n')
        code, reply = post(server, body)
        assert code == 409 and reply['status'] == 'STALE_SOURCE'
        assert not style.overlay.exists()


def test_api_key_never_enters_frame_or_language_state(tmp_path, monkeypatch):
    monkeypatch.setenv('FIGPACT_MODEL_API_KEY', 'test-secret-not-for-browser')
    with opened(tmp_path) as (server, _, _):
        for path in ('/frame.js', '/api/language/state'):
            with request.urlopen(f'http://127.0.0.1:{server.server_port}{path}') as response:
                assert b'test-secret-not-for-browser' not in response.read()
