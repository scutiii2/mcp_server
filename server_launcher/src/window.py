"""The Tk launcher window: tabs, sidebar, detail panes and instance lifecycle."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

from .config import _EXTRA_ARGS_HINTS, _POLL_MS, _RESTART_WAIT_SECONDS, ASSETS_DIR
from .discovery import discover_templates
from .instance import Instance
from .models import GroupMember, Preset, ServerGroup, ServerTemplate
from .processes import _find_free_port, _find_pid_on_port, _kill_pid_tree, _port_in_use, _spawn_detached
from .storage import (
    _load_and_clear_kept_running, _load_groups, _load_presets, _save_groups, _save_kept_running, _save_presets,
)
from .theme import (
    _BG, _BORDER, _DIM_FG, _FG, _FIELD_BG, _GREEN, _RED, _ROW_BG, _ROW_SELECTED, _SEPARATOR, _SIDEBAR_BG,
    _SIDEBAR_WIDTH, _STATUS_FILLS,
)
from .widgets import PresetChip, RoundedButton, RoundedCard


class LauncherWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Server Launcher")
        root.configure(bg=_BG)
        root.geometry("820x560")

        # Instance status changes arrive from background threads (one per
        # instance) and must never touch Tk directly from there - Tk is not
        # thread-safe, and calling root.after() from several threads at once
        # (as happened with Kill Instances stopping many instances together)
        # could hang the whole app. Background threads only ever push here;
        # only _drain_status_queue(), running on the main thread via its own
        # root.after loop, ever reads it or touches a widget.
        self._status_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self.templates = discover_templates()
        self.instances: dict[str, Instance] = {}
        self._adopt_running_instances()
        self.presets: dict[str, list[Preset]] = _load_presets()
        self.groups: dict[str, ServerGroup] = _load_groups()
        self._empty_state_image = self._load_empty_state_image()

        self.active_tab = "servers"
        self.selected_template: ServerTemplate | None = None
        self.selected_instance_id: str | None = None
        self.selected_group_name: str | None = None
        self.instance_dots: dict[str, RoundedCard] = {}

        self._last_log_len = -1
        self._log_text: tk.Text | None = None
        self._status_label: RoundedButton | None = None

        root.grid_rowconfigure(1, weight=1)
        # column 0 = sidebar (fixed), column 1 = separator (1px), column 2 = main (flexible).
        # minsize on column 0 pins the sidebar's width at the grid level too, so it can't
        # drift between tabs even if a card's content briefly requests a different width.
        root.grid_columnconfigure(0, minsize=_SIDEBAR_WIDTH)
        root.grid_columnconfigure(2, weight=1)

        tabbar = tk.Frame(root, bg=_BG)
        tabbar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 6))
        self.servers_tab_btn = RoundedButton(
            tabbar, "Servers", command=lambda: self._set_tab("servers"),
            bg=_BG, fill=_ROW_SELECTED, outline=_BORDER, fg=_FG,
        )
        self.servers_tab_btn.pack(side="left", padx=(0, 4))
        self.instances_tab_btn = RoundedButton(
            tabbar, "Instances", command=lambda: self._set_tab("instances"),
            bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self.instances_tab_btn.pack(side="left", padx=(0, 4))
        self.groups_tab_btn = RoundedButton(
            tabbar, "Groups", command=lambda: self._set_tab("groups"),
            bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self.groups_tab_btn.pack(side="left")

        sidebar = tk.Frame(root, bg=_SIDEBAR_BG, width=_SIDEBAR_WIDTH)
        sidebar.grid(row=1, column=0, sticky="ns")
        # sidebar's own children are pack-managed, not
        # grid-managed, so pack_propagate is the one that actually pins this
        # frame's width - grid_propagate would be a no-op here and let a
        # card's content silently resize the sidebar between tabs.
        sidebar.pack_propagate(False)

        separator = tk.Frame(root, bg=_SEPARATOR, width=1)
        separator.grid(row=1, column=1, sticky="ns")

        # Packed (side="bottom") before sidebar_list so it claims its slice
        # of the cavity first - sidebar_list (packed after, expand+fill
        # both, default side="top") then fills everything left above it.
        bottom_actions = tk.Frame(sidebar, bg=_SIDEBAR_BG)
        bottom_actions.pack(side="bottom", fill="x", padx=10, pady=10)
        self._instance_actions = bottom_actions
        bottom_row = tk.Frame(bottom_actions, bg=_SIDEBAR_BG)
        bottom_row.pack(fill="x")
        self._instance_actions_row = bottom_row
        self._kill_instances_button = RoundedButton(
            bottom_row, "Kill Instances", command=self._kill_all_instances,
            bg=_SIDEBAR_BG, fill=_RED, outline=_RED, fg=_FG,
        )
        self._kill_instances_button.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._refresh_button = RoundedButton(
            bottom_row, "⟳", command=self._refresh_active_tab,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG, padx=10,
        )
        self._refresh_button.pack(side="left")
        self._clear_closed_button = RoundedButton(
            bottom_actions, "Clear Closed", command=self._clear_closed_instances,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self._restart_all_button = RoundedButton(
            bottom_actions, "Restart All", command=self._restart_all_instances,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self._create_group_button = RoundedButton(
            bottom_actions, "Create Group", command=self._show_create_group_dialog,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )

        self.sidebar_list = tk.Frame(sidebar, bg=_SIDEBAR_BG)
        self.sidebar_list.pack(fill="both", expand=True, padx=8)

        self.main = tk.Frame(root, bg=_BG)
        self.main.grid(row=1, column=2, sticky="nsew")

        self.status = tk.Label(root, text="", bg=_BG, fg=_FG, anchor="w")
        self.status.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 6))

        self._set_tab("servers")
        self._tick()
        self._drain_status_queue()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- tabs / sidebar -------------------------------------------------

    def _set_tab(self, tab: str) -> None:
        self.active_tab = tab
        self.servers_tab_btn.set_selected(tab == "servers", _ROW_SELECTED if tab == "servers" else _ROW_BG)
        self.instances_tab_btn.set_selected(tab == "instances", _ROW_SELECTED if tab == "instances" else _ROW_BG)
        self.groups_tab_btn.set_selected(tab == "groups", _ROW_SELECTED if tab == "groups" else _ROW_BG)
        if tab == "instances":
            self._instance_actions.pack(side="bottom", fill="x", padx=10, pady=10, before=self.sidebar_list)
            self._kill_instances_button.pack(side="left", expand=True, fill="x", padx=(0, 4))
            self._refresh_button.pack(side="left")
            self._clear_closed_button.pack(
                fill="x", pady=(0, 6), before=self._instance_actions_row,
            )
            self._restart_all_button.pack(
                fill="x", pady=(0, 6), before=self._clear_closed_button,
            )
            self._create_group_button.pack(
                fill="x", pady=(0, 6), before=self._restart_all_button,
            )
        else:
            self._create_group_button.pack_forget()
            self._restart_all_button.pack_forget()
            self._clear_closed_button.pack_forget()
            if tab == "servers":
                self._instance_actions.pack(side="bottom", fill="x", padx=10, pady=10, before=self.sidebar_list)
                self._kill_instances_button.pack_forget()
                self._refresh_button.pack(side="left")
            else:
                self._instance_actions.pack_forget()
        self._render_sidebar()
        if tab == "servers":
            self._render_server_detail(self.selected_template)
        elif tab == "instances":
            self._render_instance_detail(self.selected_instance_id)
        else:
            self._render_group_detail(self.selected_group_name)

    def _render_sidebar(self) -> None:
        for child in self.sidebar_list.winfo_children():
            child.destroy()
        self.instance_dots.clear()

        if self.active_tab == "servers":
            if not self.templates:
                tk.Label(self.sidebar_list, text="No run.bat found.", bg=_SIDEBAR_BG, fg=_DIM_FG).pack(pady=8)
            for template in self.templates:
                selected = template is self.selected_template
                card = RoundedCard(
                    self.sidebar_list,
                    bg=_SIDEBAR_BG, fill=_ROW_SELECTED if selected else _ROW_BG, outline=_BORDER,
                    fg=_FG, fg_dim=_DIM_FG, icon="☷", name=template.display_name,
                    secondary=f":{template.default_port}", selected=selected,
                    command=lambda t=template: self._select_template(t),
                )
                card.pack(fill="x", pady=3)
        elif self.active_tab == "instances":
            if not self.instances:
                tk.Label(self.sidebar_list, text="Nothing started yet.", bg=_SIDEBAR_BG, fg=_DIM_FG).pack(pady=8)
            for instance in self.instances.values():
                selected = instance.id == self.selected_instance_id
                card = RoundedCard(
                    self.sidebar_list,
                    bg=_SIDEBAR_BG, fill=_ROW_SELECTED if selected else _ROW_BG, outline=_BORDER,
                    fg=_FG, fg_dim=_DIM_FG, name=instance.template.display_name,
                    secondary=f":{instance.port}",
                    dot_color=_GREEN if instance.is_alive() else _DIM_FG,
                    selected=selected, command=lambda i=instance: self._select_instance(i.id),
                )
                card.pack(fill="x", pady=3)
                self.instance_dots[instance.id] = card
        else:
            if not self.groups:
                tk.Label(self.sidebar_list, text="No groups saved yet.", bg=_SIDEBAR_BG, fg=_DIM_FG).pack(pady=8)
            for group in self.groups.values():
                selected = group.name == self.selected_group_name
                card = RoundedCard(
                    self.sidebar_list,
                    bg=_SIDEBAR_BG, fill=_ROW_SELECTED if selected else _ROW_BG, outline=_BORDER,
                    fg=_FG, fg_dim=_DIM_FG, icon="☷", name=group.name,
                    selected=selected, command=lambda name=group.name: self._select_group(name),
                )
                card.pack(fill="x", pady=3)

    # ---- servers tab -----------------------------------------------------

    def _select_template(self, template: ServerTemplate) -> None:
        self.selected_template = template
        self._render_sidebar()
        self._render_server_detail(template)

    def _select_group(self, group_name: str) -> None:
        self.selected_group_name = group_name
        self._render_sidebar()
        self._render_group_detail(group_name)

    def _live_group_members(self) -> list[GroupMember]:
        """Return independent recipe snapshots for instances still running."""
        return [
            GroupMember(
                instance.template.key,
                instance.port,
                dict(instance.extra_env),
                instance.extra_args,
                instance.preset_name,
            )
            for instance in self.instances.values()
            if instance.is_alive()
        ]

    def _save_group(self, name: str, members: list[GroupMember]) -> bool:
        """Save a named recipe, asking before an existing recipe is replaced."""
        if name in self.groups and not messagebox.askyesno(
            "Replace group",
            f"Replace the saved group {name!r}?",
            parent=self.root,
        ):
            return False
        self.groups[name] = ServerGroup(name, members)
        _save_groups(self.groups)
        return True

    def _show_create_group_dialog(self) -> None:
        members = self._live_group_members()
        if not members:
            messagebox.showinfo("Create Group", "No running instances to save.", parent=self.root)
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Create Group")
        dialog.configure(bg=_BG)
        dialog.resizable(False, False)
        tk.Label(dialog, text="Group name", bg=_BG, fg=_FG).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        name_var = tk.StringVar()
        name_entry = tk.Entry(dialog, textvariable=name_var, bg=_FIELD_BG, fg=_FG, insertbackground=_FG)
        name_entry.pack(fill="x", padx=16)
        selected: list[tuple[str, Instance, tk.BooleanVar]] = []
        tk.Label(dialog, text="Running instances", bg=_BG, fg=_DIM_FG).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        live_instances = [
            (instance_id, instance) for instance_id, instance in self.instances.items() if instance.is_alive()
        ]
        for instance_id, instance in live_instances:
            checked = tk.BooleanVar(value=True)
            selected.append((instance_id, instance, checked))
            tk.Checkbutton(
                dialog, text=f"{instance.template.key} :{instance.port}", variable=checked,
                bg=_BG, fg=_FG, selectcolor=_FIELD_BG, activebackground=_BG, activeforeground=_FG,
            ).pack(anchor="w", padx=16)

        actions = tk.Frame(dialog, bg=_BG)
        actions.pack(fill="x", padx=16, pady=16)

        def save() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Create Group", "Enter a group name.", parent=dialog)
                return
            chosen = []
            for instance_id, original_instance, checked in selected:
                instance = self.instances.get(instance_id)
                if checked.get():
                    if instance is not original_instance or not instance.is_alive():
                        messagebox.showerror("Create Group", "A selected instance is no longer running.", parent=dialog)
                        return
                    chosen.append(GroupMember(instance.template.key, instance.port, dict(instance.extra_env), instance.extra_args, instance.preset_name))
            if not chosen:
                messagebox.showerror("Create Group", "Choose at least one instance.", parent=dialog)
                return
            if not self._save_group(name, chosen):
                return
            dialog.destroy()
            self._set_tab("groups")
            self._select_group(name)

        RoundedButton(
            actions, "Cancel", command=dialog.destroy, bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="right")
        RoundedButton(
            actions, "Save", command=save, bg=_BG, fill=_GREEN, outline=_GREEN, fg=_FG,
        ).pack(side="right", padx=(0, 6))
        name_entry.focus_set()

    def _delete_group(self, group_name: str) -> None:
        if group_name not in self.groups:
            return
        if not messagebox.askyesno(
            "Delete group", f"Delete the saved group {group_name!r}?", parent=self.root,
        ):
            return
        del self.groups[group_name]
        _save_groups(self.groups)
        if self.selected_group_name == group_name:
            self.selected_group_name = None
        self._render_sidebar()
        if self.active_tab == "groups":
            self._render_group_detail(self.selected_group_name)

    def _group_start_issues(self, group: ServerGroup) -> list[str]:
        templates = {template.key: template for template in self.templates}
        issues = []
        requested_ports: set[int] = set()
        for member in group.members:
            if (
                not isinstance(member.template_key, str)
                or not isinstance(member.port, int) or isinstance(member.port, bool)
                or not isinstance(member.extra_env, dict)
                or not isinstance(member.extra_args, str)
                or member.preset_name is not None and not isinstance(member.preset_name, str)
            ):
                issues.append("Saved group contains an invalid member configuration.")
                continue
            if member.port in requested_ports:
                issues.append(f"Port {member.port} is requested by more than one group member.")
                continue
            requested_ports.add(member.port)
            template = templates.get(member.template_key)
            if template is None:
                issues.append(f"Missing server template: {member.template_key}.")
            elif _port_in_use(member.port):
                issues.append(
                    f"Port {member.port} is already in use for {template.display_name}."
                )
        return issues

    def _start_group(self, group_name: str) -> None:
        group = self.groups.get(group_name)
        if group is None:
            return
        issues = self._group_start_issues(group)
        if issues:
            messagebox.showerror("Start Group", "\n".join(issues), parent=self.root)
            return

        templates = {template.key: template for template in self.templates}
        instance_ids = []
        for member in group.members:
            instance = Instance(
                templates[member.template_key], member.port, dict(member.extra_env),
                member.extra_args, preset_name=member.preset_name,
            )
            self._wire_instance(instance)
            self.instances[instance.id] = instance
            instance_ids.append(instance.id)
        self.status.config(text=f"Started group {group.name!r} ({len(instance_ids)} instances).")
        self._set_tab("instances")
        if instance_ids:
            self._select_instance(instance_ids[0])

    def _clear_main(self) -> None:
        for child in self.main.winfo_children():
            child.destroy()
        self._log_text = None
        self._status_label = None

    def _load_empty_state_image(self) -> tk.PhotoImage | None:
        image_path = ASSETS_DIR / "server.png"
        if not image_path.exists():
            return None
        try:
            # subsample(4): the source is 512x512, way bigger than this
            # panel needs - Tk's PhotoImage only downsizes by an integer
            # factor (no smooth resize built in), 4 lands close to the
            # ~100-130px icon size this empty state calls for.
            return tk.PhotoImage(file=str(image_path)).subsample(4)
        except tk.TclError:
            return None

    def _render_empty_state(self, title: str, subtitle: str) -> None:
        wrapper = tk.Frame(self.main, bg=_BG)
        wrapper.place(relx=0.5, rely=0.5, anchor="center")
        if self._empty_state_image is not None:
            tk.Label(wrapper, image=self._empty_state_image, bg=_BG).pack(pady=(0, 16))
        tk.Label(wrapper, text=title, bg=_BG, fg=_FG, font=("Segoe UI", 13, "bold")).pack()
        tk.Label(wrapper, text=subtitle, bg=_BG, fg=_DIM_FG).pack(pady=(4, 0))

    def _render_group_detail(self, group_name: str | None) -> None:
        self._clear_main()
        if group_name is None:
            self._render_empty_state("Groups", "Select a group.")
            return

        group = self.groups.get(group_name)
        if group is None:
            self._render_empty_state("Groups", "Select a group.")
            return

        header = tk.Frame(self.main, bg=_BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text=group.name, bg=_BG, fg=_FG, font=("Segoe UI", 14, "bold")).pack(side="left")
        RoundedButton(
            header, "Start All", command=lambda: self._start_group(group.name),
            bg=_BG, fill=_GREEN, outline=_GREEN, fg=_FG,
        ).pack(side="right")
        RoundedButton(
            header, "Delete Group", command=lambda: self._delete_group(group.name),
            bg=_BG, fill=_RED, outline=_RED, fg=_FG,
        ).pack(side="right", padx=(0, 6))

        templates = {template.key: template for template in self.templates}
        for member in group.members:
            card = tk.Frame(self.main, bg=_ROW_BG, highlightthickness=1, highlightbackground=_BORDER)
            card.pack(fill="x", padx=16, pady=(0, 8))
            template = templates.get(member.template_key)
            template_label = member.template_key
            if template is None:
                template_label += " (unavailable)"
            else:
                template_label += f" — {template.display_name}"
            tk.Label(
                card, text=f"{template_label}  :{member.port}", bg=_ROW_BG, fg=_FG,
                font=("Segoe UI", 10, "bold"), anchor="w",
            ).pack(fill="x", padx=10, pady=(8, 2))
            if member.extra_env:
                env_text = ", ".join(f"{key}={value}" for key, value in member.extra_env.items())
            else:
                env_text = "None"
            tk.Label(card, text=f"Environment: {env_text}", bg=_ROW_BG, fg=_DIM_FG, anchor="w").pack(
                fill="x", padx=10
            )
            tk.Label(
                card, text=f"Extra args: {member.extra_args or 'None'}", bg=_ROW_BG, fg=_DIM_FG, anchor="w",
            ).pack(fill="x", padx=10)
            tk.Label(
                card, text=f"Preset: {member.preset_name or 'None'}", bg=_ROW_BG, fg=_DIM_FG, anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 8))

    def _render_server_detail(self, template: ServerTemplate | None) -> None:
        self._clear_main()
        if template is None:
            self._render_empty_state("Server", "Select a server.")
            return

        header = tk.Frame(self.main, bg=_BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text=template.display_name, bg=_BG, fg=_FG, font=("Segoe UI", 14, "bold")).pack(side="left")

        if template.description:
            tk.Label(self.main, text=template.description, bg=_BG, fg=_DIM_FG, wraplength=560, justify="left").pack(
                anchor="w", padx=16, pady=(0, 8)
            )

        field_vars: dict[str, tk.StringVar] = {}
        port_var = tk.StringVar(value=str(template.default_port))
        args_var = tk.StringVar(value="")
        applied_preset_name: str | None = None

        def start() -> None:
            desired = int(port_var.get()) if port_var.get().isdigit() else template.default_port
            actual = _find_free_port(desired)
            extra_env = {name: var.get() for name, var in field_vars.items()}
            extra_args = args_var.get() if template.supports_args else ""
            instance = Instance(
                template, actual, extra_env, extra_args, preset_name=applied_preset_name,
            )
            self._wire_instance(instance)
            self.instances[instance.id] = instance
            if actual != desired:
                self.status.config(text=f"Port {desired} was taken - started {template.display_name} on {actual}.")
            else:
                self.status.config(text=f"Started {template.display_name} on port {actual}.")
            self._set_tab("instances")
            self._select_instance(instance.id)

        def add_preset() -> None:
            name = simpledialog.askstring(
                "Add as preset", f"Name for this {template.display_name} preset:", parent=self.root
            )
            if not name or not name.strip():
                return
            preset = Preset(
                name=name.strip(),
                port=int(port_var.get()) if port_var.get().isdigit() else template.default_port,
                env_vars={vname: var.get() for vname, var in field_vars.items()},
                args=args_var.get() if template.supports_args else "",
            )
            self.presets.setdefault(template.key, []).append(preset)
            _save_presets(self.presets)
            self.status.config(text=f"Saved preset {preset.name!r} for {template.display_name}.")
            self._render_server_detail(template)

        RoundedButton(
            header, "Start", command=start, bg=_BG, fill=_GREEN, outline=_GREEN, fg=_FG,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="right")
        RoundedButton(
            header, "Add as Preset", command=add_preset, bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="right", padx=(0, 6))

        body = tk.Frame(self.main, bg=_BG)
        body.pack(fill="x", padx=16)

        self._build_field_row(body, "Port", port_var)
        for name, default_value in template.extra_env_vars.items():
            var = tk.StringVar(value=default_value)
            field_vars[name] = var
            self._build_field_row(body, name, var)
        if template.supports_args:
            self._build_field_row(body, "Extra args", args_var)
            hint = _EXTRA_ARGS_HINTS.get(template.key)
            if hint:
                tk.Label(
                    body, text=hint, bg=_BG, fg=_DIM_FG, font=("Segoe UI", 8), justify="left", anchor="w",
                ).pack(fill="x", padx=(18, 0), pady=(2, 0))

        def apply_preset(preset: Preset) -> None:
            nonlocal applied_preset_name
            port_var.set(str(preset.port))
            for vname, var in field_vars.items():
                if vname in preset.env_vars:
                    var.set(preset.env_vars[vname])
            if template.supports_args:
                args_var.set(preset.args)
            applied_preset_name = preset.name
            self.status.config(text=f"Applied preset {preset.name!r}.")

        def remove_preset(preset: Preset) -> None:
            self.presets.get(template.key, []).remove(preset)
            _save_presets(self.presets)
            self.status.config(text=f"Removed preset {preset.name!r}.")
            self._render_server_detail(template)

        presets = self.presets.get(template.key, [])
        if presets:
            tk.Label(body, text="PRESETS", bg=_BG, fg=_DIM_FG, font=("Segoe UI", 8, "bold")).pack(
                anchor="w", pady=(16, 4)
            )
            preset_row = tk.Frame(body, bg=_BG)
            preset_row.pack(fill="x")
            for preset in presets:
                PresetChip(
                    preset_row, preset.name,
                    on_apply=lambda p=preset: apply_preset(p), on_remove=lambda p=preset: remove_preset(p),
                    bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
                ).pack(side="left", padx=(0, 8), pady=(6, 2))

        tk.Label(
            body, text=f"{template.command_summary}   (cwd: {template.working_dir})",
            bg=_BG, fg=_DIM_FG, font=("Segoe UI", 8), wraplength=560, justify="left",
        ).pack(anchor="w", pady=(16, 0))

    def _build_field_row(self, parent: tk.Frame, label: str, var: tk.StringVar) -> None:
        row = tk.Frame(parent, bg=_BG)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, bg=_BG, fg=_DIM_FG, width=18, anchor="w").pack(side="left")
        tk.Entry(
            row, textvariable=var, bg=_FIELD_BG, fg=_FG, insertbackground=_FG, relief="flat",
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_BORDER,
        ).pack(side="left", fill="x", expand=True, ipady=3)

    # ---- instances tab -----------------------------------------------------

    def _select_instance(self, instance_id: str) -> None:
        self.selected_instance_id = instance_id
        self._last_log_len = -1
        self._render_sidebar()
        self._render_instance_detail(instance_id)

    def _render_instance_detail(self, instance_id: str | None) -> None:
        self._clear_main()
        instance = self.instances.get(instance_id) if instance_id else None
        if instance is None:
            self._render_empty_state("Instance", "Select an instance.")
            return

        header = tk.Frame(self.main, bg=_BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(
            header, text=f"{instance.template.display_name}  :{instance.port}",
            bg=_BG, fg=_FG, font=("Segoe UI", 14, "bold"),
        ).pack(side="left")
        self._status_label = RoundedButton(
            header, instance.status, bg=_BG,
            fill=_STATUS_FILLS.get(instance.status, _ROW_BG),
            outline=_BORDER,
            fg=_FG if instance.status in _STATUS_FILLS else _DIM_FG,
        )
        self._status_label.pack(side="left", padx=(10, 0))

        if instance.preset_name:
            tk.Label(
                self.main, text=f"Preset: {instance.preset_name}", bg=_BG, fg=_DIM_FG,
            ).pack(anchor="w", padx=16, pady=(0, 8))

        RoundedButton(
            header, "Stop", command=lambda: self._stop_instance(instance.id),
            bg=_BG, fill=_RED, outline=_RED, fg=_FG,
        ).pack(side="right", padx=(6, 0))
        RoundedButton(
            header, "Restart", command=lambda: self._restart_instance(instance.id),
            bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="right")

        log_frame = tk.Frame(self.main, bg=_BG)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        text = tk.Text(
            log_frame, bg="#0d0d12", fg="#c9c9d4", insertbackground=_FG, relief="flat",
            font=("Consolas", 9), wrap="char", state="disabled",
        )
        scrollbar = tk.Scrollbar(log_frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        self._log_text = text
        self._refresh_log()

    def _refresh_log(self) -> None:
        """Periodic-poll refresh (from _tick) - reads whatever is current
        right now, since nothing dramatic is assumed to be mid-transition."""
        if self.selected_instance_id is None:
            return
        instance = self.instances.get(self.selected_instance_id)
        if instance is None:
            return
        self._update_status_badge(instance.status)
        self._refresh_log_text(instance)

    def _update_status_badge(self, status: str) -> None:
        if self._status_label is None:
            return
        fill = _STATUS_FILLS.get(status, _ROW_BG)
        fg = _FG if status in _STATUS_FILLS else _DIM_FG
        self._status_label.set(text=status, fill=fill, fg=fg)

    def _refresh_log_text(self, instance: "Instance") -> None:
        if self._log_text is None:
            return
        lines = list(instance.log_lines)
        if len(lines) == self._last_log_len:
            return
        self._last_log_len = len(lines)
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.insert("end", "\n".join(lines))
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _drain_status_queue(self) -> None:
        """Runs only on the main thread (self-rescheduling via root.after) -
        the single place that ever turns a queued (instance_id, status) pair
        from a background thread into an actual widget update."""
        try:
            while True:
                instance_id, status = self._status_queue.get_nowait()
                self._on_instance_status_change(instance_id, status)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_status_queue)

    def _on_instance_status_change(self, instance_id: str, status: str) -> None:
        """Handles one queued status update, with the status AS OF THE
        MOMENT IT CHANGED rather than re-read here - by the time the drain
        loop gets to it, self.status may already have moved past it (e.g. a
        fast stop->exited happened within the same tick), and re-reading
        would silently skip painting the transient state at all."""
        if self.active_tab != "instances" or self.selected_instance_id != instance_id:
            return
        self._update_status_badge(status)
        instance = self.instances.get(instance_id)
        if instance is not None:
            self._refresh_log_text(instance)

    def _wire_instance(self, instance: Instance) -> None:
        # A plain thread-safe queue.put() - never touches Tk from the
        # background thread that calls this. See _status_queue and
        # _drain_status_queue().
        instance.on_status_change = lambda status: self._status_queue.put((instance.id, status))

    def _adopt_running_instances(self) -> None:
        """Startup only, before the window is shown/interactive - a bounded
        handful of netstat calls (one per template) here is a one-time
        startup cost, not a recurring UI-thread block, so it's fine to run
        synchronously. What must NOT happen is checking these adopted
        instances' liveness on every _tick() afterwards - that's what each
        Instance's own background watcher thread is for (see
        Instance._start_liveness_watcher()), so is_alive() stays a cheap
        cached read from here on.

        Checks each template's default port, plus - if the previous session
        was closed with "keep running in the background" - whatever exact
        (template, port) pairs it left behind, even a custom/bumped port
        that wouldn't otherwise be found. A port nobody explicitly kept and
        that isn't a template's default stays invisible.

        Detection can be flaky right at startup (netstat/tasklist catching a
        process mid-bind), so this retries the same candidate ports until 3
        consecutive passes find nothing new, not just once."""
        templates_by_key = {t.key: t for t in self.templates}
        candidate_ports: dict[str, set[int]] = {t.key: {t.default_port} for t in self.templates}
        for template_key, port in _load_and_clear_kept_running():
            if template_key in candidate_ports:
                candidate_ports[template_key].add(port)

        adopted_ports: set[tuple[str, int]] = set()
        misses = 0
        first_pass = True
        while misses < 3:
            if not first_pass:
                time.sleep(0.3)
            first_pass = False
            found_this_pass = 0
            for template in self.templates:
                for port in candidate_ports[template.key]:
                    if (template.key, port) in adopted_ports:
                        continue
                    if self._try_adopt_port(template, port):
                        adopted_ports.add((template.key, port))
                        found_this_pass += 1
            misses = 0 if found_this_pass else misses + 1

    def _try_adopt_port(self, template: ServerTemplate, port: int) -> bool:
        """Adopts a running process on `port` as a new Instance, if one is
        there and isn't already tracked. Returns whether it adopted one."""
        if not _port_in_use(port):
            return False
        pid = _find_pid_on_port(port)
        if pid is None:
            return False
        instance = Instance(template, port, {}, "", adopted_pid=pid)
        self._wire_instance(instance)
        self.instances[instance.id] = instance
        return True

    def _refresh_active_tab(self) -> None:
        """Refresh button: on Servers, re-discover run.bat templates (new
        ones added on disk since launch). On Instances, re-scan default
        ports for background instances that startup adoption missed - e.g.
        one started just after this app launched."""
        if self.active_tab == "servers":
            selected_key = self.selected_template.key if self.selected_template else None
            self.templates = discover_templates()
            self.selected_template = next(
                (t for t in self.templates if t.key == selected_key), None
            )
            self.status.config(text="Refreshed server list.")
        else:
            tracked_ports = {
                (i.template.key, i.port) for i in self.instances.values() if i.is_alive()
            }
            found = 0
            for template in self.templates:
                port = template.default_port
                if (template.key, port) in tracked_ports:
                    continue
                if self._try_adopt_port(template, port):
                    found += 1
            self.status.config(
                text=f"Found {found} new instance(s)." if found else "No new background instances found."
            )
        self._render_sidebar()
        if self.active_tab == "servers":
            self._render_server_detail(self.selected_template)
        else:
            self._render_instance_detail(self.selected_instance_id)

    def _stop_instance(self, instance_id: str) -> None:
        instance = self.instances.get(instance_id)
        if instance is None:
            return
        if not messagebox.askyesno(
            "Stop server", f"Stop {instance.template.display_name} (port {instance.port})?", parent=self.root
        ):
            return
        self.status.config(text=f"Stopping {instance.template.display_name}...")
        threading.Thread(target=instance.stop, daemon=True).start()

    def _restart_instance(self, instance_id: str) -> None:
        instance = self.instances.get(instance_id)
        if instance is None:
            return
        if not messagebox.askyesno(
            "Restart server", f"Restart {instance.template.display_name} (port {instance.port})?", parent=self.root
        ):
            return
        self.status.config(text=f"Restarting {instance.template.display_name}...")
        threading.Thread(target=instance.restart, daemon=True).start()

    def _kill_all_instances(self) -> None:
        """Stops every tracked instance, including ones adopted at startup
        from a previous session (see _adopt_running_instances()). Runs on a
        background thread so the (possibly several) blocking taskkill calls
        never touch the UI thread - is_alive() here is always a cheap cached
        read (Popen.poll() or Instance._adopted_alive), never a blocking
        check, so building `running` itself is instant too."""
        running = [i for i in self.instances.values() if i.is_alive()]
        if not running:
            messagebox.showinfo("Kill Instances", "No running instances.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Kill Instances",
            f"Kill all {len(running)} running instance(s)? This cannot be undone.",
            parent=self.root,
        ):
            return
        self.status.config(text=f"Killing {len(running)} instance(s)...")

        def kill_all() -> None:
            for instance in running:
                instance.stop()

        threading.Thread(target=kill_all, daemon=True).start()

    def _restart_all_instances(self) -> None:
        """Restarts every running instance in parallel (one thread each -
        Instance.restart() blocks while it waits for the old process to
        exit, so serial restarts would add up)."""
        running = [i for i in self.instances.values() if i.is_alive()]
        if not running:
            messagebox.showinfo("Restart All", "No running instances.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Restart All",
            f"Restart all {len(running)} running instance(s)?",
            parent=self.root,
        ):
            return
        self.status.config(text=f"Restarting {len(running)} instance(s)...")
        for instance in running:
            threading.Thread(target=instance.restart, daemon=True).start()

    def _clear_closed_instances(self) -> None:
        """Forgets only instances whose processes have already stopped."""
        closed_ids = [instance_id for instance_id, instance in self.instances.items() if not instance.is_alive()]
        for instance_id in closed_ids:
            del self.instances[instance_id]
        if self.selected_instance_id not in self.instances:
            self.selected_instance_id = None
        self._render_sidebar()
        self._render_instance_detail(self.selected_instance_id)
        count = len(closed_ids)
        self.status.config(
            text=f"Cleared {count} closed instance{'s' if count != 1 else ''}."
            if count else "No closed instances to clear."
        )

    # ---- periodic refresh -------------------------------------------------

    def _tick(self) -> None:
        for instance_id, card in self.instance_dots.items():
            instance = self.instances.get(instance_id)
            if instance is not None:
                card.set_dot_color(_GREEN if instance.is_alive() else _DIM_FG)
        if self.active_tab == "instances" and self.selected_instance_id:
            self._refresh_log()
        self.root.after(_POLL_MS, self._tick)

    # ---- lifecycle ----------------------------------------------------

    def _on_close(self) -> None:
        """Closing the window asks what to do with instances it launched,
        when any are still running: stop them, or leave them running in the
        background - a spawned server is a real independent OS process that
        outlives this window either way, so "leave running" needs to save
        which (template, port) pairs to re-adopt next launch (see
        _adopt_running_instances()), or they'd be invisible orphans."""
        running = [i for i in self.instances.values() if i.is_alive()]
        if not running:
            self.root.destroy()
            return
        choice = messagebox.askyesnocancel(
            "Quit Server Launcher",
            f"{len(running)} server instance(s) still running.\n\n"
            "Yes - stop them and quit.\n"
            "No - keep them running in the background (picked back up next time this app opens).\n"
            "Cancel - don't quit.",
            parent=self.root,
        )
        if choice is None:
            return
        if choice:
            for instance in running:
                instance.stop()
        else:
            _save_kept_running([self._detach_for_background(i) for i in running])
        self.root.destroy()

    def _detach_for_background(self, instance: Instance) -> tuple[str, int]:
        """A self-spawned instance's stdout pipe is read by a thread in THIS
        process - confirmed by testing that this thread reliably takes the
        child down with it at interpreter shutdown (torn down mid-syscall on
        the pipe), even though the child is otherwise an independent OS
        process. So "keep running in the background" isn't just leaving it
        alone: for a self-spawned one, swap it for a freshly-spawned
        replacement with no pipe tied to us at all (losing its log history -
        nothing would be left to read it anyway), then hand that one's port
        back to be saved. An already-adopted instance has no pipe in this
        process to begin with and needs no swap."""
        if instance.process is None:
            return instance.template.key, instance.port
        _kill_pid_tree(instance.process.pid)
        deadline = time.time() + _RESTART_WAIT_SECONDS
        while time.time() < deadline and _port_in_use(instance.port):
            time.sleep(0.2)
        _spawn_detached(instance.template, instance.port, instance.extra_env, instance.extra_args)
        return instance.template.key, instance.port
