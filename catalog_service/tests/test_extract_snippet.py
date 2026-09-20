from __future__ import annotations

from pathlib import Path

from src.scanner import extract_snippet, scan_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_extract_snippet_returns_decorator_through_end_of_function(tmp_path):
    src_root = tmp_path / "chat_app" / "src"
    _write(
        src_root / "foo.py",
        "@catalog\n"
        "def bar(x: int):\n"
        "    'Adds one.'\n"
        "    return x + 1\n",
    )
    entries = scan_project("chat_app", src_root)
    entry = entries[0].to_dict()

    snippet = extract_snippet([("chat_app", src_root)], entry)

    assert snippet == "@catalog\ndef bar(x: int):\n    'Adds one.'\n    return x + 1"


def test_extract_snippet_returns_class_body(tmp_path):
    # _class_entry stores `line` as the class's own line, not the decorator's
    # (unlike _function_entry) - the snippet starts there too, matching what
    # the UI's file:line pointer actually points at.
    src_root = tmp_path / "chat_app" / "src"
    _write(
        src_root / "widgets.py",
        "@catalog\n"
        "class Widget:\n"
        "    def __init__(self):\n"
        "        pass\n",
    )
    entries = scan_project("chat_app", src_root)
    entry = entries[0].to_dict()

    snippet = extract_snippet([("chat_app", src_root)], entry)

    assert snippet == "class Widget:\n    def __init__(self):\n        pass"


def test_extract_snippet_returns_a_decorated_methods_body(tmp_path):
    src_root = tmp_path / "chat_app" / "src"
    _write(
        src_root / "widgets.py",
        "class Widget:\n"
        "    @catalog\n"
        "    def render(self, size: int):\n"
        "        return size\n",
    )
    entries = scan_project("chat_app", src_root)
    entry = entries[0].to_dict()

    snippet = extract_snippet([("chat_app", src_root)], entry)

    assert snippet == "    @catalog\n    def render(self, size: int):\n        return size"


def test_extract_snippet_returns_none_for_unknown_project(tmp_path):
    entry = {"project": "does_not_exist", "file": "foo.py", "line": 1, "type": "function"}

    assert extract_snippet([("chat_app", tmp_path)], entry) is None


def test_extract_snippet_returns_none_when_file_missing(tmp_path):
    src_root = tmp_path / "chat_app" / "src"
    entry = {"project": "chat_app", "file": "src/gone.py", "line": 1, "type": "function"}

    assert extract_snippet([("chat_app", src_root)], entry) is None


def test_extract_snippet_returns_none_when_source_no_longer_matches(tmp_path):
    src_root = tmp_path / "chat_app" / "src"
    _write(src_root / "foo.py", "@catalog\ndef bar():\n    pass\n")
    entry = {"project": "chat_app", "file": "src/foo.py", "line": 999, "type": "function"}

    assert extract_snippet([("chat_app", src_root)], entry) is None
