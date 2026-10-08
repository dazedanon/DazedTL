"""An isolated worker must not issue new requests after its app instance is gone."""

import os

from .files import read_json


def alive(workspace, pid, token):
    try:
        current = read_json(workspace / "translation/owner.json", limit=4096)
    except ValueError, OSError:
        return False
    if current != {"pid": pid, "token": token} or not launched_by(pid):
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


def launched_by(pid):
    """Whether the owner started this worker, directly or through a venv launcher."""
    parent = os.getppid()
    if parent == pid:
        return True
    if os.name != "nt":
        return False
    # A Windows venv's python.exe is a launcher that runs the real interpreter
    # as its child, so the owner is the launcher's parent.
    return _parent_of(parent) == pid


def _parent_of(pid):
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_ssize_t
    kernel.Process32FirstW.argtypes = (ctypes.c_ssize_t, ctypes.POINTER(Entry))
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = kernel.Process32FirstW.argtypes
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (ctypes.c_ssize_t,)
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot in {0, -1}:
        return None
    try:
        entry = Entry(dwSize=ctypes.sizeof(Entry))
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32ProcessID == pid:
                return entry.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return None
    finally:
        kernel.CloseHandle(snapshot)
