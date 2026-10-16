"""Frozen one-file bootstrap. Stable verified resources; never stores evidence in TEMP."""
import hashlib,json,os,subprocess,sys,zipfile,msvcrt,time,threading
from pathlib import Path

def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def materialize(bundle, state):
 expected=json.loads((bundle/'payload.json').read_text(encoding='utf-8'))
 archive=bundle/'student.zip'
 if digest(archive)!=expected['sha256']:raise RuntimeError('Embedded archive integrity failure')
 cache=state/'builds'/expected['sha256'][:24];cache.parent.mkdir(parents=True,exist_ok=True)
 with (state/'extraction.lock').open('a+b') as lock:
  lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
  msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
  try:
   if not cache.exists():
    staging=cache.with_name(cache.name+'.extracting-'+str(os.getpid()));staging.mkdir()
    with zipfile.ZipFile(archive) as z:
     for member in z.infolist():
      path=Path(member.filename)
      if path.is_absolute() or '..' in path.parts or ':' in member.filename or '\\' in member.filename or (member.external_attr>>16)&0o170000==0o120000:raise RuntimeError('Unsafe resource path')
      target=staging/path
      if not target.resolve().is_relative_to(staging.resolve()):raise RuntimeError('Resource escapes extraction')
     z.extractall(staging)
    extracted=list(staging.iterdir())
    if len(extracted)!=1 or not extracted[0].is_dir():raise RuntimeError('Invalid application payload')
    extracted[0].rename(staging/'app')
    staging.rename(cache)
   roots=list(cache.iterdir())
   if len(roots)!=1 or not roots[0].is_dir():raise RuntimeError('Invalid application payload')
   app=roots[0]
   with zipfile.ZipFile(archive) as z:
    originals=[n for n in z.namelist() if n.endswith('/PACKAGE-INVENTORY.json') and n.count('/')==1]
    if len(originals)!=1:raise RuntimeError('Invalid embedded inventory')
    original=z.read(originals[0])
   if (app/'PACKAGE-INVENTORY.json').read_bytes()!=original:raise RuntimeError('Installed inventory integrity failure')
   inventory=json.loads(original)
   permitted={row['path'] for row in inventory['files']}|{'PACKAGE-INVENTORY.json'}
   if {p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file()}!=permitted:raise RuntimeError('Unexpected installed resources')
   for row in inventory['files']:
    file=app/row['path']
    if file.is_symlink() or not file.resolve().is_relative_to(app.resolve()) or not file.is_file() or digest(file)!=row['sha256']:raise RuntimeError('Installed resource integrity failure')
   return app
  finally:
   lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def acquire_launch_lock(state):
 lock=(state/'student-launch.lock').open('a+b')
 try:
  lock.seek(0)
  msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
  return lock
 except OSError:
  lock.close()
  raise RuntimeError('The student application or security check is already running') from None

def edition_environment(bundle,environ):
 metadata=json.loads((bundle/'payload.json').read_text(encoding='utf-8'))
 profile=metadata.get('profile_name')
 if profile is None:return dict(environ)
 profiles={'protected-no-audit':'ProtectedNoAudit','unprotected':'Unprotected'}
 if profile not in profiles:raise RuntimeError('Unknown student edition profile')
 env=dict(environ)
 # Separate explicit edition; never delete, migrate or reinterpret old attempts.
 base=Path(env['LOCALAPPDATA'])/'LocalProctoring'/'Editions'/profiles[profile]
 env['LOCALAPPDATA']=str(base/'Local');env['APPDATA']=str(base/'Roaming')
 Path(env['LOCALAPPDATA']).mkdir(parents=True,exist_ok=True)
 Path(env['APPDATA']).mkdir(parents=True,exist_ok=True)
 return env

def main():
 bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
 os.environ.update(edition_environment(bundle,os.environ))
 state=Path(os.environ['LOCALAPPDATA'])/'LocalProctoring'/'Portable'
 state.mkdir(parents=True,exist_ok=True)
 app=materialize(bundle,state)
 args=sys.argv[1:]
 audit_output=None
 if '--validate-electron-protection' in args:
  if '--native-input' not in args:raise RuntimeError('Explicit native audit readiness approval is required')
  if '--audit-output' in args:
   audit_output=Path(args[args.index('--audit-output')+1]).resolve()
  else:
   audit_output=Path(os.environ['LOCALAPPDATA'])/'LocalProctoring'/'Student'/'audits'/'electron-recovery.json'
   args += ['--audit-output',str(audit_output)]
  if audit_output.exists():raise RuntimeError('Audit output already exists; preserve it and prepare a new matching configuration')
 # Portable executable delegates audit/fixture modes to the same exact build.
 # It retains and drains both child pipes until actual process termination.
 launch_lock=acquire_launch_lock(state)
 env=dict(os.environ)
 for key in list(env):
  if key.startswith(('PROCTOR','PYTHON')) or key in ('ELECTRON_RUN_AS_NODE','NODE_OPTIONS','NODE_PATH'):env.pop(key,None)
 env['LOCAL_PROCTOR_PORTABLE_SHA256']=digest(Path(sys.executable))
 child=subprocess.Popen([str(app/'LocalProctoring-Electron.exe'),*args],cwd=app,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 counts=[0,0]
 def drain(stream,index):
  while chunk:=stream.read(65536):counts[index]+=len(chunk)
 threads=[threading.Thread(target=drain,args=(stream,index)) for index,stream in enumerate((child.stdout,child.stderr))]
 for thread in threads:thread.start()
 code=child.wait()
 for thread in threads:thread.join()
 if audit_output is not None:
  try:
   report=json.loads(audit_output.read_text(encoding='utf-8'))
   names={'binding_identity','wrong_hwnd_rejected','wrong_stale_identity_rejected','normal_release','repeated_cycles','emergency_shortcut','pin_modal_emergency','external_focus_emergency','renderer_loss_observer_alive','main_loss','main_stall','backend_loss','backend_stall','control_eof','lost_release_ack','helper_suspension','helper_loop_failure','forced_release','replay_rejected','overlapping_helper_rejected','recovery_reregister'}
   checks=report['checks']
   if code!=0 or report.get('passed') is not True or report.get('status')!='completed' or report.get('blocking_enabled') is not False or report['identity']['runtime']['build_kind']!='packaged' or len(checks)!=21 or {c['name'] for c in checks}!=names or any(c.get('passed') is not True or c.get('kind')!='native_audit' for c in checks):code=1
  except (OSError,ValueError,KeyError,TypeError):code=1
 (state/'last-launch.json').write_text(json.dumps({'pid':child.pid,'exit_code':code,'stdout_bytes':counts[0],'stderr_bytes':counts[1],'finished_at':time.time(),'build':app.parent.name}))
 launch_lock.seek(0);msvcrt.locking(launch_lock.fileno(),msvcrt.LK_UNLCK,1);launch_lock.close()
 return code

if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as error:
  import ctypes
  ctypes.windll.user32.MessageBoxW(None,'The student application could not start safely. '+str(error),'Local Proctoring',0x10)
  raise SystemExit(1)
