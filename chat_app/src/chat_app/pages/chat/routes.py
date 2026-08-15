"""Chat page, provider list, and chat API.

This blueprint owns everything under ``pages/chat/`` - both its routes and
its own ``template/`` folder (index.html + styles.css + script.js, kept as
separate files rather than one HTML file with inline <style>/<script>).
``static_folder`` points at that same folder so styles.css/script.js are
directly fetchable at runtime; ``index.html`` itself is rendered through
Jinja via the app-level PrefixLoader set up in ``app.py`` (see that file's
docstring for why a plain per-blueprint ``template_folder`` would collide
with capabilities/'s own index.html).
"""

from __future__ import annotations

import json
import urllib.error

from flask import Blueprint, jsonify, render_template, request

from chat_app.errors import report
from chat_app.security import json_body
from chat_app.services.llm import router
from chat_app.services.mcp_client import add_extension, fetch_extensions, remove_extension


chat_bp = Blueprint(
    "chat",
    __name__,
    static_folder="template",
    static_url_path="/pages/chat/assets",
)


@chat_bp.get("/chat", strict_slashes=False)
def chat_page():
    return render_template("chat/index.html")


@chat_bp.get("/api/providers")
def providers_api():
    """Live availability - the frontend uses this to gray out any provider
    whose API key isn't configured, rather than letting the user pick it
    and only finding out it fails after sending a message."""
    return jsonify(router.list_providers())


@chat_bp.get("/api/extensions")
def extensions_api():
    """Proxy for mcp_server's plain-HTTP ``/extensions`` endpoint - the
    sidebar's toggle list. Mirrors capabilities/routes.py's browse():
    an unreachable/erroring mcp_server surfaces as a 200 with an empty
    list plus an ``error`` field rather than a 500, since the frontend
    polls this every 15s and a transient failure shouldn't crash the
    page or the poll loop."""
    try:
        extensions = fetch_extensions()
        error = None
    except Exception as exc:  # noqa: BLE001 - surface any error to the sidebar
        extensions = []
        error = str(exc)
    return jsonify({"extensions": extensions, "error": error})


def _forward_extension_error(exc: urllib.error.HTTPError):
    """Forward mcp_server's own status code and message (400 validation,
    404 unknown id) rather than collapsing everything to a generic error -
    those messages were written by mcp_server for a human to read, same
    reasoning as the curated-ValueError branch in chat_api below. Falls
    back to a generic message if the body isn't the ``{"error": "..."}``
    JSON mcp_server is expected to send."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        message = body.get("error") or f"mcp_server returned {exc.code}."
    except Exception:  # noqa: BLE001 - body wasn't parseable JSON
        message = f"mcp_server returned {exc.code}."
    return jsonify({"error": message}), exc.code


@chat_bp.post("/api/extensions")
def add_extension_api():
    """Register a new extension with mcp_server. Errors here go to the
    sidebar's add-extension form, not into a chat transcript, so - unlike
    chat_api below - there's no report() indirection: mcp_server's own
    validation messages (400) are safe to show verbatim, and an unexpected
    failure (connection refused, timeout) is surfaced the same plain way
    extensions_api above already does for a GET."""
    data = json_body()
    label = (data.get("label") or "").strip()
    url = (data.get("url") or "").strip()
    description = (data.get("description") or "").strip()
    if not label or not url:
        return jsonify({"error": "Label and URL are required."}), 400
    try:
        status = add_extension(label, url, description)
        return jsonify(status), 201
    except urllib.error.HTTPError as exc:
        return _forward_extension_error(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. mcp_server unreachable
        return jsonify({"error": str(exc)}), 502


@chat_bp.delete("/api/extensions/<extension_id>")
def remove_extension_api(extension_id):
    try:
        remove_extension(extension_id)
        return "", 204
    except urllib.error.HTTPError as exc:
        return _forward_extension_error(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. mcp_server unreachable
        return jsonify({"error": str(exc)}), 502


@chat_bp.post("/api/chat")
def chat_api():
    data = json_body()
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})
    try:
        result = router.run_chat(
            question,
            data.get("history", []),
            data.get("provider"),
            data.get("model"),
            data.get("enabled_extensions", []),
        )
        return jsonify(
            {
                "response": result.response,
                "tools_used": result.tools_used,
                "provider_id": result.provider_id,
                "total_tokens": result.total_tokens,
            }
        )
    except ValueError as error:
        # Deliberately verbatim: the router raises these with wording
        # meant for whoever is chatting ("Claude is rate-limited right now
        # - try again in 42s, or pick another provider"). They contain no
        # internals, and replacing them with a reference number would make
        # the app worse for no security gain.
        return jsonify({"response": f"❌ {error}"})
    except Exception as error:
        # Anything else is unplanned, so its text is untrusted for display -
        # see errors.py.
        return jsonify({"response": f"❌ {report(error, context='answering your question')}"})
