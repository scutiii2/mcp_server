from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

URL = "/api/nav-preferences"


def save(client: TestClient, order=(), pinned=(), hidden=()):
    return client.put(URL, json={"order": list(order), "pinned": list(pinned), "hidden": list(hidden)})


def test_needs_login(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert save(client).status_code == 401
    assert client.delete(URL).status_code == 401


def test_default_is_empty(client: TestClient) -> None:
    as_admin(client)

    assert client.get(URL).json() == {"order": [], "pinned": [], "hidden": []}


def test_save_and_read_back(client: TestClient) -> None:
    as_admin(client)

    saved = save(client, ["/agents", "/", "/usage"], pinned=["/usage"], hidden=["/"])

    assert saved.status_code == 200
    expected = {"order": ["/agents", "/", "/usage"], "pinned": ["/usage"], "hidden": ["/"]}
    assert saved.json() == expected
    assert client.get(URL).json() == expected

    save(client, ["/", "/agents"])  # replaces, does not merge
    assert client.get(URL).json() == {"order": ["/", "/agents"], "pinned": [], "hidden": []}


def test_lists_are_cleaned(client: TestClient) -> None:
    as_admin(client)

    result = save(
        client,
        order=["/a", "/b", "/a"],
        pinned=["/a", "/a", "/ghost", "/b"],
        hidden=["/b", "/ghost"],
    ).json()

    assert result["order"] == ["/a", "/b"]  # repeats dropped
    assert result["hidden"] == ["/b"]  # only pages in the order
    assert result["pinned"] == ["/a"]  # not in the order, or hidden: dropped


def test_limits(client: TestClient) -> None:
    as_admin(client)

    assert save(client, [f"/p{i}" for i in range(51)]).status_code == 422
    assert save(client, ["/" + "x" * 64]).status_code == 422
    assert save(client, [""]).status_code == 422
    assert client.put(URL, json={"order": "/agents"}).status_code == 422


def test_reset(client: TestClient) -> None:
    as_admin(client)
    save(client, ["/a"], pinned=["/a"])

    assert client.delete(URL).status_code == 204
    assert client.get(URL).json() == {"order": [], "pinned": [], "hidden": []}
    assert client.delete(URL).status_code == 204  # nothing left: still fine


def test_private_per_account(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    save(alice, ["/a", "/b"], pinned=["/b"])

    bob = client_factory()
    login(bob, "bob")

    assert bob.get(URL).json() == {"order": [], "pinned": [], "hidden": []}
    save(bob, ["/c"])
    bob.delete(URL)
    assert alice.get(URL).json()["order"] == ["/a", "/b"]
