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

from src.deps import require_permission
from src.models import Account
from src.services.permissions import CHAT_USE
from src.services.text_extraction import MAX_FILE_BYTES, ExtractionError, extract_text_async

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

require_chat = require_permission(CHAT_USE)

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
