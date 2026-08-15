"""Overview (landing) page tests."""

from __future__ import annotations


def test_overview_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_overview_page_links_to_chat_and_capabilities(client):
    response = client.get("/")

    html = response.data.decode()
    assert 'href="/chat"' in html
    assert 'href="/capabilities"' in html
