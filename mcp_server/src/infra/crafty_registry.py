"""SQLite-backed registry of Crafty Controller worlds.

Owned exclusively by ``capabilities/crafty/`` - nothing else calls this
module, on the same footing as ``infra/otp.py``'s exclusive ownership by
``capabilities/otp/`` (see ``infra/README.md``).

This is where a registered world's API token lives. It is deliberately
**not** written into a ``config_*.json`` file: every other loader in
``infra/app_config.py`` keeps config free of secrets by having it only
*name* an environment variable (``${VAR}``), but a token handed to
``crafty_world_register_tool`` at runtime has no environment variable to
name - it's supplied live, by whichever caller is registering the world.
A local SQLite file (regenerated per deployment, covered by this repo's
blanket ``*.db`` gitignore rule) is the closest equivalent: it keeps the
token out of a file that gets committed, diffed, or casually opened,
without inventing a second secrets-injection mechanism just for this one
capability.

``register`` is an upsert (``INSERT OR REPLACE``) rather than refusing a
duplicate name: re-registering an existing world - to rotate its token,
or point it at a different Crafty instance - is a normal operation, not
a mistake to guard against.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorldRecord:
    name: str
    base_url: str
    server_id: str
    api_token: str
    verify_ssl: bool


@dataclass(frozen=True)
class DefaultConfig:
    base_url: str
    verify_ssl: bool


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS worlds (
            name TEXT PRIMARY KEY,
            base_url TEXT NOT NULL,
            server_id TEXT NOT NULL,
            api_token TEXT NOT NULL,
            verify_ssl INTEGER NOT NULL
        )
        """
    )
    # Single-row table (id is always 1) holding the operator-set default
    # base_url/verify_ssl that crafty_world_register_tool falls back to
    # when a call doesn't supply its own - see set_default/get_default
    # and domain.register_world's precedence order.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS default_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            base_url TEXT NOT NULL,
            verify_ssl INTEGER NOT NULL
        )
        """
    )
    return conn


def _row_to_record(row: tuple) -> WorldRecord:
    name, base_url, server_id, api_token, verify_ssl = row
    return WorldRecord(
        name=name,
        base_url=base_url,
        server_id=server_id,
        api_token=api_token,
        verify_ssl=bool(verify_ssl),
    )


def register(
    db_path: Path,
    name: str,
    *,
    server_id: str,
    api_token: str,
    base_url: str,
    verify_ssl: bool,
) -> WorldRecord:
    """Insert or overwrite one world's registration, keyed by name."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO worlds (name, base_url, server_id, api_token, verify_ssl) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, base_url, server_id, api_token, int(verify_ssl)),
        )
        conn.commit()
    finally:
        conn.close()
    return WorldRecord(
        name=name, base_url=base_url, server_id=server_id, api_token=api_token, verify_ssl=verify_ssl
    )


def get(db_path: Path, name: str) -> WorldRecord:
    """One world by name, with the available names listed if it's not
    there - the caller is usually a model that guessed, same convention
    as ``app_config.load_host_config``."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT name, base_url, server_id, api_token, verify_ssl FROM worlds WHERE name = ?",
            (name,),
        ).fetchone()
        if row is not None:
            return _row_to_record(row)

        known = [r[0] for r in conn.execute("SELECT name FROM worlds ORDER BY name")]
    finally:
        conn.close()

    if known:
        raise KeyError(f"No world named {name!r} is registered. Registered worlds: {', '.join(known)}.")
    raise KeyError(f"No world named {name!r} is registered. No worlds are registered at all.")


def remove(db_path: Path, name: str) -> None:
    """Delete one world's registration. Raises the same "unknown name"
    error as ``get`` when there's nothing to delete, rather than being
    idempotent - every other function in this module that takes a world
    name fails the same way on one it doesn't recognize, and a silent
    no-op here would be the one exception a caller has to remember."""
    conn = _connect(db_path)
    try:
        cursor = conn.execute("DELETE FROM worlds WHERE name = ?", (name,))
        conn.commit()
        if cursor.rowcount:
            return

        known = [r[0] for r in conn.execute("SELECT name FROM worlds ORDER BY name")]
    finally:
        conn.close()

    if known:
        raise KeyError(f"No world named {name!r} is registered. Registered worlds: {', '.join(known)}.")
    raise KeyError(f"No world named {name!r} is registered. No worlds are registered at all.")


def list_all(db_path: Path) -> list[WorldRecord]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name, base_url, server_id, api_token, verify_ssl FROM worlds ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_record(row) for row in rows]


def set_default(db_path: Path, *, base_url: str, verify_ssl: bool) -> DefaultConfig:
    """Set (or overwrite) the default base_url/verify_ssl that
    ``crafty_world_register_tool`` falls back to. Idempotent - calling
    this again simply replaces the previous default."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO default_config (id, base_url, verify_ssl) VALUES (1, ?, ?)",
            (base_url, int(verify_ssl)),
        )
        conn.commit()
    finally:
        conn.close()
    return DefaultConfig(base_url=base_url, verify_ssl=verify_ssl)


def get_default(db_path: Path) -> DefaultConfig | None:
    """The stored default, or None if it has never been set - the
    caller (``domain.register_world``) is the one that knows what to
    fall back to next (an environment variable, or refusing outright)."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT base_url, verify_ssl FROM default_config WHERE id = 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return DefaultConfig(base_url=row[0], verify_ssl=bool(row[1]))
