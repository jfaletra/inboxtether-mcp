# Draft Assistant development review

Reviewed October 17, 2026. This is an implementation review and synthetic validation, not an independent security assessment or authorization to enable writes.

## Findings addressed in design

- Client consent is not portable enforcement. No MCP approval tool, boolean, echoed user text or model-visible bearer grant is used. OIDC-authenticated browser review and terminal admin review are separate from MCP; exact frozen content is fingerprinted and single-use, expiring approval is consumed in a durable transaction.
- Existing Reader code/guard remains unchanged. A separate adapter permits only one exact APPEND with the Draft flag. No SMTP, folder creation, existing-message STORE/MOVE/COPY/DELETE, EXPUNGE, SELECT or CLOSE path is added.
- Host/account/folder are operator-fixed; recipient groups, threading, source identity and digest, destination UIDVALIDITY, MIME bytes and expiry are bound to the review. Source or destination changes reject before APPEND where detectable. Saved bytes are verified through APPENDUID and BODY.PEEK.
- Ambiguous attempts fail closed to further saving. No automatic retry, duplicate replacement or deletion is attempted. Durable claimed state survives a process restart; caller replay cannot grant a new APPEND.
- Private local state has ownership/mode/symlink checks and bounded records/bytes. Unsafe or changed inputs fail closed; unexpected tool errors suppress private underlying messages. No new third-party dependencies.

## Review and validation

109 local synthetic tests pass, retaining all 55 Reader tests, plus actual IMAP framing and real MCP stdio error/discovery tests. Runtime dependency consistency passes. Fresh strict pip-audit reports zero known advisories/zero skipped packages for 29 runtime and 27 auditor dependencies. Automated advisory/pattern checks have finite coverage and do not establish absence of defects or secrets.

The diff is limited to source, synthetic tests, default-off configuration, ignore rules and documentation/metadata. No production source, secret, live mailbox fixture, private infrastructure configuration or deployment history is imported. Full file/index/Git-object pattern scans and known-private-identifier checks are required on the PR head in addition to hosted tests/audits/hygiene. Public GitHub noreply attribution and the owner's existing repository username are intentional public metadata.

## Remaining limitations and decisions requiring approval

1. **Approved architecture; deployment pending:** browser approval uses OAuth2 Proxy/OIDC, independent signed-token validation, a distinct-UID web process and peer-authenticated local broker. The owner has authorized routine session-based decisions without a fresh passkey per draft. A trusted terminal remains the admin fallback. Site-specific identity mapping, authentication sessions and actual OS-account isolation still need staging acceptance before rollout. The host/operator/MCP account remain trusted; a model with that account's shell/filesystem or mailbox credentials can bypass application boundaries.
2. **Live write enablement:** separate approval is required to configure the flag, storage/ACLs, restart any service, or perform a live APPEND acceptance test. Default off leaves only Reader tools. No such action is performed in development.
3. **IMAP atomicity:** destination replacement/source change can race validation and APPEND. Standard IMAP has no conditional transaction for these checks. Read-back may detect but cannot reverse a write; no automatic deletion is acceptable. Provider folder behavior, UIDPLUS/APPENDUID, exact MIME persistence, ACL scope and flags need a dedicated approved test.
4. **Private staging:** full MIME/recipients are stored locally, unencrypted. Ten minutes is logical expiry; cleanup is on subsequent preparation, with no secure-erasure guarantee. Backups/journals/snapshots and MCP client previews require protected storage and a deliberate retention policy. Do not upload approval databases or use shared/network state.
5. **Ambiguous outcomes:** an operator must privately reconcile before preparing any replacement; no exactly-once delivery guarantee is claimed across server/storage failure. Distinct separately approved drafts are distinct operations.

No merge, release, production deployment or write enablement is authorized by this review. Reader Mode remains default, Draft live compatibility unverified, Send Assistant planned only.

## Browser implementation review

All 109 tests pass locally, including the original 84 tests, synthetic RSA-signed token validation, HTTP/CSRF/session/expiry/replay/owner checks, real Unix IPC and kernel peer credentials, actual Uvicorn worker operation over a prebound private socket, protected keys/socket modes, concurrent decisions, terminal fallback and exact approved-byte saving. Reader functions/classes are unchanged by AST comparison against main. No production or identity-provider endpoint was contacted.

The optional Python dependency resolution (29 packages) passes a fresh strict audit with zero known vulnerabilities and zero skipped packages. CI now installs/tests optional browser dependencies and audits them alongside Reader and audit-tool requirements.

Review caught and addressed a framework socket-default issue: Uvicorn's direct uds path can chmod its socket to 666. The launcher now prebinds a 660 Unix socket under a 750 owner-controlled directory and passes the listener explicitly; actual-worker tests verify those permissions remain unchanged. Forged identity headers are never trusted; signed OIDC tokens are checked again inside the web service. CSRF binds the browser nonce and authenticated-token digest, so a new login token invalidates an old form.

OAuth2 Proxy v7.15.5 was selected after inspecting its official release/advisories. That release addresses the published skip-auth path, spoofed client-IP and callback-logging issues (GHSA-63jm-59jj-478j, GHSA-wr5q-7wxw-x568, GHSA-hhqp-vx7f-5c6m). Examples define no auth-exempt routes or trusted-IP bypasses and disable request/auth/verbose error logging. This is not a full Go/transitive binary audit; the official binary/checksum and provider callback/refresh/logout behavior must be verified in the chosen staging deployment. No external auth binary is vendored or installed automatically.

State is still unencrypted and subject to documented journal/backup retention. Session theft or compromised trusted browser/web/host authority remains a risk; v1.1 does not enforce per-approval passkeys. Future multiuser policy must derive mailbox grants from verified principals, not accept user-selected tenant identities. This implementation intentionally remains single-owner per instance. See docs/BROWSER-APPROVAL.md for configuration, supported OIDC shape and remaining acceptance gates.
