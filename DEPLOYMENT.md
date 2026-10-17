# Deployment and rollback

This directory is a community package prepared from a verified Mailcow implementation. The v1.0.0 Reader source release is published; this branch is unreleased v1.1 development. Existing production deployments must not be modified just because this package or branding changed.

## Fresh deployment

Use a dedicated unprivileged account and private installation/secret directories. Follow docs/INSTALLATION.md and run the tests. Select a stdio client; it must own this process's stdin/stdout. No web listener is built into this server. For private ChatGPT connectivity, configure the official tunnel client independently using docs/CHATGPT.md.

examples/inboxtether-mcp.service is a systemd skeleton for supervising an operator-configured client launcher. It is intentionally not install-and-run: create and test /opt/inboxtether-mcp/run-configured-client first. That launcher must exec your chosen MCP client/tunnel process, which launches the venv Python server. Do not run a bare stdio server as a background daemon with no client. The example's hardening/path restrictions must be checked against your chosen client and secret locations; it is not a copy of a production unit.

## Existing installation

1. Record source/dependency fingerprints and health without copying secrets into the checkout. Make an owner-only backup on the host.
2. Stage separately and run synthetic tests. The community package uses INBOXTETHER_* environment configuration and the InboxTether MCP server name. Older private installations may have fixed settings; provide the equivalent environment explicitly rather than relying on example defaults.
3. Review the exact source/configuration diff and obtain operator approval for a production change and brief restart. Do not change credentials, security policy, or Mailcow containers as part of a routine source update.
4. Restart only the approved service, allow tunnel registration/polling to settle, then verify health/readiness and a real bounded tool call. Refresh discovery in each client. Confirm five read-only tools and retained search/read behavior.
5. For live attachment testing, wait for explicit user selection and verify the exact response identifiers, Base64 encoding, decoded size, and SHA-256. An independent read-only flag comparison on an approved test message can establish before/after flag behavior. Do not send test mail or modify flags without separate authorization.
6. If verification fails, restore the previous source and configuration, restart, refresh discovery if needed, and verify restored functionality. Do not revoke keys or rotate passwords as a rollback shortcut.

## Publishing this source

Publication does not deploy a service, publish a ChatGPT plugin, or enable any write/send capability. The owner has authorized artwork distribution and selected jfaletra/inboxtether-mcp. The repository was created privately and has since been made Public with separate approval. Hosted validation must precede any separate Public-visibility approval; enable Discussions during public-release preparation. See docs/GITHUB-SETUP.md. Public source visibility is authorized; version tags, GitHub releases and production cutover remain separate approvals.

## Optional Draft Assistant deployment gate

This branch does not change any running service. Keep INBOXTETHER_DRAFT_ASSISTANT unset or 0 for Reader-only discovery and behavior. Draft opt-in, provisioning a protected state directory, any ACL change, a service restart, and live APPEND acceptance testing require separate operator authorization. Follow docs/DRAFT-ASSISTANT.md; the existing systemd skeleton does not provision writable approval storage. Review its filesystem hardening before any approved opt-in. Turning the feature off removes both Draft tools; it does not delete previously saved drafts or local staging records. Preserve/reconcile uncertain attempts privately before replacing state. Never use credential rotation or mailbox deletion as a rollback shortcut.
