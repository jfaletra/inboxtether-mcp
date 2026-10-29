# Refreshed InboxTether 2.0.0 candidate validation

This is an unreleased application update to PR #11, based on public commit
`062db6eabf47f4a9a2b0d01750aa729924fc6843`. It is not the earlier
documentation-only stable preparation and is not yet published or deployed.

## Actually tested for this revision

- The complete public suite: **402 tests**, zero failures, errors or skips,
  on macOS / Python 3.11.5. Tests clear operational environment
  settings, reject IP sockets and use only synthetic messages and disposable files.
- Fresh virtual environment installation of the pinned runtime/test/audit dependencies;
  dependency consistency passed. The current strict advisory audit of56 pinned
  packages reported zero known findings. This is not a guarantee against unknown flaws.
- Clean public configuration and empty journal: source-bound classification of200
  fabricated messages, compact selection reference,20 preparation chunks, one exact
  consent,20 verified execution chunks, flags/hash receipts and restart preservation.
- Existing explicit-UID preparation, 24-hour review/start and fixed30-hour execution
  deadline, expired unused reservation retirement, paged discovery, safe errors,
  exclusions, stale/tampered/expired/replayed selections and interrupted claims.
- Reader/Draft canonical source contracts, independent browser/CSRF flows, opt-in
  client-relayed consent, customer checks and replay/no-retry protections.
- Source manifest, private-pattern and sending-import checks and clean archive
  extraction are checked during packaging; extracted source is rerun separately.

## Historical evidence is separate

The PR #11 baseline previously passed304 tests in GitHub Actions. Earlier rc3
acceptance used disposable Dovecot, signed-in Codex CLI and graphical Claude Desktop.
Those results apply to that older source, not to this updated public revision.
The port incorporates separately exercised organization improvements without copying
private configuration, accounts, operational receipts or production data. No new
production operation is part of this release preparation.

## Still unverified

The updated public source has not yet run through a new hosted Linux CI job, live
IMAP/provider acceptance, graphical assistant integration, graphical browser approval
or production upgrade/migration/rollback acceptance. Other providers, clients and
permission mappings are not certified. Tests do not independently prove the identity
of a human using optional client-session-consent; browser authentication remains
the independent owner fallback. Sending remains absent.

Public clean initialization remains separate from installation-specific journals.
Do not import a private ledger/witness/receipt set. No automatic downgrade, inverse
move rollback, uncertain retry, background scheduling or history pruning is supplied.
Selections expire after two hours and changed snapshots fail closed; completed
ordinary manifests retain24-hour review/start and30-hour execution deadlines.
See WORKFLOWS.md and UPGRADE.md.

## Reproduce

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-validated.txt -r requirements-test.txt -r requirements-audit.txt
.venv/bin/python -m pip check
.venv/bin/python run_tests.py
.venv/bin/python scripts/verify_release.py
.venv/bin/python -m pip_audit -r constraints-validated.txt --no-deps --disable-pip --strict --progress-spinner off
```

Push, merge, tagging and publication require separate owner approval.
