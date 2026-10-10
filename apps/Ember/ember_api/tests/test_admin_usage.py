"""Admin usage inspection is independent of chat and account-management access."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src.models import Account, Permission, Role, UsageRecord
from src.routes import usage as routes
from src.services import usage_service
from tests.test_registration import as_admin

NOW = datetime(2026, 10, 10, 12)


@pytest.fixture
def accounts(client, monkeypatch):
    monkeypatch.setattr(routes, "utcnow", lambda: NOW)
    monkeypatch.setattr(usage_service, "utcnow", lambda: NOW)

    async def seed():
        async with client.app.state.database.sessions() as session:
            users = [Account(username=name, email=f"{name}@example.com", password_hash="unused",
                             email_verified=True, is_active=name != "disabled")
                     for name in ["alice", "bob", "disabled", "empty"]]
            session.add_all(users)
            await session.flush()
            for user, turn, kind, agent, tokens, age in [
                (users[0], "chat1", "chat", "main", 100, 0),
                (users[0], "chat1", "chat", "calc", 25, 0),
                (users[0], "summary1", "summary", "main", 10, 0),
                (users[1], "chat2", "chat", "main", 200, 0),
                (users[2], "old", "chat", "main", 900, 40),
            ]:
                session.add(UsageRecord(account_id=user.id, turn_id=turn, kind=kind,
                                        agent=agent, provider_id="provider", model="m",
                                        total_tokens=tokens, created_at=NOW - timedelta(days=age)))
            await session.commit()
            return {user.username: user.id for user in users}

    return client.portal.call(seed)


def grant(client, permissions, *, verified=True):
    async def run():
        async with client.app.state.database.sessions() as session:
            root = (await session.execute(select(Account).where(Account.username == "root"))).scalar_one()
            selected = list((await session.execute(select(Permission).where(Permission.name.in_(permissions)))).scalars())
            role = Role(name="Usage test role", permissions=selected)
            root.roles = [role]
            root.email_verified = verified
            await session.commit()
    client.portal.call(run)


def test_summary_includes_zero_and_disabled_accounts_and_counts_answers(client, accounts):
    as_admin(client)
    rows = client.get("/api/admin/usage").json()
    assert [r["username"] for r in rows] == ["bob", "alice", "disabled", "empty", "root"]
    assert [(r["tokens"], r["turns"]) for r in rows[:2]] == [(200, 1), (135, 1)]
    assert all(r["tokens"] == r["turns"] == 0 and r["last_used_at"] is None for r in rows[2:])
    assert client.get("/api/admin/usage", params={"days": 90}).json()[0]["username"] == "disabled"


def test_target_reports_records_filters_and_personal_isolation(client, accounts):
    as_admin(client)
    alice = f"/api/admin/usage/{accounts['alice']}"
    report = client.get(alice).json()
    assert report["report"]["total_tokens"] == report["six_hour"]["used"] == 135
    assert report["report"]["turns"] == 1
    filtered = client.get(alice, params={"group_by": "model", "agent": "calc", "provider": "provider"}).json()
    assert filtered["report"]["total_tokens"] == 25
    assert filtered["report"]["groups"][0]["key"] == "m"
    rows = client.get(alice + "/records", params={"agent": "calc", "limit": 1}).json()
    assert len(rows) == 1 and rows[0]["total_tokens"] == 25
    assert client.get("/api/usage", params={"account_id": accounts["alice"]}).json()["report"]["total_tokens"] == 0
    assert client.get("/api/usage/records", params={"account_id": accounts["bob"]}).json() == []
    assert client.get(f"/api/admin/usage/{accounts['empty']}").json()["report"]["total_tokens"] == 0
    assert client.get(f"/api/admin/usage/{accounts['disabled']}", params={"days": 90}).json()["report"]["total_tokens"] == 900


@pytest.mark.parametrize("suffix", ["", "/records"])
def test_admin_permission_is_required_before_lookup(client, accounts, suffix):
    url = "/api/admin/usage/999999" + suffix
    assert client.get(url).status_code == 401
    as_admin(client)
    grant(client, ["chat.use"])
    assert client.get(url).status_code == 403


def test_usage_only_role_can_inspect_without_chat_or_accounts_access(client, accounts):
    as_admin(client)
    grant(client, ["usage.all.view"])
    assert client.get("/api/usage").status_code == 403
    assert client.get("/api/admin/usage").status_code == 200
    assert client.get(f"/api/admin/usage/{accounts['alice']}").status_code == 200
    assert client.get(f"/api/admin/usage/{accounts['alice']}/records").status_code == 200
    assert client.get("/api/admin/usage/999999").status_code == 404
    assert client.get("/api/admin/usage/999999/records").status_code == 404


def test_unverified_observer_is_denied(client, accounts):
    as_admin(client)
    grant(client, ["usage.all.view"], verified=False)
    assert client.get(f"/api/admin/usage/{accounts['alice']}").status_code == 403
    assert client.get(f"/api/admin/usage/{accounts['alice']}/records").status_code == 403


@pytest.mark.parametrize("suffix,params", [
    ("", {"days": 0}), ("", {"days": 367}), ("", {"since": "2026-10-11"}),
    ("", {"since": "2020-01-01"}), ("", {"group_by": "account"}),
    ("/records", {"limit": 0}), ("/records", {"limit": 501}),
    ("/records", {"since": "invalid"}),
])
def test_detail_validation(client, accounts, suffix, params):
    as_admin(client)
    assert client.get(f"/api/admin/usage/{accounts['alice']}" + suffix, params=params).status_code == 422


def test_invalid_account_id(client, accounts):
    as_admin(client)
    assert client.get("/api/admin/usage/nope").status_code == 422
    assert client.get("/api/admin/usage/nope/records").status_code == 422
