"""Loads configs/config_llms.json - per-gateway base_url/model presets for
each provider (e.g. anthropic -> openrouter/bedrock/vertex).

Real secrets never live in that file: any "{ENV_VAR_NAME}" string value is
a pointer, resolved here against the process environment (populated from
secret_llm.env by agent_config.py's _load_secrets_into_environ) - never
taken literally. A gateway block with an unresolved placeholder just
yields None for that key, same as the var being blank in secret_llm.env.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from src.catalog import catalog

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_llms.json"
_PLACEHOLDER = re.compile(r"^\{([A-Z0-9_]+)\}$")

_config: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _config
    if _config is None:
        _config = json.loads(_CONFIG_PATH.read_text())
    return _config


def _resolve(value: Any) -> Any:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value)
        if match:
            return os.getenv(match.group(1)) or None
    return value


@catalog
def gateway(provider: str, gateway_name: str) -> dict[str, Any]:
    """One gateway's config block, e.g. gateway("anthropic", "openrouter")
    - {ENV_VAR} placeholders resolved to their live env var value (None if
    that var is unset). Raises KeyError if provider/gateway_name isn't in
    config_llms.json."""
    block = _load()[provider][gateway_name]
    return {key: _resolve(value) for key, value in block.items()}
