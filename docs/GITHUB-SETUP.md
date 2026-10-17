# Repository-specific GitHub setup plan

Target: **jfaletra/inboxtether-mcp**. This is a plan, not evidence of any hosted configuration. No repository, remote push, release, or visibility change is authorized yet. Do not modify any other repository, organization defaults, or account-wide settings. All steps below require the relevant explicit user approval.

## Phase 1: authorized private creation

Create exactly jfaletra/inboxtether-mcp as **Private**. Do not create it Public, create a release, add a license-generated commit that conflicts with this package, or change existing repositories. Push only the reviewed clean candidate after creation/push authorization; exclude scratch files, operational evidence, and local Git internals. Verify owner/name/Private visibility in the UI/API.

## Phase 2: validate while private

1. Review hosted contents against the local manifest and scan Git history again, including author information. Choose a GitHub no-reply commit email or other explicitly approved public attribution before making the initial commit. The current candidate has no commits or author metadata.
2. Enable GitHub Actions for this repository only. Keep default workflow token permissions read-only; do not allow workflows to create/approve PRs. Use GitHub-hosted runners, not production hosts. Confirm Actions minutes/plan availability without changing billing. Fork PR workflows must not receive deployment secrets; use pull_request, never pull_request_target for untrusted tests.
3. Run `tests` and `dependency-audit` by manual dispatch and a test PR. Expected tests: 51. Both workflow action references are pinned to verified immutable release SHAs; checkout does not persist credentials. Jobs have timeouts and read-only contents permissions. No secrets, mail access, SSH, SMTP, write operations, or deployment steps exist.
4. Add required status checks for `unittest` and `pip-audit` under a repository-scoped branch rule/ruleset where the account plan supports it. Do not claim enforcement before confirming it. Keep auto-merge off until explicitly approved.
5. In repository Settings → Security and quality → Advanced Security (labels may vary), enable the dependency graph, Dependabot alerts, and Dependabot security updates where available. The committed .github/dependabot.yml schedules pip and GitHub Actions version updates weekly. Confirm configuration recognition and a generated update PR when one exists; having no outdated packages may legitimately produce no PR. Review Dependabot PRs manually.
6. Inspect all available repository security options; enable secret-scanning/push protection only where available for the account/visibility and approved scope. Do not purchase Advanced Security or assume paid dependency-review/CodeQL features are available. The prepared pip-audit workflow does not require paid dependency-review features. Record unavailable controls as such.
7. Confirm the security policy is recognized and the owner receives repository security notifications using repository-specific watch settings. Avoid unrelated account-wide changes.

## Private vulnerability reporting: public-stage gate

GitHub's documented researcher private vulnerability reporting applies to **public repositories**. A private repository's external report form cannot be fully tested by outsiders during Phase 2. Do not report this as enabled or validated merely because SECURITY.md exists. While private, keep security discussion limited to authorized private collaborators and do not put sensitive reports in public issues or Discussions.

For the later, separately approved public-release transition:

- Prepare to enable **Private vulnerability reporting** in the repository's Settings → Security and quality → Advanced Security. When Public visibility is authorized, enable it promptly as a release gate, then verify the **Report a vulnerability** button on Security → Advisories using an appropriate reporter view. If unavailable, stop the release process and obtain a private reporting channel before inviting public reports.
- Confirm only intended maintainers can access reports and the owner receives security-alert notifications. Do not submit real secrets as a test.
- The default GitHub reporting form is sufficient; there is no need to change an account-level .github repository or other existing repository.

See [GitHub's repository reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository) and [repository security settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository).

## Phase 3: separately approved public-release preparation

Obtain explicit approval before Public visibility or a GitHub release. Re-run audits/tests, verify contents/history, confirm branding permission and license scope, resolve hosted validation failures, and approve the privacy implications of public commits/author data. The owner has authorized public artwork distribution, not a general MIT grant for branding.

Enable **Discussions** for this repository when preparing the public release: Settings → General → Features → Discussions. Do not enable it on other repositories. Review categories/moderation and direct security reports to private reporting, not Discussions. Upload the prepared social preview only within approved repository scope; changing the live ChatGPT plugin icon remains a separate action. Changing visibility and creating a release are separate approvals, not automatic consequences of private validation.

## Renamed candidate gate

The only authorized future target under this brief is jfaletra/inboxtether-mcp, initially Private after explicit creation/push approval. Previous proposed names are superseded. Review docs/NAMING-REVIEW.md and the TETHER software-mark concern before any public launch; no legal clearance or reservation is claimed.
