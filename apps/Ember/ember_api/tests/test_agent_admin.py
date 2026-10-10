"""/api/admin/agents: forwarded to ai_agent's /agents routes, agents.manage only."""

from __future__ import annotations

import json

import httpx

from tests.conftest import FakeEmailSender, FakeUpstream
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

CONFIG = {"label": "Calc", "port": 9103, "llm": {"provider": "anthropic", "gateway": "claude"}}


def ai_agent(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    if path == "/agents/gateways":
        return httpx.Response(200, json={"providers": {"anthropic": [{"id": "claude", "label": "Claude"}]}})
    if path == "/agents/files" and method == "GET":
        return httpx.Response(200, json={"agents": [{"id": "ember", "port": 9100}]})
    if path == "/agents/files" and method == "POST":
        body = json.loads(request.content)
        if body["id"] == "ember":
            return httpx.Response(409, json={"error": "agent 'ember' already exists"})
        return httpx.Response(201, json={"id": body["id"], **body["config"]})
    if path == "/agents/files/calc" and method == "PUT":
        return httpx.Response(200, json={"id": "calc", **json.loads(request.content)})
    if path == "/agents/files/ember" and method == "DELETE":
        return httpx.Response(409, json={"error": "'ember' is the entry agent"})
    if path == "/agents/files/calc" and method == "DELETE":
        return httpx.Response(200, json={"deleted": "calc"})
    if path == "/agents/prompts" and method == "GET":
        return httpx.Response(200, json={"values": {"app_name": "Ember"}, "defaults": {"app_name": "Ember"}, "overridden": []})
    if path == "/agents/prompts" and method == "PUT":
        changes = json.loads(request.content)
        if "bogus" in changes:
            return httpx.Response(400, json={"error": "unknown prompt 'bogus'"})
        return httpx.Response(200, json={"values": changes, "defaults": {}, "overridden": sorted(changes)})
    if path == "/agents/prompt-preview":
        return httpx.Response(200, json={"prompt": "PROMPT for " + json.loads(request.content)["id"]})
    return httpx.Response(404, json={"error": "no route"})


def test_admin_lists_creates_updates_and_deletes(client, upstream: FakeUpstream) -> None:
    upstream.handler = ai_agent
    as_admin(client)

    assert client.get("/api/admin/agents/gateways").json()["providers"]["anthropic"][0]["id"] == "claude"
    assert client.get("/api/admin/agents").json() == {"agents": [{"id": "ember", "port": 9100}]}

    created = client.post("/api/admin/agents", json={"id": "calc", "config": CONFIG})
    assert (created.status_code, created.json()["port"]) == (201, 9103)
    sent = upstream.requests[-1]
    assert str(sent.url) == "http://agent-a.internal/agents/files"
    assert sent.headers["x-requester-username"] == "root"
    assert len(sent.headers["x-requester-uid"]) == 32

    assert client.put("/api/admin/agents/calc", json={"config": CONFIG}).json()["id"] == "calc"
    assert json.loads(upstream.requests[-1].content) == CONFIG
    assert client.delete("/api/admin/agents/calc").status_code == 204


def test_ai_agent_refusals_pass_through(client, upstream: FakeUpstream) -> None:
    upstream.handler = ai_agent
    as_admin(client)

    clash = client.post("/api/admin/agents", json={"id": "ember", "config": CONFIG})
    assert (clash.status_code, clash.json()["detail"]) == (409, "agent 'ember' already exists")
    assert client.delete("/api/admin/agents/ember").status_code == 409
    assert client.put("/api/admin/agents/ghost", json={"config": CONFIG}).status_code == 404


def test_bad_ids_and_bodies_are_rejected_before_ai_agent(client, upstream: FakeUpstream) -> None:
    upstream.handler = ai_agent
    as_admin(client)
    before = len(upstream.requests)

    assert client.post("/api/admin/agents", json={"id": "Bad Id", "config": CONFIG}).status_code == 422
    assert client.post("/api/admin/agents", json={"id": "calc"}).status_code == 422
    assert client.delete("/api/admin/agents/Bad_Id").status_code == 422
    assert len(upstream.requests) == before


def test_unreachable_ai_agent_is_502(client, upstream: FakeUpstream) -> None:
    upstream.unreachable = True
    as_admin(client)
    assert client.get("/api/admin/agents").status_code == 502


def test_needs_login_and_agents_manage(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    upstream.handler = ai_agent
    anonymous = client_factory()
    assert anonymous.get("/api/admin/agents").status_code == 401

    member = client_factory()
    make_member(member, email)
    login(member, "alice")
    assert member.get("/api/admin/agents").status_code == 403
    assert member.post("/api/admin/agents", json={"id": "calc", "config": CONFIG}).status_code == 403
    assert member.delete("/api/admin/agents/calc").status_code == 403
    assert upstream.requests == []


def test_shared_prompts_read_change_log_and_preview(client, upstream: FakeUpstream) -> None:
    upstream.handler = ai_agent
    as_admin(client)

    assert client.get("/api/admin/agent-prompts").json()["values"] == {"app_name": "Ember"}
    changed = client.put("/api/admin/agent-prompts", json={"app_name": "Ascended", "roster_intro": None})
    assert (changed.status_code, changed.json()["overridden"]) == (200, ["app_name", "roster_intro"])
    assert json.loads(upstream.requests[-1].content) == {"app_name": "Ascended", "roster_intro": None}
    assert client.put("/api/admin/agent-prompts", json={"bogus": "x"}).status_code == 400
    assert client.put("/api/admin/agent-prompts", json={"app_name": 5}).status_code == 422

    preview = client.post("/api/admin/agent-prompt-preview", json={"id": "calc", "config": CONFIG, "caveman": True})
    assert preview.json() == {"prompt": "PROMPT for calc"}
    assert json.loads(upstream.requests[-1].content) == {"id": "calc", "config": CONFIG, "caveman": True}
    assert client.post("/api/admin/agent-prompt-preview", json={"id": "Bad Id", "config": CONFIG}).status_code == 422


def test_shared_prompts_need_agents_manage(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    upstream.handler = ai_agent
    assert client_factory().get("/api/admin/agent-prompts").status_code == 401
    member = client_factory()
    make_member(member, email)
    login(member, "alice")
    assert member.get("/api/admin/agent-prompts").status_code == 403
    assert member.put("/api/admin/agent-prompts", json={"app_name": "x"}).status_code == 403
    assert member.post("/api/admin/agent-prompt-preview", json={"id": "calc", "config": CONFIG}).status_code == 403
    assert upstream.requests == []
