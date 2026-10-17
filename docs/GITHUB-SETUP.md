# Repository setup and public-stage gates

Target only `jfaletra/inboxtether-mcp`. It now exists as Public following explicit owner authorization. Current evidence is in PUBLIC-STAGE-VALIDATION.md; private-stage statements below are historical. Historical evidence is in PRIVATE-GITHUB-VALIDATION.md; current release gates are in RELEASE-CHECKLIST.md. No other repository or account-wide configuration is in scope.

Retain read-only workflow defaults, SHA-pinned approved actions, no workflow-created approvals, no production secrets/runners, no fork-workflow token expansion, and no cross-repository Actions access. Keep dependency graph, Dependabot alerts/security updates and weekly version monitoring enabled. Review updates rather than auto-merging; MCP 2.x is incompatible with the current FastMCP import.

Historically, the private-plan saved main rules were not enforced and native secret scanning was unavailable. After the Public transition, main rules are active/enforced and secret scanning/push protection are enabled. Candidate CI includes tests, strict dependency audits, and full-history credential-pattern scans. Keep exact-SHA manual review while these preventive controls are missing; never claim the scan prevents all leaks.

Discussions are approved for preparation under this repository only; use docs/COMMUNITY.md for categories, moderation and pinned guidance. Enabling them while private does not publish the repository. Do not create public announcements now.

After separately approved Public visibility, and before any tag/release, verify main rules are actually enforced with `unittest`, `pip-audit`, and `repository-hygiene` required from GitHub Actions, PRs, up-to-date branches, conversation resolution, blocked force pushes/deletion, and no unreviewed bypass. Enable/verify native secret scanning and push protection where available, private vulnerability reporting and reporter access, maintainer security notifications, and Discussions. Stop before release if any gate fails. Do not purchase a plan or move ownership without approval.

References: [GitHub private reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository), [repository security settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository).
