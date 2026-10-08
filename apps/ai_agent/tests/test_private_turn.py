"""turn.py: one turn's private extensions - validated, their tools fetched and
namespaced, and bound for the providers."""

from __future__ import annotations

import asyncio

from mcp import types

from src.private_extensions import turn as private_turn
from src.private_extensions.turn import MAX_TOOLS, PrivateTurn

RAW = [
    {"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}},
    {"id": "wiki", "label": "Wiki", "url": "https://wiki.example.com/mcp"},
]


def tool(name: str, description: str = "does a thing") -> types.Tool:
    return types.Tool(
        name=name, description=description,
        inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
    )


class FakePool:
    def __init__(self, tools=None, fail=()):
        self.tools_by_slug = tools or {}
        self.fail = set(fail)

    async def tools(self, account, spec):
        if spec.slug in self.fail:
            raise ConnectionError(f"down with {spec.header_map.get('X-Key', '')}")
        return self.tools_by_slug.get(spec.slug, [])


async def submit(coro):
    return await coro


def loaded(raw=RAW, pool=None, account="a@x") -> PrivateTurn:
    turn = PrivateTurn.from_raw(raw, account)
    asyncio.run(turn.prefetch(pool or FakePool(), submit))
    return turn


def test_valid_specs_are_kept_and_invalid_ones_become_errors():
    turn = PrivateTurn.from_raw([*RAW, {"id": "Bad Id", "url": "https://x.example.com"}, "junk"], "a@x")

    assert sorted(turn.specs) == ["notes", "wiki"]
    assert len(turn.errors) == 2
    assert all(set(e) == {"id", "label", "error"} for e in turn.errors)
    assert bool(turn) is True


def test_a_duplicate_id_is_refused():
    turn = PrivateTurn.from_raw([RAW[0], {**RAW[0], "url": "https://other.example.com/mcp"}], "a@x")

    assert list(turn.specs) == ["notes"]
    assert len(turn.errors) == 1


def test_nothing_is_kept_without_an_account():
    turn = PrivateTurn.from_raw(RAW, "")

    assert turn.specs == {}
    assert bool(turn) is False
    assert [e["id"] for e in turn.errors] == ["notes", "wiki"]


def test_no_specs_is_an_empty_turn():
    turn = PrivateTurn.from_raw(None, "a@x")

    assert bool(turn) is False
    assert turn.errors == []


def test_tools_are_namespaced_and_routed_back():
    turn = loaded(pool=FakePool({"notes": [tool("search")], "wiki": [tool("find")]}))

    assert sorted(t.name for t in turn.tools()) == ["u_notes__search", "u_wiki__find"]
    spec, upstream = turn.route("u_notes__search")
    assert (spec.slug, upstream) == ("notes", "search")
    assert turn.route("u_notes__other") is None
    assert turn.route("main__ping") is None
    assert turn.errors == []


def test_a_namespaced_tool_keeps_its_schema_and_says_where_it_is_from():
    turn = loaded(pool=FakePool({"notes": [tool("search", "Find notes.")]}))
    only = next(t for t in turn.tools() if t.name == "u_notes__search")

    assert only.inputSchema["properties"]["q"] == {"type": "string"}
    assert only.description.startswith("Find notes.")
    assert "Notes" in only.description


def test_names_that_are_too_long_or_not_allowed_are_left_out_with_a_note():
    long_name = "x" * 60  # u_notes__ + 60 characters is over 64
    turn = loaded(pool=FakePool({"notes": [tool("ok"), tool(long_name), tool("has space"), tool("bad.dot")]}))

    assert [t.name for t in turn.tools()] == ["u_notes__ok"]
    assert len(turn.errors) == 1
    assert turn.errors[0]["id"] == "notes"
    assert "3 tools" in turn.errors[0]["error"]


def test_at_most_max_tools_per_extension():
    many = [tool(f"t{i}") for i in range(MAX_TOOLS + 5)]
    turn = loaded(raw=[RAW[0]], pool=FakePool({"notes": many}))

    assert len(turn.tools()) == MAX_TOOLS
    assert "5 tools" in turn.errors[0]["error"]


def test_a_down_extension_is_an_error_and_the_others_still_load():
    turn = loaded(pool=FakePool({"wiki": [tool("find")]}, fail=["notes"]))

    assert [t.name for t in turn.tools()] == ["u_wiki__find"]
    assert len(turn.errors) == 1
    assert turn.errors[0]["id"] == "notes"
    assert turn.errors[0]["label"] == "Notes"
    assert "s3cret" not in turn.errors[0]["error"]


def test_every_private_name_starts_with_the_prefix():
    turn = loaded(pool=FakePool({"notes": [tool("main__ping")], "wiki": [tool("find")]}))

    assert all(t.name.startswith(private_turn.TOOL_PREFIX) for t in turn.tools())


def test_bind_current_reset():
    assert private_turn.current() is None
    turn = PrivateTurn.from_raw(RAW, "a@x")

    token = private_turn.bind(turn)
    try:
        assert private_turn.current() is turn
    finally:
        private_turn.reset(token)
    assert private_turn.current() is None
