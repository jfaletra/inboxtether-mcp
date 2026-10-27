# InboxTether 2.0.0rc2 validation

304 unique synthetic cases passed on disposable Ubuntu 24.04 arm64 / Python 3.12.3:
294 existing cases plus 10 focused regressions, zero failures/errors/skips. The source
and dependency installation followed the published documentation. The runner creates
a short 0700 temporary directory under a controlled home (or private writable checkout),
removes it on exit, and needs no externally configured TMPDIR. Enrollment safety checks
were preserved. IP socket operations are rejected in the test runner; local Unix sockets
and socketpairs are allowed. Imported unittest IDs are deduplicated.

## Four bounded corrections

- Grant only the configured Reader and actual named web identity access to the existing
  broker socket; retain proxy-only access to the web socket. Directory traversal and
  socket read/write ACLs do not grant directory write or journal/credential access.
- Serialize web socket ownership with a 0600 lock in the existing runtime directory.
  Refuse live/unsafe endpoints, recover verified disconnected owned sockets, and remove
  only the listener's own inode on close. The existing ACL helper waits for the current
  endpoint to listen, avoiding grants to an old socket during crash recovery.
- Use private short-path Linux fixture directories instead of shared default /tmp.
- Replace ast.dump-format pins with portable canonical JSON AST verification. Eight
  function bodies (the seven Basic Reader/Draft interfaces plus the Secure Draft save
  alternative) match the public v1.2.1 baseline. Meaningful parameter/body/type-parameter
  changes still fail the pin. Python 3.11 and 3.12 both pass the portable contract check.
  server.py and draft_assistant.py remain byte-identical to rc1.

## Actual disposable Linux checks

Published service identities/units, private filesystem permissions, owner enrollment,
HTTPS proxy and login/session, exact browser-manifest approval/CSRF, Python MCP SDK
stdio and Unix IPC all passed. Optional client consent approved one exact synthetic
batch, rejected a changed fingerprint and refused replay. Narrow sender/context
preferences were created, inspected, edited and revoked through the actual broker.
Reader journal access, web IMAP credential access and web IPv4 socket creation were
denied. No production resource or real mailbox was accessed.

Three normal web restarts and forced SIGKILL recovery restored healthy authenticated
browser/broker access without manual socket deletion. A protected source/configuration
backup, deliberate source-manifest failure, source restore and full service restart
passed. Journal checksums stayed unchanged; two distinct synthetic approvals and
preference revision 3 survived. No journal was restored or rewound, no daemon mailbox
move attempt occurred, and execution stayed disabled. Client consent was disabled again
after testing. This is source-only restore evidence, not legacy downgrade/migration.

Reader/search/attachments and Drafts preparation/save use fabricated IMAP fixtures.
Organization, flags, source-integrity/Keep protections, durable claims, rule revision
binding, one-message overrides and receipt-linked corrections pass synthetic tests,
including real SDK/Unix transports and simulated HTTP where applicable. No vendor
client UI or live IMAP/provider acceptance is claimed. Organization/corrections remain
experimental until separately authorized live acceptance; client-relayed consent does
not independently authenticate a human approver.

## Dependencies and package

pip check passed. All 56 constrained runtime/test/audit package versions match the
installed environment and license inventory; their current advisory audit reported
zero known vulnerabilities. Dependencies are not vendored. MIT, branding rights and
third-party/license inventory notices are unchanged. Installer bootstrap tools are
outside the application constraint inventory. Advisory checks cannot exclude undisclosed
vulnerabilities, and pattern scans cannot establish the absence of every possible secret.

Source/package checks reject credential/address/private-path patterns, unsafe paths,
operational artifacts, sending imports/tools and manifest drift. All 97 archive files
are listed by the member manifest; ZIP/tar member bytes are compared to their source.
No installation-specific inventory, rules, state, credentials or deployment configuration is
included. The retained public repository author attribution is provenance. Source
contains no executable email-sending capability; local Unix RPC send framing and MIME
serialization are not email transmission.

## Reproduce from the extracted archive

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-validated.txt -r requirements-test.txt -r requirements-audit.txt
.venv/bin/python -m pip check
.venv/bin/python run_tests.py
.venv/bin/python scripts/verify_release.py
.venv/bin/python -m pip_audit -r constraints-validated.txt --no-deps --disable-pip --strict --progress-spinner off
```

Service tests require a disposable Linux host, synthetic configuration and identities,
the documented existing proxy and unit examples, and fabricated message adapters.
Do not run validation against operational configuration. No GitHub action was triggered,
and nothing was published, deployed to production or changed in any connected plugin.
