from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.internal_token import InternalTokenMiddleware


def make_client(token: str) -> TestClient:
    app = FastAPI()

    @app.get("/mcp")
    async def mcp():
        return {"ok": True}

    @app.get("/api/x")
    async def other():
        return {"ok": True}

    app.add_middleware(InternalTokenMiddleware, token=token)
    return TestClient(app)


def test_mcp_requires_the_token():
    client = make_client("secret")
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers={"X-Internal-Token": "wrong"}).status_code == 401
    assert client.get("/mcp", headers={"X-Internal-Token": "secret"}).status_code == 200


def test_unset_token_refuses_everything_on_mcp():
    client = make_client("")
    assert client.get("/mcp", headers={"X-Internal-Token": ""}).status_code == 401


def test_other_paths_are_open():
    assert make_client("secret").get("/api/x").status_code == 200
