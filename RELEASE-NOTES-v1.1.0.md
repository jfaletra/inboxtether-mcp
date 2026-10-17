# InboxTether MCP v1.1.0 — optional Draft Assistant

Prepared release notes; v1.1.0 is not yet merged, tagged, published or deployed.

## Changes

- Reader remains the default with the same five tools and input/output schemas.
- Optional Basic Mode stages immutable threaded plain-text replies and saves them
  through client-controlled confirmation, with explicit operator acknowledgment.
- Optional Secure Mode independently approves each exact draft through a trusted
  terminal or separately authenticated OIDC browser portal. Generic OIDC is
  supported; Pocket ID is optional. Terminal use needs no identity provider.
- Recipient/content validation, a fixed existing special-use Drafts folder,
  UIDVALIDITY binding, ten-minute expiry, durable one-use approval, and exact-byte
  readback protect each save. Ambiguous saves are not automatically retried.
- Authenticated IMAP capabilities are refreshed after LOGIN on Reader and guarded
  draft connections; servers advertising UIDPLUS only after login are supported.

No SMTP, send operation, deletion, movement, or modification of existing messages
is provided. New drafts are the only optional mailbox writes. Draft attachments,
HTML composition, arbitrary new-message composition and Send Assistant are absent.
Both draft modes and the browser service remain disabled by default.

## Evidence and limits

128 synthetic tests cover Reader compatibility, Basic/Secure separation, independent
approval, browser sessions/CSRF, immutable content, expiry, replay, exact APPEND and
uncertain results. A controlled live Mailcow test saved one synthetic terminal-
approved Secure draft and verified its bytes, threading, destination and checksum;
the original content and flags were unchanged. This is not blanket provider or
browser deployment certification. A post-auth capability refresh workaround used
in that test was incorporated into the candidate and verified by regression tests.

Actual ChatGPT mock-backend UI tests found that native approval can be remembered
or disabled and normal prompts do not provide a complete email-review interface.
Basic is not independently verified human approval. Use Secure Mode when this is
required. Claude/other client approval interfaces remain unverified.

Staging is plaintext in a restricted directory; backups/journals can retain mail.
Trusted-host/operator compromise and stolen authenticated browser sessions remain
risks. Secure Mode must not share approval authority, state or credentials with
model-controlled shell/filesystem tools. A TTY alone is not proof of a human.

## Install or upgrade

Follow [installation](docs/INSTALLATION.md) and [v1.1 upgrade/rollback instructions](docs/UPGRADING-v1.1.md).
Reader upgrades need no draft opt-in. Browser deployments require separate HTTPS,
OIDC and identity-isolation acceptance testing. No PyPI publication is included.

Release gate: successful exact-final-commit tests, all dependency audits, full-history
hygiene, GitHub control verification, and separate owner merge/release authorization.
Naming uncertainty remains accepted by the owner; no trademark clearance is claimed.
