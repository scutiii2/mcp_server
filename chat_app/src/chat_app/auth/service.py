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


def network_gate_enabled() -> bool:
    """Whether the network gate (security.check_auth) is switched on at
    all - kept separate from what satisfies it once active, because
    ADMIN_USERNAME/PASSWORD is mandatory in every deployment: if "an admin
    account exists" alone were enough, every deployment would become
    reachable off-loopback automatically. Three independent signals, any
    one of which switches it on:

    1. The shared CHAT_AUTH_USER/PASSWORD pair - read directly here
       (rather than importing security.configured_credentials, which
       would be a circular import: security already imports from this
       module) with the same both-or-neither treatment.
    2. At least one currently-valid gate code - an admin minting one is
       itself a deliberate act, same reasoning as configuring the pair.
    3. CHAT_NETWORK_ACCESS_ENABLED (any non-empty value) - the explicit
       "real accounts alone, no shared secret" opt-in.
    """
    if os.getenv("CHAT_AUTH_USER") and os.getenv("CHAT_AUTH_PASSWORD"):
        return True
    if store.any_gate_code_valid(settings.users_db_path):
        return True
    return bool(os.getenv("CHAT_NETWORK_ACCESS_ENABLED"))


def gate_code_grants_access(code: str) -> bool:
    return store.gate_code_is_valid(settings.users_db_path, code)


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
        # .encode() before compare_digest: it raises TypeError on non-ASCII
        # str input (works fine on bytes), and Basic Auth credentials are
        # attacker-controlled - a non-ASCII username/password must fail
        # the comparison, not crash the request with a 500.
        if secrets.compare_digest(username.encode(), admin_user.encode()):
            return secrets.compare_digest(password.encode(), admin_password.encode())
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
    return admin is not None and secrets.compare_digest(username.encode(), admin[0].encode())


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
    if admin is not None and secrets.compare_digest(username.encode(), admin[0].encode()):
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
