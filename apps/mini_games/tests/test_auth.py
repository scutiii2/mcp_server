import asyncio

import pytest
from fastapi import HTTPException

from src.auth import InternalTokenMiddleware, load_token, requester


async def _call(token: str, path: str, headers: dict[str, str]) -> int:
    seen = {}

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        if message["type"] == "http.response.start":
            seen["status"] = message["status"]

    scope = {"type": "http", "path": path, "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    await InternalTokenMiddleware(app, token)(scope, None, send)
    return seen["status"]


def test_wrong_token_is_rejected():
    assert asyncio.run(_call("secret", "/ascension/profile", {"X-Internal-Token": "nope"})) == 401


def test_missing_token_is_rejected():
    assert asyncio.run(_call("secret", "/ascension/profile", {})) == 401


def test_right_token_passes():
    assert asyncio.run(_call("secret", "/ascension/profile", {"X-Internal-Token": "secret"})) == 200


def test_health_is_open():
    assert asyncio.run(_call("secret", "/health", {})) == 200


def test_no_token_configured_passes_everything():
    assert asyncio.run(_call("", "/ascension/profile", {})) == 200


def test_load_token_reads_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("INTERNAL_API_TOKEN=abc\n", encoding="utf-8")
    assert load_token(env) == "abc"


def test_environment_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "from-env")
    env = tmp_path / ".env"
    env.write_text("INTERNAL_API_TOKEN=abc\n", encoding="utf-8")
    assert load_token(env) == "from-env"


def test_requester_strips_and_requires_a_name():
    assert requester("  ann ") == "ann"
    with pytest.raises(HTTPException) as error:
        requester("  ")
    assert error.value.status_code == 400
