# Laya Question Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Laya tool shortlisting and Laya agent routing from ai_agent, and turn the Laya provider into a generic typed-question answerer (`choice`, `score`, `noul`) driven by a caller-supplied JSON schema.

**Architecture:** Three independent removals/rewrites, in an order that keeps every commit green. Task 1 drops `routing.*` and `agent_id="auto"` (this also removes the last non-provider import of `tool_selection`). Task 2 deletes `tool_selection` and its config. Task 3 rewrites `laya_provider.py` around a validated JSON request and a JSON response. Any "ask a real LLM when uncertain" logic stays in the orchestrator LLM, which reads the `uncertain` flags. No cascade code.

**Tech Stack:** Python, pytest, `laya` 0.3.26 (optional extra), anyio.

**Spec:** `docs/superpowers/specs/2026-10-09-laya-question-provider-design.md`

## Global Constraints

- Work in `apps/ai_agent`. Repo root for git is `D:\User\Documents\Programming\Python\MCPServer`; stage paths as `apps/ai_agent/...`.
- Test command (run from `apps/ai_agent`): `.venv_ai_agent/Scripts/python.exe -m pytest tests -q`. Below this is written `$PY -m pytest ...`; set `PY=.venv_ai_agent/Scripts/python.exe`.
- Never read `.env*` or `secrets/`. Ignore `.venv_ai_agent`, `node_modules`, `__pycache__`.
- `laya` stays an optional extra in `pyproject.toml` (`laya = ["laya"]`). Do not edit it.
- Laya limits (verbatim from spec): 512-token context (`CONTEXT_WINDOW`), `text` at most 4000 characters, 1 to 8 questions, 2 to 10 options per `choice`/`score` question, default `min_confidence` 0.7.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Edit docs/READMEs in plain English; code comments match surrounding density (short).

---

### Task 1: Remove `routing.*` and `agent_id="auto"`

**Files:**
- Modify: `apps/ai_agent/src/agents/agent_spec.py` (lines 8, 42, 45, 94-99, 139, 300-309, 325)
- Modify: `apps/ai_agent/src/agents/agent_routing.py` (full rewrite)
- Modify: `apps/ai_agent/src/agents/delegation.py` (lines 7, 34, 41, 90-94, 126-128, 138, 196-200, 265)
- Modify: `apps/ai_agent/src/llm/anthropic_provider.py` (lines 246-251, 280)
- Modify: `apps/ai_agent/src/llm/openai_provider.py` (lines 223-229, 290)
- Modify: `apps/ai_agent/agents/ember.json` (remove `routing`)
- Test: `apps/ai_agent/tests/test_agent_routing.py` (rewrite), `test_agent_spec.py`, `test_delegation.py`, `test_effort.py`, `test_agent_registry.py:272`

**Interfaces:**
- Produces: `agent_routing.specialists() -> list[RosterEntry]` (unchanged); `agent_routing.roster_for() -> list[RosterEntry]` (async, **no argument now**); `delegation.tool_parameters(roster)`, `delegation.tool_description(roster)` (no `allow_auto`); `AgentSpec` has no `routing` field; `RoutingSpec` and `delegation.AUTO_AGENT_ID` no longer exist.

- [ ] **Step 1: Rewrite `tests/test_agent_routing.py`**

Replace the whole file with:

```python
"""agent_routing.py tests: the roster is built per turn from the registry
(self and other orchestrators excluded)."""

from __future__ import annotations

import asyncio

import pytest

from src.agents import agent_registry, agent_routing, agent_spec
from src.agents.agent_spec import AgentSpec, LlmSpec

AGENTS = [
    {"id": "orchestrator", "label": "Ember", "url": "u", "orchestrator": True, "focus": "coordination"},
    {"id": "calc", "label": "Calculator", "url": "u", "focus": "arithmetic and units"},
    {"id": "explainer", "label": "Explainer", "url": "u", "focus": "plain explanations"},
    {"id": "poet", "label": "Poet", "url": "u", "focus": "poems"},
    {"id": "blank", "label": "Blank", "url": "u"},
]


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(agent_registry, "reload", lambda: None)
    monkeypatch.setattr(agent_registry, "_AGENTS", AGENTS)
    monkeypatch.setattr(agent_registry, "_AGENTS_BY_ID", {a["id"]: a for a in AGENTS})


def _use(monkeypatch, orchestrator=True):
    spec = AgentSpec(id="orchestrator", label="Ember", port=9100, llm=LlmSpec(provider="anthropic"),
                     orchestrator=orchestrator)
    monkeypatch.setattr(agent_spec, "_current", spec)


def test_specialists_exclude_self_and_orchestrators(registry, monkeypatch):
    _use(monkeypatch)
    assert [r.id for r in agent_routing.specialists()] == ["calc", "explainer", "poet", "blank"]


def test_non_orchestrator_has_no_roster(registry, monkeypatch):
    _use(monkeypatch, orchestrator=False)
    assert asyncio.run(agent_routing.roster_for()) == []


def test_orchestrator_roster_is_every_specialist(registry, monkeypatch):
    _use(monkeypatch)
    assert [r.id for r in asyncio.run(agent_routing.roster_for())] == ["calc", "explainer", "poet", "blank"]


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

- [ ] **Step 2: Update `tests/test_agent_spec.py`**

1. Delete line 36 (`    assert spec.routing.top_k == 3`).
2. In `test_load_file_reads_every_field`, delete the `"routing": {...},` line from `data` (line 79) and the two assertions `assert spec.routing.laya is True` and `assert spec.routing.min_score == 0.3` (lines 88-89).
3. In `test_load_file_rejects_bad_fields`, delete the six `routing` rows (lines 107-109 and 116-118) and add in their place one row:

```python
        ({"port": 9100, "llm": {"provider": "anthropic"}, "orchestrator": True, "routing": {"laya": True}}, "routing"),
```

- [ ] **Step 3: Update `tests/test_delegation.py`, `tests/test_effort.py`, `tests/test_agent_registry.py`**

Run from `apps/ai_agent`:

```bash
sed -i 's/, allow_auto=False)/)/g' tests/test_delegation.py tests/test_effort.py
sed -i 's/agent_routing.roster_for("q")/agent_routing.roster_for()/' tests/test_agent_registry.py
```

Then in `tests/test_delegation.py`:
- Delete the three tests `test_tool_parameters_offer_auto_when_allowed`, `test_call_resolves_auto_through_routing` and `test_attachment_metadata_does_not_change_auto_routing` entirely.
- Rename `test_tool_description_lists_the_roster_and_auto` to `test_tool_description_lists_the_roster` and replace its body with:

```python
    description = delegation.tool_description(ROSTER)
    assert "calc (Calculator): Arithmetic." in description
    assert '"auto"' not in description
```

(After the sed, `delegation.tool_description(ROSTER, allow_auto=True)` is not matched by the sed, so edit that call by hand as above. Also grep `allow_auto` in `tests/` and fix any leftover.)

- [ ] **Step 4: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_agent_routing.py tests/test_agent_spec.py tests/test_delegation.py tests/test_effort.py tests/test_agent_registry.py -q`
Expected: FAIL (`roster_for() takes ...`/`tool_parameters() got an unexpected ...`, unknown `routing` still accepted).

- [ ] **Step 5: Implement**

`src/agents/agent_routing.py` (replace whole file):

```python
"""Which specialists an orchestrator offers the model this turn.

The roster is re-read from the registry every turn (specialists start and
stop independently).
"""

from __future__ import annotations

import anyio.to_thread

from src.agents import agent_registry, agent_spec
from src.agents.agent_spec import RosterEntry
from src.llm import model_tiers, reasoning_effort


def specialists() -> list[RosterEntry]:
    """Every registered non-orchestrator agent except this one. Blocking
    (re-reads the registry file) - call from a worker thread."""
    agent_registry.reload()
    me = agent_spec.current().id
    return [
        RosterEntry(
            a["id"], a.get("label") or a["id"], a.get("focus") or "",
            model_tiers.from_records(a.get("tiers")), reasoning_effort.from_record(a.get("efforts")),
        )
        for a in agent_registry.all_agents()
        if not a.get("orchestrator") and a["id"] != me
    ]


async def roster_for() -> list[RosterEntry]:
    """This turn's roster: [] unless this agent is an orchestrator."""
    if not agent_spec.current().orchestrator:
        return []
    return await anyio.to_thread.run_sync(specialists)
```

`src/agents/agent_spec.py`:
- Line 8: change `orchestrator/routing` to `orchestrator`.
- Line 42: remove `, "routing"` from `_TOP_KEYS`.
- Delete line 45 (`_ROUTING_KEYS = ...`).
- Delete the `RoutingSpec` dataclass (the `@dataclass(frozen=True)` block at lines 94-99 and the blank line after it).
- Delete line 139 (`routing: RoutingSpec = field(default_factory=RoutingSpec)`).
- Delete lines 300-309 (the `if "routing" in data ...` check through the closing `)` of `routing = RoutingSpec(...)`).
- Delete line 325 (`routing=routing,`).

`src/agents/delegation.py`:
- Line 7: `specialists only (see agent_routing.specialists()).` stays as text, but remove `agent_routing` from the import on line 34: `from src.agents import agent_events, agent_registry, agent_spec`.
- Delete line 41 (`AUTO_AGENT_ID = "auto"`).
- Replace `tool_parameters` signature and first lines:

```python
def tool_parameters(roster: list[RosterEntry]) -> dict[str, Any]:
    """The delegate tool's input schema: agent_id limited to this turn's
    roster, and model_tier when at least one specialist offers a choice of
    model strength."""
    ids = [r.id for r in roster]
```

- In `tool_description`: signature becomes `def tool_description(roster: list[RosterEntry]) -> str:`; delete the `auto = ...` line; change the f-string to `...Specialists: {listing}.{choice}{effort} "`.
- In `call`: delete `prefix = ""` and the whole `if agent_id == AUTO_AGENT_ID:` block (4 lines); change the final line to `return note_prefix + result.get("response", "")`.

`src/llm/anthropic_provider.py`: delete the line `allow_auto = agent_spec.current().routing.allow_auto` (246); change the two calls to `delegation.tool_description(list(roster))` and `delegation.tool_parameters(list(roster))`; change line 280 to `roster = await agent_routing.roster_for()`. If `agent_spec` is then unused in the file, remove it from the import on line 45 (check with grep).

`src/llm/openai_provider.py`: same edits (lines 223, 228, 229, 290). Check `agent_spec` import (line 42) the same way.

`agents/ember.json`: remove the `"routing": {...}` object and the trailing comma after `"focus": "General questions; coordinates the specialist agents."` so the file ends:

```json
  "focus": "General questions; coordinates the specialist agents."
}
```

- [ ] **Step 6: Run the targeted tests, then check nothing else broke**

Run: `$PY -m pytest tests/test_agent_routing.py tests/test_agent_spec.py tests/test_delegation.py tests/test_effort.py tests/test_agent_registry.py tests/test_anthropic_provider.py tests/test_openai_provider.py -q`
Expected: PASS.

Run: `$PY -c "from pathlib import Path; from src.agents import agent_spec; print(len(agent_spec.load_dir(Path('agents'))))"`
Expected: prints the agent count (no `routing` rejection from `ember.json`).

Run (Grep tool or `grep -rn`): `RoutingSpec|AUTO_AGENT_ID|resolve_auto|allow_auto|\.routing` over `src tests scripts`.
Expected: no matches.

- [ ] **Step 7: Commit**

```bash
git add apps/ai_agent/src apps/ai_agent/tests apps/ai_agent/agents/ember.json
git commit -m "$(cat <<'EOF'
refactor(ai-agent): drop routing options and agent_id auto

Laya ranking is going away, so the orchestrator roster is every specialist.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Remove Laya tool shortlisting

**Files:**
- Delete: `apps/ai_agent/src/mcp_client/tool_selection.py`, `apps/ai_agent/tests/test_tool_selection.py`
- Modify: `apps/ai_agent/src/llm/anthropic_provider.py` (lines 50, 288), `apps/ai_agent/src/llm/openai_provider.py` (lines 46, 296)
- Modify: `apps/ai_agent/src/core/config_files.py` (lines 18, 49-65)
- Modify: `apps/ai_agent/configs/config_tuning.json.example`, `apps/ai_agent/configs/README.md`
- Modify: `apps/ai_agent/src/README.md` (lines 37-38, 57-58)
- Test: `apps/ai_agent/tests/test_config_tuning.py` (rewrite)

**Interfaces:**
- Consumes: Task 1 removed `agent_routing`'s import of `tool_selection`.
- Produces: `config_files.read_section(path, section, default)` unchanged; `seed_tuning` migrates only `config_limits.json`; `config_tuning.json.example` has only `token_limits`.

- [ ] **Step 1: Rewrite `tests/test_config_tuning.py`**

Replace the whole file with:

```python
"""First-read migration and shared consumers for ai_agent's tuning config."""

import json
from pathlib import Path

import pytest

from src.core import config_files
from src.llm import token_limits


@pytest.fixture
def tuning_path(tmp_path):
    path = tmp_path / "config_tuning.json"
    examples = Path(config_files.__file__).resolve().parents[2] / "configs"
    path.with_suffix(".json.example").write_bytes(
        (examples / "config_tuning.json.example").read_bytes()
    )
    return path


def test_fresh_install_seeds_token_limits(tuning_path):
    limits = config_files.read_section(tuning_path, "token_limits")
    assert limits["default"]["max_tool_rounds"] == 15
    assert json.loads(tuning_path.read_text(encoding="utf-8")).keys() == {"token_limits"}


def test_migration_preserves_legacy_limits_and_file(tuning_path):
    legacy = {"token_limits": {"default": {"max_output_tokens": 987, "max_context_tokens": 12345,
                                           "max_tool_rounds": 9},
                               "openai": {"gateways": {"ollama": {"max_context_tokens": 4321}}}}}
    old_path = tuning_path.parent / "config_limits.json"
    old_path.write_text(json.dumps(legacy), encoding="utf-8")
    original = old_path.read_bytes()

    config_files.read_section(tuning_path, "token_limits")
    merged = json.loads(tuning_path.read_text(encoding="utf-8"))
    defaults = json.loads(tuning_path.with_suffix(".json.example").read_text(encoding="utf-8"))
    assert merged == {**defaults, **legacy}
    assert old_path.read_bytes() == original
    assert not list(tuning_path.parent.glob("*.tmp"))


def test_existing_tuning_wins_and_is_not_rewritten(tuning_path):
    content = '{"token_limits": {"default": {}}}\n'
    tuning_path.write_text(content, encoding="utf-8")
    (tuning_path.parent / "config_limits.json").write_text("broken", encoding="utf-8")
    assert config_files.read_section(tuning_path, "token_limits") == {"default": {}}
    assert tuning_path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("bad", ['{broken', '[]', '{}'])
def test_invalid_legacy_limits_do_not_create_tuning(tuning_path, bad):
    (tuning_path.parent / "config_limits.json").write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError):
        config_files.read_section(tuning_path, "token_limits")
    assert not tuning_path.exists()


def test_token_limits_read_the_shared_tuning_file(tuning_path, monkeypatch):
    assert token_limits._CONFIG_PATH == config_files.TUNING_PATH
    data = {"token_limits": {"default": {"max_output_tokens": 101, "max_context_tokens": 202,
                                        "max_tool_rounds": 3}}}
    tuning_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(token_limits, "_CONFIG_PATH", tuning_path)
    token_limits.reset_cache()
    try:
        assert token_limits.max_output_tokens("anthropic") == 101
    finally:
        token_limits.reset_cache()
```

- [ ] **Step 2: Run to verify the new fresh-install test fails**

Run: `$PY -m pytest tests/test_config_tuning.py -q`
Expected: FAIL on `test_fresh_install_seeds_token_limits` (seeded file still has `tool_selection`).

- [ ] **Step 3: Implement**

Delete files:

```bash
git rm apps/ai_agent/src/mcp_client/tool_selection.py apps/ai_agent/tests/test_tool_selection.py
```

`src/llm/anthropic_provider.py`: delete line 50 (`from src.mcp_client import tool_selection`) and line 288 (`schemas = await tool_selection.shortlist_schemas(...)`).
`src/llm/openai_provider.py`: delete line 46 and line 296 the same way.

`src/core/config_files.py`:
- Line 18 comment: `# token_limits`.
- In `seed_tuning`, replace the `legacy_paths` / loop with:

```python
    legacy = path.parent / "config_limits.json"
    if not legacy.exists():
        seed_from_example(path)
        return
    example = path.with_name(path.name + ".example")
    raw = json.loads(example.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{example.name} must be an object")
    raw["token_limits"] = read_section(legacy, "token_limits")
```

(keep the existing `temporary = None` / `try:` block that writes and publishes the file unchanged). Update the docstring's first line to `Seed shared tuning, preserving a legacy config_limits.json and keeping it`.

`configs/config_tuning.json.example`: delete the `"tool_selection": {...}` block and the comma after the `token_limits` closing brace, so the file ends `  }\n}`.

`configs/README.md`: replace the `config_tuning.json` bullet (lines 9-12) with:

```markdown
- **`config_tuning.json`** - `token_limits`: output/context/tool-round
  caps, per provider and gateway (`src/llm/token_limits.py`).
```

and the migration paragraph (lines 37-43) with: `On the first read of config_tuning.json, an existing config_limits.json section takes precedence over example defaults. The old file is retained as a backup and is no longer read once the merged file exists.` followed by the existing sentences from "Edit `config_tuning.json`..." onward, replacing "files" with "file" in the rollback sentence.

`src/README.md`: replace lines 37-38 with:

```markdown
- `agent_routing.py` - per-turn roster of specialists for an orchestrator.
```

and delete the `tool_selection.py` mention on lines 57-58, leaving: `- `tool_progress.py` - per-tool progress reporting.`

- [ ] **Step 4: Run tests**

Run: `$PY -m pytest tests -q`
Expected: PASS (whole suite).

Run (Grep): `tool_selection|shortlist` over `src tests scripts configs README.md`.
Expected: no matches except historical mentions in `docs/`.

- [ ] **Step 5: Commit**

```bash
git add -A apps/ai_agent/src apps/ai_agent/tests apps/ai_agent/configs
git commit -m "$(cat <<'EOF'
refactor(ai-agent): remove Laya tool shortlisting

Tool schemas plus the question never fit Laya's 512-token window.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Generic Laya question provider

**Files:**
- Modify: `apps/ai_agent/src/llm/laya_provider.py` (full rewrite)
- Modify: `apps/ai_agent/src/server.py:436` (comment)
- Modify: `apps/ai_agent/agents/triage-assistant.json` (`focus`)
- Modify: `apps/ai_agent/scripts/check_laya_triage.py`, `apps/ai_agent/scripts/check_laya_agent.py`
- Modify: `apps/ai_agent/README.md`, `apps/ai_agent/src/llm/README.md`
- Modify: `docs/superpowers/specs/2026-10-09-laya-question-provider-design.md` (one clarification)
- Test: `apps/ai_agent/tests/test_laya_provider.py` (rewrite)

**Interfaces:**
- Produces: `laya_provider.parse_request(raw: str) -> Request` (frozen dataclass `text: str`, `questions: dict[str, dict]`, `min_confidence: float`); `LayaQuestions(engine=None)` with `prepare()` and `answer(raw: str) -> ChatResult`; module `_questions = LayaQuestions()`; `run_chat(...)` async and `prepare()`, `is_available()`, `has_api_key()`, `run_interpret()` as before. `ChatResult.response` is a JSON string `{"answers": {...}, "uncertain": bool}`.
- Consumes: Task 1/2 are independent of this task's code; only the test command is shared.

- [ ] **Step 1: Rewrite `tests/test_laya_provider.py`**

Replace the whole file with:

```python
"""The local Laya provider answers caller-supplied typed questions and never
generates text or calls another model."""

import asyncio
import copy
import json

import pytest

from src.llm import laya_provider
from src.llm.base_provider import ChatCancelled

REQUEST = {
    "text": "SQLite database is locked",
    "questions": {
        "category": {"type": "choice", "instructions": "Which category?",
                     "criteria": {"database": "SQL and storage", "network": "Connections"}},
        "severity": {"type": "score", "instructions": "How severe?", "criteria": ["none", "minor", "major"]},
        "problem": {"type": "noul", "instructions": "Is there a problem?"},
    },
}


def prediction(confidence=0.9):
    return {
        "answers": {
            "category": {"choice": "database", "probabilities": {"database": 0.9, "network": 0.1},
                         "answer_confidence": confidence},
            "severity": {"score": 1.4, "answer_confidence": confidence},
            "problem": {"noul": 0.95, "answer_confidence": confidence},
        },
        "usage": {"input_tokens": 120, "output_tokens": 0, "state_tokens": 12, "truncated": False},
    }


class FakeEngine:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else prediction()
        self.error = error
        self.calls = []

    def predict(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if self.error:
            raise self.error
        return copy.deepcopy(self.result)


@pytest.fixture
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(laya_provider, "_questions", laya_provider.LayaQuestions(fake))
    return fake


def ask(request=REQUEST, **kwargs):
    question = request if isinstance(request, str) else json.dumps(request)
    return asyncio.run(laya_provider.run_chat(question, [], None, [], **kwargs))


def payload(result):
    return json.loads(result.response)


def request_with(**changes):
    data = copy.deepcopy(REQUEST)
    data.update(changes)
    return data


def question(**changes):
    return {"type": "choice", "instructions": "Pick", "criteria": {"a": "A", "b": "B"}, **changes}


def test_answers_every_question_type_and_reports_token_usage(engine):
    result = ask()
    assert payload(result) == {
        "answers": {
            "category": {"type": "choice", "choice": "database",
                         "probabilities": {"database": 0.9, "network": 0.1},
                         "answer_confidence": 0.9, "uncertain": False},
            "severity": {"type": "score", "score": 1.4,
                         "legend": {"0": "none", "1": "minor", "2": "major"},
                         "answer_confidence": 0.9, "uncertain": False},
            "problem": {"type": "noul", "noul": 0.95, "answer_confidence": 0.9, "uncertain": False},
        },
        "uncertain": False,
    }
    assert result.provider_id == "laya"
    assert result.model == "convaiinnovations/laya"
    assert result.input_tokens == result.total_tokens == 120
    assert result.output_tokens == 0
    assert result.tools_used == result.tool_calls == []


def test_engine_gets_the_text_and_only_the_known_question_fields(engine):
    ask()
    state, questions, kwargs = engine.calls[0]
    assert state == "SQLite database is locked"
    assert questions == REQUEST["questions"]
    assert "criteria" not in questions["problem"]
    assert kwargs["max_len"] == 512


def test_low_confidence_marks_that_answer_and_the_whole_result_uncertain(engine):
    engine.result = prediction(confidence=0.4)
    data = payload(ask())
    assert data["uncertain"] is True
    assert all(answer["uncertain"] for answer in data["answers"].values())
    assert data["answers"]["category"]["choice"] == "database"


def test_min_confidence_can_be_set_per_request(engine):
    assert payload(ask(request_with(min_confidence=0.95)))["uncertain"] is True
    engine.result = prediction(confidence=0.6)
    assert payload(ask(request_with(min_confidence=0.5)))["uncertain"] is False


def test_text_after_the_json_object_is_ignored(engine):
    # delegation appends attachment references to the question string.
    ask(json.dumps(REQUEST) + "\n\nUploaded PDF file references (original attachment order):\nscan.pdf: [PDFMerger file_id: f1]")
    assert engine.calls[0][0] == "SQLite database is locked"


BAD_REQUESTS = [
    "not json",
    "[]",
    {"text": "x"},
    request_with(extra=1),
    request_with(text=""),
    request_with(text="   "),
    request_with(text="x" * 4001),
    request_with(min_confidence=0),
    request_with(min_confidence=1.5),
    request_with(min_confidence=True),
    request_with(questions={}),
    request_with(questions={f"q{i}": question() for i in range(9)}),
    request_with(questions={"q": "oops"}),
    request_with(questions={"q": question(type="multi")}),
    request_with(questions={"q": question(instructions="")}),
    request_with(questions={"q": question(extra=1)}),
    request_with(questions={"q": question(criteria={"a": "only one"})}),
    request_with(questions={"q": question(criteria={f"o{i}": "d" for i in range(11)})}),
    request_with(questions={"q": question(criteria=["a", "b"])}),
    request_with(questions={"q": question(criteria={"a": 1, "b": "B"})}),
    request_with(questions={"q": question(type="score", criteria={"a": "A", "b": "B"})}),
    request_with(questions={"q": question(type="score", criteria=["only"])}),
    request_with(questions={"q": question(type="noul", criteria={"yes": "y", "no": "n"})}),
]


@pytest.mark.parametrize("request_data", BAD_REQUESTS)
def test_invalid_requests_are_rejected_before_inference(engine, request_data):
    with pytest.raises(ValueError, match="Invalid Laya request"):
        ask(request_data)
    assert not engine.calls


def test_truncated_input_returns_no_answers(engine):
    engine.result["usage"]["truncated"] = True
    with pytest.raises(ValueError, match="complete input"):
        ask()


def test_dropped_state_tokens_return_no_answers(engine):
    engine.result["usage"]["state_tokens_dropped"] = 3
    with pytest.raises(ValueError, match="complete input"):
        ask()


@pytest.mark.parametrize("qid,field,value", [
    ("category", "choice", "invented"),
    ("category", "probabilities", {"database": 0.9}),
    ("category", "answer_confidence", float("nan")),
    ("severity", "score", 5),
    ("severity", "score", float("nan")),
    ("problem", "noul", 2),
    ("problem", "answer_confidence", True),
])
def test_malformed_model_results_are_rejected(engine, qid, field, value):
    engine.result["answers"][qid][field] = value
    with pytest.raises(ValueError, match="Laya returned"):
        ask()


def test_a_missing_answer_is_rejected(engine):
    del engine.result["answers"]["problem"]
    with pytest.raises(ValueError, match="Laya returned"):
        ask()


def test_inference_errors_propagate_without_a_fallback(engine):
    engine.error = RuntimeError("local model failed")
    with pytest.raises(RuntimeError, match="local model failed"):
        ask()
    assert len(engine.calls) == 1


def test_cancellation_is_checked_before_and_after_inference(engine, monkeypatch):
    monkeypatch.setattr(laya_provider.cancellation, "is_cancelled", lambda _: True)
    with pytest.raises(ChatCancelled):
        ask(request_id="cancelled")
    assert not engine.calls

    checks = iter([False, True])
    monkeypatch.setattr(laya_provider.cancellation, "is_cancelled", lambda _: next(checks))
    with pytest.raises(ChatCancelled):
        ask(request_id="during-inference")
    assert len(engine.calls) == 1


def test_history_and_extensions_do_not_change_the_input(engine):
    result = asyncio.run(laya_provider.run_chat(
        json.dumps(REQUEST), [{"role": "user", "content": "old issue"}], None,
        ["external-server"], caveman=True,
    ))
    assert engine.calls[0][0] == "SQLite database is locked"
    assert result.tools_used == []


def test_interpret_does_not_claim_to_summarize_or_generate_text(engine):
    with pytest.raises(ValueError, match="does not support"):
        laya_provider.run_interpret("Summarize this conversation")
    assert not engine.calls


def test_other_model_ids_cannot_be_used(engine):
    with pytest.raises(ValueError, match="only supports"):
        asyncio.run(laya_provider.run_chat(json.dumps(REQUEST), [], "gpt-x", []))
    assert not engine.calls
```

- [ ] **Step 2: Run to verify it fails**

Run: `$PY -m pytest tests/test_laya_provider.py -q`
Expected: FAIL (`module 'src.llm.laya_provider' has no attribute 'LayaQuestions'`).

- [ ] **Step 3: Rewrite `src/llm/laya_provider.py`**

Replace the whole file with:

```python
"""Local typed-question provider: answers caller-supplied choice, score and
noul questions about a short text. No generated text, tool calls or LLM fallback."""

from __future__ import annotations

import importlib.util
import json
import math
import threading
from dataclasses import dataclass
from typing import Any

import anyio.to_thread

from src.core.catalog import catalog
from src.llm import cancellation
from src.llm.base_provider import ChatCancelled, ChatResult, step_event

PROVIDER_ID = "laya"
DEFAULT_MODEL = "convaiinnovations/laya"
VENDOR_LABEL = "Laya (local)"
SUPPORTS_STREAMING = True
CONTEXT_WINDOW = 512
MAX_INPUT_CHARS = 4000
# An initial review gate, not a measured accuracy guarantee. Validate against
# representative local examples before using these answers for actions.
MIN_CONFIDENCE = 0.7
MAX_QUESTIONS = 8
MIN_OPTIONS = 2
MAX_OPTIONS = 10

_REQUEST_KEYS = {"text", "questions", "min_confidence"}
_QUESTION_KEYS = {"type", "instructions", "criteria"}
_QUESTION_TYPES = ("choice", "score", "noul")
_NOUL_KEYS = {"false", "true"}


@dataclass(frozen=True)
class Request:
    text: str
    questions: dict[str, dict[str, Any]]
    min_confidence: float


def _fail(message: str) -> ValueError:
    return ValueError(f"Invalid Laya request: {message}")


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _question(qid: str, spec: Any) -> dict[str, Any]:
    if not _is_text(qid):
        raise _fail("question ids must be non-empty strings")
    if not isinstance(spec, dict):
        raise _fail(f"question {qid!r} must be an object")
    unknown = set(spec) - _QUESTION_KEYS
    if unknown:
        raise _fail(f"question {qid!r} has unknown field(s): {', '.join(sorted(unknown))}")
    qtype = spec.get("type")
    if qtype not in _QUESTION_TYPES:
        raise _fail(f"question {qid!r} type must be choice, score or noul")
    if not _is_text(spec.get("instructions")):
        raise _fail(f"question {qid!r} needs non-empty instructions")
    criteria = spec.get("criteria")
    if qtype == "choice":
        valid = (isinstance(criteria, dict) and MIN_OPTIONS <= len(criteria) <= MAX_OPTIONS
                 and all(_is_text(k) and _is_text(v) for k, v in criteria.items()))
        rule = f"an object of {MIN_OPTIONS} to {MAX_OPTIONS} option: description strings"
    elif qtype == "score":
        valid = (isinstance(criteria, list) and MIN_OPTIONS <= len(criteria) <= MAX_OPTIONS
                 and all(_is_text(v) for v in criteria))
        rule = f"a list of {MIN_OPTIONS} to {MAX_OPTIONS} level description strings, lowest first"
    else:
        valid = criteria is None or (isinstance(criteria, dict) and set(criteria) == _NOUL_KEYS
                                     and all(_is_text(v) for v in criteria.values()))
        rule = 'omitted, or an object with exactly the keys "false" and "true"'
    if not valid:
        raise _fail(f"question {qid!r} ({qtype}) criteria must be {rule}")
    out: dict[str, Any] = {"type": qtype, "instructions": spec["instructions"]}
    if criteria is not None:
        out["criteria"] = criteria
    return out


def parse_request(raw: str) -> Request:
    """Validate the JSON question. Text after the first JSON object is ignored:
    delegation appends attachment references to the question string."""
    try:
        data, _ = json.JSONDecoder().raw_decode(raw.lstrip())
    except ValueError as error:
        raise _fail('the question must be JSON: {"text": "...", "questions": {...}}') from error
    if not isinstance(data, dict):
        raise _fail("the question must be a JSON object")
    unknown = set(data) - _REQUEST_KEYS
    if unknown:
        raise _fail(f"unknown field(s): {', '.join(sorted(unknown))}")
    text = data.get("text")
    if not _is_text(text):
        raise _fail("text must be a non-empty string")
    if len(text) > MAX_INPUT_CHARS:
        raise _fail(f"text must be at most {MAX_INPUT_CHARS} characters; send a shorter excerpt")
    min_confidence = data.get("min_confidence", MIN_CONFIDENCE)
    if not _is_number(min_confidence) or not 0 < min_confidence <= 1:
        raise _fail("min_confidence must be a number above 0 and at most 1")
    questions = data.get("questions")
    if not isinstance(questions, dict) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise _fail(f"questions must be an object with 1 to {MAX_QUESTIONS} entries")
    return Request(text, {qid: _question(qid, spec) for qid, spec in questions.items()}, float(min_confidence))


def _unit(value: Any) -> float:
    if not _is_number(value) or not 0 <= value <= 1:
        raise ValueError("invalid probability")
    return float(value)


def _answer(spec: dict[str, Any], raw: dict[str, Any], min_confidence: float) -> dict[str, Any]:
    """One validated answer in the response shape; raises on anything the
    request did not allow or that is not a finite in-range number."""
    confidence = _unit(raw["answer_confidence"])
    qtype = spec["type"]
    out: dict[str, Any] = {"type": qtype}
    if qtype == "choice":
        choice = raw["choice"]
        probabilities = raw["probabilities"]
        if choice not in spec["criteria"] or set(probabilities) != set(spec["criteria"]):
            raise ValueError("unknown choice")
        out["choice"] = choice
        out["probabilities"] = {key: _unit(value) for key, value in probabilities.items()}
    elif qtype == "score":
        score = raw["score"]
        if not _is_number(score) or not 0 <= score <= len(spec["criteria"]) - 1:
            raise ValueError("invalid score")
        out["score"] = round(float(score), 4)
        out["legend"] = {str(i): level for i, level in enumerate(spec["criteria"])}
    else:
        out["noul"] = _unit(raw["noul"])
    out["answer_confidence"] = confidence
    out["uncertain"] = confidence < min_confidence
    return out


@catalog
class LayaQuestions:
    """Load one English Laya checkpoint and answer typed questions about a text.

    Lazy load + lock; an engine can be injected for offline contract tests.
    """

    def __init__(self, engine: Any = None) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    def _load(self) -> Any:
        # Called only while holding _lock, including during inference.
        if self._engine is None:
            try:
                import laya
            except ImportError as error:
                raise RuntimeError('Laya requires the optional dependency: pip install -e ".[laya]"') from error
            self._engine = laya.load(DEFAULT_MODEL)
        return self._engine

    def prepare(self) -> None:
        """Warm the model before registering this agent as running."""
        with self._lock:
            self._load()

    def answer(self, raw: str) -> ChatResult:
        request = parse_request(raw)
        with self._lock:
            prediction = self._load().predict(request.text, request.questions, max_len=CONTEXT_WINDOW)
        usage = prediction.get("usage", {})
        if usage.get("truncated") or usage.get("state_tokens_dropped", 0):
            raise ValueError(
                "Laya could not read the complete input. Send a shorter text or fewer, shorter questions; "
                "no answers were returned."
            )
        try:
            answers = {
                qid: _answer(spec, prediction["answers"][qid], request.min_confidence)
                for qid, spec in request.questions.items()
            }
            input_tokens = usage["input_tokens"]
            if isinstance(input_tokens, bool) or not isinstance(input_tokens, int) or input_tokens < 0:
                raise ValueError("invalid token usage")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError("Laya returned an invalid result; no answers were returned.") from error
        result = {"answers": answers, "uncertain": any(a["uncertain"] for a in answers.values())}
        return ChatResult(
            response=json.dumps(result), provider_id=PROVIDER_ID, model=DEFAULT_MODEL,
            input_tokens=input_tokens, output_tokens=0, total_tokens=input_tokens,
            # State length alone excludes the question heads; don't invent a
            # context-window reading or count the JSON as generated tokens.
            context_tokens=None,
        )


_questions = LayaQuestions()


def has_api_key() -> bool:
    """Compatibility with agent_config: this local provider needs no API key."""
    return True


def is_available() -> bool:
    return importlib.util.find_spec("laya") is not None


def prepare() -> None:
    _questions.prepare()


async def run_chat(
    question: str, history: list[dict[str, Any]], model: str | None,
    enabled_extensions: list[str], request_id: str | None = None, depth: int = 0,
    on_event: Any = None, caveman: bool = False,
) -> ChatResult:
    if model and model != DEFAULT_MODEL:
        raise ValueError(f"Laya only supports {DEFAULT_MODEL}.")
    if cancellation.is_cancelled(request_id):
        raise ChatCancelled()
    result = await anyio.to_thread.run_sync(_questions.answer, question)
    if cancellation.is_cancelled(request_id):
        raise ChatCancelled()
    if on_event is not None:
        await on_event(step_event("token", text=result.response))
    return result


def run_interpret(text: str, model: str | None = None) -> ChatResult:
    raise ValueError("Laya does not support summarization or free-form text generation. Use ask with a JSON question request.")
```

- [ ] **Step 4: Run the provider tests**

Run: `$PY -m pytest tests/test_laya_provider.py tests/test_server.py tests/test_agent_config.py -q`
Expected: PASS. (If a `BAD_REQUESTS` case reaches the engine, tighten the matching rule in `_question`/`parse_request`; do not loosen the test.)

- [ ] **Step 5: Update the agent file, scripts, comment and docs**

`agents/triage-assistant.json` — replace the `focus` value with:

```json
  "focus": "Answers typed questions about a short text (at most 4000 characters) with a local model. Send the question as JSON: {\"text\": \"...\", \"questions\": {\"id\": {\"type\": \"choice|score|noul\", \"instructions\": \"...\", \"criteria\": ...}}}. choice criteria = {option: description}; score criteria = ordered list of level descriptions, lowest first; noul (yes/no) criteria optional {\"false\": \"...\", \"true\": \"...\"}. Returns JSON with an answer, answer_confidence and an uncertain flag per question; treat uncertain answers as provisional. Does not generate text, fetch data or call tools.",
```

`src/server.py` line 436: change the comment to `        # laya answers typed questions locally and never lists tools through mcp_upstream.`

`scripts/check_laya_triage.py` — replace the whole file with:

```python
"""Small real-model smoke evaluation, not an accuracy or calibration benchmark.

Run from ai_agent: python -m scripts.check_laya_triage
Loads only local Laya; never calls a cloud LLM or changes agent configuration.
Sends the triage example schema below through the same provider path agents use.
"""

import json

from src.llm.laya_provider import LayaQuestions

TRIAGE_QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "Which category best describes this technical issue?",
        "criteria": {
            "database": "Database queries, storage, SQL, locking or data integrity errors.",
            "network": "Connections, DNS, timeouts, sockets or unreachable services.",
            "authentication": "Login, identity, credentials, authorization or access denied.",
            "configuration": "Missing or incorrect settings, environment variables or setup.",
            "unknown": "No technical issue, insufficient evidence, or none of these categories fits.",
        },
    },
    "severity": {
        "type": "score",
        "instructions": "How severe is the issue described? Do not assume unstated impact.",
        "criteria": ["informational", "warning", "critical"],
    },
    "needs_investigation": {
        "type": "noul",
        "instructions": "Does this text describe a technical problem that needs investigation?",
        "criteria": {"false": "Normal operation; no technical problem.", "true": "A failure or problem needs investigation."},
    },
}

CASES = [
    ("SQLite database is locked; the SQL write failed.", "database"),
    ("PostgreSQL rejected the SQL query due to a syntax error.", "database"),
    ("Connection refused when opening a socket to the service.", "network"),
    ("DNS lookup failed; the hostname could not be resolved.", "network"),
    ("Login failed: invalid username or password.", "authentication"),
    ("Access denied: the account lacks permission to view this page.", "authentication"),
    ("Application startup failed: required configuration setting is missing.", "configuration"),
    ("The server port configuration has an invalid value.", "configuration"),
    ("The scheduled backup completed successfully. Everything is operating normally.", "unknown"),
    ("Hello, good morning!", "unknown"),
]


def main() -> None:
    laya = LayaQuestions()
    correct = 0
    uncertain = 0
    for text, expected in CASES:
        result = laya.answer(json.dumps({"text": text, "questions": TRIAGE_QUESTIONS}))
        data = json.loads(result.response)
        category = data["answers"]["category"]["choice"]
        correct += category == expected
        uncertain += data["uncertain"]
        print(json.dumps({"input": text, "expected": expected, "category": category,
                          "uncertain": data["uncertain"], "answers": data["answers"]}, ensure_ascii=True), flush=True)
    print(json.dumps({"category_matches": correct, "examples": len(CASES),
                      "uncertain": uncertain, "note": "Smoke examples only; thresholds are not calibrated."}), flush=True)


if __name__ == "__main__":
    main()
```

`scripts/check_laya_agent.py`: add `from scripts.check_laya_triage import TRIAGE_QUESTIONS` below the `from mcp.client.stdio ...` import; change the `ask` call to `{"question": json.dumps({"text": "SQLite database is locked; the SQL write failed.", "questions": TRIAGE_QUESTIONS})}`; replace the assertion `assert "Category: Database" in data["response"]` with:

```python
                answers = json.loads(data["response"])["answers"]
                assert answers["category"]["choice"] == "database", answers
```

`README.md` (apps/ai_agent) — edit by heading text:
- Field table row `llm.provider`: change `(local triage only)` to `(local typed questions only)`.
- Row `focus`: remove ` and for Laya routing`.
- Delete the four `routing.*` rows, the sentence "The `routing.*` fields are only allowed...", and the "An orchestrator file adds the routing block:" paragraph with its JSON example (keep an orchestrator example without `routing`: `{ "port": 9100, "entry": true, "llm": { "provider": "anthropic" }, "orchestrator": true }`).
- Replace the whole section `## Laya-only Triage Assistant` (through the paragraph ending "...are rejected at startup.") with:

````markdown
## Laya question agent

`agents/triage-assistant.json` defines a local specialist backed by Laya, a
small model that answers typed questions about a short text. It is part of the
tracked roster. Install the optional dependency with `pip install -e ".[laya]"`,
or set `enabled: false` if this installation should not run it. Restart the
supervisor after changing the roster. Its provider is `laya`, gateway `local`,
model `convaiinnovations/laya`; no cloud model or API key is used.

Laya never generates text. The caller supplies the questions as the `ask`
question, a JSON string:

```json
{
  "text": "SQLite database is locked",
  "min_confidence": 0.7,
  "questions": {
    "category": {"type": "choice", "instructions": "Which category?",
                 "criteria": {"database": "SQL and storage", "network": "Connections"}},
    "severity": {"type": "score", "instructions": "How severe?",
                 "criteria": ["none", "minor", "major"]},
    "problem":  {"type": "noul", "instructions": "Is there a problem?"}
  }
}
```

- `choice`: `criteria` is `{option: description}`, 2 to 10 options.
- `score`: `criteria` is a list of 2 to 10 level descriptions, lowest first.
  The answer is the expected level (0 to n-1) with a `legend`.
- `noul` (yes/no): `criteria` is optional `{"false": "...", "true": "..."}`.
  The answer is P(true).
- `text` is at most 4,000 characters; 1 to 8 questions; `min_confidence` is
  optional (default 0.70, `MIN_CONFIDENCE` in `src/llm/laya_provider.py`).
  Text after the JSON object is ignored.

The response is JSON: `{"answers": {id: {...}}, "uncertain": bool}`. Each
answer has `type`, the result (`choice`/`score`/`noul`), `answer_confidence`
and `uncertain` (confidence below `min_confidence`). A request with an unknown
field, type, or out-of-range size is rejected before inference with an
"Invalid Laya request" error.

The English checkpoint has a 512-token limit including the question heads, so
keep texts and criteria short. Input Laya reports as truncated is rejected
instead of answering from partial evidence. The model loads before the agent
registers as running; the first load may download weights. Loading/inference
errors propagate without an LLM fallback. History is deliberately excluded and
`interpret`/summarization is unsupported. Cancellation is checked before and
after inference.

Escalating to a real LLM is the orchestrator's decision: when `uncertain` is
true it can answer itself or delegate to another specialist. `0.70` is an
experimental review gate, **not a calibrated accuracy claim**. Run
`python -m scripts.check_laya_triage` for ten real-model smoke examples using
a triage question set, then evaluate representative local inputs before
relying on the answers.

Usage reports the model's actual input-token work and zero generated output
tokens. Laya is restricted to a specialist with the pinned checkpoint and
local gateway; generation settings, an entry role, or an orchestrator role are
rejected at startup.
````

- Replace the heading `## Orchestrator and routing` with `## Orchestrator`, delete the "Routing options" bullet list and the "If Laya is not installed or fails..." paragraph with its `pip install` code block, keeping the first paragraph and the "Specialist activity streams..." paragraph.

`src/llm/README.md` lines 19-22 — replace with:

```markdown
- **`laya_provider.py`** - local typed-question answerer: the caller sends JSON
  `choice`, `score` and `noul` questions about a short text and gets JSON
  answers with confidences. No tools, text generation, cloud fallback or
  API key. Inference runs in a worker thread; weights load before registration.
  Imports only when `laya` is the selected provider.
```

Spec clarification in `docs/superpowers/specs/2026-10-09-laya-question-provider-design.md`, under "Request > Validation", add the bullet: `- Text after the first JSON object is ignored, because delegation appends attachment references to the question string.`

- [ ] **Step 6: Verify the real agent file loads and the whole suite passes**

Run: `$PY -c "from pathlib import Path; from src.agents import agent_spec; print([s.id for s in agent_spec.load_dir(Path('agents'))])"`
Expected: a list including `triage-assistant` (no validation error on the longer `focus`).

Run: `$PY -m pytest tests -q`
Expected: PASS.

Run (Grep): `Category:|LayaTriage|_triage\b|classify\(` over `src tests scripts README.md`.
Expected: no matches.

- [ ] **Step 7: Real-model smoke (manual, needs the `laya` extra and a one-time weight download)**

Run: `$PY -m scripts.check_laya_triage`
Expected: ten JSON lines plus a summary line, each answer carrying `answer_confidence` and `uncertain`. Report the `category_matches` count to the user as a smoke result, not an accuracy claim. If the extra is not installed, say so and skip.

- [ ] **Step 8: Commit**

```bash
git add apps/ai_agent docs/superpowers/specs/2026-10-09-laya-question-provider-design.md
git commit -m "$(cat <<'EOF'
feat(ai-agent): make Laya a generic typed-question provider

Callers send choice, score and noul questions as JSON and get JSON answers
with confidences and uncertain flags. Escalation stays with the orchestrator.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Wrap up

**Files:**
- Modify: `C:\Users\User\.claude\projects\D--User-Documents-Programming-Python-MCPServer\memory\project-laya-tool-shortlist.md` (replace) and `MEMORY.md` (index line)
- Modify (only if asked): `Brain/Projects/MCPServer.md` and `Brain/Projects/ai_agent.md` notes

- [ ] **Step 1: Final full-suite run and leftover grep**

Run: `$PY -m pytest tests -q` from `apps/ai_agent`. Expected: PASS.
Grep `tool_selection|shortlist|allow_auto|routing\.` over `apps/ai_agent` (excluding `docs/` and `.venv_ai_agent`). Expected: no matches.

- [ ] **Step 2: Refresh memory**

The old memory ("Laya tool shortlist ... untested") is now false. Replace it with a short note: Laya is only the question provider (`choice`/`score`/`noul`, JSON in/out, 512-token window), tool shortlisting and routing were removed on 2026-10-09, escalation is the orchestrator's job. Update the `MEMORY.md` index line to match (rename the file to `project-laya-question-provider.md`, delete the old one).

- [ ] **Step 3: Offer the vault sync**

Tell the user the vault project note may mention Laya routing and shortlisting, and offer to run the `project-sync` skill. Do not edit `Brain/` unasked.
