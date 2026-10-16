"""Separate source/package Electron recovery prerequisite; never accepts Qt audits."""
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
from pathlib import Path, PurePosixPath
import sys
from .validation import machine_identity

MANDATORY_CHECKS = frozenset({
    'binding_identity','wrong_hwnd_rejected','wrong_stale_identity_rejected','normal_release',
    'repeated_cycles','emergency_shortcut','pin_modal_emergency','external_focus_emergency',
    'renderer_loss_observer_alive','main_loss','main_stall','backend_loss','backend_stall',
    'control_eof','lost_release_ack','helper_suspension','helper_loop_failure','forced_release',
    'replay_rejected','overlapping_helper_rejected','recovery_reregister',
})


def protection_policy(config):
    """Effective recovery/containment settings; no paths, credentials or consent."""
    return {'heartbeat_timeout_seconds':config.heartbeat_timeout_seconds,
            'startup_timeout_seconds':config.startup_timeout_seconds,
            'foreground_poll_ms':config.foreground_poll_ms}


def hash_paths(root, paths, prefix):
    digest = hashlib.sha256(prefix)
    root = Path(root).resolve()
    for path in sorted(paths,key=lambda p:p.relative_to(root).as_posix()):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('Recovery fingerprint contains a missing or unsafe resource')
        digest.update(path.relative_to(root).as_posix().encode('utf-8')+b'\0')
        with path.open('rb') as stream:
            for part in iter(lambda:stream.read(4*1024*1024),b''): digest.update(part)
        digest.update(b'\0')
    return digest.hexdigest()


def artifact_paths(app_root):
    paths=[]
    for folder in ('build-electron','dist'):
        directory=Path(app_root)/folder
        if not directory.is_dir(): raise ValueError('Electron build artifacts are missing')
        for path in directory.rglob('*'):
            if path.is_symlink(): raise ValueError('Electron artifacts must not contain symlinks')
            if path.is_file(): paths.append(path)
    if not paths: raise ValueError('Electron build artifacts are empty')
    return paths


def artifact_fingerprint(app_root):
    return hash_paths(app_root,artifact_paths(app_root),b'proctoring-electron-artifacts-v1\0')


def runtime_resources(binding, package_root=None):
    """The exact existing fingerprint recipe, also used by retained resource locks."""
    runtime=dict(binding.runtime)
    if runtime['build_kind']=='packaged':
        root=Path(package_root or Path(sys.executable).resolve().parents[2]).resolve()
        manifest_path=root/'resources/package-build.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest,dict) or manifest.get('schema')!=1 or manifest.get('build_kind')!='packaged':
            raise ValueError('Packaged recovery manifest is missing or incompatible')
        files=manifest.get('files')
        if not isinstance(files,list) or not files or len(files)>100000 or any(not isinstance(n,str) for n in files):
            raise ValueError('Invalid packaged resource list')
        if len(set(files))!=len(files): raise ValueError('Duplicate packaged resource')
        paths=[]
        for name in files:
            posix=PurePosixPath(name)
            if '\\' in name or posix.is_absolute() or '..' in posix.parts or ':' in name or name != posix.as_posix():
                raise ValueError('Unsafe packaged resource path')
            paths.append(root/name)
        # A manifest containing only one executable must never validate an
        # Electron/backend package with independent mutable native resources.
        if not any(n.startswith('resources/backend/') for n in files) or not any(n.startswith('resources/app/') for n in files):
            raise ValueError('Packaged manifest omits required runtimes')
        paths.append(manifest_path)
        prefix=b'proctoring-electron-package-v1\0'
        app_root=root/'resources/app'
    else:
        root=Path(__file__).resolve().parents[3]
        paths=list((root/'src/proctoring/security').glob('*.py'))+list((root/'src/proctoring/desktop_bridge').glob('*.py'))
        paths += [root/'src/proctoring'/name for name in ('controller.py','session.py','config.py','exam_policy.py','events/engine.py','connected/client.py','connected/live_workflow.py')]
        paths += list((root/'src/proctoring/advanced').glob('*.py'))
        paths += list((root/'src/proctoring/audio').glob('*.py'))
        paths += [root/'src/proctoring/vision/monitor.py',root/'src/proctoring/domain.py']
        paths += [root/'config/default.example.toml']
        paths += [p for folder in ('electron','shared','src','scripts') for p in (root/'desktop'/folder).rglob('*') if p.is_file()]
        prefix=b'proctoring-electron-source-v1\0'
        app_root=root/'desktop'
    return root,paths,prefix,app_root


def runtime_identity(binding, package_root=None):
    runtime=dict(binding.runtime)
    root,paths,prefix,app_root=runtime_resources(binding,package_root)
    fingerprint=hash_paths(root,paths,prefix)
    actual=artifact_fingerprint(app_root)
    if actual != runtime['build_id']: raise ValueError('Electron artifact identity differs from host launch')
    return {'machine':machine_identity(),'runtime':runtime,'host_executable':str(Path(binding.image_path).resolve()).casefold(),
        'python_runtime':{'implementation':platform.python_implementation(),'version':platform.python_version(),
                          'architecture':platform.machine()},'fingerprint':fingerprint}


def require_electron_validation(path, identity, max_age_hours=24.):
    if isinstance(max_age_hours,bool) or not math.isfinite(max_age_hours) or max_age_hours<=0:
        raise ValueError('Recovery validation age must be positive')
    try:
        report=json.loads(Path(path).read_text(encoding='utf-8'))
        if report.get('schema')!=2 or report.get('frontend')!='electron' or report.get('mode')!='audit_only':
            raise ValueError('Electron recovery audit required; legacy reports are incompatible')
        if report.get('blocking_enabled') is not False or report.get('passed') is not True:
            raise ValueError('Electron recovery audit did not pass')
        if report.get('status', 'completed') != 'completed':
            raise ValueError('Electron recovery audit is incomplete or failed')
        if report.get('identity') != identity: raise ValueError('Machine/runtime/build changed since audit')
        generated=datetime.fromisoformat(report['generated_at'])
        if generated.tzinfo is None: raise ValueError('Audit timestamp requires a timezone')
        age=(datetime.now(timezone.utc)-generated).total_seconds()
        if age < -60 or age > max_age_hours*3600: raise ValueError('Audit is expired or future dated')
        checks=report.get('checks')
        if not isinstance(checks,list) or any(not isinstance(c,dict) for c in checks): raise ValueError('Audit checks missing')
        names=[c.get('name') for c in checks]
        if any(not isinstance(n,str) for n in names) or len(set(names))!=len(names): raise ValueError('Duplicate or malformed audit checks')
        if not MANDATORY_CHECKS.issubset(names) or any(c.get('passed') is not True or c.get('kind')!='native_audit' for c in checks):
            raise ValueError('Required native audit checks did not all pass')
        return report
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        raise ValueError(f'Run the Electron recovery audit for this build: {error}') from error
