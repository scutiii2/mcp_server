from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.services import template_service
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin


def create(client: TestClient, name: str = "Review", body: str = "Please review this:") :
    return client.post("/api/templates", json={"name": name, "body": body})


def listing(client: TestClient) -> list[dict]:
    return client.get("/api/templates").json()


# --- access -------------------------------------------------------------------


def test_templates_need_login_and_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    assert client.get("/api/templates").status_code == 401
    assert create(client).status_code == 401

    make_member(client, email, verify=False)
    login(client, "alice")
    assert client.get("/api/templates").status_code == 403  # unverified: no permissions
    assert create(client).status_code == 403


def test_templates_are_private_per_account(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    mine = create(alice, "Mine", "secret plan").json()

    bob = client_factory()
    login(bob, "bob")

    assert listing(bob) == []
    assert bob.put(f"/api/templates/{mine['id']}", json={"name": "x", "body": "y"}).status_code == 404
    assert bob.delete(f"/api/templates/{mine['id']}").status_code == 404
    # Bob may use the same name: names are unique per account, not globally.
    assert create(bob, "Mine", "bob's").status_code == 201
    assert [t["body"] for t in listing(alice)] == ["secret plan"]


# --- CRUD ---------------------------------------------------------------------


def test_create_list_update_delete(client: TestClient) -> None:
    as_admin(client)

    created = create(client, "  Code   review ", "Line one\n  indented line\n")

    assert created.status_code == 201
    template = created.json()
    assert template["name"] == "Code review"  # trimmed, inner whitespace collapsed
    assert template["body"] == "Line one\n  indented line\n"  # the body is kept as typed
    assert listing(client) == [template]

    updated = client.put(f"/api/templates/{template['id']}", json={"name": "Review v2", "body": "New text"})
    assert updated.status_code == 200
    assert (updated.json()["name"], updated.json()["body"]) == ("Review v2", "New text")
    assert updated.json()["created_at"] == template["created_at"]

    assert client.delete(f"/api/templates/{template['id']}").status_code == 204
    assert listing(client) == []
    assert client.delete(f"/api/templates/{template['id']}").status_code == 404


def test_list_puts_the_most_recently_edited_first(client: TestClient) -> None:
    as_admin(client)
    first = create(client, "First", "1").json()
    create(client, "Second", "2")
    assert [t["name"] for t in listing(client)] == ["Second", "First"]

    client.put(f"/api/templates/{first['id']}", json={"name": "First", "body": "1 edited"})

    assert [t["name"] for t in listing(client)] == ["First", "Second"]


def test_unknown_or_out_of_range_ids(client: TestClient) -> None:
    as_admin(client)
    body = {"name": "x", "body": "y"}

    assert client.put("/api/templates/999", json=body).status_code == 404
    assert client.delete("/api/templates/999").status_code == 404
    assert client.put("/api/templates/0", json=body).status_code == 422
    assert client.delete("/api/templates/not-a-number").status_code == 422


# --- names --------------------------------------------------------------------


def test_names_are_unique_per_account_ignoring_case(client: TestClient) -> None:
    as_admin(client)
    create(client, "Review")

    duplicate = create(client, "  REVIEW  ")

    assert duplicate.status_code == 409
    assert "Review" in duplicate.json()["detail"] or "REVIEW" in duplicate.json()["detail"]
    assert len(listing(client)) == 1


def test_renaming_onto_another_name_is_refused_but_keeping_your_own_is_fine(client: TestClient) -> None:
    as_admin(client)
    a = create(client, "Alpha", "a").json()
    b = create(client, "Beta", "b").json()

    assert client.put(f"/api/templates/{b['id']}", json={"name": "alpha", "body": "b"}).status_code == 409
    # Changing only the case of its own name is an edit, not a clash.
    assert client.put(f"/api/templates/{a['id']}", json={"name": "ALPHA", "body": "a"}).status_code == 200
    assert {t["name"] for t in listing(client)} == {"ALPHA", "Beta"}


def test_a_failed_rename_leaves_the_template_as_it_was(client: TestClient) -> None:
    as_admin(client)
    create(client, "Alpha", "a")
    b = create(client, "Beta", "old body").json()

    client.put(f"/api/templates/{b['id']}", json={"name": "alpha", "body": "new body"})

    assert {t["name"]: t["body"] for t in listing(client)} == {"Alpha": "a", "Beta": "old body"}


def test_non_ascii_names_fold_too(client: TestClient) -> None:
    as_admin(client)
    create(client, "Straße")

    assert create(client, "STRASSE").status_code == 409


# --- validation and limits -----------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "body": "x"},
        {"name": "   ", "body": "x"},
        {"name": "x", "body": ""},
        {"name": "x", "body": " \n\t "},
        {"name": "n" * 61, "body": "x"},
        {"name": "x", "body": "b" * (template_service.BODY_MAX + 1)},
        {"name": "x"},
        {"body": "x"},
        {"name": 5, "body": "x"},
    ],
)
def test_validation(client: TestClient, payload: dict) -> None:
    as_admin(client)

    assert client.post("/api/templates", json=payload).status_code == 422
    assert listing(client) == []


def test_the_longest_allowed_name_and_body_are_accepted(client: TestClient) -> None:
    as_admin(client)

    response = create(client, "n" * template_service.NAME_MAX, "b" * template_service.BODY_MAX)

    assert response.status_code == 201


def test_template_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(template_service, "MAX_TEMPLATES_PER_ACCOUNT", 2)
    as_admin(client)
    create(client, "One")
    create(client, "Two")

    response = create(client, "Three")

    assert response.status_code == 409
    assert "At most 2" in response.json()["detail"]
    assert len(listing(client)) == 2
    # Editing and deleting still work at the limit, and deleting frees a slot.
    assert client.delete(f"/api/templates/{listing(client)[0]['id']}").status_code == 204
    assert create(client, "Three").status_code == 201


def test_posts_must_be_json(client: TestClient) -> None:
    as_admin(client)

    response = client.post("/api/templates", content="name=x&body=y", headers={"Content-Type": "text/plain"})

    assert response.status_code == 415


# --- account deletion -----------------------------------------------------------


def test_templates_go_with_their_account(client: TestClient, email: FakeEmailSender) -> None:
    alice_id = make_member(client, email)
    login(client, "alice")
    create(client)
    client.post("/api/auth/logout", json={})

    as_admin(client)
    client.delete(f"/api/admin/accounts/{alice_id}")

    async def remaining() -> int:
        from sqlalchemy import func, select

        from src.models import PromptTemplate

        async with client.app.state.database.sessions() as session:
            return await session.scalar(select(func.count()).select_from(PromptTemplate))

    assert client.portal.call(remaining) == 0
