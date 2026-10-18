# Plain-text draft formatting and interoperability

InboxTether prepares `text/plain; charset=utf-8` replies. The tool's `body` uses
real LF newline characters; standard JSON encodes these as `\n` and blank lines as
`\n\n`. A literal backslash followed by `n` is different text and is not expanded.
Do not infer the submitted bytes from a chat's rendered Markdown preview.

Before approval, SMTP MIME serialization uses CRLF, quoted-printable encoding,
and a terminal newline. Existing hard line breaks, blank lines, signature lines,
Unicode and trailing whitespace survive decoding. CRLF input is currently rejected
by the existing control-character validator; clients should supply LF input.
No paragraphs, HTML or client-specific headers are silently added.

Quoted-printable **encoded** lines are limited to 76 characters excluding CRLF
([RFC 2045, section 6.7](https://www.rfc-editor.org/rfc/rfc2045.html#section-6.7)).
Soft wraps (`=` followed by CRLF) are removed during decoding; they are not
paragraph breaks. The draft composer explicitly uses a 76-column SMTP policy
instead of Python's 78-column default. Headers retain the original SMTP
serialization policy; header bytes and decoded body bytes remain unchanged for
identical prepared inputs, identities and timestamps.

## Review, save and client editing

The returned preview is decoded from the frozen MIME before approval. Basic Mode
binds the full confirmation object; Secure Mode retains independent approval.
The IMAP APPEND/readback receipt verifies the exact approved MIME checksum.
An email client can subsequently rewrite that draft, create another UID, convert
it to HTML, change headers, or remove the draft after sending. Such changes are
outside the original exact-byte save guarantee.

If paragraphs disappear, compare these separately using read-only access:

1. Original tool-call argument JSON, when available. Do not reconstruct it.
2. Retained preview, MIME, approval fingerprint and save receipt.
3. The original saved Drafts UID/UIDVALIDITY, if still present.
4. Client-edited draft, Sent copy and received MIME. Compare text-part checksums,
   decoded hard/blank lines, HTML break markup and Message-ID/threading headers.

Normal HTML whitespace collapses: literal newlines inside an ordinary `div` do
not preserve plain-text paragraphs. A received message can therefore contain
correct-looking source newlines yet render as one paragraph. Do not blame the
input, IMAP storage, transport or a specific client without identifying the first
observed change. If the saved UID is gone, use its verified receipt but state the
remaining evidence gap. Check a client's plain-text editing mode before proposing
an HTML workaround. Do not resend a message already delivered.

The synthetic multiline investigation found preserved approved plain-text breaks
and a later client-generated HTML alternative without paragraph-break markup.
This does not establish which client's import/edit/send path performed the
conversion. It does not certify Mailbird, SOGo, Outlook or Thunderbird UI behavior.
The 76-column standards correction is separate and cannot by itself repair a
client's HTML conversion. No HTML drafting support is added by this correction.

## Validation and deployment

Regression tests cover JSON argument roundtrips, multiple blank lines and
signatures, no/trailing newlines, CRLF serialization, rejected CRLF input,
quoted-printable limits/soft wraps, Unicode/whitespace, inert HTML-looking text,
multiple standard parser policies, and exact-byte approved mock IMAP saving.
They use synthetic content and a mock backend; they are not live-client tests.

No dependency or tool-schema change is needed. Reader, Basic/Secure Draft and
Secure Send controls remain unchanged. Deploy only after separate approval:
back up the current runtime/configuration, install the reviewed revision, preserve
existing mode settings, keep sending/filing disabled, restart only the intended
service and verify health/discovery. Do not rewrite existing staged MIME or reuse
an old approval for reserialized content. Let pending proposals expire or reject
them through their existing approval policy and obtain a fresh review if needed.
Rollback restores the prior code while retaining current receipts/state; it does
not modify, resend, or delete mailbox messages. A deployment or live save test is
not authorized by adding these tests/documentation.
