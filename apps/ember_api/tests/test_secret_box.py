"""secret_box.py: the key in .env and the encryption of header maps."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.services.secret_box import KEY_NAME, SecretBox, SecretBoxError, ensure_secrets_key
from src.utils.config_loader import load_env_secrets
from tests.conftest import make_settings


def key() -> str:
    return Fernet.generate_key().decode("ascii")


def test_round_trip_and_the_token_hides_the_values():
    box = SecretBox(key())

    token = box.encrypt_map({"X-Api-Key": "s3cret-value", "Authorization": "Bearer t0ken"})

    assert "s3cret-value" not in token and "t0ken" not in token
    assert box.decrypt_map(token) == {"X-Api-Key": "s3cret-value", "Authorization": "Bearer t0ken"}


def test_a_token_made_with_another_key_cannot_be_read():
    token = SecretBox(key()).encrypt_map({"A": "b"})

    with pytest.raises(SecretBoxError):
        SecretBox(key()).decrypt_map(token)


def test_garbage_cannot_be_read():
    with pytest.raises(SecretBoxError):
        SecretBox(key()).decrypt_map("not a token")


def test_an_invalid_key_is_refused_with_a_clear_message():
    with pytest.raises(SecretBoxError, match=KEY_NAME):
        SecretBox("short")


def test_a_missing_key_is_generated_once_and_appended(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("INTERNAL_API_TOKEN=abc", encoding="utf-8")  # no trailing newline

    first = ensure_secrets_key(env)
    second = ensure_secrets_key(env)

    assert first == second
    text = env.read_text(encoding="utf-8")
    assert text.startswith("INTERNAL_API_TOKEN=abc\n")
    assert text.count(KEY_NAME) == 1
    assert load_env_secrets(env)[KEY_NAME] == first
    SecretBox(first)  # a usable key


def test_an_existing_key_is_kept(tmp_path: Path):
    env = tmp_path / ".env"
    mine = key()
    env.write_text(f"{KEY_NAME}={mine}\nOTHER=1\n", encoding="utf-8")

    assert ensure_secrets_key(env) == mine
    assert env.read_text(encoding="utf-8") == f"{KEY_NAME}={mine}\nOTHER=1\n"


def test_an_empty_key_line_is_filled_in_place(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(f"A=1\n{KEY_NAME}=\nB=2\n", encoding="utf-8")

    generated = ensure_secrets_key(env)

    text = env.read_text(encoding="utf-8")
    assert text == f"A=1\n{KEY_NAME}={generated}\nB=2\n"


def test_starting_the_app_creates_the_key_and_a_box(tmp_path: Path, client: TestClient):
    env = tmp_path / ".env"

    assert KEY_NAME in load_env_secrets(env)
    assert isinstance(client.app.state.secret_box, SecretBox)


def test_an_invalid_key_in_env_stops_startup(tmp_path: Path):
    from src.app import create_app

    settings = make_settings(tmp_path)
    settings.env_path.write_text(
        settings.env_path.read_text(encoding="utf-8") + f"{KEY_NAME}=not-a-key\n", encoding="utf-8"
    )

    with pytest.raises(SecretBoxError):
        with TestClient(create_app(settings)):
            pass
