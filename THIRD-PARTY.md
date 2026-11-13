# Licenses and third-party dependencies

Application source, tests and documentation use the root MIT LICENSE. Retain that
copyright/permission notice with copies or substantial portions. The included icon
is outside MIT; keep assets/BRANDING-RIGHTS.txt and use replacement branding for a
fork unless separately authorized. This package does not claim trademark rights.

Dependencies are installed separately, not vendored into this source artifact.
DEPENDENCY-LICENSES.json records package metadata from the isolated validation
resolution, including runtime/test/audit tooling. It is an inventory, not independent
legal clearance. Their own license texts and notices govern redistribution of those
packages, wheels, native extensions and bundled libraries. Project MIT does not
relicense them. If bundling dependencies in a later artifact, preserve their actual
license/NOTICE files and review native-library notices too.

Direct metadata includes MIT (mcp, PyJWT, jsonschema), BSD-3-Clause (Starlette/Uvicorn),
Apache-2.0 OR BSD-3-Clause (cryptography), ISC (dnspython), and BSD-like terms (dkimpy).
pip-audit is development-only with its own Apache-2.0 terms. Python/OS packages keep
their separate licenses. No tunnel client, model provider SDK or AI key is bundled.
Do not redistribute local virtual environments, credentials or private runtime bundles.

constraints-validated.txt records the tested dependency resolution. Recheck resolution,
licenses and vulnerability advisories before publication; a current clean advisory
check does not guarantee the absence of undisclosed vulnerabilities.

The 2.1.0rc1 inventory covers 62 pinned packages, including the six calendar
dependencies added to the previous resolution: icalendar, recurring-ical-events,
python-dateutil, six, tzdata and x-wr-timezone. It records installed metadata from
the isolated candidate environment with temporary audit tooling. No wheels or
virtual environment are included. CardDAV adds no dependency.
