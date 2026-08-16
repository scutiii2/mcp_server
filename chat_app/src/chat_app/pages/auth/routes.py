"""Login, registration, logout, and invite-code minting.

This blueprint owns everything under ``pages/auth/`` - see
``pages/chat/routes.py``/``app.py`` for why the static/template wiring
looks the way it does. Its own pages (login/register, GET and POST) are
the routes exempted from the app-wide login gate in
``security.check_login`` - everything else here, including
``create_invite``, stays gated like any other route.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from chat_app.auth import permissions, service, store
from chat_app.config import settings


auth_bp = Blueprint(
    "auth",
    __name__,
    static_folder="template",
    static_url_path="/pages/auth/assets",
)


def _safe_next(candidate: str | None) -> str:
    """Only ever redirect back to a same-app path. An unchecked ?next=
    would be an open redirect: a link to /login?next=https://evil.example
    would bounce a successful login straight at an attacker's site."""
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return url_for("overview.index")


@auth_bp.get("/login")
def login_page():
    if service.is_authenticated():
        return redirect(url_for("overview.index"))
    return render_template("auth/login.html", error=None, next=request.args.get("next", ""))


@auth_bp.post("/login")
def login_submit():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    next_path = _safe_next(request.form.get("next"))

    if not username or not password or not service.check_credentials(username, password):
        return render_template("auth/login.html", error="Invalid username or password.", next=next_path), 401

    service.login(username)
    return redirect(next_path)


@auth_bp.get("/logout")
def logout():
    service.logout()
    return redirect(url_for("auth.login_page"))


@auth_bp.get("/register")
def register_page():
    if service.is_authenticated():
        return redirect(url_for("overview.index"))
    return render_template("auth/register.html", error=None)


@auth_bp.post("/register")
def register_submit():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    invite_code = (request.form.get("invite_code") or "").strip()

    error = None
    if not username or not password or not invite_code:
        error = "Username, password, and invite code are all required."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."

    if error is None:
        try:
            store.register_user(settings.users_db_path, username, password, invite_code)
        except store.InvalidInviteCode:
            error = "That invite code is invalid or has already been used."
        except store.UsernameTaken:
            error = "That username is already taken."

    if error:
        return render_template("auth/register.html", error=error), 400

    service.login(username)
    return redirect(url_for("overview.index"))


@auth_bp.post("/api/invites")
def create_invite():
    """Mint a never-expiring, member-role invite code as the logged-in
    user. Gated by the app-wide role check like every other route here
    (the "invites" scope - see auth/permissions.py) so there is no way to
    reach this without already having an account that grants it.

    This is the simple, no-options version any member can use from the
    overview page or the sidebar. An admin who wants to pick a role or an
    expiry uses the account manager's own invite form instead - see
    pages/account/routes.py.

    Same response shape as that endpoint's create_invite_api (code_id,
    role, created_by, created_at, expires_at alongside code) even though
    the sidebar/overview callers only read ``code`` - sidebar.js also
    calls into account/script.js's prependInviteRow() with this whole
    payload when it finds itself on the account manager page, so a code
    generated from the sidebar while that page is open shows up in its
    invite list immediately, the same as one generated from the page's
    own form.
    """
    issued = store.create_invite_code(
        settings.users_db_path, created_by=service.current_username(), role=permissions.DEFAULT_ROLE
    )
    return jsonify(
        {
            "code_id": issued.code_id,
            "code": issued.code,
            "role": issued.role,
            "created_by": issued.created_by,
            "created_at": issued.created_at,
            "expires_at": issued.expires_at,
        }
    )
