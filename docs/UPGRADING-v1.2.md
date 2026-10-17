# v1.2 installation, upgrade and rollback

A reviewed runbook, not authorization to modify a running service. PR #6 targets
an unreleased v1.2.0. Use an exact separately approved release commit, not a moving
branch. Publication, installation, credentials and opt-in are separate decisions.

## Reader/Draft upgrade: no SMTP authority

1. Record current revision, launcher/service configuration, environment and
   dependency versions. Preserve existing Reader credentials, tunnel/profile,
   service identities and every already-approved Draft policy. Do not silently
   enable, disable or switch an existing Basic/Secure Draft deployment.
2. Make a protected backup and verify a quarantine restore. Keep source/config
   rollback separate from current message/approval receipt history. Never put
   secrets, state, profiles, exports or backup keys in Git/source archives/logs.
3. Stage the exact verified source in a separate versioned directory. Reader
   runtime needs `server.py`, `draft_assistant.py`, **`send_client.py`** (imported
   during tool registration even when sending is disabled), and unchanged
   `requirements.txt`. Preserve the compatible verified environment; review any
   dependency change separately. Deployment baseline is Linux/Python3.12/MCP1.30.0.
   Sender code runs separately and is not needed for a Reader-only deployment.
4. Set the NEW `INBOXTETHER_SEND_ASSISTANT=0`; do not copy an enabled example or
   obsolete test helper into production. For a new Reader-only installation also
   leave Draft/browser switches0. Existing Draft opt-ins are preserved, not reset.
   No SMTP/filing credentials, IdP, public port or sender broker is necessary.
5. Verify full synthetic suite, dependency consistency and strict runtime/browser/
   audit-tool audits, plus tracked/history hygiene. Refresh exact-commit hosted
   checks. Local tests may skip two privileged Linux cases; hosted isolation must
   succeed separately. The full test suite needs optional browser dependencies;
   the Reader runtime does not.
6. Only in an approved maintenance window change the launcher/restart the intended
   MCP service. Preserve the current tunnel ID, profile, credentials and systemd
   settings. Refresh client tool discovery without deleting/recreating the tunnel
   as a routine upgrade. Validate five Reader tools and only the existing enabled
   Draft tools against synthetic data; check unchanged source bytes/flags. No Send
   tools should be present by default. Roll back code/config if validation fails.

## Optional Secure Send: separate administrator review

Follow [the full sender guide](SEND-ASSISTANT.md). Minimum requirements: separate
non-root sender/MCP identities with no sudo/Docker access; private local Unix IPC;
root-controlled shell/interpreter/bootstrap and four stdlib-only sender sources;
private sender-owned state0700 and config/secrets0600; sanitized fixed-path
`env -i`/Python `-I -S -B` entrypoint. Verify bootstrap and real identity isolation
BEFORE introducing secrets. A mutable MCP-owned checkout/venv is not a trusted
sender runtime. The broker remains AF_UNIX-only; trusted terminal approval runs
separately with outbound TLS. No browser Send or Basic Send fallback is available.

Use a dedicated SMTP-only application password where supported, with the provider's
minimum sender rights. Preserve Reader/Draft credentials. Never pass secrets in
argv, environment, logs, chat or tracked configuration. Operator-hidden input and
private storage need verification, not just a successful prompt. Scope references
credential paths, not credential value fingerprints: rotating contents in place
does not automatically revoke pending approvals. Invalidate outstanding proposals
operationally (reject them before changing credentials) and prepare fresh reviews.
Do not assume SMTP-only also restricts recipients or all possible sending aliases.

Enabling the sender master flag/broker and MCP preparation/status requires separate
approval and the documented secure mode/socket/UID configuration. Those flags do
not approve messages. Every submission still requires a fresh independently
reviewed terminal fingerprint before original expiry. Never automate terminal
confirmation, give the AI the trusted shell, or retry ambiguous DATA outcomes.

## Optional Sent filing: separate IMAP authority

Use a NEW dedicated IMAP-only credential stored solely under trusted sender
ownership; do not reuse Reader/Draft or SMTP secrets. Mailcow app-password protocol
switches do not establish folder-only/append-only ACLs. Review actual rights and
provider auto-filing behavior before enabling this optional feature.

After explicit Sent opt-in authorization, `sent_copy.enabled=true` permits trusted
Sent operations even when SMTP `enabled=false`; it is not merely a discovery flag.
With sending still disabled, run trusted `discover-sent` to authenticate, refresh
capabilities and pin the unique existing `\\Sent` folder and UIDVALIDITY. Use an
explicit existing-folder override if missing/ambiguous; require UIDPLUS. Inspect
private `sent-destination.json`. No folder is automatically created. New message
preparation remains offline and fingerprint-binds this exact policy/destination.
Changing settings or rediscovery requires fresh pending-message review.

Before any send-and-file approval, verify a consistent encrypted backup containing
both secrets, config, destination pin and BOTH SQLite tables (`sends`, `sent_copies`).
Startup lazily creates the filing table; historical message rows remain unchanged.
A legacy accepted message with no approved filing manifest cannot be retroactively
filed. Reconcile ambiguous append claims only with trusted `reconcile-sent`, which
cannot append or send. `file-sent` can file only a previously approved accepted
message with no filing claim and matching scope. Definitive failed filing claims
also have no automatic retry. Preserve newest receipts even after disabling.

## Encrypted backups and quarantine recovery

The isolated validation used age encryption with a dedicated key generated and
retained off-host. This is an administrator backup procedure, not an application
built-in or universal installer. Reproduce it for each deployment and test restore:

- Keep only the public encryption recipient on the server. Retain the private
  recovery key in protected off-host storage and a separate encrypted/offline
  recovery copy. Losing the key makes snapshots unrecoverable. Protect the live
  disk separately; an encrypted archive does not encrypt live mail/state/secrets.
- Quiesce ONLY the isolated sender/approval operations during an approved window
  or use SQLite's online backup API. Keep related configuration/pin stable during
  capture. Do not copy a live DB while ignoring its WAL/journal.
- Stream the archive into encryption without plaintext tar files. Use restricted
  temporary SQLite snapshots, clean them after completion, and inspect leftovers
  after interruption. Include exact source/launcher/bootstrap/backup-tool hashes,
  config, private state/pins, both secret files, ownership/modes and all receipts.
- Retain ciphertext off-host, verify checksums, decrypt on trusted hardware and
  verify every member/SQLite integrity. Restore into quarantine; reject links,
  traversal, unexpected members and unsafe ownership. Never promote a snapshot
  into a live enabled sender automatically.
- Preserve newest active DB/journals/receipts before recovery. SMTP/IMAP attempts
  that occurred after an old snapshot may be absent from it. Reconcile every
  potentially attempted message with latest receipts/provider/recipient evidence;
  do not blindly reapprove restored pending proposals. Interrupted attempting
  states remain uncertain, never retry permission. A delivery cannot be recalled
  by restoring files. Expiry is not erasure or permission to reuse an approval.

## Rollback

During a separately approved window disable Send Assistant and Sent filing, and
stop ONLY the optional sender broker if running. Capture the latest consistent
receipt DB plus config/pins/secrets in a verified encrypted snapshot BEFORE changing
code. Restore the previously pinned Reader/Draft code/environment/launcher and
configuration; preserve current credentials and prior Draft policy, then verify
Reader/Draft and refresh client discovery. Do not restore older send/filing state,
delete receipts, drop tables or replay approvals to achieve a code rollback.

Retain current sender DB/pins and both secrets privately even if the older runtime
cannot display them. Use the matching reviewed sender revision in disabled,
quarantined operator recovery when historical inspection is needed; do not make
the MCP account its owner. Do not downgrade or edit a live SQLite DB in place.
Already sent/created mailbox messages remain untouched. Rollback must not invoke
SMTP, APPEND, deletion, movement or flag changes; it cannot undo delivery. A failed
Sent copy must never be repaired by resending the email. Production Mailcow or
other services are not part of application rollback.
