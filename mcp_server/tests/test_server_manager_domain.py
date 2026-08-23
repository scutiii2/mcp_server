"""Tests for the server-manager domain logic.

No real Docker daemon: every test patches `docker.from_env` with a fake
client built from `MagicMock`, exercising the wiring (which container
method gets called, how a missing container or a missing daemon is
reported) rather than Docker itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from docker.errors import DockerException, NotFound

from src.capabilities.server_manager import domain


def _fake_container(name: str, status: str = "running", tags: list[str] | None = None):
    container = MagicMock()
    container.name = name
    container.status = status
    container.image.tags = tags if tags is not None else [f"{name}:latest"]
    container.image.short_id = "sha256:abc123"
    # reload() flips status the way a real container would after start/stop -
    # tests that care about the post-action status set this themselves.
    container.reload.side_effect = lambda: None
    return container


def _fake_client(containers: list):
    def _get(name: str):
        for container in containers:
            if container.name == name:
                return container
        raise NotFound("no such container")

    client = MagicMock()
    client.containers.list.return_value = containers
    client.containers.get.side_effect = _get
    return client


# --- client construction -------------------------------------------------


def test_unreachable_daemon_gives_a_recoverable_message():
    """The caller is a model or a person reading its answer, not someone
    who can inspect the socket themselves - the message has to say what
    to actually do."""
    with patch("docker.from_env", side_effect=DockerException("no such file")):
        with pytest.raises(RuntimeError, match="docker.sock"):
            domain.list_apps()


# --- start / stop / restart ----------------------------------------------


def test_start_app_starts_and_reports_new_status():
    jellyfin = _fake_container("jellyfin", status="exited")

    def _start():
        jellyfin.status = "running"

    jellyfin.start.side_effect = _start
    client = _fake_client([jellyfin])

    with patch("docker.from_env", return_value=client):
        result = domain.start_app("jellyfin")

    jellyfin.start.assert_called_once()
    assert result.action == "start"
    assert result.status == "running"
    assert "jellyfin" in result.message


def test_stop_app_stops_and_reports_new_status():
    jellyfin = _fake_container("jellyfin", status="running")

    def _stop():
        jellyfin.status = "exited"

    jellyfin.stop.side_effect = _stop
    client = _fake_client([jellyfin])

    with patch("docker.from_env", return_value=client):
        result = domain.stop_app("jellyfin")

    jellyfin.stop.assert_called_once()
    assert result.action == "stop"
    assert result.status == "exited"


def test_restart_app_calls_restart_not_stop_then_start():
    jellyfin = _fake_container("jellyfin", status="running")
    client = _fake_client([jellyfin])

    with patch("docker.from_env", return_value=client):
        domain.restart_app("jellyfin")

    jellyfin.restart.assert_called_once()
    jellyfin.stop.assert_not_called()
    jellyfin.start.assert_not_called()


def test_unknown_app_name_lists_the_names_that_exist():
    """The caller is a model that guessed the container name - naming
    the alternatives lets it recover on the next turn, same convention
    as host_health's unknown-host error."""
    client = _fake_client([_fake_container("jellyfin"), _fake_container("plex")])

    with patch("docker.from_env", return_value=client):
        with pytest.raises(KeyError) as error:
            domain.start_app("jelyfin")

    message = str(error.value)
    assert "jellyfin" in message and "plex" in message


def test_no_apps_at_all_says_so_rather_than_an_empty_list():
    client = _fake_client([])

    with patch("docker.from_env", return_value=client):
        with pytest.raises(KeyError, match="No apps found at all"):
            domain.stop_app("anything")


# --- list ------------------------------------------------------------------


def test_list_apps_includes_stopped_containers():
    client = _fake_client([_fake_container("jellyfin", status="running"),
                            _fake_container("plex", status="exited")])

    with patch("docker.from_env", return_value=client):
        result = domain.list_apps()

    client.containers.list.assert_called_once_with(all=True)
    assert {app.name for app in result.apps} == {"jellyfin", "plex"}


def test_list_apps_is_sorted_by_name():
    client = _fake_client([_fake_container("plex"), _fake_container("jellyfin")])

    with patch("docker.from_env", return_value=client):
        result = domain.list_apps()

    assert [app.name for app in result.apps] == ["jellyfin", "plex"]


def test_list_apps_report_is_readable_text():
    client = _fake_client([_fake_container("jellyfin", status="running")])

    with patch("docker.from_env", return_value=client):
        result = domain.list_apps()

    assert "jellyfin" in result.report
    assert "running" in result.report


def test_empty_host_reports_no_apps_rather_than_raising():
    """Unlike the action tools, listing an empty host is a legitimate
    answer, not an error to recover from."""
    client = _fake_client([])

    with patch("docker.from_env", return_value=client):
        result = domain.list_apps()

    assert result.apps == []
    assert "No apps found" in result.report


def test_dangling_image_falls_back_to_the_short_id():
    """A container started from an untagged (dangling) image has no tag
    to show - reporting nothing there would look like a bug, not a fact
    about the image."""
    container = _fake_container("orphan", tags=[])

    client = _fake_client([container])

    with patch("docker.from_env", return_value=client):
        result = domain.list_apps()

    assert result.apps[0].image == "sha256:abc123"
