"""One agent's sampling/reasoning settings (agents/<id>.json "llm"),
turned into provider request kwargs.

Models differ in what they accept (e.g. current Claude models reject a
non-default temperature; a non-reasoning OpenAI model rejects
`reasoning`). Rather than keep a per-model table, a parameter the API
refuses with a 400 is dropped for that model for the rest of this process's life, with
one warning - the turn then retries without it.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Any

from src.agents import agent_spec
from src.agents.agent_spec import LlmSpec

_log = logging.getLogger(__name__)

# Reasoning effort a delegating orchestrator asked for, for the turn being run
# (agent_config.run_chat binds it per turn, like approvals and tool_filter).
# None = the agent's own llm.reasoning_effort.
_effort_override: ContextVar[str | None] = ContextVar("llm_effort_override", default=None)


def bind_effort(effort: str | None) -> Token:
    return _effort_override.set(effort)


def reset_effort(token: Token) -> None:
    _effort_override.reset(token)

# Words in a 400's message that point at each option we may send.
_MARKERS = {
    "temperature": ("temperature",),
    "reasoning": ("output_config", "effort", "reasoning", "thinking"),
}


class LlmOptions:
    def __init__(self, provider_id: str, agent_id: str, llm: LlmSpec) -> None:
        self._provider_id = provider_id
        self._agent_id = agent_id
        self._llm = llm
        self._dropped: set[tuple[str, str]] = set()

    def max_tokens(self, default: int) -> int:
        return self._llm.max_tokens or default

    def max_tool_rounds(self, default: int) -> int:
        return self._llm.max_tool_rounds or default

    def _effort(self) -> str:
        return _effort_override.get() or self._llm.reasoning_effort

    def _sent(self, model: str) -> list[str]:
        sent = []
        if self._llm.temperature is not None and (model, "temperature") not in self._dropped:
            sent.append("temperature")
        if self._effort() != "off" and (model, "reasoning") not in self._dropped:
            sent.append("reasoning")
        return sent

    def extra_kwargs(self, model: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for option in self._sent(model):
            if option == "temperature":
                kwargs["temperature"] = self._llm.temperature
            elif self._provider_id == "anthropic":
                kwargs["output_config"] = {"effort": self._effort()}
            else:
                kwargs["reasoning"] = {"effort": self._effort()}
        return kwargs

    def drop_rejected(self, message: str, model: str) -> bool:
        """True when `message` (a 400's text) names an option we sent; that
        option is then never sent again to that model (other models still get
        it). False = not ours, re-raise."""
        text = message.lower()
        for option in self._sent(model):
            if any(marker in text for marker in _MARKERS[option]):
                self._dropped.add((model, option))
                _log.warning("agent %s: model %s rejected %s; no longer sending it to it", self._agent_id, model, option)
                return True
        return False


_cache: dict[str, LlmOptions] = {}


def for_provider(provider_id: str) -> LlmOptions:
    """This process's options for `provider_id`, built once from the agent spec."""
    if provider_id not in _cache:
        spec = agent_spec.current()
        _cache[provider_id] = LlmOptions(provider_id, spec.id, spec.llm)
    return _cache[provider_id]


def reset_cache() -> None:
    _cache.clear()
