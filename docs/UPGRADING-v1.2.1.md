# Preparing an upgrade to v1.2.1

No production deployment is authorized by these instructions. The candidate is
not yet tagged or published. Use a verified published archive/checksum only after
separate approval; until then, isolated testing must pin the reviewed commit.

## Before changing an installation

Record current source/launcher hashes, Python environment, service/sandbox settings,
credentials references, tunnel, existing Draft mode, approved folder and private
state locations. Preserve these settings. No new port, browser/OIDC service,
mailbox credential, SMTP credential or dependency is required by this patch.

Take a protected backup of runtime/configuration and the latest consistent draft
state (including SQLite journal/WAL through a safe snapshot mechanism). Preserve
current send/filing receipts and secret isolation if optional sender services
exist; see [v1.2 recovery guidance](UPGRADING-v1.2.md). Encrypt sensitive backups
and verify recovery into quarantine. Do not expose staging MIME or credentials.

## Separately authorized installation

Install the verified runtime files while preserving dependencies, launcher,
credentials, protected state ownership and tunnel settings. Keep Reader enabled
and preserve the existing Basic/Secure Draft opt-in. Leave
`INBOXTETHER_DRAFT_HTML_ALTERNATIVE=0` unless explicitly approved separately. Keep
Send Assistant and Sent filing disabled wherever they are currently disabled.
Restart only the approved application service, then verify service/tunnel health,
Reader behavior and existing Draft discovery without a mailbox write.

The runtime files changed by these fixes are draft_assistant.py and approval_web.py.
Keep the rest of the candidate source consistent; no database migration is needed.
The shared composer receives corrected QP transfer wrapping for plain bodies;
no SMTP authority or new sending behavior is introduced. Existing frozen MIME is
not regenerated during save. Changing HTML format/version invalidates mismatched
pending requests: resolve outstanding requests, then prepare and approve fresh
ones. Do not silently enable HTML or fall back between approval modes.

Any live validation/save needs its own exact-message authorization. Capture raw
MIME, checksum, UID/UIDVALIDITY and flags before opening a client; opening a draft
may autosave/replace it. Do not repair client changes with additional APPENDs.

## Rollback

During an approved window stop only the affected application and preserve its
newest consistent state/receipts. Restore the prior verified runtime/launcher and
configuration, leaving HTML off; retain credentials, tunnel and prior mode settings.
Restart only that application and repeat Reader/discovery checks. Do not restore
an older approval DB over newer consumed/uncertain state, downgrade a live schema,
reapprove expired requests, or replay a saved/ambiguous operation. Leave newer
HTML proposals quarantined if older code cannot interpret them; retain evidence
for operator reconciliation. Rollback must not modify mailbox messages, invoke
SMTP, remove drafts or replay approvals. It cannot undo a client rewrite or mail
already saved. Production Mailcow and unrelated services are outside this upgrade.
