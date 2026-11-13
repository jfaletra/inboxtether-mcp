# InboxTether 2.1.0rc1 candidate validation

This is the unmerged calendar release candidate in PR #13, based on public main
8f4b4d869f51ac74186e45ab9c3a568dc6c53518. The dependency-only correction upgrades
dnspython from 2.9.0 to 2.9.2 for CVE-2026-128089. No application code, test case,
production configuration or deployed package is changed by that correction.

## Completed checks

- The accepted raw unittest discovery baseline executes 670 tests and passes with
  zero failures/errors/skips. The existing canonical `run_tests.py` de-duplicates
  identical test IDs and passes 654 distinct tests. The difference is 16 repeated
  discoveries, not removed cases. All 39 focused CardDAV regressions are retained.
- Final full suites run as an unprivileged user with CPython 3.12.16 in the
  existing isolated image, read-only source,
  private synthetic temporary state, no production credentials and no IP network.
  The canonical runner also clears operational environment settings and rejects IP
  sockets. Unix-domain/ASGI fixture approval traffic is synthetic, not provider access.
- Public-factory integration inspection preserves all eight email definitions,
  validates the sanitized configuration examples, returns 18 tools when creation
  is enabled and 16 with it disabled, and exposes no update/cancel tools. No tool
  or external action is invoked during inspection.
- All 62 constrained package versions are verified in the isolated environment
  including temporary audit tooling. pip check passes. Pinned pip-audit 2.10.1
  reports no known vulnerabilities on November 13, 2026, with strict checking and
  no advisory exclusions. Only this disposable audit container used public network
  access; it had no production credentials or mounts. A clean audit does not prove
  absence of unknown vulnerabilities or assess the host OS.
- Repository hygiene scans include source, examples and fixtures; the Git history
  pattern check scanned 504 pre-existing objects without findings. Checks do not
  print matched secret values. They are not exhaustive DLP or a substitute for review.
  The final manifest and staged-file hygiene checks must pass on the final source.

Tests cover calendar aliases and account separation, date/time-zone validation,
all-day exclusive ends, recurrence reading, moved/cancelled occurrences, search,
interval-only availability, invitation policy, immutable proposals, quotas, durable
replay, uncertainty recovery, metadata-only audits and existing email protections.
CardDAV tests cover exact/partial names, shortened N/missing FN, multiple addresses,
late matches/ambiguity, complete large scans, overflow, malformed cards, server
truncation, cross-account denial, read-only guards and response limits.

## Reproduce offline application tests

Use Linux/Python 3.12, a new environment, private HOME/scratch and reviewed pinned
packages. Install test dependencies before disconnecting networking:

```sh
python -m pip install -c constraints-validated.txt -r requirements-test.txt
python -m pip check
python -B run_tests.py
```

To reproduce the historical count, `python -B -m unittest discover -s tests`
executes 670 discoveries; supply a private TMPDIR for administrator-policy fixtures.
Do not provide live credentials or operational settings. Install the pinned audit
tool separately with requirements-audit.txt to repeat the advisory check. Packages,
wheels, virtual environments and external test logs are not included in this source.

MANIFEST.sha256 covers every shipped file except itself and uses LF text bytes.
Run `python -B scripts/verify_release.py` and `python -B scripts/check_repository.py`.
Use `--history` on the latter only with complete fetched Git history. The original
Reader/Draft contracts and public email implementation remain unchanged, apart from
an opt-in calendar read registration call in the server factory. The root-ownership
CardDAV policy fixtures use synthetic metadata so unprivileged CI needs no sudo; production
ownership/type/mode guards remain unchanged.

## Provider findings and publication limits

Owner-observed disposable Mailcow/SOGo component tests established timed/all-day
creation, read-back, replay, lost-response reconciliation, invitation receipt and
small address-book lookup. These are historical private-deployment observations,
not fresh live acceptance of this sanitized public factory or its deployment.
No real account, calendar content, contact list, credential or raw live artifact is
shipped or accessed by the candidate tests. Large real address-book compatibility
must still pass a separately authorized bounded read-only acceptance.

The tested SOGo 5.12.5 endpoint accepted an If-None-Match wildcard collision and a
missing-target PUT carrying a nonmatching If-Match. Those safety gates failed.
Creation accepts a documented residual overwrite race; update, reschedule and
cancellation remain disabled. Keep raw failed-test evidence private and unchanged.

Conversational confirmation is client-mediated authority, not a server-verifiable
human click. An authorized connection can commit without a fresh owner prompt.
Invitation storage, scheduling dispatch and email delivery remain separate facts.
No automatic retry/resend, recurring-event write, contact write, Google integration,
private email adapter, new tunnel, approval UI or state migration is included.

The initial PR CI passed all 654 distinct tests and manifest/hygiene verification,
but its fresh advisory audit flagged dnspython 2.9.0 for CVE-2026-128089. The earlier
local audit result is historical and did not waive that finding. Both applicable
pins now require 2.9.2, whose installed license metadata is recorded. The corrected
62-package environment passes pip check and the unchanged strict audit with no known
vulnerabilities; no finding is suppressed. Review fresh GitHub CI on the corrected
head before merge. Public-candidate live deployment/rollback acceptance remains
unverified.
Dependency pins are version constraints, not a wheel-hash lock. Publication and any
production rollout remain separate owner decisions.
