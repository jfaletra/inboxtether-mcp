# Secure Send Assistant — v1.2 development, not released

Reader remains the default. Existing v1.1 Basic/Secure Draft Assistant tools and approval policies are unchanged. Sending is a distinct optional capability with **no Basic Send Mode** and no MCP approval/send tool. No real SMTP provider has been tested for this implementation. This guide is not deployment approval.

## Authority boundary

The MCP account can request preparation and status through a bounded local Unix socket. Linux `SO_PEERCRED` authenticates its numeric UID; group membership alone does not authorize it. The client also verifies the sender's kernel peer UID and socket ownership/mode. Non-Linux sending fails closed; Reader and Draft Assistant remain available as before.

A different non-root OS account owns the sender configuration, SMTP password file, private staging database and terminal approval command. Never give the model shell/filesystem/database access to this account, its code, its Python runtime, its sudo rights, or a root tool. Code and its ancestors must be root/sender owned and not group/other writable. Directory checks accept root-owned sticky temporary-directory boundaries for synthetic testing; production belongs under administrator-controlled `/opt`, `/etc`, `/var/lib` and `/run` paths. The supplied broker service permits only AF_UNIX sockets, so it cannot submit SMTP even if its request dispatch is accidentally expanded. The trusted CLI, run separately by the operator, performs approval and one SMTP submission.

Host, administrator, trusted sender account, Python runtime, and operator compromise remain outside the guarantee. A TTY is an accidental-use guard, not proof of human identity. Do not connect the trusted CLI to an AI-controlled terminal, log collector or session recorder. Native ChatGPT/Claude/MCP prompts are supplementary and never authorize sending. No model statement, tool argument, callback URL, or secret link can grant approval.

## Configuration and installation review

No new Python dependencies are needed. Deployment needs Linux, a separate non-root sender account, a private IPC group, and authenticated SMTP submission with certificate-validated TLS. This branch supplies **disabled templates**, not an installer:

- `examples/secure-send/sender.json.example`: `enabled=false`, `mode=secure`.
- `examples/secure-send/mcp.env.example`: `INBOXTETHER_SEND_ASSISTANT=0`; no SMTP secret/configuration.
- `examples/secure-send/inboxtether-send.service`: optional preparation/status broker, no TCP socket authority and no automatic restart.

Before any installation, review the account/group assignments and numeric UIDs. Examples use placeholders, not actual assigned users. The sender must not share the MCP UID. Only the designated MCP account joins the IPC group. Socket directory is sender-owned `0750` with IPC group; socket is `0660`. State is sender-owned `0700`; configuration, SQLite DB, SMTP secret and exports are `0600`. Keep protected paths outside the checkout. Set umask `0077` for trusted commands. Use root-owned immutable source and Python runtime accessible to the sender, not a checkout or environment writable by the MCP account. Do not expose this IPC endpoint publicly.

The sender JSON pins the From/envelope identity, SMTP host/port, TLS mode (`implicit` or mandatory `starttls`), authentication username, password-file reference, authorized MCP UID, state and socket paths. There are no caller-controlled SMTP identities, hosts, credential paths or TLS bypasses. Credential value is read only by the trusted CLI after the durable claim. Provision **separate SMTP credentials** later through a secure local process, and verify the provider's actual submission-only/sender restrictions. Providers differ; a separate password does not itself prove reduced permissions. No credentials were created for development.

After explicit deployment approval, the operator would provision these files/accounts, review the service, set sender `enabled=true`, and independently opt the MCP service into preparation/status using `INBOXTETHER_SEND_ASSISTANT=1`, `INBOXTETHER_SEND_MODE=secure`, `INBOXTETHER_SEND_SOCKET`, and `INBOXTETHER_SEND_UID`. Each flag alone is insufficient to send. Do not change the existing Reader/Draft settings, IMAP credential or tunnel. Startup refuses same-UID operation, untrusted paths and Basic Send configuration. A stale broker socket needs operator inspection/removal; no automatic cleanup guesses.

## Preparation and exact review

`prepare_send_message` takes explicit To/Cc/Bcc, subject, plain-text body and optional attachment objects (`filename`, `content_type`, `data_base64`). Reply preparation additionally requires all three source identifiers: folder, UID and UIDVALIDITY. The existing Reader fetch path uses EXAMINE/BODY.PEEK; no original mail is changed. Existing threading validation constructs In-Reply-To/References from bounded parent headers. Original/source context is untrusted and shown in review, not a source of authority; the sender does not hold IMAP credentials or independently refetch the parent.

The trusted broker validates and freezes final MIME bytes, Message-ID/Date, complete SMTP envelope including Bcc, fixed sending identity and SMTP destination/configuration, reply context, expiry and attachment hashes. A SHA-256 fingerprint binds the complete manifest plus MIME digest. Any edit requires a new proposal/review; a prior draft approval is never reused. Ten-minute expiry is checked at approval, atomic claim, after authentication and immediately before DATA. Expiration prevents starting submission; it cannot recall bytes already transmitted.

Bcc stays in the protected approval manifest/envelope, **not** in transmitted MIME headers. Unicode body/subject are MIME encoded; address syntax is deliberately conservative ASCII and recipients are bounded to 20 total. No HTML body, arbitrary headers, automatic recipient inference or redirects are accepted.

The trusted operator uses a separately authenticated host session, then runs the trusted account's command (paths below are deployment placeholders, not instructions to enable this branch):

```sh
/opt/inboxtether-send/venv/bin/python -B /opt/inboxtether-send/send_assistant.py --config /etc/inboxtether-send/sender.json review SEND_ID
/opt/inboxtether-send/venv/bin/python -B /opt/inboxtether-send/send_assistant.py --config /etc/inboxtether-send/sender.json approve-send SEND_ID
```

The terminal shows all recipients, identity, destination, subject, full body, threading/reply context, attachment metadata/hashes and expiry. Only typing `SEND <complete fingerprint>` on that trusted interactive terminal approves and submits. Rejection/status are separate terminal commands; the MCP endpoint cannot approve, reject or submit. `send_request_status` is the only status MCP tool. IDs/fingerprints are references, not approval tokens.

For attachments, `approve-send` requires `--review-dir` naming an existing empty sender-owned `0700` directory. It exports exact MIME, full review JSON (including Bcc), and attachment bytes with generated names (`attachment-1.bin`, etc.), using exclusive `0600` files without following symlinks. Inspect these in trusted tools before confirming; nothing opens/executes/renders them automatically. An earlier separate `review --review-dir` export must use a different empty directory on final approval; existing files are never overwritten. Securely retain or remove exports under your local policy, without copying them to the repository or logs.

## Attachment limits and limitations

At most five attachments; each nonempty decoded payload at most 256 KiB, combined 512 KiB; final MIME at most 1 MiB. Allowed types/extensions: UTF-8 plain text/.txt, PDF/.pdf, PNG/.png and JPEG/.jpg or .jpeg. Type, extension, signature and text/control validation are conservative safeguards, **not malware scanning**. Archives, Office files, HTML, nested messages, paths, URLs, duplicate names and unsupported types are rejected. Bytes are never fetched by URL or path. Allowed files can still be malicious; hashes bind bytes, not safety or reviewer comprehension.

## Single attempt, SMTP outcomes and recovery

State moves from pending to a durably committed `attempting` record in one approval/claim transaction before any network activity. Expired, rejected, altered or already claimed requests cannot submit; concurrent claims have one winner. `PRAGMA synchronous=FULL` and a local SQLite database are required; do not use network storage. This does not defend against storage that lies about durability or restored/stale snapshots.

The trusted CLI uses authenticated SMTP with system CA/hostname validation, TLS 1.2 minimum, implicit TLS or mandatory STARTTLS without downgrade. Every recipient must be accepted before DATA. A refused recipient causes connection closure without DATA, preventing partial-recipient submission by this client. No SMTP debug output or raw server replies are exposed. Python audit hooks and external tracing can observe SMTP data: use a trusted runtime without message-capturing hooks, tracing, credential logging or protocol debugging.

- `accepted`: final DATA response was 250; submitted MIME bytes match the approval digest. This is submission acceptance, **not final delivery**. Relays may add DKIM/Received headers or transform messages; no byte-for-byte recipient-delivery claim is made.
- `failed`: pre-DATA failure or explicit DATA rejection. No automatic retry; resolving the cause and preparing a new proposal requires a fresh review.
- `uncertain`: connection loss during DATA, unknown final reply, worker crash/ongoing attempt, or failure to store the final receipt. **Never automatically retry or reapprove this ID.** Privately reconcile SMTP/provider logs and recipient outcomes first. A worker still submitting also reports uncertain conservatively.

Terminal CLI records an acceptance before reporting it; a failure during QUIT/close cannot erase known acceptance. Durable attempting/accepted/failed/uncertain receipts are not removed by pending-record expiry. Staging purges only expired never-attempted pending proposals. Limits: 32 pending and 256 total retained records, then fail closed until operator-reviewed maintenance. State contains plaintext mail and is not encrypted at rest: use host disk encryption, restrictive backups and short retention consistent with replay protection. There is no automatic receipt-deletion or replay-reset operation.

Standard SMTP has **no general exactly-once guarantee**. Message-ID is not an idempotency key. Replaying one ID cannot resend, but a new ID for identical content can be independently approved and sent. An operator must not create a replacement for an uncertain send until reconciliation. Never restore a pre-attempt database and re-enable sending blindly: disable sending, retain current receipts, and reconcile every potentially submitted record first. This is critical for backup/rollback, not just application retries. See [RFC 5321](https://www.rfc-editor.org/rfc/rfc5321.html) and [Python SMTP documentation](https://docs.python.org/3/library/smtplib.html).

## Sent-folder synchronization: deliberately deferred

No automatic IMAP Sent-folder APPEND, folder creation, existing draft deletion, flag update, MOVE, COPY or other mailbox mutation is implemented by Send Assistant. The SMTP server/provider might independently file a sent copy; check that behavior in future isolated tests. `sent_copy=not-written` means InboxTether did not write a copy, not that no provider-created copy exists.

Future synchronization needs a separate security review and explicit write scope/approval: bind destination special-use folder and UIDVALIDITY, define Bcc visibility in the private copy, stable Message-ID plus submitted-MIME hash and SMTP receipt linkage, record copy state independently from delivery state, and reconcile provider-created copies and ambiguous APPEND results without resending SMTP. Failure to file a Sent copy must never cause a second send. Exact-byte SMTP submission records and stable Message-ID provide a foundation, not a complete synchronization implementation.

## Browser approval and client experience

This first implementation supports the trusted terminal only. Existing Secure Draft browser/OIDC approval is preserved, but **cannot approve sends**. Reusing that portal later requires a separate send-scoped, authenticated broker protocol, explicit Send action/CSRF checks, identity ownership, and live validation. No Pocket ID, OAuth2 Proxy, HTTPS endpoint or new identity infrastructure is required for terminal operation. ChatGPT and other MCP clients share the same preparation/status protocol; no client-specific UI behavior is claimed tested for v1.2. A browser Send button is not present.

## Validation and deployment gates

Tests use synthetic messages, mock SMTP, local Unix sockets and failure injection. CI additionally runs a dedicated Linux root test that drops to transient numeric process identities (without creating users) to verify actual peer authentication and denial of client access to sender configuration/state. There is no live provider, DNS, SMTP delivery, passkey/OIDC or production test in this development work.

Before deployment: complete independent review of privilege separation and sender-runtime ownership; verify Linux hosted CI; settle SMTP account restrictions and encrypted backup/reconciliation procedure; approve isolated mock/provider testing separately; choose operator terminal workflow and retention; review actual provider MIME/Sent behavior; and explicitly authorize installation/credentials/enablement. No merge, deployment, release or real sending is authorized by this documentation.
