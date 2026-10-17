# Dependency vulnerability audit

Audit date: October 17, 2026. Tool: **pip-audit 2.10.1**, strict mode, using PyPI's Python Packaging Advisory Database. No automatic fixes, ignored vulnerability IDs, or skipped packages.

| Scope | Packages | Known vulnerability findings |
|---|---:|---:|
| Fresh dependency resolution of `mcp==1.30.0` | 29 | 0 |
| Installed verified Linux runtime snapshot, excluding installer tools | 29 | 0 |
| Resolution of CI audit tool `pip-audit==2.10.1` | 27 | 0 |

The detailed public package/version evidence is [dependency-audit-2026-10-17.json](dependency-audit-2026-10-17.json). The runtime snapshot contains package names/versions only; no host, account, credential, mail, or private filesystem information is included. Production was not modified.

Fresh resolution was audited with transitive dependencies. The existing Linux environment was collected read-only and audited as explicit pinned versions with dependency resolution disabled; the list was checked nonempty and included the expected MCP SDK before that audit was accepted. The environment audit excludes pip/setuptools/wheel because they are installer tooling, not Reader runtime dependencies. It does not cover system packages, the external tunnel binary, or GitHub's runner image. There is no claim those components were audited.

A zero-finding result means no known advisory was returned for these versions at audit time. It does not prove absence of undisclosed vulnerabilities or malicious packages. Runtime transitive dependencies are not fully locked/hashes-pinned, so a later installation may resolve differently; CI re-audits current resolution rather than treating this snapshot as permanent clearance.

## Repeat locally

Use an isolated audit environment. Install requirements-audit.txt there, then run:

```sh
python -m pip_audit -r requirements.txt --strict --progress-spinner off
python -m pip_audit -r requirements-audit.txt --strict --progress-spinner off
```

The prepared dependency-audit workflow runs on pushes, pull requests, manual dispatch, and a weekly schedule. Vulnerabilities and collection/network failures fail the job; they are not masked with continue-on-error or ignore lists. A failure requires review before merging/releasing. Scheduled Actions run only after the workflow exists on the hosted default branch and can depend on repository/account scheduling availability.

Dependabot version-update configuration covers pip and GitHub Actions weekly. Dependabot alerts/security updates are separate repository settings, documented in docs/GITHUB-SETUP.md. SHA-pinned Actions are updated through Dependabot; pip-audit scans Python packages, not Actions source. No auto-merge, deployment credentials, or mailbox/network tests are configured.

Sources: [pip-audit documentation](https://pypi.org/project/pip-audit/), [GitHub Dependabot Actions updates](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/auto-update-actions).
