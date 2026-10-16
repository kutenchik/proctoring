"""Narrow Windows observations. Names are heuristics, not proof of remote control.

No process handles are opened, programs terminated, user names/IPs collected,
or full inventories retained. Only the current RDP session is verified by WTS.
"""
import ctypes
from ctypes import wintypes as W
import sys

SIGNATURES = {
    'anydesk.exe':'anydesk', 'teamviewer.exe':'teamviewer',
    'teamviewer_service.exe':'teamviewer', 'rustdesk.exe':'rustdesk',
    'remoting_host.exe':'chrome_remote_desktop', 'quickassist.exe':'quick_assist',
    'mstsc.exe':'rdp_client',
}
INSTALL_NAMES = {'anydesk':'anydesk','teamviewer':'teamviewer','rustdesk':'rustdesk',
                 'chrome remote desktop host':'chrome_remote_desktop','quick assist':'quick_assist'}


def classify(names, *, installed=(), process_complete=True, rdp=None):
    running={SIGNATURES[name.casefold()] for name in names if name.casefold() in SIGNATURES}
    matches=[{'category':key,'state':'process_running','active_control':'unverified'} for key in sorted(running)]
    matches += [{'category':key,'state':'installed_not_running' if process_complete else 'installed_running_unknown',
                 'active_control':'unverified'} for key in sorted(set(installed)-running) if key in INSTALL_NAMES.values()]
    if rdp is True:matches.append({'category':'rdp_current_session','state':'active_session','active_control':'os_verified'})
    return {'status':'complete' if process_complete and rdp is not None else 'partial',
            'matches':matches,'rdp_status':'active' if rdp else 'not_remote_current_session' if rdp is False else 'unknown',
            'coverage':'explicit_signatures_only','not_proof_of_absence':True}


def _process_names():
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),
                  ('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',W.DWORD),('cntThreads',W.DWORD),
                  ('th32ParentProcessID',W.DWORD),('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
    kernel.Process32FirstW.argtypes=kernel.Process32NextW.argtypes=[W.HANDLE,ctypes.POINTER(Entry)]
    kernel.Process32FirstW.restype=kernel.Process32NextW.restype=W.BOOL
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle==ctypes.c_void_p(-1).value:raise OSError('snapshot_unavailable')
    matches=[]
    try:
        entry=Entry();entry.dwSize=ctypes.sizeof(entry)
        if not kernel.Process32FirstW(handle,ctypes.byref(entry)):raise OSError('snapshot_unavailable')
        for _ in range(32768):
            name=entry.szExeFile.casefold()
            if name in SIGNATURES:matches.append(name)
            if not kernel.Process32NextW(handle,ctypes.byref(entry)):
                if ctypes.get_last_error()!=18:raise OSError('snapshot_incomplete')
                return matches
        raise OSError('snapshot_limit')
    finally:kernel.CloseHandle(handle)


def _rdp():
    wts=ctypes.WinDLL('wtsapi32',use_last_error=True)
    wts.WTSQuerySessionInformationW.argtypes=[W.HANDLE,W.DWORD,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(W.DWORD)]
    wts.WTSQuerySessionInformationW.restype=W.BOOL
    wts.WTSFreeMemory.argtypes=[ctypes.c_void_p];wts.WTSFreeMemory.restype=None
    def query(kind,ctype):
        buf=ctypes.c_void_p();size=W.DWORD()
        if not wts.WTSQuerySessionInformationW(None,0xffffffff,kind,ctypes.byref(buf),ctypes.byref(size)):raise OSError('session_unavailable')
        try:
            if size.value<ctypes.sizeof(ctype):raise OSError('session_incomplete')
            return ctypes.cast(buf,ctypes.POINTER(ctype)).contents.value
        finally:wts.WTSFreeMemory(buf)
    return query(16,ctypes.c_ushort)==2 and query(8,ctypes.c_int)==0


def installed_categories():
    import winreg
    found=set()
    for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_32KEY,winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',0,winreg.KEY_READ|view) as root:
                    for i in range(min(winreg.QueryInfoKey(root)[0],10000)):
                        try:
                            with winreg.OpenKey(root,winreg.EnumKey(root,i)) as key:
                                name=str(winreg.QueryValueEx(key,'DisplayName')[0]).casefold()
                                if name in INSTALL_NAMES:found.add(INSTALL_NAMES[name])
                        except OSError:continue
            except OSError:continue
    return sorted(found)


def probe(*, installed=()):
    if sys.platform!='win32':return {'status':'unavailable','matches':[],'reason':'windows_required'}
    complete=True
    try:names=_process_names()
    except OSError:names=[];complete=False
    try:rdp=_rdp()
    except OSError:rdp=None
    result=classify(names,installed=installed,process_complete=complete,rdp=rdp)
    if not complete and rdp is None:result['status']='unavailable'
    # Installation enumeration is deliberately not polled; absent registry entries
    # cannot prove a portable/UWP product is not installed.
    result['installation_status']='matched_registry_categories_only'
    return result
