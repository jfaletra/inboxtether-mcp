# InboxTether 2.1 wizard — corrected candidate validation

Reviewed implementation: `2.1.0.dev1`, packaged as experimental `2.1.0rc1`.
This is the historical implementation-acceptance record. Later owner hands-on
Claude acceptance and the final completion/download correction are distinguished in
[RC1_VALIDATION.md](RC1_VALIDATION.md) and
[final UX validation](FINAL_WIZARD_UX_VALIDATION.md). Earlier unverified statements
below describe the scope of this historical run.
Base: public v2.0.0 commit `8f4b4d869f51ac74186e45ab9c3a568dc6c53518`.
Date: 2026-10-30. No production change or GitHub publication was performed.
The original `VALIDATION.md` and `VALIDATION.json` remain the 2.0 record.
Code was frozen before final documentation; all 90 Python/test/browser-code files
are checked against the passing snapshot. Final documentation and the 137-file
source manifest are verified separately after results are finalized.

## Correction scope

- The existing error region is focusable and announced as an alert. Showing a
  validation error focuses it and scrolls it into view, with a visible focus ring.
- Claude instructions explain full quoted paths from any working directory,
  conditional Downloads examples for macOS/Linux and Windows PowerShell, and the
  alternative of changing to the containing directory first.
- Two focused contract tests were added. Authentication, classification, filing,
  approvals, existing Reader/Draft behavior and dependencies were not changed by
  this correction. All other 85 code files match the prior tested wizard snapshot.
- There are still exactly three setup screens. Success appears on screen three.

## Complete synthetic regression

- Ubuntu 24.04 ARM64, Python 3.12.3: **546/546 passed**, no failures, errors or skips
  (161.300 seconds). This VM runs ARM instructions through hardware virtualization
  on an ARM64 Mac; it is not a bare-metal Ubuntu installation.
- Ubuntu 24.04 x86_64, Python 3.12.3: **546/546 passed, no failures, errors or skips across the three final groups**. The canonical discovery,
  duplicate-ID removal, private temporary directories and IP-socket audit guard
  were retained. Three disjoint process groups cover the same complete 546-test
  inventory. Coverage and individual full logs are retained.
- **The x86_64 results use QEMU TCG software emulation on ARM64, not native x86_64
  hardware.** Native x86_64 hardware remains untested.
- All 506 existing application/security/Organizer tests and 40 installer tests
  are included. The separate focused wizard run passed 40/40 (a subset, not 40
  additional unique regression tests).
- Separate real-loopback HTTP checks passed **6/6 on each architecture**, covering
  bootstrap replay, session/CSRF, Host/Origin, size limits, reload, security headers,
  secret-free responses and installer shutdown. These are separate from the
  canonical suite, whose process rejects IP socket operations.

## Investigated verification failure

The first x86_64 group-zero wrapper forced `umask 077` for its entire child process
while protecting output logs. This changed a fixture's requested `0750` directory
into `0700`, correctly triggering the broker ownership/mode guard. It also made an
initial fixture file `0600` where its assertion expected the standard `0644`; the
policy writer correctly preserved the file's original mode.

The two failures reproduce under `077` and both pass under the canonical `022`.
Only the external wrapper was corrected: it explicitly uses fixture-process
`umask 022`, matching the passing ARM64 reference, and creates output descriptors
with private `0600` permissions. The fresh x86_64 SSH default was `0002`; a
preflight stopped before tests began when this differed from the reference. Application
code, required modes and authorization guards were preserved. The entire affected
182-test group was rerun: **182/182 passed, exit 0 (1000.281 seconds)**. Original stdout, stderr and exit
status remain retained; public copies normalize disposable checkout paths.

The official cloud image also reported only a deprecated NoCloud seed-name warning
from the test launcher, with no cloud-init errors. This was a test-environment
readiness warning, not an installer failure.

The public fixture suite expects conventional `umask 022`; run it in a private
checkout using `(umask 022; python3 -B run_tests.py)`. This affects only the test
subshell. It is not an installation permission change or authorization workaround.

## Actual Chrome UI checks

- Two failed mailbox sign-ins displayed the existing sanitized error, focused it
  and brought it fully inside the viewport. A valid sign-in then succeeded.
- The account and separate login remained intact visually. The browser observation
  API redacts those credential-field values, so they were not recovered through
  another interface. Host/port preservation and password clearing were checked
  programmatically. Password inputs were empty in captured screenshots.
- An invalid Linux-login name produced the same visible/focused error behavior on
  screen two. Its nonsecret entry and feature choices remained intact; correcting
  the entry recovered to screen three.
- Error geometry was verified in actual 802- and 746-pixel-high browser viewports.
  Keyboard Tab left the error region for the first form field; focus was not trapped.
  No manual screen-reader acceptance or complete WCAG audit is claimed.
- The actual third screen displayed both revised platform commands and the
  full-path/containing-directory guidance. Screenshots include all three screens,
  both validation failures, and actual installation success.
- An extension-overlay interruption was cleared by the owner. No extension or
  browser security settings were changed.

## Three fresh x86_64 installations

Each path used a separate pristine overlay of the retained checksum-verified
Ubuntu 24.04 official amd64 image. Before setup, application files, nginx,
python3-venv and Dovecot were absent. A separate disposable synthetic mail provider,
SSH access, test DNS and test certificate trust were supplied as documented
prerequisites. Those private test credentials and TLS keys are excluded from the
public candidate.

| Setup | Actual verification | Result |
| --- | --- | --- |
| Reader only | Real Chrome wizard, published launcher, installed MCP SDK handshake, five tools, synthetic non-marking read | Passed |
| Reader + Drafts | Published launcher and actual wizard HTTP flow, seven tools, synthetic read and draft preview | Passed |
| Full Organizer | Same flow, eight tools, role separation, trusted HTTPS login/logout, restart invalidates session | Passed |

No installation required manual JSON editing. Installed constrained dependencies
passed `pip check`; installed source/checksum hygiene passed for all 137 public
files. Flags were preserved. No draft was saved, classification performed or move
executed by these acceptance checks. Filing, automatic policy and delegated chat
consent started disabled in the full installation. Temporary setup listeners closed.

The Reader GUI case used the image's existing administrator login; it does not
prove that login lacks other sudo powers. The other two cases used a separate
nonadministrator client and verified arbitrary Reader-shell access was denied.
Earlier ARM64 clean-install acceptance passed all three paths before this UX-only
correction; those installations were not repeated during this pass.

## Download and command verification

The actual `app.js` export handlers were executed in an isolated synthetic DOM.
Four artifacts (local/SSH JSON and local/SSH rendered Python helpers) were captured
from their Blob contents. Each JSON had exactly the intended fixed launcher or
SSH argument vector, without environment or password fields. Each helper compiled,
had its placeholder replaced, and decoded to the exact corresponding JSON.
Synthetic password sentinels present in the form did not appear in any export.
Temporary-file connector tests preserved other entries, refused conflicts, verified
backup behavior and idempotence, and never edited the owner's desktop settings.

The exact generated Linux full-path command located and executed the helper from
an unrelated working directory. Noninteractive registration was deliberately
refused, confirming that existing client configuration remained unchanged.
Windows PowerShell execution and actual macOS/Windows graphical-client registration
were not tested. The Windows example requires the Python `py` launcher; every
example must use the actual saved filename and location.

**Owner-operated Chrome save completion subsequently passed.** The owner manually
saved both actual generated files. Their exact filenames, full bytes and SHA-256
matched independently generated expected artifacts; neither contained real credentials
or production configuration. No helper was executed and no client settings changed.
See [manual download acceptance](MANUAL_DOWNLOAD_ACCEPTANCE.md). The earlier automated
download-event capture timeout remains an automation limitation; no Chrome downloads
page or security workaround was used.

## User-facing prerequisites and limitations

- Initial Ubuntu 24.04/systemd installations only; existing installations are
  refused. Recovery is the documented owner-operated `--recover` action for an
  incomplete initial installation, not an upgrade or management dashboard.
- Existing supported IMAP access, folder permissions and a separate restricted
  Organizer login are owner/provider prerequisites. The wizard does not provision
  mail accounts, ACLs, DNS, firewall rules, HTTPS certificates or certificate renewal.
- An existing non-root Linux login is required. Name syntax is checked on screen
  two; account existence and non-root suitability are enforced by installation
  preflight before system changes. Existing administrator powers are not removed.
- Full Organizer requires pre-existing trusted HTTPS certificate/key files and an
  unused approval hostname. Existing custom nginx identities/routes may require
  operator preparation. This is not a production Mailcow deployment acceptance.
- Supported folder wire paths are bounded; unsupported/non-ASCII mappings are
  refused rather than guessed. OAuth-only mailbox providers are not enrolled here.
- Desktop Python, SSH host-key trust/key access and client registration remain
  owner steps. Hosted ChatGPT needs an existing supported external connection;
  local stdio JSON alone does not connect it. No graphical-client acceptance is
  claimed for Claude, ChatGPT or other desktop clients.
- Existing customer/uncertainty protections and historical Keep behavior remain
  the 2.0 implementation. This wizard does not reclassify or automatically reopen
  saved decisions. Sending email remains excluded.

## Recommendation

The reviewed wizard implementation and manual downloads passed acceptance. It is
eligible for experimental rc1 review with the listed limitations. Current packaging,
regression, HTTP and dependency checks are recorded in [RC1_VALIDATION.md](RC1_VALIDATION.md).
Publication, tagging and merge require separate owner authorization.
