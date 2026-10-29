# Installation, upgrade and rollback

This refreshed 2.0.0 candidate extends the rc3 public application with bulk filing
and the neutral `organize_email` interface.
It excludes previously optional email sending. Existing clients must discover the new
contract in a separate test configuration. No existing private deployment or plugin
should be changed to try it. The public journal remains distinct from installation-specific
state; no private ledger, receipts, witness, account pins or migration tool is shipped. There is no automatic legacy state/configuration migration.

For a new installation, retain a protected source/configuration backup before future
updates. Stop the client transport, then approval web, then broker; validate the source
manifest; install only reviewed source; start broker, web, then client. Do not enable
execution as part of a source update. A service restart invalidates browser sessions;
logging in again never reapproves or extends an expired manifest.

For rollback, disable execution and client consent first. Preserve all current journals,
classifications, rules, approvals, receipts and attempt claims. Never restore an older
journal, erase a claim, retry uncertainty, or undo mail using an inverse script.
Before state initialization, an unused candidate can be removed without mailbox work.
After state exists, use only source that understands that journal schema; otherwise
leave execution disabled and retain the current native-aware source for investigation.
No downgrade/migration or live rollback is certified by synthetic source tests.

A source rollback does not reverse a saved draft or verified move. Any corrective move
requires an exact verified receipt plus new review/approval. Production deployment,
mailbox reads/writes and live acceptance each require separate authorization.

## Service/socket prerequisites carried forward from rc2

Before starting the broker, add the actual `inboxtether-web` UID as `web_uid` in
socket-access.json, matching organization.json. Retain the actual Reader/proxy UIDs.
The existing helper grants only these explicit socket peers and waits for a listening
endpoint before granting access. No shared group or general directory write is needed.

The web listener serializes startup with a private lock file in its existing runtime
directory. It preserves live endpoints and refuses unsafe paths. A verified disconnected,
service-owned socket is recovered automatically after a crash; ordinary close removes
only that listener's own endpoint. No manual socket deletion is part of restart/rollback.
The lock file may persist safely in the existing preserved runtime directory.

## Public candidate additions

Bulk preparation/execution and candidate selections add optional journal fields.
Do not copy a private runtime journal into a clean public installation. New ordinary
reviews use24-hour review/start and30-hour fixed execution deadlines; existing exact
manifests retain their original deadlines and approvals. No update renews approval.
Before upgrade, require no active execution, acknowledged paused chunk, in-flight
preparation or unresolved unexpected claim. Preserve every existing claim and receipt.
Use an offline protected diagnostic copy to establish compatibility; source rollback
must retain current state and keep execution disabled if compatibility is uncertain.
Synthetic clean-install tests do not certify legacy migration or downgrade.
