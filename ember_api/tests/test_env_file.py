"""utils/env_file.py: .env built from the legacy secrets/secret_*.env files."""

from __future__ import annotations

from pathlib import Path

from src.utils.env_file import ensure_env_file, migrate_legacy_secrets


def _legacy(tmp_path: Path) -> Path:
    legacy = tmp_path / "secrets"
    legacy.mkdir()
    (legacy / "secret_smtp.env").write_text("SMTP_PASSWORD=s3cret\n", encoding="utf-8")
    (legacy / "secret_bootstrap_admin.env").write_text("BOOTSTRAP_ADMIN_PASSWORD=pw", encoding="utf-8")
    (legacy / "secret_smtp.env.example").write_text("SMTP_PASSWORD=\n", encoding="utf-8")
    return legacy


def test_migrate_concatenates_legacy_env_files(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    env = tmp_path / ".env"

    assert migrate_legacy_secrets(env, legacy) is True

    text = env.read_text(encoding="utf-8")
    assert "SMTP_PASSWORD=s3cret\n" in text
    assert "BOOTSTRAP_ADMIN_PASSWORD=pw\n" in text
    assert "from secrets/secret_smtp.env" in text
    # The .example twin is not a real secret file and is not copied.
    assert "SMTP_PASSWORD=\n" not in text.replace("SMTP_PASSWORD=s3cret\n", "")


def test_migrate_leaves_an_existing_env_alone(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    env = tmp_path / ".env"
    env.write_text("KEEP=1\n", encoding="utf-8")

    assert migrate_legacy_secrets(env, legacy) is False
    assert env.read_text(encoding="utf-8") == "KEEP=1\n"


def test_ensure_copies_example_when_no_legacy_files(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("INTERNAL_API_TOKEN=\n", encoding="utf-8")
    env = tmp_path / ".env"

    ensure_env_file(env, example, tmp_path / "secrets")

    assert env.read_text(encoding="utf-8") == "INTERNAL_API_TOKEN=\n"


def test_ensure_prefers_legacy_files_over_example(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    example = tmp_path / ".env.example"
    example.write_text("INTERNAL_API_TOKEN=\n", encoding="utf-8")
    env = tmp_path / ".env"

    ensure_env_file(env, example, legacy)

    assert "SMTP_PASSWORD=s3cret" in env.read_text(encoding="utf-8")
