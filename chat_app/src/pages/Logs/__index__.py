from flask import Blueprint, abort, render_template, request
from flask_login import current_user

from src.models import Account, db
from src.services import log_service
from src.services.authz import has_permission, register_permission, require_login

blueprint = Blueprint(
    "logs", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = ("logs.view", "logs.errors.view", "logs.chat.view")
PAGE_DESCRIPTION = "View server and per-account activity, error, and chat-turn logs."

register_permission("logs.view")
register_permission("logs.errors.view")
register_permission("logs.chat.view")

_ROW_LIMIT = 200


def _resolve_actor(raw_value: str) -> int | None:
    if raw_value == "server":
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


@blueprint.route("/")
@require_login()
def index():
    can_view_logs = has_permission(current_user, "logs.view")
    can_view_errors = has_permission(current_user, "logs.errors.view")
    can_view_chat_traces = has_permission(current_user, "logs.chat.view")
    if not (can_view_logs or can_view_errors or can_view_chat_traces):
        abort(403)

    accounts = db.session.query(Account).order_by(Account.username).all()
    allowed_tabs = [
        t for t, ok in (
            ("logs", can_view_logs),
            ("errors", can_view_errors),
            ("chat_traces", can_view_chat_traces),
        ) if ok
    ]
    active_tab = request.args.get("tab", allowed_tabs[0])
    if active_tab not in allowed_tabs:
        active_tab = allowed_tabs[0]
    logs_actor = request.args.get("logs_actor", "server")
    errors_actor = request.args.get("errors_actor", "server")
    # "Server" (account_id=None) always yields zero rows for this tab - a
    # chat turn always belongs to a specific account - but the dropdown
    # keeps the same Server-first shape as the other two tabs for UI
    # consistency (see docs/superpowers/specs/2026-08-22-chat-
    # capabilities-port-design.md's "Defaults Flagged for Review").
    chat_traces_actor = request.args.get("chat_traces_actor", "server")

    log_entries = None
    error_entries = None
    chat_trace_entries = None
    if can_view_logs:
        log_entries = log_service.list_entries(
            db.session, "action", _resolve_actor(logs_actor), limit=_ROW_LIMIT
        )
    if can_view_errors:
        error_entries = log_service.list_entries(
            db.session, "error", _resolve_actor(errors_actor), limit=_ROW_LIMIT
        )
    if can_view_chat_traces:
        chat_trace_entries = log_service.list_entries(
            db.session, "chat_trace", _resolve_actor(chat_traces_actor), limit=_ROW_LIMIT
        )

    return render_template(
        "logs.html",
        can_view_logs=can_view_logs,
        can_view_errors=can_view_errors,
        can_view_chat_traces=can_view_chat_traces,
        active_tab=active_tab,
        accounts=accounts,
        logs_actor=logs_actor,
        errors_actor=errors_actor,
        chat_traces_actor=chat_traces_actor,
        log_entries=log_entries,
        error_entries=error_entries,
        chat_trace_entries=chat_trace_entries,
    )
