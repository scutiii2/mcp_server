from __future__ import annotations

from pathlib import Path

from src.scanner import scan_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_project_finds_decorated_function_across_nested_files(tmp_path):
    project_root = tmp_path / "chat_app"
    src_root = project_root / "src"
    _write(
        src_root / "services" / "foo.py",
        "from src.utils.catalog import catalog\n\n"
        "@catalog\n"
        "def bar(x: int):\n"
        "    'Adds one.'\n"
        "    return x + 1\n",
    )

    entries = scan_project("chat_app", src_root)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == "chat_app.src.services.foo.bar"
    assert entry.file == "src/services/foo.py"
    assert entry.project == "chat_app"


def test_scan_project_ignores_undecorated_functions(tmp_path):
    src_root = tmp_path / "chat_app" / "src"
    _write(src_root / "services" / "foo.py", "def bar():\n    pass\n")

    assert scan_project("chat_app", src_root) == []


def test_scan_project_skips_file_with_syntax_error_and_keeps_going(tmp_path, caplog):
    src_root = tmp_path / "chat_app" / "src"
    _write(src_root / "broken.py", "def bar(:\n    pass\n")
    _write(
        src_root / "ok.py",
        "@catalog\ndef good():\n    'fine'\n    pass\n",
    )

    import logging

    with caplog.at_level(logging.WARNING):
        entries = scan_project("chat_app", src_root)

    assert [e.id for e in entries] == ["chat_app.src.ok.good"]
    assert any("broken.py" in message for message in caplog.messages)


def test_scan_project_returns_empty_list_for_missing_directory(tmp_path):
    assert scan_project("chat_app", tmp_path / "does_not_exist") == []


def test_scan_project_catalogs_a_decorated_method_as_its_own_namespaced_entry(tmp_path):
    # A @catalog-decorated method produces its own entry, namespaced under
    # its class (Widget.render, not a bogus top-level "render"), with
    # `self` dropped from parameters - independent of the class's own
    # `methods` listing (still every public method name, decorated or not).
    src_root = tmp_path / "chat_app" / "src"
    _write(
        src_root / "widgets.py",
        "@catalog\n"
        "class Widget:\n"
        "    def __init__(self):\n"
        "        pass\n\n"
        "    @catalog\n"
        "    def render(self, size: int):\n"
        "        pass\n",
    )

    entries = scan_project("chat_app", src_root)

    assert len(entries) == 2
    class_entry = next(e for e in entries if e.type == "class")
    assert class_entry.name == "Widget"
    assert class_entry.methods == ["render"]

    method_entry = next(e for e in entries if e.type == "method")
    assert method_entry.id == "chat_app.src.widgets.Widget.render"
    assert method_entry.name == "render"
    assert [p.name for p in method_entry.parameters] == ["size"]


def test_scan_project_catalogs_a_decorated_method_on_an_undecorated_class(tmp_path):
    # A method can opt itself into the catalog without its class being
    # decorated at all - the class itself produces no entry.
    src_root = tmp_path / "chat_app" / "src"
    _write(
        src_root / "widgets.py",
        "class Widget:\n"
        "    @catalog\n"
        "    def render(self, size: int):\n"
        "        pass\n\n"
        "    def other(self):\n"
        "        pass\n",
    )

    entries = scan_project("chat_app", src_root)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.type == "method"
    assert entry.id == "chat_app.src.widgets.Widget.render"
    assert [p.name for p in entry.parameters] == ["size"]


def test_scan_project_ignores_decorated_function_nested_inside_another_function(tmp_path):
    # Regression test for Finding 1: a @catalog on a function nested inside
    # another function isn't a stable importable symbol and must not be
    # catalogued at all.
    src_root = tmp_path / "chat_app" / "src"
    _write(
        src_root / "foo.py",
        "def outer():\n"
        "    @catalog\n"
        "    def inner(x: int):\n"
        "        return x\n"
        "    return inner\n",
    )

    assert scan_project("chat_app", src_root) == []


def test_scan_project_skips_unreadable_file_and_keeps_going(tmp_path, monkeypatch, caplog):
    # Regression test for Finding 3(a): _scan_file's file_path.read_text()
    # can raise OSError subclasses (PermissionError, a cloud-sync
    # placeholder, a briefly-locked file, etc. - a real occurrence in this
    # repo's OneDrive-synced folder), not just SyntaxError/UnicodeDecodeError.
    # A single unreadable file must be skipped-and-logged, not abort the
    # whole project's scan.
    src_root = tmp_path / "chat_app" / "src"
    _write(src_root / "locked.py", "@catalog\ndef locked_func():\n    pass\n")
    _write(src_root / "ok.py", "@catalog\ndef good():\n    'fine'\n    pass\n")

    from pathlib import Path as PathlibPath

    real_read_text = PathlibPath.read_text

    def fake_read_text(self, *args, **kwargs):
        if self.name == "locked.py":
            raise PermissionError(f"[simulated] cannot read {self}")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(PathlibPath, "read_text", fake_read_text)

    import logging

    with caplog.at_level(logging.WARNING):
        entries = scan_project("chat_app", src_root)

    assert [e.id for e in entries] == ["chat_app.src.ok.good"]
    assert any("locked.py" in message for message in caplog.messages)


def test_scan_project_still_finds_top_level_functions_and_classes(tmp_path):
    # Existing behavior must continue to work after switching from
    # ast.walk() to iterating tree.body directly.
    src_root = tmp_path / "chat_app" / "src"
    _write(
        src_root / "mixed.py",
        "@catalog\n"
        "def top_level_func(x: int):\n"
        "    'A function.'\n"
        "    return x\n\n"
        "@catalog\n"
        "class TopLevelClass:\n"
        "    'A class.'\n"
        "    def __init__(self, y: int):\n"
        "        self.y = y\n\n"
        "    def method_a(self):\n"
        "        pass\n",
    )

    entries = scan_project("chat_app", src_root)

    assert sorted((e.type, e.name) for e in entries) == [
        ("class", "TopLevelClass"),
        ("function", "top_level_func"),
    ]
