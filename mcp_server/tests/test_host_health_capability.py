"""Tests for the tool that wraps the host-health resource.

The gathering logic is covered by test_host_health_domain.py and is not
retested here - the point of this capability is the wrapping, so these
cover what the wrapper adds: a recoverable error for a wrong name, and a
result that carries structure as well as text.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.capabilities.host_health import domain
from mcp_server.capabilities.host_health.contract import HostHealth
from mcp_server.resources.host_health.contract import DiskUsage


HOSTS = {
    "zima": {"hostname": "192.168.1.9", "user": "lex", "os": "linux", "key": "/k/id"},
    "desktop": {"hostname": "192.168.1.20", "user": "User", "os": "windows",
                "password": "${DESKTOP_SSH_PASSWORD}"},
}


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config_hosts.json"
    path.write_text(json.dumps(HOSTS), encoding="utf-8")
    return path


def _health() -> HostHealth:
    return HostHealth(
        name="zima", hostname="192.168.1.9", os="linux", uptime_seconds=3600,
        cpu_count=4, memory_total_kb=8_000_000, memory_available_kb=4_000_000,
        disks=[DiskUsage(mount="/", total_kb=100_000, free_kb=40_000)],
        load_average_1m=0.5,
    )


def test_check_returns_report_and_structure(tmp_path: Path):
    """A resource read is its own text, but a model may need to compare
    figures - so the tool carries both rather than making it parse prose."""
    with patch("mcp_server.capabilities.host_health.domain.collect", return_value=_health()):
        result = domain.check(_config(tmp_path), "zima")

    assert result.name == "zima"
    assert "zima" in result.report
    assert result.health.cpu_count == 4
    assert result.health.disks[0].used_percent == 60.0


def test_unknown_name_lists_the_names_that_exist(tmp_path: Path):
    """The caller is a model that guessed. "Unknown host" ends the
    interaction; naming the alternatives lets it recover on the next
    turn."""
    with pytest.raises(KeyError) as error:
        domain.check(_config(tmp_path), "zimaa")

    message = str(error.value)
    assert "zima" in message and "desktop" in message


def test_names_are_listed_even_when_a_host_secret_is_unset(tmp_path: Path, monkeypatch):
    """Regression guard: reading the names through load_hosts_config would
    resolve every ${VAR} and fail whenever any host had an unset secret -
    replacing the one message meant to help with a confusing one. Names
    are JSON keys, so they are readable without resolving anything."""
    monkeypatch.delenv("DESKTOP_SSH_PASSWORD", raising=False)

    assert domain.known_host_names(_config(tmp_path)) == ["desktop", "zima"]

    with pytest.raises(KeyError, match="desktop"):
        domain.check(_config(tmp_path), "nope")


def test_empty_hosts_file_says_so_rather_than_listing_nothing(tmp_path: Path):
    """config_hosts.json's whole content *is* the hosts map now, so an
    empty "{}" - a fresh install with no host inventory yet - is the
    "no hosts configured" state, not a malformed document."""
    path = tmp_path / "config_hosts.json"
    path.write_text(json.dumps({}), encoding="utf-8")

    with pytest.raises(KeyError, match="No hosts are configured"):
        domain.check(path, "zima")


def test_contract_reuses_the_resource_models(tmp_path: Path):
    """Not a copy: two definitions of the same facts would drift silently,
    since nothing compares them."""
    from mcp_server.capabilities.host_health import contract as capability_contract
    from mcp_server.resources.host_health import contract as resource_contract

    assert capability_contract.HostHealth is resource_contract.HostHealth
    assert capability_contract.DiskUsage is resource_contract.DiskUsage
