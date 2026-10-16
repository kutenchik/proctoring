"""Wrap an inspected folder ZIP in one unsigned portable EXE; no app is launched."""
import argparse,hashlib,json,shutil,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def build(archive,output,*,profile_name=None):
 if profile_name not in (None,'protected-no-audit','unprotected'):raise ValueError('Unknown student edition profile')
 archive=archive.resolve();output=output.resolve()
 if output.exists():raise ValueError('Existing artifacts must not be overwritten')
 work=root/'build'/'portable-bootstrap';work.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(archive,work/'student.zip')
 with archive.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
 (work/'payload.json').write_text(json.dumps({'sha256':sha,**({'profile_name':profile_name} if profile_name else {})}))
 subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed','--name',output.stem,'--distpath',str(output.parent),'--workpath',str(work/'work'),'--specpath',str(work),'--add-data',str(work/'student.zip')+';.','--add-data',str(work/'payload.json')+';.',str(root/'packaging/portable_launcher.py')],check=True,cwd=root)
 with output.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
 output.with_suffix('.exe.sha256').write_text(sha+'  '+output.name+'\n')
 print(str(output),sha)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('output',type=Path);p.add_argument('--profile-name',choices=['protected-no-audit','unprotected']);a=p.parse_args();build(a.archive,a.output,profile_name=a.profile_name)
