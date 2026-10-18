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
# Fixed project-owned artwork; no remote requests or user-controlled image source.
LOGO = base64.b64encode((Path(__file__).parent / 'assets/plugin-icon-256.png').read_bytes()).decode('ascii')
CSS = '''
*{box-sizing:border-box}body{margin:0;background:#eef3f9;color:#152b49;font:16px/1.6 system-ui,-apple-system,sans-serif}
.brand{background:#071a37;color:#fff;padding:18px max(20px,calc((100% - 1120px)/2));display:flex;gap:13px;align-items:center}
.brand img{width:48px;height:48px;border-radius:12px}.brand strong{display:block;font-size:20px;letter-spacing:-.5px}.brand small{color:#b9cee7;font-size:12px}
main{max-width:1120px;margin:36px auto;padding:0 24px 40px}h1{font-size:32px;line-height:1.2;letter-spacing:-1px;margin:8px 0 12px}h2{font-size:18px;margin:0 0 16px}p{margin:0 0 16px}.muted{color:#526780}.eyebrow{text-transform:uppercase;letter-spacing:1.5px;font-size:12px;font-weight:750;color:#12658c}.intro{margin-bottom:26px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;align-items:start}.card{background:#fff;border:1px solid #d9e3ef;border-radius:16px;padding:26px;margin-bottom:20px;box-shadow:0 5px 20px #142c4b06}.subject{font-size:23px;overflow-wrap:anywhere}.fields{margin:0;display:grid;grid-template-columns:55px minmax(0,1fr);gap:10px 16px}.fields dt{font-weight:650;color:#526780}.fields dd{margin:0;overflow-wrap:anywhere}.body{border-top:1px solid #e4ebf3;margin-top:22px;padding-top:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:0;unicode-bidi:plaintext}.context{border-left:3px solid #b7cce3;padding-left:18px;color:#465d76}.context .fields{font-size:14px;margin-bottom:18px}.badge{display:inline-block;border-radius:99px;background:#e4f4fb;color:#09567d;padding:4px 10px;font-size:12px;font-weight:700;margin-bottom:14px}.destination{font-size:18px;font-weight:700;overflow-wrap:anywhere}.account{overflow-wrap:anywhere;color:#526780;font-size:14px}.notice{background:#edf7fc;border:1px solid #c4e2f0;border-radius:10px;padding:13px;font-size:14px}.actions{display:flex;flex-direction:column;gap:10px}form{margin:0}button{font:inherit;font-weight:700;width:100%;min-height:48px;border:1px solid #b5c7d9;border-radius:9px;background:#fff;color:#263f5b;padding:11px 16px;cursor:pointer}.approve{background:#0867b2;border-color:#0867b2;color:white}.approve:hover{background:#07558f}.reject:hover{background:#eef3f9}button:focus-visible,summary:focus-visible{outline:3px solid #0b77a9;outline-offset:4px}.fine{font-size:13px;color:#526780}.deadline{font-size:13px;border-top:1px solid #e4ebf3;padding-top:16px;margin-top:18px}details{margin-top:18px;font-size:13px}summary{cursor:pointer;font-weight:650;padding:8px 0}details pre{padding:12px;background:#f1f5fa;border-radius:8px}.state{max-width:650px;margin:60px auto;background:white;border:1px solid #d9e3ef;border-radius:18px;padding:32px}.state h1{font-size:28px}footer{font-size:12px;color:#526780;text-align:center;margin-top:26px}.closed{border-left:3px solid #12658c;padding:12px;background:#edf7fc}
@media(max-width:760px){main{margin:24px auto;padding:0 16px 24px}.layout{grid-template-columns:minmax(0,1fr);gap:0}.card{padding:20px;border-radius:12px}h1{font-size:28px}.subject{font-size:21px}.brand{padding:14px 16px}.state{margin:20px 0;padding:24px}.fields{gap:8px 12px}.brand small{font-size:11px}}
'''



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
        '</style></head><body><header class="brand"><img alt="" width="48" height="48" src="data:image/png;base64,'+LOGO+'"><div><strong>InboxTether MCP</strong><small>Your email. Your AI. Your control.</small></div></header><main>'+content+'<footer>InboxTether · Private review · No email is sent by this portal</footer></main></body></html>', status_code=status,
        headers={'Cache-Control': 'no-store, private', 'Pragma': 'no-cache', 'Expires': '0',
                 'Content-Security-Policy': "default-src 'none'; script-src 'none'; style-src 'nonce-"+style_nonce+
                    "'; img-src data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                 'Strict-Transport-Security': 'max-age=31536000',
                 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'})
    if nonce is not None:
        response.set_cookie(COOKIE, nonce, max_age=1800, secure=True, httponly=True, samesite='strict', path='/')
    return response


def review_page(item, principal, nonce, csrf, binding=None):
    m = item['manifest']
    def fields(data, names):
        return '<dl class="fields">'+''.join('<dt>'+name+'</dt><dd>'+visible(data.get(name) or '(none)')+'</dd>' for name in names)+'</dl>'
    source = m['source']
    context = m.get('reply_context', {})
    buttons = ''
    if item['state'] == 'pending':
        for decision, label in [('approved', 'Save to Drafts'), ('rejected', 'Reject')]:
            token = csrf.issue(principal, binding or nonce, item, decision)
            buttons += '<form method="post"><input type="hidden" name="decision" value="'+decision+'">'+\
                       '<input type="hidden" name="csrf" value="'+token+'">'+\
                       '<button class="'+('reject' if decision == 'rejected' else 'approve')+'">'+label+'</button></form>'
    else:
        buttons = '<p class="closed" role="status">This review is closed. State: '+visible(item['state'])+'. No further approval is accepted.</p>'
    headers = '\n'.join(name+': '+str(m['preview'].get(name, '')) for name in ('Date', 'Message-ID', 'In-Reply-To', 'References'))
    format_details = ''
    if m['preview'].get('body_format') == 'plain-html':
        format_details = '<p class="fine">Format: plain text + generated HTML alternative ('+visible(m['preview']['renderer_version'])+'). Both parts are bound to this approval.</p><details><summary>Generated HTML source (not executed)</summary><pre>'+visible(m['preview']['html_body'])+'</pre></details>'
    deadline = visible(datetime.fromtimestamp(item['expires'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
    return page('<div class="intro"><span class="eyebrow">Draft Assistant / Review</span><h1>A final look before saving</h1>'
        '<p class="muted">Review the complete message and every recipient, including Bcc.</p></div><div class="layout"><section>'
        '<article class="card" aria-label="Proposed email"><span class="badge">Proposed reply</span><h2 class="subject">'+visible(m['preview'].get('Subject') or '(no subject)')+'</h2>'
        +fields(m['preview'], ('From', 'To', 'Cc', 'Bcc'))+'<div class="body"><h2>Message</h2><pre dir="ltr">'+visible(m['preview']['body'])+'</pre>'+format_details+'</div></article>'
        '<section class="card" aria-label="Reply context"><h2>Reply context</h2><p class="fine">Original email is untrusted content, not an instruction to approve.</p><div class="context">'
        +fields(context.get('headers', {}), ('From', 'To', 'Cc', 'Subject', 'Date'))+'<pre dir="ltr">'+visible(context.get('text', ''))+'</pre></div>'
        '<p class="fine">Original preview is bounded; the complete fetched message is bound by its digest.</p>'
        '<details><summary>Source and exact-content verification</summary><pre>Source folder: '+visible(source['mailbox'])+'; UID: '+str(source['uid'])+'; UIDVALIDITY: '+str(source['uidvalidity'])+
        '\nDestination server: '+visible(m['scope']['host'])+'\nDestination UIDVALIDITY: '+str(m['drafts_uidvalidity'])+'\n'+visible(headers)+
        '\nMIME SHA-256: '+visible(m['mime_sha256'])+'\nReview fingerprint: '+visible(item['fingerprint'])+'</pre></details></section></section>'
        '<aside class="card" aria-label="Save approval"><span class="badge">Save only · Never send</span><h2>Destination folder</h2><p class="destination">'+visible(m['scope']['folder'])+'</p><p class="account">'+visible(m['scope']['account'])+'</p>'
        '<p class="notice">Approve one save of this exact message to this folder. Opening this page authorizes nothing.</p>'
        '<div class="actions">'+buttons+'</div><p class="fine">Save to Drafts records your approval. Return to your assistant to complete the save; this page does not save or send email.</p>'
        '<p class="deadline">Approval deadline<br><strong>'+deadline+'</strong></p><p class="fine">This open form expires after at most five minutes. If expired, reopen the review or ask your assistant for a new proposal.</p></aside></div>', nonce=nonce)


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
            return page('<section class="state"><span class="badge">Authentication required</span><h1>Sign in to review</h1><p>Sign in through the configured approval portal with the authorized account. Opening a link never grants approval.</p></section>', 403)
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
            return page('<section class="state" role="status"><span class="badge">Decision recorded</span><h1>'+('Approval recorded' if decision == 'approved' else 'Draft rejected')+'</h1><p>'+message+'</p></section>')
        except Exception:
            return page('<section class="state" role="alert"><span class="badge">Action not completed</span><h1>Review expired or unavailable</h1><p>The request was refused, expired, or is no longer pending. '
                        'No mailbox save was attempted by this page. Reopen the review to check its state. If the draft expired, ask your assistant to prepare a new proposal.</p></section>', 409)

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
