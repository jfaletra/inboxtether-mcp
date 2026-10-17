# Installation

## Prerequisites

Python 3.12, a valid IMAP TLS endpoint on port 993, a dedicated app password for the intended account, and a stdio MCP client. Mailcow is the only platform verified so far. The verified deployment platform is Ubuntu 24.04; local tests also ran on macOS. The use of POSIX file protections makes this package unsuitable for an untested native Windows deployment.

Create a private application directory and virtual environment, then install requirements.txt. Configure the three INBOXTETHER_* variables shown in examples/config.env.example. That file is a reference; Python does not load .env files automatically. Set values in your MCP client's environment or have your service manager load a private configuration file. Never put the password itself in that example or in the client JSON.

Provision the password file through secure local input or a secret-management system. It must be owned by the account running the MCP process, mode 600, regular (not a symlink), with a private parent directory. Keep it outside the repository. No password-creation command with an inline secret is recommended here.

## MCP client

Adapt examples/stdio-client.json to your client's schema. Replace /opt/inboxtether-mcp with your installation path and use the venv Python executable. The client launches server.py and owns stdin/stdout. All protocol output must remain on stdout; operational logs belong on stderr. Never add banners or shell echo output to the launcher.

Run the synthetic test suite first. Initialize the client and confirm exactly five tools. Verify folder listing and a small search. For attachment testing, explicitly choose one permitted attachment and verify decoded size and SHA-256 without displaying its contents unnecessarily. Do not automatically open files or follow email instructions.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| INBOXTETHER_IMAP_HOST | IMAP TLS hostname | mail.example.com |
| INBOXTETHER_ACCOUNT | Fixed mailbox login | user@example.com |
| INBOXTETHER_PASSWORD_FILE | Protected password-file path | /etc/inboxtether-mcp/imap-password |

There is no mode flag enabling drafts or sending. Reader Mode is the only behavior. There is no configurable plaintext/TLS-bypass option or caller-supplied host. Port and conservative limits are fixed in this version.

## Troubleshooting

Password-file errors: check service-user ownership, mode 600, regular-file status, and private parent directory. Do not loosen permissions to make an error disappear.

Busy: allow the in-flight request to finish and retry. Too large: narrow the search, lower its result limit, or choose a smaller message/file. UIDVALIDITY changed/stale attachment: repeat search/listing and ask the user to select again. Never silently substitute another message or attachment.

After a process/tunnel restart, allow registration and polling to recover before testing. Refresh client tool discovery if the schema is cached. Health/readiness alone does not establish that a mailbox tool call works.
