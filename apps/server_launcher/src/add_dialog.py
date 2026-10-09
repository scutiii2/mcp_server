"""The Servers tab's Add dialog: collect several projects, then add them at once."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox

from .config import SELF_DIR_NAME
from .discovery import read_project_spec
from .models import LaunchSpec
from .specs import SPEC_FILE_NAME, SpecError, build_manual_spec
from .theme import _ACCENT, _ACCENT_CONTRAST, _BG, _BORDER, _DIM_FG, _FG, _FIELD_BG, _ROW_BG, _ROW_SELECTED
from .widgets import RoundedButton


def check_folder(folder: Path, taken_keys: set[str]) -> tuple[LaunchSpec | None, str | None]:
    """The spec a project folder offers (its run.srvlnchr, else its run.bat), or the reason it cannot be added."""
    if folder.name == SELF_DIR_NAME:
        return None, f"{folder.name} is this launcher, not a server."
    try:
        spec = read_project_spec(folder)
    except SpecError as error:
        return None, f"{folder.name}: {error}."
    if spec is None:
        return None, (
            f"{folder.name} has no launchable {SPEC_FILE_NAME} or run.bat "
            "(it must start a python module or an npm script). Use Manual setup to describe it by hand."
        )
    if spec.key in taken_keys:
        return None, f"{spec.label} is already in the list."
    return spec, None


def _button(parent: tk.Misc, text: str, command: Callable[[], None], primary: bool = False) -> RoundedButton:
    fill, outline, fg = (_ACCENT, _ACCENT, _ACCENT_CONTRAST) if primary else (_ROW_BG, _BORDER, _FG)
    return RoundedButton(parent, text, command=command, bg=_BG, fill=fill, outline=outline, fg=fg)


class AddServersDialog:
    """Modal list of projects. Each is checked as it is picked, so the list holds
    only servers that will be added; Add all hands their specs back."""

    def __init__(
        self, root: tk.Misc, taken_keys: set[str], on_add: Callable[[list[LaunchSpec]], None], initialdir: Path | None = None,
    ) -> None:
        self._root, self._taken, self._on_add, self._initialdir = root, set(taken_keys), on_add, initialdir
        self._specs: list[LaunchSpec] = []
        self.dialog = tk.Toplevel(root)
        self.dialog.title("Add servers")
        self.dialog.configure(bg=_BG)
        self.dialog.transient(root)
        tk.Label(
            self.dialog, text=f"Project folders with a {SPEC_FILE_NAME} or run.bat", bg=_BG, fg=_DIM_FG,
        ).pack(anchor="w", padx=16, pady=(16, 4))
        self._list = tk.Listbox(
            self.dialog, width=70, height=8, selectmode="extended", bg=_FIELD_BG, fg=_FG, selectbackground=_ROW_SELECTED,
            selectforeground=_FG, highlightthickness=1, highlightbackground=_BORDER, relief="flat", activestyle="none",
        )
        self._list.pack(fill="both", expand=True, padx=16)
        actions = tk.Frame(self.dialog, bg=_BG)
        actions.pack(fill="x", padx=16, pady=16)
        _button(actions, "Add folder…", self._pick).pack(side="left")
        _button(actions, "Manual setup…", self._manual).pack(side="left", padx=(6, 0))
        _button(actions, "Remove from list", self._drop_selected).pack(side="left", padx=(6, 0))
        _button(actions, "Cancel", self.dialog.destroy).pack(side="right")
        _button(actions, "Add all", self._confirm, primary=True).pack(side="right", padx=(0, 6))
        self.dialog.grab_set()

    def add_folder(self, folder: Path) -> bool:
        """Check a folder and list it; False (after telling the user) if it cannot be added."""
        folder = folder.resolve()
        if any(folder == spec.project_dir for spec in self._specs):
            return False
        spec, error = check_folder(folder, self._taken)
        if spec is None:
            messagebox.showerror("Add servers", error, parent=self.dialog)
            return False
        self._list_spec(spec)
        return True

    def add_spec(self, spec: LaunchSpec) -> bool:
        """List a hand-written spec; False (after telling the user) if its folder name is taken."""
        if spec.key in self._taken:
            messagebox.showerror("Add servers", f"{spec.label} is already in the list.", parent=self.dialog)
            return False
        self._list_spec(spec)
        return True

    def _list_spec(self, spec: LaunchSpec) -> None:
        self._specs.append(spec)
        self._taken.add(spec.key)
        self._list.insert("end", f"{spec.label}   {spec.project_dir}")

    def _pick(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.dialog, title=f"Choose a project folder with a {SPEC_FILE_NAME} or run.bat", initialdir=self._initialdir,
        )
        if chosen:
            self._initialdir = Path(chosen).parent
            self.add_folder(Path(chosen))

    def _manual(self) -> None:
        ManualSetupDialog(self.dialog, self.add_spec, self._initialdir)

    def _drop_selected(self) -> None:
        for index in reversed(self._list.curselection()):
            self._taken.discard(self._specs.pop(index).key)
            self._list.delete(index)

    def _confirm(self) -> None:
        if not self._specs:
            messagebox.showinfo("Add servers", "Add at least one server.", parent=self.dialog)
            return
        specs = list(self._specs)
        self.dialog.destroy()
        self._on_add(specs)


class ManualSetupDialog:
    """Form for a project that has no run file: one folder, and the lines the
    launcher needs, typed by hand. Hands a validated spec to ``on_spec``."""

    def __init__(self, parent: tk.Misc, on_spec: Callable[[LaunchSpec], bool], initialdir: Path | None = None) -> None:
        self._on_spec, self._initialdir = on_spec, initialdir
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Manual setup")
        self.dialog.configure(bg=_BG)
        self.dialog.transient(parent)
        self._folder, self._label, self._venv, self._module = (tk.StringVar() for _ in range(4))
        self._port_var, self._port = tk.StringVar(), tk.StringVar(value="8000")
        self._runtime, self._args = tk.StringVar(value="python"), tk.BooleanVar(value=False)

        folder_row = self._row("Project folder")
        self._entry(folder_row, self._folder).pack(side="left", fill="x", expand=True)
        _button(folder_row, "Browse…", self._browse).pack(side="left", padx=(6, 0))
        self._entry(self._row("Name (optional)"), self._label).pack(fill="x")
        runtime_row = self._row("Runs with")
        for value, text in (("python", "python  (.venv_<id> and -m <module>)"), ("node", "node  (npm run <script>)")):
            tk.Radiobutton(
                runtime_row, text=text, value=value, variable=self._runtime, bg=_BG, fg=_FG, selectcolor=_FIELD_BG,
                activebackground=_BG, activeforeground=_FG,
            ).pack(anchor="w")
        self._entry(self._row("Venv id: the x of .venv_x (python only)"), self._venv).pack(fill="x")
        self._entry(self._row("Module (python) or npm script (node)"), self._module).pack(fill="x")
        self._entry(self._row("Port env var (optional, else <FOLDER>_PORT)"), self._port_var).pack(fill="x")
        self._entry(self._row("Default port"), self._port).pack(fill="x")
        env_row = self._row("Other env vars, one NAME=value per line (optional)")
        self._env = tk.Text(env_row, width=50, height=4, bg=_FIELD_BG, fg=_FG, insertbackground=_FG, relief="flat")
        self._env.pack(fill="x")
        tk.Checkbutton(
            self.dialog, text="Accepts extra args", variable=self._args, bg=_BG, fg=_FG, selectcolor=_FIELD_BG,
            activebackground=_BG, activeforeground=_FG,
        ).pack(anchor="w", padx=16, pady=(8, 0))
        actions = tk.Frame(self.dialog, bg=_BG)
        actions.pack(fill="x", padx=16, pady=16)
        _button(actions, "Cancel", self.dialog.destroy).pack(side="right")
        _button(actions, "Add", self._submit, primary=True).pack(side="right", padx=(0, 6))
        self.dialog.grab_set()

    def _row(self, caption: str) -> tk.Frame:
        tk.Label(self.dialog, text=caption, bg=_BG, fg=_DIM_FG).pack(anchor="w", padx=16, pady=(10, 2))
        row = tk.Frame(self.dialog, bg=_BG)
        row.pack(fill="x", padx=16)
        return row

    def _entry(self, parent: tk.Misc, variable: tk.StringVar) -> tk.Entry:
        return tk.Entry(parent, textvariable=variable, width=50, bg=_FIELD_BG, fg=_FG, insertbackground=_FG, relief="flat")

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(parent=self.dialog, title="Choose the project folder", initialdir=self._initialdir)
        if chosen:
            self._folder.set(chosen)

    def _submit(self) -> None:
        folder = self._folder.get().strip()
        try:
            if not folder or not Path(folder).is_dir():
                raise SpecError("choose the project folder")
            spec = build_manual_spec(
                Path(folder), self._label.get(), self._runtime.get(), self._venv.get(), self._module.get(),
                self._port_var.get(), self._port.get(), self._env.get("1.0", "end"), self._args.get(),
            )
        except SpecError as error:
            messagebox.showerror("Manual setup", f"{error}.", parent=self.dialog)
            return
        if self._on_spec(spec):
            self.dialog.destroy()
