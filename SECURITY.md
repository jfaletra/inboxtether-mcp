# Security policy and boundaries

## Threat model

InboxTether MCP exposes one operator-configured mailbox to an authorized MCP client. Email, headers, filenames, and file contents may be controlled by hostile senders. The client/model must treat them as data rather than instructions. Host access and the operator environment are trusted. This stdio server does not implement user login, OAuth, mailbox-per-user isolation, or a human-approval UI. Do not expose it directly as an unauthenticated public service.

Reader Mode is the only implemented mode. There are no draft-writing or SMTP-sending capabilities. Read-only annotations are client hints; the IMAP dispatch guard enforces protocol restrictions. The password may still permit writes through another client, so application restrictions do not replace provider-side ACLs.

## Controls reviewed

- Fixed host/account; TLS verification; protected regular password file owned by the process user, exactly mode 600, no symlinks, bounded reads.
- Structured, quoted inputs; UID-based lookup; UIDVALIDITY checks; fixed fetch allowlist; EXAMINE/BODY.PEEK; no CLOSE/EXPUNGE on socket shutdown.
- Size preflight, bounded literals and cumulative wire data, bounded output and MIME traversal, one in-flight connection per process, socket timeouts.
- Attachment IDs bind message digest and attachment position. Retrieval requires folder/UID/UIDVALIDITY/ID. No wildcard or filename-only retrieval. The client must enforce explicit user selection; IDs do not prove human authorization or expire while the message remains unchanged.
- Filename/type/extension checks, basic magic bytes for allowed binary types, UTF-8/control checks for text, malformed-payload rejection. No filesystem writes, execution, archive extraction, link fetching, or automatic rendering.
- Generic error responses suppress raw authentication/parser errors. Do not turn on protocol debug logging with real credentials or mail.

## Limits and residual risks

File checks are not antivirus, content disarm, or full document/image validation. Malicious allowed files can pass. CSV may contain formulas. Base64 results travel to the MCP client and are subject to that product's logging/storage rules; this server cannot promise that a connected model provider keeps them out of its records.

Listing fetches/parses a bounded complete message internally; metadata only is returned. Retrieval fetches it again. Resource limits can reject legitimate large messages and broad searches. Socket timeouts are not an overall request deadline. Model-inferred consent is insufficient; a caller with valid identifiers can technically invoke the tool directly.

The command guard is application code, not a sandbox against a compromised host/process or a malicious dependency. Multi-process deployments have one lock per process, not a shared rate limit. The entire configured mailbox is accessible; there is no per-folder authorization layer. Do not reuse privileged mailbox or tunnel-management credentials.

## Secret handling

Use a dedicated mailbox app password and protected parent directories. Keep secrets outside the checkout and backup/export paths. Never put them in commands, issue reports, examples, screenshots, or model prompts. Keep tunnel administrative authority off the mail host; choose runtime-key expiry/rotation under your account policy and monitor connectivity. No universal non-expiring-key requirement is built into InboxTether MCP.

## Reporting a vulnerability

Private reporting setup is documented in docs/GITHUB-SETUP.md. The intended repository is jfaletra/inboxtether-mcp, initially Private only after approval. Native researcher private vulnerability reporting is documented by GitHub for public repositories, so its external form cannot be fully validated during the private stage. No personal email address is included in this prepared package. Do not open a public issue with credentials, private domains/IPs, mail, logs, or exploit material containing personal data. If the eventual repository enables GitHub private vulnerability reporting, use that channel; its availability has not yet been configured.

Code tests and the preparation review are not an independent penetration test. The dated dependency advisory report is in security/DEPENDENCY-AUDIT.md. See VALIDATION.md for evidence and outstanding checks.
