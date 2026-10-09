"""Live checklists survive reconnects without becoming chat history."""

from src.services.turns import Turn, _clamped
from tests.test_registration import as_admin
from tests.test_turns import events, new_id, start, wait_until


def test_plan_events_are_relayed_and_remembered(client, agent):
    as_admin(client)
    agent.events = [{"type": "plan_update", "agent_id": "calc", "agent_label": "Calculator", "items": [{"text": "Compute", "status": "in_progress"}]}]
    chat_id = new_id()
    start(client, chat_id)
    wait_until(lambda: (turn := client.app.state.turns.get(1, chat_id)) is not None and turn.status != "running")
    stream = events(client, chat_id)
    plan = next(event for event in stream if event["type"] == "plan_update")
    assert plan["items"] == [{"text": "Compute", "status": "in_progress"}]
    turn = client.app.state.turns.get(1, chat_id)
    assert turn.snapshot()["plans"][0]["agent_id"] == "calc"


def test_snapshot_replaces_each_agents_plan_independently():
    turn = Turn(account_id=1, chat_id="c", agent=None, caller=None)
    turn.record_plan({"agent_id": "main", "items": [{"text": "Inspect", "status": "pending"}]})
    turn.record_plan({"agent_id": "calc", "items": [{"text": "Compute", "status": "done"}]})
    turn.record_plan({"agent_id": "main", "items": []})
    assert turn.snapshot()["plans"] == [{"agent_id": "calc", "agent_label": "", "items": [{"text": "Compute", "status": "done"}]}]


def test_plan_payloads_are_bounded_at_the_browser_boundary():
    event = _clamped({"type": "plan_update", "items": [{"text": "x" * 900, "status": "pending"}] * 100})
    assert len(event["items"]) == 50
    assert len(event["items"][0]["text"]) == 300
    assert _clamped({"type": "plan_update", "items": [None, {"text": "x", "status": "bad"}]})["items"] == []
