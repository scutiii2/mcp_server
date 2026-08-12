"""Shared fixtures. No live MCP server or LLM provider needed to run this suite -
every test that touches mcp_client/llm providers mocks the specific function
it needs, at the point it's imported into the route module."""

from __future__ import annotations

import pytest

from chat_app.app import create_app
from chat_app.services.llm import cooldown


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_cooldowns():
    """Cooldown state is a module-level dict shared across the whole
    process (see cooldown.py's docstring for why) - which means it's
    equally shared across test cases unless we clear it between each one."""
    cooldown.reset()
    yield
    cooldown.reset()
