"""MCP tools: thin glue over DownloadService. No logic and no AI calls here.

Who is asking comes from the request's _meta.requester (set by ai_agent and
forwarded by mcp_server), else the X-Requester-Username header, else
"anonymous". It is never a tool parameter, so a model cannot pick it.

No tool waits for a download: start_download returns a job ID at once and the
agent polls tool_video_status, staying under the ~120 s client limit.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from src.errors import DownloaderError
from src.mcp_tools.contract import DownloadStarted, ListFilesResult, ProbeToolResult, StatusToolResult
from src.service import Caller, DownloadService

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


def _tool_error(error: DownloaderError) -> ToolError:
    return ToolError(f"{error.code}: {error.message}")


def build_mcp(service: DownloadService) -> FastMCP:
    # The internal token protects /mcp, so DNS-rebinding host checks would only
    # block legitimate LAN callers that reach this server by IP.
    mcp = FastMCP(
        "video_downloader",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(meta={"keywords": ["video", "youtube", "tiktok", "download", "link", "info"], "display_label": "Checking video link"})
    async def tool_video_probe(url: Annotated[str, Field(description="Link to a single video page (http or https).")]) -> ProbeToolResult:
        """Look up a video link: title, duration, uploader and the quality presets it offers.

        Each option has an id (best, 1080p, 720p, 480p, audio-mp3, audio-m4a), an
        estimated size and, when blocked, a reason (too long, too large). Call this
        before tool_video_download so you only request a preset that is not blocked.
        Playlist links are refused; give the link of one video.
        """
        try:
            result = await service.probe(url)
        except DownloaderError as error:
            raise _tool_error(error) from error
        return ProbeToolResult(**result.model_dump(), message=f"{result.title}: {len(result.options)} quality option(s).")

    @mcp.tool(meta={"keywords": ["video", "audio", "download", "mp3", "mp4", "youtube", "tiktok"], "display_label": "Starting download"})
    async def tool_video_download(
        url: Annotated[str, Field(description="Link to a single video page (http or https).")],
        preset: Annotated[str, Field(description="Quality id from tool_video_probe, e.g. best, 720p, audio-mp3.")],
        ctx: Context,
    ) -> DownloadStarted:
        """Start downloading a video or its audio. Returns a job_id at once; it does not wait.

        Then call tool_video_status with the job_id every few seconds until its state is
        "done" (or "error"). Only download content the user has the right to download.
        """
        try:
            job = await service.start_download(caller_from_context(ctx), url, preset)
        except DownloaderError as error:
            raise _tool_error(error) from error
        return DownloadStarted(job_id=job.id, message=f"Download started. Check tool_video_status with job_id {job.id}.")

    @mcp.tool(meta={"keywords": ["video", "download", "status", "progress", "job"], "display_label": "Checking download"})
    async def tool_video_status(job_id: Annotated[str, Field(description="The job_id from tool_video_download.")], ctx: Context) -> StatusToolResult:
        """Progress of a download job. State is queued, downloading, processing, done or error.

        When done, `file.download_url` is a link valid for about an hour: give it to the
        user. When error, `error.code` and `error.message` say what went wrong.
        """
        try:
            status = service.job_status(caller_from_context(ctx), job_id)
        except DownloaderError as error:
            raise _tool_error(error) from error
        if status.state == "done" and status.file:
            message = f"Done: {status.file.name}. Give the user this download_url: {status.file.download_url}"
        elif status.state == "error" and status.error:
            message = f"Failed ({status.error.code}): {status.error.message}"
        else:
            percent = f" {status.percent:.0f}%" if status.percent is not None else ""
            message = f"State: {status.state}{percent}."
        return StatusToolResult(**status.model_dump(), message=message)

    @mcp.tool(meta={"keywords": ["video", "files", "list", "downloads"], "display_label": "Listing downloads"})
    async def tool_video_listFiles(ctx: Context) -> ListFilesResult:
        """List files this assistant session has downloaded, with fresh download links and expiry.

        Files downloaded in the web app belong to the browser and are not listed here.
        """
        caller = caller_from_context(ctx)
        files = [service.file_info(f) for f in service.list_files(caller)]
        return ListFilesResult(files=files, message=f"{len(files)} file(s).")

    return mcp
