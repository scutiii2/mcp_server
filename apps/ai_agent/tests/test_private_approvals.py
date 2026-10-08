"""approvals.py with ask_prefixes: a private tool asks even when approvals are off."""

from __future__ import annotations

import asyncio

import pytest

from src.core import approvals

REQUEST = "req-priv"


@pytest.fixture(autouse=True)
def short_broker(monkeypatch):
    monkeypatch.setattr(approvals, "BROKER", approvals.ApprovalBroker(timeout=3.0, poll=0.05))


def policy(mode="off", allowed=(), prefixes=("u_",)):
    return approvals.ApprovalPolicy(mode, set(allowed), ask_prefixes=prefixes)


def test_needs_approval_rules():
    assert policy().needs_approval("u_notes__search") is True
    assert policy().needs_approval("main__ping") is False
    assert policy(allowed=["u_notes__search"]).needs_approval("u_notes__search") is False
    assert policy(mode="ask").needs_approval("main__ping") is True
    assert policy(prefixes=()).needs_approval("u_notes__search") is False
    assert approvals.ApprovalPolicy().needs_approval("u_notes__search") is False


def review(pol, tool, decision=None):
    events: list[dict] = []

    async def on_event(event):
        events.append(event)

    async def answer():
        for _ in range(200):
            await asyncio.sleep(0.01)
            if approvals.BROKER.decide(REQUEST, "s1", decision):
                return

    async def go():
        token = approvals.bind(pol)
        try:
            task = asyncio.create_task(answer()) if decision else None
            outcome = await approvals.review(REQUEST, "s1", tool, None, {}, on_event)
            if task:
                await task
            return outcome
        finally:
            approvals.reset(token)

    return asyncio.run(go()), events


def test_a_private_tool_asks_under_mode_off_and_runs_after_allow():
    outcome, events = review(policy(), "u_notes__search", "allow")

    assert outcome is None
    assert [e["type"] for e in events] == ["approval_request", "approval_resolved"]


def test_a_private_tool_is_declined_when_the_user_says_no():
    outcome, _events = review(policy(), "u_notes__search", "deny")

    assert outcome == approvals.DECLINED


def test_always_allows_the_tool_for_the_rest_of_the_turn():
    pol = policy()
    outcome, _ = review(pol, "u_notes__search", "always")

    assert outcome is None
    assert "u_notes__search" in pol.allowed_tools
    assert pol.needs_approval("u_notes__search") is False


def test_a_tool_already_allowed_for_the_chat_does_not_ask():
    outcome, events = review(policy(allowed=["u_notes__search"]), "u_notes__search")

    assert outcome is None
    assert events == []


def test_a_built_in_tool_still_does_not_ask_under_mode_off():
    outcome, events = review(policy(), "main__ping")

    assert outcome is None
    assert events == []


def test_a_delegated_agent_cannot_ask_so_a_private_tool_is_refused():
    outcome, events = review(policy(mode="deny"), "u_notes__search")

    assert outcome == approvals.DELEGATED
    assert events == []


def test_once_tainted_every_tool_asks_unless_already_allowed():
    pol = approvals.ApprovalPolicy("off", {"main__ping"})
    assert pol.needs_approval("main__calc") is False

    pol.tainted = True

    assert pol.needs_approval("main__calc") is True
    assert pol.needs_approval("main__ping") is False


def test_a_tainted_built_in_tool_asks_and_runs_after_allow():
    pol = approvals.ApprovalPolicy("off")
    pol.tainted = True

    outcome, events = review(pol, "main__calc", "allow")

    assert outcome is None
    assert [e["type"] for e in events] == ["approval_request", "approval_resolved"]
