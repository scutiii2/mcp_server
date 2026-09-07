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
from src.services import agent_registry, ai_agent_client, attachments_store, chats_store, commands, log_service
from src.services.authz import register_permission, require_permission
from src.services.llm.settings import settings
from src.services.mcp_client import add_extension, fetch_extensions, remove_extension
from src.utils.config_loader import load_json_config

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
    entries = []
    for agent in agent_registry.all_agents():
        try:
            live = ai_agent_client.status(agent["url"])
            entries.append(
                {
                    "id": agent["id"],
                    "label": agent["label"],
                    "available": bool(live.get("available")),
                    "reason": live.get("reason"),
                    "cooldown_seconds_remaining": int(live.get("cooldown_seconds_remaining") or 0),
                    "models": [],
                    "default_model_id": "",
                    "model": live.get("model"),
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
                            "enum": p.enum,
                            "format": p.format,
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


@blueprint.route("/api/attachments", methods=["POST"])
@require_permission("chat.access")
def upload_attachment_api():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "No file provided."}), 400

    chat_id = (request.form.get("chat_id") or "").strip() or None
    if chat_id is not None and chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
        chat_id = None
    if chat_id is None:
        chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, [])

    config = load_json_config(settings.attachments_config_path)
    max_file_size_mb = config.get("max_file_size_mb", 5)
    data = file.read()
    try:
        result = attachments_store.save_attachment(
            settings.attachments_dir, chat_id, file.filename, data, max_file_size_mb
        )
    except attachments_store.AttachmentError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"chat_id": chat_id, "filename": result["filename"], "size": result["size"]})


@blueprint.route("/api/chats/<chat_id>/attachments")
@require_permission("chat.access")
def list_attachments_api(chat_id):
    if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
        return jsonify({"error": "Chat not found."}), 404
    return jsonify(attachments_store.list_attachments(settings.attachments_dir, chat_id))


@blueprint.route("/api/chats/<chat_id>/attachments/<filename>", methods=["DELETE"])
@require_permission("chat.access")
def delete_attachment_api(chat_id, filename):
    if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
        return jsonify({"error": "Chat not found."}), 404
    if not attachments_store.delete_attachment(settings.attachments_dir, chat_id, filename):
        return jsonify({"error": "Attachment not found."}), 404
    return "", 204


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
    attachments_store.delete_chat_attachments(settings.attachments_dir, chat_id)
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
    tool_calls: list[dict] = []
    recursive_rounds: list[dict] = []
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
        response_text = commands.execute_command(question, data.get("enabled_extensions", []), chat_id)
    else:
        # Attachments are inlined only into the text sent to the model
        # for THIS turn - `question` (used below for both the LLM
        # history entry and the persisted/displayed transcript) stays
        # the clean, original text the user typed, so a reload never
        # shows a raw file dump in the chat log.
        llm_question = question
        for filename in data.get("attachments") or []:
            text = attachments_store.read_attachment_text(settings.attachments_dir, chat_id, filename)
            if text is not None:
                llm_question += f"\n\n📎 **{filename}**\n```\n{text}\n```"
        # The dropdown now selects an ai_agent, not an LLM provider - see
        # agent_registry.py. Falls back to the first configured agent when
        # the client didn't send one (e.g. an older cached page).
        requested_agent_id = data.get("provider")
        agent = agent_registry.get_agent(requested_agent_id) if requested_agent_id else None
        if agent is None:
            configured = agent_registry.all_agents()
            agent = configured[0] if configured else None

        if agent is None:
            response_text = "❌ No ai_agent is configured - add one to src/configs/config_agents.json."
        else:
            try:
                result = ai_agent_client.ask(
                    agent["url"], llm_question, llm_history, data.get("enabled_extensions", [])
                )
                response_text = result.get("response", "")
                tools_used = result.get("tools_used", [])
                tool_calls = result.get("tool_calls", [])
                recursive_rounds = result.get("recursive_rounds", [])
                provider_id = result.get("provider_id", "")
                model_used = result.get("model", "")
                total_tokens = result.get("total_tokens")
            except ai_agent_client.AgentToolError as error:
                # Deliberately verbatim: the agent raises these with wording
                # meant for whoever is chatting ("claude is rate-limited
                # right now"). No internals, safe to show as-is.
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
                    "tool_calls": tool_calls,
                    "recursive_rounds": recursive_rounds,
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
