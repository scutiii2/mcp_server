"""Tells mcp_server to delete a deleted account's memory notes.

Best effort: a failed purge must never block or undo the account deletion.
Leftover notes are harmless to other users (a uid is never reused), but
they linger, so the caller logs a failure.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

import httpx

from src.services.mcp_server_info import base_url

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0)


class _PurgeLogFilter(logging.Filter):
    """Keep the internal uid out of HTTPX's request URLs."""

    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value):
            text = str(value)
            return re.sub(r"(/memory/owners/)[^\s\"?]+", r"\1[redacted]", text) if "/memory/owners/" in text else value

        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


class MemoryPurger:
    def __init__(self, client: httpx.AsyncClient, mcp_url: str, internal_token: str | None) -> None:
        self._client = client
        self._base = base_url(mcp_url)
        self._internal_token = internal_token
        request_logger = logging.getLogger("httpx")
        if not any(isinstance(f, _PurgeLogFilter) for f in request_logger.filters):
            request_logger.addFilter(_PurgeLogFilter())

    async def purge(self, uid: str) -> bool:
        """DELETE /memory/owners/<uid> on mcp_server. True only when it confirmed; never raises."""
        if not uid:
            return False
        headers = {"X-Internal-Token": self._internal_token} if self._internal_token else {}
        try:
            response = await self._client.delete(
                f"{self._base}/memory/owners/{quote(uid, safe='')}", headers=headers, timeout=_TIMEOUT, follow_redirects=False
            )
        except Exception as error:  # noqa: BLE001 - best effort must not undo a deletion
            logger.warning("memory purge request failed (%s)", type(error).__name__)
            return False
        if not 200 <= response.status_code < 300:
            logger.warning("memory purge was refused with status %s", response.status_code)
            return False
        return True
