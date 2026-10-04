from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from tests.conftest import AGENTS, MCP_SERVER_URL, FakeUpstream
from tests.test_registration import as_admin, new_invite, register

AGENT_PATH = "/api/mcp/agents/claude-agent"
SERVER_PATH = "/api/mcp/server"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def call_tool(name: str, arguments: dict | None = None) -> dict:
    return rpc("tools/call", {"name": name, "arguments": arguments or {}})


def post(client: TestClient, path: str, payload, **headers) -> httpx.Response:
    return client.post(path, json=payload, headers={**MCP_HEADERS, **headers})


# --- agent listing ----------------------------------------------------------------


def test_agents_are_listed_without_urls(client: TestClient) -> None:
    as_admin(client)

    agents = client.get("/api/agents").json()

    assert agents == [{"id": a["id"], "label": a["label"]} for a in AGENTS]


def test_agent_listing_requires_login(client: TestClient) -> None:
    assert client.get("/api/agents").status_code == 401


# --- forwarding -------------------------------------------------------------------


def test_initialize_is_forwarded_with_identity_and_session_id(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    response = post(client, AGENT_PATH, rpc("initialize", {}))

    assert response.status_code == 200
    assert response.headers["mcp-session-id"] == "sess-1"
    sent = upstream.requests[-1]
    assert str(sent.url) == AGENTS[0]["url"]
    assert sent.headers["x-requester-username"] == "root"
    assert sent.headers["x-requester-email"] == "root@example.com"
    assert "x-internal-token" not in sent.headers  # none configured


def test_browser_cannot_forge_identity_or_leak_its_cookie(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    post(
        client,
        AGENT_PATH,
        rpc("initialize", {}),
        **{"X-Requester-Username": "someone-else", "X-Internal-Token": "guess", "mcp-session-id": "sess-9"},
    )

    sent = upstream.requests[-1]
    assert sent.headers["x-requester-username"] == "root"
    assert "x-internal-token" not in sent.headers
    assert "cookie" not in sent.headers
    assert sent.headers["mcp-session-id"] == "sess-9"  # MCP headers do pass through


def test_internal_token_is_sent_when_configured(client_factory, upstream: FakeUpstream) -> None:
    client = as_admin(client_factory(internal_token="s3cret-token"))

    post(client, AGENT_PATH, rpc("initialize", {}))

    assert upstream.requests[-1].headers["x-internal-token"] == "s3cret-token"


def test_event_stream_response_is_relayed(client: TestClient, upstream: FakeUpstream) -> None:
    events = [
        b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{"message":"tok"}}\n\n',
        b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"structuredContent":{"response":"hi"}}}\n\n',
    ]

    async def stream():
        for event in events:
            yield event

    upstream.handler = lambda _request: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=stream()
    )
    as_admin(client)

    with client.stream(
        "POST", AGENT_PATH, json=call_tool("status", {}), headers=MCP_HEADERS
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.headers["content-type"].startswith("text/event-stream")
    assert body == b"".join(events)
    assert json.loads(upstream.requests[-1].content)["params"]["name"] == "status"


def test_session_delete_without_content_type_is_forwarded(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    response = client.delete(AGENT_PATH, headers={"mcp-session-id": "sess-1"})

    assert response.status_code == 200
    assert upstream.requests[-1].method == "DELETE"


def test_unreachable_upstream_is_502(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.unreachable = True
    as_admin(client)

    assert post(client, AGENT_PATH, rpc("initialize", {})).status_code == 502


# --- what's allowed ---------------------------------------------------------------


def test_unknown_agent_is_404_and_never_contacted(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    assert post(client, "/api/mcp/agents/not-registered", rpc("initialize", {})).status_code == 404
    assert upstream.requests == []


def test_agent_tool_outside_the_allow_list_is_refused(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    response = post(client, AGENT_PATH, call_tool("interpret", {"text": "x"}))

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Tool not allowed: interpret"
    assert upstream.requests == []


def test_ask_and_cancel_are_refused_turns_run_server_side(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    for tool, arguments in (("ask", {"question": "hi"}), ("cancel", {"request_id": "x"})):
        response = post(client, AGENT_PATH, call_tool(tool, arguments))
        assert response.status_code == 403
        assert response.json()["error"]["message"] == f"Tool not allowed: {tool}"
    assert upstream.requests == []


def test_status_is_forwarded(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    assert post(client, AGENT_PATH, call_tool("status", {})).status_code == 200
    assert len(upstream.requests) == 1


def test_batch_with_one_bad_message_is_refused_whole(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    response = post(client, AGENT_PATH, [rpc("ping"), rpc("resources/list", request_id=2)])

    assert response.status_code == 403
    assert upstream.requests == []


def test_server_allows_tools_and_resources_but_not_prompts(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    assert post(client, SERVER_PATH, rpc("tools/list")).status_code == 200
    assert post(client, SERVER_PATH, call_tool("disk_usage", {"path": "/"})).status_code == 200
    assert post(client, SERVER_PATH, rpc("resources/list")).status_code == 200
    assert post(client, SERVER_PATH, rpc("resources/read", {"uri": "x"})).status_code == 200
    assert post(client, SERVER_PATH, rpc("prompts/list")).status_code == 403
    assert {str(r.url) for r in upstream.requests} == {MCP_SERVER_URL}
    assert len(upstream.requests) == 4


def test_malformed_json_is_a_parse_error(client: TestClient) -> None:
    as_admin(client)

    response = client.post(
        AGENT_PATH, content=b"{not json", headers={**MCP_HEADERS, "content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700


def test_oversized_body_is_413(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)

    response = post(client, AGENT_PATH, call_tool("status", {"pad": "x" * 1_100_000}))

    assert response.status_code == 413
    assert upstream.requests == []


# --- who may use it ---------------------------------------------------------------


def test_proxy_requires_login(client: TestClient, upstream: FakeUpstream) -> None:
    assert post(client, AGENT_PATH, rpc("initialize", {})).status_code == 401
    assert client.get(SERVER_PATH).status_code == 401
    assert upstream.requests == []


def test_unverified_account_cannot_use_the_proxy(client: TestClient, upstream: FakeUpstream) -> None:
    register(client, new_invite(client))  # logged in, email not verified

    response = post(client, AGENT_PATH, rpc("initialize", {}))

    assert response.status_code == 403
    assert response.json()["detail"] == "Email not verified"
    assert upstream.requests == []
