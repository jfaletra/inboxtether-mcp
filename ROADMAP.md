# Proposed operating modes

These modes describe product direction, not a promise of delivery or compatibility. Reader Mode must remain the default; a missing configuration value must never enable writes or sending.

## Reader Mode — implemented

Fixed-account, read-only folder listing, structured mailbox search, bounded message retrieval, and explicitly selected attachment retrieval. An AI client can summarize returned text. IMAP mutation commands are denied by application code; use server-enforced read-only permissions where the platform supports them.

Mailcow is the first verified platform. Other IMAP servers require their own authentication, folder encoding, search, MIME, read-only, and recovery testing before compatibility can be claimed.

## Draft Assistant — implemented v1.1, disabled by default

Basic Mode delegates confirmation to the MCP client with explicit acknowledgment; Secure Mode uses independent trusted terminal or browser/OIDC approval. Both retain immutable threading/content, expiry, replay and exact-byte APPEND verification. No existing-message changes or SMTP authority are granted by draft tools. Browser live deployment validation remains separate. See [draft modes](docs/DRAFT-MODES.md).

## Secure Send Assistant — unreleased v1.2 implementation

The v1.2 feature branch implements separately owned SMTP authority, independent trusted terminal approval, bounded message/attachment staging, preparation/status-only MCP tools, verified TLS, durable single-attempt records and uncertain-outcome handling. Disabled by default, with no Basic Send Mode. Tests are synthetic/mock-only; no real SMTP deployment or provider compatibility has been established. See [Send Assistant](docs/SEND-ASSISTANT.md).

Browser send approval and automatic IMAP Sent-folder synchronization remain planned and unimplemented. They require separate security review, explicit send-versus-save authority, live authentication validation and delivery/copy reconciliation. Failed Sent filing must never cause SMTP resubmission. A release, deployment, credential provisioning or live send requires explicit approval.

## Other proposals

Native file delivery, additional attachment types, larger limits, and non-Mailcow platform support require independent design and testing. None should be advertised as available until verified. Branding exports have been prepared from the approved original; publication still requires owner approval.
