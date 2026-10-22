# core/procs.py
"""Small process and version helpers with no network imports — shared by
the updater (core/updater.py) and the installer window
(core/installer.py), which is built without the network stack."""
import os
import re
import time


def parse_version(text) -> tuple | None:
    """'v2.3.0' / '2.3' / 'ModbusReader 2.3.1' → (2, 3, 0) …; None if no number."""
    m = re.search(r"(\d+)(?:[._](\d+))?(?:[._](\d+))?", str(text or ""))
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def posix_alive(pid: int) -> bool:
    try:
        # Our own child that has exited is a zombie until reaped — still
        # "there" for kill(0). Reap it; anyone else's raises ChildProcessError.
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                        # exists, belongs to another user
    return True


def wait_for_exit(pids: list[int], timeout_s: float) -> bool:
    """True once every pid has exited (or never existed)."""
    if os.name != "nt":
        # No handle to wait on: poll (Linux, macOS).
        deadline = time.monotonic() + timeout_s
        while any(posix_alive(int(p)) for p in pids):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    k32.WaitForSingleObject.restype = ctypes.c_uint32
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    ok = True
    for pid in pids:
        h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            continue                       # already gone
        try:
            if k32.WaitForSingleObject(h, int(timeout_s * 1000)) != 0:
                ok = False                 # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(h)
    return ok
