"""EmberClient against a fake ember_api (httpx's MockTransport)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from src.api import (
    Agent,
    ApiError,
    EmberClient,
    EmberUnreachable,
    SessionExpired,
    TurnGone,
    error_detail,
)

Handler = Callable[[httpx.Request], httpx.Response]


class Server:
    """Records requests and answers them with `handler`."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def client(self) -> EmberClient:
        return EmberClient("http://ember.test", transport=httpx.MockTransport(self))

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def body(self) -> dict:
        return json.loads(self.last.content)


def reply(data, status: int = 200, **headers) -> Handler:
    return lambda request: httpx.Response(status, json=data, headers=headers)


class TestLogin:
    async def test_it_posts_the_credentials_and_returns_the_account(self) -> None:
        server = Server(reply({"id": 1, "username": "ada", "email_verified": True}))

        account = await server.client().login("ada", "pw")

        assert account["username"] == "ada"
        assert (server.last.method, server.last.url.path) == ("POST", "/api/auth/login")
        assert server.body() == {"username": "ada", "password": "pw"}

    async def test_the_session_cookie_is_sent_on_later_calls(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"id": 1}, headers={"Set-Cookie": "ember_session=abc123; Path=/"})
            return httpx.Response(200, json=[])

        server = Server(handler)
        client = server.client()
        await client.login("ada", "pw")

        await client.chats()

        assert "ember_session=abc123" in server.last.headers["cookie"]

    async def test_a_wrong_password_is_an_api_error_not_an_expired_session(self) -> None:
        server = Server(reply({"detail": "Invalid username or password"}, 401))

        with pytest.raises(ApiError) as raised:
            await server.client().login("ada", "no")

        assert type(raised.value) is ApiError
        assert (raised.value.status, raised.value.detail) == (401, "Invalid username or password")

    async def test_a_lockout_carries_how_long_to_wait(self) -> None:
        server = Server(reply({"detail": "Too many failed logins. Try again in 15 minutes."}, 429, **{"Retry-After": "900"}))

        with pytest.raises(ApiError) as raised:
            await server.client().login("ada", "no")

        assert (raised.value.status, raised.value.retry_after) == (429, 900)

    async def test_it_identifies_itself(self) -> None:
        server = Server(reply({"id": 1}))

        await server.client().login("ada", "pw")

        assert server.last.headers["user-agent"].startswith("chat_cli/")


class TestErrors:
    async def test_a_401_after_login_means_the_session_ended(self) -> None:
        server = Server(reply({"detail": "Not logged in"}, 401))

        with pytest.raises(SessionExpired):
            await server.client().chats()

    @pytest.mark.parametrize("status", [403, 404, 409, 422, 500])
    async def test_other_errors_are_api_errors_with_ember_apis_message(self, status: int) -> None:
        server = Server(reply({"detail": "Because."}, status))

        with pytest.raises(ApiError) as raised:
            await server.client().chats()

        assert (raised.value.status, str(raised.value)) == (status, "Because.")

    async def test_an_unreachable_server_is_named_with_its_address(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with pytest.raises(EmberUnreachable, match="http://ember.test"):
            await Server(down).client().chats()

    def test_a_list_of_field_errors_is_shown_as_the_first_one(self) -> None:
        response = httpx.Response(422, json={"detail": [{"loc": ["body", "question"], "msg": "Field required"}]})

        assert error_detail(response) == "question: Field required"

    @pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"detail": 5}', b'{"detail": ""}'])
    def test_a_body_without_a_usable_message_falls_back_to_the_status(self, body: bytes) -> None:
        assert error_detail(httpx.Response(502, content=body)) == "ember_api answered 502"


class TestCalls:
    async def test_entry_agent(self) -> None:
        server = Server(reply({"id": "ember", "label": "Ember"}))

        assert await server.client().entry_agent() == Agent("ember", "Ember")
        assert server.last.method == "GET" and server.last.url.path == "/api/agent"

    async def test_no_entry_agent_running_is_an_api_error(self) -> None:
        server = Server(reply({"detail": "No agent is running"}, 503))

        with pytest.raises(ApiError) as caught:
            await server.client().entry_agent()
        assert caught.value.status == 503 and caught.value.detail == "No agent is running"

    async def test_chats(self) -> None:
        item = {"id": "c1", "title": "T", "agent_id": None, "message_count": 3, "created_at": "x",
                "updated_at": "2026-10-03T09:00:00", "running": True}
        chats = await Server(reply([item])).client().chats()

        assert (chats[0].id, chats[0].agent_id, chats[0].message_count, chats[0].running) == ("c1", None, 3, True)

    async def test_one_chat_with_its_messages(self) -> None:
        data = {"id": "c1", "title": "T", "agent_id": "a1", "message_count": 1, "updated_at": "u", "running": False,
                "messages": [{"role": "user", "content": "hi"}]}
        server = Server(reply(data))

        chat = await server.client().chat("c1")

        assert server.last.url.path == "/api/chats/c1"
        assert chat.messages == [{"role": "user", "content": "hi"}] and chat.summary.title == "T"

    async def test_a_new_turn_sends_the_question_agent_and_title(self) -> None:
        server = Server(reply({"chat": {}, "sequence": 7}, 202))

        sequence = await server.client().start_turn("c1", "What?", "a1", "What?")

        assert sequence == 7
        assert (server.last.method, server.last.url.path) == ("POST", "/api/chats/c1/turns")
        assert server.body() == {"question": "What?", "agent_id": "a1", "caveman": False, "enabled_extensions": [], "title": "What?"}

    async def test_a_turn_in_an_existing_chat_has_no_title(self) -> None:
        server = Server(reply({"sequence": 0}, 202))

        await server.client().start_turn("c1", "More", "a1")

        assert "title" not in server.body() and "ask_before_tools" not in server.body()

    async def test_asking_before_tools_sends_the_allowed_ones(self) -> None:
        server = Server(reply({"sequence": 0}, 202))

        await server.client().start_turn("c1", "Q", "a1", ask_before_tools=True, allowed_tools=["tool_a"])

        assert server.body()["ask_before_tools"] is True and server.body()["allowed_tools"] == ["tool_a"]

    async def test_a_reply_without_a_body_is_fine(self) -> None:
        server = Server(lambda request: httpx.Response(204))

        await server.client().cancel("c1")

    async def test_cancel(self) -> None:
        server = Server(reply({"cancelled": True}))

        await server.client().cancel("c1")

        assert (server.last.method, server.last.url.path) == ("POST", "/api/chats/c1/cancel")

    async def test_an_approval_answer_names_its_step(self) -> None:
        server = Server(reply({"decided": True}))

        await server.client().decide("c1", "step0", "allow")

        assert server.last.url.path == "/api/chats/c1/approvals"
        assert server.body() == {"step_id": "step0", "decision": "allow"}

    async def test_usage(self) -> None:
        data = {"six_hour": {"used": 5, "limit": 100, "reset_at": "2026-10-03T12:00:00"},
                "weekly": {"used": 9, "limit": 0, "reset_at": None}, "report": {}}

        usage = await Server(reply(data)).client().usage()

        assert (usage.six_hour.used, usage.six_hour.limit, usage.weekly.limit, usage.weekly.reset_at) == (5, 100, 0, None)

    @pytest.mark.parametrize("data, expected", [({"force_tool_approval": True}, True), ({"force_tool_approval": False}, False), ({}, False)])
    async def test_whether_approval_is_required(self, data, expected: bool) -> None:
        assert await Server(reply(data)).client().force_tool_approval() is expected

    async def test_a_failed_read_of_that_setting_means_not_required(self) -> None:
        assert await Server(reply({"detail": "x"}, 500)).client().force_tool_approval() is False

    async def test_leaving_never_fails(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        await Server(down).client().logout()


class TestEvents:
    def stream(self, *chunks: str, status: int = 200) -> Server:
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks:
                    yield chunk.encode()

        return Server(lambda request: httpx.Response(status, stream=Body()))

    async def collect(self, server: Server, after: int = 0) -> list[dict]:
        return [e async for e in server.client().stream_events("c1", after)]

    async def test_it_asks_for_events_after_a_sequence_as_an_event_stream(self) -> None:
        server = self.stream('data: {"sequence": 5, "type": "final"}\n\n')

        await self.collect(server, after=4)

        assert server.last.url.path == "/api/chats/c1/events"
        assert server.last.url.params["after"] == "4"
        assert server.last.headers["accept"] == "text/event-stream"

    async def test_events_come_out_in_order_even_when_split(self) -> None:
        one = 'id: 1\ndata: {"sequence": 1, "type": "token", "text": "a"}\n\n'
        two = 'id: 2\ndata: {"sequence": 2, "type": "final"}\n\n'
        server = self.stream(one[:12], one[12:] + two[:7], two[7:])

        events = await self.collect(server)

        assert [e["sequence"] for e in events] == [1, 2]

    async def test_a_404_means_there_is_no_turn(self) -> None:
        with pytest.raises(TurnGone):
            await self.collect(self.stream(status=404))

    async def test_a_401_means_the_session_ended(self) -> None:
        with pytest.raises(SessionExpired):
            await self.collect(self.stream(status=401))

    async def test_a_server_error_is_a_failed_connection(self) -> None:
        with pytest.raises(EmberUnreachable, match="500"):
            await self.collect(self.stream(status=500))

    async def test_any_other_error_status_is_a_failed_connection(self) -> None:
        with pytest.raises(EmberUnreachable, match="403"):
            await self.collect(self.stream('data: {"sequence": 1, "type": "final"}\n\n', status=403))

    async def test_a_stream_has_no_read_timeout_because_answers_can_pause_for_minutes(self) -> None:
        from src.api import STREAM_TIMEOUT

        assert STREAM_TIMEOUT.read is None

    async def test_a_network_failure_is_a_failed_connection(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadError("reset")

        with pytest.raises(EmberUnreachable):
            await self.collect(Server(down))
