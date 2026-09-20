from types import SimpleNamespace

from src import mcp_upstream


def test_tool_description_unchanged_without_flag():
    tool = SimpleNamespace(description="Does a thing.", meta={"keywords": ["x"]})
    assert mcp_upstream.tool_description(tool) == "Does a thing."


def test_tool_description_appends_explain_note_when_flagged():
    tool = SimpleNamespace(description="Does a thing.", meta={"ai_explain_result": True})
    result = mcp_upstream.tool_description(tool)
    assert result.startswith("Does a thing.")
    assert "explain the result to the user" in result


def test_tool_description_handles_missing_meta_and_description():
    tool = SimpleNamespace(description=None, meta=None)
    assert mcp_upstream.tool_description(tool) == ""
