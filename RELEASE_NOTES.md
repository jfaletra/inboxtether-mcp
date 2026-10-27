# InboxTether 2.0.0 release notes

## Scope

General-purpose self-hosted MCP stdio email access: reading/search, selected attachment
access, reply preparation, Drafts saving, bounded folder organization, exact batch
approval and owner-managed narrow classification preferences. Receipt-linked
corrections are included and backend-tested, but remain experimental pending
real-client/UI acceptance. The application and all existing MCP contracts are
byte-identical to published v2.0.0rc3. This preparation changes documentation,
version/provenance/validation records and the source checksum manifest only.

**Email sending is intentionally excluded from the entire 2.0 release line**, even
though earlier releases offered it. No sending tool, SMTP transport, submission
process, send capability or send launcher is included. Sending is absent, not merely
disabled. MIME SMTP formatting is used only to serialize saved drafts.

## Installation and configuration

Use the source/stdio setup in [README](README.md) and [installation](INSTALLATION.md).
Reader is the default; writes are opt-in. Organization/browser components require
Linux/POSIX identities, Unix sockets, protected files and explicitly reviewed mailbox
ACLs. No model key, extra AI provider, database, tunnel or assistant-specific service
is bundled. Fresh installation is supported; automatic legacy/private-state import
and in-place production migration are not provided.

The Drafts mailbox must already be selectable and advertise IMAP `\Drafts` special
use; its name alone is insufficient. Organizer uses six exact existing wire folder
paths and UIDVALIDITY pins. Folder hierarchy and authentication/master-login
separators are distinct; `*` is unsupported in configured folder paths and login
names. The supported character sets, Dovecot test example and preflight are documented
without changing the application validators.

## Approval trust

Browser approval authenticates the enrolled local owner through a separate password
session, with exact fingerprint, expiry and CSRF checks. Client tool permissions are
not a substitute for that owner approval. Optional `client-session-consent` delegates
decision relay to the authorized MCP connection: it cannot independently prove that
a human reviewed or approved the action. It is a lower-assurance mode, including
preference approval. Rules and classifications never authorize moves automatically.
Customer/uncertainty/Keep protections, source/flag/folder integrity, durable receipts
and replay prevention remain unchanged. See [workflows](WORKFLOWS.md).

## Acceptance and limitations

Unchanged rc3 passed real Dovecot/backend acceptance and actual signed-in Codex CLI
and graphical Claude Desktop smoke tests with synthetic mail. Claude completed 19
successful MCP calls. Codex recorded 24 calls: 22 completed and two safely blocked
initial calls requiring corrected client permission settings and explicit payload
guidance. Both then completed reading/search, reply preparation, one Drafts save,
one separately approved verified move and narrow preference approval/inspection/
revocation. These were guided tests of specific configurations.

Graphical Claude testing was actual native Desktop chat/MCP use, not CLI/SDK
simulation. Browser approval was programmatic HTTPS login/review against the real
approval service; no graphical browser approval UI was exercised. Drafts used Basic
mode and preferences used lower-assurance client-relayed consent. The full distinction,
prior synthetic evidence and unverified workflows are in [validation](VALIDATION.md).
No production mailbox or ordinary ChatGPT graphical acceptance is claimed.

Attachment UI/download handling, secure browser-approved Drafts, client-driven future
rule matching, receipt-linked corrections in a graphical client, other clients/models
and provider configurations remain unverified by these two client passes. Keep their
documented limitations; no universal compatibility certification is implied.

Before updates retain protected source/configuration backups and all private state;
follow [upgrade/rollback](UPGRADE.md). A source rollback never reverses mail, removes
attempt claims or permits uncertain retries. Production deployment requires separate
authorization. Root MIT, third-party notices and separate artwork restrictions remain
unchanged; dependencies are not vendored. See [third-party licensing](THIRD-PARTY.md).
