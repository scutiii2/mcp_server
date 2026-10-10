"""history_for_agent and render_messages with tool steps."""

import asyncio

from src.services import step_digest, summarization


def tool_step(tool="search", result="found 3"):
    return {"tool": tool, "arguments": {"q": "x"}, "ok": True, "result": result}


def answer(text, steps=None):
    message = {"role": "assistant", "content": text}
    if steps is not None:
        message["steps"] = steps
    return message


def test_history_is_unchanged_without_steps():
    history = summarization.history_for_agent(
        [
            {"role": "user", "content": "q1"},
            answer("a1"),
            {"role": "assistant", "kind": "log_attachment", "content": "raw"},
        ]
    )
    assert history == [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]


def test_an_answer_with_steps_gets_the_digest_appended():
    history = summarization.history_for_agent([{"role": "user", "content": "q"}, answer("a1", [tool_step()])])
    assert history[0] == {"role": "user", "content": "q"}
    assert history[1]["content"] == (
        "a1\n\n" + step_digest.digest([tool_step()], full=True)
    )
    assert "found 3" in history[1]["content"]


def test_local_tool_steps_add_nothing():
    history = summarization.history_for_agent([answer("a1", [tool_step("update_plan")])])
    assert history == [{"role": "assistant", "content": "a1"}]


def test_only_the_newest_tool_using_answers_get_full_lines():
    count = step_digest.RECENT_FULL_MESSAGES + 2
    messages = []
    for i in range(count):
        messages += [{"role": "user", "content": f"q{i}"}, answer(f"a{i}", [tool_step(result=f"result{i}")])]
    contents = [m["content"] for m in summarization.history_for_agent(messages) if m["role"] == "assistant"]
    older, recent = contents[:2], contents[2:]
    for i, text in enumerate(older):
        assert "Tools used: search" in text and f"result{i}" not in text
    for i, text in enumerate(recent, start=2):
        assert f"-> result{i}" in text


def test_answers_without_steps_do_not_use_up_the_recent_slots():
    messages = [answer("old", [tool_step(result="old result")])]
    messages += [answer(f"plain{i}") for i in range(10)]
    assert "old result" in summarization.history_for_agent(messages)[0]["content"]


def test_render_messages_default_ignores_steps():
    text = summarization.render_messages([{"role": "user", "content": "q"}, answer("a", [tool_step()])])
    assert text == "--- user ---\nq\n\n--- assistant ---\na\n"


def test_render_messages_can_include_steps():
    text = summarization.render_messages([answer("a", [tool_step()])], include_steps=True)
    assert text == "--- assistant ---\na\n\n" + step_digest.digest([tool_step()], full=True) + "\n"


def test_summary_prompt_sees_steps_but_the_log_does_not():
    class Gateway:
        def __init__(self):
            self.prompts = []

        async def interpret(self, url, caller, text):
            self.prompts.append(text)
            return {"response": "S", "total_tokens": 1}

    gateway = Gateway()
    messages = [{"role": "user", "content": "q"}, answer("a", [tool_step(result="secret-value-17")])]
    outcome = asyncio.run(summarization.summarize(gateway, "url", None, messages))
    assert "secret-value-17" in gateway.prompts[0]
    log = outcome.messages[1]
    assert log["kind"] == summarization.LOG_ATTACHMENT
    assert "secret-value-17" not in log["content"]
    assert "--- assistant ---\na\n" in log["content"]
