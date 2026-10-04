"""ChatRepl driven by a scripted line reader and a fake client."""

from __future__ import annotations

import asyncio

import pytest
from rich.console import Console

from src.api import Agent, ApiError, ChatDetail, EmberUnreachable, SessionExpired, TurnGone
from src.events import ConnectionLost
from src.repl import TOOLS_NOT_HERE, ChatRepl
from src.session import ChatSession
from tests.conftest import FakeClient, Script, api_error, final, screen, summary, token


def make_repl(client: FakeClient, console: Console, script: Script, **kwargs) -> ChatRepl:
    session = kwargs.pop("session", ChatSession(agent=client.agent_list[0]))
    return ChatRepl(client, console, script, client.agent_list, session, **kwargs)


class TestPromptLoop:
    async def test_a_question_is_sent_with_the_agent_and_the_answer_is_shown(self, client: FakeClient, console: Console) -> None:
        repl = make_repl(client, console, Script("What is up?"))

        await repl.run()

        assert [t["question"] for t in client.turns] == ["What is up?"]
        assert client.turns[0]["agent_id"] == "a1"
        assert "Hi" in screen(console)

    async def test_the_first_question_names_the_chat_and_later_ones_do_not(self, client: FakeClient, console: Console) -> None:
        repl = make_repl(client, console, Script("First   question\nwith lines", "Second"))

        await repl.run()

        assert client.turns[0]["title"] == "First question with lines"
        assert client.turns[1]["title"] is None
        assert client.turns[0]["chat_id"] == client.turns[1]["chat_id"]

    async def test_a_long_first_question_gives_a_title_of_60_characters(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("q" * 200)).run()

        assert len(client.turns[0]["title"]) == 60

    async def test_the_answer_is_watched_from_the_sequence_the_turn_returned(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("Q")).run()

        assert client.streams == [(client.turns[0]["chat_id"], 4)]

    async def test_blank_lines_are_ignored(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("", "   ", "Q")).run()

        assert len(client.turns) == 1

    async def test_ctrl_d_leaves(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script()).run()

        assert client.turns == []

    async def test_quit_leaves_without_reading_more(self, client: FakeClient, console: Console) -> None:
        script = Script("/quit", "never read")

        await make_repl(client, console, script).run()

        assert script.lines == ["never read"]

    async def test_ctrl_c_at_the_prompt_warns_and_a_second_one_leaves(self, client: FakeClient, console: Console) -> None:
        script = Script(KeyboardInterrupt, KeyboardInterrupt, "never read")

        await make_repl(client, console, script).run()

        assert "Ctrl+C again" in screen(console)
        assert script.lines == ["never read"]

    async def test_a_line_between_two_ctrl_cs_resets_the_warning(self, client: FakeClient, console: Console) -> None:
        script = Script(KeyboardInterrupt, "Q", KeyboardInterrupt, "R")

        await make_repl(client, console, script).run()

        assert [t["question"] for t in client.turns] == ["Q", "R"]  # it did not leave at the second Ctrl+C

    async def test_the_prompt_is_ascii_on_a_console_that_cannot_show_unicode(self, client: FakeClient) -> None:
        from tests.conftest import make_console

        script = Script()

        await make_repl(client, make_console("ascii"), script).run()

        assert script.prompts == ["you > "]


class TestAgentChoice:
    async def test_with_no_agent_chosen_the_picker_runs_first(self, client: FakeClient, console: Console) -> None:
        repl = ChatRepl(client, console, Script("2", "Q"), [], ChatSession())

        await repl.run()

        assert client.turns[0]["agent_id"] == "a2"
        assert "1) Agent One" in screen(console) and "2) Agent Two" in screen(console)

    async def test_a_single_agent_needs_no_question(self, client: FakeClient, console: Console) -> None:
        client.agent_list = [Agent("only", "Only Agent")]
        repl = ChatRepl(client, console, Script("Q"), [], ChatSession())

        await repl.run()

        assert client.turns[0]["agent_id"] == "only"

    async def test_a_bad_number_is_asked_again(self, client: FakeClient, console: Console) -> None:
        repl = ChatRepl(client, console, Script("9", "x", "0", "1", "Q"), [], ChatSession())

        await repl.run()

        assert client.turns[0]["agent_id"] == "a1"
        assert screen(console).count("Type a number from 1 to 2.") == 3

    async def test_no_agents_at_all_ends_with_a_hint(self, client: FakeClient, console: Console) -> None:
        client.agent_list = []

        await ChatRepl(client, console, Script("Q"), [], ChatSession()).run()

        assert client.turns == [] and "no agents" in screen(console)

    async def test_the_agent_command_switches_the_agent_and_keeps_the_chat(self, client: FakeClient, console: Console) -> None:
        repl = make_repl(client, console, Script("Q1", "/agent", "2", "Q2"))

        await repl.run()

        assert [t["agent_id"] for t in client.turns] == ["a1", "a2"]
        assert client.turns[0]["chat_id"] == client.turns[1]["chat_id"]

    async def test_enter_keeps_the_current_agent(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/agent", "", "Q")).run()

        assert client.turns[0]["agent_id"] == "a1"


class TestCommands:
    async def test_help_lists_the_commands(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/help")).run()

        out = screen(console)
        assert all(word in out for word in ("/chats", "/open", "/new", "/agent", "/ask", "/usage", "/quit"))

    async def test_an_unknown_slash_command_is_not_sent_to_the_agent(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/server list")).run()

        assert client.turns == [] and TOOLS_NOT_HERE in screen(console)

    async def test_new_starts_a_chat_with_a_new_id(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("Q1", "/new", "Q2")).run()

        assert client.turns[0]["chat_id"] != client.turns[1]["chat_id"]
        assert client.turns[1]["title"] == "Q2"

    async def test_chats_lists_them_numbered(self, client: FakeClient, console: Console) -> None:
        client.chat_list = [summary("c1", "Plan the trip"), summary("c2", "Fix the bug", running=True)]

        await make_repl(client, console, Script("/chats")).run()

        out = screen(console)
        assert "Plan the trip" in out and "Fix the bug" in out and "(answering)" in out and "Agent One" in out

    async def test_no_chats_is_said_so(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/chats")).run()

        assert "No saved chats" in screen(console)

    async def test_open_prints_the_chat_and_continues_it(self, client: FakeClient, console: Console) -> None:
        client.chat_list = [summary("c2", "Old chat", agent_id="a2")]
        client.details["c2"] = ChatDetail(summary("c2", "Old chat", agent_id="a2"),
                                          [{"role": "user", "content": "Earlier question"}, {"role": "assistant", "content": "Earlier answer"}])

        await make_repl(client, console, Script("/chats", "/open 1", "Next")).run()

        assert "Earlier question" in screen(console) and "Earlier answer" in screen(console)
        assert client.turns[0]["chat_id"] == "c2" and client.turns[0]["title"] is None
        assert client.turns[0]["agent_id"] == "a2"  # the agent that chat last used

    async def test_open_without_a_list_or_with_a_bad_number_explains(self, client: FakeClient, console: Console) -> None:
        client.chat_list = [summary("c1")]

        await make_repl(client, console, Script("/open 1", "/chats", "/open 5", "/open x")).run()

        assert screen(console).count("Use /chats first") == 3

    async def test_opening_a_chat_that_is_still_answering_joins_it(self, client: FakeClient, console: Console) -> None:
        client.chat_list = [summary("c3", "Busy", running=True)]
        client.details["c3"] = ChatDetail(summary("c3", "Busy", running=True), [{"role": "user", "content": "Q"}])
        client.events = [token("Still going."), final("Still going.")]

        await make_repl(client, console, Script("/chats", "/open 1")).run()

        assert client.streams == [("c3", 0)] and "Still going." in screen(console)

    async def test_usage_shows_both_windows(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/usage")).run()

        out = screen(console)
        assert "6 hours: 1,200 of 5,000 tokens, frees up 2026-10-03 15:00 UTC" in out
        assert "7 days: 40,000 tokens (no limit)" in out

    async def test_a_command_that_fails_is_reported_and_the_loop_goes_on(self, client: FakeClient, console: Console) -> None:
        async def broken() -> list:
            raise EmberUnreachable("Cannot reach ember_api")

        client.chats = broken  # type: ignore[method-assign]

        await make_repl(client, console, Script("/chats", "Q")).run()

        assert "Cannot reach ember_api" in screen(console) and len(client.turns) == 1


class TestAskBeforeTools:
    async def test_it_is_off_by_default_and_nothing_extra_is_sent(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("Q")).run()

        assert client.turns[0]["ask_before_tools"] is False

    async def test_the_command_switches_it(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/ask on", "Q1", "/ask off", "Q2")).run()

        assert [t["ask_before_tools"] for t in client.turns] == [True, False]

    async def test_without_an_argument_it_reports_the_state(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/ask")).run()

        assert "Asking before tools is off" in screen(console)

    async def test_the_flag_at_startup_turns_it_on(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("Q"), ask_tools=True).run()

        assert client.turns[0]["ask_before_tools"] is True

    async def test_required_for_everyone_the_cli_still_says_what_it_asks(self, client: FakeClient, console: Console) -> None:
        await make_repl(client, console, Script("/ask off"), force_approval=True).run()

        assert "requires it for everyone" in screen(console)


APPROVAL = {"sequence": 2, "type": "approval_request", "id": "step0", "tool": "tool_srv_stopApp", "label": "Stop app", "arguments": {"name": "web"}}


class TestApprovals:
    def with_request(self, client: FakeClient) -> None:
        client.events = [APPROVAL, final("Done.", 5)]

    @pytest.mark.parametrize("answer, decision", [("y", "allow"), ("YES", "allow"), ("a", "always"), ("always", "always"),
                                                  ("n", "deny"), ("", "deny"), ("maybe", "deny"), ("yy", "deny")])
    async def test_each_answer_maps_to_a_decision(self, client: FakeClient, console: Console, answer: str, decision: str) -> None:
        self.with_request(client)

        await make_repl(client, console, Script("Q", answer), ask_tools=True).run()

        assert client.decisions == [(client.turns[0]["chat_id"], "step0", decision)]

    async def test_the_card_is_shown_before_the_question(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)
        script = Script("Q", "y")

        await make_repl(client, console, script, ask_tools=True).run()

        assert "Stop app" in screen(console) and "tool_srv_stopApp" in screen(console)
        assert script.prompts[1].startswith("Allow this tool?") and "[a]lways" in script.prompts[1]

    async def test_ctrl_d_or_ctrl_c_at_the_question_denies(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)

        await make_repl(client, console, Script("Q", KeyboardInterrupt), ask_tools=True).run()

        assert client.decisions[0][2] == "deny"

    async def test_always_is_remembered_for_the_chat_and_sent_with_the_next_question(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)

        await make_repl(client, console, Script("Q1", "a", "Q2"), ask_tools=True).run()

        assert client.turns[0]["allowed_tools"] == []
        assert client.turns[1]["allowed_tools"] == ["tool_srv_stopApp"]

    async def test_a_new_chat_forgets_what_was_allowed(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)

        await make_repl(client, console, Script("Q1", "a", "/new", "Q2"), ask_tools=True).run()

        assert client.turns[1]["allowed_tools"] == []

    async def test_when_required_for_everyone_always_is_not_offered_and_means_once(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)
        script = Script("Q1", "a", "Q2")

        await make_repl(client, console, script, force_approval=True).run()

        assert "[a]lways" not in script.prompts[1]
        assert client.decisions[0][2] == "allow"
        assert client.turns[1]["allowed_tools"] is None  # nothing is pre-allowed

    async def test_a_question_that_was_already_waiting_when_the_cli_joined_comes_in_the_snapshot(self, client: FakeClient, console: Console) -> None:
        snapshot = {"sequence": 0, "type": "snapshot", "text": "", "activity": "waiting for your approval",
                    "approvals": [{"id": "step0", "tool": "tool_srv_stopApp", "label": "Stop app", "arguments": {"name": "web"}}]}
        client.events = [snapshot, final("Done.", 5)]

        await make_repl(client, console, Script("Q", "y"), ask_tools=True).run()

        assert client.decisions == [(client.turns[0]["chat_id"], "step0", "allow")]
        assert "Stop app" in screen(console)

    async def test_malformed_entries_in_a_snapshots_list_are_ignored(self, client: FakeClient, console: Console) -> None:
        good = {"id": "step0", "tool": "t", "label": "T", "arguments": {}}
        client.events = [{"sequence": 0, "type": "snapshot", "text": "", "activity": "", "approvals": ["junk", None, 5, good]},
                         final("Done.", 5)]

        await make_repl(client, console, Script("Q", "y")).run()

        assert [d[1] for d in client.decisions] == ["step0"]

    async def test_a_snapshot_with_nothing_waiting_asks_nothing(self, client: FakeClient, console: Console) -> None:
        client.events = [{"sequence": 0, "type": "snapshot", "text": "So far", "activity": "", "approvals": []}, final("So far.", 5)]

        await make_repl(client, console, Script("Q")).run()

        assert client.decisions == []

    async def test_a_question_is_not_asked_twice_when_a_reconnect_lists_it_again(self, client: FakeClient, console: Console) -> None:
        request = {"id": "step0", "tool": "t", "label": "T", "arguments": {}}
        snapshot = {"sequence": 0, "type": "snapshot", "text": "", "activity": "", "approvals": [request]}
        client.events = [snapshot, {**snapshot, "sequence": 1}, final("Done.", 5)]
        script = Script("Q", "y")

        await make_repl(client, console, script, ask_tools=True).run()

        assert len(client.decisions) == 1

    async def test_two_questions_for_different_tools_are_both_asked(self, client: FakeClient, console: Console) -> None:
        first = {"sequence": 1, "type": "approval_request", "id": "step0", "tool": "t0", "arguments": {}}
        second = {"sequence": 2, "type": "approval_request", "id": "step1", "tool": "t1", "arguments": {}}
        client.events = [first, second, final("Done.", 5)]

        await make_repl(client, console, Script("Q", "y", "n"), ask_tools=True).run()

        assert [d[1:] for d in client.decisions] == [("step0", "allow"), ("step1", "deny")]

    async def test_an_answer_that_is_too_late_is_not_an_error(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)
        client.decide_error = api_error(409, "Nothing is waiting for that answer")

        await make_repl(client, console, Script("Q", "y")).run()

        assert "Nothing is waiting" not in screen(console)

    async def test_other_failures_to_answer_are_shown(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)
        client.decide_error = api_error(502, "Agent unreachable")

        await make_repl(client, console, Script("Q", "y")).run()

        assert "Agent unreachable" in screen(console)

    async def test_a_failed_always_is_not_remembered(self, client: FakeClient, console: Console) -> None:
        self.with_request(client)
        client.decide_error = api_error(502, "x")

        await make_repl(client, console, Script("Q1", "a", "Q2"), ask_tools=True).run()

        assert client.turns[1]["allowed_tools"] == []


class TestFailures:
    @pytest.mark.parametrize("error, shown", [
        (api_error(429, "You've reached your 6-hour limit. It frees up in about 40 min."), "6-hour limit"),
        (api_error(409, "Already answering"), "Already answering"),
        (api_error(403, "Missing permission: chat.use"), "Missing permission"),
        (EmberUnreachable("Cannot reach ember_api at http://x"), "Cannot reach ember_api"),
    ])
    async def test_a_turn_that_cannot_start_shows_why_and_nothing_is_streamed(self, client: FakeClient, console: Console, error, shown: str) -> None:
        client.start_error = error

        await make_repl(client, console, Script("Q", "/help")).run()

        assert shown in screen(console) and client.streams == []

    async def test_a_failed_first_question_keeps_the_chat_new(self, client: FakeClient, console: Console) -> None:
        client.start_error = api_error(429, "limit")
        repl = make_repl(client, console, Script("Q"))

        await repl.run()

        assert repl.session.is_new is True

    async def test_an_answer_that_is_gone_says_how_to_read_it(self, client: FakeClient, console: Console) -> None:
        client.stream_error = TurnGone("gone")

        await make_repl(client, console, Script("Q")).run()

        assert "no longer running" in screen(console)

    async def test_a_lost_connection_says_the_answer_carries_on(self, client: FakeClient, console: Console) -> None:
        client.stream_error = ConnectionLost("Lost the connection to ember_api")

        await make_repl(client, console, Script("Q")).run()

        assert "carries on" in screen(console)

    async def test_an_error_event_is_shown_and_the_prompt_returns(self, client: FakeClient, console: Console) -> None:
        client.events = [{"sequence": 1, "type": "error", "message": "The agent is down"}]

        await make_repl(client, console, Script("Q", "Q again")).run()

        assert "The agent is down" in screen(console) and len(client.turns) == 2


class TestSessionEnded:
    async def test_logging_in_again_lets_the_loop_go_on(self, client: FakeClient, console: Console) -> None:
        client.start_error = SessionExpired(401, "ended")
        relogins: list[int] = []

        async def relogin() -> bool:
            relogins.append(1)
            client.start_error = None
            return True

        await make_repl(client, console, Script("Q1", "Q2"), relogin=relogin).run()

        assert relogins == [1] and [t["question"] for t in client.turns] == ["Q2"]
        assert "Logged in again" in screen(console)

    async def test_failing_to_log_in_again_leaves(self, client: FakeClient, console: Console) -> None:
        client.start_error = SessionExpired(401, "ended")
        script = Script("Q1", "never read")

        async def relogin() -> bool:
            return False

        await make_repl(client, console, script, relogin=relogin).run()

        assert script.lines == ["never read"]

    async def test_without_a_way_to_log_in_again_it_leaves(self, client: FakeClient, console: Console) -> None:
        client.start_error = SessionExpired(401, "ended")
        script = Script("Q1", "never read")

        await make_repl(client, console, script).run()

        assert script.lines == ["never read"]

    async def test_a_command_that_finds_the_session_ended_logs_in_again(self, client: FakeClient, console: Console) -> None:
        async def expired() -> list:
            raise SessionExpired(401, "ended")

        client.chats = expired  # type: ignore[method-assign]

        async def relogin() -> bool:
            return True

        await make_repl(client, console, Script("/chats", "Q"), relogin=relogin).run()

        assert "Run the command again" in screen(console) and len(client.turns) == 1

    async def test_a_session_that_ends_while_watching_logs_in_again_and_says_the_answer_carries_on(self, client: FakeClient, console: Console) -> None:
        client.stream_error = SessionExpired(401, "ended")

        async def relogin() -> bool:
            return True

        await make_repl(client, console, Script("Q"), relogin=relogin).run()

        assert "The answer carries on" in screen(console)


class TestCtrlC:
    async def test_cancelling_a_running_answer_asks_ember_api_to_stop_it_and_returns_to_the_prompt(self, client: FakeClient, console: Console) -> None:
        client.events = [token("Working")]
        client.hang_after_events = True
        repl = make_repl(client, console, Script("Q"))
        task = asyncio.create_task(repl.ask("Q"))
        await client.started.wait()
        await asyncio.sleep(0)

        task.cancel()
        await task

        assert task.cancelling() == 0  # the cancel was taken as Ctrl+C and cleared
        assert client.cancelled == [client.turns[0]["chat_id"]]
        assert "Cancelled" in screen(console) and "Working" in screen(console)

    async def test_a_failing_cancel_call_is_ignored(self, client: FakeClient, console: Console) -> None:
        client.hang_after_events = True
        client.events = []
        client.cancel_error = EmberUnreachable("down")
        repl = make_repl(client, console, Script())
        task = asyncio.create_task(repl.ask("Q"))
        await client.started.wait()

        task.cancel()
        await task

        assert "Cancelled" in screen(console)

    async def test_the_loop_goes_on_after_a_cancel(self, client: FakeClient, console: Console) -> None:
        client.hang_after_events = True
        client.events = []
        script = Script("Q1", "Q2")
        repl = make_repl(client, console, script)

        async def run_and_cancel_first() -> None:
            runner = asyncio.create_task(repl.run())
            await client.started.wait()
            client.hang_after_events = False
            client.events = [final("Second answer.")]  # what the next question gets
            runner.cancel()
            await runner

        await run_and_cancel_first()

        assert client.cancelled and len(client.turns) == 2


async def test_a_question_without_an_agent_is_not_sent(client: FakeClient, console: Console) -> None:
    repl = ChatRepl(client, console, Script(), [], ChatSession())

    await repl.ask("Q")

    assert client.turns == []
