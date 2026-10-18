# InboxTether MCP v1.2.1 — draft formatting maintenance

Release candidate materials only: no v1.2.1 tag, release or production upgrade is
authorized by this file. Final publication requires explicit owner approval and
successful checks on the exact release commit.

- Correct quoted-printable body wrapping to the RFC 2045 76-column limit while
  preserving decoded message content and existing header-folding behavior.
- Add operator-only `INBOXTETHER_DRAFT_HTML_ALTERNATIVE=1` for Draft Assistant;
  default is `0`. It generates plain-first/HTML-second multipart alternatives,
  safely escaping input and using fixed markup to preserve paragraph/signature
  breaks. No arbitrary HTML, scripts, images, links, styling or remote resources.
- Bind format, renderer version and full frozen MIME to approval; reject malformed
  structures/tampering and preserve expiry, replay, concurrency and exact readback.
- Existing plain-only previews/proposals remain supported with the option off.
  A format change requires fresh review; never rewrite a staged proposal.
- Reader remains the default. Basic/Secure Draft, Secure-only Send and optional
  Sent filing retain their opt-ins and security limits. This does not enable any
  writes or sending. The new HTML feature applies to drafts only.

Controlled synthetic tests showed correct formatting in Mailcow webmail and
Mailbird Next. Webmail preserved raw MIME. Mailbird replaced the UID/MIME, retained
exact decoded plain text and equivalent HTML, but changed flags and some headers.
See [observations and limits](docs/HTML-COMPATIBILITY-RESULTS.md); specific client
versions were not recorded. InboxTether does not prevent or repair client rewrites.

Combined suite: 247 discovered local tests, 245 passed and two privileged Linux
cases skipped on macOS; hosted Linux isolation is required before merge/release.
Dependency audits, installed dependency consistency and full-history hygiene must
pass again on the final release candidate. Pattern-based hygiene is not exhaustive
secret detection. No new dependencies or authentication infrastructure are added.

See [upgrade and rollback](docs/UPGRADING-v1.2.1.md). Production configuration,
credentials, tunnel, Radar, SMTP/Sent settings and mailbox messages are untouched
by release preparation. Publication and deployment remain separate approvals.
