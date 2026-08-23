"""The @mcp.tool() wrapper - thin on purpose.

Pairs with ``resources/host_health/``, which exposes the same data as
``host://health/{name}``. Both exist because they reach different callers:
a client reading a URI gets the resource, and a model deciding to check a
machine gets this. Only tools are offered to the model - chat_app's
providers build their schemas from ``list_tools()`` and never look at
resources - so without this wrapper, asking an assistant "how is zima
doing?" has nothing to call.

Not gated behind ``infra/approvals.py``: this only reads.
"""

from __future__ import annotations

from src.capabilities.host_health import domain
from src.capabilities.host_health.contract import HostHealthResult
from src.config import settings
from src.server import mcp


@mcp.tool(meta={"keywords": ["host", "health", "cpu", "memory", "disk", "uptime", "status"]})
def get_host_health_tool(name: str) -> HostHealthResult:
    """Check CPU, memory, disk and uptime on one of this server's configured machines.

    `name` is the key under "hosts" in the server's configuration - a
    short label like "zima", not a hostname or an IP. If you get it
    wrong, the error lists the names that exist.

    Works for Linux and Windows hosts; some figures are only available on
    one of them (load average on Linux, CPU percentage on Windows), and
    the other is left empty rather than guessed.
    """
    return domain.check(settings.hosts_config_path, name)
