"""MCP tool wrappers for the server_manager capability - thin on purpose.
No config: call the domain function, return its result."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from src.capabilities.server_manager import domain
from src.capabilities.server_manager.contract import AppActionResult, AppListResult
from src.commands import command
from src.offload import offload
from src.server import mcp

AppName = Annotated[
    str,
    Field(description="The container's name, exactly as Docker shows it - not the app's display title."),
]


@command(name="start", description="Start an app")
@mcp.tool(meta={"keywords": ["server", "app", "container", "docker", "start"], "display_label": "Starting app"})
@offload
def tool_srv_startApp(name: AppName) -> AppActionResult:
    """Start a stopped Docker app hosted on this box. If `name` matches no
    container, the error lists the names that exist; `tool_srv_listApps`
    shows them all up front."""
    return domain.start_app(name)


@command(name="stop", description="Stop an app")
@mcp.tool(meta={"keywords": ["server", "app", "container", "docker", "stop"], "display_label": "Stopping app"})
@offload
def tool_srv_stopApp(name: AppName) -> AppActionResult:
    """Stop a running Docker app hosted on this box. The app stays stopped
    until started again; the container and its data are not removed."""
    return domain.stop_app(name)


@command(name="restart", description="Restart an app")
@mcp.tool(meta={"keywords": ["server", "app", "container", "docker", "restart"], "display_label": "Restarting app"})
@offload
def tool_srv_restartApp(name: AppName) -> AppActionResult:
    """Restart a Docker app hosted on this box - stop, then start. Works
    whether the app is running or already stopped."""
    return domain.restart_app(name)


@command(name="list", description="List apps")
@mcp.tool(meta={"keywords": ["server", "app", "apps", "container", "docker", "list", "status"], "display_label": "Listing apps"})
@offload
def tool_srv_listApps() -> AppListResult:
    """List every Docker app on this box, running or not, with the exact
    `name` to pass to the start/stop/restart tools, its status and image."""
    return domain.list_apps()
