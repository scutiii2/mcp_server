"""Start, stop, restart, and list the Docker containers on this host.

Unlike `host_health`/`otp`, this doesn't go through `infra/ssh.py` or
`infra/app_config.py` - there's nothing to dial out to. The intended
deployment (see `../../../zima_host.yaml`) runs this server itself as a
container on the same ZimaOS box as the apps it manages, with the host's
Docker socket bind-mounted in, so `docker.from_env()` talks to the same
Docker daemon every other app on that box is already running under.

The client is built fresh on every call rather than cached at import
time or held as a module-level singleton. Two reasons: `run.py` imports
every capability unconditionally now (even a disabled one, so it can be
re-enabled live - see `capabilities/README.md`), so building the client
at import time would crash the *entire* server's startup the moment the
socket isn't mounted yet, instead of failing only the one tool call that
needed it. And unlike an SSH connection there's no per-call round-trip
cost being saved by holding one open - `docker.from_env()` just reads
`DOCKER_HOST`/inspects the socket path, it doesn't itself talk to the
daemon until the first real call does.
"""

from __future__ import annotations

import docker
from docker.errors import DockerException, NotFound

from src.capabilities.server_manager.contract import AppActionResult, AppInfo, AppListResult


def _client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except DockerException as error:
        raise RuntimeError(
            "Could not reach Docker from this process. If this server is running "
            "in its own container (see zima_host.yaml), make sure the host's "
            "Docker socket is bind-mounted in: add "
            "'/var/run/docker.sock:/var/run/docker.sock' to that service's "
            f"volumes. ({error})"
        ) from error


def _known_app_names(client: docker.DockerClient) -> list[str]:
    return sorted(container.name for container in client.containers.list(all=True))


def _image_label(container) -> str:
    """The image's own tag if it has one, else its short id - a container
    started from a now-untagged (dangling) image otherwise has no name at
    all to show, which reads as a bug rather than a fact about the image."""
    tags = container.image.tags
    return tags[0] if tags else container.image.short_id


def _get_container(client: docker.DockerClient, name: str):
    try:
        return client.containers.get(name)
    except NotFound as error:
        known = _known_app_names(client)
        raise KeyError(
            f"No app named {name!r} exists on this host. "
            f"{'Apps available: ' + ', '.join(known) + '.' if known else 'No apps found at all.'}"
        ) from error


def _act(name: str, action: str, verb: str) -> AppActionResult:
    client = _client()
    container = _get_container(client, name)
    getattr(container, action)()
    container.reload()
    return AppActionResult(
        name=name,
        action=action,
        status=container.status,
        message=f"{name} {verb} - it is now {container.status}.",
    )


def start_app(name: str) -> AppActionResult:
    return _act(name, "start", "started")


def stop_app(name: str) -> AppActionResult:
    return _act(name, "stop", "stopped")


def restart_app(name: str) -> AppActionResult:
    return _act(name, "restart", "restarted")


def list_apps() -> AppListResult:
    client = _client()
    containers = sorted(client.containers.list(all=True), key=lambda container: container.name)
    apps = [
        AppInfo(name=container.name, status=container.status, image=_image_label(container))
        for container in containers
    ]

    if not apps:
        report = "No apps found on this host."
    else:
        width = max(len(app.name) for app in apps)
        report = "\n".join(f"{app.name:<{width}}  {app.status:<10} {app.image}" for app in apps)

    return AppListResult(apps=apps, report=report)
