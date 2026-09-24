"""Human-friendly display titles for MCP tools.

MCP tool names are snake_case identifiers meant for machines
(``restart_service_tool``) - not something you'd want as a page heading.

This lives on the Flask side, not the MCP server side, deliberately: newer
versions of the MCP spec/FastMCP may support a ``title`` field directly on
``@mcp.tool()``, but that's an assumption about an installed package
version this scaffold can't verify without the real package available.
This approach works regardless of what your installed ``mcp`` version
supports, and needs no changes to ``mcp_server`` at all.
"""

from __future__ import annotations

import re

from src.utils.catalog import catalog

# Explicit overrides for tools whose auto-generated title wouldn't read
# well. The fallback below splits on "_" and on camelCase boundaries, then
# title-cases each word - so that's the usual reason to add an entry here:
#
#     "get_cpu_usage_tool": "Get CPU Usage",
#
# Empty until there are tools to title; every name falls through to the
# automatic version below, which is correct for most ordinary names.
_OVERRIDES: dict[str, str] = {}

# Splits camelCase/PascalCase words apart WITHOUT breaking up a run of
# capitals ("srvAPI" -> "srv API", not "srv A P I") - needed because tool
# names mix snake_case with camelCase segments (e.g. "tool_srv_startApp").
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# mcp_server's capability tools all follow "tool_{capabilityPrefix}_{camelAction}"
# (see mcp_server/src/capabilities/*/tool.py, e.g. "tool_srv_listApps").
# The prefix is just the capability tag, not part of the action - drop both it
# and the leading "tool" so the title is only the action, camel-split.
_CAPABILITY_TOOL_RE = re.compile(r"^tool_[A-Za-z0-9]+_(.+)$")


def _split_camel(word: str) -> list[str]:
    return _CAMEL_BOUNDARY_RE.sub(" ", word).split()


@catalog
def title_for(tool_name: str) -> str:
    if tool_name in _OVERRIDES:
        return _OVERRIDES[tool_name]
    name = tool_name[:-5] if tool_name.endswith("_tool") else tool_name
    match = _CAPABILITY_TOOL_RE.match(name)
    if match:
        name = match.group(1)
    words = [word for part in name.split("_") for word in _split_camel(part)]
    title = " ".join(word.upper() if word.isupper() else word.capitalize() for word in words)
    return title.strip() or tool_name
