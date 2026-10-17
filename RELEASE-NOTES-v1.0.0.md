# InboxTether MCP v1.0.0 — Reader Mode

Prepared release notes; not a published GitHub release. Tag name proposed: `v1.0.0`. Release date is assigned only after approval and final checks.

Your email. Your AI. Your control.

The first source release provides a fixed-account, read-only IMAP integration for AI assistants. Mailcow is the first verified platform. Python 3.12 and MCP SDK 1.30.0 are the verified runtime baseline.

## Included

- Folder listing and structured searches with UID, UIDVALIDITY, sender, subject and date.
- Bounded message text/headers with attachment metadata.
- Explicit selected-attachment retrieval with folder/message identity checks, type/size safeguards, Base64 output, byte count and SHA-256.
- TLS verification, protected app-password files, protocol command allowlisting, EXAMINE/BODY.PEEK reads, and bounded parsing/output.
- Installation and Secure MCP Tunnel guides, synthetic regression tests, dependency audits, Dependabot, and repository hygiene scans.

## Security and compatibility boundaries

No SMTP, sending, deletion, moving, draft-writing, flag updates, or other mailbox mutation tools are provided. Application guards do not remove write authority from an app password used elsewhere, and do not sandbox a compromised process or dependency. Client/model summarization is not a server endpoint.

Human attachment selection is enforced by the consuming client, not proven by an attachment ID. Complete messages are limited to 1 MiB and selected decoded attachments to 256 KiB. Only the documented PDF, PNG, JPEG, UTF-8 text and CSV combinations are accepted. Signature checks are not malware scanning. No native download UI or automatic opening is provided. Results reach the connected product and may be retained there.

Other IMAP platforms are unverified. Native Windows deployment is unverified. The systemd example requires an operator-tested launcher. This release publishes source only, not a hosted service, registry package, Docker image, or public ChatGPT plugin.

## Future work

Draft Assistant and Send Assistant are planned, opt-in proposals. Reader Mode remains the default. Sending would require trusted, server-side approval bound to the exact message; none of that exists in v1.0.0.

## Licensing and naming

Source/tests/docs: MIT. Branding assets: separate reserved-rights notice with owner-authorized project distribution, excluded from MIT. The name remains subject to the unresolved component-word TETHER trademark concerns in docs/NAMING-REVIEW.md; no legal clearance is claimed.

See README.md, SECURITY.md and docs/RELEASE-CHECKLIST.md before installation or publication.
