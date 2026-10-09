"""The Data folder dialog: shows where the launcher keeps its files and moves them."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from .config import DATA_DIR, DATA_DIR_ENV, DATA_DIR_FLAG, DATA_DIR_SOURCE, DEFAULT_DATA_DIR
from .storage import _data_folder_has_data, _set_data_location
from .theme import _ACCENT, _ACCENT_CONTRAST, _BG, _BORDER, _DIM_FG, _FG, _ROW_BG
from .widgets import RoundedButton

_OVERRIDE_NOTE = {
    "flag": f"This run was started with {DATA_DIR_FLAG}, which wins over a saved choice.",
    "env": f"This run uses the {DATA_DIR_ENV} variable, which wins over a saved choice.",
}


def _button(parent: tk.Misc, text: str, command, primary: bool = False) -> RoundedButton:
    fill, outline, fg = (_ACCENT, _ACCENT, _ACCENT_CONTRAST) if primary else (_ROW_BG, _BORDER, _FG)
    return RoundedButton(parent, text, command=command, bg=_BG, fill=fill, outline=outline, fg=fg)


class DataFolderDialog:
    """Modal: the folder in use, Change… to pick another, Use default to go back.
    A change is saved for the next start, so the dialog says to restart."""

    def __init__(self, root: tk.Misc, current: Path = DATA_DIR, source: str = DATA_DIR_SOURCE) -> None:
        self._current, self._source = current, source
        self.dialog = tk.Toplevel(root)
        self.dialog.title("Data folder")
        self.dialog.configure(bg=_BG)
        self.dialog.transient(root)
        tk.Label(self.dialog, text="Groups, presets and saved servers are kept in:", bg=_BG, fg=_DIM_FG).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        tk.Label(self.dialog, text=str(current), bg=_BG, fg=_FG, wraplength=480, justify="left").pack(anchor="w", padx=16)
        if source in _OVERRIDE_NOTE:
            tk.Label(self.dialog, text=_OVERRIDE_NOTE[source], bg=_BG, fg=_DIM_FG, wraplength=480, justify="left").pack(
                anchor="w", padx=16, pady=(8, 0)
            )
        actions = tk.Frame(self.dialog, bg=_BG)
        actions.pack(fill="x", padx=16, pady=16)
        _button(actions, "Change…", self._change, primary=True).pack(side="left")
        _button(actions, "Use default", self._use_default).pack(side="left", padx=(6, 0))
        _button(actions, "Close", self.dialog.destroy).pack(side="right")
        self.dialog.grab_set()

    def _change(self) -> None:
        chosen = filedialog.askdirectory(parent=self.dialog, title="Choose the data folder", initialdir=self._current.parent)
        if chosen:
            self.move_to(Path(chosen))

    def _use_default(self) -> None:
        self.move_to(None)

    def move_to(self, new_dir: Path | None) -> None:
        """Save the choice for the next start; copies your files first if you say so."""
        target = DEFAULT_DATA_DIR if new_dir is None else new_dir
        if target.resolve() == self._current.resolve():
            messagebox.showinfo("Data folder", "That is the folder already in use.", parent=self.dialog)
            return
        copy = False
        if not _data_folder_has_data(target):
            copy = messagebox.askyesno(
                "Data folder", f"Copy your groups, presets and saved servers into\n{target}?", parent=self.dialog,
            )
        try:
            _set_data_location(new_dir, copy=copy, current_dir=self._current)
        except OSError as error:
            messagebox.showerror("Data folder", f"Could not switch to {target}: {error}", parent=self.dialog)
            return
        note = f"\n\n{_OVERRIDE_NOTE[self._source]}" if self._source in _OVERRIDE_NOTE else ""
        messagebox.showinfo(
            "Data folder", f"Saved. Close and reopen the launcher to use\n{target}{note}", parent=self.dialog,
        )
        self.dialog.destroy()
