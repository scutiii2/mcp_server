from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update

from src.db import utcnow
from src.models import InviteCode
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, FakeEmailSender


def as_admin(client: TestClient) -> TestClient:
    assert client.post(
        "/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    ).status_code == 200
    return client


def new_invite(client: TestClient, **body) -> str:
    """Creates an invite as admin and returns its code; leaves the client logged out."""
    as_admin(client)
    response = client.post("/api/admin/invites", json=body)
    assert response.status_code == 201, response.text
    client.post("/api/auth/logout", json={})
    return response.json()["code"]


def register(client: TestClient, code: str, username: str = "alice", email: str = "alice@example.com"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": "long enough pw", "invite_code": code},
    )


def expire_all_invites(client: TestClient) -> None:
    async def run() -> None:
        async with client.app.state.database.sessions() as session:
            await session.execute(update(InviteCode).values(expires_at=utcnow() - timedelta(minutes=1)))
            await session.commit()

    client.portal.call(run)


# --- registration ------------------------------------------------------------


def test_register_logs_in_unverified_member_and_emails_code(client: TestClient, email: FakeEmailSender) -> None:
    response = register(client, new_invite(client))

    assert response.status_code == 201
    body = response.json()
    assert body["verification_email_sent"] is True
    assert body["account"]["email_verified"] is False
    assert body["account"]["roles"] == ["Member"]
    assert body["account"]["permissions"] == ["chat.use", "tools.use"]
    assert client.get("/api/auth/me").json()["username"] == "alice"  # session started
    assert email.sent[-1][:2] == ("verify", "alice@example.com")


def test_bad_invite_is_rejected(client: TestClient) -> None:
    assert register(client, "not-a-real-code").status_code == 400


def test_expired_invite_is_rejected(client: TestClient) -> None:
    code = new_invite(client)
    expire_all_invites(client)

    assert register(client, code).status_code == 400


def test_invite_works_only_once(client: TestClient) -> None:
    code = new_invite(client)
    assert register(client, code).status_code == 201
    client.post("/api/auth/logout", json={})

    assert register(client, code, username="bob", email="bob@example.com").status_code == 400


def test_duplicate_username_and_email_keep_the_invite_unused(client: TestClient) -> None:
    assert register(client, new_invite(client)).status_code == 201
    client.post("/api/auth/logout", json={})
    code = new_invite(client)

    taken_name = register(client, code, username="alice", email="other@example.com")
    taken_email = register(client, code, username="other", email="alice@example.com")

    assert taken_name.status_code == taken_email.status_code == 409
    assert taken_name.json()["detail"] == "Username is already taken"
    assert taken_email.json()["detail"] == "Email is already registered"
    assert register(client, code, username="carol", email="carol@example.com").status_code == 201


def test_invalid_registration_fields_are_rejected(client: TestClient) -> None:
    code = new_invite(client)

    assert register(client, code, username="a b").status_code == 422  # bad characters
    assert register(client, code, email="not-an-email").status_code == 422
    short = client.post(
        "/api/auth/register",
        json={"username": "dave", "email": "d@example.com", "password": "short", "invite_code": code},
    )
    assert short.status_code == 422


# --- email verification --------------------------------------------------------


def test_permissions_are_inactive_until_email_verified(client: TestClient, email: FakeEmailSender) -> None:
    register(client, new_invite(client))

    # A permission-gated route: blocked while unverified.
    assert client.get("/api/admin/invites").json()["detail"] == "Email not verified"

    verified = client.post("/api/auth/verify-email", json={"code": email.last_code("verify")})

    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True
    # Verified now, but a Member still lacks admin.manage.
    assert client.get("/api/admin/invites").json()["detail"] == "Missing permission: admin.manage"


def test_wrong_verification_code_is_rejected(client: TestClient) -> None:
    register(client, new_invite(client))

    assert client.post("/api/auth/verify-email", json={"code": "wrong"}).status_code == 400
    assert client.get("/api/auth/me").json()["email_verified"] is False


def test_registration_survives_email_failure_and_resend_recovers(client: TestClient, email: FakeEmailSender) -> None:
    code = new_invite(client)
    email.fail = True

    response = register(client, code)

    assert response.status_code == 201
    assert response.json()["verification_email_sent"] is False
    assert "SMTP is down" in response.json()["email_error"]
    assert client.post("/api/auth/verify-email/resend", json={}).status_code == 503

    email.fail = False
    assert client.post("/api/auth/verify-email/resend", json={}).json() == {"sent": True}
    assert client.post("/api/auth/verify-email", json={"code": email.last_code("verify")}).status_code == 200


def test_resend_when_already_verified_is_409(client: TestClient) -> None:
    as_admin(client)  # bootstrap admin is verified from the start

    assert client.post("/api/auth/verify-email/resend", json={}).status_code == 409


# --- admin invites ---------------------------------------------------------------


def test_email_invite_is_sent_and_listed_without_its_code(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)

    created = client.post(
        "/api/admin/invites", json={"invitee_email": "new@example.com", "delivery_method": "email"}
    ).json()
    listed = client.get("/api/admin/invites").json()

    assert created["email_sent"] is True
    assert email.sent[-1] == ("invite", "new@example.com", created["code"])
    assert [i["id"] for i in listed] == [created["invite"]["id"]]
    assert "code" not in listed[0]


def test_email_invite_without_address_is_422(client: TestClient) -> None:
    as_admin(client)

    assert client.post("/api/admin/invites", json={"delivery_method": "email"}).status_code == 422


def test_failed_invite_email_still_returns_the_code(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    email.fail = True

    created = client.post(
        "/api/admin/invites", json={"invitee_email": "new@example.com", "delivery_method": "email"}
    ).json()

    assert created["email_sent"] is False
    assert created["code"]


def test_invites_require_login(client: TestClient) -> None:
    assert client.get("/api/admin/invites").status_code == 401
    assert client.post("/api/admin/invites", json={}).status_code == 401
