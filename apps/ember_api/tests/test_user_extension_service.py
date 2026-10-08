"""user_extension_service.py: validation, slugs, encryption and what a turn gets."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from src.db import Database
from src.models import Account
from src.services import user_extension_service as svc
from src.services.secret_box import SecretBox
from src.services.user_extension_service import (
    ExtensionLimit,
    ExtensionNotFound,
    InvalidExtension,
    UserExtensionService,
    clean_headers,
    clean_url,
    slugify,
)

URL = "https://notes.example.com/mcp"


def new_box() -> SecretBox:
    return SecretBox(Fernet.generate_key().decode("ascii"))


class Env:
    """A real SQLite database with two accounts, and a service per account."""

    def __init__(self, tmp_path: Path, box: SecretBox | None = None):
        self.path = tmp_path / "ext.db"
        self.database = Database(f"sqlite+aiosqlite:///{self.path.as_posix()}")
        self.box = box or new_box()

    async def setup(self) -> None:
        await self.database.create_tables()
        async with self.database.sessions() as session:
            for name in ("alice", "bob"):
                session.add(Account(username=name, email=f"{name}@example.com", password_hash="x"))
            await session.commit()

    def service(self, session, account_id: int = 1) -> UserExtensionService:
        return UserExtensionService(session, account_id, self.box)


def run(tmp_path: Path, scenario, box: SecretBox | None = None):
    env = Env(tmp_path, box)

    async def go():
        await env.setup()
        try:
            async with env.database.sessions() as session:
                return await scenario(env, session)
        finally:
            await env.database.dispose()

    return asyncio.run(go())


def test_slugify():
    assert slugify("My Notes!") == "my_notes"
    assert slugify("  Wiki -- Team  ") == "wiki_team"
    assert slugify("a__b") == "a_b"
    assert slugify("???") == "extension"
    assert len(slugify("x" * 100)) == 40
    assert "__" not in slugify("a  _  b")


@pytest.mark.parametrize(
    "url", ["", "ftp://x.com/m", "notes.example.com", "https:///m", "https://u:p@x.com/m", "https://x.com/" + "a" * 1000]
)
def test_bad_urls_are_refused(url):
    with pytest.raises(InvalidExtension):
        clean_url(url)


def test_a_good_url_is_trimmed():
    assert clean_url(f"  {URL}  ") == URL


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "x"}, {"Cookie": "a=b"}, {"bad name": "v"}, {"X": ""}, {"X": "a\nb"}, {"X": "a" * 2001},
        {f"H{i}": "v" for i in range(21)},
    ],
)
def test_bad_headers_are_refused(headers):
    with pytest.raises(InvalidExtension):
        clean_headers(headers)


def test_no_headers_is_an_empty_map():
    assert clean_headers(None) == {}


def test_create_stores_the_headers_encrypted(tmp_path):
    async def scenario(env, session):
        stored = await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "s3cret-value"})
        return stored.row.slug, stored.headers, stored.header_names

    assert run(tmp_path, scenario) == ("notes", {"X-Key": "s3cret-value"}, ["X-Key"])
    with sqlite3.connect(tmp_path / "ext.db") as conn:
        (token,) = conn.execute("SELECT headers_encrypted FROM user_extensions").fetchone()
    assert token and "s3cret-value" not in token


def test_no_headers_is_stored_as_null(tmp_path):
    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL)

    run(tmp_path, scenario)
    with sqlite3.connect(tmp_path / "ext.db") as conn:
        assert conn.execute("SELECT headers_encrypted FROM user_extensions").fetchone() == (None,)


def test_slugs_stay_unique_per_account(tmp_path):
    async def scenario(env, session):
        first = await env.service(session).create(label="Notes", url=URL)
        second = await env.service(session).create(label="Notes", url=URL)
        other = await env.service(session, 2).create(label="Notes", url=URL)
        return first.row.slug, second.row.slug, other.row.slug

    assert run(tmp_path, scenario) == ("notes", "notes_2", "notes")


def test_the_limit_is_per_account(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "MAX_EXTENSIONS", 2)

    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="One", url=URL)
        await service.create(label="Two", url=URL)
        with pytest.raises(ExtensionLimit):
            await service.create(label="Three", url=URL)
        await env.service(session, 2).create(label="Three", url=URL)

    run(tmp_path, scenario)


def test_label_rules(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        with pytest.raises(InvalidExtension):
            await service.create(label="   ", url=URL)
        with pytest.raises(InvalidExtension):
            await service.create(label="x" * 61, url=URL)
        with pytest.raises(InvalidExtension):
            await service.create(label="Notes", url=URL, description="d" * 301)
        stored = await service.create(label="  My   notes ", url=URL)
        return stored.row.label

    assert run(tmp_path, scenario) == "My notes"


def test_an_account_only_sees_its_own(tmp_path):
    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL)
        assert [s.row.slug for s in await env.service(session, 2).list()] == []
        for action in (
            lambda: env.service(session, 2).get("notes"),
            lambda: env.service(session, 2).update("notes", enabled=False),
            lambda: env.service(session, 2).delete("notes"),
        ):
            with pytest.raises(ExtensionNotFound):
                await action()
        return len(await env.service(session).list())

    assert run(tmp_path, scenario) == 1


def test_update_changes_fields_and_replaces_headers_only_when_sent(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL, headers={"X-Key": "one"})
        a = await service.update("notes", label="My notes", description="d", enabled=False)
        b = await service.update("notes", headers={"Authorization": "Bearer two"})
        c = await service.update("notes", headers={})
        return (a.row.label, a.row.description, a.row.enabled, a.headers), b.headers, c.headers

    first, second, third = run(tmp_path, scenario)
    assert first == ("My notes", "d", False, {"X-Key": "one"})
    assert second == {"Authorization": "Bearer two"}
    assert third == {}


def test_a_new_host_without_new_headers_clears_the_saved_ones(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL, headers={"X-Key": "one"})
        same = await service.update("notes", url="https://notes.example.com/other")
        moved = await service.update("notes", url="https://evil.example.org/mcp")
        again = await service.update("notes", url="https://elsewhere.example.net/mcp", headers={"X-Key": "two"})
        return same.headers, moved.headers, again.headers

    assert run(tmp_path, scenario) == ({"X-Key": "one"}, {}, {"X-Key": "two"})


def test_delete_removes_it(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL)
        await service.delete("notes")
        return await service.list()

    assert run(tmp_path, scenario) == []


def test_headers_that_cannot_be_decrypted_are_reported_not_fatal(tmp_path):
    first_box = new_box()

    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "one"})
        await env.service(session).create(label="Wiki", url="https://wiki.example.com/mcp")
        # A different key now: the first extension's headers are unreadable.
        other = UserExtensionService(session, 1, new_box())
        listed = await other.list()
        return [(s.row.slug, s.readable, s.header_names) for s in listed]

    assert run(tmp_path, scenario, first_box) == [("notes", False, []), ("wiki", True, [])]


def test_an_unreadable_row_can_be_repaired_by_sending_headers(tmp_path):
    first_box = new_box()

    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "one"})
        other = UserExtensionService(session, 1, new_box())
        repaired = await other.update("notes", headers={"X-Key": "two"})
        return repaired.readable, repaired.headers

    assert run(tmp_path, scenario, first_box) == (True, {"X-Key": "two"})


def test_enabled_for_turn_gives_only_enabled_readable_rows_with_their_headers(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL, headers={"X-Key": "one"})
        await service.create(label="Off", url="https://off.example.com/mcp")
        await service.update("off", enabled=False)
        await service.create(label="Plain", url="https://plain.example.com/mcp")
        await env.service(session, 2).create(label="Bobs", url="https://bob.example.com/mcp")
        turn = await service.enabled_for_turn()
        return list(turn.items), list(turn.skipped)

    items, skipped = run(tmp_path, scenario)
    assert items == [
        {"id": "notes", "label": "Notes", "url": URL, "headers": {"X-Key": "one"}},
        {"id": "plain", "label": "Plain", "url": "https://plain.example.com/mcp", "headers": {}},
    ]
    assert skipped == []


def test_enabled_for_turn_skips_and_reports_an_unreadable_row(tmp_path):
    first_box = new_box()

    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "one"})
        turn = await UserExtensionService(session, 1, new_box()).enabled_for_turn()
        return list(turn.items), list(turn.skipped)

    items, skipped = run(tmp_path, scenario, first_box)
    assert items == []
    assert skipped == [{"id": "notes", "label": "Notes", "error": svc.UNREADABLE_MESSAGE}]
