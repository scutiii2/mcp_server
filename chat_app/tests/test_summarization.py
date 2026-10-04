"""Tests for Phase 3's on-demand summarization (see services/
summarization.py) - the fail-safe "/summarize" mechanism that replaces a
chat's stored transcript with one summary message and one cumulative
log-attachment message."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.services import chats_store as store
from src.services import summarization


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "chats.db"


def _seed_chat(db_path, messages):
    return store.save_chat(db_path, "alice", None, messages)


# --- first summarize (no prior summary) ------------------------------------


def test_summarize_chat_records_interpret_tokens_against_the_user(db_path, tmp_path):
    from src.services import usage_limits

    chat_id = _seed_chat(db_path, [{"role": "user", "content": "hi"}])
    usage_db = tmp_path / "usage.db"
    fake_result = {"response": "short summary", "model": "m", "total_tokens": 321}
    with patch.object(summarization.ai_agent_client, "interpret", return_value=fake_result):
        summarization.summarize_chat(db_path, "alice", chat_id, "http://agent", usage_db)

    assert usage_limits.get_usage(usage_db, "alice")["six_hour"]["used"] == 321


def test_summarize_chat_first_call_writes_one_summary_and_one_log_message(db_path):
    chat_id = _seed_chat(db_path, [
        {"role": "user", "content": "read /etc/config.yaml please"},
        {"role": "assistant", "content": "Sure, contents: port=8080"},
    ])

    fake_result = {"response": "User asked to read /etc/config.yaml; assistant reported port=8080.", "model": "claude-sonnet-5"}
    with patch.object(summarization.ai_agent_client, "interpret", return_value=fake_result) as fake_interpret:
        ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert ok is True
    fake_interpret.assert_called_once()
    chat = store.get_chat(db_path, "alice", chat_id)
    assert len(chat["messages"]) == 2
    assert chat["messages"][0]["kind"] == "summary"
    assert chat["messages"][0]["content"] == fake_result["response"]
    assert chat["messages"][1]["kind"] == "log_attachment"


def test_summarize_chat_preserves_exact_paths_in_the_log_attachment(db_path):
    chat_id = _seed_chat(db_path, [
        {"role": "user", "content": "read /etc/config.yaml please"},
        {"role": "assistant", "content": "Sure, contents: port=8080"},
    ])

    with patch.object(summarization.ai_agent_client, "interpret", return_value={"response": "summary", "model": "gpt-5.6-sol"}):
        summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    chat = store.get_chat(db_path, "alice", chat_id)
    log_text = chat["messages"][1]["content"]
    assert "/etc/config.yaml" in log_text
    assert "port=8080" in log_text


def test_summarize_chat_prompt_has_no_prior_summary_on_first_call(db_path):
    chat_id = _seed_chat(db_path, [{"role": "user", "content": "hi"}])

    with patch.object(summarization.ai_agent_client, "interpret", return_value={"response": "summary", "model": "gpt-5.6-sol"}) as fake_interpret:
        summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    prompt = fake_interpret.call_args.args[1]
    assert "PRIOR SUMMARY" not in prompt
    assert "hi" in prompt


# --- second summarize (folds prior summary + log) --------------------------


def test_summarize_chat_second_call_folds_prior_summary_and_covers_full_history(db_path):
    chat_id = _seed_chat(db_path, [
        {"role": "user", "content": "read /etc/config.yaml please"},
        {"role": "assistant", "content": "Sure, contents: port=8080"},
    ])
    with patch.object(summarization.ai_agent_client, "interpret", return_value={"response": "first summary", "model": "gpt-5.6-sol"}):
        summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    # New turns since the first summarize.
    chat = store.get_chat(db_path, "alice", chat_id)
    store.save_chat(db_path, "alice", chat_id, chat["messages"] + [
        {"role": "user", "content": "now also check /var/log/app.log"},
        {"role": "assistant", "content": "Found error at line 42."},
    ])

    with patch.object(
        summarization.ai_agent_client, "interpret",
        return_value={"response": "second summary", "model": "gpt-5.6-sol"},
    ) as fake_interpret:
        ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert ok is True
    prompt = fake_interpret.call_args.args[1]
    assert "PRIOR SUMMARY" in prompt
    assert "first summary" in prompt
    assert "/var/log/app.log" in prompt

    chat = store.get_chat(db_path, "alice", chat_id)
    assert len(chat["messages"]) == 2  # still exactly one summary + one log
    assert chat["messages"][0]["content"] == "second summary"
    log_text = chat["messages"][1]["content"]
    # The log covers the ENTIRE original history, not just the newest slice.
    assert "/etc/config.yaml" in log_text
    assert "/var/log/app.log" in log_text


def test_summarize_chat_with_nothing_new_since_last_summary_is_a_noop(db_path):
    chat_id = _seed_chat(db_path, [{"role": "user", "content": "hi"}])
    with patch.object(summarization.ai_agent_client, "interpret", return_value={"response": "summary", "model": "gpt-5.6-sol"}):
        summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    with patch.object(summarization.ai_agent_client, "interpret") as fake_interpret:
        ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert ok is False
    fake_interpret.assert_not_called()


# --- failure paths: transcript must stay untouched --------------------------


def test_summarize_chat_unknown_chat_raises_and_never_calls_the_agent(db_path):
    with patch.object(summarization.ai_agent_client, "interpret") as fake_interpret:
        with pytest.raises(summarization.SummarizeError):
            summarization.summarize_chat(db_path, "alice", "does-not-exist", "http://agent")
    fake_interpret.assert_not_called()


def test_summarize_chat_agent_unreachable_raises_and_leaves_transcript_untouched(db_path):
    original_messages = [{"role": "user", "content": "hi"}]
    chat_id = _seed_chat(db_path, original_messages)

    with patch.object(summarization.ai_agent_client, "interpret", side_effect=ConnectionError("no one listening")):
        with pytest.raises(summarization.SummarizeError):
            summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert store.get_chat(db_path, "alice", chat_id)["messages"] == original_messages


def test_summarize_chat_agent_tool_error_is_raised_verbatim(db_path):
    # Deliberately NOT wrapped in "Could not reach the AI agent: ..." -
    # the agent WAS reached and answered, it just declined (e.g. its
    # pinned provider is rate-limited) - script.js's
    # matchOpenRouterDailyLimit()/renderErrorMessage() need the raw
    # "Error code: 429 - {...}" shape intact to format it nicely.
    original_messages = [{"role": "user", "content": "hi"}]
    chat_id = _seed_chat(db_path, original_messages)
    raw_error = "Error code: 429 - {'error': {'message': 'daily limit', 'error_type': 'rate_limit_exceeded'}}"

    with patch.object(summarization.ai_agent_client, "interpret", side_effect=summarization.ai_agent_client.AgentToolError(raw_error)):
        with pytest.raises(summarization.SummarizeError, match=r"^Error code: 429"):
            summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert store.get_chat(db_path, "alice", chat_id)["messages"] == original_messages


def test_summarize_chat_empty_response_raises_and_leaves_transcript_untouched(db_path):
    original_messages = [{"role": "user", "content": "hi"}]
    chat_id = _seed_chat(db_path, original_messages)

    with patch.object(summarization.ai_agent_client, "interpret", return_value={"response": "   ", "model": "gpt-5.6-sol"}):
        with pytest.raises(summarization.SummarizeError):
            summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert store.get_chat(db_path, "alice", chat_id)["messages"] == original_messages


# --- cap + recompress --------------------------------------------------------


def test_summarize_chat_recompresses_when_the_summary_exceeds_the_token_cap(db_path):
    chat_id = _seed_chat(db_path, [{"role": "user", "content": "hi"}])

    responses = iter([
        {"response": "an oversized summary", "model": "gpt-5.6-sol"},
        {"response": "a shorter summary", "model": "gpt-5.6-sol"},
    ])
    with patch.object(summarization.ai_agent_client, "interpret", side_effect=lambda *a, **k: next(responses)) as fake_interpret, \
         patch.object(summarization, "count_tokens", side_effect=[summarization.SUMMARY_TOKEN_CAP + 1, 10]):
        ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert ok is True
    assert fake_interpret.call_count == 2
    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["messages"][0]["content"] == "a shorter summary"


def test_summarize_chat_keeps_the_oversized_summary_if_the_retry_itself_fails(db_path):
    chat_id = _seed_chat(db_path, [{"role": "user", "content": "hi"}])

    with patch.object(
        summarization.ai_agent_client, "interpret",
        side_effect=[{"response": "an oversized summary", "model": "gpt-5.6-sol"}, ConnectionError("down")],
    ), patch.object(summarization, "count_tokens", return_value=summarization.SUMMARY_TOKEN_CAP + 1):
        ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert ok is True
    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["messages"][0]["content"] == "an oversized summary"


# --- count_tokens ------------------------------------------------------------


def test_count_tokens_approximates_for_a_non_claude_model(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    text = "x" * 40
    assert summarization.count_tokens("gpt-5.6-sol", text) == 10


def test_count_tokens_approximates_for_claude_when_no_api_key_is_set(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    text = "x" * 40
    assert summarization.count_tokens("claude-sonnet-5", text) == 10


def test_count_tokens_uses_the_anthropic_sdk_exactly_when_a_key_is_available(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")

    class _FakeCountResult:
        input_tokens = 7

    class _FakeMessages:
        def count_tokens(self, **kwargs):
            assert kwargs["model"] == "claude-sonnet-5"
            return _FakeCountResult()

    class _FakeClient:
        def __init__(self, api_key):
            self.messages = _FakeMessages()

    with patch.object(summarization, "Anthropic", _FakeClient):
        assert summarization.count_tokens("claude-sonnet-5", "some text") == 7


def test_count_tokens_falls_back_to_approximation_if_the_anthropic_call_fails(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")

    class _FakeClient:
        def __init__(self, api_key):
            raise RuntimeError("network unreachable")

    text = "x" * 40
    with patch.object(summarization, "Anthropic", _FakeClient):
        assert summarization.count_tokens("claude-sonnet-5", text) == 10


# --- phase 6: bounded retry loop + bounded growth across repeated cycles ----


def test_summarize_chat_recompress_loop_retries_more_than_once_until_under_cap(db_path):
    # Phase 3's cap check was a single re-prompt (2 interpret calls, max).
    # Phase 6 hardens this into a real bounded loop - this exercises a
    # THIRD interpret call (two recompress retries), which the old
    # one-shot retry could never reach.
    chat_id = _seed_chat(db_path, [{"role": "user", "content": "hi"}])

    responses = iter([
        {"response": "still way too long", "model": "gpt-5.6-sol"},
        {"response": "still a bit long", "model": "gpt-5.6-sol"},
        {"response": "short enough now", "model": "gpt-5.6-sol"},
    ])
    with patch.object(summarization.ai_agent_client, "interpret", side_effect=lambda *a, **k: next(responses)) as fake_interpret, \
         patch.object(
             summarization, "count_tokens",
             side_effect=[summarization.SUMMARY_TOKEN_CAP + 100, summarization.SUMMARY_TOKEN_CAP + 1, 10],
         ):
        ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert ok is True
    assert fake_interpret.call_count == 3
    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["messages"][0]["content"] == "short enough now"
    # Each recompress prompt after the first must reference the PRIOR
    # attempt's own oversized text, not just repeat the original prompt.
    second_prompt = fake_interpret.call_args_list[1].args[1]
    assert "still way too long" in second_prompt
    third_prompt = fake_interpret.call_args_list[2].args[1]
    assert "still a bit long" in third_prompt


def test_summarize_chat_recompress_loop_is_bounded_and_keeps_the_last_attempt(db_path):
    # count_tokens NEVER reports under cap - proves the loop terminates
    # (doesn't retry forever) and keeps the last successful attempt's text
    # rather than erroring the whole summarize_chat call out.
    chat_id = _seed_chat(db_path, [{"role": "user", "content": "hi"}])

    responses = iter([
        {"response": "attempt one", "model": "gpt-5.6-sol"},
        {"response": "attempt two", "model": "gpt-5.6-sol"},
        {"response": "attempt three", "model": "gpt-5.6-sol"},
    ])
    with patch.object(summarization.ai_agent_client, "interpret", side_effect=lambda *a, **k: next(responses)) as fake_interpret, \
         patch.object(summarization, "count_tokens", return_value=summarization.SUMMARY_TOKEN_CAP + 1):
        ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

    assert ok is True
    # Initial attempt + MAX_RECOMPRESS_ATTEMPTS retries, never more.
    assert fake_interpret.call_count == 1 + summarization.MAX_RECOMPRESS_ATTEMPTS
    chat = store.get_chat(db_path, "alice", chat_id)
    assert chat["messages"][0]["content"] == "attempt three"


def test_summarize_chat_repeated_cycles_keep_summary_flat_and_log_cumulative(db_path):
    # Simulates several manual/auto-summarize cycles in a row, each
    # preceded by new turns being added - the invariant phase 6 exists to
    # verify: after EVERY cycle there is exactly one summary message at
    # the head, its token count never exceeds the cap, and the log
    # attachment always covers the complete raw history, not just the
    # newest slice.
    chat_id = _seed_chat(db_path, [
        {"role": "user", "content": "start: read /data/seed-0.txt"},
        {"role": "assistant", "content": "ok, seed-0 done"},
    ])

    seen_paths = ["/data/seed-0.txt"]
    for cycle in range(1, 6):
        path = f"/data/cycle-{cycle}.txt"
        seen_paths.append(path)
        chat = store.get_chat(db_path, "alice", chat_id)
        store.save_chat(db_path, "alice", chat_id, chat["messages"] + [
            {"role": "user", "content": f"now read {path}"},
            {"role": "assistant", "content": f"ok, cycle-{cycle} done"},
        ])

        with patch.object(
            summarization.ai_agent_client, "interpret",
            return_value={"response": f"summary through cycle {cycle}, {path} preserved", "model": "gpt-5.6-sol"},
        ):
            ok = summarization.summarize_chat(db_path, "alice", chat_id, "http://agent")

        assert ok is True
        chat = store.get_chat(db_path, "alice", chat_id)
        assert len(chat["messages"]) == 2, f"cycle {cycle}: expected exactly one summary + one log message"
        assert chat["messages"][0]["kind"] == "summary"
        summary_text = chat["messages"][0]["content"]
        assert summarization.count_tokens("gpt-5.6-sol", summary_text) <= summarization.SUMMARY_TOKEN_CAP
        log_text = chat["messages"][1]["content"]
        for seen_path in seen_paths:
            assert seen_path in log_text, f"cycle {cycle}: log_attachment lost {seen_path}"
