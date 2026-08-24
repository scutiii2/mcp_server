"""Live suggested values for specific tool parameters.

Not a schema constraint - just an `enum` hint added to a tool's already-
declared JSON schema so a client (chat_app's Capabilities form, or an
LLM doing its own tool-calling) sees the actual current options instead
of typing blind. Deliberately advisory: crafty_world_register's `name`
is a real example of a parameter this module has no entry for, because
a brand-new value there is exactly the point. Every parameter that IS
in PROVIDERS below means "the valid values are already known and
enumerable server-side", per that tool's own docstring.

Each provider is a plain sync callable, called fresh on every
apply_suggestions() rather than cached - the whole point is reflecting
live state (worlds registered, containers running, hosts configured) -
and wrapped in try/except at the call site: a missing config file or an
unmounted Docker socket means no suggestions for that one field, never
a broken tool listing.
"""

from __future__ import annotations

from collections.abc import Callable

from mcp import types

from src.capabilities.crafty import domain as crafty_domain
from src.capabilities.server_manager import domain as server_manager_domain
from src.config import settings
from src.infra.app_config import load_email_config, load_hosts_config

_SuggestionProvider = Callable[[], list[str]]


def _host_names() -> list[str]:
    return list(load_hosts_config(settings.hosts_config_path).keys())


def _app_names() -> list[str]:
    return [app.name for app in server_manager_domain.list_apps().apps]


def _crafty_world_names() -> list[str]:
    worlds = crafty_domain.list_worlds(settings.crafty_worlds_db_path).worlds
    return [world.name for world in worlds]


def _crafty_base_urls() -> list[str]:
    worlds = crafty_domain.list_worlds(settings.crafty_worlds_db_path).worlds
    # dict.fromkeys(), not set(): keeps first-seen order instead of an
    # arbitrary one, so the suggestion list looks the same across calls.
    return list(dict.fromkeys(world.base_url for world in worlds))


def _otp_recipients() -> list[str]:
    return list(load_email_config(settings.email_config_path).approver_emails)


# (tool name, parameter name) -> callable returning that parameter's
# currently-valid values. Only parameters whose valid values are already
# known and enumerable server-side belong here - see this module's
# docstring.
PROVIDERS: dict[tuple[str, str], _SuggestionProvider] = {
    ("get_host_health_tool", "name"): _host_names,
    ("start_app_tool", "name"): _app_names,
    ("stop_app_tool", "name"): _app_names,
    ("restart_app_tool", "name"): _app_names,
    ("crafty_world_start", "name"): _crafty_world_names,
    ("crafty_world_stop", "name"): _crafty_world_names,
    ("crafty_world_restart", "name"): _crafty_world_names,
    ("crafty_world_remove", "name"): _crafty_world_names,
    ("crafty_world_send_command", "name"): _crafty_world_names,
    ("crafty_world_get_status", "name"): _crafty_world_names,
    ("crafty_world_register", "base_url"): _crafty_base_urls,
    ("crafty_ping_base_url", "base_url"): _crafty_base_urls,
    ("crafty_set_default_base_url", "base_url"): _crafty_base_urls,
    ("request_otp_tool", "recipient"): _otp_recipients,
}


def apply_suggestions(tools: list[types.Tool]) -> None:
    """Inject an `enum` into each tool's inputSchema, in place, for every
    parameter PROVIDERS has an entry for. Called once per list_tools()
    response - see infra/extensions.py's merged_list_tools().

    A provider raising - a missing config file, an unmounted Docker
    socket, whatever - only drops suggestions for that one field. It
    must never be the reason a client can't see the tool at all.
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
                values = provider()
            except Exception:  # noqa: BLE001 - see docstring: never break the listing
                continue
            if values:
                field_schema["enum"] = values
