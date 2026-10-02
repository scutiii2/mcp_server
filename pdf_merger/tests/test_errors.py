from __future__ import annotations

from src.errors import ErrorCode, MergerError


def test_error_body_and_status():
    error = MergerError(ErrorCode.INVALID_RANGE, "Pages go from 1 to 3.")

    assert error.http_status == 422
    assert error.to_body() == {"error": {"code": "invalid_range", "message": "Pages go from 1 to 3."}}


def test_every_code_has_a_status():
    for code in ErrorCode:
        assert 400 <= MergerError(code, "x").http_status < 600
