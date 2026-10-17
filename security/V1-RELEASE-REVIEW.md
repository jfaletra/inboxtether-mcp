# v1.0.0 Reader Mode final preparation review

Date: October 17, 2026. Scope: source, tests, CI, docs/examples, branding, reviewed private-main history and release candidate. This is a maintainer preparation review, not an independent penetration test or legal opinion.

## Application boundary

The application file is unchanged from the reviewed private main baseline. Five Reader tools only. ReadOnlyIMAP denies nonallowlisted commands at protocol dispatch, including sends, deletes, moves/copies, stores/flags, APPEND, mailbox administration and UID mutation forms. Only read fetch forms are allowed; EXAMINE and BODY.PEEK preserve protocol read-only behavior. Socket shutdown does not CLOSE/EXPUNGE. No SMTP client or sending/draft endpoint exists. Tests include real imaplib framing over socket pairs and MCP tool discovery. These are controls for this application, not a security boundary against a compromised host/dependency or against another app using the same credential.

## Repository controls and compensations

Native secret scanning/push protection is unavailable for this private personal repository, and the saved main ruleset is not enforced under the current plan. Added CI checks scan tracked files and every locally fetched Git blob/commit/tag object with full-history checkout, reject shallow history, and redact matched values. The patterns cover common credentials/private keys, credential-bearing URLs, private IPv4, personal filesystem paths and nonexample text email addresses; they are not exhaustive and cannot detect arbitrary secrets or image-hidden data. Image metadata requires separate review. The original/AI image provenance contains public CA certificate metadata; compressed binary bytes also produced false email matches. No private user contact detail was identified there. These findings were investigated rather than called a leaked credential.

Separate local checks cover known private deployment identifiers, working/index equality, all local objects, JSON/doc links, original art preservation and icon limits. The prior private upload was hash-verified against its sanitized manifest and contains no inherited production history. Hosted checks must cover the candidate's complete fetched history before approval. GitHub no-reply attribution and absence of unexpected histories/refs must be rechecked before Public visibility. No assertion of absolute secret/PII absence is made.

Workflows remain read-only, SHA-pinned, without production secrets, deployment, SSH, pull_request_target or automatic dependency merging. Manual exact-SHA review is required because an owner can bypass missing branch enforcement. Preserve the tested SDK pin; the open major-version upgrade has failed compatibility tests and is excluded from this release.

## Results and residual risks

55 local tests and dependency consistency passed. Fresh strict runtime/auditor advisory checks passed without findings/skips; hosted candidate evidence is in the final report/PR. No private mail was read for this review and no live deployment was changed. Existing limits/risks remain: full fixed-mailbox exposure to an authorized client, client-enforced human attachment consent, credential write authority outside this app, non-antivirus file checks, product-side result retention, per-socket rather than global deadlines, and unverified non-Mailcow providers. See SECURITY.md.

README/authentication/installation and the official tunnel setup guide were reconciled; no live account profile/key is included. Reader is the default and only mode; Draft/Send remain future proposals. Source/docs retain MIT; artwork remains outside MIT with owner-authorized distribution. Naming concerns remain unresolved (docs/NAMING-REVIEW.md).

## Publication gate

Technically eligible for owner review once exact-head hosted tests/audits/hygiene pass. Public launch remains NO-GO until explicit visibility/tag/release approval, an explicit naming-risk decision, and Public-stage verification of enforced branch checks, native secret protection where available, private vulnerability reporting, Discussions/moderation and notifications. No paid-plan change or public tag/release is performed by this preparation.
