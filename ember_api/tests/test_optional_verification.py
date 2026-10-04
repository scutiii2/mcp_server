"""config_app.json's require_email_verification: off lets an unverified account
use the app, and /api/auth/me tells the web app which mode it is in."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.config import load_settings
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import new_invite, register


def test_verification_is_required_by_default(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, verify=False)
    login(client, "alice")

    assert client.get("/api/auth/me").json()["email_verification_required"] is True
    assert client.get("/api/chats").status_code == 403


def test_unverified_account_can_use_the_app_when_not_required(client_factory, email: FakeEmailSender) -> None:
    client = client_factory(require_email_verification=False)
    make_member(client, email, verify=False)
    login(client, "alice")

    me = client.get("/api/auth/me").json()
    assert (me["email_verified"], me["email_verification_required"]) == (False, False)
    assert client.get("/api/chats").status_code == 200


def test_register_sends_no_code_when_not_required(client_factory, email: FakeEmailSender) -> None:
    client = client_factory(require_email_verification=False)

    response = register(client, new_invite(client))

    assert response.status_code == 201
    body = response.json()
    assert body["verification_email_sent"] is False
    assert body["email_error"] is None
    assert body["account"]["email_verification_required"] is False
    assert email.sent == []


def test_verifying_still_works_when_not_required(client_factory, email: FakeEmailSender) -> None:
    client = client_factory(require_email_verification=False)
    make_member(client, email, verify=False)
    login(client, "alice")

    assert client.post("/api/auth/verify-email/resend", json={}).status_code == 200
    code = email.last_code("verify")
    assert client.post("/api/auth/verify-email", json={"code": code}).json()["email_verified"] is True


def test_config_flag_is_read_and_defaults_to_required(tmp_path, monkeypatch) -> None:
    from src import config

    configs = tmp_path / "configs"
    configs.mkdir()
    monkeypatch.setattr(config, "CONFIGS_DIR", configs)

    (configs / "config_app.json").write_text("{}", encoding="utf-8")
    assert load_settings().require_email_verification is True

    (configs / "config_app.json").write_text('{"require_email_verification": false}', encoding="utf-8")
    assert load_settings().require_email_verification is False
