"""G2 trusted loopback bridge: no remote origin, arbitrary file routes or source writes."""
from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager

from figpact.inspector_server import InspectorServer
from tests.test_intents import intent, make_session


@contextmanager
def running_server(session):
    server = InspectorServer(session)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()


def request(port, method, path, body=None, **headers):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    data = None if body is None else json.dumps(body)
    if data is not None:
        headers.setdefault('Content-Type', 'application/json')
    conn.request(method, path, data, headers)
    response = conn.getresponse()
    result = (response.status, response.read(), dict(response.getheaders()))
    conn.close()
    return result


def test_foreign_origin_and_rebinding_host_cannot_evaluate(tmp_path):
    session, protected = make_session(tmp_path)
    with session, running_server(session) as port:
        desired = intent(session)
        original = session.snapshot()['frame_revision']
        for headers in ({'Origin': 'https://attacker.invalid'},
                        {'Host': 'attacker.invalid'}, {'Sec-Fetch-Site': 'cross-site'}):
            status, _, _ = request(port, 'POST', '/api/intents/evaluate', desired, **headers)
            assert status == 403
            assert session.snapshot()['frame_revision'] == original
    assert all(path.read_bytes() == data for path, data in protected.items())


def test_routes_never_serve_scientific_inputs_or_accept_arbitrary_python(tmp_path):
    session, protected = make_session(tmp_path)
    with session, running_server(session) as port:
        for path in ['/../intent.yaml', '/%2e%2e/intent_plot.py', '/intent.yaml', '/source', '/api/execute']:
            status, _, _ = request(port, 'GET', path)
            assert status == 404
        for path in ['/api/execute', '/api/commit', '/api/publish']:
            assert request(port, 'POST', path, {'script': str(tmp_path / 'intent_plot.py')})[0] == 404
    assert all(path.read_bytes() == data for path, data in protected.items())


def test_wrong_media_type_and_oversize_request_do_not_modify_session(tmp_path):
    session, protected = make_session(tmp_path)
    with session, running_server(session) as port:
        desired = intent(session)
        original = session.snapshot()['frame_revision']
        assert request(port, 'POST', '/api/intents/evaluate', desired, **{'Content-Type': 'text/plain'})[0] == 415
        assert request(port, 'POST', '/api/intents/evaluate', {'padding': 'x' * 70000})[0] == 413
        assert session.snapshot()['frame_revision'] == original
    assert all(path.read_bytes() == data for path, data in protected.items())


def test_real_http_intent_returns_candidate_without_source_write(tmp_path):
    session, protected = make_session(tmp_path)
    with session, running_server(session) as port:
        status, body, headers = request(port, 'GET', '/api/frame')
        assert status == 200
        accepted = json.loads(body)
        assert headers['Cache-Control'] == 'no-store'
        status, body, _ = request(port, 'POST', '/api/intents/evaluate', intent(session))
        candidate = json.loads(body)
        assert status == 200 and candidate['status'] == 'OK', candidate
        assert candidate['measured_delta_mm'][1] == 0.15 or abs(candidate['measured_delta_mm'][1] - 0.15) < 1e-8
        assert json.loads(request(port, 'GET', '/api/frame')[1])['frame_revision'] == accepted['frame_revision']
    assert all(path.read_bytes() == data for path, data in protected.items())
