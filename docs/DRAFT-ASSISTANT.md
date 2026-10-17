# Draft Assistant: v1.1 development architecture and security review

Status: implemented on the development branch, **disabled by default**, tested with synthetic mail only. No running deployment, mailbox ACL, credential, tunnel or production service is changed. Mailcow remains the first verified **Reader** platform; Draft Assistant has no live provider certification. Send Assistant is not implemented.

## Architecture and invariants

The existing five Reader tools, parsing, attachment selection and ReadOnlyIMAP command guard are preserved. Missing configuration keeps exactly those five tools. Reader connections always use EXAMINE and BODY.PEEK and cannot APPEND. No SMTP module, sending tool, transport, credential or configuration is introduced.

Opt-in adds two tools:

| Tool | Inputs and effect |
| --- | --- |
| `prepare_reply_draft` | Original `mailbox`, `uid`, `uidvalidity`; explicit `to` array, `subject`, `body`; optional `cc` and `bcc` arrays. Reads the bounded original and target identity, freezes MIME, stores a private local pending record, returns preview/ID/fingerprint. Does not write mail. |
| `save_approved_draft` | Only `draft_id`. Requires separate unexpired operator approval, revalidates source/target, consumes approval durably, appends the frozen MIME once and reads it back. No replacement content, destination, `approved` flag or approval token is accepted. |

Preparation does not infer recipients from untrusted From/Reply-To fields. From is the fixed configured account. The original must have one valid Message-ID; In-Reply-To refers to it, and References retains the validated bounded chain. Missing/ambiguous/malformed threading headers fail closed. New Date and Message-ID are generated once and then frozen.

Canonical MIME uses UTF-8 plain text, quoted-printable and CRLF. The canonical preview includes all recipients (including Bcc), decoded subject/body, From, Date, Message-ID, In-Reply-To and References. The email library normalizes line endings and adds a terminal body newline; review the frozen preview rather than assuming it is byte-identical to tool input. There is no HTML, arbitrary-header injection, draft attachment, new-message composer or reply-all inference.

The fingerprint covers the complete canonical manifest: sender/recipients/content/headers, exact MIME digest, source folder/UID/UIDVALIDITY and SHA-256, configured host/account/Drafts folder, target UIDVALIDITY and expiry. An edit prepares a separate pending record and requires a separate review; it cannot replace an approved record. Existing approved records remain independently eligible until expiry, so operators must approve only replies they intend to save.

## Why approval is outside MCP

The [MCP maintainers' tool annotation guidance](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/) treats annotations as hints, not enforcement. Client prompts, elicitation support and authorization UX differ across clients and versions. A model-supplied boolean, text stating the user agreed, or a bearer token disclosed to that model is insufficient evidence of a fresh human review. This implementation does not depend on optional elicitation or a particular client's prompt.

Recommended initial implementation: a separate **trusted local operator CLI**, with no approval tool exposed over MCP. The CLI prints the full frozen manifest as escaped JSON, labels it untrusted, requires an interactive terminal, and requires typing `APPROVE <full-fingerprint>`. It grants one save only, with the original 10-minute expiry. It does not itself contact IMAP or save mail. MCP tool hints correctly mark both Draft tools as non-read-only because preparation writes private local state. Native client approvals may add protection but cannot replace this server-side gate.

This assumes a trusted operator and host. A TTY is not human authentication. A model with a shell, filesystem access as the service user, the approval database or mailbox password can bypass this boundary; **do not connect such tools/access to the drafting model**. Protect the entire ancestor path, local backups and operator session. Use a dedicated service account. If this isolation is unsuitable, leave Draft Assistant disabled and design a separately authenticated, isolated approval broker/UI before deployment. Such a broker is not included or claimed secure here.

## Configuration (not enabled by this change)

The shipped [configuration example](../examples/config.env.example) explicitly sets `INBOXTETHER_DRAFT_ASSISTANT=0`. Python does not load that file automatically. No new dependency is required: approval storage uses standard-library SQLite.

An **operator-approved future opt-in** must supply all three settings through a protected service/client configuration:

- `INBOXTETHER_DRAFT_ASSISTANT`: exact value `1`; otherwise unset/`0` is Reader-only. Other values cause startup failure.
- `INBOXTETHER_DRAFTS_FOLDER`: fixed existing ASCII IMAP wire name, for example `Drafts`. Callers cannot override it. Common non-Drafts targets, wildcards, quotes, backslashes and control characters are refused. Nested ASCII folder wire names can be configured explicitly.
- `INBOXTETHER_DRAFT_STATE_DIR`: absolute directory outside the repository, owned by the service user with mode `700`; for example `/var/lib/inboxtether-mcp/draft-state`. Provision it through the trusted operator, not an MCP call. The database is a regular owner-only `600` file; symlink state directories/databases and unsafe modes are rejected. Trust and protect ancestor paths.

The configured account must be a conservative ASCII bare email address. Sender aliases, display-name addresses, SMTPUTF8 and internationalized domains are unsupported. The same protected IMAP app password is read using existing ownership/mode/symlink safeguards. No new password input is exposed. If possible, use provider ACLs that permit reading and inserting into only the Drafts folder, not unrelated writes. This code cannot reduce the permissions of an existing full-access password.

The folder must already exist, advertise the `\Drafts` special-use flag in its exact LIST result, be selectable through EXAMINE, and provide UIDVALIDITY. UIDPLUS and APPENDUID are mandatory. The implementation never creates or renames folders and does not guess localized names. Servers that do not expose these exact capabilities are refused even if they have a folder named Drafts. Folder selection and [UIDPLUS](https://www.rfc-editor.org/info/rfc4315/) behavior need explicit live acceptance testing; no cross-provider compatibility is claimed.

## Operator review and save sequence

1. In the client, choose the original by folder/UID/UIDVALIDITY and ask for a proposed reply. Supply all intended recipients explicitly. Treat the original and proposed reply as untrusted.
2. Call `prepare_reply_draft`; show its returned canonical preview, ID and fingerprint. It saves no mailbox message.
3. Independently, on a trusted terminal under the configured service account/environment, run `.venv/bin/python draft_assistant.py approve <draft_id>` from the source checkout. Do not run it through an AI shell tool or put content/secrets in command arguments. The CLI loads the same configured host/account/folder/state and independently prints the stored content, including Bcc and threading headers. Review every field; enter the full requested fingerprint only if correct. Piped input and a generic `yes` are refused.
4. Call `save_approved_draft(draft_id)` within ten minutes of preparation. This call rechecks original bytes and destination UIDVALIDITY. It accepts no new content. A transaction atomically consumes the approval before any APPEND, preventing concurrent/replayed writes.
5. A separate DraftAppendIMAP adapter grants one exact APPEND literal to the configured folder with only the `\Draft` flag. No SELECT, STORE, COPY, MOVE, DELETE, CREATE, EXPUNGE or CLOSE is permitted. The connection closes without expunge. Existing messages are never deliberately changed, replaced or deleted.
6. Successful APPENDUID must identify the expected UIDVALIDITY and one UID. The server EXAMINEs and fetches that UID with BODY.PEEK; the stored MIME must equal approved bytes exactly. Only then is `status: saved` returned with UID, UIDVALIDITY and SHA-256. Reader access remains unchanged.

Thread headers follow the [Internet Message Format](https://www.rfc-editor.org/info/rfc5322/) conventions. Clients control actual thread presentation; header preservation is not a universal threading guarantee. Bcc is retained inside the private draft so the user can review it. If a user later chooses Send in their mail client, that is outside this integration; this application never sends.

## Limits, failures and reconciliation

Up to 20 distinct explicit recipients across To/Cc/Bcc, subject 200 characters, body 20,000 characters, serialized MIME 64 KiB, and 32 staged records per state directory. At least one To is required; duplicate addresses across groups, CRLF/control/format characters in headers, control/format characters in body (except LF/tab), empty content and unsupported address syntax fail before network access. Existing Reader resource/TLS/wire limits also apply.

Approval expires ten minutes after preparation, without extension on review. Exact saved retries return the prior receipt without another APPEND while the record is retained/unexpired. Crash/disconnect/missing APPENDUID, invalid identity, server byte rewriting or failed read-back after an attempt produces `uncertain`, never a retry/delete/replace/flag-repair. If the process crashes after claiming but before recording a result, a subsequent call is also uncertain, even if no message was actually stored. There is no general exactly-once delivery guarantee over IMAP.

On uncertainty, stop automated saving. A trusted operator must privately reconcile whether that draft exists in their mail client before preparing/approving anything again. Never blindly reprepare a duplicate or use deletion as an automatic rollback. Do not reset, replace or share approval state to recover a retry. Approval state must be on a local filesystem supporting SQLite locking/durability; use one service/account per directory. Multi-process locks protect the same approval, not global mailbox concurrency or distinct approved drafts.

Standard IMAP does not offer an APPEND conditional on destination UIDVALIDITY or a transaction spanning source validation and APPEND. Concurrent remote folder deletion/recreation between validation and write remains a residual race; post-write identity checks can detect but cannot undo it. An administrator/server with mailbox access is trusted. Avoid concurrent folder administration during an approved save; require a separately approved live test and suitable provider ACLs before enabling.

## Sensitive local state and logs

The pending database contains complete draft recipients/text, MIME and source identifiers. It is **not encrypted at rest**. Records expire logically after ten minutes and expired rows are purged on the next preparation, not by a background timer. SQLite deletion is not secure erasure; journal/backups/filesystem snapshots can retain bytes. Keep state out of source control, artifacts, cloud sync and model-accessible paths; use encrypted storage and a deliberate local retention/backup policy. Ignore rules are defense in depth, not a storage policy. Tool previews also reach the MCP client's logs/storage.

Do not log protocol traffic or raw database rows. Generic unexpected errors suppress underlying exception/server text. Reconciliation and operator review inherently reveal private content locally and must not be copied to issues, CI or this repository.

## Evidence and approval gates

Tests use synthetic fixtures, a socket pair exercising real imaplib APPEND framing, protected temporary SQLite directories, concurrency races, and real MCP stdio discovery/error paths. No live mailbox login, message append, ACL change or production restart is performed. See [validation](../VALIDATION.md).

Before deployment: approve the local operator trust model and workflow; approve any provider permission/configuration change; separately authorize live tests against a dedicated test Drafts folder/account and inspect existing flags/content; review filesystem hardening/state backups; confirm fail-closed behavior for the actual Mailcow capabilities and exact-byte persistence. A live failure must not trigger automatic deletion or retry. Merge, release and production rollout remain separately gated. Reader-only users can continue with the switch unset/0.
