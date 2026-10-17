# Release checklists

## v1.2.0 candidate — preparation only

PR #6 remains unmerged. This checklist is not authorization to merge, deploy,
enable sending/filing, tag, publish a release or publish packages.

1. Record exact PR head; review source, [final security assessment](../security/V1.2-RELEASE-REVIEW.md),
   [notes](../RELEASE-NOTES-v1.2.0.md) and [upgrade/rollback](UPGRADING-v1.2.md).
2. Require successful unittest, privileged send-process-isolation, repository-hygiene
   and pip-audit on that exact head. The active main ruleset requires three of
   these; isolation must also be explicitly checked until added to required checks.
3. Verify five unchanged Reader schemas, preserved Basic/Secure Draft policies,
   disabled Send/Sent defaults, mandatory independent terminal approval, no Basic
   Send, exact MIME/destination binding, expiry/replay/concurrency and no retries.
4. Retain sanitized Mailcow acceptance evidence separately from private test
   identities, credentials, raw mail, receipts and deployment files. No secret or
   private infrastructure belongs in release archives. Confirm MIT/branding split
   and previously accepted naming uncertainty; no legal clearance claim.
5. Only after explicit merge authorization, verify current SHA/checks and merge
   without bypassing active main rules. Revalidate resulting main SHA afterward.
6. Only after separate publication authorization, recheck secret scanning/push
   protection, dependency alerts, private vulnerability reporting, Discussions and
   required main rules. CodeQL is not configured; do not claim it passed.
7. Prepare/review source ZIP/tar archives and SHA-256 manifest from the approved
   final commit. Proposed annotated tag v1.2.0 must name that exact commit. Use
   existing public/noreply attribution; never generate signing credentials here.
   Do not create even a draft release/tag ref before approval. Verify published
   tag/assets/checksums only during the separately approved publication step.
8. Source publication never installs a service or enables Send/Sent. Production
   upgrade, credential provisioning, write enablement and live testing have their
   own approval/backup/rollback gates. Never restore stale pending state or resend
   an email to repair a Sent-folder failure.

## Historical v1.0.0 checklist

# v1.0.0 release checklist and tag plan

This is a preparation runbook. Public visibility has since been authorized and completed. A version tag, GitHub release, or package publication is not authorized by this file. Production and other repositories are excluded.

## Freeze and evidence

1. Review the release PR and record its immutable head SHA. Verify only Reader Mode, expected five tools, source/license/branding scope, updated docs, tests, and no private data. Keep the MCP 2.x migration proposal unmerged.
2. Require successful `unittest`, `pip-audit`, and `repository-hygiene` checks on that exact SHA. Rerun on the final merge SHA if it differs. Independently scan all fetched Git history/commit attribution and compare the manifest to hosted contents. Avoid logs with matched secrets.
3. Historically while private, the saved main rules were not enforced and native secret scanning was unavailable; Public-stage enforcement and secret protection are now enabled (PUBLIC-STAGE-VALIDATION.md). Treat them as missing preventive controls. Use an exact-SHA human gate, full-history local/CI scans and manual review; these do not block an owner bypass or establish complete secret detection.
4. The owner accepted the identified naming-search risk; retain the documented limitations and do not claim legal clearance.

## Separately authorized publication window

After explicit owner approval, change only this repository to Public. Before tagging or publishing a release, verify privacy-sensitive contents/history again and confirm the saved branch rules really enforce PRs/checks and no force pushes/deletion. All three required checks, including `repository-hygiene`, are now bound to GitHub Actions; reverify this before tag/release. Enable and verify native secret scanning and push protection where available, private vulnerability reporting and reporter access, Discussions/moderation/pinned guidance, and security notifications. Do not claim features enabled solely because documentation/config files exist. If any gate fails, pause before tag/release.

## Prepared tag specification — do not execute yet

Version: `1.0.0`. Proposed annotated tag: `v1.0.0`. Annotation: `InboxTether MCP v1.0.0 — Reader Mode`. Target: the exact reviewed, successful final release commit, not a moving branch name. No tag object/ref is created during preparation, locally or remotely. Check that the tag does not already exist before a later authorized operation. Use an approved public/no-reply tagger identity; sign only with an existing configured identity if supported, never generate credentials as part of release prep.

Prepared release body: RELEASE-NOTES-v1.0.0.md. Do not create even a draft GitHub release now because a release workflow can create a tag implicitly. A future approved release must target the verified tag and include the final source/archive SHA-256 manifest. No PyPI/npm/MCP-registry publication is included.

## Go/no-go rule

Technical readiness requires passing exact-candidate tests/audits/hygiene and accepted residual security limitations. The Public source transition and naming-risk decision are complete. Version-tag/GitHub-release publication remains NO-GO until final explicit approval and successful exact-release checks with the Public-stage controls verified. Approval of Reader-first scope is not visibility/tag/release approval.
