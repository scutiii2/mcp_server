"""Tests for the server-manager domain logic.

No real Docker daemon: every test patches `docker.from_env` with a fake
client built from `MagicMock`, exercising the wiring (which container
method gets called, how a missing container or a missing daemon is
reported) rather than Docker itself.
"""

from __future__ import annotations

from types import SimpleNamespace
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

    assert "jellyfin" in result.message
    assert "running" in result.message


def test_empty_host_reports_no_apps_rather_than_raising():
    """Unlike the action tools, listing an empty host is a legitimate
    answer, not an error to recover from."""
    client = _fake_client([])

    with patch("docker.from_env", return_value=client):
        result = domain.list_apps()

    assert result.apps == []
    assert "No apps found" in result.message


def test_dangling_image_falls_back_to_the_short_id():
    """A container started from an untagged (dangling) image has no tag
    to show - reporting nothing there would look like a bug, not a fact
    about the image."""
    container = _fake_container("orphan", tags=[])

    client = _fake_client([container])

    with patch("docker.from_env", return_value=client):
        result = domain.list_apps()

    assert result.apps[0].image == "sha256:abc123"


# --- app logs ------------------------------------------------------------


from src.services import downloads, identity_context  # noqa: E402


@pytest.fixture
def requester(monkeypatch):
    """Who is asking, and a fresh store for the file offered to them."""
    fresh = downloads.DownloadRegistry()
    monkeypatch.setattr(downloads, "registry", fresh)
    who = {"name": "alice"}
    monkeypatch.setattr(identity_context, "current_username", lambda: who["name"])
    return SimpleNamespace(store=fresh, who=who)


def _logging_container(name: str, output: bytes):
    container = _fake_container(name)
    container.logs.return_value = output
    return container


def test_the_log_is_offered_as_a_download_to_the_asker(requester):
    web = _logging_container("web", b"2026-01-01T00:00:00Z started\n2026-01-01T00:00:01Z ready\n")

    with patch("docker.from_env", return_value=_fake_client([web])):
        result = domain.get_app_logs("web", 200)

    web.logs.assert_called_once_with(tail=200, timestamps=True)
    assert result.lines == 2
    (marker,) = result.download_markers
    assert 'filename="web-logs.log"' in marker and 'label="LOGS"' in marker
    download_id = marker.split("path=")[1].split('"')[0]
    got = requester.store.get(download_id, "alice")
    assert got is not None and got.data.startswith(b"2026-01-01T00:00:00Z started")
    assert requester.store.get(download_id, "bob") is None
    assert "2 lines" in result.message and "10 minutes" in result.message


def test_the_default_is_five_hundred_lines(requester):
    web = _logging_container("web", b"x\n")

    with patch("docker.from_env", return_value=_fake_client([web])):
        domain.get_app_logs("web")

    assert web.logs.call_args.kwargs["tail"] == 500


@pytest.mark.parametrize("lines", [0, -1, 5001])
def test_the_line_count_is_bounded(requester, lines):
    with pytest.raises(ValueError, match="between 1 and 5000"):
        domain.get_app_logs("web", lines)


def test_the_largest_line_count_is_allowed(requester):
    web = _logging_container("web", b"x\n")

    with patch("docker.from_env", return_value=_fake_client([web])):
        domain.get_app_logs("web", 5000)

    assert web.logs.call_args.kwargs["tail"] == 5000


def test_an_empty_log_offers_no_file(requester):
    web = _logging_container("web", b"")

    with patch("docker.from_env", return_value=_fake_client([web])):
        result = domain.get_app_logs("web")

    assert result.download_markers == [] and result.lines == 0
    assert "no log output" in result.message
    assert len(requester.store) == 0


def test_nobody_identified_means_no_file(requester):
    requester.who["name"] = ""
    web = _logging_container("web", b"line\n")

    with patch("docker.from_env", return_value=_fake_client([web])):
        result = domain.get_app_logs("web")

    assert result.download_markers == []
    assert "not identified" in result.message
    assert len(requester.store) == 0


def test_an_unknown_app_lists_the_names_that_exist(requester):
    with patch("docker.from_env", return_value=_fake_client([_logging_container("web", b"x")])):
        with pytest.raises(KeyError, match="web"):
            domain.get_app_logs("nope")


def test_a_log_over_the_limit_is_cut_to_its_newest_whole_lines(requester, monkeypatch):
    monkeypatch.setattr(downloads, "MAX_FILE_BYTES", 20)
    web = _logging_container("web", b"aaaaaaaaaa\nbbbbbbbbbb\ncccccccccc\n")

    with patch("docker.from_env", return_value=_fake_client([web])):
        result = domain.get_app_logs("web")

    (marker,) = result.download_markers
    got = requester.store.get(marker.split("path=")[1].split('"')[0], "alice")
    assert got.data == b"cccccccccc\n"
    assert result.lines == 1 and "cut to the newest part" in result.message


def test_a_log_without_a_final_newline_counts_its_last_line(requester):
    web = _logging_container("web", b"one\ntwo")

    with patch("docker.from_env", return_value=_fake_client([web])):
        assert domain.get_app_logs("web").lines == 2


def test_a_log_that_exactly_fits_is_not_cut(requester, monkeypatch):
    monkeypatch.setattr(downloads, "MAX_FILE_BYTES", 11)
    web = _logging_container("web", b"aaaaaaaaaa\n")  # 11 bytes

    with patch("docker.from_env", return_value=_fake_client([web])):
        result = domain.get_app_logs("web")

    assert "cut" not in result.message
    assert result.lines == 1 and len(result.download_markers) == 1
