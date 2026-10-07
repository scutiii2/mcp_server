import tkinter as tk
import unittest
from pathlib import Path

from src.group_editor import GroupEditor
from src.models import GroupMember, Preset, ServerGroup, ServerTemplate


def _template(key: str, port: int, **kwargs) -> ServerTemplate:
    defaults = dict(
        key=key, display_name=key.title(), description="", working_dir=Path("."), venv_python=Path("python.exe"),
        module="src.run", port_env_var="PORT", default_port=port, extra_env_vars={}, supports_args=False,
    )
    defaults.update(kwargs)
    return ServerTemplate(**defaults)


class GroupEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.root.withdraw()
        self.templates = [
            _template("api", 8030, extra_env_vars={"MODE": "dev"}, supports_args=True),
            _template("web", 5173),
        ]
        self.presets = {"api": [Preset("prod", 9000, {"MODE": "prod"}, "--fast")]}
        self.group = ServerGroup("Main", [
            GroupMember("api", 8030, {"MODE": "dev"}, "", None),
            GroupMember("web", 5173),
        ])
        self.saved: list[list[GroupMember]] = []

    def tearDown(self) -> None:
        self.root.destroy()

    def _editor(self) -> GroupEditor:
        return GroupEditor(
            self.root, group=self.group, templates=self.templates, presets=self.presets,
            on_save=self.saved.append, on_cancel=lambda: None,
        )

    def test_edit_fields_returns_new_members_without_touching_the_group(self) -> None:
        editor = self._editor()
        api = editor._forms[0]
        api.port_var.set("8100")
        api.env_vars["MODE"].set("staging")
        api.args_var.set("--debug")
        members = editor.collect()
        self.assertEqual(members[0], GroupMember("api", 8100, {"MODE": "staging"}, "--debug", None))
        self.assertEqual(self.group.members[0].port, 8030)

    def test_remove_and_add_server(self) -> None:
        editor = self._editor()
        editor._remove_form(editor._forms[1])
        editor._add_server(self.templates[1])
        editor._forms[-1].port_var.set("5200")
        self.assertEqual([m.port for m in editor.collect()], [8030, 5200])

    def test_duplicate_port_is_rejected(self) -> None:
        editor = self._editor()
        editor._forms[0].port_var.set("5173")
        with self.assertRaisesRegex(ValueError, "5173"):
            editor.collect()

    def test_bad_port_is_rejected(self) -> None:
        editor = self._editor()
        for value in ("", "abc", "0", "70000"):
            editor._forms[0].port_var.set(value)
            with self.assertRaises(ValueError):
                editor.collect()

    def test_empty_group_is_rejected(self) -> None:
        editor = self._editor()
        for form in list(editor._forms):
            editor._remove_form(form)
        with self.assertRaisesRegex(ValueError, "at least one"):
            editor.collect()

    def test_preset_fills_fields(self) -> None:
        editor = self._editor()
        api = editor._forms[0]
        api._preset_var.set("prod")
        member = editor.collect()[0]
        self.assertEqual(member, GroupMember("api", 9000, {"MODE": "prod"}, "--fast", "prod"))

    def test_unavailable_template_is_kept(self) -> None:
        self.group.members.append(GroupMember("gone", 7000, {"X": "1"}, "a", "p"))
        editor = self._editor()
        self.assertEqual(editor.collect()[-1], GroupMember("gone", 7000, {"X": "1"}, "a", "p"))

    def test_save_error_is_shown_and_not_saved(self) -> None:
        editor = self._editor()
        editor._forms[0].port_var.set("x")
        editor._save()
        self.assertTrue(editor._error.cget("text"))
        self.assertEqual(self.saved, [])
        editor._forms[0].port_var.set("8031")
        editor._save()
        self.assertEqual(len(self.saved), 1)


if __name__ == "__main__":
    unittest.main()
