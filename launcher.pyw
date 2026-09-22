"""Start one local dashboard server and open it. Used by the desktop shortcut."""

import ctypes
from ctypes import wintypes
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8787"
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]


def ready():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            return json.load(response).get("app") == "cirqa-dashboard"
    except (OSError, ValueError):
        return False


def main():
    # Serialize double-clicks across processes without leaving a lock file behind.
    mutex = kernel.CreateMutexW(None, False, "Local\\CirqaDashboardLauncher")
    if not mutex:
        raise OSError("Unable to acquire launcher mutex")
    try:
        result = kernel.WaitForSingleObject(mutex, 20000)
        if result not in (0, 128):
            raise TimeoutError("Another dashboard launch is still running")
        try:
            if not ready():
                subprocess.Popen(
                    [sys.executable, str(ROOT / "serve.py"), "--no-open"],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    | subprocess.DETACHED_PROCESS,
                )
                for _ in range(60):
                    if ready():
                        break
                    time.sleep(0.25)
                else:
                    raise RuntimeError(
                        "Dashboard did not start. Port 8787 may be occupied."
                    )
            req = urllib.request.Request(
                URL + "/api/sync",
                data=b"",
                headers={"X-CIRQA-Request": "1"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                response.read()
            webbrowser.open(URL)
        finally:
            kernel.ReleaseMutex(mutex)
    finally:
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), "CIRQA dashboard", 0x10)
