"""Focused behavior checks for the desktop server launcher."""

from types import SimpleNamespace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from src import agent_files, discovery, instance as instance_module, models, storage, window


_PY_RUN_BAT = (
    "@echo off\nREM LABEL: {label}\nif not defined {port_var} set {port_var}={port}\n"
    "call .venv_{venv}\\Scripts\\activate\npy -m src.run\n"
)


class ExtraProjectRootTests(unittest.TestCase):
    def _make_project(self, root: Path, name: str, label: str, port: int) -> None:
        (root / name).mkdir(parents=True)
        (root / name / "run.bat").write_text(
            _PY_RUN_BAT.format(label=label, port_var=f"{name.upper()}_PORT", port=port, venv=name), encoding="utf-8"
        )

    def test_projects_in_extra_roots_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            main, extra = Path(directory) / "MCPServer", Path(directory) / "PDFMerger"
            self._make_project(main, "mcp_server", "MCP Server", 8010)
            self._make_project(extra, "pdf_merger", "PDF Merger", 8040)

            templates = discovery.discover_templates(roots=[main, extra])

        by_key = {t.key: t for t in templates}
        self.assertEqual(set(by_key), {"mcp_server", "pdf_merger"})
        self.assertEqual(by_key["pdf_merger"].display_name, "PDF Merger")
        self.assertEqual(by_key["pdf_merger"].default_port, 8040)

    def test_first_root_wins_when_two_projects_share_a_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            main, extra = Path(directory) / "a", Path(directory) / "b"
            self._make_project(main, "tool", "Main tool", 1000)
            self._make_project(extra, "tool", "Other tool", 2000)

            [template] = discovery.discover_templates(roots=[main, extra])

        self.assertEqual(template.display_name, "Main tool")

    def test_extra_roots_file_is_resolved_against_the_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "MCPServer"
            (base.parent / "PDFMerger").mkdir(parents=True)
            base.mkdir()
            roots_file = base / "extra_roots.json"
            roots_file.write_text(json.dumps(["../PDFMerger", "../Missing"]), encoding="utf-8")

            roots = discovery.project_roots(base=base, extra_roots_path=roots_file)

        self.assertEqual(roots, [base, (base.parent / "PDFMerger").resolve()])

    def test_missing_or_invalid_extra_roots_file_means_repo_root_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            bad = base / "extra_roots.json"
            self.assertEqual(discovery.project_roots(base=base, extra_roots_path=bad), [base])
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(discovery.project_roots(base=base, extra_roots_path=bad), [base])
            bad.write_text(json.dumps({"roots": ["x"]}), encoding="utf-8")
            self.assertEqual(discovery.project_roots(base=base, extra_roots_path=bad), [base])


_SUPERVISOR_RUN_BAT = "\n".join([
    "@echo off",
    "REM LABEL: AI Agent",
    r"call .venv_ai_agent\Scripts\activate",
    "py -m src.supervisor",
    "",
])


def _write_agent(folder: Path, agent_id: str, **fields) -> None:
    data = {"label": agent_id.title(), "port": 9100, "llm": {"provider": "anthropic", "model": "m1"}}
    data.update(fields)
    (folder / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")


class AgentFileTests(unittest.TestCase):
    """The launcher shows ai_agent's agent files but never changes them."""

    def _agent_project(self, root: Path) -> Path:
        project = root / "ai_agent"
        (project / "agents").mkdir(parents=True)
        (project / "run.bat").write_text(_SUPERVISOR_RUN_BAT, encoding="utf-8")
        return project

    def test_agent_files_are_read_and_the_template_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agents = self._agent_project(Path(directory)) / "agents"
            _write_agent(agents, "ember", port=9100, entry=True)
            _write_agent(agents, "reviewer", port=9102, enabled=False, llm={"provider": "openai", "model": "gpt"})
            (agents / "agents.json.template").write_text("{}", encoding="utf-8")

            found = agent_files.read_agent_files(agents)

        self.assertEqual([a.id for a in found], ["ember", "reviewer"])
        ember, reviewer = found
        self.assertEqual((ember.label, ember.port, ember.provider, ember.model, ember.enabled, ember.entry),
                         ("Ember", 9100, "anthropic", "m1", True, True))
        self.assertEqual((reviewer.provider, reviewer.enabled, reviewer.entry), ("openai", False, False))
        self.assertIsNone(ember.error)

    def test_a_broken_file_becomes_an_error_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agents = self._agent_project(Path(directory)) / "agents"
            (agents / "bad.json").write_text("{not json", encoding="utf-8")
            (agents / "list.json").write_text("[]", encoding="utf-8")

            found = agent_files.read_agent_files(agents)

        self.assertEqual([a.id for a in found], ["bad", "list"])
        self.assertTrue(all(a.error for a in found))
        self.assertTrue(all(not a.enabled and a.port is None for a in found))

    def test_entry_port_prefers_the_enabled_entry_agent_then_the_first_enabled(self) -> None:
        def agent(agent_id, port, enabled=True, entry=False):
            return models.AgentInfo(agent_id, agent_id, port, "", "", enabled, entry)

        self.assertEqual(agent_files.entry_port([agent("a", 9102), agent("e", 9100, entry=True)]), 9100)
        self.assertEqual(agent_files.entry_port([agent("e", 9100, enabled=False, entry=True), agent("b", 9103)]), 9103)
        self.assertIsNone(agent_files.entry_port([agent("off", 9100, enabled=False)]))
        self.assertIsNone(agent_files.entry_port([]))

    def test_discovery_gives_a_supervisor_project_its_agents_and_entry_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = self._agent_project(root) / "agents"
            _write_agent(agents, "ember", port=9100, entry=True)
            _write_agent(agents, "server-ops", port=9103)

            (template,) = discovery.discover_templates(roots=[root])

        self.assertEqual(template.key, "ai_agent")
        self.assertEqual([a.id for a in template.agents], ["ember", "server-ops"])
        self.assertEqual(template.default_port, 9100)

    def test_a_bat_marked_launcher_skip_is_not_listed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, extra in (("mcp_server", ""), ("chat_cli", "REM LAUNCHER: skip\n")):
                (root / name).mkdir()
                (root / name / "run.bat").write_text(
                    extra + _PY_RUN_BAT.format(label=name, port_var="X_PORT", port=8010, venv=name),
                    encoding="utf-8",
                )
            templates = discovery.discover_templates(roots=[root])

        self.assertEqual([t.key for t in templates], ["mcp_server"])

    def test_a_project_without_agent_files_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mcp_server").mkdir()
            (root / "mcp_server" / "run.bat").write_text(
                _PY_RUN_BAT.format(label="MCP", port_var="MCP_PORT", port=8010, venv="mcp"), encoding="utf-8"
            )
            (template,) = discovery.discover_templates(roots=[root])

        self.assertEqual(template.agents, [])
        self.assertEqual(template.default_port, 8010)

    def test_launch_port_uses_the_entry_port_for_an_agent_project_only(self) -> None:
        agents = [models.AgentInfo("ember", "Ember", 9100, "anthropic", "m1", True, True)]
        self.assertEqual(agent_files.launch_port(SimpleNamespace(agents=agents), 8000), 9100)
        self.assertEqual(agent_files.launch_port(SimpleNamespace(agents=[]), 8010), 8010)
        self.assertEqual(agent_files.launch_port(SimpleNamespace(), 8010), 8010)  # templates in older tests

    def test_starting_an_agent_project_is_refused_while_its_entry_port_is_taken(self) -> None:
        template = SimpleNamespace(display_name="AI Agent",
                                   agents=[models.AgentInfo("ember", "Ember", 9100, "", "", True, True)])
        self.assertIn("9100", agent_files.start_refusal(template, port_in_use=lambda port: port == 9100))
        self.assertIsNone(agent_files.start_refusal(template, port_in_use=lambda port: False))
        self.assertIsNone(agent_files.start_refusal(SimpleNamespace(agents=[]), port_in_use=lambda port: True))

    def test_an_agent_project_with_no_enabled_agent_cannot_start(self) -> None:
        template = SimpleNamespace(display_name="AI Agent",
                                   agents=[models.AgentInfo("off", "Off", 9100, "", "", False, False)])
        self.assertIn("no enabled agent", agent_files.start_refusal(template, port_in_use=lambda port: False))

    def test_group_start_uses_the_entry_port_not_the_saved_one(self) -> None:
        launcher = object.__new__(window.LauncherWindow)
        template = SimpleNamespace(key="ai_agent", display_name="AI Agent",
                                   agents=[models.AgentInfo("ember", "Ember", 9100, "", "", True, True)])
        launcher.templates = [template]
        group = models.ServerGroup("Stack", [models.GroupMember("ai_agent", 8000)])

        with patch.object(window, "_port_in_use", side_effect=lambda port: port == 9100):
            issues = launcher._group_start_issues(group)

        self.assertEqual(issues, ["Port 9100 is already in use for AI Agent."])


class GroupPersistenceTests(unittest.TestCase):
    def test_invalid_member_schema_rejects_entire_file(self) -> None:
        valid = {"template_key": "ai_agent", "port": 9100}
        invalid_fields = [
            {"extra_env": None}, {"extra_env": []}, {"extra_env": {"FLAG": 1}},
            {"port": "9101"}, {"port": True}, {"port": 0}, {"port": 65536},
            {"template_key": []}, {"template_key": 1}, {"extra_args": None},
            {"preset_name": 42},
        ]
        with tempfile.TemporaryDirectory() as directory:
            groups_path = Path(directory) / "groups.json"
            for fields in invalid_fields:
                with self.subTest(fields=fields):
                    raw = {"Stack": {"members": [valid, {**valid, **fields}]}}
                    groups_path.write_text(json.dumps(raw), encoding="utf-8")
                    with patch.object(storage, "_GROUPS_PATH", groups_path):
                        self.assertEqual(storage._load_groups(), {})

    def test_groups_round_trip_through_json(self) -> None:
        """Catches a missing or incomplete persisted group-member field."""
        groups = {
            "Local stack": models.ServerGroup(
                "Local stack",
                [
                    models.GroupMember(
                        "ai_agent",
                        9100,
                        {"AI_AGENT_PROVIDER": "anthropic"},
                        "--gateway openrouter",
                        "OpenRouter",
                    )
                ],
            )
        }

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(storage, "_GROUPS_PATH", Path(directory) / "groups.json"):
                storage._save_groups(groups)
                loaded = storage._load_groups()

        self.assertEqual(loaded, groups)

    def test_invalid_group_json_loads_as_empty_groups(self) -> None:
        """Catches malformed persisted JSON escaping the launcher startup path."""
        with tempfile.TemporaryDirectory() as directory:
            groups_path = Path(directory) / "groups.json"
            groups_path.write_text("not JSON", encoding="utf-8")
            with patch.object(storage, "_GROUPS_PATH", groups_path):
                loaded = storage._load_groups()

        self.assertEqual(loaded, {})

    def test_non_utf8_group_data_loads_as_empty_groups(self) -> None:
        """Catches corrupt group-file bytes crashing launcher startup."""
        with tempfile.TemporaryDirectory() as directory:
            groups_path = Path(directory) / "groups.json"
            groups_path.write_bytes(b"\xff\xfe")
            with patch.object(storage, "_GROUPS_PATH", groups_path):
                loaded = storage._load_groups()

        self.assertEqual(loaded, {})


class GroupTabTests(unittest.TestCase):
    def test_tab_switch_keeps_actions_before_list_and_refresh_on_servers(self) -> None:
        launcher = object.__new__(window.LauncherWindow)
        for attribute in (
            "servers_tab_btn", "instances_tab_btn", "groups_tab_btn", "_instance_actions",
            "_instance_actions_row", "_kill_instances_button", "_refresh_button",
            "_clear_closed_button", "_restart_all_button", "_create_group_button", "sidebar_list",
            "_render_sidebar", "_render_server_detail", "_render_instance_detail",
            "_render_group_detail",
        ):
            setattr(launcher, attribute, Mock())
        launcher.selected_template = launcher.selected_instance_id = launcher.selected_group_name = None

        for tab in ("groups", "instances", "servers", "instances"):
            launcher._instance_actions.reset_mock()
            launcher._kill_instances_button.reset_mock()
            launcher._set_tab(tab)
            if tab == "groups":
                launcher._instance_actions.pack_forget.assert_called_once()
            else:
                self.assertIs(
                    launcher._instance_actions.pack.call_args.kwargs["before"], launcher.sidebar_list,
                )
                launcher._instance_actions.pack_forget.assert_not_called()
            if tab == "servers":
                launcher._kill_instances_button.pack_forget.assert_called_once()
            elif tab == "instances":
                launcher._kill_instances_button.pack.assert_called_once()
        launcher._refresh_button.pack_forget.assert_not_called()

    def test_select_group_sets_selection_and_renders_detail(self) -> None:
        """Catches a group click that leaves detail state out of sync."""
        launcher = object.__new__(window.LauncherWindow)
        launcher._render_sidebar = Mock()
        launcher._render_group_detail = Mock()

        launcher._select_group("Local stack")

        self.assertEqual(launcher.selected_group_name, "Local stack")
        launcher._render_sidebar.assert_called_once_with()
        launcher._render_group_detail.assert_called_once_with("Local stack")


class GroupManagementTests(unittest.TestCase):
    def test_dialog_rechecks_selected_instance_identity_and_liveness_on_save(self) -> None:
        for change in ("stopped", "removed", "replaced", "unchanged"):
            with self.subTest(change=change):
                launcher = object.__new__(window.LauncherWindow)
                launcher.root = Mock()
                live = SimpleNamespace(
                    template=SimpleNamespace(key="ai_agent"), port=9100, extra_env={},
                    extra_args="", preset_name=None, is_alive=Mock(return_value=True),
                )
                launcher.instances = {"original": live}
                launcher._save_group = Mock(return_value=True)
                launcher._set_tab = Mock()
                launcher._select_group = Mock()
                with patch.multiple(window.tk, Toplevel=Mock(), Label=Mock(),
                                    Entry=Mock(), Checkbutton=Mock(), Frame=Mock(),
                                    StringVar=Mock(return_value=Mock(get=Mock(return_value="Stack"))),
                                    BooleanVar=Mock(return_value=Mock(get=Mock(return_value=True)))), \
                     patch.object(window, "RoundedButton") as button, \
                     patch.object(window.messagebox, "showerror") as error:
                    launcher._show_create_group_dialog()
                    save = next(call.kwargs["command"] for call in button.call_args_list
                                if call.args[1] == "Save")
                    if change == "stopped":
                        live.is_alive.return_value = False
                    elif change == "removed":
                        launcher.instances.clear()
                    elif change == "replaced":
                        launcher.instances["original"] = SimpleNamespace(**vars(live))
                    save()
                if change == "unchanged":
                    launcher._save_group.assert_called_once_with(
                        "Stack", [models.GroupMember("ai_agent", 9100)],
                    )
                    error.assert_not_called()
                else:
                    launcher._save_group.assert_not_called()
                    error.assert_called_once()

    def test_live_group_members_snapshot_only_running_instances(self) -> None:
        """Catches stopped instances or mutable env state leaking into a saved group."""
        launcher = object.__new__(window.LauncherWindow)
        env = {"AI_AGENT_PROVIDER": "anthropic"}
        live = SimpleNamespace(
            template=SimpleNamespace(key="ai_agent"), port=9100, extra_env=env,
            extra_args="--gateway openrouter", preset_name="OpenRouter", is_alive=lambda: True,
        )
        closed = SimpleNamespace(
            template=SimpleNamespace(key="mcp_server"), port=9200, extra_env={},
            extra_args="", preset_name=None, is_alive=lambda: False,
        )
        launcher.instances = {"live": live, "closed": closed}

        members = launcher._live_group_members()
        env["AI_AGENT_PROVIDER"] = "changed"

        self.assertEqual(
            members,
            [models.GroupMember(
                "ai_agent", 9100, {"AI_AGENT_PROVIDER": "anthropic"},
                "--gateway openrouter", "OpenRouter",
            )],
        )

    def test_save_group_replaces_existing_recipe_after_confirmation(self) -> None:
        """Catches replacement that mutates memory without saving the new recipe."""
        launcher = object.__new__(window.LauncherWindow)
        launcher.root = Mock()
        launcher.groups = {"Local stack": models.ServerGroup("Local stack", [])}
        members = [models.GroupMember("ai_agent", 9100)]

        with patch.object(window.messagebox, "askyesno", return_value=True) as confirm, \
             patch.object(window, "_save_groups") as save_groups:
            saved = launcher._save_group("Local stack", members)

        self.assertTrue(saved)
        self.assertEqual(launcher.groups["Local stack"].members, members)
        confirm.assert_called_once()
        save_groups.assert_called_once_with(launcher.groups)

    def test_save_group_keeps_existing_recipe_when_replacement_declined(self) -> None:
        """Catches a declined replacement overwriting a saved recipe anyway."""
        launcher = object.__new__(window.LauncherWindow)
        launcher.root = Mock()
        original = models.ServerGroup("Local stack", [models.GroupMember("old", 1)])
        launcher.groups = {"Local stack": original}

        with patch.object(window.messagebox, "askyesno", return_value=False), \
             patch.object(window, "_save_groups") as save_groups:
            saved = launcher._save_group("Local stack", [models.GroupMember("new", 2)])

        self.assertFalse(saved)
        self.assertIs(launcher.groups["Local stack"], original)
        save_groups.assert_not_called()

    def test_delete_group_removes_recipe_without_stopping_live_instances(self) -> None:
        """Catches group deletion affecting the instances from which it was saved."""
        launcher = object.__new__(window.LauncherWindow)
        launcher.root = Mock()
        launcher.active_tab = "groups"
        launcher.selected_group_name = "Local stack"
        live = Mock()
        launcher.instances = {"live": live}
        launcher.groups = {"Local stack": models.ServerGroup("Local stack", [])}
        launcher._render_sidebar = Mock()
        launcher._render_group_detail = Mock()

        with patch.object(window.messagebox, "askyesno", return_value=True), \
             patch.object(window, "_save_groups") as save_groups:
            launcher._delete_group("Local stack")

        self.assertEqual(launcher.groups, {})
        self.assertIsNone(launcher.selected_group_name)
        save_groups.assert_called_once_with(launcher.groups)
        live.stop.assert_not_called()
        launcher._render_sidebar.assert_called_once_with()
        launcher._render_group_detail.assert_called_once_with(None)


class GroupStartTests(unittest.TestCase):
    def test_multi_member_preflight_blocks_every_launch_for_invalid_or_conflicting_members(self) -> None:
        for second_member in (
            models.GroupMember("ai_agent", 9101, None),
            models.GroupMember("ai_agent", "9101"),
            models.GroupMember([], 9101),
            models.GroupMember("ai_agent", 9100),
            models.GroupMember("missing", 9101),
            models.GroupMember("ai_agent", 9200),
        ):
            with self.subTest(second_member=second_member):
                launcher = object.__new__(window.LauncherWindow)
                launcher.root = Mock()
                launcher.templates = [SimpleNamespace(key="ai_agent", display_name="AI Agent")]
                launcher.groups = {"Stack": models.ServerGroup("Stack", [
                    models.GroupMember("ai_agent", 9100), second_member,
                ])}
                launcher.instances = {}
                launcher._wire_instance = Mock()
                with patch.object(window, "_port_in_use", side_effect=lambda port: port == 9200), \
                     patch.object(window, "Instance") as instance, \
                     patch.object(window.messagebox, "showerror") as error:
                    launcher._start_group("Stack")
                instance.assert_not_called()
                launcher._wire_instance.assert_not_called()
                self.assertEqual(launcher.instances, {})
                error.assert_called_once()

    def test_preflight_reports_duplicate_ports_even_when_they_are_free(self) -> None:
        launcher = object.__new__(window.LauncherWindow)
        launcher.templates = [SimpleNamespace(key="ai_agent", display_name="AI Agent")]
        group = models.ServerGroup("Stack", [
            models.GroupMember("ai_agent", 9100),
            models.GroupMember("ai_agent", 9100),
        ])
        with patch.object(window, "_port_in_use", return_value=False):
            self.assertEqual(launcher._group_start_issues(group), [
                "Port 9100 is requested by more than one group member.",
            ])

    def test_group_preflight_lists_missing_templates_and_occupied_ports(self) -> None:
        """Catches a group launch proceeding despite every validation blocker."""
        launcher = object.__new__(window.LauncherWindow)
        launcher.templates = [SimpleNamespace(key="ai_agent", display_name="AI Agent")]
        group = models.ServerGroup("Stack", [
            models.GroupMember("missing", 8000),
            models.GroupMember("ai_agent", 9100),
        ])

        with patch.object(window, "_port_in_use", side_effect=lambda port: port == 9100):
            issues = launcher._group_start_issues(group)

        self.assertEqual(issues, [
            "Missing server template: missing.",
            "Port 9100 is already in use for AI Agent.",
        ])

    def test_start_group_does_not_launch_when_preflight_fails(self) -> None:
        """Catches an invalid group partially launching before reporting its errors."""
        launcher = object.__new__(window.LauncherWindow)
        launcher.root = Mock()
        launcher.groups = {"Stack": models.ServerGroup("Stack", [])}
        launcher._group_start_issues = Mock(return_value=["Port 9100 is already in use."])

        with patch.object(window, "Instance") as instance, \
             patch.object(window.messagebox, "showerror"):
            launcher._start_group("Stack")

        instance.assert_not_called()

    def test_start_group_uses_each_saved_member_configuration_exactly(self) -> None:
        """Catches group starts changing a saved port or launch option."""
        launcher = object.__new__(window.LauncherWindow)
        template = SimpleNamespace(key="ai_agent", display_name="AI Agent")
        member = models.GroupMember(
            "ai_agent", 9100, {"AI_AGENT_PROVIDER": "anthropic"},
            "--gateway openrouter", "OpenRouter",
        )
        launcher.groups = {"Stack": models.ServerGroup("Stack", [member])}
        launcher.templates = [template]
        launcher.instances = {}
        launcher.status = Mock()
        launcher._group_start_issues = Mock(return_value=[])
        launcher._wire_instance = Mock()
        launcher._set_tab = Mock()
        launcher._select_instance = Mock()
        created = SimpleNamespace(id="ai_agent:9100:1")

        with patch.object(window, "Instance", return_value=created) as instance:
            launcher._start_group("Stack")

        instance.assert_called_once_with(
            template, 9100, {"AI_AGENT_PROVIDER": "anthropic"},
            "--gateway openrouter", preset_name="OpenRouter",
        )
        launcher._wire_instance.assert_called_once_with(created)
        self.assertEqual(launcher.instances, {created.id: created})
        launcher._set_tab.assert_called_once_with("instances")
        launcher._select_instance.assert_called_once_with(created.id)


class InstanceTests(unittest.TestCase):
    def test_instance_remembers_the_preset_used_to_start_it(self) -> None:
        template = SimpleNamespace(key="demo")
        with patch.object(instance_module.Instance, "_launch"):
            instance = instance_module.Instance(
                template, 8123, {}, "", preset_name="local development"
            )

        self.assertEqual(instance.preset_name, "local development")


class ClearClosedInstancesTests(unittest.TestCase):
    def test_clear_closed_instances_removes_only_closed_entries_and_selection(self) -> None:
        launcher = object.__new__(window.LauncherWindow)
        open_instance = SimpleNamespace(is_alive=lambda: True)
        closed_instance = SimpleNamespace(is_alive=lambda: False)
        launcher.instances = {"open": open_instance, "closed": closed_instance}
        launcher.selected_instance_id = "closed"
        launcher._render_sidebar = Mock()
        launcher._render_instance_detail = Mock()
        launcher.status = Mock()

        launcher._clear_closed_instances()

        self.assertEqual(launcher.instances, {"open": open_instance})
        self.assertIsNone(launcher.selected_instance_id)
        launcher._render_sidebar.assert_called_once_with()
        launcher._render_instance_detail.assert_called_once_with(None)
        launcher.status.config.assert_called_once_with(text="Cleared 1 closed instance.")


class InstanceSidebarTests(unittest.TestCase):
    def test_sidebar_shows_only_the_port_when_instance_has_a_preset(self) -> None:
        launcher = object.__new__(window.LauncherWindow)
        instance = SimpleNamespace(
            id="demo:8123:1",
            template=SimpleNamespace(display_name="Demo"),
            port=8123,
            preset_name="local development",
            is_alive=lambda: True,
        )
        launcher.active_tab = "instances"
        launcher.instances = {instance.id: instance}
        launcher.selected_instance_id = instance.id
        launcher.instance_dots = {}
        launcher.sidebar_list = SimpleNamespace(winfo_children=lambda: [])

        with patch.object(window, "RoundedCard") as card:
            launcher._render_sidebar()

        self.assertEqual(card.call_args.kwargs["secondary"], ":8123")
