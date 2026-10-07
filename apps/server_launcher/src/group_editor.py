"""Inline editor for a saved group: change each member's flags, remove members, add servers."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from .agent_files import launch_port
from .models import GroupMember, Preset, ServerGroup, ServerTemplate
from .theme import (
    _ACCENT, _ACCENT_CONTRAST, _BG, _BORDER, _DANGER, _DANGER_BORDER, _DIM_FG, _ERROR_FG, _FG, _FIELD_BG, _ROW_BG,
)
from .widgets import RoundedButton, RoundedPanel, ScrollableFrame

_MAX_PORT = 65535


def _entry(parent: tk.Widget, var: tk.StringVar, *, width: int | None = None) -> tk.Entry:
    entry = tk.Entry(
        parent, textvariable=var, bg=_FIELD_BG, fg=_FG, insertbackground=_FG, relief="flat",
        highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_ACCENT,
    )
    if width is not None:
        entry.config(width=width)
    return entry


def _option_menu(parent: tk.Widget, var: tk.StringVar, values: list[str]) -> tk.OptionMenu:
    menu = tk.OptionMenu(parent, var, *values)
    menu.config(
        bg=_FIELD_BG, fg=_FG, activebackground=_BORDER, activeforeground=_FG, relief="flat",
        highlightthickness=1, highlightbackground=_BORDER, bd=0, anchor="w",
    )
    menu["menu"].config(bg=_FIELD_BG, fg=_FG, activebackground=_ACCENT, activeforeground=_ACCENT_CONTRAST, bd=0)
    return menu


class _MemberForm:
    """The editable panel for one group member. An unavailable template (one
    no longer discovered) cannot be edited: its member is kept as it was and
    can only be removed."""

    def __init__(
        self, parent: tk.Widget, member: GroupMember, template: ServerTemplate | None,
        presets: list[Preset], on_remove: Callable[["_MemberForm"], None],
    ) -> None:
        self.member = member
        self.template = template
        self.presets = presets
        self.preset_name = member.preset_name
        self.port_var = tk.StringVar(value=str(member.port))
        self.args_var = tk.StringVar(value=member.extra_args)
        self.env_vars = {
            name: tk.StringVar(value=member.extra_env.get(name, default))
            for name, default in (template.extra_env_vars.items() if template else [])
        }

        self.panel = RoundedPanel(parent, bg=_BG, fill=_ROW_BG, outline=_BORDER)
        body = self.panel.body
        head = tk.Frame(body, bg=_ROW_BG)
        head.pack(fill="x")
        title = template.display_name if template else f"{member.template_key} (unavailable)"
        tk.Label(head, text=title, bg=_ROW_BG, fg=_FG, font=("Segoe UI", 10, "bold")).pack(side="left")
        RoundedButton(
            head, "Remove", command=lambda: on_remove(self),
            bg=_ROW_BG, fill=_ROW_BG, outline=_DANGER_BORDER, fg=_DANGER,
        ).pack(side="right")
        if template is None:
            tk.Label(
                body, text="This server is no longer detected, so it can only be removed.",
                bg=_ROW_BG, fg=_DIM_FG, anchor="w",
            ).pack(fill="x", pady=(6, 0))
            return

        if template.agents:
            self._label_row(body, "Port", f"{launch_port(template, member.port)} (set by its entry agent)")
        else:
            self._field_row(body, "Port", self.port_var)
        for name, var in self.env_vars.items():
            self._field_row(body, name, var)
        if template.supports_args:
            self._field_row(body, "Extra args", self.args_var)
        if presets and not template.agents:
            self._preset_row(body)

    def _label_row(self, parent: tk.Widget, label: str, value: str) -> None:
        row = tk.Frame(parent, bg=_ROW_BG)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text=label, bg=_ROW_BG, fg=_DIM_FG, width=14, anchor="w").pack(side="left")
        tk.Label(row, text=value, bg=_ROW_BG, fg=_FG, anchor="w").pack(side="left")

    def _field_row(self, parent: tk.Widget, label: str, var: tk.StringVar) -> None:
        row = tk.Frame(parent, bg=_ROW_BG)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text=label, bg=_ROW_BG, fg=_DIM_FG, width=14, anchor="w").pack(side="left")
        _entry(row, var).pack(side="left", fill="x", expand=True, ipady=4)

    def _preset_row(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, bg=_ROW_BG)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="Preset", bg=_ROW_BG, fg=_DIM_FG, width=14, anchor="w").pack(side="left")
        names = ["None"] + [preset.name for preset in self.presets]
        self._preset_var = tk.StringVar(value=self.preset_name if self.preset_name in names else "None")
        self._preset_var.trace_add("write", lambda *_: self._apply_preset(self._preset_var.get()))
        _option_menu(row, self._preset_var, names).pack(side="left")

    def _apply_preset(self, name: str) -> None:
        """Choosing a preset fills the fields, like clicking it on the Servers tab."""
        if name == "None":
            self.preset_name = None
            return
        preset = next((p for p in self.presets if p.name == name), None)
        if preset is None:
            return
        self.preset_name = preset.name
        self.port_var.set(str(preset.port))
        for env_name, var in self.env_vars.items():
            if env_name in preset.env_vars:
                var.set(preset.env_vars[env_name])
        if self.template is not None and self.template.supports_args:
            self.args_var.set(preset.args)

    def to_member(self) -> GroupMember:
        """The edited member. Raises ValueError with a user-facing message."""
        if self.template is None:
            return self.member
        if self.template.agents:
            port = self.member.port
        else:
            try:
                port = int(self.port_var.get().strip())
            except ValueError:
                raise ValueError(f"Enter a port number for {self.template.display_name}.") from None
            if not 1 <= port <= _MAX_PORT:
                raise ValueError(f"Port for {self.template.display_name} must be between 1 and {_MAX_PORT}.")
        extra_env = dict(self.member.extra_env)  # keep keys the template no longer lists
        extra_env.update({name: var.get() for name, var in self.env_vars.items()})
        return GroupMember(
            self.member.template_key, port, extra_env,
            self.args_var.get().strip() if self.template.supports_args else self.member.extra_args,
            self.preset_name,
        )


class GroupEditor(tk.Frame):
    """Edit one group in place. Save returns the new member list through
    `on_save`; Cancel discards every change."""

    def __init__(
        self, parent: tk.Widget, *, group: ServerGroup, templates: list[ServerTemplate],
        presets: dict[str, list[Preset]], on_save: Callable[[list[GroupMember]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=_BG)
        self._templates = {template.key: template for template in templates}
        self._presets = presets
        self._on_save = on_save
        self._forms: list[_MemberForm] = []

        header = tk.Frame(self, bg=_BG)
        header.pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(header, text=f"Edit {group.name}", bg=_BG, fg=_FG, font=("Segoe UI", 14, "bold")).pack(side="left")
        RoundedButton(
            header, "Save", command=self._save,
            bg=_BG, fill=_ACCENT, outline=_ACCENT, fg=_ACCENT_CONTRAST, font=("Segoe UI", 10, "bold"),
        ).pack(side="right")
        RoundedButton(
            header, "Cancel", command=on_cancel, bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="right", padx=(0, 6))
        self._error = tk.Label(self, text="", bg=_BG, fg=_ERROR_FG, anchor="w", justify="left", wraplength=520)
        self._error.pack(fill="x", padx=16)

        self._scroll = ScrollableFrame(self, bg=_BG)
        self._scroll.pack(fill="both", expand=True, pady=(4, 0))
        for member in group.members:
            self._add_form(GroupMember(
                member.template_key, member.port, dict(member.extra_env), member.extra_args, member.preset_name,
            ))
        self._build_add_row()

    def _add_form(self, member: GroupMember) -> None:
        form = _MemberForm(
            self._scroll.body, member, self._templates.get(member.template_key),
            self._presets.get(member.template_key, []), self._remove_form,
        )
        form.panel.pack(fill="x", padx=16, pady=(0, 8))
        self._forms.append(form)
        if hasattr(self, "_add_row"):
            self._add_row.pack_forget()
            self._add_row.pack(fill="x", padx=16, pady=(0, 16))

    def _remove_form(self, form: _MemberForm) -> None:
        self._forms.remove(form)
        form.panel.destroy()
        self._error.config(text="")

    def _build_add_row(self) -> None:
        self._add_row = tk.Frame(self._scroll.body, bg=_BG)
        self._add_row.pack(fill="x", padx=16, pady=(0, 16))
        names = {template.display_name: template for template in self._templates.values()}
        if not names:
            return
        self._add_var = tk.StringVar(value=next(iter(names)))
        _option_menu(self._add_row, self._add_var, list(names)).pack(side="left")
        RoundedButton(
            self._add_row, "Add server", command=lambda: self._add_server(names[self._add_var.get()]),
            bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="left", padx=(8, 0))

    def _add_server(self, template: ServerTemplate) -> None:
        self._add_form(GroupMember(
            template.key, template.default_port, dict(template.extra_env_vars), "", None,
        ))
        self._error.config(text="")

    def collect(self) -> list[GroupMember]:
        """The edited members. Raises ValueError with the first problem found."""
        if not self._forms:
            raise ValueError("A group needs at least one server. Add one, or cancel and delete the group.")
        members = [form.to_member() for form in self._forms]
        seen: set[int] = set()
        for member in members:
            template = self._templates.get(member.template_key)
            port = launch_port(template, member.port) if template is not None else member.port
            if port in seen:
                raise ValueError(f"Port {port} is used by more than one server in this group.")
            seen.add(port)
        return members

    def _save(self) -> None:
        try:
            members = self.collect()
        except ValueError as error:
            self._error.config(text=str(error))
            return
        self._on_save(members)
