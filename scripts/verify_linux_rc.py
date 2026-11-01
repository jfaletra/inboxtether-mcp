"""Verify the source artifact with synthetic tests; never install InboxTether or access mail."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, os, subprocess, sys, tarfile, tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True, help='New directory for complete logs and exit codes')
    args = parser.parse_args()
    if sys.platform != 'linux' or sys.version_info[:2] != (3, 12):
        raise SystemExit('Use Linux with Python 3.12 and its venv module. No sudo or mailbox credentials are needed.')
    bundle = Path(__file__).resolve().parent
    version = (bundle/'VERSION').read_text().strip()
    for line in (bundle/'SHA256SUMS').read_text().splitlines():
        value, name = line.split('  ', 1)
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or hashlib.sha256((bundle/name).read_bytes()).hexdigest() != value:
            raise SystemExit('Verification-package checksum mismatch: '+name)
    results = args.results.resolve(); results.mkdir(mode=0o700, parents=False, exist_ok=False)
    env = {k:v for k,v in os.environ.items() if not k.startswith('INBOXTETHER_') and k != 'PYTHONPATH'}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    # Fixtures assert conventional modes inside private temporary parents.
    os.umask(0o022)
    steps = []
    with tempfile.TemporaryDirectory(prefix='inboxtether-rc-') as temporary:
        work = Path(temporary); source = work/('inboxtether-'+version)
        with tarfile.open(bundle/('inboxtether-'+version+'.tar.gz')) as archive:
            for item in archive.getmembers():
                name = PurePosixPath(item.name)
                if not item.isfile() or name.is_absolute() or '..' in name.parts or name.parts[0] != source.name:
                    raise SystemExit('Unexpected source archive layout')
                p = work/item.name; p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                p.write_bytes(archive.extractfile(item).read()); p.chmod(item.mode & 0o777)
        python = work/'.venv/bin/python'
        commands = [
            ('venv', [sys.executable, '-m', 'venv', str(work/'.venv')]),
            ('dependencies', [str(python), '-m', 'pip', 'install', '-c', 'constraints-validated.txt', '-r', 'requirements-test.txt', '-r', 'requirements-audit.txt']),
            ('dependency-consistency', [str(python), '-m', 'pip', 'check']),
            ('regression', [str(python), '-B', 'run_tests.py']),
            ('http-security', [str(python), '-B', 'scripts/test_installer_http.py']),
            ('source-integrity', [str(python), '-B', 'scripts/verify_release.py']),
            ('dependency-audit', [str(python), '-m', 'pip_audit', '-r', 'constraints-validated.txt', '--no-deps', '--disable-pip', '--strict', '--progress-spinner', 'off', '--format', 'json']),
        ]
        for name, command in commands:
            with (results/(name+'.stdout.log')).open('wb') as out, (results/(name+'.stderr.log')).open('wb') as err:
                p = subprocess.run(command, cwd=source, env=env, stdout=out, stderr=err)
            steps.append({'step':name, 'exit_code':p.returncode})
            (results/'RESULTS.json').write_text(json.dumps({'version':version, 'synthetic_only':True, 'steps':steps}, indent=2)+'\n')
            print(name+': '+('PASS' if p.returncode == 0 else 'FAIL'), flush=True)
            if p.returncode:
                raise SystemExit('Stopped. Full output and exit codes remain in the results directory.')
    print('Verification passed. No InboxTether service, mailbox operation or desktop connection was installed.')


if __name__ == '__main__':
    main()
