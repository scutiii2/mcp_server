"""Tests for infra/capability_registry.py.

Uses a real FastMCP instance throughout, not a mock - the whole point of
this module is manipulating that instance's actual tool/resource dicts,
so a mock would prove nothing about whether the manipulation is correct.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from src.infra import capability_registry as registry


@pytest.fixture(autouse=True)
def clean_registry():
    """Each test gets its own empty registry - module-level state, same
    reasoning as infra/approvals.py's _REGISTRY tests."""
    registry._REGISTRY.clear()
    yield
    registry._REGISTRY.clear()


@pytest.fixture
def mcp():
    return FastMCP(name="test-server")


def test_capturing_registers_a_tool_defined_inside_the_block(mcp):
    with registry.capturing(mcp, "widgets"):
        @mcp.tool()
        def make_widget(size: int) -> str:
            return f"widget of size {size}"

    assert "make_widget" in {t.name for t in mcp._tool_manager.list_tools()}
    assert registry.names() == ["widgets"]
    assert registry.is_enabled("widgets") is True


def test_capturing_only_attributes_tools_defined_inside_its_own_block(mcp):
    with registry.capturing(mcp, "widgets"):
        @mcp.tool()
        def make_widget() -> str:
            return "widget"

    with registry.capturing(mcp, "gadgets"):
        @mcp.tool()
        def make_gadget() -> str:
            return "gadget"

    assert {t.name for t in registry._REGISTRY["widgets"].tools} == {"make_widget"}
    assert {t.name for t in registry._REGISTRY["gadgets"].tools} == {"make_gadget"}


def test_capturing_a_resource_template(mcp):
    with registry.capturing(mcp, "widgets"):
        @mcp.resource("widget://catalog/{id}")
        def get_widget(id: str) -> str:
            return f"widget {id}"

    assert "widget://catalog/{id}" in mcp._resource_manager._templates
    assert registry._REGISTRY["widgets"].resource_templates[0].uri_template == "widget://catalog/{id}"


def test_capturing_the_same_name_twice_raises(mcp):
    with registry.capturing(mcp, "widgets"):
        pass

    with pytest.raises(ValueError, match="widgets"):
        with registry.capturing(mcp, "widgets"):
            pass


def test_disabling_removes_the_tool_from_the_live_server(mcp):
    with registry.capturing(mcp, "widgets"):
        @mcp.tool()
        def make_widget() -> str:
            return "widget"

    registry.set_enabled(mcp, "widgets", False)

    assert "make_widget" not in {t.name for t in mcp._tool_manager.list_tools()}
    assert registry.is_enabled("widgets") is False


def test_disabling_removes_the_resource_template_from_the_live_server(mcp):
    with registry.capturing(mcp, "widgets"):
        @mcp.resource("widget://catalog/{id}")
        def get_widget(id: str) -> str:
            return f"widget {id}"

    registry.set_enabled(mcp, "widgets", False)

    assert "widget://catalog/{id}" not in mcp._resource_manager._templates


def test_re_enabling_restores_the_tool_with_its_original_metadata(mcp):
    """The re-added Tool is the exact object captured at import time, not
    a rebuild from the bare function - so meta/description survive a
    disable/enable round trip without the toggle route needing to know
    what they were."""
    with registry.capturing(mcp, "widgets"):
        @mcp.tool(meta={"keywords": ["widget", "make"]})
        def make_widget() -> str:
            return "widget"

    registry.set_enabled(mcp, "widgets", False)
    registry.set_enabled(mcp, "widgets", True)

    restored = mcp._tool_manager.get_tool("make_widget")
    assert restored is not None
    assert restored.meta == {"keywords": ["widget", "make"]}


def test_re_enabling_restores_the_resource_template(mcp):
    with registry.capturing(mcp, "widgets"):
        @mcp.resource("widget://catalog/{id}")
        def get_widget(id: str) -> str:
            return f"widget {id}"

    registry.set_enabled(mcp, "widgets", False)
    registry.set_enabled(mcp, "widgets", True)

    assert "widget://catalog/{id}" in mcp._resource_manager._templates


def test_setting_the_same_state_twice_is_a_no_op(mcp):
    """Enabling an already-enabled capability (or disabling an
    already-disabled one) must not raise or double-remove/double-add -
    the toggle route calls this on every request regardless of prior
    state."""
    with registry.capturing(mcp, "widgets"):
        @mcp.tool()
        def make_widget() -> str:
            return "widget"

    registry.set_enabled(mcp, "widgets", True)  # already enabled
    assert "make_widget" in {t.name for t in mcp._tool_manager.list_tools()}

    registry.set_enabled(mcp, "widgets", False)
    registry.set_enabled(mcp, "widgets", False)  # already disabled
    assert "make_widget" not in {t.name for t in mcp._tool_manager.list_tools()}


def test_a_capability_with_no_tools_or_resources_is_still_registered(mcp):
    """A capability whose import block registers nothing (shouldn't
    happen in practice, but the registry must not choke on it) is still
    a known, toggleable (trivially) name."""
    with registry.capturing(mcp, "empty"):
        pass

    assert registry.names() == ["empty"]
    assert registry.is_enabled("empty") is True
    registry.set_enabled(mcp, "empty", False)  # must not raise
    assert registry.is_enabled("empty") is False


def test_names_lists_every_captured_capability_sorted(mcp):
    with registry.capturing(mcp, "otp"):
        pass
    with registry.capturing(mcp, "host_health"):
        pass

    assert registry.names() == ["host_health", "otp"]


def test_is_enabled_on_an_unknown_name_names_the_ones_that_exist(mcp):
    with registry.capturing(mcp, "widgets"):
        pass

    with pytest.raises(KeyError, match="widgets"):
        registry.is_enabled("gadgets")


def test_set_enabled_on_an_unknown_name_names_the_ones_that_exist(mcp):
    with registry.capturing(mcp, "widgets"):
        pass

    with pytest.raises(KeyError, match="widgets"):
        registry.set_enabled(mcp, "gadgets", False)
