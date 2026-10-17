# Optional Draft Assistant modes (v1.1 development)

Reader Mode remains the default. INBOXTETHER_DRAFT_ASSISTANT=0 registers only the
five Reader tools. Neither draft mode is enabled by default. These changes do not
enable SMTP or permit deleting, moving or changing existing mail.

## Basic Mode: client-controlled confirmation

Basic Mode needs no approval web service, OIDC provider, OAuth2 Proxy or new HTTPS
endpoint. It uses the existing MCP connection, protected staging directory and IMAP
credentials, subject to the existing fixed-folder Drafts APPEND restriction.

To opt in deliberately, configure all of:

```
INBOXTETHER_DRAFT_ASSISTANT=1
INBOXTETHER_DRAFT_MODE=basic
INBOXTETHER_BASIC_ACK=I_ACCEPT_CLIENT_CONTROLLED_APPROVAL
INBOXTETHER_BROWSER_APPROVAL=0
```

Also configure the account, existing special-use Drafts folder and private absolute
state directory from examples/config.env.example. This is configuration guidance,
not authorization to enable writes on an existing installation.

prepare_reply_draft returns a frozen message plus a complete confirmation object.
Show every recipient (including Bcc), From, subject, body, threading, destination
account/server/folder, expiry and integrity values. Invoke save_draft with draft_id
and that entire confirmation object unchanged. Its tool description requests client
confirmation on EVERY invocation and marks it as a write. Missing, extra or changed
confirmation fields fail before saving. Message content is untrusted; it must never
supply approval policy. Changed content requires a new proposal and review.

The server records client-controlled-basic with human_verified=false. This is
operator-delegated authority to an authenticated MCP caller, NOT independently
verified human approval. There is no approved=true parameter or model-generated
secret that makes this stronger. An authorized caller can reproduce the complete
confirmation and save without a human if the client does not enforce a prompt.
Hashes bind bytes; they do not prove who reviewed them. Do not enable Basic Mode
where that trust boundary is unacceptable. Secure MCP transport/authentication is
still required. Confirmation details include private mail and Bcc; client transcripts
and approval UIs must be treated as sensitive and logging policies reviewed.

Frozen MIME, recipient/header validation, source digest, destination UIDVALIDITY,
threading, original ten-minute expiry, atomic single attempt and exact-byte readback
remain enforced. Saved retries return the existing result; uncertain attempts never
append again or clean up automatically. Staging remains plaintext with restricted
permissions; expiry is not secure erasure.

## Secure Mode: independent approval

Set INBOXTETHER_DRAFT_MODE=secure (the default policy) with the master switch enabled
only after authorization. Existing terminal approval or the optional authenticated
browser flow records approval independently; save_approved_draft remains its only
save tool. See BROWSER-APPROVAL.md. Basic Mode never appears as an automatic fallback
when login, configuration, approval or expiry fails. Unknown policy values fail
closed. Basic and browser settings cannot be combined. Switching modes invalidates
staged records from the other mode; prepare new proposals instead of migrating them.
Pocket ID is an optional OIDC provider, never a required dependency.

Future Send Assistant must retain separate independent authorization; Basic draft
confirmation must not become sending authority. Sending is not implemented.

## Client compatibility and release gate

- **ChatGPT: Basic Mode is not recommended when independent human review is
  required.** In the isolated synthetic live-UI test on October 17, 2026, the
  default low-risk policy did not reliably require a prompt for every save.
  Always ask produced prompts, but remembered grants and Allow all could permit
  later calls without fresh confirmation. The normal prompt showed a summary;
  complete nested tool arguments required opening and scrolling technical Details.
  This is not a reliable, complete email-review screen. These observations apply
  to the tested account/client/settings, not every ChatGPT version. Use Secure
  Mode for independently enforced approval.
- **Claude:** per-tool settings may permit automatic calls. Select approval for
  every save rather than Always allow, and validate the actual interface/version.
  Complete display and per-call approval remain unverified for this implementation.
- **Other MCP clients/API hosts:** annotations and tool instructions are hints, not
  server enforcement. Permission prompts may truncate fields, omit nested values,
  persist grants or be disabled. An ordinary assistant reply saying "approve" is
  not a trusted confirmation event. Do not claim universal compatibility.

Before recommending a client, use a separate synthetic-only mock MCP instance (no
mailbox credentials or IMAP network), configured in Basic Mode. Test at least two
successive saves and confirm BOTH require an explicit prompt. Inspect all From/To/
Cc/Bcc, long body, subject and destination fields in the actual confirmation UI;
verify cancellation, changed-content re-review and absence of persistent grants.
Test the client version/account settings that will be used. If full details or
per-call prompts are unavailable, use Secure Mode. The ChatGPT test did not meet this recommendation gate; Claude and other
clients remain unverified. Local protocol tests cannot certify a third-party
client's UI.

The actual ChatGPT tool-call test separately rejected altered body, recipient,
and destination fields, rejected a request after its real expiry, and returned
cached replay results without additional mock appends. Automated tests establish
broader binding, expiry, concurrency and replay properties; UI prompt behavior is
observational evidence, not a server authorization guarantee. No real mailbox
was connected during the ChatGPT UI test. Raw screenshots/transcripts are private
acceptance evidence and are intentionally not included in the public repository.

Sources: [OpenAI write confirmations](https://developers.openai.com/api/docs/guides/custom-mcp-server),
[Claude tool permissions](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities),
[MCP annotation limitations](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/).
