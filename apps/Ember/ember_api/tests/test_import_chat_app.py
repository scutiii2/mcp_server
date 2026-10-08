"""The chat_app import: fake chat_app databases in, ember_api rows out."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from scripts.import_chat_app import check_agents, format_report, main, parse_agent_map
from src.db import Database
from src.models import Account, Chat, KnownDevice, LogEntry, Role, UsageRecord
from src.services.chat_app_import import ChatAppImporter, ChatAppSource, ember_chat_id, to_naive_utc
from src.services.chat_service import MAX_CHATS_PER_ACCOUNT
from src.services.migrations import MigrationRunner

HASH = "scrypt:32768:8:1$salt$abcdef"


def make_chat_app(
    folder: Path,
    *,
    accounts: list[tuple] | None = None,
    chats: list[tuple] | None = None,
    usage: list[tuple] | None = None,
    account_roles: list[tuple] | None = None,
    logs: list[tuple] | None = None,
    devices: list[tuple] | None = None,
) -> Path:
    """Builds data/{app,chats,usage}.db the way chat_app lays them out."""
    data = folder / "data"
    data.mkdir(parents=True)

    app = sqlite3.connect(data / "app.db")
    app.executescript(
        """
        CREATE TABLE accounts (id INTEGER PRIMARY KEY, username TEXT, email TEXT, password_hash TEXT,
            is_protected INTEGER, is_active INTEGER, email_verified INTEGER, created_at TEXT);
        CREATE TABLE roles (id INTEGER PRIMARY KEY, name TEXT, description TEXT);
        CREATE TABLE account_roles (account_id INTEGER, role_id INTEGER);
        CREATE TABLE log_entries (id INTEGER PRIMARY KEY, kind TEXT, account_id INTEGER, source TEXT,
            message TEXT, details TEXT, created_at TEXT);
        CREATE TABLE device_fingerprints (id INTEGER PRIMARY KEY, account_id INTEGER, fingerprint_hash TEXT,
            first_seen_at TEXT, last_seen_at TEXT);
        INSERT INTO roles VALUES (1, 'Administrator', 'x'), (2, 'Viewer', 'y');
        """
    )
    app.executemany(
        "INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        accounts
        if accounts is not None
        else [(1, "lex", "lex@example.com", HASH, 0, 1, 1, "2026-09-24 16:21:48.336298")],
    )
    app.executemany("INSERT INTO account_roles VALUES (?, ?)", account_roles or [])
    app.executemany("INSERT INTO log_entries VALUES (?, ?, ?, ?, ?, ?, ?)", logs or [])
    app.executemany("INSERT INTO device_fingerprints VALUES (?, ?, ?, ?, ?)", devices or [])
    app.commit()
    app.close()

    store = sqlite3.connect(data / "chats.db")
    store.execute(
        "CREATE TABLE chats (id TEXT PRIMARY KEY, username TEXT, title TEXT, messages TEXT, "
        "created_at TEXT, updated_at TEXT, last_response_at TEXT)"
    )
    store.executemany(
        "INSERT INTO chats (id, username, title, messages, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        chats or [],
    )
    store.commit()
    store.close()

    ledger = sqlite3.connect(data / "usage.db")
    ledger.execute(
        "CREATE TABLE token_usage (username TEXT, ts TEXT, tokens INTEGER, agent TEXT, model TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, chat_id TEXT)"
    )
    ledger.executemany("INSERT INTO token_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)", usage or [])
    ledger.commit()
    ledger.close()
    return folder


def messages(*texts: str) -> str:
    return json.dumps(
        [{"role": "user" if i % 2 == 0 else "assistant", "content": t, "sent_at": "2026-09-25T01:50:52+00:00"} for i, t in enumerate(texts)]
    )


CHAT = ("pHeTdzl3rpKue5Ak", "lex", "Tools?", messages("Tools?", "Many."), "2026-09-25T01:50:46.667649+00:00", "2026-09-25T01:50:52.690730+00:00")
USAGE = ("lex", "2026-09-25T01:50:52.681323+00:00", 1189, "anthropic", "openrouter/free", 1054, 135, "pHeTdzl3rpKue5Ak")


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'ember.db').as_posix()}")
    asyncio.run(database.create_tables())
    yield database
    asyncio.run(database.dispose())


def run_import(db: Database, folder: Path, apply: bool = True, agent_map: dict[str, str] | None = None):
    async def go():
        async with db.sessions() as session:
            return await ChatAppImporter(session, ChatAppSource(folder / "data"), agent_map).run(apply)

    return asyncio.run(go())


def rows(db: Database, model):
    async def go():
        async with db.sessions() as session:
            return list(await session.scalars(select(model)))

    return asyncio.run(go())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestAccounts:
    def test_copies_everything_a_login_needs(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", account_roles=[(1, 1)], accounts=[(1, "lex", "lex@example.com", HASH, 1, 1, 1, "2026-09-24 16:21:48.336298")])

        report = run_import(db, folder)

        (account,) = rows(db, Account)
        assert (account.username, account.email, account.password_hash) == ("lex", "lex@example.com", HASH)
        assert account.is_active and account.email_verified
        assert account.created_at == datetime(2026, 9, 24, 16, 21, 48, 336298)
        assert (report.accounts.imported, report.accounts.skipped) == (1, 0)

    def test_inactive_and_unverified_stay_that_way(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", accounts=[(1, "lex", "lex@example.com", HASH, 0, 0, 0, "2026-09-24 16:21:48")])

        run_import(db, folder)

        (account,) = rows(db, Account)
        assert not account.is_active
        assert not account.email_verified

    def test_the_protected_flag_is_not_copied(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", accounts=[(1, "admin", "a@example.com", HASH, 1, 1, 1, "2026-09-24 16:17:23")])

        run_import(db, folder)

        assert rows(db, Account)[0].is_protected is False

    def test_roles_are_matched_by_name_and_missing_ones_created_empty(self, db, tmp_path):
        async def seed():
            async with db.sessions() as session:
                session.add(Role(name="Administrator", description="existing"))
                await session.commit()

        asyncio.run(seed())
        folder = make_chat_app(tmp_path / "old", account_roles=[(1, 1), (1, 2)])

        report = run_import(db, folder)

        (account,) = rows(db, Account)
        assert sorted(r.name for r in account.roles) == ["Administrator", "Viewer"]
        assert report.roles_created == ["Viewer"]
        by_name = {r.name: r for r in rows(db, Role)}
        assert by_name["Administrator"].description == "existing"
        assert by_name["Viewer"].permissions == []
        assert len(rows(db, Role)) == 2

    def test_a_username_in_use_is_skipped_with_its_chats_and_usage(self, db, tmp_path):
        async def seed():
            async with db.sessions() as session:
                session.add(Account(username="lex", email="other@example.com", password_hash="x"))
                await session.commit()

        asyncio.run(seed())
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])

        report = run_import(db, folder)

        assert (report.accounts.imported, report.accounts.skipped) == (0, 1)
        assert "username already used" in report.accounts.notes[0]
        assert rows(db, Chat) == []
        assert rows(db, UsageRecord) == []
        assert rows(db, Account)[0].email == "other@example.com"

    def test_an_email_in_use_is_skipped(self, db, tmp_path):
        async def seed():
            async with db.sessions() as session:
                session.add(Account(username="someone", email="LEX@example.com", password_hash="x"))
                await session.commit()

        asyncio.run(seed())
        folder = make_chat_app(tmp_path / "old")

        report = run_import(db, folder)

        assert report.accounts.imported == 0
        assert "email already used" in report.accounts.notes[0]

    def test_the_same_username_with_another_email_is_a_different_person_even_with_the_same_hash(self, db, tmp_path):
        async def seed():
            async with db.sessions() as session:
                session.add(Account(username="lex", email="other@example.com", password_hash=HASH))
                await session.commit()

        asyncio.run(seed())
        folder = make_chat_app(tmp_path / "old", chats=[CHAT])

        report = run_import(db, folder)

        assert "username already used" in report.accounts.notes[0]
        assert rows(db, Chat) == []

    def test_an_imported_account_is_recognised_whatever_the_email_case(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", accounts=[(1, "lex", "Lex@Example.com", HASH, 0, 1, 1, "2026-09-24 16:21:48")], chats=[CHAT])
        run_import(db, folder)

        report = run_import(db, folder)

        assert "already imported" in report.accounts.notes[0]
        assert len(rows(db, Account)) == 1

    def test_an_account_is_not_replaced_when_only_the_hash_differs(self, db, tmp_path):
        async def seed():
            async with db.sessions() as session:
                session.add(Account(username="lex", email="lex@example.com", password_hash="changed"))
                await session.commit()

        asyncio.run(seed())
        folder = make_chat_app(tmp_path / "old", chats=[CHAT])

        run_import(db, folder)

        assert rows(db, Account)[0].password_hash == "changed"
        assert rows(db, Chat) == []


class TestChats:
    def test_a_chat_moves_with_its_text_title_and_times(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT])

        report = run_import(db, folder)

        (chat,) = rows(db, Chat)
        assert chat.chat_id == "pHeTdzl3rpKue5Ak"
        assert chat.title == "Tools?"
        assert chat.message_count == 2
        assert json.loads(chat.messages)[1]["content"] == "Many."
        assert chat.created_at == datetime(2026, 9, 25, 1, 50, 46, 667649)
        assert chat.updated_at == datetime(2026, 9, 25, 1, 50, 52, 690730)
        assert (report.chats.imported, report.chats.skipped, report.chats.failed) == (1, 0, 0)

    def test_offset_times_become_utc(self, db, tmp_path):
        chat = (*CHAT[:4], "2026-09-25T03:00:00+02:00", "2026-09-25T04:30:00+02:00")
        folder = make_chat_app(tmp_path / "old", chats=[chat])

        run_import(db, folder)

        (row,) = rows(db, Chat)
        assert (row.created_at, row.updated_at) == (datetime(2026, 9, 25, 1, 0), datetime(2026, 9, 25, 2, 30))

    def test_an_id_with_an_underscore_is_made_usable(self, db, tmp_path):
        chat = ("ab_cd-efgh_ijkl", *CHAT[1:])
        folder = make_chat_app(tmp_path / "old", chats=[chat])

        run_import(db, folder)

        assert rows(db, Chat)[0].chat_id == "ab-cd-efgh-ijkl"

    def test_the_agent_comes_from_the_latest_usage_row_of_the_chat(self, db, tmp_path):
        usage = [
            ("lex", "2026-09-25T01:00:00+00:00", 10, "openai", "m", 5, 5, "pHeTdzl3rpKue5Ak"),
            ("lex", "2026-09-25T02:00:00+00:00", 10, "anthropic", "m", 5, 5, "pHeTdzl3rpKue5Ak"),
            ("lex", "2026-09-25T03:00:00+00:00", 10, "elsewhere", "m", 5, 5, "another-chat-0001"),
        ]
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=usage)

        run_import(db, folder)

        assert rows(db, Chat)[0].agent_id == "anthropic"

    def test_a_chat_without_usage_has_no_agent(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT])

        run_import(db, folder)

        assert rows(db, Chat)[0].agent_id is None

    def test_a_long_title_is_cut_and_a_blank_one_replaced(self, db, tmp_path):
        long_chat = ("longtitle-0001", "lex", "word " * 60, messages("hi"), CHAT[4], CHAT[5])
        blank_chat = ("blanktitle-001", "lex", "   ", messages("hi"), CHAT[4], CHAT[5])
        folder = make_chat_app(tmp_path / "old", chats=[long_chat, blank_chat])

        run_import(db, folder)

        titles = {c.chat_id: c.title for c in rows(db, Chat)}
        assert len(titles["longtitle-0001"]) == 120
        assert titles["longtitle-0001"].endswith("…")
        assert titles["blanktitle-001"] == "Imported chat"

    def test_a_broken_chat_fails_alone(self, db, tmp_path):
        bad = ("badjson-00001", "lex", "x", "{not json", CHAT[4], CHAT[5])
        not_list = ("notalist-0001", "lex", "x", '{"a": 1}', CHAT[4], CHAT[5])
        folder = make_chat_app(tmp_path / "old", chats=[bad, CHAT, not_list])

        report = run_import(db, folder)

        assert [c.chat_id for c in rows(db, Chat)] == ["pHeTdzl3rpKue5Ak"]
        assert (report.chats.imported, report.chats.failed) == (1, 2)
        assert len(report.chats.notes) == 2

    def test_a_chat_over_the_size_limit_fails_alone(self, db, tmp_path):
        big = ("bigchat-00001", "lex", "x", messages("a" * (2 * 1024 * 1024 + 1)), CHAT[4], CHAT[5])
        folder = make_chat_app(tmp_path / "old", chats=[big, CHAT])

        report = run_import(db, folder)

        assert [c.chat_id for c in rows(db, Chat)] == ["pHeTdzl3rpKue5Ak"]
        assert report.chats.failed == 1
        assert "larger than 2 MB" in report.chats.notes[0]

    def test_an_id_that_cannot_be_used_fails(self, db, tmp_path):
        short = ("abc", *CHAT[1:])
        folder = make_chat_app(tmp_path / "old", chats=[short])

        report = run_import(db, folder)

        assert rows(db, Chat) == []
        assert report.chats.failed == 1

    def test_two_ids_that_collide_after_cleanup_keep_the_first(self, db, tmp_path):
        first = ("same_id-00001", "lex", "first", messages("a"), CHAT[4], CHAT[5])
        second = ("same-id_00001", "lex", "second", messages("b"), CHAT[4], CHAT[5])
        folder = make_chat_app(tmp_path / "old", chats=[first, second])

        report = run_import(db, folder)

        assert [c.title for c in rows(db, Chat)] == ["first"]
        assert report.chats.skipped == 1

    def test_chats_over_the_account_cap_are_left_out(self, db, tmp_path):
        many = [(f"chat-{i:08d}", "lex", f"c{i}", messages("hi"), CHAT[4], CHAT[5]) for i in range(MAX_CHATS_PER_ACCOUNT + 2)]
        folder = make_chat_app(tmp_path / "old", chats=many)

        report = run_import(db, folder)

        assert len(rows(db, Chat)) == MAX_CHATS_PER_ACCOUNT
        assert (report.chats.imported, report.chats.failed) == (MAX_CHATS_PER_ACCOUNT, 2)

    def test_a_chat_of_an_unknown_user_is_skipped(self, db, tmp_path):
        stray = ("stray-chat-01", "ghost", "x", messages("hi"), CHAT[4], CHAT[5])
        folder = make_chat_app(tmp_path / "old", chats=[stray])

        report = run_import(db, folder)

        assert rows(db, Chat) == []
        assert report.chats.skipped == 1


class TestUsage:
    def test_a_row_moves_with_its_split_agent_and_chat(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])

        report = run_import(db, folder)

        (row,) = rows(db, UsageRecord)
        assert (row.agent, row.model, row.kind) == ("anthropic", "openrouter/free", "chat")
        assert (row.total_tokens, row.input_tokens, row.output_tokens) == (1189, 1054, 135)
        assert row.chat_id == "pHeTdzl3rpKue5Ak"
        assert row.created_at == datetime(2026, 9, 25, 1, 50, 52, 681323)
        assert row.turn_id
        assert report.usage.imported == 1

    def test_the_account_owns_its_rows(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", usage=[USAGE])

        run_import(db, folder)

        (account,) = rows(db, Account)
        assert rows(db, UsageRecord)[0].account_id == account.id

    def test_old_rows_without_agent_columns_still_import(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old")
        ledger = sqlite3.connect(folder / "data" / "usage.db")
        ledger.execute("DROP TABLE token_usage")
        ledger.execute("CREATE TABLE token_usage (username TEXT, ts TEXT, tokens INTEGER)")
        ledger.execute("INSERT INTO token_usage VALUES ('lex', '2026-09-25T01:50:52+00:00', 50)")
        ledger.commit()
        ledger.close()

        run_import(db, folder)

        (row,) = rows(db, UsageRecord)
        assert (row.total_tokens, row.agent, row.model, row.input_tokens, row.chat_id) == (50, None, None, None, None)

    def test_rows_of_one_turn_share_a_turn_id(self, db, tmp_path):
        ts = "2026-09-25T01:50:52+00:00"
        usage = [
            ("lex", ts, 100, "anthropic", "m", 60, 40, None),
            ("lex", ts, 30, "openai", "m", 20, 10, None),
            ("lex", "2026-09-25T02:00:00+00:00", 5, "anthropic", "m", 3, 2, None),
        ]
        folder = make_chat_app(tmp_path / "old", usage=usage)

        run_import(db, folder)

        by_tokens = {r.total_tokens: r.turn_id for r in rows(db, UsageRecord)}
        assert by_tokens[100] == by_tokens[30]
        assert by_tokens[5] != by_tokens[100]

    def test_the_same_timestamp_for_two_accounts_is_two_turns(self, db, tmp_path):
        ts = "2026-09-25T01:50:52+00:00"
        accounts = [
            (1, "lex", "lex@example.com", HASH, 0, 1, 1, "2026-09-24 16:21:48"),
            (2, "kim", "kim@example.com", HASH, 0, 1, 1, "2026-09-24 16:22:00"),
        ]
        usage = [("lex", ts, 10, "a", "m", 5, 5, None), ("kim", ts, 20, "a", "m", 10, 10, None)]
        folder = make_chat_app(tmp_path / "old", accounts=accounts, usage=usage)

        run_import(db, folder)

        turn_ids = {r.turn_id for r in rows(db, UsageRecord)}
        assert len(turn_ids) == 2

    def test_two_identical_rows_are_two_real_turns_and_a_rerun_adds_none(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", usage=[USAGE, USAGE])

        first = run_import(db, folder)
        second = run_import(db, folder)

        assert (first.usage.imported, second.usage.imported) == (2, 0)
        assert len(rows(db, UsageRecord)) == 2

    def test_a_usage_row_without_a_chat_does_not_wipe_the_agent_of_chats(self, db, tmp_path):
        usage = [
            ("lex", "2026-09-25T01:00:00+00:00", 10, "anthropic", "m", 5, 5, "pHeTdzl3rpKue5Ak"),
            ("lex", "2026-09-25T02:00:00+00:00", 10, None, "m", 5, 5, "pHeTdzl3rpKue5Ak"),
            ("lex", "2026-09-25T03:00:00+00:00", 10, "openai", "m", 5, 5, None),
        ]
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=usage)

        run_import(db, folder)

        assert rows(db, Chat)[0].agent_id == "anthropic"

    def test_a_row_with_no_tokens_is_not_copied(self, db, tmp_path):
        usage = [("lex", "2026-09-25T01:50:52+00:00", 0, "a", "m", 0, 0, None), USAGE]
        folder = make_chat_app(tmp_path / "old", usage=usage)

        report = run_import(db, folder)

        assert [r.total_tokens for r in rows(db, UsageRecord)] == [1189]
        assert report.usage.skipped == 1

    def test_an_underscore_chat_id_matches_the_imported_chat(self, db, tmp_path):
        chat = ("ab_cd-efgh_ijkl", *CHAT[1:])
        usage = [("lex", USAGE[1], 10, "a", "m", 5, 5, "ab_cd-efgh_ijkl")]
        folder = make_chat_app(tmp_path / "old", chats=[chat], usage=usage)

        run_import(db, folder)

        assert rows(db, UsageRecord)[0].chat_id == rows(db, Chat)[0].chat_id == "ab-cd-efgh-ijkl"

    def test_a_usage_row_of_an_unknown_user_is_skipped(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", usage=[("ghost", USAGE[1], 10, "a", "m", 5, 5, None)])

        report = run_import(db, folder)

        assert rows(db, UsageRecord) == []
        assert report.usage.skipped == 1


class TestRerun:
    def test_a_second_run_adds_nothing(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE, ("lex", "2026-09-26T00:00:00+00:00", 7, "a", "m", 3, 4, None)])
        run_import(db, folder)

        report = run_import(db, folder)

        assert (report.accounts.imported, report.chats.imported, report.usage.imported) == (0, 0, 0)
        assert (report.accounts.skipped, report.chats.skipped, report.usage.skipped) == (1, 1, 2)
        assert len(rows(db, Account)) == len(rows(db, Chat)) == 1
        assert len(rows(db, UsageRecord)) == 2

    def test_new_chat_app_data_is_picked_up_on_a_later_run(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT])
        run_import(db, folder)
        store = sqlite3.connect(folder / "data" / "chats.db")
        store.execute(
            "INSERT INTO chats (id, username, title, messages, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("later-chat-001", "lex", "later", messages("hi"), CHAT[4], CHAT[5]),
        )
        store.commit()
        store.close()

        report = run_import(db, folder)

        assert (report.chats.imported, report.chats.skipped) == (1, 1)
        assert len(rows(db, Chat)) == 2

    def test_an_existing_chat_is_never_overwritten(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT])
        run_import(db, folder)

        async def edit():
            async with db.sessions() as session:
                chat = (await session.scalars(select(Chat))).one()
                chat.title = "renamed in ember"
                await session.commit()

        asyncio.run(edit())

        run_import(db, folder)

        assert rows(db, Chat)[0].title == "renamed in ember"


class TestDryRun:
    def test_it_reports_the_same_counts_and_writes_nothing(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE], account_roles=[(1, 2)])

        dry = run_import(db, folder, apply=False)

        assert not dry.applied
        assert (dry.accounts.imported, dry.chats.imported, dry.usage.imported) == (1, 1, 1)
        assert dry.roles_created == ["Viewer"]
        assert rows(db, Account) == []
        assert rows(db, Chat) == []
        assert rows(db, UsageRecord) == []
        assert rows(db, Role) == []

        real = run_import(db, folder, apply=True)

        assert real.applied
        assert (real.accounts.imported, real.chats.imported, real.usage.imported) == (1, 1, 1)


class TestSource:
    def test_the_chat_app_files_are_not_changed(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        before = {name: digest(folder / "data" / name) for name in ("app.db", "chats.db", "usage.db")}

        run_import(db, folder)

        assert {name: digest(folder / "data" / name) for name in before} == before

    def test_the_source_cannot_be_written_through_the_reader(self, tmp_path):
        folder = make_chat_app(tmp_path / "old")
        from src.services.chat_app_import import _read_only

        conn = _read_only(folder / "data" / "app.db")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM accounts")
        conn.close()

    def test_a_missing_file_leaves_that_part_out_and_says_so(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        (folder / "data" / "usage.db").unlink()

        report = run_import(db, folder)

        assert report.missing_files == ["usage.db"]
        assert (report.accounts.imported, report.chats.imported, report.usage.imported) == (1, 1, 0)
        assert "usage.db" in format_report(report)

    def test_without_app_db_nothing_is_imported(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        (folder / "data" / "app.db").unlink()

        report = run_import(db, folder)

        assert report.missing_files == ["app.db"]
        assert rows(db, Chat) == []
        assert rows(db, UsageRecord) == []


class TestHelpers:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2026-09-24 16:21:48.336298", datetime(2026, 9, 24, 16, 21, 48, 336298)),
            ("2026-09-25T01:50:52+00:00", datetime(2026, 9, 25, 1, 50, 52)),
            ("2026-09-25T01:50:52-05:00", datetime(2026, 9, 25, 6, 50, 52)),
        ],
    )
    def test_to_naive_utc(self, text, expected):
        assert to_naive_utc(text) == expected

    @pytest.mark.parametrize(
        ("chat_id", "expected"),
        [
            ("pHeTdzl3rpKue5Ak", "pHeTdzl3rpKue5Ak"),
            ("a_b-c_d-e_f-g_h", "a-b-c-d-e-f-g-h"),
            ("short", None),
            ("x" * 64, "x" * 64),
            ("x" * 65, None),
            ("abcdefgh", "abcdefgh"),
            ("abcdefg", None),
            ("abc def ghi", "abc-def-ghi"),
        ],
    )
    def test_ember_chat_id(self, chat_id, expected):
        assert ember_chat_id(chat_id) == expected


class TestCli:
    def _settings(self, monkeypatch, tmp_path):
        from scripts import import_chat_app as cli
        from src.config import load_settings

        real = load_settings()
        from dataclasses import replace

        settings = replace(real, database_path=tmp_path / "ember.db")
        monkeypatch.setattr(cli, "load_settings", lambda: settings)
        return settings

    def test_a_dry_run_prints_and_writes_nothing(self, monkeypatch, tmp_path, capsys):
        settings = self._settings(monkeypatch, tmp_path)
        existing = Database(settings.database_url)
        asyncio.run(MigrationRunner(existing.engine).run())
        asyncio.run(existing.dispose())
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])

        assert main(["--chat-app", str(folder)]) == 0

        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "accounts: 1 imported" in out
        assert not list(tmp_path.glob("ember.db.bak-*"))
        db = Database(settings.database_url)
        assert rows(db, Account) == []
        asyncio.run(db.dispose())

    def test_apply_backs_up_then_writes(self, monkeypatch, tmp_path, capsys):
        settings = self._settings(monkeypatch, tmp_path)
        seed = Database(settings.database_url)
        asyncio.run(MigrationRunner(seed.engine).run())
        asyncio.run(seed.dispose())
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])

        assert main(["--chat-app", str(folder), "--apply"]) == 0

        out = capsys.readouterr().out
        assert "APPLIED" in out
        assert len(list(tmp_path.glob("ember.db.bak-*"))) == 1
        db = Database(settings.database_url)
        assert len(rows(db, Chat)) == 1
        asyncio.run(db.dispose())

    def test_a_folder_without_data_stops(self, monkeypatch, tmp_path):
        self._settings(monkeypatch, tmp_path)

        with pytest.raises(SystemExit, match="No data folder"):
            main(["--chat-app", str(tmp_path / "nowhere")])

    def test_the_report_names_notes_and_created_roles(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", account_roles=[(1, 2)], chats=[("abc", *CHAT[1:])])

        text = format_report(run_import(db, folder, apply=False))

        assert "DRY RUN" in text
        assert "chats: 0 imported, 0 skipped, 1 failed" in text
        assert "chat id 'abc' cannot be used" in text
        assert "roles created" in text and "Viewer" in text


# --- activity log ------------------------------------------------------------------------------

SHA = hashlib.sha256(b"Firefox|en-GB|192.168.1.0/24").hexdigest()

# (id, kind, account_id, source, message, details, created_at); account 1 is lex, 2 is admin.
LOGIN = (1, "action", 1, "auth.login", "Login succeeded", None, "2026-09-24 16:17:45.220886")
SERVER_ERROR = (2, "error", None, "unhandled_exception", "Boom", "Traceback ...", "2026-09-24 16:20:00.000001")
ADMIN_ACTION = (3, "action", 2, "admin.create_invite", "Generated invite (delivery=manual)", None, "2026-09-24 16:30:00.5")
TWO_ACCOUNTS = [
    (1, "lex", "lex@example.com", HASH, 0, 1, 1, "2026-09-24 16:21:48.336298"),
    (2, "admin", "admin@example.com", HASH, 1, 1, 1, "2026-09-24 16:00:00.000000"),
]


def seed_ember_admin(db: Database) -> None:
    async def go():
        async with db.sessions() as session:
            session.add(Account(username="admin", email="ember-admin@example.com", password_hash="x"))
            await session.commit()

    asyncio.run(go())


class TestLogs:
    def test_an_entry_of_an_imported_account_keeps_everything_and_belongs_to_it(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", logs=[LOGIN])

        report = run_import(db, folder)

        (entry,) = rows(db, LogEntry)
        (account,) = rows(db, Account)
        assert (entry.kind, entry.source, entry.message, entry.details) == ("action", "auth.login", "Login succeeded", None)
        assert entry.account_id == account.id
        assert entry.created_at == datetime(2026, 9, 24, 16, 17, 45, 220886)
        assert report.logs.imported == 1

    def test_an_entry_of_no_account_stays_that_way_with_its_message_unchanged(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", logs=[SERVER_ERROR])

        run_import(db, folder)

        (entry,) = rows(db, LogEntry)
        assert (entry.account_id, entry.message, entry.details) == (None, "Boom", "Traceback ...")

    def test_an_entry_of_a_skipped_account_names_it_but_is_not_given_to_ember_admin(self, db, tmp_path):
        seed_ember_admin(db)
        folder = make_chat_app(tmp_path / "old", accounts=TWO_ACCOUNTS, logs=[ADMIN_ACTION])

        report = run_import(db, folder)

        (entry,) = rows(db, LogEntry)
        assert entry.account_id is None
        assert entry.message == "Generated invite (delivery=manual) [chat_app: admin]"
        assert report.logs.imported == 1

    def test_an_entry_of_an_account_chat_app_no_longer_has_is_kept_without_one(self, db, tmp_path):
        ghost = (4, "action", 99, "auth.login", "Login succeeded", None, "2026-09-24 17:00:00.0")
        folder = make_chat_app(tmp_path / "old", logs=[ghost])

        run_import(db, folder)

        (entry,) = rows(db, LogEntry)
        assert (entry.account_id, entry.message) == (None, "Login succeeded")

    def test_a_long_message_is_cut_so_the_origin_still_fits(self, db, tmp_path):
        seed_ember_admin(db)
        long = (5, "action", 2, "x", "m" * 500, None, "2026-09-24 17:00:00.0")
        folder = make_chat_app(tmp_path / "old", accounts=TWO_ACCOUNTS, logs=[long])

        run_import(db, folder)

        (entry,) = rows(db, LogEntry)
        assert len(entry.message) == 500
        assert entry.message.endswith("\u2026 [chat_app: admin]")

    def test_a_message_that_just_fits_is_not_cut(self, db, tmp_path):
        seed_ember_admin(db)
        suffix = " [chat_app: admin]"
        exact = (5, "action", 2, "x", "m" * (500 - len(suffix)), None, "2026-09-24 17:00:00.0")
        folder = make_chat_app(tmp_path / "old", accounts=TWO_ACCOUNTS, logs=[exact])

        run_import(db, folder)

        assert rows(db, LogEntry)[0].message == "m" * (500 - len(suffix)) + suffix

    def test_a_rerun_adds_nothing(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", logs=[LOGIN, SERVER_ERROR])
        run_import(db, folder)

        report = run_import(db, folder)

        assert len(rows(db, LogEntry)) == 2
        assert (report.logs.imported, report.logs.skipped) == (0, 2)

    def test_two_identical_entries_are_two_entries_and_a_rerun_keeps_two(self, db, tmp_path):
        twin = (9, *LOGIN[1:])
        folder = make_chat_app(tmp_path / "old", logs=[LOGIN, twin])

        run_import(db, folder)
        run_import(db, folder)

        assert len(rows(db, LogEntry)) == 2

    def test_a_second_identical_entry_in_chat_app_is_added_when_ember_has_only_one(self, db, tmp_path):
        run_import(db, make_chat_app(tmp_path / "one", logs=[LOGIN]))
        twin = (9, *LOGIN[1:])

        report = run_import(db, make_chat_app(tmp_path / "two", logs=[LOGIN, twin]))

        assert len(rows(db, LogEntry)) == 2
        assert (report.logs.imported, report.logs.skipped) == (1, 1)

    def test_a_dry_run_writes_nothing_but_counts(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", logs=[LOGIN])

        report = run_import(db, folder, apply=False)

        assert rows(db, LogEntry) == []
        assert report.logs.imported == 1

    def test_ember_entries_of_the_same_time_are_not_confused_with_imported_ones(self, db, tmp_path):
        async def seed():
            async with db.sessions() as session:
                session.add(
                    LogEntry(kind="action", account_id=None, source="auth.login", message="Login succeeded",
                             created_at=datetime(2026, 9, 24, 16, 17, 45, 220886))
                )
                await session.commit()

        asyncio.run(seed())
        folder = make_chat_app(tmp_path / "old", logs=[LOGIN])

        run_import(db, folder)

        assert len(rows(db, LogEntry)) == 2  # the account differs: not the same entry

    def test_a_missing_table_is_named_and_the_rest_still_imports(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT])
        conn = sqlite3.connect(folder / "data" / "app.db")
        conn.execute("DROP TABLE log_entries")
        conn.commit()
        conn.close()

        report = run_import(db, folder)

        assert "app.db: log_entries" in report.missing_files
        assert report.chats.imported == 1 and report.logs.imported == 0

    def test_the_report_has_a_line_for_it(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", logs=[LOGIN])

        assert "log entries: 1 imported, 0 skipped, 0 failed" in format_report(run_import(db, folder))


# --- devices -----------------------------------------------------------------------------------


class TestDevices:
    DEVICE = (1, 1, SHA, "2026-09-24 16:17:45.214958", "2026-09-26 10:00:00.000001")

    def test_a_device_moves_with_its_times_and_unknown_browser(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", devices=[self.DEVICE])

        report = run_import(db, folder)

        (device,) = rows(db, KnownDevice)
        (account,) = rows(db, Account)
        assert (device.account_id, device.fingerprint_hash) == (account.id, SHA)
        assert (device.user_agent, device.ip_subnet) == ("", "")
        assert device.first_seen_at == datetime(2026, 9, 24, 16, 17, 45, 214958)
        assert device.last_seen_at == datetime(2026, 9, 26, 10, 0, 0, 1)
        assert report.devices.imported == 1

    def test_a_device_of_a_skipped_account_is_left_out(self, db, tmp_path):
        seed_ember_admin(db)
        admin_device = (2, 2, SHA, "2026-09-24 16:00:00.0", "2026-09-24 16:00:00.0")
        folder = make_chat_app(tmp_path / "old", accounts=TWO_ACCOUNTS, devices=[admin_device])

        report = run_import(db, folder)

        assert rows(db, KnownDevice) == []
        assert report.devices.skipped == 1

    def test_a_hash_that_is_not_sha256_is_left_out_with_a_note(self, db, tmp_path):
        bad = (3, 1, "not-a-hash", "2026-09-24 16:00:00.0", "2026-09-24 16:00:00.0")
        folder = make_chat_app(tmp_path / "old", devices=[bad])

        report = run_import(db, folder)

        assert rows(db, KnownDevice) == []
        assert report.devices.failed == 1 and "not a SHA-256" in report.devices.notes[0]

    def test_a_rerun_adds_nothing(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", devices=[self.DEVICE])
        run_import(db, folder)

        report = run_import(db, folder)

        assert len(rows(db, KnownDevice)) == 1
        assert (report.devices.imported, report.devices.skipped) == (0, 1)

    def test_the_same_device_twice_in_chat_app_arrives_once(self, db, tmp_path):
        twin = (2, *self.DEVICE[1:])
        folder = make_chat_app(tmp_path / "old", devices=[self.DEVICE, twin])

        report = run_import(db, folder)

        assert len(rows(db, KnownDevice)) == 1
        assert (report.devices.imported, report.devices.skipped) == (1, 1)

    def test_a_device_the_account_already_has_is_not_doubled(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old")
        run_import(db, folder)

        async def seed():
            async with db.sessions() as session:
                (account,) = list(await session.scalars(select(Account)))
                session.add(KnownDevice(account_id=account.id, fingerprint_hash=SHA, user_agent="Firefox", ip_subnet="x"))
                await session.commit()

        asyncio.run(seed())
        folder2 = make_chat_app(tmp_path / "old2", devices=[self.DEVICE])

        run_import(db, folder2)

        (device,) = rows(db, KnownDevice)
        assert device.user_agent == "Firefox"

    def test_the_hash_is_the_one_ember_api_computes_for_the_same_signals(self):
        """chat_app's compute_fingerprint, written out: the same signals must hash the same,
        or an imported device would never match a login."""
        from src.services.device_service import DeviceSignals

        user_agent, language, ip = "Mozilla/5.0 Firefox/130.0", "en-GB,en;q=0.9", "192.168.1.57"
        chat_app = hashlib.sha256(f"{user_agent}|{language}|192.168.1.0/24".encode("utf-8")).hexdigest()

        assert DeviceSignals(user_agent, language, ip).fingerprint() == chat_app

    def test_a_missing_table_is_named(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old")
        conn = sqlite3.connect(folder / "data" / "app.db")
        conn.execute("DROP TABLE device_fingerprints")
        conn.commit()
        conn.close()

        report = run_import(db, folder)

        assert "app.db: device_fingerprints" in report.missing_files
        assert report.accounts.imported == 1


# --- mapping agent names -----------------------------------------------------------------------

MAP = {"anthropic": "claude-agent"}
TWO_TURNS = [
    ("lex", "2026-09-25T01:00:00+00:00", 10, "anthropic", "m", 5, 5, "pHeTdzl3rpKue5Ak"),
    ("lex", "2026-09-25T02:00:00+00:00", 20, "openai", "m", 10, 10, "another-chat-0001"),
]


class TestAgentMap:
    def test_new_rows_get_the_mapped_name(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])

        report = run_import(db, folder, agent_map=MAP)

        assert rows(db, Chat)[0].agent_id == "claude-agent"
        assert rows(db, UsageRecord)[0].agent == "claude-agent"
        assert report.chats.relabelled == 0 and report.usage.relabelled == 0

    def test_a_name_not_in_the_map_is_kept(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", usage=TWO_TURNS)

        run_import(db, folder, agent_map=MAP)

        assert sorted(r.agent for r in rows(db, UsageRecord)) == ["claude-agent", "openai"]

    def test_without_a_map_nothing_changes(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])

        run_import(db, folder)

        assert rows(db, Chat)[0].agent_id == "anthropic"
        assert rows(db, UsageRecord)[0].agent == "anthropic"

    def test_rows_imported_earlier_are_relabelled(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        run_import(db, folder)

        report = run_import(db, folder, agent_map=MAP)

        assert rows(db, Chat)[0].agent_id == "claude-agent"
        (usage,) = rows(db, UsageRecord)
        assert usage.agent == "claude-agent"
        assert (report.chats.relabelled, report.usage.relabelled) == (1, 1)
        assert (report.chats.imported, report.usage.imported) == (0, 0)

    def test_relabelling_leaves_the_rest_of_the_row_alone(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        run_import(db, folder)
        before_chat, before_usage = rows(db, Chat)[0], rows(db, UsageRecord)[0]
        expected = (before_chat.updated_at, before_chat.messages, before_usage.created_at, before_usage.turn_id,
                    before_usage.total_tokens)

        run_import(db, folder, agent_map=MAP)

        chat, usage = rows(db, Chat)[0], rows(db, UsageRecord)[0]
        assert (chat.updated_at, chat.messages, usage.created_at, usage.turn_id, usage.total_tokens) == expected

    def test_a_rerun_after_relabelling_changes_nothing(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        run_import(db, folder)
        run_import(db, folder, agent_map=MAP)

        report = run_import(db, folder, agent_map=MAP)

        assert len(rows(db, UsageRecord)) == 1 and len(rows(db, Chat)) == 1
        assert (report.chats.relabelled, report.usage.relabelled) == (0, 0)
        assert (report.chats.skipped, report.usage.skipped) == (1, 1)

    def test_a_chat_whose_agent_was_changed_since_is_not_touched(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        run_import(db, folder)

        async def change():
            async with db.sessions() as session:
                (chat,) = list(await session.scalars(select(Chat)))
                chat.agent_id = "openai-agent"
                await session.commit()

        asyncio.run(change())

        report = run_import(db, folder, agent_map=MAP)

        assert rows(db, Chat)[0].agent_id == "openai-agent"
        assert report.chats.relabelled == 0

    def test_a_usage_row_of_ember_with_the_same_agent_name_is_not_touched(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", usage=[USAGE])
        run_import(db, folder)

        async def native():
            async with db.sessions() as session:
                (account,) = list(await session.scalars(select(Account)))
                session.add(
                    UsageRecord(account_id=account.id, turn_id="t", kind="chat", chat_id="zzzzzzzz1", agent="anthropic",
                                model="m", total_tokens=5, created_at=datetime(2026, 10, 1))
                )
                await session.commit()

        asyncio.run(native())

        run_import(db, folder, agent_map=MAP)

        assert sorted(r.agent for r in rows(db, UsageRecord)) == ["anthropic", "claude-agent"]

    def test_identical_turns_are_relabelled_one_for_one(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", usage=[USAGE, USAGE])
        run_import(db, folder)

        report = run_import(db, folder, agent_map=MAP)

        assert [r.agent for r in rows(db, UsageRecord)] == ["claude-agent", "claude-agent"]
        assert report.usage.relabelled == 2
        again = run_import(db, folder, agent_map=MAP)
        assert len(rows(db, UsageRecord)) == 2 and again.usage.skipped == 2

    def test_a_second_identical_turn_in_chat_app_is_added_when_ember_has_only_one(self, db, tmp_path):
        run_import(db, make_chat_app(tmp_path / "one", usage=[USAGE]), agent_map=MAP)

        report = run_import(db, make_chat_app(tmp_path / "two", usage=[USAGE, USAGE]), agent_map=MAP)

        assert len(rows(db, UsageRecord)) == 2
        assert (report.usage.imported, report.usage.skipped) == (1, 1)

    def test_a_dry_run_counts_the_relabelling_but_writes_nothing(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        run_import(db, folder)

        report = run_import(db, folder, apply=False, agent_map=MAP)

        assert (report.chats.relabelled, report.usage.relabelled) == (1, 1)
        assert rows(db, Chat)[0].agent_id == "anthropic"
        assert rows(db, UsageRecord)[0].agent == "anthropic"

    def test_the_report_shows_the_relabelled_count_only_when_there_is_one(self, db, tmp_path):
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        first = format_report(run_import(db, folder))
        second = format_report(run_import(db, folder, agent_map=MAP))

        assert "relabelled" not in first
        assert "chats: 0 imported, 0 skipped, 0 failed, 1 relabelled" in second


class TestAgentMapOnTheCommandLine:
    def test_pairs_become_a_dict(self):
        assert parse_agent_map(["anthropic=claude-agent", " a = b "]) == {"anthropic": "claude-agent", "a": "b"}

    @pytest.mark.parametrize("pair", ["anthropic", "=x", "x=", " = ", ""])
    def test_a_bad_pair_stops(self, pair):
        with pytest.raises(SystemExit, match="OLD=NEW"):
            parse_agent_map([pair])

    def test_naming_one_agent_twice_stops(self):
        with pytest.raises(SystemExit, match="twice"):
            parse_agent_map(["a=b", "a=c"])

    def registry(self, tmp_path, ids):
        path = tmp_path / "agents.json"
        path.write_text(
            json.dumps({"agents": [{"id": i, "label": i, "url": "http://127.0.0.1:9100/mcp"} for i in ids]}),
            encoding="utf-8",
        )
        return path

    def test_a_registered_agent_is_accepted(self, tmp_path):
        asyncio.run(check_agents({"anthropic": "claude-agent"}, self.registry(tmp_path, ["claude-agent", "openai-agent"])))

    def test_an_unknown_agent_is_refused_naming_the_registered_ones(self, tmp_path):
        with pytest.raises(SystemExit) as raised:
            asyncio.run(check_agents({"anthropic": "claud-agent"}, self.registry(tmp_path, ["claude-agent", "openai-agent"])))

        message = str(raised.value)
        assert "'claud-agent' is not a registered" in message
        assert "claude-agent, openai-agent" in message

    def test_an_empty_registry_says_to_start_ai_agent(self, tmp_path):
        with pytest.raises(SystemExit, match="is ai_agent running"):
            asyncio.run(check_agents({"a": "b"}, tmp_path / "missing.json"))

    def test_no_mapping_needs_no_registry(self, tmp_path):
        asyncio.run(check_agents({}, tmp_path / "missing.json"))

    def test_main_applies_the_map_and_reports_it(self, monkeypatch, tmp_path, capsys):
        from dataclasses import replace

        from scripts import import_chat_app as cli
        from src.config import load_settings

        settings = replace(
            load_settings(),
            database_path=tmp_path / "ember.db",
            agents_registry_path=self.registry(tmp_path, ["claude-agent"]),
        )
        monkeypatch.setattr(cli, "load_settings", lambda: settings)
        seed = Database(settings.database_url)
        asyncio.run(MigrationRunner(seed.engine).run())
        asyncio.run(seed.dispose())
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])
        assert main(["--chat-app", str(folder), "--apply"]) == 0
        capsys.readouterr()

        assert main(["--chat-app", str(folder), "--apply", "--agent-map", "anthropic=claude-agent"]) == 0

        out = capsys.readouterr().out
        assert "chats: 0 imported, 1 skipped, 0 failed, 1 relabelled" not in out  # relabelled, not skipped
        assert "1 relabelled" in out
        check = Database(settings.database_url)
        assert rows(check, Chat)[0].agent_id == "claude-agent"
        asyncio.run(check.dispose())

    def test_main_refuses_an_unregistered_agent_before_changing_anything(self, monkeypatch, tmp_path):
        from dataclasses import replace

        from scripts import import_chat_app as cli
        from src.config import load_settings

        settings = replace(
            load_settings(),
            database_path=tmp_path / "ember.db",
            agents_registry_path=self.registry(tmp_path, ["claude-agent"]),
        )
        monkeypatch.setattr(cli, "load_settings", lambda: settings)
        folder = make_chat_app(tmp_path / "old", chats=[CHAT], usage=[USAGE])

        with pytest.raises(SystemExit, match="not a registered"):
            main(["--chat-app", str(folder), "--apply", "--agent-map", "anthropic=nope"])

        assert not list(tmp_path.glob("ember.db*"))
