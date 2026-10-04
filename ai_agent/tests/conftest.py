"""Primes a valid pinned-provider config before any test module imports
src.agent_config / src.server - both resolve PROVIDER_ID/MODEL once at
import time (see agent_config.py's module docstring) and raise
AgentConfigError immediately if AI_AGENT_PROVIDER or its API key isn't
set, which would otherwise break collection of test_server.py.

Set directly on os.environ (not via a monkeypatch fixture, which only
applies inside a running test) since this must be in place before pytest
even imports the test modules. test_agent_config.py's own tests still
freely override/clear these per test via monkeypatch - that only affects
the duration of each test, never this module-level default.
"""

import os

os.environ.setdefault("AI_AGENT_PROVIDER", "anthropic")
os.environ.setdefault("CLAUDE_API_KEY", "test-key")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_agent_registry(monkeypatch, tmp_path):
    """Point the agent registry at empty, per-test files so no test reads or
    rewrites the developer's real config_agents.json (roster_for and
    delegation.call reload it). Tests needing agents set their own."""
    from src import agent_registry

    monkeypatch.setattr(agent_registry, "_CONFIG_PATH", tmp_path / "registry" / "config_agents.json")
    monkeypatch.setattr(agent_registry, "_CHAT_APP_CONFIG_PATH", tmp_path / "registry" / "chat_app_agents.json")
    monkeypatch.setattr(agent_registry, "_AGENTS", [])
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {})


import tempfile  # noqa: E402

# server.ask() appends every turn to the usage log; keep test turns out of
# the real ai_agent/data/usage/.
os.environ.setdefault("AI_AGENT_USAGE_DIR", tempfile.mkdtemp(prefix="ai_agent_usage_"))
