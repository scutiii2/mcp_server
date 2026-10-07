# Model Tiers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each gateway offer several models of different strength (`light` / `standard` / `heavy`), let the orchestrator pick one per delegated task, and let each agent cap the tiers it may run on with `llm.min_tier` / `llm.max_tier`.

**Architecture:** A fixed tier ladder lives in `agent_spec`. `llm_config.tiers()` reads an optional `models` map from a gateway block. A new pure module `src/llm/model_tiers.py` intersects a gateway's tiers with an agent's cap and resolves a requested tier (clamping out-of-range requests). Each agent publishes its allowed tiers in the registry; the orchestrator's roster and `delegate_to_agent` schema expose them; the specialist's `ask` tool accepts `model_tier`, resolves it against its own cap, and passes the resulting model id to the unchanged provider `run_chat(model=...)`.

**Tech Stack:** Python 3, FastMCP, pytest (run from `apps/ai_agent`), JSON config files.

**Spec:** `apps/ai_agent/docs/spec_model_tiers.md`

## Global Constraints

- Tier ladder is exactly `("light", "standard", "heavy")`, weakest to strongest.
- `model` in a gateway block stays the default model; `models` is optional. A gateway without `models` offers no choice and behaves exactly as today.
- `min_tier` / `max_tier` live inside the agent file's `llm` object. Omitted = no bound on that side. Laya agents reject both.
- A request outside an agent's range, or for a tier its gateway lacks, is **clamped** to the nearest effective tier (ties go to the weaker tier) with a note. It is never an error. The specialist enforces its own cap.
- `model_tier` / `model_note` appear in `ask`'s result, and `model_tier` in the usage row, **only when set**; `tiers` appears in a registry record only when non-empty. This keeps every existing exact-shape test valid.
- The provider `run_chat` signatures do not change. The resolved model id goes in the existing `model` argument.
- `agents/*.json` (except templates) and `configs/config_*.json` are gitignored, local to each machine. Only `.template` / `.example` files are committed.
- Every command below runs from `apps/ai_agent` (the repo root is two levels up). `PY` means `.venv_ai_agent/Scripts/python.exe`.
- Commit messages end with a `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` trailer (second `-m`).

## File Structure

| File | Responsibility |
|------|----------------|
| `src/agents/agent_spec.py` (modify) | `TIERS`, `TierInfo`, `LlmSpec.min_tier/max_tier`, validation, `default_gateway()`, `RosterEntry.tiers` |
| `src/llm/llm_config.py` (modify) | `TierModel`, `tiers(provider, gateway)` reads and validates a gateway's `models` |
| `src/llm/model_tiers.py` (new) | Pure tier logic: `effective_tiers`, `resolve`, `own_tiers`, `as_records`, `from_records`, `Resolution` |
| `src/llm/base_provider.py` (modify) | `ChatResult.model_tier`, `ChatResult.model_note` |
| `src/agents/agent_config.py` (modify) | `run_chat(model_tier=...)` resolves tier to model id |
| `src/server.py` (modify) | `ask(model_tier=...)`, result fields, register tiers at startup |
| `src/core/usage_log.py` (modify) | `own_row(model_tier=...)` |
| `src/agents/agent_registry.py` (modify) | `register(tiers=...)` |
| `src/agents/agent_routing.py` (modify) | `specialists()` fills `RosterEntry.tiers` |
| `src/agents/delegation.py` (modify) | `model_tier` schema property, tier text, `call(model_tier=)`, note prefix, `dispatch()` |
| `src/llm/anthropic_provider.py`, `src/llm/openai_provider.py` (modify) | `_dispatch` calls `delegation.dispatch` |
| `configs/config_gateways.json.example`, `agents/agents.json.template`, `configs/README.md` (modify) | Committed examples and docs |
| `tests/test_llm_config.py` (new), `tests/test_model_tiers.py` (new), plus additions to existing test files | Tests |

---

### Task 1: Gateway `models` config and `llm_config.tiers()`

**Files:**
- Modify: `src/agents/agent_spec.py` (add `TIERS` only; the rest lands in Task 2)
- Modify: `src/llm/llm_config.py`
- Modify: `configs/config_gateways.json.example`
- Create: `tests/test_llm_config.py`

**Interfaces:**
- Produces: `agent_spec.TIERS: tuple[str, ...] == ("light", "standard", "heavy")`; `llm_config.TierModel(id: str, use_for: str)` (frozen dataclass); `llm_config.tiers(provider: str, gateway_name: str) -> dict[str, TierModel]` in ladder order, `{}` when the block has no `models`, raises `KeyError` for an unknown provider/gateway and `ValueError` for a malformed `models`.

- [ ] **Step 0: Commit the spec and this plan**

```bash
git add docs/spec_model_tiers.md ../../docs/superpowers/plans/2026-10-08-model-tiers.md
git commit -m "docs(ai_agent): spec and plan for per-gateway model tiers" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_config.py`:

```python
"""llm_config.tiers(): reads a gateway block's optional `models` map."""

from __future__ import annotations

import pytest

from src.llm import llm_config


def _use(monkeypatch, block):
    monkeypatch.setattr(llm_config, "_config", {"anthropic": {"claude": block}})


def test_tiers_are_returned_in_ladder_order_with_trimmed_use_for(monkeypatch):
    _use(monkeypatch, {"models": {
        "heavy": {"id": "opus", "use_for": "hard"},
        "light": {"id": "haiku", "use_for": "  quick  "},
    }})

    found = llm_config.tiers("anthropic", "claude")

    assert list(found) == ["light", "heavy"]
    assert found["light"] == llm_config.TierModel("haiku", "quick")


def test_no_models_means_no_tiers(monkeypatch):
    _use(monkeypatch, {"model": "sonnet"})
    assert llm_config.tiers("anthropic", "claude") == {}


def test_a_placeholder_id_is_resolved_from_the_environment(monkeypatch):
    monkeypatch.setenv("TIER_TEST_MODEL", "my-deployment")
    _use(monkeypatch, {"models": {"standard": {"id": "{TIER_TEST_MODEL}", "use_for": "most"}}})
    assert llm_config.tiers("anthropic", "claude")["standard"].id == "my-deployment"


def test_a_tier_whose_placeholder_is_unset_is_dropped(monkeypatch):
    monkeypatch.delenv("TIER_TEST_MODEL", raising=False)
    _use(monkeypatch, {"models": {
        "light": {"id": "{TIER_TEST_MODEL}", "use_for": "quick"},
        "heavy": {"id": "opus", "use_for": "hard"},
    }})
    assert list(llm_config.tiers("anthropic", "claude")) == ["heavy"]


def test_an_unknown_tier_name_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"giant": {"id": "x", "use_for": "y"}}})
    with pytest.raises(ValueError, match="anthropic.claude.models.giant is not a tier"):
        llm_config.tiers("anthropic", "claude")


def test_a_tier_without_use_for_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"light": {"id": "x"}}})
    with pytest.raises(ValueError, match="light.use_for must be a non-empty string"):
        llm_config.tiers("anthropic", "claude")


def test_a_tier_without_id_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"light": {"use_for": "y"}}})
    with pytest.raises(ValueError, match="light.id must be a non-empty string"):
        llm_config.tiers("anthropic", "claude")


def test_models_must_be_an_object(monkeypatch):
    _use(monkeypatch, {"models": ["light"]})
    with pytest.raises(ValueError, match="models must be an object"):
        llm_config.tiers("anthropic", "claude")


def test_an_unknown_gateway_raises_key_error(monkeypatch):
    _use(monkeypatch, {})
    with pytest.raises(KeyError):
        llm_config.tiers("anthropic", "nope")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_llm_config.py -v`
Expected: FAIL with `AttributeError: module 'src.llm.llm_config' has no attribute 'tiers'`.

- [ ] **Step 3: Add `TIERS` to `agent_spec.py`**

In `src/agents/agent_spec.py`, directly under the `REASONING_EFFORTS = ...` line (line 29), add:

```python
# Model strength, weakest to strongest. Fixed so min_tier/max_tier can be
# compared and the orchestrator sees one vocabulary across every gateway.
TIERS = ("light", "standard", "heavy")
```

- [ ] **Step 4: Implement `tiers()` in `llm_config.py`**

In `src/llm/llm_config.py`, change the imports block to:

```python
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agents.agent_spec import TIERS
from src.core.catalog import catalog
from src.core.seed import seed_from_example
```

Append at the end of the file:

```python


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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_llm_config.py -v`
Expected: 9 passed.

- [ ] **Step 6: Add the example config**

In `configs/config_gateways.json.example`, replace the `claude` block:

```json
    "claude": {
      "label": "Claude",
      "api_key": "{CLAUDE_API_KEY}",
      "model": "claude-sonnet-5"
    },
```

with:

```json
    "claude": {
      "label": "Claude",
      "api_key": "{CLAUDE_API_KEY}",
      "model": "claude-sonnet-5",
      "models": {
        "light": { "id": "claude-haiku-4-5", "use_for": "lookups, extraction, short rewrites, simple formatting" },
        "standard": { "id": "claude-sonnet-5", "use_for": "most tasks" },
        "heavy": { "id": "claude-opus-5", "use_for": "multi-step reasoning, hard code or data analysis" }
      }
    },
```

Confirm the three ids against your Anthropic account before relying on them.

- [ ] **Step 7: Run the whole suite, then commit**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest -q`
Expected: all pass (no behavior changed yet).

```bash
git add src/agents/agent_spec.py src/llm/llm_config.py configs/config_gateways.json.example tests/test_llm_config.py
git commit -m "feat(ai_agent): read per-gateway model tiers from config_gateways.json" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Agent file `min_tier` / `max_tier` and roster tier types

**Files:**
- Modify: `src/agents/agent_spec.py`
- Modify: `agents/agents.json.template`
- Test: `tests/test_agent_spec.py`

**Interfaces:**
- Consumes: `agent_spec.TIERS` (Task 1).
- Produces: `LlmSpec.min_tier: str | None = None`, `LlmSpec.max_tier: str | None = None`; `TierInfo(tier: str, id: str, use_for: str)` (frozen dataclass); `RosterEntry.tiers: tuple[TierInfo, ...] = ()`; `agent_spec.default_gateway(provider: str) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_spec.py`:

```python
def test_llm_min_and_max_tier_are_read(tmp_path):
    spec = agent_spec.load_file(_write(tmp_path, "calc", {
        "port": 9103, "llm": {"provider": "anthropic", "min_tier": "light", "max_tier": "standard"},
    }))
    assert (spec.llm.min_tier, spec.llm.max_tier) == ("light", "standard")


def test_llm_tiers_default_to_unbounded(tmp_path):
    spec = agent_spec.load_file(_write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic"}}))
    assert (spec.llm.min_tier, spec.llm.max_tier) == (None, None)


@pytest.mark.parametrize("key", ["min_tier", "max_tier"])
def test_unknown_tier_name_is_rejected(tmp_path, key):
    path = _write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic", key: "giant"}})
    with pytest.raises(AgentSpecError, match=f"llm.{key} must be one of: light, standard, heavy"):
        agent_spec.load_file(path)


def test_min_tier_above_max_tier_is_rejected(tmp_path):
    path = _write(tmp_path, "calc", {
        "port": 9103, "llm": {"provider": "anthropic", "min_tier": "heavy", "max_tier": "light"},
    })
    with pytest.raises(AgentSpecError, match="llm.min_tier 'heavy' is stronger than llm.max_tier 'light'"):
        agent_spec.load_file(path)


@pytest.mark.parametrize("key", ["min_tier", "max_tier"])
def test_laya_rejects_tier_bounds(tmp_path, key):
    path = _write(tmp_path, "triage", {"port": 9110, "llm": {"provider": "laya", key: "light"}})
    with pytest.raises(AgentSpecError, match="Laya triage does not accept"):
        agent_spec.load_file(path)


def test_default_gateway_per_provider():
    assert agent_spec.default_gateway("anthropic") == "claude"
    assert agent_spec.default_gateway("openai") == "gpt"
    assert agent_spec.default_gateway("laya") == "local"
    assert agent_spec.default_gateway("unknown") is None


def test_roster_entry_tiers_default_to_empty():
    assert agent_spec.RosterEntry("calc", "Calculator", "Math.").tiers == ()
    tier = agent_spec.TierInfo("light", "haiku", "quick")
    assert agent_spec.RosterEntry("calc", "Calculator", "Math.", (tier,)).tiers == (tier,)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_agent_spec.py -v -k "tier or default_gateway"`
Expected: FAIL (`llm.min_tier is not a known field`, `AttributeError: ... default_gateway`, `TierInfo`).

- [ ] **Step 3: Implement in `agent_spec.py`**

1. Extend `_LLM_KEYS` (line 39):

```python
_LLM_KEYS = {"provider", "gateway", "model", "temperature", "reasoning_effort", "max_tokens", "max_tool_rounds", "min_tier", "max_tier"}
```

2. Extend `LlmSpec` (after `max_tool_rounds`):

```python
    min_tier: str | None = None
    max_tier: str | None = None
```

3. Replace the `RosterEntry` dataclass with:

```python
@dataclass(frozen=True)
class TierInfo:
    """One model strength an agent may run on, as the orchestrator sees it."""

    tier: str
    id: str
    use_for: str


@dataclass(frozen=True)
class RosterEntry:
    """One specialist as the orchestrator sees it."""

    id: str
    label: str
    focus: str
    tiers: tuple[TierInfo, ...] = ()
```

4. Add a `tier` helper to `_Checker` (after `globs`):

```python
    def tier(self, data: dict[str, Any], key: str, prefix: str = "") -> str | None:
        value = data.get(key)
        if value is None:
            return None
        if value not in TIERS:
            raise self.fail(f"{prefix}{key}", f"must be one of: {', '.join(TIERS)}")
        return value
```

5. In `load_file`, directly before `llm = LlmSpec(` add:

```python
    min_tier = check.tier(llm_data, "min_tier", "llm.")
    max_tier = check.tier(llm_data, "max_tier", "llm.")
    if min_tier and max_tier and TIERS.index(min_tier) > TIERS.index(max_tier):
        raise check.fail("llm.min_tier", f"{min_tier!r} is stronger than llm.max_tier {max_tier!r}")
```

and add `min_tier=min_tier, max_tier=max_tier,` as the last two keyword arguments of that `LlmSpec(...)` call.

6. In the Laya block, extend the generation-settings tuple:

```python
        if any(key in llm_data for key in ("temperature", "max_tokens", "max_tool_rounds", "min_tier", "max_tier")) or effort != "off":
```

7. Add under `from_env()`'s predecessor helpers (anywhere at module level after `_DEFAULT_GATEWAY`'s use, e.g. just above `class AgentSpecError`):

```python
def default_gateway(provider: str) -> str | None:
    """The gateway a provider uses when an agent names none."""
    return _DEFAULT_GATEWAY.get(provider)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_agent_spec.py -v`
Expected: all pass, including the pre-existing Laya parametrized test.

- [ ] **Step 5: Update the committed template**

In `agents/agents.json.template`, change the `llm` object so it ends:

```json
    "max_tokens": 4096,
    "max_tool_rounds": 6,
    "max_tier": "standard"
  },
```

- [ ] **Step 6: Run the whole suite, then commit**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest -q`
Expected: all pass.

```bash
git add src/agents/agent_spec.py agents/agents.json.template tests/test_agent_spec.py
git commit -m "feat(ai_agent): llm.min_tier and llm.max_tier in agent files" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `model_tiers` module (effective tiers, resolve, registry records)

**Files:**
- Create: `src/llm/model_tiers.py`
- Create: `tests/test_model_tiers.py`

**Interfaces:**
- Consumes: `agent_spec.TIERS`, `agent_spec.TierInfo`, `agent_spec.default_gateway`, `agent_spec.current()`, `llm_config.tiers`.
- Produces:
  - `Resolution(model: str | None, tier: str | None, note: str = "")` (frozen dataclass)
  - `effective_tiers(provider: str, gateway: str, min_tier: str | None, max_tier: str | None) -> list[TierInfo]`
  - `resolve(requested: str | None, effective: Sequence[TierInfo], default_model: str | None, agent_id: str) -> Resolution`
  - `own_tiers() -> list[TierInfo]` (this process's agent, from its spec and `AI_AGENT_GATEWAY`)
  - `as_records(tiers: Iterable[TierInfo]) -> list[dict[str, str]]`
  - `from_records(records: Any) -> tuple[TierInfo, ...]` (tolerant of malformed input)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_model_tiers.py`:

```python
"""model_tiers.py tests: a gateway's tiers cut to an agent's cap, resolving a
requested tier (exact, clamped, invalid), and the registry record round trip."""

from __future__ import annotations

import logging

import pytest

from src.agents import agent_spec
from src.agents.agent_spec import AgentSpec, LlmSpec, TierInfo
from src.llm import llm_config, model_tiers

LIGHT = TierInfo("light", "haiku", "quick")
STANDARD = TierInfo("standard", "sonnet", "most")
HEAVY = TierInfo("heavy", "opus", "hard")
ALL = [LIGHT, STANDARD, HEAVY]

GATEWAY = {"models": {
    "light": {"id": "haiku", "use_for": "quick"},
    "standard": {"id": "sonnet", "use_for": "most"},
    "heavy": {"id": "opus", "use_for": "hard"},
}}


def _gateway(monkeypatch, block=GATEWAY):
    monkeypatch.setattr(llm_config, "_config", {"anthropic": {"claude": block}})


def test_effective_tiers_without_a_cap_is_the_whole_gateway(monkeypatch):
    _gateway(monkeypatch)
    assert model_tiers.effective_tiers("anthropic", "claude", None, None) == ALL


def test_effective_tiers_are_cut_to_the_range(monkeypatch):
    _gateway(monkeypatch)
    assert model_tiers.effective_tiers("anthropic", "claude", "standard", None) == [STANDARD, HEAVY]
    assert model_tiers.effective_tiers("anthropic", "claude", None, "standard") == [LIGHT, STANDARD]
    assert model_tiers.effective_tiers("anthropic", "claude", "standard", "standard") == [STANDARD]


def test_effective_tiers_of_a_gateway_without_models_or_unknown_is_empty(monkeypatch):
    _gateway(monkeypatch, {"model": "sonnet"})
    assert model_tiers.effective_tiers("anthropic", "claude", None, None) == []
    assert model_tiers.effective_tiers("anthropic", "nope", None, None) == []


def test_a_cap_that_excludes_every_defined_tier_warns(monkeypatch, caplog):
    _gateway(monkeypatch, {"models": {"light": {"id": "haiku", "use_for": "quick"}}})
    with caplog.at_level(logging.WARNING, logger="src.llm.model_tiers"):
        assert model_tiers.effective_tiers("anthropic", "claude", "heavy", None) == []
    assert "no tier inside" in caplog.text


def test_resolve_without_a_request_uses_the_default_model():
    assert model_tiers.resolve(None, ALL, "default-model", "calc") == model_tiers.Resolution("default-model", None)


def test_resolve_an_available_tier_is_exact_and_silent():
    assert model_tiers.resolve("heavy", ALL, "default-model", "calc") == model_tiers.Resolution("opus", "heavy")


def test_resolve_above_the_range_clamps_down_with_a_note():
    result = model_tiers.resolve("heavy", [LIGHT, STANDARD], "default-model", "pdf-assistant")
    assert (result.model, result.tier) == ("sonnet", "standard")
    assert result.note == "heavy is not available for pdf-assistant; ran on standard"


def test_resolve_below_the_range_clamps_up():
    result = model_tiers.resolve("light", [STANDARD, HEAVY], "default-model", "reviewer")
    assert (result.model, result.tier) == ("sonnet", "standard")
    assert "ran on standard" in result.note


def test_resolve_a_tie_goes_to_the_weaker_tier():
    result = model_tiers.resolve("standard", [LIGHT, HEAVY], "default-model", "calc")
    assert result.tier == "light"


def test_resolve_with_no_effective_tiers_uses_the_default_silently():
    assert model_tiers.resolve("heavy", [], "default-model", "calc") == model_tiers.Resolution("default-model", None)


def test_resolve_an_invalid_name_uses_the_default_with_a_note():
    result = model_tiers.resolve("giant", ALL, "default-model", "calc")
    assert (result.model, result.tier) == ("default-model", None)
    assert "unknown model_tier 'giant'" in result.note


def test_records_round_trip_and_malformed_records_are_skipped():
    records = model_tiers.as_records(ALL)
    assert records[0] == {"tier": "light", "id": "haiku", "use_for": "quick"}
    assert model_tiers.from_records(records) == tuple(ALL)
    assert model_tiers.from_records([{"tier": "giant", "id": "x", "use_for": "y"}, {"tier": "light"}, "junk"]) == ()
    assert model_tiers.from_records(None) == ()


def _use_spec(monkeypatch, provider="anthropic", **llm):
    spec = AgentSpec(id="calc", label="Calc", port=9103, llm=LlmSpec(provider=provider, **llm))
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_own_tiers_uses_this_agents_gateway_and_cap(monkeypatch):
    _gateway(monkeypatch)
    _use_spec(monkeypatch, max_tier="standard")
    monkeypatch.setenv("AI_AGENT_GATEWAY", "claude")
    assert model_tiers.own_tiers() == [LIGHT, STANDARD]


def test_own_tiers_falls_back_to_the_providers_default_gateway(monkeypatch):
    _gateway(monkeypatch)
    _use_spec(monkeypatch)
    monkeypatch.delenv("AI_AGENT_GATEWAY", raising=False)
    assert model_tiers.own_tiers() == ALL


def test_own_tiers_of_a_laya_agent_is_empty(monkeypatch):
    _use_spec(monkeypatch, provider="laya")
    assert model_tiers.own_tiers() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_model_tiers.py -v`
Expected: FAIL with `ImportError: cannot import name 'model_tiers' from 'src.llm'`.

- [ ] **Step 3: Implement `src/llm/model_tiers.py`**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_model_tiers.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/llm/model_tiers.py tests/test_model_tiers.py
git commit -m "feat(ai_agent): resolve a requested model tier against an agent's cap" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `ask(model_tier=...)` runs on the resolved model

**Files:**
- Modify: `src/llm/base_provider.py` (`ChatResult`)
- Modify: `src/agents/agent_config.py`
- Modify: `src/server.py`
- Modify: `src/core/usage_log.py`
- Test: `tests/test_agent_config.py`, `tests/test_server.py`, `tests/test_usage_log.py`

**Interfaces:**
- Consumes: `model_tiers.resolve`, `model_tiers.own_tiers`, `model_tiers.Resolution` (Task 3).
- Produces: `ChatResult.model_tier: str | None = None`, `ChatResult.model_note: str = ""`; `agent_config.run_chat(..., disabled_tools=None, model_tier: str | None = None)`; `server.ask(..., disabled_tools=None, model_tier: str | None = None, ctx=None)`; `usage_log.own_row(..., delegated_by, model_tier: str | None = None)`. `ask`'s result gains `model_tier` and `model_note` only when set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_config.py`:

```python
def test_run_chat_passes_the_resolved_tier_model_to_the_provider(monkeypatch):
    import asyncio

    from src.agents.agent_spec import TierInfo

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)
    monkeypatch.setattr(reloaded.model_tiers, "own_tiers", lambda: [TierInfo("light", "haiku", "q"), TierInfo("heavy", "opus", "h")])
    seen = {}

    async def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["model"] = model
        return ChatResult(response="x")

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

    result = asyncio.run(reloaded.run_chat("hi", [], [], model_tier="heavy"))
    assert seen["model"] == "opus"
    assert (result.model_tier, result.model_note) == ("heavy", "")

    result = asyncio.run(reloaded.run_chat("hi", [], [], model_tier="standard"))
    assert seen["model"] == "haiku"
    assert result.model_tier == "light"
    assert "ran on light" in result.model_note


def test_run_chat_without_a_tier_keeps_the_pinned_model(monkeypatch):
    import asyncio

    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key")
    monkeypatch.setenv("AI_AGENT_MODEL", "pinned-model")

    from src.agents import agent_config

    reloaded = importlib.reload(agent_config)
    seen = {}

    async def _fake_run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None, caveman=False):
        seen["model"] = model
        return ChatResult(response="x")

    monkeypatch.setattr(reloaded._PROVIDER_MODULE, "run_chat", _fake_run_chat)

    result = asyncio.run(reloaded.run_chat("hi", [], []))
    assert seen["model"] == "pinned-model"
    assert result.model_tier is None
```

Append to `tests/test_server.py`:

```python
def test_ask_passes_model_tier_and_reports_the_resolution():
    async def _run():
        fake_result = ChatResult(
            response="ok", provider_id="anthropic", model="haiku", model_tier="light",
            model_note="heavy is not available for calc; ran on light",
        )
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=fake_result) as fake_run_chat, \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            result = await server.ask("q", model_tier="heavy")

        assert fake_run_chat.call_args.kwargs["model_tier"] == "heavy"
        assert result["model_tier"] == "light"
        assert result["model_note"] == "heavy is not available for calc; ran on light"
        assert result["agent_usage"][0]["model_tier"] == "light"

    asyncio.run(_run())


def test_ask_without_a_tier_adds_no_tier_keys():
    async def _run():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=ChatResult(response="hi")) as fake_run_chat, \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}):
            result = await server.ask("q")

        assert "model_tier" not in fake_run_chat.call_args.kwargs
        assert "model_tier" not in result and "model_note" not in result
        assert "model_tier" not in result["agent_usage"][0]

    asyncio.run(_run())
```

Append to `tests/test_usage_log.py`:

```python
def test_own_row_records_model_tier_only_when_given():
    result = ChatResult(response="x", provider_id="anthropic", model="haiku")
    common = dict(
        agent_id="calc", agent_label="Calculator", gateway="claude",
        started_at="2026-10-08T09:00:00.000Z", finished_at="2026-10-08T09:00:01.000Z", delegated_by=None,
    )
    assert usage_log.own_row(result, **common, model_tier="light")["model_tier"] == "light"
    assert "model_tier" not in usage_log.own_row(result, **common)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_agent_config.py tests/test_server.py tests/test_usage_log.py -v -k "tier"`
Expected: FAIL (`ChatResult.__init__() got an unexpected keyword argument 'model_tier'`, `unexpected keyword argument 'model_tier'`).

- [ ] **Step 3: Add the `ChatResult` fields**

In `src/llm/base_provider.py`, after `delegated_usage` in `ChatResult` (line 147), add:

```python
    # The strength tier this turn ran on when the caller asked for one, and a
    # note when the request was changed (see llm/model_tiers.py).
    model_tier: str | None = None
    model_note: str = ""
```

- [ ] **Step 4: Resolve the tier in `agent_config.run_chat`**

In `src/agents/agent_config.py`:

1. Change the import `from src.agents import delegation` to:

```python
from src.agents import agent_spec, delegation
```

and add, next to the other `src.llm` imports (the `from src.llm import cancellation, cooldown  # noqa: E402` line stays as is), a new line directly after `from src.core import approvals, tool_filter`:

```python
from src.llm import model_tiers
```

2. Add `model_tier: str | None = None,` as the last parameter of `run_chat` (after `disabled_tools`), and one docstring paragraph:

```
    model_tier: a strength tier ("light"/"standard"/"heavy") the caller asks
    for (delegation.py). It is resolved against this agent's own tiers and
    cap (llm/model_tiers.py); a request outside the cap is clamped, with a
    note on the result. None keeps the pinned model.
```

3. Replace the body from `policy = ...` to the end of the function with:

```python
    # Validated before anything is registered: a bad mode must not start a turn.
    policy = approvals.ApprovalPolicy(approval_mode, set(allowed_tools or ()))
    resolution = (
        model_tiers.resolve(model_tier, model_tiers.own_tiers(), MODEL, agent_spec.current().id)
        if model_tier else model_tiers.Resolution(MODEL, None)
    )
    cancellation.register(request_id)
    delegated_usage, usage_token = delegation.bind_usage()
    approval_token = approvals.bind(policy)
    filter_token = tool_filter.bind(disabled_tools or ())
    try:
        if cancellation.is_cancelled(request_id):
            raise ChatCancelled()
        if inspect.iscoroutinefunction(_PROVIDER_MODULE.run_chat):
            result = await _PROVIDER_MODULE.run_chat(
                question, history, resolution.model, enabled_extensions, request_id, depth,
                on_event=on_event, caveman=caveman,
            )
            result.delegated_usage = delegated_usage
        else:
            # Phase 1: openai_provider is still sync - run it off the event
            # loop thread so a slow completion doesn't block other requests
            # this ai_agent process is serving. on_event is dropped here on
            # purpose: a sync provider has nowhere to await it from (Phase 3
            # converts openai_provider the same way Task 3 did anthropic_provider).
            result = await anyio.to_thread.run_sync(
                lambda: _PROVIDER_MODULE.run_chat(
                    question, history, resolution.model, enabled_extensions, request_id, depth,
                    caveman=caveman,
                )
            )
        result.model_tier = resolution.tier
        result.model_note = resolution.note
        return result
    finally:
        tool_filter.reset(filter_token)
        approvals.reset(approval_token)
        delegation.reset_usage(usage_token)
        cancellation.clear(request_id)
```

Keep the existing long docstring above `policy` (add only the `model_tier` paragraph). Do not touch `run_interpret`.

- [ ] **Step 5: `ask` accepts and reports the tier**

In `src/server.py`:

1. Add `model_tier: str | None = None,` after `disabled_tools: list[str] | None = None,` in `ask`'s parameter list (before `ctx`), and this docstring paragraph before the `ctx,` paragraph:

```
    model_tier: the strength of model to run this turn on ("light",
    "standard" or "heavy"), set by a delegating orchestrator. This agent
    resolves it against its own gateway tiers and min_tier/max_tier, so a
    request outside the cap runs on the nearest allowed tier; the result
    then carries `model_tier` and, when changed, `model_note`.
```

2. Replace the `run_chat` call and the `own_row` call and the `return {` in `ask` so the section reads:

```python
    try:
        tier_args = {"model_tier": model_tier} if model_tier else {}
        result = await agent_config.run_chat(
            question, history or [], enabled_extensions or [], request_id, depth,
            on_event=on_event, caveman=caveman, approval_mode=approval_mode, allowed_tools=allowed_tools,
            disabled_tools=disabled_tools, **tier_args,
        )
    except ChatCancelled:
        return _cancelled_result()
    finally:
        internal_auth.reset_requester(requester_token)
    own_usage = usage_log.own_row(
        result, agent_id=_AGENT_ID, agent_label=_AGENT_LABEL, gateway=SPEC.effective_gateway(),
        started_at=started_at, finished_at=agent_events.now_iso(), delegated_by=delegated_by,
        model_tier=result.model_tier,
    )
    await usage_log.append({**own_usage, "request_id": request_id, "depth": depth})
    reply = {
        # ... the existing dict, unchanged, assigned to `reply` instead of returned ...
    }
    if result.model_tier:
        reply["model_tier"] = result.model_tier
    if result.model_note:
        reply["model_note"] = result.model_note
    return reply
```

(Keep every existing key of the returned dict exactly as it is; only the `return {` becomes `reply = {` and the two `if` blocks plus `return reply` follow the closing brace.)

- [ ] **Step 6: `own_row` records the tier**

In `src/core/usage_log.py`, add the parameter `model_tier: str | None = None,` after `delegated_by: str | None,` and change the body to:

```python
    row = {
        "agent_id": agent_id,
        "agent_label": agent_label,
        "provider_id": result.provider_id,
        "gateway": gateway,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "started_at": started_at,
        "finished_at": finished_at,
        "delegated_by": delegated_by,
    }
    if model_tier:
        row["model_tier"] = model_tier
    return row
```

- [ ] **Step 7: Run the tests**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_agent_config.py tests/test_server.py tests/test_usage_log.py -v`
Expected: all pass (the pre-existing exact-shape tests included).

- [ ] **Step 8: Run the whole suite, then commit**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest -q`
Expected: all pass.

```bash
git add src/llm/base_provider.py src/agents/agent_config.py src/server.py src/core/usage_log.py tests/test_agent_config.py tests/test_server.py tests/test_usage_log.py
git commit -m "feat(ai_agent): ask() runs on the model tier a delegator requests, within the agent's cap" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Agents publish their tiers in the registry

**Files:**
- Modify: `src/agents/agent_registry.py`
- Modify: `src/server.py` (`main`, import)
- Modify: `src/agents/agent_routing.py`
- Test: `tests/test_agent_registry.py`, `tests/test_agent_routing.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `model_tiers.own_tiers`, `model_tiers.as_records`, `model_tiers.from_records` (Task 3); `RosterEntry.tiers` (Task 2).
- Produces: `agent_registry.register(..., focus="", tiers: list[dict[str, str]] | None = None)` (record gets `"tiers"` only when non-empty); `agent_routing.specialists()` fills `RosterEntry.tiers`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_registry.py`:

```python
def test_register_publishes_tiers_only_when_there_are_some(monkeypatch, tmp_path):
    config_path = _configure(monkeypatch, tmp_path, [])
    tiers = [{"tier": "light", "id": "haiku", "use_for": "quick"}]

    agent_registry.register("calc", "Calc", "http://127.0.0.1:9103/mcp", tiers=tiers)
    agent_registry.register("plain", "Plain", "http://127.0.0.1:9104/mcp", tiers=[])

    records = {a["id"]: a for a in json.loads(config_path.read_text(encoding="utf-8"))["agents"]}
    assert records["calc"]["tiers"] == tiers
    assert "tiers" not in records["plain"]
```

Append to `tests/test_agent_routing.py`:

```python
def test_specialists_carry_their_published_tiers(monkeypatch):
    agents = [
        {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True},
        {"id": "calc", "label": "Calculator", "url": "u", "focus": "math", "tiers": [
            {"tier": "light", "id": "haiku", "use_for": "quick"},
            {"tier": "bogus", "id": "x", "use_for": "y"},
        ]},
        {"id": "poet", "label": "Poet", "url": "u", "focus": "poems"},
    ]
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "_AGENTS", agents)
    _use(monkeypatch)

    calc, poet = agent_routing.specialists()

    assert calc.tiers == (agent_spec.TierInfo("light", "haiku", "quick"),)
    assert poet.tiers == ()
```

In `tests/test_server.py`, replace the last two lines of `test_main_registers_with_the_spec_flags` (the `kwargs ==` assertion) and add one patch line, so the test reads:

```python
def test_main_registers_with_the_spec_flags(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.mcp_upstream, "connect", lambda: None)
    monkeypatch.setattr(server.mcp_upstream, "warn_unmatched_tool_globs", lambda: None)
    monkeypatch.setattr(server.mcp_upstream, "close", lambda: None)
    monkeypatch.setattr(server.model_tiers, "own_tiers", lambda: [server.model_tiers.TierInfo("light", "haiku", "quick")])
    monkeypatch.setattr(server.agent_registry, "register", lambda *a, **k: calls.setdefault("register", (a, k)))
    monkeypatch.setattr(server.agent_registry, "deregister", lambda agent_id: calls.setdefault("deregister", agent_id))
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: None)

    server.main()

    args, kwargs = calls["register"]
    assert args[0] == server._AGENT_ID
    assert kwargs == {
        "entry": server.SPEC.entry, "orchestrator": server.SPEC.orchestrator, "focus": server.SPEC.focus,
        "tiers": [{"tier": "light", "id": "haiku", "use_for": "quick"}],
    }
    assert calls["deregister"] == server._AGENT_ID
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_agent_registry.py tests/test_agent_routing.py tests/test_server.py -v -k "tiers or registers"`
Expected: FAIL (`unexpected keyword argument 'tiers'`, `has no attribute 'model_tiers'`).

- [ ] **Step 3: Implement**

`src/agents/agent_registry.py`: change the `register` signature and record:

```python
def register(
    agent_id: str, label: str, url: str, *, entry: bool = False, orchestrator: bool = False, focus: str = "",
    tiers: list[dict[str, str]] | None = None,
) -> None:
```

add to the docstring: `tiers is this agent's allowed model tiers (model_tiers.as_records); an orchestrator offers them when delegating. It is stored only when non-empty.` and, after `record = {...}` is built:

```python
    if tiers:
        record["tiers"] = tiers
```

`src/server.py`: add `from src.llm import model_tiers` with the other `src.` imports (the test patches `server.model_tiers`, and `TierInfo` is reachable as `server.model_tiers.TierInfo` because `model_tiers` imports it). In `main()` change the register call to:

```python
    agent_registry.register(
        _AGENT_ID, _AGENT_LABEL, _AGENT_URL,
        entry=SPEC.entry, orchestrator=SPEC.orchestrator, focus=SPEC.focus,
        tiers=model_tiers.as_records(model_tiers.own_tiers()),
    )
```

`src/agents/agent_routing.py`: add `from src.llm import model_tiers` next to the other imports, and change `specialists()` to:

```python
    return [
        RosterEntry(a["id"], a.get("label") or a["id"], a.get("focus") or "", model_tiers.from_records(a.get("tiers")))
        for a in agent_registry.all_agents()
        if not a.get("orchestrator") and a["id"] != me
    ]
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_agent_registry.py tests/test_agent_routing.py tests/test_server.py -v`
Expected: all pass. Then `.venv_ai_agent/Scripts/python.exe -m pytest -q` — all pass. If a Laya `main()` test in `test_server.py` fails because it now reads the real local gateway config, add `monkeypatch.setattr(server.model_tiers, "own_tiers", lambda: [])` to that test.

- [ ] **Step 5: Commit**

```bash
git add src/agents/agent_registry.py src/agents/agent_routing.py src/server.py tests/test_agent_registry.py tests/test_agent_routing.py tests/test_server.py
git commit -m "feat(ai_agent): agents publish their allowed model tiers in the registry" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `delegate_to_agent` takes `model_tier`

**Files:**
- Modify: `src/agents/delegation.py`
- Modify: `src/llm/anthropic_provider.py`, `src/llm/openai_provider.py` (`_dispatch`)
- Test: `tests/test_delegation.py`, `tests/test_anthropic_provider.py`, `tests/test_openai_provider.py`

**Interfaces:**
- Consumes: `RosterEntry.tiers`, `TierInfo`, `TIERS` (Task 2); `ask`'s `model_tier` argument and `model_note` result field (Task 4).
- Produces: `delegation.tool_parameters` / `tool_description` expose tiers; `delegation.call(agent_id, question, depth, model_tier: str | None = None) -> str`; `delegation.dispatch(arguments: dict[str, Any], depth: int) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_delegation.py`:

```python
from src.agents.agent_spec import TierInfo

TIERED = [
    RosterEntry("calc", "Calculator", "Arithmetic.", (
        TierInfo("light", "haiku", "quick sums"), TierInfo("heavy", "opus", "proofs"),
    )),
    RosterEntry("fixed", "Fixed", "One model.", (TierInfo("standard", "sonnet", "all"),)),
]


def test_tool_parameters_have_no_model_tier_when_nobody_offers_a_choice():
    assert "model_tier" not in delegation.tool_parameters(ROSTER, allow_auto=False)["properties"]
    assert "model_tier" not in delegation.tool_parameters(TIERED[1:], allow_auto=False)["properties"]


def test_tool_parameters_offer_model_tier_when_a_specialist_has_a_choice():
    prop = delegation.tool_parameters(TIERED, allow_auto=False)["properties"]["model_tier"]
    assert prop["enum"] == ["light", "standard", "heavy"]


def test_tool_description_lists_tiers_only_for_specialists_with_a_choice():
    description = delegation.tool_description(TIERED, allow_auto=False)
    assert "calc (Calculator): Arithmetic. [model_tier: light = quick sums, heavy = proofs]" in description
    assert "fixed (Fixed): One model." in description
    assert "fixed (Fixed): One model. [" not in description
    assert "lightest model_tier" in description
    assert "lightest model_tier" not in delegation.tool_description(ROSTER, allow_auto=False)


def test_call_passes_model_tier_to_ask(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    captured = {}

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        captured["arguments"] = arguments
        return {"response": "4"}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        delegation.call("calc", "2+2?", depth=0, model_tier="light")

    assert captured["arguments"]["model_tier"] == "light"


def test_call_shows_the_orchestrator_why_a_tier_was_changed(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        return {"response": "4", "model_note": "heavy is not available for calc; ran on standard"}

    with patch("src.agents.delegation._call_tool", side_effect=_fake_call_tool):
        result = delegation.call("calc", "2+2?", depth=0, model_tier="heavy")

    assert result == "[heavy is not available for calc; ran on standard]\n\n4"


def test_dispatch_reads_the_tool_arguments():
    with patch("src.agents.delegation.call", return_value="answer") as fake_call:
        assert delegation.dispatch({"agent_id": "calc", "question": "q"}, 1) == "answer"
        delegation.dispatch({"agent_id": "calc", "question": "q", "model_tier": "heavy"}, 1)

    assert fake_call.call_args_list[0].args == ("calc", "q", 1)
    assert fake_call.call_args_list[0].kwargs == {}
    assert fake_call.call_args_list[1].args == ("calc", "q", 1)
    assert fake_call.call_args_list[1].kwargs == {"model_tier": "heavy"}
```

Add next to the existing dispatch test in `tests/test_anthropic_provider.py` (and the same, with `openai_provider` / `src.llm.openai_provider`, in `tests/test_openai_provider.py`):

```python
def test_dispatch_forwards_model_tier_to_delegation():
    with patch("src.llm.anthropic_provider.delegation.call", return_value="ok") as fake_delegate:
        anthropic_provider._dispatch(
            "delegate_to_agent", {"agent_id": "openai-agent", "question": "hi", "model_tier": "light"}, depth=1
        )

    fake_delegate.assert_called_once_with("openai-agent", "hi", 1, model_tier="light")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_delegation.py tests/test_anthropic_provider.py tests/test_openai_provider.py -v -k "tier or dispatch"`
Expected: FAIL (`KeyError: 'model_tier'`, `has no attribute 'dispatch'`, `unexpected keyword argument 'model_tier'`).

- [ ] **Step 3: Implement in `delegation.py`**

1. Change the import `from src.agents.agent_spec import RosterEntry` to `from src.agents.agent_spec import TIERS, RosterEntry`.

2. Replace `tool_parameters` and `tool_description` with:

```python
def _offers_choice(roster: list[RosterEntry]) -> bool:
    return any(len(r.tiers) > 1 for r in roster)


def tool_parameters(roster: list[RosterEntry], allow_auto: bool) -> dict[str, Any]:
    """The delegate tool's input schema: agent_id limited to this turn's
    roster (plus "auto" when Laya routing may choose), and model_tier when at
    least one specialist offers a choice of model strength."""
    ids = [r.id for r in roster] + ([AUTO_AGENT_ID] if allow_auto else [])
    properties: dict[str, Any] = {
        "agent_id": {"type": "string", "enum": ids, "description": "Which specialist to delegate to."},
        "question": {"type": "string", "description": "The focused sub-question to ask it."},
    }
    if _offers_choice(roster):
        properties["model_tier"] = {
            "type": "string",
            "enum": list(TIERS),
            "description": "Strength of the model the specialist runs on. Omit for its default.",
        }
    return {"type": "object", "properties": properties, "required": ["agent_id", "question"]}


def _roster_line(entry: RosterEntry) -> str:
    line = f"{entry.id} ({entry.label}): {entry.focus or 'no focus given'}"
    if len(entry.tiers) > 1:
        line += " [model_tier: " + ", ".join(f"{t.tier} = {t.use_for}" for t in entry.tiers) + "]"
    return line


def tool_description(roster: list[RosterEntry], allow_auto: bool) -> str:
    listing = "; ".join(_roster_line(r) for r in roster)
    auto = ' Use agent_id "auto" to let routing pick the best specialist for the question.' if allow_auto else ""
    choice = (
        " Pick the lightest model_tier whose description fits the task; omit it when unsure."
        if _offers_choice(roster) else ""
    )
    return (
        f"Hand a focused sub-question to a specialist agent and get its answer back. Specialists: {listing}.{auto}{choice} "
        "Sequential: each call adds latency, so delegate only what a specialist does better."
    )
```

3. Change the `call` signature and body. Signature:

```python
def call(agent_id: str, question: str, depth: int, model_tier: str | None = None) -> str:
```

Replace the inline `{...}` argument dict passed to `_call_tool` with a variable built before the `try`, and pass it:

```python
    arguments: dict[str, Any] = {
        "question": question,
        "history": [],
        "enabled_extensions": [],
        "request_id": None,
        "depth": depth + 1,
        "approval_mode": approval_mode,
        "delegated_by": me,
        # What the user switched off holds for the specialist too.
        "disabled_tools": sorted(tool_filter.blocked()),
    }
    if model_tier:
        arguments["model_tier"] = model_tier
```

and inside the `try`: `result = asyncio.run(_call_tool(agent["url"], "ask", arguments, on_progress=_progress_forwarder(sink, step_id)))`.

Replace the final return with:

```python
    note = result.get("model_note") or ""
    note_prefix = f"[{note}]\n\n" if note else ""
    return prefix + note_prefix + result.get("response", "")
```

4. Append at the end of the file:

```python


def dispatch(arguments: dict[str, Any], depth: int) -> str:
    """Run a delegate_to_agent tool call from its model-supplied arguments.
    Shared by both providers so neither re-reads the argument names."""
    tier = arguments.get("model_tier")
    if tier:
        return call(arguments["agent_id"], arguments["question"], depth, model_tier=tier)
    return call(arguments["agent_id"], arguments["question"], depth)
```

- [ ] **Step 4: Point both providers at `dispatch`**

In `src/llm/anthropic_provider.py` and `src/llm/openai_provider.py`, in `_dispatch`, replace `return delegation.call(arguments["agent_id"], arguments["question"], depth)` with:

```python
        return delegation.dispatch(arguments, depth)
```

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest tests/test_delegation.py tests/test_anthropic_provider.py tests/test_openai_provider.py -v`
Expected: all pass, including the existing `assert_called_once_with("openai-agent", "hi", 1)` and the exact `arguments ==` assertion in `test_call_returns_the_sub_agents_response_on_success`. Then `.venv_ai_agent/Scripts/python.exe -m pytest -q` — all pass.

- [ ] **Step 6: Commit**

```bash
git add src/agents/delegation.py src/llm/anthropic_provider.py src/llm/openai_provider.py tests/test_delegation.py tests/test_anthropic_provider.py tests/test_openai_provider.py
git commit -m "feat(ai_agent): delegate_to_agent takes a model_tier the specialist resolves" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Docs, local config, and spec alignment

**Files:**
- Modify: `configs/README.md`, `src/README.md`
- Modify: `docs/spec_model_tiers.md`
- Local, gitignored (not committed): `configs/config_gateways.json`, `agents/*.json`

**Interfaces:**
- Consumes: everything above. Produces no new code interfaces.

- [ ] **Step 1: Document `models` in `configs/README.md`**

In the `config_gateways.json` bullet, after the sentence ending `Loaded by \`src/llm/llm_config.py\`'s \`gateway()\`.` add:

```
  A block may also have `models`: up to three strength tiers (`light`,
  `standard`, `heavy`), each `{id, use_for}`, read by `tiers()`. `model`
  stays the default; an agent file's `llm.min_tier`/`llm.max_tier` cap which
  tiers it may run on, and an orchestrator picks one per delegated task from
  the `use_for` text (`src/llm/model_tiers.py`).
```

In `src/README.md`, next to the existing mention of `delegation.py`, add one line: `llm/model_tiers.py - which model strength tiers an agent offers and how a requested tier resolves (clamped to the agent's min_tier/max_tier).`

- [ ] **Step 2: Align the spec with what was built**

In `docs/spec_model_tiers.md`:
- Section 5: after the `_dispatch` bullet, replace it with: `anthropic_provider._dispatch and openai_provider._dispatch call a new shared delegation.dispatch(arguments, depth), which passes model_tier to call() only when set.`
- Section 6 and 7: after "`ask` also returns `model_tier` and `model_note`" / "`own_row` records `model_tier` (nullable)", add: `Both keys are present only when set, so existing result and row shapes are unchanged. The registry record likewise carries tiers only when non-empty.`
- Section 8: add a note under the caps table: `agents/*.json are gitignored; the caps are applied to each machine's local files by hand, and only agents/agents.json.template shows the keys.`

- [ ] **Step 3: Local gateway config (not committed)**

In your local `configs/config_gateways.json`, add the same `models` object as in the `.example` file to the `claude` block (and any other gateway you want tiers on). Confirm each model id exists for your account.

- [ ] **Step 4: Local agent files (not committed)**

Add under each `llm` object (use the table in the spec's section 8):
- `pdf-assistant.json`, `scheduler.json`, `server-ops.json`: `"max_tier": "standard"`
- `reviewer.json`, `planner.json`: `"min_tier": "standard"`

In `agents/ember.json`, append this sentence to the end of `instructions`:

```
When a specialist lists model tiers, pass model_tier on delegate_to_agent: pick the lightest tier whose description fits the task, use heavy only for multi-step reasoning or hard analysis, and omit model_tier when unsure.
```

- [ ] **Step 5: Verify the local files load**

Run: `.venv_ai_agent/Scripts/python.exe -c "from pathlib import Path; from src.agents import agent_spec; [print(s.id, s.llm.min_tier, s.llm.max_tier) for s in agent_spec.load_dir(Path('agents'))]"`
Expected: one line per agent; the capped ones show their tier, no `AgentSpecError`.

Run: `.venv_ai_agent/Scripts/python.exe -c "from src.llm import llm_config; print(llm_config.tiers('anthropic', 'claude'))"`
Expected: three `TierModel` entries (light, standard, heavy).

- [ ] **Step 6: Final full run and commit**

Run: `.venv_ai_agent/Scripts/python.exe -m pytest -q`
Expected: all pass.

```bash
git add configs/README.md src/README.md docs/spec_model_tiers.md
git commit -m "docs(ai_agent): document model tiers and align the spec with the build" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Restart the agents**

Agents read their spec and register at startup, so restart the supervisor once. After that the registry (`data/agent_registry.json`) shows a `tiers` list for every agent whose gateway defines tiers in its range. Testing the live behavior is manual (ember delegating a light task and a heavy task, then checking the `model_tier` field in `data/usage/*.jsonl`).

---

## Self-Review

**Spec coverage**
- Sec. 1 gateway config: Task 1. Sec. 2 agent file: Task 2. Sec. 3 resolution: Task 3. Sec. 4 registry: Task 5. Sec. 5 roster/delegate tool/dispatch/note: Tasks 5 (roster) and 6. Sec. 6 `ask`/`run_chat`: Task 4. Sec. 7 usage log: Task 4. Sec. 8 ember guidance and caps: Task 7.
- Error handling: unknown/disallowed tier clamps (Task 3, 4); malformed `models` raises (Task 1); bad `min_tier`/`max_tier` raises (Task 2); empty-range warning (Task 3).
- Spec testing list: `llm_config` (Task 1), `agent_spec` (Task 2), `resolve` (Task 3), `delegation` (Task 6), `ask`/`run_chat` with tier, without tier, and cap overriding (Tasks 3, 4). Existing tests are kept valid by the "only when set" rule.

**Deliberate deviations from the spec (recorded in Task 7 Step 2):** `dispatch()` helper instead of editing each provider; `model_tier`/`model_note`/`tiers` keys only when set; caps for `agents/*.json` are local because those files are gitignored.

**Type consistency:** `TierInfo(tier, id, use_for)`, `TierModel(id, use_for)`, `Resolution(model, tier, note)`, `effective_tiers`, `resolve`, `own_tiers`, `as_records`, `from_records`, `dispatch`, `call(..., model_tier=)` use identical names in every task.
