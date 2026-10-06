from __future__ import annotations

import ast

from src.scanner import _class_entry


def _parse_class(source: str) -> ast.ClassDef:
    tree = ast.parse(source)
    return tree.body[0]


def test_class_entry_captures_init_params_excluding_self():
    node = _parse_class(
        "@catalog\n"
        "class Widget:\n"
        "    'A reusable widget.'\n"
        "    def __init__(self, size: int):\n"
        "        self.size = size\n"
    )
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.type == "class"
    assert entry.name == "Widget"
    assert entry.description == "A reusable widget."
    assert entry.id == "chat_app.src.services.widgets.Widget"
    assert [p.name for p in entry.parameters] == ["size"]


def test_class_entry_lists_public_methods_only():
    node = _parse_class(
        "@catalog\n"
        "class Widget:\n"
        "    def __init__(self): pass\n"
        "    def render(self): pass\n"
        "    def resize(self): pass\n"
        "    def _internal(self): pass\n"
    )
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.methods == ["render", "resize"]


def test_class_entry_with_no_init_has_no_parameters():
    node = _parse_class("@catalog\nclass Widget:\n    def render(self): pass\n")
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.parameters == []
    assert entry.methods == ["render"]


def test_class_entry_respects_name_override():
    node = _parse_class("@catalog(name='RenamedWidget')\nclass Widget:\n    pass\n")
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.name == "RenamedWidget"
    assert entry.id == "chat_app.src.services.widgets.RenamedWidget"
