"""Trusted, loopback-only G2 Inspector bridge; no save/publish/source-edit routes.

The browser only sends geometry intents. Script/config choices belong to the
local caller, never to HTTP requests. UI assets stay in tools/inspector/.
"""
from __future__ import annotations

import argparse
import http.server
import json
from pathlib import Path
from urllib.parse import urlsplit
from typing import cast

from .intents import IntentSession

FRONTEND = Path(__file__).resolve().parents[1] / 'tools' / 'inspector'
MAX_REQUEST_BYTES = 65536


class InspectorServer(http.server.HTTPServer):
    # Single request owner: Matplotlib and the accepted set are never concurrently mutated.
    def __init__(self, session: IntentSession, address: tuple[str, int] = ('127.0.0.1', 0), *, frontend=FRONTEND):
        if address[0] != '127.0.0.1':
            raise ValueError('Inspector 只允许绑定 127.0.0.1')
        self.session = session
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
            body = 'window.FIGPACT_INSPECTOR_FRAME=' + json.dumps(
                self._app.session.snapshot(), ensure_ascii=True, allow_nan=False) + ';\n'
            self._send(body, media='text/javascript; charset=utf-8')
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

    def do_POST(self):
        if not self._allowed():
            return
        routes = {'/api/intents/evaluate': self._app.session.evaluate,
                  '/api/intents/decision': self._app.session.decide,
                  '/api/frame/quality': self._app.session.set_quality}
        route = routes.get(urlsplit(self.path).path)
        if route is None:
            self._send({'status': 'NOT_FOUND'}, 404)
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self._send({'status': 'INVALID_INTENT', 'message': '必须使用 application/json'}, 415)
            return
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or not lengths[0].isdigit():
            self._send({'status': 'INVALID_INTENT', 'message': '必须有一个有效 Content-Length'}, 400)
            return
        length = int(lengths[0])
        if length > MAX_REQUEST_BYTES:
            self._send({'status': 'INVALID_INTENT', 'message': '请求超过 64 KiB'}, 413)
            return
        if length == 0:
            self._send({'status': 'INVALID_INTENT', 'message': '请求不能为空'}, 400)
            return
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
            return
        try:
            result = route(body)
        except (ValueError, RuntimeError, OSError) as error:
            self._send({'status': 'EVALUATION_FAILED', 'message': str(error)}, 400)
            return
        self._send(result)


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
    if args.script is not None:
        session = IntentSession(script=args.script, config=args.config, scope=args.scope, dpi=args.dpi)
    elif args.example == 'plain':
        figure = plain_figure()
        figure.set_dpi(args.dpi)
        session = IntentSession(figure=figure, scope='measurement')
    else:
        folder = Path(__file__).resolve().parents[1] / 'examples' / args.example
        session = IntentSession(script=folder / ('08 NMR.py' if args.example == 'nmr' else 'plot_ftir.py'),
                                config=folder / (args.example + '.yaml'), scope=args.scope, dpi=args.dpi)
    try:
        with session, InspectorServer(session, ('127.0.0.1', args.port), frontend=args.frontend) as server:
            print(f'Inspector: http://127.0.0.1:{server.server_address[1]}', flush=True)
            print('G2: session acceptance only; no source writes or publication', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        if figure is not None:
            plt.close(figure)


if __name__ == '__main__':
    main()
