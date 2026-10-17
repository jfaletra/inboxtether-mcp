# OpenAI Secure MCP Tunnel setup

InboxTether is a stdio server, not a public HTTP service. Install OpenAI's tunnel client separately on the host that can reach IMAP. The tunnel transports mailbox results to the selected OpenAI product; it does not keep those results out of that product's retention policies. Public source release is separate from public ChatGPT plugin distribution.

## Prerequisites and permissions

Follow the [official Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), checked October 17, 2026. Download the client from Platform's tunnel settings or the [official latest release](https://github.com/openai/tunnel-client/releases/latest), and inspect `tunnel-client help quickstart`; CLI options and account availability may change. This documentation does not upgrade a running installation.

Choose the intended Platform organization and ChatGPT workspace. Tunnel creation/administration requires **Tunnels Read + Manage**; the runtime key and connection operator require **Tunnels Read + Use**. Keep Manage authority off the mail host. Workspace custom-MCP permissions and the tunnel's workspace association must also permit access; a Platform organization association alone is insufficient.

Provision your IMAP app password as described in [installation](INSTALLATION.md). Separately inject the runtime OpenAI key through your secret manager or a protected service environment as `CONTROL_PLANE_API_KEY`; do not put literal keys in shell arguments, tracked profiles, examples, logs, or chat. Follow organization expiry/rotation policy and monitor tunnel health. Never assume a non-expiring key is universally available.

## Example stdio profile

The following is a placeholder setup example, not a command executed or an end-to-end validation of a new tunnel. Replace the tunnel ID and paths locally. Ensure the client launches with the three `INBOXTETHER_*` variables from [configuration](INSTALLATION.md); `.env` is not loaded automatically. The tunnel process must be able to read the password file under its own unprivileged account.

```sh
tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile inboxtether-reader \
  --tunnel-id REPLACE_WITH_YOUR_TUNNEL_ID \
  --mcp-command "/opt/inboxtether-mcp/.venv/bin/python /opt/inboxtether-mcp/server.py"
tunnel-client doctor --profile inboxtether-reader --explain
tunnel-client run --profile inboxtether-reader
```

Keep the client running for discovery and calls. Use an operator-tested launcher/service manager; the supplied systemd file is only a skeleton. Permit outbound HTTPS to `api.openai.com:443` (or the official mTLS endpoint when configured) and IMAP TLS to your selected server. No inbound MCP firewall opening is needed. Keep the local admin/metrics interfaces on loopback; do not expose them publicly.

## Verification in the intended client

Confirm doctor, health/readiness and active polling. In ChatGPT Plugins, add a custom MCP server using Tunnel, select the associated tunnel, configure the product's offered authentication, review access, and discover tools. This server itself does not implement OAuth or per-user login; do not advertise those capabilities. Expected tools: `list_mailboxes`, `search_messages`, `read_message`, `list_attachments`, `retrieve_attachment`. Refresh tools on existing connections after an update. Readiness alone does not establish mailbox access: verify a bounded folder/search call in the intended client. Each client needs its own verification.

For attachment tests, first show choices and wait for explicit human selection. Identifiers and read-only annotations do not prove consent. Decode the selected Base64 payload in a trusted consumer, verify size/SHA-256, and do not automatically open or execute it. No native file-download UI is included. No SMTP or mailbox-write operation is exposed.

If discovery fails, check organization/workspace association, Read + Use authority, runtime key status, running client, and doctor output privately. Never attach unredacted profiles or logs to issues. Do not expose a public proxy as a troubleshooting shortcut.
