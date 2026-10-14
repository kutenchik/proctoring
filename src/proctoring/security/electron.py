"""Electron binding adapter; legacy own-PID protection remains unchanged."""
import os
import time
from .electron_binding import ElectronHostBinding
from .electron_validation import runtime_identity, require_electron_validation, protection_policy
from .electron_resources import VerifiedResources
from .windows import WindowsProtection


class ElectronProtection(WindowsProtection):
    def __init__(self, config, *, expected_launch_id=None, package_root=None,
                 binding_factory=ElectronHostBinding, identity_factory=runtime_identity,
                 audit_validator=require_electron_validation):
        super().__init__(config)
        self.expected_launch_id=expected_launch_id or os.environ.get('PROCTORING_HOST_LAUNCH_ID')
        self.package_root=package_root
        self.binding_factory,self.identity_factory,self.audit_validator=binding_factory,identity_factory,audit_validator
        self.binding=None
        self._identity=None
        self._resources=None
        self._audit_valid=False
        self._audit_message='Electron recovery audit required'
        self._phase='disabled' if not config.enabled else 'awaiting_audit'
        self._reason='disabled' if not config.enabled else 'host_binding_required'
        self._terminal=False
        self._confirmed_received=None
        self._confirmed_sequence=0
        self._requested_release_reason=None
        self._owner_cleanup_required=False

    def _reconcile_owner(self):
        """Observe the retained HANDLE without waiting for pipe EOF or native cleanup."""
        if self._closed or self._terminal or self._helper_process is None:
            return
        # Base cleanup takes termination_lock -> condition. Never invert that
        # order or wait behind a bounded terminate/join on a status-read path.
        if not self._termination_lock.acquire(blocking=False): return
        try:
            owner=self._helper_process
            handle=getattr(owner,'handle',None)
            unknown=not handle
            alive=True
            if not unknown:
                try: alive=owner.alive()
                except OSError: unknown=True
            with self._condition:
                if self._closed or self._terminal: return
                unknown=unknown or self._helper_process is not owner or getattr(owner,'handle',None)!=handle
                if not unknown and alive: return
                self._confirmed_received=None
                self._last_status.update(prepared=False,control_confirmed=False,challenge=None)
                self._writer_stop.set()  # Stop renewal; this does not claim native release.
                if unknown:
                    self._owner_cleanup_required=True
                    self._error='Retained helper identity could not be observed'
                    self._armed=False; self._status='RECOVERY'
                    self._terminal=True; self._phase='releasing'
                    self._reason=self._release_reason='helper_identity_unavailable'
                    self._event('PROTECTION_RECOVERY',
                        'Helper identity could not be observed; protection release is unconfirmed',
                        {'reason':self._reason,'release_confirmed':False})
                    self._condition.notify_all()
                else:
                    self._last_status.update(armed=False,blocking_enabled=False,hook_installed=False,
                        hotkey_registered=False,termination_confirmed=True,helper_pid=owner.pid,status='RECOVERY')
                    # Native reason is the last received helper evidence; do
                    # not manufacture a helper message for parent-observed death.
                    self._error='Protection helper exited'
                    self._recovery('helper_exited')
        finally: self._termination_lock.release()

    @property
    def status(self):
        self._reconcile_owner()
        return super().status

    @property
    def armed(self):
        self._reconcile_owner()
        return super().armed

    @property
    def diagnostics(self):
        self._reconcile_owner()
        return super().diagnostics

    def drain_events(self):
        self._reconcile_owner()
        return super().drain_events()

    def configure_window(self,*args): raise ValueError('Electron requires an explicit verified host binding')

    def _validate_audit(self,*,initial=False):
        self._audit_valid=False
        try:
            if self.identity_factory is runtime_identity:
                if initial:
                    self._resources=VerifiedResources(self.binding,self.package_root)
                if self._resources is None:
                    raise ValueError('Build resources were not verified before native preparation; restart application')
                if not initial: self._resources.validate()
                self._identity=dict(self._resources.identity)
            else:
                # Explicit injectable identity implementation for deterministic
                # tests. Production always retains verified Windows resources.
                self._identity=self.identity_factory(self.binding,self.package_root)
            self._identity={**self._identity,'protection_policy':protection_policy(self.config)}
            self.audit_validator(self.config.validation_report,self._identity,self.config.validation_max_age_hours)
            self._audit_valid=True
            self._audit_message='Current Electron native recovery audit passed'
        except (OSError,ValueError) as error:
            self._audit_message=str(error)[:600]

    def configure_host(self,payload):
        if self.binding or self._terminal: raise ValueError('Electron host binding cannot be replaced; restart application')
        binding=self.binding_factory(payload,expected_launch_id=self.expected_launch_id)
        try:
            self.binding=binding
            self._hwnd=binding.hwnd
            self._validate_audit(initial=True)
            self._phase='preparing'
            self._spawn()
            response=self._request('electron_prepare',timeout=self.config.startup_timeout_seconds,
                binding=binding.payload(),heartbeat_timeout=self.config.heartbeat_timeout_seconds)
            self._reconcile_owner()
            with self._condition:
                if self._terminal or not response.get('prepared'): raise RuntimeError('Native helper did not confirm host preparation')
                self._phase='preparing' if self._audit_valid else 'awaiting_audit'
                self._reason='control_progress_required' if self._audit_valid else 'awaiting_audit'
            return self.binding_status()
        except BaseException:
            with self._condition:
                if not self._terminal: self._terminal=True; self._phase='fault'; self._reason='native_fault'
            try: self._terminate_owned_helper()
            finally:
                try: binding.close(); self.binding=None
                finally:
                    if self._resources: self._resources.close(); self._resources=None
            raise

    @property
    def challenge(self):
        self._reconcile_owner()
        with self._condition:
            value=self._last_status.get('challenge')
            return dict(value) if isinstance(value,dict) and not self._terminal else None

    def binding_status(self):
        self._reconcile_owner()
        valid=bool(self.binding and self.binding.valid() and not self._terminal)
        prepared=valid and bool(self._last_status.get('prepared'))
        fresh=bool(self._confirmed_received is not None and time.monotonic()-self._confirmed_received < self.config.heartbeat_timeout_seconds)
        ready=prepared and fresh and self._audit_valid
        return {'ready':ready,'media_allowed':prepared,'error':None if ready else self._reason,
                'binding_id':self.binding.launch_id if self.binding else None}

    def accept_progress(self,payload):
        # Called only by Qt controller dispatch after a completed domain tick.
        self._reconcile_owner()
        if self._terminal or not self.binding: raise ValueError('No active native binding')
        self._send('electron_progress',progress=payload)
        return True  # queue admission only; binding_status uses helper-confirmed progress

    def heartbeat(self):
        # Deliberately no generic renewal: state readers and CV threads must not
        # conceal a frozen trusted renderer or controller loop.
        self._reconcile_owner()

    @staticmethod
    def _native_failure(reason):
        from .helper import RECOVERY_REASONS
        return reason in RECOVERY_REASONS | {'control_progress_lost','host_identity_lost','guardian_lost'}

    def _consume(self,message):
        # The base consumer notifies a waiting release() caller. Keep derived
        # state in the same RLock transaction so that caller cannot race ahead
        # of classification of the acknowledged terminal status.
        with self._condition:
            unsafe=any(message.get(key) for key in ('armed','prepared','blocking_enabled','hook_installed','hotkey_registered'))
            fault_after_release=(self._phase=='released' and not unsafe and
                message.get('status')=='RECOVERY' and self._native_failure(message.get('reason')))
            if (message.get('kind')=='status' and not fault_after_release and
                    (self._terminal or self._last_status.get('termination_confirmed') is True)):
                # Buffered ACTIVE/prepared messages cannot resurrect a terminal
                # owner. Still settle reply IDs so synchronous callers cannot hang.
                identifier=message.get('request_id')
                if identifier:
                    if unsafe:
                        response={'kind':'error','request_id':identifier,'message':'Helper status arrived after terminal release'}
                    else:
                        response={**self._last_status,'kind':'status','request_id':identifier}
                    self._responses.setdefault(identifier,response)
                self._condition.notify_all()
                return
            super()._consume(message)
            if message.get('kind')!='status': return
            if (self._phase=='releasing' and self._requested_release_reason is not None
                    and message.get('status')!='RECOVERY'):
                # A status queued before disable may arrive after release intent.
                # Keep its actual native flags/reply, but do not undo the pending
                # transition. Only the terminal acknowledgement can finish it.
                return
            sequence=message.get('control_sequence',0)
            if (message.get('control_confirmed') and message.get('prepared') and
                    type(sequence) is int and sequence>self._confirmed_sequence):
                self._confirmed_received=time.monotonic()
                self._confirmed_sequence=sequence
            if message.get('armed'):
                self._phase='active'; self._reason='active'
            elif message.get('status')=='RECOVERY':
                self._terminal=True
                from .helper import RECOVERY_REASONS
                # Electron helper runs in another process; do not rely on its
                # import-side additions to the legacy set existing here.
                failures=RECOVERY_REASONS | {'control_progress_lost','host_identity_lost','guardian_lost'}
                reason=message.get('reason')
                expected=(self._requested_release_reason is not None and
                    reason==self._requested_release_reason and reason not in failures and
                    all(message.get(key) is False for key in ('armed','blocking_enabled','hook_installed','hotkey_registered')))
                if expected and self._phase in {'releasing','released'}:
                    # Repeated status polls/disable replies are idempotent.
                    self._phase='released'; self._reason=reason
                elif expected and self._phase=='fault':
                    # A late normal reply must not erase a watchdog/fallback
                    # failure which already became authoritative.
                    self._release_reason=self._reason
                else:
                    self._phase='fault'; self._reason=str(reason or 'native_fault')
            elif message.get('prepared'):
                self._phase='preparing' if self._audit_valid else 'awaiting_audit'
                self._reason='ready' if self._audit_valid and message.get('control_confirmed') else ('control_progress_required' if self._audit_valid else 'awaiting_audit')

    def _recovery(self,reason):
        with self._condition:
            if self._terminal and not (self._phase=='released' and self._native_failure(reason)): return
            super()._recovery(reason)
            self._terminal=True; self._phase='fault'; self._reason=reason

    def arm(self):
        self._reconcile_owner()
        if not self.config.enabled: raise RuntimeError('Protection was not explicitly enabled')
        if self._terminal or not self.binding or not self.binding.valid(): raise RuntimeError('Native host binding unavailable')
        if self.armed: return
        # Recheck the retained exact resource set and audit freshness on Start.
        # Full byte hashing happened before helper_prepare, with write/delete
        # denied until close; no package-sized synchronous IO under the lease.
        self._validate_audit()
        if not self._audit_valid: self._reason='audit_incompatible'; raise ValueError(self._audit_message)
        if not self.binding_status()['ready']: raise RuntimeError('Fresh trusted control progress is required')
        self._phase='arming'
        try:
            response=self._request('electron_enable',timeout=self.config.startup_timeout_seconds,blocking=True,
                foreground_poll_ms=self.config.foreground_poll_ms,max_session_seconds=self._test_lease_seconds)
            self._reconcile_owner()
            with self._condition:
                if self._terminal or not self._armed or self._phase!='active' or not response.get('armed') or not response.get('blocking_enabled'):
                    raise RuntimeError('Helper did not confirm current protection')
        except BaseException:
            self._terminate_owned_helper(); self._recovery('protection_startup_failed'); raise

    def release(self,reason):
        with self._condition:
            if self._closed: return
            cleanup_required=self._terminal and self._owner_cleanup_required
            if self._terminal and not cleanup_required: return
            if not cleanup_required:
                self._requested_release_reason=reason
                self._phase='releasing'
        if cleanup_required:
            # Unknown HANDLE/query state did not prove release. Preserve the
            # explicit existing owned-cleanup attempt on controller end/close.
            self._terminate_owned_helper()
            with self._condition:
                if self._last_status.get('termination_confirmed') is not True:
                    raise RuntimeError('Protection release remains unconfirmed')
                self._last_status.update(status='RECOVERY',prepared=False,control_confirmed=False,challenge=None)
                self._owner_cleanup_required=False
                self._phase='fault'
            return
        if self._process is not None:
            try:
                response=self._request('disable',reason=reason)
                if response.get('armed') or response.get('hook_installed') or response.get('hotkey_registered'):
                    raise RuntimeError('Native release was not confirmed')
            except Exception:
                self._terminate_owned_helper(); self._recovery('release_fallback:'+reason)
        with self._condition:
            self._terminal=True
            if self._phase!='fault': self._phase='released'; self._reason=reason

    def public_state(self):
        self._reconcile_owner()
        return {'requested':self.config.enabled,'enabled':self.armed,'state':self._phase,'reason':self._reason,
            'audit':{'valid':self._audit_valid,'message':self._audit_message,'path':str(self.config.validation_report)},
            'challenge':self.challenge}

    def close(self):
        try: super().close()
        finally:
            try:
                if self.binding: self.binding.close(); self.binding=None
            finally:
                if self._resources: self._resources.close(); self._resources=None
