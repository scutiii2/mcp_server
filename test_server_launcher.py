"""Focused behavior checks for the desktop server launcher."""

from types import SimpleNamespace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import server_launcher


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
                    with patch.object(server_launcher, "_GROUPS_PATH", groups_path):
                        self.assertEqual(server_launcher._load_groups(), {})

    def test_groups_round_trip_through_json(self) -> None:
        """Catches a missing or incomplete persisted group-member field."""
        groups = {
            "Local stack": server_launcher.ServerGroup(
                "Local stack",
                [
                    server_launcher.GroupMember(
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
            with patch.object(server_launcher, "_GROUPS_PATH", Path(directory) / "groups.json"):
                server_launcher._save_groups(groups)
                loaded = server_launcher._load_groups()

        self.assertEqual(loaded, groups)

    def test_invalid_group_json_loads_as_empty_groups(self) -> None:
        """Catches malformed persisted JSON escaping the launcher startup path."""
        with tempfile.TemporaryDirectory() as directory:
            groups_path = Path(directory) / "groups.json"
            groups_path.write_text("not JSON", encoding="utf-8")
            with patch.object(server_launcher, "_GROUPS_PATH", groups_path):
                loaded = server_launcher._load_groups()

        self.assertEqual(loaded, {})

    def test_non_utf8_group_data_loads_as_empty_groups(self) -> None:
        """Catches corrupt group-file bytes crashing launcher startup."""
        with tempfile.TemporaryDirectory() as directory:
            groups_path = Path(directory) / "groups.json"
            groups_path.write_bytes(b"\xff\xfe")
            with patch.object(server_launcher, "_GROUPS_PATH", groups_path):
                loaded = server_launcher._load_groups()

        self.assertEqual(loaded, {})


class GroupTabTests(unittest.TestCase):
    def test_tab_switch_keeps_actions_before_list_and_refresh_on_servers(self) -> None:
        launcher = object.__new__(server_launcher.LauncherWindow)
        for attribute in (
            "servers_tab_btn", "instances_tab_btn", "groups_tab_btn", "_instance_actions",
            "_instance_actions_row", "_kill_instances_button", "_refresh_button",
            "_clear_closed_button", "_create_group_button", "sidebar_list",
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
        launcher = object.__new__(server_launcher.LauncherWindow)
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
                launcher = object.__new__(server_launcher.LauncherWindow)
                launcher.root = Mock()
                live = SimpleNamespace(
                    template=SimpleNamespace(key="ai_agent"), port=9100, extra_env={},
                    extra_args="", preset_name=None, is_alive=Mock(return_value=True),
                )
                launcher.instances = {"original": live}
                launcher._save_group = Mock(return_value=True)
                launcher._set_tab = Mock()
                launcher._select_group = Mock()
                with patch.multiple(server_launcher.tk, Toplevel=Mock(), Label=Mock(),
                                    Entry=Mock(), Checkbutton=Mock(), Frame=Mock(),
                                    StringVar=Mock(return_value=Mock(get=Mock(return_value="Stack"))),
                                    BooleanVar=Mock(return_value=Mock(get=Mock(return_value=True)))), \
                     patch.object(server_launcher, "RoundedButton") as button, \
                     patch.object(server_launcher.messagebox, "showerror") as error:
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
                        "Stack", [server_launcher.GroupMember("ai_agent", 9100)],
                    )
                    error.assert_not_called()
                else:
                    launcher._save_group.assert_not_called()
                    error.assert_called_once()

    def test_live_group_members_snapshot_only_running_instances(self) -> None:
        """Catches stopped instances or mutable env state leaking into a saved group."""
        launcher = object.__new__(server_launcher.LauncherWindow)
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
            [server_launcher.GroupMember(
                "ai_agent", 9100, {"AI_AGENT_PROVIDER": "anthropic"},
                "--gateway openrouter", "OpenRouter",
            )],
        )

    def test_save_group_replaces_existing_recipe_after_confirmation(self) -> None:
        """Catches replacement that mutates memory without saving the new recipe."""
        launcher = object.__new__(server_launcher.LauncherWindow)
        launcher.root = Mock()
        launcher.groups = {"Local stack": server_launcher.ServerGroup("Local stack", [])}
        members = [server_launcher.GroupMember("ai_agent", 9100)]

        with patch.object(server_launcher.messagebox, "askyesno", return_value=True) as confirm, \
             patch.object(server_launcher, "_save_groups") as save_groups:
            saved = launcher._save_group("Local stack", members)

        self.assertTrue(saved)
        self.assertEqual(launcher.groups["Local stack"].members, members)
        confirm.assert_called_once()
        save_groups.assert_called_once_with(launcher.groups)

    def test_save_group_keeps_existing_recipe_when_replacement_declined(self) -> None:
        """Catches a declined replacement overwriting a saved recipe anyway."""
        launcher = object.__new__(server_launcher.LauncherWindow)
        launcher.root = Mock()
        original = server_launcher.ServerGroup("Local stack", [server_launcher.GroupMember("old", 1)])
        launcher.groups = {"Local stack": original}

        with patch.object(server_launcher.messagebox, "askyesno", return_value=False), \
             patch.object(server_launcher, "_save_groups") as save_groups:
            saved = launcher._save_group("Local stack", [server_launcher.GroupMember("new", 2)])

        self.assertFalse(saved)
        self.assertIs(launcher.groups["Local stack"], original)
        save_groups.assert_not_called()

    def test_delete_group_removes_recipe_without_stopping_live_instances(self) -> None:
        """Catches group deletion affecting the instances from which it was saved."""
        launcher = object.__new__(server_launcher.LauncherWindow)
        launcher.root = Mock()
        launcher.active_tab = "groups"
        launcher.selected_group_name = "Local stack"
        live = Mock()
        launcher.instances = {"live": live}
        launcher.groups = {"Local stack": server_launcher.ServerGroup("Local stack", [])}
        launcher._render_sidebar = Mock()
        launcher._render_group_detail = Mock()

        with patch.object(server_launcher.messagebox, "askyesno", return_value=True), \
             patch.object(server_launcher, "_save_groups") as save_groups:
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
            server_launcher.GroupMember("ai_agent", 9101, None),
            server_launcher.GroupMember("ai_agent", "9101"),
            server_launcher.GroupMember([], 9101),
            server_launcher.GroupMember("ai_agent", 9100),
            server_launcher.GroupMember("missing", 9101),
            server_launcher.GroupMember("ai_agent", 9200),
        ):
            with self.subTest(second_member=second_member):
                launcher = object.__new__(server_launcher.LauncherWindow)
                launcher.root = Mock()
                launcher.templates = [SimpleNamespace(key="ai_agent", display_name="AI Agent")]
                launcher.groups = {"Stack": server_launcher.ServerGroup("Stack", [
                    server_launcher.GroupMember("ai_agent", 9100), second_member,
                ])}
                launcher.instances = {}
                launcher._wire_instance = Mock()
                with patch.object(server_launcher, "_port_in_use", side_effect=lambda port: port == 9200), \
                     patch.object(server_launcher, "Instance") as instance, \
                     patch.object(server_launcher.messagebox, "showerror") as error:
                    launcher._start_group("Stack")
                instance.assert_not_called()
                launcher._wire_instance.assert_not_called()
                self.assertEqual(launcher.instances, {})
                error.assert_called_once()

    def test_preflight_reports_duplicate_ports_even_when_they_are_free(self) -> None:
        launcher = object.__new__(server_launcher.LauncherWindow)
        launcher.templates = [SimpleNamespace(key="ai_agent", display_name="AI Agent")]
        group = server_launcher.ServerGroup("Stack", [
            server_launcher.GroupMember("ai_agent", 9100),
            server_launcher.GroupMember("ai_agent", 9100),
        ])
        with patch.object(server_launcher, "_port_in_use", return_value=False):
            self.assertEqual(launcher._group_start_issues(group), [
                "Port 9100 is requested by more than one group member.",
            ])

    def test_group_preflight_lists_missing_templates_and_occupied_ports(self) -> None:
        """Catches a group launch proceeding despite every validation blocker."""
        launcher = object.__new__(server_launcher.LauncherWindow)
        launcher.templates = [SimpleNamespace(key="ai_agent", display_name="AI Agent")]
        group = server_launcher.ServerGroup("Stack", [
            server_launcher.GroupMember("missing", 8000),
            server_launcher.GroupMember("ai_agent", 9100),
        ])

        with patch.object(server_launcher, "_port_in_use", side_effect=lambda port: port == 9100):
            issues = launcher._group_start_issues(group)

        self.assertEqual(issues, [
            "Missing server template: missing.",
            "Port 9100 is already in use for AI Agent.",
        ])

    def test_start_group_does_not_launch_when_preflight_fails(self) -> None:
        """Catches an invalid group partially launching before reporting its errors."""
        launcher = object.__new__(server_launcher.LauncherWindow)
        launcher.root = Mock()
        launcher.groups = {"Stack": server_launcher.ServerGroup("Stack", [])}
        launcher._group_start_issues = Mock(return_value=["Port 9100 is already in use."])

        with patch.object(server_launcher, "Instance") as instance, \
             patch.object(server_launcher.messagebox, "showerror"):
            launcher._start_group("Stack")

        instance.assert_not_called()

    def test_start_group_uses_each_saved_member_configuration_exactly(self) -> None:
        """Catches group starts changing a saved port or launch option."""
        launcher = object.__new__(server_launcher.LauncherWindow)
        template = SimpleNamespace(key="ai_agent", display_name="AI Agent")
        member = server_launcher.GroupMember(
            "ai_agent", 9100, {"AI_AGENT_PROVIDER": "anthropic"},
            "--gateway openrouter", "OpenRouter",
        )
        launcher.groups = {"Stack": server_launcher.ServerGroup("Stack", [member])}
        launcher.templates = [template]
        launcher.instances = {}
        launcher.status = Mock()
        launcher._group_start_issues = Mock(return_value=[])
        launcher._wire_instance = Mock()
        launcher._set_tab = Mock()
        launcher._select_instance = Mock()
        created = SimpleNamespace(id="ai_agent:9100:1")

        with patch.object(server_launcher, "Instance", return_value=created) as instance:
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
        with patch.object(server_launcher.Instance, "_launch"):
            instance = server_launcher.Instance(
                template, 8123, {}, "", preset_name="local development"
            )

        self.assertEqual(instance.preset_name, "local development")


class ClearClosedInstancesTests(unittest.TestCase):
    def test_clear_closed_instances_removes_only_closed_entries_and_selection(self) -> None:
        launcher = object.__new__(server_launcher.LauncherWindow)
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
        launcher = object.__new__(server_launcher.LauncherWindow)
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

        with patch.object(server_launcher, "RoundedCard") as card:
            launcher._render_sidebar()

        self.assertEqual(card.call_args.kwargs["secondary"], ":8123")
