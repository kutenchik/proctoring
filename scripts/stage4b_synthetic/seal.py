"""Offline build identity for the already-reviewed synthetic preparation."""
import hashlib
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[2]
run=Path(sys.argv[1]).resolve()
if run.parent!=root/'build/stage4b' or not (run/'synthetic.json').is_file() or (run/'deadline.json').exists():
    raise SystemExit('Only a prepared, never-exposed synthetic run can be sealed')
files=set()
for directory,suffixes in [
    ('src/proctoring_server',{'.py','.sql'}),('src/proctoring/connected',{'.py'}),
    ('desktop/electron',{'.ts'}),('shared',{'.ts'}),('teacher-web/src',{'.ts','.tsx','.css'}),
    ('teacher-web/dist',None),('scripts/stage4b_synthetic',{'.py','.mjs','.ps1'})]:
    for file in (root/directory).rglob('*'):
        if file.is_file() and not file.is_symlink() and (suffixes is None or file.suffix in suffixes):files.add(file)
for name in ['scripts/stage4b-process-identity.ps1','scripts/test-stage4b-identity.ps1','scripts/test-stage4b-lifecycle.ps1','scripts/stage4b-demo.ps1','scripts/stage4b-exposure-deadline.py','desktop/package-lock.json','teacher-web/package-lock.json']:
    files.add(root/name)
entries=[{'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]
(run/'prepared-hashes.json').write_text(json.dumps(entries,indent=2))
print(f'Sealed {len(entries)} source/build files; no service or network started.')
