"""Requiring approval for everyone: the admin switch, and what it overrides in a turn."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.models import AppSetting, LogEntry
from src.services.settings_service import FORCE_TOOL_APPROVAL, SettingsService, UnknownSetting
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_approvals import TOOL, approve, begin, wait_for_request
from tests.test_registration import as_admin
from tests.test_turns import events, new_id, start

URL = f"/api/admin/settings/{FORCE_TOOL_APPROVAL}"


def force(client: TestClient, on: bool = True) -> None:
    assert client.put(URL, json={"value": on}).status_code == 200


def log_messages(client: TestClient, source: str) -> list[str]:
    async def read() -> list[str]:
        async with client.app.state.database.sessions() as session:
            return [row.message for row in await session.scalars(select(LogEntry).where(LogEntry.source == source))]

    return asyncio.run(read())


class TestTheSwitch:
    def test_it_is_off_by_default(self, client: TestClient) -> None:
        as_admin(client)

        assert client.get("/api/settings").json() == {FORCE_TOOL_APPROVAL: False}

    def test_reading_needs_a_login(self, client: TestClient) -> None:
        assert client.get("/api/settings").status_code == 401

    def test_an_admin_turns_it_on_and_off(self, client: TestClient) -> None:
        as_admin(client)

        force(client, True)
        assert client.get("/api/settings").json() == {FORCE_TOOL_APPROVAL: True}
        force(client, False)
        assert client.get("/api/settings").json() == {FORCE_TOOL_APPROVAL: False}

    def test_any_logged_in_account_can_read_it(self, client: TestClient, email: FakeEmailSender) -> None:
        as_admin(client)
        force(client)
        make_member(client, email)
        login(client, "alice")

        assert client.get("/api/settings").json() == {FORCE_TOOL_APPROVAL: True}

    def test_only_an_admin_can_change_it(self, client: TestClient, email: FakeEmailSender) -> None:
        as_admin(client)
        make_member(client, email)
        login(client, "alice")

        assert client.put(URL, json={"value": True}).status_code == 403
        assert client.get("/api/settings").json() == {FORCE_TOOL_APPROVAL: False}

    def test_a_logged_out_visitor_cannot_change_it(self, client: TestClient) -> None:
        assert client.put(URL, json={"value": True}).status_code == 401

    def test_an_unknown_setting_is_not_found(self, client: TestClient) -> None:
        as_admin(client)

        assert client.put("/api/admin/settings/nonsense", json={"value": True}).status_code == 404

    @pytest.mark.parametrize("value", ["yes", 1, None, [True]])
    def test_the_value_must_be_true_or_false(self, client: TestClient, value) -> None:
        as_admin(client)

        assert client.put(URL, json={"value": value}).status_code == 422

    def test_a_change_is_written_to_the_activity_log_with_the_old_value(self, client: TestClient) -> None:
        as_admin(client)

        force(client, True)
        force(client, False)

        assert log_messages(client, "admin.setting") == [
            f"{FORCE_TOOL_APPROVAL}: off -> on",
            f"{FORCE_TOOL_APPROVAL}: on -> off",
        ]

    def test_it_is_stored_in_the_database(self, client: TestClient) -> None:
        as_admin(client)
        force(client)

        async def read() -> list[tuple[str, str]]:
            async with client.app.state.database.sessions() as session:
                return [(r.name, r.value) for r in await session.scalars(select(AppSetting))]

        assert asyncio.run(read()) == [(FORCE_TOOL_APPROVAL, "1")]


class TestWhileRequired:
    def test_a_turn_asks_even_when_the_browser_says_not_to(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        chat_id = new_id()

        start(client, chat_id, "hi", ask_before_tools=False)
        events(client, chat_id)

        assert agent.asks[0]["approval_mode"] == "ask"

    def test_a_turn_asks_when_the_browser_sends_nothing_about_it(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        chat_id = new_id()

        start(client, chat_id, "hi")
        events(client, chat_id)

        assert agent.asks[0]["approval_mode"] == "ask"

    def test_tools_the_browser_pre_allowed_still_ask(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        chat_id = begin(client, agent, TOOL, allowed_tools=[TOOL])

        wait_for_request(client, chat_id)  # asked, although the browser listed it as allowed
        approve(client, chat_id)
        events(client, chat_id)

        assert agent.asks[0]["allowed_tools"] == []

    def test_a_member_is_held_to_it_too(self, client: TestClient, agent: FakeAgent, email: FakeEmailSender) -> None:
        as_admin(client)
        force(client)
        make_member(client, email)
        login(client, "alice")
        chat_id = new_id()

        start(client, chat_id, "hi")
        events(client, chat_id)

        assert agent.asks[0]["approval_mode"] == "ask"

    def test_always_means_only_this_once(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        chat_id = begin(client, agent)
        wait_for_request(client, chat_id)

        assert approve(client, chat_id, decision="always").status_code == 200

        events(client, chat_id)
        assert agent.decisions[0][2] == "allow"
        assert agent.ran == [TOOL]
        assert log_messages(client, "tool.approval") == [f'allow: "{TOOL}"']

    def test_a_refusal_is_still_a_refusal(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        chat_id = begin(client, agent)
        wait_for_request(client, chat_id)

        approve(client, chat_id, decision="deny")

        events(client, chat_id)
        assert agent.decisions[0][2] == "deny"
        assert agent.ran == []


class TestAfterItIsSwitchedOff:
    def test_the_browsers_choice_applies_again(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        force(client, False)
        chat_id = new_id()

        start(client, chat_id, "hi")
        events(client, chat_id)

        assert agent.asks[0]["approval_mode"] == "off"

    def test_always_is_passed_on_again(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        force(client, False)
        chat_id = begin(client, agent)
        wait_for_request(client, chat_id)

        approve(client, chat_id, decision="always")

        events(client, chat_id)
        assert agent.decisions[0][2] == "always"

    def test_allowed_tools_are_passed_on_again(self, client: TestClient, agent: FakeAgent) -> None:
        as_admin(client)
        force(client)
        force(client, False)
        chat_id = new_id()

        start(client, chat_id, "hi", ask_before_tools=True, allowed_tools=["tool_a"])
        events(client, chat_id)

        assert agent.asks[0]["allowed_tools"] == ["tool_a"]


class TestSettingsService:
    def test_set_returns_the_value_it_replaced(self, client: TestClient) -> None:
        async def go() -> list[bool]:
            async with client.app.state.database.sessions() as session:
                service = SettingsService(session)
                return [
                    await service.set_bool(FORCE_TOOL_APPROVAL, True),
                    await service.set_bool(FORCE_TOOL_APPROVAL, True),
                    await service.set_bool(FORCE_TOOL_APPROVAL, False),
                ]

        assert asyncio.run(go()) == [False, True, True]

    def test_an_unknown_name_is_refused(self, client: TestClient) -> None:
        async def go() -> None:
            async with client.app.state.database.sessions() as session:
                await SettingsService(session).get_bool("nonsense")

        with pytest.raises(UnknownSetting):
            asyncio.run(go())
