"""Entry point: `py -m src.run` (see ../run.bat)."""

from __future__ import annotations

import os
import tkinter as tk

from .window import LauncherWindow


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
    _hide_console_window()
    root = tk.Tk()
    LauncherWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
