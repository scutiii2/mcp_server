"""approvals.py: asking the user before a tool runs - the broker that waits for
answers, the `review` gate the providers call, and how both providers, the
ask()/decide() tools and delegation use it. Plain sync tests around
asyncio.run(), like the other async tests here."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src import approvals, delegation, server
from src.llm import anthropic_provider, cancellation, openai_provider
from src.llm.base_provider import ChatCancelled, ChatResult

REQUEST = "req-1"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    cancellation.clear(REQUEST)
    # A broker with a short timeout: a test that would wait for an answer
    # nobody gives ends in seconds, not the real 4 minutes.
    monkeypatch.setattr(approvals, "BROKER", approvals.ApprovalBroker(timeout=3.0, poll=0.05))
    yield
    cancellation.clear(REQUEST)


def run(coro):
    return asyncio.run(coro)


def answer_soon(decision: str, request_id: str = REQUEST, step_id: str = "s1"):
    """Answers on the next loop turn - after the waiter has registered."""
    asyncio.get_running_loop().call_soon(approvals.BROKER.decide, request_id, step_id, decision)


class Recorder:
    """An on_event that keeps every event, and can answer requests."""

    def __init__(self, decision: str | None = None) -> None:
        self.events: list[dict] = []
        self._decision = decision

    async def __call__(self, event: dict) -> None:
        self.events.append(event)
        if event["type"] == "approval_request" and self._decision:
            answer_soon(self._decision, step_id=event["id"])

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


# --- the policy ------------------------------------------------------------------


def test_a_policy_only_accepts_known_modes() -> None:
    for mode in approvals.APPROVAL_MODES:
        approvals.ApprovalPolicy(mode)
    with pytest.raises(ValueError, match="approval_mode"):
        approvals.ApprovalPolicy("sometimes")


def test_needs_approval_depends_on_mode_and_the_allowed_tools() -> None:
    assert approvals.ApprovalPolicy("off").needs_approval("tool_x") is False
    assert approvals.ApprovalPolicy("ask").needs_approval("tool_x") is True
    assert approvals.ApprovalPolicy("deny").needs_approval("tool_x") is True
    assert approvals.ApprovalPolicy("ask", {"tool_x"}).needs_approval("tool_x") is False
    assert approvals.ApprovalPolicy("ask", {"tool_x"}).needs_approval("tool_y") is True


def test_the_default_policy_asks_nothing() -> None:
    assert approvals.current().mode == "off"


def test_bind_and_reset_restore_the_previous_policy() -> None:
    token = approvals.bind(approvals.ApprovalPolicy("ask"))
    assert approvals.current().mode == "ask"

    approvals.reset(token)

    assert approvals.current().mode == "off"


# --- the broker --------------------------------------------------------------------


def test_wait_returns_the_decision() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=5, poll=0.05)
        results = []
        for decision in ("allow", "always", "deny"):
            asyncio.get_running_loop().call_soon(broker.decide, REQUEST, "s1", decision)
            results.append(await broker.wait(REQUEST, "s1"))
        return results

    assert run(scenario()) == ["allow", "always", "deny"]


def test_decide_is_false_when_nothing_is_waiting_and_only_counts_once() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=5, poll=0.05)
        before = broker.decide(REQUEST, "s1", "allow")
        waiter = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        first = broker.decide(REQUEST, "s1", "allow")
        second = broker.decide(REQUEST, "s1", "deny")
        return before, first, second, await waiter

    assert run(scenario()) == (False, True, False, "allow")


def test_decide_is_scoped_to_the_request_and_the_step() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=5, poll=0.05)
        waiter = asyncio.create_task(broker.wait("req-A", "s1"))
        await asyncio.sleep(0)
        wrong = [broker.decide("req-B", "s1", "allow"), broker.decide("req-A", "s2", "allow")]
        broker.decide("req-A", "s1", "deny")
        return wrong, await waiter

    assert run(scenario()) == ([False, False], "deny")


def test_decide_refuses_an_unknown_decision() -> None:
    with pytest.raises(ValueError, match="decision"):
        approvals.ApprovalBroker().decide(REQUEST, "s1", "maybe")


def test_wait_times_out() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=0.15, poll=0.05)
        return await broker.wait(REQUEST, "s1"), broker.pending(REQUEST)

    assert run(scenario()) == ("timeout", [])


def test_wait_ends_when_the_turn_is_cancelled() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=30, poll=0.05)
        waiter = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0.02)
        cancellation.cancel(REQUEST)
        return await asyncio.wait_for(waiter, 2)

    assert run(scenario()) == "cancelled"


def test_a_turn_already_cancelled_never_waits() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=30, poll=0.05)
        cancellation.cancel(REQUEST)
        return await asyncio.wait_for(broker.wait(REQUEST, "s1"), 1)

    assert run(scenario()) == "cancelled"


def test_pending_lists_what_is_waiting_and_forgets_it_afterwards() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=5, poll=0.05)
        waiter = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        during = broker.pending(REQUEST)
        other = broker.pending("someone-else")
        broker.decide(REQUEST, "s1", "allow")
        await waiter
        return during, other, broker.pending(REQUEST)

    assert run(scenario()) == (["s1"], [], [])


def test_a_second_wait_on_the_same_step_denies_the_first() -> None:
    async def scenario():
        broker = approvals.ApprovalBroker(timeout=5, poll=0.05)
        first = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        second = asyncio.create_task(broker.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        broker.decide(REQUEST, "s1", "allow")
        return await first, await second

    assert run(scenario()) == ("deny", "allow")


# --- review -----------------------------------------------------------------------------


def review(recorder: Recorder | None, tool: str = "tool_x", request_id: str | None = REQUEST, step_id: str = "s1"):
    return approvals.review(request_id, step_id, tool, "Tool X", {"k": "v"}, recorder)


def under(policy: approvals.ApprovalPolicy, coro_factory):
    """Runs `coro_factory()` with `policy` bound, inside one event loop."""

    async def scenario():
        token = approvals.bind(policy)
        try:
            return await coro_factory()
        finally:
            approvals.reset(token)

    return run(scenario())


def test_review_off_lets_everything_run_without_a_word() -> None:
    rec = Recorder()

    assert under(approvals.ApprovalPolicy("off"), lambda: review(rec)) is None
    assert rec.events == []


def test_review_asks_and_runs_the_tool_only_after_allow() -> None:
    rec = Recorder("allow")

    outcome = under(approvals.ApprovalPolicy("ask"), lambda: review(rec))

    assert outcome is None
    assert rec.events == [
        {"type": "approval_request", "id": "s1", "tool": "tool_x", "label": "Tool X", "arguments": {"k": "v"}},
        {"type": "approval_resolved", "id": "s1", "outcome": "allow"},
    ]


def test_review_refuses_a_denied_tool() -> None:
    rec = Recorder("deny")

    assert under(approvals.ApprovalPolicy("ask"), lambda: review(rec)) == approvals.DECLINED
    assert rec.events[-1] == {"type": "approval_resolved", "id": "s1", "outcome": "deny"}


def test_review_always_remembers_the_tool_for_the_rest_of_the_turn() -> None:
    policy = approvals.ApprovalPolicy("ask")
    rec = Recorder("always")

    async def two_calls():
        first = await review(rec, step_id="s1")
        second = await review(rec, step_id="s2")
        other = await review(rec, tool="tool_y", step_id="s3")
        return first, second, other

    assert under(policy, two_calls) == (None, None, None)
    asked = [e["tool"] for e in rec.events if e["type"] == "approval_request"]
    assert asked == ["tool_x", "tool_y"]  # the second tool_x call did not ask
    assert policy.allowed_tools == {"tool_x", "tool_y"}


def test_review_skips_tools_allowed_beforehand() -> None:
    rec = Recorder()

    assert under(approvals.ApprovalPolicy("ask", {"tool_x"}), lambda: review(rec)) is None
    assert rec.events == []


def test_review_allow_does_not_remember() -> None:
    policy = approvals.ApprovalPolicy("ask")
    rec = Recorder("allow")

    async def two_calls():
        await review(rec, step_id="s1")
        await review(rec, step_id="s2")

    under(policy, two_calls)

    assert [e["type"] for e in rec.events].count("approval_request") == 2
    assert policy.allowed_tools == set()


def test_review_timeout_refuses_the_tool_and_says_so() -> None:
    rec = Recorder()
    with patch.object(approvals, "BROKER", approvals.ApprovalBroker(timeout=0.15, poll=0.05)):
        outcome = under(approvals.ApprovalPolicy("ask"), lambda: review(rec))

    assert outcome == approvals.TIMED_OUT
    assert rec.events[-1]["outcome"] == "timeout"


def test_review_raises_chat_cancelled_and_closes_the_step_on_stop() -> None:
    rec = Recorder()

    async def scenario():
        task = asyncio.create_task(review(rec))
        await asyncio.sleep(0.05)
        cancellation.cancel(REQUEST)
        with pytest.raises(ChatCancelled):
            await asyncio.wait_for(task, 2)

    under(approvals.ApprovalPolicy("ask"), lambda: scenario())

    assert rec.types() == ["approval_request", "approval_resolved", "step_end"]
    assert rec.events[1]["outcome"] == "cancelled"
    assert rec.events[2]["ok"] is False


def test_review_fails_closed_without_a_way_to_ask() -> None:
    assert under(approvals.ApprovalPolicy("ask"), lambda: review(None)) == approvals.NO_CHANNEL
    assert under(approvals.ApprovalPolicy("ask"), lambda: review(Recorder(), request_id=None)) == approvals.NO_CHANNEL


def test_review_in_deny_mode_refuses_without_asking() -> None:
    rec = Recorder()

    assert under(approvals.ApprovalPolicy("deny"), lambda: review(rec)) == approvals.DELEGATED
    assert rec.events == []
    assert under(approvals.ApprovalPolicy("deny", {"tool_x"}), lambda: review(rec)) is None


def test_review_asks_for_delegation_like_any_other_tool() -> None:
    rec = Recorder("deny")

    outcome = under(approvals.ApprovalPolicy("ask"), lambda: review(rec, tool=delegation.TOOL_NAME))

    assert outcome == approvals.DECLINED
    assert rec.events[0]["tool"] == "delegate_to_agent"


# --- the Anthropic tool loop --------------------------------------------------------------


def _anthropic_rounds(tool_name: str = "tool_srv_stopApp"):
    tool_block = MagicMock(type="tool_use", input={"app": "web"}, id="t1")
    tool_block.name = tool_name
    first = MagicMock(stop_reason="tool_use", content=[tool_block])
    first.usage.input_tokens = 10
    first.usage.output_tokens = 5
    second = MagicMock(stop_reason="end_turn", content=[])
    second.usage.input_tokens = 3
    second.usage.output_tokens = 1

    def round_cm(chunks, final):
        async def gen():
            for chunk in chunks:
                yield chunk

        stream = MagicMock()
        stream.text_stream = gen()
        stream.get_final_message = AsyncMock(return_value=final)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=stream)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    client = MagicMock()
    client.messages.stream = MagicMock(side_effect=[round_cm([], first), round_cm(["Done"], second)])
    return client


def anthropic_turn(monkeypatch, policy, recorder, dispatch, request_id=REQUEST):
    client = _anthropic_rounds()
    monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
    monkeypatch.setattr(anthropic_provider, "_dispatch", dispatch)
    monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None: [])

    async def scenario():
        token = approvals.bind(policy)
        try:
            return await anthropic_provider.run_chat("stop it", [], request_id=request_id, on_event=recorder)
        finally:
            approvals.reset(token)

    return run(scenario()), client


def test_anthropic_runs_an_allowed_tool(monkeypatch) -> None:
    dispatch = Mock(return_value="stopped")
    rec = Recorder("allow")

    result, _ = anthropic_turn(monkeypatch, approvals.ApprovalPolicy("ask"), rec, dispatch)

    assert result.response == "Done"
    dispatch.assert_called_once_with("tool_srv_stopApp", {"app": "web"}, 0)
    # Announced, asked, answered, run - in that order.
    steps = [t for t in rec.types() if t in ("step_start", "approval_request", "approval_resolved", "step_end")]
    assert steps == ["step_start", "approval_request", "approval_resolved", "step_end"]
    assert [e for e in rec.events if e["type"] == "step_end"][0]["ok"] is True


def test_anthropic_never_runs_a_denied_tool_and_tells_the_model(monkeypatch) -> None:
    dispatch = Mock(return_value="stopped")
    rec = Recorder("deny")

    result, client = anthropic_turn(monkeypatch, approvals.ApprovalPolicy("ask"), rec, dispatch)

    dispatch.assert_not_called()
    end = [e for e in rec.events if e["type"] == "step_end"][0]
    assert (end["ok"], end["result"]) == (False, approvals.DECLINED)
    # The refusal is what the model gets as the tool's result.
    sent = client.messages.stream.call_args_list[1].kwargs["messages"][-1]["content"][0]
    assert sent["content"] == approvals.DECLINED
    assert result.tool_calls[0].result == approvals.DECLINED


def test_anthropic_with_approvals_off_runs_at_once_and_asks_nothing(monkeypatch) -> None:
    dispatch = Mock(return_value="stopped")
    rec = Recorder()

    anthropic_turn(monkeypatch, approvals.ApprovalPolicy("off"), rec, dispatch)

    dispatch.assert_called_once()
    assert "approval_request" not in rec.types()


def test_anthropic_stop_while_waiting_ends_the_turn_without_running_the_tool(monkeypatch) -> None:
    dispatch = Mock(return_value="stopped")
    rec = Recorder()

    async def stopper(event: dict) -> None:
        await rec(event)
        if event["type"] == "approval_request":
            asyncio.get_running_loop().call_later(0.05, cancellation.cancel, REQUEST)

    with pytest.raises(ChatCancelled):
        anthropic_turn(monkeypatch, approvals.ApprovalPolicy("ask"), stopper, dispatch)

    dispatch.assert_not_called()
    assert rec.types()[-1] == "step_end"


def test_anthropic_delegate_tool_is_gated_too(monkeypatch) -> None:
    dispatch = Mock(return_value="sub answer")
    client = _anthropic_rounds(tool_name=delegation.TOOL_NAME)
    monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
    monkeypatch.setattr(anthropic_provider, "_dispatch", dispatch)
    monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None: [])
    rec = Recorder("deny")

    async def scenario():
        token = approvals.bind(approvals.ApprovalPolicy("ask"))
        try:
            await anthropic_provider.run_chat("delegate", [], request_id=REQUEST, on_event=rec)
        finally:
            approvals.reset(token)

    run(scenario())

    dispatch.assert_not_called()
    assert [e["tool"] for e in rec.events if e["type"] == "approval_request"] == ["delegate_to_agent"]


# --- the OpenAI tool loop ---------------------------------------------------------------------


def _openai_client():
    def stream_cm(deltas, final):
        events = [SimpleNamespace(type="response.output_text.delta", delta=text) for text in deltas]

        async def _aiter():
            for event in events:
                yield event

        stream = MagicMock()
        stream.__aiter__ = Mock(return_value=_aiter())
        stream.get_final_response = AsyncMock(return_value=final)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=stream)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    function_call = SimpleNamespace(type="function_call", call_id="call-1", name="tool_srv_stopApp", arguments='{"app": "web"}')
    one = SimpleNamespace(usage=SimpleNamespace(total_tokens=10), output=[function_call])
    two = SimpleNamespace(usage=SimpleNamespace(total_tokens=2), output=[], output_text="Done")
    return SimpleNamespace(responses=SimpleNamespace(stream=Mock(side_effect=[stream_cm([], one), stream_cm(["Done"], two)])))


def openai_turn(monkeypatch, policy, recorder):
    monkeypatch.setenv("GPT_API_KEY", "sk-test")
    dispatch = Mock(return_value="stopped")

    async def scenario():
        token = approvals.bind(policy)
        try:
            with patch("src.llm.openai_provider._get_client", return_value=_openai_client()), \
                 patch("src.llm.openai_provider._dispatch", dispatch), \
                 patch("src.llm.openai_provider.list_tools", return_value=[]):
                return await openai_provider.run_chat("stop it", [], request_id=REQUEST, on_event=recorder)
        finally:
            approvals.reset(token)

    return run(scenario()), dispatch


def test_openai_runs_an_allowed_tool(monkeypatch) -> None:
    rec = Recorder("allow")

    result, dispatch = openai_turn(monkeypatch, approvals.ApprovalPolicy("ask"), rec)

    assert result.response == "Done"
    dispatch.assert_called_once_with("tool_srv_stopApp", {"app": "web"}, 0)
    request = [e for e in rec.events if e["type"] == "approval_request"][0]
    assert (request["id"], request["tool"], request["arguments"]) == ("call-1", "tool_srv_stopApp", {"app": "web"})


def test_openai_never_runs_a_denied_tool_and_tells_the_model(monkeypatch) -> None:
    rec = Recorder("deny")

    result, dispatch = openai_turn(monkeypatch, approvals.ApprovalPolicy("ask"), rec)

    dispatch.assert_not_called()
    assert result.tool_calls[0].result == approvals.DECLINED
    assert [e for e in rec.events if e["type"] == "step_end"][0]["ok"] is False


def test_openai_with_approvals_off_asks_nothing(monkeypatch) -> None:
    rec = Recorder()

    _, dispatch = openai_turn(monkeypatch, approvals.ApprovalPolicy("off"), rec)

    dispatch.assert_called_once()
    assert "approval_request" not in rec.types()


# --- ask() / decide() / agent_config ------------------------------------------------------------


def _result() -> ChatResult:
    return ChatResult(response="ok", provider_id="anthropic", model="m", total_tokens=1)


def test_ask_passes_the_approval_options_on() -> None:
    async def scenario():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=_result()) as run_chat, \
             patch("src.server.agent_config.status", return_value={"context_window": 1, "model": "m"}):
            await server.ask("q", request_id="r", approval_mode="ask", allowed_tools=["tool_x"])
        return run_chat.call_args.kwargs

    kwargs = run(scenario())

    assert (kwargs["approval_mode"], kwargs["allowed_tools"]) == ("ask", ["tool_x"])


def test_ask_defaults_to_no_approvals() -> None:
    async def scenario():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=_result()) as run_chat, \
             patch("src.server.agent_config.status", return_value={"context_window": 1, "model": "m"}):
            await server.ask("q")
        return run_chat.call_args.kwargs

    kwargs = run(scenario())

    assert (kwargs["approval_mode"], kwargs["allowed_tools"]) == ("off", None)


def test_run_chat_refuses_an_unknown_mode_before_starting_anything() -> None:
    from src import agent_config

    with pytest.raises(ValueError, match="approval_mode"):
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, approval_mode="whenever"))

    assert not cancellation.is_cancelled(REQUEST)


def test_run_chat_binds_the_policy_for_the_turn_and_removes_it_after() -> None:
    from src import agent_config

    seen: list[approvals.ApprovalPolicy] = []

    async def fake_provider_run_chat(*args, **kwargs):
        seen.append(approvals.current())
        return _result()

    with patch.object(agent_config._PROVIDER_MODULE, "run_chat", fake_provider_run_chat):
        run(agent_config.run_chat("q", [], [], request_id=REQUEST, approval_mode="ask", allowed_tools=["tool_x"]))

    assert (seen[0].mode, seen[0].allowed_tools) == ("ask", {"tool_x"})
    assert approvals.current().mode == "off"


def test_decide_answers_a_pending_approval() -> None:
    async def scenario():
        waiter = asyncio.create_task(approvals.BROKER.wait(REQUEST, "s1"))
        await asyncio.sleep(0)
        decided = await server.decide(REQUEST, "s1", "always")
        return decided, await waiter

    assert run(scenario()) == ({"decided": True}, "always")


def test_decide_reports_when_nothing_is_waiting() -> None:
    assert run(server.decide(REQUEST, "s1", "allow")) == {"decided": False}


def test_decide_rejects_an_unknown_decision() -> None:
    with pytest.raises(ValueError):
        run(server.decide(REQUEST, "s1", "yolo"))


# --- delegation ----------------------------------------------------------------------------------


def _delegate_and_capture(mode: str) -> dict:
    captured: dict = {}

    async def fake_call_tool(url, name, arguments):
        captured.update(arguments)
        return {"response": "sub", "cancelled": False}

    async def scenario():
        token = approvals.bind(approvals.ApprovalPolicy(mode))
        try:
            return await asyncio.to_thread(delegation.call, "claude-agent", "sub?", 0)
        finally:
            approvals.reset(token)

    with patch("src.delegation._call_tool", side_effect=fake_call_tool), \
         patch("src.delegation.agent_registry.get_agent", return_value={"url": "http://x/mcp"}):
        run(scenario())
    return captured


def test_a_delegate_of_an_asking_turn_may_not_run_tools_that_need_asking() -> None:
    assert _delegate_and_capture("ask")["approval_mode"] == "deny"
    assert _delegate_and_capture("deny")["approval_mode"] == "deny"


def test_a_delegate_of_a_turn_without_approvals_is_left_alone() -> None:
    assert _delegate_and_capture("off")["approval_mode"] == "off"
