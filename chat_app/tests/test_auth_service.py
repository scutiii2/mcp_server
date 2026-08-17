"""Unit tests for auth/service.py's network-gate helpers - see security.py's
check_auth for how these feed into the merged credential paths."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from chat_app.auth import service, store
from chat_app.config import settings as base_settings


@pytest.fixture(autouse=True)
def no_signals(monkeypatch):
    """Default state: every activation signal off."""
    monkeypatch.delenv("CHAT_AUTH_USER", raising=False)
    monkeypatch.delenv("CHAT_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("CHAT_NETWORK_ACCESS_ENABLED", raising=False)


@pytest.fixture
def users_db(tmp_path, monkeypatch):
    """Same isolation approach as conftest.py's users_db fixture - points
    the module's own (frozen, import-time) settings reference at a fresh
    per-test SQLite file."""
    test_settings = dataclasses.replace(base_settings, users_db_path=tmp_path / "users.db")
    monkeypatch.setattr(service, "settings", test_settings)
    return test_settings.users_db_path


def test_gate_is_off_with_no_signal(users_db):
    assert service.network_gate_enabled() is False


def test_shared_pair_turns_the_gate_on(users_db, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    assert service.network_gate_enabled() is True


def test_half_configured_shared_pair_does_not_turn_the_gate_on(users_db, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")

    assert service.network_gate_enabled() is False


def test_network_access_enabled_env_var_turns_the_gate_on(users_db, monkeypatch):
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")

    assert service.network_gate_enabled() is True


def test_a_valid_gate_code_turns_the_gate_on(users_db):
    store.create_gate_code(users_db, created_by="admin", ttl_hours=1)

    assert service.network_gate_enabled() is True


def test_an_expired_gate_code_does_not_turn_the_gate_on(users_db):
    issued = store.create_gate_code(users_db, created_by="admin", ttl_hours=1)
    conn = sqlite3.connect(str(users_db))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()

    assert service.network_gate_enabled() is False


def test_gate_code_grants_access_checks_the_password_only(users_db):
    issued = store.create_gate_code(users_db, created_by="admin", ttl_hours=1)

    assert service.gate_code_grants_access(issued.code) is True
    assert service.gate_code_grants_access("wrong-code") is False
