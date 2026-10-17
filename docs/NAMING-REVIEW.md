# InboxTether naming review

Date checked: October 17, 2026. Proposed identity: **InboxTether MCP**. Proposed repository: **jfaletra/inboxtether-mcp**. Tagline: **Your email. Your AI. Your control.**

This is an availability/conflict screen, not legal clearance, a trademark opinion, a reservation, or a guarantee a registry will accept the name. A private repository may be invisible to an unauthenticated lookup; packages may be reserved or subject to registry policy despite a 404. Recheck immediately before any authorized creation/publication.

## Repository and package checks

| Source | Search | Observed result |
|---|---|---|
| GitHub public repository search | inboxtether | HTTP 200; zero results |
| Proposed GitHub repository API | jfaletra/inboxtether-mcp | HTTP 404 in unauthenticated lookup; no publicly accessible repository observed |
| PyPI JSON API | inboxtether; inboxtether-mcp | Both HTTP 404; neither name listed by the public endpoint |
| npm registry | inboxtether; inboxtether-mcp | Both HTTP 404; neither exact package listed |
| Docker Hub search | inboxtether | HTTP 200; zero results |
| Official MCP Registry web search | inboxtether | Completed search displayed “No servers found” |
| General indexed web search | “InboxTether”; “InboxTether MCP” | No indexed exact-name results returned |

Sources: [GitHub search](https://github.com/search?q=inboxtether&type=repositories), [PyPI API](https://pypi.org/pypi/inboxtether/json), [PyPI MCP-name API](https://pypi.org/pypi/inboxtether-mcp/json), [npm API](https://registry.npmjs.org/inboxtether), [npm MCP-name API](https://registry.npmjs.org/inboxtether-mcp), [Docker Hub search](https://hub.docker.com/search?q=inboxtether), [official MCP Registry](https://registry.modelcontextprotocol.io/?q=inboxtether).

The MCP Registry direct API timed out twice. The official registry web interface subsequently completed the search successfully; the result above is the observed web result, not a claimed successful API response. No names, packages, registry entries, or domains were registered.

## USPTO records

The official [USPTO Trademark Search](https://tmsearch.uspto.gov/) was searched in its live browser interface. A one-word Wordmark search for InboxTether returned “No results found.” To avoid multiword quick-search semantics, the authoritative follow-up used **Field tag and Search builder** with:

```text
CM:/.*inboxtether.*/ OR CM:"inbox tether"
```

It completed with **No results found**. The substring alternative includes compound marks such as InboxTether MCP; the second alternative checks the spaced phrase. No class or live-only restriction was added. This is a compound/phrase screen, not an exhaustive phonetic, translated, design-mark, common-law, state, or international search.

### Potentially relevant broader-name records

A broader quick search for Inbox/Tether components returned existing marks. Two visible, live registered **TETHER** records are particularly relevant to software naming:

- Serial **97056353**, With Tether Inc.: Class 009, downloadable computer/mobile application software.
- Serial **97056355**, With Tether Inc.: Class 042, online non-downloadable software.

Additional live/pending TETHER records appeared in software/communications classes, including serials 99480009 (009), 99480006 (038), and 99480014 (042). These are component-word matches, not identified InboxTether registrations. Their presence does not by itself establish infringement or a blocking conflict, but an exact-name zero result must not be presented as clearance.

Public record lookup: [USPTO TSDR](https://tsdr.uspto.gov/) using the listed serial numbers. Search syntax reference: [USPTO search help](https://tmsearch.uspto.gov/?page=help).

## Release decision

No exact repository/package/compound-wordmark collision was observed in the checked sources. **TETHER software marks are an unresolved naming risk for public release.** The owner should decide whether to obtain an independent trademark assessment before public launch; this preparation makes no legal-clearance claim. The tagline and new shield artwork have not received an independent trademark/design clearance search.

Private repository preparation remains conditional on explicit approval. Do not create the repository, reserve names, push, change visibility, publish a package, or issue a release based on this report alone. Public visibility remains a separate later approval after hosted CI/security validation and consideration of this naming risk.
