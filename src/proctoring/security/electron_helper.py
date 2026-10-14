"""Electron-specific ownership and control progress layered over legacy helper."""
import os
import time
from .control_lease import ControlLease
from .electron_binding import ElectronHostBinding, NativeIdentity
from .guardian import GuardianClient
from .helper import HelperRuntime, RECOVERY_REASONS
from .policy import HelperLease

RECOVERY_REASONS.update({'control_progress_lost','host_identity_lost','guardian_lost'})


class ElectronHelperRuntime(HelperRuntime):
    def __init__(self, *args, binding_factory=ElectronHostBinding, native_factory=NativeIdentity,
                 guardian_factory=GuardianClient, **kwargs):
        super().__init__(*args, **kwargs)
        self.binding_factory, self.native_factory, self.guardian_factory = binding_factory,native_factory,guardian_factory
        self.binding = self.control = self.guardian = self.desktop_lock = self.native = None
        self.electron_mode = False
        self.terminal = False
        self.audit_fixture = os.environ.get('PROCTORING_ELECTRON_AUDIT') == '1'
        self.retired_guardians = []
        self.released_at = None

    def status(self, request_id=None):
        if not self.electron_mode: return super().status(request_id)
        self.emit({'kind':'status','status':'ACTIVE' if self.lease.armed else ('RECOVERY' if self.terminal else 'PREPARING'),
            'armed':self.lease.armed,'blocking_enabled':self.lease.blocking_enabled,'reason':self.lease.reason,
            'hook_installed':bool(self.backend and self.backend.hook_installed),
            'hotkey_registered':bool(self.backend and self.backend.hotkey_registered),
            'prepared':bool(self.binding and self.desktop_lock and not self.terminal),
            'control_confirmed':bool(self.control and self.control.fresh(self.clock())),
            'control_sequence':self.control.main_sequence if self.control else 0,
            'control_confirmed_at':self.control.confirmed_at if self.control else None,
            'challenge_issued_at':self.control.issued_at if self.control else None,
            'released_at':self.released_at,
            'challenge':self.control.challenge if self.control else None,
            'guardian_pid':self.guardian.owner.pid if self.guardian and self.guardian.owner else None,
            'guardian_created':getattr(self.guardian,'created',None),
            'request_id':request_id})

    def command(self, command):
        action = command.get('command')
        if not str(action).startswith('electron_'):
            if self.electron_mode and action in {'enable','heartbeat'}:
                self.emit({'kind':'error','message':'Legacy renewal cannot control Electron protection','request_id':command.get('request_id')}); return
            return super().command(command)
        request_id = command.get('request_id')
        try:
            now = self.clock()
            if action == 'electron_prepare':
                if self.electron_mode or self.lease.armed or self.terminal: raise ValueError('Helper cannot be prepared twice')
                self.electron_mode = True
                self.control = ControlLease(now,float(command.get('heartbeat_timeout',5.)))
                self.binding = self.binding_factory(command['binding'],expected_launch_id=os.environ.get('PROCTORING_HOST_LAUNCH_ID'),
                    backend_pid=self.parent_pid,attached=True)
                self.native = self.native_factory()
                self.desktop_lock = self.native.desktop_mutex()
                self.guardian = self.guardian_factory()
            elif action == 'electron_progress':
                if not self.control or self.terminal: raise ValueError('Helper has no renewable Electron lease')
                self.control.acknowledge(command['progress'],now)
                if self.lease.armed: self.lease.heartbeat(now)
            elif action == 'electron_enable':
                if self.terminal or self.lease.armed or not self.binding or not self.binding.valid():
                    raise ValueError('Electron binding is not ready for arming')
                if not self.control or not self.control.fresh(now): raise ValueError('Fresh trusted presentation progress is required')
                if not self.guardian: raise ValueError('Independent guardian is required')
                blocking = command.get('blocking')
                if self.audit_fixture and blocking is not False: raise ValueError('Native recovery audit cannot suppress input')
                proposed = HelperLease()
                proposed.arm(now,blocking=blocking,heartbeat_timeout=self.control.timeout,
                    max_session_seconds=command.get('max_session_seconds'))
                poll = command.get('foreground_poll_ms',100)
                if type(poll) not in (int,float) or not 50 <= poll <= 1000: raise ValueError('Invalid foreground interval')
                backend = self.backend_factory(self.binding.pid,self.binding.hwnd,blocking,self.security,self.emergency,
                    host_binding=self.binding,desktop_lock_owned=True)
                try: backend.enable()
                except BaseException: backend.release(); raise
                self.backend,self.lease,self.foreground_poll_seconds = backend,proposed,poll/1000
            elif action == 'electron_audit_stall':
                if not self.audit_fixture or not self.lease.armed or self.lease.blocking_enabled:
                    raise ValueError('Stall injection is available only to a nonsuppressing audit fixture')
                # Bounded fixture fault; independent guardian/sentinel must end
                # this exact helper while its native message loop is stopped.
                time.sleep(4.)
            else: raise ValueError('Unknown Electron protection command')
            self.status(request_id)
        except Exception as error:
            self.emit({'kind':'error','message':str(error),'request_id':request_id})
            # Replays fail closed for renewal but do not disrupt an otherwise
            # healthy lease; failed preparation/arming releases transactionally.
            if action != 'electron_progress': self.release('helper_error')

    def release(self, reason, request_id=None, *, recovery_event=True, recovery_details=None):
        if not self.electron_mode: return super().release(reason,request_id,recovery_event=recovery_event,recovery_details=recovery_details)
        self.terminal = True
        if self.control: self.control.stop()
        # Native hooks before mutex, guardian, pipes or status acknowledgement.
        if self.backend: self.backend.release(); self.backend = None
        if self.released_at is None: self.released_at = self.clock()
        if self.desktop_lock:
            self.native.release_mutex(self.desktop_lock); self.desktop_lock = None
        if self.guardian:
            self.retired_guardians.append(self.guardian); self.guardian = None
        if self.binding: self.binding.close(); self.binding = None
        super().release(reason,request_id,recovery_event=recovery_event,recovery_details=recovery_details)

    def tick(self, *, parent_alive=True, input_open=True):
        self.finish_cleanup()
        if not self.electron_mode: return super().tick(parent_alive=parent_alive,input_open=input_open)
        if self.terminal:
            if not parent_alive or not input_open: self.stop_requested = True
            return
        if not parent_alive or not input_open:
            self.release('parent_exited' if not parent_alive else 'stdin_eof'); self.stop_requested=True; return
        if not self.binding or not self.binding.valid(): self.release('host_identity_lost'); return
        if not self.control or self.control.expired(self.clock()): self.release('control_progress_lost'); return
        try: self.guardian.tick()
        except Exception: self.release('guardian_lost'); return
        super().tick(parent_alive=parent_alive,input_open=input_open)

    def finish_cleanup(self):
        # Outside native keyboard callbacks: hooks were removed before release
        # status, and bounded child cleanup cannot delay input-chain callbacks.
        while self.retired_guardians:
            self.retired_guardians.pop().close()
