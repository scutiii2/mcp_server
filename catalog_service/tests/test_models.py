from __future__ import annotations

from src.models import CatalogEntry, Parameter


def test_function_entry_to_dict_has_no_methods_key():
    entry = CatalogEntry(
        id="chat_app.src.services.foo.bar",
        type="function",
        name="bar",
        description="Does a thing.",
        project="chat_app",
        file="src/services/foo.py",
        line=42,
        parameters=[Parameter(name="x", annotation="str", default=None)],
    )

    data = entry.to_dict()

    assert data == {
        "id": "chat_app.src.services.foo.bar",
        "type": "function",
        "name": "bar",
        "description": "Does a thing.",
        "project": "chat_app",
        "file": "src/services/foo.py",
        "line": 42,
        "parameters": [{"name": "x", "annotation": "str", "default": None}],
    }
    assert "methods" not in data


def test_class_entry_to_dict_includes_methods_key():
    entry = CatalogEntry(
        id="mcp_server.src.services.foo.Bar",
        type="class",
        name="Bar",
        description="A reusable base.",
        project="mcp_server",
        file="src/services/foo.py",
        line=10,
        parameters=[],
        methods=["method_a", "method_b"],
    )

    data = entry.to_dict()

    assert data["methods"] == ["method_a", "method_b"]
