# Controlled HTML draft compatibility results

Observed on 2026-10-18 using PR #8 at `8cd6a8b`, based on the PR #7 encoding fix.
All content was synthetic. No email was sent by InboxTether during these tests.
Mailcow is the verified email platform. Client versions were not recorded, so
these results must not be generalized to every Mailbird or webmail release.
Private mailbox identities, credentials, message IDs and raw MIME are excluded.

## Mailcow webmail

The operator opened an approved HTML-enabled draft and reported correct paragraph
spacing and signature lines. Read-only inspection found the same UID and folder
UIDVALIDITY, identical 1,413-byte MIME and checksum, and no replacement carrying
the same Message-ID. Plain text and HTML remained unchanged. Current flags were
Seen and Draft; original draft flags were not captured for this first test, so
before/after flag equality cannot be claimed.

## Mailbird Next

The operator opened a separate approved HTML-enabled draft without intentional
editing or sending and reported correct paragraphs, blank lines and signature.
Read-only inspection showed a replacement UID with the same Message-ID. The
original 1,402-byte message was replaced by a 1,412-byte message with a different
whole-message checksum. Folder UIDVALIDITY was unchanged.

Decoded plain text was byte-for-byte identical, including four blank paragraph
separators and signature lines. HTML retained equivalent text and explicit br
markup; it removed outer html/body wrappers and normalized escaped apostrophes.
The resulting body used div/br tags without attributes or remote resources.

The client changed flags from Draft/Recent to Seen, added a display name to From,
removed References, and retained Message-ID and In-Reply-To. These are observed
client-side rewrites after opening, not transformations performed by InboxTether.
The removed Draft flag and References may affect other clients or longer threads;
InboxTether does not repair flags, reappend, restore headers or resend messages.

## Interpretation and security boundary

The optional alternative addresses the tested paragraph-rendering problem. It
cannot prevent a client from autosaving, replacing UIDs, altering MIME/headers or
changing flags. InboxTether verifies the exact approved bytes immediately after
APPEND; its checksum guarantee does not cover later third-party edits. A changed
checksum after opening is not by itself an InboxTether integrity failure.

HTML stays disabled by default. It is derived from escaped plain text, never
accepted from the model as raw markup. The format/version/full MIME remain bound
to approval. Basic Draft still depends on client confirmation; Secure Draft uses
independent approval. Reader and Secure Send controls remain unchanged.

No broad interoperability claim, sending test, client-autosave prevention or
long-thread preservation guarantee is made. Additional client versions and HTML
space/tab layout remain future test cases. Temporary test credentials must be
revoked after use and their live local copies removed; deletion cannot guarantee
forensic erasure from SSD snapshots/backups, so revocation is essential.
