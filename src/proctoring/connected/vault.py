"""Current-user Windows DPAPI storage, additionally bound to this computer.

No plaintext fallback. Tests may explicitly inject a vault; application callers
cannot opt out through configuration or renderer commands.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
import secrets


class VaultError(RuntimeError):
    pass


class WindowsVault:
    def __init__(self):
        if os.name != 'nt':
            raise VaultError('secure_storage_requires_windows')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                machine = winreg.QueryValueEx(key, 'MachineGuid')[0]
            self.binding = hashlib.sha256(('LocalProctoring/Stage2/'+machine).encode()).digest()
        except OSError:
            raise VaultError('device_binding_unavailable') from None

    def _crypt(self, data, decrypt=False):
        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
        def blob(value):
            memory = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
            return Blob(len(value), memory)
        source, entropy, output = blob(data), blob(self.binding), Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
        if not fn(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
            raise VaultError('secure_storage_unavailable')
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            kernel.LocalFree(output.pbData)

    def encrypt(self, data):
        return self._crypt(data)

    def decrypt(self, data):
        return self._crypt(data, True)


def new_device():
    return {'device_id': secrets.token_hex(16), 'device_secret': secrets.token_urlsafe(32)}
