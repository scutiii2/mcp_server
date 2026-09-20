"""HTTP endpoint for chat_app to hand this server a file a user dropped
into a command-form modal, so a tool param that expects a real
server-side path 
can be filled with one instead of the user having to know/type it.

Mounted the same way command_routes.py's GET /commands is
(see run.py): a plain HTTP route, not a tool - a model should never be
able to plant its own files on this server's disk this way, only
chat_app's own upload proxy (see chat_app's Chat/__index__.py's
POST /api/upload and services/mcp_client.py's upload_file()).

Authenticated with the same static shared secret (X-Internal-Token,
compared constant-time) chat_app's internal_routes.py already checks for
calls in the OTHER direction (mcp_server -> chat_app) - see
settings.internal_api_token's docstring in config.py. This is the first
route on THIS server that needs to check the token on the way in, since
every other plain-HTTP route here already only exposes read/admin data a
trusting deployment accepts from its own chat_app with no credential at
all - accepting arbitrary file writes without a check would be a real
step up in what an unauthenticated caller on the network could do.
"""

from __future__ import annotations

import hmac
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings

# Deliberately tight, not a generic upload endpoint: no built-in tool
# consumes an uploaded file today. Extend this set only when a new file-shaped param actually
# needs a different kind, not speculatively.
_ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


def _token_valid(request: Request) -> bool:
    """Mirrors chat_app/src/internal_routes.py's _token_valid() exactly:
    an unset expected token must never validate against an equally empty
    header, or "forgot to configure this" silently becomes "anyone can
    call it"."""
    expected = settings.internal_api_token
    provided = request.headers.get("X-Internal-Token", "")
    if not expected:
        return False
    return hmac.compare_digest(expected, provided)


def _safe_extension(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    return ext if ext in _ALLOWED_EXTENSIONS else None


async def upload_file(request: Request) -> JSONResponse:
    if not _token_valid(request):
        return JSONResponse({"error": "Invalid or missing internal API token"}, status_code=401)

    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        return JSONResponse({"error": "'file' is required"}, status_code=400)

    ext = _safe_extension(upload.filename)
    if ext is None:
        allowed = ", ".join(sorted(_ALLOWED_EXTENSIONS))
        return JSONResponse({"error": f"Unsupported file type - allowed: {allowed}"}, status_code=400)

    # A random name, never the client-supplied filename - the latter is
    # attacker-controlled and would otherwise let a crafted name escape
    # uploads_dir (path traversal) or collide with another upload.
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    saved_path = settings.uploads_dir / f"{uuid4().hex}{ext}"
    saved_path.write_bytes(await upload.read())

    return JSONResponse({"path": str(saved_path.resolve())})


def install_upload_routes(app: Starlette) -> None:
    """Add the file-upload route to an existing Starlette app."""
    app.add_route("/upload", upload_file, methods=["POST"])
