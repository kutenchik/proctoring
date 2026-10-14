"""Retain verified build bytes without hashing under an active control lease.

Windows sharing locks protect the existing fingerprinted resources from ordinary
write/delete opens. This is a local consistency guard, not administrator anti-tamper.
No input hooks, process control, or hardware access occur here.
"""
import copy
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from .electron_validation import artifact_paths, runtime_identity, runtime_resources


class _FileInfo(ctypes.Structure):
    _fields_ = [('attributes',wintypes.DWORD),('created',wintypes.FILETIME),
                ('accessed',wintypes.FILETIME),('written',wintypes.FILETIME),
                ('volume',wintypes.DWORD),('size_high',wintypes.DWORD),
                ('size_low',wintypes.DWORD),('links',wintypes.DWORD),
                ('index_high',wintypes.DWORD),('index_low',wintypes.DWORD)]


class NativeResourceLocks:
    def __init__(self):
        if os.name != 'nt': raise OSError('Protected resource verification requires Windows')
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        for name,args,result in (
            ('CreateFileW',[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                            wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE],wintypes.HANDLE),
            ('GetFileInformationByHandle',[wintypes.HANDLE,ctypes.POINTER(_FileInfo)],wintypes.BOOL),
            ('CloseHandle',[wintypes.HANDLE],wintypes.BOOL),
        ):
            function=getattr(self.k,name); function.argtypes=args; function.restype=result

    def open(self,path,directory=False):
        # Files: READ access, share READ only. Existing writers (including write
        # mappings) conflict; new writers/deleters cannot acquire access later.
        # Directories: deny rename/delete, but permit normal reads/cache creation.
        handle=self.k.CreateFileW(str(path),0x80 if directory else 0x80000000,
                                  3 if directory else 1,None,3,
                                  0x00200000 | (0x02000000 if directory else 0),None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(),f'Cannot retain build resource: {path}')
        return handle

    def identity(self,handle):
        info=_FileInfo()
        if not self.k.GetFileInformationByHandle(handle,ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x400: raise ValueError('Reparse-point build resources are unsupported')
        return (info.volume,info.index_high,info.index_low,info.size_high,info.size_low,
                info.written.dwHighDateTime,info.written.dwLowDateTime,info.attributes)

    def close(self,handle):
        if not self.k.CloseHandle(handle): raise ctypes.WinError(ctypes.get_last_error())


class VerifiedResources:
    """Full verification before helper preparation; cheap same-files check at arm.

    Locks remain held until adapter.close(), including after native release, so
    audit finalization still observes the verified build. There is no stat-only
    cache: retained handles deny changing the hashed bytes in the first place.
    """
    def __init__(self,binding,package_root=None,*,native=None):
        self.native=native or NativeResourceLocks()
        self.binding=binding; self.package_root=package_root
        self.runtime=copy.deepcopy(binding.runtime)
        self.host=str(Path(binding.image_path).resolve()).casefold()
        self.retained=[]; self.closed=False; self.identity=None
        try:
            self.root,self.files=self._files()
            directories={self.root}
            for path in self.files:
                directories.update(parent for parent in path.parents if parent.is_relative_to(self.root))
            for path in sorted(directories,key=lambda p:(len(p.parts),str(p))): self._retain(path,True)
            for path in sorted(self.files): self._retain(path,False)
            # Enumeration and path identities are checked after all locks exist,
            # before hashing, then again afterwards. No partial lock set is used.
            self.validate()
            self.identity=runtime_identity(binding,package_root)
            self.validate()
        except BaseException:
            self.close()
            raise

    def _files(self):
        root,paths,_,app_root=runtime_resources(self.binding,self.package_root)
        files=frozenset(paths+artifact_paths(app_root))
        for path in files:
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                raise ValueError('Recovery fingerprint contains a missing or unsafe resource')
        return root,files

    def _retain(self,path,directory):
        handle=self.native.open(path,directory)
        try: identity=self.native.identity(handle)
        except BaseException:
            self.native.close(handle)
            raise
        self.retained.append((path,directory,handle,identity))

    def validate(self):
        if self.closed or not self.retained: raise ValueError('Verified build resources are no longer retained')
        if self.binding.runtime != self.runtime or str(Path(self.binding.image_path).resolve()).casefold()!=self.host:
            raise ValueError('Electron host runtime changed after resource verification')
        root,files=self._files()
        if root!=self.root or files!=self.files:
            raise ValueError('Build resource set changed; close the application and rerun recovery validation')
        for path,directory,handle,identity in self.retained:
            # Directory timestamps/size change when harmless caches are written;
            # only volume/file-ID identity is relevant for retained directories.
            width=3 if directory else len(identity)
            if self.native.identity(handle)[:width]!=identity[:width]:
                raise ValueError('Retained build resource changed')
            current=self.native.open(path,directory)
            try:
                if self.native.identity(current)[:width]!=identity[:width]:
                    raise ValueError('Build resource path no longer identifies the verified file')
            finally: self.native.close(current)

    def close(self):
        self.closed=True
        failures=[]
        while self.retained:
            _,_,handle,_=self.retained.pop()
            try: self.native.close(handle)
            except OSError as error: failures.append(error)
        if failures: raise OSError('Could not release all retained build resources') from failures[0]
