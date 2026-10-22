from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from PIL import Image

from figpact.host_server import HostServer, _Handler
from figpact.render_contract import validate_layout


@pytest.fixture
def server(tmp_path):
    instance = HostServer(tmp_path, "http://127.0.0.1:5173")
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def _request(server, method="GET", path="/session", *, token=None, origin=None, payload=None):
    headers = {"Host": f"127.0.0.1:{server.server_address[1]}"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}",
                                     data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.headers, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, error.headers, json.loads(error.read())


def test_session_requires_bearer_and_emits_only_authorized_cors(server):
    status, _, body = _request(server)
    assert status == 401 and body["status"] == "UNAUTHORIZED"
    status, headers, body = _request(server, token=server.token, origin="http://127.0.0.1:5173")
    assert status == 200
    assert body == {"schema": "figpact.host-session/1", "base_path": str(server.base), "panel_id": None}
    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    status, _, body = _request(server, token=server.token, origin="http://evil.example")
    assert status == 403 and body["status"] == "FORBIDDEN"


def test_unknown_route_and_strict_json_rejection(server):
    status, _, body = _request(server, token=server.token, path="/export")
    assert status == 404 and body["status"] == "NOT_FOUND"
    status, _, body = _request(server, "POST", "/frame", token=server.token,
                               payload=b'{"snapshot_revision":"x","request_id":NaN}')
    assert status == 400 and body["status"] == "INVALID"
    status, _, body = _request(server, "POST", "/frame", token=server.token,
                               payload={"snapshot_revision": "x", "request_id": True})
    assert status == 400 and body["status"] == "INVALID"


def test_bad_host_and_generation_payload_rejected(server):
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/session",
                                    headers={"Host": "localhost"})
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=3)
    assert caught.value.code == 403
    status, _, body = _request(server, "POST", "/capture", token=server.token,
                               payload={"instance_id": "browser", "generation": True})
    assert status == 400 and body["status"] == "INVALID"


def test_stale_canvas_revision_and_request_id_are_conflicts(server):
    layout = validate_layout({"schema": "figpact.layout/1", "source_mode": "live",
                              "page_mm": [100, 100], "objects": []})
    server._layout = layout
    server._capture_epoch = 1
    server._latest_request = 3
    status, _, body = _request(server, "POST", "/frame", token=server.token,
                               payload={"snapshot_revision": "0" * 64, "request_id": 4})
    assert status == 409 and body["status"] == "STALE_SNAPSHOT"
    status, _, body = _request(server, "POST", "/frame", token=server.token,
                               payload={"snapshot_revision": layout["revision"], "request_id": 2})
    assert status == 409 and body["status"] == "STALE_REQUEST"


def test_managed_guard_rejects_override_replay(server, tmp_path):
    script, config = tmp_path / "plot.py", tmp_path / "plot.yaml"
    script.touch()
    config.touch()
    server.render_session = SimpleNamespace(script=script, config=config, scope="main")
    handler = object.__new__(_Handler)
    handler._app = server
    layout = validate_layout({
        "schema": "figpact.layout/1", "source_mode": "live", "page_mm": [100, 100],
        "objects": [],
        "extensions": {"tavotto_live": {"objects": {
            "panel": {"record": {"renderOwner": "figpact", "script": "plot.py",
                                  "figpact": {"config": "plot.yaml", "scope": "main"},
                                  "overrides": [{"gid": "title", "prop": "fontsize", "value": 9}]}}
        }}}
    })
    with pytest.raises(Exception, match="override"):
        handler._managed_record(layout, "panel")


def test_equal_generation_rechecks_resource_revision_and_invalidates_stale_proof(server, tmp_path):
    image_path = tmp_path / "photo.png"
    Image.new("RGB", (8, 6), "red").save(image_path)
    payload = {
        "instance_id": "browser", "generation": 7, "document_id": "doc",
        "canvas_id": "canvas", "project_root": str(server.base),
        "document": {
            "schema": 3, "project": {"id": "doc", "name": "Project"},
            "canvases": [{
                "id": "canvas", "name": "Page", "page": {"w": 180, "h": 150},
                "objects": [{
                    "id": "panel", "type": "panel", "fileId": "photo.png",
                    "fileKind": "raster", "nativeW": 100, "nativeH": 80,
                    "x": 10, "y": 20, "w": 40, "h": 32,
                    "figureFrame": 1, "overrides": [],
                }],
            }],
            "updatedAt": 123,
        },
    }
    status, _, first = _request(server, "POST", "/capture", token=server.token, payload=payload)
    assert status == 200
    first_layout = first["layout"]
    first_resource_revision = first_layout["objects"][0]["resource_revision"]
    status, _, snapshot = _request(server, token=server.token, path="/snapshot")
    assert status == 200 and snapshot["layout"]["revision"] == first_layout["revision"]

    payload["document"]["updatedAt"] = 456
    status, _, repeated = _request(server, "POST", "/capture", token=server.token, payload=payload)
    assert status == 200 and repeated["layout"]["revision"] == first_layout["revision"]

    Image.new("RGB", (8, 6), "blue").save(image_path)
    status, _, body = _request(server, "POST", "/capture", token=server.token, payload=payload)
    assert status == 409 and body["status"] == "STALE_GENERATION"
    status, _, body = _request(server, token=server.token, path="/snapshot")
    assert status == 409 and body["status"] == "NO_CAPTURE"

    payload["generation"] = 8
    status, _, recovered = _request(server, "POST", "/capture", token=server.token, payload=payload)
    assert status == 200
    assert recovered["layout"]["revision"] != first_layout["revision"]
    assert recovered["layout"]["objects"][0]["resource_revision"] != first_resource_revision


def test_trusted_render_snapshot_freshness_rejects_old_source_revision(server):
    current = {"candidate_revision": "candidate-new", "source_revision": "source-new",
               "base_config_revision": "config-new", "frame_revision": "frame-new"}
    server.render_session = SimpleNamespace(snapshot=lambda: {"frame": current})
    stale = {**current, "source_revision": "source-old"}
    with pytest.raises(Exception, match="changed"):
        server._fresh_frame(stale)
   
