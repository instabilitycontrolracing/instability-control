"""Which programs are running - without starting a program to ask (efficiency pass, 2026-10-29).

The app used to run Windows' `tasklist` (a whole new process, which itself asks WMI-style questions of every process)
every 4 seconds for "is iRacing's sim open?" and the start-with-iRacing list, all race long. This asks Windows directly
(CreateToolhelp32Snapshot - a few hundred microseconds, no new process). Same answer: the set of running .exe names,
lower case. Anything unexpected falls back to tasklist, exactly as before.
"""
import ctypes, os, subprocess

TH32CS_SNAPPROCESS = 0x00000002
NO_WINDOW = 0x08000000


def _toolhelp():
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not h or h == wintypes.HANDLE(-1).value:
        raise OSError("CreateToolhelp32Snapshot failed")
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        out = set()
        ok = k.Process32FirstW(h, ctypes.byref(e))
        while ok:
            out.add(e.szExeFile.lower())
            ok = k.Process32NextW(h, ctypes.byref(e))
        if not out:
            raise OSError("empty process list")
        return out
    finally:
        k.CloseHandle(h)


def _tasklist():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=8,
                         creationflags=NO_WINDOW).stdout
    return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')}


def running_exes():
    """-> {"iracingsim64dx11.exe", "explorer.exe", ...} (lower case); empty set if it can't be told."""
    if os.name == "nt":
        try:
            return _toolhelp()
        except Exception:
            pass
    try:
        return _tasklist()
    except Exception:
        return set()


def is_running(exe):
    return exe.lower() in running_exes()
