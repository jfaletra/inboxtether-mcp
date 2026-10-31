> For a new Ubuntu 24.04 installation with this experimental 2.1.0rc1 candidate, see the optional [three-screen Setup Wizard](SETUP_WIZARD.md). The manual procedures below remain available.

# Installation and configuration

Install into a NEW source/state directory. This candidate deliberately refuses legacy
private journals; it is not an in-place upgrade for an existing deployment. No database,
historical inventory, receipt import, external AI service or old configuration is needed.
Do not point this candidate at another installation's state or credential files.

## Reader and Draft Assistant

Use README's source/stdio setup. Reader defaults expose five tools. Password files
must be regular, non-symlink, service-owned 0600 files; parent paths must be private.

Draft opt-in requires an existing, explicitly configured Drafts folder and a private
0700 state directory owned by the Reader/Draft identity. Configure:

```
INBOXTETHER_DRAFT_ASSISTANT=1
INBOXTETHER_DRAFT_MODE=basic
INBOXTETHER_BASIC_ACK=I_ACCEPT_CLIENT_CONTROLLED_APPROVAL
INBOXTETHER_DRAFTS_FOLDER=Drafts
INBOXTETHER_DRAFT_STATE_DIR=/var/lib/inboxtether-drafts
```

### Drafts special-use prerequisite

An existing folder named `Drafts` is insufficient by itself. The configured wire
mailbox must be selectable and its authenticated IMAP `LIST` response must advertise
the `\Drafts` special-use flag. Preparation checks that flag and pins the mailbox's
UIDVALIDITY; saves recheck the identity. InboxTether does not create the folder or
assign its server-side special-use role.

For a new disposable Dovecot 2.3 test server with an existing Drafts folder, configure
its mailbox role in the applicable namespace, then reload the test server:

```conf
namespace inbox {
  mailbox Drafts {
    special_use = \Drafts
  }
}
```

Verify the authenticated `LIST "" "Drafts"` response contains `\Drafts` before
preparing a reply. Substitute the exact configured wire path if it differs. If the
folder exists but lacks this role, 2.0.0 can return a generic mailbox-request error
from `prepare_reply_draft`; inspect the special-use flag as well as access rights.
No approval or Drafts save is needed to perform that read-only preflight.

Basic delegates approval to the client and requires the complete returned confirmation
object unchanged for `save_draft`. If independent owner authorization is required,
select `INBOXTETHER_DRAFT_MODE=secure`, remove the Basic acknowledgment and use the
existing trusted terminal approval (`python draft_assistant.py --help`) or optional
OIDC draft browser components (`examples/browser-approval/`). Secure mode exposes
`save_approved_draft`; it cannot fall back to Basic on login or approval failure.
Those OIDC examples are optional Draft review only; organization uses the dedicated
owner-password session below. Both modes prepare frozen reply MIME, never transmit it.
`INBOXTETHER_DRAFT_HTML_ALTERNATIVE=1` optionally produces escaped fixed-markup HTML;
leave it off unless the intended mail client has been checked.

## Organization: administrator setup

Install `requirements-organization.txt` with `constraints-validated.txt`. Keep three
separate OS identities: Reader/Draft, `inboxtether-organizer` (broker/executor) and
`inboxtether-web` (browser review). The web identity cannot read the organization
journal or its IMAP credential. Reader cannot impersonate the owner browser peer.
Use a dedicated IMAP organization login with explicitly reviewed mapping to the
logical account; Reader and organization password files are separate.

### Exact namespace paths and authentication separators

Mailbox hierarchy and login-name separators are separate requirements:

- **Folder namespace:** Configure the six exact, existing IMAP wire paths and their
  UIDVALIDITY values in `mailboxes`. The published Organizer accepts 1–512 ASCII
  characters per path from `A-Z a-z 0-9 _ @ . + / -`. Slash-separated components
  cannot be empty, `.` or `..`; the six paths must remain distinct ignoring case.
  Literal slash and dot hierarchies can be represented, for example `INBOX/Industry`
  or `INBOX.Industry`, only when those exact paths already exist on the server.
  These examples do not establish that a particular namespace is configured.
  InboxTether does not discover, translate or normalize namespace prefixes or
  hierarchy delimiters. `*` is unsupported in a configured path and is never a
  wildcard for discovering or choosing a destination.
- **Dedicated Organizer login:** `account` is the logical mailbox identity;
  `login_account` is a different, explicitly reviewed principal mapped to it.
  Both values accept 1–320 characters from `A-Z a-z 0-9 _ . + @ -`. In particular,
  `*` is rejected before the broker starts. A Dovecot master-login name such as
  `owner@example.com*organizer` is therefore unsupported by 2.0.0 (unchanged from rc3).
  This restriction concerns the login string, not the mailbox hierarchy delimiter.

The disposable Dovecot acceptance fixture used `auth_master_user_separator = +`.
An illustrative corresponding login is `login_account = "owner@example.com+organizer"`.
`+` is an accepted login-name character; InboxTether does not configure Dovecot or assume
that `+` has authentication semantics on another server. Use a genuinely supported
and scoped dedicated login/mapping. Do not broaden the validators, guess aliases,
or change an existing production server's namespace/authentication settings to try
this example. Identity or folder-pin changes need the documented operator assessment.

References: [Dovecot namespaces](https://doc.dovecot.org/2.3/configuration_manual/namespace/)
and [Dovecot master users](https://doc.dovecot.org/2.3/configuration_manual/authentication/master_users/).

Copy and customize the examples into administrator-controlled configuration paths:

- `organization.json.example`: exact host/logical account/dedicated login, private
  password-file path and 0700 executor-owned journal directory; actual numeric Reader
  and web UIDs; enrolled local owner ID; HTTPS review origin; exact folder wire names
  and their UIDVALIDITY; explicit protections and relationship entries.
- `owner-login.json.example`: same owner ID/origin, web-owned credential and CSRF-key
  paths, fixed broker/web socket paths, `/inboxtether` route prefix.
- `socket-access.json.example`: actual Reader, web and reverse-proxy UIDs. Example numbers
  are placeholders; derive them from the service accounts on the destination machine.
  `web_uid` must match the named `inboxtether-web` account and organization config.

The JSON configuration loader requires root-owned 0644 regular files, root-controlled
non-writable ancestry, no symlinks and bounded size. These files contain references
and policy, never raw passwords. Actual secrets are separately protected 0600 files.
Examples intentionally contain invalid owner/UIDVALIDITY placeholders and fail until
configured. Supply reviewed folder metadata through your normal administrator workflow;
setup never guesses account, folder aliases, UIDs or credentials.

Create the journal directory empty, mode 0700 and owned by the executor. Do not create
an operation file or seed classifications. First authorized `next` validates folder
identities/rights and discovers that installation's Inbox UIDs; it initializes a fresh
journal and persists the discovery frontier. Restart resumes that journal. There is
no dependency on a historical ledger or an existing mailbox inventory. An identity,
policy or folder-pin change stops for operator assessment; never delete state to fix it.

Keep `execution_enabled:false`, `client_session_consent:false` and the optional
`automatic_filing_policy.enabled:false` initially. Omission of the automatic-policy
field also means disabled. Configure standing automatic authority only through the
separate [owner activation procedure](AUTOMATIC_FILING.md). Set the
latter true only after intentionally accepting the documented delegated-client trust
model. It is needed for conversational preference approvals. Execution is a separate
operator switch and is rechecked at the move boundary. Turning a gate off does not
remove approvals, rules, receipts or claims. Changing gates does not change a manifest;
any expired review or changed preference revision requires fresh review/approval.

Enroll a dedicated owner password using `enroll_owner.py --help` in an administrator
terminal. It uses hidden password entry and Argon2id, and refuses silent replacement.
Use a freshly generated 32-hex owner ID consistently in both configs. Create a random
32-byte CSRF key privately for the web service. Do not reuse mailbox credentials as
owner credentials. Initial administrative setup is separate from routine client use.

Service templates use `/opt/inboxtether`, `/etc/inboxtether-approval` and new generic
state paths. Review them for the destination machine; they are NOT deployment scripts.
Configure `broker.env`, `web.env`, the protected socket ACL config and the existing
reverse proxy. `socket_access.py` uses the named service users and grants only the
specified Reader/web/proxy peers access to their respective sockets. It needs the Linux
`setfacl` executable; no fixed UID or production directory is assumed.
Start the broker before the web service and connect the Reader via stdio. Use the
existing TLS reverse proxy to forward `/inboxtether/` to the web Unix socket, without
stripping the prefix or bypassing authentication (`nginx-owner.conf.example`).
These components reuse the implemented approval broker/web architecture; no new
transport service is introduced by this source candidate.

Enable organization on the client-facing server with:

```
INBOXTETHER_MOVES=1
INBOXTETHER_MOVE_SOCKET=/run/inboxtether-approval-broker/moves.sock
```

No tool argument can enable execution or change the fixed account. Review tool
metadata in the intended client before any mailbox operation. Do not attach tests to
this configuration. Proceed to separate bounded live acceptance only when authorized.

## Mailbox requirements

The server must support authenticated IMAP UID MOVE and UIDPLUS mapping, TLS and
MYRIGHTS checks. Ordinary Inbox filing needs source lookup/read/delete/expunge rights
and destination lookup/read/insert/flag rights. Correcting filed mail also needs
source delete/expunge rights on the exact filing folder; restoration needs insert/flag
rights on Inbox. The adapter rejects broader or unexpected rights and identity changes.
Do not grant mailbox creation, general COPY/STORE/EXPUNGE, or administrative rights.
No ACL, account or folder is created by the application. See `organizer/imap_adapter.py`
for the exact conservative rights combinations; test them on the intended IMAP server.

## Example new-host provisioning sequence (review before use)

These commands describe a NEW Linux installation only. Do not run them against an
existing deployment or from the test suite. Run administrative commands as root:

```sh
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin inboxtether-reader
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin inboxtether-organizer
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin inboxtether-web
install -d -o root -g root -m 0755 /opt/inboxtether /etc/inboxtether-approval
install -d -o inboxtether-reader -g inboxtether-reader -m 0700 /etc/inboxtether-reader /var/lib/inboxtether-drafts
install -d -o inboxtether-organizer -g inboxtether-organizer -m 0700 /etc/inboxtether-organization /var/lib/inboxtether-organization
```

Copy the verified source (not a validation environment) into `/opt/inboxtether`;
create its venv and install the constrained organization requirements. Provision
separate Reader and organization IMAP password files through a secure administrator
workflow and verify ownership/mode. Do not overwrite an existing user's credential.
Copy/edit the JSON examples; fill account mapping, owner ID, folder pins and real
UIDs. Set root ownership/mode 0644 for configuration. Confirm the configured reverse
proxy's OS UID in socket-access.json; sample UID numbers must not be left unchanged.
The socket helper requires the distro's `acl` package and `/usr/bin/setfacl`.

Generate owner ID and CSRF bytes privately on that host, without pasting secrets into
chat. For example, the following generates files rather than displaying either value:

```sh
/opt/inboxtether/.venv/bin/python - <<'PY'
import os,pwd,secrets
uid=pwd.getpwnam('inboxtether-web').pw_uid
for path,data in [('/etc/inboxtether-approval/owner-id',secrets.token_hex(16).encode()),
                  ('/etc/inboxtether-approval/csrf.key',secrets.token_bytes(32))]:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fchown(stream.fileno(),uid,-1);os.fsync(stream.fileno())
PY
```

Use the generated owner ID in both JSON configs, then run the existing enrollment
command below. Only the non-secret owner ID is passed on the command line; password
entry is hidden. Review usernames and paths before executing:

```sh
/opt/inboxtether/.venv/bin/python /opt/inboxtether/enroll_owner.py \
  --file /etc/inboxtether-approval/owner.json \
  --owner-id "$(cat /etc/inboxtether-approval/owner-id)" \
  --username owner --web-uid "$(id -u inboxtether-web)"
```

Install the reviewed broker/web unit examples and environment files only after
configuration verification. Attach the HTTPS route to an existing TLS proxy and
start broker, web, then the client-owned stdio server. Keep both write/consent gates
off until the applicable owner approvals and bounded acceptance plan are in place.
