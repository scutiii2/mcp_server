"""Login sessions, and checking credentials against either the
env-configured default user or a runtime account in users.db."""

from __future__ import annotations

import os
import secrets

from flask import session

from chat_app.auth import permissions, store
from chat_app.config import settings


_SESSION_KEY = "username"


def _admin_credentials() -> tuple[str, str] | None:
    """The default account, or None if it isn't configured.

    Read with plain os.getenv() rather than through the frozen Settings
    dataclass - see config.py's comment on users_db_path for why - and
    both-or-neither like security.configured_credentials(): a username
    with no password (or vice versa) is a half-finished setup, and
    guessing which way to treat it is worse than just requiring both.
    """
    user = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if user and password:
        return user, password
    return None


def login_configured() -> bool:
    """Whether the default admin account is set up.

    Login itself is always required (security.check_login has no
    unconfigured fallback) - this only says whether *that one particular
    account* exists. Used by run.py's startup guard (can_anyone_log_in)
    and by anything that wants to know specifically about the admin
    account rather than "is anyone able to log in at all", which also
    accounts for accounts already in users.db.
    """
    return _admin_credentials() is not None


def can_anyone_log_in() -> bool:
    """False only when literally nobody could ever authenticate: no admin
    account and an empty users.db. Since login is mandatory with no
    fallback, that combination is a dead deployment - see run.py, which
    refuses to start rather than boot into one."""
    return login_configured() or store.any_users_exist(settings.users_db_path)


def current_username() -> str | None:
    return session.get(_SESSION_KEY)


def is_authenticated() -> bool:
    return _SESSION_KEY in session


def login(username: str) -> None:
    # Cleared first: switching accounts in one browser (log out, log back
    # in as someone else) must not leave anything from the old session
    # behind.
    session.clear()
    session[_SESSION_KEY] = username
    session.permanent = True


def logout() -> None:
    session.clear()


def check_credentials(username: str, password: str) -> bool:
    """True if username/password match the default admin user or an
    account created via an invite code.

    The admin username is checked with compare_digest even though it
    isn't a secret, for the same reason security.check_auth compares both
    halves that way: consistency means nobody reviewing this has to work
    out whether skipping it here is actually safe.
    """
    admin = _admin_credentials()
    if admin is not None:
        admin_user, admin_password = admin
        if secrets.compare_digest(username, admin_user):
            return secrets.compare_digest(password, admin_password)
    return store.verify_user(settings.users_db_path, username, password)


def is_root() -> bool:
    """True only for the literal env-configured account - never a DB row,
    regardless of what role that row names. This is what makes root
    "always highest" structural rather than just a big rank number: it's
    checked independently of current_role(), so current_rank() can give
    it an unbounded rank even though its role name (EXECUTIVE_ROLE) is
    shared with any other user promoted to executive."""
    username = current_username()
    if username is None:
        return False
    admin = _admin_credentials()
    return admin is not None and secrets.compare_digest(username, admin[0])


def current_role() -> str | None:
    """The logged-in user's role name, or None if nobody is logged in, or
    if the session names an account that no longer exists (deleted since
    the cookie was issued) - see security.check_role_permission, which
    treats that None the same as "not logged in" and clears the session.

    The env admin is checked first and never touches the database: it
    isn't a row in ``users``, so a query for it would always miss. Its
    role is EXECUTIVE_ROLE, not ADMIN_ROLE - the whole point of this
    account is to be the one guaranteed-present executive (see
    is_root()/current_rank() for how it stays above every other
    executive too, not just above admin).
    """
    username = current_username()
    if username is None:
        return None
    admin = _admin_credentials()
    if admin is not None and secrets.compare_digest(username, admin[0]):
        return permissions.EXECUTIVE_ROLE
    return store.get_user_role(settings.users_db_path, username)


def current_scopes() -> set[str] | None:
    """The logged-in user's granted scopes, or None under the same
    conditions as current_role()."""
    role = current_role()
    if role is None:
        return None
    if role == permissions.ADMIN_ROLE:
        return set(permissions.SCOPES)
    raw = store.get_role_scopes(settings.users_db_path, role)
    if raw is None:
        # The role itself was deleted out from under this user. Shouldn't
        # happen - delete_role() refuses a role still assigned to anyone -
        # but treat it the same as "no account" rather than crashing.
        return None
    return permissions.parse_scopes(raw)


def is_admin() -> bool:
    return current_role() == permissions.ADMIN_ROLE


def is_executive() -> bool:
    return current_role() == permissions.EXECUTIVE_ROLE


def current_rank() -> int | None:
    """The logged-in user's authority for ranked-role decisions (see
    pages/account/routes.py's promote/demote/delete checks) - None means
    "unbounded", not "zero"; callers compare with ``is None or n < rank``,
    never plain ``<``, or root would rank below everyone instead of above.

    Root gets None (unbounded) rather than a number one higher than
    EXECUTIVE_ROLE's rank, because a number can always be matched by
    seeding ROLE_RANK with something higher - None can't be out-ranked by
    any future tier added to that table. This is what makes "root is
    always highest" hold even against another executive with the same
    role name.
    """
    if is_root():
        return None
    # Not "None" here - that's reserved for root/unbounded above, and
    # every real caller of this is already behind security.check_login
    # (route handlers this feeds all require a session to be reached at
    # all), so this is a safe-default dead branch, not a real case: rank
    # 0 is the LEAST authority a missing role could imply, the opposite
    # of what None would mean here.
    return permissions.role_rank(current_role() or "")
