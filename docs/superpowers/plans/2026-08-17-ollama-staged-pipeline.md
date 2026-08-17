# Ollama Staged Enumerate-Execute-Conclude Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Ollama models that opt in (via a per-model `staged_pipeline` flag) a five-phase turn — Resume check, Filter, Enumerate, Execute, Conclude — that deterministically shrinks the tool list and breaks a turn into several small, separately-billed Ollama calls, with mid-plan `ask_user` steps pausing the turn and resuming on the next message.

**Architecture:** A new `chat_app/services/llm/staged_pipeline.py` module implements the five phases as small, independently-testable functions, orchestrated by a top-level `run()`. `ollama_provider.run_chat()` branches to it for opted-in models, otherwise runs its existing `_tool_loop()` unchanged. Pause/resume state lives in a new SQLite store (`staged_plans_store.py`), mirroring `mcp_server/infra/pending_requests.py`'s shape. Tool relevance filtering reads keywords off MCP's native `meta` field, which requires a small `mcp_server` fix so extension-proxied tools carry `meta` through (today it's silently dropped) plus adding `meta={"keywords": [...]}` to the two existing built-in tool files.

**Tech Stack:** Python, Flask (`chat_app`), FastMCP (`mcp_server`), `openai` SDK against Ollama's OpenAI-compatible endpoint, stdlib `sqlite3`, `pytest`.

**Spec:** [docs/superpowers/specs/2026-08-17-ollama-staged-pipeline-design.md](../specs/2026-08-17-ollama-staged-pipeline-design.md)

## Global Constraints

- Every other provider (OpenAI, Claude) and every non-opted-in Ollama model must be byte-for-byte unchanged in behavior.
- `staged_pipeline` and `recursive_chain` are mutually exclusive per model — both set on the same model entry is a config-load error, not a silent pick.
- No new third-party dependency — the tool filter is a plain deterministic keyword match, not embeddings/ML.
- Every guardrail (plan size, tool count, call budget) degrades into a usable fallback; none of them may raise out of a chat turn.
- Follow this repo's existing test conventions exactly: `unittest.mock.patch`/`Mock`, `SimpleNamespace` fakes for SDK response objects, `tmp_path`-backed real SQLite files for store tests (never a mocked `sqlite3`), `pytest.mark.anyio` for `mcp_server`'s async tests.

---

## Task 1: Preserve tool metadata through the extension proxy (mcp_server)

**Files:**
- Modify: `mcp_server/src/mcp_server/infra/extensions.py:232-245`
- Test: `mcp_server/tests/test_extensions.py`

**Interfaces:**
- Consumes: `mcp.types.Tool` (`meta`, `annotations`, `icons` fields — already present on the installed `mcp` package, confirmed via `inspect.getsource(types.Tool)`).
- Produces: `_ProxiedTool.definition` now carries `meta`/`annotations`/`icons` from the upstream tool, for Task 2 (built-in keyword `meta`) and any extension author who declares their own `meta={"keywords": [...]}` to rely on.

This is a real bug independent of this feature — `_connect_one` currently drops `meta`, `annotations`, and `icons` when building the namespaced proxy definition — and the whole tool-filtering feature depends on it being fixed, since extension tools' keywords would otherwise never survive the proxy.

- [ ] **Step 1: Write the failing test**

Add to `mcp_server/tests/test_extensions.py`, near the other namespacing tests:

```python
@pytest.mark.anyio
async def test_proxied_tool_definition_preserves_meta_annotations_and_icons(monkeypatch: pytest.MonkeyPatch):
    """Regression test: meta/annotations/icons were silently dropped when
    building _ProxiedTool.definition, which would break any feature (like
    keyword-based tool filtering) that relies on an extension's own
    declared metadata surviving the proxy."""
    tool = types.Tool(
        name="echo",
        description="Echo text back",
        inputSchema={"type": "object", "properties": {}},
        meta={"keywords": ["echo", "repeat"]},
        annotations=types.ToolAnnotations(title="Echo"),
        icons=[types.Icon(src="https://example.com/icon.png")],
    )
    session = _FakeSession(tools=[tool])
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))

    [proxied] = registry.proxied_tool_definitions()
    assert proxied.meta == {"keywords": ["echo", "repeat"]}
    assert proxied.annotations == types.ToolAnnotations(title="Echo")
    assert proxied.icons == [types.Icon(src="https://example.com/icon.png")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp_server && ./venv_mcp/Scripts/python -m pytest tests/test_extensions.py::test_proxied_tool_definition_preserves_meta_annotations_and_icons -v`
Expected: FAIL — `proxied.meta` is `None`, not `{"keywords": [...]}`.

- [ ] **Step 3: Fix `_connect_one`**

In `mcp_server/src/mcp_server/infra/extensions.py`, find this block (around line 232):

```python
        for tool in listed.tools:
            namespaced = f"{extension_id}{NAMESPACE_SEPARATOR}{tool.name}"
            self._proxied[namespaced] = _ProxiedTool(
                extension_id=extension_id,
                upstream_name=tool.name,
                definition=types.Tool(
                    name=namespaced,
                    description=tool.description,
                    inputSchema=tool.inputSchema,
                    outputSchema=tool.outputSchema,
                ),
            )
            tool_names.append(namespaced)
```

Replace with:

```python
        for tool in listed.tools:
            namespaced = f"{extension_id}{NAMESPACE_SEPARATOR}{tool.name}"
            self._proxied[namespaced] = _ProxiedTool(
                extension_id=extension_id,
                upstream_name=tool.name,
                definition=types.Tool(
                    name=namespaced,
                    description=tool.description,
                    inputSchema=tool.inputSchema,
                    outputSchema=tool.outputSchema,
                    meta=tool.meta,
                    annotations=tool.annotations,
                    icons=tool.icons,
                ),
            )
            tool_names.append(namespaced)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mcp_server && ./venv_mcp/Scripts/python -m pytest tests/test_extensions.py -v`
Expected: PASS — all tests, including the new one and every existing namespacing/dispatch test (this change only adds fields, it doesn't alter `name`/`description`/`inputSchema`/`outputSchema`).

- [ ] **Step 5: Commit**

```bash
git add mcp_server/src/mcp_server/infra/extensions.py mcp_server/tests/test_extensions.py
git commit -m "fix: preserve tool meta/annotations/icons through the extension proxy"
```

---

## Task 2: Declare keywords on the built-in tools (mcp_server)

**Files:**
- Modify: `mcp_server/src/mcp_server/capabilities/host_health/tool.py`
- Modify: `mcp_server/src/mcp_server/capabilities/otp/tool.py`
- Test: `mcp_server/tests/test_host_health_capability.py`, `mcp_server/tests/test_otp_domain.py` (new small test added to the latter's file, or a new tiny test module — see Step 1)

**Interfaces:**
- Produces: `get_host_health_tool`, `request_otp_tool`, `verify_otp_tool` each carry `meta={"keywords": [...]}`, consumed later by `chat_app`'s `staged_pipeline._filter_tools` (Task 6) via `list_tools()`.

Confirmed live against the installed `mcp`/FastMCP: `@mcp.tool(meta={...})` round-trips through `await mcp.list_tools()` unchanged (verified with a throwaway FastMCP instance before writing this plan).

- [ ] **Step 1: Write the failing test**

Create `mcp_server/tests/test_tool_keywords.py`:

```python
"""Regression coverage: every built-in tool declares `meta["keywords"]`,
consumed by chat_app's staged-pipeline tool filter (see
docs/superpowers/specs/2026-08-17-ollama-staged-pipeline-design.md). Uses
the real `mcp_server.server.mcp` FastMCP instance - importing each tool
module is what runs its @mcp.tool() decorator and registers it there (see
run.py's own comment on why these imports "look unused").
"""

from __future__ import annotations

import pytest

from mcp_server.capabilities.host_health import tool as host_health_tool  # noqa: F401
from mcp_server.capabilities.otp import tool as otp_tool  # noqa: F401
from mcp_server.server import mcp


@pytest.mark.anyio
async def test_every_built_in_tool_declares_keywords():
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    for name in ("get_host_health_tool", "request_otp_tool", "verify_otp_tool"):
        assert name in by_name, f"{name} not registered"
        meta = by_name[name].meta
        assert meta is not None and meta.get("keywords"), f"{name} has no declared keywords"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp_server && ./venv_mcp/Scripts/python -m pytest tests/test_tool_keywords.py -v`
Expected: FAIL — `meta` is `None` for all three tools today.

- [ ] **Step 3: Add keywords to `host_health/tool.py`**

In `mcp_server/src/mcp_server/capabilities/host_health/tool.py`, change:

```python
@mcp.tool()
def get_host_health_tool(name: str) -> HostHealthResult:
```

to:

```python
@mcp.tool(meta={"keywords": ["host", "health", "cpu", "memory", "disk", "uptime", "status"]})
def get_host_health_tool(name: str) -> HostHealthResult:
```

- [ ] **Step 4: Add keywords to `otp/tool.py`**

In `mcp_server/src/mcp_server/capabilities/otp/tool.py`, change:

```python
@mcp.tool()
def request_otp_tool(recipient: str | None = None) -> RequestOtpResult:
```

to:

```python
@mcp.tool(meta={"keywords": ["otp", "passcode", "code", "verify", "identity", "email"]})
def request_otp_tool(recipient: str | None = None) -> RequestOtpResult:
```

and change:

```python
@mcp.tool()
def verify_otp_tool(otp_id: str, code: str) -> VerifyOtpResult:
```

to:

```python
@mcp.tool(meta={"keywords": ["otp", "passcode", "code", "verify"]})
def verify_otp_tool(otp_id: str, code: str) -> VerifyOtpResult:
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd mcp_server && ./venv_mcp/Scripts/python -m pytest tests/test_tool_keywords.py tests/test_host_health_capability.py tests/test_otp_domain.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp_server/src/mcp_server/capabilities/host_health/tool.py mcp_server/src/mcp_server/capabilities/otp/tool.py mcp_server/tests/test_tool_keywords.py
git commit -m "feat: declare keywords on built-in tools for staged-pipeline filtering"
```

---

## Task 3: `staged_plans_store.py` — pause/resume storage

**Files:**
- Create: `chat_app/src/chat_app/services/llm/staged_plans_store.py`
- Modify: `chat_app/src/chat_app/config.py`
- Test: `chat_app/tests/test_staged_plans_store.py`

**Interfaces:**
- Produces: `save(db_path, chat_id, provider_id, model, plan, step_index, results, *, ttl_hours=24) -> None`, `get(db_path, chat_id) -> StagedPlan | None`, `delete(db_path, chat_id) -> None`, `StagedPlan` dataclass (`chat_id`, `provider_id`, `model`, `plan`, `step_index`, `results`, `created_at`, `expires_at`, `is_expired` property). Consumed by `staged_pipeline.run()` (Task 9).
- `Settings.staged_plans_db_path: Path`, consumed by `ollama_provider.run_chat()` (Task 9).

- [ ] **Step 1: Write the failing tests**

Create `chat_app/tests/test_staged_plans_store.py`:

```python
"""Tests for services/llm/staged_plans_store.py - mirrors
mcp_server/tests/test_pending_requests.py's shape: real SQLite file I/O
via tmp_path, not a mocked sqlite3, since the whole point of this module
is that the state survives outside the process.
"""

from __future__ import annotations

from pathlib import Path

from chat_app.services.llm import staged_plans_store


def test_save_then_get_roundtrips_the_plan(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    plan = [{"type": "tool_call", "detail": "check zima's health"}]
    results = [{"detail": "check zima's health", "result": "zima: cpu 12%"}]

    staged_plans_store.save(db, "chat-1", "ollama", "phi4-mini:latest", plan, 1, results)
    record = staged_plans_store.get(db, "chat-1")

    assert record is not None
    assert record.provider_id == "ollama"
    assert record.model == "phi4-mini:latest"
    assert record.plan == plan
    assert record.step_index == 1
    assert record.results == results
    assert record.is_expired is False


def test_get_unknown_chat_id_returns_none(tmp_path: Path):
    assert staged_plans_store.get(tmp_path / "staged_plans.db", "no-such-chat") is None


def test_save_twice_for_the_same_chat_id_replaces_the_row(tmp_path: Path):
    """A resumed plan's step_index advances across turns - the second
    save() must overwrite, not create a second row for the same chat."""
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "m", [{"type": "ask_user", "detail": "q1"}], 0, [])

    staged_plans_store.save(
        db, "chat-1", "ollama", "m", [{"type": "ask_user", "detail": "q1"}], 1,
        [{"detail": "q1", "result": "answered"}],
    )

    record = staged_plans_store.get(db, "chat-1")
    assert record.step_index == 1
    assert record.results == [{"detail": "q1", "result": "answered"}]


def test_negative_ttl_is_already_expired_and_get_returns_none(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "m", [], 0, [], ttl_hours=-1)

    assert staged_plans_store.get(db, "chat-1") is None


def test_delete_removes_the_row(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "m", [], 0, [])

    staged_plans_store.delete(db, "chat-1")

    assert staged_plans_store.get(db, "chat-1") is None


def test_delete_of_an_unknown_chat_id_is_a_quiet_no_op(tmp_path: Path):
    staged_plans_store.delete(tmp_path / "staged_plans.db", "no-such-chat")  # must not raise


def test_db_file_created_in_a_nonexistent_parent_directory(tmp_path: Path):
    db = tmp_path / "does" / "not" / "exist" / "staged_plans.db"

    staged_plans_store.save(db, "chat-1", "ollama", "m", [], 0, [])

    assert db.exists()
    assert staged_plans_store.get(db, "chat-1") is not None


def test_two_chats_do_not_clobber_each_other(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-a", "ollama", "m", [{"type": "ask_user", "detail": "qa"}], 0, [])
    staged_plans_store.save(db, "chat-b", "ollama", "m", [{"type": "ask_user", "detail": "qb"}], 0, [])

    staged_plans_store.delete(db, "chat-a")

    assert staged_plans_store.get(db, "chat-a") is None
    assert staged_plans_store.get(db, "chat-b") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_plans_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chat_app.services.llm.staged_plans_store'`.

- [ ] **Step 3: Implement `staged_plans_store.py`**

Create `chat_app/src/chat_app/services/llm/staged_plans_store.py`:

```python
"""Ephemeral storage bridging one paused chat turn to the next.

A staged-pipeline plan (see staged_pipeline.py) that pauses on an
`ask_user` step needs to survive between one HTTP request and the next -
longer than an in-memory dict should live, but not as long as a real
record (a chat transcript, an account). Mirrors
mcp_server/infra/pending_requests.py's shape exactly: SQLite, opaque JSON
payload, TTL-based expiry, one row per key - chosen because it's already
this project's answer to exactly this "state that must outlive one
request but shouldn't be an in-memory dict, and shouldn't be permanent"
shape.

One row per chat_id - present only while a plan is paused on `ask_user`.
Written at the pause, deleted the moment Conclude finishes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class StagedPlan:
    chat_id: str
    provider_id: str
    model: str
    plan: list[dict[str, Any]]
    step_index: int
    results: list[dict[str, Any]]
    created_at: str
    expires_at: str

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > datetime.fromisoformat(self.expires_at)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS staged_plans (
            chat_id     TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            model       TEXT NOT NULL,
            plan        TEXT NOT NULL,
            step_index  INTEGER NOT NULL,
            results     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save(
    db_path: Path,
    chat_id: str,
    provider_id: str,
    model: str,
    plan: list[dict[str, Any]],
    step_index: int,
    results: list[dict[str, Any]],
    *,
    ttl_hours: float = 24,
) -> None:
    """Create or overwrite this chat_id's paused plan. A second save() for
    the same chat_id (the step_index advancing across resumes) replaces
    the row rather than erroring - "one row per chat_id" is the whole
    point (see module docstring), and INSERT OR REPLACE is the plain
    SQLite way to express that without a separate exists-check."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO staged_plans "
            "(chat_id, provider_id, model, plan, step_index, results, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                provider_id,
                model,
                json.dumps(plan),
                step_index,
                json.dumps(results),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get(db_path: Path, chat_id: str) -> StagedPlan | None:
    """None for a missing row *or* an expired one - expiry is opaque to
    callers here (unlike pending_requests.py, which exposes is_expired for
    its callers to report separately - an emailed-link approval needs to
    tell someone "this link expired" rather than pretending it never
    existed; staged_pipeline.py has no such need, an expired plan and no
    plan at all mean exactly the same thing to it: start fresh)."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT chat_id, provider_id, model, plan, step_index, results, created_at, expires_at "
            "FROM staged_plans WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    record = StagedPlan(
        chat_id=row[0],
        provider_id=row[1],
        model=row[2],
        plan=json.loads(row[3]),
        step_index=row[4],
        results=json.loads(row[5]),
        created_at=row[6],
        expires_at=row[7],
    )
    if record.is_expired:
        return None
    return record


def delete(db_path: Path, chat_id: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM staged_plans WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Add the config setting**

In `chat_app/src/chat_app/config.py`, after the `chats_db_path` field:

```python
    chats_db_path: Path = Path(_env("CHATS_DB_PATH", "data/chats.db"))
```

add:

```python
    # Paused staged-pipeline plans (see services/llm/staged_plans_store.py) -
    # bridges one chat turn to the next when a plan pauses on an ask_user
    # step. Mirrors chats_db_path immediately above it: own file, relative
    # to CWD by default, same convention.
    staged_plans_db_path: Path = Path(_env("STAGED_PLANS_DB_PATH", "data/staged_plans.db"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_plans_store.py tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add chat_app/src/chat_app/services/llm/staged_plans_store.py chat_app/src/chat_app/config.py chat_app/tests/test_staged_plans_store.py
git commit -m "feat: add staged_plans_store for staged-pipeline pause/resume state"
```

---

## Task 4: `staged_pipeline` config flag per Ollama model

**Files:**
- Modify: `chat_app/src/chat_app/services/llm/base.py`
- Modify: `chat_app/src/chat_app/infra/app_config.py`
- Modify: `chat_app/config.json.example`
- Test: `chat_app/tests/test_app_config.py`

**Interfaces:**
- Produces: `ModelOption.staged_pipeline: bool = False`, consumed by `ollama_provider.run_chat()` (Task 9) and by `test_llm_providers.py`.

- [ ] **Step 1: Write the failing tests**

Add to `chat_app/tests/test_app_config.py`:

```python
def test_staged_pipeline_defaults_to_false_when_absent(tmp_path: Path):
    path = _write(
        tmp_path,
        {"providers": {"ollama": {"models": [{"id": "qwen2.5:7b", "label": "Qwen"}]}}},
    )

    models = load_ollama_models(path)

    assert models == [ModelOption(id="qwen2.5:7b", label="Qwen", staged_pipeline=False)]


def test_staged_pipeline_true_parses_into_model_options(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "providers": {
                "ollama": {
                    "models": [{"id": "phi4-mini:latest", "label": "Phi 4 Mini", "staged_pipeline": True}]
                }
            }
        },
    )

    models = load_ollama_models(path)

    assert models == [ModelOption(id="phi4-mini:latest", label="Phi 4 Mini", staged_pipeline=True)]


def test_entry_with_non_bool_staged_pipeline_fails_loudly(tmp_path: Path):
    path = _write(
        tmp_path,
        {"providers": {"ollama": {"models": [{"id": "qwen2.5:7b", "label": "Qwen", "staged_pipeline": "yes"}]}}},
    )

    with pytest.raises(ValueError, match=r"models\[0\].staged_pipeline"):
        load_ollama_models(path)


def test_recursive_chain_and_staged_pipeline_both_true_fails_loudly(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "providers": {
                "ollama": {
                    "models": [
                        {
                            "id": "phi4-mini:latest",
                            "label": "Phi 4 Mini",
                            "recursive_chain": True,
                            "staged_pipeline": True,
                        }
                    ]
                }
            }
        },
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        load_ollama_models(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_app_config.py -v`
Expected: FAIL — `ModelOption.__init__() got an unexpected keyword argument 'staged_pipeline'`.

- [ ] **Step 3: Add the field to `ModelOption`**

In `chat_app/src/chat_app/services/llm/base.py`, in the `ModelOption` dataclass, after:

```python
    recursive_chain: bool = False
```

add:

```python
    # Whether this model uses the staged enumerate-execute-conclude
    # pipeline (see services/llm/staged_pipeline.py) instead of
    # ollama_provider.py's default single tool-calling loop. Only
    # meaningful for ollama_provider today, same as recursive_chain above.
    # Mutually exclusive with recursive_chain in practice - see
    # infra/app_config.py's validation - since staged_pipeline's own
    # Conclude phase already plays the "final answer" role recursive_chain
    # reviews.
    staged_pipeline: bool = False
```

- [ ] **Step 4: Parse it in `load_ollama_models`**

In `chat_app/src/chat_app/infra/app_config.py`, find:

```python
        recursive_chain = entry.get("recursive_chain", False)
        if not isinstance(recursive_chain, bool):
            raise ValueError(f"Config file {config_path}: '{where}.recursive_chain' must be a boolean")

        models.append(ModelOption(id=model_id, label=label, recursive_chain=recursive_chain))
```

Replace with:

```python
        recursive_chain = entry.get("recursive_chain", False)
        if not isinstance(recursive_chain, bool):
            raise ValueError(f"Config file {config_path}: '{where}.recursive_chain' must be a boolean")

        staged_pipeline = entry.get("staged_pipeline", False)
        if not isinstance(staged_pipeline, bool):
            raise ValueError(f"Config file {config_path}: '{where}.staged_pipeline' must be a boolean")

        if recursive_chain and staged_pipeline:
            raise ValueError(
                f"Config file {config_path}: '{where}' sets both 'recursive_chain' and "
                f"'staged_pipeline' - they're mutually exclusive review/pipeline modes, pick one"
            )

        models.append(
            ModelOption(
                id=model_id, label=label, recursive_chain=recursive_chain, staged_pipeline=staged_pipeline
            )
        )
```

- [ ] **Step 5: Update `config.json.example`**

In `chat_app/config.json.example`, add `"staged_pipeline": false` to each of the four existing entries, e.g.:

```json
{
  "providers": {
    "ollama": {
      "models": [
        { "id": "qwen2.5:3b", "label": "Qwen 2.5 3B (local)", "recursive_chain": false, "staged_pipeline": false },
        { "id": "llama3.2:1b", "label": "Llama 3.2 1B (local)", "recursive_chain": false, "staged_pipeline": false },
        { "id": "phi3:mini", "label": "Phi 3 Mini (local)", "recursive_chain": false, "staged_pipeline": false },
        { "id": "phi4-mini:latest", "label": "Phi 4 Mini (local)", "recursive_chain": false, "staged_pipeline": false }
      ]
    }
  }
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_app_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add chat_app/src/chat_app/services/llm/base.py chat_app/src/chat_app/infra/app_config.py chat_app/config.json.example chat_app/tests/test_app_config.py
git commit -m "feat: add staged_pipeline config flag per Ollama model"
```

---

## Task 5: Thread `chat_id` through the run_chat call chain

**Files:**
- Modify: `chat_app/src/chat_app/services/llm/base.py` (`RunChatFn` type comment)
- Modify: `chat_app/src/chat_app/services/llm/router.py`
- Modify: `chat_app/src/chat_app/services/llm/openai_provider.py`
- Modify: `chat_app/src/chat_app/services/llm/claude_provider.py`
- Modify: `chat_app/src/chat_app/services/llm/ollama_provider.py`
- Modify: `chat_app/src/chat_app/chats/store.py`
- Modify: `chat_app/src/chat_app/pages/chat/routes.py`
- Test: `chat_app/tests/test_router.py`, `chat_app/tests/test_chat_routes.py`, `chat_app/tests/test_chats_store.py`

**Interfaces:**
- Produces: every `ProviderSpec.run_chat` now accepts `chat_id: str | None = None` as a fifth parameter (positional-or-keyword); `router.run_chat(..., chat_id=None)` forwards it; `chat_api` mints a `chat_id` before calling `router.run_chat` when the client didn't send one, so a staged-pipeline model (Task 9) always has a stable key to pause against.

A `chat_id` has to exist *before* the LLM call for a staged-pipeline model to persist a paused plan, but today `chat_api` only assigns one *after* the call returns (`chats_store.save_chat`'s own id generation). This task moves that id-minting earlier and threads it through every provider's signature uniformly (even though only the staged pipeline will ever read it) so `router.py` keeps calling every `ProviderSpec` the same way.

Minting early means the very first turn of a brand-new chat calls `chats_store.save_chat` *twice*: once up front with an empty transcript (to get a real, persisted id), once at the end with the full transcript (an UPDATE, not an INSERT). `chats_store.save_chat`'s UPDATE branch today never touches `title`, which is correct for an existing chat being renamed-and-continued, but would leave a chat created this way stuck with `title = "New chat"` forever. This task fixes that too: the UPDATE branch now recomputes the title, but *only* when the existing title is still the `"New chat"` placeholder — a real, user-set title (via `rename_chat`) is left untouched.

- [ ] **Step 1: Write the failing tests**

Add to `chat_app/tests/test_chats_store.py`, in the "save_chat: updating" section:

```python
def test_save_chat_update_sets_title_when_still_the_new_chat_placeholder(db_path):
    """Regression coverage for chat_api's early chat_id minting (see
    pages/chat/routes.py): a chat created with an empty transcript (via
    save_chat(..., None, [])) gets the "New chat" placeholder title; the
    very next save (the real transcript, via the id-given/UPDATE path)
    must compute a real title instead of leaving the placeholder forever."""
    chat_id = store.save_chat(db_path, "alice", None, [])

    store.save_chat(db_path, "alice", chat_id, [{"role": "user", "content": "how do I reset a password?"}])

    assert store.get_chat(db_path, "alice", chat_id)["title"] == "how do I reset a password?"


def test_save_chat_update_preserves_a_manually_renamed_title(db_path):
    """A title the user set via rename_chat must survive a later
    save_chat update - only the "New chat" placeholder gets replaced."""
    chat_id = store.save_chat(db_path, "alice", None, [{"role": "user", "content": "first"}])
    store.rename_chat(db_path, "alice", chat_id, "My renamed chat")

    store.save_chat(
        db_path, "alice", chat_id,
        [{"role": "user", "content": "first"}, {"role": "assistant", "content": "reply"}],
    )

    assert store.get_chat(db_path, "alice", chat_id)["title"] == "My renamed chat"
```

Add to `chat_app/tests/test_router.py`:

```python
def test_run_chat_forwards_chat_id_to_manually_selected_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude", None, None, "chat-123")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], None, None, chat_id="chat-123")


def test_run_chat_automatic_forwards_chat_id(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with _patch_run_chat("openai", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto", chat_id="chat-123")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id="chat-123")
```

Then update these existing `test_router.py` assertions (each currently checks the exact positional/keyword call `router.run_chat` makes into a provider's `run_chat` — the call shape now always includes `chat_id`):

```python
def test_run_chat_dispatches_to_requested_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], None, None, chat_id=None)


def test_run_chat_forwards_model_id_to_manually_selected_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude opus", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude", "claude-opus-4-8")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], "claude-opus-4-8", None, chat_id=None)


def test_run_chat_forwards_enabled_extensions_to_manually_selected_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "claude", "claude-opus-4-8", ["reference"])

    assert result is expected
    mock_run.assert_called_once_with("hello", [], "claude-opus-4-8", ["reference"], chat_id=None)


def test_run_chat_defaults_to_automatic_when_provider_not_specified(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with _patch_run_chat("openai", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], None)

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id=None)


def test_run_chat_automatic_falls_back_to_claude_when_openai_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id=None)


def test_run_chat_automatic_falls_back_when_openai_is_cooling_down(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cooldown.start_cooldown("openai", seconds=30)
    expected = ChatResult(response="from claude", tools_used=[], provider_id="claude")

    with _patch_run_chat("claude", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto")

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=None, chat_id=None)


def test_run_chat_automatic_forwards_enabled_extensions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    expected = ChatResult(response="from openai", tools_used=[], provider_id="openai")

    with _patch_run_chat("openai", return_value=expected) as mock_run:
        result = router.run_chat("hello", [], "auto", enabled_extensions=["reference"])

    assert result is expected
    mock_run.assert_called_once_with("hello", [], enabled_extensions=["reference"], chat_id=None)
```

Update these existing `test_chat_routes.py` assertions (chat_id is now minted before the call, so it's a real value, not omitted — assert against `body["chat_id"]` computed from the response):

```python
def test_api_chat_returns_run_chat_result(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(
            response="web-1 is running normally.",
            tools_used=["get_host_health"],
            provider_id="claude",
            model="claude-opus-4-8",
            total_tokens=1234,
        )
        response = client.post(
            "/api/chat",
            json={"question": "how is web-1 doing?", "history": [], "provider": "claude", "model": "claude-opus-4-8"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "web-1 is running normally."
    assert body["tools_used"] == ["get_host_health"]
    assert body["provider_id"] == "claude"
    assert body["model"] == "claude-opus-4-8"
    assert body["total_tokens"] == 1234
    assert body["elapsed_seconds"] >= 0
    assert body["chat_id"] is not None
    mock_run_chat.assert_called_once_with(
        "how is web-1 doing?", [], "claude", "claude-opus-4-8", [], chat_id=body["chat_id"]
    )
```

```python
def test_api_chat_defaults_provider_and_model_to_none_when_omitted(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    mock_run_chat.assert_called_once_with("hello", [], None, None, [], chat_id=body["chat_id"])


def test_api_chat_forwards_enabled_extensions_to_router(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        response = client.post(
            "/api/chat",
            json={"question": "hello", "enabled_extensions": ["reference"]},
        )

    body = response.get_json()
    mock_run_chat.assert_called_once_with("hello", [], None, None, ["reference"], chat_id=body["chat_id"])
```

Add a new test proving the id is minted *before* the LLM call, not after:

```python
def test_api_chat_mints_a_chat_id_before_calling_the_llm(client, chats_db):
    """The staged pipeline (a later feature) needs a stable chat_id to
    pause a plan against - it must exist before router.run_chat is
    called, not only be assigned afterward by chats_store.save_chat."""
    seen_chat_id = {}

    def _capture(*args, **kwargs):
        seen_chat_id["value"] = kwargs.get("chat_id")
        return ChatResult(response="ok", provider_id="openai")

    with patch("chat_app.services.llm.router.run_chat", side_effect=_capture):
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    assert seen_chat_id["value"] is not None
    assert seen_chat_id["value"] == body["chat_id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_chats_store.py tests/test_router.py tests/test_chat_routes.py -v
```
Expected: FAIL — `TypeError: run_chat() got an unexpected keyword argument 'chat_id'` and the new/updated assertions mismatching today's call shape.

- [ ] **Step 3: Fix `chats_store.save_chat`'s UPDATE branch**

In `chat_app/src/chat_app/chats/store.py`, find:

```python
        updated = conn.execute(
            "UPDATE chats SET messages = ?, updated_at = ? WHERE id = ? AND username = ?",
            (messages_json, now, chat_id, username),
        ).rowcount
```

Replace with:

```python
        # title is only replaced when it's still the "New chat" placeholder
        # - a chat created with an empty transcript up front (see
        # pages/chat/routes.py's early chat_id minting) gets that
        # placeholder on INSERT, and this is where it becomes a real title
        # once the first real transcript arrives. A title the user set via
        # rename_chat is anything else and must survive every later save.
        updated = conn.execute(
            "UPDATE chats SET messages = ?, updated_at = ?, "
            "title = CASE WHEN title = 'New chat' THEN ? ELSE title END "
            "WHERE id = ? AND username = ?",
            (messages_json, now, _derive_title(messages), chat_id, username),
        ).rowcount
```

- [ ] **Step 4: Thread `chat_id` through `base.py`, `router.py`, and every provider**

In `chat_app/src/chat_app/services/llm/base.py`, find:

```python
# model is optional - None means "use this provider's own default".
# enabled_extensions is optional - None/empty means "no extension tools",
# the same safe default list_tools() itself applies (see mcp_client.py).
RunChatFn = Callable[[str, list[dict[str, Any]], "str | None", "list[str] | None"], ChatResult]
```

Replace with:

```python
# model is optional - None means "use this provider's own default".
# enabled_extensions is optional - None/empty means "no extension tools",
# the same safe default list_tools() itself applies (see mcp_client.py).
# chat_id is optional - None means no persisted conversation exists yet
# for this turn. Only staged_pipeline.py (see ollama_provider.py) actually
# reads it, to pause/resume a plan across turns - every other provider
# accepts and ignores it, keeping one shared call signature across every
# ProviderSpec.
RunChatFn = Callable[[str, list[dict[str, Any]], "str | None", "list[str] | None", "str | None"], ChatResult]
```

In `chat_app/src/chat_app/services/llm/router.py`, find:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    provider_id: str | None,
    model_id: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
    provider_id = provider_id or DEFAULT_PROVIDER_ID

    if provider_id == AUTOMATIC_ID:
        # Automatic doesn't take a model override - whichever provider it
        # resolves to uses its own default. Mixing "pick any provider" with
        # "but insist on this specific model" gets confusing fast, and the
        # model dropdown is hidden client-side whenever Automatic is
        # selected for exactly this reason. enabled_extensions has nothing
        # to do with that - it still needs to reach whichever provider
        # gets picked, so it's forwarded by keyword here rather than
        # positionally (which would require also passing a model).
        provider = _pick_automatic()
        return provider.run_chat(question, history, enabled_extensions=enabled_extensions)

    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider '{provider_id}'")
    if not provider.has_api_key():
        raise ValueError(f"{provider.label} is not configured (missing API key)")
    if cooldown.is_in_cooldown(provider_id):
        remaining = int(cooldown.seconds_remaining(provider_id))
        raise ValueError(f"{provider.label} is rate-limited right now - try again in {remaining}s, or pick another provider")
    return provider.run_chat(question, history, model_id, enabled_extensions)
```

Replace with:

```python
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
```

In `chat_app/src/chat_app/services/llm/openai_provider.py`, find:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
```

Replace with:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    chat_id: str | None = None,  # unused here - see base.py's RunChatFn comment
) -> ChatResult:
```

In `chat_app/src/chat_app/services/llm/claude_provider.py`, find:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
```

Replace with:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    chat_id: str | None = None,  # unused here - see base.py's RunChatFn comment
) -> ChatResult:
```

In `chat_app/src/chat_app/services/llm/ollama_provider.py`, find:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
) -> ChatResult:
```

Replace with:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    chat_id: str | None = None,  # read only by the staged_pipeline branch, added in a later task
) -> ChatResult:
```

- [ ] **Step 5: Mint `chat_id` early in `chat_api`**

In `chat_app/src/chat_app/pages/chat/routes.py`, find:

```python
    llm_history = [{"role": m.get("role"), "content": m.get("content")} for m in data.get("history", [])]
    start = time.monotonic()
    try:
        result = router.run_chat(
            question,
            llm_history,
            data.get("provider"),
            data.get("model"),
            data.get("enabled_extensions", []),
        )
```

Replace with:

```python
    llm_history = [{"role": m.get("role"), "content": m.get("content")} for m in data.get("history", [])]
    # Minted before the LLM call, not only after (as this endpoint used to
    # do), so a staged-pipeline model (see staged_pipeline.py) that pauses
    # mid-turn on an ask_user step has a stable chat_id to persist its
    # paused plan against - and so the very next request (this chat's
    # reply to that question) can find it. An empty transcript is created
    # immediately for a brand-new chat rather than only generating an id
    # string, because chats_store.save_chat's contract is "None creates, a
    # given id updates (raising UnknownChat if it doesn't exist yet)" -
    # passing a not-yet-persisted id straight to the later update call
    # would raise UnknownChat against its own id.
    chat_id = data.get("chat_id")
    if chat_id is None:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, service.current_username(), None, [])
        except Exception as error:  # noqa: BLE001 - persistence must not block the chat answer itself
            report(error, context="starting a new chat")
            chat_id = None
    start = time.monotonic()
    try:
        result = router.run_chat(
            question,
            llm_history,
            data.get("provider"),
            data.get("model"),
            data.get("enabled_extensions", []),
            chat_id=chat_id,
        )
```

Then find the later block:

```python
    transcript = history_in + current_turn + [assistant_entry]
    chat_id = data.get("chat_id")
    try:
        chat_id = chats_store.save_chat(settings.chats_db_path, service.current_username(), chat_id, transcript)
```

Replace with (removing the now-redundant `chat_id = data.get("chat_id")` line — `chat_id` is already correctly set from Step 5's early mint, or from the client-supplied value if one was given):

```python
    transcript = history_in + current_turn + [assistant_entry]
    try:
        chat_id = chats_store.save_chat(settings.chats_db_path, service.current_username(), chat_id, transcript)
```

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_chats_store.py tests/test_router.py tests/test_chat_routes.py tests/test_llm_providers.py -v
```
Expected: PASS — all of `test_chats_store.py`, `test_router.py`, `test_chat_routes.py`, and every existing `test_llm_providers.py` test (each provider's `run_chat` still works with no `chat_id` argument, since it now defaults to `None`).

- [ ] **Step 7: Commit**

```bash
git add chat_app/src/chat_app/services/llm/base.py chat_app/src/chat_app/services/llm/router.py chat_app/src/chat_app/services/llm/openai_provider.py chat_app/src/chat_app/services/llm/claude_provider.py chat_app/src/chat_app/services/llm/ollama_provider.py chat_app/src/chat_app/chats/store.py chat_app/src/chat_app/pages/chat/routes.py chat_app/tests/test_chats_store.py chat_app/tests/test_router.py chat_app/tests/test_chat_routes.py
git commit -m "feat: mint chat_id before the LLM call and thread it through run_chat"
```

---

## Task 6: `staged_pipeline.py` — tool filter phase

**Files:**
- Create: `chat_app/src/chat_app/services/llm/staged_pipeline.py`
- Test: `chat_app/tests/test_staged_pipeline.py`

**Interfaces:**
- Produces: `_filter_tools(tools: list[Any], question: str) -> list[Any]`, `_MAX_FILTERED_TOOLS` constant. Consumed by Task 7's `_enumerate_plan` and Task 8's `_execute_tool_call_step`.

- [ ] **Step 1: Write the failing tests**

Create `chat_app/tests/test_staged_pipeline.py`:

```python
"""Tests for services/llm/staged_pipeline.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from chat_app.services.llm import staged_pipeline


def _tool(name: str, keywords: list[str] | None = None):
    meta = {"keywords": keywords} if keywords is not None else None
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        meta=meta,
        inputSchema={"type": "object", "properties": {}},
    )


def test_filter_tools_keeps_a_tool_whose_keyword_matches_the_question():
    health = _tool("get_host_health_tool", keywords=["disk", "cpu", "memory", "health"])
    otp = _tool("request_otp_tool", keywords=["otp", "passcode", "verify"])

    result = staged_pipeline._filter_tools([health, otp], "how is the cpu doing on zima?")

    assert result == [health]


def test_filter_tools_is_case_insensitive():
    health = _tool("get_host_health_tool", keywords=["CPU"])

    result = staged_pipeline._filter_tools([health], "check cpu usage")

    assert result == [health]


def test_filter_tools_keeps_a_tool_with_no_declared_keywords_fail_open():
    """An unannotated tool (no meta at all, e.g. an extension author who
    never adopted the keywords convention) must never become silently
    uncallable just because nothing was declared."""
    unlabeled = _tool("some_extension_tool", keywords=None)

    result = staged_pipeline._filter_tools([unlabeled], "totally unrelated question")

    assert result == [unlabeled]


def test_filter_tools_drops_a_labeled_tool_with_no_overlap():
    otp = _tool("request_otp_tool", keywords=["otp", "passcode"])

    result = staged_pipeline._filter_tools([otp], "how is the cpu doing?")

    assert result == []


def test_filter_tools_ranks_more_matches_first():
    weak_match = _tool("weak", keywords=["cpu", "unrelated1", "unrelated2"])
    strong_match = _tool("strong", keywords=["cpu", "memory", "disk"])

    result = staged_pipeline._filter_tools([weak_match, strong_match], "cpu memory disk usage")

    assert result == [strong_match, weak_match]


def test_filter_tools_caps_the_kept_set():
    tools = [_tool(f"tool_{i}", keywords=["health"]) for i in range(staged_pipeline._MAX_FILTERED_TOOLS + 3)]

    result = staged_pipeline._filter_tools(tools, "health check")

    assert len(result) == staged_pipeline._MAX_FILTERED_TOOLS


def test_filter_tools_empty_meta_dict_is_treated_as_no_keywords():
    tool = _tool("edge_case_tool")
    tool.meta = {}

    result = staged_pipeline._filter_tools([tool], "anything")

    assert result == [tool]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chat_app.services.llm.staged_pipeline'`.

- [ ] **Step 3: Implement the filter phase**

Create `chat_app/src/chat_app/services/llm/staged_pipeline.py`:

```python
"""Staged enumerate-execute-conclude pipeline for Ollama models that opt in
via ModelOption.staged_pipeline (see infra/app_config.py). Replaces
ollama_provider.py's single _tool_loop with five phases - Resume check,
Filter, Enumerate, Execute, Conclude - each a small, separately-billed
Ollama call, so no individual request needs a weak model's full reasoning
budget. See
docs/superpowers/specs/2026-08-17-ollama-staged-pipeline-design.md for the
full design.
"""

from __future__ import annotations

from typing import Any


# Caps the Filter phase's own output - the point is keeping the Enumerate
# phase's prompt small (see module docstring), not just narrowing
# relevance.
_MAX_FILTERED_TOOLS = 8


def _tool_keywords(tool: Any) -> list[str]:
    """A tool with no `meta`, or a `meta` without a "keywords" entry, both
    mean "not annotated" - not "no keywords" - see _filter_tools for why
    that's treated as always-relevant (fail open) rather than
    always-excluded."""
    meta = getattr(tool, "meta", None) or {}
    keywords = meta.get("keywords")
    return keywords if isinstance(keywords, list) else []


def _filter_tools(tools: list[Any], question: str) -> list[Any]:
    """Deterministic, dependency-free relevance filter: lowercase-tokenize
    `question`, keep any tool with at least one token in common with its
    own declared keywords, plus every tool with no declared keywords at
    all (fail-open - an unannotated extension tool must never become
    silently uncallable just because nobody keyword-tagged it, it's only
    less tightly filtered). Ranks matched tools by match count (most
    relevant first; Python's sort is stable, so ties keep original order),
    unlabeled tools after those, and caps the combined list at
    _MAX_FILTERED_TOOLS - bounding the Enumerate phase's own prompt is the
    actual point of this filter, so the cap applies even to fail-open
    tools.
    """
    question_tokens = set(question.lower().split())

    scored: list[tuple[int, Any]] = []
    unlabeled: list[Any] = []
    for tool in tools:
        keywords = _tool_keywords(tool)
        if not keywords:
            unlabeled.append(tool)
            continue
        match_count = len({keyword.lower() for keyword in keywords} & question_tokens)
        if match_count > 0:
            scored.append((match_count, tool))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [tool for _, tool in scored] + unlabeled
    return ranked[:_MAX_FILTERED_TOOLS]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/chat_app/services/llm/staged_pipeline.py chat_app/tests/test_staged_pipeline.py
git commit -m "feat: add staged_pipeline's deterministic tool filter phase"
```

---

## Task 7: `staged_pipeline.py` — Enumerate phase

**Files:**
- Modify: `chat_app/src/chat_app/services/llm/staged_pipeline.py`
- Test: `chat_app/tests/test_staged_pipeline.py`

**Interfaces:**
- Consumes: `_filter_tools` (Task 6).
- Produces: `_enumerate_plan(client, model_name, question, filtered_tools) -> list[dict[str, str]]`, `_MAX_PLAN_STEPS`, `_STEP_TYPES`, `_fallback_plan`, `_parse_plan`, `_NUM_CTX`/`_NUM_PREDICT`. Consumed by Task 8's execute functions and Task 9's `run()`.

- [ ] **Step 1: Write the failing tests**

Add to `chat_app/tests/test_staged_pipeline.py` (add `import json` to the top of the file alongside the existing imports):

```python
def test_enumerate_plan_parses_a_valid_json_plan():
    plan_json = json.dumps(
        [
            {"type": "tool_call", "detail": "check zima's health"},
            {"type": "reasoning", "detail": "summarize the result"},
        ]
    )
    message = SimpleNamespace(content=plan_json)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "how is zima?", [])

    assert plan == [
        {"type": "tool_call", "detail": "check zima's health"},
        {"type": "reasoning", "detail": "summarize the result"},
    ]


def test_enumerate_plan_falls_back_on_unparsable_json():
    message = SimpleNamespace(content="not json at all")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "how is zima?", [])

    assert plan == [{"type": "tool_call", "detail": "how is zima?"}]


def test_enumerate_plan_falls_back_when_step_count_exceeds_the_cap():
    oversized = json.dumps(
        [{"type": "reasoning", "detail": f"step {i}"} for i in range(staged_pipeline._MAX_PLAN_STEPS + 1)]
    )
    message = SimpleNamespace(content=oversized)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "q", [])

    assert plan == [{"type": "tool_call", "detail": "q"}]


def test_enumerate_plan_falls_back_on_an_unrecognized_step_type():
    bad = json.dumps([{"type": "do_a_backflip", "detail": "??"}])
    message = SimpleNamespace(content=bad)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "q", [])

    assert plan == [{"type": "tool_call", "detail": "q"}]


def test_enumerate_plan_falls_back_on_an_empty_plan():
    message = SimpleNamespace(content="[]")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    plan = staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "q", [])

    assert plan == [{"type": "tool_call", "detail": "q"}]


def test_enumerate_plan_sends_filtered_tool_names_and_descriptions_only():
    """Enumerate's own request must stay small - full JSON schemas aren't
    sent, just name + description (see module docstring)."""
    tool = _tool("get_host_health_tool", keywords=None)
    tool.description = "Check CPU, memory, disk."
    message = SimpleNamespace(content="[]")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_create = Mock(return_value=response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    staged_pipeline._enumerate_plan(fake_client, "phi4-mini:latest", "how is zima?", [tool])

    _, kwargs = fake_create.call_args
    user_message = kwargs["messages"][1]["content"]
    assert "get_host_health_tool" in user_message
    assert "Check CPU, memory, disk." in user_message
    assert "inputSchema" not in user_message and "properties" not in user_message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py -v -k enumerate`
Expected: FAIL — `AttributeError: module 'chat_app.services.llm.staged_pipeline' has no attribute '_enumerate_plan'`.

- [ ] **Step 3: Implement the Enumerate phase**

In `chat_app/src/chat_app/services/llm/staged_pipeline.py`, add `import json` to the imports at the top, then append after `_filter_tools`:

```python
# Mirrors ollama_provider.py's own tuning (not imported from there -
# ollama_provider.py imports this module to dispatch into it, so the
# reverse import would be circular). Same values, same reasoning: Ollama's
# small default context window needs raising, and nothing bounds a
# hallucinating small model's completion length by default - see
# ollama_provider.py's module-level comments on _NUM_CTX/_NUM_PREDICT for
# the full story.
_NUM_CTX = 8192
_NUM_PREDICT = 1024

# Caps the Enumerate phase's own output.
_MAX_PLAN_STEPS = 8

_STEP_TYPES = {"tool_call", "reasoning", "ask_user"}

_ENUMERATE_SYSTEM_PROMPT = (
    "You are planning how to answer a question, not answering it yet. "
    "Given the question and the tools available, return a JSON array of "
    "steps needed to answer it - nothing else, no prose before or after "
    "the array. Each step is an object: "
    '{"type": "tool_call" | "reasoning" | "ask_user", "detail": "..."}. '
    'Use "tool_call" for a step that needs one of the listed tools (name '
    'the tool and what to pass it in detail). Use "reasoning" for a step '
    'that just needs you to think something through with no tool. Use '
    '"ask_user" for a step where you must ask the user a question before '
    "you can continue - detail is the exact question to ask. Keep the "
    "plan short: as few steps as the question actually needs."
)


def _tool_summaries(tools: list[Any]) -> str:
    return "\n".join(f"- {tool.name}: {tool.description or ''}" for tool in tools)


def _fallback_plan(question: str) -> list[dict[str, str]]:
    """A single tool_call step wrapping the raw question - what a plan
    degrades to whenever Enumerate's response can't be trusted (unparsable
    JSON, wrong shape, too many steps, an unrecognized step type). Never a
    hard failure - same "degrade into something usable" spirit as
    ollama_provider._extract_fallback_tool_call."""
    return [{"type": "tool_call", "detail": question}]


def _parse_plan(content: str, question: str) -> list[dict[str, str]]:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return _fallback_plan(question)

    if not isinstance(parsed, list) or not parsed or len(parsed) > _MAX_PLAN_STEPS:
        return _fallback_plan(question)

    steps: list[dict[str, str]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            return _fallback_plan(question)
        step_type = entry.get("type")
        detail = entry.get("detail")
        if step_type not in _STEP_TYPES or not isinstance(detail, str) or not detail.strip():
            return _fallback_plan(question)
        steps.append({"type": step_type, "detail": detail})
    return steps


def _enumerate_plan(client: Any, model_name: str, question: str, filtered_tools: list[Any]) -> list[dict[str, str]]:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _ENUMERATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Tools available:\n{_tool_summaries(filtered_tools)}\n\nQuestion: {question}",
            },
        ],
        extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
    )
    content = response.choices[0].message.content or ""
    return _parse_plan(content, question)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/chat_app/services/llm/staged_pipeline.py chat_app/tests/test_staged_pipeline.py
git commit -m "feat: add staged_pipeline's Enumerate phase"
```

---

## Task 8: `staged_pipeline.py` — Execute phase

**Files:**
- Modify: `chat_app/src/chat_app/services/llm/staged_pipeline.py`
- Test: `chat_app/tests/test_staged_pipeline.py`

**Interfaces:**
- Consumes: `_filter_tools` (Task 6), `_STEP_TYPES`, `_NUM_CTX`/`_NUM_PREDICT` (Task 7), `chat_app.services.llm.base.ToolCallRecord`, `chat_app.services.mcp_client.call_tool`.
- Produces: `_AskUserPause` dataclass (`step_index`, `question`), `_execute_steps(client, model_name, all_tools, plan, step_index, results, tools_used, tool_calls_log, calls_budget) -> tuple[_AskUserPause | None, int]`, `_results_summary`. Consumed by Task 9's `run()`.

- [ ] **Step 1: Write the failing tests**

Add to `chat_app/tests/test_staged_pipeline.py` (add `from unittest.mock import patch` — already imported — and `from chat_app.services.llm.base import ToolCallRecord` to the top):

```python
def test_execute_steps_runs_a_tool_call_step_and_records_the_result():
    tool = _tool("get_host_health_tool", keywords=["health"])
    plan = [{"type": "tool_call", "detail": "check zima's health"}]
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_host_health_tool", arguments="{}"))
    round_one = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])
    round_two = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="zima is healthy", tool_calls=None))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    )
    tools_used: list[str] = []
    tool_calls_log: list[ToolCallRecord] = []
    results: list = []

    with patch("chat_app.services.llm.staged_pipeline.call_tool", return_value="cpu 12%") as mock_call_tool:
        pause, calls_used = staged_pipeline._execute_steps(
            fake_client, "phi4-mini:latest", [tool], plan, 0, results, tools_used, tool_calls_log, calls_budget=10,
        )

    assert pause is None
    assert calls_used == 1
    assert results == [{"detail": "check zima's health", "result": "zima is healthy"}]
    assert tools_used == ["get_host_health_tool"]
    mock_call_tool.assert_called_once_with("get_host_health_tool", {})


def test_execute_steps_stops_and_returns_a_pause_on_ask_user():
    plan = [
        {"type": "reasoning", "detail": "think about it"},
        {"type": "ask_user", "detail": "which host do you mean?"},
        {"type": "reasoning", "detail": "never reached"},
    ]
    reasoning_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="thought"))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=reasoning_response)))
    )
    results: list = []

    pause, calls_used = staged_pipeline._execute_steps(
        fake_client, "phi4-mini:latest", [], plan, 0, results, [], [], calls_budget=10,
    )

    assert pause == staged_pipeline._AskUserPause(step_index=1, question="which host do you mean?")
    assert calls_used == 1  # only the reasoning step before the pause
    assert results == [{"detail": "think about it", "result": "thought"}]


def test_execute_steps_resumes_from_the_given_step_index():
    plan = [
        {"type": "ask_user", "detail": "already answered"},
        {"type": "reasoning", "detail": "continue here"},
    ]
    reasoning_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done"))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=reasoning_response)))
    )
    results = [{"detail": "already answered", "result": "the user's answer"}]

    pause, calls_used = staged_pipeline._execute_steps(
        fake_client, "phi4-mini:latest", [], plan, 1, results, [], [], calls_budget=10,
    )

    assert pause is None
    assert calls_used == 1
    assert results[-1] == {"detail": "continue here", "result": "done"}


def test_execute_steps_stops_at_the_call_budget_without_erroring():
    plan = [{"type": "reasoning", "detail": f"step {i}"} for i in range(5)]
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))
    results: list = []

    pause, calls_used = staged_pipeline._execute_steps(
        fake_client, "phi4-mini:latest", [], plan, 0, results, [], [], calls_budget=2,
    )

    assert pause is None
    assert calls_used == 2
    assert len(results) == 2


def test_execute_tool_call_step_recovers_from_a_failing_tool():
    tool = _tool("get_host_health_tool", keywords=None)
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_host_health_tool", arguments="{}"))
    round_one = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])
    round_two = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="couldn't check, but here's what I know", tool_calls=None))
        ]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=[round_one, round_two])))
    )

    with patch("chat_app.services.llm.staged_pipeline.call_tool", side_effect=RuntimeError("connection refused")):
        result = staged_pipeline._execute_tool_call_step(fake_client, "phi4-mini:latest", "check zima", [tool], [], [])

    assert result == "couldn't check, but here's what I know"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py -v -k execute`
Expected: FAIL — `AttributeError: module 'chat_app.services.llm.staged_pipeline' has no attribute '_execute_steps'`.

- [ ] **Step 3: Implement the Execute phase**

In `chat_app/src/chat_app/services/llm/staged_pipeline.py`, add these imports at the top alongside the existing ones:

```python
from dataclasses import dataclass

from chat_app.services.llm.base import ToolCallRecord
from chat_app.services.mcp_client import call_tool
```

Then append after `_enumerate_plan`:

```python
_MAX_STEP_TOOL_ROUNDS = 6  # mirrors ollama_provider._MAX_TOOL_CALL_ROUNDS's value

_EXECUTE_TOOL_CALL_SYSTEM_PROMPT = (
    "Complete this one step of a larger plan. Call a tool if it helps; "
    "otherwise answer directly. Be concise - this result feeds a later "
    "step, not the user."
)


def _tool_schemas_for(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def _execute_tool_call_step(
    client: Any,
    model_name: str,
    detail: str,
    all_tools: list[Any],
    tools_used: list[str],
    tool_calls_log: list[ToolCallRecord],
) -> str:
    """Runs one bounded tool-calling round trip for a single plan step,
    scoped to just this step's own filtered tools (tighter than the
    original question - see _filter_tools) - small-context is the whole
    point of breaking Execute into per-step calls (see module docstring).
    Returns the step's result text: either the model's own plain-text
    reply (no tool needed after all), or a summary of the tool result(s)
    it actually called.
    """
    step_tools = _filter_tools(all_tools, detail)
    tool_schemas = _tool_schemas_for(step_tools)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _EXECUTE_TOOL_CALL_SYSTEM_PROMPT},
        {"role": "user", "content": detail},
    ]

    for _ in range(_MAX_STEP_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            return message.content or ""

        messages.append({"role": "assistant", "content": message.content, "tool_calls": tool_calls})
        for call in tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except Exception:
                arguments = {}
            tools_used.append(call.function.name)
            try:
                result_text = call_tool(call.function.name, arguments)
            except Exception as error:
                result_text = f"Tool '{call.function.name}' failed: {error}"
            tool_calls_log.append(ToolCallRecord(name=call.function.name, arguments=arguments, result=result_text))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})

    return "Reached maximum tool-call rounds for this step without a final answer."


def _results_summary(results: list[dict[str, Any]]) -> str:
    if not results:
        return "(none yet)"
    return "\n".join(f"- {r['detail']}: {r['result']}" for r in results)


def _execute_reasoning_step(client: Any, model_name: str, detail: str, prior_results_summary: str) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Complete this one reasoning step of a larger plan, concisely."},
            {"role": "user", "content": f"Prior results so far:\n{prior_results_summary}\n\nThis step: {detail}"},
        ],
        extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
    )
    return response.choices[0].message.content or ""


@dataclass
class _AskUserPause:
    step_index: int
    question: str


def _execute_steps(
    client: Any,
    model_name: str,
    all_tools: list[Any],
    plan: list[dict[str, str]],
    step_index: int,
    results: list[dict[str, Any]],
    tools_used: list[str],
    tool_calls_log: list[ToolCallRecord],
    calls_budget: int,
) -> tuple["_AskUserPause | None", int]:
    """Walks `plan` from `step_index` onward, appending each step's
    {"detail", "result"} to `results` in place. Stops early, without
    consuming a step, once `calls_budget` calls have been made - the
    overall per-turn call budget (see run() in a later task) - leaving
    whatever steps didn't run simply absent from `results`; Conclude still
    works from whatever's there. A tool_call step's own internal rounds
    (see _execute_tool_call_step) are bounded separately by
    _MAX_STEP_TOOL_ROUNDS and only ever count as one call against this
    budget, to keep the budget accounting simple.

    Returns (pause_or_none, calls_used) - calls_used is how many
    Execute-phase steps this invocation actually completed, for the caller
    to subtract from its own remaining per-turn budget.
    """
    calls_used = 0
    for index in range(step_index, len(plan)):
        if calls_used >= calls_budget:
            break
        step = plan[index]

        if step["type"] == "ask_user":
            return _AskUserPause(step_index=index, question=step["detail"]), calls_used

        if step["type"] == "tool_call":
            result_text = _execute_tool_call_step(
                client, model_name, step["detail"], all_tools, tools_used, tool_calls_log
            )
        else:  # "reasoning" - the only remaining member of _STEP_TYPES
            result_text = _execute_reasoning_step(client, model_name, step["detail"], _results_summary(results))

        calls_used += 1
        results.append({"detail": step["detail"], "result": result_text})

    return None, calls_used
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/chat_app/services/llm/staged_pipeline.py chat_app/tests/test_staged_pipeline.py
git commit -m "feat: add staged_pipeline's Execute phase, including ask_user pause"
```

---

## Task 9: `staged_pipeline.py` — Conclude phase, `run()`, and wiring into `ollama_provider`

**Files:**
- Modify: `chat_app/src/chat_app/services/llm/staged_pipeline.py`
- Modify: `chat_app/src/chat_app/services/llm/ollama_provider.py`
- Test: `chat_app/tests/test_staged_pipeline.py`, `chat_app/tests/test_llm_providers.py`

**Interfaces:**
- Consumes: everything from Tasks 6-8, plus `staged_plans_store` (Task 3) and `ModelOption.staged_pipeline` (Task 4).
- Produces: `_conclude(client, model_name, question, results) -> str`, `run(client, question, history, model_name, chat_id, enabled_extensions, db_path) -> ChatResult` — the pipeline's public entry point, called from `ollama_provider.run_chat()`.

- [ ] **Step 1: Write the failing tests**

Add to `chat_app/tests/test_staged_pipeline.py` (add `from pathlib import Path` and `from chat_app.services.llm import staged_plans_store` to the top):

```python
def test_run_full_happy_path_with_no_ask_user_step(tmp_path: Path):
    plan_json = json.dumps([{"type": "reasoning", "detail": "think"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    execute_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="thought result"))])
    conclude_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Here is your answer."))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(side_effect=[enumerate_response, execute_response, conclude_response])
            )
        )
    )
    db = tmp_path / "staged_plans.db"

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "how is zima?", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "Here is your answer."
    assert result.provider_id == "ollama"
    assert staged_plans_store.get(db, "chat-1") is None  # nothing left paused


def test_run_pauses_on_ask_user_and_persists_the_plan(tmp_path: Path):
    plan_json = json.dumps([{"type": "ask_user", "detail": "which host do you mean?"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=enumerate_response)))
    )
    db = tmp_path / "staged_plans.db"

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "check my host", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "which host do you mean?"
    saved = staged_plans_store.get(db, "chat-1")
    assert saved is not None
    assert saved.step_index == 0
    assert saved.model == "phi4-mini:latest"


def test_run_resumes_a_paused_plan_and_completes_it(tmp_path: Path):
    db = tmp_path / "staged_plans.db"
    plan = [
        {"type": "ask_user", "detail": "which host do you mean?"},
        {"type": "reasoning", "detail": "summarize"},
    ]
    staged_plans_store.save(db, "chat-1", "ollama", "phi4-mini:latest", plan, 0, [])
    execute_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="summarized"))])
    conclude_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Final answer about zima."))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock(side_effect=[execute_response, conclude_response]))
        )
    )

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "zima", [], "phi4-mini:latest", "chat-1", None, db)

    assert result.response == "Final answer about zima."
    assert staged_plans_store.get(db, "chat-1") is None


def test_run_discards_a_resume_row_saved_under_a_different_model(tmp_path: Path):
    """A paused plan saved under one model, then resumed after the user
    switched models, must not be silently continued under the new
    model's assumptions."""
    db = tmp_path / "staged_plans.db"
    staged_plans_store.save(db, "chat-1", "ollama", "phi4-mini:latest", [{"type": "ask_user", "detail": "q"}], 0, [])
    plan_json = json.dumps([{"type": "reasoning", "detail": "fresh plan"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    execute_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fresh result"))])
    conclude_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fresh answer"))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(side_effect=[enumerate_response, execute_response, conclude_response])
            )
        )
    )

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "new question", [], "qwen2.5:7b", "chat-1", None, db)

    assert result.response == "fresh answer"


def test_run_with_no_chat_id_still_answers_an_ask_user_pause_but_cannot_persist(tmp_path: Path):
    plan_json = json.dumps([{"type": "ask_user", "detail": "which host?"}])
    enumerate_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_json))])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=enumerate_response)))
    )
    db = tmp_path / "staged_plans.db"

    with patch("chat_app.services.llm.staged_pipeline.list_tools", return_value=[]):
        result = staged_pipeline.run(fake_client, "check my host", [], "phi4-mini:latest", None, None, db)

    assert result.response == "which host?"
    assert not db.exists()  # nothing to persist against - no chat_id
```

Add to `chat_app/tests/test_llm_providers.py`:

```python
def test_ollama_run_chat_dispatches_to_staged_pipeline_when_enabled(monkeypatch):
    monkeypatch.setattr(
        ollama_provider, "MODELS", [ModelOption(id="phi4-mini:latest", label="Phi 4 Mini", staged_pipeline=True)]
    )
    monkeypatch.setattr(ollama_provider, "_DEFAULT_MODEL_ID", "phi4-mini:latest")
    fake_result = ChatResult(response="from staged pipeline", provider_id="ollama", model="phi4-mini:latest")

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=SimpleNamespace()), \
         patch("chat_app.services.llm.ollama_provider.staged_pipeline.run", return_value=fake_result) as mock_run:
        result = ollama_provider.run_chat("hi", [], chat_id="chat-1")

    assert result.response == "from staged pipeline"
    args = mock_run.call_args[0]
    assert args[1] == "hi"        # question
    assert args[3] == "phi4-mini:latest"  # model_name
    assert args[4] == "chat-1"    # chat_id


def test_ollama_run_chat_uses_the_plain_tool_loop_when_staged_pipeline_disabled(monkeypatch):
    """Default behavior (staged_pipeline unset/False) must be unchanged -
    the plain _tool_loop path runs, staged_pipeline.run is never called."""
    monkeypatch.setattr(
        ollama_provider, "MODELS", [ModelOption(id="llama3.2:1b", label="Llama", staged_pipeline=False)]
    )
    monkeypatch.setattr(ollama_provider, "_DEFAULT_MODEL_ID", "llama3.2:1b")
    message = SimpleNamespace(content="ok", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

    with patch("chat_app.services.llm.ollama_provider._get_client", return_value=fake_client), \
         patch("chat_app.services.llm.ollama_provider.list_tools", return_value=[]), \
         patch("chat_app.services.llm.ollama_provider.staged_pipeline.run") as mock_staged_run:
        result = ollama_provider.run_chat("hi", [])

    assert result.response == "ok"
    mock_staged_run.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py tests/test_llm_providers.py -v -k "run or staged"
```
Expected: FAIL — `AttributeError: module 'chat_app.services.llm.staged_pipeline' has no attribute 'run'`, and `ollama_provider` has no `staged_pipeline` attribute yet.

- [ ] **Step 3: Implement the Conclude phase and `run()`**

In `chat_app/src/chat_app/services/llm/staged_pipeline.py`, add these imports at the top alongside the existing ones:

```python
from pathlib import Path

from chat_app.services.llm import staged_plans_store
from chat_app.services.llm.base import ChatResult
from chat_app.services.mcp_client import list_tools
```

Then append after `_execute_steps`:

```python
_MAX_TOTAL_CALLS = 20  # Enumerate + every Execute-phase step combined, this turn

_CONCLUDE_SYSTEM_PROMPT = (
    "Write the final answer to the user's original question, using the "
    "step results below. Plain, natural language only - never JSON, never "
    "a numbered step-by-step transcript. This is the only thing the user "
    "will see."
)


def _conclude(client: Any, model_name: str, question: str, results: list[dict[str, Any]]) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _CONCLUDE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Original question: {question}\n\nStep results:\n{_results_summary(results)}",
            },
        ],
        extra_body={"options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT}},
    )
    return response.choices[0].message.content or ""


def run(
    client: Any,
    question: str,
    history: list[dict[str, Any]],
    model_name: str,
    chat_id: str | None,
    enabled_extensions: list[str] | None,
    db_path: Path,
) -> ChatResult:
    """The pipeline's entry point - see module docstring for the five
    phases. `history` is intentionally unused here: each phase's own
    prompt is deliberately small (see module docstring), unlike
    ollama_provider._tool_loop's single continuous conversation, so the
    prior transcript plays no role in these calls. total_tokens is left at
    ChatResult's own default (None, meaning "not reported") - a known
    simplification for this first version rather than plumbing usage
    accumulation across five separate call sites.
    """
    tools_used: list[str] = []
    tool_calls_log: list[Any] = []
    all_tools = list_tools(enabled_extensions)

    resumed = staged_plans_store.get(db_path, chat_id) if chat_id else None
    if resumed is not None and resumed.model == model_name:
        plan = resumed.plan
        results = resumed.results
        # The paused ask_user step's own slot never got a result (that's
        # what paused it) - this turn's `question` IS the user's answer to
        # it, so it becomes that step's result before Execute continues.
        results.append({"detail": plan[resumed.step_index]["detail"], "result": question})
        step_index = resumed.step_index + 1
        calls_used_so_far = 1  # the paused turn's own Enumerate call
    else:
        # No resumable plan (none saved, expired, or saved under a
        # different model) - start fresh.
        filtered = _filter_tools(all_tools, question)
        plan = _enumerate_plan(client, model_name, question, filtered)
        results = []
        step_index = 0
        calls_used_so_far = 1  # the Enumerate call just made

    calls_budget = max(_MAX_TOTAL_CALLS - calls_used_so_far, 0)
    pause, _ = _execute_steps(
        client, model_name, all_tools, plan, step_index, results, tools_used, tool_calls_log, calls_budget
    )

    if pause is not None:
        # No chat_id means this pause can't be persisted - the question is
        # still returned as the answer (the turn still works), it just
        # can't be resumed automatically; the user's next message starts a
        # fresh Enumerate instead, which naturally treats their answer as
        # a new question.
        if chat_id:
            staged_plans_store.save(db_path, chat_id, "ollama", model_name, plan, pause.step_index, results)
        return ChatResult(
            response=pause.question,
            tools_used=tools_used,
            tool_calls=tool_calls_log,
            provider_id="ollama",
            model=model_name,
        )

    if chat_id:
        staged_plans_store.delete(db_path, chat_id)
    answer = _conclude(client, model_name, question, results)
    return ChatResult(
        response=answer,
        tools_used=tools_used,
        tool_calls=tool_calls_log,
        provider_id="ollama",
        model=model_name,
    )
```

- [ ] **Step 4: Wire `ollama_provider.run_chat` to dispatch to it**

In `chat_app/src/chat_app/services/llm/ollama_provider.py`, add this import alongside the existing ones:

```python
from chat_app.services.llm import staged_pipeline
```

Then find `_recursive_chain_enabled` and add a matching helper right after it:

```python
def _staged_pipeline_enabled(model_name: str) -> bool:
    for model in MODELS:
        if model.id == model_name:
            return model.staged_pipeline
    return False
```

Then find the start of `run_chat`:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    chat_id: str | None = None,  # read only by the staged_pipeline branch, added in a later task
) -> ChatResult:
    client = _get_client()
    system_content = f"{SYSTEM_PROMPT}\n\n{_LOCAL_MODEL_TOOL_GUIDANCE}"
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    model_name = model or _DEFAULT_MODEL_ID
    total_tokens: int | None = None
```

Replace with:

```python
def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    chat_id: str | None = None,
) -> ChatResult:
    client = _get_client()
    model_name = model or _DEFAULT_MODEL_ID

    if _staged_pipeline_enabled(model_name):
        return staged_pipeline.run(
            client, question, history, model_name, chat_id, enabled_extensions, settings.staged_plans_db_path
        )

    system_content = f"{SYSTEM_PROMPT}\n\n{_LOCAL_MODEL_TOOL_GUIDANCE}"
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}, *history]
    messages.append({"role": "user", "content": question})
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    tool_schemas = _tool_schemas(enabled_extensions)
    total_tokens: int | None = None
```

(The rest of `run_chat` below this point is unchanged — it already used `model_name`, which is now computed one line earlier than before.)

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd chat_app && ./venv_chat/Scripts/python -m pytest tests/test_staged_pipeline.py tests/test_llm_providers.py tests/test_chat_routes.py tests/test_router.py -v
```
Expected: PASS — every test in the suite, including every pre-existing `test_llm_providers.py` test (the non-staged path through `run_chat` must still behave exactly as before).

- [ ] **Step 6: Run the full test suite for both projects**

Run:
```bash
cd chat_app && ./venv_chat/Scripts/python -m pytest -v
cd mcp_server && ./venv_mcp/Scripts/python -m pytest -v
```
Expected: PASS, no regressions anywhere in either suite.

- [ ] **Step 7: Commit**

```bash
git add chat_app/src/chat_app/services/llm/staged_pipeline.py chat_app/src/chat_app/services/llm/ollama_provider.py chat_app/tests/test_staged_pipeline.py chat_app/tests/test_llm_providers.py
git commit -m "feat: add staged_pipeline's Conclude phase and wire it into ollama_provider"
```
