"""Owned Electron audit endpoint. Never enables shortcut suppression.

Started only by the separate local audit fixture, using inherited NDJSON pipes.
No commands in this module are exposed by normal bridge/preload or remote pages.
The Electron observer supplies native fixture outcomes, including crashed-child
outcomes; missing checks remain failed rather than manufacturing completion.
"""
import argparse
import ctypes
from dataclasses import replace
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
from .electron import ElectronProtection
from .electron_binding import NativeIdentity, ElectronHostBinding
from .electron_validation import MANDATORY_CHECKS, runtime_identity, protection_policy
from .settings import ProtectionConfig


def observe_stalled_helper(client, *, clock=time.monotonic, sleep=time.sleep):
    """Observe the original owner within one audit budget; never terminate it here."""
    started=clock(); deadline=started+6.
    owner=client._helper_process
    handle=getattr(owner,'handle',None)
    if owner is None or handle is None or not owner.alive():
        raise RuntimeError('Stall check requires a live retained helper')
    before=client._request('status',timeout=min(1.,max(0.,deadline-clock())))
    if (client._helper_process is not owner or owner.handle!=handle or not owner.alive() or
            before.get('armed') is not True or before.get('blocking_enabled') is not False):
        raise RuntimeError('Stall check requires the same live armed nonsuppressing helper')
    remaining=deadline-clock()
    if remaining<=0: raise RuntimeError('Stalled loop cleanup exceeded the six-second audit deadline')
    try:
        client._request('electron_audit_stall',timeout=remaining)
    except RuntimeError as error:
        request_error=str(error)
        # An injection rejection, protocol failure or timeout is not evidence
        # that the intended fault ran. Only the observed EOF path is eligible.
        if request_error!='Protection helper exited': raise
    else:
        raise RuntimeError('Stall command returned without independent helper termination')
    returned=clock(); alive_at_return=owner.alive()
    while True:
        if client._helper_process is not owner or owner.handle!=handle:
            raise RuntimeError('Retained helper identity changed during stall observation')
        now=clock()
        if now>deadline: raise RuntimeError('Stalled loop cleanup was not confirmed within six seconds')
        if not owner.alive():
            confirmed=clock()
            if confirmed>deadline: raise RuntimeError('Stalled loop cleanup was not confirmed within six seconds')
            return {'helper_pid':owner.pid,'budget_seconds':6.,'request_error':request_error,
                    'request_return_seconds':returned-started,'alive_at_request_return':alive_at_return,
                    'death_confirmed_seconds':confirmed-started,'termination_confirmed':True,
                    'observation_only':True}
        remaining=deadline-clock()
        if remaining<=0: raise RuntimeError('Stalled loop cleanup was not confirmed within six seconds')
        sleep(min(.01,remaining))


def suspend_owned_helper(client):
    owner=client._helper_process
    if owner is None or not owner.alive(): raise ValueError('No verified hook owner')
    native=NativeIdentity()
    # Owner.handle remains retained throughout; acquire suspension permission
    # for that still-live process and cross-check creation identity before use.
    query=native.open_process(owner.pid)
    try: created=native.creation(query)
    finally: native.close(query)
    handle=native.k.OpenProcess(0x00101800,False,owner.pid)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not owner.alive() or native.creation(handle)!=created: raise ValueError('Helper identity changed')
        ntdll=ctypes.WinDLL('ntdll')
        ntdll.NtSuspendProcess.argtypes=[wintypes.HANDLE]; ntdll.NtSuspendProcess.restype=ctypes.c_long
        if ntdll.NtSuspendProcess(handle)!=0: raise OSError('Owned helper suspension failed')
        deadline=time.monotonic()+5.
        while owner.alive() and time.monotonic()<deadline: time.sleep(.03)
        if owner.alive(): raise RuntimeError('Guardian failed to terminate suspended helper')
        return {'termination_confirmed':True,'helper_pid':owner.pid}
    finally:
        # Test failure must still release its exact owner before returning.
        if owner.alive(): owner.terminate_and_wait(timeout=1.)
        native.close(handle)


class AuditEndpoint:
    def __init__(self,output,package_root=None,config=None):
        self.output=Path(output)
        self.package_root=package_root
        effective=replace(config or ProtectionConfig(),enabled=True,validation_report=self.output)
        self.client=ElectronProtection(effective,package_root=package_root)
        self.identity=None
        self.last_progress=None
        self.helper_created=None
        native=NativeIdentity(); handle=native.open_process(os.getpid())
        try: self.backend_created=native.creation(handle)
        finally: native.close(handle)
        self.native_owners={'backend':{'kind':'backend','pid':os.getpid(),'created':self.backend_created}}
        self.checks={}
        self.stopped=False

    def state(self):
        owner=self.client._helper_process
        if owner and owner.alive() and self.helper_created is None:
            native=NativeIdentity(); handle=native.open_process(owner.pid)
            try:
                if not owner.alive(): raise RuntimeError('Helper exited during identity observation')
                self.helper_created=native.creation(handle)
            finally: native.close(handle)
        if owner and self.helper_created:
            self.native_owners['helper']={'kind':'helper','pid':owner.pid,'created':self.helper_created}
        native_status=self.client.diagnostics
        if native_status.get('guardian_pid') and native_status.get('guardian_created'):
            self.native_owners['guardian']={'kind':'guardian','pid':native_status['guardian_pid'],'created':native_status['guardian_created']}
        return {'protection':self.client.public_state(),'native':self.client.diagnostics,
                'helper_pid':owner.pid if owner else None,
                'helper_created':self.helper_created,'helper_alive':bool(owner and owner.alive()),
                'backend_pid':os.getpid(),'backend_created':self.backend_created,
                'protection_policy':protection_policy(self.client.config),'audit_identity':self.identity,
                'native_owners':list(self.native_owners.values())}

    def command(self,name,payload):
        if not isinstance(payload,dict): raise ValueError('Payload must be an object')
        shapes={'host.bind':{'launch_id','host_pid','windows','runtime'},
                'host.progress':{'lease_id','sequence','nonce','main_sequence'},
                'audit.enable':{'max_session_seconds'},'audit.stall_controller':{'seconds'},
                'audit.process_gone':{'pid','created'},'audit.record':{'name','passed','detail'}}
        shapes['audit.binding_rejected']={'candidate'}
        if name=='audit.finish' and set(payload)=={'persist'} and payload['persist'] is False: shapes[name]={'persist'}
        if set(payload)!=shapes.get(name,set()): raise ValueError('Unexpected audit payload fields')
        if name=='host.bind':
            self.client.configure_host(payload)
            # configure_host already computed the exact identity before the
            # helper lease began. Do not rehash a large package twice here.
            if self.client._identity is None: raise ValueError('Runtime identity could not be established')
            self.identity=json.loads(json.dumps(self.client._identity))
        elif name=='host.progress': self.client.accept_progress(payload); self.last_progress=dict(payload)
        elif name=='audit.enable':
            if set(payload)!={'max_session_seconds'} or type(payload['max_session_seconds']) not in (int,float) or not .5<=payload['max_session_seconds']<=15:
                raise ValueError('Audit requires a maximum lease of 0.5–15 seconds')
            self.client._request('electron_enable',timeout=5,blocking=False,foreground_poll_ms=100,
                                 max_session_seconds=payload['max_session_seconds'])
        elif name=='audit.release': self.client.release('normal_disable')
        elif name=='audit.status': pass
        elif name=='audit.binding_rejected':
            original=self.client.binding
            candidate=payload['candidate']
            if original is None or not isinstance(candidate,dict): raise ValueError('Prepared fixture binding required')
            attached={**candidate,'host_created':original.created,'stamp':hex(original.stamp_value)}
            try:
                probe=ElectronHostBinding(attached,expected_launch_id=self.client.expected_launch_id,attached=True)
            except (ValueError,OSError) as error:
                return {**self.state(),'binding_rejected':True,'detail':str(error)[:300]}
            probe.close()
            raise RuntimeError('Candidate binding was unexpectedly accepted')
        elif name=='audit.process_gone':
            pid,created=payload.get('pid'),payload.get('created')
            if (set(payload)!={'pid','created'} or type(pid) is not int or not 0<pid<=0xffffffff or
                    not isinstance(created,str) or not created.isdecimal() or not 1<=len(created)<=24):
                raise ValueError('Invalid observed fixture identity')
            native=NativeIdentity()
            try: handle=native.open_process(pid)
            except OSError as error:
                if getattr(error,'winerror',None) not in {87,1168}: raise
                gone=True
            else:
                try: gone=native.creation(handle)!=created or not native.alive(handle)
                finally: native.close(handle)
            return {**self.state(),'process_gone':gone}
        elif name=='audit.emergency':
            from .audit import inject_emergency_chord
            if not self.client.binding or not self.client.binding.valid(): raise ValueError('Verified fixture binding required')
            inject_emergency_chord(verified_binding=self.client.binding)
        elif name=='audit.stall_controller':
            seconds=payload.get('seconds')
            if set(payload)!={'seconds'} or type(seconds) not in (int,float) or not 0<seconds<=8: raise ValueError('Invalid bounded stall')
            time.sleep(seconds)
        elif name=='audit.crash': os._exit(23)
        elif name=='audit.loop_failure':
            observation=observe_stalled_helper(self.client)
            return {**self.state(),'loop_failure_observation':observation}
        elif name=='audit.replay':
            if not self.last_progress: raise ValueError('No previous receipt available')
            owner=self.client._helper_process
            before=self.client._request('status')
            if not owner or not owner.alive() or before.get('armed') is not True:
                raise RuntimeError('Replay check requires a live armed fixture')
            try: self.client._request('electron_progress',progress=self.last_progress)
            except RuntimeError as error:
                if str(error)!='Control progress is stale, replayed, or belongs to another launch': raise
                after=self.client._request('status')
                if (self.client._helper_process is not owner or not owner.alive() or after.get('armed') is not True or
                        any(after.get(k)!=before.get(k) for k in ('challenge','control_sequence','challenge_issued_at'))):
                    raise RuntimeError('Replay test did not preserve the same live lease without renewal')
                return {**self.state(),'replay_rejected':True,'detail':'Exact replay rejection; same live armed owner, challenge and issuance deadline unchanged'}
            raise RuntimeError('Replayed receipt unexpectedly accepted')
        elif name=='audit.terminate_helper':
            self.client._terminate_owned_helper(); self.client._recovery('audit_forced_release')
        elif name=='audit.lost_release_ack':
            original=self.client._request
            def missing_ack(command,**kwargs):
                if command=='disable': raise RuntimeError('Owned fixture dropped release acknowledgement')
                return original(command,**kwargs)
            self.client._request=missing_ack
            try: self.client.release('audit_lost_ack')
            finally: self.client._request=original
        elif name=='audit.suspend_helper':
            result=suspend_owned_helper(self.client)
            return {**self.state(),'result':result}
        elif name=='audit.record':
            if set(payload)!={'name','passed','detail'} or payload['name'] not in MANDATORY_CHECKS or type(payload['passed']) is not bool or not isinstance(payload['detail'],str) or len(payload['detail'])>2000:
                raise ValueError('Invalid native audit result')
            if payload['name'] in self.checks: raise ValueError('Audit check already recorded')
            self.checks[payload['name']]={**payload,'kind':'native_audit'}
        elif name=='audit.finish':
            if not self.client.binding or not self.identity: raise ValueError('Audit identity was not established')
            current={**runtime_identity(self.client.binding,self.package_root),'protection_policy':protection_policy(self.client.config)}
            unchanged=current==self.identity
            checks=list(self.checks.values())
            report={'schema':2,'frontend':'electron','mode':'audit_only','blocking_enabled':False,
                'passed':unchanged and MANDATORY_CHECKS==set(self.checks) and all(c['passed'] for c in checks),
                'generated_at':datetime.now(timezone.utc).isoformat(),'identity':self.identity,'checks':checks,
                'missing_checks':sorted(MANDATORY_CHECKS-set(self.checks)),
                'source_unchanged':unchanged,'limitations':['Native fixture outcomes are not physical operator tests.','No shortcut suppression or foreground containment enabled.']}
            if payload.get('persist',True):
                self.output.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.output.with_suffix(self.output.suffix+'.partial')
                temporary.write_text(json.dumps(report,indent=2),encoding='utf-8'); temporary.replace(self.output)
            return {**self.state(),'report':report}
        elif name=='shutdown': self.client.close(); self.stopped=True
        else: raise ValueError('Unknown local audit command')
        return self.state()


def main(argv=None, *, endpoint_factory=AuditEndpoint, audit_only=True):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-pid',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--package-root',type=Path)
    parser.add_argument('--config',type=Path,help='Audit the effective protection timing from this config')
    args=parser.parse_args(argv)
    if os.name!='nt' or not os.environ.get('PROCTORING_HOST_LAUNCH_ID'): raise ValueError('Owned Windows Electron fixture required')
    if audit_only: os.environ['PROCTORING_ELECTRON_AUDIT']='1'
    config=None
    if args.config:
        from proctoring.config import load_config
        config=load_config(args.config).protection
    endpoint=endpoint_factory(args.output,args.package_root,config)
    messages,closed=queue.Queue(maxsize=64),threading.Event()
    def read():
        try:
            while True:
                line=sys.stdin.readline(16385)
                if not line or len(line)>16384 or not line.endswith('\n'): break
                messages.put_nowait(json.loads(line))
        except (OSError,ValueError,queue.Full): pass
        finally: closed.set()
    threading.Thread(target=read,daemon=True).start()
    cache={}
    try:
        while not endpoint.stopped and not closed.is_set():
            try: request=messages.get(timeout=.03)
            except queue.Empty: continue
            identifier=request.get('id') if isinstance(request,dict) else None
            try:
                if not isinstance(request,dict) or set(request)!={'version','id','command','payload'} or type(request['version']) is not int or request['version']!=1 or not isinstance(identifier,str) or not 1<=len(identifier)<=128:
                    raise ValueError('Invalid audit envelope')
                fingerprint=json.dumps(request,sort_keys=True,separators=(',',':'))
                if identifier in cache:
                    previous,response=cache[identifier]
                    if previous!=fingerprint: raise ValueError('Request ID already belongs to another audit command')
                else:
                    if request['command']=='host.bind' and request['payload'].get('host_pid')!=args.parent_pid:
                        raise ValueError('Host must be the audit launcher')
                    response={'version':1,'id':identifier,'ok':True,'result':endpoint.command(request['command'],request['payload'])}
            except Exception as error: response={'version':1,'id':identifier,'ok':False,'error':{'code':'audit_rejected','message':str(error)[:600]}}
            if identifier not in cache:
                cache[identifier]=(json.dumps(request,sort_keys=True,separators=(',',':')),response)
            if len(cache)>128: cache.pop(next(iter(cache)))
            sys.stdout.write(json.dumps(response,allow_nan=False)+'\n'); sys.stdout.flush()
    finally: endpoint.client.close()
    return 0


if __name__=='__main__': raise SystemExit(main())
