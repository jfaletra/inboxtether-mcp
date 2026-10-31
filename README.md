# InboxTether MCP — 2.1.0rc1 (experimental)

> **Experimental prerelease candidate:** The optional three-screen initial installer has passed the documented acceptance checks for Ubuntu 24.04. See [Setup Wizard](SETUP_WIZARD.md), [rc1 validation](RC1_VALIDATION.md) and [release notes](RELEASE_NOTES.md). Stable v2.0.0 remains the stable baseline. The wizard does not upgrade existing installations.

Your email. Your AI. Your control.

A self-hosted, fixed-account MCP stdio server for compatible AI clients. Reader Mode
is the default. Optional reply drafts, bounded folder organization, exact batch
approval, optional owner-enabled automatic filing, narrow owner preferences and
receipt-linked corrections are included.
**Email sending is absent:** no SMTP transport, sending tools, submission process,
Send/Sent settings or send launchers are included. MIME's SMTP formatting policy is
used solely to serialize drafts and is not a transport.

This experimental 2.1 candidate adds the initial installation wizard to the stable
2.0 application. It preserves up to 200-message bulk filing, compact selections,
candidate discovery, 24-hour review/start and 30-hour execution windows, manual
chat/browser approval, opt-in automatic filing and historical correction safeguards.
The new wizard adds secure mailbox metadata validation, folder mapping, private
installation and explicit desktop-client connection guidance. It creates no
permanent management dashboard or hosted AI connection. Sending remains excluded.

The reviewed wizard's regression, clean-install, download and completion-sequence
checks are recorded in [final UX validation](FINAL_WIZARD_UX_VALIDATION.md).
The owner separately verified the earlier rc1 installation through Claude Desktop's
folder-listing tool. Native x86 hardware clean-install acceptance, graphical ChatGPT
acceptance and Windows helper execution remain unverified. This is not a stable
2.1 release.

## Tools

| Opt-in | Tools |
|---|---|
| Default Reader | `list_mailboxes`, `search_messages`, `read_message`, `list_attachments`, `retrieve_attachment` |
| Draft Assistant | `prepare_reply_draft` and Basic `save_draft` or Secure `save_approved_draft` |
| Organization | `organize_email`, with 15 action-specific payloads |

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

The 2.1 wizard has installed-server MCP SDK checks, not graphical ChatGPT/Claude
connection acceptance. The following paragraph describes historical **2.0** client
acceptance only; it does not certify the new wizard or a new client version.

The historical MCP SDK/backend checks and signed-in Codex CLI/graphical Claude
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

See [rc1 validation](RC1_VALIDATION.md), [historical 2.0 validation](VALIDATION.md), [upgrade/rollback](UPGRADE.md), [security](SECURITY.md)
and [third-party licensing](THIRD-PARTY.md). Run `(umask 022; python3 -B run_tests.py)` after installing
`requirements-test.txt`; it uses temporary synthetic resources and rejects IP socket
operations in the test process. Never supply production credentials to tests.

Application source, tests and documentation are MIT. The included project icon has
separate distribution/reuse terms in `assets/BRANDING-RIGHTS.txt`; it is not MIT.
This is an independent community project, with no affiliation claim for any client
or email provider. See [release notes](RELEASE_NOTES.md). Publication, deployment
and acceptance on a new installation require separate owner review.
