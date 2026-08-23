"""Chat page: LLM conversation UI, provider/extension APIs, and per-user
chat history. Ported from MCPArchitecture's
chat_app/src/chat_app/pages/chat/routes.py - see
docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md.
"""

from __future__ import annotations

import json
import time
import traceback
import urllib.error

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user

from src.models import db
from src.services import chats_store, commands, log_service
from src.services.authz import register_permission, require_permission
from src.services.llm import router
from src.services.llm.base import RecursiveRoundRecord, ToolCallRecord
from src.services.llm.settings import settings
from src.services.mcp_client import add_extension, fetch_extensions, remove_extension

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


@blueprint.route("/")
@require_permission("chat.access")
def index():
    return render_template("chat.html")


@blueprint.route("/api/providers")
@require_permission("chat.access")
def providers_api():
    return jsonify(router.list_providers())


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
    return jsonify(
        {
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
                        }
                        for p in entry.params
                    ],
                }
                for tool_id, entry in tools.items()
            }
            for capability, tools in registry.items()
        }
    )


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


@blueprint.route("/api/chats")
@require_permission("chat.access")
def list_chats_api():
    return jsonify(chats_store.list_chats(settings.chats_db_path, current_user.username))


@blueprint.route("/api/chats/<chat_id>")
@require_permission("chat.access")
def get_chat_api(chat_id):
    chat = chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
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
        chats_store.delete_chat(settings.chats_db_path, current_user.username, chat_id)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@blueprint.route("/api/chat", methods=["POST"])
@require_permission("chat.access")
def chat_api():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})

    is_command = question.startswith("/")
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    recursive_rounds: list[RecursiveRoundRecord] = []
    provider_id = ""
    model_used = ""
    total_tokens = None
    llm_history = [{"role": m.get("role"), "content": m.get("content")} for m in data.get("history", [])]

    chat_id = data.get("chat_id")
    if chat_id is not None:
        if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
            chat_id = None
    if chat_id is None:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, [])
        except Exception as error:  # noqa: BLE001 - persistence must not block the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.start",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            chat_id = None

    start = time.monotonic()
    if is_command:
        # A "/" command is a direct tool call, never the LLM - see
        # docs/superpowers/specs/2026-08-23-chat-slash-commands-design.md.
        response_text = commands.execute_command(question, data.get("enabled_extensions", []))
    else:
        try:
            result = router.run_chat(
                question,
                llm_history,
                data.get("provider"),
                data.get("model"),
                data.get("enabled_extensions", []),
                chat_id=chat_id,
            )
            response_text = result.response
            tools_used = result.tools_used
            tool_calls = result.tool_calls
            recursive_rounds = result.recursive_rounds
            provider_id = result.provider_id
            model_used = result.model
            total_tokens = result.total_tokens
        except ValueError as error:
            # Deliberately verbatim: the router raises these with wording meant
            # for whoever is chatting ("Claude is rate-limited right now - try
            # again in 42s, or pick another provider"). No internals, safe to
            # show as-is.
            response_text = f"❌ {error}"
        except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
            log_service.log_error(
                db.session, current_user, source="chat.answer",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            response_text = "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details."
    elapsed_seconds = round(time.monotonic() - start, 1)

    history_in = list(data.get("history", []))
    current_turn = [{"role": "user", "content": question}]
    if history_in and history_in[-1] == current_turn[0]:
        current_turn = []
    assistant_entry: dict = {"role": "assistant", "content": response_text, "elapsed_seconds": elapsed_seconds}
    if is_command:
        assistant_entry["kind"] = "command"
    if provider_id:
        assistant_entry["provider_id"] = provider_id
    if model_used:
        assistant_entry["model"] = model_used
    if total_tokens is not None:
        assistant_entry["total_tokens"] = total_tokens
    if recursive_rounds:
        assistant_entry["recursive_rounds"] = len(recursive_rounds)
    transcript = history_in + current_turn + [assistant_entry]
    try:
        chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, chat_id, transcript)
    except chats_store.UnknownChat:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, transcript)
        except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.save",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            chat_id = None
    except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
        log_service.log_error(
            db.session, current_user, source="chat.save",
            message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
        )
        chat_id = None

    if chat_id is not None:
        try:
            trace_message = f"{question[:80]} → {provider_id or 'error'}/{model_used or '-'}, {elapsed_seconds}s"
            trace_details = json.dumps(
                {
                    "tool_calls": [
                        {"name": c.name, "arguments": c.arguments, "result": c.result} for c in tool_calls
                    ],
                    "recursive_rounds": [
                        {"round": r.round, "response": r.response, "converged": r.converged}
                        for r in recursive_rounds
                    ],
                    "response": response_text,
                    "total_tokens": total_tokens,
                }
            )
            log_service.log_chat_trace(
                db.session, current_user, source="chat.turn",
                message=trace_message[:_TRACE_MESSAGE_MAX], details=trace_details,
            )
        except Exception as error:  # noqa: BLE001 - a trace write must not break the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.trace",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )

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
            "kind": "command" if is_command else "assistant",
        }
    )
