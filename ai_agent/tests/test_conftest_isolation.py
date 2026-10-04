"""The autouse registry isolation in conftest.py: no test sees (or rewrites)
the developer's real agent registry."""

from __future__ import annotations

from src import agent_registry


def test_registry_paths_do_not_point_at_the_real_config_files():
    assert not agent_registry._CONFIG_PATH.exists()
    assert not agent_registry._CHAT_APP_CONFIG_PATH.exists()


def test_registry_starts_empty_and_reload_keeps_it_empty():
    assert agent_registry.all_agents() == []
    agent_registry.reload()
    assert agent_registry.all_agents() == []
