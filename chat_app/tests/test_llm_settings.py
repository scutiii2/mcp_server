import os

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for key in ("MCP_SERVER_URL", "CHATS_DB_PATH"):
        monkeypatch.delenv(key, raising=False)


def test_defaults_when_nothing_configured():
    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.mcp_server_url == "http://127.0.0.1:8010/mcp"
    assert settings.chats_db_path.as_posix() == "data/chats.db"


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://example.test/mcp")

    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.mcp_server_url == "http://example.test/mcp"


def test_blank_env_var_counts_as_unset(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "")

    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.mcp_server_url == "http://127.0.0.1:8010/mcp"


def test_create_app_resolves_chats_db_path_against_base_dir(tmp_path, monkeypatch):
    """run.py's create_app() must set CHATS_DB_PATH as a DATA_DIR-absolute
    path, not leave it CWD-relative - see this task's Global Constraints
    note on why (the same class of bug _resolve_sqlite_uri already exists
    to fix for app.db)."""
    monkeypatch.delenv("CHATS_DB_PATH", raising=False)

    from src.run import DATA_DIR, create_app

    create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}", "TESTING": True})

    assert os.environ["CHATS_DB_PATH"] == str(DATA_DIR / "chats.db")
