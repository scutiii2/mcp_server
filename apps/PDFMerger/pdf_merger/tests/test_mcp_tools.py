from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from src.mcp_tools.tools import build_mcp, caller_from_context
from src.service import Caller
from tests.conftest import chunks, make_pdf

WEB = Caller("web:1")


async def upload_pdf(service, tmp_path: Path, widths=(100, 101)) -> str:
    path = make_pdf(tmp_path / "a.pdf", list(widths))
    return (await service.upload(WEB, path.name, chunks(path.read_bytes()))).file_id


async def test_tools_are_listed_with_labels_and_keywords(service):
    tools = {tool.name: tool for tool in await build_mcp(service).list_tools()}

    assert set(tools) == {"tool_pdf_inspect", "tool_pdf_merge", "tool_pdf_listFiles"}
    for tool in tools.values():
        assert tool.meta["display_label"]
        assert tool.meta["keywords"]


async def test_inspect_reports_found_and_failed(service, tmp_path: Path):
    file_id = await upload_pdf(service, tmp_path)

    _, result = await build_mcp(service).call_tool("tool_pdf_inspect", {"file_ids": f"{file_id}, f_nope"})

    assert [f["file_id"] for f in result["files"]] == [file_id]
    assert result["failed"][0]["file_id"] == "f_nope"
    assert result["failed"][0]["code"] == "file_not_found"
    assert "1 of 2" in result["message"]


async def test_merge_returns_download_url(service, tmp_path: Path):
    file_id = await upload_pdf(service, tmp_path)
    plan = {"segments": [{"file_id": file_id, "pages": "2,1"}], "output": {"filename": "x.pdf"}}

    _, result = await build_mcp(service).call_tool("tool_pdf_merge", {"plan": plan})

    assert result["pages"] == 2
    assert "/download?exp=" in result["download_url"]
    assert result["message"].startswith("Merged 2 pages")


async def test_merge_error_is_a_tool_error_with_code(service, tmp_path: Path):
    file_id = await upload_pdf(service, tmp_path)

    with pytest.raises(ToolError, match="invalid_range"):
        await build_mcp(service).call_tool("tool_pdf_merge", {"plan": {"segments": [{"file_id": file_id, "pages": "9"}]}})


async def test_list_files_without_request_context_is_anonymous(service, tmp_path: Path):
    _, result = await build_mcp(service).call_tool("tool_pdf_listFiles", {})

    assert result["files"] == []


def test_caller_from_meta_then_header_then_anonymous():
    def ctx(meta_extra=None, headers=None):
        meta = SimpleNamespace(model_extra=meta_extra) if meta_extra is not None else None
        request = SimpleNamespace(headers=headers) if headers is not None else None
        return SimpleNamespace(request_context=SimpleNamespace(meta=meta, request=request))

    assert caller_from_context(ctx({"requester": {"username": "alice"}})) == Caller("mcp:alice", privileged=True)
    assert caller_from_context(ctx(None, {"x-requester-username": "bob"})) == Caller("mcp:bob", privileged=True)
    assert caller_from_context(ctx({}, {})) == Caller("mcp:anonymous", privileged=True)
