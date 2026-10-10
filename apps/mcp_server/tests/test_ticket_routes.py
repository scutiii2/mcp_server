from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import ticket_routes
from src.services import tickets
from src.services.ticket_config import load_ticket_config
from src.services.ticket_store import TicketStore
from src.services.tickets import TicketService
from src.ticket_routes import install_ticket_routes

TOKEN = "shared-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    service = TicketService(TicketStore(tmp_path / "t.db"), load_ticket_config(tmp_path / "none.json"))
    monkeypatch.setattr(tickets, "_service", service)
    monkeypatch.setattr(ticket_routes, "settings", SimpleNamespace(internal_api_token=TOKEN))
    app = Starlette()
    install_ticket_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def headers(user="alice", token=TOKEN, uid="default"):
    """Requester headers: the username is only a display name; the uid (uid-<user> unless given) owns tickets."""
    result = {}
    if token is not None:
        result["X-Internal-Token"] = token
    if user is not None:
        result["X-Requester-Username"] = user
    if uid == "default":
        uid = f"uid-{user}" if user is not None else None
    if uid is not None:
        result["X-Requester-Uid"] = uid
    return result


BODY = {"type": "bug", "title": "Email fails", "description": "It does not send", "tags": ["email"]}


def file_ticket(client, user="alice", **over):
    response = client.post("/tickets", json={**BODY, **over}, headers=headers(user))
    assert response.status_code == 201, response.text
    return response.json()["ticket"]


def test_token_is_required_on_every_route(client):
    for method, path in [("get", "/tickets"), ("post", "/tickets"), ("get", "/ticket-admin/tickets"),
                         ("get", "/ticket-admin/groups"), ("get", "/ticket-admin/stats")]:
        assert getattr(client, method)(path, headers=headers(token=None)).status_code == 401
        assert getattr(client, method)(path, headers=headers(token="wrong")).status_code == 401


def test_unset_token_never_validates(client, monkeypatch):
    monkeypatch.setattr(ticket_routes, "settings", SimpleNamespace(internal_api_token=""))
    assert client.get("/tickets", headers={"X-Internal-Token": ""}).status_code == 401


def test_create_list_get_comment_close_as_reporter(client):
    created = client.post("/tickets", json=BODY, headers=headers())
    assert created.status_code == 201
    body = created.json()
    assert body["duplicate"] is False and body["group_size"] == 1 and body["ticket"]["reporter"] == "alice"
    ticket_id = body["ticket"]["id"]

    assert [t["id"] for t in client.get("/tickets", headers=headers()).json()["tickets"]] == [ticket_id]
    assert client.get(f"/tickets/{ticket_id}", headers=headers()).json()["ticket"]["comments"] == []

    commented = client.post(f"/tickets/{ticket_id}/comments", json={"body": "more detail"}, headers=headers())
    assert commented.json()["ticket"]["comments"][0]["author_role"] == "reporter"

    closed = client.post(f"/tickets/{ticket_id}/close", headers=headers())
    assert closed.json()["ticket"]["status"] == "closed"


def test_reporter_cannot_see_or_touch_someone_elses_ticket(client):
    ticket_id = file_ticket(client, user="alice")["id"]

    assert client.get(f"/tickets/{ticket_id}", headers=headers("bob")).status_code == 404
    assert client.post(f"/tickets/{ticket_id}/comments", json={"body": "x"}, headers=headers("bob")).status_code == 404
    assert client.post(f"/tickets/{ticket_id}/close", headers=headers("bob")).status_code == 404
    assert client.get("/tickets", headers=headers("bob")).json() == {"tickets": []}


def test_reporter_identity_comes_only_from_the_header(client):
    ticket = file_ticket(client, user="alice", reporter="mallory")
    assert ticket["reporter"] == "alice"
    assert client.get("/tickets", headers=headers(user=None)).status_code == 400


def test_bad_input_is_a_400_with_a_message(client):
    assert client.post("/tickets", json={**BODY, "type": "complaint"}, headers=headers()).status_code == 400
    bad_json = client.post("/tickets", content=b"{nope", headers=headers())
    assert bad_json.status_code == 400 and "JSON" in bad_json.json()["error"]
    assert client.post("/tickets", json=[1, 2], headers=headers()).status_code == 400
    assert client.get("/tickets/abc", headers=headers()).status_code in (404, 400)


def test_auto_duplicate_returns_the_existing_ticket(client):
    body = {**BODY, "source": "ai_auto", "context": {"tool_name": "t", "error_text": "boom 1"}}
    first = client.post("/tickets", json=body, headers=headers()).json()
    again = client.post("/tickets", json={**body, "context": {"tool_name": "t", "error_text": "boom 2"}}, headers=headers())

    assert again.status_code == 200
    assert again.json()["duplicate"] is True and again.json()["ticket"]["id"] == first["ticket"]["id"]


def test_staff_routes_see_everything_and_change_it(client):
    a = file_ticket(client, user="alice")
    b = file_ticket(client, user="bob", title="UI glitch", tags=["ui"])
    staff = headers("root")

    listing = client.get("/ticket-admin/tickets", params={"tag": "ui"}, headers=staff).json()["tickets"]
    assert [t["id"] for t in listing] == [b["id"]]
    assert client.get(f"/ticket-admin/tickets/{a['id']}", headers=staff).json()["ticket"]["reporter"] == "alice"

    patched = client.patch(f"/ticket-admin/tickets/{a['id']}", json={"status": "in_progress", "assignee": "root"}, headers=staff)
    assert patched.json()["ticket"]["status"] == "in_progress" and patched.json()["ticket"]["assignee"] == "root"

    comment = client.post(f"/ticket-admin/tickets/{a['id']}/comments", json={"body": "looking"}, headers=staff)
    last = comment.json()["ticket"]["comments"][-1]
    assert (last["author"], last["author_role"]) == ("root", "staff")

    moved = client.post(f"/ticket-admin/tickets/{b['id']}/move", json={"group_id": a["group_id"]}, headers=staff)
    assert moved.json()["ticket"]["group_id"] == a["group_id"]

    groups = client.get("/ticket-admin/groups", headers=staff).json()["groups"]
    assert groups[0]["ticket_count"] == 2

    pinned = client.patch(f"/ticket-admin/groups/{a['group_id']}", json={"priority": "urgent"}, headers=staff)
    assert pinned.json()["group"]["priority"] == "urgent" and pinned.json()["group"]["priority_pinned"] is True
    assert client.get("/ticket-admin/stats", headers=staff).json() == {"open": 2, "urgent": 2, "groups": 1}


def test_staff_errors(client):
    staff = headers("root")
    assert client.get("/ticket-admin/tickets/999", headers=staff).status_code == 404
    assert client.patch("/ticket-admin/tickets/999", json={"status": "open"}, headers=staff).status_code == 404
    ticket = file_ticket(client)
    assert client.patch(f"/ticket-admin/tickets/{ticket['id']}", json={"status": "done"}, headers=staff).status_code == 400
    assert client.post(f"/ticket-admin/tickets/{ticket['id']}/move", json={"group_id": 999}, headers=staff).status_code == 404
    assert client.patch("/ticket-admin/groups/999", json={"priority": "low"}, headers=staff).status_code == 404


@pytest.mark.parametrize("assignee", [42, [], {}, True])
def test_staff_assignee_requires_a_string(client, assignee):
    ticket = file_ticket(client)
    response = client.patch(f"/ticket-admin/tickets/{ticket['id']}",
                            json={"assignee": assignee}, headers=headers("root"))
    assert response.status_code == 400
    assert "assignee" in response.json()["error"]
    unchanged = client.get(f"/tickets/{ticket['id']}", headers=headers()).json()["ticket"]
    assert unchanged["assignee"] is None


def test_tag_choices_use_the_service_vocabulary_and_require_identity(client):
    response = client.get("/tickets/tags", headers=headers())
    assert response.status_code == 200
    assert {item["value"] for item in response.json()} == set(tickets.get_service()._config.tags)
    assert all(item["label"] == item["value"] and item["description"] for item in response.json())
    assert client.get("/tickets/tags", headers=headers(token=None)).status_code == 401
    assert client.get("/tickets/tags", headers=headers(user=None)).status_code == 400


def test_tag_choices_follow_custom_configuration(client, monkeypatch):
    service = tickets.get_service()
    monkeypatch.setattr(service, "_config", replace(service._config, tags={"storage": "Database issues", "network": "Connection issues"}))
    response = client.get("/tickets/tags", headers=headers())
    assert [item["value"] for item in response.json()] == ["storage", "network"]


def test_custom_tags_are_saved_and_choices_belong_to_the_reporter(client):
    created = file_ticket(client, tags=[" Mobile Bug ", "ui", "mobile-bug"])
    assert created["tags"] == ["mobile-bug", "ui"]
    alice_tags = client.get("/tickets/tags", headers=headers()).json()
    assert "mobile-bug" in {tag["value"] for tag in alice_tags}
    bob_tags = client.get("/tickets/tags", headers=headers("bob")).json()
    assert "mobile-bug" not in {tag["value"] for tag in bob_tags}


def test_invalid_custom_tag_reports_a_validation_error(client):
    response = client.post("/tickets", json={**BODY, "tags": ["x" * 65]}, headers=headers())
    assert response.status_code == 400
    assert "tag" in response.json()["error"].lower()


def test_reporter_routes_need_a_uid(client):
    no_uid = headers("alice", uid=None)

    assert client.get("/tickets", headers=no_uid).status_code == 400
    assert client.post("/tickets", json=BODY, headers=no_uid).status_code == 400
    assert client.get("/tickets/1", headers=no_uid).status_code == 400
    assert client.get("/tickets/tags", headers=no_uid).status_code == 400


def test_tickets_follow_the_uid_through_a_rename_and_name_reuse(client):
    ticket = file_ticket(client, user="alice")
    renamed = headers("alice-renamed", uid="uid-alice")
    stranger = headers("alice", uid="uid-someone-else")

    assert ticket["reporter"] == "alice"  # the name it was filed under
    assert [t["id"] for t in client.get("/tickets", headers=renamed).json()["tickets"]] == [ticket["id"]]
    assert client.get(f"/tickets/{ticket['id']}", headers=renamed).status_code == 200
    assert client.post(f"/tickets/{ticket['id']}/comments", json={"body": "still mine"}, headers=renamed).status_code == 200
    assert client.get("/tickets", headers=stranger).json() == {"tickets": []}
    assert client.get(f"/tickets/{ticket['id']}", headers=stranger).status_code == 404
    assert client.post(f"/tickets/{ticket['id']}/close", headers=stranger).status_code == 404


def test_staff_comment_is_signed_with_the_display_name(client):
    ticket = file_ticket(client, user="alice")

    response = client.post(f"/ticket-admin/tickets/{ticket['id']}/comments", json={"body": "hello"}, headers=headers("root"))

    assert response.json()["ticket"]["comments"][-1]["author"] == "root"
