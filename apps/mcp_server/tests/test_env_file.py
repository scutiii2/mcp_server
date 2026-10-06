"""Tests for utils/env_file.py: the single .env loader and its one-time
migration from the legacy .secrets/secret_*.env files."""

from __future__ import annotations

from pathlib import Path

from src.utils.env_file import ensure_env_file, load_env_file, migrate_legacy_secrets


def _legacy(tmp_path: Path) -> Path:
    legacy = tmp_path / ".secrets"
    legacy.mkdir()
    (legacy / "secret_app.env").write_text("MCP_PORT=9000", encoding="utf-8")
    (legacy / "secret_smtp.env").write_text("SMTP_PASSWORD=s3cret\n", encoding="utf-8")
    (legacy / "secret_smtp.env.example").write_text("SMTP_PASSWORD=\n", encoding="utf-8")
    return legacy


def test_migrate_concatenates_legacy_env_files(tmp_path: Path):
    legacy = _legacy(tmp_path)
    env = tmp_path / ".env"

    assert migrate_legacy_secrets(env, legacy) is True

    text = env.read_text(encoding="utf-8")
    assert "MCP_PORT=9000\n" in text
    assert "SMTP_PASSWORD=s3cret\n" in text
    assert "from .secrets/secret_app.env" in text
    # The .example twin is not a real secret file and is not copied.
    assert "SMTP_PASSWORD=\n" not in text.replace("SMTP_PASSWORD=s3cret\n", "")
    assert legacy.is_dir()


def test_migrate_leaves_an_existing_env_alone(tmp_path: Path):
    legacy = _legacy(tmp_path)
    env = tmp_path / ".env"
    env.write_text("KEEP=1\n", encoding="utf-8")

    assert migrate_legacy_secrets(env, legacy) is False
    assert env.read_text(encoding="utf-8") == "KEEP=1\n"


def test_migrate_without_legacy_files_does_nothing(tmp_path: Path):
    env = tmp_path / ".env"
    assert migrate_legacy_secrets(env, tmp_path / ".secrets") is False
    assert not env.exists()


def test_ensure_copies_example_when_nothing_else_exists(tmp_path: Path):
    example = tmp_path / ".env.example"
    example.write_text("MCP_PORT=8010\n", encoding="utf-8")
    env = tmp_path / ".env"

    ensure_env_file(env, example, tmp_path / ".secrets")

    assert env.read_text(encoding="utf-8") == "MCP_PORT=8010\n"


def test_ensure_prefers_legacy_files_over_example(tmp_path: Path):
    legacy = _legacy(tmp_path)
    example = tmp_path / ".env.example"
    example.write_text("FROM_EXAMPLE=1\n", encoding="utf-8")
    env = tmp_path / ".env"

    ensure_env_file(env, example, legacy)

    assert "SMTP_PASSWORD=s3cret" in env.read_text(encoding="utf-8")
    assert "FROM_EXAMPLE" not in env.read_text(encoding="utf-8")


def test_load_sets_environment_without_overriding_existing(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ENV_FILE_TEST_NEW=from-file\nENV_FILE_TEST_SET=from-file\n", encoding="utf-8")
    monkeypatch.delenv("ENV_FILE_TEST_NEW", raising=False)
    monkeypatch.setenv("ENV_FILE_TEST_SET", "from-process")

    load_env_file(env, tmp_path / ".env.example", tmp_path / ".secrets")

    import os

    assert os.environ["ENV_FILE_TEST_NEW"] == "from-file"
    assert os.environ["ENV_FILE_TEST_SET"] == "from-process"
    monkeypatch.delenv("ENV_FILE_TEST_NEW", raising=False)
