# ai_agent Multi-Agent (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run several ai_agent instances from `ai_agent/agents/*.json` under one supervisor, with per-agent persona, LLM settings and tool scope, an orchestrator that delegates (optionally routed by Laya), live agent-activity events, and per-agent token usage with timestamps.

**Architecture:** A new `src/supervisor.py` validates every agent file, then spawns one `python -m src.server` child per enabled file with `AI_AGENT_FILE` and `AI_AGENT_PORT` set. A new pure module `src/agent_spec.py` loads the file (or builds the same spec from today's env vars) and, before any provider module is imported, copies provider/gateway/model into the env vars the existing import-time code already reads. Everything else reads `agent_spec.current()`. All changes are additive, so today's ember_api, ember_web and chat_app keep working.

**Tech Stack:** Python 3.11+, asyncio/anyio, FastMCP (`mcp` 1.30), `anthropic` 1.x, `openai` 3.x, optional `laya` 0.3, pytest (plain `asyncio.run` in tests, no pytest-asyncio).

**Spec:** `docs/superpowers/specs/2026-10-04-ai-agent-multi-agent-design.md`

## Global Constraints

- All work is inside `ai_agent/` plus the repo-root `.gitignore`. Never touch `chat_app/`, `ember_api/`, `ember_web/` or the untracked `chat_cli/`.
- Run every command from `ai_agent/`. Tests: `.venv_ai_agent\Scripts\python -m pytest` (on Git Bash: `.venv_ai_agent/Scripts/python -m pytest`).
- Agent id = file name stem, must match `^[a-z0-9][a-z0-9-]{0,62}$`.
- Unknown keys in an agent file are an error.
- Exactly one enabled agent file has `entry: true`.
- `llm.reasoning_effort` values: `off`, `low`, `medium`, `high`.
- `tools.allow` / `tools.deny` are `fnmatch` globs on tool names without the `main__` prefix; empty `allow` means all tools; deny wins.
- Only orchestrators get `delegate_to_agent` (hub-and-spoke). `_MAX_DELEGATION_DEPTH` stays 2.
- The env-var path (`python -m src.server` with `AI_AGENT_PROVIDER` etc., no `AI_AGENT_FILE`) keeps working and keeps registering `claude-agent` / `openai-agent`.
- Timestamps: UTC ISO-8601 with milliseconds and a `Z` suffix, e.g. `2026-10-04T09:12:03.512Z`.
- Supervisor backoff: 1s, 2s, 4s… capped at 60s; a child is marked failed on its 5th crash within 300s; stop grace 10s.
- Laya failures never block a turn.
- Existing tests stay green (some are updated in the tasks that change their contract; each such update is spelled out).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work happens on the current branch (`home`).
- Code style: match the surrounding modules (module docstrings that explain why, `from __future__ import annotations`, `@catalog` only where the module already uses it).

### Deviations from the spec (decided while planning; Task 11 writes them into the spec)

1. A specialist's `usage` events are **not** forwarded to the orchestrator's stream. Today's ember treats `usage` events as the turn's live total, so forwarding them would make the usage chip jump between agents. Final per-agent usage still arrives in `agent_usage`.
2. Laya exposes scores (`shortlist_choice(..., return_scores=True)`, signed cosine), so `routing.min_score` (float, -1..1, default unset) is added. Scores are `None` when only one specialist exists; the threshold is then skipped.
3. The usage log serializes writes with a `threading.Lock` inside the worker-thread write (an `asyncio.Lock` breaks across the multiple event loops tests create).
4. The env-var path builds an orchestrator spec, so a legacy instance still gets `delegate_to_agent`. It can no longer delegate to itself, because the roster excludes the agent's own id.
5. `token_reset` from a specialist becomes `{"type": "agent_token", "text": "", "reset": true, ...}`.

---

## File Structure

New:
- `src/agent_spec.py` — `AgentSpec` dataclasses, file loading + validation, env-var fallback, `current()`, `apply_to_environ()`, `ensure_agents_dir()`, `ToolScope`, `RosterEntry`. Imports only stdlib.
- `src/agent_routing.py` — orchestrator roster (per turn, from the registry) and Laya shortlist / `"auto"` pick.
- `src/agent_events.py` — event stamping, the forwarding sink (ContextVar), specialist-event translation, `now_iso()`.
- `src/usage_log.py` — `agent_usage` row builder and JSONL append.
- `src/llm/llm_options.py` — per-agent temperature / reasoning / max_tokens / max_tool_rounds with drop-on-reject.
- `src/supervisor.py` — child process management.
- `agents.example/claude-agent.json`, `agents.example/openai-agent.json`.
- Tests: `tests/test_agent_spec.py`, `tests/test_agent_routing.py`, `tests/test_agent_events.py`, `tests/test_usage_log.py`, `tests/test_llm_options.py`, `tests/test_supervisor.py`, `tests/test_tool_scope.py`.

Modified:
- `src/agent_registry.py` — `register()` writes `entry` / `orchestrator` / `focus`.
- `src/server.py` — applies the agent file before imports, registers by agent id, stamps events, writes usage rows, takes `delegated_by`.
- `src/llm/agent_roles.py` — persona from the agent file; roster block in the system prompt.
- `src/mcp_upstream.py` — tool scope filter, call rejection, unmatched-glob warning.
- `src/tool_selection.py` — `rank_with_scores`, `default_ranker()`.
- `src/delegation.py` — roster-based schema, `"auto"`, start/end events, progress forwarding, `delegated_by`.
- `src/llm/base_provider.py` — `dispatch_with_progress` binds the agent-event sink.
- `src/llm/anthropic_provider.py`, `src/llm/openai_provider.py` — roster, LLM options, drop-on-reject retry.
- `tests/conftest.py`, `tests/test_agent_registry.py`, `tests/test_server.py`, `tests/test_delegation.py`, `tests/test_anthropic_provider.py`, `tests/test_openai_provider.py`, `tests/test_agent_roles.py`.
- `run.bat`, `README.md`, repo-root `.gitignore`.

---

### Task 1: Agent spec loading and validation

**Files:**
- Create: `src/agent_spec.py`
- Test: `tests/test_agent_spec.py`

**Interfaces:**
- Produces:
  - `class AgentSpecError(Exception)`
  - `@dataclass(frozen=True) class LlmSpec: provider: str; gateway: str | None = None; model: str | None = None; temperature: float | None = None; reasoning_effort: str = "off"; max_tokens: int | None = None; max_tool_rounds: int | None = None`
  - `@dataclass(frozen=True) class ToolScope: allow: tuple[str, ...] = (); deny: tuple[str, ...] = ()` with `allows(name: str) -> bool` and `unmatched(names: Iterable[str]) -> list[str]`
  - `@dataclass(frozen=True) class RoutingSpec: laya: bool = False; top_k: int = 3; allow_auto: bool = False; min_score: float | None = None`
  - `@dataclass(frozen=True) class RosterEntry: id: str; label: str; focus: str`
  - `@dataclass(frozen=True) class AgentSpec: id: str; label: str; port: int; llm: LlmSpec; enabled: bool = True; entry: bool = False; persona: str | None = ""; focus: str = ""; tools: ToolScope = ToolScope(); orchestrator: bool = False; routing: RoutingSpec = RoutingSpec(); source: Path | None = None` with `effective_gateway() -> str | None`
  - `AGENTS_DIR: Path`, `EXAMPLE_DIR: Path`
  - `load_file(path: Path) -> AgentSpec`
  - `load_dir(directory: Path) -> list[AgentSpec]` (validates the set)
  - `from_env() -> AgentSpec`
  - `current() -> AgentSpec` (cached in module global `_current`), `reset_cache() -> None`
  - `apply_to_environ(spec: AgentSpec) -> None`
  - `ensure_agents_dir(agents_dir: Path = AGENTS_DIR, example_dir: Path = EXAMPLE_DIR) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_spec.py`:

```python
"""agent_spec.py tests: defaults, every validation error, the set-level
checks (ports, exactly one entry), the env-var fallback spec, and the
env-var hand-off a child does before importing agent_config."""

from __future__ import annotations

import json

import pytest

from src import agent_spec
from src.agent_spec import AgentSpecError, ToolScope


def _write(directory, name, data):
    path = directory / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_file_applies_defaults(tmp_path):
    spec = agent_spec.load_file(_write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic"}}))

    assert spec.id == "calc"
    assert spec.label == "calc"
    assert spec.port == 9103
    assert spec.enabled is True
    assert spec.entry is False
    assert spec.persona == ""
    assert spec.focus == ""
    assert spec.orchestrator is False
    assert spec.tools == ToolScope()
    assert spec.llm.provider == "anthropic"
    assert spec.llm.reasoning_effort == "off"
    assert spec.routing.top_k == 3
    assert spec.source == tmp_path / "calc.json"


def test_load_file_reads_every_field(tmp_path):
    data = {
        "label": "Ember",
        "port": 9100,
        "enabled": True,
        "entry": True,
        "llm": {
            "provider": "openai", "gateway": "azure", "model": "gpt-x", "temperature": 0.2,
            "reasoning_effort": "high", "max_tokens": 4096, "max_tool_rounds": 8,
        },
        "persona": "You coordinate.",
        "focus": "Everything.",
        "tools": {"allow": ["calc_*"], "deny": ["calc_secret"]},
        "orchestrator": True,
        "routing": {"laya": True, "top_k": 2, "allow_auto": True, "min_score": 0.3},
    }
    spec = agent_spec.load_file(_write(tmp_path, "orchestrator", data))

    assert spec.label == "Ember"
    assert spec.llm.gateway == "azure"
    assert spec.llm.temperature == 0.2
    assert spec.llm.max_tool_rounds == 8
    assert spec.tools == ToolScope(allow=("calc_*",), deny=("calc_secret",))
    assert spec.routing.laya is True
    assert spec.routing.min_score == 0.3


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"llm": {"provider": "anthropic"}}, "port"),
        ({"port": 9100}, "llm"),
        ({"port": 9100, "llm": {}}, "llm.provider"),
        ({"port": 9100, "llm": {"provider": "gemini"}}, "llm.provider"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "colour": "red"}, "colour"),
        ({"port": 9100, "llm": {"provider": "anthropic", "temp": 1}}, "llm.temp"),
        ({"port": "9100", "llm": {"provider": "anthropic"}}, "port"),
        ({"port": 0, "llm": {"provider": "anthropic"}}, "port"),
        ({"port": 9100, "llm": {"provider": "anthropic", "temperature": 3}}, "llm.temperature"),
        ({"port": 9100, "llm": {"provider": "anthropic", "reasoning_effort": "max"}}, "llm.reasoning_effort"),
        ({"port": 9100, "llm": {"provider": "anthropic", "max_tokens": 0}}, "llm.max_tokens"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "tools": {"allow": "calc_*"}}, "tools.allow"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "routing": {"laya": True}}, "routing"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"top_k": 0}}, "routing.top_k"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"min_score": 2}}, "routing.min_score"),
        ({"port": 9100, "llm": {"provider": "anthropic"}, "entry": "yes"}, "entry"),
    ],
)
def test_load_file_rejects_bad_fields(tmp_path, data, message):
    with pytest.raises(AgentSpecError) as error:
        agent_spec.load_file(_write(tmp_path, "calc", data))
    assert "calc.json" in str(error.value)
    assert message in str(error.value)


def test_load_file_rejects_bad_json(tmp_path):
    path = tmp_path / "calc.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AgentSpecError, match="calc.json"):
        agent_spec.load_file(path)


def test_load_file_rejects_a_bad_id(tmp_path):
    with pytest.raises(AgentSpecError, match="id"):
        agent_spec.load_file(_write(tmp_path, "Calc_Agent", {"port": 9100, "llm": {"provider": "anthropic"}}))


def test_load_dir_requires_exactly_one_entry(tmp_path):
    _write(tmp_path, "a", {"port": 9100, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9101, "llm": {"provider": "anthropic"}})
    with pytest.raises(AgentSpecError, match="entry"):
        agent_spec.load_dir(tmp_path)

    _write(tmp_path, "a", {"port": 9100, "entry": True, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9101, "entry": True, "llm": {"provider": "anthropic"}})
    with pytest.raises(AgentSpecError, match="a.json, b.json"):
        agent_spec.load_dir(tmp_path)


def test_load_dir_ignores_disabled_files_for_set_checks(tmp_path):
    _write(tmp_path, "a", {"port": 9100, "entry": True, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9100, "entry": True, "enabled": False, "llm": {"provider": "anthropic"}})

    specs = agent_spec.load_dir(tmp_path)

    assert [s.id for s in specs] == ["a", "b"]


def test_load_dir_rejects_duplicate_ports(tmp_path):
    _write(tmp_path, "a", {"port": 9100, "entry": True, "llm": {"provider": "anthropic"}})
    _write(tmp_path, "b", {"port": 9100, "llm": {"provider": "anthropic"}})
    with pytest.raises(AgentSpecError, match="9100"):
        agent_spec.load_dir(tmp_path)


def test_load_dir_rejects_an_empty_directory(tmp_path):
    with pytest.raises(AgentSpecError, match="no agent files"):
        agent_spec.load_dir(tmp_path)


def test_tool_scope_allow_deny_and_unmatched():
    everything = ToolScope()
    assert everything.allows("anything") is True

    scope = ToolScope(allow=("calc_*", "convert_*"), deny=("calc_secret",))
    assert scope.allows("calc_add") is True
    assert scope.allows("calc_secret") is False
    assert scope.allows("weather_now") is False
    assert scope.unmatched(["calc_add", "calc_secret"]) == ["convert_*"]


def test_from_env_builds_a_legacy_orchestrator(monkeypatch):
    monkeypatch.setenv("AI_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("AI_AGENT_PORT", "9102")
    monkeypatch.setenv("AI_AGENT_MODEL", "gpt-x")
    monkeypatch.setenv("AI_AGENT_GATEWAY", "azure")

    spec = agent_spec.from_env()

    assert spec.id == "openai-agent"
    assert spec.port == 9102
    assert spec.label == ""
    assert spec.persona is None
    assert spec.orchestrator is True
    assert spec.llm.model == "gpt-x"
    assert spec.source is None
    assert spec.effective_gateway() == "azure"


def test_effective_gateway_for_a_file_spec_ignores_the_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_AGENT_GATEWAY", "openrouter")
    spec = agent_spec.load_file(_write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic"}}))
    assert spec.effective_gateway() is None


def test_current_reads_ai_agent_file_and_caches(tmp_path, monkeypatch):
    path = _write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "anthropic"}})
    monkeypatch.setenv("AI_AGENT_FILE", str(path))
    monkeypatch.setattr(agent_spec, "_current", None)

    first = agent_spec.current()
    path.write_text("{broken", encoding="utf-8")

    assert first.id == "calc"
    assert agent_spec.current() is first


def test_apply_to_environ_sets_provider_gateway_model_and_port(tmp_path, monkeypatch):
    for name in ("AI_AGENT_PROVIDER", "AI_AGENT_GATEWAY", "AI_AGENT_MODEL", "AI_AGENT_PORT"):
        monkeypatch.delenv(name, raising=False)
    spec = agent_spec.load_file(_write(tmp_path, "calc", {"port": 9103, "llm": {"provider": "openai"}}))

    agent_spec.apply_to_environ(spec)

    import os
    assert os.environ["AI_AGENT_PROVIDER"] == "openai"
    # No gateway in the file: pin the provider default so secret_llm.env's
    # AI_AGENT_GATEWAY (loaded later with setdefault) cannot override it.
    assert os.environ["AI_AGENT_GATEWAY"] == "gpt"
    assert os.environ["AI_AGENT_MODEL"] == ""
    assert os.environ["AI_AGENT_PORT"] == "9103"


def test_ensure_agents_dir_seeds_only_when_empty(tmp_path):
    example = tmp_path / "agents.example"
    example.mkdir()
    (example / "claude-agent.json").write_text("{}", encoding="utf-8")
    agents = tmp_path / "agents"

    agent_spec.ensure_agents_dir(agents, example)
    assert (agents / "claude-agent.json").exists()

    (agents / "claude-agent.json").unlink()
    (agents / "mine.json").write_text("{}", encoding="utf-8")
    agent_spec.ensure_agents_dir(agents, example)
    assert not (agents / "claude-agent.json").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_spec.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'src.agent_spec'`.

- [ ] **Step 3: Write the implementation**

Create `src/agent_spec.py`:

```python
"""One ai_agent instance's definition: an `agents/<id>.json` file, or the
same shape built from today's env vars when no file is given.

Pure on purpose (stdlib only, no provider imports): server.py loads the
file and calls apply_to_environ() BEFORE importing agent_config, because
the provider modules resolve their gateway/default model from env vars at
their own import time (see agent_config.py's long comment). Everything
read later - persona, tool scope, LLM knobs, orchestrator/routing - comes
from current().

The supervisor (supervisor.py) validates every file with load_dir() before
it starts any child, so a typo fails once, loudly, naming the file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
EXAMPLE_DIR = PROJECT_ROOT / "agents.example"

PROVIDERS = ("anthropic", "openai")
REASONING_EFFORTS = ("off", "low", "medium", "high")
# The gateway each provider uses when a file names none - pinned in the env
# so secret_llm.env's AI_AGENT_GATEWAY cannot silently re-point the agent.
_DEFAULT_GATEWAY = {"anthropic": "claude", "openai": "gpt"}
# Same mapping as agent_registry.agent_id_for (kept here so this module
# stays import-free): the legacy ids predate the "claude" -> "anthropic" rename.
_LEGACY_ID_PREFIX = {"anthropic": "claude", "openai": "openai"}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_TOP_KEYS = {"label", "port", "enabled", "entry", "llm", "persona", "focus", "tools", "orchestrator", "routing"}
_LLM_KEYS = {"provider", "gateway", "model", "temperature", "reasoning_effort", "max_tokens", "max_tool_rounds"}
_TOOLS_KEYS = {"allow", "deny"}
_ROUTING_KEYS = {"laya", "top_k", "allow_auto", "min_score"}


class AgentSpecError(Exception):
    """An agent file is missing, unreadable, or invalid - the message names
    the file and the field."""


@dataclass(frozen=True)
class LlmSpec:
    provider: str
    gateway: str | None = None
    model: str | None = None
    temperature: float | None = None
    reasoning_effort: str = "off"
    max_tokens: int | None = None
    max_tool_rounds: int | None = None


@dataclass(frozen=True)
class ToolScope:
    """Which mcp_server tools an agent may see and call, as fnmatch globs on
    the tool name without the "main__" prefix. Empty allow = every tool;
    deny always wins."""

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    def allows(self, name: str) -> bool:
        if self.allow and not any(fnmatchcase(name, glob) for glob in self.allow):
            return False
        return not any(fnmatchcase(name, glob) for glob in self.deny)

    def unmatched(self, names: Iterable[str]) -> list[str]:
        """Globs that match none of `names` - almost always a typo."""
        names = list(names)
        return [glob for glob in (*self.allow, *self.deny) if not any(fnmatchcase(n, glob) for n in names)]


@dataclass(frozen=True)
class RoutingSpec:
    laya: bool = False
    top_k: int = 3
    allow_auto: bool = False
    min_score: float | None = None


@dataclass(frozen=True)
class RosterEntry:
    """One specialist as the orchestrator sees it."""

    id: str
    label: str
    focus: str


@dataclass(frozen=True)
class AgentSpec:
    id: str
    label: str
    port: int
    llm: LlmSpec
    enabled: bool = True
    entry: bool = False
    # None = no persona in a file: use config_ai_agent_roles.json's role
    # (the env-var path). A file spec always has a string, "" included.
    persona: str | None = ""
    focus: str = ""
    tools: ToolScope = field(default_factory=ToolScope)
    orchestrator: bool = False
    routing: RoutingSpec = field(default_factory=RoutingSpec)
    source: Path | None = None

    def effective_gateway(self) -> str | None:
        """The gateway to report in usage rows: the file's own gateway (None
        = the provider used directly), or AI_AGENT_GATEWAY on the env path."""
        if self.source is not None:
            return self.llm.gateway
        return os.getenv("AI_AGENT_GATEWAY") or None


class _Checker:
    """Validation helpers that name the file and the field in every error."""

    def __init__(self, path: Path) -> None:
        self._name = path.name

    def fail(self, where: str, message: str) -> AgentSpecError:
        return AgentSpecError(f"{self._name}: {where} {message}")

    def keys(self, data: dict[str, Any], allowed: set[str], prefix: str = "") -> None:
        for key in data:
            if key not in allowed:
                raise self.fail(f"{prefix}{key}", "is not a known field")

    def boolean(self, data: dict[str, Any], key: str, default: bool, prefix: str = "") -> bool:
        value = data.get(key, default)
        if not isinstance(value, bool):
            raise self.fail(f"{prefix}{key}", "must be true or false")
        return value

    def text(self, data: dict[str, Any], key: str, default: str | None, prefix: str = "") -> str | None:
        value = data.get(key, default)
        if value is not None and not isinstance(value, str):
            raise self.fail(f"{prefix}{key}", "must be a string")
        return value

    def integer(self, data: dict[str, Any], key: str, default: int | None, low: int, high: int, prefix: str = "") -> int | None:
        value = data.get(key, default)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise self.fail(f"{prefix}{key}", f"must be a whole number from {low} to {high}")
        return value

    def number(self, data: dict[str, Any], key: str, low: float, high: float, prefix: str = "") -> float | None:
        value = data.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise self.fail(f"{prefix}{key}", f"must be a number from {low:g} to {high:g}")
        return float(value)

    def section(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        value = data.get(key, {})
        if not isinstance(value, dict):
            raise self.fail(key, "must be an object")
        return value

    def globs(self, data: dict[str, Any], key: str) -> tuple[str, ...]:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise self.fail(f"tools.{key}", "must be a list of non-empty strings")
        return tuple(value)


def load_file(path: Path) -> AgentSpec:
    """Read and validate one agent file. The id is the file name stem."""
    check = _Checker(path)
    agent_id = path.stem
    if not _ID_RE.match(agent_id):
        raise check.fail("id", f"{agent_id!r} must be lowercase letters, digits and dashes (from the file name)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise check.fail("file", f"cannot be read as JSON ({error})") from error
    if not isinstance(data, dict):
        raise check.fail("file", "must contain a JSON object")
    check.keys(data, _TOP_KEYS)

    if "port" not in data:
        raise check.fail("port", "is required")
    port = check.integer(data, "port", None, 1, 65535)
    if "llm" not in data:
        raise check.fail("llm", "is required")
    llm_data = check.section(data, "llm")
    check.keys(llm_data, _LLM_KEYS, "llm.")
    provider = llm_data.get("provider")
    if provider not in PROVIDERS:
        raise check.fail("llm.provider", f"must be one of: {', '.join(PROVIDERS)}")
    effort = llm_data.get("reasoning_effort", "off")
    if effort not in REASONING_EFFORTS:
        raise check.fail("llm.reasoning_effort", f"must be one of: {', '.join(REASONING_EFFORTS)}")
    llm = LlmSpec(
        provider=provider,
        gateway=check.text(llm_data, "gateway", None, "llm.") or None,
        model=check.text(llm_data, "model", None, "llm.") or None,
        temperature=check.number(llm_data, "temperature", 0.0, 2.0, "llm."),
        reasoning_effort=effort,
        max_tokens=check.integer(llm_data, "max_tokens", None, 1, 1_000_000, "llm."),
        max_tool_rounds=check.integer(llm_data, "max_tool_rounds", None, 1, 100, "llm."),
    )

    tools_data = check.section(data, "tools")
    check.keys(tools_data, _TOOLS_KEYS, "tools.")
    tools = ToolScope(allow=check.globs(tools_data, "allow"), deny=check.globs(tools_data, "deny"))

    orchestrator = check.boolean(data, "orchestrator", False)
    if "routing" in data and not orchestrator:
        raise check.fail("routing", "is only allowed when orchestrator is true")
    routing_data = check.section(data, "routing")
    check.keys(routing_data, _ROUTING_KEYS, "routing.")
    routing = RoutingSpec(
        laya=check.boolean(routing_data, "laya", False, "routing."),
        top_k=check.integer(routing_data, "top_k", 3, 1, 50, "routing."),
        allow_auto=check.boolean(routing_data, "allow_auto", False, "routing."),
        min_score=check.number(routing_data, "min_score", -1.0, 1.0, "routing."),
    )

    return AgentSpec(
        id=agent_id,
        label=check.text(data, "label", None) or agent_id,
        port=port,
        llm=llm,
        enabled=check.boolean(data, "enabled", True),
        entry=check.boolean(data, "entry", False),
        persona=check.text(data, "persona", "") or "",
        focus=check.text(data, "focus", "") or "",
        tools=tools,
        orchestrator=orchestrator,
        routing=routing,
        source=path,
    )


def load_dir(directory: Path) -> list[AgentSpec]:
    """Every agent file in `directory`, validated one by one and as a set:
    enabled agents need distinct ports and exactly one entry agent."""
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise AgentSpecError(f"{directory}: no agent files found")
    specs = [load_file(path) for path in paths]
    enabled = [s for s in specs if s.enabled]

    by_port: dict[int, list[str]] = {}
    for spec in enabled:
        by_port.setdefault(spec.port, []).append(f"{spec.id}.json")
    for port, names in by_port.items():
        if len(names) > 1:
            raise AgentSpecError(f"port {port} is used by more than one enabled agent: {', '.join(names)}")

    entries = [f"{s.id}.json" for s in enabled if s.entry]
    if len(entries) != 1:
        found = ", ".join(entries) if entries else "none"
        raise AgentSpecError(f"exactly one enabled agent must set entry: true (found: {found})")
    return specs


def from_env() -> AgentSpec:
    """The spec of an instance started the old way (python -m src.server
    with AI_AGENT_PROVIDER/AI_AGENT_PORT/...). It is an orchestrator so it
    still gets delegate_to_agent; persona None means "use the role"."""
    provider = os.getenv("AI_AGENT_PROVIDER") or ""
    return AgentSpec(
        id=f"{_LEGACY_ID_PREFIX.get(provider, provider)}-agent",
        label="",
        port=int(os.getenv("AI_AGENT_PORT", "9100")),
        llm=LlmSpec(
            provider=provider,
            gateway=os.getenv("AI_AGENT_GATEWAY") or None,
            model=os.getenv("AI_AGENT_MODEL") or None,
        ),
        persona=None,
        orchestrator=True,
    )


_current: AgentSpec | None = None


def current() -> AgentSpec:
    """This process's spec: AI_AGENT_FILE when set, else from_env(). Read
    once and cached - an agent's definition never changes while it runs."""
    global _current
    if _current is None:
        file = os.getenv("AI_AGENT_FILE")
        _current = load_file(Path(file)) if file else from_env()
    return _current


def reset_cache() -> None:
    global _current
    _current = None


def apply_to_environ(spec: AgentSpec) -> None:
    """Hand a file spec's provider/gateway/model/port to the env vars the
    existing import-time code reads. Set (not setdefault) so they win over
    secret_llm.env, which agent_config loads with setdefault."""
    os.environ["AI_AGENT_PROVIDER"] = spec.llm.provider
    os.environ["AI_AGENT_GATEWAY"] = spec.llm.gateway or _DEFAULT_GATEWAY[spec.llm.provider]
    # "" (not unset): agent_config reads `os.getenv("AI_AGENT_MODEL") or None`,
    # and an existing key stops secret_llm.env's setdefault from filling it.
    os.environ["AI_AGENT_MODEL"] = spec.llm.model or ""
    os.environ["AI_AGENT_PORT"] = str(spec.port)


def ensure_agents_dir(agents_dir: Path = AGENTS_DIR, example_dir: Path = EXAMPLE_DIR) -> None:
    """First run: copy agents.example/*.json into agents/ when agents/ is
    missing or has no agent files (same idea as seed_from_example)."""
    if agents_dir.exists() and any(agents_dir.glob("*.json")):
        return
    agents_dir.mkdir(parents=True, exist_ok=True)
    for example in example_dir.glob("*.json"):
        shutil.copyfile(example, agents_dir / example.name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_spec.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_spec.py tests/test_agent_spec.py
git commit -m "ai_agent: add agent_spec - load and validate agents/*.json, env-var fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Registry entries carry entry / orchestrator / focus

**Files:**
- Modify: `src/agent_registry.py` (`register`, type hints)
- Test: `tests/test_agent_registry.py`

**Interfaces:**
- Produces: `register(agent_id: str, label: str, url: str, *, entry: bool = False, orchestrator: bool = False, focus: str = "") -> None`. The registry entry dict becomes `{"id", "label", "url", "entry", "orchestrator", "focus"}`. `get_agent` / `all_agents` return `dict[str, Any]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_registry.py`, change the expected entry in `test_register_adds_this_instance_to_both_config_files`:

```python
    expected = [{
        "id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp",
        "entry": False, "orchestrator": False, "focus": "",
    }]
```

Read the rest of the file and update every other test that compares a whole registered entry the same way (add `"entry": False, "orchestrator": False, "focus": ""`). Then append:

```python
def test_register_writes_entry_orchestrator_and_focus(monkeypatch, tmp_path):
    config_path, _ = _configure(monkeypatch, tmp_path, [])

    agent_registry.register(
        "calc", "Calculator", "http://127.0.0.1:9103/mcp",
        entry=False, orchestrator=False, focus="Arithmetic and unit conversion.",
    )
    agent_registry.register("orchestrator", "Ember", "http://127.0.0.1:9100/mcp", entry=True, orchestrator=True)

    agents = {a["id"]: a for a in json.loads(config_path.read_text(encoding="utf-8"))["agents"]}
    assert agents["calc"]["focus"] == "Arithmetic and unit conversion."
    assert agents["orchestrator"]["entry"] is True
    assert agents["orchestrator"]["orchestrator"] is True


def test_old_entries_without_new_keys_still_load(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, [{"id": "claude-agent", "label": "Claude Agent", "url": "http://x/mcp"}])

    agent = agent_registry.get_agent("claude-agent")

    assert agent["url"] == "http://x/mcp"
    assert agent.get("orchestrator", False) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_registry.py -q`
Expected: FAIL. `register()` got an unexpected keyword argument `entry`, and the entry-shape asserts fail.

- [ ] **Step 3: Implement**

In `src/agent_registry.py`:
- add `from typing import Any`;
- change the `list[dict[str, str]]` / `dict[str, str]` hints in `_read`, `_write`, `_update`'s mutate, `_load`, `get_agent` and `all_agents` to `dict[str, Any]`;
- replace `register` with:

```python
def register(
    agent_id: str, label: str, url: str, *, entry: bool = False, orchestrator: bool = False, focus: str = "",
) -> None:
    """Upserts this instance's own entry into both config_agents.json
    copies (this project's and chat_app's), so neither needs a manual edit
    to learn about a newly-started instance. Call once at startup, before
    serving; see deregister() for the matching shutdown call.

    entry/orchestrator/focus are optional for readers (a missing key reads
    as False/False/""): ember_api picks the entry agent, and an
    orchestrator builds its roster and Laya options from focus."""
    record: dict[str, Any] = {
        "id": agent_id, "label": label, "url": url,
        "entry": entry, "orchestrator": orchestrator, "focus": focus,
    }

    def _upsert(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [a for a in agents if a["id"] != agent_id] + [record]

    for path in (_CONFIG_PATH, _CHAT_APP_CONFIG_PATH):
        _update(path, _upsert)
    reload()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_registry.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_registry.py tests/test_agent_registry.py
git commit -m "ai_agent: registry entries carry entry, orchestrator and focus

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Child process reads its agent file; persona from the file

**Files:**
- Modify: `src/server.py:12-97` (startup), `src/server.py:252-268` (`main`)
- Modify: `src/llm/agent_roles.py:50-100`
- Create: `agents.example/claude-agent.json`, `agents.example/openai-agent.json`
- Modify: repo-root `.gitignore`
- Test: `tests/test_agent_roles.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `agent_spec.current()`, `agent_spec.apply_to_environ()`, `AgentSpec.persona/label/id/entry/orchestrator/focus`, `agent_registry.register(..., entry=, orchestrator=, focus=)`.
- Produces:
  - `server.SPEC: AgentSpec`, `server._AGENT_ID: str`, `server._AGENT_LABEL: str`
  - `agent_roles.system_prompt_for(caveman: bool = False, roster: Sequence[RosterEntry] = ()) -> str`
  - `agent_roles.roster_block(roster: Sequence[RosterEntry]) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_roles.py`:

```python
from src import agent_spec
from src.agent_spec import AgentSpec, LlmSpec, RosterEntry


def test_resolve_uses_the_agent_file_persona(monkeypatch):
    spec = AgentSpec(id="calc", label="Calculator", port=9103, llm=LlmSpec(provider="anthropic"),
                     persona="You are a precise mathematician.")
    monkeypatch.setattr(agent_spec, "_current", spec)

    role_id, role = agent_roles._resolve()

    assert role_id == "calc"
    assert role == {"persona": "You are a precise mathematician."}


def test_system_prompt_for_adds_the_roster_before_tool_instructions(monkeypatch):
    roster = [RosterEntry("calc", "Calculator", "Arithmetic."), RosterEntry("explainer", "Explainer", "")]

    prompt = agent_roles.system_prompt_for(roster=roster)

    assert "- calc - Calculator: Arithmetic." in prompt
    assert "- explainer - Explainer: (no focus given)" in prompt
    tool_instructions = agent_roles._load()["tool_use_instructions"]
    assert prompt.index("calc - Calculator") < prompt.index(tool_instructions)


def test_system_prompt_for_without_roster_is_unchanged():
    assert agent_roles.system_prompt_for() == agent_roles.SYSTEM_PROMPT
```

At the top of `tests/test_agent_roles.py` check how `agent_roles` is imported. If it is imported as `from src.llm import agent_roles`, keep that name. Otherwise add that import.

Append to `tests/test_server.py`:

```python
def test_server_uses_the_env_spec_identity_without_an_agent_file():
    # conftest sets AI_AGENT_PROVIDER=anthropic and no AI_AGENT_FILE.
    assert server.SPEC.source is None
    assert server._AGENT_ID == "claude-agent"
    assert server._AGENT_LABEL.endswith(" Agent")


def test_main_registers_with_the_spec_flags(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.mcp_upstream, "connect", lambda: None)
    monkeypatch.setattr(server.mcp_upstream, "warn_unmatched_tool_globs", lambda: None)
    monkeypatch.setattr(server.mcp_upstream, "close", lambda: None)
    monkeypatch.setattr(server.agent_registry, "register", lambda *a, **k: calls.setdefault("register", (a, k)))
    monkeypatch.setattr(server.agent_registry, "deregister", lambda agent_id: calls.setdefault("deregister", agent_id))
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: None)

    server.main()

    args, kwargs = calls["register"]
    assert args[0] == server._AGENT_ID
    assert kwargs == {"entry": server.SPEC.entry, "orchestrator": server.SPEC.orchestrator, "focus": server.SPEC.focus}
    assert calls["deregister"] == server._AGENT_ID
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_roles.py tests/test_server.py -q`
Expected: FAIL. `system_prompt_for()` got an unexpected keyword `roster`, and `server` has no attribute `SPEC` (and `mcp_upstream` has no `warn_unmatched_tool_globs` until Step 4 adds its stub).

- [ ] **Step 3: Implement `agent_roles.py`**

In `src/llm/agent_roles.py`:
- add `from typing import Any, Sequence` (replace the existing `from typing import Any`);
- add `from src import agent_spec` and `from src.agent_spec import RosterEntry`;
- at the top of `_resolve()`, before `config = _load()`, insert:

```python
    # An agent file's persona replaces the role (AI_AGENT_ROLE is only for
    # instances started the old way, whose spec has persona None).
    spec = agent_spec.current()
    if spec.persona is not None:
        return spec.id, {"persona": spec.persona}
```

- replace `_compose_system_prompt` and `system_prompt_for` (keep the rest of the module unchanged):

```python
def roster_block(roster: Sequence[RosterEntry]) -> str:
    """The orchestrator's view of its specialists, one line each."""
    if not roster:
        return ""
    lines = "\n".join(f"- {r.id} - {r.label}: {r.focus or '(no focus given)'}" for r in roster)
    return (
        "You coordinate these specialist agents. When a part of the request fits one of them "
        "better than you, hand that part to it with delegate_to_agent, then combine the answers:\n"
        f"{lines}"
    )


def _compose_system_prompt(config: dict[str, Any], role: dict[str, Any], roster_text: str = "") -> str:
    try:
        tool_use_instructions = config["tool_use_instructions"]
    except KeyError as exc:
        raise AgentRoleError(f"{_CONFIG_PATH} is missing required key {exc}") from exc
    app_name = config.get("app_name") or ""
    app_description = config.get("app_description") or ""
    identity = ""
    if app_name:
        identity = f"Your name is {app_name}, an AI Assistant."
        if app_description:
            identity += f" {app_description}"
        identity += " When asked who you are or what your name is, answer with your name and this role."
    persona = role.get("persona") or ""
    parts = [p for p in (identity, persona, roster_text, tool_use_instructions) if p]
    return "\n\n".join(parts)
```

```python
def system_prompt_for(caveman: bool = False, roster: Sequence[RosterEntry] = ()) -> str:
    """SYSTEM_PROMPT, with this turn's orchestrator roster (if any) placed
    before the tool-use instructions, and caveman instructions appended."""
    prompt = _compose_system_prompt(_load(), _ROLE, roster_block(roster)) if roster else SYSTEM_PROMPT
    return f"{prompt}\n\n{CAVEMAN_INSTRUCTIONS}" if caveman else prompt
```

- [ ] **Step 4: Implement `server.py` startup**

In `src/server.py`, directly after the `if _args.mcp_url:` block (line 58-59) and before `import uvicorn`, insert:

```python
# A supervised child (see supervisor.py) gets its agent file in
# AI_AGENT_FILE. Its provider/gateway/model must reach the env vars before
# agent_config is imported (the providers resolve them at import time), so
# this runs first. agent_spec imports nothing from this project.
from src import agent_spec

if os.getenv("AI_AGENT_FILE"):
    try:
        agent_spec.apply_to_environ(agent_spec.current())
    except agent_spec.AgentSpecError as _exc:
        sys.stderr.write(f"\nai_agent cannot start - agent file error:\n  {_exc}\n\n")
        sys.exit(1)
```

Add `"AgentSpecError"` to `_CONFIG_ERROR_NAMES`.

Replace lines 84-85 (`_AGENT_ID = ...` and `_AGENT_URL = ...`) with:

```python
SPEC = agent_spec.current()
_AGENT_ID = SPEC.id
# An env-var instance has no label of its own: keep today's "<vendor> Agent".
_AGENT_LABEL = SPEC.label or f"{agent_config.status()['vendor_label']} Agent"
_AGENT_URL = f"http://{HOST if HOST not in ('0.0.0.0', '') else '127.0.0.1'}:{PORT}/mcp"
```

In the `FastMCP(...)` call, change `name=f"ai-agent-{agent_config.PROVIDER_ID}"` to `name=f"ai-agent-{_AGENT_ID}"`.

Replace `main()` with:

```python
def main() -> None:
    mcp_upstream.connect()
    mcp_upstream.warn_unmatched_tool_globs()
    agent_registry.register(
        _AGENT_ID, _AGENT_LABEL, _AGENT_URL,
        entry=SPEC.entry, orchestrator=SPEC.orchestrator, focus=SPEC.focus,
    )
    try:
        # Same app, host, port and log level mcp.run(transport="streamable-http")
        # would use, built explicitly so middleware can be added here. No CORS:
        # only servers call this agent (chat_app directly, ember_web's browser
        # via ember_api's proxy), never a browser - which is also why /mcp
        # can require the shared internal token (once one is configured).
        app = mcp.streamable_http_app()
        app.add_middleware(internal_auth.InternalTokenMiddleware, token=internal_auth.TOKEN)
        if not internal_auth.TOKEN:
            print("ai_agent: /mcp has no auth - set INTERNAL_API_TOKEN in secrets/secret_internal_api.env", flush=True)
        uvicorn.run(app, host=HOST, port=PORT, log_level=mcp.settings.log_level.lower())
    finally:
        agent_registry.deregister(_AGENT_ID)
        mcp_upstream.close()
```

Add a temporary stub to `src/mcp_upstream.py` so `main()` runs before Task 4 replaces it:

```python
def warn_unmatched_tool_globs() -> None:
    """Replaced in the tool-scope task."""
```

- [ ] **Step 5: Add the example agent files and gitignore lines**

Create `agents.example/claude-agent.json`:

```json
{
  "label": "Ember",
  "port": 9100,
  "entry": true,
  "orchestrator": true,
  "llm": { "provider": "anthropic" },
  "persona": "",
  "focus": "General questions; coordinates the specialist agents.",
  "routing": { "laya": false, "top_k": 3, "allow_auto": false }
}
```

Create `agents.example/openai-agent.json`:

```json
{
  "label": "OpenAI Agent",
  "port": 9102,
  "llm": { "provider": "openai" },
  "persona": "",
  "focus": "A second opinion from a different model family."
}
```

In the repo-root `.gitignore`, after the `/ai_agent/configs/*` and `!/ai_agent/configs/*.example` lines, add:

```gitignore
# ai_agent's real agent definitions (seeded from agents.example/ on first
# supervisor run) and its per-agent token usage log.
/ai_agent/agents/
/ai_agent/data/
```

- [ ] **Step 6: Run the full test suite**

Run: `.venv_ai_agent\Scripts\python -m pytest -q`
Expected: all pass. Also check that `load_dir` accepts the examples:

Run: `.venv_ai_agent\Scripts\python -c "from src import agent_spec; print([s.id for s in agent_spec.load_dir(agent_spec.EXAMPLE_DIR)])"`
Expected: `['claude-agent', 'openai-agent']`

- [ ] **Step 7: Commit**

```bash
git add src/server.py src/llm/agent_roles.py src/mcp_upstream.py agents.example tests/test_agent_roles.py tests/test_server.py ../.gitignore
git commit -m "ai_agent: child reads AI_AGENT_FILE, registers by agent id, persona and roster in the prompt

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Per-agent tool scope

**Files:**
- Modify: `src/mcp_upstream.py` (`list_tools`, `call_tool`, `warn_unmatched_tool_globs`, new `unprefixed`)
- Test: `tests/test_tool_scope.py`

**Interfaces:**
- Consumes: `agent_spec.current().tools: ToolScope`
- Produces: `mcp_upstream.unprefixed(name: str) -> str`; `list_tools()` omits out-of-scope tools; `call_tool()` raises `PermissionError` for an out-of-scope tool; `warn_unmatched_tool_globs() -> None` logs one warning per unmatched glob.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_scope.py`:

```python
"""Per-agent tool scope (agents/<id>.json "tools"): out-of-scope tools are
never offered, refused if called anyway, and a glob matching nothing is
warned about once at startup."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src import agent_spec, mcp_upstream
from src.agent_spec import AgentSpec, LlmSpec, ToolScope


def _tool(name):
    return SimpleNamespace(name=name, description="", inputSchema={})


@pytest.fixture
def scoped(monkeypatch):
    spec = AgentSpec(id="calc", label="Calculator", port=9103, llm=LlmSpec(provider="anthropic"),
                     tools=ToolScope(allow=("calc_*",), deny=("calc_secret",)))
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_list_tools_keeps_only_tools_in_scope(scoped):
    tools = [_tool("main__calc_add"), _tool("main__calc_secret"), _tool("main__weather_now")]
    with patch.object(mcp_upstream.client, "list_tools", return_value=tools):
        names = [t.name for t in mcp_upstream.list_tools()]
    assert names == ["main__calc_add"]


def test_call_tool_refuses_a_tool_out_of_scope(scoped):
    with patch.object(mcp_upstream.client, "call_tool") as call_tool:
        with pytest.raises(PermissionError, match="main__weather_now"):
            mcp_upstream.call_tool("main__weather_now", {})
    call_tool.assert_not_called()


def test_warn_unmatched_tool_globs(monkeypatch, caplog):
    spec = AgentSpec(id="calc", label="Calculator", port=9103, llm=LlmSpec(provider="anthropic"),
                     tools=ToolScope(allow=("calc_*", "convrt_*")))
    monkeypatch.setattr(agent_spec, "_current", spec)
    with patch.object(mcp_upstream.client, "list_tools", return_value=[_tool("main__calc_add")]), \
         caplog.at_level(logging.WARNING, logger="src.mcp_upstream"):
        mcp_upstream.warn_unmatched_tool_globs()
    assert "convrt_*" in caplog.text
    assert "calc_*" not in caplog.text


def test_unprefixed():
    assert mcp_upstream.unprefixed("main__calc_add") == "calc_add"
    assert mcp_upstream.unprefixed("other") == "other"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_tool_scope.py -q`
Expected: FAIL. `mcp_upstream` has no `unprefixed`, and the weather tool is still listed.

- [ ] **Step 3: Implement**

In `src/mcp_upstream.py`:
- add `import logging`, and `from src import agent_spec, internal_auth, tool_progress` (extending the existing import);
- add `_log = logging.getLogger(__name__)` after `_PREFIX`;
- replace the stub `warn_unmatched_tool_globs` and add `unprefixed`:

```python
def unprefixed(name: str) -> str:
    """A tool name without this module's "main__" registry prefix - the
    form agents/<id>.json "tools" globs are written against."""
    return name[len(_PREFIX):] if name.startswith(_PREFIX) else name


def warn_unmatched_tool_globs() -> None:
    """One warning per tools.allow/deny glob that matches no mcp_server
    tool - almost always a typo. Called once at startup, after connect()."""
    names = [unprefixed(t.name) for t in client.list_tools() if t.name.startswith(_PREFIX)]
    for glob in agent_spec.current().tools.unmatched(names):
        _log.warning("agent %s: tools glob %r matches no mcp_server tool", agent_spec.current().id, glob)
```

- in `list_tools`, after `unprefixed = tool.name[len(_PREFIX):]`, rename the local to `short = unprefixed(tool.name)` (it shadows the new function otherwise), use `short` in the `_tool_is_enabled(short, enabled)` call, and add before `result.append(tool)`:

```python
        if not scope.allows(short):
            continue
```

  with `scope = agent_spec.current().tools` assigned once before the loop.
- at the top of `call_tool`, insert:

```python
    if name.startswith(_PREFIX) and not agent_spec.current().tools.allows(unprefixed(name)):
        # The model only sees in-scope tools, but may still name another one.
        raise PermissionError(f"tool {name!r} is not available to this agent")
```

- [ ] **Step 4: Run the tests**

Run: `.venv_ai_agent\Scripts\python -m pytest -q`
Expected: all pass. The default env spec has an empty scope, so existing tests are unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_upstream.py tests/test_tool_scope.py
git commit -m "ai_agent: per-agent tool scope from the agent file

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Per-agent LLM options with drop-on-reject

**Files:**
- Create: `src/llm/llm_options.py`
- Modify: `src/llm/anthropic_provider.py` (`run_chat` loop, imports)
- Modify: `src/llm/openai_provider.py` (`run_chat` loop, imports)
- Test: `tests/test_llm_options.py`, `tests/test_anthropic_provider.py`, `tests/test_openai_provider.py`

**Interfaces:**
- Consumes: `agent_spec.current().llm: LlmSpec`
- Produces:
  - `class LlmOptions` with `max_tokens(default: int) -> int`, `max_tool_rounds(default: int) -> int`, `extra_kwargs() -> dict[str, Any]`, `drop_rejected(message: str) -> bool`
  - `for_provider(provider_id: str) -> LlmOptions` (cached per process), `reset_cache() -> None`
  - Anthropic sends `temperature=` and `output_config={"effort": ...}`. OpenAI sends `temperature=` and `reasoning={"effort": ...}`. `reasoning_effort: "off"` sends nothing (the model's default).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_options.py`:

```python
"""llm_options.py tests: per-agent knobs become provider kwargs, and a
parameter the model rejects is dropped (once, with a warning)."""

from __future__ import annotations

import logging

from src.agent_spec import LlmSpec
from src.llm.llm_options import LlmOptions


def test_defaults_send_nothing_extra():
    options = LlmOptions("anthropic", "calc", LlmSpec(provider="anthropic"))
    assert options.extra_kwargs() == {}
    assert options.max_tokens(1000) == 1000
    assert options.max_tool_rounds(6) == 6


def test_anthropic_kwargs():
    llm = LlmSpec(provider="anthropic", temperature=0.0, reasoning_effort="high", max_tokens=4096, max_tool_rounds=3)
    options = LlmOptions("anthropic", "calc", llm)
    assert options.extra_kwargs() == {"temperature": 0.0, "output_config": {"effort": "high"}}
    assert options.max_tokens(1000) == 4096
    assert options.max_tool_rounds(6) == 3


def test_openai_kwargs():
    options = LlmOptions("openai", "calc", LlmSpec(provider="openai", temperature=0.7, reasoning_effort="low"))
    assert options.extra_kwargs() == {"temperature": 0.7, "reasoning": {"effort": "low"}}


def test_drop_rejected_drops_the_named_parameter_once(caplog):
    options = LlmOptions("anthropic", "calc", LlmSpec(provider="anthropic", temperature=0.5, reasoning_effort="high"))

    with caplog.at_level(logging.WARNING):
        assert options.drop_rejected("temperature: not supported for this model") is True

    assert options.extra_kwargs() == {"output_config": {"effort": "high"}}
    assert "temperature" in caplog.text
    assert options.drop_rejected("output_config.effort: invalid") is True
    assert options.extra_kwargs() == {}
    assert options.drop_rejected("messages: roles must alternate") is False
```

In `tests/test_anthropic_provider.py`, add this autouse reset next to `_reset_state` (inside it is fine):

```python
    from src.llm import llm_options
    llm_options.reset_cache()
```

and append:

```python
def test_run_chat_sends_agent_llm_options_and_retries_without_a_rejected_one(monkeypatch):
    import anthropic
    from src import agent_spec
    from src.agent_spec import AgentSpec, LlmSpec
    from src.llm import llm_options

    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")
    spec = AgentSpec(id="calc", label="Calculator", port=9103,
                     llm=LlmSpec(provider="anthropic", temperature=0.0, max_tokens=321, max_tool_rounds=2))
    monkeypatch.setattr(agent_spec, "_current", spec)
    llm_options.reset_cache()

    rejected = anthropic.BadRequestError(
        "temperature is not supported", response=MagicMock(status_code=400), body=None,
    )

    class _RejectingCM:
        async def __aenter__(self):
            raise rejected

        async def __aexit__(self, *exc):
            return False

    stream = Mock(side_effect=[_RejectingCM(), _stream_cm(["ok"])])
    fake_client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
    with patch("src.llm.anthropic_provider._get_client", return_value=fake_client), \
         patch("src.llm.anthropic_provider.list_tools", return_value=[]):
        result = asyncio.run(anthropic_provider.run_chat("hello", []))

    assert result.response == "ok"
    first, second = stream.call_args_list
    assert first.kwargs["temperature"] == 0.0
    assert first.kwargs["max_tokens"] == 321
    assert "temperature" not in second.kwargs
```

Add the same reset and an equivalent test to `tests/test_openai_provider.py`. Use `openai.BadRequestError("temperature is not supported", response=MagicMock(status_code=400), body=None)`, patch `src.llm.openai_provider._get_client`, `client.responses.stream`, and that file's existing stream helper. Read the file's helpers first and use them, not copies. Assert that `max_output_tokens == 321` on the first call.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_llm_options.py tests/test_anthropic_provider.py tests/test_openai_provider.py -q`
Expected: FAIL with `ModuleNotFoundError: src.llm.llm_options`.

- [ ] **Step 3: Implement `llm_options.py`**

Create `src/llm/llm_options.py`:

```python
"""One agent's sampling/reasoning settings (agents/<id>.json "llm"),
turned into provider request kwargs.

Models differ in what they accept (e.g. current Claude models reject a
non-default temperature; a non-reasoning OpenAI model rejects
`reasoning`). Rather than keep a per-model table, a parameter the API
refuses with a 400 is dropped for the rest of this process's life, with
one warning - the turn then retries without it.
"""

from __future__ import annotations

import logging
from typing import Any

from src import agent_spec
from src.agent_spec import LlmSpec

_log = logging.getLogger(__name__)

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
        self._dropped: set[str] = set()

    def max_tokens(self, default: int) -> int:
        return self._llm.max_tokens or default

    def max_tool_rounds(self, default: int) -> int:
        return self._llm.max_tool_rounds or default

    def _sent(self) -> list[str]:
        sent = []
        if self._llm.temperature is not None and "temperature" not in self._dropped:
            sent.append("temperature")
        if self._llm.reasoning_effort != "off" and "reasoning" not in self._dropped:
            sent.append("reasoning")
        return sent

    def extra_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for option in self._sent():
            if option == "temperature":
                kwargs["temperature"] = self._llm.temperature
            elif self._provider_id == "anthropic":
                kwargs["output_config"] = {"effort": self._llm.reasoning_effort}
            else:
                kwargs["reasoning"] = {"effort": self._llm.reasoning_effort}
        return kwargs

    def drop_rejected(self, message: str) -> bool:
        """True when `message` (a 400's text) names an option we sent; that
        option is then never sent again. False = not ours, re-raise."""
        text = message.lower()
        for option in self._sent():
            if any(marker in text for marker in _MARKERS[option]):
                self._dropped.add(option)
                _log.warning("agent %s: the model rejected %s; no longer sending it", self._agent_id, option)
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
```

- [ ] **Step 4: Wire into `anthropic_provider.run_chat`**

In `src/llm/anthropic_provider.py`:
- add `BadRequestError` to the `from anthropic import (...)` list;
- add `llm_options` to `from src.llm import cancellation, cooldown, llm_config, token_limits`;
- after `meter = LiveUsage(on_event)` add `options = llm_options.for_provider(PROVIDER_ID)`;
- change the loop header to `for _ in range(options.max_tool_rounds(token_limits.max_tool_rounds(PROVIDER_ID))):`;
- replace the block from `text_parts: list[str] = []` through `response = await stream.get_final_message()` with:

```python
            while True:
                text_parts: list[str] = []
                try:
                    async with client.messages.stream(
                        model=model_name,
                        max_tokens=options.max_tokens(token_limits.max_output_tokens(PROVIDER_ID)),
                        system=system_prompt,
                        messages=messages,
                        tools=schemas,
                        **options.extra_kwargs(),
                    ) as stream:
                        async for chunk in stream.text_stream:
                            text_parts.append(chunk)
                            if on_event:
                                await on_event(step_event("token", text=chunk))
                            await meter.chars(len(chunk))
                        response = await stream.get_final_message()
                    break
                except BadRequestError as error:
                    # A rejected per-agent option fails before any text
                    # streams; drop it and retry this round once without it.
                    if text_parts or not options.drop_rejected(str(error)):
                        raise
```

- [ ] **Step 5: Wire into `openai_provider.run_chat`**

Same changes in `src/llm/openai_provider.py`:
- import `BadRequestError` from `openai`, and `llm_options`;
- `options = llm_options.for_provider(PROVIDER_ID)`;
- loop header: `for _ in range(options.max_tool_rounds(token_limits.max_tool_rounds(PROVIDER_ID, _limit_gateway()))):`;
- wrap the `client.responses.stream(...)` block the same way, with `max_output_tokens=options.max_tokens(token_limits.max_output_tokens(PROVIDER_ID, _limit_gateway()))` and `**options.extra_kwargs()`;
- `text_parts` goes inside the `while True:`, exactly as in Step 4.

- [ ] **Step 6: Run the tests**

Run: `.venv_ai_agent\Scripts\python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/llm/llm_options.py src/llm/anthropic_provider.py src/llm/openai_provider.py tests/test_llm_options.py tests/test_anthropic_provider.py tests/test_openai_provider.py
git commit -m "ai_agent: per-agent temperature, reasoning effort, max tokens and tool rounds

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Orchestrator roster, Laya routing and roster-based delegate tool

**Files:**
- Create: `src/agent_routing.py`
- Modify: `src/tool_selection.py` (add `rank_with_scores`, `default_ranker`)
- Modify: `src/delegation.py` (schema/description functions, `"auto"`, registry reload)
- Modify: `src/llm/anthropic_provider.py`, `src/llm/openai_provider.py` (`_tool_schemas`, `run_chat`)
- Test: `tests/test_agent_routing.py`, `tests/test_delegation.py`, `tests/test_anthropic_provider.py`, `tests/test_openai_provider.py`

**Interfaces:**
- Consumes: `agent_spec.current()` (`orchestrator`, `routing`, `id`), `agent_registry.reload/all_agents/get_agent`, `RosterEntry`, `agent_roles.system_prompt_for(caveman, roster)`.
- Produces:
  - `agent_routing.specialists() -> list[RosterEntry]` (sync, re-reads the registry)
  - `async agent_routing.roster_for(question: str, ranker: Any = None) -> list[RosterEntry]`
  - `agent_routing.resolve_auto(question: str, ranker: Any = None) -> RosterEntry` (sync; raises `ValueError` with a message the model can act on)
  - `tool_selection.LayaToolRanker.rank_with_scores(question, options, k) -> tuple[list[str], list[float] | None]`, `tool_selection.default_ranker() -> LayaToolRanker`
  - `delegation.AUTO_AGENT_ID = "auto"`, `delegation.tool_parameters(roster, allow_auto) -> dict`, `delegation.tool_description(roster, allow_auto) -> str`. `delegation.is_available` and `delegation.TOOL_PARAMETERS` are removed.
  - Providers: `_tool_schemas(enabled_extensions=None, roster=())`. `run_chat` computes `roster = await agent_routing.roster_for(question)` once per turn.

- [ ] **Step 1: Write the failing routing tests**

Create `tests/test_agent_routing.py`:

```python
"""agent_routing.py tests: roster built per turn from the registry (self
and other orchestrators excluded), the Laya shortlist above top_k, the
"auto" pick with its min_score threshold, and every fallback."""

from __future__ import annotations

import asyncio

import pytest

from src import agent_registry, agent_routing, agent_spec
from src.agent_spec import AgentSpec, LlmSpec, RoutingSpec

AGENTS = [
    {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True, "focus": "coordination"},
    {"id": "calc", "label": "Calculator", "url": "u", "focus": "arithmetic and units"},
    {"id": "explainer", "label": "Explainer", "url": "u", "focus": "plain explanations"},
    {"id": "poet", "label": "Poet", "url": "u", "focus": "poems"},
    {"id": "blank", "label": "Blank", "url": "u"},
]


class FakeRanker:
    def __init__(self, chosen=None, scores=None, error=None):
        self.chosen, self.scores, self.error, self.calls = chosen or [], scores, error, []

    def rank(self, question, options, k):
        self.calls.append((question, dict(options), k))
        if self.error:
            raise self.error
        return self.chosen[:k]

    def rank_with_scores(self, question, options, k):
        self.calls.append((question, dict(options), k))
        if self.error:
            raise self.error
        return self.chosen[:k], self.scores


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "_AGENTS", AGENTS)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {a["id"]: a for a in AGENTS})


def _use(monkeypatch, orchestrator=True, **routing):
    spec = AgentSpec(id="orchestrator", label="Ember", port=9100, llm=LlmSpec(provider="anthropic"),
                     orchestrator=orchestrator, routing=RoutingSpec(**routing))
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_specialists_exclude_self_and_orchestrators(registry, monkeypatch):
    _use(monkeypatch)
    assert [r.id for r in agent_routing.specialists()] == ["calc", "explainer", "poet", "blank"]


def test_non_orchestrator_has_no_roster(registry, monkeypatch):
    _use(monkeypatch, orchestrator=False)
    assert asyncio.run(agent_routing.roster_for("hi")) == []


def test_roster_without_laya_is_every_specialist(registry, monkeypatch):
    _use(monkeypatch, laya=False, top_k=1)
    assert len(asyncio.run(agent_routing.roster_for("hi"))) == 4


def test_roster_shortlist_keeps_chosen_plus_unfocused(registry, monkeypatch):
    _use(monkeypatch, laya=True, top_k=1)
    ranker = FakeRanker(chosen=["calc"])

    roster = asyncio.run(agent_routing.roster_for("what is 2+2", ranker))

    assert [r.id for r in roster] == ["calc", "blank"]
    question, options, k = ranker.calls[0]
    assert options == {"calc": "arithmetic and units", "explainer": "plain explanations", "poet": "poems"}
    assert k == 1


def test_roster_shortlist_skipped_at_or_below_top_k(registry, monkeypatch):
    _use(monkeypatch, laya=True, top_k=3)
    ranker = FakeRanker(chosen=["calc"])
    assert len(asyncio.run(agent_routing.roster_for("q", ranker))) == 4
    assert ranker.calls == []


def test_roster_falls_back_to_everyone_when_laya_fails(registry, monkeypatch):
    _use(monkeypatch, laya=True, top_k=1)
    roster = asyncio.run(agent_routing.roster_for("q", FakeRanker(error=ImportError("no laya"))))
    assert len(roster) == 4


def test_resolve_auto_picks_the_top_specialist(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True)
    entry = agent_routing.resolve_auto("explain gravity", FakeRanker(chosen=["explainer"], scores=[0.8]))
    assert entry.id == "explainer"


def test_resolve_auto_below_min_score_refuses(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True, min_score=0.5)
    with pytest.raises(ValueError, match="no specialist matches well enough"):
        agent_routing.resolve_auto("q", FakeRanker(chosen=["poet"], scores=[0.1]))


def test_resolve_auto_ignores_min_score_when_scores_are_missing(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True, min_score=0.5)
    assert agent_routing.resolve_auto("q", FakeRanker(chosen=["poet"], scores=None)).id == "poet"


def test_resolve_auto_reports_laya_failure(registry, monkeypatch):
    _use(monkeypatch, laya=True, allow_auto=True)
    with pytest.raises(ValueError, match="pick an agent_id explicitly"):
        agent_routing.resolve_auto("q", FakeRanker(error=RuntimeError("model load failed")))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_routing.py -q`
Expected: `ModuleNotFoundError: No module named 'src.agent_routing'`.

- [ ] **Step 3: Add `rank_with_scores` and `default_ranker` to `tool_selection.py`**

Add to `LayaToolRanker`, after `rank`:

```python
    def rank_with_scores(self, question: str, options: dict[str, str], k: int) -> tuple[list[str], list[float] | None]:
        """Like rank, plus Laya's signed cosine per kept label (rank order).
        Scores are None when k covers every option (nothing was dropped)."""
        import laya

        _, embed = self._load()
        labels, scores = laya.shortlist_choice(question, options, embed, k, return_scores=True)
        return list(labels), (list(scores) if scores is not None else None)
```

After `_default_ranker = LayaToolRanker()` add:

```python
def default_ranker() -> LayaToolRanker:
    """The process-wide Laya ranker - tool shortlisting and agent routing
    share one loaded model."""
    return _default_ranker
```

- [ ] **Step 4: Create `src/agent_routing.py`**

```python
"""Which specialists an orchestrator offers the model this turn, and which
one `delegate_to_agent(agent_id="auto")` goes to.

The roster is re-read from the registry every turn (specialists start and
stop independently). With routing.laya on, Laya ranks specialists by how
well their `focus` matches the question - the same ranker tool
shortlisting uses (tool_selection.py). Laya is optional: any failure falls
back to the full roster, and "auto" then asks the model to pick an id.
"""

from __future__ import annotations

import logging
from typing import Any

import anyio.to_thread

from src import agent_registry, agent_spec, tool_selection
from src.agent_spec import RosterEntry

_log = logging.getLogger(__name__)


def specialists() -> list[RosterEntry]:
    """Every registered non-orchestrator agent except this one. Blocking
    (re-reads the registry file) - call from a worker thread."""
    agent_registry.reload()
    me = agent_spec.current().id
    return [
        RosterEntry(a["id"], a.get("label") or a["id"], a.get("focus") or "")
        for a in agent_registry.all_agents()
        if not a.get("orchestrator") and a["id"] != me
    ]


async def roster_for(question: str, ranker: Any = None) -> list[RosterEntry]:
    """This turn's roster: [] unless this agent is an orchestrator; with
    Laya on and more than top_k focused specialists, the top_k best matches
    (plus any specialist without a focus, which cannot be ranked)."""
    spec = agent_spec.current()
    if not spec.orchestrator:
        return []
    everyone = await anyio.to_thread.run_sync(specialists)
    rankable = {r.id: r.focus for r in everyone if r.focus}
    if not spec.routing.laya or len(rankable) <= spec.routing.top_k:
        return everyone
    try:
        chosen = await anyio.to_thread.run_sync(
            (ranker or tool_selection.default_ranker()).rank, question, rankable, spec.routing.top_k
        )
    except Exception:
        _log.warning("Laya agent shortlist failed; offering every specialist", exc_info=True)
        return everyone
    keep = set(chosen)
    return [r for r in everyone if r.id in keep or not r.focus]


def resolve_auto(question: str, ranker: Any = None) -> RosterEntry:
    """The specialist whose focus best fits `question`. Blocking - runs on
    delegation's worker thread. Raises ValueError (shown to the model as
    the tool's error) when it cannot choose."""
    spec = agent_spec.current()
    everyone = specialists()
    rankable = {r.id: r.focus for r in everyone if r.focus}
    if not rankable:
        raise ValueError("no specialist has a focus to route by - pick an agent_id explicitly")
    try:
        labels, scores = (ranker or tool_selection.default_ranker()).rank_with_scores(question, rankable, 1)
    except Exception as error:
        raise ValueError(f"automatic routing is unavailable ({error}) - pick an agent_id explicitly") from error
    if not labels:
        raise ValueError("automatic routing found no specialist - pick an agent_id explicitly")
    best = labels[0]
    if spec.routing.min_score is not None and scores is not None and scores[0] < spec.routing.min_score:
        raise ValueError(
            f"no specialist matches well enough (best: {best}, score {scores[0]:.2f}) - "
            "answer yourself or pick an agent_id explicitly"
        )
    return next(r for r in everyone if r.id == best)
```

- [ ] **Step 5: Run the routing tests**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_routing.py -q`
Expected: all pass.

- [ ] **Step 6: Update the delegation tests (contract change)**

In `tests/test_delegation.py`:
- delete `test_is_available_false_with_no_configured_agents`, `test_is_available_true_with_configured_agents` and `test_tool_description_lists_configured_agent_ids_and_labels`;
- add:

```python
from src.agent_spec import RosterEntry

ROSTER = [RosterEntry("calc", "Calculator", "Arithmetic."), RosterEntry("explainer", "Explainer", "Explanations.")]


def test_tool_parameters_enumerate_the_roster():
    params = delegation.tool_parameters(ROSTER, allow_auto=False)
    assert params["properties"]["agent_id"]["enum"] == ["calc", "explainer"]
    assert params["required"] == ["agent_id", "question"]


def test_tool_parameters_offer_auto_when_allowed():
    params = delegation.tool_parameters(ROSTER, allow_auto=True)
    assert params["properties"]["agent_id"]["enum"] == ["calc", "explainer", "auto"]


def test_tool_description_lists_the_roster_and_auto():
    description = delegation.tool_description(ROSTER, allow_auto=True)
    assert "calc (Calculator): Arithmetic." in description
    assert '"auto"' in description


def test_call_resolves_auto_through_routing(monkeypatch):
    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr("src.delegation.agent_routing.resolve_auto", lambda question: ROSTER[0])

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        return {"response": "4"}

    with patch("src.delegation._call_tool", side_effect=_fake_call_tool):
        result = delegation.call("auto", "2+2?", depth=0)

    assert result == "Delegated to calc (Calculator).\n\n4"
```

- in `_configure_agents`, also add `monkeypatch.setattr(agent_registry, "reload", lambda: None)` so `call()`'s reload does not replace the configured agents with the real file.

- [ ] **Step 7: Implement delegation changes**

In `src/delegation.py`:
- add `from src import agent_registry, agent_routing, approvals, internal_auth` (extending the import) and `from src.agent_spec import RosterEntry`;
- add `AUTO_AGENT_ID = "auto"` after `TOOL_NAME`;
- delete `TOOL_PARAMETERS`, `is_available()` and the old `tool_description()`, and add:

```python
def tool_parameters(roster: list[RosterEntry], allow_auto: bool) -> dict[str, Any]:
    """The delegate tool's input schema: agent_id limited to this turn's
    roster (plus "auto" when Laya routing may choose)."""
    ids = [r.id for r in roster] + ([AUTO_AGENT_ID] if allow_auto else [])
    return {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "enum": ids, "description": "Which specialist to delegate to."},
            "question": {"type": "string", "description": "The focused sub-question to ask it."},
        },
        "required": ["agent_id", "question"],
    }


def tool_description(roster: list[RosterEntry], allow_auto: bool) -> str:
    listing = "; ".join(f"{r.id} ({r.label}): {r.focus or 'no focus given'}" for r in roster)
    auto = ' Use agent_id "auto" to let routing pick the best specialist for the question.' if allow_auto else ""
    return (
        f"Hand a focused sub-question to a specialist agent and get its answer back. Specialists: {listing}.{auto} "
        "Sequential: each call adds latency, so delegate only what a specialist does better."
    )
```

- in `call()`, replace everything from `agent = agent_registry.get_agent(agent_id)` down to (not including) the `approval_mode = ...` line with:

```python
    prefix = ""
    if agent_id == AUTO_AGENT_ID:
        chosen = agent_routing.resolve_auto(question)
        agent_id = chosen.id
        prefix = f"Delegated to {chosen.id} ({chosen.label}).\n\n"

    # Specialists start and stop on their own - read the current registry.
    agent_registry.reload()
    agent = agent_registry.get_agent(agent_id)
    if agent is None:
        configured = ", ".join(agent_registry.list_agent_ids()) or "(none configured)"
        raise ValueError(f"unknown agent_id {agent_id!r} - configured agents: {configured}")
```

- change the final `return result.get("response", "")` to `return prefix + result.get("response", "")`;
- give `_call_tool` an `on_progress` parameter now (Task 7 uses it): `async def _call_tool(url: str, name: str, arguments: dict[str, Any], on_progress: Any = None)`, and pass it on: `result = await session.call_tool(name, arguments, progress_callback=on_progress)`.

In the existing `test_call_returns_the_sub_agents_response_on_success`, change the fake to `async def _fake_call_tool(url, name, arguments, on_progress=None):`. Read the remaining `_call_tool` tests in that file and update any fake `session.call_tool` assertion to expect `progress_callback=None`.

- [ ] **Step 8: Wire the roster into both providers**

In `src/llm/anthropic_provider.py`:
- add `agent_routing, agent_spec` to `from src import approvals, delegation, tool_selection`, and `from src.agent_spec import RosterEntry`;
- replace `_tool_schemas` with:

```python
def _tool_schemas(enabled_extensions: list[str] | None = None, roster: Sequence[RosterEntry] = ()) -> list[dict[str, Any]]:
    # display_label rides along on every schema dict returned here so
    # run_chat can build its step_start "label" lookup from the same
    # list it already has - it is NOT a real Anthropic tools= schema
    # field, so run_chat pops it back off before sending schemas to the
    # API (see the `labels = {...pop...}` line below).
    schemas = [
        {
            "name": tool.name,
            "description": tool_description(tool),
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
            "display_label": (tool.meta or {}).get("display_label") if hasattr(tool, "meta") else None,
        }
        for tool in list_tools(enabled_extensions)
    ]
    # Only an orchestrator has a roster, so only it can delegate.
    if roster:
        allow_auto = agent_spec.current().routing.allow_auto
        schemas.append(
            {
                "name": delegation.TOOL_NAME,
                "description": delegation.tool_description(list(roster), allow_auto),
                "input_schema": delegation.tool_parameters(list(roster), allow_auto),
                "display_label": None,
            }
        )
    return schemas
```

  (add `from typing import Any, Sequence`);
- in `run_chat`, replace `system_prompt = system_prompt_for(caveman)` and `schemas = _tool_schemas(enabled_extensions)` with:

```python
    roster = await agent_routing.roster_for(question)
    system_prompt = system_prompt_for(caveman, roster)
```

  and

```python
    schemas = _tool_schemas(enabled_extensions, roster)
```

Make the same three changes in `src/llm/openai_provider.py`. Its schema dicts keep their `"type": "function"` and `"parameters"` shape. Its system message becomes `{"role": "system", "content": system_prompt_for(caveman, roster)}`, with `roster = await agent_routing.roster_for(question)` computed before `messages` is built.

- [ ] **Step 9: Update provider tests (contract change)**

In `tests/test_anthropic_provider.py`:
- add `from src.agent_spec import RosterEntry` and `ROSTER = [RosterEntry("openai-agent", "OpenAI Agent", "second opinion")]`;
- add this autouse fixture so no test reads the real registry:

```python
@pytest.fixture(autouse=True)
def _no_roster():
    with patch("src.llm.anthropic_provider.agent_routing.roster_for", new_callable=AsyncMock, return_value=[]):
        yield
```

- `test_tool_schemas_use_input_schema_shape` and `test_tool_schemas_excludes_delegate_tool_when_unavailable`: drop the `delegation.is_available` patch (no roster → no delegate tool);
- `test_tool_schemas_includes_delegate_tool_when_available`: drop the `is_available` patch, call `anthropic_provider._tool_schemas(roster=ROSTER)`, and expect `"input_schema": anthropic_provider.delegation.tool_parameters(ROSTER, False)`;
- in the two `run_chat` delegation tests, replace `patch("src.llm.anthropic_provider.delegation.is_available", return_value=True)` with `patch("src.llm.anthropic_provider.agent_routing.roster_for", new_callable=AsyncMock, return_value=ROSTER)`.

Make the identical edits in `tests/test_openai_provider.py`, with `src.llm.openai_provider` paths and the `"parameters"` key.

- [ ] **Step 10: Run the full suite**

Run: `.venv_ai_agent\Scripts\python -m pytest -q`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add src/agent_routing.py src/tool_selection.py src/delegation.py src/llm/anthropic_provider.py src/llm/openai_provider.py tests/test_agent_routing.py tests/test_delegation.py tests/test_anthropic_provider.py tests/test_openai_provider.py
git commit -m "ai_agent: orchestrator roster per turn, Laya shortlist and auto routing for delegate_to_agent

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Live agent-activity events

**Files:**
- Create: `src/agent_events.py`
- Modify: `src/llm/base_provider.py` (`dispatch_with_progress`)
- Modify: `src/delegation.py` (`call`, new `_progress_forwarder`)
- Modify: `src/server.py` (`ask`'s `on_event`, new `delegated_by` parameter)
- Test: `tests/test_agent_events.py`, `tests/test_delegation.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `delegation._call_tool(url, name, arguments, on_progress=None)` from Task 6; `server._AGENT_ID/_AGENT_LABEL/SPEC`.
- Produces:
  - `agent_events.now_iso() -> str`
  - `agent_events.stamp(event: dict, agent_id: str, agent_label: str) -> dict` (keeps an existing `agent_id`)
  - `agent_events.bind(sink: Callable[[dict], None], step_id: str) -> Token`, `reset(token)`, `emitter() -> Callable[[dict], None] | None`, `current_step_id() -> str | None`, `emit(event) -> None`
  - `agent_events.forwarded(event: dict, step_id: str | None) -> dict | None`
  - `server.ask(..., delegated_by: str | None = None, ...)`. Delegation passes `"delegated_by": <caller id>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_events.py`:

```python
"""agent_events.py tests: stamping keeps the innermost agent, specialist
events are translated for the orchestrator's stream, and the sink bound by
dispatch_with_progress carries them back to on_event in order."""

from __future__ import annotations

import asyncio
import re

from src import agent_events
from src.llm.base_provider import dispatch_with_progress


def test_now_iso_is_utc_with_milliseconds():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", agent_events.now_iso())


def test_stamp_adds_identity_but_keeps_an_inner_agent():
    assert agent_events.stamp({"type": "step_start"}, "orchestrator", "Ember") == {
        "type": "step_start", "agent_id": "orchestrator", "agent_label": "Ember",
    }
    inner = {"type": "step_start", "agent_id": "calc", "agent_label": "Calculator"}
    assert agent_events.stamp(inner, "orchestrator", "Ember") == inner


def test_forwarded_translates_tokens_and_drops_usage():
    token = {"type": "token", "text": "15%", "agent_id": "calc", "agent_label": "Calculator"}
    assert agent_events.forwarded(token, "step-9") == {
        "type": "agent_token", "agent_id": "calc", "agent_label": "Calculator", "step_id": "step-9", "text": "15%",
    }
    reset = agent_events.forwarded({"type": "token_reset", "agent_id": "calc", "agent_label": "C"}, "step-9")
    assert reset["reset"] is True and reset["text"] == ""
    step = {"type": "step_start", "id": "x", "agent_id": "calc"}
    assert agent_events.forwarded(step, "step-9") == step
    assert agent_events.forwarded({"type": "usage", "total_tokens": 5}, "step-9") is None
    assert agent_events.forwarded({"type": "approval_request"}, "step-9") is None


def test_dispatch_with_progress_carries_emitted_events_to_on_event():
    events = []

    async def on_event(event):
        events.append(event)

    def dispatch():
        assert agent_events.current_step_id() == "step-1"
        agent_events.emit({"type": "agent_start", "agent_id": "calc"})
        agent_events.emit({"type": "agent_end", "agent_id": "calc", "ok": True})
        return "done"

    assert asyncio.run(dispatch_with_progress(dispatch, on_event, "step-1")) == "done"
    assert [e["type"] for e in events] == ["agent_start", "agent_end"]
    assert agent_events.emitter() is None


def test_emit_without_a_bound_sink_is_a_noop():
    agent_events.emit({"type": "agent_start"})
```

Append to `tests/test_delegation.py`:

```python
def test_call_emits_start_and_end_and_forwards_specialist_progress(monkeypatch):
    import json as _json
    from src import agent_events

    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    emitted = []
    token = agent_events.bind(emitted.append, "step-7")

    async def _fake_call_tool(url, name, arguments, on_progress=None):
        assert arguments["delegated_by"] == delegation.agent_spec.current().id
        await on_progress(0, None, _json.dumps({"type": "token", "text": "4", "agent_id": "calc", "agent_label": "Calculator"}))
        await on_progress(0, None, _json.dumps({"type": "usage", "total_tokens": 9}))
        await on_progress(0, None, "not json")
        return {"response": "4"}

    try:
        with patch("src.delegation._call_tool", side_effect=_fake_call_tool):
            assert delegation.call("calc", "2+2?", depth=0) == "4"
    finally:
        agent_events.reset(token)

    assert [e["type"] for e in emitted] == ["agent_start", "agent_token", "agent_end"]
    start, tok, end = emitted
    assert start["agent_id"] == "calc" and start["question"] == "2+2?" and start["step_id"] == "step-7"
    assert tok["text"] == "4" and tok["step_id"] == "step-7"
    assert end["ok"] is True


def test_call_emits_a_failed_end_when_the_specialist_errors(monkeypatch):
    from src import agent_events

    _configure_agents(monkeypatch, [{"id": "calc", "label": "Calculator", "url": "http://c/mcp"}])
    emitted = []
    token = agent_events.bind(emitted.append, "step-7")
    try:
        with patch("src.delegation._call_tool", side_effect=RuntimeError("down")):
            try:
                delegation.call("calc", "2+2?", depth=0)
                raise AssertionError("expected RuntimeError")
            except RuntimeError:
                pass
    finally:
        agent_events.reset(token)

    assert emitted[-1]["type"] == "agent_end" and emitted[-1]["ok"] is False
```

In `test_call_returns_the_sub_agents_response_on_success`, add `"delegated_by": delegation.agent_spec.current().id` to the expected `arguments` dict.

In `tests/test_server.py`, change the last assertion of `test_ask_relays_events_via_ctx_report_progress` to:

```python
        assert json.loads(message) == {
            "type": "step_start", "id": "1", "tool": "x",
            "agent_id": server._AGENT_ID, "agent_label": server._AGENT_LABEL,
        }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_agent_events.py tests/test_delegation.py tests/test_server.py -q`
Expected: FAIL with `ModuleNotFoundError: src.agent_events`.

- [ ] **Step 3: Create `src/agent_events.py`**

```python
"""Live "which agent is working" events.

Every event an agent sends up its stream carries agent_id/agent_label
(stamp()). When an orchestrator delegates, delegation.py emits
agent_start/agent_end around the call and re-emits the specialist's own
events - received as MCP progress notifications - into the orchestrator's
stream. The path back up is a ContextVar sink bound by
base_provider.dispatch_with_progress for the duration of one tool step,
the same pattern as tool_progress.py: the delegation runs several layers
down on a worker thread, so threading a callback through every signature
would touch them all.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Callable

Sink = Callable[[dict[str, Any]], None]

_bound: ContextVar[tuple[Sink, str] | None] = ContextVar("agent_events_sink", default=None)

# Specialist events that make sense in the orchestrator's stream as-is.
# `usage` stays out on purpose: callers read usage events as the turn's
# running total, and a specialist's figure would replace the orchestrator's.
_PASS_THROUGH = {"step_start", "step_progress", "step_end", "agent_start", "agent_end", "agent_token"}


def now_iso() -> str:
    """UTC, millisecond precision, "Z" suffix - the one timestamp format
    for events and usage rows."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp(event: dict[str, Any], agent_id: str, agent_label: str) -> dict[str, Any]:
    """`event` with this agent's identity, unless it already names one (a
    forwarded event keeps the innermost agent that produced it)."""
    if event.get("agent_id"):
        return event
    return {**event, "agent_id": agent_id, "agent_label": agent_label}


def bind(sink: Sink, step_id: str) -> Token:
    return _bound.set((sink, step_id))


def reset(token: Token) -> None:
    _bound.reset(token)


def emitter() -> Sink | None:
    bound = _bound.get()
    return bound[0] if bound else None


def current_step_id() -> str | None:
    bound = _bound.get()
    return bound[1] if bound else None


def emit(event: dict[str, Any]) -> None:
    """Send `event` up the current step's stream; a no-op when nothing is
    listening (non-streaming callers, tests)."""
    sink = emitter()
    if sink is not None:
        sink(event)


def forwarded(event: dict[str, Any], step_id: str | None) -> dict[str, Any] | None:
    """A specialist's event as the orchestrator's stream should carry it,
    or None to drop it. Its answer text becomes agent_token so it never
    mixes into the orchestrator's own answer."""
    kind = event.get("type")
    if kind in ("token", "token_reset"):
        out = {
            "type": "agent_token",
            "agent_id": event.get("agent_id"),
            "agent_label": event.get("agent_label"),
            "step_id": step_id,
            "text": event.get("text", "") if kind == "token" else "",
        }
        if kind == "token_reset":
            out["reset"] = True
        return out
    if kind in _PASS_THROUGH:
        return event
    return None
```

- [ ] **Step 4: Bind the sink in `dispatch_with_progress`**

In `src/llm/base_provider.py`, import `agent_events` alongside `tool_progress` (`from src import agent_events, tool_progress`). Replace the body after `pending: list[Any] = []` with:

```python
    def sink(message: str) -> None:
        pending.append(
            asyncio.run_coroutine_threadsafe(on_event(step_event("step_progress", id=step_id, message=message)), loop)
        )

    def event_sink(event: dict[str, Any]) -> None:
        pending.append(asyncio.run_coroutine_threadsafe(on_event(event), loop))

    token = tool_progress.bind(sink)
    events_token = agent_events.bind(event_sink, step_id)
    try:
        return await anyio.to_thread.run_sync(dispatch, *args)
    finally:
        agent_events.reset(events_token)
        tool_progress.reset(token)
        # Deliver every queued progress event before the caller's step_end.
        await asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True)
```

Update the docstring's last sentence to say it also carries `agent_events` emitted by a delegated call.

- [ ] **Step 5: Emit and forward in `delegation.call`**

In `src/delegation.py`, add `import json`, and extend the project import to `from src import agent_events, agent_registry, agent_routing, agent_spec, approvals, internal_auth`. Add:

```python
def _progress_forwarder(sink: agent_events.Sink | None, step_id: str | None) -> Any:
    """An MCP progress callback that re-emits the specialist's live events
    (JSON in each progress message - see server.ask) into this agent's
    stream. The sink is captured here, not looked up per message: the
    callback runs on the MCP client's own task inside asyncio.run below."""
    if sink is None:
        return None

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        if not message:
            return
        try:
            event = json.loads(message)
        except ValueError:
            return
        if isinstance(event, dict):
            out = agent_events.forwarded(event, step_id)
            if out is not None:
                sink(out)

    return on_progress
```

In `call()`, replace from `approval_mode = ...` to the end of the function with:

```python
    # A delegate has no way to ask the user, so when this turn asks before
    # tools run, the delegate's tools that would need asking are refused.
    approval_mode = "off" if approvals.current().mode == "off" else "deny"
    me = agent_spec.current().id
    label = agent.get("label") or agent_id
    step_id = agent_events.current_step_id()
    sink = agent_events.emitter()
    agent_events.emit({
        "type": "agent_start", "agent_id": agent_id, "agent_label": label, "delegated_by": me,
        "question": question, "step_id": step_id, "at": agent_events.now_iso(),
    })
    ok = False
    try:
        result = asyncio.run(
            _call_tool(
                agent["url"],
                "ask",
                {
                    "question": question,
                    "history": [],
                    "enabled_extensions": [],
                    "request_id": None,
                    "depth": depth + 1,
                    "approval_mode": approval_mode,
                    "delegated_by": me,
                },
                on_progress=_progress_forwarder(sink, step_id),
            )
        )
        ok = True
    finally:
        agent_events.emit({
            "type": "agent_end", "agent_id": agent_id, "agent_label": label,
            "ok": ok, "step_id": step_id, "at": agent_events.now_iso(),
        })
    usage_sink = _usage_sink.get()
    if usage_sink is not None:
        # The delegate's own entries already include anything it delegated on.
        usage_sink.extend(result.get("agent_usage") or [])
    return prefix + result.get("response", "")
```

- [ ] **Step 6: Stamp events and accept `delegated_by` in `server.ask`**

In `src/server.py`, add `agent_events` to `from src import agent_config, agent_registry, approvals, internal_auth, mcp_upstream`. Add `delegated_by: str | None = None,` to `ask()`'s parameters after `allowed_tools`, and document it in the docstring: "delegated_by: the orchestrator's agent id when another agent delegated this question (see delegation.py); recorded in usage rows." Change the `on_event` body to:

```python
        if ctx is not None:
            await ctx.report_progress(0, None, json.dumps(agent_events.stamp(event, _AGENT_ID, _AGENT_LABEL)))
```

- [ ] **Step 7: Run the full suite**

Run: `.venv_ai_agent\Scripts\python -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/agent_events.py src/llm/base_provider.py src/delegation.py src/server.py tests/test_agent_events.py tests/test_delegation.py tests/test_server.py
git commit -m "ai_agent: live agent_start/agent_end/agent_token events and specialist event forwarding

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Per-agent usage rows and the usage log

**Files:**
- Create: `src/usage_log.py`
- Modify: `src/server.py` (`ask`)
- Modify: `tests/conftest.py`
- Test: `tests/test_usage_log.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `ChatResult`, `agent_events.now_iso()`, `SPEC.effective_gateway()`, `ask(..., delegated_by=...)` from Task 7.
- Produces:
  - `usage_log.own_row(result: ChatResult, *, agent_id: str, agent_label: str, gateway: str | None, started_at: str, finished_at: str, delegated_by: str | None) -> dict`
  - `async usage_log.append(row: dict, directory: Path | None = None) -> None`
  - `usage_log.usage_dir() -> Path` (env `AI_AGENT_USAGE_DIR`, default `ai_agent/data/usage`)
  - `ask()`'s `agent_usage[0]` gains `agent_id, agent_label, gateway, started_at, finished_at, delegated_by`.

- [ ] **Step 1: Keep tests from writing into `data/usage`**

Append to `tests/conftest.py`:

```python
import tempfile

# server.ask() appends every turn to the usage log; keep test turns out of
# the real ai_agent/data/usage/.
os.environ.setdefault("AI_AGENT_USAGE_DIR", tempfile.mkdtemp(prefix="ai_agent_usage_"))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_usage_log.py`:

```python
"""usage_log.py tests: the agent_usage row shape and the per-agent,
per-day JSONL append (which never fails a turn)."""

from __future__ import annotations

import asyncio
import json
import logging

from src import usage_log
from src.llm.base_provider import ChatResult


def _row():
    result = ChatResult(response="x", provider_id="anthropic", model="claude-sonnet-5-5",
                        total_tokens=15, input_tokens=10, output_tokens=5)
    return usage_log.own_row(
        result, agent_id="calc", agent_label="Calculator", gateway="openrouter",
        started_at="2026-10-04T09:12:03.512Z", finished_at="2026-10-04T09:12:07.044Z", delegated_by="claude-agent",
    )


def test_own_row_shape():
    assert _row() == {
        "agent_id": "calc", "agent_label": "Calculator", "provider_id": "anthropic", "gateway": "openrouter",
        "model": "claude-sonnet-5-5", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
        "started_at": "2026-10-04T09:12:03.512Z", "finished_at": "2026-10-04T09:12:07.044Z",
        "delegated_by": "claude-agent",
    }


def test_append_writes_one_line_per_turn_to_a_per_agent_daily_file(tmp_path):
    asyncio.run(usage_log.append({**_row(), "request_id": "r1"}, tmp_path))
    asyncio.run(usage_log.append({**_row(), "request_id": "r2"}, tmp_path))

    lines = (tmp_path / "2026-10-04.calc.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["request_id"] for line in lines] == ["r1", "r2"]


def test_append_failure_only_warns(tmp_path, caplog):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="src.usage_log"):
        asyncio.run(usage_log.append(_row(), blocker))
    assert "usage log" in caplog.text


def test_usage_dir_honours_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_AGENT_USAGE_DIR", str(tmp_path))
    assert usage_log.usage_dir() == tmp_path
```

In `tests/test_server.py`, replace the `"agent_usage": [...]` line of the big expected dict in `test_ask_returns_the_result_shape_chat_app_expects` with `"agent_usage": ANY,`. Add `ANY` to the `unittest.mock` import, and append after that `assert result == {...}`:

```python
        own = result["agent_usage"][0]
        assert own["agent_id"] == server._AGENT_ID
        assert own["agent_label"] == server._AGENT_LABEL
        assert (own["provider_id"], own["model"], own["input_tokens"], own["output_tokens"], own["total_tokens"]) == (
            "anthropic", "claude-sonnet-5", 30, 12, 42,
        )
        assert own["delegated_by"] is None
        assert own["started_at"] <= own["finished_at"]
```

Append:

```python
def test_ask_records_delegated_by_and_appends_to_the_usage_log():
    async def _run():
        with patch("src.server.agent_config.run_chat", new_callable=AsyncMock, return_value=ChatResult(response="hi")), \
             patch("src.server.agent_config.status", return_value={"model": "m", "context_window": 1}), \
             patch("src.server.usage_log.append", new_callable=AsyncMock) as append:
            result = await server.ask("q", request_id="r-1", depth=1, delegated_by="orchestrator")

        assert result["agent_usage"][0]["delegated_by"] == "orchestrator"
        row = append.await_args.args[0]
        assert row["request_id"] == "r-1" and row["depth"] == 1 and row["delegated_by"] == "orchestrator"

    asyncio.run(_run())
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_usage_log.py tests/test_server.py -q`
Expected: FAIL with `ModuleNotFoundError: src.usage_log`.

- [ ] **Step 4: Create `src/usage_log.py`**

```python
"""Token usage per agent: the row each ask() returns in agent_usage, and a
local JSONL copy of it so usage is visible even for callers that never go
through ember (chat_cli, direct MCP calls, tests).

One file per agent per UTC day (data/usage/YYYY-MM-DD.<agent id>.jsonl),
so two agent processes never write the same file. Writing never fails a
turn: an error is logged and the turn carries on.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import anyio.to_thread

from src.llm.base_provider import ChatResult

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "usage"
_log = logging.getLogger(__name__)
# Serializes appends within this process. A threading lock, not an
# asyncio one: writes run on worker threads, and tests use many loops.
_lock = threading.Lock()


def usage_dir() -> Path:
    return Path(os.getenv("AI_AGENT_USAGE_DIR") or _DEFAULT_DIR)


def own_row(
    result: ChatResult,
    *,
    agent_id: str,
    agent_label: str,
    gateway: str | None,
    started_at: str,
    finished_at: str,
    delegated_by: str | None,
) -> dict[str, Any]:
    """This agent's own agent_usage entry for one ask() (delegated agents
    add their own rows - see delegation.py)."""
    return {
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


def _write(row: dict[str, Any], directory: Path) -> None:
    path = directory / f"{row['finished_at'][:10]}.{row['agent_id']}.jsonl"
    with _lock:
        directory.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row) + "\n")


async def append(row: dict[str, Any], directory: Path | None = None) -> None:
    try:
        await anyio.to_thread.run_sync(_write, row, directory or usage_dir())
    except Exception:
        _log.warning("could not write the usage log", exc_info=True)
```

- [ ] **Step 5: Build the row in `server.ask`**

In `src/server.py`, add `usage_log` to the project import. In `ask()`:
- right before the `requester_token = ...` line, add `started_at = agent_events.now_iso()`;
- after the `try/except/finally` around `run_chat`, before `return {...}`, add:

```python
    own_usage = usage_log.own_row(
        result, agent_id=_AGENT_ID, agent_label=_AGENT_LABEL, gateway=SPEC.effective_gateway(),
        started_at=started_at, finished_at=agent_events.now_iso(), delegated_by=delegated_by,
    )
    await usage_log.append({**own_usage, "request_id": request_id, "depth": depth})
```

- replace the `"agent_usage": [ {...}, *result.delegated_usage ]` entry with:

```python
        # Own usage first, then every delegated agent's, so callers can
        # break tokens down per agent (who, which provider/gateway, when).
        "agent_usage": [own_usage, *result.delegated_usage],
```

- [ ] **Step 6: Run the full suite**

Run: `.venv_ai_agent\Scripts\python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/usage_log.py src/server.py tests/conftest.py tests/test_usage_log.py tests/test_server.py
git commit -m "ai_agent: per-agent usage rows with gateway, timestamps and delegated_by, plus a JSONL usage log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Supervisor

**Files:**
- Create: `src/supervisor.py`
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Consumes: `agent_spec.load_dir`, `agent_spec.ensure_agents_dir`, `agent_spec.AGENTS_DIR`, `AgentSpec.source/port/id/enabled`, `agent_registry.deregister`.
- Produces:
  - `CrashPolicy(max_crashes=5, window=300.0, base=1.0, cap=60.0, clock=time.monotonic)` with `record() -> float | None`
  - `child_env(spec) -> dict[str, str]`, `default_command(spec) -> list[str]`
  - `AgentProcess(spec, command_for, deregister, out, policy, sleep)` with `async run()`, `async stop(grace)`, attribute `failed: bool`
  - `Supervisor(specs, command_for=default_command, deregister=agent_registry.deregister, out=_print, policy_factory=CrashPolicy, sleep=asyncio.sleep)` with `async run()`, `async stop()`
  - `main() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_supervisor.py`:

```python
"""supervisor.py tests with real (tiny) child processes: output is
prefixed, a crash deregisters and restarts with backoff, the fifth crash
in the window gives up, stop() ends children promptly, and leftover
registry entries for our own agents are cleared at start."""

from __future__ import annotations

import asyncio
import sys

from src import supervisor
from src.agent_spec import AgentSpec, LlmSpec


def _spec(agent_id, port=9200, enabled=True, tmp_path=None):
    return AgentSpec(id=agent_id, label=agent_id, port=port, llm=LlmSpec(provider="anthropic"),
                     enabled=enabled, source=(tmp_path / f"{agent_id}.json") if tmp_path else None)


def test_crash_policy_backoff_and_give_up():
    now = [0.0]
    policy = supervisor.CrashPolicy(max_crashes=5, window=300.0, base=1.0, cap=4.0, clock=lambda: now[0])
    delays = [policy.record() for _ in range(4)]
    assert delays == [1.0, 2.0, 4.0, 4.0]
    assert policy.record() is None


def test_crash_policy_forgets_old_crashes():
    now = [0.0]
    policy = supervisor.CrashPolicy(max_crashes=2, window=10.0, clock=lambda: now[0])
    assert policy.record() == 1.0
    now[0] = 20.0
    assert policy.record() == 1.0


def test_child_env_points_at_the_agent_file(tmp_path):
    env = supervisor.child_env(_spec("calc", port=9103, tmp_path=tmp_path))
    assert env["AI_AGENT_FILE"] == str(tmp_path / "calc.json")
    assert env["AI_AGENT_PORT"] == "9103"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_crashing_child_is_prefixed_deregistered_restarted_then_failed(tmp_path):
    lines, deregistered, sleeps = [], [], []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    sup = supervisor.Supervisor(
        [_spec("calc", tmp_path=tmp_path), _spec("off", enabled=False, tmp_path=tmp_path)],
        command_for=lambda spec: [sys.executable, "-c", "print('hello from child'); raise SystemExit(3)"],
        deregister=deregistered.append,
        out=lines.append,
        policy_factory=lambda: supervisor.CrashPolicy(max_crashes=2),
        sleep=fake_sleep,
    )

    asyncio.run(asyncio.wait_for(sup.run(), timeout=30))

    assert lines.count("[calc] hello from child") == 2
    assert any("restarting in 1s" in line for line in lines)
    assert any("not restarting" in line for line in lines)
    assert sleeps == [1.0]
    # start-up cleanup for both files, one crash before the restart, one
    # after the final crash, then the shutdown sweep.
    assert deregistered[:2] == ["calc", "off"]
    assert deregistered.count("calc") >= 3
    assert "off" not in deregistered[2:]


def test_stop_terminates_a_running_child_quickly(tmp_path):
    lines = []

    async def scenario():
        sup = supervisor.Supervisor(
            [_spec("calc", tmp_path=tmp_path)],
            command_for=lambda spec: [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"],
            deregister=lambda agent_id: None,
            out=lines.append,
        )
        task = asyncio.create_task(sup.run())
        for _ in range(200):
            if "[calc] up" in lines:
                break
            await asyncio.sleep(0.05)
        await sup.stop()
        await asyncio.wait_for(task, timeout=15)

    asyncio.run(scenario())
    assert "[calc] up" in lines
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_supervisor.py -q`
Expected: `ModuleNotFoundError: No module named 'src.supervisor'`.

- [ ] **Step 3: Implement `src/supervisor.py`**

```python
"""Starts every agent in ai_agent/agents/ as its own `python -m src.server`
child process and keeps them running.

run.bat runs this module, so server_launcher still sees one ai_agent
instance. All agent files are validated before any child starts. Each
child's output is relayed line by line as "[<agent id>] ...". A child that
exits on its own is deregistered (it could not clean up after itself),
then restarted with backoff - 1s, 2s, 4s... up to 60s - until it has
crashed 5 times within 5 minutes, after which it is left stopped and the
others keep running.

Run with:
    python -m src.supervisor
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from src import agent_registry, agent_spec
from src.agent_spec import AgentSpec

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_CRASHES = 5
CRASH_WINDOW_SECONDS = 300.0
BACKOFF_CAP_SECONDS = 60.0
STOP_GRACE_SECONDS = 10.0

CommandFor = Callable[[AgentSpec], Sequence[str]]
Deregister = Callable[[str], None]
Out = Callable[[str], None]
Sleep = Callable[[float], Awaitable[None]]


def _print(line: str) -> None:
    print(line, flush=True)


def default_command(spec: AgentSpec) -> list[str]:
    return [sys.executable, "-m", "src.server"]


def child_env(spec: AgentSpec) -> dict[str, str]:
    env = dict(os.environ)
    env["AI_AGENT_FILE"] = str(spec.source)
    env["AI_AGENT_PORT"] = str(spec.port)
    env["PYTHONUNBUFFERED"] = "1"  # relay output as it happens, not per 8 KB block
    return env


class CrashPolicy:
    """Backoff for one child: record() a crash, get the delay before the
    restart, or None once it has crashed max_crashes times in `window`."""

    def __init__(
        self,
        max_crashes: int = MAX_CRASHES,
        window: float = CRASH_WINDOW_SECONDS,
        base: float = 1.0,
        cap: float = BACKOFF_CAP_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_crashes
        self._window = window
        self._base = base
        self._cap = cap
        self._clock = clock
        self._crashes: list[float] = []

    def record(self) -> float | None:
        now = self._clock()
        self._crashes = [t for t in self._crashes if now - t < self._window]
        self._crashes.append(now)
        if len(self._crashes) >= self._max:
            return None
        return min(self._base * 2 ** (len(self._crashes) - 1), self._cap)


class AgentProcess:
    """One agent's child process: start it, relay its output, restart it."""

    def __init__(
        self, spec: AgentSpec, command_for: CommandFor, deregister: Deregister, out: Out,
        policy: CrashPolicy, sleep: Sleep,
    ) -> None:
        self.spec = spec
        self.failed = False
        self._command_for = command_for
        self._deregister = deregister
        self._out = out
        self._policy = policy
        self._sleep = sleep
        self._proc: asyncio.subprocess.Process | None = None
        self._stopping = False

    async def run(self) -> None:
        while not self._stopping:
            self._proc = await asyncio.create_subprocess_exec(
                *self._command_for(self.spec),
                cwd=PROJECT_ROOT,
                env=child_env(self.spec),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await self._relay()
            code = await self._proc.wait()
            if self._stopping:
                return
            await asyncio.to_thread(self._deregister, self.spec.id)
            delay = self._policy.record()
            if delay is None:
                self.failed = True
                self._out(f"[supervisor] {self.spec.id} crashed {MAX_CRASHES} times in 5 minutes - not restarting")
                return
            self._out(f"[supervisor] {self.spec.id} exited with code {code} - restarting in {delay:g}s")
            await self._sleep(delay)

    async def _relay(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        async for raw in self._proc.stdout:
            self._out(f"[{self.spec.id}] {raw.decode(errors='replace').rstrip()}")

    async def stop(self, grace: float = STOP_GRACE_SECONDS) -> None:
        self._stopping = True
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), grace)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


class Supervisor:
    def __init__(
        self,
        specs: list[AgentSpec],
        command_for: CommandFor = default_command,
        deregister: Deregister = agent_registry.deregister,
        out: Out = _print,
        policy_factory: Callable[[], CrashPolicy] = CrashPolicy,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._specs = specs
        self._deregister = deregister
        self._out = out
        self._children = [
            AgentProcess(spec, command_for, deregister, out, policy_factory(), sleep)
            for spec in specs if spec.enabled
        ]

    async def run(self) -> None:
        # Entries a crashed earlier run left behind for OUR agents only.
        for spec in self._specs:
            await asyncio.to_thread(self._deregister, spec.id)
        self._out(f"[supervisor] starting {', '.join(c.spec.id for c in self._children) or 'no agents'}")
        try:
            await asyncio.gather(*(child.run() for child in self._children))
        finally:
            await self.stop()
        if self._children and all(child.failed for child in self._children):
            self._out("[supervisor] every agent failed - exiting")

    async def stop(self) -> None:
        await asyncio.gather(*(child.stop() for child in self._children))
        # Children deregister on a clean exit; a terminated one cannot.
        for child in self._children:
            await asyncio.to_thread(self._deregister, child.spec.id)


def main() -> None:
    agent_spec.ensure_agents_dir()
    try:
        specs = agent_spec.load_dir(agent_spec.AGENTS_DIR)
    except agent_spec.AgentSpecError as error:
        sys.stderr.write(f"\nai_agent cannot start - agent file error:\n  {error}\n\n")
        sys.exit(1)
    try:
        asyncio.run(Supervisor(specs).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `.venv_ai_agent\Scripts\python -m pytest tests/test_supervisor.py -q`
Expected: all pass. If `test_stop_terminates_a_running_child_quickly` hangs on Windows, check that the child is created with `asyncio.create_subprocess_exec` under the default Proactor loop (do not switch loop policies).

- [ ] **Step 5: Commit**

```bash
git add src/supervisor.py tests/test_supervisor.py
git commit -m "ai_agent: supervisor spawns one child per agent file, relays output, restarts with backoff

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Launcher, README and manual smoke check

**Files:**
- Modify: `run.bat`
- Modify: `README.md`

**Interfaces:**
- Consumes: `python -m src.supervisor`, the `agents.example/` files.

- [ ] **Step 1: Point `run.bat` at the supervisor**

Replace the header comment block (lines 2-12) with:

```bat
REM ai_agent dev launcher - starts every agent in agents\*.json (seeded
REM from agents.example\ on first run) under src.supervisor, one child
REM process per agent on that file's port.
REM
REM To run a single instance the old way instead (provider from env vars,
REM no agent files), skip this bat and run:
REM   set AI_AGENT_PROVIDER=openai
REM   set AI_AGENT_PORT=9101
REM   .venv_ai_agent\Scripts\python -m src.server --gateway openrouter
```

Keep the `REM LABEL:` line. Change `REM DESCRIPTION:` to `REM DESCRIPTION: Starts every configured AI agent (agents\*.json) - each talks to mcp_server as an MCP client and serves MCP to ember_api/chat_app.` Delete the two `if not defined AI_AGENT_... set ...` lines. Change `py -m src.server %*` to `py -m src.supervisor`. Change the stop message to `echo  ai_agent supervisor stopped.`

- [ ] **Step 2: Document agents in `README.md`**

Read `README.md` first. Then:
- replace the "Run an instance" steps and the "run a second instance" paragraph with a section **"Agents"** that covers:
  - `agents/<id>.json` and the field table from the spec's "Fields" section (copy it verbatim)
  - the two shipped examples
  - "exactly one `entry: true`"
  - that `run.bat` starts all agents
- add a section **"Orchestrator and routing"** covering:
  - roster per turn
  - `delegate_to_agent` only for orchestrators
  - `routing.laya` / `top_k` / `allow_auto` / `min_score`
  - `pip install -e ".[laya]"`
- add a section **"Usage log"** covering:
  - `data/usage/YYYY-MM-DD.<agent id>.jsonl`
  - the row fields
  - `AI_AGENT_USAGE_DIR`
- replace the **Limitation** paragraph about same-provider instances overwriting each other with one sentence: agent files give each instance its own id, so any number of same-provider agents can run side by side.
- in the role section, add: an agent file's `persona` replaces the role; `AI_AGENT_ROLE` / `--role` apply only to an instance started without an agent file.

- [ ] **Step 3: Full suite**

Run: `.venv_ai_agent\Scripts\python -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Manual smoke check (no LLM call needed)**

Run: `.venv_ai_agent\Scripts\python -c "from src import agent_spec; agent_spec.ensure_agents_dir(); print([s.id for s in agent_spec.load_dir(agent_spec.AGENTS_DIR)])"`
Expected: `['claude-agent', 'openai-agent']` (or the user's own files if `agents/` already existed).

Do **not** start the real supervisor here. It needs mcp_server and API keys, and the user tests live runs manually (see memory: skip live verification).

- [ ] **Step 5: Commit**

```bash
git add run.bat README.md
git commit -m "ai_agent: run.bat starts the supervisor; document agents, routing and the usage log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Record the planning deviations in the spec

**Files:**
- Modify: `../docs/superpowers/specs/2026-10-04-ai-agent-multi-agent-design.md`

- [ ] **Step 1: Edit the spec**

- In "Live agent activity events", change the forwarding bullet to say a specialist's `step_*` events pass through and its `usage` events are dropped (final usage still arrives in `agent_usage`), and that `token_reset` becomes `agent_token` with `"reset": true`.
- In "Laya routing", replace the "Score threshold" bullet with the decided behavior: `routing.min_score` (signed cosine, -1..1, default unset), skipped when Laya returns no scores (only one specialist).
- In the Fields table, add the `routing.min_score` row.
- In "Usage log", change the serialization note to a `threading.Lock` around a worker-thread write.
- In "Registry" or "Orchestrator", add: an instance started from env vars is an orchestrator, and the roster never includes the agent itself.

- [ ] **Step 2: Commit**

```bash
git add ../docs/superpowers/specs/2026-10-04-ai-agent-multi-agent-design.md
git commit -m "docs: record phase 1 planning decisions in the ai_agent multi-agent spec

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
