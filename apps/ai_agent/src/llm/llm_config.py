"""Loads configs/config_gateways.json - per-gateway base_url/model presets for
each provider (e.g. anthropic -> openrouter/bedrock/vertex).

Real secrets never live in that file: any "{ENV_VAR_NAME}" string value is
a pointer, resolved here against the process environment (populated from
.env by agent_config.py's _load_secrets_into_environ) - never
taken literally. A gateway block with an unresolved placeholder just
yields None for that key, same as the var being blank in .env.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agents.agent_spec import TIERS
from src.core.catalog import catalog
from src.core.seed import seed_from_example

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_gateways.json"
_PLACEHOLDER = re.compile(r"^\{([A-Z0-9_]+)\}$")

_config: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _config
    if _config is None:
        seed_from_example(_CONFIG_PATH)
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
    config_gateways.json."""
    block = _load()[provider][gateway_name]
    return {key: _resolve(value) for key, value in block.items()}


@dataclass(frozen=True)
class TierModel:
    """One model a gateway offers for a strength tier."""

    id: str
    use_for: str


def _text(entry: dict[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.{key} must be a non-empty string")
    return value.strip()


@catalog
def tiers(provider: str, gateway_name: str) -> dict[str, TierModel]:
    """The strength tiers one gateway offers, e.g. tiers("anthropic",
    "claude") - {"light": TierModel(...), ...} in ladder order (light,
    standard, heavy), from the block's optional `models` map. A tier whose
    `id` is an {ENV_VAR} placeholder that is unset is left out. Returns {}
    when the block has no `models`. Raises KeyError if provider/gateway_name
    isn't in config_gateways.json and ValueError for a malformed `models`."""
    models = _load()[provider][gateway_name].get("models")
    if models is None:
        return {}
    where = f"config_gateways.json {provider}.{gateway_name}.models"
    if not isinstance(models, dict):
        raise ValueError(f"{where} must be an object")
    for name in models:
        if name not in TIERS:
            raise ValueError(f"{where}.{name} is not a tier (use: {', '.join(TIERS)})")
    found: dict[str, TierModel] = {}
    for name in TIERS:
        if name not in models:
            continue
        entry = models[name]
        if not isinstance(entry, dict):
            raise ValueError(f"{where}.{name} must be an object")
        use_for = _text(entry, "use_for", f"{where}.{name}")
        model_id = _resolve(_text(entry, "id", f"{where}.{name}"))
        if model_id:
            found[name] = TierModel(model_id, use_for)
    return found
