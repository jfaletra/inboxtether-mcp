# Contributing

Use Python 3.12 and a virtual environment, install requirements.txt, and run `python -m unittest discover -s tests -v`. Tests must use synthetic mail and never depend on live credentials. Retain tests for denied IMAP mutation commands, UID/UIDVALIDITY identity, attachment selection and limits, and MCP stdio behavior.

Reader Mode remains the default and only implemented mode. Draft-writing and SMTP work needs a separate security design and opt-in architecture before implementation; do not loosen the existing command allowlist as a convenience. Do not claim a provider is compatible without verifying it.

Keep source, docs, and limits consistent. Use example.com addresses in fixtures. Never attach private mail, account screenshots, raw logs, API keys, passwords, tunnel IDs, or production configuration to an issue or pull request. Security reports follow SECURITY.md rather than public issue discussion.

Review dependency changes and upstream advisories before release. CI is test-only, has read-only repository permissions, and needs no secrets. Passing CI does not replace review of file handling and security boundaries.
