# Approval, preferences and corrections

## Trust choices

Browser approval independently authenticates the enrolled local owner using a separate
password session, exact review fingerprint, expiry and CSRF protection. Signing in,
opening a review URL, preparing a batch or classifying a message does not approve it.
The browser records a decision; the separate broker executes only the approved batch.

Optional `client-session-consent` trusts an authorized MCP connection to relay the
owner's fresh decision. The backend cannot distinguish the owner's chat from another
context allowed to use that connection. This is NOT independently verifiable human
approval. Native prompts, a model saying approved, a boolean or a hash do not prove
human review. Enable only if that delegated authority is acceptable; restrict access
using the client's/transport's existing controls. Browser review remains available.
Client-relayed preference approval uses this same weaker trust boundary. Client UI
behavior and saved permission grants must be assessed separately for each client.

## Exact batch and compact bulk handoff

1. On an owner request, use `next` and source-bound `propose`. Keep customer,
   uncertain, unsupported and conflicting messages in Inbox. Bind all six proposal
   fields to the same fresh result; classification bindings last five minutes.
2. `candidates {"limit":100}` reads saved, compatible, unreserved proposals without
   reading mail or changing records. Follow its exact snapshot cursor for another
   page. Eligibility counts explain excluded/legacy records; missing preference
   bindings are excluded, never fabricated.
3. Prefer `candidates {"select_count":200}` for bulk handoff. It stores up to 200
   exact eligible messages/destinations in the existing private journal and returns
   only a compact snapshot-bound `selection_ref`, count and destination totals.
   No source reservations, mailbox reads or approval occur at selection.
4. Inspect individual messages with `candidates {"selection_ref":"REF","offset":0,
   "limit":10}`; use `next_offset` (maximum25/page). Previews are untrusted data.
   Remove explicitly named selected messages with `candidates {"selection_ref":"REF",
   "exclude_uids":[UID]}` **before preparation**. The returned new reference is the
   exact remaining subset; nothing is silently replaced. The old reference cannot
   prepare. Selection references expire after two hours or any bound state change.
5. `prepare {"selection_ref":"REF"}` freshly validates ten sources. Continue only
   acknowledged `preparing` responses using `prepare {"batch_id":"ID"}`. All
   selected sources pass current source/destination identity, content/hash, flags,
   classification and customer checks before the reference path reserves them.
   A `validating`/`blocked` state or lost acknowledgement means stop and inspect;
   never blindly repeat. Existing `prepare {"uids":[...]}` remains supported for
   1–200 exact UIDs, with ten-source chunks and early durable reservations.
6. Preparation completes as ONE exact manifest/fingerprint. Present destination
   counts, fingerprint, preference revision and deadlines, with paginated individual
   details and the existing full browser review available. A selection is not an
   approval. The final response is compact, so the assistant need not retain 200 UIDs.
7. Obtain explicit fresh owner consent for that exact completed manifest. Browser
   review authenticates the enrolled owner; opt-in client consent uses exactly
   `batch_id`, `fingerprint`, `decision:"approved"` (or `"rejected"`). Do not infer
   consent from classification, a prior yes, a rule or a generic request to organize.
8. `execute {"batch_id":"ID"}` processes up to ten messages per acknowledged chunk.
   It requires enabled execution, exact consent, current preferences and fresh
   source/destination/hash/flag/customer checks. Continue the same approved batch
   only after `paused` acknowledges verified progress. Report receipts and stop
   on any ambiguous result; claims survive interruptions and cannot be retried.

New ordinary manifests allow **24 hours to review, approve and START**. Their
execution deadline is fixed at **30 hours after preparation completes**, never
extended by approval, restart or continuation. Admission requires 90 seconds per
remaining message plus30 seconds; a started batch may continue after the review
window only within its original execution deadline. Old/corrective manifests keep
original timing. No silent renewal or new consent is manufactured.

`status` requires a real batch/preparation ID; an empty payload is invalid. With
client consent configured, `cancel` can retire an exact expired, never-attempted
batch or a blocked/unstarted preparation. New explicit preparation safely retires
expired never-attempted ordinary reservations. Claimed, uncertain, started or
completed sources remain protected. Retirement retains original manifests,
approvals, progress and receipts; a replacement always needs fresh exact approval.

Errors expose only allowlisted `error_code`, `stage`, `failed_uid` and
`preparation_id` where known, plus a fixed next action and `retry_allowed:false`.
Transport failure is not proof that no request ran: inspect saved state first.
The journal remains bounded to16 MiB, at most500 bulk preparations and64 selection
audit records. There is no automatic history pruning or compaction; capacity
exhaustion stops safely. These are on-demand workflows, with no background mail task.

## One message or remember a rule

For a classified Inbox message, `correction_context {uid}` returns fresh source-bound
context. Submit the corrected category with `propose`. This changes that classification
only and moves nothing. Cancel an unattempted batch that reserves it before changing
classification. Never infer persistent learning from a one-message correction.

`preferences {}` lists current revision, active/revoked rules, approval history and
configured protections/context. A persistent rule requires an EXACT bare sender plus
a literal subject phrase of 4–200 characters; no domain-wide guesses, wildcards, regex
or inferred supplier relationships. `prepare_preference` previews upsert/revoke at the
current revision, with immutable before/after values, fingerprint and expiry. Show
that plan and obtain separate fresh owner consent; then `decide_preference` applies it.

Edit by upserting the same rule ID at the current revision. Revoke with operation
`revoke` and `spec:null`, using the same two-step approval. Rejection, expiry, stale
revision and replay cannot apply a change. Revocation disables future matching and
retains prior revisions. Rules live in the same private journal; no database/service
or provider is added. Never edit the journal manually.

Approved rules constrain future proposals and execution revalidation. They do not
schedule classifications or authorize movement. Customer/uncertainty/identity and
configured Keep protections win. One-message corrections can override category
preferences but cannot override those protections. Baseline protections/relationships
remain administrator configuration; conversational rules cannot broaden them.

## Already filed mail

`filed_context {receipt_id,uid}` must resolve a verified receipt from this installation.
No search, Message-ID substitution or imported old receipt can authorize a correction.
`prepare_correction` uses its fresh context/fingerprint to prepare a NEW exact batch.
Inbox / Keep restores to Inbox; a protected/customer message can only be restored,
not filed elsewhere. Show and separately approve the new corrective manifest, then
execute once. Original approvals/claims/receipts remain immutable; a new durable
receipt links the correction. Browser review can approve the corrective batch.

Missing, changed or ambiguous receipt sources stop. A restored Inbox source cannot
silently enter an ordinary refiling batch. Only a later separately reviewed correction
anchored to the new verified receipt may move it again. Corrective folder ACLs must
be separately reviewed on the destination installation.
