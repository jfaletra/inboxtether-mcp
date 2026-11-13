# InboxTether MCP 2.1.0rc1: local release candidate

This unpublished candidate extends the public 2.0.0 email release with reusable
Mailcow/SOGo calendar and contact modules. It does not deploy or import private
production email adapters, settings, state or business-specific rules.

- Multi-account calendar discovery, aliases, event retrieval/search and free/busy,
  with exact scope, version checks, recurrence reading and a 31-day window.
- Opt-in standalone timed/all-day creation, Public/Busy defaults and explicit
  privacy/availability overrides, random identities, durable idempotency, quotas,
  metadata-only audits, read-back and no blind retry after uncertainty.
- Controlled attendees on new events, organizer pinned to the account, separate
  invitation policy and truthful event/dispatch/delivery receipts.
- Read-only CardDAV discovery and local exact/partial name matching, multiple
  email choices, shortened SOGo names and a bounded 2,000-resource scan with a
  2,001-resource overflow sentinel. No incomplete scan is a complete lookup.
- Existing-connection calendar hook, public-factory adapter, disabled-write
  configuration examples and sanitized deployment/rollback guidance.
- LF source normalization, operational-data exclusions, current dependency/license
  inventory and refreshed source/checksum/validation metadata.

The accepted 670-discovery baseline is retained. The canonical runner removes 16
repeated test IDs and executes 654 distinct cases. Neither count represents live
provider certification. See VALIDATION.md for exact completed checks.

Email Reader/Draft/organization source contracts, approvals and opt-in automatic
filing remain unchanged. No SMTP email sender, synchronization, booking platform,
contact writer or additional approval infrastructure is added. Calendar updates,
rescheduling, cancellations and recurrence writes remain disabled: SOGo 5.12.5
failed the required conditional protection tests. Creation retains an explicitly
accepted residual overwrite race, not an atomic create-only guarantee.

No public release, push, merge or live deployment is authorized by this preparation.
