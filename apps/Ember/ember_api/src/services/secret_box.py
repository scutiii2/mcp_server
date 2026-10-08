"""Encrypting the header values of private extensions at rest.

Header values are secrets (a token the user's own MCP server wants). They are
stored as one Fernet token per extension, made with the key in ``.env``
(`EMBER_SECRETS_KEY`). The key is generated on first start. If it is later
lost or replaced, the stored headers cannot be read; the extensions that need
them report an error until their headers are entered again. The key is never
printed or logged.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from src.utils.config_loader import load_env_secrets

KEY_NAME = "EMBER_SECRETS_KEY"

logger = logging.getLogger(__name__)


class SecretBoxError(Exception):
    """A key that is not valid, or a token that cannot be read. The message is safe to show."""


def ensure_secrets_key(env_path: Path) -> str:
    """The key in `env_path`; generated and written there first if it is missing or empty."""
    existing = load_env_secrets(env_path).get(KEY_NAME, "").strip()
    if existing:
        return existing
    key = Fernet.generate_key().decode("ascii")
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    empty_line = re.compile(rf"(?m)^{KEY_NAME}=\s*$")
    if empty_line.search(text):
        text = empty_line.sub(f"{KEY_NAME}={key}", text, count=1)
    else:
        newline = "" if not text or text.endswith("\n") else "\n"
        text = f"{text}{newline}{KEY_NAME}={key}\n"
    env_path.write_text(text, encoding="utf-8")
    logger.warning(
        "Generated %s and wrote it to %s. Keep it with any backup of that file: without it the saved "
        "headers of private extensions cannot be read.",
        KEY_NAME,
        env_path.name,
    )
    return key


class SecretBox:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError, UnicodeEncodeError):
            raise SecretBoxError(
                f"{KEY_NAME} in .env is not a valid key. Remove the line to have a new one made "
                "(saved headers of private extensions will then need to be entered again)."
            ) from None

    def encrypt_map(self, values: dict[str, str]) -> str:
        payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt_map(self, token: str) -> dict[str, str]:
        try:
            loaded = json.loads(self._fernet.decrypt(token.encode("ascii")))
        except (InvalidToken, ValueError, UnicodeError):
            raise SecretBoxError("The stored headers can't be read") from None
        if not isinstance(loaded, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in loaded.items()
        ):
            raise SecretBoxError("The stored headers can't be read")
        return loaded
