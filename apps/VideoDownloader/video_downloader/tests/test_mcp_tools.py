from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from src.mcp_tools.tools import build_mcp, caller_from_context
from src.service import Caller

URL = "https://example.com/watch?v=1"


async def test_tools_are_listed_with_labels_and_keywords(service):
    tools = {tool.name: tool for tool in await build_mcp(service).list_tools()}
    assert set(tools) == {"tool_video_probe", "tool_video_download", "tool_video_status", "tool_video_listFiles"}
    for tool in tools.values():
        assert tool.meta["display_label"]
        assert tool.meta["keywords"]


async def test_probe_lists_presets(service):
    _, result = await build_mcp(service).call_tool("tool_video_probe", {"url": URL})
    assert result["title"] == "Cat video"
    assert "720p" in [o["id"] for o in result["options"]]
    assert "Cat video" in result["message"]


async def test_download_returns_job_id_immediately_then_status_reaches_done(service):
    mcp = build_mcp(service)
    _, started = await mcp.call_tool("tool_video_download", {"url": URL, "preset": "720p"})
    job_id = started["job_id"]
    assert job_id.startswith("j_")

    caller = Caller("mcp:anonymous", privileged=True)
    await service.wait(service.get_job(caller, job_id))
    _, status = await mcp.call_tool("tool_video_status", {"job_id": job_id})
    assert status["state"] == "done"
    assert "/api/files/" in status["file"]["download_url"]
    assert "download_url" in status["message"]


async def test_status_of_unknown_job_is_a_tool_error_with_code(service):
    with pytest.raises(ToolError) as error:
        await build_mcp(service).call_tool("tool_video_status", {"job_id": "j_nope"})
    assert "job_not_found" in str(error.value)


async def test_download_of_private_url_is_a_tool_error(service):
    with pytest.raises(ToolError) as error:
        await build_mcp(service).call_tool("tool_video_download", {"url": "http://127.0.0.1/x", "preset": "best"})
    assert "blocked_host" in str(error.value)


async def test_list_files_without_request_context_is_anonymous(service):
    _, result = await build_mcp(service).call_tool("tool_video_listFiles", {})
    assert result["files"] == []
    assert result["message"] == "0 file(s)."


def test_caller_from_meta_then_header_then_anonymous():
    def ctx(meta_extra=None, headers=None):
        meta = SimpleNamespace(model_extra=meta_extra) if meta_extra is not None else None
        request = SimpleNamespace(headers=headers or {}) if headers is not None else None
        return SimpleNamespace(request_context=SimpleNamespace(meta=meta, request=request))

    assert caller_from_context(ctx({"requester": {"username": "alice"}}, {"x-requester-username": "bob"})) == Caller("mcp:alice", True)
    assert caller_from_context(ctx(None, {"x-requester-username": "bob"})) == Caller("mcp:bob", True)
    assert caller_from_context(ctx(None, {})) == Caller("mcp:anonymous", True)
