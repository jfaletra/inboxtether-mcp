# InboxTether v2.1.0rc1 — experimental prerelease candidate

## Post-rc1 discovery-completion documentation correction

The 2.1 development branch now tells assistants to call `next` again after the
final pending message. Completion requires the same response to have no UID,
`remaining=0` and the "No new messages" notice. A zero count alongside a message
or automatic Keep is not fresh discovery. Newly discovered messages are processed
normally, within the owner's scope, before repeating the check. Errors or uncertain
outcomes mean incomplete status, never an automatic retry. Report "caught up as of
the final discovery check"; InboxTether processes mail on request, not continuously.

The procedure and generic "Handle my email" prompt are in
[WORKFLOWS.md](WORKFLOWS.md#owner-requested-discovery-and-completion), with matching
automatic-filing guidance and MCP tool-description wording. Executable discovery
logic, schemas, authorization, customer protections, filing policies and Reader/Draft
behavior are unchanged. Local packaged Linux validation passed 554 regression and
six HTTP security tests, source/package checks and the 56-record dependency audit.
Fresh CI on the follow-up PR commit remains required; see [validation](RC1_VALIDATION.md).

The published `v2.1.0rc1` tag, commit and release assets remain immutable. This
branch follow-up is not a replacement rc1 release or a stable 2.1 publication.

## Retained rc1 implementation and evidence

Final wizard UX review correction: configure first, install and verify, then
reveal **Next Step: Download Your AI Connector**. Downloads use the validated
connection snapshot from the completed installation. Desktop connection success
is explicitly separate. Setup-link recovery and password re-entry instructions
are clarified without weakening security. Those UX corrections were included in
the published experimental rc1 at `c409a05ca30b26602b6babb5e99b3817682cd01f`.

PR review continues against stable `v2.0.0`. This is an initial-installation
experiment, not a production upgrade. Stable 2.0 remains unchanged.

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

After fresh checks and owner review, merging or publishing a later candidate
requires separate authorization. Do not move the published `v2.1.0rc1` tag or
replace its assets. Preserve stable `v2.0.0`; do not mark rc1 as a stable release
or enable production authority as part of publication.

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
