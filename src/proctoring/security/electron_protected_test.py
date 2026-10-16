"""Explicit Gate 3B fixture support. Never invoked by ordinary app launch.

Requires --allow-short-protection and a current Gate 3A audit. Every actual arm
uses an independent maximum lease <=15 seconds. Results cannot authorize future
protected operation: only the separate nonsuppressing recovery audit can do so.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from .audit import _inject_keys
from .electron_audit import AuditEndpoint, main as run_endpoint
from .electron_binding import NativeIdentity, ancestors, pointer


SHORTCUTS={
    'alt_tab':([0x12,0x09],'BLOCKED_ALT_TAB'),
    'alt_shift_tab':([0x12,0x10,0x09],'BLOCKED_ALT_TAB'),
    'left_win':([0x5b],'BLOCKED_WINDOWS_KEY'),'right_win':([0x5c],'BLOCKED_WINDOWS_KEY'),
    'copy':([0x11,0x43],'BLOCKED_COPY'),'paste':([0x11,0x56],'BLOCKED_PASTE'),
    'ctrl_insert':([0x11,0x2d],'BLOCKED_COPY'),'shift_insert':([0x10,0x2d],'BLOCKED_PASTE'),
    'print_screen':([0x2c],'BLOCKED_SCREENSHOT'),'alt_f4':([0x12,0x73],'BLOCKED_CLOSE'),
    'alt_escape':([0x12,0x1b],'BLOCKED_ALT_ESCAPE'),'ctrl_escape':([0x11,0x1b],'BLOCKED_START_MENU'),
    'ctrl_shift_escape':([0x11,0x10,0x1b],'BLOCKED_TASK_MANAGER'),
}
REQUIRED_CHECKS={f'{focus}:{name}' for focus in ('trusted','pin','external') for name in SHORTCUTS} | {
    'normal_release','focus_containment','wrong_pin','correct_pin','emergency_release',
    'renderer_loss','main_loss','backend_loss','helper_suspension','repeated_cleanup',
    'maximum_lease','normal_input_restored','cross_process_foreground_recovery',
}


def observe_owned_foreground(binding,payload,*,native=None,parent_chain=ancestors,clock=time.monotonic,sleep=time.sleep):
    """Read-only bounded observation of a sibling fixture, never another app."""
    if set(payload)!={'pid','hwnd','duration_seconds'} or type(payload['pid']) is not int or payload['pid']<=0:
        raise ValueError('Invalid owned foreground observation')
    duration=payload['duration_seconds']
    if type(duration) not in (int,float) or not 1.5<=duration<=3.0:
        raise ValueError('Foreground observation must last 1.5–3 seconds')
    if not binding or not binding.valid() or payload['pid']==binding.pid:
        raise ValueError('A distinct verified sibling fixture is required')
    native=native or NativeIdentity(); pid=payload['pid']; hwnd=pointer(payload['hwnd'])
    handle=native.open_process(pid)
    try:
        created=native.creation(handle)
        own_parents=parent_chain(binding.pid); other_parents=parent_chain(pid)
        if (not native.alive(handle) or native.window_owner(hwnd)!=pid or not own_parents or not other_parents or
                own_parents[0]!=other_parents[0] or
                str(Path(native.image(handle)).resolve()).casefold()!=str(Path(binding.image_path).resolve()).casefold()):
            raise ValueError('Foreign foreground target is not an owned sibling Electron fixture')
        started=clock(); samples=[]
        while clock()-started<duration:
            if not native.alive(handle) or native.creation(handle)!=created or native.window_owner(hwnd)!=pid:
                raise ValueError('Owned foreground target identity changed during observation')
            current=int(native.u.GetForegroundWindow() or 0)
            kind='none' if not current else 'exam' if binding.allows(current) else 'foreign' if current==hwnd else 'other'
            sample={'at':clock(),'hwnd':hex(current),'kind':kind}
            if not samples or samples[-1]['hwnd']!=sample['hwnd'] or samples[-1]['kind']!=kind:
                if len(samples)>=101: raise ValueError('Foreground transitions exceeded the bounded observer')
                samples.append(sample)
            sleep(.02)
        return {'target':{'pid':pid,'created':created,'hwnd':hex(hwnd)},'started_at':started,'ended_at':clock(),'samples':samples}
    finally: native.close(handle)


class ProtectedEndpoint(AuditEndpoint):
    def __init__(self,output,package_root,config,*,recovery_report):
        super().__init__(output,package_root,config)
        self.client.config=replace(self.client.config,validation_report=Path(recovery_report))

    def command(self,name,payload):
        if not isinstance(payload,dict): raise ValueError('Payload must be an object')
        if name in {'audit.enable','audit.record','audit.finish'}:
            raise ValueError('Recovery-audit operations are not available in a protected test')
        if name=='test.enable':
            maximum=payload.get('max_session_seconds')
            if set(payload)!={'max_session_seconds'} or type(maximum) not in (int,float) or not .5<=maximum<=15:
                raise ValueError('Explicit protected test must use an independent lease of 0.5–15 seconds')
            self.client._test_lease_seconds=maximum
            self.client.arm()  # Current machine, policy and build Gate 3A validation is mandatory.
            return self.state()
        if name=='test.foreground':
            if payload: raise ValueError('Unexpected foreground fields')
            binding=self.client.binding
            if not binding or not binding.valid(): raise ValueError('Verified fixture binding required')
            # Read-only precondition: never arm, inject input or steal focus here.
            current=int(binding.native.u.GetForegroundWindow() or 0)
            return {'owned_foreground':binding.allows(current)}
        if name=='test.shortcut':
            if set(payload)!={'name'} or not isinstance(payload['name'],str) or payload['name'] not in SHORTCUTS:
                raise ValueError('Only named existing-policy shortcuts may be exercised')
            if not self.client.armed or not self.client.binding or not self.client.binding.valid():
                raise ValueError('Verified actively protected fixture required before injecting test keys')
            keys,event_type=SHORTCUTS[payload['name']]
            injection=_inject_keys(keys,verified_binding=self.client.binding)
            return {**self.state(),'expected_event':event_type,'injection':injection}
        if name=='test.events':
            if payload: raise ValueError('Unexpected event fields')
            events=self.client.drain_events()
            return {**self.state(),'events':events[-250:],'omitted_count':max(0,len(events)-250)}
        if name=='test.foreground_observe':
            observation=observe_owned_foreground(self.client.binding,payload)
            return {**self.state(),'foreground_observation':observation}
        if name in {'test.normal_input','test.unprotected_input'}:
            native=self.client.diagnostics
            if name=='test.normal_input':
                if payload: raise ValueError('Unexpected normal input fields')
                keys=[0x41]
            else:
                if set(payload)!={'name'} or payload['name'] not in ('a','insert'): raise ValueError('Only owned unprotected A/Insert probes are supported')
                keys=[0x41 if payload['name']=='a' else 0x2d]
            if (self.client.armed or not self.client.binding or not self.client.binding.valid() or
                    any(native.get(field) is not False for field in ('armed','hook_installed','hotkey_registered'))):
                raise ValueError('Confirmed native release and exact fixture foreground are required')
            injection=_inject_keys(keys,verified_binding=self.client.binding)
            return {**self.state(),'injection':injection}
        if name=='test.record':
            if (set(payload)!={'name','passed','detail'} or payload['name'] not in REQUIRED_CHECKS or
                    type(payload['passed']) is not bool or not isinstance(payload['detail'],str) or len(payload['detail'])>2000):
                raise ValueError('Invalid protected native check')
            if payload['name'] in self.checks: raise ValueError('Protected check already recorded')
            self.checks[payload['name']]={**payload,'kind':'native_protected_test'}
            return self.state()
        if name=='test.finish':
            if payload and not (set(payload)=={'persist'} and payload['persist'] is False): raise ValueError('Unexpected report fields')
            self.client._validate_audit()
            report={'schema':1,'frontend':'electron','mode':'protected_validation','blocking_enabled':True,
                'passed':self.client._audit_valid and REQUIRED_CHECKS==set(self.checks) and all(c['passed'] for c in self.checks.values()),
                'identity':self.client._identity,'generated_at':datetime.now(timezone.utc).isoformat(),
                'checks':list(self.checks.values()),'missing_checks':sorted(REQUIRED_CHECKS-set(self.checks)),
                'limitations':['Owned injected tests are separate from physical operator validation.','This report is not a recovery-audit authorization.']}
            if payload.get('persist',True):
                self.output.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.output.with_suffix(self.output.suffix+'.partial')
                temporary.write_text(json.dumps(report,indent=2),encoding='utf-8'); temporary.replace(self.output)
            return {**self.state(),'report':report}
        return super().command(name,payload)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,add_help=False)
    parser.add_argument('--allow-short-protection',action='store_true')
    parser.add_argument('--recovery-report',type=Path,required=True)
    options,remaining=parser.parse_known_args(argv)
    if not options.allow_short_protection: parser.error('Explicit --allow-short-protection is required')
    os.environ.pop('PROCTORING_ELECTRON_AUDIT',None)
    def factory(output,package_root,config):
        return ProtectedEndpoint(output,package_root,config,recovery_report=options.recovery_report)
    return run_endpoint(remaining,endpoint_factory=factory,audit_only=False)


if __name__=='__main__': raise SystemExit(main())
