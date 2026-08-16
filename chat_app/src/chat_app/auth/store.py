"""Runtime-created accounts, roles, and the invite codes that unlock them.

Registration is invite-gated: the only way into ``users`` is through a
code minted by someone who can already log in (see ``create_invite_code``),
so there is no path to an account that doesn't trace back to an existing
one - the env-configured default admin, ultimately. Same connection style
and stdlib-first choice as ``mcp_server/infra/otp.py``: plain ``sqlite3``,
no ORM, secrets hashed rather than stored, atomic claims done as a single
UPDATE so two concurrent requests can't both win the same invite code.

Passwords are hashed with ``hashlib.scrypt`` (memory-hard, unlike a plain
salted SHA-256) since - unlike the six-digit OTPs in ``otp.py``, which are
defended by a short clock and an attempt limit - a stolen password
database is exactly the scenario this has to survive on its own, and
people reuse passwords across services. Invite codes get the lighter
HMAC-SHA256 treatment that ``otp.py`` uses for its codes: they're
high-entropy (``secrets.token_urlsafe``, not typed from memory) and
single-use, so a slow hash would only cost CPU for no real defense.

Roles are a name plus a comma-separated set of scope keys from
``auth/permissions.py``; ``"admin"`` is seeded with the literal value
``"*"`` (every current and future scope - see ``permissions.parse_scopes``)
and can't be deleted, so there is always at least one role that can reach
the account manager and repair a misconfigured deployment.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chat_app.auth import permissions


# scrypt cost parameters. N=2**14 (16384) is the interactive-login setting
# from the algorithm's own RFC (7914) - roughly 15-20ms per hash on modern
# hardware, cheap enough that a login request doesn't stall, expensive
# enough that hashing a large stolen table stays slow.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LENGTH = 32


class UsernameTaken(Exception):
    """Raised when the username already exists."""


class InvalidInviteCode(Exception):
    """Raised when a code is unknown, already used, or expired."""


class UnknownUser(Exception):
    """Raised when an operation names a username that doesn't exist."""


class UnknownRole(Exception):
    """Raised when an operation names a role that doesn't exist."""


class RoleTaken(Exception):
    """Raised by create_role() when the name already exists."""


class InvalidScope(Exception):
    """Raised by create_role() when given a scope key not in permissions.SCOPES."""


class ProtectedRole(Exception):
    """Raised by delete_role() for the built-in admin role."""


class RoleInUse(Exception):
    """Raised by delete_role() when a user or a live invite still references it."""


class UnknownInvite(Exception):
    """Raised by delete_invite_code() when the code_id doesn't exist."""


def _hash_password(salt: bytes, password: str) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_LENGTH
    )


def _password_matches(salt: bytes, stored_hash: bytes, password: str) -> bool:
    return secrets.compare_digest(stored_hash, _hash_password(salt, password))


def _hash_invite_code(salt: bytes, code: str) -> bytes:
    return hmac.new(salt, code.encode("utf-8"), hashlib.sha256).digest()


def _invite_code_matches(salt: bytes, stored_hash: bytes, code: str) -> bool:
    return secrets.compare_digest(stored_hash, _hash_invite_code(salt, code))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            name TEXT PRIMARY KEY,
            scopes TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            salt BLOB NOT NULL,
            password_hash BLOB NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invite_codes (
            code_id TEXT PRIMARY KEY,
            salt BLOB NOT NULL,
            code_hash BLOB NOT NULL,
            role TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            used_by TEXT,
            used_at TEXT
        )
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO roles (name, scopes, created_by, created_at) VALUES (?, '*', 'system', ?)",
        (permissions.ADMIN_ROLE, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO roles (name, scopes, created_by, created_at) VALUES (?, ?, 'system', ?)",
        (permissions.DEFAULT_ROLE, permissions.format_scopes(set(permissions.SCOPES) - {"accounts"}), now),
    )
    # Registered so the comparison happens inside SQL, letting verify_user
    # and register_user express "does this row's secret match" as part of
    # a WHERE clause instead of pulling the hash out and comparing in
    # Python after the fact.
    conn.create_function("password_matches", 3, _password_matches, deterministic=True)
    conn.create_function("invite_code_matches", 3, _invite_code_matches, deterministic=True)
    conn.commit()
    return conn


# --- roles -----------------------------------------------------------------


def list_roles(db_path: Path) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT name, scopes, created_by, created_at FROM roles ORDER BY name").fetchall()
    finally:
        conn.close()
    return [
        {"name": name, "scopes": permissions.parse_scopes(scopes), "created_by": created_by, "created_at": created_at}
        for name, scopes, created_by, created_at in rows
    ]


def get_role_scopes(db_path: Path, name: str) -> str | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT scopes FROM roles WHERE name = ?", (name,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def create_role(db_path: Path, name: str, scopes: set[str], created_by: str) -> None:
    unknown = scopes - set(permissions.SCOPES)
    if unknown:
        raise InvalidScope(", ".join(sorted(unknown)))
    conn = _connect(db_path)
    try:
        try:
            conn.execute(
                "INSERT INTO roles (name, scopes, created_by, created_at) VALUES (?, ?, ?, ?)",
                (name, permissions.format_scopes(scopes), created_by, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise RoleTaken(name) from None
    finally:
        conn.close()


def delete_role(db_path: Path, name: str) -> None:
    if name == permissions.ADMIN_ROLE:
        raise ProtectedRole(name)
    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM roles WHERE name = ?", (name,)).fetchone() is None:
            raise UnknownRole(name)

        in_use_by_users = conn.execute("SELECT 1 FROM users WHERE role = ?", (name,)).fetchone() is not None
        now = datetime.now(timezone.utc).isoformat()
        # Every row still in invite_codes is by definition unredeemed -
        # register_user() deletes a code's row the moment it's used, so
        # there's no "used but still present" state left to filter out
        # here the way an earlier version of this query had to.
        in_use_by_invites = (
            conn.execute(
                "SELECT 1 FROM invite_codes WHERE role = ? AND (expires_at IS NULL OR expires_at > ?)",
                (name, now),
            ).fetchone()
            is not None
        )
        if in_use_by_users or in_use_by_invites:
            raise RoleInUse(name)

        conn.execute("DELETE FROM roles WHERE name = ?", (name,))
        conn.commit()
    finally:
        conn.close()


# --- users -------------------------------------------------------------


def list_users(db_path: Path) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT username, role, created_at, created_by FROM users ORDER BY username"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"username": username, "role": role, "created_at": created_at, "created_by": created_by}
        for username, role, created_at, created_by in rows
    ]


def any_users_exist(db_path: Path) -> bool:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def get_user_role(db_path: Path, username: str) -> str | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def verify_user(db_path: Path, username: str, password: str) -> bool:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT salt, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            # Hash something anyway, so a request for a nonexistent user
            # doesn't return measurably faster than one for a real user
            # with the wrong password - otherwise the response time alone
            # lets an attacker enumerate valid usernames.
            _hash_password(secrets.token_bytes(16), password)
            return False
        salt, password_hash = row
        return _password_matches(salt, password_hash, password)
    finally:
        conn.close()


def create_user_direct(db_path: Path, username: str, password: str, role: str, created_by: str) -> None:
    """An admin creating an account outright, bypassing the invite flow."""
    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM roles WHERE name = ?", (role,)).fetchone() is None:
            raise UnknownRole(role)
        salt = secrets.token_bytes(16)
        try:
            conn.execute(
                "INSERT INTO users (username, salt, password_hash, role, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, salt, _hash_password(salt, password), role, datetime.now(timezone.utc).isoformat(), created_by),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise UsernameTaken(username) from None
    finally:
        conn.close()


def delete_user(db_path: Path, username: str) -> None:
    conn = _connect(db_path)
    try:
        deleted = conn.execute("DELETE FROM users WHERE username = ?", (username,)).rowcount
        conn.commit()
        if deleted == 0:
            raise UnknownUser(username)
    finally:
        conn.close()


def set_user_role(db_path: Path, username: str, role: str) -> None:
    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM roles WHERE name = ?", (role,)).fetchone() is None:
            raise UnknownRole(role)
        updated = conn.execute("UPDATE users SET role = ? WHERE username = ?", (role, username)).rowcount
        conn.commit()
        if updated == 0:
            raise UnknownUser(username)
    finally:
        conn.close()


# --- invite codes --------------------------------------------------------


@dataclass(frozen=True)
class IssuedInvite:
    """What create_invite_code() hands back. ``code`` exists here and
    nowhere else - only its salted HMAC is stored (see module docstring).

    The rest of the fields mirror a row from list_invite_codes() so a
    caller (see pages/account/routes.py's create_invite_api) can hand the
    whole thing to the frontend and have it render one immediately, in
    the same shape as the server-rendered rows - except this one, uniquely,
    still has its code.
    """

    code_id: str
    code: str
    role: str
    created_by: str
    created_at: str
    expires_at: str | None


def create_invite_code(
    db_path: Path, created_by: str, role: str, ttl_hours: float | None = None
) -> IssuedInvite:
    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM roles WHERE name = ?", (role,)).fetchone() is None:
            raise UnknownRole(role)

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat() if ttl_hours else None
        code = secrets.token_urlsafe(9)
        code_id = secrets.token_urlsafe(12)
        salt = secrets.token_bytes(16)
        conn.execute(
            "INSERT INTO invite_codes (code_id, salt, code_hash, role, created_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (code_id, salt, _hash_invite_code(salt, code), role, created_by, now_iso, expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    return IssuedInvite(
        code_id=code_id, code=code, role=role, created_by=created_by, created_at=now_iso, expires_at=expires_at
    )


def list_invite_codes(db_path: Path) -> list[dict]:
    """Still-outstanding invite codes. Redeeming one deletes its row (see
    register_user) rather than marking it used, so nothing returned here
    has ever been redeemed - only unused, though possibly expired. Never
    the plaintext either way, which exists nowhere but the IssuedInvite
    returned at creation time."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT code_id, role, created_by, created_at, expires_at, used_by, used_at "
            "FROM invite_codes ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "code_id": code_id,
            "role": role,
            "created_by": created_by,
            "created_at": created_at,
            "expires_at": expires_at,
            "used_by": used_by,
            "used_at": used_at,
        }
        for code_id, role, created_by, created_at, expires_at, used_by, used_at in rows
    ]


def delete_invite_code(db_path: Path, code_id: str) -> None:
    """Revoke an invite code before anyone redeems it, or clear out one
    that's expired unused - the only two states a row here can be in,
    since register_user() deletes a code's row itself the moment it's
    redeemed. There's nothing to protect the way delete_role() protects a
    role still in use: nothing downstream reads this row again once it's
    gone."""
    conn = _connect(db_path)
    try:
        deleted = conn.execute("DELETE FROM invite_codes WHERE code_id = ?", (code_id,)).rowcount
        conn.commit()
        if deleted == 0:
            raise UnknownInvite(code_id)
    finally:
        conn.close()


def register_user(db_path: Path, username: str, password: str, invite_code: str) -> None:
    """Redeem an invite code and create the account it unlocks, with the
    role the code was minted for.

    Both happen on one connection so a code that turns out not to win -
    already claimed by a racing request, expired, or a username that's
    taken - is rolled back rather than burned for nothing. Redeeming
    deletes the code's row outright rather than marking it used: once
    consumed, a code can't be redeemed again either way, so there's
    nothing left for a lingering "used" row to mean except clutter in the
    account manager's invite list - ``users.created_by`` already records
    who invited whom, which is the fact actually worth keeping. The claim
    itself is a single DELETE keyed on ``code_id``: SQLite serializes
    writers against the same database file, so of two requests redeeming
    the same code, the second one's DELETE always affects zero rows,
    matching ``otp.verify``'s reasoning for doing a claim as one statement
    rather than a check-then-write.
    """
    conn = _connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            "SELECT code_id, role, created_by FROM invite_codes "
            "WHERE (expires_at IS NULL OR expires_at > ?) AND invite_code_matches(salt, code_hash, ?)",
            (now, invite_code),
        ).fetchone()
        if row is None:
            raise InvalidInviteCode()
        code_id, role, invited_by = row

        won = conn.execute("DELETE FROM invite_codes WHERE code_id = ?", (code_id,)).rowcount
        if won != 1:
            conn.rollback()
            raise InvalidInviteCode()

        # Guards against the role being deleted between the SELECT above
        # and here - shouldn't happen (delete_role refuses a role with a
        # live invite outstanding), but this is the last gate before an
        # account referencing a nonexistent role would be created.
        if conn.execute("SELECT 1 FROM roles WHERE name = ?", (role,)).fetchone() is None:
            conn.rollback()
            raise InvalidInviteCode()

        salt = secrets.token_bytes(16)
        try:
            conn.execute(
                "INSERT INTO users (username, salt, password_hash, role, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, salt, _hash_password(salt, password), role, now, invited_by),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            raise UsernameTaken(username) from None
        conn.commit()
    finally:
        conn.close()
