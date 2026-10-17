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

Use the [security policy](https://github.com/jfaletra/inboxtether-mcp/security/policy) and, when enabled, Security → Advisories → **Report a vulnerability**. Private vulnerability reporting is enabled for this Public repository, and its entry link is visible to signed-out visitors; a GitHub account is required to submit a report. If the form is absent, do not open a public issue/Discussion or upload exploit material: wait for a maintainer-provided private channel. No personal contact address is published or invented here. See docs/COMMUNITY.md for the launch procedure and synthetic-report fields.

Never include real mailbox content, secrets, private domains/IPs, or raw logs. Privately describe affected version, impact, and minimal synthetic reproduction. Responses are best effort, without a guaranteed SLA.

## Repository security limitations

The earlier private-plan limitations have been replaced by verified Public-stage controls: active main rules with all three required GitHub Actions checks and no bypass actors, native secret scanning, push protection and private vulnerability reporting. Full-history CI patterns and manual exact-SHA review remain additional detective checks, not exhaustive DLP. Reverify controls before a tag/release; see docs/PUBLIC-STAGE-VALIDATION.md and docs/RELEASE-CHECKLIST.md. No paid plan or account-wide setting was changed.

Code tests and this review are not an independent penetration test. Dependency advisory results are dated and may change. See VALIDATION.md and security/DEPENDENCY-AUDIT.md for evidence and limitations.
