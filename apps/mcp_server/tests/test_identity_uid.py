"""current_uid(): read from the header or _meta.requester, like the username."""

from __future__ import annotations

import pytest
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from mcp.types import RequestParams
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.services import extensions, identity_context
from src.services.identity_context import IdentityContextMiddleware


@pytest.fixture
def mcp_request_meta():
    tokens = []

    def bind(meta: dict | None) -> None:
        context = RequestContext(
            request_id=1,
            meta=RequestParams.Meta(**meta) if meta is not None else None,
            session=None,
            lifespan_context=None,
        )
        tokens.append(request_ctx.set(context))

    yield bind
    for token in reversed(tokens):
        request_ctx.reset(token)


def test_the_uid_falls_back_to_request_meta(mcp_request_meta):
    mcp_request_meta({"requester": {"username": "alice", "uid": "u-1"}})
    assert identity_context.current_uid() == "u-1"


def test_the_uid_is_empty_without_meta_or_with_odd_meta(mcp_request_meta):
    assert identity_context.current_uid() == ""
    mcp_request_meta(None)
    assert identity_context.current_uid() == ""
    mcp_request_meta({"requester": {"uid": 7}})
    assert identity_context.current_uid() == ""


def test_the_header_wins_over_meta_and_is_scoped_to_one_request(mcp_request_meta):
    async def whoami(request):
        return JSONResponse({"uid": identity_context.current_uid(), "username": identity_context.current_username()})

    app = Starlette(routes=[Route("/who", whoami)])
    app.add_middleware(IdentityContextMiddleware)
    client = TestClient(app)
    mcp_request_meta({"requester": {"uid": "from-meta"}})

    sent = client.get("/who", headers={"X-Requester-Uid": "abc123", "X-Requester-Username": "alice"})
    assert sent.json() == {"uid": "abc123", "username": "alice"}
    # No header: the middleware sets nothing, so the meta fallback applies again.
    assert client.get("/who").json()["uid"] == "from-meta"


def test_the_uid_is_never_forwarded_to_extensions(monkeypatch):
    monkeypatch.setattr(extensions, "current_username", lambda: "alice")
    monkeypatch.setattr(extensions, "current_email", lambda: "alice@example.com")
    token = identity_context._uid.set("secret-uid")
    try:
        meta = extensions._requester_meta()
    finally:
        identity_context._uid.reset(token)
    assert meta == {"requester": {"username": "alice", "email": "alice@example.com"}}
