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
import time
import urllib.error

from flask import Blueprint, jsonify, render_template, request

from chat_app.auth import service
from chat_app.chats import store as chats_store
from chat_app.config import settings
from chat_app.errors import report
from chat_app.security import json_body
from chat_app.services import session_log
from chat_app.services.llm import router
from chat_app.services.llm.base import RecursiveRoundRecord, ToolCallRecord
from chat_app.services.mcp_client import add_extension, fetch_extensions, remove_extension


chat_bp = Blueprint(
    "chat",
    __name__,
    static_folder="template",
    static_url_path="/pages/chat/assets",
)


@chat_bp.get("/chat", strict_slashes=False)
def chat_page():
    # Login is mandatory app-wide (security.check_login has no
    # unconfigured fallback), so reaching this view at all guarantees a
    # session - current_scopes() can't return None here.
    return render_template(
        "chat/index.html",
        username=service.current_username(),
        role=service.current_role(),
        scopes=service.current_scopes() or set(),
        is_executive=service.is_executive(),
        current_page="chat",
    )


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


@chat_bp.get("/api/chats")
def list_chats_api():
    return jsonify(chats_store.list_chats(settings.chats_db_path, service.current_username()))


@chat_bp.get("/api/chats/<chat_id>")
def get_chat_api(chat_id):
    chat = chats_store.get_chat(settings.chats_db_path, service.current_username(), chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
    return jsonify(chat)


@chat_bp.patch("/api/chats/<chat_id>")
def rename_chat_api(chat_id):
    data = json_body()
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title must not be blank."}), 400
    try:
        chats_store.rename_chat(settings.chats_db_path, service.current_username(), chat_id, title)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@chat_bp.delete("/api/chats/<chat_id>")
def delete_chat_api(chat_id):
    try:
        chats_store.delete_chat(settings.chats_db_path, service.current_username(), chat_id)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@chat_bp.post("/api/chat")
def chat_api():
    data = json_body()
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})

    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    recursive_rounds: list[RecursiveRoundRecord] = []
    provider_id = ""
    model_used = ""
    total_tokens = None
    # A stripped role/content-only copy, not the client's `history` as-is:
    # every provider spreads this list directly into its raw API call
    # (e.g. openai_provider.py: [..., *history]), and `history` may now
    # carry extra fields (provider_id/model/total_tokens/elapsed_seconds -
    # see the transcript-building block below) that a provider's API would
    # choke on or reject. Those extra fields are only ever meant for
    # chats_store/the browser, never for the LLM call itself.
    llm_history = [{"role": m.get("role"), "content": m.get("content")} for m in data.get("history", [])]
    start = time.monotonic()
    try:
        result = router.run_chat(
            question,
            llm_history,
            data.get("provider"),
            data.get("model"),
            data.get("enabled_extensions", []),
        )
        response_text = result.response
        tools_used = result.tools_used
        tool_calls = result.tool_calls
        recursive_rounds = result.recursive_rounds
        provider_id = result.provider_id
        model_used = result.model
        total_tokens = result.total_tokens
    except ValueError as error:
        # Deliberately verbatim: the router raises these with wording
        # meant for whoever is chatting ("Claude is rate-limited right now
        # - try again in 42s, or pick another provider"). They contain no
        # internals, and replacing them with a reference number would make
        # the app worse for no security gain.
        response_text = f"❌ {error}"
    except Exception as error:
        # Anything else is unplanned, so its text is untrusted for display -
        # see errors.py.
        response_text = f"❌ {report(error, context='answering your question')}"
    elapsed_seconds = round(time.monotonic() - start, 1)

    # Persisted regardless of which branch above ran - an error turn is
    # saved too, same as the client already does unconditionally on its
    # own `history` array, so reopening a chat shows what happened.
    #
    # history_in may or may not already end with the current question:
    # script.js's send() sends a `priorHistory` snapshot taken before the
    # question was pushed, so it never does - but this endpoint is a
    # public JSON API other callers could hit directly, and one might
    # send `history` already including the current turn. Guard against
    # that so the saved transcript never duplicates the question either
    # way.
    history_in = list(data.get("history", []))
    current_turn = [{"role": "user", "content": question}]
    if history_in and history_in[-1] == current_turn[0]:
        current_turn = []
    # provider_id/model/total_tokens are only meaningful once a real run
    # happened - the ValueError/Exception branches above leave them at
    # their empty defaults, so they're omitted here rather than stored as
    # "" / null noise on an error turn. elapsed_seconds is always real
    # (even a rate-limit check that fails fast still took some time), so
    # it's always included. Only the round COUNT is persisted here, not
    # each round's own answer text - that full detail lives in
    # session_log's JSONL trace only (see the record_turn() call below),
    # same split as tool_calls: chats.db carries just enough for the UI's
    # compact meta line, not the technical detail behind it.
    assistant_entry: dict = {"role": "assistant", "content": response_text, "elapsed_seconds": elapsed_seconds}
    if provider_id:
        assistant_entry["provider_id"] = provider_id
    if model_used:
        assistant_entry["model"] = model_used
    if total_tokens is not None:
        assistant_entry["total_tokens"] = total_tokens
    if recursive_rounds:
        assistant_entry["recursive_rounds"] = len(recursive_rounds)
    transcript = history_in + current_turn + [assistant_entry]
    chat_id = data.get("chat_id")
    try:
        chat_id = chats_store.save_chat(settings.chats_db_path, service.current_username(), chat_id, transcript)
    except chats_store.UnknownChat:
        # The chat_id the client sent no longer exists (deleted from
        # another tab, most likely) - fall back to creating a fresh chat
        # rather than losing this turn entirely.
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, service.current_username(), None, transcript)
        except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
            report(error, context="saving chat history")
            chat_id = None
    except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
        report(error, context="saving chat history")
        chat_id = None

    if chat_id is not None:
        try:
            session_log.record_turn(
                service.current_username(),
                chat_id,
                question=question,
                response=response_text,
                provider_id=provider_id,
                model=model_used,
                tool_calls=tool_calls,
                recursive_rounds=recursive_rounds,
                total_tokens=total_tokens,
                elapsed_seconds=elapsed_seconds,
            )
        except Exception as error:  # noqa: BLE001 - a trace write must not break the chat answer itself
            report(error, context="writing the chat session log")

    return jsonify(
        {
            "response": response_text,
            "tools_used": tools_used,
            "provider_id": provider_id,
            "model": model_used,
            "total_tokens": total_tokens,
            "elapsed_seconds": elapsed_seconds,
            "recursive_rounds": len(recursive_rounds),
            "chat_id": chat_id,
        }
    )
