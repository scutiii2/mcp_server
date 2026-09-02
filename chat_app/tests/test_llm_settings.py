import os

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for key in (
        "MCP_SERVER_URL", "OPENAI_MODEL", "CLAUDE_MODEL",
        "CHAT_CONFIG_PATH", "CHATS_DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_defaults_when_nothing_configured():
    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.mcp_server_url == "http://127.0.0.1:8010/mcp"
    assert settings.openai_model == "gpt-5.6-sol"
    assert settings.claude_model == "claude-sonnet-5"
    assert settings.chat_config_path.as_posix() == "src/configs/config_chat.json"
    assert settings.chats_db_path.as_posix() == "data/chats.db"


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://example.test/mcp")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-custom")

    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.mcp_server_url == "http://example.test/mcp"
    assert settings.openai_model == "gpt-custom"


def test_blank_env_var_counts_as_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "")

    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.openai_model == "gpt-5.6-sol"


def test_create_app_resolves_llm_paths_against_base_dir(tmp_path, monkeypatch):
    """run.py's create_app() must set CHATS_DB_PATH/CHAT_CONFIG_PATH as
    BASE_DIR-absolute paths, not leave them CWD-relative - see this
    task's Global Constraints note on why (the same class of bug
    _resolve_sqlite_uri already exists to fix for app.db)."""
    for key in ("CHATS_DB_PATH", "CHAT_CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)

    from src.run import BASE_DIR, create_app

    create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}", "TESTING": True})

    assert os.environ["CHATS_DB_PATH"] == str(BASE_DIR / "data" / "chats.db")
    assert os.environ["CHAT_CONFIG_PATH"] == str(BASE_DIR / "configs" / "config_chat.json")
