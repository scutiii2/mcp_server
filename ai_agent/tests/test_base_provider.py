from src.llm.base_provider import step_event


def test_step_event_stamps_type():
    event = step_event("step_start", id="1", tool="x", arguments={})
    assert event == {"type": "step_start", "id": "1", "tool": "x", "arguments": {}}
