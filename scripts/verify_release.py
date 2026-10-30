"""Read-only source/package hygiene checks; matched secret values are never printed."""
from pathlib import Path
import ast,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_repository import findings

def verify():
    errors=[];count=0
    for p in sorted(ROOT.rglob('*')):
        if any(part in ('.git','.venv','__pycache__') for part in p.parts):continue
        if p.is_symlink():errors.append((str(p.relative_to(ROOT)),'symlink'));continue
        if not p.is_file():continue
        name=str(p.relative_to(ROOT));count+=1
        if p.suffix in ('.pyc','.sqlite3','.zip','.gz') or p.name in ('operation.json','witness.json','owner.json'):
            errors.append((name,'operational/build artifact'))
        for hit in findings(p.read_bytes()):errors.append((name,hit))
        if p.suffix=='.py':
            tree=ast.parse(p.read_text())
            for n in ast.walk(tree):
                modules=[]
                if isinstance(n,ast.Import):modules=[a.name.split('.')[0] for a in n.names]
                elif isinstance(n,ast.ImportFrom) and n.module:modules=[n.module.split('.')[0]]
                if set(modules)&{'smtplib','aiosmtplib','send_assistant','send_bootstrap','send_client'}:
                    errors.append((name,'prohibited sending import'))
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('prepare_send_message','send_request_status'):
                    errors.append((name,'prohibited sending tool'))
    manifest=ROOT/'MANIFEST.sha256'
    if manifest.exists():
        expected={}
        for line in manifest.read_text().splitlines():
            sha,name=line.split('  ',1);expected[name]=sha
            p=ROOT/name
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:errors.append((name,'checksum mismatch'))
        actual={str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts and '.venv' not in p.parts and p!=manifest}
        if actual!=set(expected):errors.append(('MANIFEST.sha256','file set mismatch'))
    if errors:
        for name,kind in errors:print(name+': '+kind)
        return 1
    print(json.dumps({'files_checked':count,'pattern_findings':0,'sending_capability_imports':0,'manifest_verified':manifest.exists()}))
    return 0
if __name__=='__main__':sys.exit(verify())
