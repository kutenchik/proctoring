"""Independent process watchdog for the exact hook owner (including suspension).

Only the helper message loop returns challenge receipts. This process retains a
verified native process handle; it never searches or terminates by image name.
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from .control_lease import ControlLease
from .electron_binding import NativeIdentity, ancestors
from .helper_process import OwnedHelperProcess


class GuardianOwner:
    def __init__(self, pid, created, *, native=None, parent_chain=ancestors):
        self.native = native or NativeIdentity()
        self.handle = self.native.open_process(pid, terminate=True)
        try:
            if not self.native.alive(self.handle) or self.native.creation(self.handle) != created:
                raise ValueError('Helper identity changed before guardian attachment')
            if pid not in parent_chain(os.getpid())[:4]:
                raise ValueError('Guardian may supervise only its own helper ancestor')
        except BaseException:
            self.native.close(self.handle); self.handle = None; raise

    def alive(self): return self.native.alive(self.handle)
    def terminate(self): self.native.terminate(self.handle, timeout=1.)
    def close(self):
        if self.handle: self.native.close(self.handle); self.handle = None


def _reader(stream, messages, failed):
    try:
        while True:
            line = stream.readline(2049)
            if not line or len(line) > 2048 or not line.endswith('\n'): break
            messages.put_nowait(json.loads(line))
    except (OSError, ValueError, queue.Full): pass
    finally: failed.set()


def guardian_command(pid, created):
    route = ['--protection-guardian'] if getattr(sys, 'frozen', False) else ['-m','proctoring.security.guardian']
    return [sys.executable, *route, '--helper-pid', str(pid), '--helper-created', created]


class GuardianClient:
    """Helper-side client: call tick ONLY from the native hook message loop."""
    def __init__(self):
        native = NativeIdentity(); handle = native.open_process(os.getpid())
        try: created = native.creation(handle)
        finally: native.close(handle)
        self.process = subprocess.Popen(guardian_command(os.getpid(),created), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
        self.messages, self.failed = queue.Queue(maxsize=4), threading.Event()
        self.owner = None
        self.created = None
        self.last_challenge = time.monotonic()
        self.next_ack = 0.
        self.pending = None
        self.sequence = 0
        threading.Thread(target=_reader,args=(self.process.stdout,self.messages,self.failed),daemon=True).start()
        try:
            ready = self.messages.get(timeout=2.)
            if not isinstance(ready,dict) or ready.get('kind') != 'ready': raise RuntimeError('Guardian did not identify itself')
            self.owner = OwnedHelperProcess(ready['pid'],self.process)
            retained=native.open_process(self.owner.pid)
            try:
                if not self.owner.alive(): raise RuntimeError('Guardian exited during attachment')
                self.created=native.creation(retained)
            finally: native.close(retained)
        except BaseException:
            self.close(); raise

    def tick(self):
        now = time.monotonic()
        if self.failed.is_set() or self.process.poll() is not None or now-self.last_challenge >= 3.:
            raise RuntimeError('Independent helper guardian unavailable')
        try:
            message = self.messages.get_nowait()
            if set(message) != {'lease_id','sequence','nonce'}: raise ValueError('Invalid guardian challenge')
            self.pending = message
            self.last_challenge = now
        except queue.Empty: pass
        if self.pending is not None and now >= self.next_ack:
            self.sequence += 1
            self.process.stdin.write(json.dumps({**self.pending,'main_sequence':self.sequence})+'\n')
            self.process.stdin.flush()
            self.pending = None
            self.next_ack = now+.2

    def close(self):
        # Caller must remove native hooks first. Terminating the guardian itself
        # here cannot leave a hook owner armed without its safety process.
        process = getattr(self,'process',None)
        if process is None: return
        try:
            if process.poll() is None:
                process.stdin.write('{"stop":true}\n'); process.stdin.flush()
                process.wait(timeout=.5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            if self.owner: self.owner.terminate_and_wait(timeout=1.)
            elif process.poll() is None: process.terminate(); process.wait(timeout=1.)
        finally:
            if self.owner: self.owner.close()
            for stream in (process.stdin,process.stdout):
                if stream: stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper-pid',required=True,type=int)
    parser.add_argument('--helper-created',required=True)
    args = parser.parse_args(argv)
    owner = GuardianOwner(args.helper_pid,args.helper_created)
    messages, failed = queue.Queue(maxsize=4), threading.Event()
    threading.Thread(target=_reader,args=(sys.stdin,messages,failed),daemon=True).start()
    def write(value):
        sys.stdout.write(json.dumps(value)+'\n'); sys.stdout.flush()
    try:
        write({'kind':'ready','pid':os.getpid()})
        lease = ControlLease(time.monotonic(),2.5)
        write(lease.challenge)
        while owner.alive():
            # Expiration precedes queued receipts: suspended loops cannot renew
            # retrospectively with buffered acknowledgements.
            if lease.expired(time.monotonic()) or failed.is_set():
                owner.terminate(); return 3
            try: value = messages.get(timeout=.03)
            except queue.Empty: continue
            if value == {'stop':True}: return 0
            lease.acknowledge(value,time.monotonic()); write(lease.challenge)
        return 0
    except (OSError, ValueError):
        if owner.alive(): owner.terminate()
        return 2
    finally: owner.close()


if __name__ == '__main__': raise SystemExit(main())
