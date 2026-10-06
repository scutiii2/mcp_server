"""StreamRenderer: what a turn looks like on a recording console."""

from __future__ import annotations

from rich.console import Console

from src.renderer import ASCII, UNICODE, StreamRenderer, first_line, symbols_for
from tests.conftest import final, make_console, screen, token


def draw(console: Console, events: list[dict], labels: dict[str, str] | None = None) -> str:
    renderer = StreamRenderer(console, labels)
    for event in events:
        renderer.handle(event)
    renderer.finish()
    return screen(console)


def step_start(id_: str = "s1", tool: str = "tool_srv_listApps", label: str | None = "List apps") -> dict:
    return {"sequence": 1, "type": "step_start", "id": id_, "tool": tool, "label": label, "arguments": {}}


def step_end(id_: str = "s1", ok: bool = True, result: str = "done") -> dict:
    return {"sequence": 2, "type": "step_end", "id": id_, "ok": ok, "result": result}


class TestAnswerText:
    def test_streamed_text_is_shown_once(self, console: Console) -> None:
        out = draw(console, [token("Hello "), token("there."), final("Hello there.")])

        assert out.count("Hello there.") == 1

    def test_markdown_is_rendered(self, console: Console) -> None:
        out = draw(console, [token("**bold** and `code`"), final("**bold** and `code`")])

        assert "bold and code" in out and "**" not in out

    def test_an_answer_that_was_not_streamed_is_shown_from_the_final_event(self, console: Console) -> None:
        assert "All at once." in draw(console, [final("All at once.")])

    def test_a_reset_throws_away_what_was_written_so_far(self, console: Console) -> None:
        out = draw(console, [token("first try"), {"sequence": 2, "type": "token_reset"}, token("second try"), final("second try")])

        assert "second try" in out and "first try" not in out

    def test_a_snapshot_shows_the_tool_questions_that_are_waiting(self, console: Console) -> None:
        snapshot = {"sequence": 3, "type": "snapshot", "text": "Looking.", "activity": "",
                    "approvals": [{"id": "s1", "tool": "tool_srv_stopApp", "label": "Stop app", "arguments": {"name": "web"}}]}

        out = draw(console, [snapshot])

        assert "Looking." in out and out.index("Looking.") < out.index("Stop app") and "tool_srv_stopApp" in out

    def test_malformed_entries_in_a_snapshots_list_are_ignored(self, console: Console) -> None:
        snapshot = {"sequence": 3, "type": "snapshot", "text": "Hi", "activity": "", "approvals": ["junk", None, 5]}

        out = draw(console, [snapshot])

        assert "Hi" in out and "wants to run" not in out

    def test_a_snapshot_joins_an_answer_already_under_way(self, console: Console) -> None:
        snapshot = {"sequence": 3, "type": "snapshot", "text": "So far", "activity": ""}

        out = draw(console, [snapshot, token(" and more"), final("So far and more")])

        assert out.count("So far and more") == 1


class TestTools:
    def test_a_tool_run_prints_a_line_when_it_starts_and_one_when_it_succeeds(self, console: Console) -> None:
        out = draw(console, [step_start(), step_end(), final("ok")])

        assert f"{UNICODE.running} List apps" in out and f"{UNICODE.ok} List apps" in out

    def test_a_failed_tool_shows_the_first_line_of_its_result(self, console: Console) -> None:
        out = draw(console, [step_start(), step_end(ok=False, result="\n\nNo app named x.\nApps: a, b"), final("sorry")])

        assert f"{UNICODE.failed} List apps: No app named x." in out and "Apps: a, b" not in out

    def test_a_long_reason_is_cut_to_120_characters(self) -> None:
        console = make_console()
        console.width = 400
        out = draw(console, [step_start(), step_end(ok=False, result="x" * 500), final("sorry")])

        assert "x" * 119 + "…" in out and "x" * 120 not in out

    def test_a_reason_of_exactly_120_characters_is_not_cut(self) -> None:
        console = make_console()
        console.width = 400
        out = draw(console, [step_start(), step_end(ok=False, result="x" * 120), final("sorry")])

        assert "x" * 120 in out and "…" not in out

    def test_without_a_label_the_tool_name_is_used(self, console: Console) -> None:
        out = draw(console, [step_start(label=None, tool="tool_x_do"), final("ok")])

        assert "tool_x_do" in out

    def test_text_before_and_after_a_tool_keeps_its_order_without_repeating(self, console: Console) -> None:
        events = [token("Checking."), step_start(), step_end(), token("All good."), final("Checking.All good.")]

        out = draw(console, events)

        assert out.index("Checking.") < out.index("List apps") < out.index("All good.")
        assert out.count("Checking.") == 1 and out.count("All good.") == 1

    def test_a_tool_line_starts_on_a_line_of_its_own_after_streamed_text(self, console: Console) -> None:
        out = draw(console, [token("Checking."), step_start(), step_end(), final("Checking.")])

        assert not any("Checking." in line and "List apps" in line for line in out.splitlines())

    def test_a_terminal_gets_no_extra_blank_line_after_streamed_text(self) -> None:
        import io

        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True, width=60, color_system=None, record=True)

        draw(console, [token("Checking."), step_start(), final("Checking.")])

        text = buffer.getvalue()
        after = text[text.index("Checking.") + len("Checking.") :]
        assert "\n\n" not in after.lstrip(" ")[: after.lstrip(" ").index("List apps")]

    def test_an_approval_card_names_the_tool_and_its_arguments(self, console: Console) -> None:
        card = {"sequence": 3, "type": "approval_request", "id": "s1", "tool": "tool_srv_stopApp", "label": "Stop app",
                "arguments": {"name": "web"}}

        out = draw(console, [card])

        assert "Stop app" in out and "tool_srv_stopApp" in out and '"name": "web"' in out

    def test_long_arguments_are_cut_to_600_characters(self) -> None:
        console = make_console()
        console.width = 3000
        card = {"sequence": 3, "type": "approval_request", "id": "s1", "tool": "t", "arguments": {"text": "y" * 2000}}

        out = draw(console, [card])

        line = next(ln for ln in out.splitlines() if "arguments:" in ln)
        assert len(line.strip()[len("arguments: "):]) == 600 and line.rstrip().endswith("…")


class TestEnds:
    def test_an_error_is_shown_with_its_message(self, console: Console) -> None:
        out = draw(console, [token("partial"), {"sequence": 2, "type": "error", "message": "The agent is down"}])

        assert f"{UNICODE.error} The agent is down" in out and "partial" in out

    def test_a_cancelled_answer_says_so(self, console: Console) -> None:
        event = final("Stopped early.")
        event["cancelled"] = True

        assert f"{UNICODE.cancelled} Cancelled" in draw(console, [event])

    def test_status_lines_for_summarizing_and_cancelling(self, console: Console) -> None:
        out = draw(console, [{"sequence": 1, "type": "summarizing"}, {"sequence": 2, "type": "cancelling"}])

        assert "Summarizing" in out and "Cancelling" in out

    def test_events_that_draw_nothing_do_nothing(self, console: Console) -> None:
        out = draw(console, [{"sequence": 1, "type": "usage", "total_tokens": 5, "estimated": True},
                             {"sequence": 2, "type": "approval_resolved", "id": "s1", "outcome": "allow"},
                             {"sequence": 3, "type": "step_progress", "id": "s1", "message": "50%"}])

        assert out.strip() == ""

    def test_finish_commits_text_that_was_still_live(self, console: Console) -> None:
        renderer = StreamRenderer(console)
        renderer.handle(token("cut off"))

        renderer.finish()

        assert "cut off" in screen(console)

    def test_a_second_turn_starts_clean(self, console: Console) -> None:
        renderer = StreamRenderer(console)
        for event in (token("one"), final("one")):
            renderer.handle(event)
        renderer.finish()

        for event in (final("two"),):
            renderer.handle(event)
        renderer.finish()

        assert screen(console).count("one") == 1 and "two" in screen(console)


class TestFooter:
    def footer(self, message: dict, labels: dict[str, str] | None = None, console: Console | None = None) -> str:
        return StreamRenderer(console or make_console(), labels).footer(message)

    def test_everything_present(self) -> None:
        message = {"agent": "a1", "model": "m-1", "input_tokens": 90, "output_tokens": 30, "total_tokens": 120, "duration_s": 1.25}

        assert self.footer(message, {"a1": "Agent One"}) == "Agent One · m-1 · 90/30 tokens · 1.2 s"

    def test_the_agent_id_stands_in_for_an_unknown_label(self) -> None:
        assert self.footer({"agent": "zz"}) == "zz"

    def test_only_a_total_when_there_is_no_split(self) -> None:
        assert self.footer({"total_tokens": 100}) == "100 tokens"

    def test_a_split_beats_the_total(self) -> None:
        assert self.footer({"input_tokens": 1, "output_tokens": 2, "total_tokens": 99}) == "1/2 tokens"

    def test_a_zero_split_still_counts(self) -> None:
        assert self.footer({"input_tokens": 0, "output_tokens": 0}) == "0/0 tokens"

    def test_a_duration_of_zero_is_still_shown(self) -> None:
        assert self.footer({"duration_s": 0}) == "0.0 s"

    def test_a_message_with_nothing_has_no_footer(self) -> None:
        assert self.footer({"role": "assistant", "content": "x"}) == ""

    def test_the_footer_follows_the_final_answer(self, console: Console) -> None:
        out = draw(console, [final("Hi", agent="a1")], {"a1": "Agent One"})

        assert out.index("Hi") < out.index("Agent One")

    def test_ascii_separators_on_a_console_that_cannot_show_unicode(self) -> None:
        assert self.footer({"agent": "a", "model": "m"}, console=make_console("ascii")) == "a | m"


class TestSymbols:
    def test_utf8_consoles_get_the_unicode_marks(self) -> None:
        assert symbols_for(make_console("utf-8")) is UNICODE

    def test_other_consoles_get_ascii(self) -> None:
        assert symbols_for(make_console("ascii")) is ASCII

    def test_a_tool_line_uses_the_ascii_marks_there(self) -> None:
        console = make_console("ascii")

        out = draw(console, [step_start(), step_end(), final("ok")])

        assert "[..] List apps" in out and "[ok] List apps" in out


class TestHistory:
    def test_a_saved_chat_is_printed_with_questions_and_answers(self, console: Console) -> None:
        StreamRenderer(console, {"a1": "Agent One"}).print_history([
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello", "agent": "a1", "total_tokens": 10},
        ])

        out = screen(console)
        assert f"{UNICODE.prompt}Hi" in out and "Hello" in out and "Agent One" in out

    def test_raw_logs_are_left_out_and_a_summary_is_noted(self, console: Console) -> None:
        StreamRenderer(console).print_history([
            {"role": "user", "content": "SECRET RAW", "kind": "log_attachment"},
            {"role": "assistant", "content": "digest", "kind": "summary"},
            {"role": "user", "content": "/server list", "kind": "command"},
        ])

        out = screen(console)
        assert "SECRET RAW" not in out and "digest" not in out
        assert "summarized" in out and "/server list" in out


def test_first_line() -> None:
    assert first_line("\n  \n  hello  \nworld") == "hello"
    assert first_line("") == ""
    assert first_line("x" * 10, limit=5) == "xxxx…"
