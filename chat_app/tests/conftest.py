"""Shared fixtures. No live MCP server or OpenAI key needed to run this suite -
every test that touches mcp_client/openai_service mocks the specific function
it needs, at the point it's imported into the route module."""

from __future__ import annotations

import pytest

from chat_app.app import create_app


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
