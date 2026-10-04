# ember Multi-Agent (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **ember_web gate (user's standing rule, overrides continuous execution):** every task whose ID starts with `W` changes ember_web. Before implementing one, the controller states the files it will create/change/delete and waits for the user's approval; it commits only after the user agrees. `E` tasks (ember_api) run without that gate. The user tests in the browser by hand: never launch browser-verification agents.

**Goal:** ember always talks to the main (entry) agent so the agent dropdown goes away, shows live which agent is working during a turn, and reports tokens per agent, provider and gateway with date and time.

**Architecture:** ember_api picks the entry agent from ai_agent's registry (`AgentDirectory.entry()`), ignores the browser's `agent_id`, relays Phase 1's `agent_start` / `agent_end` / `agent_token` events over the existing `/events` SSE stream (plus an `active_agents` list in the late-joiner snapshot), and stores Phase 1's richer `agent_usage` rows in new nullable `usage_records` columns. ember_web drops the picker, keeps a small entry-agent store for the label, adds an "Ember → Calculator" activity breadcrumb, per-agent step badges, and group-by/records views on the Usage page.

**Tech Stack:** Python 3.14, FastAPI, async SQLAlchemy 2 + Alembic (SQLite), pytest; Vue 3 + TypeScript, Pinia, Vitest, vue-tsc, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-04-ember-multi-agent-design.md` (contracts it builds on: `docs/superpowers/specs/2026-10-04-ai-agent-multi-agent-design.md`, already implemented and merged to `main`).

## Global Constraints

- Phase 1 is merged. The registry entries in `ai_agent/configs/config_agents.json` carry optional `entry` (bool), `orchestrator` (bool) and `focus` (str); a missing key reads as `false` / `false` / `""`.
- `AgentDirectory.entry()` order: the agent with `entry: true`; else the first with `orchestrator: true`; else the agent with id `claude-agent`; else `None`.
- No entry agent: new turns and summarize return `503` with detail exactly `No agent is running`.
- `TurnRequest.agent_id` and `SummarizeRequest.agent_id` stay accepted but are ignored. An existing chat's `agent_id` is rewritten to the entry agent's id by its next turn (already how `replace_messages(..., agent_id=...)` works).
- Remove `GET /api/agents`. Add `GET /api/agent` returning `{id, label}` (no URL), permission `chat.use`, `503 No agent is running` when none.
- Relayed event caps: `agent_start.question` at 500 characters, `agent_token.text` at 4,000 characters. `agent_token` text is never saved with the answer.
- Snapshot gains `active_agents: [{agent_id, label, since, step_id}]` (a stack: push on `agent_start`, remove the matching `step_id` on `agent_end`, cleared on `final` / `error`).
- A step is keyed by `(agent_id, id)` (nested specialist step ids can collide with the orchestrator's). Saved steps keep `agent_id` / `agent_label` when the event had them.
- `usage_records` gets nullable `agent_id` (String 120), `provider_id` (String 60), `gateway` (String 60), `started_at` (DateTime), `finished_at` (DateTime), `delegated_by` (String 120) via Alembic migration `0003`. The existing `agent` column holds `agent_id` for new rows when present, else `provider_id` (as today). Old rows are not rewritten. All times are naive UTC; the browser shows local time.
- Usage API: `GET /api/usage` gains `group_by` (`agent` default, `provider`, `gateway`, `model`), `agent`, `provider` filters and a `groups` list in `report`; `by_agent` stays unchanged. New `GET /api/usage/records` lists rows newest first with their times.
- POST bodies are JSON; `require_permission(CHAT_USE)` gates chat routes. Colors only via theme tokens (`--bg`, `--surface`, `--text`, `--muted`, `--border`, `--accent`, `--accent-contrast`, `--danger`, `--code-bg`, `--mono`). `tsconfig.app.json` has `erasableSyntaxOnly` (no constructor parameter properties, no enums). Markdown from a model only via `components/MarkdownContent.vue`.
- Commands: ember_api tests `ember_api\.venv_ember_api\Scripts\python -m pytest -q` run from `ember_api/`; ember_web `npx vitest run`, `npx vue-tsc -b --noEmit` (must print nothing) and `npx vite build` (then delete `dist/`) from `ember_web/`.
- Line endings: some files in this repo are CRLF (check with `file`). Preserve each file's endings; do not convert.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (or the model that implements). Work on branch `home`.

### Decisions made while planning (Task E7 writes them into the spec)

1. `GET /api/agent` (singular) is the entry-agent route; the spec's `GET /mcp/agent` meant the `/api/` prefix this app uses.
2. Saved answers from before this change keep their `agent` id (for example `openai-agent`); with the picker and `/api/agents` gone only the entry agent's label is known to the browser, so older ids show as the id.
3. The late-joiner snapshot's `active_agents` also carries `step_id` (the delegate step id) so the browser can attach specialist text to its step.
4. A new records endpoint is needed for "date and time per row": the existing report only has aggregates.
5. The entry-agent label comes from a small `stores/entryAgent.ts`; availability still comes from the agent's `status` tool through the existing proxy path.

---

## File Structure

**ember_api (new):** `tests/test_agent_directory.py`, `tests/test_agent_events.py`, `tests/test_usage_groups.py`, `migrations/versions/0003_usage_agent_detail.py`.
**ember_api (changed):** `src/services/agent_directory.py`, `src/routes/mcp.py`, `src/routes/chats.py`, `src/services/turns.py`, `src/models/usage.py`, `src/services/usage_service.py`, `src/routes/usage.py`, `tests/test_turns.py`, `tests/test_mcp_proxy.py`, `tests/test_account.py`, `tests/test_usage_report.py` (only if a whole-row assertion breaks), `README.md`.
**ember_web (new):** `src/stores/entryAgent.ts`, `src/components/EntryAgentTag.vue`, `src/components/AgentActivity.vue`, `src/utils/agentLabels.ts`, tests beside each.
**ember_web (deleted):** `src/components/AgentPicker.vue`, `src/stores/agents.ts`.
**ember_web (changed):** `src/api/types.ts`, `src/api/ChatsClient.ts`, `src/api/UsageClient.ts`, `src/stores/chat.ts`, `src/views/ChatView.vue`, `src/components/MessageList.vue`, `src/components/ToolSteps.vue`, `src/components/UsageChip.vue`, `src/utils/usageFormat.ts`, `src/views/UsageView.vue`, store/component tests that set up agents, `e2e/fakeApi.ts`, `e2e/chat.spec.ts`, `README.md`.
**Docs:** the Phase 2 spec (Task E7).

---

### Task E1: AgentDirectory knows the entry agent

**Files:**
- Modify: `ember_api/src/services/agent_directory.py`
- Create: `ember_api/tests/test_agent_directory.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AgentEntry: id: str; label: str; url: str; entry: bool = False; orchestrator: bool = False; focus: str = ""`
  - `NO_AGENT_RUNNING = "No agent is running"`
  - `LEGACY_ENTRY_ID = "claude-agent"`
  - `async AgentDirectory.entry() -> AgentEntry | None`
  - `all()` / `get()` unchanged in behavior.

- [ ] **Step 1: Write the failing tests**

Create `ember_api/tests/test_agent_directory.py`:

```python
"""AgentDirectory: reads ai_agent's registry, including the optional entry /
orchestrator / focus keys, and picks the entry agent with its fallbacks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.services.agent_directory import LEGACY_ENTRY_ID, NO_AGENT_RUNNING, AgentDirectory


def directory(tmp_path: Path, agents: list[dict]) -> AgentDirectory:
    path = tmp_path / "config_agents.json"
    path.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    return AgentDirectory(path)


def agent(agent_id: str, **extra) -> dict:
    return {"id": agent_id, "label": agent_id.title(), "url": f"http://{agent_id}/mcp", **extra}


def test_no_agent_running_message_is_the_one_the_routes_use() -> None:
    assert NO_AGENT_RUNNING == "No agent is running"


def test_entries_without_the_new_keys_read_as_plain_agents(tmp_path: Path) -> None:
    found = asyncio.run(directory(tmp_path, [agent("old")]).all())

    assert found[0].entry is False
    assert found[0].orchestrator is False
    assert found[0].focus == ""


def test_new_keys_are_read(tmp_path: Path) -> None:
    found = asyncio.run(
        directory(tmp_path, [agent("main", entry=True, orchestrator=True, focus="Coordinates.")]).all()
    )

    assert (found[0].entry, found[0].orchestrator, found[0].focus) == (True, True, "Coordinates.")


def test_bad_types_for_the_new_keys_fall_back_to_defaults(tmp_path: Path) -> None:
    found = asyncio.run(directory(tmp_path, [agent("odd", entry="yes", orchestrator=1, focus=5)]).all())

    assert (found[0].entry, found[0].orchestrator, found[0].focus) == (False, False, "")


def test_entry_prefers_the_flagged_agent(tmp_path: Path) -> None:
    d = directory(tmp_path, [agent("claude-agent"), agent("orch", orchestrator=True), agent("main", entry=True)])

    assert asyncio.run(d.entry()).id == "main"


def test_entry_falls_back_to_the_first_orchestrator(tmp_path: Path) -> None:
    d = directory(tmp_path, [agent("claude-agent"), agent("orch", orchestrator=True)])

    assert asyncio.run(d.entry()).id == "orch"


def test_entry_falls_back_to_the_legacy_agent(tmp_path: Path) -> None:
    d = directory(tmp_path, [agent("other"), agent(LEGACY_ENTRY_ID)])

    assert asyncio.run(d.entry()).id == LEGACY_ENTRY_ID


def test_entry_is_none_when_nothing_qualifies_or_the_file_is_missing(tmp_path: Path) -> None:
    assert asyncio.run(directory(tmp_path, [agent("other")]).entry()) is None
    assert asyncio.run(AgentDirectory(tmp_path / "missing.json").entry()) is None
```

- [ ] **Step 2: Run to verify they fail**

Run (from `ember_api/`): `.venv_ember_api\Scripts\python -m pytest tests/test_agent_directory.py -q`
Expected: ImportError / collection error (`LEGACY_ENTRY_ID` and `NO_AGENT_RUNNING` do not exist).

- [ ] **Step 3: Implement**

In `ember_api/src/services/agent_directory.py` replace the dataclass and extend the class:

```python
NO_AGENT_RUNNING = "No agent is running"
# An ai_agent registry written before agent files existed marks no entry
# agent; the one instance every older setup had was this id.
LEGACY_ENTRY_ID = "claude-agent"


@dataclass(frozen=True)
class AgentEntry:
    id: str
    label: str
    url: str
    # Optional in the registry (older ai_agent versions do not write them).
    entry: bool = False
    orchestrator: bool = False
    focus: str = ""
```

Add after `get`:

```python
    async def entry(self) -> AgentEntry | None:
        """The agent every new question goes to: the one flagged `entry`, else
        the first orchestrator, else the legacy single agent, else None."""
        agents = await self.all()
        return (
            next((a for a in agents if a.entry), None)
            or next((a for a in agents if a.orchestrator), None)
            or next((a for a in agents if a.id == LEGACY_ENTRY_ID), None)
        )
```

Replace the entry-building loop in `_read` with:

```python
        entries = []
        for item in raw.get("agents", []) if isinstance(raw, dict) else []:
            if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in ("id", "label", "url")):
                focus = item.get("focus")
                entries.append(
                    AgentEntry(
                        id=item["id"],
                        label=item["label"],
                        url=item["url"],
                        entry=item.get("entry") is True,
                        orchestrator=item.get("orchestrator") is True,
                        focus=focus if isinstance(focus, str) else "",
                    )
                )
        return entries
```

Update the module docstring's last sentence to mention the entry agent.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_agent_directory.py -q` → all pass. Then the whole suite: `.venv_ember_api\Scripts\python -m pytest -q` → still green (the dataclass only gained defaulted fields).

- [ ] **Step 5: Commit**

```bash
git add ember_api/src/services/agent_directory.py ember_api/tests/test_agent_directory.py
git commit -m "ember_api: AgentDirectory reads entry/orchestrator/focus and picks the entry agent"
```

---

### Task E2: Turns and summaries use the entry agent; `/api/agent` replaces `/api/agents`

**Files:**
- Modify: `ember_api/src/routes/mcp.py`, `ember_api/src/routes/chats.py`
- Modify tests: `ember_api/tests/test_turns.py`, `ember_api/tests/test_mcp_proxy.py`, `ember_api/tests/test_account.py`

**Interfaces:**
- Consumes: `AgentDirectory.entry()`, `NO_AGENT_RUNNING` (Task E1).
- Produces: `GET /api/agent -> {"id": str, "label": str}` (503 `No agent is running`); `POST /api/chats/{id}/turns` and `POST /api/chats/{id}/summarize` pick the agent with `directory.entry()` and ignore a body `agent_id`.

- [ ] **Step 1: Update and add the tests (they fail first)**

`tests/test_mcp_proxy.py` — replace the "agent listing" section (lines ~33-43) with:

```python
# --- entry agent -------------------------------------------------------------------


def test_entry_agent_is_returned_without_a_url(client: TestClient) -> None:
    as_admin(client)

    # conftest's registry marks no entry agent, so the legacy fallback applies.
    assert client.get("/api/agent").json() == {"id": AGENTS[0]["id"], "label": AGENTS[0]["label"]}


def test_entry_agent_requires_login(client: TestClient) -> None:
    assert client.get("/api/agent").status_code == 401


def test_no_entry_agent_is_a_503(client: TestClient, tmp_path) -> None:
    as_admin(client)
    (tmp_path / "config_agents.json").write_text('{"agents": []}', encoding="utf-8")

    response = client.get("/api/agent")

    assert response.status_code == 503
    assert response.json()["detail"] == "No agent is running"


def test_the_old_agent_list_is_gone(client: TestClient) -> None:
    as_admin(client)

    assert client.get("/api/agents").status_code == 404
```

`tests/test_account.py` lines 36 and 39: replace `"/api/agents"` with `"/api/agent"` (it is only used as a "has chat.use" probe).

`tests/test_turns.py`:
- Replace `test_each_answer_saves_which_agent_wrote_it` with:

```python
def test_the_entry_agent_answers_whatever_agent_the_browser_names(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    other = AGENTS[1]["id"]

    assert start(client, chat_id, "first").status_code == 202
    events(client, chat_id)
    assert client.post(f"/api/chats/{chat_id}/turns", json={"question": "second", "agent_id": other}).status_code == 202
    events(client, chat_id)

    answers = [m for m in chat(client, chat_id)["messages"] if m["role"] == "assistant"]
    assert [m["agent"] for m in answers] == [AGENT_ID, AGENT_ID]
    assert [a["url"] for a in agent.asks] == [AGENTS[0]["url"], AGENTS[0]["url"]]


def test_a_turn_needs_no_agent_id(client: TestClient) -> None:
    as_admin(client)
    chat_id = new_id()

    response = client.post(f"/api/chats/{chat_id}/turns", json={"question": "no agent named"})

    assert response.status_code == 202
    events(client, chat_id)
    assert chat(client, chat_id)["agent_id"] == AGENT_ID


def test_an_old_chat_moves_to_the_entry_agent_on_its_next_turn(client: TestClient) -> None:
    as_admin(client)
    chat_id = new_id()
    client.put(
        f"/api/chats/{chat_id}",
        json={"title": "Old", "agent_id": AGENTS[1]["id"], "messages": [{"role": "user", "content": "hi"}]},
    )

    assert start(client, chat_id, "again").status_code == 202
    events(client, chat_id)

    assert chat(client, chat_id)["agent_id"] == AGENT_ID
```

- Replace `test_turn_needs_chat_use_and_a_known_agent` (line ~345) with:

```python
def test_turn_needs_chat_use_and_a_running_agent(client: TestClient, email: FakeEmailSender, tmp_path) -> None:
    assert start(client, new_id()).status_code == 401
    as_admin(client)
    (tmp_path / "config_agents.json").write_text('{"agents": []}', encoding="utf-8")
    response = start(client, new_id())
    assert response.status_code == 503
    assert response.json()["detail"] == "No agent is running"
    client.post("/api/auth/logout", json={})

    make_member(client, email, verify=False)
    login(client, "alice")
    assert start(client, new_id()).status_code == 403
```

- Add next to `test_manual_summarize` in `tests/test_turns.py` (it reuses that file's `seed` helper):

```python
def test_summarize_needs_a_running_agent(client: TestClient, tmp_path) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    (tmp_path / "config_agents.json").write_text('{"agents": []}', encoding="utf-8")

    response = client.post(f"/api/chats/{chat_id}/summarize", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == "No agent is running"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_mcp_proxy.py tests/test_account.py tests/test_turns.py -q`
Expected: failures (no `/api/agent` route, 404 vs 503, second answer's agent).

- [ ] **Step 3: Implement `mcp.py`**

Replace the `AgentOut` / `list_agents` block with:

```python
class AgentOut(BaseModel):
    # No URL: where the internal servers live stays server-side.
    id: str
    label: str


@router.get("/agent")
async def entry_agent(
    _account: Account = Depends(require_chat),
    directory: AgentDirectory = Depends(get_agent_directory),
) -> AgentOut:
    """The agent every question goes to; ember_web shows its name."""
    agent = await directory.entry()
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_AGENT_RUNNING)
    return AgentOut(id=agent.id, label=agent.label)
```

and import `NO_AGENT_RUNNING` from `src.services.agent_directory` (extend the existing import line).

- [ ] **Step 4: Implement `chats.py`**

- Import `NO_AGENT_RUNNING` next to `AgentDirectory`.
- `TurnRequest.agent_id`: `agent_id: str | None = Field(default=None, max_length=120)` with the comment `# Ignored: every question goes to the entry agent. Kept so older browsers still validate.`
- `SummarizeRequest.agent_id` comment: `# Ignored, see TurnRequest.agent_id.`
- In `start_turn` replace the first lines of the body:

```python
    agent = await directory.entry()
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_AGENT_RUNNING)
```

- In `summarize_chat` replace `agent = await directory.get(body.agent_id or chat.agent_id or "")` and its 404 with the same `entry()` / 503 pair.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest -q`
Expected: all pass (the other 30 occurrences of `agent_id` in tests only send it in bodies, which is still accepted).

- [ ] **Step 6: Commit**

```bash
git add ember_api/src/routes/mcp.py ember_api/src/routes/chats.py ember_api/tests
git commit -m "ember_api: every turn goes to the entry agent; GET /api/agent replaces /api/agents"
```

---

### Task E3: Relay the live agent events

**Files:**
- Modify: `ember_api/src/services/turns.py`, `ember_api/src/routes/chats.py` (`StepIn`)
- Create: `ember_api/tests/test_agent_events.py`

**Interfaces:**
- Consumes: Phase 1 events (stamped `agent_id` / `agent_label` on every event; `agent_start`, `agent_end`, `agent_token`).
- Produces:
  - `Turn.active_agents: list[dict]` of `{"agent_id", "label", "since", "step_id"}`
  - `Turn.record_agent(event)`
  - `Turn.snapshot()["active_agents"]`
  - steps carry `agent_id` / `agent_label` when present; `Turn.step_index` is keyed `(agent_id, step_id)`
  - constants `AGENT_QUESTION_MAX = 500`, `AGENT_TEXT_MAX = 4000`
  - `StepIn.agent_id` / `StepIn.agent_label` (optional, max 120)

- [ ] **Step 1: Write the failing tests**

Create `ember_api/tests/test_agent_events.py`:

```python
"""Live agent activity: agent_start / agent_end / agent_token are relayed, a
late joiner's snapshot lists who is working, nested steps keep their agent, and
nothing of it is saved with the answer except the steps' agent."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import chat, events, new_id, start

ORCH = {"agent_id": "claude-agent", "agent_label": "Ember"}
CALC = {"agent_id": "calc", "agent_label": "Calculator"}


def delegation_events() -> list[dict]:
    return [
        {"type": "step_start", "id": "d1", "tool": "delegate_to_agent", "label": "Delegate", "arguments": {}, **ORCH},
        {
            "type": "agent_start", "agent_id": "calc", "agent_label": "Calculator", "delegated_by": "claude-agent",
            "question": "q" * 900, "step_id": "d1", "at": "2026-10-04T09:12:03.512Z",
        },
        {"type": "agent_token", "step_id": "d1", "text": "t" * 5000, **CALC},
        # Same step id as the orchestrator's own step: only agent_id tells them apart.
        {"type": "step_start", "id": "d1", "tool": "tool_calc", "label": "Calc", "arguments": {"x": 1}, **CALC},
        {"type": "step_end", "id": "d1", "ok": True, "result": "4", **CALC},
        {"type": "agent_end", "agent_id": "calc", "agent_label": "Calculator", "ok": True, "step_id": "d1", "at": "2026-10-04T09:12:07.044Z"},
        {"type": "step_end", "id": "d1", "ok": True, "result": "Delegated to calc", **ORCH},
        {"type": "token", "text": "Done."},
    ]


def test_agent_events_are_relayed_with_their_caps(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()
    agent.answer = "Done."
    chat_id = new_id()

    assert start(client, chat_id).status_code == 202
    stream = events(client, chat_id)

    kinds = [e["type"] for e in stream]
    assert kinds.count("agent_start") == kinds.count("agent_end") == kinds.count("agent_token") == 1
    started = next(e for e in stream if e["type"] == "agent_start")
    assert (started["agent_id"], started["agent_label"], started["delegated_by"]) == ("calc", "Calculator", "claude-agent")
    assert len(started["question"]) == 500
    assert len(next(e for e in stream if e["type"] == "agent_token")["text"]) == 4000


def test_nested_steps_are_kept_apart_and_labelled_with_their_agent(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    steps = [m for m in chat(client, chat_id)["messages"] if m["role"] == "assistant"][-1]["steps"]

    assert [(s["tool"], s["agent_id"], s["ok"], s["result"]) for s in steps] == [
        ("delegate_to_agent", "claude-agent", True, "Delegated to calc"),
        ("tool_calc", "calc", True, "4"),
    ]
    assert steps[1]["agent_label"] == "Calculator"


def test_agent_tokens_are_not_saved_with_the_answer(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    saved = chat(client, chat_id)["messages"][-1]

    assert "ttt" not in saved["content"]
    assert "active_agents" not in saved


def test_a_late_joiner_is_told_who_is_working(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()[:3]  # delegation started, specialist streaming
    agent.hold = True
    chat_id = new_id()
    start(client, chat_id)
    try:
        from tests.test_turns import wait_until

        wait_until(lambda: agent.gate is not None)
        with client.stream("GET", f"/api/chats/{chat_id}/events") as response:
            first = next(line for line in response.iter_lines() if line.startswith("data: "))
        import json

        snapshot = json.loads(first[6:])
    finally:
        agent.release()
    events(client, chat_id)

    assert snapshot["type"] == "snapshot"
    assert snapshot["active_agents"] == [
        {"agent_id": "calc", "label": "Calculator", "since": "2026-10-04T09:12:03.512Z", "step_id": "d1"}
    ]


def test_the_stack_is_empty_when_the_turn_ends_without_agent_end(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()[:2]  # started, never ended (specialist crashed)
    chat_id = new_id()
    start(client, chat_id)

    stream = events(client, chat_id)

    assert stream[-1]["type"] == "final"
    registry = client.app.state.turns
    turn = registry.get(1, chat_id)
    assert turn is not None and turn.active_agents == []
```

(If `client.app.state.turns` is not the registry's attribute name, use whatever `deps.get_turns` reads: `grep -n "def get_turns" -A3 ember_api/src/deps.py ember_api/src/routes/chats.py`.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_agent_events.py -q`
Expected: failures (events are dropped by the allowlist, steps lack `agent_id`).

- [ ] **Step 3: Implement in `turns.py`**

Add constants near `MAX_AGENT_USAGE_ROWS`:

```python
# Caps on what a delegated agent's live events may carry to a browser.
AGENT_QUESTION_MAX = 500
AGENT_TEXT_MAX = 4000
```

Add to `Turn` after `step_index`; change its type and add the stack:

```python
    # (agent id, step id) -> index in `steps`: a specialist's step ids can
    # equal the orchestrator's own.
    step_index: dict[tuple[str, str], int] = field(default_factory=dict)
    # Agents working right now, outermost first: {agent_id, label, since, step_id}.
    active_agents: list[dict[str, str]] = field(default_factory=list)
```

(delete the old `step_index: dict[str, int]` line.)

`snapshot()` gains `"active_agents": [dict(a) for a in self.active_agents],`.

Add method and rewrite `record_step`:

```python
    def record_agent(self, event: dict[str, Any]) -> None:
        """Folds agent_start / agent_end into the stack of working agents."""
        agent_id = str(event.get("agent_id") or "")
        step_id = str(event.get("step_id") or "")
        if event.get("type") == "agent_start":
            self.active_agents.append(
                {
                    "agent_id": agent_id,
                    "label": str(event.get("agent_label") or ""),
                    "since": str(event.get("at") or ""),
                    "step_id": step_id,
                }
            )
        else:
            self.active_agents = [
                a for a in self.active_agents if not (a["step_id"] == step_id and a["agent_id"] == agent_id)
            ]

    def record_step(self, event: dict[str, Any]) -> None:
        """Folds a step_start / step_end event into `steps`."""
        step_id = str(event.get("id") or "")
        key = (str(event.get("agent_id") or ""), step_id)
        if event.get("type") == "step_start":
            if len(self.steps) >= MAX_STEPS:
                return
            self.step_index[key] = len(self.steps)
            step = {
                "tool": str(event.get("tool") or ""),
                "label": str(event.get("label") or ""),
                "arguments": event.get("arguments") if isinstance(event.get("arguments"), dict) else {},
                "ok": None,
                "result": "",
            }
            if event.get("agent_id"):
                step["agent_id"] = str(event["agent_id"])
                step["agent_label"] = str(event.get("agent_label") or "")
            self.steps.append(step)
        elif key in self.step_index:
            step = self.steps[self.step_index[key]]
            step["ok"] = bool(event.get("ok"))
            step["result"] = str(event.get("result") or "")[:STEP_RESULT_MAX]
```

In `_publish` add before `elif kind == "approval_request":`

```python
            elif kind in ("agent_start", "agent_end"):
                turn.record_agent(event)
```

and in the terminal block (`if kind in TERMINAL:`) add `turn.active_agents.clear()` next to `turn.pending_approvals.clear()`.

In `_answer`'s `on_event` extend the allowlist tuple with `"agent_start", "agent_end", "agent_token"` and clamp:

```python
        async def on_event(event: dict[str, Any]) -> None:
            if event.get("type") in (
                "token", "token_reset", "step_start", "step_progress", "step_end", "usage",
                "approval_request", "approval_resolved", "agent_start", "agent_end", "agent_token",
            ):
                await self._publish(turn, _clamped(event))
```

and add the helper at module level (near `_interrupted`):

```python
def _clamped(event: dict[str, Any]) -> dict[str, Any]:
    """A delegated agent's question and streamed text are shown to browsers: cap them."""
    kind = event.get("type")
    if kind == "agent_start" and isinstance(event.get("question"), str):
        return {**event, "question": event["question"][:AGENT_QUESTION_MAX]}
    if kind == "agent_token" and isinstance(event.get("text"), str):
        return {**event, "text": event["text"][:AGENT_TEXT_MAX]}
    return event
```

Note: `token` events published by Phase 1 now carry `agent_id` / `agent_label` keys; `_publish` ignores extra keys, so `turn.text` handling is unchanged.

- [ ] **Step 4: Implement in `chats.py`**

In `StepIn` add:

```python
    # Which agent ran it, when a delegated agent did.
    agent_id: str | None = Field(default=None, max_length=120)
    agent_label: str | None = Field(default=None, max_length=120)
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest -q` → all pass (existing step tests use events without `agent_id`, so their keys are `("", id)`).

- [ ] **Step 6: Commit**

```bash
git add ember_api/src/services/turns.py ember_api/src/routes/chats.py ember_api/tests/test_agent_events.py
git commit -m "ember_api: relay agent_start/agent_end/agent_token, snapshot active agents, label nested steps"
```

---

### Task E4: Usage records keep who, where and when

**Files:**
- Modify: `ember_api/src/models/usage.py`, `ember_api/src/services/usage_service.py`, `ember_api/src/services/turns.py` (`_agent_usage`), `ember_api/src/routes/chats.py` (`AgentUsageIn`)
- Create: `ember_api/migrations/versions/0003_usage_agent_detail.py`
- Test: `ember_api/tests/test_usage_detail.py` (new)

**Interfaces:**
- Consumes: Phase 1 `agent_usage` row keys: `agent_id, agent_label, provider_id, gateway, model, input_tokens, output_tokens, total_tokens, started_at, finished_at, delegated_by`.
- Produces:
  - `usage_rows(result)` rows now also contain `agent_id`, `provider_id`, `gateway`, `started_at` (naive UTC `datetime | None`), `finished_at`, `delegated_by`, and display-only `agent_label`; `"agent"` is `agent_id or provider_id`
  - `UsageRecord` new nullable columns
  - saved message `agent_usage` entries gain `agent_label`, `provider_id`, `gateway`, `started_at`, `finished_at` (ISO strings with `Z`) when known
  - `AgentUsageIn` accepts those keys

- [ ] **Step 1: Write the failing tests**

Create `ember_api/tests/test_usage_detail.py`:

```python
"""Usage rows keep which agent, provider and gateway spent tokens and when."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.services.usage_service import usage_rows
from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import chat, events, new_id, start

ORCH_ROW = {
    "agent_id": "claude-agent", "agent_label": "Ember", "provider_id": "anthropic", "gateway": "openrouter",
    "model": "claude-sonnet-5-5", "input_tokens": 70, "output_tokens": 30, "total_tokens": 100,
    "started_at": "2026-10-04T09:12:03.512Z", "finished_at": "2026-10-04T09:12:07.044Z", "delegated_by": None,
}
CALC_ROW = {
    "agent_id": "calc", "agent_label": "Calculator", "provider_id": "openai", "gateway": None,
    "model": "gpt-x", "input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
    "started_at": "2026-10-04T09:12:04.000Z", "finished_at": "2026-10-04T09:12:05.250Z", "delegated_by": "claude-agent",
}


def test_rows_carry_the_new_fields_and_name_the_agent_by_id() -> None:
    rows = usage_rows({"agent_usage": [ORCH_ROW, CALC_ROW]})

    assert [r["agent"] for r in rows] == ["claude-agent", "calc"]
    assert rows[0]["provider_id"] == "anthropic" and rows[0]["gateway"] == "openrouter"
    assert rows[0]["started_at"] == datetime(2026, 10, 4, 9, 12, 3, 512000)
    assert rows[0]["finished_at"] == datetime(2026, 10, 4, 9, 12, 7, 44000)
    assert rows[1]["delegated_by"] == "claude-agent" and rows[1]["gateway"] is None
    assert rows[1]["agent_label"] == "Calculator"


def test_an_older_row_without_the_fields_still_works() -> None:
    rows = usage_rows({"agent_usage": [{"provider_id": "claude", "model": "m", "total_tokens": 9}]})

    assert rows[0]["agent"] == "claude"
    assert rows[0]["agent_id"] is None and rows[0]["started_at"] is None


def test_bad_times_are_dropped_not_fatal() -> None:
    rows = usage_rows({"agent_usage": [{**ORCH_ROW, "started_at": "yesterday", "finished_at": 5}]})

    assert rows[0]["started_at"] is None and rows[0]["finished_at"] is None


def test_a_turn_stores_the_detail_and_the_answer_lists_each_agent(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.result_extra = {"total_tokens": 125, "agent_usage": [ORCH_ROW, CALC_ROW]}
    chat_id = new_id()

    assert start(client, chat_id).status_code == 202
    events(client, chat_id)

    answer = [m for m in chat(client, chat_id)["messages"] if m["role"] == "assistant"][-1]
    assert [u["agent"] for u in answer["agent_usage"]] == ["claude-agent", "calc"]
    calc = answer["agent_usage"][1]
    assert (calc["agent_label"], calc["provider_id"], calc["total_tokens"]) == ("Calculator", "openai", 25)
    assert calc["started_at"] == "2026-10-04T09:12:04.000Z"
    assert calc["finished_at"] == "2026-10-04T09:12:05.250Z"
    # The saved answer must round-trip through a normal PUT.
    saved = chat(client, chat_id)
    put = client.put(
        f"/api/chats/{chat_id}",
        json={"title": saved["title"], "agent_id": saved["agent_id"], "messages": saved["messages"]},
    )
    assert put.status_code == 200, put.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_usage_detail.py -q`
Expected: failures (`KeyError: 'agent_id'`, etc.).

- [ ] **Step 3: Model + migration**

In `src/models/usage.py` add after `output_tokens`:

```python
    # Which agent, provider and gateway spent the tokens, and when its call ran
    # (naive UTC). Absent on rows recorded before multi-agent ai_agent.
    agent_id: Mapped[str | None] = mapped_column(String(120))
    provider_id: Mapped[str | None] = mapped_column(String(60))
    gateway: Mapped[str | None] = mapped_column(String(60))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    # The orchestrator that handed this agent its question.
    delegated_by: Mapped[str | None] = mapped_column(String(120))
```

Run (ember_api stopped): `.venv_ember_api\Scripts\python -m scripts.migrate_db revision "usage agent detail"` and read the file it writes. It must be equivalent to the following; if the generated id/name differs, rename to `0003_usage_agent_detail.py` with `revision = "0003"`, `down_revision = "0002"`:

```python
"""Which agent, provider and gateway spent usage tokens, and when (usage_records).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.add_column(sa.Column("agent_id", sa.String(120), nullable=True))
        batch.add_column(sa.Column("provider_id", sa.String(60), nullable=True))
        batch.add_column(sa.Column("gateway", sa.String(60), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("delegated_by", sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_column("delegated_by")
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
        batch.drop_column("gateway")
        batch.drop_column("provider_id")
        batch.drop_column("agent_id")
```

- [ ] **Step 4: `usage_service.py`**

Add imports `timezone` (`from datetime import date, datetime, time, timedelta, timezone`). Add helpers after `_int`:

```python
def _time(value: Any) -> datetime | None:
    """An ISO-8601 time from ai_agent ("...Z") as naive UTC; None when absent or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def _text(value: Any, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


# Keys of a usage row that are shown but not stored (no column).
_DISPLAY_ONLY = {"agent_label"}
```

Replace the `agent_usage` loop body in `usage_rows`:

```python
    for entry in result.get("agent_usage") or []:
        if isinstance(entry, dict) and _int(entry.get("total_tokens")):
            agent_id = _text(entry.get("agent_id"), 120)
            provider_id = _text(entry.get("provider_id"), 60)
            rows.append(
                {
                    "agent": agent_id or provider_id,
                    "agent_id": agent_id,
                    "agent_label": _text(entry.get("agent_label"), 120),
                    "provider_id": provider_id,
                    "gateway": _text(entry.get("gateway"), 60),
                    "model": entry.get("model"),
                    "input_tokens": _int(entry.get("input_tokens")),
                    "output_tokens": _int(entry.get("output_tokens")),
                    "total_tokens": _int(entry.get("total_tokens")),
                    "started_at": _time(entry.get("started_at")),
                    "finished_at": _time(entry.get("finished_at")),
                    "delegated_by": _text(entry.get("delegated_by"), 120),
                }
            )
```

The fallback row (no `agent_usage`) gains the same keys with `None` values, `agent_id=None`, `provider_id=result.get("provider_id")`, `agent` unchanged:

```python
        rows.append(
            {
                "agent": result.get("provider_id"),
                "agent_id": None,
                "agent_label": None,
                "provider_id": result.get("provider_id"),
                "gateway": None,
                "model": result.get("model"),
                "input_tokens": _int(result.get("input_tokens")),
                "output_tokens": _int(result.get("output_tokens")),
                "total_tokens": _int(result.get("total_tokens")),
                "started_at": None,
                "finished_at": None,
                "delegated_by": None,
            }
        )
```

In `UsageService.record` strip display-only keys:

```python
        for row in rows:
            stored = {k: v for k, v in row.items() if k not in _DISPLAY_ONLY}
            self._session.add(
                UsageRecord(account_id=account_id, turn_id=turn_id, kind=kind, chat_id=chat_id, created_at=now, **stored)
            )
```

If an existing test compares a whole `usage_rows(...)` dict, update its expected dict with the new keys.

- [ ] **Step 5: `turns.py` `_agent_usage` and `AgentUsageIn`**

In `turns.py` replace `_agent_usage`:

```python
def _iso(value: Any) -> str | None:
    """A naive-UTC datetime as the ISO string with "Z" ai_agent sent it as."""
    return value.isoformat(timespec="milliseconds") + "Z" if hasattr(value, "isoformat") else None


def _agent_usage(row: dict[str, Any]) -> dict[str, Any]:
    """One saved `agent_usage` entry from a usage row: who, which model, where
    it ran and when, and the token counts that are known."""
    entry = {
        "agent": row["agent"] or "unknown",
        "agent_label": row.get("agent_label"),
        "provider_id": row.get("provider_id"),
        "gateway": row.get("gateway"),
        "model": row["model"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "total_tokens": row["total_tokens"],
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
    }
    return {key: value for key, value in entry.items() if value is not None}
```

In `chats.py` `AgentUsageIn` add:

```python
    agent_label: str | None = Field(default=None, max_length=120)
    provider_id: str | None = Field(default=None, max_length=60)
    gateway: str | None = Field(default=None, max_length=60)
    # ISO-8601 UTC ("...Z"), as ai_agent reported them.
    started_at: str | None = Field(default=None, max_length=40)
    finished_at: str | None = Field(default=None, max_length=40)
```

- [ ] **Step 6: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest -q`
Expected: all pass, including `tests/test_migrations.py` (it fails when a model change has no migration, and exercises up/down).

- [ ] **Step 7: Commit**

```bash
git add ember_api/src ember_api/migrations ember_api/tests/test_usage_detail.py
git commit -m "ember_api: usage records keep agent, provider, gateway and call times (migration 0003)"
```

---

### Task E5: Usage API groups, filters and a records list

**Files:**
- Modify: `ember_api/src/services/usage_service.py`, `ember_api/src/routes/usage.py`
- Create: `ember_api/tests/test_usage_groups.py`

**Interfaces:**
- Consumes: Task E4's columns.
- Produces:
  - `UsageService.report(account_id, days, since_date=None, *, group_by="agent", agent=None, provider=None)`; the returned dict gains `"group_by"` and `"groups": [{"key", "tokens", "input_tokens", "output_tokens", "turns"}]` (largest first)
  - `UsageService.records(account_id, days, since_date=None, *, agent=None, provider=None, limit=100) -> list[dict]`
  - `GET /api/usage?group_by=agent|provider|gateway|model&agent=&provider=`
  - `GET /api/usage/records?days&since&agent&provider&limit` → `[UsageRecordOut]`

- [ ] **Step 1: Write the failing tests**

Create `ember_api/tests/test_usage_groups.py`:

```python
"""Usage grouped by agent, provider, gateway or model, filtered, and listed
row by row with their times."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import events, new_id, start
from tests.test_usage_report import Clock, clock  # noqa: F401 - the fixture

NOW = datetime(2026, 3, 15, 10, 0, 0)

ROWS = [
    {"agent_id": "claude-agent", "provider_id": "anthropic", "gateway": "openrouter", "model": "m1",
     "input_tokens": 60, "output_tokens": 40, "total_tokens": 100,
     "started_at": "2026-03-15T09:00:00.000Z", "finished_at": "2026-03-15T09:00:04.000Z"},
    {"agent_id": "calc", "provider_id": "openai", "gateway": "azure", "model": "m2",
     "input_tokens": 20, "output_tokens": 10, "total_tokens": 30, "delegated_by": "claude-agent",
     "started_at": "2026-03-15T09:00:01.000Z", "finished_at": "2026-03-15T09:00:02.000Z"},
]


def run_turn(client: TestClient, agent: FakeAgent) -> None:
    agent.result_extra = {"total_tokens": 130, "agent_usage": ROWS}
    chat_id = new_id()
    assert start(client, chat_id).status_code == 202
    events(client, chat_id)


def report(client: TestClient, **params) -> dict:
    response = client.get("/api/usage", params=params)
    assert response.status_code == 200, response.text
    return response.json()["report"]


@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        ("agent", {"claude-agent": 100, "calc": 30}),
        ("provider", {"anthropic": 100, "openai": 30}),
        ("gateway", {"openrouter": 100, "azure": 30}),
        ("model", {"m1": 100, "m2": 30}),
    ],
)
def test_groups(client: TestClient, agent: FakeAgent, clock, group_by, expected) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    result = report(client, group_by=group_by)

    assert result["group_by"] == group_by
    assert {g["key"]: g["tokens"] for g in result["groups"]} == expected
    assert [g["tokens"] for g in result["groups"]] == sorted((g["tokens"] for g in result["groups"]), reverse=True)
    assert result["groups"][0]["turns"] == 1


def test_by_agent_is_unchanged_and_default_group_is_agent(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    result = report(client)

    assert result["group_by"] == "agent"
    assert {(a["agent"], a["model"]): a["tokens"] for a in result["by_agent"]} == {
        ("claude-agent", "m1"): 100, ("calc", "m2"): 30,
    }


def test_filters_apply_to_totals_and_groups(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    by_agent = report(client, agent="calc")
    by_provider = report(client, provider="anthropic", group_by="provider")

    assert by_agent["total_tokens"] == 30
    assert [g["key"] for g in by_provider["groups"]] == ["anthropic"]
    assert by_provider["total_tokens"] == 100


def test_unknown_group_by_is_422(client: TestClient) -> None:
    as_admin(client)

    assert client.get("/api/usage", params={"group_by": "colour"}).status_code == 422


def test_old_rows_without_detail_group_as_unknown(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    agent.result_extra = {"total_tokens": 9, "agent_usage": [{"provider_id": "claude", "model": "m", "total_tokens": 9}]}
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    assert [g["key"] for g in report(client, group_by="gateway")["groups"]] == ["unknown"]
    assert [g["key"] for g in report(client, group_by="agent")["groups"]] == ["claude"]


def test_records_list_rows_newest_first_with_their_times(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    response = client.get("/api/usage/records")

    assert response.status_code == 200
    rows = response.json()
    assert {r["agent_id"] for r in rows} == {"claude-agent", "calc"}
    calc = next(r for r in rows if r["agent_id"] == "calc")
    assert calc["provider_id"] == "openai" and calc["gateway"] == "azure"
    assert calc["delegated_by"] == "claude-agent"
    assert calc["started_at"].startswith("2026-03-15T09:00:01")
    assert calc["created_at"].startswith("2026-03-15T10:00:00")
    assert client.get("/api/usage/records", params={"agent": "calc"}).json() == [calc]
    assert len(client.get("/api/usage/records", params={"limit": 1}).json()) == 1


def test_records_need_login_and_a_sane_limit(client: TestClient) -> None:
    assert client.get("/api/usage/records").status_code == 401
    as_admin(client)
    assert client.get("/api/usage/records", params={"limit": 0}).status_code == 422
    assert client.get("/api/usage/records", params={"limit": 501}).status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_usage_groups.py -q` → failures (no `group_by`, no `/records` route).

- [ ] **Step 3: Service**

In `usage_service.py` add near the top:

```python
GROUP_BY = ("agent", "provider", "gateway", "model")
```

Change `report`'s signature and query. Replace its `rows = ...` select and loop with (keeping the existing daily/hourly/agents logic):

```python
    async def report(
        self,
        account_id: int,
        days: int,
        since_date: date | None = None,
        *,
        group_by: str = "agent",
        agent: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        since, days = period_start(days, since_date)
        query = (
            select(
                UsageRecord.created_at,
                UsageRecord.turn_id,
                UsageRecord.kind,
                UsageRecord.chat_id,
                UsageRecord.agent,
                UsageRecord.provider_id,
                UsageRecord.gateway,
                UsageRecord.model,
                UsageRecord.input_tokens,
                UsageRecord.output_tokens,
                UsageRecord.total_tokens,
            )
            .where(UsageRecord.account_id == account_id, UsageRecord.created_at >= since)
            .order_by(UsageRecord.created_at)
        )
        if agent:
            query = query.where(UsageRecord.agent == agent)
        if provider:
            query = query.where(UsageRecord.provider_id == provider)
        rows = (await self._session.execute(query)).all()

        daily: dict[str, int] = {}
        hourly = [0] * 24
        agents: dict[tuple[str, str], int] = {}
        groups: dict[str, dict[str, Any]] = {}
        turns: set[str] = set()
        chats: set[str] = set()
        total = input_total = output_total = summary_total = 0
        for created_at, turn_id, kind, chat_id, agent_name, provider_id, gateway, model, input_tokens, output_tokens, tokens in rows:
            day = created_at.date().isoformat()
            daily[day] = daily.get(day, 0) + tokens
            hourly[created_at.hour] += tokens
            key = (agent_name or "unknown", model or "")
            agents[key] = agents.get(key, 0) + tokens
            group_key = {
                "agent": agent_name,
                "provider": provider_id,
                "gateway": gateway,
                "model": model,
            }[group_by] or "unknown"
            group = groups.setdefault(group_key, {"key": group_key, "tokens": 0, "input_tokens": 0, "output_tokens": 0, "turns": set()})
            group["tokens"] += tokens
            group["input_tokens"] += input_tokens or 0
            group["output_tokens"] += output_tokens or 0
            group["turns"].add(turn_id)
            if kind == "summary":
                summary_total += tokens
            else:
                turns.add(turn_id)
            if chat_id:
                chats.add(chat_id)
            total += tokens
            input_total += input_tokens or 0
            output_total += output_tokens or 0
```

and in the returned dict add after `"by_agent": [...]`:

```python
            "group_by": group_by,
            "groups": [
                {**g, "turns": len(g["turns"])} for g in sorted(groups.values(), key=lambda g: -g["tokens"])
            ],
```

(The local variable formerly named `agent` in the loop is renamed `agent_name` because `agent` is now the filter parameter.)

Add the records method:

```python
    async def records(
        self,
        account_id: int,
        days: int,
        since_date: date | None = None,
        *,
        agent: str | None = None,
        provider: str | None = None,
        limit: int = 100,
    ) -> list[UsageRecord]:
        """This account's usage rows, newest first, with when each agent's call ran."""
        since, _ = period_start(days, since_date)
        query = (
            select(UsageRecord)
            .where(UsageRecord.account_id == account_id, UsageRecord.created_at >= since)
            .order_by(UsageRecord.created_at.desc(), UsageRecord.id.desc())
            .limit(limit)
        )
        if agent:
            query = query.where(UsageRecord.agent == agent)
        if provider:
            query = query.where(UsageRecord.provider_id == provider)
        return list((await self._session.execute(query)).scalars())
```

- [ ] **Step 4: Routes**

In `routes/usage.py` add `Literal` to the typing import (`from typing import Any, Literal`) and:

```python
class UsageRecordOut(BaseModel):
    id: int
    turn_id: str
    kind: str
    chat_id: str | None
    agent: str | None
    agent_id: str | None
    provider_id: str | None
    gateway: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int
    started_at: datetime | None
    finished_at: datetime | None
    delegated_by: str | None
    created_at: datetime

    @classmethod
    def of(cls, row: UsageRecord) -> UsageRecordOut:
        return cls(**{name: getattr(row, name) for name in cls.model_fields})
```

(import `UsageRecord` from `src.models`.) Update `my_usage`:

```python
@router.get("/api/usage")
async def my_usage(
    days: int = Query(default=30, ge=1, le=366),
    since: date | None = Query(default=None),
    group_by: Literal["agent", "provider", "gateway", "model"] = Query(default="agent"),
    agent: str | None = Query(default=None, max_length=120),
    provider: str | None = Query(default=None, max_length=60),
    account: Account = Depends(require_chat),
    usage: UsageService = Depends(get_usage_service),
) -> UsageOut:
    windows = await usage.windows(account.id)
    return UsageOut(
        six_hour=WindowOut.of(windows["six_hour"]),
        weekly=WindowOut.of(windows["weekly"]),
        report=await usage.report(
            account.id, days, check_since(since), group_by=group_by, agent=agent, provider=provider
        ),
    )


@router.get("/api/usage/records")
async def my_usage_records(
    days: int = Query(default=30, ge=1, le=366),
    since: date | None = Query(default=None),
    agent: str | None = Query(default=None, max_length=120),
    provider: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
    account: Account = Depends(require_chat),
    usage: UsageService = Depends(get_usage_service),
) -> list[UsageRecordOut]:
    rows = await usage.records(account.id, days, check_since(since), agent=agent, provider=provider, limit=limit)
    return [UsageRecordOut.of(row) for row in rows]
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest -q` → all pass (the clock fixture patches `usage_service.utcnow` and `usage_routes.utcnow`; `records` uses `period_start`, which reads `usage_service.utcnow`).

- [ ] **Step 6: Commit**

```bash
git add ember_api/src ember_api/tests/test_usage_groups.py
git commit -m "ember_api: usage grouped by agent/provider/gateway/model, filters and a records list"
```

---

### Task E6: ember_api README

**Files:** Modify `ember_api/README.md`.

- [ ] **Step 1: Edit the API table and notes**

- Replace the `GET /api/agents` row (line ~185) with `| GET | /api/agent | chat.use | The agent every question goes to, as {id, label} - no URL. 503 "No agent is running" when none is registered. |`.
- In the chat turn rows, note that `agent_id` in `POST /api/chats/{id}/turns` and `.../summarize` is accepted but ignored.
- In the `/events` description add: `agent_start`, `agent_end`, `agent_token` events and the snapshot's `active_agents`; `agent_token` text is never saved.
- In the usage rows add `GET /api/usage` params `group_by`, `agent`, `provider`, and the new `GET /api/usage/records`.
- Add one line under migrations/features: `usage_records` keeps `agent_id`, `provider_id`, `gateway`, `started_at`, `finished_at`, `delegated_by` (migration 0003).

- [ ] **Step 2: Verify and commit**

Run: `.venv_ember_api\Scripts\python -m pytest -q` → green.

```bash
git add ember_api/README.md
git commit -m "ember_api: document the entry agent, agent events and usage grouping"
```

---

### Task E7: Record the planning decisions in the Phase 2 spec

**Files:** Modify `docs/superpowers/specs/2026-10-04-ember-multi-agent-design.md`.

- [ ] **Step 1: Edit**

- Entry-agent section: the route is `GET /api/agent` (the `/api/` prefix); `GET /api/agents` is removed.
- Live activity relay: the snapshot's `active_agents` entries also carry `step_id`; steps are keyed `(agent_id, id)`.
- Usage section: add `GET /api/usage/records` (limit 1-500, default 100) and the `groups` field of the report.
- Add a "Known limits" line: saved answers from before keep their old agent id, which the browser shows as the id since only the entry agent's label is known.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-10-04-ember-multi-agent-design.md
git commit -m "docs: record phase 2 planning decisions in the ember multi-agent spec"
```

---

### Task W1: Drop the picker; ember always uses the entry agent

**ember_web gate: propose, wait for the user's approval, then implement.**

**Files:**
- Create: `ember_web/src/stores/entryAgent.ts`, `ember_web/src/stores/entryAgent.test.ts`, `ember_web/src/components/EntryAgentTag.vue`, `ember_web/src/components/EntryAgentTag.test.ts`, `ember_web/src/utils/agentLabels.ts`, `ember_web/src/utils/agentLabels.test.ts`
- Delete: `ember_web/src/components/AgentPicker.vue`, `ember_web/src/stores/agents.ts`
- Modify: `ember_web/src/api/ChatsClient.ts`, `ember_web/src/api/types.ts`, `ember_web/src/stores/chat.ts`, `ember_web/src/views/ChatView.vue`, `ember_web/src/stores/chat.test.ts`, `chat.approvals.test.ts`, `chat.forced.test.ts`, `chat.notify.test.ts`, `ember_web/e2e/fakeApi.ts`, `ember_web/e2e/chat.spec.ts`, `ember_web/src/components/UsageChip.test.ts` / `MessageList.test.ts` only if they import the agents store

**Interfaces:**
- Consumes: ember_api `GET /api/agent` (E2), `chatsClient.startTurn` response `chat.agent_id`.
- Produces:
  - `useEntryAgentStore()` with `entry: Ref<AgentInfo | null>`, `labels: ComputedRef<Record<string, string>>`, `available: Ref<boolean | null>` (`null` = not checked), `loadError: Ref<string>`, `loading`, `refresh(): Promise<void>`
  - `agentLabelFor(id: string | undefined, labels: Record<string, string>): string | undefined` (in `utils/agentLabels.ts`)
  - `TurnStart` without `agent_id`; `chatsClient.summarize(id)` without an agent argument.

- [ ] **Step 1: Write the failing tests**

`src/utils/agentLabels.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { agentLabelFor } from "./agentLabels";

describe("agentLabelFor", () => {
  it("uses the known label, else the id, else nothing", () => {
    expect(agentLabelFor("main", { main: "Ember" })).toBe("Ember");
    expect(agentLabelFor("old-agent", { main: "Ember" })).toBe("old-agent");
    expect(agentLabelFor(undefined, { main: "Ember" })).toBeUndefined();
  });
});
```

`src/stores/entryAgent.test.ts`:

```ts
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { useAuthStore } from "./auth";
import { useEntryAgentStore } from "./entryAgent";

const request = vi.hoisted(() => vi.fn());
const status = vi.hoisted(() => vi.fn());
vi.mock("../api/http", async (original) => ({ ...(await original<typeof import("../api/http")>()), apiRequest: request }));
vi.mock("../api/AiAgentClient", () => ({ AiAgentClient: vi.fn(() => ({ status })) }));

beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = {
    id: 1, username: "root", email: "r@example.com", email_verified: true, roles: [], permissions: ["chat.use"],
  };
  request.mockReset();
  status.mockReset();
});

describe("entry agent store", () => {
  it("loads the entry agent and checks that it is available", async () => {
    request.mockResolvedValue({ id: "main", label: "Ember" });
    status.mockResolvedValue({ available: true });
    const store = useEntryAgentStore();

    await store.refresh();

    expect(request).toHaveBeenCalledWith("GET", "/api/agent");
    expect(store.entry).toEqual({ id: "main", label: "Ember" });
    expect(store.labels).toEqual({ main: "Ember" });
    expect(store.available).toBe(true);
  });

  it("marks an agent whose status says unavailable (or that cannot be reached)", async () => {
    request.mockResolvedValue({ id: "main", label: "Ember" });
    status.mockResolvedValue({ available: false });
    const store = useEntryAgentStore();
    await store.refresh();
    expect(store.available).toBe(false);

    status.mockRejectedValue(new Error("down"));
    await store.refresh();
    expect(store.available).toBe(false);
  });

  it("keeps the server's message when no agent is running", async () => {
    request.mockRejectedValue(new ApiError(503, "No agent is running"));
    const store = useEntryAgentStore();

    await store.refresh();

    expect(store.entry).toBeNull();
    expect(store.labels).toEqual({});
    expect(store.loadError).toBe("No agent is running");
  });

  it("forgets the agent when another user logs in", async () => {
    request.mockResolvedValue({ id: "main", label: "Ember" });
    status.mockResolvedValue({ available: true });
    const store = useEntryAgentStore();
    await store.refresh();

    useAuthStore().account = { ...useAuthStore().account!, id: 2 };
    await flushPromises();

    expect(request).toHaveBeenCalledTimes(2); // reloaded for the new user
  });
});
```

(Check `ApiError`'s constructor in `src/api/http.ts` and match it; if it takes `(status, message, ...)` in a different order, adjust the test.)

`src/components/EntryAgentTag.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntryAgentTag from "./EntryAgentTag.vue";
import { useEntryAgentStore } from "../stores/entryAgent";

vi.mock("../api/http", async (original) => ({ ...(await original<typeof import("../api/http")>()), apiRequest: vi.fn() }));

beforeEach(() => setActivePinia(createPinia()));

function tag() {
  return mount(EntryAgentTag, { global: { plugins: [] } });
}

describe("EntryAgentTag", () => {
  it("names the agent the user is talking to", () => {
    const store = useEntryAgentStore();
    store.entry = { id: "main", label: "Ember" };
    store.available = true;
    store.refresh = vi.fn();

    expect(tag().text()).toContain("Talking to Ember");
  });

  it("says when it is unavailable, and when none is running", () => {
    const store = useEntryAgentStore();
    store.refresh = vi.fn();
    store.entry = { id: "main", label: "Ember" };
    store.available = false;
    expect(tag().text()).toContain("unavailable");

    store.entry = null;
    store.loadError = "No agent is running";
    expect(tag().text()).toContain("No agent is running");
  });
});
```

(Use the same pinia-mounting style as `UsageChip.test.ts` / `ShareDialog.test.ts` if `setActivePinia` alone is not enough to mount; follow whichever those use.)

Update the existing chat store tests: in `chat.test.ts`, `chat.approvals.test.ts`, `chat.forced.test.ts`, `chat.notify.test.ts` remove `import { useAgentsStore } from "./agents";` and every `useAgentsStore().agents = [...]` line; in expectations on `startTurn` drop `agent_id` (for example `expect(client.startTurn).toHaveBeenCalledWith("id", expect.objectContaining({ question: "hi" }))`). Add to `chat.test.ts`:

```ts
it("sends no agent id: ember_api picks the agent, and the chat takes the id it reports", async () => {
  const chat = await storeWith({});
  client.startTurn.mockResolvedValue({
    chat: { ...summary("new", 1), agent_id: "main", running: true },
    sequence: 1,
  });

  await chat.send("hello");

  const body = client.startTurn.mock.calls[0]![1];
  expect(body).not.toHaveProperty("agent_id");
  expect(chat.active?.agentId).toBe("main");
});
```

(Adapt `chat.active` to the accessor the existing tests use for the open conversation, e.g. `chat.conversations.find(...)`.)

- [ ] **Step 2: Run to verify they fail**

Run (from `ember_web/`): `npx vitest run src/utils/agentLabels.test.ts src/stores/entryAgent.test.ts src/components/EntryAgentTag.test.ts src/stores/chat.test.ts`
Expected: failures (modules missing; chat tests still import the agents store).

- [ ] **Step 3: Implement**

`src/utils/agentLabels.ts`:

```ts
/** The name to show for an agent id: its known label, else the id itself
 * (answers saved before the agent list went away name agents ember no longer lists). */
export function agentLabelFor(id: string | undefined, labels: Record<string, string>): string | undefined {
  if (!id) return undefined;
  return labels[id] ?? id;
}
```

`src/stores/entryAgent.ts`:

```ts
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { AiAgentClient } from "../api/AiAgentClient";
import { apiRequest, ApiError } from "../api/http";
import type { AgentInfo } from "../api/types";
import { useAuthStore } from "./auth";

/** The agent ember_api sends every question to (the main agent), for the
 * header and for naming answers. The browser never chooses an agent. */
export const useEntryAgentStore = defineStore("entryAgent", () => {
  const auth = useAuthStore();

  const entry = ref<AgentInfo | null>(null);
  const available = ref<boolean | null>(null); // null = not checked yet
  const loading = ref(false);
  const loadError = ref("");

  const labels = computed<Record<string, string>>(() => (entry.value ? { [entry.value.id]: entry.value.label } : {}));

  async function checkStatus(agent: AgentInfo): Promise<void> {
    try {
      available.value = (await new AiAgentClient(agent.id).status()).available !== false;
    } catch {
      available.value = false; // not running, or unreachable
    }
  }

  async function refresh(): Promise<void> {
    if (loading.value) return;
    loading.value = true;
    loadError.value = "";
    try {
      entry.value = await apiRequest<AgentInfo>("GET", "/api/agent");
    } catch (err) {
      entry.value = null;
      available.value = null;
      loadError.value = err instanceof ApiError || err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
    if (entry.value) await checkStatus(entry.value);
  }

  // Another user (or the same one once verified) may have different permissions.
  watch(
    () => `${auth.account?.id ?? ""}:${auth.account?.email_verified ?? ""}`,
    () => {
      entry.value = null;
      available.value = null;
      loadError.value = "";
      if (auth.hasPermission("chat.use")) void refresh();
    },
  );

  return { entry, available, labels, loading, loadError, refresh };
});
```

`src/components/EntryAgentTag.vue`:

```vue
<script setup lang="ts">
import { storeToRefs } from "pinia";
import { onMounted } from "vue";
import { useEntryAgentStore } from "../stores/entryAgent";

const store = useEntryAgentStore();
const { entry, available, loading, loadError } = storeToRefs(store);

onMounted(() => void store.refresh());
</script>

<template>
  <div class="agent-tag" :title="loadError">
    <template v-if="entry">
      Talking to <strong>{{ entry.label }}</strong
      ><span v-if="available === false" class="down"> (unavailable)</span>
    </template>
    <span v-else-if="loading" class="muted">loading ...</span>
    <span v-else class="down">{{ loadError || "No agent is running" }}</span>
    <button type="button" class="refresh" title="Check the agent again" :disabled="loading" @click="store.refresh()">↻</button>
  </div>
</template>

<style scoped>
.agent-tag {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.9em;
  color: var(--muted);
}
.agent-tag strong {
  color: var(--text);
}
.down {
  color: var(--danger);
}
.refresh {
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--muted);
  cursor: pointer;
}
</style>
```

(Copy the `.refresh` button styling from the deleted `AgentPicker.vue` if it differs; read it before deleting.)

Then:
- `git rm ember_web/src/components/AgentPicker.vue ember_web/src/stores/agents.ts`.
- `api/ChatsClient.ts`: delete `agent_id: string;` from `TurnStart`; change `summarize` to `summarize: (id: string) => apiRequest<ChatDetail>("POST", `${path(id)}/summarize`, {}),`.
- `api/types.ts`: update the `AgentInfo` doc comment to "The main agent, as ember_api's GET /api/agent returns it."
- `stores/chat.ts`:
  - delete `import { useAgentsStore } from "./agents";` and `const agents = useAgentsStore();`
  - in `send()` delete the `const agent = agents.selected; if (!agent) {...}` block; the new-conversation literal uses `agentId: undefined,` (delete the property) and delete `conversation.agentId = agent.id;`; delete `agent_id: agent.id,` from the `startTurn` body; after `const turn = await chatsClient.startTurn(...)` and `if (started !== generation) return;` add `conversation.agentId = turn.chat.agent_id ?? undefined;`
  - delete `if (chat.agent_id) agents.select(chat.agent_id);` (around line 723) and the "Reopening a chat switches back to the agent" block `if (conversation.agentId) agents.select(conversation.agentId);` (around line 804)
  - `summarize`: `chatsClient.summarize(id)`.
  - Update the `send` doc comment ("Asks the selected agent" → "Asks the main agent").
- `views/ChatView.vue`: replace `import AgentPicker ...` with `import EntryAgentTag from "../components/EntryAgentTag.vue";` and `import { useEntryAgentStore } from "../stores/entryAgent";`; replace `const agentsStore = useAgentsStore(); const agentLabels = computed(() => Object.fromEntries(...))` with `const entryAgent = useEntryAgentStore(); const agentLabels = computed(() => entryAgent.labels);`; the export line becomes `const agentLabel = agentLabelFor(conversation.agentId, entryAgent.labels) ?? null;` (import `agentLabelFor` from `../utils/agentLabels`); replace `<AgentPicker :locked="busy" />` with `<EntryAgentTag />`.
- `components/MessageList.vue`: `agentLabel(m)` returns `agentLabelFor(m.agent, props.agentLabels ?? {})` (import it) so unknown ids show as ids.
- `e2e/fakeApi.ts` line ~96: `if (method === "GET" && path === "/api/agent") return json(route, { id: "agent-1", label: "Test Agent" });`; `e2e/chat.spec.ts` line ~37: `expect(api.turns[0]).toMatchObject({ question: QUESTION });` and update the comment above it ("the question, no agent id, no tool approval asked for"). Keep the `/api/mcp/agents/agent-1` mock (the availability check).

- [ ] **Step 4: Run to verify they pass**

Run: `npx vitest run` → all pass; `npx vue-tsc -b --noEmit` → no output; `npx vite build` → success, then delete `ember_web/dist/`.
Do not run Playwright (the user runs e2e by hand).

- [ ] **Step 5: Commit (only after the user agrees)**

```bash
git add ember_web
git commit -m "ember_web: always talk to the main agent; the agent picker is gone"
```

---

### Task W2: Live "who is working" indicator

**ember_web gate: propose, wait for approval, then implement.**

**Files:**
- Create: `ember_web/src/components/AgentActivity.vue`, `ember_web/src/components/AgentActivity.test.ts`
- Modify: `ember_web/src/api/types.ts`, `ember_web/src/stores/chat.ts`, `ember_web/src/components/MessageList.vue`, `ember_web/src/stores/chat.agents.test.ts` (new)

**Interfaces:**
- Consumes: W1's `useEntryAgentStore().entry`; ember_api events `agent_start` / `agent_end` / `agent_token` and the snapshot's `active_agents` (E3).
- Produces:
  - `ActiveAgent { agent_id: string; label: string; since: string; step_id: string }` in `api/types.ts`
  - chat store: `activeAgents: Ref<ActiveAgent[]>`, `agentText: Ref<Record<string, string>>` (by delegate step id), both reset in `unfollow()` and on `final` / `error`
  - `AgentActivity.vue` (no props; reads the stores)

- [ ] **Step 1: Write the failing tests**

`src/stores/chat.agents.test.ts` — the harness is `chat.notify.test.ts`'s: a mocked `watchTurn` hands the store's event handler to the test, which calls it. (W1 has already removed the agents-store lines from that file; do the same here.)

```ts
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage, TurnEvent } from "../api/types";
import { watchTurn, type WatchEnd } from "../services/turnStream";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

vi.mock("../api/ChatsClient", () => ({
  chatsClient: {
    list: vi.fn(), get: vi.fn(), startTurn: vi.fn(), cancel: vi.fn(), search: vi.fn(), remove: vi.fn(),
    removeAll: vi.fn(), rename: vi.fn(), importChats: vi.fn(), append: vi.fn(), branch: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({
  chimeIfAway: vi.fn(), notifyIfAway: vi.fn(), notificationsSupported: vi.fn(() => false), requestNotifyPermission: vi.fn(),
}));

const client = vi.mocked(chatsClient);
const watch = vi.mocked(watchTurn);

const summary = (id: string, count = 0, running = false): ChatSummary => ({
  id, title: `Chat ${id}`, agent_id: "main", message_count: count,
  created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00", running,
});
const TWO: ChatMessage[] = [{ role: "user", content: "q1" }, { role: "assistant", content: "a1" }];

let emit: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};
const fire = (event: Record<string, unknown>) => emit({ sequence: 1, ...event } as TurnEvent);

/** The store with chat c1 open and an answer being written; `emit` reaches its event handler. */
async function runningTurn() {
  setActivePinia(createPinia());
  useAuthStore().account = {
    id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use"],
  };
  client.list.mockResolvedValue([summary("c1", 2)]);
  client.get.mockImplementation(async (id: string) => ({ ...summary(id, 2), messages: structuredClone(TWO) }));
  const chat = useChatStore();
  await flushPromises();
  await chat.selectChat("c1");
  await chat.send("ask something");
  return { chat, emit: fire };
}

beforeEach(() => {
  vi.clearAllMocks();
  watch.mockImplementation(
    (_id, _after, onEvent) =>
      new Promise<WatchEnd>(() => {
        emit = onEvent;
      }),
  );
  client.startTurn.mockResolvedValue({ chat: summary("c1", 2, true), sequence: 5 });
  client.search.mockResolvedValue([]);
});
```

In the tests below `emit({...})` means `fire` from `runningTurn()`: call it with the event's fields; it adds `sequence: 1` unless the object already has one (spread order: put your own `sequence` after the helper's by writing `fire({ sequence: 2, ... })`; in these tests the sequence value does not matter). Then:

```ts
describe("live agent activity", () => {
  it("tracks who is working from agent_start / agent_end", async () => {
    const { chat, emit } = await runningTurn(); // helper copied from chat.notify.test.ts

    emit({ type: "agent_start", sequence: 1, agent_id: "calc", agent_label: "Calculator", delegated_by: "main", question: "2+2", step_id: "d1", at: "2026-10-04T09:12:03.512Z" });
    expect(chat.activeAgents).toEqual([{ agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:03.512Z", step_id: "d1" }]);

    emit({ type: "agent_end", sequence: 2, agent_id: "calc", agent_label: "Calculator", ok: true, step_id: "d1", at: "2026-10-04T09:12:07.044Z" });
    expect(chat.activeAgents).toEqual([]);
  });

  it("collects a specialist's text under its delegate step, and a reset clears it", async () => {
    const { chat, emit } = await runningTurn();

    emit({ type: "agent_token", sequence: 1, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "15% of " });
    emit({ type: "agent_token", sequence: 2, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "2,340" });
    expect(chat.agentText).toEqual({ d1: "15% of 2,340" });
    expect(chat.streaming).toBe(""); // never mixed into the answer

    emit({ type: "agent_token", sequence: 3, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "", reset: true });
    expect(chat.agentText).toEqual({ d1: "" });
  });

  it("restores the working agents from a snapshot", async () => {
    const { chat, emit } = await runningTurn();

    emit({ type: "snapshot", sequence: 5, text: "so far", activity: "", steps: [], approvals: [],
      active_agents: [{ agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:03.512Z", step_id: "d1" }] });

    expect(chat.activeAgents.map((a) => a.agent_id)).toEqual(["calc"]);
  });

  it("clears everything when the answer ends, even if agent_end never came", async () => {
    const { chat, emit } = await runningTurn();
    emit({ type: "agent_start", sequence: 1, agent_id: "calc", agent_label: "Calculator", delegated_by: "main", question: "q", step_id: "d1", at: "2026-10-04T09:12:03.512Z" });

    emit({ type: "final", sequence: 2, message: { role: "assistant", content: "done" }, cancelled: false });

    expect(chat.activeAgents).toEqual([]);
    expect(chat.agentText).toEqual({});
  });
});
```

`src/components/AgentActivity.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AgentActivity from "./AgentActivity.vue";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";

vi.mock("../api/ChatsClient", () => ({ chatsClient: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn(() => Promise.resolve("aborted")) }));

const T0 = Date.parse("2026-10-04T09:12:00Z");
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0 + 3000);
  setActivePinia(createPinia());
  useEntryAgentStore().entry = { id: "main", label: "Ember" };
});
afterEach(() => vi.useRealTimers());

describe("AgentActivity", () => {
  it("is hidden while only the main agent works", () => {
    expect(mount(AgentActivity).text()).toBe("");
  });

  it("shows the chain of working agents with a clock for the innermost", () => {
    useChatStore().activeAgents = [
      { agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:00.000Z", step_id: "d1" },
    ];

    const text = mount(AgentActivity).text();

    expect(text).toContain("Ember → Calculator");
    expect(text).toContain("3.0 s");
  });

  it("shows nested agents in order", () => {
    useChatStore().activeAgents = [
      { agent_id: "a", label: "Alpha", since: "2026-10-04T09:12:00.000Z", step_id: "1" },
      { agent_id: "b", label: "Beta", since: "2026-10-04T09:12:01.000Z", step_id: "2" },
    ];

    expect(mount(AgentActivity).text()).toContain("Ember → Alpha → Beta");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/stores/chat.agents.test.ts src/components/AgentActivity.test.ts` → failures (no `activeAgents`, no component).

- [ ] **Step 3: Types** (`api/types.ts`)

Add:

```ts
/** An agent that is working on the running answer right now (ember_api's `active_agents`). */
export interface ActiveAgent {
  agent_id: string;
  label: string;
  /** When it started (ISO-8601 UTC). */
  since: string;
  /** The orchestrator's delegate_to_agent step that handed it its question. */
  step_id: string;
}
```

Extend `TurnEvent`: add `active_agents?: ActiveAgent[]` to the `snapshot` member; add `agent_id?: string; agent_label?: string;` to the `step_start`, `step_progress`, `step_end` members; add the members

```ts
  | { type: "agent_start"; agent_id: string; agent_label: string; delegated_by: string; question: string; step_id: string; at: string }
  | { type: "agent_end"; agent_id: string; agent_label: string; ok: boolean; step_id: string; at: string }
  | { type: "agent_token"; agent_id: string; agent_label: string; step_id: string; text: string; reset?: boolean }
```

- [ ] **Step 4: Chat store** (`stores/chat.ts`)

Import `ActiveAgent` in the `type` import list. Next to `liveSteps`:

```ts
  const activeAgents = ref<ActiveAgent[]>([]); // delegated agents working on the answer, outermost first
  const agentText = ref<Record<string, string>>({}); // a delegated agent's streamed text, by delegate step id
```

In `onEvent`: in `case "snapshot":` add `activeAgents.value = event.active_agents ?? []; agentText.value = {};`. Add cases before `case "final"`:

```ts
      case "agent_start":
        activeAgents.value = [
          ...activeAgents.value,
          { agent_id: event.agent_id, label: event.agent_label, since: event.at, step_id: event.step_id },
        ];
        break;
      case "agent_end":
        activeAgents.value = activeAgents.value.filter(
          (a) => !(a.step_id === event.step_id && a.agent_id === event.agent_id),
        );
        break;
      case "agent_token":
        agentText.value = {
          ...agentText.value,
          [event.step_id]: event.reset ? "" : ((agentText.value[event.step_id] ?? "") + event.text).slice(-20_000),
        };
        break;
```

and in `case "final":` and `case "error":` add `activeAgents.value = []; agentText.value = {};` (before the existing assignment). In `unfollow()` add the same two resets. Add `activeAgents,` and `agentText,` to the returned object (next to `activity`).

Also give live steps their id and agent so W3 can use them: in `case "step_start":` the pushed object gains `id: event.id,` and `...(event.agent_id ? { agent_id: event.agent_id, agent_label: event.agent_label ?? "" } : {}),`. (`ToolStep` gets optional `id`, `agent_id`, `agent_label` in Task W3; add them to `ToolStep` now in `types.ts` as optional so this compiles:)

```ts
  /** Live steps only: the step's id in the event stream. */
  id?: string;
  /** Which agent ran it, when a delegated agent did (absent for the main agent's own steps and older answers). */
  agent_id?: string;
  agent_label?: string;
```

- [ ] **Step 5: Component** (`components/AgentActivity.vue`)

```vue
<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";
import ElapsedTime from "./ElapsedTime.vue";

/** While an answer is written: which agent is working ("Ember → Calculator")
 * and for how long the innermost one has. Hidden when only the main agent works. */
const { activeAgents } = storeToRefs(useChatStore());
const { entry } = storeToRefs(useEntryAgentStore());

const chain = computed(() => [entry.value?.label ?? "Agent", ...activeAgents.value.map((a) => a.label || a.agent_id)].join(" → "));
const since = computed(() => {
  const innermost = activeAgents.value[activeAgents.value.length - 1];
  const parsed = innermost ? Date.parse(innermost.since) : NaN;
  return Number.isNaN(parsed) ? null : parsed;
});
</script>

<template>
  <div v-if="activeAgents.length" class="agent-activity" role="status">
    <span class="dot" />{{ chain }}<template v-if="since !== null"> · <ElapsedTime :since="since" /></template>
  </div>
</template>

<style scoped>
.agent-activity {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--muted);
  font-size: 0.9em;
}
.dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--accent);
}
</style>
```

(If `MessageList.vue`'s `.dot` has an animation, reuse that class name/animation by copying its keyframes rule.)

- [ ] **Step 6: Place it** (`components/MessageList.vue`)

Import `AgentActivity` and render `<AgentActivity />` immediately above the `<span v-if="activity" class="activity">` line (~338), inside the same live-answer block.

- [ ] **Step 7: Run to verify they pass**

`npx vitest run` → green; `npx vue-tsc -b --noEmit` → no output; `npx vite build` then delete `dist/`.

- [ ] **Step 8: Commit (after the user agrees)**

```bash
git add ember_web
git commit -m "ember_web: show which agent is working while an answer is written"
```

---

### Task W3: Steps per agent, and a delegated agent's text

**ember_web gate: propose, wait for approval, then implement.**

**Files:**
- Modify: `ember_web/src/components/ToolSteps.vue`
- Create: `ember_web/src/components/ToolSteps.test.ts`

**Interfaces:**
- Consumes: `ToolStep.id` / `agent_id` / `agent_label` (W2), `useChatStore().agentText`, `useEntryAgentStore().entry`.
- Produces: an agent badge on a step whose `agent_id` differs from the main agent's, and (live only) a collapsible "<label> is working" block with the delegated agent's streamed text inside the matching `delegate_to_agent` step.

- [ ] **Step 1: Write the failing tests**

`src/components/ToolSteps.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ToolStep } from "../api/types";
import ToolSteps from "./ToolSteps.vue";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";

vi.mock("../api/ChatsClient", () => ({ chatsClient: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn(() => Promise.resolve("aborted")) }));

beforeEach(() => {
  setActivePinia(createPinia());
  useEntryAgentStore().entry = { id: "main", label: "Ember" };
});

const own: ToolStep = { tool: "delegate_to_agent", label: "Delegate", arguments: {}, ok: true, result: "4", id: "d1", agent_id: "main", agent_label: "Ember" };
const nested: ToolStep = { tool: "tool_calc", label: "Calc", arguments: {}, ok: true, result: "4", id: "d1", agent_id: "calc", agent_label: "Calculator" };

describe("ToolSteps agents", () => {
  it("badges only the steps a delegated agent ran", () => {
    const wrapper = mount(ToolSteps, { props: { steps: [own, nested] } });

    const badges = wrapper.findAll(".agent-badge");
    expect(badges.map((b) => b.text())).toEqual(["Calculator"]);
  });

  it("shows no badge on older answers whose steps name no agent", () => {
    const old: ToolStep = { tool: "t", label: "T", arguments: {}, ok: true, result: "" };

    expect(mount(ToolSteps, { props: { steps: [old] } }).find(".agent-badge").exists()).toBe(false);
  });

  it("shows a delegated agent's live text inside its delegate step", () => {
    useChatStore().agentText = { d1: "15% of 2,340 is 351" };
    const live: ToolStep = { ...own, ok: null, result: "" };

    const wrapper = mount(ToolSteps, { props: { steps: [live], live: true } });

    expect(wrapper.text()).toContain("is working");
    expect(wrapper.text()).toContain("15% of 2,340 is 351");
  });

  it("does not show live text on a saved answer", () => {
    useChatStore().agentText = { d1: "leftover" };

    expect(mount(ToolSteps, { props: { steps: [own] } }).text()).not.toContain("leftover");
  });
});
```

(The live-text block's label is "{agent label} is working"; the agent label comes from the delegated agent that the text belongs to. Because `agentText` is keyed by delegate step id only, take the label from `activeAgents` with that `step_id`, falling back to "Delegated agent".)

- [ ] **Step 2: Run to verify they fail**

`npx vitest run src/components/ToolSteps.test.ts` → failures.

- [ ] **Step 3: Implement** (`ToolSteps.vue`)

Script additions:

```ts
import { storeToRefs } from "pinia";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";

const { agentText, activeAgents } = storeToRefs(useChatStore());
const { entry } = storeToRefs(useEntryAgentStore());

/** The agent that ran a step, when it was a delegated one (not the main agent). */
function badge(step: ToolStep): string | null {
  if (!step.agent_id || step.agent_id === entry.value?.id) return null;
  return step.agent_label || step.agent_id;
}

/** A delegated agent's text so far, for the delegate step that handed it its question. */
function workingText(step: ToolStep): string {
  return props.live && step.id && step.agent_id === entry.value?.id ? (agentText.value[step.id] ?? "") : "";
}

function workingLabel(step: ToolStep): string {
  return activeAgents.value.find((a) => a.step_id === step.id)?.label || "Delegated agent";
}
```

Template: inside `<summary>` after the title span add `<span v-if="badge(step)" class="agent-badge">{{ badge(step) }}</span>`; inside `.detail` before the result add

```vue
        <details v-if="workingText(step)" class="agent-text" open>
          <summary>{{ workingLabel(step) }} is working</summary>
          <pre>{{ workingText(step) }}</pre>
        </details>
```

Styles (scoped, theme tokens only):

```css
.agent-badge {
  margin-left: 0.4rem;
  padding: 0 0.4rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--accent);
  font-size: 0.85em;
}
.agent-text {
  margin: 0.3rem 0;
}
.agent-text pre {
  background: var(--code-bg);
  font-family: var(--mono);
  white-space: pre-wrap;
}
```

- [ ] **Step 4: Run to verify they pass**

`npx vitest run` → green; `npx vue-tsc -b --noEmit` → no output; `npx vite build`, delete `dist/`.

- [ ] **Step 5: Commit (after the user agrees)**

```bash
git add ember_web
git commit -m "ember_web: badge steps run by a delegated agent and show its live text"
```

---

### Task W4: Answer usage shows agent, provider, gateway and time

**ember_web gate: propose, wait for approval, then implement.**

**Files:**
- Modify: `ember_web/src/api/types.ts` (`AgentUsage`), `ember_web/src/utils/usageFormat.ts`, `ember_web/src/components/UsageChip.vue`
- Test: `ember_web/src/utils/usageFormat.test.ts`, `ember_web/src/components/UsageChip.test.ts` (extend)

**Interfaces:**
- Consumes: saved `agent_usage` entries from E4 (`agent`, `agent_label`, `provider_id`, `gateway`, `model`, tokens, `started_at`, `finished_at`).
- Produces: `AgentUsage` with those optional fields; `agentUsageText(a)` now includes provider/gateway; the chip panel lists each agent by label.

- [ ] **Step 1: Write the failing tests**

Read the existing `agentUsageText` tests in `usageFormat.test.ts` and `UsageChip.test.ts` first and extend them with these cases (keep the old expectations that still hold; the old text format must be unchanged when no new fields are present):

```ts
it("adds provider and gateway when known", () => {
  expect(
    agentUsageText({ agent: "calc", model: "gpt-x", provider_id: "openai", gateway: "azure", input_tokens: 20, output_tokens: 5, total_tokens: 25 }),
  ).toBe("gpt-x · openai via azure · 20 in · 5 out · 25 total");
});

it("leaves out the gateway when the provider was used directly", () => {
  expect(agentUsageText({ agent: "calc", model: "m", provider_id: "anthropic", total_tokens: 9 })).toContain("anthropic");
  expect(agentUsageText({ agent: "calc", model: "m", provider_id: "anthropic", total_tokens: 9 })).not.toContain("via");
});
```

and in `UsageChip.test.ts`:

```ts
it("lists each agent by its label, with when its call ran", async () => {
  const message: ChatMessage = {
    role: "assistant", content: "x", agent: "main", total_tokens: 125,
    agent_usage: [
      { agent: "main", agent_label: "Ember", model: "m1", total_tokens: 100 },
      { agent: "calc", agent_label: "Calculator", model: "m2", total_tokens: 25, started_at: "2026-10-04T09:12:04.000Z", finished_at: "2026-10-04T09:12:05.250Z" },
    ],
  };
  const wrapper = mount(UsageChip, { props: { message } });
  await wrapper.find("summary, button, .chip").trigger("click"); // open the panel the way the existing tests do

  expect(wrapper.text()).toContain("Calculator");
  expect(wrapper.text()).toContain("1.3 s"); // finished - started, to a tenth
});
```

(Match how the existing `UsageChip.test.ts` opens the details panel; copy that line.)

- [ ] **Step 2: Run to verify they fail**

`npx vitest run src/utils/usageFormat.test.ts src/components/UsageChip.test.ts` → failures.

- [ ] **Step 3: Implement**

`types.ts` — extend:

```ts
export interface AgentUsage {
  /** The agent's id (older answers: its provider's name). */
  agent: string;
  agent_label?: string;
  provider_id?: string;
  /** Null/absent: the provider was used directly. */
  gateway?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens: number;
  /** When the agent's call began and ended (ISO-8601 UTC). */
  started_at?: string;
  finished_at?: string;
}
```

`usageFormat.ts` — read `agentUsageText` and change it to put `provider_id` / `via gateway` right after the model:

```ts
const where = a.provider_id ? (a.gateway ? `${a.provider_id} via ${a.gateway}` : a.provider_id) : "";
// parts: [model, where, "N in", "N out", "N total"] joined with " · ", skipping empty ones
```

Add:

```ts
/** How long an agent's call took, "1.3 s", or "" when the times are missing. */
export function agentDuration(a: AgentUsage): string {
  const start = a.started_at ? Date.parse(a.started_at) : NaN;
  const end = a.finished_at ? Date.parse(a.finished_at) : NaN;
  return Number.isNaN(start) || Number.isNaN(end) || end < start ? "" : formatDuration((end - start) / 1000);
}
```

(use the existing `formatDuration` signature — read it; it may take seconds or milliseconds and have its own rounding, in which case the test's "1.3 s" should match its output for 1.25 s.)

`UsageChip.vue` — in the loop over `m.agent_usage` use `label: a.agent_label ?? a.agent` and `value: [agentUsageText(a), agentDuration(a)].filter(Boolean).join(" · ")`.

- [ ] **Step 4: Run to verify they pass**

`npx vitest run` → green; type-check and build as before.

- [ ] **Step 5: Commit (after the user agrees)**

```bash
git add ember_web
git commit -m "ember_web: answer usage names each agent with its provider, gateway and call time"
```

---

### Task W5: Usage page — group by, filters and a records table

**ember_web gate: propose, wait for approval, then implement.**

**Files:**
- Modify: `ember_web/src/api/UsageClient.ts`, `ember_web/src/views/UsageView.vue`, `ember_web/src/utils/usageExport.ts`
- Test: `ember_web/src/views/UsageView.test.ts` (extend), `ember_web/src/utils/usageExport.test.ts` (extend)

**Interfaces:**
- Consumes: `GET /api/usage?group_by=&agent=&provider=` and `GET /api/usage/records` (E5).
- Produces:
  - `UsageGroupBy = "agent" | "provider" | "gateway" | "model"`
  - `UsageReport.group_by`, `UsageReport.groups: { key: string; tokens: number; input_tokens: number; output_tokens: number; turns: number }[]`
  - `UsageRecordRow` (fields as `UsageRecordOut` in E5, times as strings)
  - `usageClient.mine(days, since?, options?: { groupBy?: UsageGroupBy; agent?: string; provider?: string })`
  - `usageClient.records(days, since?, options?: { agent?: string; provider?: string; limit?: number })`

- [ ] **Step 1: Write the failing tests**

Read `UsageView.test.ts` first (it mocks `usageClient`); extend it:

```ts
it("groups the report by the chosen field", async () => {
  mine.mockResolvedValue(report({ group_by: "agent", groups: [{ key: "calc", tokens: 30, input_tokens: 20, output_tokens: 10, turns: 1 }] }));
  const wrapper = await mountView();

  await wrapper.find("select.group-by").setValue("provider");

  expect(mine).toHaveBeenLastCalledWith(30, undefined, expect.objectContaining({ groupBy: "provider" }));
});

it("lists each row with its provider, gateway and time", async () => {
  records.mockResolvedValue([
    { id: 1, turn_id: "t", kind: "chat", chat_id: "c", agent: "calc", agent_id: "calc", provider_id: "openai", gateway: "azure",
      model: "gpt-x", input_tokens: 20, output_tokens: 5, total_tokens: 25, started_at: "2026-10-04T09:12:04", finished_at: "2026-10-04T09:12:05",
      delegated_by: "main", created_at: "2026-10-04T09:12:06" },
  ]);
  const wrapper = await mountView();

  const row = wrapper.find("table.records tbody tr").text();
  expect(row).toContain("calc");
  expect(row).toContain("openai");
  expect(row).toContain("azure");
  expect(row).toContain("25");
});
```

(`report()`, `mine`, `records`, `mountView` follow the helpers already in that file; add `records: vi.fn()` to its `usageClient` mock and a default `records.mockResolvedValue([])` in `beforeEach`. If the existing `report()` helper builds a `UsageReport`, add `group_by: "agent", groups: []` defaults to it.)

`usageExport.test.ts`: add a case that a report with `groups` for `group_by: "provider"` exports a `## By provider` table (`| Provider | Tokens | Turns |`); keep the existing "By agent" table.

- [ ] **Step 2: Run to verify they fail**

`npx vitest run src/views/UsageView.test.ts src/utils/usageExport.test.ts` → failures.

- [ ] **Step 3: Client** (`UsageClient.ts`)

Add the types and extend the client:

```ts
export type UsageGroupBy = "agent" | "provider" | "gateway" | "model";

export interface UsageGroup {
  key: string;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  turns: number;
}

/** One stored usage row: an agent's call in a turn. Times are naive UTC. */
export interface UsageRecordRow {
  id: number;
  turn_id: string;
  kind: string;
  chat_id: string | null;
  agent: string | null;
  agent_id: string | null;
  provider_id: string | null;
  gateway: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number;
  started_at: string | null;
  finished_at: string | null;
  delegated_by: string | null;
  created_at: string;
}

export interface UsageFilters {
  agent?: string;
  provider?: string;
}
```

`UsageReport` gains `group_by: UsageGroupBy; groups: UsageGroup[];`. Replace `mine` and add `records`:

```ts
function query(days: number, since: string | undefined, extra: Record<string, string | number | undefined>): string {
  const parts = [period(days, since)];
  for (const [name, value] of Object.entries(extra)) {
    if (value !== undefined && value !== "") parts.push(`${name}=${encodeURIComponent(String(value))}`);
  }
  return parts.join("&");
}

  mine: (days: number, since?: string, options: UsageFilters & { groupBy?: UsageGroupBy } = {}) =>
    apiRequest<MyUsage>(
      "GET",
      `/api/usage?${query(days, since, { group_by: options.groupBy, agent: options.agent, provider: options.provider })}`,
    ),
  /** This account's rows, newest first (limit 1-500). */
  records: (days: number, since?: string, options: UsageFilters & { limit?: number } = {}) =>
    apiRequest<UsageRecordRow[]>(
      "GET",
      `/api/usage/records?${query(days, since, { agent: options.agent, provider: options.provider, limit: options.limit })}`,
    ),
```

(Existing callers `usageClient.mine(days, since)` and `mine(366)` stay valid.)

- [ ] **Step 4: View** (`UsageView.vue`)

Script: `const groupBy = ref<UsageGroupBy>("agent");` and `const records = ref<UsageRecordRow[]>([]);`. `load()` passes `{ groupBy: groupBy.value }` to `mine` and also fetches `usageClient.records(days, since, { limit: 100 })` in the same `Promise.all` (a failed records fetch must not hide the report: catch it separately into `records.value = []`). `watch([range, groupBy], load)`. Add a `groupHeading` computed: `{ agent: "Agent", provider: "Provider", gateway: "Gateway", model: "Model" }[groupBy.value]`.

Template: next to the existing "By agent" section add

```vue
      <section>
        <h3>
          By
          <select v-model="groupBy" class="group-by" aria-label="Group usage by">
            <option value="agent">agent</option>
            <option value="provider">provider</option>
            <option value="gateway">gateway</option>
            <option value="model">model</option>
          </select>
        </h3>
        <p v-if="usage.report.groups.length === 0" class="muted">None.</p>
        <table v-else class="groups">
          <thead><tr><th>{{ groupHeading }}</th><th>Tokens</th><th>In</th><th>Out</th><th>Turns</th></tr></thead>
          <tbody>
            <tr v-for="g in usage.report.groups" :key="g.key">
              <td>{{ g.key }}</td><td>{{ tokens(g.tokens) }}</td><td>{{ tokens(g.input_tokens) }}</td><td>{{ tokens(g.output_tokens) }}</td><td>{{ g.turns }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h3>Recent calls</h3>
        <p v-if="records.length === 0" class="muted">None.</p>
        <table v-else class="records">
          <thead><tr><th>When</th><th>Agent</th><th>Provider</th><th>Gateway</th><th>Model</th><th>In</th><th>Out</th><th>Total</th></tr></thead>
          <tbody>
            <tr v-for="r in records" :key="r.id">
              <td>{{ localTime(r.started_at ?? r.created_at) }}</td>
              <td>{{ r.agent_id ?? r.agent ?? "unknown" }}<span v-if="r.delegated_by" class="muted"> ← {{ r.delegated_by }}</span></td>
              <td>{{ r.provider_id ?? "-" }}</td>
              <td>{{ r.gateway ?? "-" }}</td>
              <td>{{ r.model ?? "-" }}</td>
              <td>{{ r.input_tokens === null ? "-" : tokens(r.input_tokens) }}</td>
              <td>{{ r.output_tokens === null ? "-" : tokens(r.output_tokens) }}</td>
              <td>{{ tokens(r.total_tokens) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
```

with

```ts
/** A naive-UTC API time as the viewer's local date and time. */
function localTime(value: string): string {
  return new Date(`${value}${value.endsWith("Z") ? "" : "Z"}`).toLocaleString();
}
```

Reuse the existing table/section CSS classes of the "By agent" table (copy its class names; add `.group-by` styling: `background: var(--surface); color: var(--text); border: 1px solid var(--border);`). The existing "By agent" section and `favorite agent` stat stay (they read `by_agent`).

`usageExport.ts`: after the "By agent" table add a table for `report.groups` titled `## By <group_by>` when `report.group_by !== "agent"`, with columns `| <Heading> | Tokens | Turns |` using the same `cell()` / `n()` helpers.

- [ ] **Step 5: Run to verify they pass**

`npx vitest run` → green; `npx vue-tsc -b --noEmit` → no output; `npx vite build`, delete `dist/`.

- [ ] **Step 6: Commit (after the user agrees)**

```bash
git add ember_web
git commit -m "ember_web: usage page groups by agent/provider/gateway/model and lists each call with its time"
```

---

### Task W6: ember_web README and the e2e assertion

**ember_web gate: propose, wait for approval, then implement.**

**Files:** Modify `ember_web/README.md`, `ember_web/e2e/chat.spec.ts`, `ember_web/e2e/fakeApi.ts`.

- [ ] **Step 1: README**

Replace mentions of the agent picker with "Talking to <agent>" (the main agent; ember_api chooses), add the live "Ember → Calculator" indicator, the step badges, and the Usage page's group-by selector and Recent calls table; remove `stores/agents.ts` / `AgentPicker.vue` from the layout list and add `stores/entryAgent.ts`, `AgentActivity.vue`, `EntryAgentTag.vue`.

- [ ] **Step 2: e2e**

In `e2e/fakeApi.ts` add to the turn stream a delegated agent: before the answer's tokens emit `agent_start` (`agent_id: "calc"`, `agent_label: "Calculator"`, `step_id: "d1"`, `at`, `question`, `delegated_by: "agent-1"`) and, after a short pause, `agent_end`; make the fake `/api/usage` and `/api/usage/records` return `groups: []` and `[]`. In `e2e/chat.spec.ts` after sending the question assert `await expect(page.getByText("Ember → Calculator")).toBeVisible()` — use the fake agent's label (`Test Agent → Calculator`) and keep the existing assertions; assert there is no element with the old picker's `#agent-select`.

(The user runs `npx playwright test` by hand; do not run it.)

- [ ] **Step 3: Verify and commit (after the user agrees)**

`npx vue-tsc -b --noEmit` → no output (the e2e files are type-checked by the node config; if `vue-tsc -b` does not cover them, run `npx tsc -p tsconfig.node.json --noEmit` if it does).

```bash
git add ember_web
git commit -m "ember_web: document the main-agent flow and cover the live agent indicator in e2e"
```
