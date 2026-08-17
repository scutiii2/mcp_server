"""The Logs page: chat transcripts (with tool-call detail) and error
tracebacks, read straight off disk via services/logs_reader.py.

Reachable only by an executive - see security.check_role_permission's
EXECUTIVE_ENDPOINTS branch. Deliberately not scope-gated the way every
other page here is (see auth/permissions.py's EXECUTIVE_ROLE docstring
for why "give it a scope" doesn't work for something meant to sit above
admin), so this blueprint's endpoints are registered in
permissions.EXECUTIVE_ENDPOINTS instead of SCOPES.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from chat_app.auth import service
from chat_app.config import settings
from chat_app.services import logs_reader


logs_bp = Blueprint(
    "logs",
    __name__,
    url_prefix="/logs",
    static_folder="template",
    static_url_path="/pages/logs/assets",
)


@logs_bp.get("/")
def logs_page():
    # Reaching this view at all already means security.py confirmed
    # is_executive() - see this module's docstring - so current_scopes()
    # is only for the sidebar's own rendering, same as every other page.
    return render_template(
        "logs/index.html",
        username=service.current_username(),
        role=service.current_role(),
        scopes=service.current_scopes() or set(),
        is_executive=True,
        current_page="logs",
        chat_users=logs_reader.list_chat_log_users(settings.log_dir),
    )


@logs_bp.get("/api/chats/<username>")
def list_user_chat_logs_api(username: str):
    return jsonify(logs_reader.list_user_chat_logs(settings.log_dir, username))


@logs_bp.get("/api/chats/<username>/<chat_id>")
def get_chat_log_api(username: str, chat_id: str):
    turns = logs_reader.read_chat_log(settings.log_dir, username, chat_id)
    if turns is None:
        return jsonify({"error": "No such chat log."}), 404
    return jsonify(turns)


@logs_bp.get("/api/chat-users")
def list_chat_log_users_api():
    return jsonify(logs_reader.list_chat_log_users(settings.log_dir))


@logs_bp.get("/api/errors")
def list_error_logs_api():
    return jsonify(logs_reader.list_error_logs(settings.log_dir))


@logs_bp.get("/api/errors/<reference>")
def get_error_log_api(reference: str):
    content = logs_reader.read_error_log(settings.log_dir, reference)
    if content is None:
        return jsonify({"error": "No such error log."}), 404
    return jsonify({"reference": reference, "content": content})
