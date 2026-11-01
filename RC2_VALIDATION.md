# InboxTether v2.1.0rc2 — validation and release boundary

This experimental candidate follows the reviewed PR #12 source at
`4bda893bd10569ec3acb002c4e93967e3d74f535`. That source passed both GitHub
Actions runs, with 554 regression tests and six HTTP security tests from checkout
and again from the extracted Linux package. Those results establish the application
baseline; fresh checks on the rc2 metadata commit are required before publication.

## Release identity

`VERSION`, the current installation/release documentation and CI packaging paths
identify **2.1.0rc2**. Expected review artifacts are:

- `inboxtether-2.1.0rc2.zip`
- `inboxtether-2.1.0rc2.tar.gz`
- `inboxtether-2.1.0rc2-linux-verification.tar.gz`
- `SHA256SUMS`, covering the archives and copied release documents.

Source archives use the `inboxtether-2.1.0rc2/` prefix and contain the same VERSION
and checked source manifest as the candidate. The Linux verification bundle uses
the `inboxtether-2.1.0rc2-linux-verification/` prefix, its own matching VERSION and
checksum list, and the exact rc2 source tarball. `BUILD_INFO.json` binds the source
manifest to the checkout commit. Generated archives and private test evidence stay
outside the source repository.

Historical references to rc1 describe retained evidence or the published release;
they are not current package identifiers. The existing rc1 tag, archives and
release documentation remain unchanged on GitHub.

## Change scope and preserved behavior

Only release metadata, documentation, source checksums and CI package paths change.
The packager additionally exports this validation document. Application Python
files, wizard assets and templates, dependency pins and the discovery-completion
guides/tool description remain byte-identical to the reviewed application baseline.
Schemas, authentication, customer/uncertainty protections, manual/browser approval,
automatic policy, execution deadlines, message hashes/flags, receipts and no-retry
controls are unchanged. Automatic filing, execution and delegated chat consent
remain disabled by default; sending remains excluded.

The discovery-completion rule is preserved: after the final pending message, call
`next` again. Completion requires one response with no UID, `remaining=0` and the
"No new messages" notice. Process additional discovered messages within the owner's
scope and repeat the check. Errors or uncertainty leave completion incomplete.
Report "caught up as of the final discovery check"; there is no continuous monitor.

## Required exact-candidate validation

Run the complete regression and loopback HTTP security suites, pinned dependency
consistency/advisory audit, source/private-information checks and deterministic
packaging checks. Verify each archived file and checksum, matching rc2 identifiers,
and the self-contained Linux verification bundle in a disposable environment.
The existing CI repeats the suites from checkout and from independently extracted
source. Check the exact PR head, step exit codes, complete logs and CI-built archive
checksums against the reviewed local artifacts. Full local output and diagnostics
are retained separately; fresh hosted results are available on PR #12. This file
defines the evidence required; earlier CI does not certify a later commit.

These are synthetic and metadata checks. The earlier clean Reader-only, Reader
plus Drafts and full Organizer installations, Chrome downloads and owner-operated
Claude folder listing remain historical evidence, not repeated rc2 acceptance.
See [rc1 validation](RC1_VALIDATION.md) and [wizard evidence](FINAL_WIZARD_UX_VALIDATION.md).
Native x86 hardware clean-install acceptance, graphical ChatGPT acceptance and
Windows helper/PowerShell execution remain unverified. No existing-state upgrade,
production deployment or provider/permission provisioning is certified here.

## Publication boundary

Candidate preparation may update only the existing PR #12 branch. Do not merge,
create `v2.1.0rc2` or publish without separate owner approval of the new commit and
checksums. Preserve stable `v2.0.0`, main, and the published `v2.1.0rc1` tag/assets.
Do not access or modify production, existing connections, mailbox state or private
operational records. Any eventual rc2 release must be marked prerelease, not stable.
