"""Build deterministic source and Linux verification archives from the checked manifest."""
from pathlib import Path
import argparse, gzip, hashlib, json, shutil, subprocess, sys, tarfile, zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_release import verify


def archive_tar(path, items):
    with path.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for p, name in items:
                item = archive.gettarinfo(str(p), arcname=name)
                item.uid = item.gid = 0; item.uname = item.gname = ''; item.mtime = 0
                item.mode = 0o755 if p.stat().st_mode & 0o111 else 0o644
                with p.open('rb') as source: archive.addfile(item, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve()
    if out == ROOT or ROOT in out.parents: raise SystemExit('Choose an output directory outside the checkout.')
    if verify(): raise SystemExit('Source verification failed; no package built.')
    out.mkdir(parents=True, exist_ok=True)
    names = [line.split('  ', 1)[1] for line in (ROOT/'MANIFEST.sha256').read_text().splitlines()]+['MANIFEST.sha256']
    files = [ROOT/name for name in sorted(names)]; version = (ROOT/'VERSION').read_text().strip(); prefix = 'inboxtether-'+version
    source_zip = out/(prefix+'.zip'); source_tar = out/(prefix+'.tar.gz')
    with zipfile.ZipFile(source_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in files:
            entry = zipfile.ZipInfo(prefix+'/'+str(p.relative_to(ROOT)), date_time=(2026,10,30,0,0,0))
            entry.create_system = 3; entry.external_attr = (0o100755 if p.stat().st_mode & 0o111 else 0o100644)<<16
            entry.compress_type = zipfile.ZIP_DEFLATED; archive.writestr(entry, p.read_bytes())
    archive_tar(source_tar, [(p, prefix+'/'+str(p.relative_to(ROOT))) for p in files])
    with zipfile.ZipFile(source_zip) as z:
        assert len(z.namelist()) == len(files)
        for p in files: assert z.read(prefix+'/'+str(p.relative_to(ROOT))) == p.read_bytes()
    with tarfile.open(source_tar) as t:
        assert len(t.getmembers()) == len(files)
        for p in files: assert t.extractfile(prefix+'/'+str(p.relative_to(ROOT))).read() == p.read_bytes()
    verification = out/(prefix+'-linux-verification'); verification.mkdir(exist_ok=False)
    for src, name in [(source_tar, source_tar.name),(ROOT/'scripts/verify_linux_rc.py','verify_linux_rc.py'),(ROOT/'VERSION','VERSION'),(ROOT/'LICENSE','LICENSE'),(ROOT/'THIRD-PARTY.md','THIRD-PARTY.md'),(ROOT/'DEPENDENCY-LICENSES.json','DEPENDENCY-LICENSES.json'),(ROOT/'assets/BRANDING-RIGHTS.txt','BRANDING-RIGHTS.txt')]: shutil.copyfile(src, verification/name)
    (verification/'README.md').write_text('''# Experimental InboxTether Linux verification\n\nRequires Linux, Python 3.12 with venv, outbound HTTPS for pinned dependencies and\naudit advisories, and a normal non-root login with a private writable home.\nRun from any directory, using actual full paths:\n\n    python3 /full/path/to/verify_linux_rc.py --results /full/path/to/new-results\n\nThe new results directory must have an existing parent. It retains complete stdout,\nstderr and step exit codes, including failures. Source checksums are verified before\nextraction. Tests use synthetic fixtures and loopback HTTP; no mailbox credentials,\nsudo, application installation, existing client changes or production data are used.\nDependencies are downloaded separately, not vendored. Keep all included licenses.\n''')
    manifest = lambda paths, base: ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(base))+'\n' for p in sorted(paths))
    (verification/'SHA256SUMS').write_text(manifest([p for p in verification.iterdir() if p.is_file()], verification))
    verification_tar = out/(prefix+'-linux-verification.tar.gz')
    archive_tar(verification_tar, [(p, verification.name+'/'+p.name) for p in sorted(verification.iterdir())])
    for name in ('RELEASE_NOTES.md','SETUP_WIZARD.md','SECURITY.md','THIRD-PARTY.md','LICENSE','RC1_VALIDATION.md'): shutil.copyfile(ROOT/name, out/name)
    commit = subprocess.run(['git','rev-parse','HEAD'], cwd=ROOT, capture_output=True, text=True)
    (out/'BUILD_INFO.json').write_text(json.dumps({'version':version,'source_files':len(files),'source_manifest_sha256':hashlib.sha256((ROOT/'MANIFEST.sha256').read_bytes()).hexdigest(),'checkout_head':commit.stdout.strip() if commit.returncode == 0 else None,'tag_or_release_created':False}, indent=2)+'\n')
    outputs = [p for p in out.iterdir() if p.is_file() and p.name != 'SHA256SUMS']
    (out/'SHA256SUMS').write_text(manifest(outputs, out))
    print(json.dumps({'version':version,'source_files':len(files),'archives':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source_zip,source_tar,verification_tar)}}))


if __name__ == '__main__': main()
