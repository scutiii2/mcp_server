from __future__ import annotations

import ast

from src.scanner import _decorator_overrides, _extract_parameters, _function_entry, _is_catalog_decorator


def _parse_function(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    return tree.body[0]


def test_is_catalog_decorator_matches_bare_name():
    node = _parse_function("@catalog\ndef f(): pass")
    assert _is_catalog_decorator(node.decorator_list[0]) is True


def test_is_catalog_decorator_matches_call_form():
    node = _parse_function("@catalog(name='x')\ndef f(): pass")
    assert _is_catalog_decorator(node.decorator_list[0]) is True


def test_is_catalog_decorator_rejects_other_decorators():
    node = _parse_function("@staticmethod\ndef f(): pass")
    assert _is_catalog_decorator(node.decorator_list[0]) is False


def test_decorator_overrides_empty_for_bare_decorator():
    node = _parse_function("@catalog\ndef f(): pass")
    assert _decorator_overrides(node.decorator_list[0]) == {}


def test_decorator_overrides_reads_name_and_description():
    node = _parse_function("@catalog(name='renamed', description='custom')\ndef f(): pass")
    assert _decorator_overrides(node.decorator_list[0]) == {
        "name": "renamed",
        "description": "custom",
    }


def test_extract_parameters_no_default_is_json_null():
    node = _parse_function("def f(x): pass")
    params = _extract_parameters(node.args)
    assert params == [__import__("src.models", fromlist=["Parameter"]).Parameter("x", None, None)]


def test_extract_parameters_literal_none_default_is_the_string_none():
    node = _parse_function("def f(x=None): pass")
    params = _extract_parameters(node.args)
    assert params[0].default == "None"


def test_extract_parameters_captures_annotation_and_default():
    node = _parse_function("def f(x: str = 'hi'): pass")
    params = _extract_parameters(node.args)
    assert params[0].name == "x"
    assert params[0].annotation == "str"
    assert params[0].default == "'hi'"


def test_extract_parameters_skip_first_drops_self():
    node = _parse_function("def f(self, x): pass")
    params = _extract_parameters(node.args, skip_first=True)
    assert [p.name for p in params] == ["x"]


def test_extract_parameters_skip_first_with_defaults_aligns_correctly():
    node = _parse_function("def f(self, x, y=1): pass")
    params = _extract_parameters(node.args, skip_first=True)
    assert [p.name for p in params] == ["x", "y"]
    assert params[0].default is None
    assert params[1].default == "1"


def test_function_entry_uses_docstring_when_no_override():
    node = _parse_function("@catalog\ndef greet(name: str):\n    'Says hello.'\n    pass")
    entry = _function_entry("chat_app", "src.services.foo", "src/services/foo.py", node)

    assert entry.id == "chat_app.src.services.foo.greet"
    assert entry.type == "function"
    assert entry.name == "greet"
    assert entry.description == "Says hello."
    assert entry.project == "chat_app"
    assert entry.file == "src/services/foo.py"
    assert entry.line == 1
    assert [p.name for p in entry.parameters] == ["name"]


def test_function_entry_prefers_explicit_overrides_over_docstring():
    node = _parse_function(
        "@catalog(name='renamed', description='custom')\ndef greet():\n    'ignored'\n    pass"
    )
    entry = _function_entry("chat_app", "src.services.foo", "src/services/foo.py", node)

    assert entry.name == "renamed"
    assert entry.description == "custom"
    assert entry.id == "chat_app.src.services.foo.renamed"
