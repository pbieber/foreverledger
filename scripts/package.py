"""Build an installable addon/tool archive without including gameplay data."""
from pathlib import Path
import hashlib
import zipfile

root=Path(__file__).resolve().parents[1]
toc=(root/'ForeverLedger'/'ForeverLedger.toc').read_text(encoding='utf-8')
version=next(line.split(':',1)[1].strip() for line in toc.splitlines() if line.startswith('## Version:'))
files=[]
for folder in ('ForeverLedger','ForeverLedger-tools'):
    files.extend(p for p in sorted((root/folder).rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.lua','.toc','.py'))
files.extend(root/n for n in ('README.md','SCHEMA.md','TESTING.md','LICENSE.txt','VALIDATION.txt'))
dist=root/'dist'
dist.mkdir(exist_ok=True)
archive=dist/f'ForeverLedger-{version}.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for path in files:
        z.write(path,path.relative_to(root).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for line in toc.splitlines():
        if line and not line.startswith('#'):
            assert 'ForeverLedger/'+line in z.namelist()
print(f'{archive}: {len(files)} files')
print('SHA256: '+hashlib.sha256(archive.read_bytes()).hexdigest())
