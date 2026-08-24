"""The @mcp.tool() wrappers - thin on purpose.

Load nothing (there's no config file for this one - see `domain.py`'s
docstring for why), call the domain function, return its result.

Not gated behind `infra/approvals.py`. Starting, stopping and restarting
a container are all reversible - the same button reverses them - and on
a single-operator homelab deployment the extra ceremony of an emailed
approval buys little. Revisit that if this server is ever reachable by
more than one person.
"""

from __future__ import annotations

from src.capabilities.server_manager import domain
from src.capabilities.server_manager.contract import AppActionResult, AppListResult
from src.commands import command
from src.server import mcp
from src.tool_response import respond


@command(name="start", description="Start an app")
@mcp.tool(meta={"keywords": ["server", "manager", "docker", "app", "start"]})
def start_app_tool(name: str) -> AppActionResult:
    """Start a stopped Docker app hosted on this box.

    `name` is the container's name, exactly as Docker/ZimaOS shows it -
    not the app's display title, which can differ. If it doesn't match
    any container, the error lists the names that do exist; `list_apps_tool`
    shows them all up front.
    """
    return respond(domain.start_app(name))


@command(name="stop", description="Stop an app")
@mcp.tool(meta={"keywords": ["server", "manager", "docker", "app", "stop"]})
def stop_app_tool(name: str) -> AppActionResult:
    """Stop a running Docker app hosted on this box.

    `name` is the container's name, exactly as Docker/ZimaOS shows it.
    The app stays stopped until something starts it again - this does
    not remove the container or its data.
    """
    return respond(domain.stop_app(name))


@command(name="restart", description="Restart an app")
@mcp.tool(meta={"keywords": ["server", "manager", "docker", "app", "restart"]})
def restart_app_tool(name: str) -> AppActionResult:
    """Restart a Docker app hosted on this box - stop, then start again.

    `name` is the container's name, exactly as Docker/ZimaOS shows it.
    Works whether the app is currently running or already stopped.
    """
    return respond(domain.restart_app(name))


@command(name="list", description="List apps")
@mcp.tool(meta={"keywords": ["server", "manager", "docker", "app", "list"]})
def list_apps_tool() -> AppListResult:
    """List every Docker app on this box, running or not.

    Each entry gives the exact `name` to pass to `start_app_tool`,
    `stop_app_tool` or `restart_app_tool`, its current status, and the
    image it runs.
    """
    return respond(domain.list_apps())
