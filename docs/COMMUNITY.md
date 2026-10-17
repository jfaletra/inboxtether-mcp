# Community and security-reporting preparation

The source repository is Public following owner authorization. Discussions is enabled; no announcement or welcome post has been sent. Discussions content below is prepared for the separately approved launch; no public announcement is sent by this file.

## Discussions

Enable Discussions only for `jfaletra/inboxtether-mcp`; this can be prepared privately without changing visibility. Use Announcements (maintainer posts), Q&A (installation and Reader usage), Ideas (future work), and General. Disable unused categories rather than encouraging private-mail uploads. Verify categories, moderation, and pinned guidance before inviting the community. Settings availability is not evidence that an external reader can access a still-private repository.

Prepared welcome/pinned text:

Welcome to InboxTether MCP. Reader Mode is available first: read-only search, bounded message access, and selected attachments. Mailcow is the first verified platform. Draft Assistant and Send Assistant remain proposals. Please share minimal synthetic examples and consult CONTRIBUTING.md. Never post mailbox contents, credentials, domains/IPs from private deployments, tunnel IDs, or raw logs. Security vulnerabilities belong in GitHub private vulnerability reporting, not Discussions or public issues. If the private report button is unavailable, do not publish sensitive details; wait for the maintainer to establish a private channel.

## Private vulnerability reporting launch gate

Private vulnerability reporting is now enabled. The Security → Advisories → Report a vulnerability entry point was verified in a signed-out public view. GitHub authentication is required to submit; no test report was submitted. Maintain and reverify this setting in repository Settings → Advanced Security. Confirm maintainer access and repository security notifications, using synthetic data only. Do not invite reports until this works; if unavailable, pause release until a private channel exists. No personal contact address is invented here.

Suggested report: affected version/commit, impact, reproduction using synthetic mail, relevant environment versions, and a proposed fix if known. Exclude real secrets and mailbox contents. Acknowledgment/remediation timelines are best effort; this volunteer project has no guaranteed SLA.

Official instructions: [private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
