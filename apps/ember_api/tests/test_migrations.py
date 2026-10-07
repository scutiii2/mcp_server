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
HEAD = "0006"
NEXT = "0007"


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
                async with database.engine.begin() as conn:
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
            drop_chat_folders(conn)
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
        shutil.copytree(MIGRATIONS_DIR, scripts, ignore=shutil.ignore_patterns("__pycache__", "0002*", "0003*", "0004*", "0005*", "0006*"))
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
    (scripts / "versions" / "0007_add_nickname.py").write_text(
        'revision = "0007"\n'
        'down_revision = "0006"\n'
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
                "INSERT INTO accounts (username, email, password_hash, is_protected, is_active, email_verified, created_at)"
                " VALUES ('lex', 'lex@example.com', 'x', 0, 1, 1, '2026-01-01 00:00:00')"
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
            for column in ("agent_id", "provider_id", "gateway", "started_at", "finished_at", "delegated_by"):
                conn.execute(f"ALTER TABLE usage_records DROP COLUMN {column}")
            drop_chat_folders(conn)
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
