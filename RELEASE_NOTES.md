# InboxTether MCP 2.0.0 — refreshed release candidate (unreleased)

This candidate replaces the earlier documentation-only stable preparation. It has
application changes and requires fresh review/CI before merge or publication.

- Prepare one exact manifest for up to200 accepted noncustomer messages.
- Execute in acknowledged ten-message chunks with durable verified receipts.
- Review/approve/start within24 hours, with a separate fixed30-hour execution
  deadline. Neither approval nor continuation extends the manifest.
- Discover saved compatible candidates in pages of100 with counts and snapshot
  cursors. Reject missing or incompatible preference bindings before reservations.
- Use a compact server-managed reference for up to200 exact candidates; inspect
  individual details in pages and exclude explicit messages without replacements.
  The reference path validates all sources before reserving the completed manifest.
- Return allowlisted actionable errors and preserve blocked progress for inspection.
- Retire expired, never-attempted ordinary reservations safely on a new preparation.

Existing Reader/Draft functions, exact-manifest chat consent, independent browser
approval fallback, customer/content protections, persistent flags, source hashes,
UIDVALIDITY, destination verification and permanent no-retry claims are preserved.
No new service, database, AI provider, scheduler or authentication platform is added.
Email sending remains entirely excluded.

This public source uses neutral tool/configuration names and fresh initialization.
It contains no private accounts, operational records, deployment paths or mailbox
data, and includes no import/migration of private state. All writes remain opt-in.

See VALIDATION.md for current test results, clean-install scope, historical versus
current client acceptance and remaining limitations. No merge, tag, publication or
production deployment has occurred for this candidate.
