"""/api/attachments: text from a file attached to a chat question
(chat.use). The browser folds the text into the question it sends; the
file itself is read here and discarded, never stored or passed on.

The file comes base64-encoded in JSON: every POST to ember_api is JSON
(see json_only.py), which keeps cross-site form posts out."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.deps import get_log_writer, require_permission
from src.models import Account
from src.routes.server_info import get_server_info
from src.services.log_service import LogWriter
from src.services.mcp_server_info import McpServerInfo, McpServerRefused, McpServerUnavailable
from src.services.permissions import FILES_UPLOAD
from src.services.text_extraction import MAX_FILE_BYTES, ExtractionError, extract_text_async

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

require_chat = require_permission(FILES_UPLOAD)

# base64 is 4 characters per 3 bytes.
_MAX_BASE64 = (MAX_FILE_BYTES + 2) // 3 * 4


class AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=_MAX_BASE64)


class AttachmentTextOut(BaseModel):
    filename: str
    text: str
    char_count: int
    truncated: bool


@router.post("/text")
async def attachment_text(body: AttachmentIn, _account: Account = Depends(require_chat)) -> AttachmentTextOut:
    try:
        content = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "data must be base64") from error
    # Only the last path part: a browser may send a full path.
    filename = body.filename.replace("\\", "/").rsplit("/", 1)[-1]
    try:
        extracted = await extract_text_async(filename, content)
    except ExtractionError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    return AttachmentTextOut(
        filename=extracted.filename,
        text=extracted.text,
        char_count=extracted.char_count,
        truncated=extracted.truncated,
    )


# The data tools read the whole file on mcp_server, which accepts only these.
_TABLE_SUFFIXES = (".csv", ".xlsx")


class AttachmentTableOut(BaseModel):
    table_id: str
    filename: str
    rows: int
    columns: list[str]
    sheet: str | None = None
    notes: list[str] = Field(default_factory=list)


@router.post("/table")
async def attachment_table(
    body: AttachmentIn,
    account: Account = Depends(require_chat),
    info: McpServerInfo = Depends(get_server_info),
    logs: LogWriter = Depends(get_log_writer),
) -> AttachmentTableOut:
    """Hands a .csv / .xlsx to mcp_server, which keeps the whole file as a table
    for the data tools and answers with its id. The text preview of the same
    file still comes from /text; this call is what lets the agent see all rows."""
    filename = body.filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(_TABLE_SUFFIXES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .csv and .xlsx files can be analysed.")
    try:
        content = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "data must be base64") from error
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 15 MB")
    try:
        table = await info.upload_table(account, filename, content)
    except McpServerUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "mcp_server is unreachable") from error
    except McpServerRefused as error:
        if error.status in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            # Our own token was refused: a setup fault, not something the user did.
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "mcp_server is unreachable") from error
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    await logs.action(account, "attachments.table", f"Attached '{filename}' ({len(content):,} bytes) as a table")
    return AttachmentTableOut(
        table_id=table["table_id"],
        filename=str(table.get("filename", filename)),
        rows=int(table.get("rows", 0)),
        columns=[str(name) for name in table.get("columns", [])],
        sheet=table.get("sheet"),
        notes=[str(note) for note in table.get("notes", [])],
    )
