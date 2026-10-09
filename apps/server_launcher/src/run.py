"""Entry point: `py -m src.run` (see ../run.bat)."""

from __future__ import annotations

import os
import tkinter as tk
from contextlib import contextmanager
from collections.abc import Iterator

from .storage import _migrate_legacy_data
from .window import LauncherWindow


@contextmanager
def _single_instance() -> Iterator[bool]:
    """Keep an OS lock for the GUI lifetime; process exit also releases it.

    The identity is independent of the checkout, executable and data folder.
    Windows scopes the named object to the current desktop session.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, "Local\\ScutiServerLauncher")
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        try:
            yield error != 183  # ERROR_ALREADY_EXISTS
        finally:
            kernel32.CloseHandle(handle)
    else:
        import errno
        import fcntl
        import tempfile
        from pathlib import Path

        path = Path(tempfile.gettempdir()) / f"scuti_server_launcher-{os.getuid()}.lock"
        # Keep the file in place: unlinking it can let two processes lock
        # different inodes. Only the live descriptor determines ownership.
        with path.open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                yield False
            else:
                yield True


def _hide_console_window() -> None:
    """Hides the console window this process was launched from (running
    via `python server_launcher.py` from a shell opens one) once the GUI
    is up - it serves no purpose alongside the Tk window and just looks
    like a leftover terminal. Hidden, not closed: closing the console
    that owns this process's own stdio can take the process down with
    it on Windows. No-op off Windows or if there's no console to hide
    (e.g. launched via pythonw.exe already)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:  # noqa: BLE001 - cosmetic only, never block startup over this
        pass


def main() -> None:
    with _single_instance() as acquired:
        if not acquired:
            return
        _hide_console_window()
        _migrate_legacy_data()
        root = tk.Tk()
        LauncherWindow(root)
        root.mainloop()


if __name__ == "__main__":
    main()
