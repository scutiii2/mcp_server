"""Provider registry and dispatch.

The only file that imports both provider modules. Routes never talk to
``openai_provider``/``claude_provider`` directly - only through here, so
adding a third provider later means touching this file and nothing else
on the routing side.
"""

from __future__ import annotations

from typing import Any

from chat_app.services.llm import claude_provider, cooldown, openai_provider, sap_ai_hub_provider
from chat_app.services.llm.base import ChatResult, ProviderSpec


_PROVIDERS: dict[str, ProviderSpec] = {
    openai_provider.PROVIDER.id: openai_provider.PROVIDER,
    claude_provider.PROVIDER.id: claude_provider.PROVIDER,
    sap_ai_hub_provider.PROVIDER.id: sap_ai_hub_provider.PROVIDER,
}

# First entry tried first. Change this order to change which provider
# "Automatic" prefers when more than one is available. SAP AI Hub is
# listed last by default since it typically proxies to the same
# underlying models OpenAI/Claude already offer directly, with more
# setup overhead (tenant-specific deployments) - reorder if your
# organization's policy prefers routing everything through SAP AI Core.
AUTOMATIC_ORDER: list[str] = [
    openai_provider.PROVIDER.id,
    claude_provider.PROVIDER.id,
    sap_ai_hub_provider.PROVIDER.id,
]

AUTOMATIC_ID = "auto"
AUTOMATIC_LABEL = "Automatic"

DEFAULT_PROVIDER_ID = AUTOMATIC_ID


def _pick_automatic() -> ProviderSpec:
    for provider_id in AUTOMATIC_ORDER:
        provider = _PROVIDERS[provider_id]
        if provider.is_available():
            return provider
    raise ValueError(
        "No provider is currently available - check that at least one API "
        "key is configured and not rate-limited."
    )


def list_providers() -> list[dict[str, Any]]:
    """Live availability, not a static list - reflects both whichever API
    keys are actually set right now and whether a provider is mid rate-limit
    cooldown from a previous request. "Automatic" is listed first and is
    available whenever at least one real provider is."""
    entries = []
    any_available = False
    for provider in _PROVIDERS.values():
        remaining = cooldown.seconds_remaining(provider.id)
        reason = None
        if remaining > 0:
            reason = "rate_limited"
        elif not provider.has_api_key():
            reason = "missing_key"
        available = provider.is_available()
        any_available = any_available or available
        entries.append(
            {
                "id": provider.id,
                "label": provider.label,
                "available": available,
                "reason": reason,
                "cooldown_seconds_remaining": int(remaining),
                "models": [{"id": m.id, "label": m.label} for m in provider.models],
                "default_model_id": provider.default_model_id,
            }
        )

    automatic_entry = {
        "id": AUTOMATIC_ID,
        "label": AUTOMATIC_LABEL,
        "available": any_available,
        "reason": None if any_available else "none_available",
        "cooldown_seconds_remaining": 0,
        "models": [],
        "default_model_id": "",
    }
    return [automatic_entry, *entries]


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    provider_id: str | None,
    model_id: str | None = None,
) -> ChatResult:
    provider_id = provider_id or DEFAULT_PROVIDER_ID

    if provider_id == AUTOMATIC_ID:
        # Automatic doesn't take a model override - whichever provider it
        # resolves to uses its own default. Mixing "pick any provider" with
        # "but insist on this specific model" gets confusing fast, and the
        # model dropdown is hidden client-side whenever Automatic is
        # selected for exactly this reason.
        provider = _pick_automatic()
        return provider.run_chat(question, history)

    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider '{provider_id}'")
    if not provider.has_api_key():
        raise ValueError(f"{provider.label} is not configured (missing API key)")
    if cooldown.is_in_cooldown(provider_id):
        remaining = int(cooldown.seconds_remaining(provider_id))
        raise ValueError(f"{provider.label} is rate-limited right now - try again in {remaining}s, or pick another provider")
    return provider.run_chat(question, history, model_id)
