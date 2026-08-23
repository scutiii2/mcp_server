"""Live enable/disable for built-in capabilities.

FastMCP's own surface only gets a capability halfway to toggleable:
``mcp.add_tool()``/``mcp.remove_tool()`` are public, but there is no
public way to remove a resource *template* (only ``add_template()`` on
``ResourceManager``, confirmed against the installed mcp==1.28.0
source - ``ResourceManager`` has no ``remove_resource``/
``remove_template`` at all). So this module reaches into
``mcp._tool_manager``/``mcp._resource_manager``'s private dicts for the
other half, the same kind of justified reach ``infra/extensions.py``
already documents for ``mcp._mcp_server`` - there is no other way to do
this with the SDK as installed.

``run.py`` wraps each capability's import block in ``capturing(mcp,
name)``, which diffs what got newly registered onto ``mcp`` before and
after the block and stores those exact ``Tool``/``ResourceTemplate``
objects - not just the bare functions. That matters: re-enabling a
capability later puts back the precise object captured at import time,
metadata (``meta``, ``description``, annotations) and all, rather than
rebuilding one from scratch and needing to remember what the original
``@mcp.tool(meta=...)`` call passed.

Auto-discovering what a capability registered (rather than a
hand-maintained list of its tool/resource names) means a capability
that gains a second tool later is toggle-ready with no change here.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources.templates import ResourceTemplate
from mcp.server.fastmcp.tools.base import Tool


@dataclass
class _CapabilityHandle:
    tools: list[Tool] = field(default_factory=list)
    resource_templates: list[ResourceTemplate] = field(default_factory=list)
    # True at capture time by construction: capturing() runs while the
    # tools/templates it just diffed are actually live on `mcp`.
    enabled: bool = True


_REGISTRY: dict[str, _CapabilityHandle] = {}


@contextmanager
def capturing(mcp: FastMCP, name: str) -> Iterator[None]:
    """Wrap a capability's import block; records whatever it registered.

    Diffs ``mcp``'s tool/resource-template dicts before and after the
    block runs, so anything the block's ``@mcp.tool()``/
    ``@mcp.resource()`` decorators added is attributed to ``name`` -
    without needing to know its tool/resource names in advance.
    """
    if name in _REGISTRY:
        raise ValueError(f"Capability {name!r} is already registered")

    tools_before = set(mcp._tool_manager._tools)
    templates_before = set(mcp._resource_manager._templates)
    yield
    _REGISTRY[name] = _CapabilityHandle(
        tools=[tool for tname, tool in mcp._tool_manager._tools.items() if tname not in tools_before],
        resource_templates=[
            template
            for uri, template in mcp._resource_manager._templates.items()
            if uri not in templates_before
        ],
    )


def _handle(name: str) -> _CapabilityHandle:
    if name not in _REGISTRY:
        known = ", ".join(names()) or "none configured"
        raise KeyError(f"Unknown capability {name!r}. Registered: {known}.")
    return _REGISTRY[name]


def names() -> list[str]:
    return sorted(_REGISTRY)


def is_enabled(name: str) -> bool:
    return _handle(name).enabled


def set_enabled(mcp: FastMCP, name: str, enabled: bool) -> None:
    """Add or remove `name`'s tools/resource templates on the live
    `mcp` instance. A no-op if `enabled` already matches the current
    state - the toggle route calls this on every request regardless of
    what it was before, and re-adding an already-live tool would hit
    FastMCP's duplicate-tool warning for no reason."""
    handle = _handle(name)
    if enabled == handle.enabled:
        return

    if enabled:
        for tool in handle.tools:
            mcp._tool_manager._tools[tool.name] = tool
        for template in handle.resource_templates:
            mcp._resource_manager._templates[template.uri_template] = template
    else:
        for tool in handle.tools:
            mcp.remove_tool(tool.name)
        for template in handle.resource_templates:
            mcp._resource_manager._templates.pop(template.uri_template, None)

    handle.enabled = enabled
