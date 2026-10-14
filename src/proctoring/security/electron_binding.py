"""Exact Electron launch/window identity; separate from legacy PID binding.

This is a local recovery prerequisite, not authentication against an administrator.
Retained process handles and creation times prevent stale-PID ownership. Window
properties distinguish a registered HWND from a destroyed/recycled numeric value.
"""
import ctypes
from ctypes import wintypes
import os
import re
import secrets


def pointer(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}', value):
        raise ValueError('HWND must be an unsigned hexadecimal pointer')
    number = int(value, 16)
    if not 0 < number < 1 << (ctypes.sizeof(ctypes.c_void_p)*8):
        raise ValueError('HWND is outside the native pointer width')
    return number


class NativeIdentity:
    """Small injectable Win32 identity surface. No hooks or input operations."""
    def __init__(self):
        if os.name != 'nt': raise OSError('Electron protection requires Windows')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        signatures = [
            (self.k, 'OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.k, 'GetProcessTimes', [wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4, wintypes.BOOL),
            (self.k, 'WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            (self.k, 'CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
            (self.k, 'TerminateProcess', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            (self.k, 'QueryFullProcessImageNameW', [wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
            (self.k, 'CreateMutexW', [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR],wintypes.HANDLE),
            (self.k, 'ReleaseMutex', [wintypes.HANDLE],wintypes.BOOL),
            (self.k, 'ProcessIdToSessionId', [wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
            (self.u, 'IsWindow', [wintypes.HWND],wintypes.BOOL),
            (self.u, 'GetForegroundWindow', [],wintypes.HWND),
            (self.u, 'GetWindowThreadProcessId', [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)],wintypes.DWORD),
            (self.u, 'SetPropW', [wintypes.HWND,wintypes.LPCWSTR,wintypes.HANDLE],wintypes.BOOL),
            (self.u, 'GetPropW', [wintypes.HWND,wintypes.LPCWSTR],wintypes.HANDLE),
            (self.u, 'RemovePropW', [wintypes.HWND,wintypes.LPCWSTR],wintypes.HANDLE),
        ]
        for dll, name, args, result in signatures:
            function = getattr(dll, name); function.argtypes, function.restype = args, result

    def open_process(self, pid, terminate=False):
        handle = self.k.OpenProcess(0x00101000 | (1 if terminate else 0), False, pid)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def creation(self, handle):
        values = [wintypes.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(handle, *[ctypes.byref(v) for v in values]):
            raise ctypes.WinError(ctypes.get_last_error())
        return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)

    def alive(self, handle):
        result = self.k.WaitForSingleObject(handle, 0)
        if result not in (0, 0x102): raise ctypes.WinError(ctypes.get_last_error())
        return result == 0x102

    def image(self, handle):
        text = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(text))
        if not self.k.QueryFullProcessImageNameW(handle,0,text,ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return text.value

    def close(self, handle): self.k.CloseHandle(handle)
    def window_owner(self, hwnd):
        pid = wintypes.DWORD()
        if not self.u.IsWindow(hwnd) or not self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid)):
            return None
        return pid.value
    def stamp(self, hwnd, name, value):
        if not self.u.SetPropW(hwnd,name,value): raise ctypes.WinError(ctypes.get_last_error())
    def stamped(self, hwnd, name): return int(self.u.GetPropW(hwnd,name) or 0)
    def unstamp(self, hwnd, name): self.u.RemovePropW(hwnd,name)
    def terminate(self, handle, timeout=1.):
        if not self.alive(handle): return
        if not self.k.TerminateProcess(handle, 1) and self.alive(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        if self.k.WaitForSingleObject(handle, max(1,int(timeout*1000))) != 0:
            raise RuntimeError('Owned process termination was not confirmed')

    def desktop_mutex(self):
        # Local\ already scopes Terminal Services sessions. Including the
        # interactive-session ID prevents an alternate account's PID changing it.
        session = wintypes.DWORD()
        if not self.k.ProcessIdToSessionId(os.getpid(),ctypes.byref(session)):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = self.k.CreateMutexW(None,False,f'Local\\LocalProctoring.Protection.{session.value}')
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        result = self.k.WaitForSingleObject(handle,0)
        if result not in (0,0x80):
            self.close(handle)
            raise RuntimeError('Another protected application already owns this interactive desktop')
        return handle
    def release_mutex(self, handle):
        self.k.ReleaseMutex(handle); self.close(handle)


def ancestors(pid):
    import psutil
    return [process.pid for process in psutil.Process(pid).parents()]


class ElectronHostBinding:
    def __init__(self, payload, *, expected_launch_id, backend_pid=None, native=None,
                 parent_chain=ancestors, attached=False):
        self.native = native or NativeIdentity()
        self.handle = None
        self.windows = []
        self.owner = not attached
        if not isinstance(payload,dict): raise ValueError('Invalid Electron binding')
        expected = {'launch_id','host_pid','windows','runtime'} | ({'host_created','stamp'} if attached else set())
        if set(payload) != expected: raise ValueError('Unexpected Electron binding fields')
        launch = payload['launch_id']
        if not isinstance(launch,str) or not re.fullmatch('[a-f0-9]{32}',launch) or launch != expected_launch_id:
            raise ValueError('Electron launch identity does not match inherited launch')
        pid = payload['host_pid']; backend = backend_pid or os.getpid()
        if type(pid) is not int or not 0 < pid <= 0xffffffff or pid == backend:
            raise ValueError('Electron host PID is invalid')
        rows = payload['windows']
        if not isinstance(rows,list) or not 1 <= len(rows) <= 8:
            raise ValueError('One to eight explicit native windows are required')
        windows = []
        for row in rows:
            if not isinstance(row,dict) or set(row) != {'hwnd','role'} or not isinstance(row['role'],str) or row['role'] not in {'exam','dialog'}:
                raise ValueError('Invalid registered window')
            windows.append((pointer(row['hwnd']),row['role']))
        if len(set(w for w,_ in windows)) != len(windows) or sum(r=='exam' for _,r in windows) != 1:
            raise ValueError('Exactly one unique exam HWND is required')
        runtime = payload['runtime']
        if not isinstance(runtime,dict) or set(runtime) != {'electron_version','app_version','build_kind','build_id'}:
            raise ValueError('Runtime identity fields are required')
        if not isinstance(runtime['build_kind'],str) or runtime['build_kind'] not in {'source','packaged'} or not isinstance(runtime['build_id'],str) or not re.fullmatch('[a-f0-9]{64}',runtime['build_id']):
            raise ValueError('Invalid runtime build identity')
        if any(not isinstance(runtime[k],str) or not 1 <= len(runtime[k]) <= 64 for k in ('electron_version','app_version')):
            raise ValueError('Invalid runtime version')
        self.launch_id, self.pid, self.runtime = launch,pid,dict(runtime)
        self.property_name = 'LocalProctoring.Binding.'+launch
        self.stamp_value = pointer(payload['stamp']) if attached else secrets.randbits(ctypes.sizeof(ctypes.c_void_p)*8-1)+1
        try:
            self.handle = self.native.open_process(pid)
            self.created = self.native.creation(self.handle)
            if not self.native.alive(self.handle) or pid not in parent_chain(backend)[:8]:
                raise ValueError('Electron host is not a live ancestor of this backend launch')
            if attached and payload['host_created'] != self.created:
                raise ValueError('Electron PID creation identity changed')
            self.image_path = self.native.image(self.handle)
            for hwnd,role in windows:
                if self.native.window_owner(hwnd) != pid: raise ValueError('HWND is not owned by this Electron host')
                if attached:
                    if self.native.stamped(hwnd,self.property_name) != self.stamp_value:
                        raise ValueError('Registered HWND was destroyed or replaced')
                else:
                    self.native.stamp(hwnd,self.property_name,self.stamp_value)
                self.windows.append((hwnd,role))
            if not self.valid(): raise ValueError('Host identity changed during binding')
        except BaseException:
            self.close(); raise

    @property
    def hwnd(self): return next(hwnd for hwnd,role in self.windows if role=='exam')
    def valid(self):
        return bool(self.handle and self.native.alive(self.handle) and
                    self.native.creation(self.handle)==self.created and
                    all(self.native.window_owner(hwnd)==self.pid and
                        self.native.stamped(hwnd,self.property_name)==self.stamp_value for hwnd,_ in self.windows))
    def allows(self, hwnd): return self.valid() and any(hwnd==value for value,_ in self.windows)
    def payload(self):
        return {'launch_id':self.launch_id,'host_pid':self.pid,'host_created':self.created,
                'stamp':hex(self.stamp_value),'windows':[{'hwnd':hex(w),'role':r} for w,r in self.windows],
                'runtime':dict(self.runtime)}
    def close(self):
        if self.owner:
            for hwnd,_ in self.windows:
                try:
                    if self.native.stamped(hwnd,self.property_name)==self.stamp_value:
                        self.native.unstamp(hwnd,self.property_name)
                except OSError:
                    pass  # Window may already be destroyed; always close the retained process handle.
        self.windows=[]
        if self.handle:
            self.native.close(self.handle); self.handle=None
