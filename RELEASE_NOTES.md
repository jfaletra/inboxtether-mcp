# InboxTether MCP 2.0.0 — final release candidate (unreleased)

This updates the existing release PR with the reviewed production improvements,
adapted to the public clean-install source. It adds no new infrastructure or AI
provider. It is not yet merged, tagged, published or deployed as this public build.

- Prepare exact manifests for up to 200 accepted noncustomer messages.
- Execute in acknowledged ten-message chunks with fresh validation, preserved
  flags, durable destination receipts and permanent stop-on-ambiguity claims.
- Review/approve/start within 24 hours; the execution deadline is fixed at 30 hours
  after preparation. No implicit approval renewal or uncertain retry.
- Discover compatible saved proposals with paginated counts and actionable errors;
  use compact, two-hour, snapshot-bound selection references instead of relaying
  hundreds of UIDs through the assistant. Explicit exclusions never replace mail.
- Keep manual exact chat consent and independent browser approval as alternatives.
- Optionally enable an inspectable and revocable owner automatic-filing policy for
  Industry, Marketing, Orders and Suppliers. It is disabled by default and never
  manufactures per-batch human consent. Review, customer/potential-customer, mixed
  and uncertain messages remain in Inbox. No background scheduler is included.
- Read accepted customer risk from the actual nested saved reply, strictly requiring
  clear risk; malformed, missing, uncertain and flat legacy fields fail closed.
- Tolerate only the demonstrated inert HTML forms (closing br, unmatched closing
  body, compact doctypehtml), while rejecting active content, decoding failures
  and unfinished markup. Customer keywords and identity rules are not relaxed.
- Correct explicitly reviewed historical classifications using fresh source-bound
  context and archive the original decision. Historical Keeps are not automatically
  reopened, and conservative protections may continue to produce false Keeps.

Reader/Draft source and declarations, public socket recovery, approval authentication,
customer safeguards, full-message hashes, UIDVALIDITY, destination verification and
replay protections remain. **Sending email is excluded.** Draft preparation/save is
a separate opt-in workflow, never invoked by organization.

The public distribution contains application source, synthetic tests, templates,
dependency pins and documentation only. No private configuration, credentials,
mailbox content, business rules, journals, receipts, witnesses or migration data.
The public journal remains distinct from private deployment state. No private-state
migration, downgrade, automatic inverse-move rollback or provider certification is
claimed. See VALIDATION.md, INSTALLATION.md, AUTOMATIC_FILING.md and UPGRADE.md.
