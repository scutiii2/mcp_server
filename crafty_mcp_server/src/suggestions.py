"""Live suggested values for specific tool parameters.

Not a schema constraint - just an `enum` hint added to a tool's already-
declared JSON schema so a client (chat_app's Chat/Capabilities UI, or an
LLM doing its own tool-calling) sees the actual current options instead
of typing blind. Ported from mcp_server's own infra/tool_suggestions.py,
scoped down to just this project's tools.

This keeps working once crafty is proxied through mcp_server's extension
mechanism rather than imported in-process: mcp_server's own extension
proxy re-fetches ``list_tools()`` from every connected extension on
every call now (see its infra/extensions.py), instead of caching the
list from when it first connected - so whatever this module injects into
this server's own ``list_tools()`` response shows up there too, live.
No bespoke protocol was needed on mcp_server's side for that; it's just
the plain, repeated MCP ``list_tools()`` call every server already has
to support.

Every parameter that IS in PROVIDERS below means "the valid values are
already known and enumerable server-side" - `register_world`'s `name` is
deliberately absent, since a brand-new value there is exactly the point.
Each provider is a plain callable, called fresh on every
``apply_suggestions()`` rather than cached, and wrapped in try/except at
the call site: a missing/locked database file means no suggestions for
that one field, never a broken tool listing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mcp import types

from src import registry

_SuggestionProvider = Callable[[Path], list[str]]


def _world_names(db_path: Path) -> list[str]:
    return [world.name for world in registry.list_all(db_path)]


def _base_urls(db_path: Path) -> list[str]:
    # dict.fromkeys(), not set(): keeps first-seen order instead of an
    # arbitrary one, so the suggestion list looks the same across calls.
    return list(dict.fromkeys(world.base_url for world in registry.list_all(db_path)))


# (tool name, parameter name) -> callable returning that parameter's
# currently-valid values.
PROVIDERS: dict[tuple[str, str], _SuggestionProvider] = {
    ("crafty_world_start", "name"): _world_names,
    ("crafty_world_stop", "name"): _world_names,
    ("crafty_world_restart", "name"): _world_names,
    ("crafty_world_remove", "name"): _world_names,
    ("crafty_world_send_command", "name"): _world_names,
    ("crafty_world_get_status", "name"): _world_names,
    ("crafty_world_register", "base_url"): _base_urls,
    ("crafty_ping_base_url", "base_url"): _base_urls,
    ("crafty_set_default_base_url", "base_url"): _base_urls,
}


def apply_suggestions(tools: list[types.Tool], db_path: Path) -> None:
    """Inject an `enum` into each tool's inputSchema, in place, for every
    parameter PROVIDERS has an entry for.

    A provider raising - a missing/locked database file, whatever - only
    drops suggestions for that one field. It must never be the reason a
    client can't see the tool at all.
    """
    for tool in tools:
        properties = (tool.inputSchema or {}).get("properties")
        if not properties:
            continue
        for param_name, field_schema in properties.items():
            provider = PROVIDERS.get((tool.name, param_name))
            if provider is None:
                continue
            try:
                values = provider(db_path)
            except Exception:  # noqa: BLE001 - see docstring: never break the listing
                continue
            if values:
                field_schema["enum"] = values
