# Publication preparation security review

Review date: October 17, 2026. Scope: this repository's source, synthetic tests, docs, examples, branding files, Git index, and reachable local Git objects. This is a preparation review, not an independent security audit.

This original preparation snapshot predates private hosting. For the v1.0 candidate, use security/V1-RELEASE-REVIEW.md and the exact-candidate CI evidence.

## Findings and changes

- Removed private deployment host/account/password-file settings from public source; operator environment variables now use example-domain defaults. Application behavior otherwise matches the verified Reader implementation.
- Excluded deployment scripts, protected secrets, operational reports, real message/attachment identifiers, private account screenshots, scratch files, virtual environments, and caches. Tests contain synthetic data only.
- Reconciled docs with production: five read-only tools, selected attachment flow, actual size/type restrictions, Base64 response limitations, and explicit client responsibility for consent. Summarization is a client/model capability, not a server endpoint.
- Reader Mode is the default and only implemented mode. Draft Assistant and Send Assistant are explicitly planned; no SMTP or IMAP write operations were added.
- Corrected earlier documentation that overstated verification or implied native file delivery. No claim of non-Mailcow compatibility, full file safety, or server-enforced human consent remains.
- Preserved the original logo unchanged. No EXIF, IPTC, or XMP data was found in the supplied original. Export metadata was inspected; live account screenshots are excluded. Artwork rights are separated from the MIT code license.
- Created a fresh local repository with no inherited commits, remotes, or production history. No commit or push was made. The final index and reachable objects were scanned, not just visible working-tree files.

The final preparation scan found no known private environment identifiers or common credential/private-key patterns in the publishable file set. The explicitly approved public GitHub handle/repository name is intentional project metadata; no private email address, personal name, or account secret is included. Automated scanning cannot establish absolute absence of all secrets or replace owner review. No actual credential files were opened or copied for this review.

## Documented residual risks

An authorized client can invoke retrieval without human confirmation; identifiers are not consent tokens. Application read-only guards do not revoke write authority from the mailbox password. The fixed account exposes all accessible folders to that client. Allowed file signatures are not antivirus. CSV can contain formulas. Results may be retained by the consuming product. Resource limits can reject legitimate mail and socket timeout is not an overall deadline. No new production changes were made to address these already documented boundaries.

## Before publication

The intended repository is jfaletra/inboxtether-mcp. The owner has confirmed branding distribution permission while excluding artwork from MIT. The repository now exists privately; Public visibility remains a separate approval. Configure GitHub private vulnerability reporting (or a suitable private contact) before accepting public security reports. Retain the dependency-audit workflow and Dependabot configuration; review their findings and proposed updates before merging. A dated pip-audit report is included. Future scans can discover new advisories; no finding has been suppressed. Run the prepared CI once hosted. Branding uploads and live plugin-icon changes are separate actions, not implied by publishing source.
