"""Loopback-only setup, protected by one-use access, session and CSRF tokens."""
import argparse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from .app import Session
from .model import SetupError, check

STATIC = Path(__file__).parent / 'web'
SOURCE = Path(__file__).resolve().parents[1]


def make_server(session, port):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'InboxTetherSetup'

        def log_message(self, *args):
            pass  # URLs, cookies, passwords and request bodies are never logged.

        def send(self, status, body, content_type='application/json', cookie=None):
            raw = json.dumps(body).encode() if content_type == 'application/json' else body
            self.send_response(status)
            for key, value in {'Content-Type': content_type, 'Content-Length': str(len(raw)),
                               'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                               'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
                               'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}.items():
                self.send_header(key, value)
            if cookie:
                self.send_header('Set-Cookie', 'ibt_setup='+cookie+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=3600')
            self.end_headers()
            self.wfile.write(raw)

        def origin(self, write=False):
            host = '127.0.0.1:'+str(self.server.server_port)
            check(self.headers.get('Host') == host, 'host', 'Use the loopback setup address printed in Terminal.')
            origin = self.headers.get('Origin')
            check((origin == 'http://'+host) if write else origin in (None, 'http://'+host),
                  'origin', 'Cross-site setup requests are not permitted.')

        def cookie(self):
            parsed = SimpleCookie(self.headers.get('Cookie', ''))
            return parsed['ibt_setup'].value if 'ibt_setup' in parsed else None

        def do_GET(self):
            try:
                self.origin()
                files = {'/': ('index.html', 'text/html; charset=utf-8'),
                         '/app.js': ('app.js', 'application/javascript'), '/style.css': ('style.css', 'text/css'),
                         '/connect_claude.py': ('connect_claude.py', 'text/plain; charset=utf-8'),
                         '/icon.png': (None, 'image/png')}
                if self.path in files:
                    name, kind = files[self.path]
                    p = STATIC / name if name else SOURCE / 'assets/plugin-icon-256.png'
                    self.send(200, p.read_bytes(), kind)
                elif self.path == '/api/status':
                    session.authorize(self.cookie())
                    self.send(200, session.status())
                else:
                    self.send(404, {'error': {'code': 'route', 'message': 'Setup page not found.'}})
            except SetupError as error:
                self.send(403, {'error': {'code': error.code, 'message': error.message}})
            except Exception:
                self.send(400, {'error': {'code': 'request', 'message': 'The setup request could not be processed.'}})

        def do_POST(self):
            try:
                self.origin(write=True)
                check(self.headers.get('Content-Type') == 'application/json' and self.headers.get('Transfer-Encoding') is None,
                      'request', 'Use the installation form to submit JSON setup requests.')
                length = self.headers.get('Content-Length', '')
                check(length.isdigit() and 0 < int(length) <= 65536, 'request_size', 'The setup request is outside its permitted size.')
                value = json.loads(self.rfile.read(int(length)))
                if self.path == '/api/session':
                    if value == {}:
                        session.authorize(self.cookie())
                        self.send(200, {'csrf': session.csrf})
                        return
                    check(type(value) is dict and set(value) == {'ticket'}, 'fields', 'Use the private setup link.')
                    cookie, csrf = session.authenticate(value['ticket'])
                    self.send(200, {'csrf': csrf}, cookie=cookie)
                    return
                session.authorize(self.cookie(), self.headers.get('X-InboxTether-CSRF'), write=True)
                if self.path == '/api/finish':
                    check(value == {} and session.result is not None and not session.busy(), 'state', 'Installation has not completed successfully.')
                    session.clear()
                    session.cookie = session.csrf = None
                    self.send(200, {'closed': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                self.send(200, session.dispatch(self.path, value))
            except SetupError as error:
                self.send(400, {'error': {'code': error.code, 'message': error.message}})
            except Exception:
                self.send(400, {'error': {'code': 'request', 'message': 'Setup could not validate this request. No automatic retry was made.'}})
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description='Temporary InboxTether initial installation for Ubuntu 24.04')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--recover', action='store_true', help='Guarded cleanup of an interrupted initial installation only')
    args = parser.parse_args()
    from .install import platform_check, recover
    platform_check()
    if args.recover:
        check(sys.stdin.isatty(), 'recovery', 'Use your own administrator Terminal for recovery.')
        print('This removes only recorded, unfinished setup resources. It never removes a completed installation or changes email.')
        check(input('Type REMOVE-INCOMPLETE-INSTALL to continue: ') == 'REMOVE-INCOMPLETE-INSTALL', 'recovery', 'Recovery was not confirmed.')
        print('Protected diagnostics retained at '+recover())
        return
    check(1024 <= args.port <= 65535, 'port', 'Choose a local setup port from 1024 to 65535.')
    session = Session(SOURCE)
    server = make_server(session, args.port)
    print('InboxTether initial installation — temporary, local access only.', flush=True)
    print('For a remote server, forward the SAME port through your existing authenticated SSH connection.', flush=True)
    print('Open this private link in your own browser; do not share it or enter passwords into chat:', flush=True)
    print('http://127.0.0.1:'+str(server.server_port)+'/#'+session.bootstrap, flush=True)
    def expiry():
        while not getattr(server, '_BaseServer__shutdown_request', False):
            time.sleep(5)
            if session.expired():
                session.clear(); server.shutdown(); return
    threading.Thread(target=expiry, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nSetup stopped. If installation was interrupted, use --recover before another attempt.', file=sys.stderr)
    finally:
        server.server_close()
        if session.job is not None and session.job.is_alive():
            session.job.join()
        session.clear()


if __name__ == '__main__':
    try:
        main()
    except SetupError as error:
        raise SystemExit(error.message) from None
