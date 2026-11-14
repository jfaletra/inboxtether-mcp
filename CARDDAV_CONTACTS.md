# Read-only CardDAV lookup

`contacts_list_address_books` discovers only explicitly allowlisted books for one
configured account. `contacts_search` takes that account ID, selected book IDs,
name, exact/partial mode and a result limit. It returns names and all usable stored
email addresses. It never guesses an email, silently selects a preferred address,
changes a contact or authorizes an invitation.

Accounts reuse their distinct configured DAV credentials. Book configuration cannot
override the account, host or credential. Foreign principals, accounts, origins,
paths, redirects and unallowlisted books fail closed. Only PROPFIND on the account
home and addressbook-query REPORT on its allowlisted books are permitted. No contact
creation, update, deletion, sharing change or contact export tool is exposed.

## SOGo name compatibility and complete scans

The controlled SOGo endpoint omitted FN and empty trailing N components. The parser
accepts one to five structured N components and derives a display name from the
stored given/family fields if FN is absent. It supports UTF-8 vCard 3.0 and 4.0,
folding and the reviewed text escapes. Unsupported encodings, ambiguous fields,
malformed cards and invalid addresses never produce guessed recipients.

The observed FN/N server filter searched surnames only. Therefore every search
retrieves the bounded selected book without a name filter and performs normalized,
case-insensitive exact/partial matching locally across FN and structured N variants.
There is no pagination or cache. Exact matching does not treat a prefix as equality.

The per-book scan ceiling is 2,000 resources; the query requests 2,001 to detect
overflow. Responses remain limited to 2 MiB, cards to 64 KiB, request timeouts to
15 seconds and selected books to ten. Only name/email/type/version fields are
requested, excluding notes, photos and phone fields. The aggregate matching-contact
ceiling remains 100; callers may display 1–50 results. A displayed subset reports
`complete: false` and `truncated: true` and cannot establish a unique recipient.

An over-limit, malformed, incomplete or server-truncated scan is an explicit error,
not zero matches or a partial success. DAV 507/error markers and invalid multistatus
root children are rejected. Even a malformed card after an apparent match fails the
whole lookup. A narrower name cannot bypass the full-book size ceiling. If the real
projected book exceeds the byte budget, report the failure before adding batching.

Multiple matching contacts, multiple/invalid/missing addresses and groups require
clarification. Every selected recipient still requires owner confirmation and the
separate calendar invitation policy. Contact text is untrusted content.

The 39 focused CardDAV regressions cover these rules, including matches at positions
101, 500 and 2,000 and overflow at 2,001. Large real address-book compatibility remains
unverified for this public candidate. See [validation](VALIDATION.md).
