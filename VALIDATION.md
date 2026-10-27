# InboxTether 2.0.0 validation and acceptance

Prepared on 2026-10-27 from the exact published v2.0.0rc3 source ZIP:
`46a9135d88bb2cb87c6bd532d33fec7a3d2a582011ccecb6bac6fca12bd44c91`,
commit `cf7f2cbad4a699e42b9bc6cd3eee268b858f52bf`.
Only documentation, version/provenance/validation/release records and the checksum
manifest change. All 58 Python files are byte-identical: 37 application/support
files and 21 test files. Dependency files, examples, CI, licenses and artwork are
unchanged. The seven Reader/Draft contracts, Secure alternative, 13 organization
actions, exact approvals, protections, preferences and replay/receipt controls are
preserved. Sending remains absent.

## Checks on this stable candidate

- The complete 304-case synthetic suite passed on macOS / Python 3.11.5 with zero
  failures, errors or skips. The existing runner clears operational settings and
  rejects IP socket operations. No production resources were supplied.
- Full MCP metadata/schema/annotation comparison against extracted rc3 matched in
  Reader-only (5 tools), Basic Drafts/organization (8) and Secure Drafts/organization
  (8) profiles. This is SDK metadata inspection, not new AI-client acceptance.
- All 56 installed pinned package versions and recorded license metadata matched
  the unchanged constraints/inventory; dependency consistency passed. The strict
  2026-10-27 pip-audit check reported zero known vulnerabilities in those pins.
  This is bounded advisory evidence, not an undisclosed-vulnerability guarantee.
- The source manifest is regenerated. Archive entries, checksums, license/artwork
  notices, local documentation links and source/private-pattern hygiene are checked
  separately during packaging. No dependencies, private configuration or state are
  bundled. Root MIT and separate artwork restrictions remain intact.

The unchanged rc3 application/test baseline previously passed all 304 tests on
Ubuntu 24.04 / Python 3.12.3 as UIDs 0, 1001 and 1002, and [GitHub Actions](https://github.com/jfaletra/inboxtether-mcp/actions/runs/40427695602)
for the exact commit above. Those are historical rc3 results, not a new hosted run
of this 2.0.0 documentation snapshot. No GitHub write or new Linux/mailbox/client
acceptance was performed during this preparation.

## Actual acceptance of the unchanged rc3 application

| Layer/client | Actual coverage | Boundaries |
|---|---|---|
| Dovecot 2.3.21 on disposable Ubuntu 24.04 / Python 3.12.3, MCP SDK stdio/Unix broker | Real TLS IMAP reading/search, Basic Drafts save, approved moves, receipt-linked correction, one-message correction, preference create/edit/revoke and future constraints, restart preservation | Programmatic protocol/backend acceptance; not an AI assistant or graphical browser |
| Signed-in Codex CLI 0.164.0-alpha.11.1 | Reading/search, reply preparation, one saved draft, source-bound classification, one separately approved verified move, narrow preference approval/inspection/revocation | Actual AI client, not graphical or SDK simulation. 24 MCP calls: 22 completed, two initial calls safely blocked by client approval settings and an omitted payload; corrected settings/guidance completed the test |
| Signed-in Claude Desktop 3.6556.2, Sonnet 5.5 Medium | Same bounded workflows; eight tools and all 13 actions discovered; **19 successful MCP calls** | Actual native graphical chat and local MCP connection, not CLI/SDK simulation. Guided test of one client/model/configuration |

The client tests used synthetic messages on disposable Dovecot, never a production
mailbox. Complete displayed draft/batch/preference plans were compared independently
with the backend before fresh exact consent. One Drafts save and one move completed
in each real-client pass. Independent IMAP checks verified the saved MIME and moved
bytes, destination UID/UIDVALIDITY, source removal and persistent flags. The graphical
Claude move preserved an empty flag set; protected flagged/customer originals stayed
unchanged. All test connections/environments were removed after verification.

**Graphical Claude MCP testing is distinct from browser approval.** The separate
browser-password-session mechanism was exercised through real verified HTTPS login
and review forms, cookies and CSRF by an operator harness. No graphical browser
approval click-through was tested, and the synthetic owner does not certify a human
identity. Draft saves used Basic/client-controlled confirmation. Preference decisions
used optional `client-session-consent`, which is lower assurance and cannot
independently prove human approval. Native client permission prompts are not backend
owner authorization. See [trust guarantees](WORKFLOWS.md).

Initial Claude UI/clipboard coordination and JSON presentation needed explicit
guidance. The model initially misidentified its host and later abbreviated a receipt;
neither claim was treated as evidence. Exact copied JSON and independent checks
provided the comparisons. No application defect or extra mailbox write resulted.

## Remaining unverified client workflows and known limits

Ordinary ChatGPT graphical interaction, graphical browser approval, Secure Drafts
browser/OIDC use, attachment presentation/download UI, client-driven future rule
matching and receipt-linked corrections in a graphical client were not exercised
by the two real-client passes. Corrections remain experimental at that UI level;
their backend and synthetic evidence is separate. Other clients/models, provider
account mappings/ACLs and production deployment are not certified by these results.

Use the fixed categories and exact folder/login character constraints; the revised
[installation prerequisites](INSTALLATION.md) document IMAP `\Drafts` special use
and unsupported `*` separators. No new installation rerun is claimed for these
documentation-only corrections. Native Windows organization, automatic legacy-state
migration, automatic moves, inverse rollback and uncertain retries are unsupported.
The existing discovery/journal/review bounds fail closed. A guarded smoke test does
not certify arbitrary classification quality, sender authenticity, every credential
exposure pattern or universal compatibility. See [README limitations](README.md).

## Reproduce focused checks

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-validated.txt -r requirements-test.txt -r requirements-audit.txt
.venv/bin/python -m pip check
.venv/bin/python run_tests.py
.venv/bin/python scripts/verify_release.py
.venv/bin/python -m pip_audit -r constraints-validated.txt --no-deps --disable-pip --strict --progress-spinner off
```

Publication, tagging, stable-branch changes, installation and mailbox acceptance on
a new deployment are separate owner-controlled actions. This dated preparation
record grants none of them. [Machine-readable record](VALIDATION.json) includes the
baseline and operator evidence report hashes without private raw transcripts/state.
