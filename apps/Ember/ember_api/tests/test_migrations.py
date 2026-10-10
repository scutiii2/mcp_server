"""Schema migrations: a fresh database, one that predates them, and a later change."""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from src.db import Base, Database
from src.services.migrations import BASELINE, MIGRATIONS_DIR, MigrationRunner

# The newest real migration; the tests' throwaway one comes after it.
HEAD = "0012"
NEXT = "0013"


def drop_account_uid(conn: sqlite3.Connection) -> None:
    """Undo migration 0011 on a database built from the current models."""
    conn.execute("DROP INDEX ix_accounts_uid")
    conn.execute("ALTER TABLE accounts DROP COLUMN uid")


def test_permission_split_preserves_access_once_and_keeps_revocations(tmp_path: Path) -> None:
    run_with(make_database(tmp_path))
    path = tmp_path / "ember.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE alembic_version SET version_num = '0009'")
        drop_account_uid(conn)
        for name in ("admin.manage", "tools.use", "chat.use"):
            conn.execute("INSERT INTO roles (name) VALUES (?)", (name,))
            conn.execute("INSERT INTO permissions (name) VALUES (?)", (name,))
            conn.execute(
                "INSERT INTO role_permission SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.name = ? AND p.name = ?", (name, name)
            )
        conn.commit()

    assert run_with(make_database(tmp_path)) == "upgraded"

    def grants(name: str) -> set[str]:
        with closing(sqlite3.connect(path)) as conn:
            return {row[0] for row in conn.execute(
                "SELECT p.name FROM role_permission rp JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id WHERE r.name = ?", (name,)
            )}

    assert {"accounts.view", "roles.assign", "capabilities.manage", "usage.all.view"} <= grants("admin.manage")
    assert {"tools.view", "tools.execute", "files.upload", "files.download"} <= grants("tools.use")
    assert {"chat.share", "extensions.personal.manage", "tools.execute", "files.upload"} <= grants("chat.use")
    assert "files.download" not in grants("chat.use")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "DELETE FROM role_permission WHERE role_id = (SELECT id FROM roles WHERE name = 'chat.use') "
            "AND permission_id = (SELECT id FROM permissions WHERE name = 'chat.share')"
        )
        conn.commit()
    assert run_with(make_database(tmp_path)) == "current"
    assert "chat.share" not in grants("chat.use")


def test_ticket_permission_is_granted_to_chat_roles_once(tmp_path: Path) -> None:
    run_with(make_database(tmp_path))
    path = tmp_path / "ember.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE alembic_version SET version_num = '0011'")
        for name in ("chatters", "readers"):
            conn.execute("INSERT INTO roles (name) VALUES (?)", (name,))
        conn.execute("INSERT INTO permissions (name) VALUES ('chat.use')")
        conn.execute(
            "INSERT INTO role_permission SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.name = 'chatters' AND p.name = 'chat.use'"
        )
        conn.commit()

    assert run_with(make_database(tmp_path)) == "upgraded"

    def grants(name: str) -> set[str]:
        with closing(sqlite3.connect(path)) as conn:
            return {row[0] for row in conn.execute(
                "SELECT p.name FROM role_permission rp JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id WHERE r.name = ?", (name,)
            )}

    assert "tickets.create" in grants("chatters")
    assert "tickets.create" not in grants("readers")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "DELETE FROM role_permission WHERE role_id = (SELECT id FROM roles WHERE name = 'chatters') "
            "AND permission_id = (SELECT id FROM permissions WHERE name = 'tickets.create')"
        )
        conn.commit()
    assert run_with(make_database(tmp_path)) == "current"
    assert "tickets.create" not in grants("chatters")  # a later revocation sticks


def make_database(tmp_path: Path) -> Database:
    return Database(f"sqlite+aiosqlite:///{(tmp_path / 'ember.db').as_posix()}")


def drop_chat_folders(conn: sqlite3.Connection) -> None:
    """Take chat folders out of a database built from the models, as a legacy one lacks them.
    SQLite cannot drop a foreign-key column, so the (empty) chats table is made again as it was."""
    conn.execute("DROP TABLE chats")
    conn.execute("DROP TABLE chat_folders")
    conn.execute(
        "CREATE TABLE chats (id INTEGER NOT NULL, account_id INTEGER NOT NULL, chat_id VARCHAR(64) NOT NULL,"
        " title VARCHAR(120) NOT NULL, agent_id VARCHAR(120), messages TEXT NOT NULL,"
        " message_count INTEGER NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,"
        " PRIMARY KEY (id), UNIQUE (account_id, chat_id),"
        " FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE)"
    )
    conn.execute("CREATE INDEX ix_chats_updated_at ON chats (updated_at)")
    conn.execute("CREATE INDEX ix_chats_account_id ON chats (account_id)")


def tables_of(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def revision_of(path: Path) -> str | None:
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def run_with(database: Database, **kwargs) -> str:
    async def go() -> str:
        try:
            return await MigrationRunner(database.engine, **kwargs).run()
        finally:
            await database.dispose()

    return asyncio.run(go())


def differences(database: Database) -> list:
    async def go() -> list:
        try:
            async with database.engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync: compare_metadata(
                        MigrationContext.configure(sync, opts={"compare_type": True}), Base.metadata
                    )
                )
        finally:
            await database.dispose()

    from src import models  # noqa: F401

    return asyncio.run(go())


def test_account_uid_is_backfilled_unique_and_removed_by_the_downgrade(tmp_path: Path) -> None:
    run_with(make_database(tmp_path))
    path = tmp_path / "ember.db"
    with closing(sqlite3.connect(path)) as conn:
        drop_account_uid(conn)
        conn.execute("UPDATE alembic_version SET version_num = '0010'")
        for name in ("lex", "sam"):
            conn.execute(
                "INSERT INTO accounts (username, email, password_hash, is_protected, is_active, email_verified, created_at)"
                f" VALUES ('{name}', '{name}@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"
            )
        conn.execute("INSERT INTO roles (name) VALUES ('Keeper')")
        conn.execute("INSERT INTO account_role (account_id, role_id) SELECT a.id, r.id FROM accounts a, roles r WHERE a.username = 'lex' AND r.name = 'Keeper'")
        conn.execute(
            "INSERT INTO chats (account_id, chat_id, title, messages, message_count, pinned, created_at, updated_at)"
            " SELECT id, 'kept-chat', 'Keep my transcript', '[]', 0, 0, '2026-01-01', '2026-01-01' FROM accounts WHERE username = 'lex'"
        )
        children = {
            table: conn.execute(f"SELECT * FROM {table}").fetchall() for table in ("account_role", "chats")
        }
        conn.commit()

    assert run_with(make_database(tmp_path)) == "upgraded"

    with closing(sqlite3.connect(path)) as conn:
        for table, rows in children.items():
            assert conn.execute(f"SELECT * FROM {table}").fetchall() == rows
        uids = [row[0] for row in conn.execute("SELECT uid FROM accounts ORDER BY id")]
        assert len(uids) == 2 and len(set(uids)) == 2
        assert all(len(uid) == 32 and int(uid, 16) >= 0 for uid in uids)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO accounts (uid, username, email, password_hash, is_protected, is_active, email_verified, created_at)"
                f" VALUES ('{uids[0]}', 'dup', 'dup@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"
            )

    from alembic import command

    async def downgrade() -> None:
        database = make_database(tmp_path)
        runner = MigrationRunner(database.engine)
        try:
            async with database.engine.connect() as conn:
                await conn.run_sync(lambda sync: command.downgrade(runner._config(sync), "0010"))
                assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar() == 1
        finally:
            await database.dispose()

    asyncio.run(downgrade())

    assert revision_of(path) == "0010"
    with closing(sqlite3.connect(path)) as conn:
        assert "uid" not in {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
        for table, rows in children.items():
            assert conn.execute(f"SELECT * FROM {table}").fetchall() == rows
        conn.execute("INSERT INTO account_role (account_id, role_id) VALUES (9999, 1)")
        conn.commit()

    async def invalid_upgrade() -> None:
        database = make_database(tmp_path)
        try:
            with pytest.raises(RuntimeError, match="invalid foreign key references"):
                await MigrationRunner(database.engine).run()
            async with database.engine.connect() as conn:
                assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar() == 1
        finally:
            await database.dispose()

    asyncio.run(invalid_upgrade())


class TestFreshDatabase:
    def test_the_migrations_build_every_table(self, tmp_path: Path) -> None:
        database = make_database(tmp_path)

        assert run_with(database) == "created"

        from src import models  # noqa: F401

        assert tables_of(tmp_path / "ember.db") == set(Base.metadata.tables) | {"alembic_version"}

    def test_the_migrations_match_the_models_exactly(self, tmp_path: Path) -> None:
        """Fails when a model is edited without a migration for it."""
        run_with(make_database(tmp_path))

        assert differences(make_database(tmp_path)) == []

    def test_a_second_run_changes_nothing(self, tmp_path: Path) -> None:
        run_with(make_database(tmp_path))

        assert run_with(make_database(tmp_path)) == "current"

    def test_the_database_is_recorded_at_the_newest_revision(self, tmp_path: Path) -> None:
        run_with(make_database(tmp_path))

        assert revision_of(tmp_path / "ember.db") == HEAD

    def test_0003_downgrades_to_0002_and_drops_its_columns(self, tmp_path: Path) -> None:
        from alembic import command

        added = {"agent_id", "provider_id", "gateway", "started_at", "finished_at", "delegated_by"}
        path = tmp_path / "ember.db"
        run_with(make_database(path.parent))

        def columns() -> set[str]:
            with closing(sqlite3.connect(path)) as conn:
                return {row[1] for row in conn.execute("PRAGMA table_info(usage_records)")}

        assert added <= columns()

        async def downgrade() -> None:
            database = make_database(tmp_path)
            runner = MigrationRunner(database.engine)
            try:
                async with database.engine.connect() as conn:
                    await conn.run_sync(lambda sync: command.downgrade(runner._config(sync), "0002"))
            finally:
                await database.dispose()

        asyncio.run(downgrade())

        assert revision_of(path) == "0002"
        assert not (added & columns())
        assert {"id", "account_id", "total_tokens", "created_at"} <= columns()


class TestDatabaseFromBeforeMigrations:
    def build_legacy(self, tmp_path: Path) -> Path:
        """What ember_api made before: tables from the models, no revision, some data."""
        database = make_database(tmp_path)
        asyncio.run(database.create_tables())
        asyncio.run(database.dispose())
        path = tmp_path / "ember.db"
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("DROP TABLE app_settings")  # made after the baseline, so a legacy database lacks it
            conn.execute("DROP TABLE traffic_buckets")  # likewise
            conn.execute("DROP TABLE nav_preferences")  # likewise
            conn.execute("DROP TABLE account_capabilities")  # likewise
            conn.execute("DROP TABLE user_extensions")  # likewise
            drop_chat_folders(conn)
            conn.execute("ALTER TABLE accounts DROP COLUMN prompt_suggestions")  # added after the baseline too
            drop_account_uid(conn)  # likewise
            for column in ("agent_id", "provider_id", "gateway", "started_at", "finished_at", "delegated_by"):
                conn.execute(f"ALTER TABLE usage_records DROP COLUMN {column}")  # added after the baseline too
            conn.execute(
                "INSERT INTO accounts (username, email, password_hash, is_protected, is_active, email_verified, created_at)"
                " VALUES ('lex', 'lex@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"
            )
            conn.commit()
        assert "alembic_version" not in tables_of(path)
        return path

    def test_it_is_stamped_then_brought_up_to_date_with_its_data_kept(self, tmp_path: Path) -> None:
        path = self.build_legacy(tmp_path)

        assert run_with(make_database(tmp_path)) == "upgraded"

        assert revision_of(path) == HEAD
        assert {"app_settings", "traffic_buckets"} <= tables_of(path)
        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute("SELECT username FROM accounts").fetchall() == [("lex",)]

    def test_a_backup_is_made_before_the_changes(self, tmp_path: Path) -> None:
        path = self.build_legacy(tmp_path)
        seen: list[bool] = []

        async def backup() -> None:
            seen.append("alembic_version" in tables_of(path))  # nothing changed yet

        run_with(make_database(tmp_path), before_upgrade=backup)

        assert seen == [False]

    def test_it_is_only_stamped_when_the_baseline_is_the_newest_revision(self, tmp_path: Path) -> None:
        path = self.build_legacy(tmp_path)
        scripts = tmp_path / "baseline_only"
        shutil.copytree(MIGRATIONS_DIR, scripts, ignore=shutil.ignore_patterns("__pycache__", "0002*", "0003*", "0004*", "0005*", "0006*", "0007*", "0008*", "0009*", "0010*", "0011*", "0012*"))
        calls: list[int] = []

        async def backup() -> None:
            calls.append(1)

        result = run_with(make_database(tmp_path), before_upgrade=backup, scripts=scripts)

        assert result == "stamped"
        assert revision_of(path) == BASELINE
        assert calls == []  # nothing but the version table was written

    def test_the_updated_database_matches_the_models(self, tmp_path: Path) -> None:
        self.build_legacy(tmp_path)
        run_with(make_database(tmp_path))

        assert differences(make_database(tmp_path)) == []


@pytest.fixture
def scripts_with_a_new_migration(tmp_path: Path) -> Path:
    """The real migrations plus a throwaway one adding a column."""
    scripts = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "versions" / f"{NEXT}_add_nickname.py").write_text(
        f'revision = "{NEXT}"\n'
        f'down_revision = "{HEAD}"\n'
        "branch_labels = None\n"
        "depends_on = None\n"
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n\n"
        "def upgrade():\n"
        '    with op.batch_alter_table("accounts") as batch:\n'
        '        batch.add_column(sa.Column("nickname", sa.String(40), nullable=True))\n\n\n'
        "def downgrade():\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )
    return scripts


class TestLaterMigration:
    def build_at_baseline(self, tmp_path: Path) -> Path:
        run_with(make_database(tmp_path))
        path = tmp_path / "ember.db"
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "INSERT INTO accounts (uid, username, email, password_hash, is_protected, is_active, email_verified, created_at)"
                " VALUES ('0123456789abcdef0123456789abcdef', 'lex', 'lex@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"
            )
            conn.commit()
        return path

    def test_a_column_is_added_and_the_data_kept(self, tmp_path: Path, scripts_with_a_new_migration: Path) -> None:
        path = self.build_at_baseline(tmp_path)

        result = run_with(make_database(tmp_path), scripts=scripts_with_a_new_migration)

        assert result == "upgraded"
        assert revision_of(path) == NEXT
        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute("SELECT username, nickname FROM accounts").fetchall() == [("lex", None)]

    def test_a_backup_is_made_before_it_runs(self, tmp_path: Path, scripts_with_a_new_migration: Path) -> None:
        path = self.build_at_baseline(tmp_path)
        seen: list[str | None] = []

        async def backup() -> None:
            seen.append(revision_of(path))  # the database is still at the old revision

        run_with(make_database(tmp_path), before_upgrade=backup, scripts=scripts_with_a_new_migration)

        assert seen == [HEAD]

    def test_a_failed_backup_stops_the_migration(self, tmp_path: Path, scripts_with_a_new_migration: Path) -> None:
        path = self.build_at_baseline(tmp_path)

        async def backup() -> None:
            raise RuntimeError("disk full")

        with pytest.raises(RuntimeError, match="disk full"):
            run_with(make_database(tmp_path), before_upgrade=backup, scripts=scripts_with_a_new_migration)

        assert revision_of(path) == HEAD

    def test_a_legacy_database_is_stamped_then_upgraded_after_a_backup(
        self, tmp_path: Path, scripts_with_a_new_migration: Path
    ) -> None:
        database = make_database(tmp_path)
        asyncio.run(database.create_tables())
        asyncio.run(database.dispose())
        with closing(sqlite3.connect(tmp_path / "ember.db")) as conn:
            conn.execute("DROP TABLE app_settings")  # a legacy database predates it
            conn.execute("DROP TABLE traffic_buckets")
            conn.execute("DROP TABLE nav_preferences")  # likewise
            conn.execute("DROP TABLE account_capabilities")  # likewise
            conn.execute("DROP TABLE user_extensions")  # likewise
            for column in ("agent_id", "provider_id", "gateway", "started_at", "finished_at", "delegated_by"):
                conn.execute(f"ALTER TABLE usage_records DROP COLUMN {column}")
            drop_chat_folders(conn)
            conn.execute("ALTER TABLE accounts DROP COLUMN prompt_suggestions")  # added after the baseline too
            drop_account_uid(conn)  # likewise
            conn.commit()
        calls: list[int] = []

        async def backup() -> None:
            calls.append(1)

        result = run_with(make_database(tmp_path), before_upgrade=backup, scripts=scripts_with_a_new_migration)

        assert result == "upgraded"
        assert calls == [1]  # one backup for both pending migrations
        assert revision_of(tmp_path / "ember.db") == NEXT

    def test_a_new_empty_database_is_not_backed_up(self, tmp_path: Path, scripts_with_a_new_migration: Path) -> None:
        calls: list[int] = []

        async def backup() -> None:
            calls.append(1)

        result = run_with(make_database(tmp_path), before_upgrade=backup, scripts=scripts_with_a_new_migration)

        assert result == "created"
        assert calls == []
        assert revision_of(tmp_path / "ember.db") == NEXT


class TestStatusAndRevision:
    def test_current_reports_none_then_the_head(self, tmp_path: Path) -> None:
        async def go() -> tuple:
            database = make_database(tmp_path)
            runner = MigrationRunner(database.engine)
            before = await runner.current()
            await runner.run()
            after = await runner.current()
            await database.dispose()
            return before, after

        assert asyncio.run(go()) == ((None, HEAD), (HEAD, HEAD))

    def test_revision_writes_a_file_for_a_model_change(self, tmp_path: Path) -> None:
        scripts = tmp_path / "migrations"
        shutil.copytree(MIGRATIONS_DIR, scripts, ignore=shutil.ignore_patterns("__pycache__"))
        from sqlalchemy import Column, Integer, String

        async def go() -> str:
            database = make_database(tmp_path)
            try:
                return await MigrationRunner(database.engine, scripts=scripts).revision("add a probe table")
            finally:
                await database.dispose()

        probe = type("Probe", (Base,), {"__tablename__": "probe", "id": Column(Integer, primary_key=True), "name": Column(String(10))})
        try:
            written = Path(asyncio.run(go()))
        finally:
            Base.metadata.remove(probe.__table__)

        body = written.read_text(encoding="utf-8")
        assert "probe" in body and "create_table" in body
        assert f'down_revision = "{HEAD}"' in body or f"down_revision = '{HEAD}'" in body


def test_stamping_and_upgrading_are_not_confused_by_a_foreign_table(tmp_path: Path) -> None:
    """Only the accounts table marks a database as ember_api's."""
    database = make_database(tmp_path)

    async def go() -> str:
        async with database.engine.begin() as conn:
            await conn.execute(text("CREATE TABLE unrelated (id INTEGER)"))
        try:
            return await MigrationRunner(database.engine).run()
        finally:
            await database.dispose()

    assert asyncio.run(go()) == "created"
