"""Overview (landing) page tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def client(client, monkeypatch):
    """Login is mandatory app-wide with no unconfigured fallback (see
    security.py), so every test below needs a real session to reach the
    page at all. Overrides conftest.py's plain client with one that's
    already logged in as an always-full-access admin - the tests here
    are about the overview page's own content, not about login/RBAC
    itself (that's test_auth_routes.py/test_account_routes.py's job)."""
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw-1")
    client.post("/login", data={"username": "test-admin", "password": "test-admin-pw-1"})
    return client


def test_overview_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_overview_page_links_to_chat_and_capabilities(client):
    response = client.get("/")

    html = response.data.decode()
    assert 'href="/chat"' in html
    assert 'href="/capabilities"' in html
