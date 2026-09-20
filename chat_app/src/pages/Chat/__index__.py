"""Chat page: LLM conversation UI, provider/extension APIs, and per-user
chat history. Ported from MCPArchitecture's
chat_app/src/chat_app/pages/chat/routes.py - see
docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import traceback
import urllib.error
from urllib.parse import quote
from uuid import uuid4
from datetime import datetime, timezone

import httpx
from flask import Blueprint, Response, current_app, jsonify, render_template, request
from flask_login import current_user

from src.models import db
from src.services import agent_registry, tool_capabilities, ai_agent_client, chats_store, commands, log_service, summarization, text_extraction, usage_limits
from src.services.authz import register_permission, require_permission
from src.services.chat_jobs import ChatAlreadyRunning, ChatJobRegistry
from src.services.llm.settings import settings
from src.services.mcp_client import add_extension, fetch_capabilities, fetch_extensions, fetch_options, remove_extension, upload_file
from src.services.sse import encode_sse, stream_async_generator

blueprint = Blueprint(
    "chat", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = "chat.access"
PAGE_DESCRIPTION = "Chat with the MCP-connected LLM."
PAGE_LAYOUT = "full"
CSRF_EXEMPT = True

register_permission("chat.access")

_MESSAGE_MAX = 200
_TRACE_MESSAGE_MAX = 500
# A saved step's result is capped so a chat with many/large tool results
# doesn't bloat its stored transcript; the full result stays in the Logs
# page's trace (chat.turn).
_STEP_RESULT_MAX = 4000


def _chat_jobs() -> ChatJobRegistry:
    app = current_app._get_current_object()
    # setdefault keeps a single registry even when initial requests race.
    return app.extensions.setdefault(
        "chat_jobs", ChatJobRegistry(settings.chats_db_path, context_factory=app.app_context)
    )


@blueprint.route("/")
@require_permission("chat.access")
def index():
    return render_template("chat.html")


@blueprint.route("/api/providers")
@require_permission("chat.access")
def providers_api():
    """One entry per configured ai_agent (see agent_registry.py), each
    live-polled via its own status tool - so a rate-limited or
    unreachable agent still shows up in the dropdown, greyed out with a
    reason, same UX as the old per-provider cooldown entries. models/
    default_model_id stay empty: an agent is hard-pinned to one model,
    there's no sub-dropdown to populate.

    label prefers the agent's live vendor_label (its status tool's
    reading of the CURRENTLY SELECTED AI_AGENT_GATEWAY block's "label" in
    ai_agent's configs/config_llms.json - e.g. "OpenRouter" rather than a
    static "Claude Agent" once that instance's gateway points elsewhere)
    over config_agents.json's own static label, which only remains a
    fallback for an agent that's unreachable (no live status to read).

    A `?refresh=1` query param (script.js's dropdown refresh button)
    reloads the agent list itself from config_agents.json first - the
    per-agent live status above is already polled every 15s regardless,
    but the SET of agents was only ever read once at import time, so an
    ai_agent instance started or stopped since then wouldn't otherwise
    show up without restarting chat_app."""
    if request.args.get("refresh"):
        agent_registry.reload()
    entries = []
    for agent in agent_registry.all_agents():
        try:
            live = ai_agent_client.status(agent["url"])
            entries.append(
                {
                    "id": agent["id"],
                    "label": live.get("vendor_label") or agent["label"],
                    "available": bool(live.get("available")),
                    "reason": live.get("reason"),
                    "cooldown_seconds_remaining": int(live.get("cooldown_seconds_remaining") or 0),
                    "models": [],
                    "default_model_id": "",
                    "model": live.get("model"),
                    "context_window": live.get("context_window"),
                }
            )
        except Exception:  # noqa: BLE001 - an unreachable agent still shows up, greyed out
            entries.append(
                {
                    "id": agent["id"],
                    "label": agent["label"],
                    "available": False,
                    "reason": "unreachable",
                    "cooldown_seconds_remaining": 0,
                    "models": [],
                    "default_model_id": "",
                    "model": None,
                    "context_window": None,
                }
            )
    return jsonify(entries)


@blueprint.route("/api/extensions")
@require_permission("chat.access")
def extensions_api():
    try:
        extensions = fetch_extensions()
        error = None
    except Exception as exc:  # noqa: BLE001 - surface any error to the sidebar
        extensions = []
        error = str(exc)
    return jsonify({"extensions": extensions, "error": error})


@blueprint.route("/api/commands")
@require_permission("chat.access")
def commands_api():
    enabled = request.args.get("enabled_extensions", "")
    enabled_extensions = [e for e in enabled.split(",") if e]
    registry = commands.build_command_registry(enabled_extensions)
    options_by_url: dict[str, list[dict[str, str]] | None] = {}

    def _options_for(url: str | None):
        # A param's options_url is fetched once per request; a failure just
        # leaves the param without options, and the form falls back to its
        # plain input.
        if not url or "{" in url:
            return None  # a {placeholder} url is fetched by the form via /api/param-options
        if url not in options_by_url:
            try:
                options_by_url[url] = fetch_options(url)
            except Exception:  # noqa: BLE001 - supplementary
                options_by_url[url] = None
        return options_by_url[url]

    payload = {
            capability: {
                tool_id: {
                    "description": entry.description,
                    "params": [
                        {
                            "name": p.name,
                            "required": p.required,
                            "type": p.type,
                            "has_default": p.has_default,
                            "default": p.default,
                            "examples": p.examples,
                            "format": p.format,
                            "input": p.input,
                            "options": _options_for(p.options_url),
                            "options_url": p.options_url,
                            "enum": p.enum,
                            "minimum": p.minimum,
                            "maximum": p.maximum,
                            "step": p.step,
                            "max_length": p.max_length,
                            "pattern": p.pattern,
                            "depends_on": p.depends_on,
                            "sets": p.sets,
                            "shows": p.shows,
                            "initial": p.initial,
                        }
                        for p in entry.params
                    ],
                }
                for tool_id, entry in tools.items()
            }
            for capability, tools in registry.items()
    }
    return jsonify(payload)


@blueprint.route("/api/capability-labels")
@require_permission("chat.access")
def capability_labels_api():
    """``{capability_id: label}`` as registered on mcp_server - the Chat
    page's suggestion bar and welcome card show these instead of a
    hand-kept map. Falls back to the last cached labels when mcp_server
    is unreachable."""
    try:
        tool_capabilities.refresh_from(fetch_capabilities())
    except Exception:  # noqa: BLE001 - cached labels are good enough
        pass
    return jsonify(tool_capabilities.known_labels())


@blueprint.route("/api/param-options")
@require_permission("chat.access")
def param_options_api():
    """Options for a select param whose options_url has a {placeholder}
    (``depends_on``), filled from ``arg.<param>`` query args - e.g. a
    dependent picker once its parent is chosen. ``template`` must be an
    options_url some registered command actually declares, so this can't be
    used to fetch arbitrary mcp_server paths."""
    template = request.args.get("template", "")
    enabled = request.args.get("enabled_extensions", "")
    registry = commands.build_command_registry([e for e in enabled.split(",") if e])
    known = {p.options_url for tools in registry.values() for entry in tools.values() for p in entry.params if p.options_url}
    if template not in known:
        return jsonify({"error": "unknown options template"}), 400
    url = template
    for name in re.findall(r"\{(\w+)\}", template):
        value = request.args.get(f"arg.{name}", "")
        if not value:
            return jsonify({"error": f"arg.{name} is required"}), 400
        url = url.replace("{" + name + "}", quote(value, safe=""))
    try:
        return jsonify(fetch_options(url))
    except Exception as exc:  # noqa: BLE001 - surface to the picker, not a 500
        return jsonify({"error": str(exc)}), 502


@blueprint.route("/api/upload", methods=["POST"])
@require_permission("chat.access")
def upload_api():
    """Proxies a file the command-form modal's drop zone collected to
    mcp_server's POST /upload (see services/mcp_client.py's upload_file()
    and mcp_server's upload_routes.py), so a file-format param (e.g.
    a tool's file_path) can be
    filled with a real server-side path instead of the user typing one.

    The browser never talks to mcp_server directly - this route is the
    only thing holding the shared internal-API-token secret that trip
    needs, same reasoning every other Chat API route already follows for
    mcp_client calls.
    """
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "'file' is required"}), 400
    try:
        result = upload_file(upload.filename, upload.read(), upload.mimetype)
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            message = body.get("error", str(exc))
        except Exception:  # noqa: BLE001 - a malformed error body still needs a message
            message = str(exc)
        return jsonify({"error": message}), exc.response.status_code
    except Exception as exc:  # noqa: BLE001 - mcp_server unreachable
        return jsonify({"error": f"Could not reach mcp_server: {exc}"}), 502
    return jsonify(result)


@blueprint.route("/api/chat/attach", methods=["POST"])
@require_permission("chat.access")
def chat_attach_api():
    """Extracts plain text from a file dropped/attached in the chat
    composer, so script.js can fold it into the next question sent to
    ai_agent as context - see services/text_extraction.py. Distinct from
    upload_api above: that one hands mcp_server a file path for a
    command-form tool param, never touching its contents here; this one
    never leaves chat_app - the file is read, converted to text, and
    otherwise discarded."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "'file' is required"}), 400
    try:
        result = text_extraction.extract_text(upload.filename, upload.read())
    except text_extraction.ExtractionError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


def _forward_extension_error(exc: urllib.error.HTTPError):
    try:
        body = json.loads(exc.read().decode("utf-8"))
        message = body.get("error") or f"mcp_server returned {exc.code}."
    except Exception:  # noqa: BLE001 - body wasn't parseable JSON
        message = f"mcp_server returned {exc.code}."
    return jsonify({"error": message}), exc.code


@blueprint.route("/api/extensions", methods=["POST"])
@require_permission("chat.access")
def add_extension_api():
    data = request.get_json(silent=True) or {}
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


@blueprint.route("/api/extensions/<extension_id>", methods=["DELETE"])
@require_permission("chat.access")
def remove_extension_api(extension_id):
    try:
        remove_extension(extension_id)
        return "", 204
    except urllib.error.HTTPError as exc:
        return _forward_extension_error(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. mcp_server unreachable
        return jsonify({"error": str(exc)}), 502


@blueprint.route("/api/usage")
@require_permission("chat.access")
def usage_api():
    return jsonify(usage_limits.get_usage(settings.usage_db_path, current_user.username))


@blueprint.route("/api/chats")
@require_permission("chat.access")
def list_chats_api():
    return jsonify(chats_store.list_chats(
        settings.chats_db_path, current_user.username,
        activity_by_chat=_chat_jobs().status_for_user(current_user.username),
    ))


@blueprint.route("/api/chats", methods=["DELETE"])
@require_permission("chat.access")
def delete_chats_api():
    data = request.get_json(silent=True) or {}
    chat_ids = data.get("chat_ids")
    if (
        not isinstance(chat_ids, list)
        or not chat_ids
        or any(not isinstance(chat_id, str) or not chat_id for chat_id in chat_ids)
    ):
        return jsonify({"error": "'chat_ids' must be a non-empty list of chat IDs."}), 400
    for chat_id in chat_ids:
        _chat_jobs().cancel(current_user.username, chat_id)
    deleted = chats_store.delete_chats(settings.chats_db_path, current_user.username, chat_ids)
    for chat_id in chat_ids:
        _chat_jobs().discard(current_user.username, chat_id)
    return jsonify({"deleted": deleted})


@blueprint.route("/api/chats/<chat_id>")
@require_permission("chat.access")
def get_chat_api(chat_id):
    # Snapshot the job before reading the authoritative transcript.  A worker
    # may save its terminal response and update this job between the two
    # reads; taking the transcript second then gives a reconnecting browser
    # current persisted content while the running snapshot still causes it to
    # replay/reconcile the terminal event.  This especially matters for
    # cancelled, failed, and command turns, which retain last_response_at.
    job = _chat_jobs().get(current_user.username, chat_id)
    activity = None
    pending_question = None
    if job is not None:
        with job.condition:
            activity = {"status": job.status, "started_at": job.started_at,
                        "request_id": job.request_id, "provider_id": job.provider_id}
            pending_question = job.question if job.status == "running" else None
    chat = chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
    if activity is not None:
        chat["activity"] = activity
        chat["pending_question"] = pending_question
    return jsonify(chat)


_EXPORT_FILENAME_UNSAFE_RE = re.compile(r'[\\/:*?"<>|]+')


@blueprint.route("/api/chats/<chat_id>/export")
@require_permission("chat.access")
def export_chat_api(chat_id):
    """Raw-transcript download - phase 2's standalone feature, and the
    "log attachment" building block later phases (summarize/clear) reuse.
    Same None-means-not-yours-or-missing 404 as get_chat_api above."""
    chat = chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
    text = chats_store.export_messages(settings.chats_db_path, current_user.username, chat_id)
    safe_title = _EXPORT_FILENAME_UNSAFE_RE.sub("_", chat["title"]).strip() or chat_id
    return Response(
        text,
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.md"'},
    )


@blueprint.route("/api/chats/<chat_id>/summarize", methods=["POST"])
@require_permission("chat.access")
def summarize_chat_api(chat_id):
    """Compresses this chat's history into one summary + one cumulative
    log-attachment message (see services/summarization.py) - fully
    manual, triggered by the "/summarize" command in script.js. Only
    ever overwrites the stored transcript on a clean success; every
    failure (missing chat, no agent configured, agent unreachable or
    empty reply) leaves it completely untouched and reports a clear
    error instead - same "commit only on success" contract as the rest
    of this file's persistence calls."""
    if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
        return jsonify({"error": "Chat not found."}), 404

    data = request.get_json(silent=True) or {}
    agent = agent_registry.resolve_agent(data.get("provider"))
    if agent is None:
        return jsonify({"error": "No ai_agent is configured - add one to configs/config_agents.json."}), 502

    try:
        summarized = summarization.summarize_chat(
            settings.chats_db_path, current_user.username, chat_id, agent["url"], settings.usage_db_path
        )
    except summarization.SummarizeError as error:
        return jsonify({"error": str(error)}), 502
    except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
        log_service.log_error(
            db.session, current_user, source="chat.summarize",
            message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
        )
        return jsonify({"error": "Something went wrong while summarizing. Check the Logs page (Errors tab) for details."}), 500

    if not summarized:
        return jsonify({"error": "Nothing new to summarize yet."}), 400

    chat = chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id)
    return jsonify(chat)


@blueprint.route("/api/chats/<chat_id>/clear", methods=["POST"])
@require_permission("chat.access")
def clear_chat_api(chat_id):
    """No-AI clear for "/clear" (see script.js's clearChat()): reached
    either when the user explicitly picks "Just clear" over "Generate
    summary" in the clear-confirmation modal, or as the AI-unavailable
    fallback when they picked "Generate summary" but summarize_chat_api
    above couldn't be reached. Either way, trims the transcript for real
    by keeping just the cumulative raw log (no summary, since none was
    requested/produced). Same has_prior/prior_log/new_range folding as
    summarize_chat (see services/summarization.py) so a chat that already
    has a prior summary+log still ends up with ONE log covering the
    entire original history, not just the newest slice - just without a
    summary message in front of it this time."""
    chat = chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404

    messages = chat["messages"]
    has_prior = bool(messages) and messages[0].get("kind") == "summary"
    prior_log = (messages[1].get("content") or "") if has_prior and len(messages) > 1 else ""
    new_range = messages[2:] if has_prior else messages
    if new_range:
        full_log = prior_log + chats_store.render_messages(new_range)
        chats_store.save_chat(
            settings.chats_db_path, current_user.username, chat_id,
            [{"role": "assistant", "kind": "log_attachment", "content": full_log}],
        )
        chat = chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id)
    return jsonify(chat)


@blueprint.route("/api/chats/<chat_id>", methods=["PATCH"])
@require_permission("chat.access")
def rename_chat_api(chat_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title must not be blank."}), 400
    try:
        chats_store.rename_chat(settings.chats_db_path, current_user.username, chat_id, title)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@blueprint.route("/api/chats/<chat_id>", methods=["DELETE"])
@require_permission("chat.access")
def delete_chat_api(chat_id):
    try:
        _chat_jobs().cancel(current_user.username, chat_id)
        chats_store.delete_chat(settings.chats_db_path, current_user.username, chat_id)
        _chat_jobs().discard(current_user.username, chat_id)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@blueprint.route("/api/chat/cancel", methods=["POST"])
@require_permission("chat.access")
def cancel_chat_api():
    """Compatibility endpoint: request IDs may cancel only owned jobs."""
    data = request.get_json(silent=True) or {}
    registry = _chat_jobs()
    for chat_id, activity in registry.status_for_user(current_user.username).items():
        if activity["request_id"] == data.get("request_id") and activity["provider_id"] == data.get("provider"):
            registry.cancel(current_user.username, chat_id)
    return "", 204


@blueprint.route("/api/chats/<chat_id>/events")
@require_permission("chat.access")
def chat_events_api(chat_id):
    registry = _chat_jobs()
    if (chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None
            or registry.get(current_user.username, chat_id) is None):
        return jsonify({"error": "Chat not found."}), 404
    try:
        after_sequence = int(request.args.get("after_sequence", request.headers.get("Last-Event-ID", "0")))
        if after_sequence < 0:
            raise ValueError
    except ValueError:
        return jsonify({"error": "after_sequence must be a non-negative integer."}), 400
    try:
        events = registry.subscribe(current_user.username, chat_id, after_sequence)
    except chats_store.UnknownChat:
        # Retention may expire between the ownership lookup and subscription.
        return jsonify({"error": "Chat replay expired. Reload the saved chat."}), 404

    def stream_events():
        try:
            for event in events:
                yield encode_sse(event)
        except chats_store.UnknownChat:
            # Flask starts consuming SSE bodies only after this route returns,
            # so expiry can also race a successfully-created lazy iterator.
            yield encode_sse({
                "type": "error",
                "message": "Chat replay expired. Reload the saved chat.",
                "failed": True,
            })

    return Response(
        stream_events(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@blueprint.route("/api/chats/<chat_id>/cancel", methods=["POST"])
@require_permission("chat.access")
def cancel_owned_chat_api(chat_id):
    if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
        return jsonify({"error": "Chat not found."}), 404
    _chat_jobs().cancel(current_user.username, chat_id)
    return "", 204


def _llm_history_from_messages(messages: list[dict]) -> list[dict]:
    """log_attachment messages (see services/summarization.py) are never
    resent to the LLM - it's the raw history a summary already replaced,
    so resending it would re-inflate the very context a summarize cycle
    just excised. script.js's loadChat() applies the same filter when
    rebuilding its own `history` array; this is the server-side half of
    that, shared by chat_api's normal history build and its phase 5
    auto-summarize rebuild below."""
    return [{"role": m.get("role"), "content": m.get("content")} for m in messages if m.get("kind") != "log_attachment"]


def _last_context_usage(messages: list[dict]) -> tuple[float | None, float | None]:
    """Walks a chat's stored messages in order, keeping the LAST
    assistant turn's context_tokens/context_window pair - same walk
    script.js's loadChat() does client-side to restore the usage bar
    after a reload (phase 1), mirrored here so phase 5's auto-summarize
    trigger below reads that same "last known" reading."""
    tokens = window = None
    for message in messages:
        t, w = message.get("context_tokens"), message.get("context_window")
        if isinstance(t, (int, float)) and isinstance(w, (int, float)):
            tokens, window = t, w
    return tokens, window


def _maybe_auto_summarize(chat_id: str, agent_url: str, username: str) -> list[dict] | None:
    """Phase 5: transparent pre-send auto-summarize. Reads the
    server-persisted chat (not the client-sent `history` payload) so a
    stale client can't skip or double-trigger this - server-side check
    preferred over client-side, same chat_app-owns-consistency reasoning
    the rest of this file already follows. Returns the chat's freshly
    summarized raw message list when a summarize actually ran, or None
    when nothing changed: below threshold, nothing new to summarize since
    the last cycle, or the agent couldn't produce one. A failure here
    never blocks or surfaces an error for the user's actual turn - it
    just leaves the oversized context to be sent through unchanged, same
    as if this check didn't run at all."""
    chat = chats_store.get_chat(settings.chats_db_path, username, chat_id)
    if chat is None:
        return None
    tokens, window = _last_context_usage(chat["messages"])
    if not tokens or not window or window <= 0:
        return None
    # A configurable soft cap (configs/config_usage_limits.json) independent
    # of the model's real context_window - lets an operator force earlier
    # summarization regardless of which model/provider a chat is using.
    window = min(window, usage_limits.MAX_CONTEXT_TOKENS_PER_CHAT)
    if tokens / window < summarization.AUTO_SUMMARIZE_THRESHOLD_RATIO:
        return None
    try:
        if not summarization.summarize_chat(
            settings.chats_db_path, username, chat_id, agent_url, settings.usage_db_path
        ):
            return None
    except summarization.SummarizeError:
        return None
    chat = chats_store.get_chat(settings.chats_db_path, username, chat_id)
    return chat["messages"] if chat else None


@blueprint.route("/api/chat", methods=["POST"])
@require_permission("chat.access")
def chat_api():
    """Start a server-owned turn and subscribe to its live SSE events.

    The worker consumes the provider stream, saves the terminal transcript,
    and accounts for usage once. Closing or replaying the HTTP response
    never controls the worker. ``background: true`` returns its identifiers
    immediately so a browser can subscribe through the chat events route.
    """
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return Response(
            encode_sse({"type": "final", "response": "Please enter a question."}),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    # Commands run directly against mcp_server inside the worker; only
    # model responses support the ai_agent's cooperative cancellation.
    request_id = data.get("request_id") or uuid4().hex

    is_command = question.startswith("/")
    # Defense-in-depth filter (see _llm_history_from_messages) for a stale
    # client that still sent a log_attachment message anyway; overwritten
    # below by _maybe_auto_summarize's own rebuild whenever phase 5's
    # auto-trigger actually fires for this turn.
    llm_history = _llm_history_from_messages(data.get("history", []))

    chat_id = data.get("chat_id")
    if chat_id is not None:
        if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
            return jsonify({"error": "Chat not found."}), 404
    if chat_id is None:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, [])
        except Exception as error:  # noqa: BLE001 - jobs require an owned chat row
            log_service.log_error(
                db.session, current_user, source="chat.start",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            return jsonify({"error": "Could not create the chat."}), 500

    start = time.monotonic()
    # Capture the owner before the worker leaves this request context.
    user = current_user._get_current_object()
    agent = agent_registry.resolve_agent(data.get("provider"))

    def event_source(job):
        if job.cancel_requested:
            yield {"type": "final", "response": "⏹️ Cancelled.", "cancelled": True}
            return
        if is_command:
            # A "/" command is a direct tool call, never the LLM - see
            # docs/superpowers/specs/2026-08-23-chat-slash-commands-design.md.
            # The tool can take a while (e.g. a remote host); run it on a
            # side thread so the progress messages it reports can be
            # streamed to the browser as they arrive instead of after.
            progress_queue: queue.Queue = queue.Queue()
            outcome: dict = {}

            def run_command() -> None:
                try:
                    outcome["text"] = commands.execute_command(
                        question, data.get("enabled_extensions", []), user=user,
                        on_progress=lambda message: progress_queue.put(message),
                    )
                except Exception as error:  # noqa: BLE001 - re-raised on the generator side below
                    outcome["error"] = error
                finally:
                    progress_queue.put(None)

            threading.Thread(target=run_command, daemon=True).start()
            while (message := progress_queue.get()) is not None:
                yield {"type": "progress", "message": message}
            if "error" in outcome:
                raise outcome["error"]
            yield {
                "type": "final",
                "response": outcome["text"],
                "kind": "command",
            }
            return

        # The dropdown now selects an ai_agent, not an LLM provider - see
        # agent_registry.py. resolve_agent falls back to the first
        # configured agent when the client didn't send one (e.g. an older
        # cached page).
        if agent is None:
            yield {
                "type": "final",
                "response": "❌ No ai_agent is configured - add one to configs/config_agents.json.",
                "kind": "assistant",
                "failed": True,
            }
            return

        allowed, blocked_reason, reset_at = usage_limits.check_limit(settings.usage_db_path, user.username)
        if not allowed:
            reset_text = reset_at.strftime("%H:%M UTC") if reset_at else "later"
            yield {
                "type": "final",
                "response": f"⏸️ {blocked_reason}, resets at {reset_text}.",
                "kind": "assistant",
                "failed": True,
            }
            return

        history = llm_history
        if chat_id is not None:
            summarized_messages = _maybe_auto_summarize(chat_id, agent["url"], user.username)
            if summarized_messages is not None:
                history = _llm_history_from_messages(summarized_messages)

        try:
            async def factory():
                if not job.begin_provider():
                    yield {"type": "final", "response": "⏹️ Cancelled.", "cancelled": True}
                    return
                async for event in ai_agent_client.ask_stream(
                    agent["url"], question, history, data.get("enabled_extensions", []), job.provider_request_id,
                ):
                    yield event

            for event in stream_async_generator(factory):
                if event["type"] == "error":
                    if event.get("unplanned"):
                        # A genuinely unplanned failure (see
                        # ai_agent_client.ask_stream's except Exception) -
                        # untrusted text, never shown raw; logged so an
                        # admin can see it on the Logs page, same as the
                        # old `except Exception` branch below did before
                        # streaming existed.
                        log_service.log_error(
                            db.session, user, source="chat.answer",
                            message=f"Error: {event['message']}"[:_MESSAGE_MAX], details=event["message"],
                        )
                        yield {
                            "type": "final",
                            "response": "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details.",
                            "kind": "assistant",
                            "failed": True,
                        }
                    else:
                        # Agent-authored (isError result, e.g. a
                        # rate-limit message) - meant for whoever is
                        # chatting, safe to show as-is, deliberately not
                        # logged - same treatment the old AgentToolError
                        # branch gave it.
                        yield {"type": "final", "response": f"❌ {event['message']}", "kind": "assistant", "failed": True}
                    return
                if event["type"] == "final":
                    payload = dict(event)
                    payload["kind"] = "assistant"
                    if payload.get("cancelled"):
                        # The user hit Stop and the agent noticed at its
                        # next between-round checkpoint - an expected user
                        # action, not a failure, so this deliberately never
                        # reaches the except Exception branch below.
                        payload.setdefault("response", "⏹️ Cancelled.")
                    yield payload
                    return
                yield event
            raise RuntimeError("The AI agent stream ended without a final response.")
        except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
            log_service.log_error(
                db.session, user, source="chat.answer",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            yield {
                "type": "final",
                "response": "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details.",
                "kind": "assistant",
                "failed": True,
            }

    def safe_event_source(job):
        try:
            yield from event_source(job)
        except Exception as error:  # commands and pre-send work can fail too
            log_service.log_error(
                db.session, user, source="chat.answer",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            yield {
                "type": "final", "failed": True, "kind": "assistant",
                "response": "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details.",
            }

    def generate(job):
        # Tool steps seen this turn, saved on the assistant message so a
        # reload can rebuild the collapsed "Ran N tools" block (script.js's
        # renderSavedTrace). Built from the same step_start/step_end
        # events the live view renders.
        steps: list[dict] = []
        steps_by_id: dict[str, dict] = {}
        for event in safe_event_source(job):
            if event["type"] == "step_start":
                step = {
                    "tool": event.get("tool", ""), "label": event.get("label") or "",
                    "arguments": event.get("arguments") or {}, "ok": None, "result": "",
                }
                steps.append(step)
                steps_by_id[event.get("id")] = step
            elif event["type"] == "step_end":
                step = steps_by_id.get(event.get("id"))
                if step is not None:
                    step["ok"] = bool(event.get("ok"))
                    step["result"] = str(event.get("result") or "")[:_STEP_RESULT_MAX]
            if event["type"] != "final":
                yield event
                continue

            elapsed_seconds = round(time.monotonic() - start, 1)
            response_text = event.get("response", "")
            tools_used = event.get("tools_used", [])
            tool_calls = event.get("tool_calls", [])
            provider_id = event.get("provider_id", "")
            model_used = event.get("model", "")
            total_tokens = event.get("total_tokens")
            context_tokens = event.get("context_tokens")
            context_window = event.get("context_window")
            kind = event.get("kind", "assistant")
            ai_used = event.get("ai_used")

            if isinstance(total_tokens, int):
                usage_limits.record_usage(settings.usage_db_path, user.username, total_tokens)

            # Base this turn's save on the chat's OWN current persisted
            # transcript, never on the client's `history` payload: phase 5's
            # auto-summarize can rewrite storage mid-request (see
            # _maybe_auto_summarize above), and script.js only ever
            # resyncs its local `history` array after an explicit
            # /summarize or /clear reload - never after an ordinary turn
            # (it just appends locally, see script.js's send()). Trusting
            # the client's payload here would silently overwrite that
            # mutation back to the stale pre-summarize history on the very
            # next normal turn. A brand-new chat_id (nothing persisted yet)
            # or a lookup failure falls back to the client's payload, same
            # as before this existed.
            history_in = None
            if chat_id is not None:
                stored_chat = chats_store.get_chat(settings.chats_db_path, user.username, chat_id)
                if stored_chat is not None:
                    history_in = stored_chat["messages"]
            if history_in is None:
                history_in = list(data.get("history", []))
            current_turn = [{
                "role": "user",
                "content": question,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }]
            if history_in and history_in[-1] == current_turn[0]:
                current_turn = []
            assistant_entry: dict = {
                "role": "assistant",
                "content": response_text,
                "request_id": job.request_id,
                "elapsed_seconds": elapsed_seconds,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
            if steps:
                assistant_entry["steps"] = steps
            if kind == "command":
                assistant_entry["kind"] = "command"
                assistant_entry["ai_used"] = bool(ai_used)
            if provider_id:
                assistant_entry["provider_id"] = provider_id
            if model_used:
                assistant_entry["model"] = model_used
            if total_tokens is not None:
                assistant_entry["total_tokens"] = total_tokens
            if context_tokens is not None:
                assistant_entry["context_tokens"] = context_tokens
            if context_window is not None:
                assistant_entry["context_window"] = context_window
            transcript = history_in + current_turn + [assistant_entry]

            saved_chat_id = chat_id
            try:
                saved_chat_id = chats_store.save_chat(settings.chats_db_path, user.username, chat_id, transcript)
            except chats_store.UnknownChat:
                # Deleted while running: never resurrect the removed chat.
                saved_chat_id = None
            except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
                log_service.log_error(
                    db.session, user, source="chat.save",
                    message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
                )
                saved_chat_id = None

            if saved_chat_id is not None:
                try:
                    if kind in ("assistant", "command") and not event.get("cancelled") and not event.get("failed"):
                        chats_store.record_last_response(
                            settings.chats_db_path, user.username, saved_chat_id, assistant_entry["sent_at"]
                        )
                    trace_message = f"{question[:80]} → {provider_id or 'error'}/{model_used or '-'}, {elapsed_seconds}s"
                    trace_details = json.dumps(
                        {"tool_calls": tool_calls, "response": response_text, "total_tokens": total_tokens}
                    )
                    log_service.log_chat_trace(
                        db.session, user, source="chat.turn",
                        message=trace_message[:_TRACE_MESSAGE_MAX], details=trace_details,
                    )
                except Exception as error:  # noqa: BLE001 - a trace write must not break the chat answer itself
                    log_service.log_error(
                        db.session, user, source="chat.trace",
                        message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
                    )

            yield (
                {
                    "type": "final",
                    "response": response_text,
                    "tools_used": tools_used,
                    "provider_id": provider_id,
                    "model": model_used,
                    "total_tokens": total_tokens,
                    "context_tokens": context_tokens,
                    "context_window": context_window,
                    "elapsed_seconds": elapsed_seconds,
                    # Dead weight carried over verbatim from the pre-streaming
                    # code: recursive_rounds was always len() of an
                    # always-empty local list there too - not a regression.
                    "recursive_rounds": 0,
                    "chat_id": saved_chat_id,
                    "kind": kind,
                    "ai_used": ai_used,
                    "cancelled": bool(event.get("cancelled")),
                    "failed": bool(event.get("failed")) or saved_chat_id is None,
                }
            )

    registry = _chat_jobs()
    try:
        job = registry.start(
            user.username, chat_id, agent["id"] if agent else None, request_id,
            question, data.get("history", []), run_turn=generate,
        )
    except ChatAlreadyRunning:
        return jsonify({"error": "This chat already has a running response."}), 409
    if data.get("background"):
        return jsonify({"chat_id": chat_id, "request_id": job.request_id}), 202
    return Response(
        (encode_sse(event) for event in registry.subscribe(user.username, chat_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
                 "X-Chat-Id": chat_id, "X-Request-Id": job.request_id},
    )
