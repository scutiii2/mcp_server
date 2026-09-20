"""Configured per-request token caps (output and context).

This is deliberately separate from model_limits.py: that module supplies
display-only model context windows, while this module enforces an operator
configured per-request policy. Usage counting and rate limits live in chat_app.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from src.catalog import catalog
from src.seed import seed_from_example

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_token_limits.json"
_REQUIRED_FIELDS = (
    "max_output_tokens",
    "max_context_tokens",
    "max_tool_rounds",
)
_config: dict[str, dict[str, Any]] | None = None


class ContextLimitError(ValueError):
    """Raised before an outbound request exceeds its configured context cap."""


def _load_config() -> dict[str, dict[str, Any]]:
    global _config
    if _config is not None:
        return _config
    seed_from_example(_CONFIG_PATH)
    raw = json.loads(_CONFIG_PATH.read_text())
    if not isinstance(raw, dict) or not isinstance(raw.get("default"), dict):
        raise ValueError("config_token_limits.json must contain a 'default' object")
    default = raw["default"]
    for field in _REQUIRED_FIELDS:
        if not isinstance(default.get(field), int) or default[field] <= 0:
            raise ValueError(f"config_token_limits.json default.{field} must be a positive integer")
    parsed: dict[str, dict[str, Any]] = {"default": dict(default)}
    for provider_id, override in raw.items():
        if provider_id == "default":
            continue
        if not isinstance(override, dict):
            raise ValueError(f"config_token_limits.json {provider_id} must be an object")
        parsed[provider_id] = dict(override)
        for field, value in override.items():
            if field == "gateways":
                if not isinstance(value, dict):
                    raise ValueError(f"config_token_limits.json {provider_id}.gateways must be an object")
                for gateway_id, gateway_override in value.items():
                    if not isinstance(gateway_override, dict):
                        raise ValueError(
                            f"config_token_limits.json {provider_id}.gateways.{gateway_id} must be an object"
                        )
                    for gateway_field, gateway_value in gateway_override.items():
                        if gateway_field not in _REQUIRED_FIELDS or not isinstance(gateway_value, int) or gateway_value <= 0:
                            raise ValueError(
                                f"config_token_limits.json {provider_id}.gateways.{gateway_id}.{gateway_field} "
                                "must be a positive known integer"
                            )
                continue
            if field not in _REQUIRED_FIELDS or not isinstance(value, int) or value <= 0:
                raise ValueError(f"config_token_limits.json {provider_id}.{field} must be a positive known integer")
    _config = parsed
    return parsed


@catalog
def limits_for(provider_id: str, gateway_id: str | None = None) -> dict[str, int]:
    """Return default, provider, and optional gateway-specific token limits."""
    config = _load_config()
    provider_override = config.get(provider_id, {})
    gateway_override = provider_override.get("gateways", {}).get(gateway_id, {})
    return {
        **config["default"],
        **{field: value for field, value in provider_override.items() if field in _REQUIRED_FIELDS},
        **gateway_override,
    }


@catalog
def max_output_tokens(provider_id: str, gateway_id: str | None = None) -> int:
    return limits_for(provider_id, gateway_id)["max_output_tokens"]


@catalog
def max_context_tokens(provider_id: str, gateway_id: str | None = None) -> int:
    return limits_for(provider_id, gateway_id)["max_context_tokens"]


@catalog
def max_tool_rounds(provider_id: str, gateway_id: str | None = None) -> int:
    """Max model<->tool rounds per ask() before giving up. A multi-step task
    needs one round per tool call plus one for the final answer."""
    return limits_for(provider_id, gateway_id)["max_tool_rounds"]


@catalog
def estimate_context_tokens(messages: list[Any]) -> int:
    """Conservatively estimate provider-neutral prompt tokens from request data."""
    encoded = json.dumps(messages, ensure_ascii=False, default=str, separators=(",", ":"))
    return max(1, math.ceil(len(encoded) / 4))


@catalog
def enforce_context_limit(provider_id: str, messages: list[Any], gateway_id: str | None = None) -> None:
    estimated = estimate_context_tokens(messages)
    limit = max_context_tokens(provider_id, gateway_id)
    if estimated > limit:
        raise ContextLimitError(
            f"{provider_id} request context is approximately {estimated} tokens; configured limit is {limit}"
        )


@catalog
def trim_history_to_fit(
    history: list[Any], provider_id: str, gateway_id: str | None = None, reserve_ratio: float = 0.5,
) -> list[Any]:
    """Defensive fallback for callers that skip chat_app's own summarizer
    (e.g. a direct MCP client hitting ai_agent's `ask` tool without ever
    going through chat_app's phase-5 auto-summarize). Drops oldest turns,
    two at a time to keep any user/assistant pairing intact, until the
    remaining history's estimated size fits within reserve_ratio of this
    provider+gateway's configured max_context_tokens - leaving headroom for
    the system prompt, tool schemas, and this turn's own question/answer.
    Not a replacement for proactive summarization: this only prevents
    unbounded blow-up, it throws away content rather than condensing it.
    """
    if not history:
        return history
    budget = max_context_tokens(provider_id, gateway_id) * reserve_ratio
    trimmed = history
    while len(trimmed) > 2 and estimate_context_tokens(trimmed) > budget:
        trimmed = trimmed[2:]
    return trimmed


@catalog
def reset_cache() -> None:
    """Clear only the module's config cache; primarily useful after config reloads."""
    global _config
    _config = None
