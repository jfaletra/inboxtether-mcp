# InboxTether v2.1.0rc1 — validation and release boundary

Experimental 2.1 development based on stable `v2.0.0`, commit
`8f4b4d869f51ac74186e45ab9c3a568dc6c53518`. The experimental `v2.1.0rc1`
prerelease was published from `c409a05ca30b26602b6babb5e99b3817682cd01f`;
its tag and assets remain unchanged. No stable 2.1 release exists.
This file separates original rc1 checks, the final UX correction and the later
discovery-completion documentation correction.
See [final wizard UX validation](FINAL_WIZARD_UX_VALIDATION.md) for the new 551-test
run, three fresh installations and actual Chrome completion/download checks.
Earlier GitHub Actions results apply to their exact PR commit, not this correction.

## November 1 discovery-completion follow-up

The follow-up to the published rc1 changes `WORKFLOWS.md`, `AUTOMATIC_FILING.md`
and the existing `organize_email` description. After the final pending message,
the assistant calls `next` again. Successful discovery completion requires one
response with no `uid` field, `remaining=0` and the explicit "No new messages"
notice. Additional messages are processed within the owner's scope, followed by
another discovery check. Errors, uncertain operations or scope limits leave the
completion status incomplete. Results say "caught up as of the final discovery
check"; there is no continuous monitoring. See [the procedure](WORKFLOWS.md#owner-requested-discovery-and-completion).

Three contract tests inspect both guides, the generic user prompt and the actual
exported MCP description. An AST comparison excluding docstrings and comparison
of the exported MCP metadata confirmed that executable code, schemas, annotations
and authorization metadata are unchanged. The discovery engine, customer guards,
manual/automatic authorization and all seven Reader/Draft declarations are preserved.

Local validation used a disposable Ubuntu 24.04 ARM64 snapshot, Python 3.12.3 and
the self-contained packaged verifier: **554/554 regression tests**, **6/6 loopback
HTTP security tests**, dependency consistency, source/archive integrity and an
audit of **56 dependency records with zero reported vulnerabilities** passed.
There were no test failures, errors or skips. The first snapshot stopped before
tests because the documented `python3.12-venv` prerequisite was absent. After
installing that prerequisite in a fresh snapshot, all steps passed; both attempts'
full stdout, stderr and exit codes were retained. Application code was not changed
to accommodate the environment.

This is synthetic regression and metadata validation, not a new clean-install,
graphical-client or live-mail acceptance test. Fresh GitHub Actions must pass on
the updated PR commit; earlier rc1 results do not validate that commit. No production,
client connection, plugin registration, published tag or release asset is changed.

## Exact reviewed implementation

The original published PR candidate at `6bc1a3b9f6b5145f42c1b1da6345cea8c8b6d219`
matched all 90 reviewed code files. The owner-authorized October 31 final UX
correction now changes only wizard completion/download sequencing, its temporary
connection snapshot, recovery wording, tests and related documentation. Runtime,
test and audit dependency pins, authentication/CSRF checks, password erasure,
Reader/Draft behavior and the 2.0 filing engine are unchanged. See the accompanying
final-UX validation evidence for new local results; earlier CI below is historical
until the corrected commit receives fresh CI.
The reviewed package checksum was independently verified before preparation:

`323706a15528e2cf15653600276c5908e2c8bbc5ea20e92394696cbdc9d9535b`

## Original rc1 local Linux checks (before final UX correction)

Environment: disposable Ubuntu 24.04 ARM64 VM using hardware virtualization on an
ARM64 host, Python 3.12.3, normal non-root login, fresh virtual environment and
explicit fixture-process `umask 022`. No production credentials or data were used.

| Check | Result |
| --- | --- |
| Complete synthetic regression | 546/546 passed; 0 failures/errors/skips |
| Separate real-loopback installer HTTP security | 6/6 passed |
| Pinned dependency installation and consistency | Passed |
| Current advisory audit of pinned resolution | 56 dependency records; 0 reported vulnerabilities |
| Private-information/source integrity and no-sending import checks | Passed |
| License inventory | 57 installed package metadata records; pinned dependencies unchanged |

Complete stdout, stderr, step timings and exit codes were retained. Audit success
is the advisory database's result at validation time, not a guarantee against
undisclosed vulnerabilities. The earlier implementation-validation wrapper mode
problem and its corrected rerun remain disclosed in WIZARD_VALIDATION.md; no
application guard was weakened. The public fixture suite expects conventional
`umask 022` inside its private temporary parents.

## Retained installation and manual evidence

The three original clean Ubuntu ARM64 paths and three fresh emulated x86_64 paths
passed Reader-only, Reader plus Drafts and full Organizer acceptance. Reader-only
also completed through actual Chrome UI. Installed MCP declarations were 5/7/8,
including unchanged seven-tool Reader/Draft behavior when Drafts is selected.
Synthetic reads preserved flags; no acceptance draft save, classification or move
was made. Full setup left execution, automatic policy and delegated chat consent
false. HTTPS login/logout, role separation and session invalidation were checked.

The reviewed implementation passed 546/546 tests on ARM64 and 546/546 across the
complete disjoint emulated x86_64 inventory, plus 6/6 HTTP checks on each. These
are retained implementation results, distinct from the fresh rc1 source/CI checks.

Owner-operated Chrome downloads subsequently passed for both actual files, with
exact expected names, bytes and SHA-256. No real credential or production setting
was present; the helper was not run. The actual completion screen states that setup
is installed while separately requiring the AI-client connection. See
[MANUAL_DOWNLOAD_ACCEPTANCE.md](MANUAL_DOWNLOAD_ACCEPTANCE.md).

## Package and CI verification

The source manifest covers application code, synthetic tests, configuration examples,
applicable licenses, documentation and screenshots. Packaging verifies every source
checksum and archive entry against those files; source ZIP/tar and the standalone
Linux verifier have separate SHA-256 checksums. No virtual environment, mailbox
content, journals, witnesses, receipts, TLS/SSH keys or private support data is shipped.

The CI job retains its required `synthetic` name, runs the entire regression and HTTP
suites, source checks, dependency audit, package builder and self-contained Linux
verification package. The verifier creates a fresh temporary source/venv, preserves
complete step logs, uses synthetic/loopback tests, needs no sudo and does not install
InboxTether or connect to email. Full verifier output, exit codes and package checksums remain in CI job logs.
The repository allowlist permits only the existing checkout and Python setup actions;
no artifact-upload action or permission expansion is required. Checksummed review
packages are also retained separately for owner review.
Current required checks must pass on the exact PR head before publication approval.

## Explicitly unverified and unsupported scope

- Native x86 hardware **clean-install acceptance** remains unverified. Retained
  x86 wizard installs used QEMU TCG software emulation on ARM64. A native-instruction
  CI regression run does not certify native-hardware installation acceptance.
- The owner completed full-feature rc1 installation and a graphical Claude Desktop
  one-call folder-listing test on October 31 before this final wording correction.
  The helper implementation is unchanged. The corrected UI is tested separately
  without re-registering or modifying that existing client connection. Graphical
  ChatGPT connection acceptance, Windows helper execution and PowerShell commands
  remain unverified. The fixture HTTPS hostname is VM-local; no Mac DNS or CA trust
  change was made.
- Provider provisioning/ACL changes, OAuth enrollment, DNS/firewall/certificate
  issuance and renewal are owner prerequisites. Hosted clients need their own
  supported connection; exported stdio JSON alone does not connect them.
- Initial installations only. No existing-state upgrade/migration/downgrade,
  automatic inverse-mailbox rollback or production deployment is certified.
- No malware guarantee, DKIM-authenticity certification or blanket relaxation of
  conservative customer, identity, MIME or uncertainty controls is claimed.
  Historical Keeps are not automatically reconsidered.

**Recommendation: include this follow-up in the existing 2.1 PR, conditional on
fresh PR CI success.** Preserve stable v2.0.0 and the published v2.1.0rc1 tag/assets.
Merge and any later tag or release require separate owner approval. Sending remains excluded; automatic filing and execution
are disabled by default for new installations. No production installation, mailbox,
Radar/plugin, credential, account, ACL or historical record was changed.
