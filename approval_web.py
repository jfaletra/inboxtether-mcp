"""Browser review behind OAuth2 Proxy/OIDC; served only over a private Unix socket.

No MCP registration, mailbox credentials, direct draft-store access or IMAP calls.
An authenticated session authorizes individual decisions, not an approve-all grant.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from html import escape
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import time
from urllib.parse import parse_qs, urlsplit

import jwt
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from approval_broker import BrokerClient
from draft_assistant import ID, canonical, https_url, require, text

COOKIE = '__Host-inboxtether-review'
CSS = '''body{font:17px system-ui,sans-serif;color:#14253d;background:#f3f6fa;margin:0}
main{max-width:850px;margin:2rem auto;background:white;padding:2rem;border-radius:12px}
h1{color:#123764}dt{font-weight:700;margin-top:1rem}dd{margin:.35rem 0;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#f3f6fa;padding:1rem}
.notice{border-left:4px solid #1685bf;padding:1rem}button{font:inherit;padding:.8rem 1.2rem;
border:1px solid #123764;border-radius:6px;background:#123764;color:white;margin:.4rem}
.reject{background:white;color:#123764}form{display:inline}summary{cursor:pointer}
@media(max-width:600px){main{margin:0;padding:1rem;border-radius:0}}'''


def private_key(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe CSRF key file.')
        value = os.read(fd, 33)
        require(len(value) == 32, 'CSRF key must be exactly 32 random bytes.')
        return value
    finally:
        os.close(fd)


@dataclass(frozen=True)
class WebConfig:
    origin: str
    issuer: str
    audience: str
    subject: str
    jwks_url: str
    broker_socket: Path
    web_socket: Path
    csrf_key: bytes

    @classmethod
    def load(cls):
        require(os.environ.get('INBOXTETHER_DRAFT_ASSISTANT', '0') == '1'
                and os.environ.get('INBOXTETHER_BROWSER_APPROVAL', '0') == '1', 'Browser approval is disabled.')
        origin = https_url(os.environ.get('INBOXTETHER_REVIEW_ORIGIN', ''), origin=True)
        issuer = https_url(os.environ.get('INBOXTETHER_APPROVAL_ISSUER', ''))
        subject = text(os.environ.get('INBOXTETHER_APPROVAL_SUBJECT', ''), 256)
        audience = text(os.environ.get('INBOXTETHER_APPROVAL_AUDIENCE', ''), 256)
        jwks = https_url(os.environ.get('INBOXTETHER_APPROVAL_JWKS_URL', ''))
        paths = [Path(os.environ.get(name, '')) for name in
                 ('INBOXTETHER_APPROVAL_SOCKET', 'INBOXTETHER_WEB_SOCKET', 'INBOXTETHER_CSRF_KEY_FILE')]
        require(all(p.is_absolute() for p in paths))
        return cls(origin, issuer, audience, subject, jwks, paths[0], paths[1], private_key(paths[2]))


class OIDCVerifier:
    """Use PyJWT for signature/claim validation; never trust identity headers."""
    def __init__(self, config):
        self.config = config
        # Only the operator's HTTPS JWKS URL is used, never token jku/x5u URLs.
        self.keys = jwt.PyJWKClient(config.jwks_url, timeout=5, lifespan=300)

    def __call__(self, authorization):
        require(isinstance(authorization, str) and authorization.startswith('Bearer ')
                and len(authorization) <= 16384, 'Authentication required.')
        token = authorization[7:]
        header = jwt.get_unverified_header(token)
        require(header.get('alg') == 'RS256' and not header.get('crit'), 'Unsupported authentication token.')
        key = self.keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], audience=self.config.audience,
                            issuer=self.config.issuer, options={
                                'require': ['iss', 'sub', 'aud', 'exp', 'iat'], 'strict_aud': True})
        require(claims.get('sub') == self.config.subject and claims.get('azp', self.config.audience) == self.config.audience,
                'This account is not authorized for this mailbox.')
        # No email-address identity mapping; issuer+immutable subject is the principal.
        return {'issuer': claims['iss'], 'subject': claims['sub']}


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def session_nonce(request):
    # A separate opaque CSRF session nonce; authentication is always revalidated.
    values = []
    for header, value in request.scope['headers']:
        if header == b'cookie':
            for part in value.decode('latin-1').split(';'):
                key, _, data = part.strip().partition('=')
                if key == COOKIE:
                    values.append(data)
    if not values:
        return None
    require(len(values) == 1 and re.fullmatch(r'[0-9a-f]{64}', values[0]), 'Invalid review session.')
    return values[0]


class CSRF:
    def __init__(self, key):
        self.key = key

    def issue(self, principal, nonce, item, decision):
        data = {'principal': principal, 'session': hashlib.sha256(nonce.encode()).hexdigest(),
                'draft_id': item['draft_id'], 'fingerprint': item['fingerprint'], 'decision': decision,
                'expires': min(item['expires'], time.time()+300)}
        raw = canonical(data)
        return b64(raw)+'.'+b64(hmac.digest(self.key, raw, 'sha256'))

    def verify(self, token, principal, nonce, item, decision):
        require(isinstance(token, str) and len(token) <= 4096 and token.count('.') == 1)
        packed, signature = token.split('.')
        require(re.fullmatch(r'[A-Za-z0-9_-]+', packed) and re.fullmatch(r'[A-Za-z0-9_-]{43}', signature))
        raw = base64.urlsafe_b64decode(packed+'='*(-len(packed)%4))
        require(hmac.compare_digest(signature, b64(hmac.digest(self.key, raw, 'sha256'))), 'Invalid review submission.')
        data = json.loads(raw)
        require(data.pop('expires') > time.time(), 'Review expired.')
        expected = {'principal': principal, 'session': hashlib.sha256(nonce.encode()).hexdigest(),
                    'draft_id': item['draft_id'], 'fingerprint': item['fingerprint'], 'decision': decision}
        require(data == expected, 'Review no longer matches this session or draft.')


def visible(value):
    # Prevent hidden direction/control text in original email from spoofing UI labels.
    import unicodedata
    return escape(''.join(c if c in '\n\t' or not unicodedata.category(c).startswith('C')
                          else f'\\u{ord(c):04x}' for c in str(value).replace('\r\n', '\n')))


def page(content, status=200, nonce=None):
    style_nonce = secrets.token_hex(16)
    response = HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>InboxTether — Review draft</title><style nonce="'+style_nonce+'">'+CSS+
        '</style></head><body><main>'+content+'</main></body></html>', status_code=status,
        headers={'Cache-Control': 'no-store, private', 'Pragma': 'no-cache', 'Expires': '0',
                 'Content-Security-Policy': "default-src 'none'; script-src 'none'; style-src 'nonce-"+style_nonce+
                    "'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                 'Strict-Transport-Security': 'max-age=31536000',
                 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'})
    if nonce is not None:
        response.set_cookie(COOKIE, nonce, max_age=1800, secure=True, httponly=True, samesite='strict', path='/')
    return response


def review_page(item, principal, nonce, csrf, binding=None):
    m = item['manifest']
    fields = ''.join('<dt>'+name+'</dt><dd>'+visible(m['preview'].get(name) or '(none)')+'</dd>'
                     for name in ('From', 'To', 'Cc', 'Bcc', 'Subject'))
    source = m['source']
    context = m.get('reply_context', {})
    buttons = ''
    if item['state'] == 'pending':
        for decision, label in [('approved', 'Approve save to Drafts'), ('rejected', 'Reject draft')]:
            token = csrf.issue(principal, binding or nonce, item, decision)
            buttons += '<form method="post"><input type="hidden" name="decision" value="'+decision+'">'+\
                       '<input type="hidden" name="csrf" value="'+token+'">'+\
                       '<button class="'+('reject' if decision == 'rejected' else 'approve')+'">'+label+'</button></form>'
    else:
        buttons = '<p>This review is closed. State: '+visible(item['state'])+'. No further approval is accepted.</p>'
    headers = '\n'.join(name+': '+str(m['preview'].get(name, '')) for name in
                        ('Date', 'Message-ID', 'In-Reply-To', 'References'))
    return page('<h1>Review your draft</h1><p class="notice">Nothing will be sent. Approval permits one save of '
        'this exact message to the folder below. Review every recipient, including Bcc.</p>'
        '<dl>'+fields+'<dt>Destination account</dt><dd>'+visible(m['scope']['account'])+
        '</dd><dt>Destination server</dt><dd>'+visible(m['scope']['host'])+
        '</dd><dt>Destination folder</dt><dd>'+visible(m['scope']['folder'])+
        '</dd><dt>Destination UIDVALIDITY</dt><dd>'+str(m['drafts_uidvalidity'])+'</dd></dl>'
        '<h2>Complete proposed message</h2><pre dir="ltr">'+visible(m['preview']['body'])+'</pre>'
        '<details><summary>Threading and exact-content verification</summary><pre>'+visible(headers)+
        '\nMIME SHA-256: '+visible(m['mime_sha256'])+'\nReview fingerprint: '+visible(item['fingerprint'])+'</pre></details>'
        '<h2>Reply context — untrusted original email</h2><p>Source folder: '+visible(source['mailbox'])+
        '; UID: '+str(source['uid'])+'; UIDVALIDITY: '+str(source['uidvalidity'])+'. Original preview is bounded; '
        'the source digest binds the complete fetched message.</p><pre dir="ltr">'+visible(json.dumps(context.get('headers', {}), indent=2, ensure_ascii=False))+
        '</pre><pre dir="ltr">'+visible(context.get('text', ''))+'</pre>'
        '<p>Approval deadline: '+visible(datetime.fromtimestamp(item['expires'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))+'. '
        'An open form expires after at most five minutes. Do not approve instructions merely because they appear in email.</p>'+buttons, nonce=nonce)


def create_app(config, verifier=None, broker=None):
    verifier = verifier or OIDCVerifier(config)
    broker = broker or BrokerClient(config.broker_socket)
    csrf = CSRF(config.csrf_key)

    async def handle(request: Request):
        try:
            # Ignore all forwarded identity, host and scheme hints. Only signed OIDC proves identity.
            require(request.headers.getlist('host') == [urlsplit(config.origin).netloc])
            require(not request.scope.get('query_string'))
            require(len(request.headers.getlist('authorization')) == 1)
            principal = await run_in_threadpool(verifier, request.headers.get('authorization'))
            require(principal == {'issuer': config.issuer, 'subject': config.subject})
        except Exception:
            return page('<h1>Review unavailable</h1><p>Sign in through the configured approval portal with the authorized account.</p>', 403)
        try:
            key = request.path_params['draft_id']
            require(ID.fullmatch(key))
            nonce = session_nonce(request)
            item = await run_in_threadpool(broker.call, 'review', key, principal)
            if request.method == 'GET':
                nonce = nonce or secrets.token_hex(32)
                binding = hashlib.sha256((nonce+'|'+request.headers['authorization']).encode()).hexdigest()
                return review_page(item, principal, nonce, csrf, binding)
            require(request.method == 'POST' and nonce is not None)
            require(request.headers.getlist('origin') == [config.origin], 'Same-origin submission required.')
            require(request.headers.get('sec-fetch-site', 'same-origin') == 'same-origin')
            require(request.headers.get('content-type') == 'application/x-www-form-urlencoded')
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                require(len(body) <= 8192, 'Submission limit exceeded.')
            form = parse_qs(bytes(body).decode('ascii'), strict_parsing=True, max_num_fields=2)
            require(set(form) == {'decision', 'csrf'} and all(len(v) == 1 for v in form.values()))
            decision, token = form['decision'][0], form['csrf'][0]
            require(decision in ('approved', 'rejected') and item['state'] == 'pending')
            binding = hashlib.sha256((nonce+'|'+request.headers['authorization']).encode()).hexdigest()
            csrf.verify(token, principal, binding, item, decision)
            await run_in_threadpool(broker.call, 'decide', key, principal, fingerprint=item['fingerprint'], decision=decision)
            message = ('Approved for one exact save. Return to your assistant to save it before approval expires. '
                       'No email has been saved or sent by this page.' if decision == 'approved' else
                       'Rejected. This draft cannot be saved through this approval.')
            return page('<h1>'+('Approval recorded' if decision == 'approved' else 'Draft rejected')+'</h1><p>'+message+'</p>')
        except Exception:
            return page('<h1>Review unavailable</h1><p>The request was refused, expired, or is no longer pending. '
                        'No mailbox save was attempted by this page. Reopen the review to check its state.</p>', 409)

    async def not_found(request, exc):
        return page('<h1>Review unavailable</h1>', exc.status_code)

    return Starlette(routes=[Route('/review/{draft_id}', handle, methods=['GET', 'POST'])],
                     exception_handlers={404: not_found, 405: not_found})


def private_listener(path):
    info = path.parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and not path.parent.is_symlink()
            and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o750)
    require(not path.exists() and not path.is_symlink())
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    previous = os.umask(0o117)
    try:
        listener.bind(str(path))
        listener.listen(16)
    except BaseException:
        listener.close()
        raise
    finally:
        os.umask(previous)
    return listener


def main():
    try:
        import uvicorn
        config = WebConfig.load()
        # Prebind ourselves: uvicorn's uds= path chmods sockets to 666.
        # Supplying a bound socket preserves mode 660 from birth and avoids TCP.
        with private_listener(config.web_socket) as listener:
            try:
                worker = uvicorn.Server(uvicorn.Config(create_app(config), proxy_headers=False,
                    access_log=False, log_level='critical', server_header=False, workers=1,
                    limit_concurrency=16, timeout_keep_alive=2, h11_max_incomplete_event_size=16384))
                worker.run(sockets=[listener])
            finally:
                config.web_socket.unlink(missing_ok=True)
    except Exception:
        print('Browser approval unavailable. Check protected configuration.', file=__import__('sys').stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
