"""Validate caller-supplied history before it reaches a provider."""

from typing import Any

from src.core.catalog import catalog


@catalog
def validate_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Copy text-only user/assistant messages; reject privileged roles and SDK items.

    Tool activity is created by the provider loop, never accepted from callers.
    Validate the whole history before trimming so discarded items cannot hide
    an invalid request. Errors name the position, never echo message contents.
    """
    if not isinstance(history, list):
        raise ValueError("history must be a list of user/assistant text messages")
    validated = []
    for index, message in enumerate(history):
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] not in ("user", "assistant")
            or not isinstance(message["content"], str)
        ):
            raise ValueError(f"history[{index}] must contain only a user/assistant role and string content")
        validated.append({"role": message["role"], "content": message["content"]})
    return validated
