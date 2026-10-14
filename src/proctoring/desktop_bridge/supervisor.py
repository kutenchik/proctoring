"""Inherited-pipe backend supervisor; no Qt, capture, hooks or public listener.

The native backend HANDLE is acquired from an authenticated early announcement,
then checked against the exact launched process ancestry and creation time. Main
EOF/death allows helper recovery first, then bounds wedged backend cleanup. No
executable-name or stale numeric-PID termination is used.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time

from ..security.electron_binding import NativeIdentity, ancestors

IDENTITY_PREFIX = 'PROCTORING_BACKEND_IDENTITY:'


def announce_backend_identity():
    nonce = os.environ.get('PROCTORING_BACKEND_NONCE', '')
    if re.fullmatch('[a-f0-9]{64}', nonce):
        print(IDENTITY_PREFIX + json.dumps({'pid': os.getpid(), 'nonce': nonce}),
              file=sys.stderr, flush=True)


class BackendOwner:
    def __init__(self, pid, launcher, *, native=None, parent_chain=ancestors):
        if type(pid) is not int or pid <= 0 or pid == os.getpid() or launcher.poll() is not None:
            raise ValueError('Invalid backend ownership announcement')
        self.native = native or NativeIdentity()
        self.handle = self.native.open_process(pid, terminate=True)
        try:
            self.created = self.native.creation(self.handle)
            if not self.native.alive(self.handle):
                raise ValueError('Backend already exited')
            if pid != launcher.pid and launcher.pid not in parent_chain(pid)[:4]:
                raise ValueError('Backend is not owned by its launched process')
            launcher_handle = self.native.open_process(launcher.pid)
            try:
                if not self.native.alive(launcher_handle) or int(self.created) < int(self.native.creation(launcher_handle)):
                    raise ValueError('Backend ancestry has a stale process identity')
            finally:
                self.native.close(launcher_handle)
            if launcher.poll() is not None or not self.native.alive(self.handle):
                raise ValueError('Backend ownership changed while binding')
        except BaseException:
            self.close()
            raise

    def alive(self): return self.handle is not None and self.native.alive(self.handle)
    def terminate(self): self.native.terminate(self.handle, timeout=1.)
    def close(self):
        if self.handle is not None:
            self.native.close(self.handle)
            self.handle = None


def backend_command(config, preview_pipe=None, preview_token=None):
    command = ([sys.executable, '--desktop-bridge'] if getattr(sys, 'frozen', False)
               else [sys.executable, '-u', '-m', 'proctoring.desktop_bridge'])
    command += ['--config', str(config)]
    if preview_pipe: command += ['--preview-pipe', preview_pipe, '--preview-token', preview_token]
    return command


def _copy(source, target, disconnected):
    try:
        while True:
            data = source.read(4096)
            if not data: break
            remaining = memoryview(data)
            while remaining:
                written = target.write(remaining)
                if not written: raise OSError('Control pipe closed')
                remaining = remaining[written:]
            target.flush()
    except (OSError, ValueError):
        pass
    finally:
        disconnected.set()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Owned Electron backend supervisor')
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--host-pid', required=True, type=int)
    parser.add_argument('--preview-pipe')
    parser.add_argument('--preview-token')
    args = parser.parse_args(argv)
    if not re.fullmatch('[a-f0-9]{32}', os.environ.get('PROCTORING_HOST_LAUNCH_ID', '')):
        parser.error('An inherited Electron launch identity is required')
    native = NativeIdentity()
    host = native.open_process(args.host_pid)
    if not native.alive(host) or args.host_pid not in ancestors(os.getpid())[:4]:
        native.close(host)
        parser.error('Supervisor host is not its live launching ancestor')
    from ..config import load_config
    config = load_config(args.config)
    # Independent helper/guardian release precedes forced backend termination.
    cleanup_seconds = max(8., config.protection.heartbeat_timeout_seconds + 3.)
    nonce = secrets.token_hex(32)
    environment = dict(os.environ, PROCTORING_BACKEND_NONCE=nonce, PYTHONUNBUFFERED='1', PYTHONUTF8='1')
    child = subprocess.Popen(backend_command(args.config, args.preview_pipe, args.preview_token),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=environment, creationflags=subprocess.CREATE_NO_WINDOW, bufsize=0)
    host_lost = threading.Event()
    output_closed = threading.Event()
    identity_ready = threading.Event()
    ownership = {'owner': None, 'error': False}

    def diagnostics():
        try:
            while line := child.stderr.readline(65537):
                if len(line) > 65536: raise ValueError('Backend diagnostic line too large')
                if line.startswith(IDENTITY_PREFIX.encode()):
                    if ownership['owner'] is not None: raise ValueError('Duplicate backend identity')
                    value = json.loads(line[len(IDENTITY_PREFIX):])
                    if set(value) != {'pid', 'nonce'} or value['nonce'] != nonce:
                        raise ValueError('Backend identity nonce mismatch')
                    ownership['owner'] = BackendOwner(value['pid'], child, native=native)
                    identity_ready.set()
                else:
                    sys.stderr.buffer.write(line)
                    sys.stderr.buffer.flush()
        except Exception:
            ownership['error'] = True
            identity_ready.set()
            host_lost.set()

    raw_input = getattr(sys.stdin.buffer, 'raw', sys.stdin.buffer)
    raw_output = getattr(sys.stdout.buffer, 'raw', sys.stdout.buffer)
    for target, arguments in [(diagnostics, ()), (_copy, (raw_input, child.stdin, host_lost)),
                              (_copy, (child.stdout, raw_output, output_closed))]:
        threading.Thread(target=target, args=arguments, daemon=True).start()
    started = time.monotonic()
    deadline = None
    forced = False
    try:
        while child.poll() is None:
            now = time.monotonic()
            if not identity_ready.is_set() and now - started > 5.:
                host_lost.set()
            if not native.alive(host): host_lost.set()
            if output_closed.is_set(): host_lost.set()
            if host_lost.is_set() and deadline is None:
                deadline = now + cleanup_seconds
                def close_input():
                    try: child.stdin.close()
                    except (OSError, ValueError): pass
                threading.Thread(target=close_input, daemon=True).start()
            if deadline is not None and now >= deadline:
                owner = ownership['owner']
                if owner is not None and owner.alive(): owner.terminate()
                # Popen retains this exact launcher HANDLE; never taskkill a PID.
                if child.poll() is None: child.terminate()
                child.wait(timeout=2.)
                forced = True
                break
            time.sleep(.02)
    finally:
        owner = ownership['owner']
        if owner is not None:
            if owner.alive():
                # Launcher loss can precede the interpreter: still enforce the
                # independent release grace before terminating its retained handle.
                until = deadline if deadline is not None else time.monotonic() + cleanup_seconds
                while owner.alive() and time.monotonic() < until: time.sleep(.02)
                if owner.alive():
                    owner.terminate()
                    forced = True
            owner.close()
        native.close(host)
    return 4 if forced or ownership['error'] else (child.returncode or 0)


if __name__ == '__main__':
    raise SystemExit(main())
