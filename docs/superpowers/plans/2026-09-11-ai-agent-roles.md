# AI Agent Roles (System Prompt Personas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each `ai_agent` instance be started with a named persona (e.g. `ops_specialist`) that prepends role-specific framing to the LLM system prompt, configured in a new `ai_agent/configs/config_ai_agent_roles.json`, selectable via `AI_AGENT_ROLE` env var or `--role` CLI flag.

**Architecture:** New module `ai_agent/src/llm/agent_roles.py` loads the JSON config once at import time (mirrors `agent_config.py`'s fail-loud-at-import pattern), resolves the active role id from `AI_AGENT_ROLE`/`--role` against `roles` in the config, and computes a module-level `SYSTEM_PROMPT` string: `persona + "\n\n" + tool_use_instructions` (or just `tool_use_instructions` for the `generic` role, which has an empty persona). `anthropic_provider.py` and `openai_provider.py` import `SYSTEM_PROMPT` from `agent_roles` instead of `base_provider`; `base_provider.py` drops the old hardcoded constant. `server.py` gains a `--role` flag next to its existing `--gateway` flag, setting `AI_AGENT_ROLE` before `agent_config` (and therefore `agent_roles`) is imported.

**Tech Stack:** Python, stdlib `json`/`os`/`argparse`, pytest + `monkeypatch`/`importlib.reload` (matching `test_agent_config.py`'s pattern).

**Spec:** This plan's own "Global Constraints" section below captures the full design (no separate spec doc — decided via `mattpocock-skills:grilling` interview).

## Global Constraints

- Config file: `ai_agent/configs/config_ai_agent_roles.json`, with a checked-in `.example` twin — matches `config_llms.json`/`config_agents.json` convention.
- Schema (keyed map, not array):
  ```json
  {
    "default_role": "generic",
    "tool_use_instructions": "You are a helpful assistant with access to tools. Use them to get real data rather than guessing, and say so plainly when no tool can answer the question. Confirm with the user before any destructive or hard-to-reverse action.",
    "roles": {
      "generic": { "label": "Generic Assistant", "persona": "" },
      "ops_specialist": { "label": "Ops Specialist", "persona": "<see Task 3 for full text>" }
    }
  }
  ```
- Role resolution precedence: `--role` CLI flag > `AI_AGENT_ROLE` env var > `default_role` from config.
- Unknown role id (from either the flag/env var) → fail loud at import time with a clear error naming the bad id and the valid ids. No silent fallback to `generic`.
- No per-request/runtime role override — one role per running process, for its whole lifetime.
- `tool_use_instructions` is single-sourced in the config; every role's final system prompt is `persona + "\n\n" + tool_use_instructions` when `persona` is non-empty, else just `tool_use_instructions`.
- `base_provider.py`'s old hardcoded `SYSTEM_PROMPT` constant is removed — replaced by `agent_roles.SYSTEM_PROMPT`, computed from config.

---

### Task 1: `config_ai_agent_roles.json` + `.example` twin

**Files:**
- Create: `ai_agent/configs/config_ai_agent_roles.json`
- Create: `ai_agent/configs/config_ai_agent_roles.json.example`

**Interfaces:**
- Produces: on-disk JSON file matching the schema in Global Constraints, consumed by Task 2's `agent_roles.py` via `json.loads(path.read_text())`.

This config holds no secrets, so (unlike `config_llms.json`/`secret_llm.env`) the real file and the `.example` file are identical — both get committed. There's nothing here for a developer to fill in locally.

- [ ] **Step 1: Write `config_ai_agent_roles.json.example`**

```json
{
  "default_role": "generic",
  "tool_use_instructions": "You are a helpful assistant with access to tools. Use them to get real data rather than guessing, and say so plainly when no tool can answer the question. Confirm with the user before any destructive or hard-to-reverse action.",
  "roles": {
    "generic": {
      "label": "Generic Assistant",
      "persona": ""
    },
    "ops_specialist": {
      "label": "Ops Specialist",
      "persona": "You are an experienced operations specialist. You think in terms of hosts, services, deployments, and access controls - not generic software abstractions. Your working knowledge covers: starting, stopping, restarting, and listing managed applications. When a question touches any of these areas, prefer your tools over general knowledge - they read the actual system state rather than relying on assumptions about how a given landscape is configured. Speak in precise operations terminology (hosts, services, deployments, access-control concepts) rather than paraphrasing them into generic security language, since that precision is what your audience - Basis admins and GRC reviewers - actually needs to act on your answer."
    }
  }
}
```

- [ ] **Step 2: Copy it to the real config**

```bash
cp "ai_agent/configs/config_ai_agent_roles.json.example" "ai_agent/configs/config_ai_agent_roles.json"
```

- [ ] **Step 3: Commit**

```bash
git add ai_agent/configs/config_ai_agent_roles.json ai_agent/configs/config_ai_agent_roles.json.example
git commit -m "$(cat <<'EOF'
feat(ai_agent): add config_ai_agent_roles.json with generic + ops_specialist roles

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `agent_roles.py` - load config, resolve role, compute `SYSTEM_PROMPT`

**Files:**
- Create: `ai_agent/src/llm/agent_roles.py`
- Test: `ai_agent/tests/test_agent_roles.py`

**Interfaces:**
- Consumes: `ai_agent/configs/config_ai_agent_roles.json` (Task 1), read via `Path(__file__).resolve().parent.parent.parent / "configs" / "config_ai_agent_roles.json"`.
- Produces (for Task 3's providers and Task 4's `server.py`):
  - `agent_roles.AgentRoleError(Exception)` - raised at import time (via `_resolve()`) for a missing/unknown role id.
  - `agent_roles._resolve() -> tuple[str, dict]` - returns `(role_id, role_dict)`; `role_dict` has `"label"` and `"persona"` keys. Callable directly in tests (same reasoning as `agent_config._resolve()`: reload() creates a new exception class, so tests that need `pytest.raises` against the *already-imported* module's exception class call `_resolve()` directly instead of reloading).
  - `agent_roles.ROLE_ID: str` - resolved at import time.
  - `agent_roles.SYSTEM_PROMPT: str` - resolved at import time: `persona + "\n\n" + tool_use_instructions` if `persona` is truthy, else `tool_use_instructions` alone.
  - `agent_roles._CONFIG_PATH` - module-level `Path` constant, overridable via `monkeypatch.setattr` in tests (same pattern as `agent_config._SECRETS_PATH`).

- [ ] **Step 1: Write the failing tests**

```python
"""agent_roles.py tests: role resolution (including the fail-loud paths)
and SYSTEM_PROMPT composition.

ROLE_ID/SYSTEM_PROMPT are resolved once at import time, so success-path
tests re-import the module fresh (via importlib.reload) after setting the
env var and redirecting _CONFIG_PATH to a tmp_path fixture file - same
reasoning as test_agent_config.py's handling of _SECRETS_PATH/PROVIDER_ID.
"""

from __future__ import annotations

import importlib
import json

import pytest

_CONFIG = {
    "default_role": "generic",
    "tool_use_instructions": "Use tools. Confirm before destructive actions.",
    "roles": {
        "generic": {"label": "Generic Assistant", "persona": ""},
        "ops_specialist": {"label": "Ops Specialist", "persona": "You are an ops specialist."},
    },
}


@pytest.fixture(autouse=True)
def _config_file(monkeypatch, tmp_path):
    path = tmp_path / "config_ai_agent_roles.json"
    path.write_text(json.dumps(_CONFIG))

    from src.llm import agent_roles

    monkeypatch.setattr(agent_roles, "_CONFIG_PATH", path)
    return path


def _clear_env(monkeypatch):
    monkeypatch.delenv("AI_AGENT_ROLE", raising=False)


def test_default_role_used_when_env_var_unset(monkeypatch):
    _clear_env(monkeypatch)

    from src.llm import agent_roles

    role_id, role = agent_roles._resolve()

    assert role_id == "generic"
    assert role["label"] == "Generic Assistant"


def test_env_var_overrides_default_role(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_ROLE", "ops_specialist")

    from src.llm import agent_roles

    role_id, role = agent_roles._resolve()

    assert role_id == "ops_specialist"
    assert role["label"] == "Ops Specialist"


def test_unknown_role_env_var_fails_loudly(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_ROLE", "bogus")

    from src.llm import agent_roles

    with pytest.raises(agent_roles.AgentRoleError, match="Unknown AI_AGENT_ROLE 'bogus'"):
        agent_roles._resolve()


def test_generic_role_system_prompt_is_tool_use_instructions_only(monkeypatch):
    _clear_env(monkeypatch)

    from src.llm import agent_roles

    reloaded = importlib.reload(agent_roles)

    assert reloaded.ROLE_ID == "generic"
    assert reloaded.SYSTEM_PROMPT == "Use tools. Confirm before destructive actions."


def test_ops_specialist_role_prepends_persona(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_AGENT_ROLE", "ops_specialist")

    from src.llm import agent_roles

    reloaded = importlib.reload(agent_roles)

    assert reloaded.ROLE_ID == "ops_specialist"
    assert reloaded.SYSTEM_PROMPT == (
        "You are an ops specialist.\n\nUse tools. Confirm before destructive actions."
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ai_agent && python -m pytest tests/test_agent_roles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.llm.agent_roles'`

- [ ] **Step 3: Write `agent_roles.py`**

```python
"""Resolves this ai_agent instance's active persona role, once, at import
time - fails loudly if AI_AGENT_ROLE names an id not present in
configs/config_ai_agent_roles.json, rather than discovering that on the
first real request.

SYSTEM_PROMPT (imported by anthropic_provider.py/openai_provider.py in
place of the old base_provider.SYSTEM_PROMPT constant) is the resolved
role's persona text followed by the config's shared tool_use_instructions
- persona first for identity framing, tool-use boilerplate after, so
editing the boilerplate once updates every role. The generic role's
persona is empty, so its SYSTEM_PROMPT is just tool_use_instructions
unchanged from the old constant.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_ai_agent_roles.json"


class AgentRoleError(Exception):
    """Raised at import time for an AI_AGENT_ROLE naming an id that isn't
    in configs/config_ai_agent_roles.json's "roles" map."""


def _load() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text())


def _resolve() -> tuple[str, dict[str, Any]]:
    config = _load()
    roles = config["roles"]
    role_id = os.getenv("AI_AGENT_ROLE") or config["default_role"]
    role = roles.get(role_id)
    if role is None:
        raise AgentRoleError(
            f"Unknown AI_AGENT_ROLE {role_id!r} - must be one of: {', '.join(sorted(roles))}"
        )
    return role_id, role


def _compose_system_prompt(config: dict[str, Any], role: dict[str, Any]) -> str:
    tool_use_instructions = config["tool_use_instructions"]
    persona = role.get("persona") or ""
    if persona:
        return f"{persona}\n\n{tool_use_instructions}"
    return tool_use_instructions


ROLE_ID, _ROLE = _resolve()
SYSTEM_PROMPT = _compose_system_prompt(_load(), _ROLE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ai_agent && python -m pytest tests/test_agent_roles.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ai_agent/src/llm/agent_roles.py ai_agent/tests/test_agent_roles.py
git commit -m "$(cat <<'EOF'
feat(ai_agent): add agent_roles module resolving AI_AGENT_ROLE -> SYSTEM_PROMPT

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Wire providers to `agent_roles.SYSTEM_PROMPT`, drop old constant

**Files:**
- Modify: `ai_agent/src/llm/base_provider.py:19-24` (remove `SYSTEM_PROMPT` constant and its docstring reference)
- Modify: `ai_agent/src/llm/anthropic_provider.py:39` (import `SYSTEM_PROMPT` from `agent_roles` instead of `base_provider`)
- Modify: `ai_agent/src/llm/openai_provider.py:44` (same)
- Modify: `ai_agent/tests/test_anthropic_provider.py` (if it asserts on `SYSTEM_PROMPT` text/import path)
- Modify: `ai_agent/tests/test_openai_provider.py` (same)

**Interfaces:**
- Consumes: `agent_roles.SYSTEM_PROMPT` (Task 2).
- Produces: no new interface - `anthropic_provider.run_chat`/`run_interpret` and `openai_provider.run_chat`/`run_interpret` behave exactly as before when `AI_AGENT_ROLE` is unset (config's `generic.persona` is `""`, so `SYSTEM_PROMPT` is byte-for-byte the same string the old constant held).

- [ ] **Step 1: Check existing provider tests for `SYSTEM_PROMPT` references**

```bash
cd ai_agent && grep -n "SYSTEM_PROMPT" tests/test_anthropic_provider.py tests/test_openai_provider.py
```

If either file imports or asserts on `base_provider.SYSTEM_PROMPT`, note the line numbers - Step 5 updates them to `agent_roles.SYSTEM_PROMPT` instead. If neither references it, skip straight to Step 2 (nothing to update there).

- [ ] **Step 2: Update `base_provider.py` - remove the constant**

In `ai_agent/src/llm/base_provider.py`, delete lines 19-24:

```python
SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. Use them to get "
    "real data rather than guessing, and say so plainly when no tool can "
    "answer the question. Confirm with the user before any destructive or "
    "hard-to-reverse action."
)
```

and update the module docstring (lines 1-9) to drop the now-stale claim that `SYSTEM_PROMPT` "carries over unchanged":

```python
"""Shared types for ai_agent's LLM providers.

Trimmed from chat_app/src/services/llm/base.py: this project pins one
provider+model per instance (see agent_config.py) rather than routing
between several, so ProviderSpec/ModelOption/ModelAvailability* and the
Ollama-only RecursiveRoundRecord - all built for chat_app's per-request
provider dropdown - have no equivalent need here. ChatCancelled,
ToolCallRecord and ChatResult carry over unchanged. SYSTEM_PROMPT moved to
agent_roles.py, which composes it from configs/config_ai_agent_roles.json
instead of a fixed string.
"""
```

- [ ] **Step 3: Update `anthropic_provider.py`'s import**

In `ai_agent/src/llm/anthropic_provider.py:39`, change:

```python
from src.llm.base_provider import BaseProvider, ChatCancelled, SYSTEM_PROMPT, ChatResult, ToolCallRecord
```

to:

```python
from src.llm.agent_roles import SYSTEM_PROMPT
from src.llm.base_provider import BaseProvider, ChatCancelled, ChatResult, ToolCallRecord
```

- [ ] **Step 4: Update `openai_provider.py`'s import**

In `ai_agent/src/llm/openai_provider.py:44`, same change:

```python
from src.llm.agent_roles import SYSTEM_PROMPT
from src.llm.base_provider import BaseProvider, ChatCancelled, ChatResult, ToolCallRecord
```

- [ ] **Step 5: Fix any provider tests found in Step 1**

If Step 1 found references, update each `from src.llm.base_provider import ... SYSTEM_PROMPT ...` (or similar) to import from `src.llm.agent_roles` instead, matching the production change above.

- [ ] **Step 6: Run full ai_agent test suite**

Run: `cd ai_agent && python -m pytest tests/ -v`
Expected: PASS - `test_anthropic_provider.py`/`test_openai_provider.py` unaffected in behavior since `generic` role's `SYSTEM_PROMPT` equals the old constant verbatim; `test_agent_roles.py` from Task 2 still passes.

- [ ] **Step 7: Commit**

```bash
git add ai_agent/src/llm/base_provider.py ai_agent/src/llm/anthropic_provider.py ai_agent/src/llm/openai_provider.py ai_agent/tests/test_anthropic_provider.py ai_agent/tests/test_openai_provider.py
git commit -m "$(cat <<'EOF'
refactor(ai_agent): providers import SYSTEM_PROMPT from agent_roles, not base_provider

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `server.py` `--role` CLI flag

**Files:**
- Modify: `ai_agent/src/server.py:16-31` (add `--role` alongside existing `--gateway` argparse block)
- Test: `ai_agent/tests/test_server.py` (add a role-flag test if the file already tests `--gateway`'s env-var-setting behavior the same way; otherwise this task's own test below is sufficient)

**Interfaces:**
- Consumes: `os.environ["AI_AGENT_ROLE"]`, read by `agent_roles._resolve()` (Task 2) at `agent_config` import time.
- Produces: no new interface - `--role ops_specialist` on the command line makes `AI_AGENT_ROLE=ops_specialist` visible to every subsequent import in the process, same mechanism as the existing `--gateway` flag setting `AI_AGENT_GATEWAY`.

- [ ] **Step 1: Check how `test_server.py` currently tests `--gateway`**

```bash
cd ai_agent && grep -n "gateway\|AI_AGENT_GATEWAY\|argparse\|_parser" tests/test_server.py
```

Use whatever pattern it finds (likely invoking `server._parser.parse_known_args([...])` directly, since `server.py` does real network binding via `FastMCP(...)` at import time and can't be freely reloaded) as the template for Step 3's test.

- [ ] **Step 2: Write the failing test**

Add to `ai_agent/tests/test_server.py` (adjust the exact invocation to match whatever pattern Step 1 found for the `--gateway` flag - the shape below assumes `server._parser` is directly accessible, matching `server.py`'s current module-level `_parser`):

```python
def test_role_flag_sets_env_var(monkeypatch):
    monkeypatch.delenv("AI_AGENT_ROLE", raising=False)

    from src import server

    args, _ = server._parser.parse_known_args(["--role", "ops_specialist"])

    assert args.role == "ops_specialist"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ai_agent && python -m pytest tests/test_server.py::test_role_flag_sets_env_var -v`
Expected: FAIL with `AttributeError: 'Namespace' object has no attribute 'role'`

- [ ] **Step 4: Add `--role` to `server.py`**

In `ai_agent/src/server.py`, after the existing `--gateway` block (lines 16-31), add:

```python
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--gateway",
    help=(
        "Override this run's gateway block (configs/config_llms.json), "
        "e.g. openrouter/bedrock/vertex/litellm/helicone/portkey for "
        "anthropic, or azure/together/groq/fireworks/deepinfra/"
        "perplexity/ollama/vllm for openai. Takes precedence over "
        "AI_AGENT_GATEWAY. Set before importing "
        "agent_config, since the provider resolves its client/default "
        "model from the gateway at import time."
    ),
)
_parser.add_argument(
    "--role",
    help=(
        "Override this run's persona role (configs/config_ai_agent_roles.json), "
        "e.g. ops_specialist. Takes precedence over AI_AGENT_ROLE. Set "
        "before importing agent_config, since agent_roles resolves "
        "SYSTEM_PROMPT from the role at import time, same as --gateway "
        "above."
    ),
)
_args, _ = _parser.parse_known_args()
if _args.gateway:
    os.environ["AI_AGENT_GATEWAY"] = _args.gateway
if _args.role:
    os.environ["AI_AGENT_ROLE"] = _args.role
```

(This replaces the existing block - one `_parser` with both arguments added before the single `parse_known_args()` call, not two separate parsers.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ai_agent && python -m pytest tests/test_server.py::test_role_flag_sets_env_var -v`
Expected: PASS

- [ ] **Step 6: Update `server.py`'s module docstring run examples**

In `ai_agent/src/server.py:5-8`, add a `--role` example next to the existing `--gateway` one:

```python
Run with:
    python -m src.server
    python -m src.server --gateway openrouter
    python -m src.server --role ops_specialist
"""
```

- [ ] **Step 7: Run full ai_agent test suite**

Run: `cd ai_agent && python -m pytest tests/ -v`
Expected: PASS (all tests, including Task 1-3's)

- [ ] **Step 8: Commit**

```bash
git add ai_agent/src/server.py ai_agent/tests/test_server.py
git commit -m "$(cat <<'EOF'
feat(ai_agent): add --role CLI flag to server.py, mirroring --gateway

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: README documentation

**Files:**
- Modify: `ai_agent/README.md` (add a section on roles, next to wherever `AI_AGENT_GATEWAY`/`--gateway` is documented)

**Interfaces:**
- Consumes: nothing new - this is documentation only, summarizing Tasks 1-4's behavior for a developer reading the README.

- [ ] **Step 1: Read the current README's gateway section to match its structure**

```bash
grep -n "gateway\|AI_AGENT_GATEWAY\|--gateway" "ai_agent/README.md"
```

- [ ] **Step 2: Add a matching "Roles" section**

Insert a section (placed next to the gateway documentation found in Step 1, same heading level) covering:
- What `config_ai_agent_roles.json` is and where it lives.
- How to select a role: `AI_AGENT_ROLE=ops_specialist` env var, or `--role ops_specialist` CLI flag (flag wins).
- That an unknown role id fails loudly at startup.
- That role selection is fixed for the process lifetime - no per-request override.
- The two roles shipped out of the box: `generic` (default, unchanged behavior) and `ops_specialist`.
- How to add a new role: add an entry under `roles` in `config_ai_agent_roles.json` with a `label` and `persona`; no code change needed.

- [ ] **Step 3: Commit**

```bash
git add ai_agent/README.md
git commit -m "$(cat <<'EOF'
docs(ai_agent): document AI_AGENT_ROLE / --role persona selection

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
