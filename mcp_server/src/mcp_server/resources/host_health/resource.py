"""The @mcp.resource() wrapper - thin on purpose.

Load config, call the domain function, return text. Everything worth
testing lives in domain.py, which knows nothing about MCP.

A resource rather than a tool because this only reads: there are no
arguments to reason about beyond which host, and a client can fetch
``host://health/desktop`` directly without a tool-call round trip.
"""

from __future__ import annotations

from mcp_server.config import settings
from mcp_server.infra.app_config import load_host_config
from mcp_server.resources.host_health.domain import collect, format_report
from mcp_server.server import mcp


@mcp.resource("host://health/{name}")
def host_health(name: str) -> str:
    """Current CPU, memory, disk and uptime for a configured host.

    `name` is the key under "hosts" in config.json, not a hostname.
    """
    config = load_host_config(settings.config_path, name)
    return format_report(collect(config))
