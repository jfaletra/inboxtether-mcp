# Owner-connection calendar operations

The public candidate supports multiple configured Mailcow/SOGo principals, exact
calendar allowlists and friendly calendar aliases. It reuses the existing private
owner MCP connection. It installs no tunnel, approval website or scheduling service.
The email implementation and its independent approval/filing rules are unchanged.

## Conversational contract

The assistant resolves missing dates, time zone, duration, calendar and any recipient
addresses. It shows the complete appointment and asks for conversational confirmation
before committing. A name is not an email address. Resolve contact/address ambiguity
with the owner and bind the confirmed literal addresses to the immutable proposal.

The server grants limited authority to the authenticated connection, not to an
independently verified human click. Receipts say `human_approval_verified: false`.
A caller authorized on that connection can technically commit without a fresh click.
Do not describe a model-generated yes or confirmation payload as proof of approval.

## Registration and account isolation

Use `existing_connection_entry.py` for the public email factory plus the protected
`calendar_read_extension.py` hook. See [deployment](deploy/calendar/README.md).
The hook is the reviewed production calendar hook; the entry point adapts it to the
public email factory without importing private production email adapters.
Ordinary `server.py` retains its existing email behavior and legacy opt-in calendar
read registration. Do not configure both calendar registration paths together.

`accounts.json` defines each account's separate credential file, calendar home,
read IDs, full-visibility assertions and aliases. Its write allowlists stay empty.
The hook constructs a separate writer view for the one account selected by
`creation.json`. Multiple accounts can be read; this pilot hook authorizes one
creation account and one invitation policy at a time. It is not a multi-writer
policy manager. Each additional account needs explicit owner/operator selection.

`contacts.json` refers to those account IDs and exact address-book read allowlists.
It cannot override credentials. Contact aliases are conversational labels; there
is no native address-book aliases configuration field.

## Standalone creation and recovery

The default event is PUBLIC and OPAQUE (Busy). Explicit PRIVATE, CONFIDENTIAL and
TRANSPARENT (Free) remain supported. Timed events require valid offset-bearing
times and an IANA time zone. All-day events use date-only values and exclusive ends.
Attendee and recurrence modifications are not ordinary creation operations.

Preparation binds exact normalized fields, account, calendar and a ten-minute
expiration to the operation ID. It persists a cryptographically random resource URL
and UID. A repeated request with different content is rejected. Commit serializes
preflight GET, durable attempt/quota accounting, PUT and read-back under one state
lock. It never intentionally reuses an occupied URL. The pilot hook enforces at most
two attempts per hour and day; receipts and limits persist across restart/rollback.

SOGo 5.12.5 failed the required wildcard If-None-Match protection. The header remains
defense in depth, not an atomic create-only guarantee. A different client can occupy
the random URL between preflight and PUT. Random identifiers and a shared lock reduce
that risk but do not eliminate it. Read-back cannot prove no intermediate overwrite
occurred. The owner must accept this residual risk before enabling any writer.

After a timeout or unclear result, reconcile the original operation and resource by
GET. Never automatically retry, allocate a replacement URL, reset the journal or
change a request ID to bypass uncertainty. A verified historical receipt and a fresh
observation are distinct. Reconciliation may update the protected local journal,
but sends no CalDAV write. Audit rows contain operation metadata, not event contents
or recipient addresses. Full proposals belong only in protected runtime state.

## Unsupported operations

Updates, rescheduling and cancellation stay disabled. The running SOGo route also
accepted a valid PUT to a missing target with a nonmatching If-Match validator.
See [the failed safety gate](CALENDAR_PHASE2.md). The experimental
`calendar_radar_extension.py` and internal update/cancel handlers are retained for
synthetic research only; they are not the production registration hook and must not
be enabled against that route. Recurrence writes, contact writes, Google coordination
and bidirectional synchronization are outside this candidate.
