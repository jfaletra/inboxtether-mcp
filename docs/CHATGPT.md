# ChatGPT and private MCP connectivity

The verified integration uses OpenAI's separately installed Secure MCP Tunnel client to reach this stdio server without exposing the mailbox service as a public MCP endpoint. InboxTether MCP does not vendor the tunnel binary or manage OpenAI credentials.

Follow the current [official Secure MCP Tunnel documentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) for account eligibility, tunnel associations, permissions, runtime credentials, and client configuration. Use the minimum required runtime permissions and keep administrative credentials separate. Do not copy another operator's tunnel profile, account IDs, key paths, or unit into your installation.

Configure the tunnel client to launch the venv Python executable and server.py with your INBOXTETHER_* environment. Keep the process supervised by your chosen service manager. Verify readiness and successful polling, then discover tools in the intended ChatGPT connection. Expected inventory: list_mailboxes, search_messages, read_message, list_attachments, retrieve_attachment. Existing connections may need their Refresh tools action after an update. Validate each client separately; one client's success does not establish every assistant's access.

Require explicit selection before retrieve_attachment. Read-only annotations may let a client call tools without additional permission prompts, so they cannot replace the human-selection flow. No SMTP or mailbox-write authority exists in this release.

The current attachment response is Base64 JSON with MIME type, filename, byte count, and SHA-256. A consumer must decode and validate it to obtain a file; a native download UI is not included. Do not automatically render it. Tool results can be subject to the connected product's normal logging and retention policies.

A public GitHub source repository is separate from public ChatGPT plugin distribution. Do not advertise a hosted service or public plugin listing unless separately implemented, reviewed, and approved. The 256 × 256 InboxTether icon is prepared as a derivative of the approved artwork, with public distribution authorized by the owner; it has not been uploaded to the live plugin.
