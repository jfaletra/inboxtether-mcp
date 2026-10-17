# Draft Assistant development review

Reviewed October 17, 2026. This is an implementation review and synthetic validation, not an independent security assessment or authorization to enable writes.

## Findings addressed in design

- Client consent is not portable enforcement. No remote approval tool, boolean, echoed user text or model-visible bearer grant is used. Local operator review is separate from MCP; exact frozen content is fingerprinted and single-use, expiring approval is consumed in a durable transaction.
- Existing Reader code/guard remains unchanged. A separate adapter permits only one exact APPEND with the Draft flag. No SMTP, folder creation, existing-message STORE/MOVE/COPY/DELETE, EXPUNGE, SELECT or CLOSE path is added.
- Host/account/folder are operator-fixed; recipient groups, threading, source identity and digest, destination UIDVALIDITY, MIME bytes and expiry are bound to the review. Source or destination changes reject before APPEND where detectable. Saved bytes are verified through APPENDUID and BODY.PEEK.
- Ambiguous attempts fail closed to further saving. No automatic retry, duplicate replacement or deletion is attempted. Durable claimed state survives a process restart; caller replay cannot grant a new APPEND.
- Private local state has ownership/mode/symlink checks and bounded records/bytes. Unsafe or changed inputs fail closed; unexpected tool errors suppress private underlying messages. No new third-party dependencies.

## Review and validation

84 local synthetic tests pass, retaining all 55 Reader tests, plus actual IMAP framing and real MCP stdio error/discovery tests. Runtime dependency consistency passes. Fresh strict pip-audit reports zero known advisories/zero skipped packages for 29 runtime and 27 auditor dependencies. Automated advisory/pattern checks have finite coverage and do not establish absence of defects or secrets.

The diff is limited to source, synthetic tests, default-off configuration, ignore rules and documentation/metadata. No production source, secret, live mailbox fixture, private infrastructure configuration or deployment history is imported. Full file/index/Git-object pattern scans and known-private-identifier checks are required on the PR head in addition to hosted tests/audits/hygiene. Public GitHub noreply attribution and the owner's existing repository username are intentional public metadata.

## Remaining limitations and decisions requiring approval

1. **Approval trust model:** approve the local operator-terminal workflow before enabling it. The host/operator/service account are trusted; a model with that account's shell/filesystem or credentials can bypass it. A TTY is not identity verification. A separately authenticated isolated approval broker is future work, not an implemented client-portable UI.
2. **Live write enablement:** separate approval is required to configure the flag, storage/ACLs, restart any service, or perform a live APPEND acceptance test. Default off leaves only Reader tools. No such action is performed in development.
3. **IMAP atomicity:** destination replacement/source change can race validation and APPEND. Standard IMAP has no conditional transaction for these checks. Read-back may detect but cannot reverse a write; no automatic deletion is acceptable. Provider folder behavior, UIDPLUS/APPENDUID, exact MIME persistence, ACL scope and flags need a dedicated approved test.
4. **Private staging:** full MIME/recipients are stored locally, unencrypted. Ten minutes is logical expiry; cleanup is on subsequent preparation, with no secure-erasure guarantee. Backups/journals/snapshots and MCP client previews require protected storage and a deliberate retention policy. Do not upload approval databases or use shared/network state.
5. **Ambiguous outcomes:** an operator must privately reconcile before preparing any replacement; no exactly-once delivery guarantee is claimed across server/storage failure. Distinct separately approved drafts are distinct operations.

No merge, release, production deployment or write enablement is authorized by this review. Reader Mode remains default, Draft live compatibility unverified, Send Assistant planned only.
