"""Read-only status of background watchers, for any capability.

Live data, not stored here: every row comes from mcp_server at request
time (see services/mcp_client.py) - this page has no database of its own.

Convention: a capability that runs ``JobWatcher``s exposes a tool named
``tool_<alias>_listWatchers`` returning ``{"watchers": [...]}``. Recipients
are shown read-only; they are set on the mcp_server side
(``tool_<alias>_setWatcherRecipients``). This page discovers every such tool from the live tool catalog, so a new
capability's watchers show up here without any change to chat_app.
"""

from __future__ import annotations

import json
import re

from flask import Blueprint, abort, jsonify, render_template
from flask_login import current_user

from src.services.authz import has_permission, register_permission, require_login, require_permission
from src.services.mcp_client import call_tool, list_tools

blueprint = Blueprint(
    "watchers", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = "watchers.view"
PAGE_DESCRIPTION = "Status of background watchers exposed by mcp_server capabilities."
CSRF_EXEMPT = True

register_permission("watchers.view")

_LIST_TOOL_RE = re.compile(r"^tool_([A-Za-z0-9]+)_listWatchers$")


def _call_tool_json(name: str, arguments: dict) -> tuple[dict | None, str | None]:
    """Call an mcp_server tool and parse its JSON result: (parsed_dict,
    None) on success, (None, raw_text) when the call succeeded at the
    transport level but didn't return JSON. Raises only on a transport
    failure."""
    raw = call_tool(name, arguments)
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, raw


def _list_all_watchers() -> tuple[list[dict], list[str]]:
    """Every watcher from every capability that exposes ``listWatchers``,
    each tagged with its ``capability`` alias. Per-capability failures are
    returned as messages instead of failing the whole page."""
    aliases = sorted(
        {m.group(1) for tool in list_tools() if (m := _LIST_TOOL_RE.match(tool.name))}
    )
    watchers: list[dict] = []
    errors: list[str] = []
    for alias in aliases:
        try:
            result, raw_error = _call_tool_json(f"tool_{alias}_listWatchers", {})
        except Exception as exc:  # noqa: BLE001 - degrade per capability, not a broken page
            errors.append(f"{alias}: {exc}")
            continue
        if result is None:
            errors.append(f"{alias}: {raw_error}")
            continue
        for row in result.get("watchers", []):
            watchers.append({**row, "capability": alias})
    return watchers, errors


@blueprint.route("/")
@require_login()
def index():
    if not has_permission(current_user, "watchers.view"):
        abort(403)

    # No SSR fetch here - the table loads (and reports errors) entirely
    # through /api/watchers (see script.js's refreshWatchers()).
    return render_template("watchers.html")


@blueprint.route("/api/watchers")
@require_permission("watchers.view")
def api_watchers():
    try:
        watchers, errors = _list_all_watchers()
    except Exception as exc:  # noqa: BLE001 - e.g. mcp_server unreachable
        return jsonify({"status": "error", "message": str(exc)}), 502
    if errors and not watchers:
        return jsonify({"status": "error", "message": "; ".join(errors)}), 502
    return jsonify({"status": "ok", "watchers": watchers, "errors": errors})

