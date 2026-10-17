# InboxTether MCP v1.2.0 — Secure Send Assistant and optional Sent copies

Prepared release notes, not a published release. PR #6 remains unmerged; no tag,
production deployment, credential provisioning or feature enablement is authorized
by this document. Runtime reviewed/live-tested at `b92ab52`; release documentation
is prepared afterward. Publication must name the final successful merge commit.

## Reader and Draft compatibility

Reader remains the default, with the same five tools/schemas and read-only IMAP
protections as v1.1. Basic and Secure Draft Assistant retain their existing
explicit opt-ins, threading, approval, expiry and uncertain-save protections.
Basic Draft confirmation still depends on client behavior; actual ChatGPT testing
showed full review/per-save confirmation cannot be guaranteed. Use Secure Draft
where independent approval is required. Its browser portal still needs separate
HTTPS/OIDC configuration and live validation; it cannot authorize sends.

## Optional Secure Send Assistant

Disabled by default. There is **no Basic Send Mode**. MCP exposes only message
preparation and status, never sending or approval. A separate unprivileged Linux
sender account owns SMTP credentials/state; a separately authenticated trusted
operator reviews and types the exact fingerprint on a terminal for every send.
A TTY is not proof of a human: never give the AI this account, terminal, sudo,
private files, mutable source/runtime or approval authority.

The frozen approval binds sending identity, SMTP destination, complete To/Cc/Bcc
envelope, subject, plain-text body, threading, MIME and attachment hashes, ten-minute
expiry, and optional Sent destination/policy. SMTP uses certificate-validated TLS
1.2+ with implicit TLS or mandatory STARTTLS. Every recipient must be accepted
before DATA. An atomic durable claim prevents concurrent/replayed submissions.
Unknown SMTP outcomes are never automatically retried or replaced.

Up to five explicitly supplied supported attachments are bounded to 256 KiB each,
512 KiB combined and 1 MiB serialized MIME. Content/type/signature checks are not
malware scanning. HTML, arbitrary headers, URLs and filesystem attachment reads
are not provided. Bcc appears in the private review envelope, not submitted MIME.

## Optional Sent synchronization

Disabled by default and independently configured. A separate IMAP-only credential
is available only to the trusted sender. Authenticated special-use discovery pins
an existing Sent folder/UIDVALIDITY; ambiguous/missing discovery requires an
explicit existing-folder override. No folder is guessed or created.

Only durable SMTP acceptance can begin a one-use filing claim. Exact submitted
MIME is appended once and checked through APPENDUID/UIDVALIDITY and non-marking
byte readback. Filing failures never call SMTP. Interrupted/ambiguous appends are
reconciled by searching and verifying an existing exact copy, without appending
again. SMTP and filing receipts are separate: an immutable SMTP receipt can say
`sent_copy=not-written` while the later filing receipt correctly says `saved`.
No deletion, moving, or alteration of existing mail is added.

## Validation and limits

217 local tests: 215 passed, two privileged Linux cases skipped on macOS; both
privileged cases also passed hosted CI. Coverage includes unchanged Reader/Draft
behavior, terminal enforcement, TLS/refusals, exact content, expiry, replay,
concurrency, IPC deadlines, startup isolation, lost receipts, IMAP uncertainty and
SQLite recovery. Runtime/browser/audit-tool dependency audits report no known
vulnerabilities. Recheck all results on the exact final release commit.

Controlled isolated Mailcow tests verified TLS/authentication, SMTP acceptance,
recipient receipt, authenticated UIDPLUS/special-use discovery, one independently
approved send-and-file, and one exact matching Sent copy via read-only readback.
The operator independently confirmed recipient receipt and Sent visibility.
Synthetic quarantine restore verified historical receipts and non-retry state;
encrypted backups were retained off-host with the private recovery key outside
the VPS. These are bounded tests, not broad provider/client certification. Live
v1.2 ChatGPT/Claude UI, non-Mailcow servers and browser Send approval are unverified.
An initial discovery reporting-harness error occurred after successful EXAMINE;
it was not an application bug, did not retry, and a later read-only verification
completed cleanly.

SMTP/IMAP cannot guarantee global exactly-once delivery or filing. An external
auto-filer may race; conservative no-retry policy may leave a missing Sent copy.
Mailcow protocol-limited app passwords do not alone impose Sent-only/append-only
ACLs or a fixed recipient allowlist. Verify provider permissions independently.
Live staging/secrets are plaintext behind filesystem permissions; encrypted
backups do not encrypt the running host. Stolen trusted-account/root/operator
access remains outside the independent-approval boundary. Retain current receipts:
blind restoration of older pending state can defeat replay history.

## Installation, upgrade and release gates

See [upgrade and rollback](docs/UPGRADING-v1.2.md), [Send setup/security](docs/SEND-ASSISTANT.md)
and [final review](security/V1.2-RELEASE-REVIEW.md). Reader-only upgrades need no SMTP
credential, separate sender service, new port, browser or identity provider.
Enabling send/filing remains a separately approved deployment step. No registry
package, hosted endpoint, public plugin, Docker image or automatic upgrade is
published here. Source/docs retain MIT; branding remains outside MIT. Previously
accepted naming uncertainty remains; no trademark clearance is claimed.

Proposed tag: `v1.2.0`, created only after explicit publication approval at the exact
post-merge validated commit. Prepare source archives and SHA-256 manifest then;
none is published or tagged by this review. Merge, deployment and publication
require separate owner authorization.
