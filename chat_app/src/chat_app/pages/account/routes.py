"""Account manager: create/remove users, assign roles, define custom
roles, and mint invite codes with a chosen role and expiry.

Reachable only by whoever's role grants the "accounts" scope (see
auth/permissions.py) - the env admin always has it; a custom role only has
it if an admin explicitly checked that box when creating the role. This
blueprint owns everything under ``pages/account/`` - see
``pages/chat/routes.py``/``app.py`` for why the static/template wiring
looks the way it does.

Granting/revoking a RANKED role (admin, executive - see
auth/permissions.ROLE_RANK) is gated on top of the "accounts" scope
check above: create_user_api, set_role_api, and create_invite_api all
require the acting user's rank (auth/service.current_rank()) to be high
enough, via _can_grant()/_can_act_on() below. Assigning member or any
custom (unranked) role stays governed by "accounts" scope alone, same as
before this existed - the whole point is protecting the two tiers that
form an actual hierarchy, not re-gating everything this page already did.
"""

from __future__ import annotations

import math

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


def _can_grant(actor_rank: int | None, role_name: str) -> bool:
    """Can the actor set someone's role TO role_name?

    None (root) is unbounded. Otherwise strictly-higher rank is required
    for every ranked role EXCEPT executive itself, which only needs
    at-or-above: any executive must be able to grant the executive role
    to someone else (that's the specific ask EXECUTIVE_ROLE exists to
    satisfy - see its docstring), but the same "at or above" logic must
    NOT generalize to admin, or a plain admin could grant admin to a
    peer, undoing the whole point of ranking admin at all.
    """
    if actor_rank is None:
        return True
    target_rank = permissions.role_rank(role_name)
    if role_name == permissions.EXECUTIVE_ROLE:
        return actor_rank >= target_rank
    return actor_rank > target_rank


def _can_act_on(actor_rank: int | None, current_role_name: str) -> bool:
    """Can the actor change or delete a user CURRENTLY holding
    current_role_name? None (root) is unbounded; otherwise strictly
    above that role's rank - strictly, so two same-rank executives can't
    touch each other's account at all (only root can, or the user
    themselves via set_role_api's self-demotion carve-out)."""
    return actor_rank is None or permissions.role_rank(current_role_name) < actor_rank


@account_bp.get("/")
def manage_page():
    # Login is mandatory app-wide (security.check_login has no
    # unconfigured fallback), so reaching this view at all guarantees a
    # session - current_scopes() can't return None here.
    roles = store.list_roles(settings.users_db_path)
    viewer_rank = service.current_rank()
    return render_template(
        "account/index.html",
        scopes=service.current_scopes() or set(),
        is_executive=service.is_executive(),
        current_page="account",
        username=service.current_username(),
        role=service.current_role(),
        users=store.list_users(settings.users_db_path),
        roles=roles,
        # Plain numeric rank, for script.js's self-demotion comparison
        # ("is my new choice lower than my current role?") - a simple
        # ordering question, unlike the asymmetric assignable_roles below.
        # Keyed by name rather than adding a "rank" field to
        # store.list_roles() itself, which every OTHER caller of that
        # function would then have to ignore.
        role_ranks={r["name"]: permissions.role_rank(r["name"]) for r in roles},
        # Whether the VIEWER could grant each role to someone right now -
        # reuses _can_grant() itself (not a separate rank comparison in
        # the template) specifically so this can never drift out of sync
        # with what the API actually enforces; see _can_grant's docstring
        # for why this isn't just "role_ranks[name] <= viewer_rank".
        assignable_roles={r["name"]: _can_grant(viewer_rank, r["name"]) for r in roles},
        invites=store.list_invite_codes(settings.users_db_path),
        gate_codes=store.list_gate_codes(settings.users_db_path),
        scope_catalog=[{"key": key, "label": entry["label"]} for key, entry in permissions.SCOPES.items()],
        admin_role=permissions.ADMIN_ROLE,
        executive_role=permissions.EXECUTIVE_ROLE,
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
    if not _can_grant(service.current_rank(), role):
        return _api_error(f"You don't have permission to grant the {role!r} role.", 403)

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
    # Deliberately checked even though this user may not exist - a rank
    # check that only ran on a successful lookup would be a no-op for
    # nonexistent usernames anyway (store.delete_user raises UnknownUser
    # below regardless), so there's no ordering issue either way.
    current = store.get_user_role(settings.users_db_path, username)
    if current is not None and not _can_act_on(service.current_rank(), current):
        return _api_error("You don't have permission to delete this user.", 403)
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

    current = store.get_user_role(settings.users_db_path, username)
    if current is not None:
        # The one exception to "only a strictly-higher rank can act on
        # you": lowering your OWN rank, allowed unconditionally - see
        # pages/account/template/script.js's confirmModal() for the
        # warning shown before this request is ever sent. Anything else
        # (raising your own rank, touching someone else) goes through the
        # normal checks below same as any other actor.
        self_demotion = (
            username == service.current_username()
            and permissions.role_rank(role) < permissions.role_rank(current)
        )
        if not self_demotion:
            actor_rank = service.current_rank()
            if not _can_act_on(actor_rank, current):
                return _api_error("You don't have permission to change this user's role.", 403)
            if not _can_grant(actor_rank, role):
                return _api_error(f"You don't have permission to grant the {role!r} role.", 403)

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
    if not _can_grant(service.current_rank(), role):
        # Checked at mint time, not re-checked at redemption - same
        # "trust the moment it was issued" trust model the rest of the
        # invite system already uses (a code minted while a role still
        # existed stays redeemable even if the minting admin's own access
        # changes later).
        return _api_error(f"You don't have permission to grant the {role!r} role.", 403)

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


@account_bp.post("/api/gate-codes")
def create_gate_code_api():
    """Mint a temporary Basic Auth password that satisfies the network
    gate without tying to any identity - see security.check_auth's third
    credential path. Admin-facing: TTL is a required choice (the account
    manager's own form offers 1/24/168 hours), unlike the invite form's
    optional "never expires" - a gate code with no expiry would
    contradict "temporary" by definition (see auth/store.py's schema).
    """
    data = json_body()
    try:
        ttl_hours = float(data.get("ttl_hours"))
    except (TypeError, ValueError):
        return _api_error("ttl_hours is required and must be a number.")
    # float() accepts "nan"/"inf"/huge strings without raising - none of
    # which the plain `<= 0` check below catches, and all of which crash
    # store.create_gate_code's timedelta(hours=...) with ValueError/
    # OverflowError instead of failing this request cleanly with a 400.
    if not math.isfinite(ttl_hours) or not (0 < ttl_hours <= 8760):  # 8760 hours = 1 year
        return _api_error("ttl_hours must be a positive number of hours, at most 8760 (1 year).")

    issued = store.create_gate_code(settings.users_db_path, created_by=service.current_username(), ttl_hours=ttl_hours)
    return (
        jsonify(
            {
                "code_id": issued.code_id,
                "code": issued.code,
                "created_by": issued.created_by,
                "created_at": issued.created_at,
                "expires_at": issued.expires_at,
            }
        ),
        201,
    )


@account_bp.delete("/api/gate-codes/<code_id>")
def delete_gate_code_api(code_id: str):
    try:
        store.delete_gate_code(settings.users_db_path, code_id)
    except store.UnknownGateCode:
        return _api_error(f"No such gate code {code_id!r}.", 404)
    return jsonify({"status": "ok"})
