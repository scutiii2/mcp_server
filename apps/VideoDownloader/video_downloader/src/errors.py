"""Every failure a caller can see, as a code plus a plain-language message.

Routers turn DownloaderError into an HTTP error body; MCP tools turn it into a
ToolError. Anything else that escapes is logged and reported as
internal_error, so raw exception text never reaches a caller.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_URL = "invalid_url"
    BLOCKED_HOST = "blocked_host"
    TOO_LONG = "too_long"
    TOO_LARGE = "too_large"
    LIVE_STREAM = "live_stream"
    UNSUPPORTED_SITE = "unsupported_site"
    LOGIN_REQUIRED = "login_required"
    DRM_PROTECTED = "drm_protected"
    FFMPEG_MISSING = "ffmpeg_missing"
    QUEUE_FULL = "queue_full"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    EXTRACTOR_FAILED = "extractor_failed"
    LIMIT_EXCEEDED = "limit_exceeded"
    FILE_NOT_FOUND = "file_not_found"
    JOB_NOT_FOUND = "job_not_found"
    INVALID_REQUEST = "invalid_request"
    INTERNAL = "internal_error"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_URL: 422,
    ErrorCode.BLOCKED_HOST: 403,
    ErrorCode.TOO_LONG: 413,
    ErrorCode.TOO_LARGE: 413,
    ErrorCode.LIVE_STREAM: 422,
    ErrorCode.UNSUPPORTED_SITE: 422,
    ErrorCode.LOGIN_REQUIRED: 422,
    ErrorCode.DRM_PROTECTED: 422,
    ErrorCode.FFMPEG_MISSING: 503,
    ErrorCode.QUEUE_FULL: 429,
    ErrorCode.CANCELLED: 409,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.EXTRACTOR_FAILED: 502,
    ErrorCode.LIMIT_EXCEEDED: 413,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.JOB_NOT_FOUND: 404,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.INTERNAL: 500,
}


LIVE_STREAM_MESSAGE = "Live streams can't be downloaded. Try again after the stream has ended."


class DownloaderError(Exception):
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
