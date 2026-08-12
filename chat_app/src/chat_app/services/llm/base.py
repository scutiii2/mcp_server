"""The shape every LLM provider implements.

A provider is anything that can turn (question, history) into a final
answer, using MCP tools along the way. Providers differ wildly in their
own wire format - OpenAI's Responses API vs. Anthropic's Messages API
have different tool-schema shapes and different response-parsing rules -
but nothing outside ``services/llm/`` needs to know that. ``router.py`` is
the only thing that talks to a ``ProviderSpec`` directly; everything else
(routes, templates) just picks a provider id and, optionally, a model id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ChatResult:
    response: str
    tools_used: list[str] = field(default_factory=list)
    provider_id: str = ""


@dataclass
class ModelOption:
    id: str
    label: str


# model is optional - None means "use this provider's own default".
RunChatFn = Callable[[str, list[dict[str, Any]], "str | None"], ChatResult]
IsAvailableFn = Callable[[], bool]


@dataclass
class ProviderSpec:
    id: str
    label: str
    has_api_key: IsAvailableFn
    is_available: IsAvailableFn
    run_chat: RunChatFn
    models: list[ModelOption] = field(default_factory=list)
    default_model_id: str = ""
