"""Tests for infra/crafty.py.

``aiohttp.ClientSession`` is mocked - these assert on what request would
be made and how a non-ok response is turned into ``CraftyError``, not on
real HTTP behavior. Same "mock at the network boundary" convention as
``test_email.py`` mocking ``smtplib.SMTP``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infra import crafty


def _session_mock(payload: dict, status: int = 200):
    """Returns (patch target, the session mock, the response mock)."""
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=payload)

    request_cm = MagicMock()
    request_cm.__aenter__ = AsyncMock(return_value=response)
    request_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.request = MagicMock(return_value=request_cm)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    session_cls = MagicMock(return_value=session)
    return session_cls, session, response


@pytest.mark.anyio
async def test_stats_gets_the_servers_stats_endpoint():
    session_cls, session, _response = _session_mock({"status": "ok", "data": {"running": True}})

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        result = await crafty.stats("https://crafty.example.com", "tok3n", "srv1")

    session.request.assert_called_once()
    method, url = session.request.call_args.args
    assert method == "GET"
    assert url == "https://crafty.example.com/api/v2/servers/srv1/stats"
    assert result == {"status": "ok", "data": {"running": True}}


@pytest.mark.anyio
async def test_authorization_header_carries_the_api_token():
    session_cls, _session, _response = _session_mock({"status": "ok", "data": {}})

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        await crafty.stats("https://crafty.example.com", "tok3n", "srv1")

    headers = session_cls.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer tok3n"


@pytest.mark.anyio
async def test_action_posts_to_the_action_endpoint():
    session_cls, session, _response = _session_mock({"status": "ok"})

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        await crafty.action("https://crafty.example.com", "tok3n", "srv1", "start_server")

    method, url = session.request.call_args.args
    assert method == "POST"
    assert url == "https://crafty.example.com/api/v2/servers/srv1/action/start_server"


@pytest.mark.anyio
async def test_unsupported_action_is_rejected_before_any_request_is_made():
    session_cls, session, _response = _session_mock({"status": "ok"})

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        with pytest.raises(ValueError, match="kill_server"):
            await crafty.action("https://crafty.example.com", "tok3n", "srv1", "kill_server")

    session.request.assert_not_called()


@pytest.mark.anyio
async def test_send_command_posts_plain_text_to_stdin():
    session_cls, session, _response = _session_mock({"status": "ok"})

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        await crafty.send_command("https://crafty.example.com", "tok3n", "srv1", "say hello")

    method, url = session.request.call_args.args
    kwargs = session.request.call_args.kwargs
    assert method == "POST"
    assert url == "https://crafty.example.com/api/v2/servers/srv1/stdin"
    assert kwargs["data"] == "say hello"
    assert kwargs["headers"]["Content-Type"] == "text/plain"


@pytest.mark.anyio
async def test_a_non_ok_status_field_raises_crafty_error_with_the_message():
    session_cls, _session, _response = _session_mock({"status": "error", "error": "Server not found"})

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        with pytest.raises(crafty.CraftyError, match="Server not found"):
            await crafty.stats("https://crafty.example.com", "tok3n", "srv1")


@pytest.mark.anyio
async def test_a_connection_failure_raises_a_recoverable_crafty_error():
    import aiohttp

    session_cls, session, _response = _session_mock({"status": "ok"})
    session.request.side_effect = aiohttp.ClientConnectionError("refused")

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        with pytest.raises(crafty.CraftyError, match="Could not reach Crafty"):
            await crafty.stats("https://crafty.example.com", "tok3n", "srv1")


# --- ping ------------------------------------------------------------------


def _get_mock(status: int = 200):
    """Returns (patch target, the session mock, the response mock) - same
    shape as _session_mock, but for session.get() (ping has no method/path
    to route and no JSON envelope to parse - it just wants an answer)."""
    response = MagicMock()
    response.status = status

    request_cm = MagicMock()
    request_cm.__aenter__ = AsyncMock(return_value=response)
    request_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=request_cm)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    session_cls = MagicMock(return_value=session)
    return session_cls, session, response


@pytest.mark.anyio
async def test_ping_reports_reachable_for_a_200_response():
    session_cls, session, _response = _get_mock(status=200)

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        result = await crafty.ping("https://crafty.example.com")

    session.get.assert_called_once_with("https://crafty.example.com")
    assert result.reachable is True
    assert result.status_code == 200
    assert result.error is None


@pytest.mark.anyio
async def test_ping_reports_reachable_even_for_an_unauthorized_response():
    """A 401 still proves something answered - that's the question this
    asks. Whether the token is any good is a separate question from
    whether the instance is reachable at all."""
    session_cls, _session, _response = _get_mock(status=401)

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        result = await crafty.ping("https://crafty.example.com")

    assert result.reachable is True
    assert result.status_code == 401


@pytest.mark.anyio
async def test_ping_strips_a_trailing_slash_from_base_url():
    session_cls, session, _response = _get_mock()

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        await crafty.ping("https://crafty.example.com/")

    session.get.assert_called_once_with("https://crafty.example.com")


@pytest.mark.anyio
async def test_ping_reports_unreachable_on_a_connection_error():
    import aiohttp

    session_cls, session, _response = _get_mock()
    session.get.side_effect = aiohttp.ClientConnectionError("Connection refused")

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        result = await crafty.ping("https://crafty.example.com")

    assert result.reachable is False
    assert result.status_code is None
    assert "refused" in result.error
    assert result.latency_ms is None


@pytest.mark.anyio
async def test_ping_reports_unreachable_on_timeout():
    session_cls, session, _response = _get_mock()
    session.get.side_effect = TimeoutError()

    with patch("src.infra.crafty.aiohttp.ClientSession", session_cls):
        result = await crafty.ping("https://crafty.example.com", timeout=1.0)

    assert result.reachable is False
    assert "1.0" in result.error or "timed out" in result.error.lower()
