# InboxTether 2.1 — final manual download acceptance

**PASS. GO for an experimental 2.1 release candidate, with the existing documented
limitations. Publication remains separately authorized.**

The owner manually clicked the actual wizard's Download JSON and Download one-time
Claude connector controls in Chrome and saved both files. Verification read only
the two owner-identified saved paths; no directory crawling, Chrome downloads-page
access, browser-security changes or undocumented workarounds were used.

| Saved filename | Bytes | Expected and actual SHA-256 | Result |
| --- | ---: | --- | --- |
| `inboxtether-client.json` | 231 | `5ca9d1eca5da2b8ae9b3dff361a55ec1f2ed6ed610fd69e6232ddb72827b1b2a` | PASS |
| `connect_inboxtether_claude.py` | 5153 | `8d54d4723a87c5639b446a09c120592bc9f556ebb956b3c869afa8d78bbfb9ae` | PASS |

Both saved files exist as regular files with the exact expected names. Their entire
contents match independently generated expected Blob artifacts byte for byte.
The JSON contains only the fixed SSH command/arguments and the synthetic destination
`desktop-owner@example-server`, with no environment/password fields. The Python
helper compiles, its embedded JSON decodes to that same exact configuration, and
its template placeholder is replaced. No real credentials, production configuration
or private mailbox data are embedded. The helper was never executed, and no desktop
client configuration was modified. No security warning was reported by the owner.

The actual wizard explains how to locate Downloads, use a quoted full path from
any working directory, substitute the actual saved location, or change to the
containing directory first. It displays macOS/Linux Terminal and Windows PowerShell
examples. This check verifies the displayed instructions, not Windows execution.

The actual completed page says **InboxTether is installed** and separately shows
**Finish in your client**, followed by **Connect your chosen AI client using the
generated configuration**. Its MCP handshake check is the installed server's health
probe, not a claim that Claude or another graphical client was registered. Setup
completion and the remaining client connection are accurately distinguished.

This closes the previously unverified owner-operated Chrome download/save check.
It supplements the frozen candidate validation rather than changing the reviewed
source or archive. All 90 tested code files remain unchanged. The original review
package SHA-256 remains:

`323706a15528e2cf15653600276c5908e2c8bbc5ea20e92394696cbdc9d9535b`

The prior 546-test ARM64 and emulated x86_64 regression results and three clean
installation paths remain applicable. Native x86 hardware, graphical-client
connection acceptance and Windows command execution remain explicitly unverified.
No additional application development is indicated by this manual test.

Production InboxTether, Mailcow, Radar, plugins, GitHub and historical records were
not accessed or changed. No production email was accessed or moved. All mailbox
validation was against the retained disposable synthetic fixture. No code change,
merge, tag, deployment to production or publication was performed.
