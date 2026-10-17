# Secure Send Assistant — v1.2 development, not released

Reader remains the default. Existing v1.1 Basic/Secure Draft Assistant tools and approval policies are unchanged. Sending is a distinct optional capability with **no Basic Send Mode** and no MCP approval/send tool. An isolated controlled Mailcow SMTP submission was accepted and recipient delivery confirmed. Sent synchronization has not been live-tested. This guide is not deployment approval.

## Authority boundary

The MCP account can request preparation and status through a bounded local Unix socket. Linux `SO_PEERCRED` authenticates its numeric UID; group membership alone does not authorize it. The client also verifies the sender's kernel peer UID and socket ownership/mode. Non-Linux sending fails closed; Reader and Draft Assistant remain available as before.

A different non-root OS account owns the sender configuration, SMTP password file, private staging database and terminal approval command. Never give the model shell/filesystem/database access to this account, its code, its Python runtime, its sudo rights, or a root tool. The installed launcher, bootstrap, application code and Python runtime must be administrator-owned and not writable by either service account; mutable state/configuration remain sender-owned. Directory checks accept root-owned sticky temporary-directory boundaries for synthetic testing; production belongs under administrator-controlled `/opt`, `/etc`, `/var/lib` and `/run` paths. The supplied broker service permits only AF_UNIX sockets, so it cannot submit SMTP even if its request dispatch is accidentally expanded. The trusted CLI, run separately by the operator, performs approval and one SMTP submission.

Host, administrator, trusted sender account, Python runtime, and operator compromise remain outside the guarantee. A TTY is an accidental-use guard, not proof of human identity. Do not connect the trusted CLI to an AI-controlled terminal, log collector or session recorder. Native ChatGPT/Claude/MCP prompts are supplementary and never authorize sending. No model statement, tool argument, callback URL, or secret link can grant approval.

## Configuration and installation review

No new Python dependencies are needed. Deployment needs Linux, a separate non-root sender account, a private IPC group, and authenticated SMTP submission with certificate-validated TLS. This branch supplies **disabled templates**, not an installer:

- `examples/secure-send/sender.json.example`: `enabled=false`, `mode=secure`.
- `examples/secure-send/mcp.env.example`: `INBOXTETHER_SEND_ASSISTANT=0`; no SMTP secret/configuration.
- `examples/secure-send/inboxtether-send.service`: optional preparation/status broker, no TCP socket authority and no automatic restart.
- `examples/secure-send/inboxtether-send`: administrator-installed sanitized launcher; `send_bootstrap.py` validates administrator-owned runtime/code before importing application modules.

Before any installation, review the account/group assignments and numeric UIDs. Examples use placeholders, not actual assigned users. The sender must not share the MCP UID. Only the designated MCP account joins the IPC group. Socket directory is sender-owned `0750` with IPC group; socket is `0660`. State is sender-owned `0700`; configuration, SQLite DB, SMTP secret and exports are `0600`. Keep protected paths outside the checkout. Set umask `0077` for trusted commands. Use root-owned immutable source and Python runtime accessible to the sender, not a checkout or environment writable by the MCP account. Do not expose this IPC endpoint publicly.

### Mandatory sanitized launch, before credentials

Install the fixed-path shell entrypoint root-owned `0755` as `/usr/local/libexec/inboxtether-send`, the four source files (`send_bootstrap.py`, `send_assistant.py`, `send_client.py`, `draft_assistant.py`) root-owned/non-writable under `/opt/inboxtether-send`, and an administrator-owned Python runtime at the template's fixed interpreter path. Root-owned directories must not be group/other writable. Verify interpreter, shell, bootstrap and ancestors independently before executing them: an application cannot defend against its own already-compromised interpreter or launcher. Normal administrator-controlled authentication/service launch must also exclude loader injection or tracing; the wrapper cannot undo code executed before it starts.

The launcher uses `env -i` with only fixed PATH, locale and timezone, then Python `-I -S -B`. This ignores Python environment/user-site paths and disables site initialization, `.pth` files and sitecustomize/usercustomize. No SMTP credentials are accepted through environment variables. Python bootstrap verifies isolation flags, exact sanitized environment, runtime/search-path ownership and all four source files **before application imports or configuration/credential reads**. Only then is the verified source directory added to the isolated import path. Send authority is stdlib-only; normal venv site-packages are deliberately unavailable. Direct invocation of `send_assistant.py` is unsupported and cannot invoke its main command.

As the intended sender account, validate `/usr/local/libexec/inboxtether-send --help` under the reviewed installation **before provisioning any SMTP credential**. The command performs bootstrap checks but reads no credential/configuration and makes no SMTP connection. Do not bypass a failure using a raw interpreter, `-c`, PYTHONPATH, relaxed permissions or shared MCP-owned code. Deployment tests include a hostile-environment control showing the old launch executes a harmless hook, while the new launcher ignores environment hooks and venv `.pth` files and rejects unsafe source ownership before import. These are CI fixtures, not evidence an uninspected live installation is safe.

The sender JSON pins the From/envelope identity, SMTP host/port, TLS mode (`implicit` or mandatory `starttls`), authentication username, password-file reference, authorized MCP UID, state and socket paths. There are no caller-controlled SMTP identities, hosts, credential paths or TLS bypasses. Credential value is read only by the trusted CLI after the durable claim. Provision **separate SMTP credentials** later through a secure local process, and verify the provider's actual submission-only/sender restrictions. Providers differ; a separate password does not itself prove reduced permissions. No credentials were created for development.

After explicit deployment approval, the operator would provision these files/accounts, review the service, set sender `enabled=true`, and independently opt the MCP service into preparation/status using `INBOXTETHER_SEND_ASSISTANT=1`, `INBOXTETHER_SEND_MODE=secure`, `INBOXTETHER_SEND_SOCKET`, and `INBOXTETHER_SEND_UID`. Each flag alone is insufficient to send. Do not change the existing Reader/Draft settings, IMAP credential or tunnel. Startup refuses same-UID operation, untrusted paths and Basic Send configuration. A stale broker socket needs operator inspection/removal; no automatic cleanup guesses.

## Preparation and exact review

`prepare_send_message` takes explicit To/Cc/Bcc, subject, plain-text body and optional attachment objects (`filename`, `content_type`, `data_base64`). Reply preparation additionally requires all three source identifiers: folder, UID and UIDVALIDITY. The existing Reader fetch path uses EXAMINE/BODY.PEEK; no original mail is changed. Existing threading validation constructs In-Reply-To/References from bounded parent headers. Original/source context is untrusted and shown in review, not a source of authority; the sender does not hold IMAP credentials or independently refetch the parent.

The trusted broker validates and freezes final MIME bytes, Message-ID/Date, complete SMTP envelope including Bcc, fixed sending identity and SMTP destination/configuration, reply context, expiry and attachment hashes. A SHA-256 fingerprint binds the complete manifest plus MIME digest. Any edit requires a new proposal/review; a prior draft approval is never reused. Ten-minute expiry is checked at approval, atomic claim, after authentication and immediately before DATA. Expiration prevents starting submission; it cannot recall bytes already transmitted.

Bcc stays in the protected approval manifest/envelope, **not** in transmitted MIME headers. Unicode body/subject are MIME encoded; address syntax is deliberately conservative ASCII and recipients are bounded to 20 total. No HTML body, arbitrary headers, automatic recipient inference or redirects are accepted.

The trusted operator uses a separately authenticated host session, then runs the trusted account's command (paths below are deployment placeholders, not instructions to enable this branch):

```sh
/usr/local/libexec/inboxtether-send --config /etc/inboxtether-send/sender.json review SEND_ID
/usr/local/libexec/inboxtether-send --config /etc/inboxtether-send/sender.json approve-send SEND_ID
```

The terminal shows all recipients, identity, destination, subject, full body, threading/reply context, attachment metadata/hashes and expiry. Only typing `SEND <complete fingerprint>` on that trusted interactive terminal approves and submits. Rejection/status are separate terminal commands; the MCP endpoint cannot approve, reject or submit. `send_request_status` is the only status MCP tool. IDs/fingerprints are references, not approval tokens.

For attachments, `approve-send` requires `--review-dir` naming an existing empty sender-owned `0700` directory. It exports exact MIME, full review JSON (including Bcc), and attachment bytes with generated names (`attachment-1.bin`, etc.), using exclusive `0600` files without following symlinks. Inspect these in trusted tools before confirming; nothing opens/executes/renders them automatically. An earlier separate `review --review-dir` export must use a different empty directory on final approval; existing files are never overwritten. Securely retain or remove exports under your local policy, without copying them to the repository or logs.

## Attachment limits and limitations

At most five attachments; each nonempty decoded payload at most 256 KiB, combined 512 KiB; final MIME at most 1 MiB. Allowed types/extensions: UTF-8 plain text/.txt, PDF/.pdf, PNG/.png and JPEG/.jpg or .jpeg. Type, extension, signature and text/control validation are conservative safeguards, **not malware scanning**. Archives, Office files, HTML, nested messages, paths, URLs, duplicate names and unsupported types are rejected. Bytes are never fetched by URL or path. Allowed files can still be malicious; hashes bind bytes, not safety or reviewer comprehension.

## IPC deadlines and historical receipts

Header, body, response and error writes share a single five-second monotonic deadline from broker acceptance. Each read gets only the remaining budget; slow or incomplete clients cannot renew it by dripping bytes. An expired error path closes immediately rather than allocating another timeout. Client connect/send/receive likewise share a ten-second budget. Size limits, bounded local validation and SQLite timeouts remain separate safeguards; this is not a hard realtime scheduler or an unbounded worker pool. CI verifies a slow authorized peer is disconnected and a queued healthy request resumes on the real Linux broker.

Historical integrity checks are separate from current send eligibility. The trusted operator's `status` command returns retained accepted/failed/uncertain receipts and their original approved scope even after SMTP host, port, TLS, authentication identity, sender or client-UID changes. Read-only `status`, `review` and `reject` also work when the JSON has `enabled=false`; preparation, serving and claims remain disabled. State must remain available at its configured location; moving it needs an explicit migration/reconciliation plan.

MCP status is deliberately narrower: old receipts remain readable only when the original sending identity **and** authorized MCP UID still match. Transport/credential-reference changes do not hide those minimal receipts; identity/UID changes require the trusted operator instead. IPC never accepts a `trusted` override or exposes historical message bodies/scopes. Every new claim and interactive approval still requires the exact current scope plus explicit enablement, pending state and expiry. Historical read access does not authorize resubmission, and no receipt is reset or deleted by configuration changes.

## Single attempt, SMTP outcomes and recovery

State moves from pending to a durably committed `attempting` record in one approval/claim transaction before any network activity. Expired, rejected, altered or already claimed requests cannot submit; concurrent claims have one winner. `PRAGMA synchronous=FULL` and a local SQLite database are required; do not use network storage. This does not defend against storage that lies about durability or restored/stale snapshots.

The trusted CLI uses authenticated SMTP with system CA/hostname validation, TLS 1.2 minimum, implicit TLS or mandatory STARTTLS without downgrade. Every recipient must be accepted before DATA. A refused recipient causes connection closure without DATA, preventing partial-recipient submission by this client. No SMTP debug output or raw server replies are exposed. Python audit hooks and external tracing can observe SMTP data: use a trusted runtime without message-capturing hooks, tracing, credential logging or protocol debugging.

- `accepted`: final DATA response was 250; submitted MIME bytes match the approval digest. This is submission acceptance, **not final delivery**. Relays may add DKIM/Received headers or transform messages; no byte-for-byte recipient-delivery claim is made.
- `failed`: pre-DATA failure or explicit DATA rejection. No automatic retry; resolving the cause and preparing a new proposal requires a fresh review.
- `uncertain`: connection loss during DATA, unknown final reply, worker crash/ongoing attempt, or failure to store the final receipt. **Never automatically retry or reapprove this ID.** Privately reconcile SMTP/provider logs and recipient outcomes first. A worker still submitting also reports uncertain conservatively.

Terminal CLI records an acceptance before reporting it; a failure during QUIT/close cannot erase known acceptance. Durable attempting/accepted/failed/uncertain receipts are not removed by pending-record expiry. Staging purges only expired never-attempted pending proposals. Limits: 32 pending and 256 total retained records, then fail closed until operator-reviewed maintenance. State contains plaintext mail and is not encrypted at rest: use host disk encryption, restrictive backups and short retention consistent with replay protection. There is no automatic receipt-deletion or replay-reset operation.

Standard SMTP has **no general exactly-once guarantee**. Message-ID is not an idempotency key. Replaying one ID cannot resend, but a new ID for identical content can be independently approved and sent. An operator must not create a replacement for an uncertain send until reconciliation. Never restore a pre-attempt database and re-enable sending blindly: disable sending, retain current receipts, and reconcile every potentially submitted record first. This is critical for backup/rollback, not just application retries. See [RFC 5321](https://www.rfc-editor.org/rfc/rfc5321.html) and [Python SMTP documentation](https://docs.python.org/3/library/smtplib.html).

## Optional Sent-folder synchronization (disabled by default)

Omit `sent_copy` for legacy behavior, or leave its `enabled=false` in the example. No new Python dependency or service is required. Reader and Draft tools, credentials and approvals remain unchanged. Only the separately run trusted sender terminal performs IMAP I/O; the preparation broker retains its AF_UNIX-only network restriction. No filing/discovery/reconciliation operation is exposed through MCP.

### Configuration and discovery

Use a **separate IMAP-only application password** in `sent_copy.password_file`, never the SMTP or existing Reader/Draft password. The secret must be sender-owned0600 under a private0700 directory inaccessible to MCP. The mailbox username must match the sending identity. IMAP uses implicit TLS with certificate/hostname validation and TLS1.2 minimum. The trusted startup checks the credential parent alongside other protected directories.

After administrator-controlled installation/configuration, a trusted operator runs:

```sh
/usr/local/libexec/inboxtether-send --config /etc/inboxtether-send/sender.json discover-sent
```

This authenticates, explicitly refreshes capabilities, requires UIDPLUS, reads standard LIST special-use flags and selects the unique selectable `\Sent` mailbox read-only to obtain UIDVALIDITY. It pins the policy, exact folder and UIDVALIDITY in private `state_dir/sent-destination.json`. The pin is configuration, not an approval token. No message is appended and no folder is created. If discovery is unavailable/ambiguous, set `sent_copy.folder` to an explicit existing folder and rerun discovery. Never guess folder names. Modified UTF-7, quoted and literal folder names are supported; folders with control characters are refused. This version does not enable IMAP UTF8=ACCEPT.

Preparation stays offline and refuses missing/stale pins. The full IMAP destination, credential-path reference, folder and UIDVALIDITY are fingerprint-bound in the reviewed manifest alongside the SMTP scope and exact MIME. Changed configuration/pin invalidates pending approval. Rediscover only under operator control and prepare fresh approvals afterward. The copied message is the exact submitted MIME, including Message-ID/threading/attachments, with no added Bcc header: Bcc recipients remain only in the approval envelope and private database. Newly appended copies receive `\Seen`; existing messages/flags are never changed.

### Independent send and filing receipts

SMTP acceptance is committed first. A separate `sent_copies` table in the same SQLite database records an atomic, durable single-use filing claim **before any IMAP operation**. Only an accepted send whose manifest approved filing can acquire it. One claim can issue at most one APPEND, including concurrent invocations. Before appending, verify the pinned folder still exists and UIDVALIDITY matches; search by Message-ID and verify exact bytes to recognize an already filed provider copy. Conflicting/duplicate matches block appending. After APPEND, require APPENDUID UIDVALIDITY/UID and verify size and exact bytes via `BODY.PEEK[]` without marking existing messages read. No UID EXPUNGE, STORE, MOVE, COPY, DELETE or CREATE is used.

Send status and filing state remain separate: `status=accepted` can coexist with `sent_copy=pending/saved/failed/uncertain`. With synchronization disabled/unapproved, `sent_copy=not-written` means InboxTether made no copy; it says nothing about provider-created copies. Definitive setup/connection/append rejection reports failed filing; lost acknowledgment, missing/bad APPENDUID, changed mailbox identity after APPEND, verification failure or interrupted claim reports uncertain. Neither can cause SMTP resubmission. This conservative version does not retry even definitely failed filing claims automatically.

### Recovery (trusted operator only)

```sh
# Recover a durable accepted message with NO previous filing claim:
/usr/local/libexec/inboxtether-send --config /etc/inboxtether-send/sender.json file-sent SEND_ID
# Reconcile an interrupted/uncertain append; search/fetch only, NEVER APPEND:
/usr/local/libexec/inboxtether-send --config /etc/inboxtether-send/sender.json reconcile-sent SEND_ID
```

These commands work with SMTP `enabled=false` if Sent configuration still matches the approved policy. They cannot send SMTP or approve another message. `reconcile-sent` marks saved only after an exact existing match; absence remains uncertain, never permission to reappend. A missing/unwritable/recreated folder leaves SMTP acceptance intact and produces a filing warning/receipt. Fix configuration through an operator; never create a replacement send to repair a missing Sent copy. SMTP failure/uncertainty, including lost SMTP receipt persistence, never automatically starts filing.

Standard IMAP has no generic idempotent APPEND. A lost connection cannot guarantee both eventual filing and zero duplicates. This implementation favors no second APPEND after uncertainty. It prevents its own repeated attempts; an external auto-filer can race it. Verify provider auto-filing policy before enablement. An old restored snapshot may predate a send/append claim: keep sending disabled, quarantine restores and reconcile latest durable receipts before any write. Never blindly restore old pending state then retry. Include the entire SQLite database (both tables) using consistent backup, plus the destination pin, configuration and both secrets in the encrypted off-host backup; older backup scripts must be updated/reviewed before live Sent testing. Historical send/filing receipts survive config changes and disabling; changed config never grants old approval new authority.

### Mailcow permissions and residual limits

The installed Mailcow inspected during isolated SMTP preparation supports per-application SMTP/IMAP/POP3/Sieve/EAS/DAV protocol flags. An IMAP-only application password disables SMTP for that credential, but **does not itself enforce append-only or Sent-folder-only access**. It may retain broader mailbox read/write authority. Do not claim otherwise or widen Reader credentials. Folder ACL restrictions/delegation, if configured, need independent verification on the actual deployment; no such restriction is assumed tested. Minimum required access is LIST, read-only SELECT/search/peek and APPEND on the chosen Sent folder, with UIDPLUS verification. Application code restricts operations, but compromise of the trusted sender/host can expose its broader provider-granted credential authority. Shared hosting administrator/root access remains outside the boundary. Plaintext live state and secrets require filesystem protection; encrypted backups do not encrypt live staging storage.

## Browser approval and client experience

This first implementation supports the trusted terminal only. Existing Secure Draft browser/OIDC approval is preserved, but **cannot approve sends**. Reusing that portal later requires a separate send-scoped, authenticated broker protocol, explicit Send action/CSRF checks, identity ownership, and live validation. No Pocket ID, OAuth2 Proxy, HTTPS endpoint or new identity infrastructure is required for terminal operation. ChatGPT and other MCP clients share the same preparation/status protocol; no client-specific UI behavior is claimed tested for v1.2. A browser Send button is not present.

## Validation and deployment gates

Tests use synthetic messages, mock SMTP, local Unix sockets and failure injection. CI additionally runs a dedicated Linux root test that drops to transient numeric process identities (without creating users) to verify actual peer authentication and denial of client access to sender configuration/state. Sent synchronization is validated using mocks only, not live IMAP. The earlier isolated Mailcow SMTP test does not establish live Sent behavior. No passkey/OIDC or production deployment is validated by these tests.

Before deployment: complete independent review of privilege separation and sender-runtime ownership; verify Linux hosted CI; settle SMTP account restrictions and encrypted backup/reconciliation procedure; approve isolated mock/provider testing separately; choose operator terminal workflow and retention; review actual provider MIME/Sent behavior; and explicitly authorize installation/credentials/enablement. No merge, deployment, release or real sending is authorized by this documentation.
