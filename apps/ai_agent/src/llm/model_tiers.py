"""Model strength tiers for one agent: which tiers its gateway offers inside
its min_tier/max_tier range, and which model a requested tier resolves to.

Pure logic over llm_config.tiers() and the agent spec - no provider or SDK
imports. A request outside the range is clamped to the nearest effective tier
(ties go to the weaker one), never refused: the agent enforces its own cap, so
a stale or careless caller cannot push it past it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from src.agents import agent_spec
from src.agents.agent_spec import TIERS, TierInfo
from src.llm import llm_config

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resolution:
    """The model a turn runs on. `tier` is None when the default model was
    used; `note` says why a request was changed ("" when it was not)."""

    model: str | None
    tier: str | None
    note: str = ""


def effective_tiers(provider: str, gateway: str, min_tier: str | None, max_tier: str | None) -> list[TierInfo]:
    """The gateway's tiers inside [min_tier, max_tier], weakest first. Empty
    when the gateway is unknown or defines no `models`."""
    try:
        defined = llm_config.tiers(provider, gateway)
    except KeyError:
        return []
    low = TIERS.index(min_tier) if min_tier else 0
    high = TIERS.index(max_tier) if max_tier else len(TIERS) - 1
    found = [
        TierInfo(name, model.id, model.use_for)
        for name, model in defined.items()
        if low <= TIERS.index(name) <= high
    ]
    if defined and not found:
        _log.warning(
            "gateway %s/%s defines no tier inside min_tier=%s max_tier=%s; this agent offers no model choice",
            provider, gateway, min_tier, max_tier,
        )
    return found


def resolve(requested: str | None, effective: Sequence[TierInfo], default_model: str | None, agent_id: str) -> Resolution:
    """Turn a requested tier into a model. No request, or nothing to choose
    from: the default model, silently. An unknown name: the default model with
    a note. A tier outside the range: the nearest effective tier with a note."""
    if not requested:
        return Resolution(default_model, None)
    if requested not in TIERS:
        return Resolution(default_model, None, f"unknown model_tier {requested!r}; ran on {agent_id}'s default model")
    if not effective:
        return Resolution(default_model, None)
    by_name = {t.tier: t for t in effective}
    if requested in by_name:
        return Resolution(by_name[requested].id, requested)
    want = TIERS.index(requested)
    chosen = min(effective, key=lambda t: (abs(TIERS.index(t.tier) - want), TIERS.index(t.tier)))
    return Resolution(chosen.id, chosen.tier, f"{requested} is not available for {agent_id}; ran on {chosen.tier}")


def own_tiers() -> list[TierInfo]:
    """This process's agent's effective tiers (its gateway from
    AI_AGENT_GATEWAY, which the supervisor pins - see agent_spec.apply_to_environ)."""
    spec = agent_spec.current()
    provider = spec.llm.provider
    if provider == "laya":
        return []
    gateway = os.getenv("AI_AGENT_GATEWAY") or agent_spec.default_gateway(provider)
    if not gateway:
        return []
    return effective_tiers(provider, gateway, spec.llm.min_tier, spec.llm.max_tier)


def as_records(tiers: Iterable[TierInfo]) -> list[dict[str, str]]:
    """The registry form of an agent's tiers (JSON-serializable)."""
    return [{"tier": t.tier, "id": t.id, "use_for": t.use_for} for t in tiers]


def from_records(records: Any) -> tuple[TierInfo, ...]:
    """Read registry records back; anything malformed is skipped, since the
    registry file is written by other processes."""
    if not isinstance(records, list):
        return ()
    found = []
    for record in records:
        if (
            isinstance(record, dict)
            and record.get("tier") in TIERS
            and all(isinstance(record.get(key), str) and record[key] for key in ("id", "use_for"))
        ):
            found.append(TierInfo(record["tier"], record["id"], record["use_for"]))
    return tuple(found)
