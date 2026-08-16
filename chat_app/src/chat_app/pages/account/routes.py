"""Account manager: create/remove users, assign roles, define custom
roles, and mint invite codes with a chosen role and expiry.

Reachable only by whoever's role grants the "accounts" scope (see
auth/permissions.py) - the env admin always has it; a custom role only has
it if an admin explicitly checked that box when creating the role. This
blueprint owns everything under ``pages/account/`` - see
``pages/chat/routes.py``/``app.py`` for why the static/template wiring
looks the way it does.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from chat_app.auth import permissions, service, store
from chat_app.config import settings
from chat_app.security import json_body


account_bp = Blueprint(
    "account",
    __name__,
    url_prefix="/accounts",
    static_folder="template",
    static_url_path="/pages/account/assets",
)


def _api_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@account_bp.get("/")
def manage_page():
    # Login is mandatory app-wide (security.check_login has no
    # unconfigured fallback), so reaching this view at all guarantees a
    # session - current_scopes() can't return None here.
    return render_template(
        "account/index.html",
        scopes=service.current_scopes() or set(),
        current_page="account",
        username=service.current_username(),
        role=service.current_role(),
        users=store.list_users(settings.users_db_path),
        roles=store.list_roles(settings.users_db_path),
        invites=store.list_invite_codes(settings.users_db_path),
        scope_catalog=[{"key": key, "label": entry["label"]} for key, entry in permissions.SCOPES.items()],
        admin_role=permissions.ADMIN_ROLE,
    )


@account_bp.post("/api/users")
def create_user_api():
    data = json_body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "").strip()

    if not username or not password or not role:
        return _api_error("Username, password, and role are all required.")
    if len(password) < 8:
        return _api_error("Password must be at least 8 characters.")

    try:
        store.create_user_direct(
            settings.users_db_path, username, password, role, created_by=service.current_username()
        )
    except store.UsernameTaken:
        return _api_error(f"Username {username!r} is already taken.")
    except store.UnknownRole:
        return _api_error(f"Role {role!r} does not exist.")
    return jsonify({"status": "ok"}), 201


@account_bp.delete("/api/users/<username>")
def delete_user_api(username: str):
    if username == service.current_username():
        return _api_error("You can't delete your own account while logged in as it.")
    try:
        store.delete_user(settings.users_db_path, username)
    except store.UnknownUser:
        return _api_error(f"No such user {username!r}.", 404)
    return jsonify({"status": "ok"})


@account_bp.post("/api/users/<username>/role")
def set_role_api(username: str):
    data = json_body()
    role = (data.get("role") or "").strip()
    if not role:
        return _api_error("Role is required.")
    try:
        store.set_user_role(settings.users_db_path, username, role)
    except store.UnknownUser:
        return _api_error(f"No such user {username!r}.", 404)
    except store.UnknownRole:
        return _api_error(f"Role {role!r} does not exist.")
    return jsonify({"status": "ok"})


@account_bp.post("/api/roles")
def create_role_api():
    data = json_body()
    name = (data.get("name") or "").strip()
    scopes = set(data.get("scopes") or [])
    if not name:
        return _api_error("Role name is required.")

    try:
        store.create_role(settings.users_db_path, name, scopes, created_by=service.current_username())
    except store.RoleTaken:
        return _api_error(f"Role {name!r} already exists.")
    except store.InvalidScope as exc:
        return _api_error(f"Unknown scope(s): {exc}.")
    return jsonify({"status": "ok"}), 201


@account_bp.delete("/api/roles/<name>")
def delete_role_api(name: str):
    try:
        store.delete_role(settings.users_db_path, name)
    except store.ProtectedRole:
        return _api_error(f"{name!r} is a built-in role and can't be deleted.")
    except store.RoleInUse:
        return _api_error(f"Role {name!r} is still assigned to a user or an outstanding invite.")
    except store.UnknownRole:
        return _api_error(f"No such role {name!r}.", 404)
    return jsonify({"status": "ok"})


@account_bp.post("/api/invites")
def create_invite_api():
    """The admin-facing invite form: pick the role the code grants and,
    optionally, how many hours until it expires. Contrast auth.create_invite,
    the plain member-role, never-expiring code any user can mint for
    themselves."""
    data = json_body()
    role = (data.get("role") or "").strip() or permissions.DEFAULT_ROLE
    ttl_hours = data.get("ttl_hours")
    try:
        ttl_hours = float(ttl_hours) if ttl_hours not in (None, "") else None
    except (TypeError, ValueError):
        return _api_error("ttl_hours must be a number.")
    if ttl_hours is not None and ttl_hours <= 0:
        return _api_error("ttl_hours must be positive.")

    try:
        issued = store.create_invite_code(
            settings.users_db_path, created_by=service.current_username(), role=role, ttl_hours=ttl_hours
        )
    except store.UnknownRole:
        return _api_error(f"Role {role!r} does not exist.")
    return (
        jsonify(
            {
                "code_id": issued.code_id,
                "code": issued.code,
                "role": issued.role,
                "created_by": issued.created_by,
                "created_at": issued.created_at,
                "expires_at": issued.expires_at,
            }
        ),
        201,
    )


@account_bp.delete("/api/invites/<code_id>")
def delete_invite_api(code_id: str):
    try:
        store.delete_invite_code(settings.users_db_path, code_id)
    except store.UnknownInvite:
        return _api_error(f"No such invite {code_id!r}.", 404)
    return jsonify({"status": "ok"})
