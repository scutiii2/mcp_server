from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender, FakeUpstream
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

URL = "/api/account-capabilities"
CAPABILITIES = [
    {"name": "pdf", "enabled": True, "label": "PDF files", "tools": ["tool_pdf_split", "tool_pdf_merge"], "resources": [], "has_gui": False},
    {"name": "calc", "enabled": True, "label": "Calculator", "tools": ["tool_calc"], "resources": [], "has_gui": False},
]
ALL_TOOLS = ["tool_calc", "tool_pdf_merge", "tool_pdf_split"]


def mcp_server(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/capabilities":
        return httpx.Response(200, json=CAPABILITIES)
    return httpx.Response(404, json={"error": "nope"})


@pytest.fixture(autouse=True)
def serve_capabilities(upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server


def put(client: TestClient, kind: str, key: str, enabled: bool = True):
    return client.put(f"{URL}/{kind}/{key}", json={"enabled": enabled})


def test_needs_login(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert put(client, "capability", "pdf").status_code == 401


def test_a_new_account_has_nothing_added_so_every_tool_is_disabled(client: TestClient) -> None:
    as_admin(client)

    assert client.get(URL).json() == {"capabilities": [], "extensions": [], "disabled_tools": ALL_TOOLS}


def test_adding_a_capability_frees_its_tools(client: TestClient) -> None:
    as_admin(client)

    added = put(client, "capability", "pdf")

    assert added.status_code == 200
    expected = {"capabilities": ["pdf"], "extensions": [], "disabled_tools": ["tool_calc"]}
    assert added.json() == expected
    assert client.get(URL).json() == expected


def test_adding_an_extension_leaves_the_tools_alone(client: TestClient) -> None:
    as_admin(client)

    result = put(client, "extension", "notes").json()

    assert result == {"capabilities": [], "extensions": ["notes"], "disabled_tools": ALL_TOOLS}


def test_the_same_change_twice_is_a_no_op(client: TestClient) -> None:
    as_admin(client)

    first = put(client, "capability", "pdf").json()
    second = put(client, "capability", "pdf").json()

    assert first == second
    assert put(client, "capability", "calc", enabled=False).json() == first  # was never added


def test_disabling_takes_it_away_again(client: TestClient) -> None:
    as_admin(client)
    put(client, "capability", "pdf")
    put(client, "capability", "calc")

    result = put(client, "capability", "pdf", enabled=False).json()

    assert result == {"capabilities": ["calc"], "extensions": [], "disabled_tools": ["tool_pdf_merge", "tool_pdf_split"]}


def test_lists_are_sorted(client: TestClient) -> None:
    as_admin(client)
    put(client, "extension", "zeta")
    put(client, "extension", "alpha")

    assert client.get(URL).json()["extensions"] == ["alpha", "zeta"]


def test_a_capability_and_an_extension_can_share_an_id(client: TestClient) -> None:
    as_admin(client)
    put(client, "capability", "notes")
    put(client, "extension", "notes")

    body = client.get(URL).json()

    assert (body["capabilities"], body["extensions"]) == (["notes"], ["notes"])


def test_bad_input_is_refused(client: TestClient) -> None:
    as_admin(client)

    assert put(client, "widget", "pdf").status_code == 422
    assert put(client, "capability", "x" * 65).status_code == 422
    assert put(client, "capability", "bad key").status_code == 422
    assert client.put(f"{URL}/capability/pdf", json={}).status_code == 422
    assert client.put(f"{URL}/capability/pdf", json={"enabled": "yes please"}).status_code == 422


def test_private_per_account(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    put(alice, "capability", "pdf")

    bob = client_factory()
    login(bob, "bob")

    assert bob.get(URL).json()["capabilities"] == []
    put(bob, "capability", "calc")
    put(bob, "capability", "calc", enabled=False)
    assert alice.get(URL).json()["capabilities"] == ["pdf"]


def test_at_most_max_items_per_account(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.account_capability_service.MAX_ITEMS", 2)
    as_admin(client)
    assert put(client, "extension", "a").status_code == 200
    assert put(client, "extension", "b").status_code == 200

    over = put(client, "extension", "c")

    assert over.status_code == 409
    assert put(client, "extension", "a").status_code == 200  # already added: not a new row
    assert put(client, "extension", "b", enabled=False).status_code == 200  # taking one away still works
    assert put(client, "extension", "c").status_code == 200


def test_mcp_server_down_means_no_answer_and_no_change(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)
    upstream.unreachable = True

    assert client.get(URL).status_code == 502
    assert put(client, "capability", "pdf").status_code == 502

    upstream.unreachable = False
    assert client.get(URL).json()["capabilities"] == []


def test_each_change_is_logged(client: TestClient) -> None:
    as_admin(client)
    put(client, "capability", "pdf")
    put(client, "extension", "notes")
    put(client, "capability", "pdf", enabled=False)
    me = client.get("/api/auth/me").json()["id"]

    logged = [e["message"] for e in client.get("/api/logs/action", params={"actor": me}).json()]

    assert logged[:3] == [
        "Disabled capability 'pdf'",
        "Added extension 'notes'",
        "Added capability 'pdf'",
    ]


def test_removing_an_extension_clears_it_for_every_account(
    client_factory, email: FakeEmailSender, upstream: FakeUpstream
) -> None:
    def server(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" and request.url.path == "/extensions/notes":
            return httpx.Response(204)
        return mcp_server(request)

    upstream.handler = server
    alice = client_factory()
    make_member(alice, email)
    login(alice, "alice")
    put(alice, "extension", "notes")
    put(alice, "extension", "wiki")

    admin = as_admin(client_factory())
    put(admin, "extension", "notes")
    assert admin.delete("/api/extensions/notes").status_code == 204

    assert alice.get(URL).json()["extensions"] == ["wiki"]
    assert admin.get(URL).json()["extensions"] == []
