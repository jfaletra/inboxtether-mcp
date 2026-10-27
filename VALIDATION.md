# InboxTether 2.0.0rc3 focused validation

The only Python-code change is the socket-readiness test fixture in
`tests/test_rc2_regressions.py`. Its fixed mock peer UIDs collided with the actual
socket owner on GitHub runners. The application correctly refused that identity
combination; no application defect or security-control change was required.

The fixture now chooses two positive, bounded, distinct synthetic peer UIDs from
1..3 excluding the real socket owner. The mocked web lookup and exact four ACL
assertions use those values. All account lookup and ACL changes remain mocked:
the fixture creates no OS users/groups, grants no real ACLs and needs no privilege.
The failing path does not use a fixed group ID.

## Completed local checks

- Full 304-case suite passed locally on macOS / Python 3.11.5, zero failures/errors/skips.
- The original rc2 failing case was reproduced under both UIDs 1001 and 1002 in a
  disposable Ubuntu 24.04 arm64 / Python 3.12.3 environment.
- All 304 rc3 cases passed there as UID 0, UID 1001 and UID 1002, with zero
  failures/errors/skips in each run. Separate test identities existed only in that VM.
- Every runtime Python file, all other test code, the Reader/Draft contract pins,
  dependency constraints, workflow, licenses and artwork notices are byte-identical
  to rc2. The seven Reader/Draft interfaces, Secure Draft alternative, 13 organization
  actions, approval behavior and security controls are unchanged. Sending is absent.

The complete suite retains fabricated Reader/Draft/organization/correction adapters,
real MCP stdio/internal Unix IPC checks, exact consent/preference/replay protections
and private temporary directories. Operational settings are cleared by the runner,
which rejects IP socket operations. No production email or configuration is needed.
Previous rc2 service/login/crash/rollback evidence covers unchanged application code;
this fixture correction is not a new service deployment or live acceptance.

## Hosted check and review gate

The unchanged `.github/workflows/ci.yml` runs the full 304 tests, dependency consistency,
source/manifest hygiene and the constrained advisory audit on the CI-only branch
`ci/v2.0.0rc3-validation`. Publication recommendation requires complete success for
exactly the candidate commit. The final review report supplied alongside the checksummed
archives records the actual GitHub run URL and result. Validation creates no rc3 tag
or GitHub release and does not change the stable branch or release.

## Reproduce

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-validated.txt -r requirements-test.txt -r requirements-audit.txt
.venv/bin/python -m pip check
.venv/bin/python run_tests.py
.venv/bin/python scripts/verify_release.py
.venv/bin/python -m pip_audit -r constraints-validated.txt --no-deps --disable-pip --strict --progress-spinner off
```

No dependencies are vendored. Source manifest and archive checksums must be verified
before review. Pattern/advisory checks are bounded evidence, not guarantees of absence
of undisclosed vulnerabilities or every secret. Organization, corrections and actual
ChatGPT/Claude/provider acceptance remain experimental. Optional client-relayed consent
is lower assurance, not independently verified human authorization. Sending stays
excluded from the 2.0 line. No production deployment or mailbox work is authorized.
