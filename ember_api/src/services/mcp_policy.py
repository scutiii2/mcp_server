"""What a browser may send through the MCP proxy.

Each proxied POST body is JSON-RPC (one message or a batch). A policy allows
the MCP handshake/housekeeping for everyone who passed the route's
permission check, plus a fixed set of tool calls - and for some tools, only
certain arguments. Anything else is refused before it reaches the server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Handshake and housekeeping every MCP client sends; none of them act on data.
_SESSION_METHODS = frozenset(
    {
        "initialize",
        "ping",
        "notifications/initialized",
        "notifications/cancelled",
        "notifications/roots/list_changed",
    }
)


class PolicyViolation(ValueError):
    """The message is not allowed; str() is safe to return to the client."""


@dataclass(frozen=True)
class McpPolicy:
    # Methods allowed beyond the session ones (e.g. tools/list).
    extra_methods: frozenset[str] = frozenset()
    # tools/call: None = every tool; else tool name -> allowed argument names
    # (None there = any arguments).
    tools: dict[str, frozenset[str] | None] | None = field(default_factory=dict)

    def check(self, payload: Any) -> None:
        """Raises PolicyViolation unless every message in `payload` is allowed."""
        messages = payload if isinstance(payload, list) else [payload]
        if not messages:
            raise PolicyViolation("Empty batch")
        for message in messages:
            self._check_message(message)

    def _check_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            raise PolicyViolation("Not a JSON-RPC message")
        method = message.get("method")
        if method is None:
            # A response to a server-initiated request (e.g. ping): carries
            # result/error, never a new action.
            if "result" in message or "error" in message:
                return
            raise PolicyViolation("Not a JSON-RPC message")
        if method in _SESSION_METHODS or method in self.extra_methods:
            return
        if method == "tools/call":
            self._check_tool_call(message.get("params"))
            return
        raise PolicyViolation(f"Method not allowed: {method}")

    def _check_tool_call(self, params: Any) -> None:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise PolicyViolation("tools/call needs a tool name")
        name = params["name"]
        if self.tools is None:
            return
        if name not in self.tools:
            raise PolicyViolation(f"Tool not allowed: {name}")
        allowed_args = self.tools[name]
        if allowed_args is None:
            return
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise PolicyViolation("Tool arguments must be an object")
        extra = sorted(set(arguments) - allowed_args)
        if extra:
            raise PolicyViolation(f"Arguments not allowed for {name}: {', '.join(extra)}")


# ai_agent: chat only. `depth` is deliberately not allowed on ask - it's set
# by a delegating agent, and a browser setting it could skew delegation.
AGENT_POLICY = McpPolicy(
    tools={
        "ask": frozenset({"question", "history", "request_id", "enabled_extensions", "caveman"}),
        "cancel": frozenset({"request_id"}),
        "status": frozenset(),
    },
)

# mcp_server: list and call any tool it exposes (tools.use covers that).
SERVER_POLICY = McpPolicy(extra_methods=frozenset({"tools/list"}), tools=None)
