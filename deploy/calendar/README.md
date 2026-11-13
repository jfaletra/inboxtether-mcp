# Add calendars to an existing owner connection

This is a source/runbook candidate, not an installer or deployment authorization.
Use the installation's existing authenticated owner MCP transport, service identity
and virtual environment. Do not create another tunnel, service or approval system.
No live credentials, hostnames, private policies or journals are supplied here.

## Source and integration boundary

`calendar_read_extension.py` is the account-neutral production calendar registration
hook. `existing_connection_entry.py` is its small public-factory adapter. The private
production launcher and email adapters were not imported. The public organization
tool retains its generic `organize_email` name. Existing private integrations should
add `calendar_read_extension.register(app)` to their already authenticated app
factory without replacing their email backend or changing its approval policies.

The hook expects root-controlled JSON under `/etc/inboxtether-calendar-radar/`:
accounts.json, creation.json, invitations.json and, when contacts are wanted,
contacts.json. Use the sanitized files in `examples/calendar/` as schema examples,
not as production policy. They contain invented reserved-domain identities and no
credential material. Never put edited private copies back into the checkout.

The read account records retain empty write permissions. The hook injects a writer
view for only the creation policy's selected account and calendar paths. Creation
and invitations default off in the examples. Update and cancellation are forced off
by this hook; do not replace it with the experimental calendar_radar_extension hook.

## Reviewed installation sequence

1. Export the approved commit into new administrator-owned staging. Verify every
   entry in MANIFEST.sha256 before running code. Install only required calendar
   dependencies into the existing reviewed environment using constraints-validated.txt
   and requirements-calendar.txt; run pip check. CardDAV needs no additional package.
2. Back up the existing launcher/hook/module bytes, their hashes and protected
   configuration separately. Snapshot the existing email tool definitions through
   its current no-network/no-write registration inspector. Never invoke email or
   calendar tools as a registration check. Keep the current email source intact.
3. Copy the calendar modules and hook into administrator-owned, service-readable
   source (directories 0755; files 0644; not writable by the service account).
   Add the public entry point only for a public-factory installation. For an
   existing private factory, preserve that factory and register the hook on its app.
4. In a separately reviewed operator step, install private JSON as root-owned 0644
   files in a root-owned directory, with no group/other write permission on any
   ancestor. Use dedicated app credentials in service-owned 0600 files and private
   0700 secret directories. Create a service-owned 0700 durable calendar state
   directory. Add only that directory to an existing service's writable paths if
   its sandbox requires it; preserve all existing restrictions and writable paths.
5. Discover only account principals and collection metadata first. Select exact
   calendar and address-book paths; do not grant all collections or reuse another
   account's credential. Full-visibility assertions require actual owner permission.
   Keep creation/invitations disabled while accepting read tools. Do not configure
   legacy calendar environment registration and the protected hook simultaneously.
6. Re-run guarded registration and compare the original email definitions exactly.
   With the existing eight public email tools, five calendar reads, three enabled
   creation/reconciliation tools and two contact reads, the inventory is 18. With
   creation disabled, prepare/commit are absent while reconciliation remains: 16.
   Default Reader-only installations have fewer opt-ins; do not fake an 18-tool check.
7. After separate deployment approval, restart only the existing MCP service once,
   verify it is active, and repeat the same guarded inventory comparison. Through
   the existing connection, accept calendar and address-book discovery before any
   event or contact read. A harmless approved email read can separately confirm the
   connection; do not trigger filing, create appointments or send invitations.

The public adapter supports isolated Python after installation in trusted source:

```sh
python -I -B existing_connection_entry.py
```

It explicitly imports adjacent modules from its own installed source directory;
it does not rely on the working directory or PYTHONPATH. Do not run it from a
service-writable upload directory. Test the actual installation's launch command
and service sandbox before restart. No live upgrade or data migration of this
public candidate has been certified.

## Module replacement and rollback pattern

Reuse the installation's reviewed hash-pinned, one-file replacement procedure.
Stage a root-owned copy, verify the reviewed new/old SHA256 values, back up the old
module with mode 0600, install to a temporary file in the target directory with
root:root 0644, and rename atomically. Compare the full tool catalog and hashes of
unrelated source/policies before the one approved restart and afterward. Stop if
anything differs unexpectedly; preserve the backup rather than deleting it to rerun.
This applies to the read-only hook, creation/invitation modules and CardDAV fixes.
Do not copy historical deployment bundles over newer email or calendar code.

For a fast writer rollback, atomically set only the protected creation policy's
enabled value to false and restart the existing service after approval. Prepare/commit
disappear; reconciliation remains. To disable invitations alone, set only their
policy's enabled value false; ordinary event creation stays available. For a source
rollback, restore only the reviewed module/hook version, then check inventory again.
Keep every state database, attempt claim, quota, proposal, receipt and audit record.
Do not delete events, reset a journal, remove one-shot markers or retry uncertain writes.

Invitation acceptance requires a separately approved disposable appointment and
controlled recipient, followed by independent recipient inspection. Verified event
storage is not verified mail delivery. The known SOGo conditional-write race remains
an explicit owner risk decision; update/cancel safety gates remain failed.
