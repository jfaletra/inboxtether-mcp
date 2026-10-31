# Initial installation wizard — 2.1.0rc1 experimental candidate

This temporary, three-screen installer provisions a **new Ubuntu 24.04 server**.
It is not an upgrade, migration, hosted control panel, account provider, or new MCP
transport. Existing installations are refused. Reader is the default; Drafts and
Organizer are optional. No email is sent by InboxTether.

## Before starting

- Use a new Ubuntu 24.04 host with systemd, administrator access, working DNS,
  an accurate clock, and outbound HTTPS access for Ubuntu/Python dependencies.
- Download the reviewed source archive and independently verify its published
  SHA-256 before unpacking it. The installer also checks `MANIFEST.sha256`.
- Have a working IMAP password/application password. The provider must support
  implicit TLS with a trusted certificate. Port 993 is the default; another TLS
  port and an IMAP login distinct from the email address are supported.
- Have an existing non-root Linux login for the client connection. Remote desktop
  clients also need independently established SSH host-key trust and key access.
- The wizard never creates mail accounts, changes provider ACLs, creates mailbox
  folders, reads messages, changes flags, or classifies mail during setup.

Reader needs only read access to the mailbox. Drafts additionally needs an
existing selectable special-use `\Drafts` folder, UIDPLUS and permission to append.
The initial wizard offers **Basic Draft Mode**: approval before each save is the
AI client's responsibility, explicitly acknowledged on screen. Preparing a draft
saves nothing. Use the existing manual installation procedure for Secure Draft
Mode; this wizard does not silently claim equivalent independent approval.

Organizer additionally requires an **already restricted, distinct IMAP login**
accessing the same mailbox, ACL/MOVE/UIDPLUS support, and six existing selectable
folders: the source Inbox and Industry, Marketing, Orders, Review, Suppliers.
Select the exact discovered wire paths. Existing 2.0 Organizer path restrictions
remain: ASCII paths without spaces, wildcards or unsupported master-login syntax.
The existing adapter's least-privilege rights checks are reused. Excess privileges,
unmatched source identity and changed UIDVALIDITY stop setup. Provider account,
folder and ACL administration remains outside this installer.

For browser approval, arrange a dedicated HTTPS hostname, DNS, firewall access and
an existing trusted, matching certificate/key under administrator-controlled
`/etc` paths. The private key must not be world-readable; encrypted interactive
keys are unsupported. The certificate must have over one day remaining. The wizard
validates trust, hostname and key compatibility; it does **not** obtain or renew
certificates, change DNS or open a firewall. It installs/reuses Ubuntu nginx and
adds only its named approval vhost, preserving other sites. An already occupied
approval hostname or custom nginx worker identity is refused. nginx's normal
package installation behavior still applies on a new server.

## Launch the temporary wizard

From the independently verified, unpacked source directory on Ubuntu:

```sh
sudo ./install.sh
```

Open the private `http://127.0.0.1:8765/#…` link printed in that Terminal. Do not
share the link or any passwords in chat. For a remote server, first forward the
**same loopback port** from your desktop in a separate Terminal:

```sh
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 your-login@your-server
```

Then open the server's printed link locally. Choose another `--port` and matching
forward if 8765 is occupied. The listener never binds to a public address. The
one-use bootstrap is removed from browser history after entry. Requests require
the owner session, same origin and CSRF token. Idle sessions expire after fifteen
minutes; absolute lifetime is one hour, without killing an installation underway.
Passwords are held only for the current session, not in URLs, downloads or logs.
Python memory erasure is best effort, not a guarantee that no copies ever exist.

1. **Connect email.** Enter hostname, TLS port, email address, optional distinct
   login and hidden password. Test TLS/authentication and mailbox metadata.
   This uses LIST/EXAMINE/MYRIGHTS, never message reads or flag writes.
2. **Choose features.** Leave Reader selected; optionally enable Drafts and/or
   Organizer. Map discovered folders. Supply the existing restricted Organizer
   password and a **different**, dedicated browser-owner password of at least
   sixteen characters. Advanced settings hold the Linux login and existing TLS
   paths. Validate to obtain the exact nonsecret installation plan/fingerprint.
3. **Install, then connect your AI.** Choose a client and local/SSH location, review the plan,
   explicitly confirm it, and install. Source verification, constrained dependency
   installation, role permissions, real MCP initialization/tool declarations and
   applicable HTTPS/service checks run before success is reported. The sequence is
   **Configure → Install → Verify → Download Connector → Connect AI**. The review
   panel explicitly says that InboxTether is not installed yet. Downloads and copy
   controls remain hidden/disabled through installation and failures. Only after
   verified success does **Next Step: Download Your AI Connector** appear. The
   exported settings are the server-validated snapshot attached to that completed
   installation, not later edits in the form. Keep the page open until saved.

No JSON editing is needed for this supported flow. Credentials are written to
separate service-owned 0600 files inside private directories. The owner password
uses the existing salted Argon2id enrollment implementation. The selected Linux
login receives permission only for the fixed Reader launch command, not a shell
or arbitrary Python invocation as the Reader identity. Reader-only creates no
InboxTether background service. Organizer reuses the two existing approval
broker/web service templates, Unix sockets and peer-authenticated role separation.
It creates no additional MCP server, database, tunnel or authentication provider.

**Mailbox execution, automatic filing and chat-consent activation stay disabled.**
Installation does not inventory mail or start classification. Enabling filing is
a separate, explicit owner operation under the existing 2.0 approval/policy model.
A successful setup check is not proof of a live, owner-approved move.

## Client connection and genuinely manual steps

- **Claude Desktop:** first complete installation and wait for its Verified badge.
  Then download the one-time connector in the Next Step section. This is separate
  from connecting Claude; the wizard never reports that an external AI client is
  connected. Confirm a working desktop Python 3 with `python3 --version`
  (macOS/Linux) or `py -3 --version` (Windows). If your command points to a missing
  interpreter, use the full path to a working Python 3 executable or install Python
  3 before running the helper. First locate the actual saved file. If it is in Downloads, these
  commands work from **any current directory**:
  macOS/Linux Terminal: `python3 "$HOME/Downloads/connect_inboxtether_claude.py"`;
  Windows PowerShell: `py -3 "$HOME\Downloads\connect_inboxtether_claude.py"`.
  If the browser adds a number to the filename or it is saved elsewhere, replace the quoted path with its actual full path. You may
  instead change Terminal to the containing folder first and run
  `python3 ./connect_inboxtether_claude.py` (Windows: `py -3 .\connect_inboxtether_claude.py`).
  Review the command and type
  `ADD-INBOXTETHER`. It adds only InboxTether, backs up existing configuration,
  preserves other settings and refuses a different existing InboxTether entry.
  Restart Claude. This is an owner-run local file update, not a background agent;
  the Ubuntu installer never accesses your desktop files. Tests use temporary
  synthetic client files, never an actual user's client configuration.
- **Supported ChatGPT desktop/Codex hosts:** use Settings → MCP servers → Add
  server → STDIO; enter the displayed command and separate arguments, save and
  restart. Exact UI availability depends on the installed host/client version.
- **ChatGPT web:** cannot consume local stdio configuration. Use the existing
  documented, separately owner-configured supported plugin/Secure MCP Tunnel
  route. This wizard creates no tunnel or plugin and does not claim to connect
  hosted ChatGPT automatically.
- **Other clients:** the screen provides/downloads valid `mcpServers` JSON and the
  command/arguments. A client's import UI, approval behavior and compatibility
  remain client-specific. The export contains no mailbox credentials.

Remote client commands use `ssh -T -o BatchMode=yes … /usr/local/bin/inboxtether`.
Verify desktop-to-server host trust and key access before relying on that command.
The installer reports these manual requirements; it cannot silently authorize
SSH, configure a hosted client or validate an external AI conversation for you.

References: [Claude local MCP configuration](https://modelcontextprotocol.io/docs/develop/connect-local-servers),
[ChatGPT MCP hosts](https://learn.chatgpt.com/docs/extend/mcp),
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

## Completion, failure and recovery

**Installed successfully is not AI client connected successfully.** The success
screen verifies the server, then explains the separate desktop connection. After
running the helper, fully quit/reopen Claude and verify its InboxTether tools.
No desktop-success claim is inferred from downloading a file.

If the private setup link is refused, Test connection is disabled. Obtain the full
current link (including its # code) from the launch Terminal or the person who
prepared the server; open it once in one browser. If that browser already signed
in, the base address without the # code can resume its existing session. If access
is missing/expired, request a fresh link. Inspect any in-progress installation
receipt before restarting; never repeat Install blindly.

After a connection/feature validation attempt, password fields are cleared to
reduce their time in browser memory. Following a failed feature check, re-enter
the Organizer password and both owner passphrase fields. Nonsecret fields remain.
This does not relax secret erasure or reuse a failed credential.

Successful installation reports checks performed, tool names and remaining manual
requirements, erases session secrets, invalidates its session and closes the
loopback listener. The final browser screen and secret-free client download remain
available as a static page. The installer is not kept running for administration.

Diagnostics and an atomic, protected resource receipt are under
`/var/lib/inboxtether-setup` (administrator only). Subprocess exit status and output
are retained with known secrets redacted. Do not share unreviewed diagnostics.
There is no automatic retry. Interrupting the launcher waits for an active provisioning
thread to settle rather than abruptly killing package operations; inspect the receipt
before relaunching. A failed installation attempts to stop/remove only
its recorded resources and service identities. Installed Ubuntu dependencies and
protected diagnostics remain; no mailbox rollback is attempted or needed.

For an interrupted/failed **initial** installation, inspect the receipt first.
Then, from the same verified source:

```sh
sudo ./install.sh --recover
```

Type `REMOVE-INCOMPLETE-INSTALL` in Terminal when asked. Recovery validates receipt
ownership, recorded paths, resource identities and service accounts before
cleanup; replaced resources cause a safe stop. It archives diagnostics and allows
a separate fresh attempt. Completed installations are never removed by recovery.
A power loss between an OS operation and its receipt checkpoint can require owner
assessment of an unrecorded resource; the wizard refuses an existing account or
path rather than guessing ownership. This is not a general uninstall/upgrade tool.
Use a server snapshot for complete OS/package rollback.

## Scope and acceptance limits

The existing Reader/Draft contracts, customer/uncertainty checks, exact-manifest
approval, hashes/flags, receipts and replay/no-retry guards are retained. Historical
Keeps are not reconsidered by installation. No sending capability, Setup Wizard
migration, OAuth flow, provider provisioning, public management dashboard or
background classification is introduced. See `WIZARD_VALIDATION.md` for actual
isolated testing and remaining unverified client/platform combinations.


## Acceptance evidence and screenshots

See [final wizard UX validation](FINAL_WIZARD_UX_VALIDATION.md),
[rc1 validation](RC1_VALIDATION.md), [the earlier implementation checks](WIZARD_VALIDATION.md)
and [earlier manual Chrome download acceptance](MANUAL_DOWNLOAD_ACCEPTANCE.md).
Source and helper/configuration downloads were verified using synthetic settings.
Downloading does not register or validate a graphical AI client.

![Review the installation before any connector download](docs/screenshots/setup-final-review.jpg)
![InboxTether installed successfully; AI connection is separate](docs/screenshots/setup-final-installed.jpg)
![Download the connector only after installation verification](docs/screenshots/setup-final-connector.jpg)
![Failed validation clears passwords and explains re-entry](docs/screenshots/setup-final-password-retry.jpg)
