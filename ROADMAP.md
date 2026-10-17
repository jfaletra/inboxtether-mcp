# Proposed operating modes

These modes describe product direction, not a promise of delivery or compatibility. Reader Mode must remain the default; a missing configuration value must never enable writes or sending.

## Reader Mode — implemented

Fixed-account, read-only folder listing, structured mailbox search, bounded message retrieval, and explicitly selected attachment retrieval. An AI client can summarize returned text. IMAP mutation commands are denied by application code; use server-enforced read-only permissions where the platform supports them.

Mailcow is the first verified platform. Other IMAP servers require their own authentication, folder encoding, search, MIME, read-only, and recovery testing before compatibility can be claimed.

## Draft Assistant Mode — experimental v1.1 development, disabled by default

This branch implements preparation of plain-text threaded replies and a separate trusted local operator approval before one exact APPEND to a configured special-use Drafts folder. Reader tools and their command guard remain unchanged. No in-chat approval mechanism, attachments in drafts, arbitrary folder writes, SMTP, or automatic retries are supported.

See [the architecture and security review](docs/DRAFT-ASSISTANT.md). Synthetic IMAP/MCP tests are not live provider certification. Enabling writes, live acceptance testing, merging and releasing require separate operator approval. A future authenticated approval UI/broker would need independent design and review; native client approval prompts alone are insufficient.

## Send Assistant Mode — planned, not implemented

Optional SMTP sending only after explicit approval of the exact message, enforced server-side. No SMTP client, credentials, transport, sending endpoint, or approval service exists in this implementation.

A future design must bind a single-use, expiring approval to the exact envelope recipients (including Bcc), sender, subject, body, attachments and their hashes, and relevant delivery options. Edits must invalidate approval. Approval must come from a trusted user interaction, not a model assertion, email content, or a boolean tool argument. Reject unapproved/changed messages and replay attempts. Define retry/idempotency behavior to avoid accidental duplicate sends.

Before implementation: complete a security design, authenticated approval mechanism, secrets isolation, validation and abuse controls, explicit opt-in, and tests proving the server refuses unapproved sending. Reader Mode remains available with no SMTP credentials and no write/send authority.

## Other proposals

Native file delivery, additional attachment types, larger limits, and non-Mailcow platform support require independent design and testing. None should be advertised as available until verified. Branding exports have been prepared from the approved original; publication still requires owner approval.
