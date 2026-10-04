"""Headers for this app's MCP sessions to mcp_server and ai_agent.

Both require the shared INTERNAL_API_TOKEN (secrets/secret_internal_api.env,
the same value everywhere) on /mcp once they have one configured, so every
streamablehttp_client this app opens goes through mcp_headers(). run.py's
create_app() copies the token into os.environ, the same way it does for
secret_llm.env / secret_mcp.env, so this module needs no Flask context.
"""

from __future__ import annotations

import os

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


def mcp_headers(extra: dict[str, str] | None = None) -> dict[str, str] | None:
    """`extra` (e.g. identity headers) plus the internal token if one is
    configured; None when there's nothing to send, which keeps the
    transport call's original shape."""
    headers = dict(extra or {})
    token = os.getenv("INTERNAL_API_TOKEN")
    if token:
        headers[INTERNAL_TOKEN_HEADER] = token
    return headers or None
