"""Trusted, loopback-only G2 Inspector bridge; no save/publish/source-edit routes.

The browser only sends geometry intents. Script/config choices belong to the
local caller, never to HTTP requests. UI assets stay in tools/inspector/.

G5a adds read-only selection and task coordination (``/api/selection``,
``/api/tasks``) through an in-memory SessionHub. It still grants neither source
writes nor publishing.

G5b adds a constrained source-write path (``/api/plans`` series): a plan is minted
by the server (zero bytes written to user source), the *page* consents with the
per-served-page token the server injects into ``/frame.js`` (``window.FIGPACT_UI_TOKEN``),
and the *client that requested that plan* applies it only while every file still
matches the plan's ``before_sha256``. Body fields never authorize anything: this is
single-machine, single-user consent (loopback + same-origin + page session token),
not multi-user authentication.
"""
from __future__ import annotations

import argparse
import http.server
import json
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from typing import cast

from .hub import CLIENT_HEADER, UI_TOKEN_HEADER, SessionHub
from .intents import IntentSession

FRONTEND = Path(__file__).resolve().parents[1] / 'tools' / 'inspector'
MAX_REQUEST_BYTES = 65536
#: ``/api/plans/<plan_id>/<action>``：只有这三个动作，其它一律 404。
PLAN_ACTIONS = ('authorize', 'apply', 'cancel')


def _plan_route(path: str):
    """``/api/plans/<id>/<action>`` → (plan_id, action)；不是这个形状返回 None。"""
    parts = path.strip('/').split('/')
    if len(parts) == 4 and parts[:2] == ['api', 'plans'] and parts[3] in PLAN_ACTIONS:
        return parts[2], parts[3]
    return None


class InspectorServer(http.server.HTTPServer):
    # Single request owner: Matplotlib and the accepted set are never concurrently mutated.
    def __init__(self, session: IntentSession, address: tuple[str, int] = ('127.0.0.1', 0), *,
                 frontend=FRONTEND, state_home=None, source=None):
        if address[0] != '127.0.0.1':
            raise ValueError('Inspector 只允许绑定 127.0.0.1')
        self.session = session
        # 页面会话令牌：服务这个页面时签发、注入 /frame.js；授权请求必须原样带回来。
        self.ui_token = secrets.token_urlsafe(32)
        self.hub = SessionHub(state_home=state_home, source=source, ui_token=self.ui_token)
        self.frontend = Path(frontend).resolve()
        super().__init__(address, _Handler)


class _Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self._app = cast(InspectorServer, self.server)
        self.connection.settimeout(15)
        self._body_consumed = False

    def log_message(self, format, *args):
        pass

    def _send(self, body, code=200, media='application/json; charset=utf-8'):
        if code >= 400 and self.command == 'POST' and not self._body_consumed:
            # Windows may reset an error response if the receive queue is unread.
            # Drain only a bounded rejected body; large/slow requests may disconnect.
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) == 1 and lengths[0].isdigit():
                self.connection.settimeout(1)
                try:
                    self.rfile.read(min(int(lengths[0]), 2 * MAX_REQUEST_BYTES))
                except OSError:
                    pass
            self.close_connection = True
        if media.startswith('application/json'):
            body = json.dumps(body, ensure_ascii=True, allow_nan=False).encode('utf8')
        elif isinstance(body, str):
            body = body.encode('utf8')
        self.send_response(code)
        self.send_header('Content-Type', media)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self):
        port = self._app.server_port
        origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if (self.headers.get('Host') not in hosts or
                self.headers.get('Origin') not in (None, *origins) or
                self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none')):
            self._send({'status': 'FORBIDDEN', 'message': '仅允许本机同源 Inspector 页面'}, 403)
            return False
        return True

    def do_GET(self):
        if not self._allowed():
            return
        path = urlsplit(self.path).path
        if path == '/api/frame':
            self._send(self._app.session.snapshot())
            return
        if path == '/frame.js':
            # 既有 frame 行为字节不变，只追加一行：页面会话令牌（授权请求必须带回来的那个）。
            body = ('window.FIGPACT_INSPECTOR_FRAME=' + json.dumps(
                self._app.session.snapshot(), ensure_ascii=True, allow_nan=False) + ';\n'
                'window.FIGPACT_UI_TOKEN=' + json.dumps(self._app.ui_token) + ';\n')
            self._send(body, media='text/javascript; charset=utf-8')
            return
        if path == '/api/selection':
            self._send(*self._app.hub.read_selection(self._app.session))
            return
        if path == '/api/tasks':
            self._send(*self._app.hub.read_tasks())
            return
        if path == '/api/plans':
            self._send(*self._app.hub.read_plans())
            return
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/index.html': ('index.html', 'text/html; charset=utf-8'),
                  '/inspector.js': ('inspector.js', 'text/javascript; charset=utf-8'),
                  '/inspector.css': ('inspector.css', 'text/css; charset=utf-8')}
        if path not in assets:
            self._send({'status': 'NOT_FOUND'}, 404)
            return
        name, media = assets[path]
        try:
            body = (self._app.frontend / name).read_bytes()
        except OSError:
            self._send({'status': 'NOT_FOUND', 'message': 'Inspector 静态资源不存在'}, 404)
            return
        self._send(body, media=media)

    def _json_body(self):
        """共享的 Content-Type / Content-Length / 64 KiB / JSON 校验；失败时直接回包并返回 None。"""
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self._send({'status': 'INVALID_INTENT', 'message': '必须使用 application/json'}, 415)
            return None
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or not lengths[0].isdigit():
            self._send({'status': 'INVALID_INTENT', 'message': '必须有一个有效 Content-Length'}, 400)
            return None
        length = int(lengths[0])
        if length > MAX_REQUEST_BYTES:
            self._send({'status': 'INVALID_INTENT', 'message': '请求超过 64 KiB'}, 413)
            return None
        if length == 0:
            self._send({'status': 'INVALID_INTENT', 'message': '请求不能为空'}, 400)
            return None
        try:
            def invalid_constant(_):
                raise ValueError('JSON 不能包含 NaN/Infinity')
            raw = self.rfile.read(length)
            self._body_consumed = True
            body = json.loads(raw, parse_constant=invalid_constant)
            if not isinstance(body, dict):
                raise ValueError('请求必须是 JSON 对象')
        except (ValueError, UnicodeError, TimeoutError) as error:
            self._send({'status': 'INVALID_INTENT', 'message': str(error)}, 400)
            return None
        return body

    def _plan_body(self):
        """计划动作路由的输入在路径与 header 上：body 可选，给了仍走既有 JSON 校验。

        body 里的任何字段都不参与授权判定——``{"authorized": true}`` 在这里只是一段被忽略
        的 JSON，授权来自注入页面的会话令牌与 grant。
        """
        lengths = self.headers.get_all('Content-Length', [])
        if not lengths or (len(lengths) == 1 and lengths[0] == '0'):
            self._body_consumed = True
            return {}
        return self._json_body()

    def _plan_action(self, plan_id, action):
        if action == 'authorize':
            return self._app.hub.authorize_plan(plan_id, self.headers.get(UI_TOKEN_HEADER))
        if action == 'apply':
            return self._app.hub.apply_plan(plan_id, self.headers.get(CLIENT_HEADER))
        return self._app.hub.cancel_plan(plan_id)

    def do_POST(self):
        if not self._allowed():
            return
        path = urlsplit(self.path).path
        plan = _plan_route(path)
        routes = {'/api/intents/evaluate': self._app.session.evaluate,
                  '/api/intents/decision': self._app.session.decide,
                  '/api/frame/quality': self._app.session.set_quality}
        route = routes.get(path)
        if route is None and plan is None and path not in ('/api/selection', '/api/tasks',
                                                           '/api/plans'):
            self._send({'status': 'NOT_FOUND'}, 404)
            return
        body = self._json_body() if plan is None else self._plan_body()
        if body is None:
            return
        try:
            if plan is not None:
                result, code = self._plan_action(*plan)
            elif path == '/api/selection':
                result, code = self._app.hub.publish_selection(body)
            elif path == '/api/tasks':
                result, code = self._app.hub.submit_task(body, self._app.session)
            elif path == '/api/plans':
                result, code = self._app.hub.create_plan(body)
            else:
                result, code = route(body), 200
        except (ValueError, RuntimeError, OSError) as error:
            self._send({'status': 'EVALUATION_FAILED', 'message': str(error)}, 400)
            return
        self._send(result, code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', choices=('plain', 'nmr', 'ftir'), default='plain')
    parser.add_argument('--script', type=Path, help='Explicitly trusted local script, never supplied by HTTP')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--scope', default='main')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--dpi', type=int, choices=(120, 240, 600), default=600,
                        help='Display resolution only; originals and publication files are never changed')
    parser.add_argument('--frontend', type=Path, default=FRONTEND,
                        help='Trusted local Inspector assets (development worktree only)')
    args = parser.parse_args()
    if bool(args.script) != bool(args.config):
        parser.error('--script 和 --config 必须同时指定')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from tools.inspector_demo import plain_figure
    figure = None
    source = None
    if args.script is not None:
        session = IntentSession(script=args.script, config=args.config, scope=args.scope, dpi=args.dpi)
        # history 工作区身份：G5b 授权写入的 source_change 检查点落在同一个工作区里。
        source = {'script': str(args.script), 'config': str(args.config), 'scope': args.scope}
    elif args.example == 'plain':
        figure = plain_figure()
        figure.set_dpi(args.dpi)
        session = IntentSession(figure=figure, scope='measurement')
    else:
        folder = Path(__file__).resolve().parents[1] / 'examples' / args.example
        script = folder / ('08 NMR.py' if args.example == 'nmr' else 'plot_ftir.py')
        config = folder / (args.example + '.yaml')
        session = IntentSession(script=script, config=config, scope=args.scope, dpi=args.dpi)
        source = {'script': str(script), 'config': str(config), 'scope': args.scope}
    try:
        with session, InspectorServer(session, ('127.0.0.1', args.port), frontend=args.frontend,
                                      source=source) as server:
            print(f'Inspector: http://127.0.0.1:{server.server_address[1]}', flush=True)
            print('G2/G5a: session acceptance only; G5b source writes land only after the page '
                  'session token consents to a minted plan', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        if figure is not None:
            plt.close(figure)


if __name__ == '__main__':
    main()
