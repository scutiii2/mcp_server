"""Login and the command line."""

from __future__ import annotations

import pytest
from rich.console import Console

from src.api import ApiError, EmberUnreachable
from src.main import authenticate, build_parser
from tests.conftest import Script, screen


class FakeLogin:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.tried: list[tuple[str, str]] = []

    async def login(self, username: str, password: str) -> dict:
        self.tried.append((username, password))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


OK = {"id": 1, "username": "ada", "email_verified": True}


class TestAuthenticate:
    async def test_the_right_password_logs_in(self, console: Console) -> None:
        client = FakeLogin(OK)
        script = Script("pw")

        assert await authenticate(client, "ada", script, console) is True

        assert client.tried == [("ada", "pw")] and script.prompts == ["Password for ada: "]

    async def test_a_wrong_password_is_asked_again_up_to_three_times(self, console: Console) -> None:
        wrong = ApiError(401, "Invalid username or password")
        client = FakeLogin(wrong, wrong, OK)

        assert await authenticate(client, "ada", Script("a", "b", "c"), console) is True

        assert [p for _, p in client.tried] == ["a", "b", "c"]
        assert screen(console).count("Try again.") == 2

    async def test_three_wrong_passwords_give_up(self, console: Console) -> None:
        wrong = ApiError(401, "Invalid username or password")
        client = FakeLogin(wrong, wrong, wrong, OK)

        assert await authenticate(client, "ada", Script("a", "b", "c", "d"), console) is False

        assert len(client.tried) == 3
        out = screen(console)
        assert out.count("Invalid username or password") == 3 and out.count("Try again.") == 2

    async def test_a_lockout_stops_at_once_and_shows_its_message(self, console: Console) -> None:
        client = FakeLogin(ApiError(429, "Too many failed logins. Try again in 15 minutes.", 900), OK)

        assert await authenticate(client, "ada", Script("a", "b"), console) is False

        assert len(client.tried) == 1 and "Try again in 15 minutes" in screen(console)

    async def test_an_unreachable_server_stops_at_once(self, console: Console) -> None:
        client = FakeLogin(EmberUnreachable("Cannot reach ember_api at http://x"), OK)

        assert await authenticate(client, "ada", Script("a", "b"), console) is False

        assert len(client.tried) == 1 and "Cannot reach" in screen(console)

    async def test_an_unverified_email_cannot_chat(self, console: Console) -> None:
        client = FakeLogin({"id": 1, "email_verified": False})

        assert await authenticate(client, "ada", Script("pw"), console) is False

        assert "not verified" in screen(console)

    @pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
    async def test_ctrl_d_or_ctrl_c_at_the_password_gives_up_without_trying(self, console: Console, interruption) -> None:
        client = FakeLogin(OK)

        assert await authenticate(client, "ada", Script(interruption), console) is False

        assert client.tried == []

    async def test_the_number_of_tries_can_be_set(self, console: Console) -> None:
        wrong = ApiError(401, "no")
        client = FakeLogin(wrong, wrong)

        assert await authenticate(client, "ada", Script("a", "b"), console, tries=2) is False

        assert len(client.tried) == 2

    async def test_the_password_is_never_shown(self, console: Console) -> None:
        await authenticate(FakeLogin(OK), "ada", Script("hunter2"), console)

        assert "hunter2" not in screen(console)


class TestCommandLine:
    def test_every_option_is_optional(self) -> None:
        args = build_parser().parse_args([])

        assert (args.url, args.user, args.ask) == (None, None, False)

    def test_options(self) -> None:
        args = build_parser().parse_args(["--url", "http://x:1", "--user", "ada", "--ask"])

        assert (args.url, args.user, args.ask) == ("http://x:1", "ada", True)

    def test_there_is_no_password_option(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--password", "x"])

    def test_there_is_no_agent_option(self) -> None:
        # Every question goes to ember_api's entry agent, so there is nothing to pick.
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--agent", "a1"])
