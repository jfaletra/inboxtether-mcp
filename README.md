# InboxTether MCP — 2.0.0rc3

Your email. Your AI. Your control.

A self-hosted, fixed-account MCP stdio server for compatible AI clients. Reader Mode
is the default. Optional reply drafts, bounded folder organization, exact batch
approval, narrow owner preferences and receipt-linked corrections are included.
**Email sending is absent:** no SMTP transport, sending tools, submission process,
Send/Sent settings or send launchers are included. MIME's SMTP formatting policy is
used solely to serialize drafts and is not a transport.

This is a review candidate, not a published release or deployment. Organization and
new-client workflows are experimental pending controlled live acceptance. Mailcow
is the previously validated provider; other IMAP providers are not certified.

## Tools

| Opt-in | Tools |
|---|---|
| Default Reader | `list_mailboxes`, `search_messages`, `read_message`, `list_attachments`, `retrieve_attachment` |
| Draft Assistant | `prepare_reply_draft` and Basic `save_draft` or Secure `save_approved_draft` |
| Organization | `organize_email`, with 13 action-specific payloads |

Organization actions: `next`, `propose`, `prepare`, `status`, `execute`, `consent`,
`cancel`, `correction_context`, `preferences`, `prepare_preference`,
`decide_preference`, `filed_context`, `prepare_correction`.

There is no server-side AI provider or model key. The connected assistant proposes
classifications; local policy independently applies customer, identity, uncertainty,
source integrity, exclusion and approved-preference constraints. Proposals and rules
never move messages automatically. The tool schema documents exact required fields.

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

See [installation](INSTALLATION.md) for Draft Assistant, organization, browser review,
roles, mailbox rights and clean initialization. Read [approval and learning](WORKFLOWS.md)
before enabling write capabilities. All write switches are off by default.

## Compatibility and limitations

The MCP SDK stdio handshake, tool declarations, synthetic tool calls and Unix broker
flows are tested. ChatGPT and Claude are intended compatible-client targets, not
certified live UI integrations for this candidate. Use a client's supported stdio
launcher or independently configured MCP transport; no assistant-specific plugin,
tunnel or authentication platform is bundled or required by the application protocol.
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
cannot gain supplier status through a learned category rule.

## Verification and release status

See [validation](VALIDATION.md), [upgrade/rollback](UPGRADE.md), [security](SECURITY.md)
and [third-party licensing](THIRD-PARTY.md). Run `python run_tests.py` after installing
`requirements-test.txt`; it uses temporary synthetic resources and rejects IP socket
operations in the test process. Never supply production credentials to tests.

Application source, tests and documentation are MIT. The included project icon has
separate distribution/reuse terms in `assets/BRANDING-RIGHTS.txt`; it is not MIT.
This is an independent community project, with no affiliation claim for any client
or email provider. Publication and live acceptance require separate owner review.
