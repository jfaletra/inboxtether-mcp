# Invitations for newly created standalone events

Invitations reuse `calendar_prepare_create` and `calendar_commit_create`. No new MCP
or SMTP sending tool is added. Email sending remains absent from the email module;
calendar invitations are sent by SOGo's scheduling subsystem when configured.

The `event.attendees` array contains explicit plain email addresses. The organizer
is pinned to the configured calendar account, never supplied as an arbitrary event
field. Reject duplicate/unsupported addresses, the organizer as attendee, excessive
recipients and addresses outside the separate invitation policy. CardDAV lookup
does not grant invitation authority. Confirm every resolved address conversationally.

The root-controlled invitation policy selects a subset of the creation account's
calendars, explicit recipient allowlists and a per-event limit. The public template
has invitations disabled. The creation tool schema supports attendees without a new
tool. Update, cancellation, attendee updates and recurrence writes remain disabled.

## SOGo scheduling and evidence

A stored ATTENDEE or successful PUT alone is not evidence of invitation delivery.
The implementation uses normal CalDAV event creation, a pinned ORGANIZER,
SCHEDULE-AGENT=SERVER, SEQUENCE=0 and attendees with individual/required-participant,
RSVP and NEEDS-ACTION parameters. It does not write METHOD on the stored calendar.
The supported X-SOGo NoGroupsDecomposition header avoids SOGo group expansion;
SMTP aliases and forwarding remain server-controlled. There is no second outbox
POST, email-tool fallback or resend path.

Owner-reported controlled live acceptance on Mailcow/SOGo 5.12.5 verified a stored
event and independently received invitation with matching event identity, organizer
and appointment fields. That evidence concerns a separate disposable deployment,
not live certification of this sanitized public candidate. Different account/domain
notification settings and server versions need their own controlled acceptance.

SOGo can send notices before saving the organizer resource. Even a failed or timed-out
PUT may have sent mail. Never assume an absent event permits an invitation retry.
The durable invitation fingerprint blocks a fresh request ID for the same normalized
appointment/recipient set. Preserve that reservation and the original operation ID.
No fuzzy duplicate detection for deliberately changed fields is claimed.

Receipts distinguish event creation from scheduling and delivery:

```json
{"event_creation":"verified","invitations":{"recipient_count":1,"dispatch":"unknown","email_delivery":"unverified","resend_allowed":false}}
```

Before any attempt, dispatch is `not_attempted`; afterward it remains `unknown`.
Read-back verifies event/organizer/recipient fields, not SMTP dispatch or delivery.
Owner-observed delivery is separate evidence and does not become a model-supplied
server delivery receipt. Replay and reconciliation send no second invitation.

See [SOGo scheduling source](https://github.com/Alinto/sogo/blob/SOGo-5.12.5/SoObjects/Appointments/SOGoAppointmentObject.m),
[CalDAV scheduling](https://www.rfc-editor.org/rfc/rfc6638.html), and the
[creation/recovery contract](CALENDAR_RADAR.md).
