# Emberlings Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `apps/mini_games`, a standalone backend that hosts Emberlings: players collect and battle Sparks with a persistent collection, a battle engine whose autonomous Sparks pick actions through an engine-side policy that uses Laya only to read the situation, and an HTTP API for `ember_api` to proxy later.

**Architecture:** An object-oriented, async service. A pure `BattleEngine` and a pure `ActionPolicy` hold the rules and the personality maths; services (`CollectionService`, `EncounterService`, `ShopService`, `ProgressionService`) and a `RoundCoordinator` sit on a `SparkRepository` interface backed by SQLite (one transaction at a time, blocking calls in a worker thread). Laya answers three typed situation questions; an engine heuristic replaces any read it cannot give. Every mutation is idempotent and every round is a revision-checked checkpoint, so a restart or a retry never rerolls an outcome.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, SQLite (standard library), python-dotenv, pytest, httpx (test client), optional `laya` extra.

**Spec:** `docs/superpowers/specs/2026-10-10-emberlings-backend-design.md`, with the decision record `docs/superpowers/specs/2026-10-09-emberlings-decisions.md`.

## Global Constraints

- Project folder `apps/mini_games/`, shaped per `.agents/skills/root-project-scaffold/SKILL.md`: `README.md`, `pyproject.toml`, `run.bat`, `configs/`, `secrets/`, `src/`, `tests/`, plus `data/` (runtime SQLite, gitignored) and `docs/` (the Laya evaluation). No other top-level folders.
- Own venv `.venv_mini_games` (ignored by the root `.venv_*/` rule). Never import another project; the Laya client is its own copy of ai_agent's contract. No LLM is ever called, so nothing is billed.
- Port 8060. Header names `X-Internal-Token`, `X-Requester-Username`, `Idempotency-Key`. `secrets/.env` holds `INTERNAL_API_TOKEN`; once set, every route except `/health` rejects a missing or wrong token. Ownership comes only from the requester header, never from a body.
- Real `configs/config_app.json` and `secrets/.env` are gitignored and seeded from their `.example` twins. `configs/spark_catalog.json` is tracked (versioned game data, not a secret) and `data/` is gitignored.
- Code is object-oriented: one class per responsibility, interfaces as `typing.Protocol`, constructor injection, composition over inheritance, frozen dataclasses for values, a single composition root (`build_spark_services`). Everything that waits (SQLite, Laya, deadlines) is `async`; blocking calls run in worker threads (`asyncio.to_thread`); the engine and policy stay synchronous and pure.
- Laya (optional): 512-token context window, text at most 4000 characters, at most 8 questions per call, `choice` needs 2 to 10 options, default `min_confidence` 0.7, inference deadline 2 seconds. A Laya read that is uncertain, invalid, late or missing is replaced by its engine heuristic, one question at a time. The default `situation_source` is `heuristic`.
- EMBLEM prompt: five seconds, enforced by the server; a late answer is refused. After the deadline Laya picks within the autonomous tier limit; a failed, invalid, uncertain or impossible choice replaces CATCH with basic ATTACK before reveal and spends nothing.
- Encounter rolls: one per 30 seconds from the previous generation. Faint: 300 seconds, any tier, no copy loss. One active battle per player.
- Statuses: 400 bad input (including unknown fields in a body, unknown species or tier); 401 bad token; 404 missing or foreign record; 409 state conflict (stale round or revision, wrong phase, not enough Insignia or EMBLEMs, cooldown, active battle, reused idempotency key). Timestamps are UTC epoch seconds.
- All commands run from the repo root `D:/User/Documents/Programming/Python/MCPServer` in Git Bash; the project venv Python is `apps/mini_games/.venv_mini_games/Scripts/python`. Every code file below was written and run against its tests before this plan was finalised: building the files in task order passes the suite after every task (474 tests at the end). Copy them exactly; if a test fails, fix the cause and do not loosen the test.

## Relationship to the chess and Tetris plan

`docs/superpowers/plans/2026-10-09-mini-games-backend.md` was written first and is not built yet. Emberlings goes first, so this plan supersedes parts of it. When that plan is executed later, make these edits first:

1. Skip its Task 1 (scaffold and config), Task 2 (auth) and Task 6 (Laya client): this plan's Tasks 1, 2 and 3 replace them. Its `.gitignore` block is replaced by the one in Task 1 below.
2. Extend `src/config.py` and `configs/config_app.json.example` with its keys (`session_ttl_seconds`, `max_sessions_per_user`, `default_picker`, `difficulties`) and add `python-chess` to `pyproject.toml`.
3. Its `src/opponent/laya_client.py` becomes this plan's `src/laya_client.py`. The API differs: the minimum confidence is set on the client (`LayaClient(engine, timeout, min_confidence)`), and `choose(text, instructions, options)` returns a `LayaAnswer` whose `.value` is the chosen key and which has `.uncertain`. Adapt its `LayaPicker`; its `FakeEngine` is replaced by `tests/fake_laya.py` below (same `pick`, `confidence`, `delay`, `usage` arguments, plus `scores`, `noul`, `raw`, `fail`).
4. Its `create_app(store, games, token)` becomes `src.app.create_app(token)` plus a router mounted like `mount_sparks`; use `src.auth.requester` for the owner.
5. Its `tests/conftest.py` `config` fixture is replaced by this plan's.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml`, `run.bat`, `README.md` | Project metadata, launcher, docs |
| `configs/config_app.json.example`, `secrets/.env.example` | Committed twins of the real, gitignored files |
| `configs/spark_catalog.json` | Tracked game data: tiers, species, abilities, personalities, economy, policy numbers |
| `src/seed.py`, `src/config.py`, `src/auth.py` | Seed a missing file from its `.example`; typed config; token middleware and requester dependency |
| `src/laya_client.py` | Local Laya wrapper: `choice`, `score` and `noul` questions |
| `src/app.py` | The FastAPI shell any game mounts into |
| `src/sparks/models.py` | Frozen value objects with JSON round trips |
| `src/sparks/catalog.py` | `Catalog`: loads and validates the game data; stat, tier and price lookups |
| `src/sparks/runtime.py` | `Clock` and `RandomSource` protocols, seeded and recording random sources |
| `src/sparks/passives.py` | One small class per species passive, built by `PassiveFactory` |
| `src/sparks/engine.py` | `BattleEngine`: legal actions and round resolution (pure) |
| `src/sparks/policy.py` | `ActionPolicy` and `Mood`: personality, situation and repeat penalty into action probabilities (pure) |
| `src/sparks/situation.py` | `SituationView`, heuristic and Laya situation readers, fallback composition |
| `src/sparks/errors.py`, `records.py`, `repository.py` | Error types with HTTP statuses; row values; the SQLite repository |
| `src/sparks/idempotency.py` | `IdempotentWriter`: exactly-once mutations |
| `src/sparks/progression.py` | XP, copies, tiers, rewards, fainting; applies a finished battle atomically |
| `src/sparks/collection.py`, `encounters.py`, `shop.py` | Profile, personalities and presets; encounter rolls; shop |
| `src/sparks/decider.py`, `battle_view.py`, `emblem_picker.py` | One Spark's decision; the public battle JSON; EMBLEM choice |
| `src/sparks/coordinator.py` | `RoundCoordinator`: the battle lifecycle |
| `src/sparks/api.py`, `composition.py`, `src/run.py` | HTTP routes; the composition root; the process entry point |
| `src/sparks/simulation.py`, `src/sparks/eval/situation_eval.py` | AI-versus-AI battles; the manual Laya evaluation |
| `tests/` | One test file per module, plus `fake_laya.py`, `sparks/helpers.py`, `sparks/env.py` |

---

### Task 1: Scaffold, configuration and the gitignore

**Files:**
- Create: `apps/mini_games/pyproject.toml`, `configs/config_app.json.example`, `secrets/.env.example`, `src/__init__.py`, `src/seed.py`, `src/config.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py` (all under `apps/mini_games/`)
- Modify: `.gitignore` (repo root)

**Interfaces:**
- Produces: `src.config.AppConfig` (frozen: `host, port, database_path, catalog_path, situation_source, laya_timeout_seconds, laya_min_confidence, emblem_prompt_seconds, encounter_cooldown_seconds, faint_seconds`), `ConfigError`, `parse_config(raw, root=PROJECT_ROOT)`, `load_config(path=None)`; `src.seed.seed_from_example(path)`; fixture `config` in `tests/conftest.py`.

- [ ] **Step 1: Create the folders and the empty package files**

```bash
mkdir -p apps/mini_games/{src,tests,configs,secrets}
touch apps/mini_games/src/__init__.py apps/mini_games/tests/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`, the two `.example` files and the gitignore block**

`apps/mini_games/pyproject.toml`

```toml
[project]
name = "mini-games"
description = "Game backend for Ember: Emberlings (Spark collecting and battling) with a Laya-assisted action policy; chess and Tetris plug in later"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]
laya = ["laya"]

[project.scripts]
mini-games = "src.run:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`apps/mini_games/configs/config_app.json.example`

```json
{
  "host": "127.0.0.1",
  "port": 8060,
  "database_path": "data/sparks.sqlite3",
  "catalog_path": "configs/spark_catalog.json",
  "situation_source": "heuristic",
  "laya_timeout_seconds": 2.0,
  "laya_min_confidence": 0.7,
  "emblem_prompt_seconds": 5.0,
  "encounter_cooldown_seconds": 30.0,
  "faint_seconds": 300.0
}
```

`apps/mini_games/secrets/.env.example`

```text
# mini_games' one credentials file. Copy to .env (the loader also creates it
# from this file on first run). .env itself is gitignored.
#
# Set the same value as mcp_server's, ai_agent's and ember_api's
# INTERNAL_API_TOKEN. Generate one with:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
#
# When set, every route except /health rejects requests without it
# (X-Internal-Token). Leave blank only while every caller stays on this machine.
INTERNAL_API_TOKEN=
```

Append to the repo-root `.gitignore`:

```gitignore
# mini_games: real config, secrets and game data stay local; the .example twins and the game catalog are tracked.
/apps/mini_games/configs/*
!/apps/mini_games/configs/*.example
!/apps/mini_games/configs/spark_catalog.json
/apps/mini_games/secrets/*
!/apps/mini_games/secrets/*.example
/apps/mini_games/data/
```

- [ ] **Step 3: Create the venv and install**

```bash
cd apps/mini_games && py -m venv .venv_mini_games && .venv_mini_games/Scripts/python -m pip install -e ".[dev]" && cd ../..
```

Expected: install succeeds (fastapi, uvicorn, python-dotenv, pytest, httpx).

- [ ] **Step 4: Write the failing tests**

`apps/mini_games/tests/conftest.py`

```python
"""Shared fixtures. Tests never read the real configs/ or secrets/ files."""

from pathlib import Path

import pytest

from src.config import AppConfig, load_config

EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "config_app.json.example"


@pytest.fixture
def config() -> AppConfig:
    return load_config(EXAMPLE_CONFIG)
```

`apps/mini_games/tests/test_config.py`

```python
import json

import pytest

from src.config import ConfigError, load_config, parse_config
from tests.conftest import EXAMPLE_CONFIG


def test_example_config_loads(config):
    assert config.port == 8060
    assert config.situation_source == "heuristic"
    assert config.emblem_prompt_seconds == 5.0
    assert config.database_path.name == "sparks.sqlite3"


@pytest.fixture
def raw():
    return json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))


def test_unknown_situation_source_is_rejected(raw):
    raw["situation_source"] = "magic"
    with pytest.raises(ConfigError, match="situation_source"):
        parse_config(raw)


def test_bool_is_not_a_number(raw):
    raw["port"] = True
    with pytest.raises(ConfigError, match="port"):
        parse_config(raw)


def test_confidence_above_one_is_rejected(raw):
    raw["laya_min_confidence"] = 1.5
    with pytest.raises(ConfigError, match="at most"):
        parse_config(raw)


def test_missing_field_is_rejected(raw):
    del raw["host"]
    with pytest.raises(ConfigError, match="host"):
        parse_config(raw)


def test_unreadable_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.json")
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_config.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.config'`.

- [ ] **Step 6: Write the implementation**

`apps/mini_games/src/seed.py`

```python
"""Auto-create a missing config/secret file from its `.example` sibling."""

import shutil
from pathlib import Path


def seed_from_example(path: Path) -> None:
    if path.exists():
        return
    example = path.with_name(path.name + ".example")
    if example.exists():
        shutil.copyfile(example, path)
```

`apps/mini_games/src/config.py`

```python
"""Typed loader for configs/config_app.json (seeded from its .example)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.seed import seed_from_example

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "config_app.json"
SITUATION_SOURCES = ("heuristic", "laya")


class ConfigError(ValueError):
    """config_app.json is missing a field or holds a bad value."""


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    database_path: Path
    catalog_path: Path
    situation_source: str
    laya_timeout_seconds: float
    laya_min_confidence: float
    emblem_prompt_seconds: float
    encounter_cooldown_seconds: float
    faint_seconds: float


def _number(raw: dict[str, Any], key: str, kind: type, minimum: float, maximum: float | None = None) -> Any:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ConfigError(f"{key} must be a number of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{key} must be at most {maximum}")
    return kind(value)


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string")
    return value


def _path(raw: dict[str, Any], key: str, root: Path) -> Path:
    path = Path(_text(raw, key))
    return path if path.is_absolute() else root / path


def parse_config(raw: Any, root: Path = PROJECT_ROOT) -> AppConfig:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    source = _text(raw, "situation_source")
    if source not in SITUATION_SOURCES:
        raise ConfigError(f"situation_source must be one of {', '.join(SITUATION_SOURCES)}")
    return AppConfig(
        host=_text(raw, "host"),
        port=_number(raw, "port", int, 1, 65535),
        database_path=_path(raw, "database_path", root),
        catalog_path=_path(raw, "catalog_path", root),
        situation_source=source,
        laya_timeout_seconds=_number(raw, "laya_timeout_seconds", float, 0.1),
        laya_min_confidence=_number(raw, "laya_min_confidence", float, 0.01, 1.0),
        emblem_prompt_seconds=_number(raw, "emblem_prompt_seconds", float, 0.1),
        encounter_cooldown_seconds=_number(raw, "encounter_cooldown_seconds", float, 0.0),
        faint_seconds=_number(raw, "faint_seconds", float, 0.0),
    )


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate the config. With no path, use configs/config_app.json
    and create it from the .example on first run."""
    if path is None:
        path = CONFIG_PATH
        seed_from_example(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    return parse_config(raw)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_config.py -q`
Expected: 6 passed.

- [ ] **Step 8: Commit**

```bash
git add .gitignore apps/mini_games
git status --short   # only the files above: no .venv_mini_games, no real config or .env
git commit -m "feat(mini_games): project scaffold and config loader"
```

---

### Task 2: Internal token and requester

**Files:**
- Create: `apps/mini_games/src/auth.py`
- Test: `apps/mini_games/tests/test_auth.py`

**Interfaces:**
- Consumes: `src.seed.seed_from_example`.
- Produces: `load_token(path=None) -> str`; `InternalTokenMiddleware(app, token)` (ASGI; everything except `/health` needs `X-Internal-Token` once a token is set); `requester` (FastAPI dependency returning the stripped `X-Requester-Username`, 400 when missing); `INTERNAL_TOKEN_HEADER`, `REQUESTER_USERNAME_HEADER`, `OPEN_PATHS`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_auth.py`

```python
import asyncio

import pytest
from fastapi import HTTPException

from src.auth import InternalTokenMiddleware, load_token, requester


async def _call(token: str, path: str, headers: dict[str, str]) -> int:
    seen = {}

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        if message["type"] == "http.response.start":
            seen["status"] = message["status"]

    scope = {"type": "http", "path": path, "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    await InternalTokenMiddleware(app, token)(scope, None, send)
    return seen["status"]


def test_wrong_token_is_rejected():
    assert asyncio.run(_call("secret", "/sparks/profile", {"X-Internal-Token": "nope"})) == 401


def test_missing_token_is_rejected():
    assert asyncio.run(_call("secret", "/sparks/profile", {})) == 401


def test_right_token_passes():
    assert asyncio.run(_call("secret", "/sparks/profile", {"X-Internal-Token": "secret"})) == 200


def test_health_is_open():
    assert asyncio.run(_call("secret", "/health", {})) == 200


def test_no_token_configured_passes_everything():
    assert asyncio.run(_call("", "/sparks/profile", {})) == 200


def test_load_token_reads_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("INTERNAL_API_TOKEN=abc\n", encoding="utf-8")
    assert load_token(env) == "abc"


def test_environment_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "from-env")
    env = tmp_path / ".env"
    env.write_text("INTERNAL_API_TOKEN=abc\n", encoding="utf-8")
    assert load_token(env) == "from-env"


def test_requester_strips_and_requires_a_name():
    assert requester("  ann ") == "ann"
    with pytest.raises(HTTPException) as error:
        requester("  ")
    assert error.value.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_auth.py -q`
Expected: `ModuleNotFoundError: No module named 'src.auth'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/auth.py`

```python
"""The shared internal token (checked on every route but /health) and the
asking user's name, which owns every game record."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from dotenv import dotenv_values
from fastapi import Header, HTTPException

from src.seed import seed_from_example

SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets" / ".env"
INTERNAL_TOKEN_HEADER = "X-Internal-Token"
REQUESTER_USERNAME_HEADER = "X-Requester-Username"
OPEN_PATHS = ("/health",)


def load_token(path: Path | None = None) -> str:
    """INTERNAL_API_TOKEN from the environment, else from secrets/.env
    (seeded from its .example on first run). "" = not configured."""
    if path is None:
        path = SECRETS_PATH
        seed_from_example(path)
    return os.getenv("INTERNAL_API_TOKEN") or dotenv_values(path).get("INTERNAL_API_TOKEN") or ""


def requester(x_requester_username: str = Header(default="")) -> str:
    """FastAPI dependency: the trusted owner name from the requester header.
    Ownership never comes from a request body."""
    owner = x_requester_username.strip()
    if not owner:
        raise HTTPException(400, f"{REQUESTER_USERNAME_HEADER} header is required")
    return owner


class InternalTokenMiddleware:
    """Plain ASGI middleware: a request whose X-Internal-Token does not match
    (constant-time) gets 401 JSON. Does nothing when no token is configured."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    def _protects(self, scope) -> bool:
        return bool(self._token) and scope["type"] == "http" and scope.get("path", "") not in OPEN_PATHS

    async def __call__(self, scope, receive, send):
        if self._protects(scope):
            provided = dict(scope.get("headers") or []).get(INTERNAL_TOKEN_HEADER.lower().encode("latin-1"), b"")
            if not hmac.compare_digest(self._token, provided):
                body = json.dumps({"error": "Invalid or missing internal API token"}).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_auth.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/auth.py apps/mini_games/tests/test_auth.py
git commit -m "feat(mini_games): internal token middleware and requester dependency"
```

---

### Task 3: Laya client

**Files:**
- Create: `apps/mini_games/src/laya_client.py`, `apps/mini_games/tests/fake_laya.py`
- Test: `apps/mini_games/tests/test_laya_client.py`

**Interfaces:**
- Produces (`src.laya_client`): `LayaClient(engine=None, timeout=2.0, min_confidence=0.7)` with `is_available()`, `prepare()`, `async ask(text, questions) -> dict[str, LayaAnswer]`, `async choose(text, instructions, options) -> LayaAnswer`; `LayaAnswer(kind, value, confidence, uncertain)` where `value` is the option key (choice), a float score from 0 to levels - 1 (score) or the yes probability (noul); question builders `choice_question(instructions, options)`, `score_question(instructions, levels)` (lowest first), `noul_question(instructions, false_text, true_text)`; `LayaError`, `LayaUnavailable`.
- Engine contract (copied from `ai_agent/src/llm/laya_provider.py`): `predict(text, questions, max_len=512)` returns `{"answers": {qid: {...}}, "usage": {...}}`; `usage.truncated` or `usage.state_tokens_dropped` means the input was cut. Any exception from the model becomes a `LayaError`.
- Produces (`tests/fake_laya.py`): `FakeEngine(pick, confidence, delay, usage, scores, noul, raw, fail)` with `.calls`.

- [ ] **Step 1: Write the fake engine and the failing tests**

`apps/mini_games/tests/fake_laya.py`

```python
"""A stand-in for the real Laya engine: tests inject it into LayaClient."""

from __future__ import annotations

import time
from typing import Any


class FakeEngine:
    """Answers every question. Defaults: choice -> first option, score -> 1.0,
    noul -> 0.8. `raw` maps a question id to a full raw answer to return as is
    (for invalid-output tests); `scores` and `noul` map ids to values."""

    def __init__(
        self,
        pick: str | None = None,
        confidence: float = 0.9,
        delay: float = 0.0,
        usage: dict | None = None,
        scores: dict[str, float] | None = None,
        noul: dict[str, float] | None = None,
        raw: dict[str, dict] | None = None,
        fail: bool = False,
    ) -> None:
        self.pick, self.confidence, self.delay = pick, confidence, delay
        self.usage = usage if usage is not None else {"input_tokens": 10}
        self.scores, self.noul, self.raw, self.fail = scores or {}, noul or {}, raw or {}, fail
        self.calls: list[tuple[str, dict]] = []

    def predict(self, text: str, questions: dict[str, Any], max_len: int = 512) -> dict[str, Any]:
        self.calls.append((text, questions))
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("engine failure")
        answers = {}
        for qid, spec in questions.items():
            if qid in self.raw:
                answers[qid] = self.raw[qid]
                continue
            if spec["type"] == "choice":
                keys = list(spec["criteria"])
                choice = self.pick if self.pick in keys else keys[0]
                spread = (1 - self.confidence) / (len(keys) - 1)
                probabilities = {key: (self.confidence if key == choice else spread) for key in keys}
                answers[qid] = {"choice": choice, "probabilities": probabilities, "answer_confidence": self.confidence}
            elif spec["type"] == "score":
                answers[qid] = {"score": self.scores.get(qid, 1.0), "answer_confidence": self.confidence}
            else:
                answers[qid] = {"noul": self.noul.get(qid, 0.8), "answer_confidence": self.confidence}
        return {"answers": answers, "usage": self.usage}
```

`apps/mini_games/tests/test_laya_client.py`

```python
import asyncio

import pytest

from src.laya_client import LayaClient, LayaError, choice_question, noul_question, score_question
from tests.fake_laya import FakeEngine

OPTIONS = {"a": "first", "b": "second", "c": "third"}
LEVELS = ["low", "mid", "high"]
QUESTIONS = {
    "level": score_question("How high?", LEVELS),
    "yes": noul_question("Is it so?", "No.", "Yes."),
    "pick": choice_question("Which?", OPTIONS),
}


def ask(client, text="A short text.", questions=None):
    return asyncio.run(client.ask(text, QUESTIONS if questions is None else questions))


def test_all_three_question_types_are_answered():
    answers = ask(LayaClient(FakeEngine(pick="b", scores={"level": 1.7}, noul={"yes": 0.25})))
    assert answers["level"].value == 1.7 and answers["level"].kind == "score"
    assert answers["yes"].value == 0.25 and answers["yes"].kind == "noul"
    assert answers["pick"].value == "b" and answers["pick"].confidence == 0.9
    assert not any(a.uncertain for a in answers.values())


def test_low_confidence_is_flagged_uncertain_per_answer():
    answers = ask(LayaClient(FakeEngine(confidence=0.5)))
    assert all(a.uncertain for a in answers.values())


def test_min_confidence_comes_from_the_client():
    assert ask(LayaClient(FakeEngine(confidence=0.8), min_confidence=0.9))["pick"].uncertain is True


def test_choose_returns_the_chosen_key():
    answer = asyncio.run(LayaClient(FakeEngine(pick="c")).choose("Text.", "Which?", OPTIONS))
    assert (answer.value, answer.uncertain) == ("c", False)


def test_questions_are_sent_to_the_engine_unchanged():
    engine = FakeEngine()
    ask(LayaClient(engine))
    text, sent = engine.calls[0]
    assert text == "A short text." and sent == QUESTIONS


@pytest.mark.parametrize("questions", [
    {},
    {f"q{i}": noul_question("Q?", "n", "y") for i in range(9)},
    {"x": {"type": "weird", "instructions": "?", "criteria": {}}},
    {"x": choice_question("Which?", {"only": "one"})},
    {"x": score_question("How?", ["just one"])},
    {"x": {"type": "noul", "instructions": "?", "criteria": {"yes": "a", "no": "b"}}},
    {"": noul_question("Q?", "n", "y")},
])
def test_invalid_questions_are_rejected_before_the_model(questions):
    engine = FakeEngine()
    with pytest.raises(LayaError):
        ask(LayaClient(engine), questions=questions)
    assert engine.calls == []


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_text_length_is_checked(text):
    with pytest.raises(LayaError, match="characters"):
        ask(LayaClient(FakeEngine()), text=text)


def test_truncated_input_is_rejected():
    with pytest.raises(LayaError, match="complete input"):
        ask(LayaClient(FakeEngine(usage={"truncated": True})))


@pytest.mark.parametrize("raw", [
    {"level": {"score": 9, "answer_confidence": 0.9}},
    {"level": {"score": float("nan"), "answer_confidence": 0.9}},
    {"level": {"score": 1, "answer_confidence": 2}},
    {"yes": {"noul": 1.5, "answer_confidence": 0.9}},
    {"pick": {"choice": "z", "probabilities": {"a": 1, "b": 0, "c": 0}, "answer_confidence": 0.9}},
    {"pick": {"choice": "a", "probabilities": {"a": 1}, "answer_confidence": 0.9}},
    {"pick": {"choice": "a"}},
])
def test_invalid_engine_output_is_rejected(raw):
    with pytest.raises(LayaError, match="invalid result"):
        ask(LayaClient(FakeEngine(raw=raw)))


def test_engine_exceptions_become_laya_errors():
    with pytest.raises(LayaError, match="Laya failed: engine failure"):
        ask(LayaClient(FakeEngine(fail=True)))


def test_timeout_raises_laya_error():
    with pytest.raises(LayaError, match="timed out"):
        ask(LayaClient(FakeEngine(delay=0.5), timeout=0.05))


def test_missing_package_is_unavailable_and_raises():
    client = LayaClient()
    if client.is_available():
        pytest.skip("laya is installed here")
    with pytest.raises(LayaError, match="optional dependency"):
        ask(client)


def test_injected_engine_counts_as_available():
    assert LayaClient(FakeEngine()).is_available() is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_laya_client.py -q`
Expected: `ModuleNotFoundError: No module named 'src.laya_client'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/laya_client.py`

```python
"""Local Laya wrapper: typed questions about a short text.

A copy of the contract in ai_agent's laya_provider.py (projects never import
each other): `choice`, `score` and `noul` questions, validated answers, a
`uncertain` flag per answer. Lazy model load under a lock, inference in a
worker thread, and a timeout so a slow model never stalls a game turn. Laya
reads text only; it generates no text and is never trusted without its own
confidence flag.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
import threading
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "convaiinnovations/laya"
CONTEXT_WINDOW = 512
MAX_TEXT_CHARS = 4000
MAX_QUESTIONS = 8
MIN_OPTIONS, MAX_OPTIONS = 2, 10
_TYPES = ("choice", "score", "noul")
_NOUL_KEYS = {"false", "true"}


class LayaError(RuntimeError):
    """Laya failed, timed out, or returned something unusable."""


class LayaUnavailable(LayaError):
    """The optional `laya` package is not installed."""


@dataclass(frozen=True)
class LayaAnswer:
    """One validated answer. `value` is the chosen option key (choice), the
    score from 0 to len(levels) - 1 (score) or the yes probability (noul)."""

    kind: str
    value: Any
    confidence: float
    uncertain: bool


def choice_question(instructions: str, options: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def score_question(instructions: str, levels: list[str]) -> dict[str, Any]:
    """`levels` are descriptions, lowest first."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def noul_question(instructions: str, false_text: str, true_text: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": instructions, "criteria": {"false": false_text, "true": true_text}}


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unit(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid probability")
    return float(value)


def _check_question(qid: str, spec: Any) -> None:
    if not _is_text(qid) or not isinstance(spec, dict):
        raise LayaError("every question needs a non-empty id and an object")
    kind, criteria = spec.get("type"), spec.get("criteria")
    if kind not in _TYPES or not _is_text(spec.get("instructions")):
        raise LayaError(f"question {qid!r} needs a valid type and instructions")
    if kind == "choice":
        valid = (isinstance(criteria, dict) and MIN_OPTIONS <= len(criteria) <= MAX_OPTIONS
                 and all(_is_text(k) and _is_text(v) for k, v in criteria.items()))
    elif kind == "score":
        valid = (isinstance(criteria, list) and MIN_OPTIONS <= len(criteria) <= MAX_OPTIONS
                 and all(_is_text(v) for v in criteria))
    else:
        valid = isinstance(criteria, dict) and set(criteria) == _NOUL_KEYS and all(_is_text(v) for v in criteria.values())
    if not valid:
        raise LayaError(f"question {qid!r} ({kind}) has invalid criteria")


def _answer(spec: dict[str, Any], raw: dict[str, Any], min_confidence: float) -> LayaAnswer:
    confidence = _unit(raw["answer_confidence"])
    kind = spec["type"]
    if kind == "choice":
        key, probabilities = raw["choice"], raw["probabilities"]
        if key not in spec["criteria"] or set(probabilities) != set(spec["criteria"]):
            raise ValueError("unknown choice")
        for probability in probabilities.values():
            _unit(probability)
        value: Any = key
    elif kind == "score":
        score = raw["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) \
                or not 0 <= score <= len(spec["criteria"]) - 1:
            raise ValueError("invalid score")
        value = float(score)
    else:
        value = _unit(raw["noul"])
    return LayaAnswer(kind, value, confidence, confidence < min_confidence)


class LayaClient:
    """Engine injection (`engine=`) lets tests run without the real model."""

    def __init__(self, engine: Any = None, timeout: float = 2.0, min_confidence: float = 0.7) -> None:
        self._engine = engine
        self._timeout = timeout
        self._min_confidence = min_confidence
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return self._engine is not None or importlib.util.find_spec("laya") is not None

    def _load(self) -> Any:
        # Called only while holding _lock, including during inference.
        if self._engine is None:
            try:
                import laya
            except ImportError as error:
                raise LayaUnavailable('Laya needs the optional dependency: pip install -e ".[laya]"') from error
            self._engine = laya.load(DEFAULT_MODEL)
        return self._engine

    def prepare(self) -> None:
        """Warm the model so the first game turn is not slow."""
        with self._lock:
            self._load()

    def _ask_sync(self, text: str, questions: dict[str, dict[str, Any]]) -> dict[str, LayaAnswer]:
        if not 1 <= len(questions) <= MAX_QUESTIONS:
            raise LayaError(f"ask 1 to {MAX_QUESTIONS} questions at once")
        for qid, spec in questions.items():
            _check_question(qid, spec)
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise LayaError(f"text must be 1 to {MAX_TEXT_CHARS} characters")
        try:
            with self._lock:
                prediction = self._load().predict(text, questions, max_len=CONTEXT_WINDOW)
        except LayaError:
            raise
        except Exception as error:  # the model library's own failures, whatever their type
            raise LayaError(f"Laya failed: {error}") from error
        try:
            usage = prediction.get("usage", {})
            if usage.get("truncated") or usage.get("state_tokens_dropped", 0):
                raise LayaError("Laya could not read the complete input")
            return {qid: _answer(spec, prediction["answers"][qid], self._min_confidence) for qid, spec in questions.items()}
        except LayaError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise LayaError("Laya returned an invalid result") from error

    async def ask(self, text: str, questions: dict[str, dict[str, Any]]) -> dict[str, LayaAnswer]:
        """All answers or a LayaError. Individual answers may be `uncertain`."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._ask_sync, text, questions), self._timeout)
        except asyncio.TimeoutError as error:
            raise LayaError(f"Laya timed out after {self._timeout}s") from error

    async def choose(self, text: str, instructions: str, options: dict[str, str]) -> LayaAnswer:
        """One `choice` question; the answer's value is the chosen option key."""
        answers = await self.ask(text, {"choice": choice_question(instructions, options)})
        return answers["choice"]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_laya_client.py -q`
Expected: 27 passed (one test skips itself if the real `laya` package is installed).

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/laya_client.py apps/mini_games/tests/fake_laya.py apps/mini_games/tests/test_laya_client.py
git commit -m "feat(mini_games): local Laya client for typed questions"
```

---

### Task 4: Value objects and the catalog

**Files:**
- Create: `apps/mini_games/src/sparks/__init__.py` (empty), `src/sparks/models.py`, `configs/spark_catalog.json`, `src/sparks/catalog.py`, `tests/sparks/__init__.py` (empty)
- Test: `apps/mini_games/tests/sparks/test_catalog.py`

**Interfaces:**
- Produces (`src.sparks.models`): constants `PLAYER`, `WILD`, `SIDES`, `CATEGORIES` (`ATTACK, DEFENSE, SUPPORT, FEAR, INTERCEPT`), `other(side)`; frozen dataclasses `AbilitySpec`, `PassiveSpec(kind, params)`, `Action(kind, category, ability_id, percentage, emblem_tier)` with `.key`, `Buff`, `DefenseEffect`, `Fighter`, `FighterState`, `RevealedRound`, `BattleState` (with `.of(side)`), `BattleSetup` (with `.of(side)`), `PersonalityInstance(id, type_id, tier)`, `RoundOutcome`; each saved type has `to_dict` / `from_dict`.
- Produces (`src.sparks.catalog`): `Catalog(raw)` / `Catalog.load(path)` with `.tiers`, `.regular_tiers`, `.forbidden_tier`, `.levels`, `.economy`, `.personalities`, `.policy`, `tier(id)`, `species(id)`, `has_species(id)`, `all_species()`, `regular_species()`, `starter_species()`, `forbidden_species()`, `level_cap(species_id)`, `stat_value(species_id, level, tier_id, stat)`, `tier_for_copies(species_id, copies)`, `sale_value(species_id, tier_id, level)`; `CatalogError`; `TierSpec`, `SpeciesSpec`, `PolicySpec`, `Economy`, `Levels`.
- Rules in the catalog: stats are `(base + growth × (level − 1)) × tier multiplier` floored to a positive integer; a regular Spark's tier is the highest whose copy threshold its copies meet; Forbidden is always Forbidden. Ability names and the species role names are working names.

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p apps/mini_games/src/sparks apps/mini_games/tests/sparks
touch apps/mini_games/src/sparks/__init__.py apps/mini_games/tests/sparks/__init__.py
```

`apps/mini_games/tests/sparks/test_catalog.py`

```python
import copy
import json
from pathlib import Path

import pytest

from src.sparks.catalog import Catalog, CatalogError

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json"


@pytest.fixture(scope="module")
def raw():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load(CATALOG_PATH)


def test_shipped_catalog_is_valid(catalog):
    assert catalog.version == 1
    assert [t.id for t in catalog.tiers] == ["normal", "rare", "legendary", "royalty", "ascended", "forbidden"]
    assert len(catalog.all_species()) == 7
    assert [s.id for s in catalog.starter_species()] == ["guardian", "striker", "scout"]
    assert catalog.forbidden_species().id == "forbidden"
    assert len(catalog.regular_species()) == 6


def test_stats_use_growth_then_tier_multiplier_and_floor(catalog):
    assert catalog.stat_value("guardian", 1, "normal", "hp") == 150
    assert catalog.stat_value("guardian", 11, "normal", "hp") == 300  # 150 + 15 * 10
    assert catalog.stat_value("scout", 3, "rare", "essence") == 33  # (22 + 2.2 * 2) * 1.25 = 33.0
    assert catalog.stat_value("forbidden", 1, "forbidden", "hp") == 800
    assert catalog.stat_value("forbidden", 1, "forbidden", "speed") == 120
    assert catalog.stat_value("scout", 2, "normal", "speed") == 38  # 35 + 3.5 = 38.5 floored


def test_every_species_grows_ten_percent_of_base(catalog):
    for species in catalog.all_species():
        for stat in ("hp", "essence", "speed"):
            assert species.growth[stat] == pytest.approx(species.base[stat] * 0.1)


@pytest.mark.parametrize("copies,tier", [(0, "normal"), (9, "normal"), (10, "rare"), (39, "rare"), (40, "legendary"), (100, "royalty"), (250, "ascended"), (9999, "ascended")])
def test_regular_tier_follows_copies(catalog, copies, tier):
    assert catalog.tier_for_copies("sentinel", copies) == tier


def test_forbidden_is_always_forbidden(catalog):
    assert catalog.tier_for_copies("forbidden", 0) == "forbidden"
    assert catalog.tier_for_copies("forbidden", 100) == "forbidden"


def test_level_caps(catalog):
    assert catalog.level_cap("guardian") == 30 and catalog.level_cap("forbidden") == 50


def test_sale_value_formula(catalog):
    assert catalog.sale_value("guardian", "normal", 1) == 100
    assert catalog.sale_value("guardian", "rare", 11) == 187  # 100 * 1.25 * 1.5 = 187.5
    assert catalog.sale_value("forbidden", "forbidden", 1) == 4000


def _broken(raw, mutate):
    data = copy.deepcopy(raw)
    mutate(data)
    return data


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["tiers"][0].update(encounter_probability=0.5), "sum to 1"),
    (lambda d: d["tiers"][1].update(id="normal"), "unique"),
    (lambda d: d["tiers"][2].update(copy_threshold=5), "strictly increase"),
    (lambda d: d["species"][0].update(starter=False), "three species must be starters"),
    (lambda d: d["species"][3]["abilities"].pop(), "unlock at levels"),
    (lambda d: d["species"][0]["abilities"][1].pop("duration"), "SUPPORT needs"),
    (lambda d: d["species"][0]["abilities"][0].update(category="HEAL"), "category must be"),
    (lambda d: d["personalities"][0].update(categories=["NOPE"]), "invalid categories"),
    (lambda d: d["policy"]["coefficients"].pop("FEAR"), "coefficients missing"),
    (lambda d: d["species"][0]["base"].pop("hp"), "exactly hp, essence and speed"),
])
def test_inconsistent_catalogs_are_rejected(raw, mutate, message):
    with pytest.raises(CatalogError, match=message):
        Catalog(_broken(raw, mutate))


def test_unreadable_file_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError, match="cannot load"):
        Catalog.load(tmp_path / "missing.json")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_catalog.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.catalog'`.

- [ ] **Step 3: Write the value objects, the catalog data and the loader**

`apps/mini_games/src/sparks/models.py`

```python
"""Immutable value objects shared by the battle engine, policy and services.

Everything that is saved with a battle has to_dict/from_dict so a battle can be
rebuilt exactly after a restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PLAYER, WILD = "player", "wild"
SIDES = (PLAYER, WILD)
CATEGORIES = ("ATTACK", "DEFENSE", "SUPPORT", "FEAR", "INTERCEPT")
ABILITY_CATEGORIES = ("ATTACK", "DEFENSE", "SUPPORT")


def other(side: str) -> str:
    return WILD if side == PLAYER else PLAYER


@dataclass(frozen=True)
class AbilitySpec:
    id: str
    name: str
    unlock_level: int
    category: str  # ATTACK, DEFENSE or SUPPORT
    percentage: float  # of ESSENCE
    cooldown: int
    stat: str | None = None  # SUPPORT only: "essence" or "speed"
    duration: int | None = None  # SUPPORT only: rounds, counting the activation round

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AbilitySpec":
        return cls(**raw)


@dataclass(frozen=True)
class PassiveSpec:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PassiveSpec":
        return cls(raw["kind"], dict(raw.get("params", {})))


@dataclass(frozen=True)
class Action:
    """A choice for one round. `kind` is attack (basic), ability, flee or catch."""

    kind: str
    category: str
    ability_id: str | None = None
    percentage: float = 100.0
    emblem_tier: str | None = None  # CATCH by the collecting side only

    @property
    def key(self) -> str:
        return f"ability:{self.ability_id}" if self.kind == "ability" else self.kind

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "category": self.category, "ability_id": self.ability_id,
                "percentage": self.percentage, "emblem_tier": self.emblem_tier}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Action":
        return cls(raw["kind"], raw["category"], raw.get("ability_id"), raw.get("percentage", 100.0), raw.get("emblem_tier"))


@dataclass(frozen=True)
class Buff:
    source: str  # ability id, or "passive:<kind>"
    stat: str  # "essence" or "speed"
    amount: int
    rounds_left: int | None  # None = lasts the whole battle

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Buff":
        return cls(**raw)


@dataclass(frozen=True)
class DefenseEffect:
    rating: float
    attacks_left: int
    rounds_left: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DefenseEffect":
        return cls(**raw)


@dataclass(frozen=True)
class Fighter:
    """A battle participant's stats and abilities, frozen when the battle starts
    so later balance changes never alter a fight in progress."""

    side: str
    species_id: str
    tier_id: str
    level: int
    max_hp: int
    essence: int  # unbuffed
    speed: int  # unbuffed
    abilities: tuple[AbilitySpec, ...]
    passive: PassiveSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side, "species_id": self.species_id, "tier_id": self.tier_id, "level": self.level,
            "max_hp": self.max_hp, "essence": self.essence, "speed": self.speed,
            "abilities": [a.to_dict() for a in self.abilities], "passive": self.passive.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Fighter":
        return cls(
            raw["side"], raw["species_id"], raw["tier_id"], raw["level"], raw["max_hp"], raw["essence"], raw["speed"],
            tuple(AbilitySpec.from_dict(a) for a in raw["abilities"]), PassiveSpec.from_dict(raw["passive"]),
        )


@dataclass(frozen=True)
class FighterState:
    hp: int
    buffs: tuple[Buff, ...] = ()
    defense: DefenseEffect | None = None
    cooldowns: tuple[tuple[str, int], ...] = ()  # (ability id, first round it is available again)

    def to_dict(self) -> dict[str, Any]:
        return {"hp": self.hp, "buffs": [b.to_dict() for b in self.buffs],
                "defense": self.defense.to_dict() if self.defense else None,
                "cooldowns": [[a, r] for a, r in self.cooldowns]}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FighterState":
        return cls(raw["hp"], tuple(Buff.from_dict(b) for b in raw["buffs"]),
                   DefenseEffect.from_dict(raw["defense"]) if raw["defense"] else None,
                   tuple((a, r) for a, r in raw["cooldowns"]))


@dataclass(frozen=True)
class RevealedRound:
    """What both sides chose in a finished round: public after the reveal."""

    round: int
    actions: dict[str, tuple[str, str]]  # side -> (action key, category)
    events: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "actions": {s: list(a) for s, a in self.actions.items()}, "events": list(self.events)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RevealedRound":
        return cls(raw["round"], {s: (a[0], a[1]) for s, a in raw["actions"].items()}, tuple(raw["events"]))


@dataclass(frozen=True)
class BattleState:
    round: int
    player: FighterState
    wild: FighterState
    history: tuple[RevealedRound, ...] = ()

    def of(self, side: str) -> FighterState:
        return self.player if side == PLAYER else self.wild

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "player": self.player.to_dict(), "wild": self.wild.to_dict(),
                "history": [h.to_dict() for h in self.history]}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BattleState":
        return cls(raw["round"], FighterState.from_dict(raw["player"]), FighterState.from_dict(raw["wild"]),
                   tuple(RevealedRound.from_dict(h) for h in raw["history"]))


@dataclass(frozen=True)
class BattleSetup:
    """The two frozen fighters of one battle."""

    player: Fighter
    wild: Fighter

    def of(self, side: str) -> Fighter:
        return self.player if side == PLAYER else self.wild

    def to_dict(self) -> dict[str, Any]:
        return {"player": self.player.to_dict(), "wild": self.wild.to_dict()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BattleSetup":
        return cls(Fighter.from_dict(raw["player"]), Fighter.from_dict(raw["wild"]))


@dataclass(frozen=True)
class PersonalityInstance:
    """One collected personality: a type (AGGRESSIVE ...) at tier 1 to 3."""

    id: str
    type_id: str
    tier: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PersonalityInstance":
        return cls(raw["id"], raw["type_id"], raw["tier"])


@dataclass(frozen=True)
class RoundOutcome:
    state: BattleState
    events: tuple[dict[str, Any], ...]
    terminal: str | None  # won, knocked_out, captured, escaped, wild_escaped
    emblem_consumed: str | None
    draws: tuple[float, ...]


TERMINAL_KINDS = ("won", "knocked_out", "captured", "escaped", "wild_escaped", "forfeited")
```

`apps/mini_games/configs/spark_catalog.json`

```json
{
  "version": 1,
  "tiers": [
    {"id": "normal", "stat_multiplier": 1.0, "capture_multiplier": 1, "hp_floor": 0.10, "emblem_strength": 100, "emblem_price": 20, "encounter_probability": 0.60, "copy_threshold": 0, "copy_reward": 1},
    {"id": "rare", "stat_multiplier": 1.25, "capture_multiplier": 2, "hp_floor": 0.20, "emblem_strength": 200, "emblem_price": 40, "encounter_probability": 0.25, "copy_threshold": 10, "copy_reward": 2},
    {"id": "legendary", "stat_multiplier": 1.5, "capture_multiplier": 4, "hp_floor": 0.35, "emblem_strength": 400, "emblem_price": 80, "encounter_probability": 0.10, "copy_threshold": 40, "copy_reward": 3},
    {"id": "royalty", "stat_multiplier": 2.0, "capture_multiplier": 8, "hp_floor": 0.50, "emblem_strength": 800, "emblem_price": 160, "encounter_probability": 0.04, "copy_threshold": 100, "copy_reward": 4},
    {"id": "ascended", "stat_multiplier": 2.5, "capture_multiplier": 16, "hp_floor": 0.65, "emblem_strength": 1600, "emblem_price": 320, "encounter_probability": 0.009, "copy_threshold": 250, "copy_reward": 5},
    {"id": "forbidden", "stat_multiplier": 4.0, "capture_multiplier": 128, "hp_floor": 0.80, "emblem_strength": 3200, "emblem_price": 640, "encounter_probability": 0.001, "copy_threshold": null, "copy_reward": 1}
  ],
  "levels": {"regular_cap": 30, "forbidden_cap": 50, "xp_per_level": 100},
  "economy": {
    "xp_reward_factor": 20,
    "insignia_reward_factor": 10,
    "sale_level_bonus": 0.05,
    "purchase_factor": 2,
    "forbidden_copy_cap": 100,
    "base_capture_resistance": 100,
    "starter_emblems": {"normal": 5},
    "starter_personality_tier": 1,
    "encounter_level_window": 2,
    "personality_tier_probabilities": [0.6, 0.3, 0.1]
  },
  "personalities": [
    {"id": "AGGRESSIVE", "categories": ["ATTACK"]},
    {"id": "DEFENSIVE", "categories": ["DEFENSE"]},
    {"id": "SUPPORTIVE", "categories": ["SUPPORT"]},
    {"id": "COWARD", "categories": ["FEAR"]},
    {"id": "TENACIOUS", "categories": ["INTERCEPT"]},
    {"id": "BOLD", "categories": ["ATTACK", "SUPPORT"]},
    {"id": "CAUTIOUS", "categories": ["DEFENSE", "FEAR"]},
    {"id": "DISCIPLINED", "categories": ["DEFENSE", "SUPPORT"]}
  ],
  "policy": {
    "gain": 0.25,
    "off_mood_factor": 0.5,
    "repeat_factor": 0.5,
    "floor": 0.05,
    "default_aggression": 0.5,
    "default_flee_share": 0.1,
    "coefficients": {
      "ATTACK": {"base": 0.5, "advantage": 0.8, "safety": 0.4},
      "DEFENSE": {"base": 0.3, "danger": 0.9, "aggression": 0.5},
      "SUPPORT": {"base": 0.3, "safety": 0.7, "passivity": 0.4},
      "FEAR": {"base": 0.05, "escape_pressure": 1.2},
      "INTERCEPT": {"collector_base": 0.05, "collector_weakness": 1.2, "wild_base": 0.05, "wild_flee_share": 1.0}
    }
  },
  "species": [
    {"id": "guardian", "name": "Guardian", "starter": true, "forbidden": false, "base_price": 100,
     "base": {"hp": 150, "essence": 20, "speed": 15}, "growth": {"hp": 15, "essence": 2, "speed": 1.5},
     "passive": {"kind": "defense_extension", "params": {"protected_attacks": 2, "rounds": 2}},
     "abilities": [
       {"id": "guardian_bulwark", "name": "Bulwark", "unlock_level": 1, "category": "DEFENSE", "percentage": 200, "cooldown": 1},
       {"id": "guardian_rally", "name": "Rally", "unlock_level": 10, "category": "SUPPORT", "percentage": 50, "cooldown": 2, "stat": "essence", "duration": 2},
       {"id": "guardian_heavy_blow", "name": "Heavy Blow", "unlock_level": 20, "category": "ATTACK", "percentage": 150, "cooldown": 2}]},
    {"id": "striker", "name": "Striker", "starter": true, "forbidden": false, "base_price": 120,
     "base": {"hp": 100, "essence": 30, "speed": 20}, "growth": {"hp": 10, "essence": 3, "speed": 2},
     "passive": {"kind": "low_hp_attack_bonus", "params": {"hp_below": 0.5, "essence_fraction": 0.2}},
     "abilities": [
       {"id": "striker_rending_strike", "name": "Rending Strike", "unlock_level": 1, "category": "ATTACK", "percentage": 150, "cooldown": 1},
       {"id": "striker_battle_focus", "name": "Battle Focus", "unlock_level": 10, "category": "SUPPORT", "percentage": 50, "cooldown": 2, "stat": "essence", "duration": 2},
       {"id": "striker_brace", "name": "Brace", "unlock_level": 20, "category": "DEFENSE", "percentage": 100, "cooldown": 1}]},
    {"id": "scout", "name": "Scout", "starter": true, "forbidden": false, "base_price": 110,
     "base": {"hp": 120, "essence": 22, "speed": 35}, "growth": {"hp": 12, "essence": 2.2, "speed": 3.5},
     "passive": {"kind": "battle_start_speed", "params": {"essence_fraction": 0.5}},
     "abilities": [
       {"id": "scout_quickstep", "name": "Quickstep", "unlock_level": 1, "category": "SUPPORT", "percentage": 100, "cooldown": 2, "stat": "speed", "duration": 2},
       {"id": "scout_swift_slash", "name": "Swift Slash", "unlock_level": 10, "category": "ATTACK", "percentage": 125, "cooldown": 1},
       {"id": "scout_evade", "name": "Evade", "unlock_level": 20, "category": "DEFENSE", "percentage": 150, "cooldown": 1}]},
    {"id": "sentinel", "name": "Sentinel", "starter": false, "forbidden": false, "base_price": 140,
     "base": {"hp": 180, "essence": 18, "speed": 10}, "growth": {"hp": 18, "essence": 1.8, "speed": 1},
     "passive": {"kind": "defense_rating_bonus", "params": {"essence_fraction": 0.5}},
     "abilities": [
       {"id": "sentinel_stone_guard", "name": "Stone Guard", "unlock_level": 1, "category": "DEFENSE", "percentage": 300, "cooldown": 1},
       {"id": "sentinel_hold_fast", "name": "Hold Fast", "unlock_level": 10, "category": "SUPPORT", "percentage": 50, "cooldown": 2, "stat": "essence", "duration": 2},
       {"id": "sentinel_shield_bash", "name": "Shield Bash", "unlock_level": 20, "category": "ATTACK", "percentage": 125, "cooldown": 2}]},
    {"id": "bruiser", "name": "Bruiser", "starter": false, "forbidden": false, "base_price": 130,
     "base": {"hp": 140, "essence": 28, "speed": 12}, "growth": {"hp": 14, "essence": 2.8, "speed": 1.2},
     "passive": {"kind": "attack_bonus_vs_defense", "params": {"essence_fraction": 0.25}},
     "abilities": [
       {"id": "bruiser_crushing_blow", "name": "Crushing Blow", "unlock_level": 1, "category": "ATTACK", "percentage": 175, "cooldown": 1},
       {"id": "bruiser_guard_up", "name": "Guard Up", "unlock_level": 10, "category": "DEFENSE", "percentage": 100, "cooldown": 1},
       {"id": "bruiser_rage", "name": "Rage", "unlock_level": 20, "category": "SUPPORT", "percentage": 50, "cooldown": 2, "stat": "essence", "duration": 2}]},
    {"id": "channeler", "name": "Channeler", "starter": false, "forbidden": false, "base_price": 150,
     "base": {"hp": 90, "essence": 25, "speed": 25}, "growth": {"hp": 9, "essence": 2.5, "speed": 2.5},
     "passive": {"kind": "support_duration_bonus", "params": {"rounds": 1}},
     "abilities": [
       {"id": "channeler_focus", "name": "Focus", "unlock_level": 1, "category": "SUPPORT", "percentage": 75, "cooldown": 2, "stat": "essence", "duration": 2},
       {"id": "channeler_bolt", "name": "Bolt", "unlock_level": 10, "category": "ATTACK", "percentage": 125, "cooldown": 1},
       {"id": "channeler_ward", "name": "Ward", "unlock_level": 20, "category": "DEFENSE", "percentage": 100, "cooldown": 1}]},
    {"id": "forbidden", "name": "Forbidden", "starter": false, "forbidden": true, "base_price": 1000,
     "base": {"hp": 200, "essence": 40, "speed": 30}, "growth": {"hp": 20, "essence": 4, "speed": 3},
     "passive": {"kind": "cooldown_reduction", "params": {"rounds": 1, "minimum": 1}},
     "abilities": [
       {"id": "forbidden_ruin", "name": "Ruin", "unlock_level": 1, "category": "ATTACK", "percentage": 200, "cooldown": 2},
       {"id": "forbidden_dread_ward", "name": "Dread Ward", "unlock_level": 10, "category": "DEFENSE", "percentage": 300, "cooldown": 2},
       {"id": "forbidden_ascendance", "name": "Ascendance", "unlock_level": 20, "category": "SUPPORT", "percentage": 100, "cooldown": 3, "stat": "essence", "duration": 2}]}
  ]
}
```

`apps/mini_games/src/sparks/catalog.py`

```python
"""The versioned game catalog: species, abilities, tiers, personalities, the
economy and the action-policy numbers. Loaded and validated once at startup.

Balance numbers are initial values; changing the file affects future battles
only (a battle freezes its fighters when it starts).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.sparks.models import ABILITY_CATEGORIES, CATEGORIES, AbilitySpec, PassiveSpec

ABILITY_UNLOCK_LEVELS = (1, 10, 20)
STATS = ("hp", "essence", "speed")


class CatalogError(ValueError):
    """The catalog file is missing a field or holds an inconsistent value."""


@dataclass(frozen=True)
class TierSpec:
    id: str
    stat_multiplier: float
    capture_multiplier: float
    hp_floor: float
    emblem_strength: int
    emblem_price: int
    encounter_probability: float
    copy_threshold: int | None  # None = outside the copy-based progression (Forbidden)
    copy_reward: int


@dataclass(frozen=True)
class SpeciesSpec:
    id: str
    name: str
    starter: bool
    forbidden: bool
    base_price: int
    base: Mapping[str, float]
    growth: Mapping[str, float]
    passive: PassiveSpec
    abilities: tuple[AbilitySpec, ...]


@dataclass(frozen=True)
class PersonalitySpec:
    id: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class PolicySpec:
    gain: float
    off_mood_factor: float
    repeat_factor: float
    floor: float
    default_aggression: float
    default_flee_share: float
    coefficients: Mapping[str, Mapping[str, float]]


@dataclass(frozen=True)
class Economy:
    xp_reward_factor: float
    insignia_reward_factor: float
    sale_level_bonus: float
    purchase_factor: float
    forbidden_copy_cap: int
    base_capture_resistance: float
    starter_emblems: Mapping[str, int]
    starter_personality_tier: int
    encounter_level_window: int
    personality_tier_probabilities: tuple[float, ...]


@dataclass(frozen=True)
class Levels:
    regular_cap: int
    forbidden_cap: int
    xp_per_level: int


def _require(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise CatalogError(f"{where}: missing {key!r}")
    return raw[key]


def _ability(raw: Mapping[str, Any], species_id: str) -> AbilitySpec:
    where = f"species {species_id!r} ability {raw.get('id')!r}"
    ability = AbilitySpec(
        id=_require(raw, "id", where), name=_require(raw, "name", where),
        unlock_level=_require(raw, "unlock_level", where), category=_require(raw, "category", where),
        percentage=float(_require(raw, "percentage", where)), cooldown=_require(raw, "cooldown", where),
        stat=raw.get("stat"), duration=raw.get("duration"),
    )
    if ability.category not in ABILITY_CATEGORIES:
        raise CatalogError(f"{where}: category must be one of {ABILITY_CATEGORIES}")
    if ability.cooldown < 1 or ability.percentage <= 0:
        raise CatalogError(f"{where}: cooldown must be at least 1 and percentage positive")
    if ability.category == "SUPPORT" and (ability.stat not in ("essence", "speed") or not ability.duration or ability.duration < 1):
        raise CatalogError(f"{where}: SUPPORT needs a stat (essence or speed) and a duration of at least 1")
    return ability


def _species(raw: Mapping[str, Any]) -> SpeciesSpec:
    sid = _require(raw, "id", "species")
    where = f"species {sid!r}"
    base, growth = _require(raw, "base", where), _require(raw, "growth", where)
    if set(base) != set(STATS) or set(growth) != set(STATS):
        raise CatalogError(f"{where}: base and growth need exactly hp, essence and speed")
    abilities = tuple(_ability(a, sid) for a in _require(raw, "abilities", where))
    if tuple(a.unlock_level for a in abilities) != ABILITY_UNLOCK_LEVELS:
        raise CatalogError(f"{where}: abilities must unlock at levels {ABILITY_UNLOCK_LEVELS}")
    passive = _require(raw, "passive", where)
    return SpeciesSpec(
        id=sid, name=_require(raw, "name", where), starter=bool(raw.get("starter")), forbidden=bool(raw.get("forbidden")),
        base_price=_require(raw, "base_price", where), base=dict(base), growth=dict(growth),
        passive=PassiveSpec(passive["kind"], dict(passive.get("params", {}))), abilities=abilities,
    )


class Catalog:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.version: int = _require(raw, "version", "catalog")
        self.tiers: tuple[TierSpec, ...] = tuple(TierSpec(**t) for t in _require(raw, "tiers", "catalog"))
        self.levels = Levels(**_require(raw, "levels", "catalog"))
        economy = dict(_require(raw, "economy", "catalog"))
        economy["personality_tier_probabilities"] = tuple(economy["personality_tier_probabilities"])
        self.economy = Economy(**economy)
        self.personalities: dict[str, PersonalitySpec] = {
            p["id"]: PersonalitySpec(p["id"], tuple(p["categories"])) for p in _require(raw, "personalities", "catalog")
        }
        policy = dict(_require(raw, "policy", "catalog"))
        self.policy = PolicySpec(**policy)
        self._species = {s.id: s for s in (_species(s) for s in _require(raw, "species", "catalog"))}
        self._tiers = {t.id: t for t in self.tiers}
        self._validate()

    # -- validation ----------------------------------------------------------------

    def _validate(self) -> None:
        if len(self._tiers) != len(self.tiers):
            raise CatalogError("tier ids must be unique")
        if not math.isclose(sum(t.encounter_probability for t in self.tiers), 1.0, abs_tol=1e-9):
            raise CatalogError("tier encounter probabilities must sum to 1")
        if not math.isclose(sum(self.economy.personality_tier_probabilities), 1.0, abs_tol=1e-9):
            raise CatalogError("personality tier probabilities must sum to 1")
        forbidden_tiers = [t for t in self.tiers if t.copy_threshold is None]
        if len(forbidden_tiers) != 1 or self.tiers[-1] is not forbidden_tiers[0]:
            raise CatalogError("exactly one tier, the last, may have copy_threshold null (Forbidden)")
        thresholds = [t.copy_threshold for t in self.regular_tiers]
        if thresholds[0] != 0 or thresholds != sorted(set(thresholds)):
            raise CatalogError("regular copy thresholds must start at 0 and strictly increase")
        if len([s for s in self._species.values() if s.starter]) != 3:
            raise CatalogError("exactly three species must be starters")
        if len([s for s in self._species.values() if s.forbidden]) != 1:
            raise CatalogError("exactly one species must be Forbidden")
        if any(s.starter and s.forbidden for s in self._species.values()):
            raise CatalogError("a starter cannot be Forbidden")
        for personality in self.personalities.values():
            if not personality.categories or any(c not in CATEGORIES for c in personality.categories):
                raise CatalogError(f"personality {personality.id!r} has invalid categories")
        for category in CATEGORIES:
            if category not in self.policy.coefficients:
                raise CatalogError(f"policy coefficients missing for {category}")
        for tier_id in self.economy.starter_emblems:
            self.tier(tier_id)

    # -- lookups -------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise CatalogError(f"cannot load catalog {path}: {error}") from error

    @property
    def regular_tiers(self) -> tuple[TierSpec, ...]:
        return self.tiers[:-1]

    @property
    def forbidden_tier(self) -> TierSpec:
        return self.tiers[-1]

    def tier(self, tier_id: str) -> TierSpec:
        try:
            return self._tiers[tier_id]
        except KeyError:
            raise CatalogError(f"unknown tier {tier_id!r}") from None

    def species(self, species_id: str) -> SpeciesSpec:
        try:
            return self._species[species_id]
        except KeyError:
            raise CatalogError(f"unknown species {species_id!r}") from None

    def has_species(self, species_id: str) -> bool:
        return species_id in self._species

    def all_species(self) -> tuple[SpeciesSpec, ...]:
        return tuple(self._species.values())

    def regular_species(self) -> tuple[SpeciesSpec, ...]:
        return tuple(s for s in self._species.values() if not s.forbidden)

    def starter_species(self) -> tuple[SpeciesSpec, ...]:
        return tuple(s for s in self._species.values() if s.starter)

    def forbidden_species(self) -> SpeciesSpec:
        return next(s for s in self._species.values() if s.forbidden)

    def level_cap(self, species_id: str) -> int:
        return self.levels.forbidden_cap if self.species(species_id).forbidden else self.levels.regular_cap

    def stat_value(self, species_id: str, level: int, tier_id: str, stat: str) -> int:
        """Full-precision stat, then floored to a positive whole number."""
        species = self.species(species_id)
        raw = (species.base[stat] + species.growth[stat] * (level - 1)) * self.tier(tier_id).stat_multiplier
        return max(1, math.floor(raw + 1e-9))

    def tier_for_copies(self, species_id: str, copies: int) -> str:
        """Highest regular tier whose threshold the copy count meets; Forbidden is fixed."""
        if self.species(species_id).forbidden:
            return self.forbidden_tier.id
        reached = [t for t in self.regular_tiers if copies >= t.copy_threshold]
        return reached[-1].id

    def sale_value(self, species_id: str, tier_id: str, level: int) -> int:
        """Insignia for selling one copy of a Spark at this tier and level."""
        species = self.species(species_id)
        factor = 1 + self.economy.sale_level_bonus * (level - 1)
        return math.floor(species.base_price * self.tier(tier_id).stat_multiplier * factor + 1e-9)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_catalog.py -q`
Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks apps/mini_games/configs/spark_catalog.json apps/mini_games/tests/sparks
git commit -m "feat(mini_games): Spark value objects and the game catalog"
```

---

### Task 5: Runtime sources, passives and test helpers

**Files:**
- Create: `apps/mini_games/src/sparks/runtime.py`, `src/sparks/passives.py`, `tests/sparks/helpers.py`
- Test: `apps/mini_games/tests/sparks/test_passives.py`

**Interfaces:**
- Produces (`runtime`): `Clock` and `RandomSource` protocols; `SystemClock`, `SystemRandom`; `SeededRandom(seed, counter=0)` (`next()`, `.seed`, `.counter`; draw n depends only on seed and n, so a battle's stream is saved as two integers); `RecordingRandom(inner)` with `.draws`; `new_seed()`, `new_id()`.
- Produces (`passives`): `Passive` (neutral defaults for `start_buffs`, `defense_limits`, `defense_rating_bonus`, `support_extra_rounds`, `attack_bonus`, `cooldown`), one subclass per catalog passive kind, and `PassiveFactory().create(PassiveSpec)` / `.register(kind, builder)`.
- Produces (`tests/sparks/helpers.py`): `ScriptedRandom(*draws)`, `FixedClock`, builders `fighter`, `setup`, `ability`, `battle_record`, and `ScriptedPolicy` (a policy double). Later tasks import them; the heavier imports inside are deliberately local.

- [ ] **Step 1: Write the helpers and the failing test**

`apps/mini_games/tests/sparks/helpers.py`

```python
"""Test doubles and builders shared by the Spark tests."""

from __future__ import annotations

from src.sparks.models import PLAYER, WILD, AbilitySpec, BattleSetup, Fighter, PassiveSpec


class ScriptedRandom:
    """Returns the given draws in order; fails loudly if the code draws too often."""

    def __init__(self, *values: float) -> None:
        self._values = list(values)
        self.used = 0

    def next(self) -> float:
        if self.used >= len(self._values):
            raise AssertionError("more random draws than the test scripted")
        value = self._values[self.used]
        self.used += 1
        return value


class FixedClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.t = now

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def fighter(
    side: str = PLAYER,
    hp: int = 100,
    essence: int = 40,
    speed: int = 20,
    abilities: tuple[AbilitySpec, ...] = (),
    passive: PassiveSpec | None = None,
    species_id: str = "guardian",
    tier_id: str = "normal",
    level: int = 1,
) -> Fighter:
    return Fighter(side, species_id, tier_id, level, hp, essence, speed, abilities, passive or PassiveSpec("none"))


def setup(player: Fighter | None = None, wild: Fighter | None = None) -> BattleSetup:
    return BattleSetup(player or fighter(PLAYER), wild or fighter(WILD))


def ability(
    id: str = "a1", category: str = "ATTACK", percentage: float = 150, cooldown: int = 1,
    stat: str | None = None, duration: int | None = None, unlock_level: int = 1,
) -> AbilitySpec:
    return AbilitySpec(id, id, unlock_level, category, percentage, cooldown, stat, duration)


def battle_record(owner: str = "ann", battle_id: str = "b1", encounter_id: str = "e1", status: str = "active", revision: int = 1):
    """A minimal valid BattleRecord for repository tests."""
    from src.sparks.models import BattleState, FighterState, PersonalityInstance
    from src.sparks.records import BattleRecord

    s = setup()
    state = BattleState(1, FighterState(100), FighterState(100))
    return BattleRecord(
        id=battle_id, owner=owner, encounter_id=encounter_id, status=status, phase="choosing" if status == "active" else "terminal",
        mode="manual", revision=revision, setup=s, state=state,
        player_personalities=(PersonalityInstance("p1", "AGGRESSIVE", 1),), wild_personalities=(PersonalityInstance("w1", "COWARD", 2),),
        emblem_limit=None, rng_seed=42, rng_counter=0, created_at=1.0, updated_at=1.0,
    )


class ScriptedPolicy:
    """Stands in for ActionPolicy: returns scripted action keys per actor, then basic ATTACK.

    The player's Spark is the collector. It never draws, so scripted tests stay exact."""

    def __init__(self, player=(), wild=()) -> None:
        self.player, self.wild = list(player), list(wild)
        self.contexts = []

    def probabilities(self, actions, ctx):
        return [1 / len(actions)] * len(actions)

    def choose(self, actions, ctx, u):
        from src.sparks.policy import PolicyDecision

        self.contexts.append(ctx)
        script = self.player if ctx.collector else self.wild
        key = script.pop(0) if script else "attack"
        action = next(a for a in actions if a.key == key)
        return PolicyDecision(action, tuple(self.probabilities(actions, ctx)))
```

`apps/mini_games/tests/sparks/test_passives.py`

```python
import pytest

from src.sparks.models import PassiveSpec
from src.sparks.passives import Passive, PassiveFactory

factory = PassiveFactory()


def make(kind, **params):
    return factory.create(PassiveSpec(kind, params))


def test_neutral_passive_changes_nothing():
    p = make("none")
    assert p.start_buffs(40) == [] and p.defense_limits() == (1, 1) and p.defense_rating_bonus(40) == 0
    assert p.support_extra_rounds() == 0 and p.attack_bonus(40, 10, 100, True) == 0 and p.cooldown(2) == 2


def test_defense_extension_sets_limits():
    assert make("defense_extension", protected_attacks=2, rounds=2).defense_limits() == (2, 2)


def test_low_hp_bonus_applies_strictly_below_half():
    p = make("low_hp_attack_bonus", hp_below=0.5, essence_fraction=0.2)
    assert p.attack_bonus(50, 49, 100, False) == pytest.approx(10)
    assert p.attack_bonus(50, 50, 100, False) == 0
    assert p.attack_bonus(50, 100, 100, False) == 0


def test_scout_start_speed_uses_unbuffed_essence_floor():
    assert make("battle_start_speed", essence_fraction=0.5).start_buffs(25) == [("speed", 12)]


def test_sentinel_adds_defense_rating():
    assert make("defense_rating_bonus", essence_fraction=0.5).defense_rating_bonus(30) == 15


def test_bruiser_bonus_only_against_defense():
    p = make("attack_bonus_vs_defense", essence_fraction=0.25)
    assert p.attack_bonus(40, 100, 100, True) == 10 and p.attack_bonus(40, 100, 100, False) == 0


def test_channeler_extends_support():
    assert make("support_duration_bonus", rounds=1).support_extra_rounds() == 1


@pytest.mark.parametrize("base,expected", [(2, 1), (3, 2), (1, 1)])
def test_forbidden_cooldown_reduction_has_a_floor(base, expected):
    assert make("cooldown_reduction", rounds=1, minimum=1).cooldown(base) == expected


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="unknown passive"):
        make("teleport")


def test_new_kinds_can_be_registered():
    custom = PassiveFactory()
    custom.register("echo", lambda: Passive())
    assert isinstance(custom.create(PassiveSpec("echo")), Passive)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_passives.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.passives'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/runtime.py`

```python
"""Time and randomness behind small interfaces, so tests control both.

`SeededRandom` is stateless apart from (seed, counter): draw n is derived from
the seed and n alone, so a battle's random stream is saved as two integers and
a restart or retry replays the same draws instead of rerolling.
"""

from __future__ import annotations

import random
import secrets
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Seconds since the epoch, UTC."""


class RandomSource(Protocol):
    def next(self) -> float:
        """A float in [0, 1)."""


class SystemClock:
    def now(self) -> float:
        return time.time()


class SystemRandom:
    """Unseeded randomness for rolls that need no replay (encounters, awards)."""

    def __init__(self) -> None:
        self._random = random.SystemRandom()

    def next(self) -> float:
        return self._random.random()


class SeededRandom:
    def __init__(self, seed: int, counter: int = 0) -> None:
        self.seed = seed
        self.counter = counter

    def next(self) -> float:
        value = random.Random(f"{self.seed}:{self.counter}").random()
        self.counter += 1
        return value


class RecordingRandom:
    """Wraps a source and remembers every draw, to store with a round result."""

    def __init__(self, inner: RandomSource) -> None:
        self._inner = inner
        self.draws: list[float] = []

    def next(self) -> float:
        value = self._inner.next()
        self.draws.append(value)
        return value


def new_seed() -> int:
    return secrets.randbits(62)


def new_id() -> str:
    """A server-created identifier; clients never choose ids."""
    return secrets.token_urlsafe(9)
```

`apps/mini_games/src/sparks/passives.py`

```python
"""Species passives as small polymorphic objects.

Each passive overrides only the hooks it changes; the base class holds the
neutral defaults, so the engine asks every passive the same questions.
"""

from __future__ import annotations

import math
from typing import Callable

from src.sparks.models import PassiveSpec


class Passive:
    """Neutral behavior: a species without a passive effect."""

    def start_buffs(self, essence: int) -> list[tuple[str, int]]:
        """(stat, amount) bonuses applied once when the battle starts."""
        return []

    def defense_limits(self) -> tuple[int, int]:
        """(protected attacks, rounds) of a fresh DEFENSE effect."""
        return 1, 1

    def defense_rating_bonus(self, essence: int) -> float:
        return 0.0

    def support_extra_rounds(self) -> int:
        return 0

    def attack_bonus(self, essence: int, hp: int, max_hp: int, target_chose_defense: bool) -> float:
        """Raw damage added to an attack, before mitigation."""
        return 0.0

    def cooldown(self, base: int) -> int:
        return base


class DefenseExtension(Passive):
    def __init__(self, protected_attacks: int, rounds: int) -> None:
        self._attacks, self._rounds = protected_attacks, rounds

    def defense_limits(self) -> tuple[int, int]:
        return self._attacks, self._rounds


class LowHpAttackBonus(Passive):
    def __init__(self, hp_below: float, essence_fraction: float) -> None:
        self._below, self._fraction = hp_below, essence_fraction

    def attack_bonus(self, essence: int, hp: int, max_hp: int, target_chose_defense: bool) -> float:
        return essence * self._fraction if hp < max_hp * self._below else 0.0


class BattleStartSpeed(Passive):
    def __init__(self, essence_fraction: float) -> None:
        self._fraction = essence_fraction

    def start_buffs(self, essence: int) -> list[tuple[str, int]]:
        return [("speed", math.floor(essence * self._fraction))]


class DefenseRatingBonus(Passive):
    def __init__(self, essence_fraction: float) -> None:
        self._fraction = essence_fraction

    def defense_rating_bonus(self, essence: int) -> float:
        return essence * self._fraction


class AttackBonusVersusDefense(Passive):
    def __init__(self, essence_fraction: float) -> None:
        self._fraction = essence_fraction

    def attack_bonus(self, essence: int, hp: int, max_hp: int, target_chose_defense: bool) -> float:
        return essence * self._fraction if target_chose_defense else 0.0


class SupportDurationBonus(Passive):
    def __init__(self, rounds: int) -> None:
        self._rounds = rounds

    def support_extra_rounds(self) -> int:
        return self._rounds


class CooldownReduction(Passive):
    def __init__(self, rounds: int, minimum: int) -> None:
        self._rounds, self._minimum = rounds, minimum

    def cooldown(self, base: int) -> int:
        return max(base - self._rounds, self._minimum)


class PassiveFactory:
    """Builds a Passive from the saved spec. Register new kinds with `register`."""

    def __init__(self) -> None:
        self._kinds: dict[str, Callable[..., Passive]] = {
            "none": Passive,
            "defense_extension": DefenseExtension,
            "low_hp_attack_bonus": LowHpAttackBonus,
            "battle_start_speed": BattleStartSpeed,
            "defense_rating_bonus": DefenseRatingBonus,
            "attack_bonus_vs_defense": AttackBonusVersusDefense,
            "support_duration_bonus": SupportDurationBonus,
            "cooldown_reduction": CooldownReduction,
        }

    def register(self, kind: str, builder: Callable[..., Passive]) -> None:
        self._kinds[kind] = builder

    def create(self, spec: PassiveSpec) -> Passive:
        try:
            return self._kinds[spec.kind](**spec.params)
        except KeyError:
            raise ValueError(f"unknown passive kind {spec.kind!r}") from None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_passives.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/runtime.py apps/mini_games/src/sparks/passives.py apps/mini_games/tests/sparks/helpers.py apps/mini_games/tests/sparks/test_passives.py
git commit -m "feat(mini_games): clock, seeded randomness and species passives"
```

---

### Task 6: The battle engine

**Files:**
- Create: `apps/mini_games/src/sparks/engine.py`
- Test: `apps/mini_games/tests/sparks/test_engine.py`

**Interfaces:**
- Consumes: `Catalog`, `PassiveFactory`, `RandomSource`, `RecordingRandom`, the models.
- Produces: `BattleEngine(catalog, passives=None)` with `build_fighter(side, species_id, tier_id, level) -> Fighter`, `start_state(setup) -> BattleState`, `stat(fighter, fstate, "essence" | "speed") -> int` (including buffs), `legal_actions(setup, state, side, *, can_collect) -> list[Action]`, `resolve_action(legal, payload) -> Action` (payload `{kind, ability_id?, emblem_tier?}`), `capture_chance(emblem_tier, target_fighter, target_state) -> float`, `resolve_round(setup, state, player_action, wild_action, rng) -> RoundOutcome`; `ActionError(ValueError)`.
- Round rules implemented here (spec "Round state machine and resolution"): cooldown starts when an action is revealed and blocks the next `d` rounds; SUPPORT then DEFENSE; SUPPORT buffs use unbuffed ESSENCE, refresh instead of stacking, different buffs add; DEFENSE rating uses current ESSENCE, snapshot at activation, overlapping defenses keep the strongest rating and a refresh resets the limits; CATCH reduces FLEE whatever the order and spends no EMBLEM; exactly one order roll per round from the updated SPEED; ATTACK, CATCH and FLEE resolve in that order; FLEE chance uses the HP left when the attempt resolves; a collection attempt spends one EMBLEM win or lose; the first knockout, capture or escape stops the round; terminal kinds are `won`, `knocked_out`, `captured`, `escaped`, `wild_escaped`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_engine.py`

```python
from dataclasses import replace
from pathlib import Path

import pytest

from src.sparks.catalog import Catalog
from src.sparks.engine import ActionError, BattleEngine
from src.sparks.models import PLAYER, WILD, Action, BattleSetup, BattleState, Buff, FighterState, PassiveSpec
from tests.sparks.helpers import ScriptedRandom, ability, fighter, setup

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
engine = BattleEngine(CATALOG)

ATTACK = Action("attack", "ATTACK")
FLEE = Action("flee", "FEAR")
CATCH_WILD = Action("catch", "INTERCEPT")


def catch(tier="normal"):
    return Action("catch", "INTERCEPT", emblem_tier=tier)


def use(spec):
    return Action("ability", spec.category, spec.id, spec.percentage)


def play(s, pa, wa, *draws, state=None):
    return engine.resolve_round(s, state or engine.start_state(s), pa, wa, ScriptedRandom(*draws))


# -- setup ---------------------------------------------------------------------------

def test_build_fighter_unlocks_abilities_by_level():
    assert len(engine.build_fighter(PLAYER, "guardian", "normal", 1).abilities) == 1
    assert len(engine.build_fighter(PLAYER, "guardian", "normal", 10).abilities) == 2
    assert len(engine.build_fighter(PLAYER, "guardian", "normal", 20).abilities) == 3


def test_build_fighter_applies_tier_to_stats():
    f = engine.build_fighter(WILD, "forbidden", "forbidden", 1)
    assert (f.max_hp, f.essence, f.speed) == (800, 160, 120)


def test_scout_starts_with_a_speed_buff_from_unbuffed_essence():
    s = BattleSetup(engine.build_fighter(PLAYER, "scout", "normal", 1), engine.build_fighter(WILD, "guardian", "normal", 1))
    state = engine.start_state(s)
    assert engine.stat(s.player, state.player, "speed") == 35 + 11  # 50% of 22 ESSENCE
    assert engine.stat(s.wild, state.wild, "speed") == 15 and state.round == 1


# -- legal actions -------------------------------------------------------------------

def test_legal_actions_include_basic_actions_and_abilities():
    s = setup(fighter(abilities=(ability("hit"),)))
    keys = [a.key for a in engine.legal_actions(s, engine.start_state(s), PLAYER, can_collect=True)]
    assert keys == ["attack", "ability:hit", "flee", "catch"]


def test_collector_needs_an_emblem_to_catch_but_wild_does_not():
    s = setup()
    state = engine.start_state(s)
    assert "catch" not in [a.key for a in engine.legal_actions(s, state, PLAYER, can_collect=False)]
    assert "catch" in [a.key for a in engine.legal_actions(s, state, WILD, can_collect=False)]


@pytest.mark.parametrize("cooldown,blocked,available", [(1, [2], 3), (2, [2, 3], 4)])
def test_cooldown_blocks_exactly_the_following_rounds(cooldown, blocked, available):
    spec = ability("hit", cooldown=cooldown)
    s = setup(fighter(abilities=(spec,)))
    state = play(s, use(spec), FLEE, 0.5, 0.99).state
    for rnd in blocked + [available]:
        at = replace(state, round=rnd)
        keys = [a.key for a in engine.legal_actions(s, at, PLAYER, can_collect=False)]
        assert ("ability:hit" in keys) == (rnd == available)


def test_forbidden_passive_shortens_cooldowns_to_a_minimum_of_one():
    spec = ability("ruin", cooldown=2)
    s = setup(fighter(abilities=(spec,), passive=PassiveSpec("cooldown_reduction", {"rounds": 1, "minimum": 1})))
    state = play(s, use(spec), FLEE, 0.5, 0.99).state
    assert dict(state.player.cooldowns)["ruin"] == 3  # used round 1 + cooldown 1 + 1


def test_resolve_action_matches_payloads():
    s = setup(fighter(abilities=(ability("hit"),)))
    legal = engine.legal_actions(s, engine.start_state(s), PLAYER, can_collect=True)
    assert engine.resolve_action(legal, {"kind": "attack"}).key == "attack"
    assert engine.resolve_action(legal, {"kind": "ability", "ability_id": "hit"}).percentage == 150
    assert engine.resolve_action(legal, {"kind": "catch", "emblem_tier": "rare"}).emblem_tier == "rare"
    for bad in [{"kind": "ability", "ability_id": "nope"}, {"kind": "dance"}, {"kind": "catch"}, {"kind": "catch", "emblem_tier": "gold"}]:
        with pytest.raises((ActionError, ValueError)):
            engine.resolve_action(legal, bad)


# -- attack and defense --------------------------------------------------------------

def test_basic_attack_is_one_hundred_percent_of_essence():
    out = play(setup(), ATTACK, FLEE, 0.1, 0.99)  # player first; wild flee fails
    assert out.state.wild.hp == 60 and out.state.round == 2


def test_minimum_damage_is_one():
    s = setup(fighter(essence=0))
    assert play(s, ATTACK, FLEE, 0.1, 0.99).state.wild.hp == 99


def test_defense_uses_diminishing_returns_and_protects_one_attack():
    guard = ability("guard", "DEFENSE", 250)  # rating 40 * 2.5 = 100 -> halves damage
    s = setup(wild=fighter(WILD, abilities=(guard,)))
    out = play(s, ATTACK, use(guard), 0.1)
    assert out.state.wild.hp == 80  # 40 * 100 / 200 = 20
    assert out.state.wild.defense is None  # expired at round end


def test_defense_protects_only_its_allowed_attacks():
    guard = ability("guard", "DEFENSE", 250)
    passive = PassiveSpec("defense_extension", {"protected_attacks": 2, "rounds": 2})
    s = setup(player=fighter(PLAYER, speed=1000), wild=fighter(WILD, essence=40, abilities=(guard,), passive=passive))
    r1 = play(s, ATTACK, use(guard), 0.1)
    assert r1.state.wild.hp == 80 and r1.state.wild.defense.attacks_left == 1 and r1.state.wild.defense.rounds_left == 1
    r2 = engine.resolve_round(s, r1.state, ATTACK, ATTACK, ScriptedRandom(0.1))
    assert r2.state.wild.hp == 60  # second protected attack: 20 more damage
    assert r2.state.wild.defense is None  # attacks exhausted


def test_defense_refresh_keeps_the_strongest_rating_and_resets_limits():
    weak, strong = ability("weak", "DEFENSE", 100), ability("strong", "DEFENSE", 300)
    passive = PassiveSpec("defense_extension", {"protected_attacks": 2, "rounds": 2})
    s = setup(wild=fighter(WILD, abilities=(weak, strong), passive=passive))
    r1 = play(s, FLEE, use(strong), 0.5, 0.99)
    assert r1.state.wild.defense.rating == 120 and r1.state.wild.defense.rounds_left == 1
    r2 = engine.resolve_round(s, r1.state, FLEE, use(weak), ScriptedRandom(0.5, 0.99))
    assert r2.state.wild.defense is None or r2.state.wild.defense.rating == 120


def test_defense_refresh_restores_allowance_without_banking():
    guard = ability("guard", "DEFENSE", 100)
    passive = PassiveSpec("defense_extension", {"protected_attacks": 2, "rounds": 2})
    s = setup(wild=fighter(WILD, abilities=(guard,), passive=passive))
    r1 = play(s, FLEE, use(guard), 0.5, 0.99)
    spent = replace(r1.state, wild=replace(r1.state.wild, defense=replace(r1.state.wild.defense, attacks_left=1, rounds_left=1)))
    refreshed = engine.resolve_round(s, spent, FLEE, use(guard), ScriptedRandom(0.5, 0.99))
    assert (refreshed.state.wild.defense.attacks_left, refreshed.state.wild.defense.rounds_left) == (2, 1)


def test_sentinel_adds_unbuffed_essence_share_to_defense_rating():
    guard = ability("guard", "DEFENSE", 100)
    passive = PassiveSpec("defense_rating_bonus", {"essence_fraction": 0.5})
    s = setup(wild=fighter(WILD, essence=40, abilities=(guard,), passive=passive))
    event = next(e for e in play(s, FLEE, use(guard), 0.5, 0.99).events if e["type"] == "defense")
    assert event["rating"] == 60  # 40 + 20


def test_striker_bonus_below_half_hp_and_bruiser_bonus_against_defense():
    low = PassiveSpec("low_hp_attack_bonus", {"hp_below": 0.5, "essence_fraction": 0.5})
    s = setup(player=fighter(PLAYER, essence=40, passive=low))
    hurt = BattleState(1, FighterState(hp=40), FighterState(hp=100))
    assert play(s, ATTACK, FLEE, 0.1, 0.99, state=hurt).state.wild.hp == 40  # 40 + 20 raw
    guard = ability("guard", "DEFENSE", 0)
    bruise = PassiveSpec("attack_bonus_vs_defense", {"essence_fraction": 0.5})
    s2 = setup(player=fighter(PLAYER, essence=40, passive=bruise), wild=fighter(WILD, abilities=(guard,)))
    assert play(s2, ATTACK, use(guard), 0.1).state.wild.hp == 40  # 60 raw, defense rating ~0


def test_knockout_ends_the_round_and_skips_later_actions():
    s = setup(player=fighter(PLAYER, essence=200, speed=1000), wild=fighter(WILD, hp=50))
    out = play(s, ATTACK, ATTACK, 0.1)
    assert out.terminal == "won" and out.state.round == 1
    assert out.state.player.hp == 100  # the wild's attack never ran
    assert len(out.draws) == 1 and out.emblem_consumed is None


def test_player_knocked_out():
    s = setup(player=fighter(PLAYER, hp=10, speed=1), wild=fighter(WILD, essence=200, speed=1000))
    assert play(s, ATTACK, ATTACK, 0.99).terminal == "knocked_out"


# -- support and buffs ---------------------------------------------------------------

def test_support_buff_applies_to_this_rounds_attack_and_lasts_its_duration():
    focus = ability("focus", "SUPPORT", 50, stat="essence", duration=2)
    s = setup(player=fighter(PLAYER, essence=40, abilities=(focus,)))
    r1 = play(s, use(focus), FLEE, 0.1, 0.99)
    assert r1.state.player.buffs[0].amount == 20 and r1.state.player.buffs[0].rounds_left == 1
    r2 = engine.resolve_round(s, r1.state, ATTACK, FLEE, ScriptedRandom(0.1, 0.99))
    assert r2.state.wild.hp == 40  # attack uses 60 ESSENCE
    assert r2.state.player.buffs == ()  # expired after its second round


def test_reusing_a_support_refreshes_without_stacking_and_different_buffs_add():
    a = ability("a", "SUPPORT", 50, stat="essence", duration=2)
    b = ability("b", "SUPPORT", 25, stat="essence", duration=3)
    s = setup(player=fighter(PLAYER, essence=40, abilities=(a, b)))
    running = replace(engine.start_state(s), player=FighterState(hp=100, buffs=(Buff("a", "essence", 20, 2),)))
    refreshed = engine.resolve_round(s, running, use(a), FLEE, ScriptedRandom(0.1, 0.99)).state
    assert [(x.source, x.amount, x.rounds_left) for x in refreshed.player.buffs] == [("a", 20, 1)]  # one copy, restarted
    added = engine.resolve_round(s, running, use(b), FLEE, ScriptedRandom(0.1, 0.99)).state
    assert sum(x.amount for x in added.player.buffs) == 30  # 20 + 10, added


def test_channeler_passive_extends_support_duration():
    focus = ability("focus", "SUPPORT", 50, stat="essence", duration=2)
    s = setup(player=fighter(PLAYER, abilities=(focus,), passive=PassiveSpec("support_duration_bonus", {"rounds": 1})))
    assert play(s, use(focus), FLEE, 0.1, 0.99).state.player.buffs[0].rounds_left == 2  # 3 total, 1 spent


def test_speed_buff_changes_this_rounds_order_roll():
    quick = ability("quick", "SUPPORT", 100, stat="speed", duration=2)
    s = setup(player=fighter(PLAYER, essence=30, speed=10, abilities=(quick,)), wild=fighter(WILD, speed=40))
    out = play(s, use(quick), FLEE, 0.5, 0.99)
    order = next(e for e in out.events if e["type"] == "order")
    assert order["chance_player_first"] == pytest.approx(40 / 80, abs=1e-4)  # speed 10 + 30 against 40


# -- order ---------------------------------------------------------------------------

@pytest.mark.parametrize("draw,first", [(0.59, PLAYER), (0.61, WILD)])
def test_order_roll_uses_speed_probability(draw, first):
    s = setup(player=fighter(PLAYER, speed=60), wild=fighter(WILD, speed=40))
    out = play(s, ATTACK, ATTACK, draw)
    assert next(e for e in out.events if e["type"] == "order")["first"] == first


def test_exactly_one_order_roll_even_when_nothing_needs_ordering():
    guard = ability("guard", "DEFENSE", 100)
    s = setup(player=fighter(PLAYER, abilities=(guard,)), wild=fighter(WILD, abilities=(guard,)))
    out = play(s, use(guard), use(guard), 0.5)
    assert len(out.draws) == 1


# -- flee and catch ------------------------------------------------------------------

def test_flee_chance_formula_and_success():
    s = setup(player=fighter(PLAYER, essence=100, speed=1000))
    out = play(s, FLEE, ATTACK, 0.1, 0.49)  # 100 / 200 * full HP = 0.5
    assert out.terminal == "escaped"
    flee = next(e for e in out.events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.5) and flee["success"] is True


def test_flee_chance_scales_with_remaining_hp():
    s = setup(player=fighter(PLAYER, essence=100, speed=1000))
    hurt = BattleState(1, FighterState(hp=50), FighterState(hp=100))
    flee = next(e for e in play(s, FLEE, ATTACK, 0.1, 0.99, state=hurt).events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.25)


def test_flee_uses_the_hp_left_when_the_attempt_resolves():
    # The wild Spark acts first and halves the player's HP, so the escape chance is 0.5 * 0.5.
    s = setup(player=fighter(PLAYER, hp=100, essence=100, speed=1), wild=fighter(WILD, essence=50, speed=1000))
    out = play(s, FLEE, ATTACK, 0.99, 0.99)
    flee = next(e for e in out.events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.25) and out.state.player.hp == 50


def test_the_order_roll_follows_the_speed_ratio_over_many_rounds():
    from src.sparks.runtime import SeededRandom

    s = setup(player=fighter(PLAYER, speed=60), wild=fighter(WILD, speed=40))
    state, rng, first = engine.start_state(s), SeededRandom(9), 0
    for _ in range(4000):
        out = engine.resolve_round(s, state, FLEE, FLEE, rng)
        first += next(e for e in out.events if e["type"] == "order")["first"] == PLAYER
    assert first / 4000 == pytest.approx(0.6, abs=0.03)


@pytest.mark.parametrize("draw", [0.01, 0.99])  # the order roll must not matter
def test_catch_counters_flee_whatever_the_order(draw):
    s = setup(player=fighter(PLAYER, essence=100), wild=fighter(WILD, essence=100))
    out = play(s, FLEE, CATCH_WILD, draw, 0.2)
    flee = next(e for e in out.events if e["type"] == "flee")
    assert flee["chance"] == pytest.approx(0.25)  # 0.5 * 100 / 200
    assert out.emblem_consumed is None


def test_player_catch_against_flee_makes_no_collection_attempt():
    s = setup(player=fighter(PLAYER, essence=100), wild=fighter(WILD, essence=100))
    out = play(s, catch(), FLEE, 0.01, 0.99)
    assert out.emblem_consumed is None and out.terminal is None
    assert next(e for e in out.events if e["type"] == "flee")["chance"] == pytest.approx(0.25)


def test_capture_chance_matches_the_formula():
    s = setup(wild=fighter(WILD, hp=100, tier_id="rare"))
    state = engine.start_state(s)
    # resistance = 100 * 2 * (0.2 + 0.8 * 1) = 200; Rare EMBLEM strength 200
    assert engine.capture_chance("rare", s.wild, state.wild) == pytest.approx(0.5)
    half = FighterState(hp=50)
    assert engine.capture_chance("rare", s.wild, half) == pytest.approx(200 / (200 + 200 * 0.6))


def test_forbidden_keeps_most_of_its_resistance_at_low_hp():
    s = setup(wild=fighter(WILD, hp=100, tier_id="forbidden"))
    nearly_dead = FighterState(hp=1)
    chance = engine.capture_chance("forbidden", s.wild, nearly_dead)
    assert chance == pytest.approx(3200 / (3200 + 12800 * (0.8 + 0.2 * 0.01)))


@pytest.mark.parametrize("draw,captured", [(0.4, True), (0.6, False)])
def test_collection_consumes_the_emblem_win_or_lose(draw, captured):
    s = setup(wild=fighter(WILD, tier_id="rare"))
    out = play(s, catch("rare"), ATTACK, 0.1, draw)  # player acts first; chance 0.5
    assert out.emblem_consumed == "rare"
    assert (out.terminal == "captured") is captured


def test_wild_catch_against_a_non_flee_action_does_nothing():
    out = play(setup(), ATTACK, CATCH_WILD, 0.1)
    assert out.terminal is None and out.emblem_consumed is None


def test_terminal_result_preempts_a_later_collection_attempt():
    s = setup(player=fighter(PLAYER, speed=1), wild=fighter(WILD, essence=500, speed=1000))
    out = play(s, catch(), ATTACK, 0.99)  # wild acts first and knocks the player out
    assert out.terminal == "knocked_out" and out.emblem_consumed is None


# -- history and serialization -------------------------------------------------------

def test_history_records_revealed_actions_and_round_advances():
    out = play(setup(), ATTACK, FLEE, 0.1, 0.99)
    revealed = out.state.history[0]
    assert revealed.round == 1 and revealed.actions == {PLAYER: ("attack", "ATTACK"), WILD: ("flee", "FEAR")}


def test_battle_state_and_setup_round_trip_through_json():
    import json

    s = BattleSetup(engine.build_fighter(PLAYER, "scout", "rare", 12), engine.build_fighter(WILD, "forbidden", "forbidden", 5))
    out = play(s, ATTACK, FLEE, 0.1, 0.99)
    assert BattleSetup.from_dict(json.loads(json.dumps(s.to_dict()))) == s
    assert BattleState.from_dict(json.loads(json.dumps(out.state.to_dict()))) == out.state
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_engine.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.engine'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/engine.py`

```python
"""The battle rules. Pure: no database, HTTP, clock or model.

One round, in order: lock both actions, apply SUPPORT then DEFENSE, settle
CATCH-versus-FLEE, roll the action order once from the updated SPEED, resolve
ATTACK / CATCH / FLEE in that order, stop at the first terminal result, then
expire end-of-round effects.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.models import (
    PLAYER,
    SIDES,
    WILD,
    AbilitySpec,
    Action,
    BattleSetup,
    BattleState,
    Buff,
    DefenseEffect,
    Fighter,
    FighterState,
    RevealedRound,
    RoundOutcome,
    other,
)
from src.sparks.passives import Passive, PassiveFactory
from src.sparks.runtime import RandomSource, RecordingRandom

_EPS = 1e-9


class ActionError(ValueError):
    """The chosen action is not legal this round."""


class _Side:
    """Mutable working copy of one fighter while a round resolves."""

    def __init__(self, side: str, fighter: Fighter, fstate: FighterState, passive: Passive) -> None:
        self.side, self.fighter, self.passive = side, fighter, passive
        self.hp = fstate.hp
        self.buffs = list(fstate.buffs)
        self.defense = fstate.defense
        self.cooldowns = dict(fstate.cooldowns)

    def stat(self, name: str) -> int:
        return getattr(self.fighter, name) + sum(b.amount for b in self.buffs if b.stat == name)

    def freeze(self) -> FighterState:
        return FighterState(self.hp, tuple(self.buffs), self.defense, tuple(sorted(self.cooldowns.items())))


class BattleEngine:
    def __init__(self, catalog: Catalog, passives: PassiveFactory | None = None) -> None:
        self._catalog = catalog
        self._passives = passives or PassiveFactory()

    # -- setup ---------------------------------------------------------------------

    def build_fighter(self, side: str, species_id: str, tier_id: str, level: int) -> Fighter:
        species = self._catalog.species(species_id)
        stat = lambda name: self._catalog.stat_value(species_id, level, tier_id, name)  # noqa: E731
        return Fighter(
            side=side, species_id=species_id, tier_id=tier_id, level=level,
            max_hp=stat("hp"), essence=stat("essence"), speed=stat("speed"),
            abilities=tuple(a for a in species.abilities if a.unlock_level <= level), passive=species.passive,
        )

    def start_state(self, setup: BattleSetup) -> BattleState:
        def fresh(fighter: Fighter) -> FighterState:
            kind = fighter.passive.kind
            buffs = tuple(Buff(f"passive:{kind}", stat, amount, None)
                          for stat, amount in self._passives.create(fighter.passive).start_buffs(fighter.essence))
            return FighterState(hp=fighter.max_hp, buffs=buffs)

        return BattleState(round=1, player=fresh(setup.player), wild=fresh(setup.wild))

    def stat(self, fighter: Fighter, fstate: FighterState, name: str) -> int:
        """Current ESSENCE or SPEED including temporary buffs."""
        return getattr(fighter, name) + sum(b.amount for b in fstate.buffs if b.stat == name)

    # -- legal actions -------------------------------------------------------------

    def legal_actions(self, setup: BattleSetup, state: BattleState, side: str, *, can_collect: bool) -> list[Action]:
        """Every action `side` may choose this round. `can_collect` says whether
        the collecting side owns an EMBLEM; a wild Spark may always CATCH (it
        only counters FLEE)."""
        fighter, fstate = setup.of(side), state.of(side)
        ready = dict(fstate.cooldowns)
        actions = [Action("attack", "ATTACK")]
        for ability in fighter.abilities:
            if state.round >= ready.get(ability.id, 0):
                actions.append(Action("ability", ability.category, ability.id, ability.percentage))
        actions.append(Action("flee", "FEAR"))
        if side == WILD or can_collect:
            actions.append(Action("catch", "INTERCEPT"))
        return actions

    def resolve_action(self, legal: list[Action], payload: dict[str, Any]) -> Action:
        """Match a client payload ({kind, ability_id?, emblem_tier?}) to a legal action."""
        kind, ability_id = payload.get("kind"), payload.get("ability_id")
        for action in legal:
            if action.kind == kind and action.ability_id == (ability_id if kind == "ability" else None):
                if kind != "catch":
                    return action
                tier = payload.get("emblem_tier")
                if not isinstance(tier, str):
                    raise ActionError("CATCH needs an emblem_tier")
                self._catalog.tier(tier)
                return replace(action, emblem_tier=tier)
        raise ActionError("that action is not available this round")

    # -- chances -------------------------------------------------------------------

    def capture_chance(self, emblem_tier: str, target: Fighter, target_state: FighterState) -> float:
        tier = self._catalog.tier(target.tier_id)
        resistance = (
            self._catalog.economy.base_capture_resistance * tier.capture_multiplier
            * (tier.hp_floor + (1 - tier.hp_floor) * target_state.hp / target.max_hp)
        )
        strength = self._catalog.tier(emblem_tier).emblem_strength
        return strength / (strength + resistance)

    # -- one round -----------------------------------------------------------------

    def resolve_round(
        self, setup: BattleSetup, state: BattleState, player_action: Action, wild_action: Action, rng: RandomSource
    ) -> RoundOutcome:
        rec = RecordingRandom(rng)
        sides = {s: _Side(s, setup.of(s), state.of(s), self._passives.create(setup.of(s).passive)) for s in SIDES}
        actions = {PLAYER: player_action, WILD: wild_action}
        events: list[dict[str, Any]] = []
        rnd = state.round

        for side, action in actions.items():  # cooldowns start when the action is revealed
            if action.kind == "ability":
                ability = self._ability(sides[side].fighter, action.ability_id)
                sides[side].cooldowns[ability.id] = rnd + sides[side].passive.cooldown(ability.cooldown) + 1
        for side in SIDES:  # SUPPORT first, so DEFENSE sees this round's ESSENCE buffs
            if actions[side].category == "SUPPORT":
                self._support(sides[side], self._ability(sides[side].fighter, actions[side].ability_id), events)
        for side in SIDES:
            if actions[side].category == "DEFENSE":
                self._defense(sides[side], self._ability(sides[side].fighter, actions[side].ability_id), events)

        catchers: dict[str, int | None] = {}
        for side in SIDES:  # CATCH reduces FLEE whatever the action order; settled before any escape roll
            if actions[side].kind == "flee":
                foe = sides[other(side)]
                catchers[side] = foe.stat("essence") if actions[other(side)].kind == "catch" else None
                if catchers[side] is not None:
                    events.append({"type": "catch_counters_flee", "side": other(side), "target": side})

        speed = {s: sides[s].stat("speed") for s in SIDES}
        chance_player_first = speed[PLAYER] / (speed[PLAYER] + speed[WILD])
        order = [PLAYER, WILD] if rec.next() < chance_player_first else [WILD, PLAYER]
        events.append({"type": "order", "first": order[0], "chance_player_first": round(chance_player_first, 4)})

        terminal: str | None = None
        emblem: str | None = None
        for side in order:
            if terminal:
                break
            action = actions[side]
            if action.category == "ATTACK":
                terminal = self._attack(sides, actions, side, events)
            elif action.kind == "catch":
                terminal, spent = self._catch(setup, sides, actions, side, rec, events)
                emblem = spent or emblem
            elif action.kind == "flee":
                chance = self._flee(sides[side], catchers[side])  # uses HP as it is when the attempt resolves
                succeeded = rec.next() < chance
                events.append({"type": "flee", "side": side, "chance": round(chance, 4), "success": succeeded})
                if succeeded:
                    terminal = "escaped" if side == PLAYER else "wild_escaped"

        revealed = RevealedRound(rnd, {s: (actions[s].key, actions[s].category) for s in SIDES}, tuple(events))
        if not terminal:
            for side_obj in sides.values():
                self._expire(side_obj)
        new_state = BattleState(
            round=rnd if terminal else rnd + 1,
            player=sides[PLAYER].freeze(), wild=sides[WILD].freeze(), history=state.history + (revealed,),
        )
        return RoundOutcome(new_state, tuple(events), terminal, emblem, tuple(rec.draws))

    # -- parts of a round ----------------------------------------------------------

    @staticmethod
    def _ability(fighter: Fighter, ability_id: str | None) -> AbilitySpec:
        for ability in fighter.abilities:
            if ability.id == ability_id:
                return ability
        raise ActionError(f"unknown ability {ability_id!r}")

    @staticmethod
    def _support(me: _Side, ability: AbilitySpec, events: list) -> None:
        amount = math.floor(me.fighter.essence * ability.percentage / 100 + _EPS)  # unbuffed ESSENCE
        duration = ability.duration + me.passive.support_extra_rounds()
        me.buffs = [b for b in me.buffs if b.source != ability.id]  # reuse refreshes, never stacks
        me.buffs.append(Buff(ability.id, ability.stat, amount, duration))
        events.append({"type": "support", "side": me.side, "ability": ability.id, "stat": ability.stat, "amount": amount})

    @staticmethod
    def _defense(me: _Side, ability: AbilitySpec, events: list) -> None:
        rating = me.stat("essence") * ability.percentage / 100 + me.passive.defense_rating_bonus(me.fighter.essence)
        attacks, rounds = me.passive.defense_limits()
        if me.defense:
            rating = max(rating, me.defense.rating)  # overlapping defenses keep the strongest rating
        me.defense = DefenseEffect(rating, attacks, rounds)  # refresh resets the limits, nothing is banked
        events.append({"type": "defense", "side": me.side, "ability": ability.id, "rating": round(rating, 2)})

    @staticmethod
    def _flee(me: _Side, catcher_essence: int | None) -> float:
        essence = me.stat("essence")
        chance = essence / (100 + essence) * me.hp / me.fighter.max_hp
        return chance * 100 / (100 + catcher_essence) if catcher_essence is not None else chance

    @staticmethod
    def _attack(sides: dict[str, _Side], actions: dict[str, Action], attacker: str, events: list) -> str | None:
        me, foe = sides[attacker], sides[other(attacker)]
        essence = me.stat("essence")
        raw = essence * actions[attacker].percentage / 100 + me.passive.attack_bonus(
            essence, me.hp, me.fighter.max_hp, actions[foe.side].category == "DEFENSE"
        )
        protected = bool(foe.defense and foe.defense.attacks_left > 0)
        if protected:
            damage = math.floor(raw * 100 / (100 + foe.defense.rating) + _EPS)
            foe.defense = replace(foe.defense, attacks_left=foe.defense.attacks_left - 1)
        else:
            damage = math.floor(raw + _EPS)
        damage = max(1, damage)
        foe.hp = max(0, foe.hp - damage)
        events.append({"type": "attack", "side": attacker, "damage": damage, "protected": protected, "target_hp": foe.hp})
        if foe.hp == 0:
            return "won" if foe.side == WILD else "knocked_out"
        return None

    def _catch(self, setup: BattleSetup, sides: dict[str, _Side], actions: dict[str, Action], catcher: str,
               rec: RecordingRandom, events: list) -> tuple[str | None, str | None]:
        foe = other(catcher)
        if actions[foe].kind == "flee":  # already counted against the escape; no collection, no EMBLEM
            return None, None
        if catcher == WILD:
            events.append({"type": "catch_ignored", "side": WILD})
            return None, None
        tier = actions[catcher].emblem_tier
        chance = self.capture_chance(tier, setup.of(foe), sides[foe].freeze())
        succeeded = rec.next() < chance
        events.append({"type": "capture_attempt", "side": catcher, "emblem": tier, "chance": round(chance, 4), "success": succeeded})
        return ("captured" if succeeded else None), tier

    @staticmethod
    def _expire(me: _Side) -> None:
        me.buffs = [replace(b, rounds_left=b.rounds_left - 1) if b.rounds_left is not None else b for b in me.buffs]
        me.buffs = [b for b in me.buffs if b.rounds_left is None or b.rounds_left > 0]
        if me.defense:
            left = replace(me.defense, rounds_left=me.defense.rounds_left - 1)
            me.defense = left if left.rounds_left > 0 and left.attacks_left > 0 else None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_engine.py -q`
Expected: 41 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/engine.py apps/mini_games/tests/sparks/test_engine.py
git commit -m "feat(mini_games): battle engine"
```

---

### Task 7: The action policy

**Files:**
- Create: `apps/mini_games/src/sparks/policy.py`
- Test: `apps/mini_games/tests/sparks/test_policy.py`

**Interfaces:**
- Consumes: `Catalog`, `PolicySpec`, the models.
- Produces: `Situation(danger, aggression, advantage)` (each 0 to 1); `PolicyContext(situation, enemy_hp_fraction, enemy_flee_share, collector, recent_keys, weights)`; `PolicyDecision(action, probabilities)`; `Mood(catalog)` with `Mood.pick(count, u) -> int` and `weights(instances, lead) -> dict[category, float]`; `ActionPolicy(policy_spec)` with `situation_value(category, ctx)`, `probabilities(actions, ctx) -> list[float]`, `choose(actions, ctx, u) -> PolicyDecision`.
- Rules: `weight(x) = situation(category) × (1 + gain × W_category) × potency(x) × repeat_factor^n`, normalised, with every legal action keeping a positive probability; `n` counts the immediately preceding rounds in which the Spark chose the same action; `potency` is the action's ability percentage over the category's mean among legal actions; the leading personality counts fully and the others at `off_mood_factor`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_policy.py`

```python
import random
from pathlib import Path

import pytest

from src.sparks.catalog import Catalog
from src.sparks.models import Action, PersonalityInstance
from src.sparks.policy import ActionPolicy, Mood, PolicyContext, Situation

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
policy = ActionPolicy(CATALOG.policy)
mood = Mood(CATALOG)

ATTACK = Action("attack", "ATTACK")
FLEE = Action("flee", "FEAR")
CATCH = Action("catch", "INTERCEPT")
DEFEND = Action("ability", "DEFENSE", "guard", 200)
BUFF = Action("ability", "SUPPORT", "rally", 50)
ACTIONS = [ATTACK, DEFEND, BUFF, FLEE, CATCH]


def ctx(danger=0.3, aggression=0.5, advantage=0.5, weights=None, recent=(), collector=False, enemy_hp=1.0, flee_share=0.1):
    return PolicyContext(Situation(danger, aggression, advantage), enemy_hp, flee_share, collector, tuple(recent), weights or {})


def probs(actions=ACTIONS, **kwargs):
    return dict(zip([a.key for a in actions], policy.probabilities(actions, ctx(**kwargs))))


# -- mood ----------------------------------------------------------------------------

AGGRESSIVE3 = PersonalityInstance("p1", "AGGRESSIVE", 3)
CAUTIOUS2 = PersonalityInstance("p2", "CAUTIOUS", 2)


def test_mood_draw_is_uniform_over_instances():
    assert [Mood.pick(3, u) for u in (0.0, 0.33, 0.34, 0.66, 0.67, 0.999)] == [0, 0, 1, 1, 2, 2]
    assert Mood.pick(1, 0.7) == 0


def test_mood_weights_follow_the_spec_example():
    assert mood.weights([AGGRESSIVE3, CAUTIOUS2], 0) == {"ATTACK": 3, "DEFENSE": 1, "SUPPORT": 0, "FEAR": 1, "INTERCEPT": 0}
    assert mood.weights([AGGRESSIVE3, CAUTIOUS2], 1) == {"ATTACK": 1.5, "DEFENSE": 2, "SUPPORT": 0, "FEAR": 2, "INTERCEPT": 0}


def test_a_single_personality_is_always_the_mood():
    assert mood.weights([AGGRESSIVE3], 0)["ATTACK"] == 3


def test_repeated_types_add():
    three = [PersonalityInstance(f"p{i}", "AGGRESSIVE", 3) for i in range(3)]
    assert mood.weights(three, 0)["ATTACK"] == 3 + 1.5 + 1.5


# -- probabilities -------------------------------------------------------------------

def test_probabilities_sum_to_one_and_cover_every_action():
    p = probs()
    assert sum(p.values()) == pytest.approx(1.0) and set(p) == {"attack", "ability:guard", "ability:rally", "flee", "catch"}


def test_every_legal_action_stays_possible():
    assert all(value > 0 for value in probs(weights={"ATTACK": 9}, danger=0.0, advantage=1.0).values())


def test_personality_weight_raises_its_category_without_forcing_it():
    base, aggressive = probs(), probs(weights={"ATTACK": 3})
    assert aggressive["attack"] > base["attack"] and aggressive["attack"] < 0.9


def test_low_hp_still_raises_defense_and_flee_for_an_aggressive_spark():
    safe = probs(weights={"ATTACK": 3}, danger=0.0, advantage=0.5)
    critical = probs(weights={"ATTACK": 3}, danger=1.0, advantage=0.1)
    assert critical["ability:guard"] > safe["ability:guard"] and critical["flee"] > safe["flee"]
    assert critical["attack"] < safe["attack"]


def test_each_repeat_halves_an_actions_weight_until_another_action_breaks_the_run():
    ratio = lambda p: p["attack"] / p["ability:guard"]  # noqa: E731  (the guard weight is never repeated here)
    base = ratio(probs())
    assert ratio(probs(recent=["attack"])) == pytest.approx(base * 0.5)
    assert ratio(probs(recent=["attack", "attack"])) == pytest.approx(base * 0.25)
    assert ratio(probs(recent=["attack", "attack", "flee"])) == pytest.approx(base)  # the run ended at flee


def test_stronger_abilities_are_preferred_within_a_category():
    weak, strong = Action("ability", "ATTACK", "weak", 100), Action("ability", "ATTACK", "strong", 200)
    p = probs([weak, strong, FLEE])
    assert p["ability:strong"] == pytest.approx(2 * p["ability:weak"])


def test_a_lone_action_in_its_category_has_unit_potency():
    p1 = probs([ATTACK, FLEE])
    assert p1["attack"] > p1["flee"]


def test_collector_catch_grows_as_the_enemy_weakens():
    healthy = probs(collector=True, enemy_hp=1.0)["catch"]
    weak = probs(collector=True, enemy_hp=0.1)["catch"]
    assert weak > healthy


def test_wild_catch_follows_the_enemys_flee_share():
    low = probs(collector=False, flee_share=0.1)["catch"]
    high = probs(collector=False, flee_share=0.9)["catch"]
    assert high > low


def test_no_actions_is_an_error():
    with pytest.raises(ValueError):
        policy.probabilities([], ctx())


# -- choosing ------------------------------------------------------------------------

def test_choose_walks_the_cumulative_distribution():
    p = policy.probabilities(ACTIONS, ctx())
    assert policy.choose(ACTIONS, ctx(), 0.0).action == ATTACK
    assert policy.choose(ACTIONS, ctx(), p[0] + 1e-6).action == DEFEND
    assert policy.choose(ACTIONS, ctx(), 0.999999).action == CATCH
    assert policy.choose(ACTIONS, ctx(), 0.0).probabilities == tuple(p)


def sample(weights, n=4000, **kwargs):
    rng = random.Random(7)
    counts: dict[str, int] = {}
    for _ in range(n):
        key = policy.choose(ACTIONS, ctx(weights=weights, **kwargs), rng.random()).action.key
        counts[key] = counts.get(key, 0) + 1
    return {k: v / n for k, v in counts.items()}


def test_aggressive_attacks_more_and_coward_flees_more_over_many_draws():
    aggressive = sample(mood.weights([AGGRESSIVE3], 0))
    coward = sample(mood.weights([PersonalityInstance("c", "COWARD", 3)], 0))
    neutral = sample({})
    assert aggressive["attack"] > neutral["attack"] > coward["attack"]
    assert coward["flee"] > neutral["flee"] > aggressive["flee"]


def test_no_personality_picks_one_action_every_time():
    freq = sample(mood.weights([AGGRESSIVE3], 0), danger=0.2, advantage=0.8)
    assert max(freq.values()) < 0.8 and len(freq) == len(ACTIONS)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_policy.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.policy'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/policy.py`

```python
"""The action policy: how a Spark picks its action when it plays on its own.

Pure and synchronous. Situation values (from Laya or heuristics), the round's
personality weights, a potency term and a repeat penalty become action
probabilities; the engine's seeded random draw picks one. A fixed personality
therefore biases behaviour without making it predictable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.sparks.catalog import Catalog, PolicySpec
from src.sparks.models import CATEGORIES, Action, PersonalityInstance


@dataclass(frozen=True)
class Situation:
    """Each value is 0 to 1."""

    danger: float
    aggression: float  # how aggressively the enemy has acted
    advantage: float  # does this Spark have the upper hand


@dataclass(frozen=True)
class PolicyContext:
    situation: Situation
    enemy_hp_fraction: float
    enemy_flee_share: float  # share of revealed rounds the enemy chose FLEE
    collector: bool  # True for the player's Spark: CATCH can collect
    recent_keys: tuple[str, ...]  # this Spark's own previous action keys, oldest first
    weights: Mapping[str, float]  # round personality weights per category


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    probabilities: tuple[float, ...]  # same order as the actions passed in


class Mood:
    """Which equipped personality leads this round, and the resulting weights."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._off = catalog.policy.off_mood_factor

    @staticmethod
    def pick(count: int, u: float) -> int:
        """Uniform index of the leading instance for one draw u in [0, 1)."""
        return min(int(u * count), count - 1)

    def weights(self, instances: Sequence[PersonalityInstance], lead: int) -> dict[str, float]:
        """The lead instance counts fully, the others at the off-mood factor;
        weights add per category. A personality gives its tier as the weight for
        each of its categories."""
        totals = {category: 0.0 for category in CATEGORIES}
        for index, instance in enumerate(instances):
            factor = 1.0 if index == lead else self._off
            for category in self._catalog.personalities[instance.type_id].categories:
                totals[category] += instance.tier * factor
        return totals


class ActionPolicy:
    def __init__(self, spec: PolicySpec) -> None:
        self._spec = spec

    def situation_value(self, category: str, ctx: PolicyContext) -> float:
        s, c = ctx.situation, self._spec.coefficients[category]
        if category == "ATTACK":
            value = c["base"] + c["advantage"] * s.advantage + c["safety"] * (1 - s.danger)
        elif category == "DEFENSE":
            value = c["base"] + c["danger"] * s.danger + c["aggression"] * s.aggression
        elif category == "SUPPORT":
            value = c["base"] + c["safety"] * (1 - s.danger) + c["passivity"] * (1 - s.aggression)
        elif category == "FEAR":
            value = c["base"] + c["escape_pressure"] * s.danger * (1 - s.advantage)
        elif ctx.collector:
            value = c["collector_base"] + c["collector_weakness"] * (1 - ctx.enemy_hp_fraction) * (1 - s.danger)
        else:
            value = c["wild_base"] + c["wild_flee_share"] * ctx.enemy_flee_share
        return max(value, self._spec.floor)

    def probabilities(self, actions: Sequence[Action], ctx: PolicyContext) -> list[float]:
        if not actions:
            raise ValueError("no legal actions to choose from")
        mean_percentage: dict[str, float] = {}
        for category in CATEGORIES:
            members = [a.percentage for a in actions if a.category == category]
            if members:
                mean_percentage[category] = sum(members) / len(members)
        weights = []
        for action in actions:
            potency = 1.0
            if action.kind in ("attack", "ability") and mean_percentage[action.category] > 0:
                potency = action.percentage / mean_percentage[action.category]
            repeats = 0
            for key in reversed(ctx.recent_keys):
                if key != action.key:
                    break
                repeats += 1
            weights.append(
                self.situation_value(action.category, ctx)
                * (1 + self._spec.gain * ctx.weights.get(action.category, 0.0))
                * potency
                * self._spec.repeat_factor ** repeats
            )
        total = sum(weights)
        return [w / total for w in weights]

    def choose(self, actions: Sequence[Action], ctx: PolicyContext, u: float) -> PolicyDecision:
        probabilities = self.probabilities(actions, ctx)
        cumulative = 0.0
        for action, probability in zip(actions, probabilities):
            cumulative += probability
            if u < cumulative:
                return PolicyDecision(action, tuple(probabilities))
        return PolicyDecision(actions[-1], tuple(probabilities))  # u rounding past the last bucket
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_policy.py -q`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/policy.py apps/mini_games/tests/sparks/test_policy.py
git commit -m "feat(mini_games): action policy with mood and repeat penalty"
```

---

### Task 8: Situation reads

**Files:**
- Create: `apps/mini_games/src/sparks/situation.py`
- Test: `apps/mini_games/tests/sparks/test_situation.py`

**Interfaces:**
- Consumes: `LayaClient`, `score_question`, `noul_question` (Task 3); `BattleEngine` (Task 6); `Situation` (Task 7).
- Produces: `SituationView(round, own_hp_fraction, enemy_hp_fraction, own_essence, enemy_essence, own_speed, enemy_speed, own_history, enemy_history)` with `to_text()`; `SituationViewBuilder(engine).build(setup, state, side)`; `PartialSituation(danger, aggression, advantage)` (any may be `None`); protocols `SituationReader.read(view) -> Situation` and `PartialSituationReader.read_partial(view) -> PartialSituation`; `HeuristicSituationReader(default_aggression=0.5)` (`compute`, `read`); `LayaPartialSituationReader(client)`; `FallbackSituationReader(primary, heuristic)`.
- Heuristics: `danger = 1 − own HP fraction`; `aggression` = the enemy's ATTACK share of revealed rounds (default before round 2); `advantage = 0.5 + 0.5 × (own HP fraction − enemy HP fraction)`. Only public information enters a question; round 1 never asks about aggression.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_situation.py`

```python
import asyncio
from pathlib import Path

import pytest

from src.laya_client import LayaClient
from src.sparks.catalog import Catalog
from src.sparks.engine import BattleEngine
from src.sparks.models import PLAYER, WILD, Action
from src.sparks.situation import (
    FallbackSituationReader,
    HeuristicSituationReader,
    LayaPartialSituationReader,
    SituationView,
    SituationViewBuilder,
)
from tests.fake_laya import FakeEngine
from tests.sparks.helpers import ScriptedRandom, fighter, setup

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
engine = BattleEngine(CATALOG)
heuristic = HeuristicSituationReader()


def view(**changes) -> SituationView:
    base = dict(round=3, own_hp_fraction=0.5, enemy_hp_fraction=0.8, own_essence=52, enemy_essence=40,
                own_speed=30, enemy_speed=25, own_history=("ATTACK", "FEAR"), enemy_history=("ATTACK", "ATTACK", "DEFENSE"))
    base.update(changes)
    return SituationView(**base)


def run(coro):
    return asyncio.run(coro)


# -- view ----------------------------------------------------------------------------

def test_text_is_compact_and_public():
    text = view().to_text()
    assert text == ("Round 3. Own HP 50%, enemy HP 80%. ESSENCE own 52, enemy 40. SPEED own 30, enemy 25. "
                    "Enemy recent actions: ATTACK, ATTACK, DEFENSE. Own recent actions: ATTACK, FEAR.")


def test_text_keeps_only_recent_history_and_handles_none():
    long = view(enemy_history=tuple(["ATTACK"] * 20), own_history=())
    assert long.to_text().count("ATTACK") == 6 and "Own recent actions: none." in long.to_text()


def test_builder_reads_public_state_from_each_side():
    s = setup(fighter(PLAYER, hp=100, essence=40, speed=20), fighter(WILD, hp=200, essence=30, speed=10))
    state = engine.start_state(s)
    out = engine.resolve_round(s, state, Action("attack", "ATTACK"), Action("flee", "FEAR"), ScriptedRandom(0.1, 0.99))
    mine = SituationViewBuilder(engine).build(s, out.state, PLAYER)
    theirs = SituationViewBuilder(engine).build(s, out.state, WILD)
    assert (mine.own_hp_fraction, mine.enemy_hp_fraction) == (1.0, 0.8)
    assert mine.own_history == ("ATTACK",) and mine.enemy_history == ("FEAR",)
    assert theirs.own_history == ("FEAR",) and theirs.enemy_essence == 40


# -- heuristic -----------------------------------------------------------------------

def test_heuristic_values():
    s = heuristic.compute(view())
    assert s.danger == pytest.approx(0.5)
    assert s.aggression == pytest.approx(2 / 3)
    assert s.advantage == pytest.approx(0.5 + 0.5 * (0.5 - 0.8))


def test_heuristic_defaults_before_any_history_and_clamps():
    s = heuristic.compute(view(round=1, enemy_history=(), own_hp_fraction=1.0, enemy_hp_fraction=0.0))
    assert (s.danger, s.aggression, s.advantage) == (0.0, 0.5, 1.0)
    assert heuristic.compute(view(own_hp_fraction=0.0, enemy_hp_fraction=1.0)).advantage == 0.0


def test_heuristic_reader_is_a_reader():
    assert run(heuristic.read(view())) == heuristic.compute(view())


# -- laya ----------------------------------------------------------------------------

def laya_reader(**kwargs):
    return LayaPartialSituationReader(LayaClient(FakeEngine(**kwargs)))


def test_laya_values_are_normalised():
    p = run(laya_reader(scores={"danger": 3.0, "aggression": 1.0}, noul={"advantage": 0.25}).read_partial(view()))
    assert (p.danger, p.aggression, p.advantage) == (1.0, 0.5, 0.25)


def test_round_one_does_not_ask_about_enemy_aggression():
    engine_ = FakeEngine()
    p = run(LayaPartialSituationReader(LayaClient(engine_)).read_partial(view(round=1, enemy_history=())))
    assert set(engine_.calls[0][1]) == {"danger", "advantage"} and p.aggression is None


def test_question_text_is_the_public_view_only():
    engine_ = FakeEngine()
    run(LayaPartialSituationReader(LayaClient(engine_)).read_partial(view()))
    assert engine_.calls[0][0] == view().to_text()


def test_uncertain_answers_are_dropped():
    assert run(laya_reader(confidence=0.4).read_partial(view())) == run(laya_reader(fail=True).read_partial(view()))


def test_laya_failure_returns_nothing():
    p = run(laya_reader(fail=True).read_partial(view()))
    assert (p.danger, p.aggression, p.advantage) == (None, None, None)


# -- fallback ------------------------------------------------------------------------

def test_fallback_uses_laya_where_it_answered():
    reader = FallbackSituationReader(laya_reader(scores={"danger": 0.0, "aggression": 2.0}, noul={"advantage": 1.0}), heuristic)
    s = run(reader.read(view()))
    assert (s.danger, s.aggression, s.advantage) == (0.0, 1.0, 1.0)


def test_fallback_fills_each_missing_value_from_the_heuristic():
    class OneAnswer:
        async def read_partial(self, v):
            from src.sparks.situation import PartialSituation

            return PartialSituation(danger=0.9)

    s = run(FallbackSituationReader(OneAnswer(), heuristic).read(view()))
    base = heuristic.compute(view())
    assert (s.danger, s.aggression, s.advantage) == (0.9, base.aggression, base.advantage)


def test_without_laya_everything_is_heuristic():
    reader = FallbackSituationReader(laya_reader(fail=True), heuristic)
    assert run(reader.read(view())) == heuristic.compute(view())
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_situation.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.situation'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/situation.py`

```python
"""Situation reads: how much danger a Spark is in, how aggressive its enemy has
been and whether it has the upper hand.

Laya answers these as typed questions about a short public-state text. An
engine heuristic computes the same three values, and a read that is uncertain,
invalid, late or missing is replaced by its heuristic value one question at a
time, so the game never depends on the model. Only public information goes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.laya_client import LayaClient, LayaError, noul_question, score_question
from src.sparks.engine import BattleEngine
from src.sparks.models import BattleSetup, BattleState, other
from src.sparks.policy import Situation

DANGER_LEVELS = ["safe", "pressured", "endangered", "critical"]
AGGRESSION_LEVELS = ["passive", "mixed", "aggressive"]
HISTORY_ROUNDS = 6  # keeps the Laya text well inside the 512-token window


@dataclass(frozen=True)
class SituationView:
    """Public state from one Spark's side of the battle."""

    round: int
    own_hp_fraction: float
    enemy_hp_fraction: float
    own_essence: int
    enemy_essence: int
    own_speed: int
    enemy_speed: int
    own_history: tuple[str, ...]  # categories of its own revealed actions, oldest first
    enemy_history: tuple[str, ...]

    def to_text(self) -> str:
        recent = lambda h: ", ".join(h[-HISTORY_ROUNDS:]) or "none"  # noqa: E731
        return (
            f"Round {self.round}. Own HP {self.own_hp_fraction:.0%}, enemy HP {self.enemy_hp_fraction:.0%}. "
            f"ESSENCE own {self.own_essence}, enemy {self.enemy_essence}. "
            f"SPEED own {self.own_speed}, enemy {self.enemy_speed}. "
            f"Enemy recent actions: {recent(self.enemy_history)}. Own recent actions: {recent(self.own_history)}."
        )


@dataclass(frozen=True)
class PartialSituation:
    """Any value may be missing; None means "use the heuristic"."""

    danger: float | None = None
    aggression: float | None = None
    advantage: float | None = None


class SituationViewBuilder:
    def __init__(self, engine: BattleEngine) -> None:
        self._engine = engine

    def build(self, setup: BattleSetup, state: BattleState, side: str) -> SituationView:
        foe = other(side)
        own, enemy = setup.of(side), setup.of(foe)
        own_state, enemy_state = state.of(side), state.of(foe)
        return SituationView(
            round=state.round,
            own_hp_fraction=own_state.hp / own.max_hp,
            enemy_hp_fraction=enemy_state.hp / enemy.max_hp,
            own_essence=self._engine.stat(own, own_state, "essence"),
            enemy_essence=self._engine.stat(enemy, enemy_state, "essence"),
            own_speed=self._engine.stat(own, own_state, "speed"),
            enemy_speed=self._engine.stat(enemy, enemy_state, "speed"),
            own_history=tuple(r.actions[side][1] for r in state.history),
            enemy_history=tuple(r.actions[foe][1] for r in state.history),
        )


class SituationReader(Protocol):
    async def read(self, view: SituationView) -> Situation: ...


class PartialSituationReader(Protocol):
    async def read_partial(self, view: SituationView) -> PartialSituation: ...


class HeuristicSituationReader:
    """The engine's own estimate. Needs no model."""

    def __init__(self, default_aggression: float = 0.5) -> None:
        self._default_aggression = default_aggression

    def compute(self, view: SituationView) -> Situation:
        history = view.enemy_history
        aggression = history.count("ATTACK") / len(history) if history else self._default_aggression
        advantage = 0.5 + 0.5 * (view.own_hp_fraction - view.enemy_hp_fraction)
        return Situation(
            danger=min(1.0, max(0.0, 1 - view.own_hp_fraction)),
            aggression=aggression,
            advantage=min(1.0, max(0.0, advantage)),
        )

    async def read(self, view: SituationView) -> Situation:
        return self.compute(view)


class LayaPartialSituationReader:
    """Asks Laya the three questions in one call. A failed call, or an uncertain
    answer, leaves that value as None."""

    def __init__(self, client: LayaClient) -> None:
        self._client = client

    async def read_partial(self, view: SituationView) -> PartialSituation:
        questions = {
            "danger": score_question("How much danger is this fighter in?", DANGER_LEVELS),
            "advantage": noul_question(
                "Does this fighter have the upper hand?",
                "The fighter is at a disadvantage.", "The fighter has the upper hand.",
            ),
        }
        if view.enemy_history:  # nothing to judge in round 1
            questions["aggression"] = score_question("How aggressively has the enemy acted?", AGGRESSION_LEVELS)
        try:
            answers = await self._client.ask(view.to_text(), questions)
        except LayaError:
            return PartialSituation()

        def value(qid: str, scale: float) -> float | None:
            answer = answers.get(qid)
            return None if answer is None or answer.uncertain else answer.value / scale

        return PartialSituation(
            danger=value("danger", len(DANGER_LEVELS) - 1),
            aggression=value("aggression", len(AGGRESSION_LEVELS) - 1),
            advantage=value("advantage", 1.0),
        )


class FallbackSituationReader:
    """Primary read, with the heuristic filling in each value the primary lacks."""

    def __init__(self, primary: PartialSituationReader, heuristic: HeuristicSituationReader) -> None:
        self._primary, self._heuristic = primary, heuristic

    async def read(self, view: SituationView) -> Situation:
        fallback = self._heuristic.compute(view)
        partial = await self._primary.read_partial(view)
        return Situation(
            danger=fallback.danger if partial.danger is None else partial.danger,
            aggression=fallback.aggression if partial.aggression is None else partial.aggression,
            advantage=fallback.advantage if partial.advantage is None else partial.advantage,
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_situation.py -q`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/situation.py apps/mini_games/tests/sparks/test_situation.py
git commit -m "feat(mini_games): situation readers with heuristic fallback"
```

---

### Task 9: Errors, records and the SQLite repository

**Files:**
- Create: `apps/mini_games/src/sparks/errors.py`, `src/sparks/records.py`, `src/sparks/repository.py`
- Test: `apps/mini_games/tests/sparks/test_repository.py`

**Interfaces:**
- Produces (`errors`): `SparkError` with `status_code`, and `InvalidRequest` (400), `NotFound` (404), `Conflict` (409) with subclasses `AlreadyInitialized`, `ActiveBattleExists`, `StaleBattle`, `WrongPhase`, `BattleFinished`, `DeadlinePassed`, `EncounterCooldown(retry_after)`, `SparkFainted`, `InsufficientFunds`, `InsufficientEmblems`, `IdempotencyConflict`, `NothingToSell`.
- Produces (`records`): frozen `PlayerRecord`, `SparkRecord(owner, species_id, copies, level, xp, faint_until=None)`, `PersonalityRecord` (with `.instance()`), `PresetRecord`, `EncounterRecord`, `BattleRecord`, `IdempotencyRecord`.
- Produces (`repository`): protocols `SparkTransaction` (every read and write a service needs) and `SparkRepository.transaction()` (async context manager: commit on success, roll back on any exception); `SqliteSparkRepository(path)` (`":memory:"` works) with `close()`. One transaction at a time; blocking `sqlite3` calls run in a worker thread; schema version 1 in `PRAGMA user_version`; unique partial index allows one `active` battle per owner; `save_battle(record, expected_revision)` raises `StaleBattle` when the revision moved; EMBLEM and Insignia counts cannot go negative.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_repository.py`

```python
import asyncio
import sqlite3
from dataclasses import replace

import pytest

from src.sparks.errors import ActiveBattleExists, StaleBattle
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord, PersonalityRecord, PresetRecord, SparkRecord
from src.sparks.repository import SqliteSparkRepository
from tests.sparks.helpers import battle_record


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "data" / "sparks.sqlite3"


def test_players_and_wallet(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            assert await tx.get_player("ann") is None
            await tx.create_player("ann", 5.0)
            await tx.add_insignia("ann", 30)
            await tx.set_last_roll("ann", 9.0)
            player = await tx.get_player("ann")
        assert (player.insignia, player.last_roll_at, player.created_at) == (30, 9.0, 5.0)
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.add_insignia("ann", -31)
        await repo.close()

    run(scenario())


def test_emblems_accumulate_and_cannot_go_negative(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.add_emblems("ann", "normal", 5)
            await tx.add_emblems("ann", "normal", -2)
            await tx.add_emblems("ann", "rare", 1)
            await tx.add_emblems("ann", "rare", -1)
            counts = await tx.emblem_counts("ann")
        assert counts == {"normal": 3}
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.add_emblems("ann", "normal", -4)
        await repo.close()

    run(scenario())


def test_sparks_upsert_and_list(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.put_spark(SparkRecord("ann", "guardian", 0, 1, 0))
            await tx.put_spark(SparkRecord("ann", "guardian", 3, 4, 50, faint_until=99.0))
            await tx.put_spark(SparkRecord("bob", "guardian", 0, 1, 0))
            mine = await tx.list_sparks("ann")
            one = await tx.get_spark("ann", "guardian")
            missing = await tx.get_spark("ann", "scout")
        assert mine == [one] and one == SparkRecord("ann", "guardian", 3, 4, 50, 99.0) and missing is None
        await repo.close()

    run(scenario())


def test_personalities_are_scoped_and_paginated(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            for i in range(5):
                await tx.add_personality(PersonalityRecord(f"p{i}", "ann", "guardian", "AGGRESSIVE", 1, float(i)))
            await tx.add_personality(PersonalityRecord("other", "ann", "scout", "COWARD", 2, 9.0))
            await tx.add_personality(PersonalityRecord("bobs", "bob", "guardian", "COWARD", 2, 9.0))
            first = await tx.list_personalities("ann", "guardian", 2, 0)
            second = await tx.list_personalities("ann", "guardian", 2, first[-1].seq)
            picked = await tx.get_personalities("ann", "guardian", ["p1", "other", "bobs", "p9"])
            nothing = await tx.get_personalities("ann", "guardian", [])
        assert [p.id for p in first] == ["p0", "p1"] and [p.id for p in second] == ["p2", "p3"]
        assert [p.id for p in picked] == ["p1"] and nothing == []
        assert first[0].instance() == PersonalityInstance("p0", "AGGRESSIVE", 1)
        await repo.close()

    run(scenario())


def test_presets_hold_five_slots(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.put_preset(PresetRecord("ann", "guardian", 1, ("a", "b")))
            await tx.put_preset(PresetRecord("ann", "guardian", 1, ("c",)))
            await tx.put_preset(PresetRecord("ann", "guardian", 2, ()))
            one = await tx.get_preset("ann", "guardian", 1)
            every = await tx.list_presets("ann", "guardian")
            nothing = await tx.get_preset("ann", "guardian", 3)
        assert one.instance_ids == ("c",) and [p.slot for p in every] == [1, 2] and nothing is None
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.put_preset(PresetRecord("ann", "guardian", 6, ()))
        await repo.close()

    run(scenario())


def test_encounters_are_owner_safe_and_one_pending_at_a_time_is_read(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        wild = (PersonalityInstance("w1", "COWARD", 2),)
        async with repo.transaction() as tx:
            await tx.add_encounter(EncounterRecord("e1", "ann", "scout", "rare", 7, "pending", wild, 1.0))
            await tx.add_encounter(EncounterRecord("e2", "ann", "scout", "normal", 3, "pending", wild, 2.0))
            newest = await tx.pending_encounter("ann")
            await tx.set_encounter_status("e2", "declined")
            after = await tx.pending_encounter("ann")
            mine = await tx.get_encounter("ann", "e1")
            foreign = await tx.get_encounter("bob", "e1")
        assert newest.id == "e2" and after.id == "e1" and mine.wild_personalities == wild and foreign is None
        await repo.close()

    run(scenario())


def test_battles_round_trip_and_enforce_one_active_per_owner(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        record = replace(battle_record(), pending={"wild_action": {"kind": "flee"}}, emblem_limit="rare")
        async with repo.transaction() as tx:
            await tx.add_battle(record)
            loaded = await tx.get_battle("ann", "b1")
            active = await tx.active_battle("ann")
            foreign = await tx.get_battle("bob", "b1")
        assert loaded == record and active == record and foreign is None
        with pytest.raises(ActiveBattleExists):
            async with repo.transaction() as tx:
                await tx.add_battle(battle_record(battle_id="b2", encounter_id="e2"))
        async with repo.transaction() as tx:
            await tx.save_battle(replace(record, status="terminal", phase="terminal", revision=2, result={"kind": "won"}), 1)
            await tx.add_battle(battle_record(battle_id="b3", encounter_id="e3"))  # the finished one no longer blocks
            assert (await tx.get_battle("ann", "b1")).result == {"kind": "won"}
            assert (await tx.active_battle("ann")).id == "b3"
        await repo.close()

    run(scenario())


def test_saving_with_a_stale_revision_is_rejected(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        record = battle_record()
        async with repo.transaction() as tx:
            await tx.add_battle(record)
            await tx.save_battle(replace(record, revision=2), 1)
        with pytest.raises(StaleBattle):
            async with repo.transaction() as tx:
                await tx.save_battle(replace(record, revision=2, rng_counter=9), 1)
        await repo.close()

    run(scenario())


def test_rounds_are_stored_and_replaced(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.add_round("b1", 1, {"mood": 0})
            await tx.add_round("b1", 1, {"mood": 1})
            rows = await tx._run("SELECT record FROM rounds WHERE battle_id = 'b1'", (), "all")
        assert [r["record"] for r in rows] == ['{"mood":1}']
        await repo.close()

    run(scenario())


def test_idempotency_records_are_unique_per_owner_and_key(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.put_idempotent("ann", "k1", "hash", {"ok": True}, 1.0)
            await tx.put_idempotent("bob", "k1", "other", {"ok": False}, 1.0)
            ann = await tx.get_idempotent("ann", "k1")
            missing = await tx.get_idempotent("ann", "k2")
        assert (ann.request_hash, ann.response) == ("hash", {"ok": True}) and missing is None
        with pytest.raises(sqlite3.IntegrityError):
            async with repo.transaction() as tx:
                await tx.put_idempotent("ann", "k1", "hash", {}, 2.0)
        await repo.close()

    run(scenario())


def test_a_failed_transaction_rolls_back_everything(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        with pytest.raises(RuntimeError):
            async with repo.transaction() as tx:
                await tx.create_player("ann", 1.0)
                await tx.add_emblems("ann", "normal", 5)
                raise RuntimeError("boom")
        async with repo.transaction() as tx:
            assert await tx.get_player("ann") is None and await tx.emblem_counts("ann") == {}
        await repo.close()

    run(scenario())


def test_data_survives_a_restart(db_path):
    async def first():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)
            await tx.add_battle(battle_record())
        await repo.close()

    async def second():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            return await tx.get_player("ann"), await tx.active_battle("ann")

    run(first())
    player, battle = run(second())
    assert player.owner == "ann" and battle.id == "b1"


def test_transactions_run_one_at_a_time(db_path):
    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)

        async def bump():
            async with repo.transaction() as tx:
                before = (await tx.get_player("ann")).insignia
                await asyncio.sleep(0.01)
                await tx.add_insignia("ann", 1)
                return before

        seen = await asyncio.gather(*(bump() for _ in range(5)))
        async with repo.transaction() as tx:
            total = (await tx.get_player("ann")).insignia
        await repo.close()
        return sorted(seen), total

    seen, total = run(scenario())
    assert seen == [0, 1, 2, 3, 4] and total == 5


def test_unsupported_schema_version_is_refused(db_path):
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    async def scenario():
        repo = SqliteSparkRepository(db_path)
        async with repo.transaction():
            pass

    with pytest.raises(RuntimeError, match="schema version 99"):
        run(scenario())
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_repository.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.repository'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/errors.py`

```python
"""Errors a caller can fix. Each carries the HTTP status the API maps it to:
400 for bad input, 404 for a missing or foreign record, 409 for a state
conflict (wrong phase, stale revision, not enough money, ...)."""

from __future__ import annotations


class SparkError(Exception):
    status_code = 400


class InvalidRequest(SparkError):
    status_code = 400


class NotFound(SparkError):
    status_code = 404


class Conflict(SparkError):
    status_code = 409


class AlreadyInitialized(Conflict):
    pass


class ActiveBattleExists(Conflict):
    pass


class StaleBattle(Conflict):
    """The caller's round or revision no longer matches the battle."""


class WrongPhase(Conflict):
    pass


class BattleFinished(Conflict):
    pass


class DeadlinePassed(Conflict):
    pass


class EncounterCooldown(Conflict):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"a new encounter can be rolled in {retry_after:.0f} seconds")
        self.retry_after = retry_after


class SparkFainted(Conflict):
    pass


class InsufficientFunds(Conflict):
    pass


class InsufficientEmblems(Conflict):
    pass


class IdempotencyConflict(Conflict):
    """The same Idempotency-Key was reused with a different request."""


class NothingToSell(Conflict):
    pass
```

`apps/mini_games/src/sparks/records.py`

```python
"""Rows as immutable values, so services never touch SQL or JSON text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.sparks.models import BattleSetup, BattleState, PersonalityInstance


@dataclass(frozen=True)
class PlayerRecord:
    owner: str
    insignia: int
    last_roll_at: float | None
    created_at: float


@dataclass(frozen=True)
class SparkRecord:
    owner: str
    species_id: str
    copies: int
    level: int
    xp: int
    faint_until: float | None = None


@dataclass(frozen=True)
class PersonalityRecord:
    id: str
    owner: str
    species_id: str
    type_id: str
    tier: int
    created_at: float
    seq: int = 0  # assigned by the database

    def instance(self) -> PersonalityInstance:
        return PersonalityInstance(self.id, self.type_id, self.tier)


@dataclass(frozen=True)
class PresetRecord:
    owner: str
    species_id: str
    slot: int
    instance_ids: tuple[str, ...]


@dataclass(frozen=True)
class EncounterRecord:
    id: str
    owner: str
    species_id: str
    tier_id: str
    level: int
    status: str  # pending, declined, started or expired
    wild_personalities: tuple[PersonalityInstance, ...]  # hidden until a capture
    created_at: float


@dataclass(frozen=True)
class BattleRecord:
    id: str
    owner: str
    encounter_id: str
    status: str  # active or terminal
    phase: str  # choosing, awaiting_emblem or terminal
    mode: str  # manual or autonomous
    revision: int
    setup: BattleSetup
    state: BattleState
    player_personalities: tuple[PersonalityInstance, ...]  # frozen from the preset at start
    wild_personalities: tuple[PersonalityInstance, ...]
    emblem_limit: str | None
    rng_seed: int
    rng_counter: int
    created_at: float
    updated_at: float
    pending: dict[str, Any] | None = None  # private: wild action and EMBLEM prompt while awaiting_emblem
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class IdempotencyRecord:
    request_hash: str
    response: dict[str, Any] = field(default_factory=dict)
```

`apps/mini_games/src/sparks/repository.py`

```python
"""Durable storage behind an async interface.

`SparkRepository.transaction()` yields a `SparkTransaction`; everything done
inside commits together or not at all. The SQLite implementation uses the
standard-library driver on one shared connection: every call runs in a worker
thread, and a lock admits one transaction at a time, so the event loop never
blocks and a half-finished battle result can never be saved.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncContextManager, AsyncIterator, Protocol

from src.sparks.errors import ActiveBattleExists, StaleBattle
from src.sparks.models import BattleSetup, BattleState, PersonalityInstance
from src.sparks.records import (
    BattleRecord,
    EncounterRecord,
    IdempotencyRecord,
    PersonalityRecord,
    PlayerRecord,
    PresetRecord,
    SparkRecord,
)

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE players (
    owner TEXT PRIMARY KEY, insignia INTEGER NOT NULL CHECK (insignia >= 0),
    last_roll_at REAL, created_at REAL NOT NULL);
CREATE TABLE emblems (
    owner TEXT NOT NULL, tier_id TEXT NOT NULL, count INTEGER NOT NULL CHECK (count >= 0),
    PRIMARY KEY (owner, tier_id));
CREATE TABLE sparks (
    owner TEXT NOT NULL, species_id TEXT NOT NULL, copies INTEGER NOT NULL CHECK (copies >= 0),
    level INTEGER NOT NULL, xp INTEGER NOT NULL, faint_until REAL,
    PRIMARY KEY (owner, species_id));
CREATE TABLE personalities (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
    species_id TEXT NOT NULL, type_id TEXT NOT NULL, tier INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE INDEX personalities_by_species ON personalities (owner, species_id, seq);
CREATE TABLE presets (
    owner TEXT NOT NULL, species_id TEXT NOT NULL, slot INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 5),
    instance_ids TEXT NOT NULL, PRIMARY KEY (owner, species_id, slot));
CREATE TABLE encounters (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, species_id TEXT NOT NULL, tier_id TEXT NOT NULL,
    level INTEGER NOT NULL, status TEXT NOT NULL, wild_personalities TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX encounters_by_owner ON encounters (owner, status);
CREATE TABLE battles (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, encounter_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
    phase TEXT NOT NULL, mode TEXT NOT NULL, revision INTEGER NOT NULL, setup TEXT NOT NULL, state TEXT NOT NULL,
    player_personalities TEXT NOT NULL, wild_personalities TEXT NOT NULL, emblem_limit TEXT,
    rng_seed INTEGER NOT NULL, rng_counter INTEGER NOT NULL, pending TEXT, result TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE UNIQUE INDEX one_active_battle ON battles (owner) WHERE status = 'active';
CREATE TABLE rounds (
    battle_id TEXT NOT NULL, round_number INTEGER NOT NULL, record TEXT NOT NULL,
    PRIMARY KEY (battle_id, round_number));
CREATE TABLE idempotency (
    owner TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL,
    created_at REAL NOT NULL, PRIMARY KEY (owner, key));
"""


class SparkTransaction(Protocol):
    """Everything a service may read or write inside one transaction."""

    async def get_player(self, owner: str) -> PlayerRecord | None: ...
    async def create_player(self, owner: str, now: float) -> None: ...
    async def add_insignia(self, owner: str, delta: int) -> None: ...
    async def set_last_roll(self, owner: str, when: float) -> None: ...
    async def emblem_counts(self, owner: str) -> dict[str, int]: ...
    async def add_emblems(self, owner: str, tier_id: str, delta: int) -> None: ...
    async def get_spark(self, owner: str, species_id: str) -> SparkRecord | None: ...
    async def list_sparks(self, owner: str) -> list[SparkRecord]: ...
    async def put_spark(self, record: SparkRecord) -> None: ...
    async def add_personality(self, record: PersonalityRecord) -> None: ...
    async def list_personalities(self, owner: str, species_id: str, limit: int, after_seq: int) -> list[PersonalityRecord]: ...
    async def get_personalities(self, owner: str, species_id: str, ids: list[str]) -> list[PersonalityRecord]: ...
    async def get_preset(self, owner: str, species_id: str, slot: int) -> PresetRecord | None: ...
    async def list_presets(self, owner: str, species_id: str) -> list[PresetRecord]: ...
    async def put_preset(self, record: PresetRecord) -> None: ...
    async def add_encounter(self, record: EncounterRecord) -> None: ...
    async def get_encounter(self, owner: str, encounter_id: str) -> EncounterRecord | None: ...
    async def pending_encounter(self, owner: str) -> EncounterRecord | None: ...
    async def set_encounter_status(self, encounter_id: str, status: str) -> None: ...
    async def add_battle(self, record: BattleRecord) -> None: ...
    async def get_battle(self, owner: str, battle_id: str) -> BattleRecord | None: ...
    async def active_battle(self, owner: str) -> BattleRecord | None: ...
    async def save_battle(self, record: BattleRecord, expected_revision: int) -> None: ...
    async def add_round(self, battle_id: str, round_number: int, record: dict[str, Any]) -> None: ...
    async def get_idempotent(self, owner: str, key: str) -> IdempotencyRecord | None: ...
    async def put_idempotent(self, owner: str, key: str, request_hash: str, response: dict[str, Any], now: float) -> None: ...


class SparkRepository(Protocol):
    def transaction(self) -> AsyncContextManager[SparkTransaction]: ...


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _instances(raw: str) -> tuple[PersonalityInstance, ...]:
    return tuple(PersonalityInstance.from_dict(i) for i in json.loads(raw))


class _SqliteTransaction:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    async def _run(self, sql: str, params: tuple = (), mode: str = "none") -> Any:
        def work() -> Any:
            cursor = self._conn.execute(sql, params)
            if mode == "one":
                return cursor.fetchone()
            if mode == "all":
                return cursor.fetchall()
            return cursor.rowcount

        return await asyncio.to_thread(work)

    # -- players and wallet --------------------------------------------------------

    async def get_player(self, owner: str) -> PlayerRecord | None:
        row = await self._run("SELECT * FROM players WHERE owner = ?", (owner,), "one")
        return PlayerRecord(row["owner"], row["insignia"], row["last_roll_at"], row["created_at"]) if row else None

    async def create_player(self, owner: str, now: float) -> None:
        await self._run("INSERT INTO players (owner, insignia, created_at) VALUES (?, 0, ?)", (owner, now))

    async def add_insignia(self, owner: str, delta: int) -> None:
        await self._run("UPDATE players SET insignia = insignia + ? WHERE owner = ?", (delta, owner))

    async def set_last_roll(self, owner: str, when: float) -> None:
        await self._run("UPDATE players SET last_roll_at = ? WHERE owner = ?", (when, owner))

    async def emblem_counts(self, owner: str) -> dict[str, int]:
        rows = await self._run("SELECT tier_id, count FROM emblems WHERE owner = ? AND count > 0", (owner,), "all")
        return {row["tier_id"]: row["count"] for row in rows}

    async def add_emblems(self, owner: str, tier_id: str, delta: int) -> None:
        # Update first: an upsert would check the raw delta against count >= 0 even for an existing row.
        changed = await self._run("UPDATE emblems SET count = count + ? WHERE owner = ? AND tier_id = ?", (delta, owner, tier_id))
        if changed == 0:
            await self._run("INSERT INTO emblems (owner, tier_id, count) VALUES (?, ?, ?)", (owner, tier_id, delta))

    # -- sparks, personalities, presets --------------------------------------------

    @staticmethod
    def _spark(row: sqlite3.Row) -> SparkRecord:
        return SparkRecord(row["owner"], row["species_id"], row["copies"], row["level"], row["xp"], row["faint_until"])

    async def get_spark(self, owner: str, species_id: str) -> SparkRecord | None:
        row = await self._run("SELECT * FROM sparks WHERE owner = ? AND species_id = ?", (owner, species_id), "one")
        return self._spark(row) if row else None

    async def list_sparks(self, owner: str) -> list[SparkRecord]:
        rows = await self._run("SELECT * FROM sparks WHERE owner = ? ORDER BY species_id", (owner,), "all")
        return [self._spark(r) for r in rows]

    async def put_spark(self, record: SparkRecord) -> None:
        await self._run(
            "INSERT INTO sparks (owner, species_id, copies, level, xp, faint_until) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (owner, species_id) DO UPDATE SET copies = excluded.copies, level = excluded.level, "
            "xp = excluded.xp, faint_until = excluded.faint_until",
            (record.owner, record.species_id, record.copies, record.level, record.xp, record.faint_until),
        )

    @staticmethod
    def _personality(row: sqlite3.Row) -> PersonalityRecord:
        return PersonalityRecord(row["id"], row["owner"], row["species_id"], row["type_id"], row["tier"],
                                 row["created_at"], row["seq"])

    async def add_personality(self, record: PersonalityRecord) -> None:
        await self._run(
            "INSERT INTO personalities (id, owner, species_id, type_id, tier, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record.id, record.owner, record.species_id, record.type_id, record.tier, record.created_at),
        )

    async def list_personalities(self, owner: str, species_id: str, limit: int, after_seq: int) -> list[PersonalityRecord]:
        rows = await self._run(
            "SELECT * FROM personalities WHERE owner = ? AND species_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (owner, species_id, after_seq, limit), "all",
        )
        return [self._personality(r) for r in rows]

    async def get_personalities(self, owner: str, species_id: str, ids: list[str]) -> list[PersonalityRecord]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = await self._run(
            f"SELECT * FROM personalities WHERE owner = ? AND species_id = ? AND id IN ({marks})",
            (owner, species_id, *ids), "all",
        )
        return [self._personality(r) for r in rows]

    async def get_preset(self, owner: str, species_id: str, slot: int) -> PresetRecord | None:
        row = await self._run(
            "SELECT * FROM presets WHERE owner = ? AND species_id = ? AND slot = ?", (owner, species_id, slot), "one")
        return PresetRecord(owner, species_id, slot, tuple(json.loads(row["instance_ids"]))) if row else None

    async def list_presets(self, owner: str, species_id: str) -> list[PresetRecord]:
        rows = await self._run(
            "SELECT * FROM presets WHERE owner = ? AND species_id = ? ORDER BY slot", (owner, species_id), "all")
        return [PresetRecord(owner, species_id, r["slot"], tuple(json.loads(r["instance_ids"]))) for r in rows]

    async def put_preset(self, record: PresetRecord) -> None:
        await self._run(
            "INSERT INTO presets (owner, species_id, slot, instance_ids) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (owner, species_id, slot) DO UPDATE SET instance_ids = excluded.instance_ids",
            (record.owner, record.species_id, record.slot, _dumps(list(record.instance_ids))),
        )

    # -- encounters ----------------------------------------------------------------

    @staticmethod
    def _encounter(row: sqlite3.Row) -> EncounterRecord:
        return EncounterRecord(row["id"], row["owner"], row["species_id"], row["tier_id"], row["level"], row["status"],
                               _instances(row["wild_personalities"]), row["created_at"])

    async def add_encounter(self, record: EncounterRecord) -> None:
        await self._run(
            "INSERT INTO encounters (id, owner, species_id, tier_id, level, status, wild_personalities, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (record.id, record.owner, record.species_id, record.tier_id, record.level, record.status,
             _dumps([i.to_dict() for i in record.wild_personalities]), record.created_at),
        )

    async def get_encounter(self, owner: str, encounter_id: str) -> EncounterRecord | None:
        row = await self._run("SELECT * FROM encounters WHERE owner = ? AND id = ?", (owner, encounter_id), "one")
        return self._encounter(row) if row else None

    async def pending_encounter(self, owner: str) -> EncounterRecord | None:
        row = await self._run(
            "SELECT * FROM encounters WHERE owner = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1", (owner,), "one")
        return self._encounter(row) if row else None

    async def set_encounter_status(self, encounter_id: str, status: str) -> None:
        await self._run("UPDATE encounters SET status = ? WHERE id = ?", (status, encounter_id))

    # -- battles -------------------------------------------------------------------

    @staticmethod
    def _battle(row: sqlite3.Row) -> BattleRecord:
        return BattleRecord(
            id=row["id"], owner=row["owner"], encounter_id=row["encounter_id"], status=row["status"], phase=row["phase"],
            mode=row["mode"], revision=row["revision"], setup=BattleSetup.from_dict(json.loads(row["setup"])),
            state=BattleState.from_dict(json.loads(row["state"])),
            player_personalities=_instances(row["player_personalities"]), wild_personalities=_instances(row["wild_personalities"]),
            emblem_limit=row["emblem_limit"], rng_seed=row["rng_seed"], rng_counter=row["rng_counter"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            pending=json.loads(row["pending"]) if row["pending"] else None,
            result=json.loads(row["result"]) if row["result"] else None,
        )

    @staticmethod
    def _battle_values(r: BattleRecord) -> tuple:
        return (
            r.status, r.phase, r.mode, r.revision, _dumps(r.setup.to_dict()), _dumps(r.state.to_dict()),
            _dumps([i.to_dict() for i in r.player_personalities]), _dumps([i.to_dict() for i in r.wild_personalities]),
            r.emblem_limit, r.rng_seed, r.rng_counter, _dumps(r.pending) if r.pending is not None else None,
            _dumps(r.result) if r.result is not None else None, r.updated_at,
        )

    async def add_battle(self, record: BattleRecord) -> None:
        try:
            await self._run(
                "INSERT INTO battles (id, owner, encounter_id, created_at, status, phase, mode, revision, setup, state, "
                "player_personalities, wild_personalities, emblem_limit, rng_seed, rng_counter, pending, result, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.id, record.owner, record.encounter_id, record.created_at, *self._battle_values(record)),
            )
        except sqlite3.IntegrityError as error:
            raise ActiveBattleExists("finish or forfeit the active battle first") from error

    async def get_battle(self, owner: str, battle_id: str) -> BattleRecord | None:
        row = await self._run("SELECT * FROM battles WHERE owner = ? AND id = ?", (owner, battle_id), "one")
        return self._battle(row) if row else None

    async def active_battle(self, owner: str) -> BattleRecord | None:
        row = await self._run("SELECT * FROM battles WHERE owner = ? AND status = 'active'", (owner,), "one")
        return self._battle(row) if row else None

    async def save_battle(self, record: BattleRecord, expected_revision: int) -> None:
        changed = await self._run(
            "UPDATE battles SET status = ?, phase = ?, mode = ?, revision = ?, setup = ?, state = ?, "
            "player_personalities = ?, wild_personalities = ?, emblem_limit = ?, rng_seed = ?, rng_counter = ?, "
            "pending = ?, result = ?, updated_at = ? WHERE id = ? AND revision = ?",
            (*self._battle_values(record), record.id, expected_revision),
        )
        if changed != 1:
            raise StaleBattle("the battle changed; reload it and try again")

    async def add_round(self, battle_id: str, round_number: int, record: dict[str, Any]) -> None:
        await self._run(
            "INSERT OR REPLACE INTO rounds (battle_id, round_number, record) VALUES (?, ?, ?)",
            (battle_id, round_number, _dumps(record)),
        )

    # -- idempotency ---------------------------------------------------------------

    async def get_idempotent(self, owner: str, key: str) -> IdempotencyRecord | None:
        row = await self._run("SELECT * FROM idempotency WHERE owner = ? AND key = ?", (owner, key), "one")
        return IdempotencyRecord(row["request_hash"], json.loads(row["response"])) if row else None

    async def put_idempotent(self, owner: str, key: str, request_hash: str, response: dict[str, Any], now: float) -> None:
        await self._run(
            "INSERT INTO idempotency (owner, key, request_hash, response, created_at) VALUES (?, ?, ?, ?, ?)",
            (owner, key, request_hash, _dumps(response), now),
        )


class SqliteSparkRepository:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    def _open(self) -> sqlite3.Connection:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(f"BEGIN; {SCHEMA} PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")
        elif version != SCHEMA_VERSION:
            conn.close()
            raise RuntimeError(f"database schema version {version} is not supported (expected {SCHEMA_VERSION})")
        return conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SparkTransaction]:
        async with self._lock:
            if self._conn is None:
                self._conn = await asyncio.to_thread(self._open)
            conn = self._conn
            await asyncio.to_thread(conn.execute, "BEGIN IMMEDIATE")
            try:
                yield _SqliteTransaction(conn)
            except BaseException:
                await asyncio.to_thread(conn.execute, "ROLLBACK")
                raise
            else:
                await asyncio.to_thread(conn.execute, "COMMIT")

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_repository.py -q`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/errors.py apps/mini_games/src/sparks/records.py apps/mini_games/src/sparks/repository.py apps/mini_games/tests/sparks/test_repository.py
git commit -m "feat(mini_games): SQLite repository with transactions and constraints"
```

---

### Task 10: Idempotency and progression

**Files:**
- Create: `apps/mini_games/src/sparks/idempotency.py`, `src/sparks/progression.py`
- Test: `apps/mini_games/tests/sparks/test_idempotency.py`, `apps/mini_games/tests/sparks/test_progression.py`

**Interfaces:**
- Consumes: `SparkRepository`, `SparkTransaction`, `Clock`, `Catalog`, the records and errors.
- Produces: `IdempotentWriter(repository, clock)` with `lookup(owner, key, operation, payload) -> dict | None` and `commit(owner, key, operation, payload, work) -> dict` (`work(tx)` runs and its response is stored in the same transaction; a retry returns the stored response; the same key with a different request raises `IdempotencyConflict`; keys are 1 to 200 characters).
- Produces: `ProgressionService(catalog, clock, faint_seconds)` with `xp_needed(level)`, `add_xp(species_id, level, xp, gained) -> (level, xp)`, `add_copies(species_id, copies, granted)`, `rewards_for(enemy_level, enemy_tier_id) -> (xp, insignia)` and `async apply_terminal(tx, battle, terminal, rng) -> dict` (the public result). Rules: XP and Insignia only for `won` and `captured` (`20 × level × stat multiplier`, and half that for Insignia), to the Spark that fought; XP carries through level-ups and is discarded at the cap; a capture adds the tier's copies (first capture starts at level 1; Forbidden grants 1 up to 100), awards one personality chosen with equal odds among the wild Spark's instances and reveals every instance; `knocked_out` and `forfeited` faint the fighter for `faint_seconds`; escapes change nothing.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_idempotency.py`

```python
import asyncio

import pytest

from src.sparks.errors import IdempotencyConflict, InvalidRequest
from src.sparks.idempotency import IdempotentWriter
from src.sparks.repository import SqliteSparkRepository
from tests.sparks.helpers import FixedClock


def run(coro):
    return asyncio.run(coro)


def make(tmp_path):
    repo = SqliteSparkRepository(tmp_path / "s.sqlite3")
    return repo, IdempotentWriter(repo, FixedClock())


def test_a_retry_returns_the_original_response_without_rerunning(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)
        calls = []

        async def work(tx):
            calls.append(1)
            await tx.create_player("ann", 1.0)
            return {"n": len(calls)}

        first = await writer.commit("ann", "k", "init", {"a": 1}, work)
        second = await writer.commit("ann", "k", "init", {"a": 1}, work)
        await repo.close()
        return first, second, calls

    first, second, calls = run(scenario())
    assert first == second == {"n": 1} and calls == [1]


def test_the_same_key_with_a_different_payload_conflicts(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def work(tx):
            return {}

        await writer.commit("ann", "k", "init", {"a": 1}, work)
        with pytest.raises(IdempotencyConflict):
            await writer.commit("ann", "k", "init", {"a": 2}, work)
        with pytest.raises(IdempotencyConflict):
            await writer.commit("ann", "k", "other-operation", {"a": 1}, work)
        await repo.close()

    run(scenario())


def test_keys_are_per_owner(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def work(tx):
            return {"who": "x"}

        await writer.commit("ann", "k", "op", {}, work)
        again = await writer.commit("bob", "k", "op", {}, work)
        await repo.close()
        return again

    assert run(scenario()) == {"who": "x"}


def test_a_failed_change_stores_nothing_so_the_retry_runs(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def failing(tx):
            await tx.create_player("ann", 1.0)
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await writer.commit("ann", "k", "op", {}, failing)

        async def fine(tx):
            await tx.create_player("ann", 2.0)
            return {"ok": True}

        result = await writer.commit("ann", "k", "op", {}, fine)
        await repo.close()
        return result

    assert run(scenario()) == {"ok": True}


def test_lookup_finds_a_stored_response_and_checks_the_payload(tmp_path):
    async def scenario():
        repo, writer = make(tmp_path)

        async def work(tx):
            return {"done": 1}

        assert await writer.lookup("ann", "k", "op", {"a": 1}) is None
        await writer.commit("ann", "k", "op", {"a": 1}, work)
        found = await writer.lookup("ann", "k", "op", {"a": 1})
        with pytest.raises(IdempotencyConflict):
            await writer.lookup("ann", "k", "op", {"a": 2})
        await repo.close()
        return found

    assert run(scenario()) == {"done": 1}


@pytest.mark.parametrize("key", ["", "x" * 201])
def test_bad_keys_are_rejected(tmp_path, key):
    async def scenario():
        repo, writer = make(tmp_path)
        with pytest.raises(InvalidRequest):
            await writer.lookup("ann", key, "op", {})
        await repo.close()

    run(scenario())
```

`apps/mini_games/tests/sparks/test_progression.py`

```python
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from src.sparks.catalog import Catalog
from src.sparks.engine import BattleEngine
from src.sparks.models import PLAYER, WILD, BattleSetup, PersonalityInstance
from src.sparks.progression import ProgressionService
from src.sparks.records import SparkRecord
from src.sparks.repository import SqliteSparkRepository
from tests.sparks.helpers import FixedClock, ScriptedRandom, battle_record

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
engine = BattleEngine(CATALOG)
clock = FixedClock(1000.0)
progression = ProgressionService(CATALOG, clock, faint_seconds=300)


def run(coro):
    return asyncio.run(coro)


# -- pure rules ----------------------------------------------------------------------

@pytest.mark.parametrize("level,xp,gained,expected", [
    (1, 0, 99, (1, 99)),
    (1, 0, 100, (2, 0)),
    (1, 50, 400, (3, 150)),  # 450 - 100 -> level 2; 350 - 200 -> level 3 with 150 left
    (29, 2899, 1, (30, 0)),  # reaching the cap drops the remainder
    (30, 0, 5000, (30, 0)),  # no XP at the cap
])
def test_xp_carries_through_level_ups_and_stops_at_the_cap(level, xp, gained, expected):
    assert progression.add_xp("guardian", level, xp, gained) == expected


def test_forbidden_levels_to_fifty():
    assert progression.add_xp("forbidden", 49, 0, 4900) == (50, 0)
    assert progression.add_xp("forbidden", 30, 0, 100) == (30, 100)


@pytest.mark.parametrize("level,tier,xp,insignia", [(10, "normal", 200, 100), (10, "legendary", 300, 150), (1, "rare", 25, 12), (30, "forbidden", 2400, 1200)])
def test_reward_formulas(level, tier, xp, insignia):
    assert progression.rewards_for(level, tier) == (xp, insignia)


def test_forbidden_copies_cap_at_one_hundred():
    assert progression.add_copies("forbidden", 99, 1) == 100 and progression.add_copies("forbidden", 100, 1) == 100
    assert progression.add_copies("guardian", 500, 5) == 505


# -- applying a terminal result ------------------------------------------------------

def build_battle(player_species="guardian", wild_species="scout", wild_tier="normal", wild_level=10, wild_instances=None):
    setup = BattleSetup(
        engine.build_fighter(PLAYER, player_species, "normal", 5),
        engine.build_fighter(WILD, wild_species, wild_tier, wild_level),
    )
    record = battle_record()
    instances = wild_instances or (PersonalityInstance("w1", "COWARD", 2), PersonalityInstance("w2", "BOLD", 3), PersonalityInstance("w3", "AGGRESSIVE", 1))
    return replace(record, setup=setup, wild_personalities=instances)


async def apply(terminal, battle, spark, *draws, others=()):
    repo = SqliteSparkRepository(":memory:")
    async with repo.transaction() as tx:
        await tx.create_player("ann", 1.0)
        await tx.put_spark(spark)
        for other in others:
            await tx.put_spark(other)
        result = await progression.apply_terminal(tx, battle, terminal, ScriptedRandom(*draws))
        after = {s.species_id: s for s in await tx.list_sparks("ann")}
        player = await tx.get_player("ann")
        personalities = {s: await tx.list_personalities("ann", s, 50, 0) for s in after}
    await repo.close()
    return result, after, player, personalities


FIGHTER = SparkRecord("ann", "guardian", 7, 5, 30)


def test_a_win_pays_xp_and_insignia_to_the_fighter_only():
    result, sparks, player, _ = run(apply("won", build_battle(), FIGHTER))
    assert (result["xp"], result["insignia"]) == (200, 100)
    assert (sparks["guardian"].level, sparks["guardian"].xp) == (5, 230)  # 30 + 200, below the 500 needed at level 5
    assert player.insignia == 100 and sparks["guardian"].copies == 7 and sparks["guardian"].faint_until is None
    assert set(sparks) == {"guardian"}


def test_a_win_levels_up_with_carry():
    spark = replace(FIGHTER, level=1, xp=0)
    result, sparks, _, _ = run(apply("won", build_battle(wild_level=10), spark))  # 200 XP -> level 2 (100) -> level 3 needs 200
    assert (sparks["guardian"].level, sparks["guardian"].xp) == (2, 100)
    assert result["level_before"] == 1 and result["level_after"] == 2


def test_capturing_an_unowned_species_starts_it_at_level_one_with_the_tiers_copies():
    battle = build_battle(wild_species="channeler", wild_tier="rare")
    result, sparks, player, personalities = run(apply("captured", battle, FIGHTER, 0.5))
    new = sparks["channeler"]
    assert (new.level, new.xp, new.copies) == (1, 0, 2)  # Rare grants 2 copies
    assert result["copies_granted"] == 2 and result["tier_id"] == "normal"
    assert player.insignia == 125  # Rare level 10: 10 * 10 * 1.25
    assert [p.type_id for p in personalities["channeler"]] == ["BOLD"]  # draw 0.5 of 3 -> index 1
    assert result["awarded_personality"]["type"] == "BOLD"
    assert [p["type"] for p in result["revealed_personalities"]] == ["COWARD", "BOLD", "AGGRESSIVE"]
    assert (sparks["guardian"].level, sparks["guardian"].xp) == (5, 280)  # 20 * 10 * 1.25 = 250 XP


def test_capture_adds_copies_to_an_owned_species_and_tier_follows_the_count():
    owned = SparkRecord("ann", "scout", 8, 12, 40)
    battle = build_battle(wild_species="scout", wild_tier="rare")
    result, sparks, _, _ = run(apply("captured", battle, FIGHTER, 0.0, others=(owned,)))
    assert (sparks["scout"].copies, sparks["scout"].level) == (10, 12) and result["tier_id"] == "rare"


@pytest.mark.parametrize("draw,index", [(0.0, 0), (0.33, 0), (0.34, 1), (0.99, 2)])
def test_every_source_personality_is_equally_likely_to_be_awarded(draw, index):
    battle = build_battle(wild_species="channeler")
    result, _, _, _ = run(apply("captured", battle, FIGHTER, draw))
    assert result["awarded_personality"]["type"] == ["COWARD", "BOLD", "AGGRESSIVE"][index]


def test_identical_personalities_stay_distinct_instances():
    same = (PersonalityInstance("a", "BOLD", 2), PersonalityInstance("b", "BOLD", 2))
    owned = SparkRecord("ann", "channeler", 1, 3, 0)
    battle = build_battle(wild_species="channeler", wild_instances=same)

    async def twice():
        repo = SqliteSparkRepository(":memory:")
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)
            await tx.put_spark(FIGHTER)
            await tx.put_spark(owned)
            await progression.apply_terminal(tx, battle, "captured", ScriptedRandom(0.0))
            await progression.apply_terminal(tx, battle, "captured", ScriptedRandom(0.0))
            found = await tx.list_personalities("ann", "channeler", 50, 0)
        await repo.close()
        return found

    found = run(twice())
    assert len(found) == 2 and found[0].id != found[1].id


def test_a_capped_forbidden_capture_still_pays_xp_insignia_and_a_personality():
    capped = SparkRecord("ann", "forbidden", 100, 40, 0)
    battle = build_battle(wild_species="forbidden", wild_tier="forbidden", wild_level=20)
    result, sparks, player, personalities = run(apply("captured", battle, FIGHTER, 0.0, others=(capped,)))
    assert sparks["forbidden"].copies == 100 and result["copies_granted"] == 0
    assert player.insignia == 800 and len(personalities["forbidden"]) == 1


def test_a_first_forbidden_capture_grants_one_copy():
    battle = build_battle(wild_species="forbidden", wild_tier="forbidden", wild_level=3)
    result, sparks, _, _ = run(apply("captured", battle, FIGHTER, 0.0))
    assert (sparks["forbidden"].copies, sparks["forbidden"].level, result["tier_id"]) == (1, 1, "forbidden")


@pytest.mark.parametrize("terminal", ["knocked_out", "forfeited"])
def test_losing_faints_the_fighter_for_five_minutes_without_losing_copies(terminal):
    result, sparks, player, _ = run(apply(terminal, build_battle(), FIGHTER))
    assert sparks["guardian"].faint_until == 1300.0 and result["faint_until"] == 1300.0
    assert sparks["guardian"].copies == 7 and player.insignia == 0 and "xp" not in result


@pytest.mark.parametrize("terminal", ["escaped", "wild_escaped"])
def test_escapes_change_nothing(terminal):
    result, sparks, player, _ = run(apply(terminal, build_battle(), FIGHTER))
    assert sparks["guardian"] == FIGHTER and player.insignia == 0 and result == {"kind": terminal}


def test_the_whole_result_is_atomic():
    async def scenario():
        repo = SqliteSparkRepository(":memory:")
        async with repo.transaction() as tx:
            await tx.create_player("ann", 1.0)
            await tx.put_spark(FIGHTER)
        with pytest.raises(RuntimeError):
            async with repo.transaction() as tx:
                await progression.apply_terminal(tx, build_battle(), "won", ScriptedRandom())
                raise RuntimeError("crash before commit")
        async with repo.transaction() as tx:
            spark, player = await tx.get_spark("ann", "guardian"), await tx.get_player("ann")
        await repo.close()
        return spark, player

    spark, player = run(scenario())
    assert spark == FIGHTER and player.insignia == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_idempotency.py tests/sparks/test_progression.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.idempotency'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/idempotency.py`

```python
"""Exactly-once mutations.

Every mutation carries an idempotency key. The response is stored in the same
transaction as the change, so a retry returns the original result and never
repeats the change or rerolls its randomness. Reusing a key for a different
request is a conflict.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Awaitable, Callable

from src.sparks.errors import IdempotencyConflict, InvalidRequest
from src.sparks.repository import SparkRepository, SparkTransaction
from src.sparks.runtime import Clock

MAX_KEY_LENGTH = 200


class IdempotentWriter:
    def __init__(self, repository: SparkRepository, clock: Clock) -> None:
        self._repo, self._clock = repository, clock

    @staticmethod
    def _check_key(key: str) -> None:
        if not key or len(key) > MAX_KEY_LENGTH:
            raise InvalidRequest(f"the idempotency key must be 1 to {MAX_KEY_LENGTH} characters")

    @staticmethod
    def fingerprint(operation: str, payload: Any) -> str:
        text = json.dumps({"operation": operation, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _match(cached, fingerprint: str) -> dict[str, Any] | None:
        if cached is None:
            return None
        if cached.request_hash != fingerprint:
            raise IdempotencyConflict("this idempotency key was already used for a different request")
        return cached.response

    async def lookup(self, owner: str, key: str, operation: str, payload: Any) -> dict[str, Any] | None:
        """The stored response for this exact request, or None if it has not run."""
        self._check_key(key)
        async with self._repo.transaction() as tx:
            return self._match(await tx.get_idempotent(owner, key), self.fingerprint(operation, payload))

    async def commit(
        self, owner: str, key: str, operation: str, payload: Any,
        work: Callable[[SparkTransaction], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Run `work` and store its response in one transaction (or replay the stored one)."""
        self._check_key(key)
        fingerprint = self.fingerprint(operation, payload)
        async with self._repo.transaction() as tx:
            cached = self._match(await tx.get_idempotent(owner, key), fingerprint)
            if cached is not None:
                return cached
            response = await work(tx)
            await tx.put_idempotent(owner, key, fingerprint, response, self._clock.now())
            return response
```

`apps/mini_games/src/sparks/progression.py`

```python
"""Progression: what a finished battle is worth.

`apply_terminal` runs inside the caller's transaction, so XP, Insignia, copies,
the awarded personality, fainting and the battle result are saved together or
not at all.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.models import PersonalityInstance
from src.sparks.records import BattleRecord, PersonalityRecord, SparkRecord
from src.sparks.repository import SparkTransaction
from src.sparks.runtime import Clock, RandomSource, new_id

_EPS = 1e-9
REWARDED = ("won", "captured")
FAINTING = ("knocked_out", "forfeited")


class ProgressionService:
    def __init__(self, catalog: Catalog, clock: Clock, faint_seconds: float) -> None:
        self._catalog, self._clock, self._faint_seconds = catalog, clock, faint_seconds

    # -- pure helpers --------------------------------------------------------------

    def xp_needed(self, level: int) -> int:
        return self._catalog.levels.xp_per_level * level

    def add_xp(self, species_id: str, level: int, xp: int, gained: int) -> tuple[int, int]:
        """Carry excess XP through level-ups; at the cap XP stops and the excess is discarded."""
        cap = self._catalog.level_cap(species_id)
        if level >= cap:
            return cap, 0
        xp += gained
        while level < cap and xp >= self.xp_needed(level):
            xp -= self.xp_needed(level)
            level += 1
        return level, (0 if level >= cap else xp)

    def add_copies(self, species_id: str, copies: int, granted: int) -> int:
        if self._catalog.species(species_id).forbidden:
            return min(copies + granted, self._catalog.economy.forbidden_copy_cap)
        return copies + granted

    def rewards_for(self, enemy_level: int, enemy_tier_id: str) -> tuple[int, int]:
        """(XP, Insignia) for beating or collecting an enemy."""
        multiplier = self._catalog.tier(enemy_tier_id).stat_multiplier
        eco = self._catalog.economy
        return (
            math.floor(eco.xp_reward_factor * enemy_level * multiplier + _EPS),
            math.floor(eco.insignia_reward_factor * enemy_level * multiplier + _EPS),
        )

    # -- a finished battle ---------------------------------------------------------

    async def apply_terminal(
        self, tx: SparkTransaction, battle: BattleRecord, terminal: str, rng: RandomSource
    ) -> dict[str, Any]:
        """Apply the consequences of `terminal` and return the public result."""
        owner = battle.owner
        fighter, enemy = battle.setup.player, battle.setup.wild
        result: dict[str, Any] = {"kind": terminal}
        spark = await tx.get_spark(owner, fighter.species_id)

        if terminal in REWARDED:
            xp, insignia = self.rewards_for(enemy.level, enemy.tier_id)
            level, new_xp = self.add_xp(fighter.species_id, spark.level, spark.xp, xp)
            await tx.put_spark(replace(spark, level=level, xp=new_xp))
            await tx.add_insignia(owner, insignia)
            result.update(xp=xp, insignia=insignia, level_before=spark.level, level_after=level)
            if terminal == "captured":
                result.update(await self._collect(tx, battle, rng))
        elif terminal in FAINTING:
            until = self._clock.now() + self._faint_seconds
            await tx.put_spark(replace(spark, faint_until=until))
            result["faint_until"] = until
        return result

    async def _collect(self, tx: SparkTransaction, battle: BattleRecord, rng: RandomSource) -> dict[str, Any]:
        owner, enemy = battle.owner, battle.setup.wild
        reward = self._catalog.tier(enemy.tier_id).copy_reward
        owned = await tx.get_spark(owner, enemy.species_id)
        if owned is None:
            copies = self.add_copies(enemy.species_id, 0, reward)
            await tx.put_spark(SparkRecord(owner, enemy.species_id, copies, 1, 0))
            granted = copies
        else:
            copies = self.add_copies(enemy.species_id, owned.copies, reward)
            await tx.put_spark(replace(owned, copies=copies))
            granted = copies - owned.copies
        instances = battle.wild_personalities
        chosen = instances[min(int(rng.next() * len(instances)), len(instances) - 1)]
        award = PersonalityRecord(new_id(), owner, enemy.species_id, chosen.type_id, chosen.tier, self._clock.now())
        await tx.add_personality(award)
        return {
            "species_id": enemy.species_id,
            "copies_granted": granted,
            "copies": copies,
            "tier_id": self._catalog.tier_for_copies(enemy.species_id, copies),
            "awarded_personality": _describe(award.instance()),
            "revealed_personalities": [_describe(i) for i in instances],  # every source instance, awarded or not
        }


def _describe(instance: PersonalityInstance) -> dict[str, Any]:
    return {"id": instance.id, "type": instance.type_id, "tier": instance.tier}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_idempotency.py tests/sparks/test_progression.py -q`
Expected: 34 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/idempotency.py apps/mini_games/src/sparks/progression.py apps/mini_games/tests/sparks/test_idempotency.py apps/mini_games/tests/sparks/test_progression.py
git commit -m "feat(mini_games): idempotent writes and battle progression"
```

---

### Task 11: Collection, encounters and the shop

**Files:**
- Create: `apps/mini_games/src/sparks/collection.py`, `src/sparks/encounters.py`, `src/sparks/shop.py`, `tests/sparks/env.py`
- Test: `apps/mini_games/tests/sparks/test_collection.py`, `test_encounters.py`, `test_shop.py`

**Interfaces:**
- Consumes: everything from Tasks 4 to 10.
- Produces: `CollectionService(repository, writer, catalog, clock, rng, roll_cooldown_seconds)` with `profile_view(tx, owner)`, `profile(owner)`, `initialize(owner, key, starter_species_id)` (one level-1 starter, five Normal EMBLEMs, zero Insignia, one random tier-1 personality in preset 1; a second call is `AlreadyInitialized`), `personalities(owner, species_id, limit, cursor)` (default 50, maximum 100), `get_preset(owner, species_id, slot)`, `put_preset(owner, key, species_id, slot, instance_ids)` (slots 1 to 5, up to three distinct instances of that species; one instance may sit in several presets).
- Produces: `EncounterRoller(catalog).roll(highest_level, rng) -> RolledEncounter` (tier by the 60/25/10/4/0.9/0.1 odds; species uniform among the six regular ones, or the Forbidden species; level uniform in `clamp(highest ± 2, 1, cap)`; one to three personalities with equal odds for the count, equal odds among the eight types, tiers 60/30/10) and `EncounterService(repository, writer, catalog, clock, rng, cooldown_seconds)` with `roll`, `get`, `decline`, `preview` (never includes personalities).
- Produces: `ShopService(writer, catalog, progression)` with `copy_price(species_id, owned, tier_id) -> (price, granted, resulting_tier)`, `buy_emblems`, `buy_copies`, `sell_copy`. Prices follow the spec: EMBLEM price is 20% of its strength; a copy package costs `2 × copies × resale value at the resulting tier and level`; a sale pays the value at the tier and level before the copy goes; the Forbidden species is capture-only; a species fighting in the active battle cannot be bought or sold.
- Produces (`tests/sparks/env.py`): `Env(db_path, rng=None)` with `repo`, `clock`, `writer`, `engine`, `progression`, `collection`, `encounters`, `shop`, `coordinator(...)`, `key()`, `start_player()`, `give()`, `close()`, and `run(coro)`. `coordinator()` imports lazily because the coordinator arrives in Task 12.

- [ ] **Step 1: Write the test environment and the failing tests**

`apps/mini_games/tests/sparks/env.py`

```python
"""Builds the service graph over a temporary database for service-level tests."""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

from src.sparks.catalog import Catalog
from src.sparks.collection import CollectionService
from src.sparks.encounters import EncounterService
from src.sparks.engine import BattleEngine
from src.sparks.idempotency import IdempotentWriter
from src.sparks.progression import ProgressionService
from src.sparks.repository import SqliteSparkRepository
from src.sparks.runtime import RandomSource, SeededRandom
from src.sparks.shop import ShopService
from tests.sparks.helpers import FixedClock

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
COOLDOWN = 30.0
FAINT = 300.0
PROMPT = 5.0
_KEYS = itertools.count(1)  # unique across Env instances, so a restarted Env never reuses a key


class Env:
    def __init__(self, db_path: Path, rng: RandomSource | None = None) -> None:
        self.catalog = CATALOG
        self.clock = FixedClock()
        self.rng = rng or SeededRandom(11)
        self.repo = SqliteSparkRepository(db_path)
        self.writer = IdempotentWriter(self.repo, self.clock)
        self.engine = BattleEngine(CATALOG)
        self.progression = ProgressionService(CATALOG, self.clock, FAINT)
        self.collection = CollectionService(self.repo, self.writer, CATALOG, self.clock, self.rng, COOLDOWN)
        self.encounters = EncounterService(self.repo, self.writer, CATALOG, self.clock, self.rng, COOLDOWN)
        self.shop = ShopService(self.writer, CATALOG, self.progression)

    def coordinator(self, policy=None, reader=None, picker=None, laya=None):
        """A RoundCoordinator over this Env. Imports are local: the coordinator is built in a later task."""
        from src.laya_client import LayaClient
        from src.sparks.battle_view import BattleViewBuilder
        from src.sparks.coordinator import CoordinatorSettings, RoundCoordinator
        from src.sparks.decider import ActionDecider
        from src.sparks.emblem_picker import LayaEmblemPicker
        from src.sparks.policy import ActionPolicy, Mood
        from src.sparks.situation import HeuristicSituationReader, SituationViewBuilder
        from tests.fake_laya import FakeEngine

        views = BattleViewBuilder(self.engine, CATALOG)
        client = LayaClient(laya or FakeEngine(fail=True))
        situation_views = SituationViewBuilder(self.engine)
        decider = ActionDecider(
            CATALOG, self.engine, policy or ActionPolicy(CATALOG.policy), Mood(CATALOG),
            reader or HeuristicSituationReader(CATALOG.policy.default_aggression), situation_views,
        )
        return RoundCoordinator(
            self.repo, self.writer, CATALOG, self.engine, decider, situation_views,
            picker or LayaEmblemPicker(client), self.progression, views, self.clock, CoordinatorSettings(PROMPT),
        )

    def key(self) -> str:
        return f"key-{next(_KEYS)}"

    async def start_player(self, owner: str = "ann", starter: str = "guardian") -> dict:
        return await self.collection.initialize(owner, self.key(), starter)

    async def give(self, owner: str = "ann", insignia: int = 0, **sparks) -> None:
        """Test setup: add Insignia and/or replace Spark records directly."""
        async with self.repo.transaction() as tx:
            if insignia:
                await tx.add_insignia(owner, insignia)
            for record in sparks.values():
                await tx.put_spark(record)

    async def close(self) -> None:
        await self.repo.close()


def run(coro):
    return asyncio.run(coro)
```

`apps/mini_games/tests/sparks/test_collection.py`

```python
import pytest

from src.sparks.errors import AlreadyInitialized, IdempotencyConflict, InvalidRequest, NotFound
from tests.sparks.env import Env, run
from tests.sparks.helpers import ScriptedRandom


def make(tmp_path, *draws):
    return Env(tmp_path / "s.sqlite3", ScriptedRandom(*draws) if draws else None)


def test_initialize_creates_the_starter_setup(tmp_path):
    async def scenario():
        env = make(tmp_path, 0.0)  # first personality type: AGGRESSIVE
        profile = await env.start_player("ann", "scout")
        presets = await env.collection.get_preset("ann", "scout", 1)
        pool = await env.collection.personalities("ann", "scout", None, 0)
        await env.close()
        return profile, presets, pool

    profile, preset, pool = run(scenario())
    assert profile["insignia"] == 0 and profile["emblems"] == {"normal": 5}
    [spark] = profile["sparks"]
    assert (spark["species_id"], spark["level"], spark["copies"], spark["tier_id"]) == ("scout", 1, 0, "normal")
    assert pool["items"][0]["type"] == "AGGRESSIVE" and pool["items"][0]["tier"] == 1
    assert preset["instance_ids"] == [pool["items"][0]["id"]]


@pytest.mark.parametrize("draw,expected", [(0.0, "AGGRESSIVE"), (0.99, "DISCIPLINED")])
def test_the_starter_personality_is_uniform_over_the_eight_types(tmp_path, draw, expected):
    async def scenario():
        env = make(tmp_path, draw)
        await env.start_player()
        pool = await env.collection.personalities("ann", "guardian", None, 0)
        await env.close()
        return pool

    assert run(scenario())["items"][0]["type"] == expected


def test_only_the_three_starters_can_be_chosen(tmp_path):
    async def scenario():
        env = make(tmp_path)
        with pytest.raises(InvalidRequest, match="guardian, scout, striker"):
            await env.collection.initialize("ann", "k", "sentinel")
        await env.close()

    run(scenario())


def test_initialization_happens_once_and_retries_return_the_same_result(tmp_path):
    async def scenario():
        env = make(tmp_path)
        first = await env.collection.initialize("ann", "k1", "guardian")
        again = await env.collection.initialize("ann", "k1", "guardian")
        with pytest.raises(AlreadyInitialized):
            await env.collection.initialize("ann", "k2", "striker")
        with pytest.raises(IdempotencyConflict):
            await env.collection.initialize("ann", "k1", "striker")
        await env.close()
        return first, again

    first, again = run(scenario())
    assert first == again


def test_profiles_are_isolated_between_owners(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player("ann")
        with pytest.raises(NotFound):
            await env.collection.profile("bob")
        with pytest.raises(NotFound):
            await env.collection.get_preset("bob", "guardian", 1)
        await env.close()

    run(scenario())


def test_profile_reports_xp_needed_faint_and_timers(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        from src.sparks.records import SparkRecord

        await env.give(guardian=SparkRecord("ann", "guardian", 12, 30, 0, faint_until=env.clock.now() + 60))
        profile = await env.collection.profile("ann")
        await env.close()
        return profile["sparks"][0]

    spark = run(scenario())
    assert spark["fainted"] is True and spark["xp_needed"] is None and spark["tier_id"] == "rare"


def test_presets_hold_up_to_three_distinct_collected_instances(tmp_path):
    async def scenario():
        env = make(tmp_path, 0.0)
        await env.start_player()
        from src.sparks.records import PersonalityRecord

        async with env.repo.transaction() as tx:
            for name in ("b", "c", "d"):
                await tx.add_personality(PersonalityRecord(name, "ann", "guardian", "COWARD", 2, 1.0))
            await tx.add_personality(PersonalityRecord("other", "ann", "scout", "COWARD", 2, 1.0))
        ok = await env.collection.put_preset("ann", "k1", "guardian", 2, ["b", "c", "d"])
        again = await env.collection.put_preset("ann", "k2", "guardian", 3, ["b"])  # the same instance in two presets
        for bad in (["b", "b"], ["b", "c", "d", "x"], ["nope"], ["other"]):
            with pytest.raises(InvalidRequest):
                await env.collection.put_preset("ann", env.key(), "guardian", 4, bad)
        for slot in (0, 6):
            with pytest.raises(InvalidRequest):
                await env.collection.put_preset("ann", env.key(), "guardian", slot, [])
        stored = await env.collection.get_preset("ann", "guardian", 2)
        empty = await env.collection.get_preset("ann", "guardian", 5)
        await env.close()
        return ok, again, stored, empty

    ok, again, stored, empty = run(scenario())
    assert ok["instance_ids"] == ["b", "c", "d"] == stored["instance_ids"] and again["instance_ids"] == ["b"] and empty["instance_ids"] == []


def test_a_preset_cannot_use_someone_elses_instances_or_an_unowned_species(tmp_path):
    async def scenario():
        env = make(tmp_path, 0.0, 0.0)
        await env.start_player("ann")
        await env.start_player("bob")
        bobs = (await env.collection.personalities("bob", "guardian", None, 0))["items"][0]["id"]
        with pytest.raises(InvalidRequest):
            await env.collection.put_preset("ann", "k", "guardian", 2, [bobs])
        with pytest.raises(NotFound):
            await env.collection.put_preset("ann", "k2", "scout", 2, [])
        await env.close()

    run(scenario())


def test_personality_pages_default_to_fifty_and_cap_at_one_hundred(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        from src.sparks.records import PersonalityRecord

        async with env.repo.transaction() as tx:
            for i in range(120):
                await tx.add_personality(PersonalityRecord(f"p{i:03}", "ann", "guardian", "BOLD", 1, 1.0))
        first = await env.collection.personalities("ann", "guardian", None, 0)
        cursor, seen = first["next_cursor"], len(first["items"])
        while cursor:
            page = await env.collection.personalities("ann", "guardian", 100, cursor)
            seen += len(page["items"])
            cursor = page["next_cursor"]
        for bad in (0, 101):
            with pytest.raises(InvalidRequest):
                await env.collection.personalities("ann", "guardian", bad, 0)
        await env.close()
        return len(first["items"]), seen

    first, seen = run(scenario())
    assert first == 50 and seen == 121  # 120 added plus the starter's own
```

`apps/mini_games/tests/sparks/test_encounters.py`

```python
import pytest

from src.sparks.encounters import EncounterRoller
from src.sparks.errors import ActiveBattleExists, EncounterCooldown, NotFound, WrongPhase
from src.sparks.runtime import SeededRandom
from tests.sparks.env import CATALOG, COOLDOWN, Env, run
from tests.sparks.helpers import ScriptedRandom, battle_record

roller = EncounterRoller(CATALOG)


def roll(highest, *draws):
    return roller.roll(highest, ScriptedRandom(*draws))


# -- the draws -----------------------------------------------------------------------

@pytest.mark.parametrize("u,tier", [(0.3, "normal"), (0.7, "rare"), (0.9, "legendary"), (0.97, "royalty"), (0.995, "ascended"), (0.9995, "forbidden")])
def test_tier_follows_the_encounter_probabilities(u, tier):
    assert roll(10, u, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0).tier_id == tier


def test_regular_tiers_pick_uniformly_among_the_six_regular_species():
    picked = [roll(10, 0.3, u, 0.0, 0.0, 0.0, 0.0).species_id for u in (0.0, 0.17, 0.34, 0.5, 0.67, 0.99)]
    assert picked == ["guardian", "striker", "scout", "sentinel", "bruiser", "channeler"]


def test_forbidden_tier_is_always_the_forbidden_species_and_uses_one_fewer_draw():
    assert roll(10, 0.9995, 0.0, 0.0, 0.0, 0.0).species_id == "forbidden"


@pytest.mark.parametrize("highest,species_draw,low,high", [
    (10, 0.0, 8, 12),
    (1, 0.0, 1, 3),
    (30, 0.0, 28, 30),
    (50, 0.0, 30, 30),  # a level-50 collection still meets valid regular enemies
])
def test_enemy_level_window_is_clamped_to_the_species_cap(highest, species_draw, low, high):
    levels = {roll(highest, 0.3, species_draw, u, 0.0, 0.0, 0.0).level for u in (0.0, 0.25, 0.5, 0.75, 0.999)}
    assert min(levels) == low and max(levels) == high


def test_forbidden_levels_can_exceed_the_regular_cap():
    assert roll(50, 0.9995, 0.999, 0.0, 0.0, 0.0).level == 50
    assert roll(3, 0.9995, 0.0, 0.0, 0.0, 0.0).level == 1


@pytest.mark.parametrize("count_draw,count", [(0.0, 1), (0.4, 2), (0.9, 3)])
def test_one_to_three_personalities_with_equal_odds(count_draw, count):
    draws = [0.3, 0.0, 0.0, count_draw] + [0.0, 0.0] * 3
    assert len(roll(10, *draws).personalities) == count


def test_personality_type_and_tier_come_from_the_draws():
    rolled = roll(10, 0.3, 0.0, 0.0, 0.0, 0.99, 0.95)  # one instance: last type, tier 3
    [only] = rolled.personalities
    assert (only.type_id, only.tier) == ("DISCIPLINED", 3)
    assert roll(10, 0.3, 0.0, 0.0, 0.0, 0.0, 0.59).personalities[0].tier == 1
    assert roll(10, 0.3, 0.0, 0.0, 0.0, 0.0, 0.7).personalities[0].tier == 2


def test_distribution_over_many_rolls_matches_the_tables():
    rng = SeededRandom(3)
    tiers: dict[str, int] = {}
    instance_tiers = {1: 0, 2: 0, 3: 0}
    n = 20000
    for _ in range(n):
        rolled = roller.roll(10, rng)
        tiers[rolled.tier_id] = tiers.get(rolled.tier_id, 0) + 1
        for instance in rolled.personalities:
            instance_tiers[instance.tier] += 1
    assert tiers["normal"] / n == pytest.approx(0.60, abs=0.02)
    assert tiers["rare"] / n == pytest.approx(0.25, abs=0.02)
    assert tiers["legendary"] / n == pytest.approx(0.10, abs=0.015)
    total = sum(instance_tiers.values())
    assert instance_tiers[1] / total == pytest.approx(0.6, abs=0.02) and instance_tiers[3] / total == pytest.approx(0.1, abs=0.015)


# -- the service ---------------------------------------------------------------------

def test_a_roll_creates_a_preview_without_personalities_and_starts_the_cooldown(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        preview = await env.encounters.roll("ann", "r1")
        profile = await env.collection.profile("ann")
        again = await env.encounters.roll("ann", "r1")  # a retry, not a new roll
        fetched = await env.encounters.get("ann", preview["id"])
        await env.close()
        return preview, profile, again, fetched, env.clock.now()

    preview, profile, again, fetched, now = run(scenario())
    assert set(preview) == {"id", "species_id", "name", "tier_id", "level", "status", "created_at"}
    assert preview == again == fetched and preview["status"] == "pending"
    assert profile["pending_encounter"] == preview["id"] and profile["next_roll_at"] == now + COOLDOWN


def test_a_new_roll_waits_thirty_seconds_from_the_previous_generation(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        first = await env.encounters.roll("ann", "r1")
        env.clock.advance(10)
        with pytest.raises(EncounterCooldown) as early:
            await env.encounters.roll("ann", "r2")
        env.clock.advance(20)
        second = await env.encounters.roll("ann", "r3")
        old = await env.encounters.get("ann", first["id"])
        await env.close()
        return early.value, second, old

    early, second, old = run(scenario())
    assert early.retry_after == pytest.approx(20) and old["status"] == "expired" and second["status"] == "pending"


def test_declining_is_free_and_final(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        preview = await env.encounters.roll("ann", "r1")
        declined = await env.encounters.decline("ann", "d1", preview["id"])
        with pytest.raises(WrongPhase):
            await env.encounters.decline("ann", "d2", preview["id"])
        with pytest.raises(NotFound):
            await env.encounters.decline("ann", "d3", "nope")
        profile = await env.collection.profile("ann")
        await env.close()
        return declined, profile

    declined, profile = run(scenario())
    assert declined["status"] == "declined" and profile["pending_encounter"] is None and profile["insignia"] == 0


def test_encounters_are_owner_safe(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player("ann")
        await env.start_player("bob")
        preview = await env.encounters.roll("ann", "r1")
        with pytest.raises(NotFound):
            await env.encounters.get("bob", preview["id"])
        with pytest.raises(NotFound):
            await env.encounters.decline("bob", "d1", preview["id"])
        await env.close()

    run(scenario())


def test_rolling_needs_a_profile_and_no_active_battle(tmp_path):
    async def scenario():
        env = Env(tmp_path / "s.sqlite3")
        with pytest.raises(NotFound):
            await env.encounters.roll("ann", "r0")
        await env.start_player()
        async with env.repo.transaction() as tx:
            await tx.add_battle(battle_record())
        with pytest.raises(ActiveBattleExists):
            await env.encounters.roll("ann", "r1")
        await env.close()

    run(scenario())
```

`apps/mini_games/tests/sparks/test_shop.py`

```python
import pytest

from src.sparks.catalog import CatalogError
from src.sparks.errors import InsufficientFunds, InvalidRequest, NothingToSell, WrongPhase
from src.sparks.records import SparkRecord
from tests.sparks.env import CATALOG, Env, run
from tests.sparks.helpers import battle_record


def make(tmp_path):
    return Env(tmp_path / "s.sqlite3")


async def balance(env, owner="ann"):
    async with env.repo.transaction() as tx:
        return (await tx.get_player(owner)).insignia, await tx.emblem_counts(owner)


def test_emblem_prices_are_a_fifth_of_their_strength(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=1000)
        bought = await env.shop.buy_emblems("ann", "e1", "rare", 3)
        after = await balance(env)
        await env.close()
        return bought, after

    bought, (insignia, emblems) = run(scenario())
    assert bought["price"] == 120 and insignia == 880 and emblems == {"normal": 5, "rare": 3}


def test_forbidden_emblems_are_the_most_expensive(tmp_path):
    prices = {t.id: t.emblem_price for t in CATALOG.tiers}
    assert prices == {"normal": 20, "rare": 40, "legendary": 80, "royalty": 160, "ascended": 320, "forbidden": 640}


def test_not_enough_insignia_changes_nothing(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=50)
        with pytest.raises(InsufficientFunds):
            await env.shop.buy_emblems("ann", "e1", "rare", 2)
        result = await balance(env)
        await env.close()
        return result

    assert run(scenario()) == (50, {"normal": 5})


@pytest.mark.parametrize("quantity", [0, -1, 100, True, "3"])
def test_bad_quantities_are_rejected(tmp_path, quantity):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        with pytest.raises(InvalidRequest):
            await env.shop.buy_emblems("ann", "e1", "normal", quantity)
        await env.close()

    run(scenario())


def test_unknown_tier_is_a_catalog_error(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        with pytest.raises(CatalogError):
            await env.shop.buy_emblems("ann", "e1", "gold", 1)
        await env.close()

    run(scenario())


def test_buying_a_new_species_starts_it_at_level_one(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=1000)
        bought = await env.shop.buy_copies("ann", "c1", "sentinel", "normal")
        profile = await env.collection.profile("ann")
        await env.close()
        return bought, profile

    bought, profile = run(scenario())
    assert bought["price"] == 2 * 1 * 140 and bought["copies_granted"] == 1
    sentinel = next(s for s in profile["sparks"] if s["species_id"] == "sentinel")
    assert (sentinel["level"], sentinel["copies"]) == (1, 1) and profile["insignia"] == 1000 - 280


def test_buying_keeps_an_owned_species_level_and_prices_at_the_resulting_tier(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=5000, guardian=SparkRecord("ann", "guardian", 9, 11, 40))
        bought = await env.shop.buy_copies("ann", "c1", "guardian", "rare")  # 9 + 2 = 11 copies -> Rare
        profile = await env.collection.profile("ann")
        await env.close()
        return bought, profile

    bought, profile = run(scenario())
    assert bought["resulting_tier_id"] == "rare" and bought["copies_granted"] == 2
    assert bought["price"] == 2 * 2 * CATALOG.sale_value("guardian", "rare", 11)  # 2 x copies x resale at Rare, level 11
    guardian = profile["sparks"][0]
    assert (guardian["level"], guardian["xp"], guardian["copies"]) == (11, 40, 11)


def test_the_forbidden_species_and_tier_cannot_be_bought(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=10**6)
        with pytest.raises(InvalidRequest, match="captured"):
            await env.shop.buy_copies("ann", "c1", "forbidden", "normal")
        with pytest.raises(InvalidRequest, match="regular tiers"):
            await env.shop.buy_copies("ann", "c2", "sentinel", "forbidden")
        await env.close()

    run(scenario())


def test_selling_pays_the_value_before_the_copy_goes_and_can_downgrade(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(guardian=SparkRecord("ann", "guardian", 10, 11, 0))  # Rare at 10 copies
        sale = await env.shop.sell_copy("ann", "s1", "guardian")
        insignia, _ = await balance(env)
        await env.close()
        return sale, insignia

    sale, insignia = run(scenario())
    value = CATALOG.sale_value("guardian", "rare", 11)
    assert sale["value"] == value == insignia and sale["downgraded"] is True and sale["tier_id"] == "normal" and sale["copies"] == 9


def test_selling_never_removes_the_owned_spark_or_causes_fainting(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        with pytest.raises(NothingToSell):
            await env.shop.sell_copy("ann", "s1", "guardian")  # zero copies
        with pytest.raises(NothingToSell):
            await env.shop.sell_copy("ann", "s2", "sentinel")  # not owned
        await env.give(guardian=SparkRecord("ann", "guardian", 1, 1, 0))
        await env.shop.sell_copy("ann", "s3", "guardian")
        profile = await env.collection.profile("ann")
        await env.close()
        return profile["sparks"][0]

    spark = run(scenario())
    assert spark["copies"] == 0 and spark["fainted"] is False


@pytest.mark.parametrize("species_id", [s.id for s in CATALOG.regular_species()])
@pytest.mark.parametrize("package", ["normal", "rare", "legendary", "royalty", "ascended"])
@pytest.mark.parametrize("start_copies,level", [(0, 1), (8, 7), (39, 30), (99, 12), (249, 30)])
def test_buying_then_reselling_never_makes_a_profit(species_id, package, start_copies, level):
    owned = SparkRecord("ann", species_id, start_copies, level, 0)
    price, granted, resulting = _price(owned, package)
    resale = 0
    copies = owned.copies + granted
    for _ in range(granted):
        tier = CATALOG.tier_for_copies(species_id, copies)
        resale += CATALOG.sale_value(species_id, tier, level)
        copies -= 1
    assert resale < price


def _price(owned, package):
    from src.sparks.shop import ShopService

    return ShopService(None, CATALOG, None).copy_price(owned.species_id, owned, package)


def test_a_species_that_is_fighting_cannot_be_bought_or_sold_but_others_can(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=5000, guardian=SparkRecord("ann", "guardian", 3, 1, 0))
        async with env.repo.transaction() as tx:
            await tx.add_battle(battle_record())  # its fighter is the guardian species by default
        with pytest.raises(WrongPhase):
            await env.shop.buy_copies("ann", "c1", "guardian", "normal")
        with pytest.raises(WrongPhase):
            await env.shop.sell_copy("ann", "s1", "guardian")
        await env.shop.buy_copies("ann", "c2", "scout", "normal")
        await env.shop.buy_emblems("ann", "e1", "normal", 1)
        await env.close()

    run(scenario())


def test_a_retried_purchase_is_charged_once(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=1000)
        first = await env.shop.buy_emblems("ann", "same", "normal", 2)
        second = await env.shop.buy_emblems("ann", "same", "normal", 2)
        result = await balance(env)
        await env.close()
        return first, second, result

    first, second, (insignia, emblems) = run(scenario())
    assert first == second and insignia == 960 and emblems == {"normal": 7}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_collection.py tests/sparks/test_encounters.py tests/sparks/test_shop.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.collection'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/collection.py`

```python
"""A player's collection: profile, starter, personality pool and presets."""

from __future__ import annotations

from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.errors import AlreadyInitialized, InvalidRequest, NotFound
from src.sparks.idempotency import IdempotentWriter
from src.sparks.records import PersonalityRecord, PresetRecord, SparkRecord
from src.sparks.repository import SparkRepository, SparkTransaction
from src.sparks.runtime import Clock, RandomSource, new_id

PRESET_SLOTS = range(1, 6)
PRESET_SIZE = 3
DEFAULT_PAGE, MAX_PAGE = 50, 100


class CollectionService:
    def __init__(self, repository: SparkRepository, writer: IdempotentWriter, catalog: Catalog,
                 clock: Clock, rng: RandomSource, roll_cooldown_seconds: float) -> None:
        self._repo, self._writer, self._catalog = repository, writer, catalog
        self._clock, self._rng, self._cooldown = clock, rng, roll_cooldown_seconds

    # -- profile -------------------------------------------------------------------

    async def profile_view(self, tx: SparkTransaction, owner: str) -> dict[str, Any]:
        player = await tx.get_player(owner)
        if player is None:
            raise NotFound("no profile yet; choose a starter first")
        now = self._clock.now()
        sparks = []
        for spark in await tx.list_sparks(owner):
            species = self._catalog.species(spark.species_id)
            level_cap = self._catalog.level_cap(spark.species_id)
            sparks.append({
                "species_id": spark.species_id, "name": species.name, "level": spark.level, "xp": spark.xp,
                "xp_needed": None if spark.level >= level_cap else self._catalog.levels.xp_per_level * spark.level,
                "level_cap": level_cap, "copies": spark.copies,
                "tier_id": self._catalog.tier_for_copies(spark.species_id, spark.copies),
                "faint_until": spark.faint_until,
                "fainted": spark.faint_until is not None and spark.faint_until > now,
            })
        pending = await tx.pending_encounter(owner)
        active = await tx.active_battle(owner)
        return {
            "owner": owner, "insignia": player.insignia, "emblems": await tx.emblem_counts(owner), "sparks": sparks,
            "pending_encounter": pending.id if pending else None, "active_battle": active.id if active else None,
            "next_roll_at": None if player.last_roll_at is None else player.last_roll_at + self._cooldown,
        }

    async def profile(self, owner: str) -> dict[str, Any]:
        async with self._repo.transaction() as tx:
            return await self.profile_view(tx, owner)

    async def initialize(self, owner: str, key: str, starter_species_id: str) -> dict[str, Any]:
        """Create the profile once: a level-1 starter with one random tier-1 personality in preset 1."""
        starters = {s.id for s in self._catalog.starter_species()}
        if starter_species_id not in starters:
            raise InvalidRequest(f"choose a starter from: {', '.join(sorted(starters))}")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            if await tx.get_player(owner) is not None:
                raise AlreadyInitialized("this profile already exists")
            now = self._clock.now()
            await tx.create_player(owner, now)
            for tier_id, count in self._catalog.economy.starter_emblems.items():
                await tx.add_emblems(owner, tier_id, count)
            await tx.put_spark(SparkRecord(owner, starter_species_id, 0, 1, 0))
            types = list(self._catalog.personalities)
            type_id = types[min(int(self._rng.next() * len(types)), len(types) - 1)]
            personality = PersonalityRecord(new_id(), owner, starter_species_id, type_id,
                                            self._catalog.economy.starter_personality_tier, now)
            await tx.add_personality(personality)
            await tx.put_preset(PresetRecord(owner, starter_species_id, 1, (personality.id,)))
            return await self.profile_view(tx, owner)

        return await self._writer.commit(owner, key, "profile.initialize", {"starter": starter_species_id}, work)

    # -- personalities and presets -------------------------------------------------

    async def _require_spark(self, tx: SparkTransaction, owner: str, species_id: str) -> None:
        if not self._catalog.has_species(species_id) or await tx.get_spark(owner, species_id) is None:
            raise NotFound("you do not own that species")

    async def personalities(self, owner: str, species_id: str, limit: int | None, cursor: int) -> dict[str, Any]:
        limit = DEFAULT_PAGE if limit is None else limit
        if not 1 <= limit <= MAX_PAGE:
            raise InvalidRequest(f"limit must be from 1 to {MAX_PAGE}")
        async with self._repo.transaction() as tx:
            await self._require_spark(tx, owner, species_id)
            rows = await tx.list_personalities(owner, species_id, limit + 1, max(cursor, 0))
        page = rows[:limit]
        return {
            "items": [{"id": r.id, "type": r.type_id, "tier": r.tier} for r in page],
            "next_cursor": page[-1].seq if len(rows) > limit else None,
        }

    async def get_preset(self, owner: str, species_id: str, slot: int) -> dict[str, Any]:
        self._check_slot(slot)
        async with self._repo.transaction() as tx:
            await self._require_spark(tx, owner, species_id)
            preset = await tx.get_preset(owner, species_id, slot)
        return {"species_id": species_id, "slot": slot, "instance_ids": list(preset.instance_ids) if preset else []}

    @staticmethod
    def _check_slot(slot: int) -> None:
        if slot not in PRESET_SLOTS:
            raise InvalidRequest(f"preset slot must be from {PRESET_SLOTS.start} to {PRESET_SLOTS.stop - 1}")

    async def put_preset(self, owner: str, key: str, species_id: str, slot: int, instance_ids: list[str]) -> dict[str, Any]:
        """Equip up to three distinct personality instances of this species. The same
        instance may appear in several presets."""
        self._check_slot(slot)
        if not isinstance(instance_ids, list) or len(instance_ids) > PRESET_SIZE or len(set(instance_ids)) != len(instance_ids):
            raise InvalidRequest(f"a preset holds up to {PRESET_SIZE} distinct personality instances")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            await self._require_spark(tx, owner, species_id)
            found = await tx.get_personalities(owner, species_id, instance_ids)
            if len(found) != len(instance_ids):
                raise InvalidRequest("every instance must be one of this species' collected personalities")
            await tx.put_preset(PresetRecord(owner, species_id, slot, tuple(instance_ids)))
            return {"species_id": species_id, "slot": slot, "instance_ids": list(instance_ids)}

        return await self._writer.commit(
            owner, key, "preset.put", {"species": species_id, "slot": slot, "ids": instance_ids}, work)
```

`apps/mini_games/src/sparks/encounters.py`

```python
"""Wild encounters: roll a preview, decline it, and hand it to a battle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.errors import ActiveBattleExists, EncounterCooldown, InvalidRequest, NotFound, WrongPhase
from src.sparks.idempotency import IdempotentWriter
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord
from src.sparks.repository import SparkRepository, SparkTransaction
from src.sparks.runtime import Clock, RandomSource, new_id


@dataclass(frozen=True)
class RolledEncounter:
    species_id: str
    tier_id: str
    level: int
    personalities: tuple[PersonalityInstance, ...]


class EncounterRoller:
    """The random draws behind an encounter. Pure given the random source."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    @staticmethod
    def _pick(count: int, u: float) -> int:
        return min(int(u * count), count - 1)

    def _tier(self, u: float) -> str:
        cumulative = 0.0
        for tier in self._catalog.tiers:
            cumulative += tier.encounter_probability
            if u < cumulative:
                return tier.id
        return self._catalog.tiers[-1].id

    def roll(self, highest_level: int, rng: RandomSource) -> RolledEncounter:
        tier_id = self._tier(rng.next())
        if tier_id == self._catalog.forbidden_tier.id:
            species = self._catalog.forbidden_species()
        else:
            regular = self._catalog.regular_species()
            species = regular[self._pick(len(regular), rng.next())]
        cap = self._catalog.level_cap(species.id)
        window = self._catalog.economy.encounter_level_window
        low = min(max(highest_level - window, 1), cap)
        high = min(max(highest_level + window, 1), cap)
        level = low + self._pick(high - low + 1, rng.next())
        types = list(self._catalog.personalities)
        tier_odds = self._catalog.economy.personality_tier_probabilities
        instances = []
        for index in range(1 + self._pick(3, rng.next())):
            type_id = types[self._pick(len(types), rng.next())]
            u, tier, cumulative = rng.next(), len(tier_odds), 0.0
            for number, probability in enumerate(tier_odds, start=1):
                cumulative += probability
                if u < cumulative:
                    tier = number
                    break
            instances.append(PersonalityInstance(new_id(), type_id, tier))
        return RolledEncounter(species.id, tier_id, level, tuple(instances))


class EncounterService:
    def __init__(self, repository: SparkRepository, writer: IdempotentWriter, catalog: Catalog,
                 clock: Clock, rng: RandomSource, cooldown_seconds: float) -> None:
        self._repo, self._writer, self._catalog = repository, writer, catalog
        self._clock, self._rng, self._cooldown = clock, rng, cooldown_seconds
        self._roller = EncounterRoller(catalog)

    def preview(self, record: EncounterRecord) -> dict[str, Any]:
        """What the player may see: species, tier and level, never the personalities."""
        species = self._catalog.species(record.species_id)
        return {"id": record.id, "species_id": record.species_id, "name": species.name,
                "tier_id": record.tier_id, "level": record.level, "status": record.status,
                "created_at": record.created_at}

    async def roll(self, owner: str, key: str) -> dict[str, Any]:
        async def work(tx: SparkTransaction) -> dict[str, Any]:
            player = await tx.get_player(owner)
            if player is None:
                raise NotFound("no profile yet; choose a starter first")
            if await tx.active_battle(owner) is not None:
                raise ActiveBattleExists("finish or forfeit the active battle first")
            now = self._clock.now()
            if player.last_roll_at is not None and now - player.last_roll_at < self._cooldown:
                raise EncounterCooldown(self._cooldown - (now - player.last_roll_at))
            previous = await tx.pending_encounter(owner)
            if previous is not None:
                await tx.set_encounter_status(previous.id, "expired")
            highest = max(s.level for s in await tx.list_sparks(owner))
            rolled = self._roller.roll(highest, self._rng)
            record = EncounterRecord(new_id(), owner, rolled.species_id, rolled.tier_id, rolled.level, "pending",
                                     rolled.personalities, now)
            await tx.add_encounter(record)
            await tx.set_last_roll(owner, now)
            return self.preview(record)

        return await self._writer.commit(owner, key, "encounter.roll", {}, work)

    async def get(self, owner: str, encounter_id: str) -> dict[str, Any]:
        async with self._repo.transaction() as tx:
            record = await tx.get_encounter(owner, encounter_id)
        if record is None:
            raise NotFound("no such encounter")
        return self.preview(record)

    async def decline(self, owner: str, key: str, encounter_id: str) -> dict[str, Any]:
        if not encounter_id:
            raise InvalidRequest("an encounter id is required")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            record = await tx.get_encounter(owner, encounter_id)
            if record is None:
                raise NotFound("no such encounter")
            if record.status != "pending":
                raise WrongPhase(f"this encounter is already {record.status}")
            await tx.set_encounter_status(record.id, "declined")
            return self.preview(EncounterRecord(**{**record.__dict__, "status": "declined"}))

        return await self._writer.commit(owner, key, "encounter.decline", {"id": encounter_id}, work)
```

`apps/mini_games/src/sparks/shop.py`

```python
"""The shop: buy EMBLEMs and regular-species copies, sell copies back."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.errors import InsufficientFunds, InvalidRequest, NotFound, NothingToSell, WrongPhase
from src.sparks.idempotency import IdempotentWriter
from src.sparks.progression import ProgressionService
from src.sparks.records import SparkRecord
from src.sparks.repository import SparkTransaction

MAX_EMBLEM_PURCHASE = 99


class ShopService:
    def __init__(self, writer: IdempotentWriter, catalog: Catalog, progression: ProgressionService) -> None:
        self._writer, self._catalog, self._progression = writer, catalog, progression

    # -- prices --------------------------------------------------------------------

    def copy_price(self, species_id: str, owned: SparkRecord | None, tier_id: str) -> tuple[int, int, str]:
        """(price, copies granted, resulting tier) for buying the regular `tier_id` package.
        The price is twice the resale value of the granted copies at the resulting tier and level."""
        granted = self._catalog.tier(tier_id).copy_reward
        copies = (owned.copies if owned else 0) + granted
        resulting = self._catalog.tier_for_copies(species_id, copies)
        level = owned.level if owned else 1
        per_copy = self._catalog.sale_value(species_id, resulting, level)
        return self._catalog.economy.purchase_factor * granted * per_copy, granted, resulting

    # -- operations ----------------------------------------------------------------

    @staticmethod
    async def _spend(tx: SparkTransaction, owner: str, price: int) -> None:
        player = await tx.get_player(owner)
        if player is None:
            raise NotFound("no profile yet; choose a starter first")
        if player.insignia < price:
            raise InsufficientFunds(f"that costs {price} Insignia and you have {player.insignia}")
        await tx.add_insignia(owner, -price)

    @staticmethod
    async def _reject_if_fighting(tx: SparkTransaction, owner: str, species_id: str) -> None:
        battle = await tx.active_battle(owner)
        if battle is not None and battle.setup.player.species_id == species_id:
            raise WrongPhase("that species is fighting in the active battle")

    async def buy_emblems(self, owner: str, key: str, tier_id: str, quantity: int) -> dict[str, Any]:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_EMBLEM_PURCHASE:
            raise InvalidRequest(f"quantity must be a whole number from 1 to {MAX_EMBLEM_PURCHASE}")
        tier = self._catalog.tier(tier_id)  # forbidden EMBLEMs are sold too

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            price = tier.emblem_price * quantity
            await self._spend(tx, owner, price)
            await tx.add_emblems(owner, tier_id, quantity)
            return {"kind": "emblems", "tier_id": tier_id, "quantity": quantity, "price": price}

        return await self._writer.commit(owner, key, "shop.emblems", {"tier": tier_id, "quantity": quantity}, work)

    async def buy_copies(self, owner: str, key: str, species_id: str, tier_id: str) -> dict[str, Any]:
        species = self._catalog.species(species_id)
        if species.forbidden:
            raise InvalidRequest("the Forbidden species can only be captured")
        if self._catalog.tier(tier_id).copy_threshold is None:
            raise InvalidRequest("choose one of the five regular tiers")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            await self._reject_if_fighting(tx, owner, species_id)
            owned = await tx.get_spark(owner, species_id)
            price, granted, resulting = self.copy_price(species_id, owned, tier_id)
            await self._spend(tx, owner, price)
            if owned is None:
                await tx.put_spark(SparkRecord(owner, species_id, granted, 1, 0))
            else:
                await tx.put_spark(replace(owned, copies=owned.copies + granted))
            return {"kind": "copies", "species_id": species_id, "tier_id": tier_id, "copies_granted": granted,
                    "price": price, "resulting_tier_id": resulting}

        return await self._writer.commit(owner, key, "shop.copies", {"species": species_id, "tier": tier_id}, work)

    async def sell_copy(self, owner: str, key: str, species_id: str) -> dict[str, Any]:
        self._catalog.species(species_id)

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            await self._reject_if_fighting(tx, owner, species_id)
            owned = await tx.get_spark(owner, species_id)
            if owned is None or owned.copies == 0:
                raise NothingToSell("there is no absorbed copy to sell")
            before = self._catalog.tier_for_copies(species_id, owned.copies)
            value = self._catalog.sale_value(species_id, before, owned.level)  # tier and level before the copy goes
            await tx.put_spark(replace(owned, copies=owned.copies - 1))
            await tx.add_insignia(owner, value)
            after = self._catalog.tier_for_copies(species_id, owned.copies - 1)
            return {"kind": "sale", "species_id": species_id, "value": value, "copies": owned.copies - 1,
                    "tier_id": after, "downgraded": after != before}

        return await self._writer.commit(owner, key, "shop.sell", {"species": species_id}, work)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_collection.py tests/sparks/test_encounters.py tests/sparks/test_shop.py -q`
Expected: 199 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/collection.py apps/mini_games/src/sparks/encounters.py apps/mini_games/src/sparks/shop.py apps/mini_games/tests/sparks/env.py apps/mini_games/tests/sparks/test_collection.py apps/mini_games/tests/sparks/test_encounters.py apps/mini_games/tests/sparks/test_shop.py
git commit -m "feat(mini_games): collection, encounters and shop services"
```

---

### Task 12: The round coordinator

**Files:**
- Create: `apps/mini_games/src/sparks/decider.py`, `src/sparks/battle_view.py`, `src/sparks/emblem_picker.py`, `src/sparks/coordinator.py`
- Test: `apps/mini_games/tests/sparks/test_coordinator.py`

**Interfaces:**
- Consumes: Tasks 4 to 11.
- Produces: `Decision(action, audit)` and `ActionDecider(catalog, engine, policy, mood, reader, views).decide(setup, state, side, instances, rng, *, can_collect)` (reads public state, draws the mood, builds the probabilities, draws the action); `BattleViewBuilder(engine, catalog)` with `build(record, emblems, now)`, `permitted_tiers(emblems, limit)`, `tiers_up_to(limit)` (the public JSON: stats, effects, legal actions, history, EMBLEM prompt, result; never the wild personalities, pending action, mood or probabilities); `EmblemPicker` protocol and `LayaEmblemPicker(client)` (`pick(view, chances) -> tier | None`; a single option needs no question).
- Produces: `RoundCoordinator(repository, writer, catalog, engine, decider, situation_views, emblem_picker, progression, battle_views, clock, settings)` and `CoordinatorSettings(emblem_prompt_seconds)` with `start(owner, key, *, encounter_id, species_id, preset_slot, mode, emblem_limit)`, `view(owner, battle_id)`, `submit_action(owner, key, battle_id, *, round, revision, action)`, `advance(owner, key, battle_id, *, round, revision)`, `answer_emblem(owner, key, battle_id, *, round, revision, tier)`, `set_mode(owner, key, battle_id, *, round, revision, mode, emblem_limit)`, `forfeit(owner, key, battle_id)`. Each returns the public battle view (a dict).
- Behaviour: the wild Spark's action is decided from public state before the player's action is read; a round's choices, resolution, EMBLEM spent, checkpoint and (at the end) rewards commit in one transaction; the only choice stored before a reveal is the wild action and the player's CATCH intent while the five-second prompt is open (`phase = awaiting_emblem`, `pending` holds both and the deadline); the battle's random stream is `SeededRandom(rng_seed, rng_counter)` and its counter is saved with every checkpoint; round and revision must match (409 otherwise); `lock` resolves one battle at a time; the preset's personalities are frozen at start; closing the view needs no server state (nobody calls `advance`).
- Phases: `choosing`, `awaiting_emblem`, `terminal` are persisted. The spec's `locked` and `resolved` phases are transient inside one transaction, so a crash can never leave a half-resolved round.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_coordinator.py`

```python
import asyncio
import json

import pytest

import src.sparks.coordinator as coordinator_module
from src.sparks.errors import (
    ActiveBattleExists,
    BattleFinished,
    DeadlinePassed,
    IdempotencyConflict,
    InsufficientEmblems,
    InvalidRequest,
    NotFound,
    SparkFainted,
    StaleBattle,
    WrongPhase,
)
from src.sparks.models import PersonalityInstance
from src.sparks.records import EncounterRecord, SparkRecord
from tests.sparks.env import Env, run
from tests.sparks.helpers import ScriptedPolicy

COWARD = PersonalityInstance("wild-secret-1", "COWARD", 2)
BOLD = PersonalityInstance("wild-secret-2", "BOLD", 3)
SECRET_WORDS = ("COWARD", "BOLD", "wild-secret-1", "wild-secret-2")  # hidden wild personalities; ids that cannot occur by chance


@pytest.fixture(autouse=True)
def fixed_seed(monkeypatch):
    monkeypatch.setattr(coordinator_module, "new_seed", lambda: 7)


def make(tmp_path, **kwargs):
    return Env(tmp_path / "s.sqlite3", **kwargs)


async def encounter(env, species="scout", tier="normal", level=1, instances=(COWARD, BOLD), eid="e1", owner="ann"):
    async with env.repo.transaction() as tx:
        await tx.add_encounter(EncounterRecord(eid, owner, species, tier, level, "pending", tuple(instances), env.clock.now()))
    return eid


async def strong_guardian(env, copies=250, level=30):
    await env.give(guardian=SparkRecord("ann", "guardian", copies, level, 0))


async def begin(env, coord, mode="manual", eid=None, slot=1, limit=None, **enc):
    eid = eid or await encounter(env, **enc)
    return await coord.start("ann", env.key(), encounter_id=eid, species_id="guardian", preset_slot=slot,
                             mode=mode, emblem_limit=limit)


def act(coord, env, view, kind="attack", **extra):
    return coord.submit_action("ann", env.key(), view["id"], round=view["round"], revision=view["revision"],
                               action={"kind": kind, **extra})


def advance(coord, env, view):
    return coord.advance("ann", env.key(), view["id"], round=view["round"], revision=view["revision"])


async def stats(env):
    async with env.repo.transaction() as tx:
        return (await tx.get_player("ann")).insignia, await tx.emblem_counts("ann"), {s.species_id: s for s in await tx.list_sparks("ann")}


# -- starting ------------------------------------------------------------------------

def test_start_creates_a_public_view_and_marks_the_encounter(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        view = await begin(env, env.coordinator())
        async with env.repo.transaction() as tx:
            enc = await tx.get_encounter("ann", "e1")
            active = (await tx.active_battle("ann")).id
        await env.close()
        return view, enc, active

    view, enc, active = run(scenario())
    assert (view["status"], view["phase"], view["mode"], view["round"], view["revision"]) == ("active", "choosing", "manual", 1, 1)
    assert enc.status == "started" and active == view["id"]
    assert view["player"]["species_id"] == "guardian" and view["wild"]["species_id"] == "scout"
    assert {"attack", "flee", "catch"} <= {a["kind"] for a in view["actions"]}
    assert not any(word in json.dumps(view) for word in SECRET_WORDS)


def test_start_validates_its_inputs(tmp_path):
    async def scenario():
        env = make(tmp_path)
        coord = env.coordinator()
        await env.start_player()
        eid = await encounter(env)
        base = dict(encounter_id=eid, species_id="guardian", preset_slot=1, mode="manual", emblem_limit=None)
        for bad in (dict(mode="turbo"), dict(mode="autonomous", emblem_limit=None), dict(mode="autonomous", preset_slot=None, emblem_limit="normal"),
                    dict(emblem_limit="gold"), dict(species_id="nope")):
            with pytest.raises(InvalidRequest):
                await coord.start("ann", env.key(), **{**base, **bad})
        with pytest.raises(NotFound):
            await coord.start("ann", env.key(), **{**base, "encounter_id": "nope"})
        with pytest.raises(NotFound):
            await coord.start("ann", env.key(), **{**base, "species_id": "scout"})  # not owned
        await env.close()

    run(scenario())


def test_an_empty_preset_cannot_play_autonomously_but_can_play_manually(tmp_path):
    async def scenario():
        env = make(tmp_path)
        coord = env.coordinator()
        await env.start_player()
        eid = await encounter(env)
        with pytest.raises(InvalidRequest, match="no personalities"):
            await coord.start("ann", env.key(), encounter_id=eid, species_id="guardian", preset_slot=2, mode="autonomous", emblem_limit="normal")
        view = await coord.start("ann", env.key(), encounter_id=eid, species_id="guardian", preset_slot=2, mode="manual", emblem_limit=None)
        await env.close()
        return view

    assert run(scenario())["mode"] == "manual"


def test_a_fainted_spark_cannot_start_a_battle(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(guardian=SparkRecord("ann", "guardian", 0, 1, 0, faint_until=env.clock.now() + 100))
        with pytest.raises(SparkFainted):
            await begin(env, env.coordinator())
        env.clock.advance(101)
        view = await begin(env, env.coordinator(), eid="e1")
        await env.close()
        return view

    assert run(scenario())["status"] == "active"


def test_one_active_battle_at_a_time_and_encounters_are_single_use(tmp_path):
    async def scenario():
        env = make(tmp_path)
        coord = env.coordinator()
        await env.start_player()
        await begin(env, coord)
        second = await encounter(env, eid="e2")
        with pytest.raises(ActiveBattleExists):
            await begin(env, coord, eid=second)
        with pytest.raises(WrongPhase):
            await begin(env, coord, eid="e1")  # e1 was already used
        await env.close()

    run(scenario())


def test_the_preset_is_frozen_for_the_battle(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord, mode="autonomous", limit="normal")
        await env.collection.put_preset("ann", env.key(), "guardian", 1, [])  # edited after the fight began
        record, _ = await coord._load("ann", view["id"])
        await env.close()
        return record

    assert len(run(scenario()).player_personalities) == 1


# -- manual rounds -------------------------------------------------------------------

def test_a_manual_round_resolves_and_advances_the_checkpoint(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"]))
        view = await begin(env, coord)
        after = await act(coord, env, view)
        await env.close()
        return view, after

    view, after = run(scenario())
    assert (after["round"], after["revision"], after["phase"]) in {(2, 2, "choosing"), (1, 2, "terminal")}
    assert len(after["history"]) == 1 and after["history"][0]["actions"]["player"] == ["attack", "ATTACK"]
    assert not any(word in json.dumps(after) for word in SECRET_WORDS)


def test_stale_round_or_revision_is_a_conflict(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 5))
        view = await begin(env, coord)
        await act(coord, env, view)
        for round_, revision in ((view["round"], view["revision"]), (view["round"] + 5, view["revision"] + 1)):
            with pytest.raises(StaleBattle):
                await coord.submit_action("ann", env.key(), view["id"], round=round_, revision=revision, action={"kind": "attack"})
        await env.close()

    run(scenario())


def test_a_retry_with_the_same_key_returns_the_first_result_and_applies_once(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 3))
        view = await begin(env, coord)
        first = await coord.submit_action("ann", "same", view["id"], round=1, revision=1, action={"kind": "attack"})
        again = await coord.submit_action("ann", "same", view["id"], round=1, revision=1, action={"kind": "attack"})
        with pytest.raises(IdempotencyConflict):
            await coord.submit_action("ann", "same", view["id"], round=1, revision=1, action={"kind": "flee"})
        await env.close()
        return first, again

    first, again = run(scenario())
    assert first == again and len(first["history"]) == 1


@pytest.mark.parametrize("action", [{"kind": "dance"}, {"kind": "ability", "ability_id": "nope"}, {"kind": "catch"}, {"kind": "catch", "emblem_tier": "gold"}])
def test_illegal_manual_actions_are_rejected_without_changing_the_battle(tmp_path, action):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord)
        with pytest.raises(InvalidRequest):
            await coord.submit_action("ann", env.key(), view["id"], round=1, revision=1, action=action)
        after = await coord.view("ann", view["id"])
        await env.close()
        return view, after

    view, after = run(scenario())
    assert after == view


def test_catching_needs_an_emblem_of_that_tier(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord)
        with pytest.raises(InsufficientEmblems):
            await act(coord, env, view, "catch", emblem_tier="rare")
        await env.close()

    run(scenario())


def test_an_ability_on_cooldown_is_not_offered_again(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 5))
        view = await begin(env, coord)
        after = await act(coord, env, view, "ability", ability_id="guardian_bulwark")
        offered = [a.get("ability_id") for a in after["actions"]]
        with pytest.raises(InvalidRequest):
            await act(coord, env, after, "ability", ability_id="guardian_bulwark")
        await env.close()
        return offered

    assert "guardian_bulwark" not in run(scenario())


def test_the_wild_decision_cannot_depend_on_the_players_action(tmp_path):
    async def one(kind):
        env = Env(tmp_path / f"{kind}.sqlite3")
        await env.start_player()
        policy = ScriptedPolicy()
        coord = env.coordinator(policy)
        view = await begin(env, coord)
        views_seen = []
        original = coord._decider._reader.read

        async def spy(situation_view):
            views_seen.append(situation_view)
            return await original(situation_view)

        coord._decider._reader.read = spy
        await act(coord, env, view, kind)
        await env.close()
        return views_seen, [c for c in policy.contexts if not c.collector]

    attack_views, attack_ctx = run(one("attack"))
    flee_views, flee_ctx = run(one("flee"))
    assert attack_views == flee_views and attack_ctx == flee_ctx  # identical inputs whatever the player chose


# -- endings -------------------------------------------------------------------------

def test_a_win_pays_out_exactly_once(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        coord = env.coordinator(ScriptedPolicy(wild=["flee"]))
        view = await begin(env, coord, level=1)
        done = await coord.submit_action("ann", "win", view["id"], round=1, revision=1, action={"kind": "attack"})
        replay = await coord.submit_action("ann", "win", view["id"], round=1, revision=1, action={"kind": "attack"})
        with pytest.raises(BattleFinished):
            await act(coord, env, view)
        after = await stats(env)
        await env.close()
        return done, replay, after

    done, replay, (insignia, emblems, sparks) = run(scenario())
    assert done == replay and done["status"] == "terminal" and done["result"]["kind"] == "won"
    assert insignia == 10 and done["result"]["xp"] == 20 and sparks["guardian"].faint_until is None and emblems == {"normal": 5}


def test_a_knockout_faints_the_fighter_for_five_minutes_without_copy_loss(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(guardian=SparkRecord("ann", "guardian", 3, 1, 0))
        coord = env.coordinator(ScriptedPolicy())
        view = await begin(env, coord, species="forbidden", tier="forbidden", level=50)
        done = await act(coord, env, view)
        while done["status"] == "active":
            done = await act(coord, env, done)
        sparks = (await stats(env))[2]
        await env.close()
        return done, sparks["guardian"], env.clock.now()

    done, guardian, now = run(scenario())
    assert done["result"]["kind"] == "knocked_out" and guardian.copies == 3 and guardian.faint_until == now + 300


def test_a_successful_escape_ends_without_rewards_or_fainting(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        coord = env.coordinator(ScriptedPolicy(wild=["catch"]))
        view = await begin(env, coord, level=1)
        outcome = None
        for _ in range(60):  # FLEE is a roll; keep trying until it lands
            outcome = await act(coord, env, view, "flee")
            if outcome["status"] == "terminal":
                break
            view = outcome
        sparks = (await stats(env))
        await env.close()
        return outcome, sparks

    outcome, (insignia, _, sparks) = run(scenario())
    assert outcome["result"] == {"kind": "escaped"} and insignia == 0 and sparks["guardian"].faint_until is None


def test_a_capture_reveals_every_source_personality_and_spends_the_emblem(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        async with env.repo.transaction() as tx:
            await tx.add_emblems("ann", "ascended", 40)
        coord = env.coordinator(ScriptedPolicy())  # the wild Spark only attacks, so nothing preempts the attempt
        view = await begin(env, coord, species="channeler", level=1)
        outcome = view
        for _ in range(100):
            outcome = await act(coord, env, view, "catch", emblem_tier="ascended")
            if outcome["status"] == "terminal":
                break
            view = outcome
        after = await stats(env)
        async with env.repo.transaction() as tx:
            pool = await tx.list_personalities("ann", "channeler", 50, 0)
        await env.close()
        return outcome, after, pool

    outcome, (insignia, emblems, sparks), pool = run(scenario())
    result = outcome["result"]
    assert result["kind"] == "captured" and {p["type"] for p in result["revealed_personalities"]} == {"COWARD", "BOLD"}
    assert len(pool) == 1 and result["awarded_personality"]["type"] in {"COWARD", "BOLD"}
    assert sparks["channeler"].level == 1 and sparks["channeler"].copies == 1 and insignia == 10
    assert emblems["ascended"] == 40 - len(outcome["history"])  # one EMBLEM per attempt, win or lose


def test_a_failed_collection_attempt_still_costs_the_emblem(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)  # 1462 HP survives one hit from the level-50 Forbidden Spark
        coord = env.coordinator(ScriptedPolicy())
        view = await begin(env, coord, species="forbidden", tier="forbidden", level=50)
        after = await act(coord, env, view, "catch", emblem_tier="normal")  # 100 / (100 + 12800): about 0.8%
        counts = (await stats(env))[1]
        await env.close()
        return after, counts

    after, counts = run(scenario())
    assert counts == {"normal": 4}
    assert after["status"] == "active" and after["result"] is None and len(after["history"]) == 1


def test_forfeit_ends_the_battle_as_a_loss_and_is_final(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord)
        done = await coord.forfeit("ann", "f1", view["id"])
        replay = await coord.forfeit("ann", "f1", view["id"])
        with pytest.raises(BattleFinished):
            await coord.forfeit("ann", "f2", view["id"])
        with pytest.raises(BattleFinished):
            await act(coord, env, view)
        sparks = (await stats(env))[2]
        profile = await env.collection.profile("ann")
        await env.close()
        return done, replay, sparks, profile, env.clock.now()

    done, replay, sparks, profile, now = run(scenario())
    assert done == replay and done["result"]["kind"] == "forfeited" and sparks["guardian"].faint_until == now + 300
    assert profile["active_battle"] is None


def test_forfeit_and_resolution_race_leaves_one_consistent_ending(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await strong_guardian(env)
        coord = env.coordinator(ScriptedPolicy(wild=["flee"]))
        view = await begin(env, coord, level=1)
        results = await asyncio.gather(
            coord.submit_action("ann", "a", view["id"], round=1, revision=1, action={"kind": "attack"}),
            coord.forfeit("ann", "f", view["id"]),
            return_exceptions=True,
        )
        final = await coord.view("ann", view["id"])
        insignia, _, sparks = await stats(env)
        await env.close()
        return results, final, insignia, sparks["guardian"]

    results, final, insignia, guardian = run(scenario())
    kinds = {final["result"]["kind"]}
    assert kinds <= {"won", "forfeited"} and sum(isinstance(r, Exception) for r in results) == 1
    assert (final["result"]["kind"] == "won") == (insignia == 10) and (final["result"]["kind"] == "forfeited") == (guardian.faint_until is not None)


def test_other_owners_cannot_see_or_touch_a_battle(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player("ann")
        await env.start_player("bob")
        coord = env.coordinator()
        view = await begin(env, coord)
        with pytest.raises(NotFound):
            await coord.view("bob", view["id"])
        with pytest.raises(NotFound):
            await coord.submit_action("bob", "k", view["id"], round=1, revision=1, action={"kind": "attack"})
        with pytest.raises(NotFound):
            await coord.forfeit("bob", "k", view["id"])
        await env.close()

    run(scenario())


# -- autonomous rounds and the EMBLEM prompt -----------------------------------------

def test_an_autonomous_round_plays_without_input(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(player=["attack"], wild=["flee"]))
        view = await begin(env, coord, mode="autonomous", limit="normal")
        with pytest.raises(WrongPhase):
            await act(coord, env, view)
        after = await advance(coord, env, view)
        await env.close()
        return after

    after = run(scenario())
    assert len(after["history"]) == 1 and after["history"][0]["actions"]["player"][0] == "attack"


def catch_battle(tmp_path, *, laya=None, emblems=None, limit="rare", reader_policy=None, kwargs=None):
    async def setup():
        env = Env(tmp_path / "s.sqlite3")
        await env.start_player()
        await strong_guardian(env)  # survives the wild attack, so the CATCH is never preempted
        async with env.repo.transaction() as tx:
            for tier, count in (emblems or {"rare": 2, "royalty": 1}).items():
                await tx.add_emblems("ann", tier, count)
        coord = env.coordinator(ScriptedPolicy(player=["catch"], wild=["attack"]), laya=laya)
        view = await begin(env, coord, mode="autonomous", limit=limit, species="channeler", tier="normal", level=1)
        return env, coord, view

    return setup()


def test_an_autonomous_catch_opens_a_five_second_prompt(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        again = await coord.advance("ann", env.key(), view["id"], round=1, revision=prompt["revision"])
        await env.close()
        return view, prompt, again

    view, prompt, again = run(scenario())
    assert prompt["phase"] == "awaiting_emblem" and prompt["prompt"]["seconds_left"] == 5.0
    assert prompt["prompt"]["permitted_tiers"] == ["normal", "rare"] and prompt["history"] == []
    assert again == prompt  # still waiting for the player: nothing changes before the deadline
    assert not any(word in json.dumps(prompt) for word in SECRET_WORDS + ("wild_action",))


def test_the_player_can_answer_with_any_owned_emblem_even_above_the_limit(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        env.clock.advance(2)
        done = await coord.answer_emblem("ann", env.key(), view["id"], round=1, revision=prompt["revision"], tier="royalty")
        counts = (await stats(env))[1]
        await env.close()
        return done, counts

    done, counts = run(scenario())
    assert "royalty" not in counts and done["history"][0]["actions"]["player"][0] == "catch"


def test_a_late_answer_is_refused(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        env.clock.advance(5)
        with pytest.raises(DeadlinePassed):
            await coord.answer_emblem("ann", env.key(), view["id"], round=1, revision=prompt["revision"], tier="rare")
        counts = (await stats(env))[1]
        await env.close()
        return counts

    assert run(scenario()) == {"normal": 5, "rare": 2, "royalty": 1}


def test_an_answer_needs_an_owned_emblem(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        with pytest.raises(InsufficientEmblems):
            await coord.answer_emblem("ann", env.key(), view["id"], round=1, revision=prompt["revision"], tier="ascended")
        await env.close()

    run(scenario())


def test_after_the_deadline_laya_picks_within_the_limit(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path, laya=FakeEngineWith("rare"))
        prompt = await advance(coord, env, view)
        env.clock.advance(6)
        done = await advance(coord, env, prompt)
        counts = (await stats(env))[1]
        await env.close()
        return done, counts

    done, counts = run(scenario())
    assert done["history"][0]["actions"]["player"][0] == "catch" and counts["rare"] == 1 and counts["royalty"] == 1


def FakeEngineWith(pick):
    from tests.fake_laya import FakeEngine

    return FakeEngine(pick=pick, confidence=0.95)


@pytest.mark.parametrize("laya_factory", [
    lambda: None,  # no Laya at all
    lambda: __import__("tests.fake_laya", fromlist=["FakeEngine"]).FakeEngine(confidence=0.3),  # uncertain
    lambda: __import__("tests.fake_laya", fromlist=["FakeEngine"]).FakeEngine(raw={"choice": {"choice": "gold", "probabilities": {}, "answer_confidence": 0.9}}),  # invalid
])
def test_when_laya_cannot_choose_the_catch_becomes_basic_attack_and_nothing_is_spent(tmp_path, laya_factory):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path, laya=laya_factory())
        prompt = await advance(coord, env, view)
        env.clock.advance(6)
        done = await advance(coord, env, prompt)
        counts = (await stats(env))[1]
        await env.close()
        return done, counts

    done, counts = run(scenario())
    assert done["history"][0]["actions"]["player"] == ["attack", "ATTACK"] and counts == {"normal": 5, "rare": 2, "royalty": 1}


def test_with_no_permitted_emblem_at_the_deadline_it_falls_back_to_attack(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path, emblems={"rare": 1}, limit="rare")
        prompt = await advance(coord, env, view)
        async with env.repo.transaction() as tx:  # the permitted EMBLEMs vanish while the prompt is open
            await tx.add_emblems("ann", "rare", -1)
            await tx.add_emblems("ann", "normal", -5)
        env.clock.advance(6)
        done = await advance(coord, env, prompt)
        await env.close()
        return done

    assert run(scenario())["history"][0]["actions"]["player"][0] == "attack"


def test_an_open_prompt_survives_a_restart_and_keeps_its_deadline(tmp_path):
    async def first():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        now = env.clock.now()
        await env.close()
        return prompt, now

    async def second(prompt, now, wait):
        env = Env(tmp_path / "s.sqlite3")
        env.clock.t = now + wait
        coord = env.coordinator(ScriptedPolicy(player=["flee"], wild=["flee"]))  # a rerolled choice would differ
        resumed = await coord.view("ann", prompt["id"])
        result = await coord.answer_emblem("ann", env.key(), prompt["id"], round=1, revision=prompt["revision"], tier="rare")
        await env.close()
        return resumed, result

    prompt, now = run(first())
    resumed, result = run(second(prompt, now, 3))
    assert resumed["prompt"]["seconds_left"] == pytest.approx(2.0) and result["history"][0]["actions"]["wild"][0] == "attack"  # the saved choice


def test_closing_the_view_pauses_a_battle_and_reopening_resumes_it(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 4))
        view = await begin(env, coord, mode="autonomous", limit="normal")
        after = await advance(coord, env, view)
        await env.close()
        env2 = Env(tmp_path / "s.sqlite3")
        env2.clock.t = env.clock.now() + 3600  # an hour passes with nobody calling advance
        coord2 = env2.coordinator(ScriptedPolicy(wild=["flee"] * 4))
        resumed = await coord2.view("ann", after["id"])
        profile = await env2.collection.profile("ann")
        await env2.close()
        return after, resumed, profile

    after, resumed, profile = run(scenario())
    assert resumed == after and len(resumed["history"]) == 1 and profile["active_battle"] == after["id"]


# -- mode ----------------------------------------------------------------------------

def test_mode_can_be_switched_between_rounds_and_keeps_the_frozen_preset(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator(ScriptedPolicy(wild=["flee"] * 4))
        view = await begin(env, coord)
        with pytest.raises(InvalidRequest, match="EMBLEM tier limit"):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=1, mode="autonomous", emblem_limit=None)
        auto = await coord.set_mode("ann", env.key(), view["id"], round=1, revision=1, mode="autonomous", emblem_limit="rare")
        back = await coord.set_mode("ann", env.key(), view["id"], round=1, revision=auto["revision"], mode="manual", emblem_limit=None)
        with pytest.raises(InvalidRequest):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=back["revision"], mode="turbo", emblem_limit=None)
        await env.close()
        return auto, back

    auto, back = run(scenario())
    assert (auto["mode"], auto["emblem_limit"], auto["revision"]) == ("autonomous", "rare", 2)
    assert (back["mode"], back["emblem_limit"]) == ("manual", "rare")


def test_mode_cannot_change_while_an_emblem_prompt_is_open(tmp_path):
    async def scenario():
        env, coord, view = await catch_battle(tmp_path)
        prompt = await advance(coord, env, view)
        with pytest.raises(WrongPhase):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=prompt["revision"], mode="manual", emblem_limit=None)
        await env.close()

    run(scenario())


def test_a_battle_without_personalities_cannot_go_autonomous(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        coord = env.coordinator()
        view = await begin(env, coord, slot=2)  # an empty preset
        with pytest.raises(InvalidRequest):
            await coord.set_mode("ann", env.key(), view["id"], round=1, revision=1, mode="autonomous", emblem_limit="normal")
        await env.close()

    run(scenario())


# -- recovery ------------------------------------------------------------------------

def test_a_restart_between_rounds_gives_the_same_battle_as_not_restarting(tmp_path):
    async def play(path, restart):
        env = Env(path / "s.sqlite3")
        await env.start_player()
        coord = env.coordinator()  # the real policy and situation reader, driven by the saved seed
        view = await begin(env, coord, mode="autonomous", limit="normal", species="sentinel", level=3)
        view = await advance(coord, env, view)
        if restart:
            await env.close()
            env = Env(path / "s.sqlite3")
            coord = env.coordinator()
        for _ in range(3):
            if view["status"] != "active":
                break
            view = await advance(coord, env, view)
        history = view["history"]
        await env.close()
        return history

    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir(), two.mkdir()
    assert run(play(one, restart=False)) == run(play(two, restart=True))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_coordinator.py -q`
Expected: failures with `ModuleNotFoundError: No module named 'src.sparks.coordinator'` (raised inside `Env.coordinator`).

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sparks/decider.py`

```python
"""Turns a battle's public state into one Spark's action: situation read,
mood draw, personality weights, probabilities, seeded draw."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from src.sparks.catalog import Catalog
from src.sparks.engine import BattleEngine
from src.sparks.models import PLAYER, Action, BattleSetup, BattleState, PersonalityInstance
from src.sparks.policy import ActionPolicy, Mood, PolicyContext
from src.sparks.runtime import RandomSource
from src.sparks.situation import SituationReader, SituationViewBuilder


@dataclass(frozen=True)
class Decision:
    action: Action
    audit: dict[str, Any]  # kept privately with the round; never in a public view


class ActionDecider:
    def __init__(self, catalog: Catalog, engine: BattleEngine, policy: ActionPolicy, mood: Mood,
                 reader: SituationReader, views: SituationViewBuilder) -> None:
        self._catalog, self._engine, self._policy, self._mood = catalog, engine, policy, mood
        self._reader, self._views = reader, views

    async def decide(
        self, setup: BattleSetup, state: BattleState, side: str, instances: Sequence[PersonalityInstance],
        rng: RandomSource, *, can_collect: bool,
    ) -> Decision:
        """Pick `side`'s action from public state, its own personalities and its own history.
        Nothing about the opponent's pending choice is available here."""
        view = self._views.build(setup, state, side)
        situation = await self._reader.read(view)
        legal = self._engine.legal_actions(setup, state, side, can_collect=can_collect)
        lead = Mood.pick(len(instances), rng.next()) if instances else None
        weights = self._mood.weights(instances, lead) if instances else {}
        history = view.enemy_history
        flee_share = history.count("FEAR") / len(history) if history else self._catalog.policy.default_flee_share
        context = PolicyContext(
            situation=situation, enemy_hp_fraction=view.enemy_hp_fraction, enemy_flee_share=flee_share,
            collector=side == PLAYER, recent_keys=tuple(r.actions[side][0] for r in state.history), weights=weights,
        )
        decision = self._policy.choose(legal, context, rng.next())
        audit = {
            "side": side, "mood": instances[lead].id if instances else None,
            "situation": {"danger": situation.danger, "aggression": situation.aggression, "advantage": situation.advantage},
            "probabilities": {a.key: round(p, 4) for a, p in zip(legal, decision.probabilities)},
            "chosen": decision.action.key,
        }
        return Decision(decision.action, audit)
```

`apps/mini_games/src/sparks/battle_view.py`

```python
"""The public JSON view of a battle.

Only public information: both Sparks' stats and effects, revealed history, the
player's legal actions and any EMBLEM prompt. Never the wild Spark's
personalities, its pending action, the mood draw or action probabilities. A
finished battle adds its result, which reveals the source personalities only
after a capture.
"""

from __future__ import annotations

from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.engine import BattleEngine
from src.sparks.models import PLAYER, WILD
from src.sparks.records import BattleRecord


class BattleViewBuilder:
    def __init__(self, engine: BattleEngine, catalog: Catalog) -> None:
        self._engine, self._catalog = engine, catalog

    def tiers_up_to(self, limit: str | None) -> list[str]:
        """Tier ids from the weakest up to and including `limit`."""
        if limit is None:
            return []
        ids = [t.id for t in self._catalog.tiers]
        return ids[: ids.index(self._catalog.tier(limit).id) + 1]

    def permitted_tiers(self, emblems: dict[str, int], limit: str | None) -> list[str]:
        """Owned EMBLEM tiers an autonomous Spark may use."""
        return [tier for tier in self.tiers_up_to(limit) if emblems.get(tier, 0) > 0]

    def _fighter(self, record: BattleRecord, side: str) -> dict[str, Any]:
        fighter, state = record.setup.of(side), record.state.of(side)
        ready = dict(state.cooldowns)
        return {
            "species_id": fighter.species_id, "name": self._catalog.species(fighter.species_id).name,
            "tier_id": fighter.tier_id, "level": fighter.level, "hp": state.hp, "max_hp": fighter.max_hp,
            "essence": self._engine.stat(fighter, state, "essence"), "speed": self._engine.stat(fighter, state, "speed"),
            "buffs": [b.to_dict() for b in state.buffs],
            "defense": state.defense.to_dict() if state.defense else None,
            "abilities": [
                {"id": a.id, "name": a.name, "category": a.category, "percentage": a.percentage,
                 "cooldown": a.cooldown, "ready": record.state.round >= ready.get(a.id, 0)}
                for a in fighter.abilities
            ],
        }

    def build(self, record: BattleRecord, emblems: dict[str, int], now: float) -> dict[str, Any]:
        finished = record.status != "active"
        actions: list[dict[str, Any]] = []
        if not finished:
            names = {a.id: a.name for a in record.setup.player.abilities}
            for action in self._engine.legal_actions(record.setup, record.state, PLAYER, can_collect=bool(emblems)):
                actions.append({"kind": action.kind, "category": action.category, "ability_id": action.ability_id,
                                "name": names.get(action.ability_id), "percentage": action.percentage})
        prompt = None
        if record.phase == "awaiting_emblem" and record.pending:
            deadline = record.pending["deadline"]
            prompt = {"deadline": deadline, "seconds_left": max(0.0, deadline - now),
                      "permitted_tiers": self.permitted_tiers(emblems, record.emblem_limit), "owned": emblems}
        return {
            "id": record.id, "status": record.status, "phase": record.phase, "mode": record.mode,
            "round": record.state.round, "revision": record.revision, "emblem_limit": record.emblem_limit,
            "player": self._fighter(record, PLAYER), "wild": self._fighter(record, WILD),
            "actions": actions, "emblems": emblems, "prompt": prompt,
            "history": [h.to_dict() for h in record.state.history], "result": record.result,
        }
```

`apps/mini_games/src/sparks/emblem_picker.py`

```python
"""Choosing an EMBLEM tier for an autonomous CATCH after the player's prompt timed out."""

from __future__ import annotations

from typing import Protocol

from src.laya_client import LayaClient, LayaError
from src.sparks.situation import SituationView

INSTRUCTIONS = "Which EMBLEM tier should this fighter spend on collecting the enemy?"


class EmblemPicker(Protocol):
    async def pick(self, view: SituationView, chances: dict[str, float]) -> str | None:
        """A tier id from `chances` (tier id -> chance to collect now), or None."""


class LayaEmblemPicker:
    def __init__(self, client: LayaClient) -> None:
        self._client = client

    async def pick(self, view: SituationView, chances: dict[str, float]) -> str | None:
        if not chances:
            return None
        if len(chances) == 1:  # nothing to choose between
            return next(iter(chances))
        options = {tier: f"{tier} EMBLEM, {chance:.0%} chance to collect" for tier, chance in chances.items()}
        try:
            answer = await self._client.choose(view.to_text(), INSTRUCTIONS, options)
        except LayaError:
            return None
        return None if answer.uncertain else answer.value
```

`apps/mini_games/src/sparks/coordinator.py`

```python
"""The battle lifecycle: start, choose, resolve, prompt for an EMBLEM, switch
mode, forfeit, and resume after a restart.

Rules this class keeps:
- Decisions are built from public state only. The wild Spark's action is
  decided before the player's action is read, and nothing but the battle's
  public state is passed to the situation reader, so an AI never sees the
  opponent's pending choice.
- A round's lock and resolution commit in one transaction with the new
  checkpoint, the EMBLEM spent and (when the battle ends) the rewards. The
  only choice ever stored before a reveal is the wild action and the player's
  CATCH intent while an EMBLEM prompt is open; a restart never rerolls it.
- The battle's random stream is (seed, counter). Retries and restarts replay
  the same draws; mutations are idempotent and revision-checked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

from src.sparks.battle_view import BattleViewBuilder
from src.sparks.catalog import Catalog, CatalogError
from src.sparks.decider import ActionDecider, Decision
from src.sparks.emblem_picker import EmblemPicker
from src.sparks.engine import ActionError, BattleEngine
from src.sparks.errors import (
    BattleFinished,
    DeadlinePassed,
    InsufficientEmblems,
    InvalidRequest,
    NotFound,
    SparkFainted,
    StaleBattle,
    WrongPhase,
)
from src.sparks.idempotency import IdempotentWriter
from src.sparks.models import PLAYER, WILD, Action, BattleSetup
from src.sparks.progression import ProgressionService
from src.sparks.records import BattleRecord
from src.sparks.repository import SparkRepository, SparkTransaction
from src.sparks.runtime import Clock, SeededRandom, new_id, new_seed
from src.sparks.situation import SituationViewBuilder

MODES = ("manual", "autonomous")


@dataclass(frozen=True)
class CoordinatorSettings:
    emblem_prompt_seconds: float


class RoundCoordinator:
    def __init__(
        self, repository: SparkRepository, writer: IdempotentWriter, catalog: Catalog, engine: BattleEngine,
        decider: ActionDecider, situation_views: SituationViewBuilder, emblem_picker: EmblemPicker,
        progression: ProgressionService, battle_views: BattleViewBuilder, clock: Clock, settings: CoordinatorSettings,
    ) -> None:
        self._repo, self._writer, self._catalog, self._engine = repository, writer, catalog, engine
        self._decider, self._situation_views = decider, situation_views
        self._emblem_picker, self._progression, self._battle_views = emblem_picker, progression, battle_views
        self._clock, self._settings = clock, settings
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, battle_id: str) -> asyncio.Lock:
        return self._locks.setdefault(battle_id, asyncio.Lock())

    # -- reading -------------------------------------------------------------------

    async def _load(self, owner: str, battle_id: str) -> tuple[BattleRecord, dict[str, int]]:
        async with self._repo.transaction() as tx:
            record = await tx.get_battle(owner, battle_id)
            if record is None:
                raise NotFound("no such battle")
            return record, await tx.emblem_counts(owner)

    async def view(self, owner: str, battle_id: str) -> dict[str, Any]:
        record, emblems = await self._load(owner, battle_id)
        return self._battle_views.build(record, emblems, self._clock.now())

    @staticmethod
    def _require(record: BattleRecord, *, round: int, revision: int, phase: str | tuple[str, ...] = "choosing") -> None:
        if record.status != "active":
            raise BattleFinished("this battle is over")
        phases = (phase,) if isinstance(phase, str) else phase
        if record.phase not in phases:
            raise WrongPhase(f"this battle is in the {record.phase} phase")
        if record.state.round != round or record.revision != revision:
            raise StaleBattle("the battle moved on; reload it and try again")

    # -- starting ------------------------------------------------------------------

    async def start(
        self, owner: str, key: str, *, encounter_id: str, species_id: str, preset_slot: int | None,
        mode: str, emblem_limit: str | None,
    ) -> dict[str, Any]:
        payload = {"encounter": encounter_id, "species": species_id, "slot": preset_slot, "mode": mode, "limit": emblem_limit}
        if mode not in MODES:
            raise InvalidRequest(f"mode must be one of {', '.join(MODES)}")
        try:
            if emblem_limit is not None:
                self._catalog.tier(emblem_limit)
            self._catalog.species(species_id)
        except CatalogError as error:
            raise InvalidRequest(str(error)) from error
        if mode == "autonomous" and (emblem_limit is None or preset_slot is None):
            raise InvalidRequest("autonomous play needs a personality preset and an EMBLEM tier limit")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            encounter = await tx.get_encounter(owner, encounter_id)
            if encounter is None:
                raise NotFound("no such encounter")
            if encounter.status != "pending":
                raise WrongPhase(f"this encounter is already {encounter.status}")
            spark = await tx.get_spark(owner, species_id)
            if spark is None:
                raise NotFound("you do not own that species")
            now = self._clock.now()
            if spark.faint_until is not None and spark.faint_until > now:
                raise SparkFainted(f"that Spark is fainted for another {spark.faint_until - now:.0f} seconds")
            instances = ()
            if preset_slot is not None:
                preset = await tx.get_preset(owner, species_id, preset_slot)
                ids = list(preset.instance_ids) if preset else []
                by_id = {p.id: p.instance() for p in await tx.get_personalities(owner, species_id, ids)}
                instances = tuple(by_id[i] for i in ids if i in by_id)  # frozen for the whole battle
            if mode == "autonomous" and not instances:
                raise InvalidRequest("that preset has no personalities; equip at least one")
            setup = BattleSetup(
                self._engine.build_fighter(PLAYER, species_id, self._catalog.tier_for_copies(species_id, spark.copies), spark.level),
                self._engine.build_fighter(WILD, encounter.species_id, encounter.tier_id, encounter.level),
            )
            record = BattleRecord(
                id=new_id(), owner=owner, encounter_id=encounter.id, status="active", phase="choosing", mode=mode,
                revision=1, setup=setup, state=self._engine.start_state(setup), player_personalities=instances,
                wild_personalities=encounter.wild_personalities, emblem_limit=emblem_limit, rng_seed=new_seed(),
                rng_counter=0, created_at=now, updated_at=now,
            )
            await tx.add_battle(record)
            await tx.set_encounter_status(encounter.id, "started")
            return self._battle_views.build(record, await tx.emblem_counts(owner), now)

        return await self._writer.commit(owner, key, "battle.start", payload, work)

    # -- deciding ------------------------------------------------------------------

    async def _decide(self, record: BattleRecord, side: str, rng: SeededRandom, *, can_collect: bool) -> Decision:
        instances = record.player_personalities if side == PLAYER else record.wild_personalities
        return await self._decider.decide(record.setup, record.state, side, instances, rng, can_collect=can_collect)

    # -- committing ----------------------------------------------------------------

    async def _commit_round(
        self, owner: str, key: str, operation: str, payload: dict[str, Any], record: BattleRecord,
        player_action: Action, wild_action: Action, rng: SeededRandom, audits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async def work(tx: SparkTransaction) -> dict[str, Any]:
            fresh = await tx.get_battle(owner, record.id)
            if fresh is None or fresh.revision != record.revision or fresh.status != "active":
                raise StaleBattle("the battle moved on; reload it and try again")
            emblems = await tx.emblem_counts(owner)
            if player_action.kind == "catch" and emblems.get(player_action.emblem_tier, 0) < 1:
                raise InsufficientEmblems(f"you have no {player_action.emblem_tier} EMBLEM")
            outcome = self._engine.resolve_round(fresh.setup, fresh.state, player_action, wild_action, rng)
            now = self._clock.now()
            updated = replace(fresh, state=outcome.state, revision=fresh.revision + 1, phase="choosing", pending=None, updated_at=now)
            if outcome.emblem_consumed:
                await tx.add_emblems(owner, outcome.emblem_consumed, -1)
            await tx.add_round(fresh.id, fresh.state.round, {
                "actions": {PLAYER: player_action.to_dict(), WILD: wild_action.to_dict()}, "audit": audits,
                "draws": list(outcome.draws), "events": list(outcome.events), "terminal": outcome.terminal,
            })
            if outcome.terminal:
                result = await self._progression.apply_terminal(tx, updated, outcome.terminal, rng)
                updated = replace(updated, status="terminal", phase="terminal", result=result)
            updated = replace(updated, rng_counter=rng.counter)
            await tx.save_battle(updated, fresh.revision)
            return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

        return await self._writer.commit(owner, key, operation, payload, work)

    # -- manual play ---------------------------------------------------------------

    async def submit_action(
        self, owner: str, key: str, battle_id: str, *, round: int, revision: int, action: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {"battle": battle_id, "round": round, "revision": revision, "action": action}
        cached = await self._writer.lookup(owner, key, "battle.action", payload)
        if cached is not None:
            return cached
        async with self._lock(battle_id):
            record, emblems = await self._load(owner, battle_id)
            self._require(record, round=round, revision=revision)
            if record.mode != "manual":
                raise WrongPhase("this battle is autonomous; switch to manual or use advance")
            legal = self._engine.legal_actions(record.setup, record.state, PLAYER, can_collect=bool(emblems))
            try:
                player_action = self._engine.resolve_action(legal, action)
            except (ActionError, CatalogError) as error:
                raise InvalidRequest(str(error)) from error
            if player_action.kind == "catch" and emblems.get(player_action.emblem_tier, 0) < 1:
                raise InsufficientEmblems(f"you have no {player_action.emblem_tier} EMBLEM")
            rng = SeededRandom(record.rng_seed, record.rng_counter)
            wild = await self._decide(record, WILD, rng, can_collect=False)  # decided without sight of player_action
            return await self._commit_round(
                owner, key, "battle.action", payload, record, player_action, wild.action, rng, [wild.audit])

    # -- autonomous play -----------------------------------------------------------

    async def advance(self, owner: str, key: str, battle_id: str, *, round: int, revision: int) -> dict[str, Any]:
        """Play one autonomous round, or settle an EMBLEM prompt whose time is up."""
        payload = {"battle": battle_id, "round": round, "revision": revision}
        cached = await self._writer.lookup(owner, key, "battle.advance", payload)
        if cached is not None:
            return cached
        async with self._lock(battle_id):
            record, emblems = await self._load(owner, battle_id)
            self._require(record, round=round, revision=revision, phase=("choosing", "awaiting_emblem"))
            if record.mode != "autonomous":
                raise WrongPhase("this battle is manual; choose an action")
            now = self._clock.now()
            if record.phase == "awaiting_emblem":
                if now < record.pending["deadline"]:
                    return self._battle_views.build(record, emblems, now)  # still the player's turn to answer
                return await self._settle_prompt(owner, key, payload, record, emblems)
            rng = SeededRandom(record.rng_seed, record.rng_counter)
            permitted = self._battle_views.permitted_tiers(emblems, record.emblem_limit)
            player = await self._decide(record, PLAYER, rng, can_collect=bool(permitted))
            wild = await self._decide(record, WILD, rng, can_collect=False)
            if player.action.kind == "catch":
                return await self._open_prompt(owner, key, payload, record, wild, player, rng)
            return await self._commit_round(
                owner, key, "battle.advance", payload, record, player.action, wild.action, rng, [player.audit, wild.audit])

    async def _open_prompt(self, owner, key, payload, record, wild: Decision, player: Decision, rng) -> dict[str, Any]:
        """The player's Spark wants to CATCH: keep both private choices and ask for an EMBLEM."""
        async def work(tx: SparkTransaction) -> dict[str, Any]:
            fresh = await tx.get_battle(owner, record.id)
            if fresh is None or fresh.revision != record.revision:
                raise StaleBattle("the battle moved on; reload it and try again")
            now = self._clock.now()
            pending = {
                "wild_action": wild.action.to_dict(), "audit": [player.audit, wild.audit],
                "deadline": now + self._settings.emblem_prompt_seconds,
            }
            updated = replace(fresh, phase="awaiting_emblem", pending=pending, revision=fresh.revision + 1,
                              rng_counter=rng.counter, updated_at=now)
            await tx.save_battle(updated, fresh.revision)
            return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

        return await self._writer.commit(owner, key, "battle.advance", payload, work)

    async def _settle_prompt(self, owner, key, payload, record: BattleRecord, emblems: dict[str, int]) -> dict[str, Any]:
        """The prompt expired: Laya picks within the player's limit, else basic ATTACK."""
        permitted = self._battle_views.permitted_tiers(emblems, record.emblem_limit)
        wild_state = record.state.wild
        chances = {t: self._engine.capture_chance(t, record.setup.wild, wild_state) for t in permitted}
        tier = await self._emblem_picker.pick(self._situation_views.build(record.setup, record.state, PLAYER), chances)
        player_action = (
            Action("catch", "INTERCEPT", emblem_tier=tier) if tier in chances else Action("attack", "ATTACK")
        )
        rng = SeededRandom(record.rng_seed, record.rng_counter)
        wild_action = Action.from_dict(record.pending["wild_action"])
        return await self._commit_round(
            owner, key, "battle.advance", payload, record, player_action, wild_action, rng, record.pending["audit"])

    async def answer_emblem(
        self, owner: str, key: str, battle_id: str, *, round: int, revision: int, tier: str
    ) -> dict[str, Any]:
        """The player's own EMBLEM choice (any owned tier, even above the autonomous limit)."""
        payload = {"battle": battle_id, "round": round, "revision": revision, "tier": tier}
        cached = await self._writer.lookup(owner, key, "battle.emblem", payload)
        if cached is not None:
            return cached
        async with self._lock(battle_id):
            record, emblems = await self._load(owner, battle_id)
            self._require(record, round=round, revision=revision, phase="awaiting_emblem")
            if self._clock.now() >= record.pending["deadline"]:
                raise DeadlinePassed("the prompt has expired; advance the battle instead")
            try:
                self._catalog.tier(tier)
            except CatalogError as error:
                raise InvalidRequest(str(error)) from error
            if emblems.get(tier, 0) < 1:
                raise InsufficientEmblems(f"you have no {tier} EMBLEM")
            rng = SeededRandom(record.rng_seed, record.rng_counter)
            return await self._commit_round(
                owner, key, "battle.emblem", payload, record, Action("catch", "INTERCEPT", emblem_tier=tier),
                Action.from_dict(record.pending["wild_action"]), rng, record.pending["audit"])

    # -- mode and forfeit ----------------------------------------------------------

    async def set_mode(
        self, owner: str, key: str, battle_id: str, *, round: int, revision: int, mode: str, emblem_limit: str | None
    ) -> dict[str, Any]:
        """Switch between manual and autonomous before the next action is locked."""
        payload = {"battle": battle_id, "round": round, "revision": revision, "mode": mode, "limit": emblem_limit}
        if mode not in MODES:
            raise InvalidRequest(f"mode must be one of {', '.join(MODES)}")
        async with self._lock(battle_id):
            async def work(tx: SparkTransaction) -> dict[str, Any]:
                record = await tx.get_battle(owner, battle_id)
                if record is None:
                    raise NotFound("no such battle")
                self._require(record, round=round, revision=revision)
                limit = emblem_limit or record.emblem_limit
                if mode == "autonomous" and (not record.player_personalities or limit is None):
                    raise InvalidRequest("autonomous play needs equipped personalities and an EMBLEM tier limit")
                try:
                    if limit is not None:
                        self._catalog.tier(limit)
                except CatalogError as error:
                    raise InvalidRequest(str(error)) from error
                now = self._clock.now()
                updated = replace(record, mode=mode, emblem_limit=limit, revision=record.revision + 1, updated_at=now)
                await tx.save_battle(updated, record.revision)
                return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

            return await self._writer.commit(owner, key, "battle.mode", payload, work)

    async def forfeit(self, owner: str, key: str, battle_id: str) -> dict[str, Any]:
        """End the battle as a loss. Serialized with resolution, so a finished result is never replaced."""
        async with self._lock(battle_id):
            async def work(tx: SparkTransaction) -> dict[str, Any]:
                record = await tx.get_battle(owner, battle_id)
                if record is None:
                    raise NotFound("no such battle")
                if record.status != "active":
                    raise BattleFinished("this battle is already over")
                rng = SeededRandom(record.rng_seed, record.rng_counter)
                result = await self._progression.apply_terminal(tx, record, "forfeited", rng)
                now = self._clock.now()
                updated = replace(record, status="terminal", phase="terminal", pending=None, result=result,
                                  revision=record.revision + 1, rng_counter=rng.counter, updated_at=now)
                await tx.save_battle(updated, record.revision)
                return self._battle_views.build(updated, await tx.emblem_counts(owner), now)

            return await self._writer.commit(owner, key, "battle.forfeit", {"battle": battle_id}, work)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_coordinator.py -q`
Expected: 40 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/decider.py apps/mini_games/src/sparks/battle_view.py apps/mini_games/src/sparks/emblem_picker.py apps/mini_games/src/sparks/coordinator.py apps/mini_games/tests/sparks/test_coordinator.py
git commit -m "feat(mini_games): round coordinator with EMBLEM prompt and recovery"
```

---

### Task 13: HTTP API, composition root and the launcher

**Files:**
- Create: `apps/mini_games/src/app.py`, `src/sparks/api.py`, `src/sparks/composition.py`, `src/run.py`, `run.bat`
- Test: `apps/mini_games/tests/sparks/test_api.py`

**Interfaces:**
- Consumes: Tasks 2 to 12.
- Produces: `src.app.create_app(token="") -> FastAPI` (token middleware, `/health`, JSON error shape, validation errors as 400); `SparkServices(catalog, collection, encounters, shop, coordinator)`; `build_router(services)`, `install_error_handlers(app)`, `mount_sparks(app, services)`; `build_spark_services(config, laya, catalog=None, repository=None, clock=None, rng=None)` (the one composition root); `src.run.build_app() -> (app, config)` and `main()`.
- Routes (all under `/sparks`; every mutation needs an `Idempotency-Key` header; bodies reject unknown fields): `GET /catalog`, `POST /profile`, `GET /profile`, `GET /species/{id}/personalities`, `GET` and `PUT /species/{id}/presets/{slot}`, `POST /encounters`, `GET /encounters/{id}`, `POST /encounters/{id}/decline`, `POST /battles`, `GET /battles/{id}`, `POST /battles/{id}/actions`, `/emblem`, `/advance`, `/mode`, `/forfeit`, `POST /shop/purchases` (`kind` `emblem` or `copies`), `POST /species/{id}/sales`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_api.py`

```python
import dataclasses
import itertools

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.laya_client import LayaClient
from src.sparks.api import mount_sparks
from src.sparks.composition import build_spark_services
from src.sparks.runtime import SeededRandom
from tests.fake_laya import FakeEngine
from tests.sparks.helpers import FixedClock

TOKEN = "t0ken"
_KEYS = itertools.count(1)


def headers(owner="ann", key=True, token=TOKEN):
    result = {"X-Internal-Token": token} if token else {}
    if owner:
        result["X-Requester-Username"] = owner
    if key is True:
        result["Idempotency-Key"] = f"k{next(_KEYS)}"
    elif key:
        result["Idempotency-Key"] = key
    return result


@pytest.fixture
def clock():
    return FixedClock()


@pytest.fixture
def client(config, tmp_path, clock):
    config = dataclasses.replace(config, database_path=tmp_path / "api.sqlite3")
    app = create_app(TOKEN)
    services = build_spark_services(config, LayaClient(FakeEngine(fail=True)), clock=clock, rng=SeededRandom(5))
    mount_sparks(app, services)
    with TestClient(app) as test_client:
        yield test_client


def start_profile(client, owner="ann", starter="guardian"):
    response = client.post("/sparks/profile", json={"starter_species_id": starter}, headers=headers(owner))
    assert response.status_code == 201, response.text
    return response.json()


# -- access --------------------------------------------------------------------------

def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("h", [{}, {"X-Requester-Username": "ann"}, {"X-Internal-Token": "wrong", "X-Requester-Username": "ann"}])
def test_the_internal_token_is_required(client, h):
    assert client.get("/sparks/profile", headers=h).status_code == 401


def test_the_requester_header_is_required(client):
    response = client.get("/sparks/profile", headers=headers(owner=None))
    assert response.status_code == 400 and "X-Requester-Username" in response.json()["error"]


def test_mutations_need_an_idempotency_key(client):
    response = client.post("/sparks/profile", json={"starter_species_id": "guardian"}, headers=headers(key=False))
    assert response.status_code == 400 and "Idempotency-Key" in response.json()["error"]


def test_the_catalog_is_readable_and_complete(client):
    data = client.get("/sparks/catalog", headers=headers(owner="anyone")).json()
    assert len(data["species"]) == 7 and [t["id"] for t in data["tiers"]][-1] == "forbidden"
    assert {s["id"] for s in data["species"] if s["starter"]} == {"guardian", "striker", "scout"}
    assert len(data["personalities"]) == 8


# -- profile, personalities, presets -------------------------------------------------

def test_profile_creation_is_once_and_idempotent(client):
    first = client.post("/sparks/profile", json={"starter_species_id": "scout"}, headers=headers(key="same"))
    again = client.post("/sparks/profile", json={"starter_species_id": "scout"}, headers=headers(key="same"))
    other = client.post("/sparks/profile", json={"starter_species_id": "scout"}, headers=headers())
    clash = client.post("/sparks/profile", json={"starter_species_id": "striker"}, headers=headers(key="same"))
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert other.status_code == 409 and clash.status_code == 409
    profile = client.get("/sparks/profile", headers=headers()).json()
    assert profile["emblems"] == {"normal": 5} and profile["insignia"] == 0 and profile["sparks"][0]["species_id"] == "scout"


def test_a_bad_starter_and_unknown_fields_are_400(client):
    assert client.post("/sparks/profile", json={"starter_species_id": "forbidden"}, headers=headers()).status_code == 400
    assert client.post("/sparks/profile", json={"starter_species_id": "guardian", "insignia": 9999}, headers=headers()).status_code == 400
    assert client.post("/sparks/profile", json={}, headers=headers()).status_code == 400


def test_profiles_are_private_to_their_owner(client):
    start_profile(client, "ann")
    assert client.get("/sparks/profile", headers=headers("bob")).status_code == 404
    assert client.get("/sparks/species/guardian/personalities", headers=headers("bob")).status_code == 404


def test_personalities_and_presets_over_http(client):
    start_profile(client)
    pool = client.get("/sparks/species/guardian/personalities", headers=headers()).json()
    ids = [p["id"] for p in pool["items"]]
    assert len(ids) == 1 and pool["next_cursor"] is None
    put = client.put("/sparks/species/guardian/presets/2", json={"instance_ids": ids}, headers=headers())
    assert put.status_code == 200 and client.get("/sparks/species/guardian/presets/2", headers=headers()).json()["instance_ids"] == ids
    assert client.put("/sparks/species/guardian/presets/2", json={"instance_ids": ["nope"]}, headers=headers()).status_code == 400
    assert client.put("/sparks/species/guardian/presets/9", json={"instance_ids": []}, headers=headers()).status_code == 400
    assert client.get("/sparks/species/guardian/personalities?limit=500", headers=headers()).status_code == 400


# -- encounters ----------------------------------------------------------------------

def test_encounter_rolls_respect_the_cooldown(client, clock):
    start_profile(client)
    first = client.post("/sparks/encounters", headers=headers())
    early = client.post("/sparks/encounters", headers=headers())
    assert first.status_code == 201 and "personalities" not in first.text
    assert early.status_code == 409 and early.json()["retry_after"] == pytest.approx(30)
    clock.advance(31)
    assert client.post("/sparks/encounters", headers=headers()).status_code == 201


def test_decline_over_http(client):
    start_profile(client)
    encounter = client.post("/sparks/encounters", headers=headers()).json()
    assert client.post(f"/sparks/encounters/{encounter['id']}/decline", headers=headers()).json()["status"] == "declined"
    assert client.get(f"/sparks/encounters/{encounter['id']}", headers=headers("bob")).status_code == 404


# -- battles -------------------------------------------------------------------------

def open_battle(client, mode="manual", **extra):
    start_profile(client)
    encounter = client.post("/sparks/encounters", headers=headers()).json()
    body = {"encounter_id": encounter["id"], "species_id": "guardian", "preset_slot": 1, "mode": mode, **extra}
    response = client.post("/sparks/battles", json=body, headers=headers())
    assert response.status_code == 201, response.text
    return response.json()


def test_a_battle_can_be_started_played_and_forfeited(client):
    view = open_battle(client)
    assert view["phase"] == "choosing" and any(a["kind"] == "attack" for a in view["actions"])
    action = {"round": view["round"], "revision": view["revision"], "action": {"kind": "attack"}}
    after = client.post(f"/sparks/battles/{view['id']}/actions", json=action, headers=headers())
    assert after.status_code == 200 and after.json()["revision"] == 2 and len(after.json()["history"]) == 1
    if after.json()["status"] == "active":
        done = client.post(f"/sparks/battles/{view['id']}/forfeit", headers=headers()).json()
        assert done["status"] == "terminal" and done["result"]["kind"] == "forfeited"
        assert client.post(f"/sparks/battles/{view['id']}/forfeit", headers=headers()).status_code == 409


def test_a_stale_action_is_a_409_and_a_retry_is_not_repeated(client):
    view = open_battle(client)
    body = {"round": 1, "revision": 1, "action": {"kind": "attack"}}
    first = client.post(f"/sparks/battles/{view['id']}/actions", json=body, headers=headers(key="once"))
    retry = client.post(f"/sparks/battles/{view['id']}/actions", json=body, headers=headers(key="once"))
    stale = client.post(f"/sparks/battles/{view['id']}/actions", json=body, headers=headers())
    assert first.status_code == retry.status_code == 200 and first.json() == retry.json()
    assert stale.status_code == 409


def test_clients_cannot_send_rewards_or_chances(client):
    view = open_battle(client)
    cheat = {"round": 1, "revision": 1, "action": {"kind": "attack", "damage": 9999}}
    assert client.post(f"/sparks/battles/{view['id']}/actions", json=cheat, headers=headers()).status_code == 400
    cheat = {"round": 1, "revision": 1, "action": {"kind": "attack"}, "xp": 5000}
    assert client.post(f"/sparks/battles/{view['id']}/actions", json=cheat, headers=headers()).status_code == 400


def test_illegal_actions_and_wrong_modes(client):
    view = open_battle(client)
    nope = {"round": 1, "revision": 1, "action": {"kind": "ability", "ability_id": "unknown"}}
    assert client.post(f"/sparks/battles/{view['id']}/actions", json=nope, headers=headers()).status_code == 400
    advance = client.post(f"/sparks/battles/{view['id']}/advance", json={"round": 1, "revision": 1}, headers=headers())
    assert advance.status_code == 409  # manual battles wait for the player


def test_autonomous_advance_and_mode_switch(client):
    view = open_battle(client, mode="autonomous", emblem_limit="normal")
    played = client.post(f"/sparks/battles/{view['id']}/advance", json={"round": 1, "revision": 1}, headers=headers())
    assert played.status_code == 200
    data = played.json()
    if data["phase"] == "awaiting_emblem":  # the Spark chose CATCH: the player has five seconds to pick an EMBLEM
        assert data["history"] == [] and data["prompt"]["seconds_left"] == 5.0
        body = {"round": data["round"], "revision": data["revision"], "mode": "manual"}
        assert client.post(f"/sparks/battles/{view['id']}/mode", json=body, headers=headers()).status_code == 409
        return
    assert len(data["history"]) == 1
    if data["status"] == "active":
        body = {"round": data["round"], "revision": data["revision"], "mode": "manual"}
        assert client.post(f"/sparks/battles/{view['id']}/mode", json=body, headers=headers()).json()["mode"] == "manual"


def test_battles_are_private_to_their_owner(client):
    view = open_battle(client)
    start_profile(client, "bob")
    assert client.get(f"/sparks/battles/{view['id']}", headers=headers("bob")).status_code == 404
    assert client.post(f"/sparks/battles/{view['id']}/forfeit", headers=headers("bob")).status_code == 404
    assert client.get("/sparks/battles/missing", headers=headers()).status_code == 404


def test_a_second_battle_is_refused_while_one_is_active(client):
    open_battle(client)
    assert client.post("/sparks/encounters", headers=headers()).status_code == 409


# -- shop ----------------------------------------------------------------------------

def test_shop_over_http(client):
    start_profile(client)
    poor = client.post("/sparks/shop/purchases", json={"kind": "emblem", "tier": "rare", "quantity": 1}, headers=headers())
    assert poor.status_code == 409
    assert client.post("/sparks/shop/purchases", json={"kind": "copies", "species_id": "sentinel", "tier": "normal"}, headers=headers()).status_code == 409
    assert client.post("/sparks/shop/purchases", json={"kind": "stock", "tier": "rare"}, headers=headers()).status_code == 400
    assert client.post("/sparks/shop/purchases", json={"kind": "emblem", "tier": "gold", "quantity": 1}, headers=headers()).status_code == 400
    assert client.post("/sparks/species/guardian/sales", headers=headers()).status_code == 409  # nothing to sell
    assert client.post("/sparks/species/dragon/sales", headers=headers()).status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_api.py -q`
Expected: `ModuleNotFoundError: No module named 'src.app'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/app.py`

```python
"""The FastAPI shell every game mounts into: token check, health and error shape."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.auth import InternalTokenMiddleware


def create_app(token: str = "") -> FastAPI:
    app = FastAPI(title="mini_games", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(InternalTokenMiddleware, token=token)

    @app.exception_handler(RequestValidationError)
    async def bad_body(request: Request, error: RequestValidationError) -> JSONResponse:
        detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()[:3])
        return JSONResponse({"error": "invalid request", "detail": detail}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"error": error.detail}, status_code=error.status_code)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

`apps/mini_games/src/sparks/api.py`

```python
"""HTTP routes for Emberlings: thin adapters over the services.

Ownership comes from the trusted requester header only. Request bodies reject
unknown fields, so a client can never supply rewards, stats, chances, random
results or personalities. Every mutation needs an Idempotency-Key header.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt

from src.auth import requester
from src.sparks.catalog import Catalog, CatalogError
from src.sparks.collection import CollectionService
from src.sparks.coordinator import RoundCoordinator
from src.sparks.encounters import EncounterService
from src.sparks.errors import EncounterCooldown, SparkError
from src.sparks.shop import ShopService


@dataclass(frozen=True)
class SparkServices:
    catalog: Catalog
    collection: CollectionService
    encounters: EncounterService
    shop: ShopService
    coordinator: RoundCoordinator


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InitializeBody(_Body):
    starter_species_id: str


class PresetBody(_Body):
    instance_ids: list[str]


class StartBody(_Body):
    encounter_id: str
    species_id: str
    preset_slot: StrictInt | None = None
    mode: str = "manual"
    emblem_limit: str | None = None


class ActionBody(_Body):
    kind: str
    ability_id: str | None = None
    emblem_tier: str | None = None


class RoundBody(_Body):
    round: StrictInt
    revision: StrictInt


class ActionRequest(RoundBody):
    action: ActionBody


class EmblemRequest(RoundBody):
    tier: str


class ModeRequest(RoundBody):
    mode: str
    emblem_limit: str | None = None


class PurchaseBody(_Body):
    kind: str
    tier: str
    quantity: StrictInt = 1
    species_id: str | None = None


def idempotency_key(idempotency_key: str = Header(default="", alias="Idempotency-Key")) -> str:
    if not idempotency_key.strip():
        raise HTTPException(400, "an Idempotency-Key header is required for this request")
    return idempotency_key.strip()


def catalog_summary(catalog: Catalog) -> dict[str, Any]:
    """Public catalog data: species, abilities, tiers, personalities and shop metadata."""
    return {
        "version": catalog.version,
        "tiers": [
            {"id": t.id, "stat_multiplier": t.stat_multiplier, "copy_threshold": t.copy_threshold, "copy_reward": t.copy_reward,
             "emblem_strength": t.emblem_strength, "emblem_price": t.emblem_price}
            for t in catalog.tiers
        ],
        "levels": {"regular_cap": catalog.levels.regular_cap, "forbidden_cap": catalog.levels.forbidden_cap},
        "species": [
            {"id": s.id, "name": s.name, "starter": s.starter, "forbidden": s.forbidden, "base": dict(s.base),
             "growth": dict(s.growth), "base_price": s.base_price, "passive": s.passive.to_dict(),
             "abilities": [a.to_dict() for a in s.abilities]}
            for s in catalog.all_species()
        ],
        "personalities": [{"id": p.id, "categories": list(p.categories)} for p in catalog.personalities.values()],
    }


def build_router(services: SparkServices) -> APIRouter:
    router = APIRouter(prefix="/sparks")
    collection, encounters, shop, coordinator = services.collection, services.encounters, services.shop, services.coordinator

    @router.get("/catalog")
    async def catalog() -> dict[str, Any]:
        return catalog_summary(services.catalog)

    @router.post("/profile", status_code=201)
    async def create_profile(body: InitializeBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await collection.initialize(owner, key, body.starter_species_id)

    @router.get("/profile")
    async def get_profile(owner: str = Depends(requester)):
        return await collection.profile(owner)

    @router.get("/species/{species_id}/personalities")
    async def list_personalities(species_id: str, limit: int | None = Query(default=None), cursor: int = Query(default=0),
                                 owner: str = Depends(requester)):
        return await collection.personalities(owner, species_id, limit, cursor)

    @router.get("/species/{species_id}/presets/{slot}")
    async def get_preset(species_id: str, slot: int, owner: str = Depends(requester)):
        return await collection.get_preset(owner, species_id, slot)

    @router.put("/species/{species_id}/presets/{slot}")
    async def put_preset(species_id: str, slot: int, body: PresetBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await collection.put_preset(owner, key, species_id, slot, body.instance_ids)

    @router.post("/encounters", status_code=201)
    async def roll_encounter(owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await encounters.roll(owner, key)

    @router.get("/encounters/{encounter_id}")
    async def get_encounter(encounter_id: str, owner: str = Depends(requester)):
        return await encounters.get(owner, encounter_id)

    @router.post("/encounters/{encounter_id}/decline")
    async def decline_encounter(encounter_id: str, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await encounters.decline(owner, key, encounter_id)

    @router.post("/battles", status_code=201)
    async def start_battle(body: StartBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.start(owner, key, encounter_id=body.encounter_id, species_id=body.species_id,
                                       preset_slot=body.preset_slot, mode=body.mode, emblem_limit=body.emblem_limit)

    @router.get("/battles/{battle_id}")
    async def get_battle(battle_id: str, owner: str = Depends(requester)):
        return await coordinator.view(owner, battle_id)

    @router.post("/battles/{battle_id}/actions")
    async def submit_action(battle_id: str, body: ActionRequest, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.submit_action(owner, key, battle_id, round=body.round, revision=body.revision,
                                               action=body.action.model_dump(exclude_none=True))

    @router.post("/battles/{battle_id}/emblem")
    async def answer_emblem(battle_id: str, body: EmblemRequest, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.answer_emblem(owner, key, battle_id, round=body.round, revision=body.revision, tier=body.tier)

    @router.post("/battles/{battle_id}/advance")
    async def advance_battle(battle_id: str, body: RoundBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.advance(owner, key, battle_id, round=body.round, revision=body.revision)

    @router.post("/battles/{battle_id}/mode")
    async def set_mode(battle_id: str, body: ModeRequest, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.set_mode(owner, key, battle_id, round=body.round, revision=body.revision,
                                          mode=body.mode, emblem_limit=body.emblem_limit)

    @router.post("/battles/{battle_id}/forfeit")
    async def forfeit(battle_id: str, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.forfeit(owner, key, battle_id)

    @router.post("/shop/purchases", status_code=201)
    async def purchase(body: PurchaseBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        if body.kind == "emblem":
            return await shop.buy_emblems(owner, key, body.tier, body.quantity)
        if body.kind == "copies" and body.species_id:
            return await shop.buy_copies(owner, key, body.species_id, body.tier)
        raise HTTPException(400, 'kind must be "emblem" (with tier, quantity) or "copies" (with species_id, tier)')

    @router.post("/species/{species_id}/sales", status_code=201)
    async def sell(species_id: str, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await shop.sell_copy(owner, key, species_id)

    return router


def install_error_handlers(app: FastAPI) -> None:
    async def spark_error(request: Request, error: SparkError) -> JSONResponse:
        body: dict[str, Any] = {"error": str(error)}
        if isinstance(error, EncounterCooldown):
            body["retry_after"] = error.retry_after
        return JSONResponse(body, status_code=error.status_code)

    async def catalog_error(request: Request, error: CatalogError) -> JSONResponse:
        return JSONResponse({"error": str(error)}, status_code=400)

    app.add_exception_handler(SparkError, spark_error)
    app.add_exception_handler(CatalogError, catalog_error)


def mount_sparks(app: FastAPI, services: SparkServices) -> None:
    install_error_handlers(app)
    app.include_router(build_router(services))
```

`apps/mini_games/src/sparks/composition.py`

```python
"""The composition root: builds the whole Emberlings object graph once at startup."""

from __future__ import annotations

from src.config import AppConfig
from src.laya_client import LayaClient
from src.sparks.api import SparkServices
from src.sparks.battle_view import BattleViewBuilder
from src.sparks.catalog import Catalog
from src.sparks.collection import CollectionService
from src.sparks.coordinator import CoordinatorSettings, RoundCoordinator
from src.sparks.decider import ActionDecider
from src.sparks.emblem_picker import LayaEmblemPicker
from src.sparks.encounters import EncounterService
from src.sparks.engine import BattleEngine
from src.sparks.idempotency import IdempotentWriter
from src.sparks.policy import ActionPolicy, Mood
from src.sparks.progression import ProgressionService
from src.sparks.repository import SparkRepository, SqliteSparkRepository
from src.sparks.runtime import Clock, RandomSource, SystemClock, SystemRandom
from src.sparks.shop import ShopService
from src.sparks.situation import (
    FallbackSituationReader,
    HeuristicSituationReader,
    LayaPartialSituationReader,
    SituationReader,
    SituationViewBuilder,
)


def build_spark_services(
    config: AppConfig, laya: LayaClient, catalog: Catalog | None = None, repository: SparkRepository | None = None,
    clock: Clock | None = None, rng: RandomSource | None = None,
) -> SparkServices:
    """Everything is injected, so tests and other front ends can swap any part."""
    catalog = catalog or Catalog.load(config.catalog_path)
    clock, rng = clock or SystemClock(), rng or SystemRandom()
    repository = repository or SqliteSparkRepository(config.database_path)
    writer = IdempotentWriter(repository, clock)
    engine = BattleEngine(catalog)
    progression = ProgressionService(catalog, clock, config.faint_seconds)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    reader: SituationReader = (
        FallbackSituationReader(LayaPartialSituationReader(laya), heuristic) if config.situation_source == "laya" else heuristic
    )
    situation_views = SituationViewBuilder(engine)
    decider = ActionDecider(catalog, engine, ActionPolicy(catalog.policy), Mood(catalog), reader, situation_views)
    coordinator = RoundCoordinator(
        repository, writer, catalog, engine, decider, situation_views, LayaEmblemPicker(laya), progression,
        BattleViewBuilder(engine, catalog), clock, CoordinatorSettings(config.emblem_prompt_seconds),
    )
    return SparkServices(
        catalog=catalog,
        collection=CollectionService(repository, writer, catalog, clock, rng, config.encounter_cooldown_seconds),
        encounters=EncounterService(repository, writer, catalog, clock, rng, config.encounter_cooldown_seconds),
        shop=ShopService(writer, catalog, progression),
        coordinator=coordinator,
    )
```

`apps/mini_games/src/run.py`

```python
"""Start the mini_games backend: `python -m src.run`."""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from src.app import create_app
from src.auth import load_token
from src.config import AppConfig, load_config
from src.laya_client import LayaClient, LayaError
from src.sparks.api import mount_sparks
from src.sparks.composition import build_spark_services

log = logging.getLogger("mini_games")


def build_app() -> tuple[FastAPI, AppConfig]:
    config = load_config()
    laya = LayaClient(timeout=config.laya_timeout_seconds, min_confidence=config.laya_min_confidence)
    if laya.is_available():
        try:
            laya.prepare()
            log.info("Laya loaded")
        except LayaError as error:
            log.warning("Laya could not be loaded; game decisions will use heuristics: %s", error)
    else:
        log.info("Laya is not installed; game decisions will use heuristics")
    app = create_app(load_token())
    mount_sparks(app, build_spark_services(config, laya))
    return app, config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app, config = build_app()
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
```

`apps/mini_games/run.bat`

```bat
@echo off
REM mini_games dev launcher - serves the game backend (Emberlings) over HTTP on the
REM port in configs\config_app.json (8060 by default).
REM LABEL: Mini Games
REM DESCRIPTION: Game backend for Ember (Emberlings: collect and battle Sparks). Battle engine, Laya-assisted AI and saved progress. No LLM, no billing.

cd /d "%~dp0"

if not exist ".venv_mini_games\Scripts\python.exe" (
    echo Creating virtual environment .venv_mini_games ...
    py -m venv .venv_mini_games
    call .venv_mini_games\Scripts\activate
    echo Installing mini_games in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_mini_games\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  mini_games stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_api.py -q`
Expected: 21 passed (a starlette `httpx` deprecation warning is harmless).

- [ ] **Step 5: Smoke-test the real process**

Run `apps/mini_games/run.bat` in one terminal (it seeds `configs/config_app.json` and `secrets/.env` from the examples). In another:

```bash
curl -s http://127.0.0.1:8060/health
curl -s -X POST -H "X-Requester-Username: ann" -H "Idempotency-Key: first" -H "Content-Type: application/json" -d '{"starter_species_id":"striker"}' http://127.0.0.1:8060/sparks/profile
curl -s -X POST -H "X-Requester-Username: ann" -H "Idempotency-Key: second" http://127.0.0.1:8060/sparks/encounters
```

Expected: `{"status":"ok"}`, then a profile JSON with one level-1 Striker and five Normal EMBLEMs, then an encounter preview (species, tier, level, no personalities). With a token set in `secrets/.env` the second and third calls return 401 until `-H "X-Internal-Token: <value>"` is added. Stop the server (Ctrl+C, then `Q`). `data/sparks.sqlite3` now exists and must show as untracked-and-ignored in `git status`.

- [ ] **Step 6: Commit**

```bash
git add apps/mini_games/src/app.py apps/mini_games/src/sparks/api.py apps/mini_games/src/sparks/composition.py apps/mini_games/src/run.py apps/mini_games/run.bat apps/mini_games/tests/sparks/test_api.py
git status --short   # no configs/config_app.json, no secrets/.env, no data/
git commit -m "feat(mini_games): Emberlings HTTP API and entry point"
```

---

### Task 14: Battle simulation and the Laya evaluation

**Files:**
- Create: `apps/mini_games/src/sparks/simulation.py`, `src/sparks/eval/__init__.py` (empty), `src/sparks/eval/situation_eval.py`
- Test: `apps/mini_games/tests/sparks/test_simulation.py`, `apps/mini_games/tests/sparks/test_situation_eval.py`

**Interfaces:**
- Produces (`simulation`): `Combatant(species_id, tier_id, level, personalities, reader)`, `SimulationReport(winner, ended_by, rounds, actions, views)` with `share(side, category)`, `BattleSimulator(catalog, engine=None).run(player, wild, seed, max_rounds=60)` (same engine and `ActionDecider` as a real battle; neither side can collect), `personality_set(catalog, *types_and_tiers)`.
- Produces (`situation_eval`): `QuestionStats`, `EvalReport` with `.verdict`, `collect_views`, `measure_reads`, `monotonic_agreement`, `win_rate`, `evaluate`, `render_report`, `run`, `main`; constants `MIN_CONFIDENT_RATE = 0.7`, `MIN_MONOTONIC = 0.8`, `MIN_WIN_GAIN = 0.05`, `MIN_BATTLES = 100`. Run manually: `python -m src.sparks.eval.situation_eval`; it writes `docs/emberlings-laya-eval.md`. The verdict is `laya` only when danger and advantage are answered confidently at least 70% of the time, danger rises as HP falls in at least 80% of paired reads, and, over at least 100 battles, a Spark using Laya's reads wins at least five points more often than one using the heuristics.
- The simulation tests also verify the spec's personality claims on the engine's own distributions: AGGRESSIVE attacks more than COWARD, COWARD flees more, no personality collapses to one category in durable matchups, and low HP raises DEFENSE and FEAR for every personality.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/sparks/test_simulation.py`

```python
import asyncio
from pathlib import Path

import pytest

from src.sparks.catalog import Catalog
from src.sparks.models import PLAYER, WILD
from src.sparks.simulation import BattleSimulator, Combatant, personality_set
from src.sparks.situation import HeuristicSituationReader

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
sim = BattleSimulator(CATALOG)
reader = HeuristicSituationReader(CATALOG.policy.default_aggression)


def spark(species="striker", level=5, personalities=(), tier="normal"):
    return Combatant(species, tier, level, personality_set(CATALOG, *personalities), reader)


def run(coro):
    return asyncio.run(coro)


def test_a_battle_finishes_and_the_same_seed_replays_exactly():
    a, b = spark(personalities=[("AGGRESSIVE", 2)]), spark("bruiser", personalities=[("BOLD", 2)])
    first, second = run(sim.run(a, b, seed=4)), run(sim.run(a, b, seed=4))
    assert first == second and first.ended_by != "round_limit" and first.rounds >= 1
    assert sum(first.actions[PLAYER].values()) == len(first.views)


def test_a_much_stronger_spark_wins():
    strong = spark("forbidden", level=40, tier="forbidden", personalities=[("AGGRESSIVE", 3)])
    weak = spark("guardian", level=1, personalities=[("AGGRESSIVE", 3)])
    results = [run(sim.run(strong, weak, seed=s)).winner for s in range(10)]
    assert WILD not in results and results.count(PLAYER) >= 8  # the weak side may escape, but never wins


def shares(personality, category, side, battles=120):
    me = spark(personalities=[personality])
    other = spark("guardian", personalities=[("DEFENSIVE", 1)])
    reports = [run(sim.run(me, other, seed=s, max_rounds=30)) for s in range(battles)]
    return sum(r.share(side, category) for r in reports) / battles


def test_aggressive_attacks_more_often_than_coward_and_coward_flees_more_often():
    aggressive_attack = shares(("AGGRESSIVE", 3), "ATTACK", PLAYER)
    coward_attack = shares(("COWARD", 3), "ATTACK", PLAYER)
    aggressive_flee = shares(("AGGRESSIVE", 3), "FEAR", PLAYER)
    coward_flee = shares(("COWARD", 3), "FEAR", PLAYER)
    assert aggressive_attack > coward_attack
    assert coward_flee > aggressive_flee


def test_neither_personality_collapses_to_one_action():
    """Evenly matched, durable Sparks fight for many rounds; no personality repeats one category."""
    for personality in ("AGGRESSIVE", "COWARD", "DEFENSIVE"):
        mine = spark("sentinel", level=20, personalities=[(personality, 3)])
        reports = [run(sim.run(mine, spark("sentinel", level=20, personalities=[("DISCIPLINED", 2)]), seed=s, max_rounds=30))
                   for s in range(40)]
        totals: dict[str, int] = {}
        for r in reports:
            for category, n in r.actions[PLAYER].items():
                totals[category] = totals.get(category, 0) + n
        assert sum(totals.values()) > 200 and max(totals.values()) / sum(totals.values()) < 0.85, (personality, totals)


def test_low_hp_makes_every_personality_more_defensive_or_fearful():
    low, high = _situation_probabilities(0.1), _situation_probabilities(1.0)
    assert low["DEFENSE"] + low["FEAR"] > high["DEFENSE"] + high["FEAR"]


def _situation_probabilities(own_hp_fraction):
    from src.sparks.models import Action
    from src.sparks.policy import ActionPolicy, PolicyContext
    from src.sparks.situation import SituationView

    view = SituationView(3, own_hp_fraction, 0.8, 40, 40, 20, 20, ("ATTACK",), ("ATTACK",))
    situation = reader.compute(view)
    actions = [Action("attack", "ATTACK"), Action("ability", "DEFENSE", "g", 150), Action("ability", "SUPPORT", "s", 50),
               Action("flee", "FEAR"), Action("catch", "INTERCEPT")]
    ctx = PolicyContext(situation, 0.8, 0.1, True, (), {"ATTACK": 3.0})  # an aggressive personality
    p = ActionPolicy(CATALOG.policy).probabilities(actions, ctx)
    return {"DEFENSE": p[1], "FEAR": p[3]}


def test_neither_side_can_collect_in_a_simulation():
    report = run(sim.run(spark(), spark("sentinel"), seed=2, max_rounds=40))
    assert "captured" != report.ended_by and "INTERCEPT" not in report.actions[PLAYER]


@pytest.mark.parametrize("max_rounds", [1, 2])
def test_the_round_limit_stops_a_long_battle(max_rounds):
    tank_a, tank_b = spark("sentinel", level=30, personalities=[("DEFENSIVE", 3)]), spark("sentinel", level=30, personalities=[("DEFENSIVE", 3)])
    report = run(sim.run(tank_a, tank_b, seed=1, max_rounds=max_rounds))
    assert report.rounds <= max_rounds
```

`apps/mini_games/tests/sparks/test_situation_eval.py`

```python
import asyncio
from datetime import date
from pathlib import Path


from src.laya_client import LayaClient
from src.sparks.catalog import Catalog
from src.sparks.eval import situation_eval as ev
from src.sparks.simulation import BattleSimulator
from src.sparks.situation import (
    HeuristicSituationReader,
    LayaPartialSituationReader,
    PartialSituation,
    SituationView,
)
from tests.fake_laya import FakeEngine

CATALOG = Catalog.load(Path(__file__).resolve().parents[2] / "configs" / "spark_catalog.json")
sim = BattleSimulator(CATALOG)
heuristic = HeuristicSituationReader()


def run(coro):
    return asyncio.run(coro)


class SensibleReader:
    """A partial reader whose reads move the right way."""

    async def read_partial(self, view: SituationView) -> PartialSituation:
        attack_share = view.enemy_history.count("ATTACK") / len(view.enemy_history) if view.enemy_history else None
        return PartialSituation(1 - view.own_hp_fraction, attack_share, 0.5)


class ConstantReader:
    async def read_partial(self, view: SituationView) -> PartialSituation:
        return PartialSituation(0.5, 0.5, 0.5)


class SilentReader:
    async def read_partial(self, view: SituationView) -> PartialSituation:
        return PartialSituation()


def test_collected_views_are_realistic_and_reproducible():
    a, b = run(ev.collect_views(sim, CATALOG, 25, seed=3)), run(ev.collect_views(sim, CATALOG, 25, seed=3))
    assert len(a) == 25 and a == b and all(0 < v.own_hp_fraction <= 1 for v in a)
    assert any(v.enemy_history for v in a) and any(not v.enemy_history for v in a)


def test_read_statistics_count_confident_answers_and_skip_round_one_aggression():
    views = run(ev.collect_views(sim, CATALOG, 30, seed=1))
    stats, latency = run(ev.measure_reads(LayaPartialSituationReader(LayaClient(FakeEngine())), views))
    assert stats["danger"].rate == 1.0 and stats["advantage"].asked == 30 and latency >= 0
    assert stats["aggression"].asked == sum(1 for v in views if v.enemy_history)
    silent, _ = run(ev.measure_reads(SilentReader(), views))
    assert silent["danger"].rate == 0.0


def test_uncertain_answers_lower_the_confident_rate():
    views = run(ev.collect_views(sim, CATALOG, 10, seed=1))
    stats, _ = run(ev.measure_reads(LayaPartialSituationReader(LayaClient(FakeEngine(confidence=0.3))), views))
    assert stats["danger"].confident == 0 and stats["danger"].asked == 10


def test_monotonic_agreement_tells_sensible_reads_from_constant_ones():
    views = run(ev.collect_views(sim, CATALOG, 12, seed=2))
    assert run(ev.monotonic_agreement(SensibleReader(), views)) == (1.0, 1.0)
    assert run(ev.monotonic_agreement(ConstantReader(), views)) == (0.0, 0.0)
    assert run(ev.monotonic_agreement(SilentReader(), views)) == (0.0, 0.0)


def test_win_rates_compare_two_readers_over_identical_matchups():
    same_a = run(ev.win_rate(sim, CATALOG, heuristic, 20, seed=4))
    same_b = run(ev.win_rate(sim, CATALOG, heuristic, 20, seed=4))
    assert same_a == same_b and 0.0 <= same_a <= 1.0


def test_the_whole_evaluation_runs_with_a_fake_model():
    report = run(ev.evaluate(CATALOG, LayaClient(FakeEngine()), views=12, battles=6, seed=5))
    assert report.views == 12 and report.battles == 6 and report.verdict == "heuristic"  # too few battles to qualify


def report(**changes):
    base = dict(views=100, danger=ev.QuestionStats(100, 90), aggression=ev.QuestionStats(80, 60), advantage=ev.QuestionStats(100, 85),
                mean_latency=0.2, danger_monotonic=0.9, aggression_monotonic=0.8, battles=150, laya_win_rate=0.58, heuristic_win_rate=0.5)
    return ev.EvalReport(**{**base, **changes})


def test_every_gate_must_pass_for_a_laya_verdict():
    assert report().verdict == "laya"
    for change in (
        dict(danger=ev.QuestionStats(100, 60)), dict(advantage=ev.QuestionStats(100, 69)), dict(danger_monotonic=0.79),
        dict(battles=99), dict(laya_win_rate=0.54), dict(laya_win_rate=0.4),
    ):
        assert report(**change).verdict == "heuristic", change


def test_the_report_states_results_gates_and_verdict():
    text = ev.render_report(report(), seed=7, today=date(2026, 10, 10))
    assert "2026-10-10" in text and "Seed: 7" in text and "Danger higher at low HP | 90%" in text
    assert "`situation_source` = `laya`" in text and "No gate was relaxed" in text
    assert "`heuristic`" in ev.render_report(report(battles=10), seed=7, today=date(2026, 10, 10))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/sparks/test_simulation.py tests/sparks/test_situation_eval.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sparks.simulation'`.

- [ ] **Step 3: Write the implementation**

```bash
mkdir -p apps/mini_games/src/sparks/eval && touch apps/mini_games/src/sparks/eval/__init__.py
```

`apps/mini_games/src/sparks/simulation.py`

```python
"""AI against AI battles, for tuning balance and checking that personalities
change behaviour. The same engine and decider as a real battle, with no database
and no clock. Neither side can collect, so a battle ends by knockout or escape."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.sparks.catalog import Catalog
from src.sparks.decider import ActionDecider
from src.sparks.engine import BattleEngine
from src.sparks.models import PLAYER, SIDES, WILD, BattleSetup, PersonalityInstance
from src.sparks.policy import ActionPolicy, Mood
from src.sparks.runtime import SeededRandom
from src.sparks.situation import SituationReader, SituationView, SituationViewBuilder

WINNER_BY_TERMINAL = {"won": PLAYER, "knocked_out": WILD}


@dataclass(frozen=True)
class Combatant:
    species_id: str
    tier_id: str
    level: int
    personalities: tuple[PersonalityInstance, ...]
    reader: SituationReader


@dataclass(frozen=True)
class SimulationReport:
    winner: str | None  # PLAYER or WILD; None when someone escaped or the round limit hit
    ended_by: str  # won, knocked_out, escaped, wild_escaped or round_limit
    rounds: int
    actions: dict[str, dict[str, int]]  # side -> category -> times chosen
    views: tuple[SituationView, ...] = field(default=(), compare=False)  # the player's view each round

    def share(self, side: str, category: str) -> float:
        counts = self.actions[side]
        total = sum(counts.values())
        return counts.get(category, 0) / total if total else 0.0


class BattleSimulator:
    def __init__(self, catalog: Catalog, engine: BattleEngine | None = None) -> None:
        self._catalog = catalog
        self._engine = engine or BattleEngine(catalog)
        self._policy, self._mood = ActionPolicy(catalog.policy), Mood(catalog)
        self._views = SituationViewBuilder(self._engine)

    async def run(self, player: Combatant, wild: Combatant, seed: int, max_rounds: int = 60) -> SimulationReport:
        setup = BattleSetup(
            self._engine.build_fighter(PLAYER, player.species_id, player.tier_id, player.level),
            self._engine.build_fighter(WILD, wild.species_id, wild.tier_id, wild.level),
        )
        deciders = {
            side: ActionDecider(self._catalog, self._engine, self._policy, self._mood, who.reader, self._views)
            for side, who in ((PLAYER, player), (WILD, wild))
        }
        instances = {PLAYER: player.personalities, WILD: wild.personalities}
        state = self._engine.start_state(setup)
        rng = SeededRandom(seed)
        counts: dict[str, dict[str, int]] = {side: {} for side in SIDES}
        seen: list[SituationView] = []
        for _ in range(max_rounds):
            seen.append(self._views.build(setup, state, PLAYER))
            chosen = {}
            for side in SIDES:
                decision = await deciders[side].decide(setup, state, side, instances[side], rng, can_collect=False)
                chosen[side] = decision.action
                counts[side][decision.action.category] = counts[side].get(decision.action.category, 0) + 1
            outcome = self._engine.resolve_round(setup, state, chosen[PLAYER], chosen[WILD], rng)
            state = outcome.state
            if outcome.terminal:
                return SimulationReport(WINNER_BY_TERMINAL.get(outcome.terminal), outcome.terminal, state.round, counts, tuple(seen))
        return SimulationReport(None, "round_limit", max_rounds, counts, tuple(seen))


def personality_set(catalog: Catalog, *types_and_tiers: tuple[str, int]) -> tuple[PersonalityInstance, ...]:
    """Convenience for tests and tuning: ("AGGRESSIVE", 3) -> a PersonalityInstance."""
    return tuple(PersonalityInstance(f"sim-{i}", type_id, tier) for i, (type_id, tier) in enumerate(types_and_tiers))
```

`apps/mini_games/src/sparks/eval/situation_eval.py`

```python
"""Do Laya's situation reads earn their place? Run manually with the real model:

    python -m src.sparks.eval.situation_eval [--views N] [--battles N] [--seed S] [--out PATH]

Needs `pip install -e ".[laya]"`. Not part of the test suite. It measures, on
matched states, how often Laya answers confidently, whether its reads move the
right way (danger rises as HP falls; enemy aggression rises with the enemy's
ATTACK share), how slowly it answers, and whether a Spark that uses Laya's reads
beats one that uses the engine heuristics. The default `situation_source` stays
`heuristic` unless every gate below passes.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Sequence

from src.config import load_config
from src.laya_client import DEFAULT_MODEL, LayaClient
from src.sparks.catalog import Catalog
from src.sparks.models import PLAYER, PersonalityInstance
from src.sparks.simulation import BattleSimulator, Combatant
from src.sparks.situation import (
    FallbackSituationReader,
    HeuristicSituationReader,
    LayaPartialSituationReader,
    PartialSituationReader,
    SituationReader,
    SituationView,
)

OUT_PATH = Path(__file__).resolve().parents[3] / "docs" / "emberlings-laya-eval.md"
MIN_CONFIDENT_RATE = 0.7  # danger and advantage answers that are valid and confident
MIN_MONOTONIC = 0.8  # danger rises as HP falls
MIN_WIN_GAIN = 0.05  # win rate with Laya reads minus win rate with heuristics
MIN_BATTLES = 100
LOW_HP, HIGH_HP = 0.15, 0.9


@dataclass(frozen=True)
class QuestionStats:
    asked: int
    confident: int

    @property
    def rate(self) -> float:
        return self.confident / self.asked if self.asked else 0.0


@dataclass(frozen=True)
class EvalReport:
    views: int
    danger: QuestionStats
    aggression: QuestionStats
    advantage: QuestionStats
    mean_latency: float
    danger_monotonic: float
    aggression_monotonic: float
    battles: int
    laya_win_rate: float
    heuristic_win_rate: float

    @property
    def verdict(self) -> str:
        enough = self.battles >= MIN_BATTLES
        passed = (
            self.danger.rate >= MIN_CONFIDENT_RATE and self.advantage.rate >= MIN_CONFIDENT_RATE
            and self.danger_monotonic >= MIN_MONOTONIC and enough
            and self.laya_win_rate - self.heuristic_win_rate >= MIN_WIN_GAIN
        )
        return "laya" if passed else "heuristic"


def random_combatant(catalog: Catalog, rng: random.Random, reader: SituationReader) -> Combatant:
    species = rng.choice(catalog.regular_species())
    types = list(catalog.personalities)
    instances = tuple(PersonalityInstance(f"e{n}", rng.choice(types), rng.randint(1, 3)) for n in range(rng.randint(1, 3)))
    return Combatant(species.id, "normal", rng.randint(3, 25), instances, reader)


async def collect_views(simulator: BattleSimulator, catalog: Catalog, count: int, seed: int) -> list[SituationView]:
    """Situations reached in AI-against-AI battles, so the questions see realistic states."""
    rng = random.Random(seed)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    views: list[SituationView] = []
    while len(views) < count:
        a, b = random_combatant(catalog, rng, heuristic), random_combatant(catalog, rng, heuristic)
        report = await simulator.run(a, b, seed=rng.randrange(10**9), max_rounds=40)
        views.extend(report.views)
    return views[:count]


async def measure_reads(reader: PartialSituationReader, views: Sequence[SituationView]) -> tuple[dict[str, QuestionStats], float]:
    asked = {"danger": 0, "aggression": 0, "advantage": 0}
    confident = dict.fromkeys(asked, 0)
    elapsed = 0.0
    for view in views:
        started = time.monotonic()
        partial = await reader.read_partial(view)
        elapsed += time.monotonic() - started
        for name in asked:
            if name == "aggression" and not view.enemy_history:
                continue  # never asked in round 1
            asked[name] += 1
            confident[name] += getattr(partial, name) is not None
    return {n: QuestionStats(asked[n], confident[n]) for n in asked}, elapsed / max(len(views), 1)


async def monotonic_agreement(reader: PartialSituationReader, views: Sequence[SituationView]) -> tuple[float, float]:
    """Share of paired reads where danger is higher at low HP and where enemy aggression is higher
    after ATTACK-only history than after DEFENSE-only history. Pairs with a missing read are skipped."""
    danger_hits = danger_pairs = aggression_hits = aggression_pairs = 0
    for view in views:
        low = await reader.read_partial(replace(view, own_hp_fraction=LOW_HP))
        high = await reader.read_partial(replace(view, own_hp_fraction=HIGH_HP))
        if low.danger is not None and high.danger is not None:
            danger_pairs += 1
            danger_hits += low.danger > high.danger
        attacking = await reader.read_partial(replace(view, enemy_history=("ATTACK",) * 4))
        defending = await reader.read_partial(replace(view, enemy_history=("DEFENSE",) * 4))
        if attacking.aggression is not None and defending.aggression is not None:
            aggression_pairs += 1
            aggression_hits += attacking.aggression > defending.aggression
    return (danger_hits / danger_pairs if danger_pairs else 0.0, aggression_hits / aggression_pairs if aggression_pairs else 0.0)


async def win_rate(simulator: BattleSimulator, catalog: Catalog, reader: SituationReader, battles: int, seed: int) -> float:
    """Wins of a Spark that uses `reader` against one that uses the heuristic, over the same matchups."""
    rng = random.Random(seed)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    wins = 0
    for _ in range(battles):
        mine, theirs = random_combatant(catalog, rng, reader), random_combatant(catalog, rng, heuristic)
        report = await simulator.run(mine, theirs, seed=rng.randrange(10**9), max_rounds=40)
        wins += report.winner == PLAYER
    return wins / battles


async def evaluate(catalog: Catalog, laya: LayaClient, views: int, battles: int, seed: int) -> EvalReport:
    simulator = BattleSimulator(catalog)
    heuristic = HeuristicSituationReader(catalog.policy.default_aggression)
    partial = LayaPartialSituationReader(laya)
    sample = await collect_views(simulator, catalog, views, seed)
    stats, latency = await measure_reads(partial, sample)
    danger_monotonic, aggression_monotonic = await monotonic_agreement(partial, sample[: max(views // 4, 1)])
    laya_rate = await win_rate(simulator, catalog, FallbackSituationReader(partial, heuristic), battles, seed + 1)
    heuristic_rate = await win_rate(simulator, catalog, heuristic, battles, seed + 1)
    return EvalReport(views, stats["danger"], stats["aggression"], stats["advantage"], latency,
                      danger_monotonic, aggression_monotonic, battles, laya_rate, heuristic_rate)


def render_report(report: EvalReport, seed: int, today: date) -> str:
    rate = lambda s: f"{s.rate:.0%} of {s.asked}"  # noqa: E731
    return "\n".join([
        "# Emberlings: Laya situation reads", "",
        f"Date: {today.isoformat()}. Model: `{DEFAULT_MODEL}`. Seed: {seed}. Views: {report.views}. Battles per side: {report.battles}.", "",
        "| Measure | Result | Gate |", "|---|---|---|",
        f"| Danger answered confidently | {rate(report.danger)} | at least {MIN_CONFIDENT_RATE:.0%} |",
        f"| Advantage answered confidently | {rate(report.advantage)} | at least {MIN_CONFIDENT_RATE:.0%} |",
        f"| Enemy aggression answered confidently | {rate(report.aggression)} | reported only |",
        f"| Danger higher at low HP | {report.danger_monotonic:.0%} | at least {MIN_MONOTONIC:.0%} |",
        f"| Aggression higher after ATTACK history | {report.aggression_monotonic:.0%} | reported only |",
        f"| Mean latency per read | {report.mean_latency:.2f} s | reported only |",
        f"| Win rate with Laya reads | {report.laya_win_rate:.0%} | |",
        f"| Win rate with heuristic reads | {report.heuristic_win_rate:.0%} | Laya at least {MIN_WIN_GAIN:.0%} higher, with {MIN_BATTLES}+ battles |",
        "", f"**Verdict: `situation_source` = `{report.verdict}`.** Set it in `configs/config_app.json` and its `.example`.", "",
        "Positions and battles come from simulated play, not from real players. Personality influence is tested on the "
        "engine's own distributions (`tests/sparks/test_simulation.py`), not on the model. No gate was relaxed to reach a verdict.", "",
    ])


async def run(views: int, battles: int, seed: int, out: Path) -> str:
    config = load_config()
    laya = LayaClient(timeout=30.0, min_confidence=config.laya_min_confidence)
    if not laya.is_available():
        raise SystemExit('Laya is not installed: pip install -e ".[laya]"')
    laya.prepare()
    report = await evaluate(Catalog.load(config.catalog_path), laya, views, battles, seed)
    text = render_report(report, seed, date.today())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--views", type=int, default=120)
    parser.add_argument("--battles", type=int, default=150)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    print(asyncio.run(run(args.views, args.battles, args.seed, args.out)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the whole suite**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest -q`
Expected: 474 passed (about 15 seconds).

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sparks/simulation.py apps/mini_games/src/sparks/eval apps/mini_games/tests/sparks/test_simulation.py apps/mini_games/tests/sparks/test_situation_eval.py
git commit -m "feat(mini_games): battle simulator and Laya situation evaluation"
```

---

### Task 15: README, scaffold audit and launcher check

**Files:**
- Create: `apps/mini_games/README.md`

- [ ] **Step 1: Write the README**

`apps/mini_games/README.md`

````markdown
# mini_games

Game backend for Ember. It hosts **Emberlings**, a game of collecting and
battling **Sparks**, with a local Laya model helping the AI read the battle. It
never calls an LLM, so it costs nothing to play. Chess and Tetris will plug in
later as further games (see `docs/superpowers/` at the repo root).

Specs and plans: `docs/superpowers/specs/2026-10-10-emberlings-backend-design.md`
and `docs/superpowers/plans/2026-10-10-emberlings-backend.md`; the decision record
is `docs/superpowers/specs/2026-10-09-emberlings-decisions.md`.

Part of a series. This project is the backend only; the `ember_api` proxy, the
`ember_web` pages and the chat tools come in later specs.

## The game in short

- You choose a starter Spark (Guardian, Striker or Scout), then roll wild
  encounters. The preview shows species, tier and level; personalities stay hidden.
- A battle is 1v1 against a wild Spark. Each round both sides choose in secret,
  then the actions are revealed and resolved together: SUPPORT, then DEFENSE,
  then a speed-weighted order for ATTACK, CATCH and FLEE.
- **CATCH** collects the wild Spark with an EMBLEM. Winning or collecting pays XP
  and Insignia; collecting also adds copies and one random personality.
- Sparks keep absorbed copies, which set their tier; Insignia buys EMBLEMs and
  copies in the shop.
- Play manually, or let your Spark play on its own with a personality preset.

## How a Spark chooses on its own

A fixed personality fed to a classifier would pick the same action every time, so
the engine owns the choice. Laya only reads the situation:

1. Laya answers three short typed questions (danger, enemy aggression, advantage)
   about a public-state text. If a read is uncertain, invalid, late or missing, an
   engine heuristic supplies that value instead.
2. The engine turns those values, the round's personality weights (one equipped
   personality leads each round), a potency term and a repeat penalty into action
   probabilities, then draws with the battle's seeded random stream.

`situation_source` in `configs/config_app.json` is `heuristic` (the default) or
`laya`. Choose `laya` only if `docs/emberlings-laya-eval.md`, produced by the manual
evaluation, says so. EMBLEM choice after a timed-out prompt always asks Laya, and
falls back to basic ATTACK.

## Requirements

- Python 3.11 or newer on Windows (`py` launcher).
- Optional: the `laya` package (`pip install -e ".[laya]"`).

## Run

```
run.bat
```

The first start creates `.venv_mini_games`, installs the project and creates
`configs/config_app.json` and `secrets/.env` from their `.example` twins. Both
real files are gitignored; `configs/spark_catalog.json` (species, abilities,
tiers, economy and policy numbers) is tracked. Put the same `INTERNAL_API_TOKEN`
in `secrets/.env` that `mcp_server`, `ai_agent` and `ember_api` use; once set,
every route except `/health` needs the `X-Internal-Token` header. Game data lives
in `data/sparks.sqlite3` (gitignored).

`server_launcher` lists this project from its `run.bat`. Default port 8060.

## API

Every route except `/health` needs `X-Internal-Token` (once configured) and
`X-Requester-Username`, the owner of all records. Mutations also need an
`Idempotency-Key` header; a retry with the same key returns the first result.
Bodies reject unknown fields. Round mutations carry the `round` and `revision` you
last saw; a stale pair is a 409.

| Route | Purpose |
|---|---|
| `GET /sparks/catalog` | Species, abilities, tiers, personalities, shop data |
| `POST /sparks/profile` | Create the profile with a starter |
| `GET /sparks/profile` | Wallet, Sparks, timers, pending encounter, active battle |
| `GET /sparks/species/{id}/personalities` | Collected personality instances (paginated) |
| `GET`/`PUT /sparks/species/{id}/presets/{slot}` | One of five presets (up to three instances) |
| `POST /sparks/encounters` | Roll a preview (one per 30 seconds) |
| `GET /sparks/encounters/{id}` | The same preview, never rerolled |
| `POST /sparks/encounters/{id}/decline` | Decline for free |
| `POST /sparks/battles` | Start the battle: Spark, preset, mode, EMBLEM limit |
| `GET /sparks/battles/{id}` | Public state, legal actions, history, result |
| `POST /sparks/battles/{id}/actions` | Manual action for a round |
| `POST /sparks/battles/{id}/emblem` | Answer the five-second EMBLEM prompt |
| `POST /sparks/battles/{id}/advance` | Play one autonomous round, or settle an expired prompt |
| `POST /sparks/battles/{id}/mode` | Switch manual or autonomous between rounds |
| `POST /sparks/battles/{id}/forfeit` | End as a loss |
| `POST /sparks/shop/purchases` | Buy EMBLEMs or regular-species copies |
| `POST /sparks/species/{id}/sales` | Sell one absorbed copy |

Errors: 400 bad input or unknown species or tier, 401 bad token, 404 missing or
someone else's record, 409 state conflict (stale revision, wrong phase, not enough
Insignia, cooldown, one active battle).

Closing the game view simply stops calls to `advance`: the battle stays saved
between rounds and resumes where it was, including an open EMBLEM prompt and its
deadline. Timers run in real time while the service is stopped.

## Tests and the Laya evaluation

```
.venv_mini_games\Scripts\python -m pytest
.venv_mini_games\Scripts\python -m src.sparks.eval.situation_eval
```

The tests use a fake Laya engine. The evaluation needs the real model, is run by
hand and writes `docs/emberlings-laya-eval.md`.

## Layout

- `src/` - shared shell: config, auth, the Laya client, the FastAPI app.
- `src/sparks/` - Emberlings: catalog, battle engine, passives, action policy and
  decider, situation readers, repository, services, coordinator, API.
- `src/sparks/eval/` - the manual Laya evaluation.
- `configs/`, `secrets/` - gitignored real files with `.example` twins, plus the
  tracked `spark_catalog.json`.
- `data/` - SQLite database (created at runtime).
````

- [ ] **Step 2: Audit the folder against `root-project-scaffold`**

Run: `ls -A apps/mini_games`
Expected exactly: `.venv_mini_games`, `README.md`, `configs`, `data` (after the smoke test), `pyproject.toml`, `run.bat`, `secrets`, `src`, `tests` (and `docs` once Task 16 writes it). Any other entry is a convention break: move it under `src/` or remove it.

Run: `git check-ignore apps/mini_games/configs/config_app.json apps/mini_games/secrets/.env apps/mini_games/data apps/mini_games/.venv_mini_games`
Expected: all four paths are printed (ignored). `git ls-files apps/mini_games/configs apps/mini_games/secrets` lists exactly `config_app.json.example`, `spark_catalog.json` and `.env.example`.

- [ ] **Step 3: Check that server_launcher discovers it**

Start `apps/server_launcher/run.bat`. Expected: "Mini Games" appears in the project list (it reads the `REM LABEL:` and `REM DESCRIPTION:` lines of `run.bat`) and starting it brings up port 8060. If the launcher keeps a hardcoded project list, add the entry there and say so in the commit message.

- [ ] **Step 4: Commit**

```bash
git add apps/mini_games/README.md
git commit -m "docs(mini_games): README"
```

---

### Task 16: Run the Laya evaluation and set `situation_source` (manual, needs the real model)

**Files:**
- Create: `apps/mini_games/docs/emberlings-laya-eval.md` (written by the harness)
- Modify: `apps/mini_games/configs/config_app.json.example`, and the real `configs/config_app.json` (gitignored)

This task needs the real `laya` package and checkpoint. If they cannot be installed, do Step 4 and stop.

- [ ] **Step 1: Install Laya into the project venv**

```bash
cd apps/mini_games && .venv_mini_games/Scripts/python -m pip install -e ".[laya]" && cd ../..
```

- [ ] **Step 2: Run the evaluation**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m src.sparks.eval.situation_eval --views 120 --battles 150 --seed 1`
Expected: prints the table and writes `docs/emberlings-laya-eval.md`. It takes several minutes; latency per read is in the table.

- [ ] **Step 3: Apply the verdict**

The last line of the report says `situation_source` = `laya` or `heuristic`. Set `"situation_source"` to that value in `configs/config_app.json.example` and in your real `configs/config_app.json`. Do not relax `MIN_CONFIDENT_RATE`, `MIN_MONOTONIC`, `MIN_WIN_GAIN` or `MIN_BATTLES` to reach a verdict. If results look noisy, rerun with another `--seed` and more `--views` and `--battles`, keeping the same gates.

- [ ] **Step 4: If Laya could not be run**

Create `apps/mini_games/docs/emberlings-laya-eval.md` with the date, the reason it was not run, and the sentence "`situation_source` stays `heuristic` until `python -m src.sparks.eval.situation_eval` is run."

- [ ] **Step 5: Run the whole suite and commit**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest -q`
Expected: 474 passed (a test that needs Laya to be absent skips itself if it is installed).

```bash
git add apps/mini_games/docs apps/mini_games/configs/config_app.json.example
git commit -m "docs(mini_games): Laya situation evaluation and situation_source"
```

---

## Self-Review

**Spec coverage** (`2026-10-10-emberlings-backend-design.md`)
- Architecture, three boundaries and the object-oriented structure: Tasks 5 to 13 (`BattleEngine`, `ActionPolicy` pure; `RoundCoordinator` and services; `SqliteSparkRepository`; every protocol in the class table, plus `CollectionService`, `ActionDecider`, `IdempotentWriter`, `BattleViewBuilder`, `EncounterRoller`, `BattleSimulator` which the spec table did not list).
- Collection and progression, stats and abilities, FLEE and CATCH formulas, personalities and presets, rewards, recovery and economy: Tasks 4, 6, 10, 11 (formulas are asserted exactly in the tests).
- Encounters and lifecycle (preview without personalities, decline, 30-second limit, one active battle, saved participants, no reroll, manual untimed, mode switch, pause by not calling `advance`, forfeit): Tasks 11, 12.
- Round state machine, simultaneous reveal, one SPEED roll, terminal preemption, atomic terminal results, persisted random draws: Tasks 6, 12.
- Action policy, situation reads, mood, EMBLEM selection and the evidence requirement: Tasks 7, 8, 12, 14, 16.
- Persistent model and API (table of routes, idempotency, round and revision, 404 for foreign, no client-supplied outcomes, pagination, deadlines on the server): Tasks 9, 10, 13.
- Verification list: phase order, cooldowns, buffs, defense, passives, formulas, preemption (Task 6); seeded repeatability and statistical order, tier and award checks (Tasks 6, 10, 11); ownership, once-only profile, duplicate personalities, preset limits, copy thresholds and downgrades, Forbidden caps, XP overflow, prices, no buy-and-resell profit (Tasks 9 to 11); restart checkpoints, five-second prompt and late answers, mode boundaries, one active battle, forfeit race, exactly-once rewards and EMBLEMs (Tasks 10, 12); fault-injected Laya and no private data in questions or views (Tasks 3, 8, 12).
- Out of scope, as the spec says: the Ember proxy and UI, chat tools, NPC players, artwork.

**Interpretations and deviations to confirm when reviewing**
- `locked` and `resolved` are never persisted (lock and resolution share one transaction); `choosing`, `awaiting_emblem` and `terminal` are.
- Routes use the prefix `/sparks` (the spec said the "Spark route family").
- Cooldowns start when an action is revealed, whether or not it later resolves; the decision record left this open.
- The wild action is not stored between rounds: it is decided from public state when the round is submitted and stored only while an EMBLEM prompt is open. A crash before commit replays the same draws.
- A collecting Spark may choose CATCH autonomously only if it owns an EMBLEM within its tier limit; the timeout fallback to basic ATTACK still covers EMBLEMs that disappear meanwhile.
- FLEE chance is computed with the HP the Spark has when the attempt resolves (after an earlier hit this round), while CATCH's reduction is settled first.
- Autonomous play needs a preset slot and an EMBLEM tier limit at battle start (or at the mode switch).
- Forbidden EMBLEMs are sold (the spec makes them purchasable); the Forbidden species is capture-only.
- The catalog's ability names and role names are working names; the spec still lists them as open.
- Policy numbers (gain 0.25, off-mood 0.5, repeat 0.5, the per-category formulas) are initial balance values to tune with `BattleSimulator`.
- `situation_source` defaults to `heuristic` until Task 16 measures Laya.
