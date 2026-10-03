"""Fixes from the 2026-10-03 security review: body sizes, attachment parsing
limits, dot segments in command options, wrong-password guessing outside the
login route, case-insensitive registration and old login attempts."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.body_limit import BodyLimitMiddleware
from src.config import SecuritySettings
from src.db import Database, utcnow
from src.models import Account, LoginAttempt
from src.services import text_extraction
from src.services.auth_service import AuthService
from src.services.text_extraction import ExtractionError, extract_text
from tests.conftest import ADMIN_PASSWORD, FakeEmailSender, FakeServerTools, FakeUpstream
from tests.test_admin import MEMBER_PASSWORD, login, make_member
from tests.test_registration import as_admin, new_invite, register

MB = 1024 * 1024


# --- body sizes -----------------------------------------------------------------------


class TestBodyLimits:
    def test_login_refuses_a_big_body_but_not_a_normal_one(self, client: TestClient) -> None:
        big = client.post("/api/auth/login", json={"username": "root", "password": "x" * (2 * MB)})
        normal = client.post("/api/auth/login", json={"username": "root", "password": "wrong"})

        assert big.status_code == 413
        assert normal.status_code == 401

    def test_registration_and_templates_get_the_small_limit_too(self, client: TestClient) -> None:
        as_admin(client)
        blob = "x" * (2 * MB)

        assert client.post("/api/auth/register", json={"username": "kim", "email": "k@e.co", "password": blob, "invite_code": "x"}).status_code == 413
        assert client.post("/api/templates", json={"name": "n", "text": blob}).status_code == 413

    def test_the_limit_is_just_below_a_megabyte(self, client: TestClient) -> None:
        under = client.post("/api/auth/login", json={"username": "root", "password": "x" * (900 * 1024)})
        over = client.post("/api/auth/login", json={"username": "root", "password": "x" * (1100 * 1024)})

        assert under.status_code == 422  # a long password is refused by its own rule, not by size
        assert over.status_code == 413

    def test_chats_still_take_a_big_body(self, client: TestClient) -> None:
        as_admin(client)
        question = "x" * (2 * MB)

        response = client.post(
            "/api/chats/00000000-0000-0000-0000-000000000001/turns", json={"question": question, "agent_id": "claude-agent"}
        )

        assert response.status_code != 413

    def test_attachments_and_uploads_still_take_a_big_body(self, client: TestClient) -> None:
        as_admin(client)
        data = base64.b64encode(b"x" * (3 * MB)).decode()

        assert client.post("/api/attachments/text", json={"filename": "a.txt", "data": data}).status_code != 413
        assert client.post("/api/uploads", json={"filename": "a.csv", "data": data}).status_code != 413

    def test_nothing_is_taken_over_the_large_limit(self, client: TestClient) -> None:
        as_admin(client)
        huge = "x" * (40 * MB)

        assert client.post("/api/chats/00000000-0000-0000-0000-000000000001/turns", content=json.dumps({"question": huge}), headers={"content-type": "application/json"}).status_code == 413

    def test_the_longest_matching_prefix_wins(self) -> None:
        middleware = BodyLimitMiddleware(None, max_bytes=10, path_limits={"/a": 100, "/a/b": 1000})

        assert middleware._limit_for("/a/b/c") == 1000
        assert middleware._limit_for("/a/x") == 100
        assert middleware._limit_for("/other") == 10
        assert middleware._limit_for("") == 10

    def test_a_declared_length_of_exactly_the_limit_passes_and_one_more_does_not(self) -> None:
        from starlette.applications import Starlette as App
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient as Starlette

        async def echo(request: Request) -> JSONResponse:
            return JSONResponse({"size": len(await request.body())})

        app = App(routes=[Route("/x", echo, methods=["POST"])])
        app.add_middleware(BodyLimitMiddleware, max_bytes=100)
        client = Starlette(app)

        assert client.post("/x", content=b"x" * 100).status_code == 200
        assert client.post("/x", content=b"x" * 101).status_code == 413

    def test_a_chunked_body_is_stopped_at_its_paths_limit(self) -> None:
        from starlette.testclient import TestClient as Starlette
        from starlette.applications import Starlette as App
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def echo(request: Request) -> JSONResponse:
            return JSONResponse({"size": len(await request.body())})

        app = App(routes=[Route("/small", echo, methods=["POST"]), Route("/big/x", echo, methods=["POST"])])
        app.add_middleware(BodyLimitMiddleware, max_bytes=100, path_limits={"/big": 1000})
        client = Starlette(app)

        def chunks(total: int):
            for _ in range(total // 50):
                yield b"x" * 50

        assert client.post("/small", content=chunks(100)).status_code == 200
        assert client.post("/small", content=chunks(150)).status_code == 413
        assert client.post("/big/x", content=chunks(900)).status_code == 200
        assert client.post("/big/x", content=chunks(1100)).status_code == 413


# --- attachments ----------------------------------------------------------------------


def zip_with(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class TestAttachmentLimits:
    @pytest.mark.parametrize("name", ["bomb.docx", "bomb.xlsx", "bomb.xlsm"])
    def test_a_zip_that_expands_too_far_is_refused(self, name: str) -> None:
        bomb = zip_with({"word/document.xml": b"\0" * (120 * MB)})
        assert len(bomb) < 1 * MB

        with pytest.raises(ExtractionError, match="far larger than it looks"):
            extract_text(name, bomb)

    def test_the_size_limit_counts_every_entry(self) -> None:
        many = zip_with({f"part{i}.xml": b"\0" * (30 * MB) for i in range(4)})

        with pytest.raises(ExtractionError, match="far larger"):
            extract_text("x.docx", many)

    def test_an_archive_just_under_the_limit_is_opened(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(text_extraction, "MAX_UNZIPPED_BYTES", 5000)
        archive = zip_with({"a.xml": b"\0" * 4999})

        # Not refused as a bomb; the library then says it is no Word file.
        with pytest.raises(ExtractionError, match="Could not read this Word document"):
            extract_text("x.docx", archive)

    def test_an_archive_at_the_limit_plus_one_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(text_extraction, "MAX_UNZIPPED_BYTES", 5000)

        with pytest.raises(ExtractionError, match="far larger"):
            extract_text("x.docx", zip_with({"a.xml": b"\0" * 5001}))

    def test_too_many_entries_are_refused(self) -> None:
        crowded = zip_with({f"f{i}.txt": b"" for i in range(text_extraction.MAX_ZIP_ENTRIES + 1)})

        with pytest.raises(ExtractionError, match="far larger"):
            extract_text("x.xlsx", crowded)

    def test_the_real_limits_are_the_documented_ones(self) -> None:
        assert text_extraction.MAX_UNZIPPED_BYTES == 100 * MB
        assert text_extraction.MAX_ZIP_ENTRIES == 5_000
        assert text_extraction.MAX_PDF_PAGES == 500
        assert text_extraction.MAX_SHEET_ROWS == 200_000

    def test_five_thousand_entries_are_allowed_and_one_more_is_not(self) -> None:
        five_thousand = zip_with({f"f{i}.txt": b"" for i in range(5_000)})
        one_more = zip_with({f"f{i}.txt": b"" for i in range(5_001)})

        with pytest.raises(ExtractionError, match="Could not read"):  # not refused as a bomb
            extract_text("x.xlsx", five_thousand)
        with pytest.raises(ExtractionError, match="far larger"):
            extract_text("x.xlsx", one_more)

    def test_an_archive_of_exactly_the_size_limit_is_opened(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(text_extraction, "MAX_UNZIPPED_BYTES", 5000)

        with pytest.raises(ExtractionError, match="Could not read this Word document"):
            extract_text("x.docx", zip_with({"a.xml": b"\0" * 5000}))

    def test_the_entry_limit_itself_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(text_extraction, "MAX_ZIP_ENTRIES", 3)
        three = zip_with({f"f{i}.txt": b"" for i in range(3)})

        with pytest.raises(ExtractionError, match="Could not read"):
            extract_text("x.xlsx", three)

    def test_a_file_that_is_not_a_zip_gets_the_librarys_message(self) -> None:
        with pytest.raises(ExtractionError, match="Could not read this Word document"):
            extract_text("x.docx", b"not a zip at all")

    def test_a_real_word_file_still_reads(self) -> None:
        from docx import Document

        document = Document()
        document.add_paragraph("Hello there")
        buffer = io.BytesIO()
        document.save(buffer)

        assert extract_text("a.docx", buffer.getvalue()).text == "Hello there"

    def test_a_pdf_is_read_page_by_page_and_stops_when_it_has_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pypdf

        read: list[int] = []

        class Page:
            def __init__(self, number: int) -> None:
                self.number = number

            def extract_text(self) -> str:
                read.append(self.number)
                return "x" * 6000

        class Reader:
            def __init__(self, _stream) -> None:
                self.pages = [Page(i) for i in range(50)]

        monkeypatch.setattr(pypdf, "PdfReader", Reader)

        result = extract_text("a.pdf", b"%PDF")

        assert result.truncated and result.char_count == text_extraction.MAX_TEXT_CHARS
        assert read == [0, 1, 2, 3]  # 4 x 6000 characters pass 20,000

    def test_text_that_exactly_fills_the_attachment_ends_the_reading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pypdf

        read: list[int] = []

        class Page:
            def __init__(self, number: int) -> None:
                self.number = number

            def extract_text(self) -> str:
                read.append(self.number)
                return "x" * text_extraction.MAX_TEXT_CHARS

        class Reader:
            def __init__(self, _stream) -> None:
                self.pages = [Page(i) for i in range(5)]

        monkeypatch.setattr(pypdf, "PdfReader", Reader)

        extract_text("a.pdf", b"%PDF")

        assert read == [0]

    def test_a_pdf_of_endless_empty_pages_stops_at_exactly_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pypdf

        read: list[int] = []

        class Page:
            def extract_text(self) -> str:
                read.append(1)
                return ""

        class Reader:
            def __init__(self, _stream) -> None:
                self.pages = [Page() for _ in range(600)]

        monkeypatch.setattr(pypdf, "PdfReader", Reader)

        with pytest.raises(ExtractionError, match="No readable text"):
            extract_text("a.pdf", b"%PDF")

        assert len(read) == 500

    def test_a_sheet_of_empty_rows_stops_at_exactly_two_hundred_thousand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import openpyxl

        asked: list[int] = []

        class Sheet:
            title = "S"

            def iter_rows(self, values_only: bool):
                for i in range(250_000):
                    asked.append(i)
                    yield (None,)

        class Book:
            sheetnames = ["S"]
            worksheets = [Sheet()]

            def close(self) -> None:
                pass

        monkeypatch.setattr(text_extraction, "_refuse_zip_bomb", lambda _content: None)
        monkeypatch.setattr(openpyxl, "load_workbook", lambda *args, **kwargs: Book())

        with pytest.raises(ExtractionError, match="No readable text"):
            extract_text("a.xlsx", b"x")

        assert len(asked) == 200_001  # 200,000 rows read, then the next one is asked for and the loop stops

    def test_a_pdf_with_endless_empty_pages_stops_at_the_page_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pypdf

        read: list[int] = []

        class Page:
            def extract_text(self) -> str:
                read.append(1)
                return ""

        class Reader:
            def __init__(self, _stream) -> None:
                self.pages = [Page() for _ in range(text_extraction.MAX_PDF_PAGES + 100)]

        monkeypatch.setattr(pypdf, "PdfReader", Reader)

        with pytest.raises(ExtractionError, match="No readable text"):
            extract_text("a.pdf", b"%PDF")

        assert len(read) == text_extraction.MAX_PDF_PAGES

    def test_a_pdf_with_a_broken_page_keeps_the_rest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pypdf

        class Broken:
            def extract_text(self) -> str:
                raise ValueError("bad page")

        class Fine:
            def extract_text(self) -> str:
                return "kept"

        class Reader:
            def __init__(self, _stream) -> None:
                self.pages = [Broken(), Fine()]

        monkeypatch.setattr(pypdf, "PdfReader", Reader)

        assert extract_text("a.pdf", b"%PDF").text == "kept"

    def test_a_sheet_is_read_row_by_row_and_stops_when_it_has_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import openpyxl

        scanned: list[int] = []

        class Sheet:
            title = "S"

            def iter_rows(self, values_only: bool):
                for i in range(10_000):
                    scanned.append(i)
                    yield ("y" * 5000,)

        class Book:
            sheetnames = ["S"]
            worksheets = [Sheet()]

            def close(self) -> None:
                pass

        monkeypatch.setattr(text_extraction, "_refuse_zip_bomb", lambda _content: None)
        monkeypatch.setattr(openpyxl, "load_workbook", lambda *args, **kwargs: Book())

        result = extract_text("a.xlsx", b"x")

        assert result.truncated
        assert len(scanned) <= 6  # 4 rows reach 20,000 characters; the generator is asked for the next one

    def test_a_sheet_of_empty_rows_stops_at_the_row_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import openpyxl

        asked: list[int] = []

        class Sheet:
            title = "S"

            def iter_rows(self, values_only: bool):
                for i in range(50):
                    asked.append(i)
                    yield (None,)

        class Book:
            sheetnames = ["S"]
            worksheets = [Sheet()]

            def close(self) -> None:
                pass

        monkeypatch.setattr(text_extraction, "_refuse_zip_bomb", lambda _content: None)
        monkeypatch.setattr(text_extraction, "MAX_SHEET_ROWS", 7)
        monkeypatch.setattr(openpyxl, "load_workbook", lambda *args, **kwargs: Book())

        with pytest.raises(ExtractionError, match="No readable text"):
            extract_text("a.xlsx", b"x")

        assert len(asked) == 8  # rows 0 to 6 are read, the generator is asked for row 7 and the loop stops

    def test_a_second_sheet_is_skipped_once_the_first_filled_the_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import openpyxl

        touched: list[str] = []

        class Sheet:
            def __init__(self, title: str, cell: str) -> None:
                self.title = title
                self.cell = cell

            def iter_rows(self, values_only: bool):
                touched.append(self.title)
                yield (self.cell,)

        class Book:
            sheetnames = ["A", "B"]
            worksheets = [Sheet("A", "a" * 25_000), Sheet("B", "b")]

            def close(self) -> None:
                pass

        monkeypatch.setattr(text_extraction, "_refuse_zip_bomb", lambda _content: None)
        monkeypatch.setattr(openpyxl, "load_workbook", lambda *args, **kwargs: Book())

        extract_text("a.xlsx", b"x")

        assert touched == ["A"]

    def test_a_word_file_stops_reading_paragraphs_once_it_has_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docx

        read: list[int] = []

        class Paragraph:
            def __init__(self, i: int) -> None:
                self._i = i

            @property
            def text(self) -> str:
                read.append(self._i)
                return "z" * 9000

        class Document:
            def __init__(self, _stream) -> None:
                self.paragraphs = [Paragraph(i) for i in range(100)]
                self.tables = []

        monkeypatch.setattr(text_extraction, "_refuse_zip_bomb", lambda _content: None)
        monkeypatch.setattr(docx, "Document", Document)

        result = extract_text("a.docx", b"x")

        assert result.truncated
        assert sorted(set(read)) == [0, 1, 2]  # 3 x 9000 pass 20,000 (each is read twice by the check)

    def test_a_word_file_stops_reading_table_rows_once_it_has_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docx

        rows_read: list[int] = []

        class Cell:
            def __init__(self, text: str) -> None:
                self.text = text

        class Row:
            def __init__(self, i: int) -> None:
                self.i = i

            @property
            def cells(self):
                rows_read.append(self.i)
                return [Cell("c" * 8000)]

        class Table:
            rows = [Row(i) for i in range(100)]

        class Document:
            def __init__(self, _stream) -> None:
                self.paragraphs = []
                self.tables = [Table()]

        monkeypatch.setattr(text_extraction, "_refuse_zip_bomb", lambda _content: None)
        monkeypatch.setattr(docx, "Document", Document)

        result = extract_text("a.docx", b"x")

        assert result.truncated
        assert rows_read == [0, 1, 2]


# --- command options ------------------------------------------------------------------


class TestOptionDotSegments:
    @pytest.fixture
    def declared(self, client: TestClient, upstream: FakeUpstream, server_tools: FakeServerTools) -> TestClient:
        import httpx

        upstream.handler = lambda request: httpx.Response(200, json=["a"])
        server_tools.templates = {"/options/apps/{app}/versions"}
        as_admin(client)
        return client

    @pytest.mark.parametrize("value", [".", ".."])
    def test_a_dot_segment_is_refused_and_nothing_is_sent(self, declared: TestClient, upstream: FakeUpstream, value: str) -> None:
        before = len(upstream.requests)

        response = declared.get(
            "/api/commands/options", params={"template": "/options/apps/{app}/versions", "arg.app": value}
        )

        assert response.status_code == 400
        assert len(upstream.requests) == before

    @pytest.mark.parametrize("value", ["web", "a.b", "..x", "x..", "...", "v1.2"])
    def test_other_values_with_dots_are_fine(self, declared: TestClient, upstream: FakeUpstream, value: str) -> None:
        response = declared.get(
            "/api/commands/options", params={"template": "/options/apps/{app}/versions", "arg.app": value}
        )

        assert response.status_code == 200
        assert upstream.requests[-1].url.raw_path.decode() == f"/options/apps/{value}/versions"


# --- wrong passwords outside the login route -------------------------------------------


def wrong(client: TestClient, route: str):
    body = {"current_password": "wrong password"}
    body.update({"new_password": "another new password"} if route == "password" else {"email": "new@example.com"})
    return client.post(f"/api/account/{route}", json=body)


class TestPasswordGuessing:
    @pytest.mark.parametrize("route", ["password", "email"])
    def test_five_wrong_passwords_lock_the_route_even_for_the_right_one(
        self, client: TestClient, email: FakeEmailSender, route: str
    ) -> None:
        make_member(client, email)
        login(client, "alice")

        statuses = [wrong(client, route).status_code for _ in range(5)]
        locked = wrong(client, route)
        right_body = {"current_password": MEMBER_PASSWORD}
        right_body.update({"new_password": "another new password"} if route == "password" else {"email": "ok@example.com"})
        right = client.post(f"/api/account/{route}", json=right_body)

        assert statuses == [400] * 5
        assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0
        assert right.status_code == 429

    def test_the_account_is_locked_from_other_addresses_too(self, client_factory, email: FakeEmailSender) -> None:
        # The peer is a trusted proxy (loopback), so X-Forwarded-For names the client.
        client = client_factory(address="127.0.0.1")
        make_member(client, email)
        login(client, "alice")
        body = {"current_password": "wrong password", "new_password": "another new password"}
        for _ in range(5):
            assert client.post("/api/account/password", json=body, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 400

        other = client.post("/api/account/password", json=body, headers={"X-Forwarded-For": "10.0.0.2"})

        assert other.status_code == 429

    def test_the_two_routes_share_one_count(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email)
        login(client, "alice")

        for _ in range(3):
            assert wrong(client, "password").status_code == 400
        for _ in range(2):
            assert wrong(client, "email").status_code == 400

        assert wrong(client, "password").status_code == 429

    def test_guesses_here_also_lock_the_login_route(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email)
        login(client, "alice")
        for _ in range(5):
            wrong(client, "password")
        client.post("/api/auth/logout", json={})

        response = client.post("/api/auth/login", json={"username": "alice", "password": MEMBER_PASSWORD})

        assert response.status_code == 429

    def test_four_wrong_then_the_right_one_works(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email)
        login(client, "alice")
        for _ in range(4):
            assert wrong(client, "password").status_code == 400

        right = client.post(
            "/api/account/password", json={"current_password": MEMBER_PASSWORD, "new_password": "another new password"}
        )

        assert right.status_code == 200

    def test_a_refusal_that_is_not_a_wrong_password_does_not_count(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email)
        make_member(client, email, "bob")
        login(client, "alice")

        for _ in range(8):  # an email another account already has: refused, but the password was right
            response = client.post(
                "/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": "bob@example.com"}
            )
            assert response.status_code == 409

    def test_the_lock_can_be_switched_off_with_the_login_one(
        self, client_factory, email: FakeEmailSender
    ) -> None:
        client = client_factory(security=SecuritySettings(rate_limit_enabled=False))
        make_member(client, email)
        login(client, "alice")

        assert [wrong(client, "password").status_code for _ in range(8)] == [400] * 8

    def test_another_account_is_not_locked(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, "alice")
        make_member(client, email, "bob")
        login(client, "alice")
        for _ in range(5):
            wrong(client, "password")
        client.post("/api/auth/logout", json={})

        # bob shares the test client's address, so scope "both" still counts it: use an ip-less scope.
        # (The address lock is the login route's own rule; this only checks the account is not blamed.)
        async def count() -> list[int | None]:
            database = Database(client.app.state.settings.database_url)
            try:
                async with database.sessions() as session:
                    return list(await session.scalars(select(LoginAttempt.account_id).where(LoginAttempt.succeeded.is_(False))))
            finally:
                await database.dispose()

        attempts = asyncio.run(count())
        assert attempts and set(attempts) == {attempts[0]}
        assert len(attempts) == 5


# --- registration is not case sensitive ---------------------------------------------------


class TestRegistrationCase:
    def test_a_name_that_differs_only_in_case_is_taken(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, "alice")
        as_admin(client)

        response = register(client, new_invite(client), username="ALICE", email="other@example.com")

        assert response.status_code == 409
        assert "Username" in response.json()["detail"]

    def test_an_email_that_differs_only_in_case_is_taken(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, "alice")
        as_admin(client)

        response = register(client, new_invite(client), username="other", email="ALICE@Example.com")

        assert response.status_code == 409
        assert "Email" in response.json()["detail"]

    def test_the_invite_survives_a_refusal(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, "alice")
        as_admin(client)
        invite = new_invite(client)
        assert register(client, invite, username="ALICE", email="o@example.com").status_code == 409

        assert register(client, invite, username="fresh", email="fresh@example.com").status_code == 201

    def test_different_names_still_register(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, "alice")
        as_admin(client)

        assert register(client, new_invite(client), username="alicia", email="alicia@example.com").status_code == 201


# --- old login attempts ------------------------------------------------------------------------


class TestLoginAttemptPurge:
    def run(self, client: TestClient, ages_days: list[float]) -> tuple[int, int]:
        url = client.app.state.settings.database_url

        async def go() -> tuple[int, int]:
            database = Database(url)
            try:
                async with database.sessions() as session:
                    for days in ages_days:
                        session.add(LoginAttempt(ip_address="1.2.3.4", account_id=None, succeeded=False, attempted_at=utcnow() - timedelta(days=days)))
                    await session.commit()
                    before = len(list(await session.scalars(select(LoginAttempt))))
                    removed = await AuthService(session).purge_login_attempts()
                    after = len(list(await session.scalars(select(LoginAttempt))))
                    return removed, before - after
            finally:
                await database.dispose()

        return asyncio.run(go())

    def test_rows_older_than_the_retention_go_and_newer_stay(self, client: TestClient) -> None:
        removed, gone = self.run(client, [1, 29, 31, 90])

        assert removed == gone == 2

    def test_nothing_old_means_nothing_removed(self, client: TestClient) -> None:
        assert self.run(client, [0, 5])[0] == 0

    def test_it_runs_at_startup(self, client_factory) -> None:
        # A row older than the retention, written before the app starts, is gone after the lifespan ran.
        first = client_factory()
        url = first.app.state.settings.database_url
        path = first.app.state.settings.database_path

        async def seed() -> None:
            database = Database(url)
            try:
                async with database.sessions() as session:
                    session.add(LoginAttempt(ip_address="9.9.9.9", account_id=None, succeeded=False, attempted_at=utcnow() - timedelta(days=60)))
                    await session.commit()
            finally:
                await database.dispose()

        asyncio.run(seed())
        assert path.exists()
        second = client_factory()  # the same data folder: its startup purges

        async def count() -> int:
            database = Database(url)
            try:
                async with database.sessions() as session:
                    return len(list(await session.scalars(select(LoginAttempt).where(LoginAttempt.ip_address == "9.9.9.9"))))
            finally:
                await database.dispose()

        assert asyncio.run(count()) == 0
        assert second is not first
