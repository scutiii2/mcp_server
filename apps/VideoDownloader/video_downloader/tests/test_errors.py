from __future__ import annotations

from src.errors import DownloaderError, ErrorCode


def test_to_body_has_code_and_message():
    error = DownloaderError(ErrorCode.TOO_LONG, "Too long.")
    assert error.to_body() == {"error": {"code": "too_long", "message": "Too long."}}


def test_http_status_for_every_code():
    for code in ErrorCode:
        assert 400 <= DownloaderError(code, "x").http_status <= 599


def test_specific_statuses():
    assert DownloaderError(ErrorCode.FILE_NOT_FOUND, "x").http_status == 404
    assert DownloaderError(ErrorCode.QUEUE_FULL, "x").http_status == 429
    assert DownloaderError(ErrorCode.BLOCKED_HOST, "x").http_status == 403
