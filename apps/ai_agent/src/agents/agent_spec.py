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
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"

PROVIDERS = ("anthropic", "openai", "laya")
REASONING_EFFORTS = ("off", "low", "medium", "high")
# Model strength, weakest to strongest. Fixed so min_tier/max_tier can be
# compared and the orchestrator sees one vocabulary across every gateway.
TIERS = ("light", "standard", "heavy")
# The gateway each provider uses when a file names none - pinned in the env
# so .env's AI_AGENT_GATEWAY cannot silently re-point the agent.
_DEFAULT_GATEWAY = {"anthropic": "claude", "openai": "gpt", "laya": "local"}
# Same mapping as agent_registry.agent_id_for (kept here so this module
# stays import-free): the legacy ids predate the "claude" -> "anthropic" rename.
_LEGACY_ID_PREFIX = {"anthropic": "claude", "openai": "openai"}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_TOP_KEYS = {"label", "port", "url", "enabled", "entry", "llm", "identity", "persona", "instructions", "focus", "tools", "orchestrator", "routing"}
_LLM_KEYS = {"provider", "gateway", "model", "temperature", "reasoning_effort", "max_tokens", "max_tool_rounds", "min_tier", "max_tier", "max_effort"}
_TOOLS_KEYS = {"allow", "deny"}
_ROUTING_KEYS = {"laya", "top_k", "allow_auto", "min_score"}


def default_gateway(provider: str) -> str | None:
    """The gateway a provider uses when an agent names none."""
    return _DEFAULT_GATEWAY.get(provider)


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
    min_tier: str | None = None
    max_tier: str | None = None
    # Highest reasoning effort a delegating orchestrator may request of this
    # agent; None = no cap. Its own reasoning_effort is never above it.
    max_effort: str | None = None


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
    # Reasoning efforts it accepts from a delegator, weakest first.
    efforts: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    id: str
    label: str
    port: int
    llm: LlmSpec
    enabled: bool = True
    entry: bool = False
    # "" = the shared identity template (prompt_config); else replaces the identity line.
    identity: str = ""
    persona: str = ""
    # "" = agent_roles.DEFAULT_INSTRUCTIONS.
    instructions: str = ""
    focus: str = ""
    tools: ToolScope = field(default_factory=ToolScope)
    orchestrator: bool = False
    routing: RoutingSpec = field(default_factory=RoutingSpec)
    # Address peers and ember_api reach this agent at (what it registers);
    # None = derived from the host and port it listens on.
    url: str | None = None
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
            if default is not None:
                raise self.fail(f"{prefix}{key}", f"must be a whole number from {low} to {high}, not null")
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

    def tier(self, data: dict[str, Any], key: str, prefix: str = "") -> str | None:
        value = data.get(key)
        if value is None:
            return None
        if value not in TIERS:
            raise self.fail(f"{prefix}{key}", f"must be one of: {', '.join(TIERS)}")
        return value


def _agent_url(check: _Checker, data: dict[str, Any]) -> str | None:
    """`url`: the http(s) address this agent registers under. A bare origin
    gets /mcp, the path ai_agent serves."""
    value = check.text(data, "url", None)
    if not value:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise check.fail("url", "must be an http(s) address like http://10.0.0.5:9103/mcp")
    try:
        parts.port  # noqa: B018 - raises ValueError for a port out of range
    except ValueError:
        raise check.fail("url", "has an invalid port") from None
    path = parts.path.rstrip("/") or "/mcp"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


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
    if port is None:
        raise check.fail("port", "must be a whole number from 1 to 65535, not null")
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
    max_effort = llm_data.get("max_effort")
    if max_effort is not None and max_effort not in REASONING_EFFORTS:
        raise check.fail("llm.max_effort", f"must be one of: {', '.join(REASONING_EFFORTS)}")
    if max_effort is not None and REASONING_EFFORTS.index(effort) > REASONING_EFFORTS.index(max_effort):
        raise check.fail("llm.reasoning_effort", f"{effort!r} is above llm.max_effort {max_effort!r}")
    min_tier = check.tier(llm_data, "min_tier", "llm.")
    max_tier = check.tier(llm_data, "max_tier", "llm.")
    if min_tier and max_tier and TIERS.index(min_tier) > TIERS.index(max_tier):
        raise check.fail("llm.min_tier", f"{min_tier!r} is stronger than llm.max_tier {max_tier!r}")
    llm = LlmSpec(
        provider=provider,
        gateway=check.text(llm_data, "gateway", None, "llm.") or None,
        model=check.text(llm_data, "model", None, "llm.") or None,
        temperature=check.number(llm_data, "temperature", 0.0, 2.0, "llm."),
        reasoning_effort=effort,
        max_tokens=check.integer(llm_data, "max_tokens", None, 1, 1_000_000, "llm."),
        max_tool_rounds=check.integer(llm_data, "max_tool_rounds", None, 1, 100, "llm."),
        min_tier=min_tier,
        max_tier=max_tier,
        max_effort=max_effort,
    )

    tools_data = check.section(data, "tools")
    check.keys(tools_data, _TOOLS_KEYS, "tools.")
    tools = ToolScope(allow=check.globs(tools_data, "allow"), deny=check.globs(tools_data, "deny"))

    orchestrator = check.boolean(data, "orchestrator", False)
    if provider == "laya":
        if orchestrator or check.boolean(data, "entry", False):
            raise check.fail("llm.provider", "Laya triage must be a specialist, not an entry agent or orchestrator")
        if llm.gateway not in (None, "local"):
            raise check.fail("llm.gateway", "Laya triage runs locally; cloud gateways are not supported")
        if llm.model not in (None, "convaiinnovations/laya"):
            raise check.fail("llm.model", "Laya triage only supports convaiinnovations/laya")
        if any(key in llm_data for key in ("temperature", "max_tokens", "max_tool_rounds", "min_tier", "max_tier", "max_effort")) or effort != "off":
            raise check.fail("llm", "Laya triage does not accept generation or tool-loop settings")
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
        url=_agent_url(check, data),
        label=check.text(data, "label", None) or agent_id,
        port=port,
        llm=llm,
        enabled=check.boolean(data, "enabled", True),
        entry=check.boolean(data, "entry", False),
        identity=check.text(data, "identity", "") or "",
        persona=check.text(data, "persona", "") or "",
        instructions=check.text(data, "instructions", "") or "",
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
        raise AgentSpecError(f"{directory}: no agent files found (create <id>.json)")
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
    still gets delegate_to_agent."""
    provider = os.getenv("AI_AGENT_PROVIDER") or ""
    raw_port = os.getenv("AI_AGENT_PORT", "9100")
    try:
        port = int(raw_port)
    except ValueError:
        raise AgentSpecError(f"AI_AGENT_PORT must be a whole number from 1 to 65535 (got {raw_port!r})") from None
    return AgentSpec(
        id=f"{_LEGACY_ID_PREFIX.get(provider, provider)}-agent",
        label="",
        port=port,
        llm=LlmSpec(
            provider=provider,
            gateway=os.getenv("AI_AGENT_GATEWAY") or None,
            model=os.getenv("AI_AGENT_MODEL") or None,
        ),
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
    .env, which agent_config loads with setdefault."""
    os.environ["AI_AGENT_PROVIDER"] = spec.llm.provider
    os.environ["AI_AGENT_GATEWAY"] = spec.llm.gateway or _DEFAULT_GATEWAY[spec.llm.provider]
    # "" (not unset): agent_config reads `os.getenv("AI_AGENT_MODEL") or None`,
    # and an existing key stops .env's setdefault from filling it.
    os.environ["AI_AGENT_MODEL"] = spec.llm.model or ""
    os.environ["AI_AGENT_PORT"] = str(spec.port)
