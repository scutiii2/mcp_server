"""DELETE /memory/owners/{uid}: removes one account's memory notes.

A plain HTTP route and not a tool, so no model can name a user: only
ember_api calls it, after it deletes an account. Checked against the
internal token like /upload (an unset token never validates).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings
from src.services import capability_registry, memory_store

_UID = re.compile(r"[0-9a-f]{32}")


def _token_valid(request: Request) -> bool:
    expected = settings.internal_api_token
    provided = request.headers.get("X-Internal-Token", "")
    if not expected:
        return False
    return hmac.compare_digest(expected, provided)


def _memory_online() -> bool:
    return "memory" in capability_registry.names() and capability_registry.is_enabled("memory")


async def purge_memory_owner(request: Request) -> JSONResponse:
    if not _token_valid(request):
        return JSONResponse({"error": "Invalid or missing internal API token"}, status_code=401)
    if not _memory_online():
        return JSONResponse({"error": "Memory is not enabled"}, status_code=404)
    uid = request.path_params["uid"]
    if not _UID.fullmatch(uid):
        return JSONResponse({"error": "Not a valid account uid"}, status_code=400)
    purged = await asyncio.to_thread(memory_store.purge_owner, settings.memory_db_path, uid)
    return JSONResponse({"purged": purged})


class _PurgeLogFilter(logging.Filter):
    """Keep the internal uid out of Uvicorn's request paths."""

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


def install_memory_routes(app: Starlette) -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _PurgeLogFilter) for f in access_logger.filters):
        access_logger.addFilter(_PurgeLogFilter())
    app.add_route("/memory/owners/{uid}", purge_memory_owner, methods=["DELETE"])
