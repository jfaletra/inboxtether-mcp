# Optional HTML draft compatibility alternative

This feature is opt-in, **disabled by default**. Reader remains the default and
Draft Assistant still requires its separate master/mode opt-ins. It does not
provide SMTP, a Basic Send mode, model approval, draft attachments or arbitrary
HTML composition. It adds no dependencies or new MCP tool arguments.

```ini
INBOXTETHER_DRAFT_HTML_ALTERNATIVE=0
```

Only an operator may set this to `1`, after review and a separately authorized
isolated-mailbox compatibility test. Use the same configuration for the MCP and
independent approval broker/terminal worker. Browser approval still requires its
existing HTTPS/OIDC/session/CSRF setup; HTML does not enable that infrastructure.
No production deployment or mailbox writes are authorized by this documentation.

## Content and MIME

The model still supplies plain-text `body` with real LF characters. The existing
validation rejects CR/control injection. SMTP canonicalization converts LF to
CRLF and adds a terminal newline **before approval**, as in plain-only mode.
The decoded plain part is byte-for-byte equal to the existing canonical body,
including blank/signature lines, Unicode, tabs and trailing spaces.

When enabled, MIME contains exactly two leaves under `multipart/alternative`:
UTF-8 `text/plain` first, equivalent UTF-8 `text/html` second. Both use bounded,
76-column quoted-printable encoding and CRLF. Threading and recipient headers
remain at the message level. Total serialized MIME still cannot exceed 64 KiB;
escaping/duplication overhead can reject a body that fits plain-only mode. It is
never silently shortened or switched back to plain text.

Renderer `escaped-br-v1` escapes **all** text characters before inserting fixed
`html`, `body`, `div` and `br` tags. Each canonical line break becomes an explicit
`br`; repeated breaks retain blank-line spacing and signature lines. There are
no attributes, CSS, active links, images, remote resources, scripts or user-supplied
markup. HTML-looking input is displayed literally. A client can independently
auto-link text or apply its own rendering; InboxTether cannot control that behavior.
Ordinary HTML space/tab layout may still differ from a plain-text viewer.

Validation accepts only the generated two-leaf shape, order, UTF-8/QP encoding,
known MIME headers, boundaries and canonical renderer output. Nested multiparts,
attachments, external body locations, alternate markup, malformed encodings,
extra parts/headers and text/HTML disagreement are rejected. Reader attachment
retrieval and Secure Send attachment handling are unchanged; draft attachments
are not added by this feature.

## Approval and backwards compatibility

The private scope binds `body_format=plain-html`, renderer version and configured
destination. The preview includes canonical plain text, format/version and HTML
source. The fingerprint binds the full manifest and MIME checksum, including both
parts and the boundary. Basic confirmation must return the complete frozen preview
unchanged; it remains client-controlled and is **not** independently verified human
approval. Secure terminal/browser approval remains independent. No format fallback
exists. Replay/expiry/concurrency/uncertain-save handling and exact APPEND/readback
are unchanged. Saving uses stored bytes, never freshly rendered HTML.

Browser review displays the canonical text and **escaped HTML source**, not an
executed HTML document. No untrusted content is loaded by this preview. Terminal
review prints the complete manifest. Existing plain-text proposal previews/scopes
remain unchanged with this option off; there is no database migration. Do not
rewrite old rows. Switching the format or renderer requires fresh review and will
reject a pending proposal under mismatched configuration. Reject outstanding
proposals before changing format; retain receipts/backups through rollback.

## Mailbird compatibility test — separate approval required

Controlled operator-observed tests confirmed correct paragraphs and signature lines
in Mailcow webmail and Mailbird Next with this generated alternative. These are
bounded observations, not certification of every client version or provider.
See [the compatibility record](HTML-COMPATIBILITY-RESULTS.md). Client MIME, flags,
headers and UID rewrites remain possible even when visible formatting is correct.

1. Review code/CI and authorize installation in an isolated environment. Preserve
   production and existing settings. Enable HTML only in that isolated instance;
   keep sending/Sent filing disabled and use a dedicated test identity/mailbox.
2. Prepare uniquely labeled synthetic plain and alternative control proposals
   with the same decoded body: multiple paragraphs/blank lines, signature, Unicode,
   a long line, and literal markup characters. Capture actual tool JSON, previews,
   raw MIME, decoded-body hashes, format/version and original client versions.
   Preparation is not save approval. Tests must not use customer content.
3. Present each exact proposal for explicit approval before each one-use save.
   Retain raw read-only `BODY.PEEK[]`, UID/UIDVALIDITY, flags and checksum before
   opening a client. Keep an untouched control; use separately approved disposable
   client copies because opening a composer may autosave. Never reuse an approval.
4. Observe Mailbird Next and webmail separately, without sending or intentional
   editing. Capture screenshots plus read-only raw MIME/flags/UIDs after each
   opening; check for replacement drafts. Stop if uncertainty or unexpected writes
   exceed the authorized test scope. Never automatically retry a save.
5. Require preserved visible paragraphs/signature and equivalent decoded plain
   text; record transformations rather than masking them. Do not send or clean up
   mailbox drafts until separately authorized. A failing client test is not
   permission to alter production settings or introduce a raw-HTML workaround.

Synthetic regressions cover escaping, malformed boundaries/headers/encoding,
plain-body and rendered-text equivalence, signatures/Unicode, both-part tampering,
Basic/Secure approval, configuration/version changes, size limits, replay,
concurrent consumption, uncertain APPEND and safe browser preview. They certify
these code paths only, not real-client behavior.

## Relationship to the separate encoding fix and deployment

PR #7's 76-column quoted-printable correction is incorporated. Plain-only and
alternative bodies use the corrected transfer wrapping; decoded content and
original header folding are preserved. Existing staged plain-text proposals are
not rewritten; exact stored bytes remain authoritative. HTML remains disabled by
default and independently enabled only by the operator.

For any approved deployment, back up runtime/configuration and current staging
receipts, install a pinned reviewed revision, preserve account/tunnel/credentials
and mode settings, and restart only the authorized service. Restore previous
code/configuration on failure; disable the new option, retain newest state/receipts
and never replay or rewrite an uncertain/saved proposal during rollback. HTML
staging increases private data volume; existing restrictive permissions, encrypted
storage/backup recommendations and retention risks still apply.
