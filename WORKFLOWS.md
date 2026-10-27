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

## Exact batch

1. On an owner request, use `next` and source-bound `propose`. Keep customers, uncertain,
   unsupported and conflicting classifications in Inbox. Copy request bindings exactly.
2. `prepare {uids:[...]}` freezes 1–10 eligible messages. Show every source, destination,
   preview/reason, fingerprint, preference revision and expiration. No move occurs.
3. Obtain an explicit new decision for that exact manifest, either at its browser URL
   or, with client consent opted in, in conversation. Relay `consent` with the returned
   batch ID/fingerprint and approved/rejected decision. Never reuse a prior yes.
4. `execute {batch_id:...}` succeeds only with execution enabled and an unexpired,
   exact approval, unchanged content/flags/folder identity and current preference
   revision. A changed destination or policy requires a new review. Report durable
   receipts and stop on any uncertain result. Do not retry an uncertain move.

`status` inspects one batch. With client consent enabled, `cancel` rejects an exact
unattempted review while retaining its history. Claimed/completed/uncertain attempts
cannot be cancelled into a retry. Existing expired unclaimed batches need fresh review.

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
