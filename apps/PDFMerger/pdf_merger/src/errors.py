"""Every failure a caller can see, as a code plus a plain-language message.

Routers turn MergerError into an HTTP error body; MCP tools turn it into a
ToolError. Anything else that escapes is logged and reported as
internal_error, so raw exception text never reaches a caller.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    UNSUPPORTED_TYPE = "unsupported_type"
    FILE_TOO_LARGE = "file_too_large"
    ENCRYPTED_PDF = "encrypted_pdf"
    CORRUPT_FILE = "corrupt_file"
    INVALID_RANGE = "invalid_range"
    INVALID_REQUEST = "invalid_request"
    FILE_NOT_FOUND = "file_not_found"
    JOB_NOT_FOUND = "job_not_found"
    LIMIT_EXCEEDED = "limit_exceeded"
    MERGE_TIMEOUT = "merge_timeout"
    INTERNAL = "internal_error"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNSUPPORTED_TYPE: 415,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.ENCRYPTED_PDF: 422,
    ErrorCode.CORRUPT_FILE: 422,
    ErrorCode.INVALID_RANGE: 422,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.JOB_NOT_FOUND: 404,
    ErrorCode.LIMIT_EXCEEDED: 413,
    ErrorCode.MERGE_TIMEOUT: 504,
    ErrorCode.INTERNAL: 500,
}


class MergerError(Exception):
    """An expected failure with a stable code and a message safe to show users."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS[self.code]

    def to_body(self) -> dict:
        return {"error": {"code": str(self.code), "message": self.message}}
