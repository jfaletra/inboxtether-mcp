# InboxTether 2.0.0 final candidate validation

This unreleased synchronization candidate updates existing PR #11 from commit
`27465c6ca68e784df96b51ea34e251f04ff214cb`. Its version is 2.0.0; merging,
tagging and publication still require owner approval.

## Tested for this source

- **506 tests passed on macOS/Python 3.11 and Linux/Python 3.12.3**, with zero
  failures, errors or skips. Exact artifact/bundle reruns are retained in release
  preparation evidence; GitHub-hosted validation is linked in PR #11 after push.
- Fresh Linux virtual environment and unchanged 56 constrained runtime/test/audit
  dependencies: installation and pip consistency passed. Strict advisory audit
  reported no known vulnerabilities on October 30, 2026. This does not establish
  absence of unknown vulnerabilities or audit the operating system.
- Synthetic empty public initialization: 200 classifications, compact reference,
  twenty acknowledged preparation chunks and twenty verified execution chunks,
  with restarts. Both manual exact-consent and owner-policy modes passed.
- Manual chat consent, independent owner-password/CSRF browser workflow through
  fixture HTTP/Unix IPC, exact-fingerprint validation, malformed/expired/replayed
  requests, revocation and execution-gate changes at the MOVE boundary.
- Automatic policy disabled by default, four-folder restriction, Review/customer/
  potential-customer/uncertainty Keeps, strict nested saved-risk handling, history-
  preserving corrections, current source/destination/hash/flag validation, deadlines,
  immutable receipts, interrupted execution and permanent no-retry claims.
- Inert HTML tolerances and active/unsafe/MIME/decoding/unfinished-markup rejection;
  customer keywords and identity guards remain unchanged.
- Original Reader/Draft source and canonical tool contracts, real SDK stdio calls,
  browser listener recovery, fixture peer permissions, source/secret-pattern and
  sending-import checks. No real message is required by any test.

The Linux suite ran unprivileged against root-owned read-only source and private
synthetic scratch in an isolated network namespace. Owner-enrollment tests use a
fabricated administrator/TTY fixture; no production policy or credential is loaded.
The initial local run found a missing synthetic format fixture and restricted-path
Unix socket length failures; fixture packaging and test environment were corrected,
without weakening application checks. An initial wheel-only dependency download
failed because pinned dkimpy is source-only; the same pinned source was built into
a wheel. Complete output and exit codes for failed and passing runs are retained
outside the public source. No application change was made for wheel packaging.

## Self-contained verification

The source archive contains every first-party module, imported synthetic support
module, JSON fixture, example/configuration template and asset needed by the suite.
MANIFEST.sha256 detects missing or changed files before acceptance. The companion
Linux CPython 3.12 x86_64 verification bundle also contains the complete public
dependency wheel closure, a checksum preflight and an offline installer/verifier.
System Python/venv, Linux/glibc and standard libraries are platform prerequisites,
not bundled applications. Dependency versions are pinned in constraints-validated.txt.
The companion bundle is a release-preparation artifact, not a new runtime service
or a dependency on private files. Deliberately missing helpers, fixtures, wheels and
changed source must fail preflight.

## Historical evidence and unverified boundaries

Earlier public rc3 acceptance exercised signed-in Codex CLI and graphical Claude
Desktop against disposable Dovecot. That evidence belongs to older code. Separate
private deployment experience motivated these reviewed component ports; no private
accounts, business rules, mail, journals, receipts or operational evidence are shipped.
This preparation does not independently repeat or certify those production moves.

This final public source has **no new live IMAP/provider, graphical assistant, actual
HTTPS/browser or production upgrade/migration/rollback acceptance**. Synthetic
browser HTTP/IPC is not graphical acceptance. Other providers/clients, permission
mappings and supported versions must be assessed on the destination installation.
Optional client-session consent trusts the connected client; it is not independently
verified human identity. Automatic owner policy is distinct standing authority.
Sending remains absent; no SMTP transport is shipped.

Public clean initialization stays separate from private journals. Do not import a
private ledger/witness/receipt set, erase a claim or restore an older journal. No
automatic downgrade, inverse-move rollback, uncertain retry, history compaction or
background scheduling is supplied. Historical Keeps remain closed and may include
conservative false positives. See AUTOMATIC_FILING.md, WORKFLOWS.md and UPGRADE.md.

## Reproduce

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-validated.txt -r requirements-test.txt -r requirements-audit.txt
.venv/bin/python -m pip check
.venv/bin/python run_tests.py
.venv/bin/python scripts/verify_release.py
.venv/bin/python -m pip_audit -r constraints-validated.txt --no-deps --disable-pip --strict --progress-spinner off
```

Do not use production credentials in tests. Separate the dependency-install/audit
network step from isolated synthetic test execution.
