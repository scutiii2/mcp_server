"""delegation.py tests: availability/description built from the
configured agent registry, the depth cap, unknown-agent handling, and
the isError -> plain-exception translation - mirroring
chat_app/tests/test_ai_agent_client.py's convention (asyncio.run() in a
plain test function, no pytest-asyncio plugin needed).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.agents import agent_registry, delegation
from src.agents.agent_spec import RosterEntry

ROSTER = [RosterEntry("calc", "Calculator", "Arithmetic."), RosterEntry("explainer", "Explainer", "Explanations.")]


def _configure_agents(monkeypatch, agents):
    monkeypatch.setattr(agent_registry, "_AGENTS", agents)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {a["id"]: a for a in agents})
    monkeypatch.setattr(agent_registry, "reload", lambda: None)


def test_tool_parameters_enumerate_the_roster():
    params = delegation.tool_parameters(ROSTER, allow_auto=False)
    assert params["properties"]["agent_id"]["enum"] == ["calc", "explainer"]
    assert params["required"] == ["agent_id", "question"]


def test_tool_parameters_offer_auto_when_allowed():
    params = delegation.tool_parameters(ROSTER, allow_auto=True)
    assert params["properties"]["agent_id"]["enum"] == ["calc", "explainer", "auto"]


def test_tool_description_lists_the_roster_and_auto():
    description = delegation.tool_description(ROSTER, allow_auto=True)
    assert "calc (Calculator): Arithmetic." in description
    assert '"auto"' in description


def test_call_resolves_auto_through_routing(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    monkeypatch.setattr("src.agents.delegation.agent_routing.resolve_auto", lambda question: ROSTER[0])

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        return {"response": "4"}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        result = delegation.call("auto", "2+2?", depth=0)

    assert result == "Delegated to calc (Calculator).\n\n4"


def test_call_raises_at_the_depth_cap_without_any_network_call(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}])

    with patch("src.agents.delegation._call_tool") as fake_call_tool:
        try:
            delegation.call("claude-agent", "hi", depth=delegation._MAX_DELEGATION_DEPTH)
            raise AssertionError("expected ValueError")
        except ValueError as error:
            assert "max delegation depth" in str(error)

    fake_call_tool.assert_not_called()


def test_call_raises_for_an_unknown_agent_id(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}])

    try:
        delegation.call("nope", "hi", depth=0)
        raise AssertionError("expected ValueError")
    except ValueError as error:
        assert "unknown agent_id 'nope'" in str(error)


def test_call_returns_the_sub_agents_response_on_success(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "openai-agent", "label": "OpenAI Agent", "url": "http://127.0.0.1:9101/mcp"}])

    captured = {}

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        captured["url"] = url
        captured["name"] = name
        captured["arguments"] = arguments
        return {"response": "the answer", "cancelled": False}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        result = delegation.call("openai-agent", "sub-question", depth=0)

    assert result == "the answer"
    assert captured["url"] == "http://127.0.0.1:9101/mcp"
    assert captured["name"] == "ask"
    assert captured["arguments"] == {
        "question": "sub-question",
        "history": [],
        "enabled_extensions": [],
        "request_id": None,
        "depth": 1,
        "approval_mode": "off",
        "delegated_by": delegation.agent_spec.current().id,
        "disabled_tools": [],
    }


def _fake_session(*, is_error: bool, content: list, structured: dict | None):
    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(isError=is_error, content=content, structuredContent=structured)
    )
    return session


def _cm(value):
    class _ACM:
        async def __aenter__(self):
            return value

        async def __aexit__(self, *args):
            return False

    return _ACM()


def test_call_tool_raises_plain_exception_on_iserror_result():
    session = _fake_session(is_error=True, content=[SimpleNamespace(text="openai is rate-limited")], structured=None)

    with patch("src.agents.delegation.streamablehttp_client", return_value=_cm((None, None, None))), \
         patch("src.agents.delegation.ClientSession", return_value=_cm(session)):
        try:
            asyncio.run(delegation._call_tool("http://127.0.0.1:9101/mcp", "ask", {}))
            raise AssertionError("expected RuntimeError")
        except RuntimeError as error:
            assert "rate-limited" in str(error)


def test_call_reports_the_delegates_agent_usage_to_the_bound_sink(monkeypatch):
    usage = [{"provider_id": "openai", "model": "gpt", "input_tokens": 5, "output_tokens": 2, "total_tokens": 7}]

    async def fake_call_tool(url, name, arguments, on_progress=None):
        return {"response": "sub-answer", "agent_usage": usage}

    monkeypatch.setattr(delegation, "_call_tool", fake_call_tool)
    monkeypatch.setattr(delegation.agent_registry, "get_agent", lambda agent_id: {"url": "http://x/mcp"})

    sink, token = delegation.bind_usage()
    try:
        assert delegation.call("other", "q", 0) == "sub-answer"
    finally:
        delegation.reset_usage(token)

    assert sink == usage


def test_call_emits_start_and_end_and_forwards_specialist_progress(monkeypatch):
    import json as _json
    from src.agents import agent_events

    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    emitted = []
    token = agent_events.bind(emitted.append, "step-7")

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        assert arguments["delegated_by"] == delegation.agent_spec.current().id
        await on_progress(0, None, _json.dumps({"type": "token", "text": "4", "agent_id": "calc", "agent_label": "Calculator"}))
        await on_progress(0, None, _json.dumps({"type": "usage", "total_tokens": 9}))
        await on_progress(0, None, "not json")
        return {"response": "4"}

    try:
        with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
            assert delegation.call("calc", "2+2?", depth=0) == "4"
    finally:
        agent_events.reset(token)

    assert [e["type"] for e in emitted] == ["agent_start", "agent_token", "agent_end"]
    start, tok, end = emitted
    assert start["agent_id"] == "calc" and start["question"] == "2+2?" and start["step_id"] == "step-7"
    assert tok["text"] == "4" and tok["step_id"] == "step-7"
    assert end["ok"] is True


def test_call_emits_a_failed_end_when_the_specialist_errors(monkeypatch):
    from src.agents import agent_events

    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    emitted = []
    token = agent_events.bind(emitted.append, "step-7")
    try:
        with patch("src.agents.delegation._call_tool", side_effect=RuntimeError("down")):
            try:
                delegation.call("calc", "2+2?", depth=0)
                raise AssertionError("expected RuntimeError")
            except RuntimeError:
                pass
    finally:
        agent_events.reset(token)

    assert emitted[-1]["type"] == "agent_end" and emitted[-1]["ok"] is False


from src.agents.agent_spec import TierInfo

TIERED = [
    RosterEntry("calc", "Calculator", "Arithmetic.", (
        TierInfo("light", "haiku", "quick sums"), TierInfo("heavy", "opus", "proofs"),
    )),
    RosterEntry("fixed", "Fixed", "One model.", (TierInfo("standard", "sonnet", "all"),)),
]


def test_tool_parameters_have_no_model_tier_when_nobody_offers_a_choice():
    assert "model_tier" not in delegation.tool_parameters(ROSTER, allow_auto=False)["properties"]
    assert "model_tier" not in delegation.tool_parameters(TIERED[1:], allow_auto=False)["properties"]


def test_tool_parameters_offer_model_tier_when_a_specialist_has_a_choice():
    prop = delegation.tool_parameters(TIERED, allow_auto=False)["properties"]["model_tier"]
    assert prop["enum"] == ["light", "standard", "heavy", "extreme"]


def test_tool_description_lists_tiers_only_for_specialists_with_a_choice():
    description = delegation.tool_description(TIERED, allow_auto=False)
    assert "calc (Calculator): Arithmetic. [model_tier: light = quick sums, heavy = proofs]" in description
    assert "fixed (Fixed): One model." in description
    assert "fixed (Fixed): One model. [" not in description
    assert "lightest model_tier" in description
    assert "lightest model_tier" not in delegation.tool_description(ROSTER, allow_auto=False)


def test_call_passes_model_tier_to_ask(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    captured = {}

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        captured["arguments"] = arguments
        return {"response": "4"}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        delegation.call("calc", "2+2?", depth=0, model_tier="light")

    assert captured["arguments"]["model_tier"] == "light"


def test_call_shows_the_orchestrator_why_a_tier_was_changed(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        return {"response": "4", "model_note": "heavy is not available for calc; ran on standard"}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        result = delegation.call("calc", "2+2?", depth=0, model_tier="heavy")

    assert result == "[heavy is not available for calc; ran on standard]\n\n4"


def test_dispatch_reads_the_tool_arguments():
    with patch("src.agents.delegation.call", return_value="answer") as fake_call:
        assert delegation.dispatch({"agent_id": "calc", "question": "q"}, 1) == "answer"
        delegation.dispatch({"agent_id": "calc", "question": "q", "model_tier": "heavy"}, 1)

    assert fake_call.call_args_list[0].args == ("calc", "q", 1)
    assert fake_call.call_args_list[0].kwargs == {}
    assert fake_call.call_args_list[1].args == ("calc", "q", 1)
    assert fake_call.call_args_list[1].kwargs == {"model_tier": "heavy"}


def test_dispatch_ignores_a_non_string_model_tier():
    with patch("src.agents.delegation.call", return_value="answer") as fake_call:
        delegation.dispatch({"agent_id": "calc", "question": "q", "model_tier": 1}, 1)

    assert fake_call.call_args.args == ("calc", "q", 1)
    assert fake_call.call_args.kwargs == {}


def test_attachment_references_survive_rewritten_delegation_and_reset(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "pdf-assistant", "label": "PDF Assistant", "url": "http://pdf/mcp"}])
    question = 'Merge these\n[[ATTACHMENT filename="scan.pdf" chars="0" truncated="false"]]\n[PDFMerger file_id: f_scan | 2 pages]\nsecret preview text\n[[/ATTACHMENT]]'
    token = delegation.bind_attachments(question, [])
    captured = []
    async def fake(url, name, arguments, on_progress=None):
        captured.append(arguments["question"])
        return {"response": "ok"}
    try:
        with patch("src.agents.delegation._call_tool", side_effect=fake):
            delegation.call("pdf-assistant", "Merge the uploaded files", 0)
        assert "f_scan" in captured[0] and "scan.pdf" in captured[0]
        assert "secret preview text" not in captured[0]
        nested = delegation.bind_attachments(captured[0], [])
        try:
            assert "f_scan" in delegation._attachments.get()
        finally:
            delegation.reset_attachments(nested)
    finally:
        delegation.reset_attachments(token)
    assert delegation._attachments.get() == ""


def test_attachment_metadata_does_not_change_auto_routing(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://calc/mcp"}])
    routed = []
    def route(question):
        routed.append(question)
        return ROSTER[0]
    monkeypatch.setattr(delegation.agent_routing, "resolve_auto", route)
    token = delegation._attachments.set("scan.pdf: [PDFMerger file_id: f_scan]")
    async def fake(url, name, arguments, on_progress=None):
        return {"response": "4"}
    try:
        with patch("src.agents.delegation._call_tool", side_effect=fake):
            delegation.call("auto", "2+2?", 0)
        assert routed == ["2+2?"]
    finally:
        delegation.reset_attachments(token)
