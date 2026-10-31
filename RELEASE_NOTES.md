# InboxTether v2.1.0rc1 — experimental prerelease candidate

Final wizard UX review correction: configure first, install and verify, then
reveal **Next Step: Download Your AI Connector**. Downloads use the validated
connection snapshot from the completed installation. Desktop connection success
is explicitly separate. Setup-link recovery and password re-entry instructions
are clarified without weakening security. This local correction awaits owner
review and fresh PR validation before publication.

Prepared for PR review against stable `v2.0.0`. No 2.1 tag or GitHub release has
been created. This is an initial-installation experiment, not a production upgrade.

## Included in rc1

- Three screens: Connect Email, Choose Features, Install & connect AI. Success
  remains on screen three, with remaining client connection steps shown separately.
- Implicit-TLS IMAP validation, existing-folder discovery and exact mapping, an
  optional distinct IMAP login and bounded port, private role credentials and the
  existing Linux approval services when Organizer is selected.
- Reader by default; optional Basic Drafts and Organizer. Existing rights, folder
  identity, UIDVALIDITY, source/package checks and owner approval controls remain.
- Visible, keyboard-focused validation errors, retained nonsecret entries and
  cleared password fields. No raw backend exceptions or passwords are displayed.
- Claude helper instructions for Downloads, quoted full paths and an explicit
  containing-directory alternative; JSON/helper exports contain no mailbox secrets.
- Actual owner-operated Chrome downloads passed exact filename, byte and SHA-256
  checks. The final screen distinguishes installed setup from connecting an AI client.

The stable 2.0 Reader/Draft contracts and filing engine are retained: up to 200
messages, acknowledged ten-message chunks, 24-hour review/start and fixed 30-hour
execution windows, compact selections, candidate discovery, actionable errors,
manual chat/browser approval, opt-in automatic filing, history, flags, integrity,
customer protections, receipts and replay/no-retry claims. **Sending is excluded.**
Mailbox execution, automatic filing and delegated chat consent are disabled in a
new wizard installation. Enabling authority is a separate explicit owner operation.
No AI provider/key, MCP transport, database or permanent dashboard is added.

## Evidence and limits

See [final UX validation](FINAL_WIZARD_UX_VALIDATION.md),
[rc1 validation](RC1_VALIDATION.md), [reviewed wizard evidence](WIZARD_VALIDATION.md)
and [manual downloads](MANUAL_DOWNLOAD_ACCEPTANCE.md). Actual screenshots are in
[the setup guide](SETUP_WIZARD.md#acceptance-evidence-and-screenshots).

- Target: new Ubuntu 24.04/systemd installations. Three clean ARM64 paths and three
  emulated x86_64 paths passed the retained installation acceptance. Reader-only
  additionally completed through the actual Chrome UI. Fresh source/CI regression
  evidence is distinct from those installation acceptance runs.
- **Native x86 hardware clean-install acceptance remains unverified.** Prior full
  x86_64 wizard checks used QEMU TCG emulation on ARM64; CI's environment is reported
  separately and is not a native-hardware installation acceptance claim.
- The owner completed full-feature rc1 installation and a graphical Claude Desktop
  folder-listing check before this final completion-screen correction. Its helper
  implementation is unchanged. The corrected UI and its downloaded connection were
  tested separately, without changing that existing desktop connection.
  **Graphical ChatGPT acceptance and Windows PowerShell/helper execution remain
  unverified.**
- Existing restricted mailbox access, folder permissions, a non-root Linux login,
  SSH trust/access and, for Organizer, trusted HTTPS certificate/key and DNS are
  prerequisites. The wizard does not provision provider accounts, ACLs, folders,
  certificates, DNS or firewall policy. Hosted clients need their own supported
  connection; exported stdio JSON does not connect hosted ChatGPT automatically.
- Existing installations are refused. There is no automatic upgrade, private-state
  migration, inverse move rollback, background classification or dashboard.
  Conservative customer/identity/MIME rules can retain false Keeps. Historical
  Keeps are not silently reconsidered.

## Install, recovery and release boundary

Verify the source archive checksum, then follow [SETUP_WIZARD.md](SETUP_WIZARD.md).
Incomplete initial installs use the guarded documented `--recover` procedure.
Completed installs are never removed by it; retain a disposable host/snapshot for
experimental acceptance. Existing 2.0 production installations should remain on
stable 2.0. See [UPGRADE.md](UPGRADE.md) and [SECURITY.md](SECURITY.md).

Source ZIP/tar and the Linux verification package include applicable MIT, branding
and dependency notices. Dependencies are separately downloaded, not vendored.
The verifier needs a normal Linux login, Python 3.12/venv and Internet access; it
runs synthetic/loopback checks and preserves full logs without installing a service.

After checks and owner review, merging, creating `v2.1.0rc1` and publishing a GitHub
**prerelease** require separate authorization. Preserve stable `v2.0.0`; do not
mark rc1 as a stable release or enable production authority as part of publication.

---

# Historical 2.0 application release notes

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
