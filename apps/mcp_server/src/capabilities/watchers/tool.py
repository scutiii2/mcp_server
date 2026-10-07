"""MCP tool wrappers for the watch capability - thin on purpose.
Read the caller's identity and the state folder, call the domain function."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from src.capabilities.watchers import domain
from src.capabilities.watchers.contract import CancelResult, CreateResult, WatcherListResult
from src.commands import command
from src.config import settings
from src.offload import offload
from src.server import mcp
from src.services import identity_context


@command(name="create", description="Watch a URL, app or port and email me when it is up")
@mcp.tool(meta={"keywords": ["watch", "watcher", "notify", "alert", "tell me when", "wait for", "uptime", "back up", "monitor", "schedule", "port", "app started", "email me"], "display_label": "Creating a watcher"})
@offload
def tool_watch_create(
    kind: Annotated[str, Field(description="What to check: url (a web address), app (a managed app or container name) or tcp (host:port).")],
    target: Annotated[str, Field(description="The web address, the app name, or host:port, depending on kind.")],
    expect: Annotated[str, Field(description="up (default) to be told when it is up or running or open, or down to be told when it is down.")] = "up",
    contains: Annotated[str, Field(description="Optional, only with kind url and expect up: text the page must contain.")] = "",
    label: Annotated[str, Field(description="Optional short name shown in lists and in the email.")] = "",
) -> CreateResult:
    """Start a background watcher that checks a URL, a managed app or a TCP
    port, first every 30 seconds then every 5 minutes for up to 24 hours, and
    emails the requesting user once when the condition is met (or when it
    gives up). It watches once; it does not monitor continuously. Never
    invent a target: ask the user for it. The email always goes to the
    user's own address."""
    return domain.create_watcher(
        settings.watchers_dir,
        identity_context.current_username(),
        identity_context.current_email(),
        kind, target, expect, contains, label,
    )


@command(name="list", description="List my watchers")
@mcp.tool(meta={"keywords": ["watch", "watcher", "watchers", "list", "status", "waiting", "running", "monitor"], "display_label": "Listing watchers"})
@offload
def tool_watch_listWatchers() -> WatcherListResult:
    """List the requesting user's own watchers, newest first, with their state,
    what they watch, the last check, the email outcome and recipients.
    Read-only."""
    return domain.list_watchers(settings.watchers_dir, identity_context.current_username())


@command(name="cancel", description="Cancel one of my watchers")
@mcp.tool(meta={"keywords": ["watch", "watcher", "cancel", "stop", "remove", "delete"], "display_label": "Cancelling a watcher"})
@offload
def tool_watch_cancel(
    key: Annotated[str, Field(description="The watcher's id, such as w-1a2b3c4d, from the create or list result.")],
) -> CancelResult:
    """Cancel one of the requesting user's own watchers (running or finished) by
    its key. Any other key answers 'No such watcher.'"""
    return domain.cancel_watcher(settings.watchers_dir, identity_context.current_username(), key)
