# Historical terminal-approved creation prototype

`calendar_create.py` retains the original explicit-approval prototype and shared
normalization, rendering, transport and durable-store primitives. Its legacy tools
are not the production owner-connection interface. The production hook calls calendar
read registration with legacy writes disabled and uses `calendar_owner_operations.py`.
See [the current contract](CALENDAR_RADAR.md) and [deployment](deploy/calendar/README.md).

Normal conversational calendar operations do not require terminal approval. The
legacy prototype's exact confirmation/fingerprint machinery is retained for backward
source compatibility and synthetic regression tests, not as a replacement owner UI.
Do not enable both legacy and owner-connection write registration paths together.

The default EventSpec/OwnerEventSpec classification is PUBLIC and transparency OPAQUE
(Busy); explicit PRIVATE, CONFIDENTIAL and TRANSPARENT remain supported. Existing
appointments, prepared proposals and saved receipts are not migrated by this default.

Any old claim that If-None-Match: * supplies atomic create-only protection on SOGo
5.12.5 is superseded by the [failed safety gate](CALENDAR_PHASE2.md). The working
owner-connection mode uses random resource identities, preflight, serialized writes,
durable idempotency, read-back and no blind retry, with the documented residual race.
Keep legacy state separate from owner-connection state; do not reset either journal.
