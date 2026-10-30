# Optional owner-enabled automatic filing

New installations default to disabled. This optional mode is persistent owner
authority to file clearly classified noncustomer messages into exactly **Industry,
Marketing, Orders and Suppliers**. All Review/action-required messages, customers,
potential customers, mixed correspondence and uncertainty stay in Inbox.

The existing connected assistant supplies classifications; no model/provider or
background scheduler is installed. It must act only on an owner request. The server
cannot prove who typed a chat message: restrict the existing MCP connection to
trusted users/clients. Enabling automatic policy delegates bounded filing authority
to that connection; it is not independently authenticated per-batch human approval.
Independent browser approval and optional client-relayed exact consent remain the
manual alternative. Manual/corrective batches never inherit automatic authority.

## Inspect, activate and revoke

`organize_email` with `action:"automatic_policy", payload:{}` is read-only inspection.
It reports enabled/execution gates, four folders, policy revision/fingerprint and
authority type. MCP cannot activate or revoke the policy.

After a reviewed installation and separate bounded acceptance, the owner uses an
administrator terminal and the existing protected configuration. Example paths
match the supplied service templates; substitute your reviewed installation paths:

```sh
sudo /opt/inboxtether/.venv/bin/python /opt/inboxtether/enroll_automatic_policy.py \
  --config /etc/inboxtether-approval/organization.json --enable
```

The helper displays the exact owner/source/destination policy plan fingerprint.
The owner personally types `ENABLE-AUTOMATIC-FILING <displayed fingerprint>`.
The helper creates a protected configuration backup, writes only the policy field
atomically and generates a new random revision. It does not enable the separate
execution gate, start a service, access mail, approve a batch or move messages.
No assistant should run the helper or enter the owner's confirmation.

To revoke through the same existing mechanism:

```sh
sudo /opt/inboxtether/.venv/bin/python /opt/inboxtether/enroll_automatic_policy.py \
  --config /etc/inboxtether-approval/organization.json --disable
```

The owner types `REVOKE-AUTOMATIC-FILING <displayed fingerprint>`. Revocation sets
enabled false and writes a new revision. The running broker checks current policy
at every automatic start, continuation, message and actual MOVE boundary; no restart
is needed. Future work stops; verified receipts remain. An already transmitted MOVE
cannot be recalled. An ambiguous in-flight outcome retains its permanent no-retry
claim and needs read-only reconciliation, never an automatic retry. Re-enabling
creates a new revision and cannot authorize an older automatic manifest. Manual
execution remains governed by its separate gate and exact consent.

## Owner-requested workflow

1. Read/classify newly pending Inbox messages with fresh source-bound context and
   the documented six-field proposal contract. Record automatic Keeps directly;
   do not resubmit them. Historical Keeps remain closed.
2. Call `candidates` with `{"select_count":200,"filing_mode":"automatic"}`.
   This returns a compact snapshot-bound selection and destination totals. Inspect
   paginated details or explicitly exclude selected UIDs before preparation.
3. Prepare using that reference, continue only acknowledged preparation chunks
   and retain the final exact manifest/fingerprint. Do not submit `consent` for
   an automatic manifest.
4. With execution enabled, call execute for the exact automatic batch and continue
   only acknowledged paused chunks. The server revalidates current explicit policy,
   saved nested classification.reply.customer_risk == "clear", current eligibility,
   source/destination pins, full hashes, persistent flags and customer protections.
5. Report processed, moved, kept, Review/attention and any errors separately. Stop
   on uncertain outcomes or lost acknowledgements and inspect saved state.

Selections last two hours; completed manifests retain the 24-hour start and fixed
30-hour execution deadline. No renewal or automatic retry is performed. Review is
excluded even when it has a clear noncustomer classification. Missing, malformed,
flat legacy or uncertain risk records fail closed; missing preference bindings are
not fabricated. Sending/deleting/replying/draft saving are not organization actions.
Native UID MOVE files messages while preserving flags; InboxTether never issues an
organization STORE to change read status.

## Limits and historical false Keeps

The non-rendering extractor tolerates only the reviewed inert forms: closing br,
unmatched closing body without unwinding other elements, and compact doctypehtml.
Active content, incomplete markup, decoding errors and unsupported MIME still fail
closed. Full available text is checked for customer/mixed-thread/identity risk,
even when the assistant receives an explicitly marked representative excerpt.

Conservative customer-keyword and reply-identity rules can retain ordinary promotion
or industry articles. No sender exceptions or global customer-keyword relaxation
are included. Historical Keeps are not reconsidered merely because extraction
improves. Use explicit owner-selected historical correction, which preserves the
original decision and still cannot bypass customer, identity or omission guards.
