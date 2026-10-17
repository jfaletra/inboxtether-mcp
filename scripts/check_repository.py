"""Bounded repository hygiene check; findings never print matched secret values.

This is a detective pattern check, not exhaustive secret/PII detection or DLP.
Run from any source checkout. CI must fetch full history before using --history.
"""
from pathlib import Path
import argparse
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'OpenAI-style key': rb'\bsk-[A-Za-z0-9_-]{16,}',
    'GitHub-style token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    'private key': rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----',
    'AWS access ID': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'credential URL': rb'(?i)\b(?:https?|imaps?|smtps?)://[^\s/@:]+:[^\s/@]+@',
    'private IPv4': rb'\b(?:10(?:\.[0-9]{1,3}){3}|192\.168(?:\.[0-9]{1,3}){2}|172\.(?:1[6-9]|2[0-9]|3[01])(?:\.[0-9]{1,3}){2})\b',
    'personal filesystem path': rb'/(?:Users|home)/[A-Za-z0-9_.-]+/',
}


def findings(data):
    result = {name for name, pattern in PATTERNS.items() if re.search(pattern, data)}
    # PNG provenance certificates may contain public CA addresses, and compressed
    # pixels can resemble email text. Review image metadata separately; do not
    # mistake these bytes for a contributor's private contact address.
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return sorted(result)
    for address in re.findall(rb'[A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', data):
        domain = address.rsplit(b'@', 1)[1].lower()
        if (domain not in (b'example.com', b'example.org', b'github.com', b'users.noreply.github.com')
                and not domain.endswith((b'.example.com', b'.example.org'))):
            result.add('nonexample email address')
        # Dependabot signs commit messages with GitHub's public support address.
        elif domain == b'github.com' and address.lower() not in (b'noreply@github.com', b'support@github.com'):
            result.add('nonexample email address')
    return sorted(result)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--history', action='store_true', help='also scan every local Git blob/commit/tag object')
    args = parser.parse_args()
    failures = []
    names = [n for n in git('ls-files', '-z').decode().split('\0') if n]
    for name in names:
        path = ROOT / name
        if path.is_symlink():
            failures.append(('tracked file', 'symlink'))
        else:
            failures.extend(('tracked file', item) for item in findings(path.read_bytes()))
    scanned = 0
    if args.history:
        if git('rev-parse', '--is-shallow-repository').strip() == b'true':
            raise SystemExit('Refusing incomplete history scan: shallow checkout.')
        objects = git('cat-file', '--batch-all-objects', '--batch-check=%(objectname) %(objecttype)').decode().splitlines()
        for row in objects:
            oid, kind = row.split()
            if kind in ('blob', 'commit', 'tag'):
                scanned += 1
                failures.extend(('Git object', item) for item in findings(git('cat-file', kind, oid)))
    if failures:
        for location, category in sorted(set(failures)):
            print(f'REVIEW REQUIRED: {location}: {category}', file=sys.stderr)
        return 1
    print(f'Hygiene patterns passed: {len(names)} tracked files, {scanned} Git objects. Manual review remains required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
