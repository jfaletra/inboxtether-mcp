# v1.1 installation, upgrade and rollback

This is a runbook, not authorization to change a running service. v1.1.0 is still
an unmerged release candidate. Do not use an unreviewed moving branch in production.

## Reader-only upgrade (default)

1. Record your current source revision, service/launcher and protected configuration.
   Back up secrets outside Git with restricted access. Do not copy credentials or
   application state into a source archive, PR, issue or logs.
2. After release authorization, obtain the exact approved release revision into a
   separate application directory. Create a Python 3.12 virtual environment there
   and install `requirements.txt`. Follow [installation](INSTALLATION.md) for the
   unprivileged account, valid IMAP TLS and mode-600 password file. Do not rotate
   or replace mailbox credentials merely to perform an upgrade.
3. Keep `INBOXTETHER_DRAFT_ASSISTANT=0`, `INBOXTETHER_BROWSER_APPROVAL=0` and Basic
   acknowledgment blank. Python does not load `.env` automatically; update your
   actual client/service environment. `INBOXTETHER_DRAFT_MODE=secure` selects a
   policy only and does not enable drafts. Browser packages/services are optional.
4. Run `python -m unittest discover -s tests -v` in an isolated development/test
   environment with `requirements-browser.txt` installed for the complete suite;
   the Reader runtime itself needs only `requirements.txt`. Run `python -m pip check`
   and the repository hygiene/dependency checks in the approved release checklist.
5. During a separately approved maintenance window, point the existing launcher
   at the new environment. Preserve the existing secure tunnel/profile and its
   protected runtime key; no new inbound MCP port, DNS or credential is required.
6. Refresh client discovery: exactly five Reader tools must appear. Verify a bounded
   folder/search/read using a designated test message; confirm source flags remain
   unchanged. Readiness alone is insufficient. Do not expose draft tools as part
   of a Reader upgrade.

## Optional Draft Assistant — separate authorization

Use a dedicated test mailbox first, an existing special-use Drafts folder and a
service-owned local state directory (0700; SQLite database 0600) outside the checkout.
Require UIDPLUS and TLS; APPEND must be allowed only for the intended mailbox.
An IMAP app password by itself does not prove read-only mailbox ACL enforcement.

Configure the master opt-in and choose exactly one policy using
[Draft modes](DRAFT-MODES.md) and [configuration examples](../examples/config.env.example).
Secure is the default policy: trusted terminal approval needs no web service. It
must run as the trusted operator with private state access, independently of the
MCP caller; use the configured environment with
`python draft_assistant.py approve DRAFT_ID`, review the complete escaped manifest,
and enter the exact requested approval line. This grants no save after the original
ten-minute expiry and does not itself save mail. Then invoke `save_approved_draft`
once. Never manufacture terminal approval through a model-controlled shell.

Basic requires the explicit acknowledgment and exposes `save_draft` with the full
unchanged confirmation object. It delegates authority to the client; it must not
be presented as independent human approval. There is never automatic fallback.

For browser Secure Mode, follow [browser deployment](BROWSER-APPROVAL.md): optional
browser dependencies, established OIDC, HTTPS, distinct service identities, private
IPC, owner binding, session/CSRF and recovery testing are separate deployment gates.
Do not expose the portal without authentication. Live browser/IdP acceptance is
not established by the terminal Mailcow test.

Refresh discovery after a separately approved opt-in: five Reader tools plus
preparation and one mode-specific save tool. Review all recipients, subject, body,
threading and destination. Approve one synthetic draft, save once, read back exact
bytes/checksum and verify the original. An expired proposal requires fresh review;
an uncertain save requires manual read-only reconciliation, never an automatic
retry, deletion or replacement. No SMTP or sending configuration exists.

## Retention and rollback

Keep staging/backups on encrypted local storage with restrictive ownership and a
short documented retention period; expiry is not erasure. Do not share state with
untrusted model tools. Do not reuse staged proposals after changing policy/account.

To roll back during an approved window, disable the master draft switch and browser
service, restore the previous pinned Reader environment/configuration and refresh
client discovery. Preserve uncertain-save receipts privately for reconciliation;
do not delete or edit existing mailbox drafts during rollback. Existing drafts
remain in the mailbox. Do not downgrade a live SQLite state database in place.
Restore source/environment rather than weakening TLS, permissions or approval.
