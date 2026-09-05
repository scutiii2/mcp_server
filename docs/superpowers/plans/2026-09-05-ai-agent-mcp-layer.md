# ai_agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a new standalone `ai_agent` project (an MCP server to `chat_app`, an MCP client to `mcp_server`, hard-pinned to one LLM provider+model) and migrate `chat_app`'s Chat page onto it, replacing its in-process provider+tool-loop.

**Architecture:** `chat_app` (MCP client) -> `ai_agent` (MCP server + MCP client) -> `mcp_server` (MCP server). `ai_agent` is built by copying and adapting two existing repo templates: `mcp_server_ext` (server side) and `mcp_client_template` (client side, talking to `mcp_server`). `chat_app`'s existing `services/llm/` provider code is copied into `ai_agent` and deleted from `chat_app`. Slash commands and the extension/capability admin surface are untouched — `chat_app` keeps talking to `mcp_server` directly for those.

**Tech Stack:** Python >=3.11, `mcp==1.28.0` SDK, `anthropic`, `openai`, `python-dotenv`, FastMCP (`mcp.server.fastmcp`), Flask (chat_app side, unchanged).

**Spec:** [`docs/superpowers/specs/2026-09-04-ai-agent-mcp-layer-design.md`](../specs/2026-09-04-ai-agent-mcp-layer-design.md)

## Global Constraints

- This slice ports **Claude and OpenAI only** — Ollama support is explicitly deferred (per user decision during planning); do not add an `ollama_provider.py` copy in this plan.
- **No automated tests are written in this plan.** Per the user's explicit preference, every task ends with a **manual verification** step (exact commands + expected output) instead of a pytest cycle. Do not add `tests/` directories, pytest config, or test dependencies to `ai_agent`.
- `ai_agent` is hard-pinned to one provider + one model per instance via `AI_AGENT_PROVIDER`/`AI_AGENT_MODEL` env vars — no per-request provider/model choice, no cross-provider "automatic" fallback inside `ai_agent`.
- No change to `mcp_server` itself, `chat_app`'s slash-command path (`services/commands.py`), or its extension/capability admin routes (`services/mcp_client.py`'s `fetch_extensions`/`add_extension`/`remove_extension`/`fetch_capabilities`/`set_capability_enabled`) — these keep talking to `mcp_server` directly, unchanged.
- `mcp_server` runs at `http://127.0.0.1:8010/mcp` by default (confirmed: `mcp_server/src/config.py`'s `MCP_PORT` default is `8010`) — every example command below assumes it's already running via `run_mcp.bat` from the repo root.
- Commit after every task, following this repo's existing message style (see recent `git log`). End every commit message with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

## Task 1: Scaffold the `ai_agent` project

**Files:**
- Create: `ai_agent/pyproject.toml`
- Create: `ai_agent/src/__init__.py`
- Create: `ai_agent/src/llm/__init__.py`
- Create: `ai_agent/configs/config_servers.json`
- Create: `ai_agent/secrets/secret_llm.env.example`
- Modify: `.gitignore` (repo root)

**Interfaces:**
- Produces: an installable `ai_agent` package (`src.*` importable once its venv is active), and the two config files every later task's code reads (`ai_agent/configs/config_servers.json` for `src/mcp_upstream.py`, Task 3; `ai_agent/secrets/secret_llm.env` for `src/agent_config.py`, Task 6).

- [ ] **Step 1: Create the directory structure and empty package markers**

```
ai_agent/
ai_agent/src/
ai_agent/src/llm/
ai_agent/configs/
ai_agent/secrets/
```

`ai_agent/src/__init__.py` and `ai_agent/src/llm/__init__.py` are both empty files (matching `mcp_server_ext/src/__init__.py` and `mcp_client_template/src/__init__.py`, which are also empty).

- [ ] **Step 2: Write `ai_agent/pyproject.toml`**

```toml
[project]
name = "ai-agent"
version = "0.1.0"
description = "Standalone MCP agent: one pinned LLM provider+model, talking to mcp_server as an MCP client while exposing itself as an MCP server to chat_app"
requires-python = ">=3.11"
dependencies = [
    "mcp==1.28.0",
    "anthropic>=0.121.0",
    "openai>=2.43.0",
    "python-dotenv>=1.0",
]

[project.scripts]
ai-agent = "src.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]
```

- [ ] **Step 3: Write `ai_agent/configs/config_servers.json`**

This is the one upstream `ai_agent` connects to as an MCP client — `mcp_server` itself, matching `mcp_client_template`'s `config_servers.json` shape (`src/config.py`'s `ServerConfig`: `label`, `transport`, `url` are required for an `http` entry). Not gitignored — a localhost URL is not sensitive, same treatment as `mcp_server`'s own `config_extensions.json`.

```json
{
  "main": {
    "label": "mcp_server",
    "description": "This repo's own MCP tool server.",
    "transport": "http",
    "url": "http://127.0.0.1:8010/mcp"
  }
}
```

- [ ] **Step 4: Write `ai_agent/secrets/secret_llm.env.example`**

```
# Copy to secret_llm.env and fill in real values. secret_llm.env itself
# is gitignored - never commit real API keys.

# Which LLM this ai_agent instance is pinned to. One of: claude, openai.
AI_AGENT_PROVIDER=claude

# Optional - blank uses that provider's own default model (see
# src/llm/claude_provider.py / openai_provider.py's DEFAULT_MODEL).
AI_AGENT_MODEL=

# Only the key for whichever AI_AGENT_PROVIDER you picked above is
# actually required; the other can stay blank.
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

- [ ] **Step 5: Add `ai_agent`'s secrets to the root `.gitignore`**

Edit `.gitignore` (repo root), adding this block after the existing `mcp_server` secrets section (after the line `!/mcp_server/src/secrets/README.md`):

```gitignore

# ai_agent's real API keys / pinned-provider selection, mirroring
# mcp_server's secret_*.env treatment - only the .example is committed.
/ai_agent/secrets/*
!/ai_agent/secrets/*.example
```

- [ ] **Step 6: Manual verification — dependencies install cleanly**

```powershell
python -m venv venv_ai_agent
.\venv_ai_agent\Scripts\Activate.ps1
cd ai_agent
pip install -e .
python -c "import mcp, anthropic, openai, dotenv; print('ok')"
cd ..
```

Expected: `pip install -e .` completes with no errors, and the final line prints `ok`. Leave `venv_ai_agent` activated for the following tasks, or reactivate it (`.\venv_ai_agent\Scripts\Activate.ps1`) at the start of each later task's verification step.

- [ ] **Step 7: Commit**

```bash
git add ai_agent/pyproject.toml ai_agent/src/__init__.py ai_agent/src/llm/__init__.py ai_agent/configs/config_servers.json ai_agent/secrets/secret_llm.env.example .gitignore
git commit -m "$(cat <<'EOF'
Scaffold ai_agent project

New standalone project: an MCP agent that will sit between chat_app and
mcp_server, hard-pinned to one LLM provider+model per instance. This
commit is the empty scaffold (dependencies, config, secrets template)
before any of its own code exists.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Copy `mcp_client_template`'s client code into `ai_agent`

**Files:**
- Create: `ai_agent/src/config.py` (copy of `mcp_client_template/src/config.py`, unchanged)
- Create: `ai_agent/src/transports.py` (copy of `mcp_client_template/src/transports.py`, unchanged)
- Create: `ai_agent/src/registry.py` (copy of `mcp_client_template/src/registry.py`, unchanged)
- Create: `ai_agent/src/sync_wrapper.py` (copy of `mcp_client_template/src/sync_wrapper.py`, unchanged)

**Interfaces:**
- Produces: `src.sync_wrapper.SyncMcpClient` (`.connect_all(config_path)`, `.list_tools()`, `.call_tool(name, arguments)`, `.close()`) — this is what Task 3's `mcp_upstream.py` wraps.

These four files are copied **verbatim, with zero edits** — they only import from each other via `src.config`/`src.transports`/`src.registry`, which resolve correctly once copied into `ai_agent/src/` (same package-relative shape as the original template). This is exactly what `mcp_client_template/README.md`'s own "To build a real client" instructions describe.

- [ ] **Step 1: Copy the four files**

```powershell
Copy-Item mcp_client_template\src\config.py ai_agent\src\config.py
Copy-Item mcp_client_template\src\transports.py ai_agent\src\transports.py
Copy-Item mcp_client_template\src\registry.py ai_agent\src\registry.py
Copy-Item mcp_client_template\src\sync_wrapper.py ai_agent\src\sync_wrapper.py
```

- [ ] **Step 2: Manual verification — the copied modules import cleanly**

```powershell
.\venv_ai_agent\Scripts\Activate.ps1
cd ai_agent
python -c "from src.registry import McpClientRegistry; from src.sync_wrapper import SyncMcpClient; from src.config import load_servers_config; print('ok')"
cd ..
```

Expected: prints `ok` with no import errors.

- [ ] **Step 3: Commit**

```bash
git add ai_agent/src/config.py ai_agent/src/transports.py ai_agent/src/registry.py ai_agent/src/sync_wrapper.py
git commit -m "$(cat <<'EOF'
Copy mcp_client_template's client code into ai_agent

Verbatim copy (config.py/transports.py/registry.py/sync_wrapper.py) -
this is the MCP-client half of ai_agent, giving it a persistent,
namespaced connection to mcp_server via SyncMcpClient instead of
reconnecting per call.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `ai_agent/src/mcp_upstream.py`

**Files:**
- Create: `ai_agent/src/mcp_upstream.py`

**Interfaces:**
- Consumes: `src.sync_wrapper.SyncMcpClient` (Task 2).
- Produces: `connect() -> None`, `close() -> None`, `list_tools(enabled_extensions: list[str] | None) -> list[mcp.types.Tool]`, `call_tool(name: str, arguments: dict) -> str` — this is the exact shape `claude_provider.py`/`openai_provider.py` (Task 5) import and call, matching `chat_app/src/services/mcp_client.py`'s `list_tools`/`call_tool` signatures today.

`SyncMcpClient`'s underlying `McpClientRegistry` namespaces every tool under its configured server id (`registry.py`'s `NAMESPACE_SEPARATOR = "__"`) — since `config_servers.json` (Task 1) configures exactly one server, `"main"`, every tool name `list_tools()` returns is prefixed `"main__"` (e.g. `"main__request_otp_tool"`, or `"main__myext__sometool"` for a proxied extension tool). `chat_app`'s existing `enabled_extensions` filtering logic (`_tool_is_enabled` in `mcp_client.py`) must be applied to the name **after** stripping that `"main__"` prefix, not the raw namespaced name — otherwise every extension tool's `ext_id` would incorrectly be read as `"main"`.

- [ ] **Step 1: Write `ai_agent/src/mcp_upstream.py`**

```python
"""ai_agent's connection to mcp_server - a thin, sync-friendly wrapper
around mcp_client_template's SyncMcpClient (src/sync_wrapper.py), giving
the copied provider files (src/llm/claude_provider.py,
src/llm/openai_provider.py) the same call_tool(name, args) -> str /
list_tools(enabled_extensions) -> list shape chat_app's own
services/mcp_client.py gives them today.

Connected once at process startup (see server.py's main()) and reused
for every request via SyncMcpClient's own persistent background
connection - not reconnected per call, unlike chat_app's current
mcp_client.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.sync_wrapper import SyncMcpClient

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "config_servers.json"

# The single upstream server id configured in configs/config_servers.json.
# Every tool list_tools() returns is namespaced "main__<tool name>" by
# SyncMcpClient's underlying McpClientRegistry (see registry.py's
# NAMESPACE_SEPARATOR) even though there's only one upstream server today.
_SERVER_ID = "main"
_PREFIX = f"{_SERVER_ID}__"

client = SyncMcpClient()


def connect() -> None:
    client.connect_all(_CONFIG_PATH)


def _tool_is_enabled(name: str, enabled: set[str]) -> bool:
    """Mirrors chat_app's mcp_client._tool_is_enabled, applied to the
    tool's name AFTER stripping this module's own "main__" registry
    prefix - a proxied extension tool arrives as "main__{ext_id}__{tool}",
    mcp_server's own built-ins as "main__{tool}" with no further "__"."""
    ext_id, sep, _ = name.partition("__")
    if not sep:
        return True
    return ext_id in enabled


def list_tools(enabled_extensions: list[str] | None = None) -> list[Any]:
    """Live tool catalog from mcp_server, filtered the same way
    chat_app's mcp_client.list_tools() filters it today - an extension
    tool is only kept when its extension id is in enabled_extensions."""
    tools = client.list_tools()
    enabled = set(enabled_extensions or [])
    result = []
    for tool in tools:
        if not tool.name.startswith(_PREFIX):
            continue
        unprefixed = tool.name[len(_PREFIX):]
        if _tool_is_enabled(unprefixed, enabled):
            result.append(tool)
    return result


def call_tool(name: str, arguments: dict[str, Any]) -> str:
    result = client.call_tool(name, arguments)
    parts = [getattr(block, "text", str(block)) for block in result.content]
    return "\n".join(parts) if parts else "(no output)"


def close() -> None:
    client.close()
```

- [ ] **Step 2: Manual verification — connect to a running `mcp_server` and list its tools**

Make sure `mcp_server` is running first (`run_mcp.bat` from the repo root, in its own window). Then, with `venv_ai_agent` active and `cd ai_agent`:

```powershell
python -c "from src import mcp_upstream; mcp_upstream.connect(); tools = mcp_upstream.list_tools(); print(len(tools), 'tools'); print([t.name for t in tools][:5]); mcp_upstream.close()"
```

Expected: prints a tool count greater than 0, and the first few tool names all start with `main__` (e.g. `main__ping_host`). If this fails with a connection error, confirm `mcp_server` is actually running and reachable at `http://127.0.0.1:8010/mcp` (matches `ai_agent/configs/config_servers.json`).

- [ ] **Step 3: Commit**

```bash
git add ai_agent/src/mcp_upstream.py
git commit -m "$(cat <<'EOF'
Add ai_agent's mcp_upstream module

Wraps SyncMcpClient with the list_tools/call_tool shape ai_agent's
copied provider files expect, and strips the registry's own "main__"
namespace prefix before applying enabled_extensions filtering.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `ai_agent/src/llm/base.py` and `cooldown.py`

**Files:**
- Create: `ai_agent/src/llm/base.py` (trimmed copy of `chat_app/src/services/llm/base.py`)
- Create: `ai_agent/src/llm/cooldown.py` (verbatim copy of `chat_app/src/services/llm/cooldown.py`)

**Interfaces:**
- Produces: `SYSTEM_PROMPT: str`, `ChatResult` (fields: `response: str`, `tools_used: list[str]`, `tool_calls: list[ToolCallRecord]`, `provider_id: str`, `model: str`, `total_tokens: int | None`), `ToolCallRecord` (fields: `name: str`, `arguments: dict`, `result: str`) from `base.py`; `start_cooldown(provider_id, seconds)`, `seconds_remaining(provider_id) -> float`, `is_in_cooldown(provider_id) -> bool`, `extract_retry_after_seconds(error) -> float | None`, `DEFAULT_COOLDOWN_SECONDS: float` from `cooldown.py` — both consumed by Task 5's provider files.

`base.py` is **trimmed**, not a verbatim copy: `chat_app`'s version also defines `ProviderSpec`/`ModelOption`/`ModelAvailability`/`ModelAvailabilityCheck`/`CheckModelsFn` — a registry abstraction for routing between several providers per request. `ai_agent` pins exactly one provider per instance (`agent_config.py`, Task 6, imports a provider module directly), so none of that is needed here.

- [ ] **Step 1: Write `ai_agent/src/llm/base.py`**

```python
"""Shared types for ai_agent's LLM providers.

Trimmed from chat_app/src/services/llm/base.py: this project pins one
provider+model per instance (see agent_config.py) rather than routing
between several, so ProviderSpec/ModelOption/ModelAvailability - built
for chat_app's per-request provider dropdown - have no equivalent need
here. ChatResult/ToolCallRecord/SYSTEM_PROMPT carry over unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. Use them to get "
    "real data rather than guessing, and say so plainly when no tool can "
    "answer the question. Confirm with the user before any destructive or "
    "hard-to-reverse action."
)


@dataclass
class ToolCallRecord:
    """One tool invocation's full detail - name, the arguments the model
    supplied, and the result text that went back to it."""

    name: str
    arguments: dict[str, Any]
    result: str


@dataclass
class ChatResult:
    response: str
    tools_used: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    provider_id: str = ""
    model: str = ""
    total_tokens: int | None = None
```

- [ ] **Step 2: Copy `ai_agent/src/llm/cooldown.py` verbatim**

```powershell
Copy-Item chat_app\src\services\llm\cooldown.py ai_agent\src\llm\cooldown.py
```

No edits needed — it has no internal imports (only stdlib `time`).

- [ ] **Step 3: Manual verification**

```powershell
.\venv_ai_agent\Scripts\Activate.ps1
cd ai_agent
python -c "from src.llm.base import SYSTEM_PROMPT, ChatResult, ToolCallRecord; from src.llm import cooldown; r = ChatResult(response='hi'); print(r.response, cooldown.is_in_cooldown('x'))"
cd ..
```

Expected: prints `hi False`.

- [ ] **Step 4: Commit**

```bash
git add ai_agent/src/llm/base.py ai_agent/src/llm/cooldown.py
git commit -m "$(cat <<'EOF'
Add ai_agent's llm base types and cooldown tracking

base.py is trimmed from chat_app's copy (drops the multi-provider
ProviderSpec registry - not needed when one provider is pinned per
instance); cooldown.py is copied verbatim.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add `ai_agent/src/llm/claude_provider.py` and `openai_provider.py`

**Files:**
- Create: `ai_agent/src/llm/claude_provider.py` (adapted copy of `chat_app/src/services/llm/claude_provider.py`)
- Create: `ai_agent/src/llm/openai_provider.py` (adapted copy of `chat_app/src/services/llm/openai_provider.py`)

**Interfaces:**
- Consumes: `src.llm.cooldown` and `src.llm.base.{SYSTEM_PROMPT, ChatResult, ToolCallRecord}` (Task 4); `src.mcp_upstream.{call_tool, list_tools}` (Task 3).
- Produces per module: `PROVIDER_ID: str`, `DEFAULT_MODEL: str`, `has_api_key() -> bool`, `is_available() -> bool`, `run_chat(question, history, model, enabled_extensions) -> ChatResult` — consumed directly by Task 6's `agent_config.py`.

Both files are the **exact same tool-calling loop** as chat_app's originals (the 6-round cap, per-round token accounting, rate-limit cooldown handling — all unchanged). Three changes from the chat_app originals, identical in both files: (1) `src.mcp_upstream` replaces `src.services.mcp_client` as the tool-call source; (2) no `MODELS`/`ModelOption` list or trailing `PROVIDER = ProviderSpec(...)` registration — nothing in `ai_agent` routes between providers, so there's no registry to register into; (3) the default model is a local `DEFAULT_MODEL` constant instead of chat_app's shared `Settings` object.

- [ ] **Step 1: Write `ai_agent/src/llm/claude_provider.py`**

```python
"""Anthropic Messages API provider - pinned by agent_config.py when
AI_AGENT_PROVIDER=claude.

Adapted from chat_app/src/services/llm/claude_provider.py - see this
file's own module docstring vs. that one for exactly what changed
(tool calls go through src.mcp_upstream; no MODELS list or
ProviderSpec registration; DEFAULT_MODEL replaces chat_app's shared
Settings object). The tool-calling loop itself is unchanged.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic, RateLimitError

from src.llm import cooldown
from src.llm.base import SYSTEM_PROMPT, ChatResult, ToolCallRecord
from src.mcp_upstream import call_tool, list_tools


PROVIDER_ID = "claude"

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")
        _client = Anthropic(api_key=api_key)
    return _client


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def is_available() -> bool:
    return has_api_key() and not cooldown.is_in_cooldown(PROVIDER_ID)


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in list_tools(enabled_extensions)
    ]


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
    client = _get_client()
    model_name = model or DEFAULT_MODEL
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    total_tokens = 0

    try:
        for _ in range(6):
            response = client.messages.create(
                model=model_name,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tool_schemas,
            )
            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            if response.stop_reason != "tool_use":
                text = "".join(block.text for block in response.content if block.type == "text")
                return ChatResult(
                    response=text,
                    tools_used=tools_used,
                    tool_calls=tool_calls,
                    provider_id=PROVIDER_ID,
                    model=model_name,
                    total_tokens=total_tokens,
                )

            messages.append({"role": "assistant", "content": response.content})

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append(block.name)
                try:
                    result_text = call_tool(block.name, block.input)
                except Exception as error:
                    result_text = f"Tool '{block.name}' failed: {error}"
                tool_calls.append(ToolCallRecord(name=block.name, arguments=block.input, result=result_text))
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})

            messages.append({"role": "user", "content": tool_results})
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise

    return ChatResult(
        response="Reached maximum tool-call rounds without a final answer.",
        tools_used=tools_used,
        tool_calls=tool_calls,
        provider_id=PROVIDER_ID,
        model=model_name,
        total_tokens=total_tokens,
    )
```

- [ ] **Step 2: Write `ai_agent/src/llm/openai_provider.py`**

```python
"""OpenAI Responses API provider - pinned by agent_config.py when
AI_AGENT_PROVIDER=openai.

Adapted from chat_app/src/services/llm/openai_provider.py - see
claude_provider.py's module docstring for what changed and why.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI, RateLimitError

from src.llm import cooldown
from src.llm.base import SYSTEM_PROMPT, ChatResult, ToolCallRecord
from src.mcp_upstream import call_tool, list_tools


PROVIDER_ID = "openai"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        _client = OpenAI(api_key=api_key)
    return _client


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def is_available() -> bool:
    return has_api_key() and not cooldown.is_in_cooldown(PROVIDER_ID)


def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in list_tools(enabled_extensions)
    ]


def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
    client = _get_client()
    model_name = model or DEFAULT_MODEL
    messages: list[Any] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    total_tokens: int | None = None

    try:
        for _ in range(6):
            response = client.responses.create(
                model=model_name,
                input=messages,
                tools=tool_schemas if tool_schemas else None,
            )
            usage = getattr(response, "usage", None)
            round_tokens = getattr(usage, "total_tokens", None) if usage is not None else None
            if round_tokens is not None:
                total_tokens = (total_tokens or 0) + round_tokens

            function_calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
            if not function_calls:
                return ChatResult(
                    response=response.output_text,
                    tools_used=tools_used,
                    tool_calls=tool_calls,
                    provider_id=PROVIDER_ID,
                    model=model_name,
                    total_tokens=total_tokens,
                )

            messages.extend(response.output)
            for call in function_calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                except Exception:
                    arguments = {}
                tools_used.append(call.name)
                try:
                    result_text = call_tool(call.name, arguments)
                except Exception as error:
                    result_text = f"Tool '{call.name}' failed: {error}"
                tool_calls.append(ToolCallRecord(name=call.name, arguments=arguments, result=result_text))
                messages.append({"type": "function_call_output", "call_id": call.call_id, "output": result_text})
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise

    return ChatResult(
        response="Reached maximum tool-call rounds without a final answer.",
        tools_used=tools_used,
        tool_calls=tool_calls,
        provider_id=PROVIDER_ID,
        model=model_name,
        total_tokens=total_tokens,
    )
```

- [ ] **Step 3: Manual verification — both modules import and report availability correctly**

```powershell
.\venv_ai_agent\Scripts\Activate.ps1
cd ai_agent
python -c "from src.llm import claude_provider, openai_provider; print(claude_provider.PROVIDER_ID, claude_provider.has_api_key()); print(openai_provider.PROVIDER_ID, openai_provider.has_api_key())"
cd ..
```

Expected: prints `claude False` and `openai False` (no API keys are set in your shell's real environment yet — that's expected and correct at this point; Task 6 wires up loading them from `secret_llm.env`). No import errors.

- [ ] **Step 4: Commit**

```bash
git add ai_agent/src/llm/claude_provider.py ai_agent/src/llm/openai_provider.py
git commit -m "$(cat <<'EOF'
Add ai_agent's claude and openai providers

Adapted copies of chat_app's provider files: same 6-round tool-calling
loop, rate-limit cooldown handling, and per-round token accounting,
now calling mcp_upstream instead of chat_app's services.mcp_client and
with no multi-provider registry (this project pins one provider per
instance - see agent_config.py, next task).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add `ai_agent/src/agent_config.py`

**Files:**
- Create: `ai_agent/src/agent_config.py`

**Interfaces:**
- Consumes: `src.llm.claude_provider`, `src.llm.openai_provider` (Task 5), `src.llm.cooldown` (Task 4).
- Produces: `AgentConfigError` (exception class), `PROVIDER_ID: str`, `MODEL: str | None` (module-level, resolved once at import time), `run_chat(question, history, enabled_extensions) -> ChatResult`, `status() -> dict[str, Any]` — consumed by Task 7's `server.py`.

Resolution happens **once, at import time** — a missing/unknown `AI_AGENT_PROVIDER` or a missing API key for the selected provider raises `AgentConfigError` immediately when `ai_agent` starts, not on its first real request. This matches `mcp_client_template`'s own `ConfigError`-on-load convention for `config_servers.json`.

- [ ] **Step 1: Write `ai_agent/src/agent_config.py`**

```python
"""Resolves this ai_agent instance's pinned LLM provider+model, once, at
import time - fails loudly if AI_AGENT_PROVIDER is missing, unknown, or
its API key isn't configured, rather than discovering that on the first
real request.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from src.llm import claude_provider, cooldown, openai_provider
from src.llm.base import ChatResult

_SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets" / "secret_llm.env"

_PROVIDERS = {
    "claude": claude_provider,
    "openai": openai_provider,
}


class AgentConfigError(Exception):
    """Raised at import time for a missing/unknown AI_AGENT_PROVIDER, or
    a missing API key for the selected provider."""


def _load_secrets_into_environ() -> None:
    for key, value in dotenv_values(_SECRETS_PATH).items():
        if value:
            os.environ.setdefault(key, value)


def _resolve() -> tuple[str, Any]:
    _load_secrets_into_environ()
    provider_id = os.getenv("AI_AGENT_PROVIDER")
    if not provider_id:
        raise AgentConfigError(
            f"AI_AGENT_PROVIDER is not set in {_SECRETS_PATH} - must be one of: {', '.join(sorted(_PROVIDERS))}"
        )
    module = _PROVIDERS.get(provider_id)
    if module is None:
        raise AgentConfigError(
            f"Unknown AI_AGENT_PROVIDER {provider_id!r} - must be one of: {', '.join(sorted(_PROVIDERS))}"
        )
    if not module.has_api_key():
        raise AgentConfigError(
            f"AI_AGENT_PROVIDER is {provider_id!r} but its API key is not configured in {_SECRETS_PATH}"
        )
    return provider_id, module


PROVIDER_ID, _PROVIDER_MODULE = _resolve()
MODEL = os.getenv("AI_AGENT_MODEL") or None


def run_chat(question: str, history: list[dict[str, Any]], enabled_extensions: list[str]) -> ChatResult:
    return _PROVIDER_MODULE.run_chat(question, history, MODEL, enabled_extensions)


def status() -> dict[str, Any]:
    reason = None
    if not _PROVIDER_MODULE.has_api_key():
        reason = "missing_key"
    elif cooldown.is_in_cooldown(PROVIDER_ID):
        reason = "rate_limited"
    return {
        "provider_id": PROVIDER_ID,
        "model": MODEL or _PROVIDER_MODULE.DEFAULT_MODEL,
        "available": _PROVIDER_MODULE.is_available(),
        "reason": reason,
        "cooldown_seconds_remaining": int(cooldown.seconds_remaining(PROVIDER_ID)),
    }
```

- [ ] **Step 2: Manual verification — both the success and failure paths**

First, create the real secrets file and fill in a real Anthropic key (or OpenAI, matching whichever you want to test with):

```powershell
Copy-Item ai_agent\secrets\secret_llm.env.example ai_agent\secrets\secret_llm.env
notepad ai_agent\secrets\secret_llm.env
```

Set `AI_AGENT_PROVIDER=claude` and paste a real `ANTHROPIC_API_KEY=`. Save and close, then:

```powershell
.\venv_ai_agent\Scripts\Activate.ps1
cd ai_agent
python -c "from src import agent_config; print(agent_config.PROVIDER_ID, agent_config.MODEL, agent_config.status())"
cd ..
```

Expected: prints `claude None {'provider_id': 'claude', 'model': 'claude-sonnet-5', 'available': True, 'reason': None, 'cooldown_seconds_remaining': 0}`.

Now test the fail-loud path — temporarily rename the provider to something invalid:

```powershell
cd ai_agent
(Get-Content secrets\secret_llm.env) -replace 'AI_AGENT_PROVIDER=claude', 'AI_AGENT_PROVIDER=bogus' | Set-Content secrets\secret_llm.env
python -c "from src import agent_config"
```

Expected: raises `AgentConfigError: Unknown AI_AGENT_PROVIDER 'bogus' - must be one of: claude, openai` (not a bare traceback from somewhere else, and not a silent fallback). Then restore it:

```powershell
(Get-Content secrets\secret_llm.env) -replace 'AI_AGENT_PROVIDER=bogus', 'AI_AGENT_PROVIDER=claude' | Set-Content secrets\secret_llm.env
cd ..
```

- [ ] **Step 3: Commit**

```bash
git add ai_agent/src/agent_config.py
git commit -m "$(cat <<'EOF'
Add ai_agent's provider+model resolution

Reads AI_AGENT_PROVIDER/AI_AGENT_MODEL from secret_llm.env once at
import time and resolves directly to that one provider module - no
registry, no fallback. Fails loudly (AgentConfigError) for a missing,
unknown, or unconfigured provider rather than on first request.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

*(`secrets/secret_llm.env` itself is gitignored per Task 1 — nothing to add there.)*

---

## Task 7: Add `ai_agent/src/server.py` and `ai_agent/README.md` — seam checkpoint

**Files:**
- Create: `ai_agent/src/server.py`
- Create: `ai_agent/README.md`
- Create: `run_ai_agent.bat` (repo root)
- Modify: `run_all.bat` (repo root)

**Interfaces:**
- Consumes: `src.agent_config` (Task 6), `src.mcp_upstream` (Task 3).
- Produces: a running MCP server exposing two tools, `ask` and `status`, at `http://127.0.0.1:9100/mcp` by default — this is the interface Task 9 (`chat_app`'s `ai_agent_client.py`) calls into.

This is the checkpoint we agreed on: verify the `ask`/`status` seam works end-to-end **before** touching `chat_app`. A bug in the MCP tool contract here is far cheaper to find now than after `chat_app`'s side is also rewired.

- [ ] **Step 1: Write `ai_agent/src/server.py`**

```python
"""ai_agent entry point - a FastMCP server exposing ask/status tools to
chat_app, backed by one pinned LLM provider (agent_config.py) that
itself talks to mcp_server as an MCP client (mcp_upstream.py).

Run with:
    python -m src.server
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from src import agent_config, mcp_upstream

HOST = os.getenv("AI_AGENT_HOST", "127.0.0.1")
PORT = int(os.getenv("AI_AGENT_PORT", "9100"))

mcp = FastMCP(
    name=f"ai-agent-{agent_config.PROVIDER_ID}",
    instructions=(
        f"Chat agent backed by {agent_config.PROVIDER_ID} "
        f"({agent_config.MODEL or 'provider default'}), with tool access to "
        "mcp_server. Call ask() with a question."
    ),
    host=HOST,
    port=PORT,
)


@mcp.tool()
def ask(
    question: str,
    history: list[dict[str, Any]] | None = None,
    enabled_extensions: list[str] | None = None,
) -> dict[str, Any]:
    """Ask this agent a question. Runs its own tool-calling loop against
    mcp_server (up to 6 rounds) before returning a final answer."""
    result = agent_config.run_chat(question, history or [], enabled_extensions or [])
    return {
        "response": result.response,
        "tools_used": result.tools_used,
        "tool_calls": [
            {"name": c.name, "arguments": c.arguments, "result": c.result} for c in result.tool_calls
        ],
        "total_tokens": result.total_tokens,
        "provider_id": result.provider_id,
        "model": result.model,
    }


@mcp.tool()
def status() -> dict[str, Any]:
    """Live availability of this agent's pinned provider."""
    return agent_config.status()


def main() -> None:
    mcp_upstream.connect()
    try:
        mcp.run(transport="streamable-http")
    finally:
        mcp_upstream.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `ai_agent/README.md`**

```markdown
# ai_agent

A standalone MCP agent, hard-pinned to one LLM provider+model, sitting
between `chat_app` and `mcp_server`:

```
chat_app  --(MCP: ask/status)-->  ai_agent  --(MCP, persistent)-->  mcp_server
```

It is both an MCP *server* (to `chat_app`, exposing `ask`/`status`) and
an MCP *client* (to `mcp_server`, via a persistent connection - see
`src/mcp_upstream.py`).

## Setup

1. From `ai_agent/`, install dependencies:

   ```
   pip install -e .
   ```

2. Copy `secrets/secret_llm.env.example` to `secrets/secret_llm.env` and
   set `AI_AGENT_PROVIDER` (`claude` or `openai`), optionally
   `AI_AGENT_MODEL`, and the matching API key.

3. Make sure `mcp_server` is running (`run_mcp.bat` from the repo
   root) - `ai_agent/configs/config_servers.json` points at its default
   `http://127.0.0.1:8010/mcp`.

4. Run it:

   ```
   run_ai_agent.bat
   ```

   (from the repo root; activates `venv_ai_agent` and runs `py -m
   src.server`.) Defaults to `http://127.0.0.1:9100/mcp` - override with
   `AI_AGENT_HOST`/`AI_AGENT_PORT`.

## Project layout

- `src/server.py` - FastMCP entry point; `ask`/`status` tools.
- `src/agent_config.py` - resolves the pinned provider+model from
  `secrets/secret_llm.env` once at startup; fails loudly on a bad config.
- `src/llm/` - copied from `chat_app/src/services/llm/` (Claude and
  OpenAI only - see this project's design spec for why Ollama is
  deferred), adapted to call `src/mcp_upstream.py` instead of
  chat_app's own MCP client.
- `src/mcp_upstream.py`, `src/registry.py`, `src/config.py`,
  `src/transports.py`, `src/sync_wrapper.py` - copied from
  `mcp_client_template/` (see that project's README for the general
  client pattern); `mcp_upstream.py` is the only one adapted for this
  project's specific single-upstream, enabled-extensions-filtered use.

See
[`docs/superpowers/specs/2026-09-04-ai-agent-mcp-layer-design.md`](../docs/superpowers/specs/2026-09-04-ai-agent-mcp-layer-design.md)
for the full design rationale.
```

- [ ] **Step 3: Write `run_ai_agent.bat`** (repo root, mirroring `run_mcp.bat`/`run_chat.bat`)

```bat
@echo off
REM Activate the virtual environment
call .\venv_ai_agent\Scripts\activate

REM Change directory to ai_agent
cd /d "%~dp0ai_agent"

:run
REM Run ai_agent
py -m src.server

echo.
echo ----------------------------------------
echo  ai_agent stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
```

- [ ] **Step 4: Add ai_agent to `run_all.bat`**

Edit `run_all.bat`, adding this after the existing `start "Chat App" ...` line:

```bat

start "AI Agent" cmd /k call "%~dp0run_ai_agent.bat"
```

- [ ] **Step 5: Manual verification — the full seam, standalone (no chat_app involved yet)**

With `mcp_server` already running (`run_mcp.bat`) and `secrets/secret_llm.env` filled in (Task 6):

```powershell
run_ai_agent.bat
```

In a **second** terminal, with `venv_ai_agent` active, write and run a small throwaway test script:

```powershell
.\venv_ai_agent\Scripts\Activate.ps1
```

Create `ai_agent\manual_test_ask.py`:

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main() -> None:
    async with streamablehttp_client("http://127.0.0.1:9100/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            status = await session.call_tool("status", {})
            print("status:", status.structuredContent)

            result = await session.call_tool("ask", {"question": "Say hello in exactly three words.", "history": []})
            print("isError:", result.isError)
            print("ask:", result.structuredContent)


asyncio.run(main())
```

Run it:

```powershell
python ai_agent\manual_test_ask.py
```

Expected:
- `status:` line shows `{'provider_id': 'claude', 'model': 'claude-sonnet-5', 'available': True, 'reason': None, 'cooldown_seconds_remaining': 0}` (or your chosen provider/model).
- `isError: False`.
- `ask:` line shows a dict with a real three-word `response`, `tools_used: []` (this particular question needs no tools), `total_tokens` a positive number, and `provider_id`/`model` matching what `status` reported.

Then try a question that should trigger a real `mcp_server` tool call (pick one you know `mcp_server` exposes, e.g. a host-health or ping tool) and confirm `tools_used`/`tool_calls` in the output are non-empty and `tool_calls[0]["name"]` starts with `main__`.

If this works, delete the throwaway script (`Remove-Item ai_agent\manual_test_ask.py`) — it isn't part of the committed project.

- [ ] **Step 6: Commit**

```bash
git add ai_agent/src/server.py ai_agent/README.md run_ai_agent.bat run_all.bat
git commit -m "$(cat <<'EOF'
Add ai_agent's server entry point

FastMCP server exposing ask/status tools, connecting to mcp_server via
mcp_upstream at startup. This is the seam chat_app will talk to next -
verified standalone (a raw MCP client script) before any chat_app
changes, per the plan.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `chat_app` — add the agent registry

**Files:**
- Create: `chat_app/src/services/agent_registry.py`
- Create: `chat_app/src/configs/config_agents.json`

**Interfaces:**
- Produces: `list_agent_ids() -> list[str]`, `get_agent(agent_id: str) -> dict[str, str] | None`, `all_agents() -> list[dict[str, str]]` (each dict: `{"id", "label", "url"}`) — consumed by Task 10's rewired `chat_api()`/`providers_api()`.

Same role as `chat_app`'s existing `config_chat.json` (a committed, non-secret, deployment-editable list) — adding a second/third agent later is just another entry here plus a restart.

- [ ] **Step 1: Write `chat_app/src/configs/config_agents.json`**

```json
{
  "agents": [
    {
      "id": "claude-agent",
      "label": "Claude Agent",
      "url": "http://127.0.0.1:9100/mcp"
    }
  ]
}
```

(`"claude-agent"`/`"Claude Agent"` assume Task 6's `secret_llm.env` was set to `AI_AGENT_PROVIDER=claude` — adjust the `id`/`label` to match whichever provider you actually configured `ai_agent` with.)

- [ ] **Step 2: Write `chat_app/src/services/agent_registry.py`**

```python
"""Configured ai_agent instances chat_app can send chat questions to -
read once at import time from src/configs/config_agents.json, the same
way services/llm/app_config.py read config_chat.json before this
project's Chat page migrated onto ai_agent.
"""

from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "config_agents.json"


def _load() -> list[dict[str, str]]:
    if not _CONFIG_PATH.exists():
        return []
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("agents", [])


_AGENTS = _load()
_AGENTS_BY_ID = {agent["id"]: agent for agent in _AGENTS}


def list_agent_ids() -> list[str]:
    return [agent["id"] for agent in _AGENTS]


def get_agent(agent_id: str) -> dict[str, str] | None:
    return _AGENTS_BY_ID.get(agent_id)


def all_agents() -> list[dict[str, str]]:
    return list(_AGENTS)
```

- [ ] **Step 3: Manual verification**

```powershell
.\venv_chat\Scripts\Activate.ps1
cd chat_app
python -c "from src.services import agent_registry; print(agent_registry.all_agents()); print(agent_registry.get_agent('claude-agent')); print(agent_registry.get_agent('nope'))"
cd ..
```

Expected: prints the one configured agent dict twice (second line — the direct lookup by id), then `None` for the unknown id.

- [ ] **Step 4: Commit**

```bash
git add chat_app/src/services/agent_registry.py chat_app/src/configs/config_agents.json
git commit -m "$(cat <<'EOF'
Add chat_app's agent registry

Reads which ai_agent instances chat_app can talk to from the new
config_agents.json - the dropdown data source once chat_api() is
rewired onto ai_agent (next tasks).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

*(This is a chat_app-side task — commit inside `chat_app`'s own nested git repo, not the outer one: run these `git`/`add`/`commit` commands with your working directory at `chat_app/`, exactly as chat_app's other commits already are.)*

---

## Task 9: `chat_app` — add `ai_agent_client.py`

**Files:**
- Create: `chat_app/src/services/ai_agent_client.py`

**Interfaces:**
- Produces: `AgentToolError` (exception class — an agent-reported clean error, e.g. rate-limited), `ask(url, question, history, enabled_extensions) -> dict[str, Any]`, `status(url) -> dict[str, Any]` — consumed by Task 10's rewired `chat_api()`/`providers_api()`.

Mirrors `chat_app/src/services/mcp_client.py`'s own connect-per-call pattern (`asyncio.run(...)` around a fresh `streamablehttp_client`/`ClientSession`) — this module is scoped to calling `ai_agent`'s two specific tools, not a generic MCP client. A tool-level error inside `ai_agent` (e.g. its pinned provider is rate-limited) comes back as a normal `CallToolResult` with `isError=True`, not a raised exception — confirmed against this repo's own `mcp_server/tests/test_extensions.py`, which asserts on `.isError` the same way. `ask()`/`status()` convert that into an `AgentToolError` so `chat_api()` can tell "the agent gave a clean, safe-to-show error" apart from "something else broke" (an unreachable agent, a network failure) exactly the way it distinguishes `ValueError` from bare `Exception` today.

- [ ] **Step 1: Write `chat_app/src/services/ai_agent_client.py`**

```python
"""MCP client for chat_app's configured ai_agent(s) - the LLM Q&A path
only. Slash commands and admin/extension/capability management still go
through services/mcp_client.py directly to mcp_server, unchanged; this
module is used only by chat_api()'s non-command branch and by
providers_api()'s live status poll.

One connection per call, like services/mcp_client.py today - not a
persistent connection, matching this project's per-request Flask model.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class AgentToolError(Exception):
    """Raised when the agent itself reports a tool-call error (isError on
    the MCP result) - e.g. its pinned provider is rate-limited. Distinct
    from a bare connection/transport failure, which propagates as
    whatever exception the mcp SDK itself raises."""


async def _call_tool(url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            if result.isError:
                parts = [getattr(block, "text", str(block)) for block in result.content]
                raise AgentToolError("\n".join(parts) if parts else f"{name} failed")
            return result.structuredContent or {}


def ask(url: str, question: str, history: list[dict[str, Any]], enabled_extensions: list[str]) -> dict[str, Any]:
    return asyncio.run(
        _call_tool(url, "ask", {"question": question, "history": history, "enabled_extensions": enabled_extensions})
    )


def status(url: str) -> dict[str, Any]:
    return asyncio.run(_call_tool(url, "status", {}))
```

- [ ] **Step 2: Manual verification — call the running `ai_agent` through this module**

With `mcp_server` and `ai_agent` both running (from Task 7's verification):

```powershell
.\venv_chat\Scripts\Activate.ps1
cd chat_app
python -c "from src.services import ai_agent_client; print(ai_agent_client.status('http://127.0.0.1:9100/mcp')); print(ai_agent_client.ask('http://127.0.0.1:9100/mcp', 'Say hello in exactly three words.', [], []))"
cd ..
```

Expected: the `status(...)` dict prints first, then the `ask(...)` dict with a real three-word response — same shape you already confirmed in Task 7's `manual_test_ask.py`, now reached through the module `chat_api()` will actually use.

- [ ] **Step 3: Commit**

```bash
git add chat_app/src/services/ai_agent_client.py
git commit -m "$(cat <<'EOF'
Add chat_app's ai_agent_client

MCP client for the ask/status tools ai_agent exposes - the seam
chat_api() will call into instead of router.run_chat() (next task). A
tool-level error from the agent (isError on the MCP result) becomes
AgentToolError, so chat_api() can show it directly the same way it
shows a ValueError from router.run_chat() today.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `chat_app` — rewire `chat_api()`/`providers_api()`, delete `services/llm/`

**Files:**
- Modify: `chat_app/src/pages/Chat/__index__.py`
- Delete: `chat_app/src/services/llm/` (entire directory)
- Delete: `chat_app/tests/test_llm_providers.py`
- Delete: `chat_app/tests/test_llm_settings.py`
- Modify: `chat_app/pyproject.toml`

**Interfaces:**
- Consumes: `src.services.agent_registry` (Task 8), `src.services.ai_agent_client` (Task 9).

- [ ] **Step 1: Edit `chat_app/src/pages/Chat/__index__.py` — imports**

Replace:

```python
from src.services import chats_store, commands, log_service
from src.services.authz import register_permission, require_permission
from src.services.llm import router
from src.services.llm.base import ToolCallRecord
from src.services.llm.settings import settings
from src.services.mcp_client import add_extension, fetch_extensions, remove_extension
```

with:

```python
from src.services import agent_registry, ai_agent_client, chats_store, commands, log_service
from src.services.authz import register_permission, require_permission
from src.services.llm.settings import settings
from src.services.mcp_client import add_extension, fetch_extensions, remove_extension
```

`src.services.llm.settings` still exists after this task — only `base.py`/`router.py`/`claude_provider.py`/`openai_provider.py`/`ollama_provider.py`/`cooldown.py` are deleted in Step 3 below. `settings.mcp_server_url` is still read by `mcp_client.py` for the unchanged slash-command/admin path, and `settings.chats_db_path`/`settings.chat_config_path` are unrelated to the LLM router — check `chat_app/src/services/llm/settings.py` before deleting anything to confirm this, and if a later step in this task would otherwise delete a file `settings.py` itself needs, keep `settings.py` in place explicitly (do not delete the whole `services/llm/` directory blindly — see Step 3's exact file list).

- [ ] **Step 2: Edit `chat_app/src/pages/Chat/__index__.py` — `providers_api()`**

Replace:

```python
@blueprint.route("/api/providers")
@require_permission("chat.access")
def providers_api():
    return jsonify(router.list_providers())
```

with:

```python
@blueprint.route("/api/providers")
@require_permission("chat.access")
def providers_api():
    entries = []
    for agent in agent_registry.all_agents():
        try:
            live = ai_agent_client.status(agent["url"])
            entries.append(
                {
                    "id": agent["id"],
                    "label": agent["label"],
                    "available": bool(live.get("available")),
                    "reason": live.get("reason"),
                    "cooldown_seconds_remaining": int(live.get("cooldown_seconds_remaining") or 0),
                    "models": [],
                    "default_model_id": "",
                    "model": live.get("model"),
                }
            )
        except Exception:  # noqa: BLE001 - an unreachable agent still shows up, greyed out
            entries.append(
                {
                    "id": agent["id"],
                    "label": agent["label"],
                    "available": False,
                    "reason": "unreachable",
                    "cooldown_seconds_remaining": 0,
                    "models": [],
                    "default_model_id": "",
                    "model": None,
                }
            )
    return jsonify(entries)
```

- [ ] **Step 3: Edit `chat_app/src/pages/Chat/__index__.py` — `chat_api()`**

Replace this block:

```python
    start = time.monotonic()
    if is_command:
        # A "/" command is a direct tool call, never the LLM - see
        # docs/superpowers/specs/2026-08-23-chat-slash-commands-design.md.
        response_text = commands.execute_command(question, data.get("enabled_extensions", []))
    else:
        try:
            result = router.run_chat(
                question,
                llm_history,
                data.get("provider"),
                data.get("model"),
                data.get("enabled_extensions", []),
            )
            response_text = result.response
            tools_used = result.tools_used
            tool_calls = result.tool_calls
            provider_id = result.provider_id
            model_used = result.model
            total_tokens = result.total_tokens
        except ValueError as error:
            # Deliberately verbatim: the router raises these with wording meant
            # for whoever is chatting ("Claude is rate-limited right now - try
            # again in 42s, or pick another provider"). No internals, safe to
            # show as-is.
            response_text = f"❌ {error}"
        except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
            log_service.log_error(
                db.session, current_user, source="chat.answer",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            response_text = "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details."
    elapsed_seconds = round(time.monotonic() - start, 1)
```

with:

```python
    start = time.monotonic()
    if is_command:
        # A "/" command is a direct tool call, never the LLM - see
        # docs/superpowers/specs/2026-08-23-chat-slash-commands-design.md.
        response_text = commands.execute_command(question, data.get("enabled_extensions", []))
    else:
        # The dropdown now selects an ai_agent, not an LLM provider - see
        # agent_registry.py. Falls back to the first configured agent when
        # the client didn't send one (e.g. an older cached page).
        requested_agent_id = data.get("provider")
        agent = agent_registry.get_agent(requested_agent_id) if requested_agent_id else None
        if agent is None:
            configured = agent_registry.all_agents()
            agent = configured[0] if configured else None

        if agent is None:
            response_text = "❌ No ai_agent is configured - add one to src/configs/config_agents.json."
        else:
            try:
                result = ai_agent_client.ask(agent["url"], question, llm_history, data.get("enabled_extensions", []))
                response_text = result.get("response", "")
                tools_used = result.get("tools_used", [])
                tool_calls = result.get("tool_calls", [])
                provider_id = result.get("provider_id", "")
                model_used = result.get("model", "")
                total_tokens = result.get("total_tokens")
            except ai_agent_client.AgentToolError as error:
                # Deliberately verbatim: the agent raises these with wording
                # meant for whoever is chatting ("claude is rate-limited
                # right now"). No internals, safe to show as-is.
                response_text = f"❌ {error}"
            except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
                log_service.log_error(
                    db.session, current_user, source="chat.answer",
                    message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
                )
                response_text = "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details."
    elapsed_seconds = round(time.monotonic() - start, 1)
```

Note `tool_calls` is now a **plain list of dicts** (`{"name", "arguments", "result"}`, exactly `ai_agent`'s `ask` tool's own structured shape), not a list of `ToolCallRecord` objects — that type lived in `services/llm/base.py`, which is deleted in Step 5. Find the trace-logging block further down in the same function:

```python
            trace_details = json.dumps(
                {
                    "tool_calls": [
                        {"name": c.name, "arguments": c.arguments, "result": c.result} for c in tool_calls
                    ],
                    "response": response_text,
                    "total_tokens": total_tokens,
                }
            )
```

and simplify it, since `tool_calls` is already in exactly that shape:

```python
            trace_details = json.dumps(
                {
                    "tool_calls": tool_calls,
                    "response": response_text,
                    "total_tokens": total_tokens,
                }
            )
```

- [ ] **Step 4: Check `chat_app/src/services/llm/settings.py` before deleting the directory**

Read `chat_app/src/services/llm/settings.py`. It currently defines `mcp_server_url`, `openai_model`, `claude_model`, `chat_config_path`, `chats_db_path`. `mcp_server_url` and `chats_db_path` are still used (by `mcp_client.py` and `chats_store`-related code respectively via `settings.chats_db_path`/`settings.mcp_server_url`, both still imported per Step 1 above); `openai_model`/`claude_model`/`chat_config_path` become unused once the router/providers are deleted. **Do not delete `settings.py`** — only remove the two now-unused fields (`openai_model`, `claude_model`) and, if nothing else in `chat_app` reads `chat_config_path` (grep for it first — `app_config.py`, deleted in Step 5, was its only other reader), remove that field too. Leave `mcp_server_url` and `chats_db_path` exactly as they are.

- [ ] **Step 5: Delete the rest of `services/llm/`**

```bash
git rm chat_app/src/services/llm/base.py
git rm chat_app/src/services/llm/router.py
git rm chat_app/src/services/llm/cooldown.py
git rm chat_app/src/services/llm/claude_provider.py
git rm chat_app/src/services/llm/openai_provider.py
git rm chat_app/src/services/llm/ollama_provider.py
git rm chat_app/src/services/llm/app_config.py
git rm chat_app/src/services/llm/README.md
git rm chat_app/tests/test_llm_providers.py
git rm chat_app/tests/test_llm_settings.py
```

(`settings.py` and `services/llm/__init__.py`, if present, are **not** in this list — `settings.py` is kept per Step 4; `__init__.py` stays because `settings.py` still lives in the `services/llm` package.)

- [ ] **Step 6: Remove now-unused dependencies from `chat_app/pyproject.toml`**

`anthropic` and `openai` are no longer imported anywhere in `chat_app` once `services/llm/{claude,openai,ollama}_provider.py` are gone (`ai_agent` owns those now). `mcp`/`pydantic`/`pydantic_core` stay — `services/mcp_client.py` and the new `ai_agent_client.py` both still use the `mcp` package directly. Edit the `dependencies` list, removing the `"openai>=2.43.0"` and `"anthropic>=0.121.0"` lines.

- [ ] **Step 7: Manual verification — chat_app starts and the agent dropdown responds (backend only; UI polish is Task 11)**

With `mcp_server` and `ai_agent` running:

```powershell
.\venv_chat\Scripts\Activate.ps1
cd chat_app
pip install -e .
py -m src.run
```

In a browser, open the Chat page and check the browser's dev tools Network tab (or just curl the route directly in a second terminal: `curl http://127.0.0.1:5000/chat/api/providers` — adjust the port to whatever `chat_app` actually binds, with a valid session cookie, or simplest: just watch the page load and confirm the provider dropdown shows "Claude Agent" instead of "Automatic"/"ChatGPT"/"Claude"/"Local (Ollama)"). Send a real question in the chat box and confirm you get a real answer back (the dropdown option being disabled, per the known `noModelsConfigured` issue fixed in Task 11, may still block actually selecting it in the UI at this exact point — if so, this step's real confirmation is the `/chat/api/providers` JSON response looking right; the full click-and-chat verification is Task 11's).

- [ ] **Step 8: Commit**

```bash
git add chat_app/src/pages/Chat/__index__.py chat_app/src/services/llm/settings.py chat_app/pyproject.toml
git commit -m "$(cat <<'EOF'
Rewire chat_api/providers_api onto ai_agent, delete services/llm/

chat_app's Chat page no longer runs an LLM provider+tool-loop
in-process - it now calls the configured ai_agent's ask/status tools
instead. router.py/base.py/cooldown.py/the three provider files/
app_config.py move to ai_agent (already ported); settings.py stays,
trimmed to only the fields still read (mcp_server_url, chats_db_path).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

*(Run from `chat_app/`, its own nested git repo — same note as Task 8.)*

---

## Task 11: `chat_app` — fix the dropdown's disabled-option logic

**Files:**
- Modify: `chat_app/src/pages/Chat/script.js`

**Interfaces:**
- Consumes: the `/api/providers` response shape from Task 10 (now per-agent, always `models: []`, with a new informational `model` field).

`script.js`'s existing `loadProviders()` disables any available entry whose `models` array is empty (`noModelsConfigured = p.available && p.id !== 'auto' && ...; opt.disabled = !p.available || noModelsConfigured`) — a real problem now, not cosmetic: since every agent entry always has `models: []` (there's no per-agent model sub-list; the model is fixed and only reported informationally), this logic would make every agent option **permanently disabled and unselectable**, breaking the Chat page entirely. This check existed for a real chat_app case before this migration (Ollama with no `providers.ollama.models` configured) that no longer applies now that Ollama support has moved to `ai_agent` and is deferred there — so this branch is dead weight to remove, not something to special-case around.

- [ ] **Step 1: Edit `chat_app/src/pages/Chat/script.js`**

Replace:

```javascript
      const opt = document.createElement('option');
      opt.value = p.id;
      // A provider can report available:true with an empty models list -
      // Ollama with no "providers.ollama.models" entries in config_chat.json
      // is the real-world case (its own has_api_key()/is_available() have
      // no concept of "configured", by design - see ollama_provider.py).
      // "Automatic" legitimately has no models list of its own either, so
      // it's excluded from this check. Selectable-but-guaranteed-to-fail
      // (posting model: null once the now-hidden model dropdown has
      // nothing to offer) is worse than disabling it with a clear reason,
      // same as every other unavailable case below.
      const noModelsConfigured = p.available && p.id !== 'auto' && Array.isArray(p.models) && p.models.length === 0;
      if (noModelsConfigured) {
        opt.textContent = `${p.label} (no models configured)`;
      } else if (p.available) {
        opt.textContent = p.label;
      } else if (p.reason === 'rate_limited') {
        opt.textContent = `${p.label} (rate-limited, ~${p.cooldown_seconds_remaining}s)`;
      } else if (p.reason === 'none_available') {
        opt.textContent = `${p.label} (nothing available)`;
      } else if (p.reason === 'unreachable') {
        opt.textContent = `${p.label} (unreachable)`;
      } else if (p.reason === 'missing_key') {
        opt.textContent = `${p.label} (no API key)`;
      } else {
        // Unrecognized reason - surface it raw rather than guessing (and
        // previously, silently mislabeling anything unrecognized as a
        // missing API key - including Ollama, which has no API key
        // concept at all and reports "unreachable" instead) - same idea
        // as describeModelReason()'s fallback below.
        opt.textContent = `${p.label} (${p.reason || 'unavailable'})`;
      }
      opt.disabled = !p.available || noModelsConfigured;
      providerSelect.appendChild(opt);
```

with:

```javascript
      const opt = document.createElement('option');
      opt.value = p.id;
      // The dropdown now lists ai_agent instances, not LLM providers -
      // each is pinned to exactly one model (reported in p.model), so
      // there's no "no models configured" case to special-case here
      // the way a per-request-selectable provider used to have.
      if (p.available) {
        opt.textContent = p.model ? `${p.label} - ${p.model}` : p.label;
      } else if (p.reason === 'rate_limited') {
        opt.textContent = `${p.label} (rate-limited, ~${p.cooldown_seconds_remaining}s)`;
      } else if (p.reason === 'unreachable') {
        opt.textContent = `${p.label} (unreachable)`;
      } else if (p.reason === 'missing_key') {
        opt.textContent = `${p.label} (no API key)`;
      } else {
        // Unrecognized reason - surface it raw rather than guessing.
        opt.textContent = `${p.label} (${p.reason || 'unavailable'})`;
      }
      opt.disabled = !p.available;
      providerSelect.appendChild(opt);
```

(`'none_available'` was only ever produced by the old `router.list_providers()`'s "Automatic" entry, which no longer exists in this response — dropped along with it.)

- [ ] **Step 2: Manual verification — full end-to-end in the browser**

With `mcp_server` and `ai_agent` both running (or use `run_all.bat` plus `run_ai_agent.bat` together), start `chat_app` and open the Chat page:

1. The provider dropdown shows **"Claude Agent - claude-sonnet-5"** (or whatever you configured), selectable (not greyed out), with no separate model dropdown showing beneath it.
2. Type a question that needs no tools (e.g. "What's 2+2?") and send it. Confirm you get a real answer, and the response's footer shows a token count and the model label.
3. Type a question that should trigger a real `mcp_server` tool (the same one you tried in Task 7) and confirm the "tools used" chip appears and names the tool that ran.
4. Open the Logs page's chat-trace tab (if your account has `logs.chat.view`) and confirm the turn you just sent is logged with its `tool_calls` detail intact.
5. Stop `ai_agent` (close its window / Ctrl+C) and send another question from the Chat page - confirm you get the generic "❌ Something went wrong..." message (not a raw stack trace or a hung request), then restart `ai_agent` and confirm chat works again.

- [ ] **Step 3: Commit**

```bash
git add chat_app/src/pages/Chat/script.js
git commit -m "$(cat <<'EOF'
Fix Chat page's provider dropdown for agent entries

The old "no models configured" disabling logic (built for chat_app's
own per-request Ollama model list) would have made every ai_agent
entry permanently unselectable, since an agent's model is now always
pinned rather than listed. Dropped in favor of showing the agent's
reported model directly in the option label.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

*(Run from `chat_app/`, its own nested git repo — same note as Tasks 8 and 10.)*

---

## Self-Review Notes

- **Spec coverage:** every numbered section of the design spec has a corresponding task — Architecture/Code reuse (Tasks 1-2), Project layout & config (Task 1, 6), Interface (Task 7), Data flow (Tasks 9-10), Agent registry & dropdown (Tasks 8, 10-11), Error handling (Tasks 9-10's `AgentToolError` split), Testing (superseded by the user's explicit manual-testing preference — see Global Constraints).
- **Deferred from the spec, by explicit user decision during planning:** Ollama support (no `ollama_provider.py` copy in `ai_agent`); sub-agent delegation (no `delegate_to_agent` tool - not in the spec either, confirmed out of scope for this first agent).
- **Type consistency check:** `ChatResult`/`ToolCallRecord` (Task 4) match their usage in both provider files (Task 5) and `server.py`'s `ask()` (Task 7); `agent_config.status()`'s return dict shape (Task 6) matches what `ai_agent_client.status()` (Task 9) and `providers_api()` (Task 10) expect (`provider_id`, `model`, `available`, `reason`, `cooldown_seconds_remaining`); `mcp_upstream.list_tools()`/`call_tool()` (Task 3) match the exact call signatures both provider files already use (Task 5), unchanged from chat_app's original `mcp_client.py` contract.
