"""An isolated worker must not issue new requests after its app instance is gone."""

import os

from .files import read_json


def alive(workspace, pid, token):
    try:
        current = read_json(workspace / "translation/owner.json", limit=4096)
    except ValueError, OSError:
        return False
    if current != {"pid": pid, "token": token} or os.getppid() != pid:
        return False
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        status = wintypes.DWORD()
        return (
            bool(kernel.GetExitCodeProcess(handle, ctypes.byref(status)))
            and status.value == 259
        )
    finally:
        kernel.CloseHandle(handle)
