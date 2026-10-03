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

from scripts.import_chat_app import format_report, main
from src.db import Database
from src.models import Account, Chat, Role, UsageRecord
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


def run_import(db: Database, folder: Path, apply: bool = True):
    async def go():
        async with db.sessions() as session:
            return await ChatAppImporter(session, ChatAppSource(folder / "data")).run(apply)

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
