"""MCP tools: thin glue over MergeService. No logic and no AI calls here.

Who is asking comes from the request's _meta.requester (set by ai_agent and
forwarded by mcp_server), else the X-Requester-Username header, else
"anonymous". It is never a tool parameter, so a model cannot pick it.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from src.errors import MergerError
from src.mcp_tools.contract import FailedItem, InspectResult, ListFilesResult, MergeToolResult
from src.models import FileInfo, MergePlan
from src.service import Caller, MergeService

REQUESTER_META_KEY = "requester"


def caller_from_context(ctx: Any) -> Caller:
    username = ""
    try:
        request_context = ctx.request_context
    except (ValueError, LookupError):
        request_context = None  # called outside an MCP request (tests, direct calls)
    if request_context is not None:
        meta = getattr(request_context, "meta", None)
        requester = (getattr(meta, "model_extra", None) or {}).get(REQUESTER_META_KEY) if meta is not None else None
        if isinstance(requester, dict) and isinstance(requester.get("username"), str):
            username = requester["username"]
        request = getattr(request_context, "request", None)
        if not username and request is not None:
            username = request.headers.get("x-requester-username", "")
    return Caller(session=f"mcp:{username.strip() or 'anonymous'}", privileged=True)


def _tool_error(error: MergerError) -> ToolError:
    return ToolError(f"{error.code}: {error.message}")


def build_mcp(service: MergeService) -> FastMCP:
    # The internal token protects /mcp, so DNS-rebinding host checks would only
    # block legitimate LAN callers that reach this server by IP.
    mcp = FastMCP(
        "pdf_merger",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(meta={"keywords": ["pdf", "inspect", "pages", "file", "info"], "display_label": "Inspecting files"})
    async def tool_pdf_inspect(
        file_ids: Annotated[str, Field(description="Comma-separated file IDs (f_...) the user gave you.")],
        ctx: Context,
    ) -> InspectResult:
        """Look up uploaded files: name, kind (pdf or image), page count, size and expiry.

        Call this before tool_pdf_merge so you know each PDF's page count when
        choosing page ranges. File IDs come from the user (the PDF merger web
        app has a "Copy ID" button). Never invent an ID.
        """
        files, failed = service.inspect(caller_from_context(ctx), [i.strip() for i in file_ids.split(",") if i.strip()])
        return InspectResult(
            files=[FileInfo.of(f) for f in files],
            failed=[FailedItem(file_id=i, code=str(e.code), message=e.message) for i, e in failed],
            message=f"Found {len(files)} of {len(files) + len(failed)} file(s).",
        )

    @mcp.tool(meta={"keywords": ["pdf", "merge", "combine", "join", "images"], "display_label": "Merging files"})
    async def tool_pdf_merge(
        plan: Annotated[MergePlan, Field(description="Ordered segments plus output options.")],
        ctx: Context,
    ) -> MergeToolResult:
        """Merge PDFs and images into one PDF, in segment order.

        Each segment takes pages from one file ("1-3,7", 1-based; null = all).
        Use several segments of the same file to interleave pages. Each page may
        appear once. Images become one page each, laid out by output.image_*.
        Returns a download link valid for about an hour and the new file's ID,
        which can be merged again. Run tool_pdf_inspect first.
        """
        try:
            result = await service.merge_and_wait(caller_from_context(ctx), plan)
        except MergerError as error:
            raise _tool_error(error) from error
        return MergeToolResult(**result.model_dump(), message=f"Merged {result.pages} pages into {result.name}.")

    @mcp.tool(meta={"keywords": ["pdf", "files", "list", "uploads"], "display_label": "Listing files"})
    async def tool_pdf_listFiles(ctx: Context) -> ListFilesResult:
        """List files this assistant session has uploaded or produced, with expiry.

        Files uploaded in the web app belong to the browser and are not listed
        here; ask the user for their IDs instead.
        """
        files = service.list_files(caller_from_context(ctx))
        return ListFilesResult(files=[FileInfo.of(f) for f in files], message=f"{len(files)} file(s).")

    return mcp
