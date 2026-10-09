"""Focused behavior checks for the desktop server launcher."""

from types import SimpleNamespace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from src import add_dialog, agent_files, config, discovery, instance as instance_module, models, runtimes, specs, storage, window


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

    def test_only_the_given_project_folders_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            main, extra = Path(directory) / "MCPServer", Path(directory) / "PDFMerger"
            self._make_project(main, "mcp_server", "MCP Server", 8010)
            self._make_project(main, "unlisted", "Unlisted", 8011)
            self._make_project(extra, "pdf_merger", "PDF Merger", 8040)

            templates = discovery.discover_templates([main / "mcp_server", extra / "pdf_merger", extra / "nope"])

        by_key = {t.key: t for t in templates}
        self.assertEqual(set(by_key), {"mcp_server", "pdf_merger"})
        self.assertEqual(by_key["pdf_merger"].display_name, "PDF Merger")
        self.assertEqual(by_key["pdf_merger"].default_port, 8040)

    def test_first_folder_wins_when_two_projects_share_a_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            main, extra = Path(directory) / "a", Path(directory) / "b"
            self._make_project(main, "tool", "Main tool", 1000)
            self._make_project(extra, "tool", "Other tool", 2000)

            [template] = discovery.discover_templates([main / "tool", extra / "tool"])

        self.assertEqual(template.display_name, "Main tool")

    def test_saved_specs_round_trip_and_a_bad_copy_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projects = Path(directory) / "projects"
            with patch.object(storage, "_PROJECTS_DIR", projects):
                good = models.LaunchSpec(
                    Path(directory) / "tool", "Tool", "d", "python", "tool", "src.run", "T_PORT", 9000, {"A": "1"}, True, "bat",
                )
                storage._save_spec(good)
                (projects / "broken").mkdir()
                (projects / "broken" / specs.SPEC_FILE_NAME).write_text("{not json", encoding="utf-8")
                loaded = storage._load_saved_specs()
                storage._delete_saved_spec("tool")
                after = storage._load_saved_specs()

        self.assertEqual(loaded, [good])
        self.assertEqual(after, [])


class SpecFileTests(unittest.TestCase):
    def _project(self, root: Path, name: str, spec: object = None, bat: bool = False) -> Path:
        folder = root / name
        folder.mkdir()
        if spec is not None:
            (folder / specs.SPEC_FILE_NAME).write_text(spec if isinstance(spec, str) else json.dumps(spec), encoding="utf-8")
        if bat:
            (folder / "run.bat").write_text(
                _PY_RUN_BAT.format(label="From bat", port_var="X_PORT", port=1111, venv=name), encoding="utf-8"
            )
        return folder

    def test_run_srvlnchr_is_read_and_wins_over_run_bat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = self._project(
                Path(directory), "tool",
                {"label": "From file", "venv": "tool", "module": "src.run", "port": 9000, "port_env_var": "T_PORT", "env": {"mode": "dev"}},
                bat=True,
            )
            spec = discovery.read_project_spec(folder)

        self.assertEqual(
            (spec.label, spec.source, spec.port, spec.port_env_var, spec.env),
            ("From file", "srvlnchr", 9000, "T_PORT", {"MODE": "dev"}),
        )

    def test_a_bad_run_srvlnchr_names_the_problem_and_skip_leaves_the_project_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ("notjson", "{nope"), ("novenv", {"module": "m"}), ("badport", {"venv": "x", "module": "m", "port": "80"}),
                ("nopkg", {"runtime": "node", "module": "dev"}),
            )
            for name, content in cases:
                with self.subTest(name=name), self.assertRaises(specs.SpecError):
                    discovery.read_project_spec(self._project(root, name, content))
            self.assertIsNone(discovery.read_project_spec(self._project(root, "skipped", {"skip": True}, bat=True)))
            self.assertIsNone(discovery.read_project_spec(self._project(root, "nothing")))

    def test_saved_spec_still_runs_after_the_project_file_is_erased(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = self._project(Path(directory), "tool", bat=True)
            saved = discovery.read_project_spec(folder)
            (folder / "run.bat").unlink()

            self.assertEqual(discovery.refreshed_spec(saved), saved)
            (folder / "run.bat").write_text(
                _PY_RUN_BAT.format(label="Renamed", port_var="X_PORT", port=1111, venv="tool"), encoding="utf-8"
            )
            self.assertEqual(discovery.refreshed_spec(saved).label, "Renamed")
            manual = models.LaunchSpec(folder, "Mine", module="m", venv="v", source="manual")
            self.assertEqual(discovery.refreshed_spec(manual), manual)

    def test_manual_spec_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            spec = specs.build_manual_spec(folder, " ", "python", "v", "src.run", "", "8123", "A=1\n\nb = 2", True)
            self.assertEqual(
                (spec.label, spec.port_env_var, spec.port, spec.env, spec.supports_args, spec.source),
                (folder.name, f"{folder.name.upper()}_PORT", 8123, {"A": "1", "B": "2"}, True, "manual"),
            )
            bad_values = (
                ("python", "", "m", "", "8000", ""), ("python", "v", "m", "", "x", ""),
                ("python", "v", "m", "", "8000", "oops"), ("node", "", "dev", "", "8000", ""),
            )
            for runtime, venv, module, port_var, port, env in bad_values:
                with self.subTest(runtime=runtime, venv=venv, port=port, env=env), self.assertRaises(specs.SpecError):
                    specs.build_manual_spec(folder, "", runtime, venv, module, port_var, port, env, False)


class AddDialogTests(unittest.TestCase):
    def _bat_project(self, root: Path, name: str) -> Path:
        (root / name).mkdir()
        (root / name / "run.bat").write_text(
            _PY_RUN_BAT.format(label=name, port_var="X_PORT", port=9000, venv=name), encoding="utf-8"
        )
        return root / name

    def test_check_folder_accepts_a_launchable_project_and_names_why_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool = self._bat_project(root, "tool")
            (root / "empty").mkdir()
            (root / "bad").mkdir()
            (root / "bad" / specs.SPEC_FILE_NAME).write_text("{nope", encoding="utf-8")

            spec, error = add_dialog.check_folder(tool, set())
            self.assertEqual((spec.key, error), ("tool", None))
            spec, error = add_dialog.check_folder(root / "empty", set())
            self.assertIsNone(spec)
            self.assertIn("no launchable", error)
            spec, error = add_dialog.check_folder(root / "bad", set())
            self.assertIn("not valid JSON", error)
            spec, error = add_dialog.check_folder(tool, {"tool"})
            self.assertIn("already in the list", error)

    def test_add_folder_lists_valid_folders_once_and_confirm_returns_the_specs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a", "b"):
                self._bat_project(root, name)
            (root / "bad").mkdir()
            dialog = object.__new__(add_dialog.AddServersDialog)
            dialog._taken, dialog._specs, dialog._list, dialog.dialog = set(), [], Mock(), Mock()
            dialog._on_add = Mock()
            manual = models.LaunchSpec(root / "m", "Manual", module="x", venv="v", source="manual")
            with patch.object(add_dialog.messagebox, "showerror") as error:
                results = [dialog.add_folder(root / name) for name in ("a", "b", "a", "bad")]
                results += [dialog.add_spec(manual), dialog.add_spec(manual)]
                dialog._confirm()

        self.assertEqual(results, [True, True, False, False, True, False])
        self.assertEqual(error.call_count, 2)
        [sent] = dialog._on_add.call_args.args
        self.assertEqual([spec.key for spec in sent], ["a", "b", "m"])

    def test_add_servers_saves_each_spec_lists_them_and_selects_the_first(self) -> None:
        a = SimpleNamespace(key="a", working_dir=Path("/p/a").resolve())
        b = SimpleNamespace(key="b", working_dir=Path("/p/b").resolve())
        launcher = object.__new__(window.LauncherWindow)
        launcher.status, launcher.templates = Mock(), []
        launcher._render_sidebar = launcher._render_server_detail = Mock()
        launcher._discover = lambda: [a, b]
        new = [models.LaunchSpec(Path("/p/a"), "A"), models.LaunchSpec(Path("/p/b"), "B")]
        with patch.object(window, "_save_spec") as save:
            launcher._add_servers(new)

        self.assertEqual([call.args[0] for call in save.call_args_list], new)
        self.assertIs(launcher.selected_template, a)


class DataDirTests(unittest.TestCase):
    def test_default_is_appdata_scuti_server_launcher(self) -> None:
        self.assertEqual(config.resolve_data_dir([], {"APPDATA": r"C:\Users\me\AppData\Roaming"}),
                         Path(r"C:\Users\me\AppData\Roaming") / "scuti_server_launcher")

    def test_flag_beats_env_beats_location_file_beats_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            appdata = Path(directory)
            default = appdata / "scuti_server_launcher"
            default.mkdir()
            (default / "data_location.txt").write_text(f"{directory}/from_file\nignored\n", encoding="utf-8")
            env = {"APPDATA": directory, "SCUTI_SERVER_LAUNCHER_DATA": f"{directory}/from_env"}

            self.assertEqual(config.resolve_data_dir(["--data-dir", f"{directory}/from_flag"], env), Path(f"{directory}/from_flag"))
            self.assertEqual(config.resolve_data_dir([f"--data-dir={directory}/from_eq"], env), Path(f"{directory}/from_eq"))
            self.assertEqual(config.resolve_data_dir([], env), Path(f"{directory}/from_env"))
            self.assertEqual(config.resolve_data_dir([], {"APPDATA": directory}), Path(f"{directory}/from_file"))
            (default / "data_location.txt").write_text("  \n", encoding="utf-8")
            self.assertEqual(config.resolve_data_dir(["--data-dir"], {"APPDATA": directory}), default)

    def test_legacy_groups_and_presets_are_copied_once_and_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            legacy, data = Path(directory) / "old", Path(directory) / "new"
            legacy.mkdir()
            (legacy / "groups.json").write_text("{\"old\": 1}", encoding="utf-8")
            (legacy / "presets.json").write_text("{}", encoding="utf-8")
            data.mkdir()
            (data / "presets.json").write_text("{\"kept\": 1}", encoding="utf-8")
            with patch.object(storage, "_GROUPS_PATH", data / "groups.json"), patch.object(storage, "_PRESETS_PATH", data / "presets.json"):
                storage._migrate_legacy_data(legacy)
                storage._migrate_legacy_data(legacy)
            self.assertEqual((data / "groups.json").read_text(encoding="utf-8"), "{\"old\": 1}")
            self.assertEqual((data / "presets.json").read_text(encoding="utf-8"), "{\"kept\": 1}")


class RuntimeWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        for finder in (runtimes.find_python, runtimes.find_node):
            finder.cache_clear()
            self.addCleanup(finder.cache_clear)

    def _template(self, runtime: str, venv_python: Path | None = None) -> SimpleNamespace:
        return SimpleNamespace(runtime=runtime, venv_python=venv_python)

    def test_python_project_warns_only_when_it_has_no_venv_and_no_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / "python.exe"
            with patch.object(runtimes, "find_python", return_value=None):
                self.assertIn("python.org", runtimes.runtime_warning(self._template("python", venv)))
                venv.write_text("", encoding="utf-8")
                self.assertIsNone(runtimes.runtime_warning(self._template("python", venv)))
            with patch.object(runtimes, "find_python", return_value=["py", "-3"]):
                venv.unlink()
                self.assertIsNone(runtimes.runtime_warning(self._template("python", venv)))

    def test_node_project_warns_when_node_or_npm_is_missing(self) -> None:
        for found, warned in ((True, False), (False, True)):
            with self.subTest(found=found), patch.object(runtimes, "find_node", return_value=found):
                warning = runtimes.runtime_warning(self._template("node"))
                self.assertEqual(warning is not None, warned)
                if warned:
                    self.assertIn("nodejs.org", warning)

    def test_find_python_runs_each_candidate_so_a_store_stub_is_not_taken_for_python(self) -> None:
        results = {"py": 9009, "python": 0}

        def run(command, **kwargs):
            return SimpleNamespace(returncode=results[command[0]])

        with patch.object(runtimes.shutil, "which", side_effect=lambda name: name if name in results else None), \
                patch.object(runtimes.subprocess, "run", side_effect=run):
            self.assertEqual(runtimes.find_python(), ["python"])
            runtimes.find_python.cache_clear()
            results["python"] = 1  # too old, or the Store stub
            self.assertIsNone(runtimes.find_python())

    def test_find_node_needs_both_node_and_npm(self) -> None:
        for present, expected in (({"node", "npm"}, True), ({"node"}, False), (set(), False)):
            runtimes.find_node.cache_clear()
            with self.subTest(present=present), patch.object(runtimes.shutil, "which", side_effect=lambda n: n if n in present else None):
                self.assertEqual(runtimes.find_node(), expected)


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

            (template,) = discovery.discover_templates([root / "ai_agent"])

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
            templates = discovery.discover_templates([root / "mcp_server", root / "chat_cli"])

        self.assertEqual([t.key for t in templates], ["mcp_server"])

    def test_a_project_without_agent_files_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mcp_server").mkdir()
            (root / "mcp_server" / "run.bat").write_text(
                _PY_RUN_BAT.format(label="MCP", port_var="MCP_PORT", port=8010, venv="mcp"), encoding="utf-8"
            )
            (template,) = discovery.discover_templates([root / "mcp_server"])

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

        with patch.object(window, "_port_in_use", side_effect=lambda port: port == 9100), \
                patch.object(window, "runtime_warning", return_value=None):
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
            "_add_server_button", "_remove_server_button", "_clear_closed_button", "_restart_all_button", "_create_group_button", "sidebar_list", "_sidebar_scroll",
            "_render_sidebar", "_render_server_detail", "_render_instance_detail",
            "_render_group_detail",
        ):
            setattr(launcher, attribute, Mock())
        launcher.selected_template = launcher.selected_instance_id = launcher.selected_group_name = None

        for tab in ("groups", "instances", "servers", "instances"):
            launcher._instance_actions.reset_mock()
            launcher._kill_instances_button.reset_mock()
            launcher._add_server_button.reset_mock()
            launcher._remove_server_button.reset_mock()
            launcher._refresh_button.reset_mock()
            launcher._set_tab(tab)
            if tab == "groups":
                launcher._instance_actions.pack_forget.assert_called_once()
            else:
                self.assertIs(
                    launcher._instance_actions.pack.call_args.kwargs["before"], launcher._sidebar_scroll,
                )
                launcher._instance_actions.pack_forget.assert_not_called()
            if tab == "servers":
                launcher._kill_instances_button.pack_forget.assert_called_once()
                launcher._kill_instances_button.pack.assert_not_called()
                launcher._add_server_button.pack.assert_called_once()
                launcher._remove_server_button.pack.assert_called_once()
            elif tab == "instances":
                launcher._kill_instances_button.pack.assert_called_once()
                launcher._add_server_button.pack.assert_not_called()
                launcher._remove_server_button.pack.assert_not_called()
            if tab in ("servers", "instances"):
                launcher._refresh_button.pack.assert_called_once()  # refresh stays visible on both tabs

    def test_remove_forgets_the_saved_copy_and_does_nothing_when_declined_or_unselected(self) -> None:
        added = SimpleNamespace(key="tool", display_name="Tool", working_dir=Path("/elsewhere/tool").resolve())
        launcher = object.__new__(window.LauncherWindow)
        launcher.templates, launcher.status = [added], Mock()
        launcher.root = launcher._render_sidebar = launcher._render_server_detail = Mock()
        launcher._discover = lambda: []
        with patch.object(window, "_delete_saved_spec") as delete, patch.object(window.messagebox, "askyesno", return_value=False):
            launcher.selected_template = None
            launcher._remove_server()
            launcher.selected_template = added
            launcher._remove_server()
        delete.assert_not_called()

        with patch.object(window, "_delete_saved_spec") as delete, patch.object(window.messagebox, "askyesno", return_value=True):
            launcher._remove_server()

        delete.assert_called_once_with("tool")
        self.assertEqual(launcher.templates, [])
        self.assertIsNone(launcher.selected_template)

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
    def setUp(self) -> None:
        patcher = patch.object(window, "runtime_warning", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

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
