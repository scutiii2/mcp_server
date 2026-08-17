"""Shared fixtures. No live MCP server or LLM provider needed to run this suite -
every test that touches mcp_client/llm providers mocks the specific function
it needs, at the point it's imported into the route module."""

from __future__ import annotations

import dataclasses

import pytest

from chat_app import errors
from chat_app.app import create_app
from chat_app.auth import service as auth_service
from chat_app.config import settings as base_settings
from chat_app.pages.account import routes as account_routes
from chat_app.pages.auth import routes as auth_routes
from chat_app.pages.chat import routes as chat_routes
from chat_app.pages.logs import routes as logs_routes
from chat_app.services import session_log
from chat_app.services.llm import cooldown


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def log_dir(tmp_path, monkeypatch):
    """Points errors.report()'s per-error files, session_log's per-chat
    traces, and the Logs page's reads at a throwaway directory.

    Without this, any test that triggers report() (e.g. an unexpected
    exception from a route) or completes a chat turn (session_log.record_turn,
    called unconditionally from chat_api) would write into the real,
    CWD-relative logs/ directory as a side effect of running the test suite -
    and any test hitting the Logs page would read whatever's actually
    there instead of test-controlled fixtures."""
    test_settings = dataclasses.replace(base_settings, log_dir=tmp_path / "logs")
    monkeypatch.setattr(errors, "settings", test_settings)
    monkeypatch.setattr(session_log, "settings", test_settings)
    monkeypatch.setattr(logs_routes, "settings", test_settings)
    return test_settings.log_dir


@pytest.fixture(autouse=True)
def reset_cooldowns():
    """Cooldown state is a module-level dict shared across the whole
    process (see cooldown.py's docstring for why) - which means it's
    equally shared across test cases unless we clear it between each one."""
    cooldown.reset()
    yield
    cooldown.reset()


@pytest.fixture(autouse=True)
def users_db(tmp_path, monkeypatch):
    """Points every module that reads settings.users_db_path at a fresh,
    per-test SQLite file instead of the real (import-time-frozen) one -
    see config.py's comment on that field for why a frozen dataclass field
    can't just be monkeypatched directly.

    autouse: security.check_auth() calls service.network_gate_enabled() on
    EVERY request (even ones that never mention users_db), which reads
    settings.users_db_path via store.any_gate_code_valid. Without this
    fixture applying unconditionally, any test that doesn't explicitly
    request `users_db` would fall through to the real, CWD-relative
    data/users.db as a side effect of just running the suite - and could
    fail nondeterministically if that file happens to contain a live gate
    code. Still requestable by name for its return value (the path), same
    as log_dir/reset_cooldowns above - autouse doesn't prevent that."""
    test_settings = dataclasses.replace(base_settings, users_db_path=tmp_path / "users.db")
    monkeypatch.setattr(auth_routes, "settings", test_settings)
    monkeypatch.setattr(auth_service, "settings", test_settings)
    monkeypatch.setattr(account_routes, "settings", test_settings)
    return test_settings.users_db_path


@pytest.fixture
def chats_db(tmp_path, monkeypatch):
    """Points chat_app.pages.chat.routes' `settings` at a fresh, per-test
    SQLite file - same reasoning as users_db above: a frozen,
    import-time-evaluated Settings field can't be monkeypatched directly."""
    test_settings = dataclasses.replace(base_settings, chats_db_path=tmp_path / "chats.db")
    monkeypatch.setattr(chat_routes, "settings", test_settings)
    return test_settings.chats_db_path
