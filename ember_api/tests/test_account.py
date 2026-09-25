from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import ADMIN_PASSWORD, FakeEmailSender
from tests.test_admin import MEMBER_PASSWORD, login, make_member
from tests.test_registration import as_admin

NEW_PASSWORD = "a brand new password"


def test_account_routes_need_login(client: TestClient) -> None:
    assert client.post("/api/account/email", json={"current_password": "x", "email": "a@b.co"}).status_code == 401
    assert client.post(
        "/api/account/password", json={"current_password": "x", "new_password": NEW_PASSWORD}
    ).status_code == 401


# --- email ----------------------------------------------------------------------


def test_change_email_unverifies_until_new_code(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    login(client, "alice")

    response = client.post(
        "/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": "new@example.com"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verification_email_sent"] is True
    assert (body["account"]["email"], body["account"]["email_verified"]) == ("new@example.com", False)
    assert email.sent[-1][:2] == ("verify", "new@example.com")
    # Permissions are off until the new address is verified.
    assert client.get("/api/agents").status_code == 403

    assert client.post("/api/auth/verify-email", json={"code": email.last_code("verify")}).status_code == 200
    assert client.get("/api/agents").status_code == 200


def test_same_email_changes_nothing(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    login(client, "alice")
    sent_before = len(email.sent)

    response = client.post(
        "/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": "ALICE@example.com"}
    )

    assert response.json()["account"]["email_verified"] is True
    assert response.json()["verification_email_sent"] is False
    assert len(email.sent) == sent_before


def test_change_email_refuses_wrong_password_and_taken_email(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    make_member(client, email, "bob")
    login(client, "alice")

    wrong = client.post("/api/account/email", json={"current_password": "nope", "email": "x@example.com"})
    taken = client.post(
        "/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": "Bob@example.com"}
    )
    invalid = client.post("/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": "nope"})

    assert (wrong.status_code, taken.status_code, invalid.status_code) == (400, 409, 422)
    assert client.get("/api/auth/me").json()["email"] == "alice@example.com"


def test_unverified_user_can_fix_email(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, verify=False)
    login(client, "alice")

    response = client.post(
        "/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": "fixed@example.com"}
    )

    assert response.status_code == 200
    assert email.sent[-1][:2] == ("verify", "fixed@example.com")


def test_email_change_reports_smtp_failure(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    login(client, "alice")
    email.fail = True

    response = client.post(
        "/api/account/email", json={"current_password": MEMBER_PASSWORD, "email": "new@example.com"}
    )

    assert response.status_code == 200
    assert response.json()["verification_email_sent"] is False
    assert response.json()["email_error"]


# --- password -----------------------------------------------------------------


def test_change_password_logs_out_other_sessions(client_factory, email: FakeEmailSender) -> None:
    here = client_factory()
    make_member(here, email)
    login(here, "alice")
    elsewhere = client_factory()
    login(elsewhere, "alice")

    response = here.post(
        "/api/account/password", json={"current_password": MEMBER_PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 200
    assert here.get("/api/auth/me").status_code == 200
    assert elsewhere.get("/api/auth/me").status_code == 401
    assert elsewhere.post(
        "/api/auth/login", json={"username": "alice", "password": MEMBER_PASSWORD}
    ).status_code == 401
    login(elsewhere, "alice", NEW_PASSWORD)


def test_change_password_refuses_wrong_or_short_password(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    login(client, "alice")

    wrong = client.post("/api/account/password", json={"current_password": "nope", "new_password": NEW_PASSWORD})
    short = client.post("/api/account/password", json={"current_password": MEMBER_PASSWORD, "new_password": "short"})

    assert (wrong.status_code, short.status_code) == (400, 422)


# --- protected admin ------------------------------------------------------------


def test_protected_admin_is_refused(client: TestClient) -> None:
    as_admin(client)

    email_change = client.post(
        "/api/account/email", json={"current_password": ADMIN_PASSWORD, "email": "other@example.com"}
    )
    password_change = client.post(
        "/api/account/password", json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert (email_change.status_code, password_change.status_code) == (409, 409)
    assert "secret_bootstrap_admin.env" in email_change.json()["detail"]
