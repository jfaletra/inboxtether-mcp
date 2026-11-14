# Calendar approval history and current boundary

The current mode delegates limited creation authority to the private owner connection.
The assistant asks for conversational approval; the server does not independently
verify that an owner clicked or typed approval. See [the current contract](CALENDAR_RADAR.md).
This does not change email draft, filing or independent email approval behavior.

Historical harmless-probe acceptance showed native per-tool prompts in an ordinary
ChatGPT conversation: denial did not invoke commit and two distinct approvals each
produced one synthetic receipt under a continuous process identity. The same probe
on the tested Radar/Dot surface invoked commit without an owner-visible prompt despite
the configured confirmation preference. No real mail or calendar was involved.

No documented server-verifiable native approval receipt was established. MCP form
elicitation/tunnel feasibility experiments did not become the production authorization
mechanism. Their temporary endpoints, private IDs, credentials and raw evidence are
not part of this public source. Do not claim a correlated response proves a human click.

The owner later accepted conversational delegation with exact proposals, calendar
and recipient allowlists, expiry, quotas, idempotency and verification. This candidate
adds no approval website, custom card, callback, tunnel or terminal approval step for
normal owner-connection calendar operations. An authorized connection can technically
commit without fresh conversational confirmation; that is an explicit trust tradeoff.
