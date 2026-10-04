"""Verification emails: a code never verifies a different address than the one
it was sent to, and an account cannot be used to flood an inbox."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db import Database, utcnow
from src.models import Account, EmailVerificationCode
from src.services import otp_service
from src.services.otp_service import OtpService
from tests.conftest import FakeEmailSender
from tests.test_admin import MEMBER_PASSWORD, login, make_member


@pytest.fixture
def cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real cooldown (the other tests switch it off)."""
    monkeypatch.undo()


def change_email(client: TestClient, address: str):
    return client.post("/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": address})


def test_the_limits_are_thirty_seconds_and_five_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # back to the real values, not the tests' zero cooldown

    assert otp_service.VERIFICATION_COOLDOWN == timedelta(seconds=30)
    assert otp_service.VERIFICATION_PER_HOUR == 5


class TestOldCodeAfterAnEmailChange:
    def test_a_code_sent_to_the_old_address_does_not_verify_the_new_one(
        self, client: TestClient, email: FakeEmailSender
    ) -> None:
        make_member(client, email, verify=False)
        login(client, "alice")
        old_code = email.last_code("verify")

        assert change_email(client, "victim@example.com").status_code == 200

        refused = client.post("/api/auth/verify-email", json={"code": old_code})
        assert refused.status_code == 400
        assert client.get("/api/auth/me").json()["email_verified"] is False

    def test_the_code_sent_to_the_new_address_works(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, verify=False)
        login(client, "alice")

        change_email(client, "new@example.com")

        assert email.sent[-1][:2] == ("verify", "new@example.com")
        assert client.post("/api/auth/verify-email", json={"code": email.last_code("verify")}).status_code == 200

    def test_an_unchanged_address_keeps_its_code(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, verify=False)
        login(client, "alice")
        code = email.last_code("verify")

        change_email(client, "ALICE@example.com")  # same address, other case

        assert client.post("/api/auth/verify-email", json={"code": code}).status_code == 200

    def test_a_refused_change_keeps_the_code(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, verify=False)
        login(client, "alice")
        code = email.last_code("verify")

        wrong = client.post("/api/account/email", json={"current_password": "wrong password", "email": "x@example.com"})

        assert wrong.status_code == 400
        assert client.post("/api/auth/verify-email", json={"code": code}).status_code == 200

    def test_codes_of_other_accounts_are_untouched(self, client: TestClient, email: FakeEmailSender) -> None:
        make_member(client, email, "alice", verify=False)
        alice_code = email.last_code("verify")
        make_member(client, email, "bob", verify=False)
        login(client, "bob")

        change_email(client, "bob2@example.com")

        client.post("/api/auth/logout", json={})
        login(client, "alice")
        assert client.post("/api/auth/verify-email", json={"code": alice_code}).status_code == 200


class TestResendLimits:
    def test_a_second_resend_within_the_cooldown_waits(
        self, client: TestClient, email: FakeEmailSender, cooldown: None
    ) -> None:
        make_member(client, email, verify=False)
        login(client, "alice")
        sent_before = len(email.sent)

        first = client.post("/api/auth/verify-email/resend", json={})

        # make_member's registration code is the first one: the cooldown is already running.
        assert first.status_code == 429
        assert 1 <= int(first.headers["retry-after"]) <= 30
        assert len(email.sent) == sent_before

    def test_the_message_says_how_long(self, client: TestClient, email: FakeEmailSender, cooldown: None) -> None:
        make_member(client, email, verify=False)
        login(client, "alice")

        response = client.post("/api/auth/verify-email/resend", json={})

        assert f"{response.headers['retry-after']} s" in response.json()["detail"]

    def test_the_limit_is_per_account(self, client: TestClient, email: FakeEmailSender, cooldown: None) -> None:
        make_member(client, email, "alice", verify=False)
        make_member(client, email, "bob", verify=False)
        login(client, "alice")
        assert client.post("/api/auth/verify-email/resend", json={}).status_code == 429
        client.post("/api/auth/logout", json={})

        login(client, "bob")

        assert client.post("/api/auth/verify-email/resend", json={}).status_code == 429  # bob's own cooldown

    def test_an_email_change_waits_too(self, client: TestClient, email: FakeEmailSender, cooldown: None) -> None:
        make_member(client, email, verify=False)
        login(client, "alice")
        sent_before = len(email.sent)

        response = change_email(client, "other@example.com")

        assert response.status_code == 429
        assert len(email.sent) == sent_before
        assert client.get("/api/auth/me").json()["email"] == "alice@example.com"  # nothing changed

    def test_a_verified_account_is_refused_before_the_limit(
        self, client: TestClient, email: FakeEmailSender, cooldown: None
    ) -> None:
        make_member(client, email)
        login(client, "alice")

        assert client.post("/api/auth/verify-email/resend", json={}).status_code == 409


async def seed_codes(session, username: str, ages: list[timedelta]) -> Account:
    account = await session.scalar(select(Account).where(Account.username == username))
    await session.execute(EmailVerificationCode.__table__.delete().where(EmailVerificationCode.account_id == account.id))
    for age in ages:
        created = utcnow() - age
        session.add(
            EmailVerificationCode(
                code_hash=f"h{age.total_seconds()}", account_id=account.id, created_at=created,
                expires_at=created + timedelta(minutes=15),
            )
        )
    await session.commit()
    return account


class TestWaitRule:
    """The rule itself, with codes of chosen ages (no sleeping)."""

    @pytest.fixture
    def service(self, client: TestClient, email: FakeEmailSender, cooldown: None):
        make_member(client, email, "alice", verify=False)
        url = client.app.state.settings.database_url

        async def wait(ages: list[timedelta]) -> int | None:
            # Its own engine on the same file: the app's one lives on the test client's loop.
            database = Database(url)
            try:
                async with database.sessions() as session:
                    account = await seed_codes(session, "alice", ages)
                    return await OtpService(session).verification_wait(account)
            finally:
                await database.dispose()

        return lambda ages: asyncio.run(wait(ages))

    def test_no_code_means_no_wait(self, service) -> None:
        assert service([]) is None

    def test_a_code_older_than_the_cooldown_means_no_wait(self, service) -> None:
        assert service([timedelta(seconds=31)]) is None

    def test_a_fresh_code_waits_out_the_cooldown(self, service) -> None:
        wait = service([timedelta(seconds=10)])

        assert wait is not None and 19 <= wait <= 21

    def test_the_cooldown_counts_from_the_newest_code(self, service) -> None:
        wait = service([timedelta(seconds=25), timedelta(minutes=10)])

        assert wait is not None and 4 <= wait <= 6

    def test_five_in_the_hour_waits_until_the_oldest_leaves_it(self, service) -> None:
        ages = [timedelta(minutes=m) for m in (1, 10, 20, 30, 50)]

        wait = service(ages)

        assert wait is not None and 9 * 60 <= wait <= 10 * 60 + 1

    def test_four_in_the_hour_is_still_allowed(self, service) -> None:
        ages = [timedelta(minutes=m) for m in (2, 10, 20, 30)]

        assert service(ages) is None

    def test_codes_older_than_an_hour_do_not_count(self, service) -> None:
        ages = [timedelta(minutes=m) for m in (61, 62, 63, 64, 65, 70)]

        assert service(ages) is None

    def test_the_hourly_wait_wins_when_it_is_longer_than_the_cooldown(self, service) -> None:
        ages = [timedelta(seconds=5)] + [timedelta(minutes=m) for m in (10, 20, 30, 40)]

        wait = service(ages)

        assert wait is not None and wait > 30
