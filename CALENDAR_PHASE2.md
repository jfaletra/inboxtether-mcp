# Update and cancellation safety gate: failed

Standalone update, reschedule and cancellation handlers exist behind experimental
gates for synthetic testing. They are not enabled by the production calendar hook.
Do not enable them for the tested SOGo 5.12.5 route or infer protection from sending
a header. There is no approved update/cancel live rollout in this release candidate.

Two separate owner-reported disposable tests established the limitation:

1. A collision challenge replaced an existing event despite If-None-Match: *.
   The earlier create-only safety gate remains failed permanently for that test.
2. A new random URL first returned 404. One valid standalone PUT with a deliberately
   nonmatching If-Match header returned 201, and GET returned the created resource.
   The required 412 and continued absence did not occur.

These are observed provider compatibility failures, not synthetic test successes.
Keep original journals, one-shot markers, stored fixtures and raw evidence private
and unchanged. This repository records sanitized findings only, with no resource
URLs, operation IDs, real payloads or account identities.

GET-before-PUT, locks and random names do not provide atomic update or delete
protection against other clients. No further protocol experiment, alternate calendar
server or approval service is part of this candidate. Existing creation uses the
separately accepted residual-risk contract in [CALENDAR_RADAR.md](CALENDAR_RADAR.md).
Recurring-event modifications and attendee updates/cancellation notices remain out
of scope. Existing recurrence reading is preserved.
