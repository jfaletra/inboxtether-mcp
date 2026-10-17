# Validation evidence

Prepared October 17, 2026. **51 local tests passed** on Python 3.12 with MCP SDK 1.30.0. A clean local CI-equivalent environment passed dependency consistency checks. A separate pip-audit 2.10.1 advisory audit found zero known vulnerabilities and zero skipped packages across fresh runtime resolution (29 packages), the installed Linux runtime snapshot (29 packages), and the auditor tool resolution (27 packages); see security/dependency-audit-2026-10-17.json.

## Relation to the working implementation

Source was reconciled against the verified deployed Reader implementation. A syntax-tree comparison confirmed the same application logic after normalizing only the three operator-configuration assignments and product-name strings. The community package reads INBOXTETHER_IMAP_HOST, INBOXTETHER_ACCOUNT, and INBOXTETHER_PASSWORD_FILE with example defaults. The working private deployment was not renamed, reconfigured, restarted, or updated during this preparation.

Mailcow is the first verified platform. Existing live evidence covers mailbox listing, enhanced search, bounded message retrieval, five-tool discovery, and one explicitly user-selected attachment retrieved through the connected MCP plugin with independent size/SHA-256 validation. No private headers, filenames, contents, account/tunnel identifiers, server addresses, or screenshots are included here. The public environment-variable packaging/branding changes have not been deployed to that system. Other IMAP platforms have not been certified.

## Local tests

The 49 tests for the deployed behavior cover the read-only command guard, TLS configuration, password-file protections, MIME/output limits, actual IMAP framing over socket pairs, MCP stdio initialization/discovery, additive search metadata and identity checks, selected attachment choice, stale IDs, wrong UIDVALIDITY, size boundaries, unsafe type/name/signature, invalid encoding, MIME depth/count limits, and credential-free errors. Two additional tests check the community configuration defaults and explicit operator environment.

Tests use synthetic fixtures and do not authenticate to a mailbox. Local maximum-size tests do not establish maximum-size behavior through every MCP client/tunnel. Basic JPEG signature and checksum validation are not full image validation or malware scanning. No independent before/after live flag comparison or deliberate crash/reboot test was performed. Read-only wire behavior is tested; the credential itself may still permit writes through another client.

## Package checks

Local configuration JSON and repository-relative documentation links were checked. Brand PNG dimensions, byte limits, preservation hashes, and metadata were inspected. All candidate files, the Git index, and reachable local Git objects were scanned for known private environment strings and common credential/private-key patterns; findings are documented in SECURITY-REVIEW.md. No private deployment history is imported.

CI is prepared but has not run on GitHub. A clean local requirements installation and all 51 tests passed; workflow/Dependabot YAML, event triggers, SHA pins, permissions, and fail-closed audit steps were checked locally. The two official Actions release pins were resolved against the upstream release API and Git tags, not guessed. The systemd example is an uninstalled skeleton requiring a tested operator launcher. No public endpoint, Docker image, package-registry release, or public plugin submission has been created or verified. A code/packaging review is not an independent penetration test or guarantee that no sensitive data could exist.

## InboxTether rename validation

All 51 tests and runtime/auditor dependency audits were rerun after the rename and passed. A syntax-tree comparison against the preceding verified community candidate passed after normalizing only branding/configuration identifiers. INBOXTETHER_* replaces the prior community configuration namespace; production was not changed or migrated. PROJECT.json records source-repository metadata and does not claim an installable PyPI distribution. Naming results and limitations are in docs/NAMING-REVIEW.md. The earlier Linux runtime audit is historical read-only evidence; fresh package audits are rerun evidence.
