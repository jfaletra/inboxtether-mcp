# InboxTether MCP 2.1.0rc1

A local, unreleased calendar-focused candidate based on the public 2.0.0 email
release. It adds reusable Mailcow/SOGo CalDAV calendars, standalone creation,
controlled invitations and read-only CardDAV contact lookup. It uses an existing
owner-authenticated MCP connection; no additional server, tunnel or approval UI is
required. No commit, tag or GitHub release has been published for this candidate.

Reader Mode remains the default. Email tools, draft approvals, filing protections
and optional owner-authorized automatic filing retain the public 2.0.0 implementation.
No production-only email adapters or business-specific filing policies are imported.
The email module has no SMTP transport or email sending tools. Optional calendar
invitations use SOGo scheduling and do not add an email sender.

## Tools and opt-ins

| Area | Tools |
| --- | --- |
| Email reader | list_mailboxes, search_messages, read_message, list_attachments, retrieve_attachment |
| Basic drafts | prepare_reply_draft, save_draft (Secure mode retains save_approved_draft instead) |
| Organization | organize_email, with the existing action-specific approval/filing contract |
| Calendar reads | calendar_list_calendars, calendar_list_events, calendar_get_event, calendar_search_events, calendar_free_busy |
| Owner-connection creation | calendar_prepare_create, calendar_commit_create, calendar_reconcile_operation |
| Read-only contacts | contacts_list_address_books, contacts_search |

With Basic drafts, organization, creation and contacts configured, this is an
18-tool inventory. New installations do not enable those opt-ins automatically.
Private deployments may retain their existing organization tool name; the public
factory keeps its generic organize_email name. No email permission is expanded.

## Mailcow/SOGo calendars and contacts

Use [the existing-connection runbook](deploy/calendar/README.md) and sanitized
[configuration examples](examples/calendar). Each account has its own protected
DAV app-password file, exact calendar/book read allowlists and optional calendar
aliases. An address-book alias is a conversational label, not a configuration field.
Creation and invitations are disabled in the examples. Updates, rescheduling,
cancellations, recurrence writes and contact writes remain disabled.

Search and availability use selected calendars, resource/version checks and at most
a 31-day offset-bearing window. Free/busy returns intervals without event details
and requires explicit full-visibility assertions. Contact lookup locally matches
exact/partial names after a bounded scan of up to 2,000 contacts per book, retaining
all usable addresses and explicit ambiguity/truncation flags. It never guesses email.

Standalone creation defaults to Public/Busy, supports explicit overrides and uses
random UIDs/URLs, preflight, serialized writes, persistent quotas/idempotency and
read-back. SOGo 5.12.5 failed atomic conditional-write safety tests. Creation has a
residual overwrite race; updates and cancellation are not approved. Uncertain writes
require original-operation reconciliation, never a fresh automatic attempt.
Invitations pin the organizer to the account and restrict recipients separately.
Verified event storage does not prove invitation dispatch or delivery.

The assistant asks for conversational confirmation. The server authorizes the owner
connection and records human_approval_verified=false; it cannot verify a human click.
Google coordination, synchronization, booking workflows and contact writes are outside
this MCP. See [calendar policy](CALENDAR_RADAR.md), [invitations](CALENDAR_INVITATIONS.md),
[CardDAV](CARDDAV_CONTACTS.md) and [unsupported updates](CALENDAR_PHASE2.md).

Install optional calendar dependencies with the existing constraints:

```sh
python -m pip install -c constraints-validated.txt -r requirements-calendar.txt
```

The accepted baseline is 670 offline synthetic tests, including 39 focused CardDAV
cases. [Validation](VALIDATION.md) distinguishes those tests from owner-reported
component live acceptance and the unverified public-candidate deployment. Historical
approval prototypes are documented separately and are not normal calendar workflows.

Organization actions: `next`, `propose`, `prepare`, `status`, `execute`, `consent`,
`cancel`, `candidates`, `automatic_policy`, `correction_context`, `preferences`, `prepare_preference`,
`decide_preference`, `filed_context`, `prepare_correction`.

There is no server-side AI provider or model key. The connected assistant proposes
classifications; local policy independently applies customer, identity, uncertainty,
source integrity, exclusion and approved-preference constraints. Proposals and preference rules alone never authorize moves. Manual mode requires
exact manifest consent. Optional automatic mode requires the independently enabled
owner policy and files only Industry, Marketing, Orders and Suppliers. Customer,
potential-customer, mixed and uncertain mail and all Review messages remain in Inbox.
Both execution modes are disabled by default. See [automatic filing](AUTOMATIC_FILING.md).
The tool schema documents exact required fields.

## Quick start: Reader only

Use an isolated Python environment (Python 3.11+; intended server target Linux).
From the extracted source directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-validated.txt -r requirements.txt
```

Configure the client using `examples/stdio-client.json`, replacing its example paths,
account and host. Provision the IMAP password file privately, owned by the Reader
service identity, mode 0600, under a private directory. Do not put credentials in
chat, command arguments, environment examples, logs or the repository.
The client launches `.venv/bin/python server.py` and owns its stdin/stdout. This
starts no public HTTP endpoint. Read connections use TLS, EXAMINE and BODY.PEEK.
The fixed host/account cannot be selected by tool arguments.

Draft saves require a selectable mailbox advertising the IMAP `\Drafts` special-use
flag. Organizer requires exact literal folder paths; its login-name constraints reject
`*`, including master-login names that use it. Folder hierarchy and authentication
separators are distinct; see the installation prerequisites below.

See [installation](INSTALLATION.md) for Draft Assistant, organization, browser review,
roles, mailbox rights and clean initialization. Read [approval and learning](WORKFLOWS.md)
before enabling write capabilities. All write switches are off by default.

## Compatibility and limitations

The MCP SDK/backend checks and actual signed-in Codex CLI and graphical Claude
Desktop acceptance are distinct evidence. Claude completed 19 successful MCP calls;
Codex completed the same bounded workflows after two safely blocked initial calls
and corrected client permissions/guidance. Both used disposable Dovecot mailboxes.
Browser-password-session approval used the real verified HTTPS service driven by
an operator harness, not a graphical browser. Draft saves used Basic mode; preference
decisions used optional lower-assurance client-session consent. See the exact
[acceptance matrix and limits](VALIDATION.md) before making compatibility claims.
Ordinary ChatGPT graphical acceptance, secure browser-approved Drafts, graphical
corrections and other provider/client configurations remain unverified in these
client passes. Use a client's supported stdio launcher or independently configured
MCP transport; no assistant-specific plugin, tunnel or authentication platform is
bundled or required by the application protocol.
Client prompts may omit details or remember grants. They are not independent proof
of an owner decision. See [trust guarantees](WORKFLOWS.md).

Organization/browser processes require POSIX users, Unix sockets and peer credentials;
Linux service templates are supplied. Native Windows organization is unsupported.
Five logical filing categories are fixed: Industry, Marketing, Orders, Review and
Suppliers, plus Inbox / Keep. Exact wire folders and UIDVALIDITY are operator-pinned;
custom display labels and automatic folder creation are not supported.
Initial discovery is bounded to 20,000 UIDs per discovery page; over-limit inventories
fail closed and need operator assessment, not silent truncation. Private journals are
bounded to 16 MiB; preference/review record caps also fail closed. There is no automatic
compaction, migration, background organization, uncertain-move retry or inverse rollback.

Attachment retrieval is explicitly selected, bounded and returns Base64 rather than
a native download UI. Mail and attachments are untrusted; no malware guarantee is made.
Practical organization uses content/relationship protections, not a guarantee of sender
authenticity, delivery provenance, or independent DKIM verification. Unknown suppliers
cannot gain supplier status through a learned category rule. Historical Keeps are
not automatically reconsidered. Conservative customer keywords, reply identities,
MIME handling and context-omission safeguards can produce false Keeps; owner-reviewed
one-message corrections preserve prior history and cannot bypass these safeguards.

## Verification and release status

See [validation](VALIDATION.md), [upgrade/rollback](UPGRADE.md), [security](SECURITY.md)
and [third-party licensing](THIRD-PARTY.md). Run `python run_tests.py` after installing
`requirements-test.txt`; it uses temporary synthetic resources and rejects IP socket
operations in the test process. Never supply production credentials to tests.

Application source, tests and documentation are MIT. The included project icon has
separate distribution/reuse terms in `assets/BRANDING-RIGHTS.txt`; it is not MIT.
This is an independent community project, with no affiliation claim for any client
or email provider. See [release notes](RELEASE_NOTES.md). Publication, deployment
and acceptance on a new installation require separate owner review.
