"""Live suggested values for specific tool parameters.

Not a schema constraint - just an `enum` hint added to a tool's already-
declared JSON schema so a client (chat_app's Capabilities form, or an
LLM doing its own tool-calling) sees the actual current options instead
of typing blind. Every parameter in PROVIDERS below means "the valid
values are already known and enumerable server-side", per that tool's
own docstring - a parameter with no entry here (a brand-new name being
registered, say) is deliberately left alone.

Covers only this server's own built-in capabilities' tools - an
extension's tools (proxied via infra/extensions.py) get the same live-
suggestion treatment by applying this same technique to their own
`list_tools()` on their own side; see crafty_mcp_server's suggestions.py
for the worked example, and extensions.py's merged_list_tools() for why
that reaches this server's clients unchanged.

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

from src.capabilities.server_manager import domain as server_manager_domain
from src.config import settings
from src.infra.app_config import load_email_config, load_hosts_config

_SuggestionProvider = Callable[[], list[str]]


def _host_names() -> list[str]:
    return list(load_hosts_config(settings.hosts_config_path).keys())


def _app_names() -> list[str]:
    return [app.name for app in server_manager_domain.list_apps().apps]


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
