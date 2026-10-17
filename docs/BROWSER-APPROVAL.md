# Browser approval for Draft Assistant (v1.1 development)

Implemented on the Draft Assistant branch; **not enabled, deployed or live-provider certified**. Reader configuration and its five tools remain unchanged. Both Draft Assistant and browser approval default off. No SMTP or sending is implemented. Terminal approval remains a protected administrative fallback.

## What the user does

1. Ask the assistant to prepare a reply. With browser approval explicitly configured, `prepare_reply_draft` returns a `review_url` containing only an opaque draft ID. A link is not an approval or access credential.
2. Open the link and sign in through the configured identity provider. Review From, To, Cc, **Bcc**, subject, complete proposed body, destination account/folder and UIDVALIDITY. The page also shows bounded original-message context and source identity; threading headers, exact MIME hash and review fingerprint are available in a details panel.
3. Select **Approve save to Drafts** or **Reject draft**. This records one decision for that exact frozen record. It neither sends nor saves email by itself. Return to the assistant to call `save_approved_draft(draft_id)` before expiry. The existing save path revalidates source/destination and verifies stored MIME byte-for-byte. Rejection permanently closes that pending record.

Routine saves can use an existing authenticated browser session. There is no new passkey challenge per decision in v1.1. A future policy may enforce `auth_time`, `acr`/`amr` or transaction-bound passkey verification; none is claimed today. The supplied OIDC example uses a 30-minute cookie lifetime with a five-minute refresh interval; refresh may extend an active session, so this is not an absolute session-age limit. Configure the identity provider's session/revocation policy separately. Draft approval still expires ten minutes after **preparation**, and a review form expires after at most five minutes. An expired/refreshed authentication token can invalidate a form: reopen review rather than bypassing the check.

Email is untrusted. The proposed body and original context are escaped plain text with no scripts, images, links, HTML rendering, analytics, third-party fonts or external content loads. Format/control characters in original context are made visible. The original preview is bounded, not a claim that the complete original message is displayed; its digest binds the complete fetched source. The complete proposed reply is displayed without UI truncation.

## Components and authority

```text
Browser -- HTTPS --> OAuth2 Proxy / OIDC session gateway
                         | signed ID token, private Unix socket
                         v
                  Review web service (distinct OS UID)
                         | authenticated kernel peer UID, local framed IPC
                         v
                  Approval broker --> protected draft/decision database
                                             ^
MCP Reader/Draft backend ---------------------|
      | save only after atomic approval claim
      v
    IMAP Drafts (no SMTP)
```

- `approval_web.py`: a separate Starlette process; verifies signed identity using PyJWT, renders the immutable review, and validates explicit POST/CSRF. It has no MCP tools, IMAP connection, mailbox password or direct database access. It listens only on an explicitly prebound private Unix socket, mode 660 in an owner-controlled 750 directory. It does not expose a TCP listener or unauthenticated development mode.
- `approval_broker.py`: a separate local process under the existing state-owner account. Only the configured web UID may call its private Unix socket; Linux SO_PEERCRED or macOS/BSD getpeereid verifies the caller **before** reading requests. It rechecks the configured issuer/subject, store scope, exact fingerprint, expiry and state, then atomically records approve/reject plus a private actor receipt. There is no save/SMTP operation in this interface. The production launcher refuses to run with the same broker/web UID.
- The MCP process receives no browser session, OIDC client secret, signing key or approval endpoint. It can prepare/read/save using its existing rules but cannot approve through an MCP argument. The broker's example unit is restricted to AF_UNIX and loads no mailbox password.
- `draft_assistant.py approve <draft_id>` remains an interactive local administrator path. Its decision receipt records terminal method and UID instead of OIDC principal. It still prints exact content and requires the complete fingerprint. It does not become a remote MCP approval tool.

The broker/state-owner account, terminal administrator, host and deployed code are trusted. The original warning still applies: never give the model shell/filesystem access as the MCP/broker user or mailbox credentials. Browser authentication does not sandbox a compromised mail process. Root, a compromised web process, a stolen authenticated browser session, or automation allowed to control that trusted session can act with that authority. Session reuse is an explicit v1.1 tradeoff; disable such agent access, keep sessions short and use stronger provider authentication as appropriate.

## Established authentication, not identity headers

Use **OAuth2 Proxy v7.15.5** (current inspected release) with a registered confidential **OIDC** web client. It performs login/callback handling and maintains encrypted Secure/HttpOnly browser session cookies. Pin and verify the official binary/checksum through the operator's trusted distribution process; it is not bundled or automatically installed by this project. Recheck upstream advisories before deployment.

The proxy forwards its signed OIDC ID token in the upstream Authorization header. The web process independently validates it using **PyJWT**, the operator-configured HTTPS JWKS URL, RS256 signatures, exact issuer and audience, required expiry/issued-at/subject claims and authorized party if present. It rejects missing/duplicate credentials, wrong subjects, expired/future-issued tokens and algorithm substitution. Token-supplied JWKS URLs are never used. Plain `X-Forwarded-User`, `X-Auth-Request-User`, email strings or model assertions grant no authority.

A single fixed owner is configured for v1.1. The principal is **issuer + immutable OIDC subject**, not a mutable email address. That principal is bound into the draft's scope at preparation and independently checked by web and broker. Changing the owner invalidates old records. Future multiuser routing can introduce per-principal mailbox grants and authenticated MCP ownership; it must not let callers pick an owner or share this instance's database across tenants. **This version is not a multiuser service.**

OIDC provider/client selection, exact subject mapping, audience and JWKS URL require operator configuration. RS256 and single-string audiences are deliberately supported first; providers issuing different formats fail closed and require a reviewed adapter. OAuth access-token forwarding, client bearer-token login, unverified email/TLS bypasses and authentication-exempt review routes are not used by the examples.

## Sessions, CSRF and replay

OAuth2 Proxy handles the authenticated session and login-flow CSRF. The review service additionally uses a separate `__Host-inboxtether-review` opaque nonce cookie (Secure, HttpOnly, SameSite=Strict, path `/`, no Domain). It grants no access without a freshly validated ID token on every request.

The review form's HMAC-SHA256 token binds the browser nonce and authenticated ID-token digest, verified principal, draft ID, immutable fingerprint, decision and expiry. Its 32-byte secret belongs only to the web account, never the MCP process or repository. POST requires an exact configured Origin/Host, same-origin Fetch Metadata where present, a bounded form body and exactly the expected fields. No CORS access, GET approval, approve-all setting, model-visible bearer approval, editable content/destination form or client-asserted approval boolean exists. Decisions use the original atomic pending-state transition, so duplicate forms and concurrent approve/reject requests cannot both succeed.

Responses are no-store and no-referrer, with restrictive CSP, script blocking, frame denial and MIME sniffing protection. The web worker and broker do not log requests, tokens, mail or raw exceptions. Supplied gateway/frontend examples disable request/auth logging and verbose error pages. Do not enable upstream access/body/trace logging with live mail. Audit receipts in the protected database contain the actor, fingerprint, decision time and method; draft state remains private and unencrypted as documented in DRAFT-ASSISTANT.md. There is no secure-erasure guarantee for SQLite journals/backups.

The existing one-use APPEND, exact fixed folder/flags, UIDPLUS/APPENDUID, UIDVALIDITY/source digest and read-back checks are retained. Browser approval does not change ambiguous-save behavior: never retry/delete automatically; reconcile privately. Standard IMAP still cannot make destination validation and APPEND atomic.

## Configuration and deployment reference (not installed)

Install optional dependencies in a staging environment with `python -m pip install -r requirements-browser.txt`. Reader-only installations continue to use requirements.txt. The application does not auto-load example environment files.

Reference files in [examples/browser-approval](../examples/browser-approval):

- [web.env.example](../examples/browser-approval/web.env.example): origin, OIDC issuer/subject/client audience, JWKS URL, private socket paths and CSRF secret-file path. Both enable switches remain `0`.
- [broker.env.example](../examples/browser-approval/broker.env.example): fixed mailbox/state settings, the same origin/issuer/subject, allowed web OS account and broker socket. Both switches remain `0`.
- [oauth2-proxy.cfg.example](../examples/browser-approval/oauth2-proxy.cfg.example): cookie/session settings, PKCE, OIDC callback, private upstream socket, stripped identity headers and disabled sensitive logging. Replace all placeholders and restrict the provider-side user population; the application's subject check is mandatory regardless of the gateway's email-domain filter.
- [nginx.conf.example](../examples/browser-approval/nginx.conf.example): dedicated HTTPS site, fixed local auth-gateway upstream, bounded requests/rate, logging disabled and no-store responses. Never automatically alter an existing frontend.
- Separate reference systemd units: [broker](../examples/browser-approval/inboxtether-approval-broker.service), [web](../examples/browser-approval/inboxtether-approval-web.service), [auth gateway](../examples/browser-approval/inboxtether-approval-auth.service). They are examples requiring site validation, not a production installer.

Provision three distinct nonlogin service accounts: existing MCP/state owner, `inboxtether-web`, and `inboxtether-auth`. A dedicated `inboxtether-approval` group grants socket-directory traversal and socket connection only. Runtime directories must be owned by the respective serving account, group inboxtether-approval, mode 750; sockets are mode 660. Group members cannot replace directory entries. The broker additionally accepts only the web UID, not every group member. Keep the database directory owner-only 700/database 600. Do not loosen those permissions to share it with the web service.

Provision **independent** 32-random-byte CSRF and OAuth2 Proxy cookie secrets outside the checkout, owner-only 600, in protected parent directories owned by the corresponding web/auth account. Provision the OIDC client secret only to the auth account. TLS private keys belong only to the chosen HTTPS frontend. The web and auth units deny access to mailbox secrets/state and each other's private secret paths. The old Reader systemd skeleton is not changed; an operator must review any approved Draft deployment's writable-state permissions separately.

MCP, broker and terminal environments must agree on fixed mailbox settings, review origin, issuer and owner subject. Only web/auth processes need the audience/JWKS/client configuration; the MCP process must not receive auth cookies/client secrets/CSRF key. To enable only after separate rollout approval, set both switches to `1` explicitly and provision/start the separate services. Old records prepared without the new owner scope cannot be approved after browser opt-in; prepare fresh reviews rather than migrating approvals. Terminal-only mode continues with browser approval `0`.

A browser-reachable HTTPS endpoint is required; a public internet endpoint is **not** required if the user has private-network/VPN access. The separate login gateway/portal must be reachable from the user's browser; MCP tunnel connectivity alone does not host this review site. Protect the gateway's loopback port from untrusted local services; use a dedicated host/network boundary where local users are not trusted. The portal rejects forged headers independently, but the gateway session boundary must not be bypassed. No direct worker socket/TCP endpoint should be publicly exposed.

## Clients and validation

All MCP clients can use the returned ordinary HTTPS review link and then call save by ID. No native elicitation or client prompt is accepted as proof of approval. Future URL elicitation can open the same authenticated page without changing authority. No ChatGPT/Claude settings, tool discovery or production tunnel are changed by implementation.

Tests use synthetic RSA-signed identity tokens, in-memory HTTP requests, protected temporary SQLite storage, real local Unix IPC/peer credentials and a fake IMAP backend. They cover user/scope isolation, invalid signatures/claims, CSRF/session binding, replay/expiry/rejection, concurrency, escaped complete previews, response protections, private socket/key permissions, terminal fallback and exact approved-byte save. Existing Reader/protocol tests remain in the suite. No IdP login, live TLS frontend, real cross-account deployment or live mailbox APPEND is certified by those tests.

Before deployment, approve the IdP/client and immutable owner mapping, HTTPS/VPN route, service accounts/group and storage/retention; validate the pinned gateway configuration, callback/refresh/logout, denial cases and cookie flags in a staging browser; check Unix peer identity/permissions on the actual Linux host; review the complete source/config diff; separately authorize any restart and dedicated live Mailcow draft acceptance test. Do not merge, release or enable production writes implicitly.

Primary configuration references: [OAuth2 Proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/), [v7.15.5](https://github.com/oauth2-proxy/oauth2-proxy/releases/tag/v7.15.5), [PyJWT validation API](https://pyjwt.readthedocs.io/en/latest/api.html). No third-party application source or competitor implementation is copied into this project.
