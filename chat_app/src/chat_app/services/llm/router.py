"""Provider registry and dispatch.

The only file that imports both provider modules. Routes never talk to
``openai_provider``/``claude_provider`` directly - only through here, so
adding a third provider later means touching this file and nothing else
on the routing side.
"""

from __future__ import annotations

from typing import Any

from chat_app.services.llm import claude_provider, cooldown, ollama_provider, openai_provider
from chat_app.services.llm.base import ChatResult, ProviderSpec


_PROVIDERS: dict[str, ProviderSpec] = {
    openai_provider.PROVIDER.id: openai_provider.PROVIDER,
    claude_provider.PROVIDER.id: claude_provider.PROVIDER,
    ollama_provider.PROVIDER.id: ollama_provider.PROVIDER,
}

# First entry tried first. Change this order to change which provider
# "Automatic" prefers when more than one is available.
#
# ollama_provider is deliberately NOT in this list - see its module
# docstring for why. It's still fully selectable manually from the
# provider dropdown (list_providers() below shows every entry in
# _PROVIDERS regardless of AUTOMATIC_ORDER); it just never gets picked
# silently on your behalf.
AUTOMATIC_ORDER: list[str] = [
    openai_provider.PROVIDER.id,
    claude_provider.PROVIDER.id,
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
    available whenever at least one AUTOMATIC_ORDER provider is - NOT
    whenever any registered provider is. Those aren't the same set:
    ollama_provider is registered (so it's manually selectable) but
    deliberately excluded from AUTOMATIC_ORDER (see its module
    docstring), so it being available must not make "Automatic" claim
    to be available too - _pick_automatic() would never actually try it."""
    entries = []
    for provider in _PROVIDERS.values():
        remaining = cooldown.seconds_remaining(provider.id)
        reason = None
        if remaining > 0:
            reason = "rate_limited"
        elif not provider.has_api_key():
            reason = "missing_key"

        # Called at most once per provider per request - its result feeds
        # BOTH the provider-level and every per-model available/reason
        # field below, never two separate calls for the two uses.
        availability = provider.check_models() if provider.check_models is not None else None

        if availability is not None:
            models = [
                {
                    "id": m.id,
                    "label": m.label,
                    "available": availability.models[m.id].available,
                    "reason": availability.models[m.id].reason,
                }
                for m in provider.models
            ]
            provider_available = provider.is_available() and availability.reachable
            if not availability.reachable:
                # A provider whose reachability can't be confirmed
                # shouldn't claim to be available - but this must not
                # stomp a higher-priority reason that's already set
                # (rate_limited/missing_key both win over "unreachable").
                reason = reason or availability.reason
        else:
            # No live check for this provider - every model is
            # unconditionally available, same as before this feature
            # existed. Keeps the shape uniform so the frontend never has
            # to special-case by provider id.
            models = [{"id": m.id, "label": m.label, "available": True, "reason": None} for m in provider.models]
            provider_available = provider.is_available()

        entries.append(
            {
                "id": provider.id,
                "label": provider.label,
                "available": provider_available,
                "reason": reason,
                "cooldown_seconds_remaining": int(remaining),
                "models": models,
                "default_model_id": provider.default_model_id,
            }
        )

    any_automatic_available = any(_PROVIDERS[provider_id].is_available() for provider_id in AUTOMATIC_ORDER)
    automatic_entry = {
        "id": AUTOMATIC_ID,
        "label": AUTOMATIC_LABEL,
        "available": any_automatic_available,
        "reason": None if any_automatic_available else "none_available",
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
    enabled_extensions: list[str] | None = None,
    chat_id: str | None = None,
) -> ChatResult:
    provider_id = provider_id or DEFAULT_PROVIDER_ID

    if provider_id == AUTOMATIC_ID:
        # Automatic doesn't take a model override - whichever provider it
        # resolves to uses its own default. Mixing "pick any provider" with
        # "but insist on this specific model" gets confusing fast, and the
        # model dropdown is hidden client-side whenever Automatic is
        # selected for exactly this reason. enabled_extensions/chat_id
        # have nothing to do with that - they still need to reach whichever
        # provider gets picked, so both are forwarded by keyword here
        # rather than positionally (which would require also passing a
        # model).
        provider = _pick_automatic()
        return provider.run_chat(question, history, enabled_extensions=enabled_extensions, chat_id=chat_id)

    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider '{provider_id}'")
    if not provider.has_api_key():
        raise ValueError(f"{provider.label} is not configured (missing API key)")
    if cooldown.is_in_cooldown(provider_id):
        remaining = int(cooldown.seconds_remaining(provider_id))
        raise ValueError(f"{provider.label} is rate-limited right now - try again in {remaining}s, or pick another provider")
    return provider.run_chat(question, history, model_id, enabled_extensions, chat_id=chat_id)