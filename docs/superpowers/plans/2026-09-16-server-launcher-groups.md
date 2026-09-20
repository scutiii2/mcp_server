# Server Launcher Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save live server configurations as named groups and launch each saved group as an exact, validated set.

**Architecture:** Keep group data and behavior in `server_launcher.py`, matching its current single-file Tkinter design. Serializable group dataclasses and pure persistence/preflight helpers underpin the revised UI; existing `Instance` lifecycle code remains the sole owner of processes and logs.

**Tech Stack:** Python 3.11+, standard-library Tkinter, `json`, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-16-server-launcher-groups-design.md`

## Global Constraints

- Add no dependencies.
- Persist independent groups at `server_launcher/groups.json`; unreadable data means no groups.
- Store template key, requested port, extra environment, extra arguments, and optional preset name for every group member.
- Group names are unique; replace and delete require confirmation.
- Create groups from live tracked instances only.
- Preflight every member and launch none if a template is absent or a port is occupied; never choose another port.
- Preserve all existing instance lifecycle, logs, status polling, Stop/Restart, Clear Closed, Kill Instances, and Refresh behavior.

---

### Task 1: Add group model and JSON persistence

**Files:**
- Modify: `server_launcher.py:60-70, 514-550`
- Modify: `test_server_launcher.py`

**Interfaces:**
- Produces `GroupMember(template_key: str, port: int, extra_env: dict[str, str], extra_args: str, preset_name: str | None)`.
- Produces `ServerGroup(name: str, members: list[GroupMember])`.
- Produces `_load_groups() -> dict[str, ServerGroup]` and `_save_groups(groups: dict[str, ServerGroup]) -> None`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_groups_round_trip_every_launch_setting(self) -> None:
    group = server_launcher.ServerGroup("Local stack", [
        server_launcher.GroupMember(
            "ai_agent", 9100, {"AI_AGENT_PROVIDER": "anthropic"},
            "--gateway openrouter", "OpenRouter",
        )
    ])
    with patch.object(server_launcher, "_GROUPS_PATH", self.groups_path):
        server_launcher._save_groups({group.name: group})
        self.assertEqual(server_launcher._load_groups(), {group.name: group})

def test_malformed_groups_file_loads_as_no_groups(self) -> None:
    self.groups_path.write_text("not json", encoding="utf-8")
    with patch.object(server_launcher, "_GROUPS_PATH", self.groups_path):
        self.assertEqual(server_launcher._load_groups(), {})
```

Use `tempfile.TemporaryDirectory()` to give `self.groups_path` an isolated file location.

- [ ] **Step 2: Verify the tests fail**

Run: `py -m unittest test_server_launcher.GroupPersistenceTests`

Expected: failure because the model and persistence helpers do not exist.

- [ ] **Step 3: Implement the model and persistence helpers**

```python
@dataclass
class GroupMember:
    template_key: str
    port: int
    extra_env: dict[str, str] = field(default_factory=dict)
    extra_args: str = ""
    preset_name: str | None = None

@dataclass
class ServerGroup:
    name: str
    members: list[GroupMember] = field(default_factory=list)
```

Add `_GROUPS_PATH = ROOT / "server_launcher" / "groups.json"`. Serialize the five member fields. `_load_groups` catches `OSError`, `json.JSONDecodeError`, `KeyError`, and `TypeError`, returns `{}` on failure, and defaults missing optional fields.

- [ ] **Step 4: Verify persistence and current checks pass**

Run: `py -m unittest test_server_launcher.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add server_launcher.py test_server_launcher.py
git commit -m "feat: persist launcher groups"
```

### Task 2: Move navigation above the panes and add Groups state

**Files:**
- Modify: `server_launcher.py:885-1025`
- Modify: `test_server_launcher.py`

**Interfaces:**
- Consumes `_load_groups()`.
- Produces `LauncherWindow.selected_group_name: str | None`.
- Produces `LauncherWindow._select_group(group_name: str) -> None` and `_render_group_detail(group_name: str | None) -> None`.

- [ ] **Step 1: Write the failing selection test**

```python
def test_select_group_sets_selection_and_renders_detail(self) -> None:
    launcher = object.__new__(server_launcher.LauncherWindow)
    launcher._render_sidebar = Mock()
    launcher._render_group_detail = Mock()
    launcher._select_group("Local stack")
    self.assertEqual(launcher.selected_group_name, "Local stack")
    launcher._render_sidebar.assert_called_once_with()
    launcher._render_group_detail.assert_called_once_with("Local stack")
```

- [ ] **Step 2: Verify it fails**

Run: `py -m unittest test_server_launcher.GroupTabTests`

Expected: failure because `_select_group` does not exist.

- [ ] **Step 3: Implement global navigation and tab routing**

Create a root-level `tabbar` in a new grid row spanning the sidebar, separator, and main columns. Move Servers/Instances controls into it, add Groups, then shift the sidebar/main/status rows down one. Keep the sidebar fixed-width and its packing behavior. Load `self.groups`, initialize `selected_group_name`, and make `_set_tab` select and render all three tabs.

```python
def _select_group(self, group_name: str) -> None:
    self.selected_group_name = group_name
    self._render_sidebar()
    self._render_group_detail(group_name)
```

Keep all instance actions hidden outside Instances at this stage.

- [ ] **Step 4: Verify all focused checks pass**

Run: `py -m unittest test_server_launcher.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add server_launcher.py test_server_launcher.py
git commit -m "feat: add launcher groups tab"
```

### Task 3: Create, replace, and delete group recipes

**Files:**
- Modify: `server_launcher.py:960-1025, 1150-1170`
- Modify: `test_server_launcher.py`

**Interfaces:**
- Produces `_live_group_members() -> list[GroupMember]`.
- Produces `_save_group(name: str, members: list[GroupMember]) -> bool`.
- Produces `_show_create_group_dialog() -> None` and `_delete_group(group_name: str) -> None`.

- [ ] **Step 1: Write failing live-snapshot and replacement tests**

```python
def test_live_group_members_snapshot_only_live_instances(self) -> None:
    launcher = object.__new__(server_launcher.LauncherWindow)
    live = SimpleNamespace(
        template=SimpleNamespace(key="ai_agent"), port=9100,
        extra_env={"AI_AGENT_PROVIDER": "anthropic"},
        extra_args="--gateway openrouter", preset_name="OpenRouter",
        is_alive=lambda: True,
    )
    launcher.instances = {"live": live, "closed": SimpleNamespace(is_alive=lambda: False)}
    self.assertEqual(launcher._live_group_members(), [
        server_launcher.GroupMember(
            "ai_agent", 9100, {"AI_AGENT_PROVIDER": "anthropic"},
            "--gateway openrouter", "OpenRouter",
        )
    ])
```

Add a test that patches `messagebox.askyesno` to approve replacement and asserts `_save_group` replaces an existing name and calls `_save_groups`.

- [ ] **Step 2: Verify these tests fail**

Run: `py -m unittest test_server_launcher.GroupManagementTests`

Expected: failure because the management helpers do not exist.

- [ ] **Step 3: Implement exact snapshot and confirmation behavior**

```python
def _live_group_members(self) -> list[GroupMember]:
    return [
        GroupMember(i.template.key, i.port, dict(i.extra_env), i.extra_args, i.preset_name)
        for i in self.instances.values() if i.is_alive()
    ]

def _save_group(self, name: str, members: list[GroupMember]) -> bool:
    if name in self.groups and not messagebox.askyesno(
        "Replace Group", f"Replace the saved group {name!r}?", parent=self.root,
    ):
        return False
    self.groups[name] = ServerGroup(name, members)
    _save_groups(self.groups)
    return True
```

Add an Instances-only Create Group button above Clear Closed. Its `tk.Toplevel` has a name `Entry`, one `Checkbutton` per live member, and Cancel/Save. Reject blank names and zero selections with `messagebox.showerror`. After a successful save, select the group and switch to Groups. If there are no live instances, show an informational message instead.

Delete asks confirmation, removes only the recipe, persists it, clears a deleted selection, and re-renders; it never calls `Instance.stop()`.

- [ ] **Step 4: Verify all focused checks pass**

Run: `py -m unittest test_server_launcher.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add server_launcher.py test_server_launcher.py
git commit -m "feat: create launcher groups from instances"
```

### Task 4: Render and start groups with all-or-nothing preflight

**Files:**
- Modify: `server_launcher.py:1160-1460`
- Modify: `test_server_launcher.py`

**Interfaces:**
- Produces `_group_start_issues(group: ServerGroup) -> list[str]`.
- Produces `_start_group(group_name: str) -> None`.
- Uses `Instance(template, port, extra_env, extra_args, preset_name=member.preset_name)` and `_wire_instance(instance)`.

- [ ] **Step 1: Write failing preflight tests**

```python
def test_group_preflight_lists_missing_templates_and_occupied_ports(self) -> None:
    launcher = object.__new__(server_launcher.LauncherWindow)
    launcher.templates = [SimpleNamespace(key="ai_agent", display_name="AI Agent")]
    group = server_launcher.ServerGroup("Stack", [
        server_launcher.GroupMember("missing", 8000),
        server_launcher.GroupMember("ai_agent", 9100),
    ])
    with patch.object(server_launcher, "_port_in_use", side_effect=lambda port: port == 9100):
        self.assertEqual(launcher._group_start_issues(group), [
            "Missing server template: missing.",
            "Port 9100 is already in use for AI Agent.",
        ])

def test_start_group_does_not_launch_when_preflight_fails(self) -> None:
    launcher = object.__new__(server_launcher.LauncherWindow)
    launcher.groups = {"Stack": server_launcher.ServerGroup("Stack", [])}
    launcher._group_start_issues = Mock(return_value=["Port 9100 is already in use."])
    with patch.object(server_launcher, "Instance") as instance:
        launcher._start_group("Stack")
    instance.assert_not_called()
```

- [ ] **Step 2: Verify the preflight checks fail**

Run: `py -m unittest test_server_launcher.GroupStartTests`

Expected: failure because preflight and group start methods do not exist.

- [ ] **Step 3: Implement preflight, detail rendering, and exact launch**

```python
def _group_start_issues(self, group: ServerGroup) -> list[str]:
    templates = {template.key: template for template in self.templates}
    issues = []
    for member in group.members:
        template = templates.get(member.template_key)
        if template is None:
            issues.append(f"Missing server template: {member.template_key}.")
        elif _port_in_use(member.port):
            issues.append(f"Port {member.port} is already in use for {template.display_name}.")
    return issues
```

Groups sidebar lists saved names. Its detail pane shows each member's template key, port, environment values, extra arguments, preset label, and missing-template marker, plus Start All and Delete.

Start All shows every preflight issue in one error dialog and creates no instances on failure. On success, create/wire/store one `Instance` per member with exact options; update the status, switch to Instances, and select the first new instance. Never call `_find_free_port`.

- [ ] **Step 4: Run full verification**

Run:

```bash
py -m unittest test_server_launcher.py
py -m py_compile server_launcher.py
git diff --check
```

Expected: all tests pass, compilation exits 0, and no whitespace errors are reported.

- [ ] **Step 5: Commit**

```bash
git add server_launcher.py test_server_launcher.py
git commit -m "feat: start saved launcher groups"
```
