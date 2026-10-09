# mini_games Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `apps/mini_games`, a standalone backend that hosts chess and Tetris engines, a Laya-assisted opponent and per-user game sessions behind an HTTP API.

**Architecture:** A `Game` protocol with one plugin per game (state is an immutable value, moves are JSON dicts). A conventional engine proposes and scores moves; a `Picker` chooses the bot's move from the engine's top candidates, and `LayaPicker` lets the local Laya model choose among them with the engine's best move as fallback. An in-memory `SessionStore` (per-session lock, turn check, owner isolation, TTL, per-user cap) sits behind a FastAPI app guarded by the shared internal token.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, python-chess, python-dotenv, pytest, httpx (test client), optional `laya` extra.

**Spec:** `docs/superpowers/specs/2026-10-09-mini-games-backend-design.md`

## Global Constraints

- Project folder is `apps/mini_games/`, shaped per `.agents/skills/root-project-scaffold/SKILL.md`: `README.md`, `pyproject.toml`, `run.bat`, `configs/`, `secrets/`, `src/`, `tests/`, plus `docs/` for the Laya eval. No other top-level folders.
- Own venv `.venv_mini_games` (gitignored by the root `.venv_*/` rule). Never import another project (`ai_agent`, `mcp_server`, ...). The Laya wrapper is a copy, not an import.
- Port 8060. Header names: `X-Internal-Token`, `X-Requester-Username`. `secrets/.env` holds `INTERNAL_API_TOKEN`; every route except `/health` rejects a missing or wrong token once it is set.
- Real `configs/config_app.json` and `secrets/.env` are gitignored and seeded from committed `.example` twins on first run.
- Laya limits: 512-token context window, text at most 4000 characters, a `choice` question takes 2 to 10 options, default `min_confidence` 0.7. `k` (candidates per move) is at most 10.
- The backend never calls an LLM and never bills. Laya is optional: if it is missing, slow or wrong, the engine's best move is used and the turn still succeeds.
- Non-blocking: engine search and Laya inference run in worker threads (`asyncio.to_thread`); nothing blocks the event loop. Sessions use one `asyncio.Lock` each.
- API errors: 400 illegal move, bad body, bad option or unknown game; 401 bad token; 404 unknown or foreign session; 409 wrong turn, game over or session cap.
- Sessions are in memory only; a restart ends all games. Tetris is a lockstep versus race (player places piece n, then the bot places piece n) with no garbage lines.
- All commands below run from the repo root `D:/User/Documents/Programming/Python/MCPServer` in Git Bash. The git repo is that root (paths in `git add` start with `apps/mini_games/`). Python is the project venv: `apps/mini_games/.venv_mini_games/Scripts/python`.
- Code files are given in full below. Every one was written and run against its tests before this plan was finalised (144 tests pass), so copy them exactly; if a test fails, fix the cause, do not loosen the test.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml`, `run.bat`, `README.md` | Project metadata, launcher, docs |
| `configs/config_app.json.example`, `secrets/.env.example` | Committed twins of the real, gitignored files |
| `src/seed.py` | Create a missing config/secret file from its `.example` |
| `src/config.py` | Typed `AppConfig` / `Difficulty` loader and validation |
| `src/auth.py` | Token loading and the ASGI token middleware |
| `src/games/base.py` | `Game` protocol, `Status`, `Candidate`, game errors |
| `src/games/chess_game.py` | Chess plugin: python-chess rules plus alpha-beta engine |
| `src/games/tetris_board.py` | Pure Tetris functions: pieces, drop, lock, scoring |
| `src/games/tetris_game.py` | Tetris versus plugin built on `tetris_board` |
| `src/games/registry.py` | The games the backend hosts |
| `src/opponent/laya_client.py` | Local Laya wrapper (`choose`) |
| `src/opponent/base.py`, `engine_picker.py`, `variety_picker.py`, `laya_picker.py` | `Picker` interface and its three implementations |
| `src/sessions.py` | `SessionStore`: sessions, locks, turn check, TTL, cap, views |
| `src/api.py`, `src/run.py` | FastAPI app and the process entry point |
| `src/eval/laya_eval.py` | Manual harness measuring Laya against random choice |
| `tests/` | One test file per module, plus `fake_laya.py` |

---

### Task 1: Project scaffold and config loader

**Files:**
- Create: `apps/mini_games/pyproject.toml`, `apps/mini_games/configs/config_app.json.example`, `apps/mini_games/secrets/.env.example`
- Create: `apps/mini_games/src/__init__.py`, `apps/mini_games/src/seed.py`, `apps/mini_games/src/config.py`
- Create: `apps/mini_games/tests/__init__.py`, `apps/mini_games/tests/conftest.py`, `apps/mini_games/tests/test_config.py`
- Modify: `.gitignore` (repo root)

**Interfaces:**
- Produces: `src.config.AppConfig`, `Difficulty(depth, k, time_limit, trust_uncertain)`, `ConfigError`, `load_config(path=None)`, `parse_config(raw)`, `PICKER_NAMES`, `MAX_CANDIDATES`; `src.seed.seed_from_example(path)`; fixture `config` in `tests/conftest.py`.

- [ ] **Step 1: Create the folders, the empty package files and the venv**

```bash
mkdir -p apps/mini_games/{src,tests,configs,secrets}
touch apps/mini_games/src/__init__.py apps/mini_games/tests/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`, the two `.example` files and the gitignore block**

`apps/mini_games/pyproject.toml`

```toml
[project]
name = "mini-games"
description = "Game backend: chess and Tetris engines, a Laya-assisted opponent and per-user game sessions behind an HTTP API"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "python-chess>=1.10,<2.0",
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
  "session_ttl_seconds": 3600,
  "max_sessions_per_user": 5,
  "laya_timeout_seconds": 5.0,
  "default_picker": {"chess": "variety", "tetris": "variety"},
  "difficulties": {
    "easy": {"depth": 1, "k": 5, "time_limit": 1.0, "trust_uncertain": true},
    "medium": {"depth": 2, "k": 4, "time_limit": 2.0, "trust_uncertain": false},
    "hard": {"depth": 3, "k": 3, "time_limit": 4.0, "trust_uncertain": false}
  }
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
# mini_games' real config and secrets - only the .example twins are committed.
/apps/mini_games/configs/*
!/apps/mini_games/configs/*.example
/apps/mini_games/secrets/*
!/apps/mini_games/secrets/*.example
```

- [ ] **Step 3: Create the venv and install**

```bash
cd apps/mini_games && py -m venv .venv_mini_games && .venv_mini_games/Scripts/python -m pip install -e ".[dev]" && cd ../..
```

Expected: install succeeds (fastapi, uvicorn, python-chess, python-dotenv, pytest, httpx).

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
    assert config.difficulties["medium"].depth == 2
    assert config.default_picker == {"chess": "variety", "tetris": "variety"}


@pytest.fixture
def raw():
    return json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))


def test_unknown_picker_is_rejected(raw):
    raw["default_picker"]["chess"] = "magic"
    with pytest.raises(ConfigError, match="default_picker"):
        parse_config(raw)


def test_k_above_ten_is_rejected(raw):
    raw["difficulties"]["easy"]["k"] = 11
    with pytest.raises(ConfigError, match="at most 10"):
        parse_config(raw)


def test_bool_is_not_a_number(raw):
    raw["port"] = True
    with pytest.raises(ConfigError, match="port"):
        parse_config(raw)


def test_missing_difficulties_is_rejected(raw):
    raw["difficulties"] = {}
    with pytest.raises(ConfigError, match="difficulties"):
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

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "config_app.json"
PICKER_NAMES = ("engine", "variety", "laya")
MAX_CANDIDATES = 10


class ConfigError(ValueError):
    """config_app.json is missing a field or holds a bad value."""


@dataclass(frozen=True)
class Difficulty:
    depth: int
    k: int
    time_limit: float
    trust_uncertain: bool


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    session_ttl_seconds: float
    max_sessions_per_user: int
    laya_timeout_seconds: float
    default_picker: dict[str, str]
    difficulties: dict[str, Difficulty]


def _number(raw: dict[str, Any], key: str, kind: type, minimum: float) -> Any:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ConfigError(f"{key} must be a number of at least {minimum}")
    return kind(value)


def _difficulty(name: str, raw: Any) -> Difficulty:
    if not isinstance(raw, dict):
        raise ConfigError(f"difficulty {name!r} must be an object")
    depth = _number(raw, "depth", int, 1)
    k = _number(raw, "k", int, 1)
    if k > MAX_CANDIDATES:
        raise ConfigError(f"difficulty {name!r}: k must be at most {MAX_CANDIDATES}")
    trust = raw.get("trust_uncertain")
    if not isinstance(trust, bool):
        raise ConfigError(f"difficulty {name!r}: trust_uncertain must be true or false")
    return Difficulty(depth, k, _number(raw, "time_limit", float, 0.1), trust)


def parse_config(raw: Any) -> AppConfig:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    host = raw.get("host")
    if not isinstance(host, str) or not host:
        raise ConfigError("host must be a non-empty string")
    pickers = raw.get("default_picker")
    if not isinstance(pickers, dict) or any(v not in PICKER_NAMES for v in pickers.values()):
        raise ConfigError(f"default_picker must map game ids to one of {', '.join(PICKER_NAMES)}")
    difficulties = raw.get("difficulties")
    if not isinstance(difficulties, dict) or not difficulties:
        raise ConfigError("difficulties must be a non-empty object")
    return AppConfig(
        host=host,
        port=_number(raw, "port", int, 1),
        session_ttl_seconds=_number(raw, "session_ttl_seconds", float, 1),
        max_sessions_per_user=_number(raw, "max_sessions_per_user", int, 1),
        laya_timeout_seconds=_number(raw, "laya_timeout_seconds", float, 0.1),
        default_picker=dict(pickers),
        difficulties={name: _difficulty(name, spec) for name, spec in difficulties.items()},
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
git status --short   # only the files listed above; no .venv_mini_games, no real config or .env
git commit -m "feat(mini_games): project scaffold and config loader"
```

---

### Task 2: Internal token auth

**Files:**
- Create: `apps/mini_games/src/auth.py`
- Test: `apps/mini_games/tests/test_auth.py`

**Interfaces:**
- Consumes: `src.seed.seed_from_example`.
- Produces: `src.auth.load_token(path=None) -> str`, `InternalTokenMiddleware(app, token)` (ASGI), `INTERNAL_TOKEN_HEADER`, `REQUESTER_USERNAME_HEADER`, `OPEN_PATHS`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_auth.py`

```python
import asyncio

from src.auth import InternalTokenMiddleware, load_token


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
    assert asyncio.run(_call("secret", "/sessions", {"X-Internal-Token": "nope"})) == 401


def test_missing_token_is_rejected():
    assert asyncio.run(_call("secret", "/sessions", {})) == 401


def test_right_token_passes():
    assert asyncio.run(_call("secret", "/sessions", {"X-Internal-Token": "secret"})) == 200


def test_health_is_open():
    assert asyncio.run(_call("secret", "/health", {})) == 200


def test_no_token_configured_passes_everything():
    assert asyncio.run(_call("", "/sessions", {})) == 200


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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_auth.py -q`
Expected: `ModuleNotFoundError: No module named 'src.auth'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/auth.py`

```python
"""The shared internal token, checked on every route but /health."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from dotenv import dotenv_values

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
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/auth.py apps/mini_games/tests/test_auth.py
git commit -m "feat(mini_games): internal token middleware"
```

---

### Task 3: Game protocol and the chess plugin

**Files:**
- Create: `apps/mini_games/src/games/__init__.py` (empty), `apps/mini_games/src/games/base.py`, `apps/mini_games/src/games/chess_game.py`
- Test: `apps/mini_games/tests/test_chess.py`

**Interfaces:**
- Produces (`src.games.base`): `Move = dict[str, Any]`; `GameError`, `IllegalMove(GameError)`, `InvalidOptions(GameError)`; `Status(finished, winner=None, reason="")`; `Candidate(move, score, features={})`; `Game` protocol with `id`, `option_schema()`, `assign_sides(options) -> (player, bot)`, `new_state(options)`, `side_to_move(state) -> str | None`, `legal_moves(state)`, `apply(state, move)`, `status(state)`, `evaluate(state, side) -> float`, `candidates(state, k, depth, time_limit) -> list[Candidate]`, `summarize(state, candidate) -> str`, `describe_position(state) -> str`, `to_dict(state) -> dict`.
- Produces (`src.games.chess_game`): `ChessGame`, `MATE = 10_000.0`. Chess state is a FEN string; a move is `{"uci": "e2e4"}`; sides are `"white"` / `"black"`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_chess.py`

```python
import chess
import pytest

from src.games.base import IllegalMove, InvalidOptions
from src.games.chess_game import MATE, ChessGame

game = ChessGame()
START = chess.STARTING_FEN
# White to move and mate in one with Qxf7#.
SCHOLARS = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"


def test_new_state_and_sides():
    assert game.new_state({}) == START
    assert game.assign_sides({}) == ("white", "black")
    assert game.assign_sides({"player_side": "black"}) == ("black", "white")


@pytest.mark.parametrize("options", [{"player_side": "green"}, {"speed": 1}])
def test_bad_options_are_rejected(options):
    with pytest.raises(InvalidOptions):
        game.new_state(options)


def test_legal_moves_at_the_start():
    assert len(game.legal_moves(START)) == 20
    assert game.side_to_move(START) == "white"


def test_apply_a_legal_move():
    after = game.apply(START, {"uci": "e2e4"})
    assert game.side_to_move(after) == "black"


@pytest.mark.parametrize("move", [{"uci": "e2e5"}, {"uci": "zz"}, {"uci": 5}, {}])
def test_illegal_moves_are_rejected(move):
    with pytest.raises(IllegalMove):
        game.apply(START, move)


def test_checkmate_status():
    state = game.apply(SCHOLARS, {"uci": "h5f7"})
    status = game.status(state)
    assert (status.finished, status.winner, status.reason) == (True, "white", "checkmate")
    assert game.side_to_move(state) is None


def test_ongoing_status():
    assert game.status(START).finished is False


def test_candidates_find_mate_in_one():
    best = game.candidates(SCHOLARS, k=3, depth=1, time_limit=5.0)[0]
    assert best.move == {"uci": "h5f7"}
    assert best.score > MATE / 2


def test_candidates_are_sorted_and_limited():
    cands = game.candidates(START, k=4, depth=2, time_limit=5.0)
    assert len(cands) == 4
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)


def test_candidates_take_a_free_queen():
    # Black queen hangs on d5 to the white pawn on e4.
    fen = "rnb1kbnr/ppp1pppp/8/3q4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 3"
    assert game.candidates(fen, k=1, depth=2, time_limit=5.0)[0].move == {"uci": "e4d5"}


def test_no_candidates_when_the_game_is_over():
    mated = game.apply(SCHOLARS, {"uci": "h5f7"})
    assert game.candidates(mated, k=3, depth=2, time_limit=1.0) == []


def test_timeout_keeps_the_last_finished_depth():
    # time_limit=0 makes every search past depth 1 time out mid-move; the board
    # must be left intact and the depth-1 ranking returned.
    cands = game.candidates(START, k=3, depth=6, time_limit=0.0)
    assert len(cands) == 3
    assert cands == game.candidates(START, k=3, depth=1, time_limit=5.0)


def test_evaluate_is_symmetric():
    state = game.apply(START, {"uci": "e2e4"})
    assert game.evaluate(state, "white") == -game.evaluate(state, "black")


def test_summary_and_description():
    cand = game.candidates(SCHOLARS, k=1, depth=1, time_limit=5.0)[0]
    assert game.summarize(SCHOLARS, cand) == "Qxf7# (capture, check, forced mate)"
    assert game.describe_position(START) == "White to move, move 1, material +0 for white."


def test_to_dict_lists_legal_moves():
    data = game.to_dict(START)
    assert data["turn"] == "white" and len(data["legal_moves"]) == 20
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_chess.py -q`
Expected: `ModuleNotFoundError: No module named 'src.games'`.

- [ ] **Step 3: Write the implementation**

```bash
touch apps/mini_games/src/games/__init__.py
```

`apps/mini_games/src/games/base.py`

```python
"""The Game protocol every plugin implements, and the types it exchanges.

Moves are plain JSON objects (dict) so the API, the sessions and the Laya
picker never need to know a game's move type. States are immutable values
owned by the plugin; callers pass them back unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

Move = dict[str, Any]


class GameError(Exception):
    """Base for errors a caller can fix (bad move, bad option)."""


class IllegalMove(GameError):
    """The move is not legal in this position."""


class InvalidOptions(GameError):
    """Unknown or out-of-range game option, or unknown game id."""


@dataclass(frozen=True)
class Status:
    finished: bool
    winner: str | None = None  # a side name; None with finished=True is a draw
    reason: str = ""


@dataclass(frozen=True)
class Candidate:
    move: Move
    score: float  # higher is better for the side to move
    features: dict[str, Any] = field(default_factory=dict)


class Game(Protocol):
    id: str

    def option_schema(self) -> dict[str, Any]:
        """JSON-friendly description of the options new_state accepts."""

    def assign_sides(self, options: dict[str, Any]) -> tuple[str, str]:
        """(player side, bot side) for these options."""

    def new_state(self, options: dict[str, Any]) -> Any:
        """Start a game; raises InvalidOptions."""

    def side_to_move(self, state: Any) -> str | None:
        """The side that must move next; None when the game is over."""

    def legal_moves(self, state: Any) -> list[Move]: ...

    def apply(self, state: Any, move: Move) -> Any:
        """The state after the move; raises IllegalMove."""

    def status(self, state: Any) -> Status: ...

    def evaluate(self, state: Any, side: str) -> float:
        """Engine score of the position from `side`'s view; higher is better."""

    def candidates(self, state: Any, k: int, depth: int, time_limit: float) -> list[Candidate]:
        """Up to k best moves for the side to move, best first. Blocking CPU
        work: callers run it in a worker thread."""

    def summarize(self, state: Any, candidate: Candidate) -> str:
        """One short feature line for a candidate, for the Laya question."""

    def describe_position(self, state: Any) -> str:
        """A compact text summary of the position, for the Laya question."""

    def to_dict(self, state: Any) -> dict[str, Any]:
        """The JSON shape the API sends for this state."""
```

`apps/mini_games/src/games/chess_game.py`

```python
"""Chess plugin: python-chess rules plus a small alpha-beta engine.

State is a FEN string. A move is {"uci": "e2e4"}. Scores are in pawns from the
side to move's view; forced mates score +-MATE.
"""

from __future__ import annotations

import time
from typing import Any

import chess

from src.games.base import Candidate, IllegalMove, InvalidOptions, Move, Status

MATE = 10_000.0
_VALUES = {chess.PAWN: 1.0, chess.KNIGHT: 3.0, chess.BISHOP: 3.2, chess.ROOK: 5.0, chess.QUEEN: 9.0}
_CENTRE = (chess.D4, chess.E4, chess.D5, chess.E5)
_SIDES = ("white", "black")


class _Timeout(Exception):
    """The search ran out of time; the previous depth's result stands."""


def _static(board: chess.Board) -> float:
    """Material plus a small centre bonus, from the side to move's view."""
    me, them = board.turn, not board.turn
    score = 0.0
    for piece_type, value in _VALUES.items():
        score += value * (len(board.pieces(piece_type, me)) - len(board.pieces(piece_type, them)))
    for square in _CENTRE:
        piece = board.piece_at(square)
        if piece is not None and piece.piece_type in (chess.PAWN, chess.KNIGHT):
            score += 0.1 if piece.color == me else -0.1
    return score


def _ordered(board: chess.Board) -> list[chess.Move]:
    return sorted(board.legal_moves, key=lambda m: not board.is_capture(m))


def _negamax(board: chess.Board, depth: int, alpha: float, beta: float, ply: int, deadline: float | None) -> float:
    if board.is_checkmate():
        return -MATE + ply
    if board.is_stalemate() or board.is_insufficient_material():
        return 0.0
    if depth == 0:
        return _static(board)
    if deadline is not None and time.monotonic() > deadline:
        raise _Timeout
    best = -MATE * 2
    for move in _ordered(board):
        board.push(move)
        try:
            score = -_negamax(board, depth - 1, -beta, -alpha, ply + 1, deadline)
        finally:
            board.pop()  # also on _Timeout, so the caller's board is never left mid-search
        best = max(best, score)
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    return best


def _score_root(board: chess.Board, depth: int, deadline: float | None) -> list[tuple[chess.Move, float]]:
    scored = []
    for move in _ordered(board):
        board.push(move)
        try:
            score = -_negamax(board, depth - 1, -MATE * 2, MATE * 2, 1, deadline)
        finally:
            board.pop()
        scored.append((move, score))
    return scored


class ChessGame:
    id = "chess"

    def option_schema(self) -> dict[str, Any]:
        return {"player_side": {"type": "string", "enum": list(_SIDES), "default": "white"}}

    def _player_side(self, options: dict[str, Any]) -> str:
        unknown = set(options) - {"player_side"}
        if unknown:
            raise InvalidOptions(f"unknown chess option(s): {', '.join(sorted(unknown))}")
        side = options.get("player_side", "white")
        if side not in _SIDES:
            raise InvalidOptions("player_side must be 'white' or 'black'")
        return side

    def assign_sides(self, options: dict[str, Any]) -> tuple[str, str]:
        player = self._player_side(options)
        return player, "black" if player == "white" else "white"

    def new_state(self, options: dict[str, Any]) -> str:
        self._player_side(options)
        return chess.STARTING_FEN

    def side_to_move(self, state: str) -> str | None:
        board = chess.Board(state)
        if board.is_game_over(claim_draw=True):
            return None
        return "white" if board.turn else "black"

    def legal_moves(self, state: str) -> list[Move]:
        return [{"uci": m.uci()} for m in chess.Board(state).legal_moves]

    def apply(self, state: str, move: Move) -> str:
        board = chess.Board(state)
        uci = move.get("uci") if isinstance(move, dict) else None
        try:
            parsed = chess.Move.from_uci(uci) if isinstance(uci, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed not in board.legal_moves:
            raise IllegalMove(f"illegal chess move: {uci!r}")
        board.push(parsed)
        return board.fen()

    def status(self, state: str) -> Status:
        outcome = chess.Board(state).outcome(claim_draw=True)
        if outcome is None:
            return Status(False)
        winner = None if outcome.winner is None else ("white" if outcome.winner else "black")
        return Status(True, winner, outcome.termination.name.lower())

    def evaluate(self, state: str, side: str) -> float:
        board = chess.Board(state)
        score = _static(board)
        return score if board.turn == (side == "white") else -score

    def candidates(self, state: str, k: int, depth: int, time_limit: float) -> list[Candidate]:
        board = chess.Board(state)
        if not any(board.legal_moves):
            return []
        deadline = time.monotonic() + time_limit
        scored: list[tuple[chess.Move, float]] = []
        for current in range(1, max(1, depth) + 1):
            try:
                scored = _score_root(board, current, None if current == 1 else deadline)
            except _Timeout:
                break
        scored.sort(key=lambda pair: -pair[1])
        return [self._candidate(board, move, score) for move, score in scored[:k]]

    @staticmethod
    def _candidate(board: chess.Board, move: chess.Move, score: float) -> Candidate:
        san = board.san(move)
        features = {
            "san": san,
            "capture": board.is_capture(move),
            "check": board.gives_check(move),
            "castle": board.is_castling(move),
            "promotion": move.promotion is not None,
        }
        return Candidate({"uci": move.uci()}, score, features)

    def summarize(self, state: str, candidate: Candidate) -> str:
        f = candidate.features
        tags = [name for name in ("capture", "check", "castle", "promotion") if f.get(name)] or ["quiet"]
        rating = "forced mate" if abs(candidate.score) > MATE / 2 else f"eval {candidate.score:+.1f}"
        return f"{f['san']} ({', '.join(tags)}, {rating})"

    def describe_position(self, state: str) -> str:
        board = chess.Board(state)
        material = sum(
            value * (len(board.pieces(t, chess.WHITE)) - len(board.pieces(t, chess.BLACK)))
            for t, value in _VALUES.items()
        )
        side = "White" if board.turn else "Black"
        check = ", in check" if board.is_check() else ""
        return f"{side} to move, move {board.fullmove_number}, material {material:+.0f} for white{check}."

    def to_dict(self, state: str) -> dict[str, Any]:
        board = chess.Board(state)
        return {
            "fen": state,
            "turn": "white" if board.turn else "black",
            "in_check": board.is_check(),
            "legal_moves": [m.uci() for m in board.legal_moves],
        }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_chess.py -q`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/games apps/mini_games/tests/test_chess.py
git commit -m "feat(mini_games): game protocol and chess plugin"
```

---

### Task 4: Tetris board functions

**Files:**
- Create: `apps/mini_games/src/games/tetris_board.py`
- Test: `apps/mini_games/tests/test_tetris_board.py`

**Interfaces:**
- Produces (`src.games.tetris_board`): constants `ROWS = 20`, `COLS = 10`, `PIECES`, `EMPTY_BOARD`, `ROTATIONS` (piece -> tuple of rotations, each a tuple of `(row, col)` cells normalised to the origin); `Board = tuple[tuple[int, ...], ...]`; `piece_at(seed, index) -> str` (stateless seeded 7-bag); `placements(piece) -> list[(rotation, column)]`; `landing_row(board, cells, column) -> int | None` (None = cannot spawn); `lock(board, cells, row, column) -> (Board, lines_cleared)`; `column_heights`, `count_holes`, `bumpiness`, `placement_score(board, lines) -> float`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_tetris_board.py`

```python
import pytest

from src.games.tetris_board import (
    COLS,
    EMPTY_BOARD,
    PIECES,
    ROTATIONS,
    ROWS,
    bumpiness,
    column_heights,
    count_holes,
    landing_row,
    lock,
    piece_at,
    placement_score,
    placements,
)


def _board(rows: dict[int, str]):
    """Board from {row index: 10-char string of '#' and '.'}."""
    grid = [[0] * COLS for _ in range(ROWS)]
    for index, text in rows.items():
        grid[index] = [1 if ch == "#" else 0 for ch in text]
    return tuple(tuple(r) for r in grid)


@pytest.mark.parametrize("piece,count", [("I", 2), ("O", 1), ("T", 4), ("S", 2), ("Z", 2), ("J", 4), ("L", 4)])
def test_distinct_rotation_counts(piece, count):
    assert len(ROTATIONS[piece]) == count


def test_every_rotation_has_four_cells_at_the_origin():
    for rotations in ROTATIONS.values():
        for cells in rotations:
            assert len(cells) == 4
            assert min(r for r, _ in cells) == 0 and min(c for _, c in cells) == 0


def test_piece_sequence_is_seeded_and_a_seven_bag():
    first = [piece_at(7, i) for i in range(14)]
    assert first == [piece_at(7, i) for i in range(14)]
    assert sorted(first[:7]) == sorted(PIECES) and sorted(first[7:]) == sorted(PIECES)
    assert first != [piece_at(8, i) for i in range(14)]


def test_placement_counts():
    assert len(placements("O")) == 9
    assert len(placements("I")) == 7 + 10  # flat I fits 7 columns, upright I fits 10


def test_o_drops_to_the_floor():
    cells = ROTATIONS["O"][0]
    assert landing_row(EMPTY_BOARD, cells, 0) == ROWS - 2


def test_piece_rests_on_the_stack():
    board = _board({ROWS - 1: "#" * COLS})
    assert landing_row(board, ROTATIONS["O"][0], 3) == ROWS - 3


def test_full_stack_cannot_spawn():
    board = _board({0: "#" * COLS})
    assert landing_row(board, ROTATIONS["O"][0], 0) is None


def test_lock_clears_full_lines():
    board = _board({ROWS - 1: "########.."})
    after, cleared = lock(board, ROTATIONS["O"][0], ROWS - 2, 8)
    assert cleared == 1
    assert sum(map(sum, after)) == 2  # the O's upper half is left
    assert all(not any(r) for r in after[: ROWS - 2])


def test_heights_holes_and_bumpiness():
    board = _board({ROWS - 3: "#.........", ROWS - 2: "..........", ROWS - 1: "#........."})
    assert column_heights(board)[:2] == [3, 0]
    assert count_holes(board) == 1
    assert bumpiness([3, 0, 0]) == 3


def test_flat_placement_scores_higher_than_a_tall_one():
    flat, _ = lock(EMPTY_BOARD, ROTATIONS["I"][0], ROWS - 1, 0)
    tall, _ = lock(EMPTY_BOARD, ROTATIONS["I"][1], ROWS - 4, 0)
    assert placement_score(flat, 0) > placement_score(tall, 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_tetris_board.py -q`
Expected: `ModuleNotFoundError: No module named 'src.games.tetris_board'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/games/tetris_board.py`

```python
"""Tetris pieces, the 10 by 20 board and placement scoring. Pure functions."""

from __future__ import annotations

import random

ROWS, COLS = 20, 10
Cells = tuple[tuple[int, int], ...]
Board = tuple[tuple[int, ...], ...]

_SHAPES: dict[str, Cells] = {
    "I": ((0, 0), (0, 1), (0, 2), (0, 3)),
    "O": ((0, 0), (0, 1), (1, 0), (1, 1)),
    "T": ((0, 1), (1, 0), (1, 1), (1, 2)),
    "S": ((0, 1), (0, 2), (1, 0), (1, 1)),
    "Z": ((0, 0), (0, 1), (1, 1), (1, 2)),
    "J": ((0, 0), (1, 0), (1, 1), (1, 2)),
    "L": ((0, 2), (1, 0), (1, 1), (1, 2)),
}
PIECES = tuple(_SHAPES)
EMPTY_BOARD: Board = tuple(tuple(0 for _ in range(COLS)) for _ in range(ROWS))


def _normalise(cells) -> Cells:
    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    return tuple(sorted((r - min_r, c - min_c) for r, c in cells))


def _rotations(piece: str) -> tuple[Cells, ...]:
    """The distinct rotations of a piece, each normalised to the top-left."""
    seen: list[Cells] = []
    cells = _normalise(_SHAPES[piece])
    while cells not in seen:
        seen.append(cells)
        cells = _normalise([(c, -r) for r, c in cells])
    return tuple(seen)


ROTATIONS: dict[str, tuple[Cells, ...]] = {piece: _rotations(piece) for piece in PIECES}


def piece_at(seed: int, index: int) -> str:
    """The index-th piece of the seeded 7-bag sequence; stateless."""
    bag = list(PIECES)
    random.Random(f"{seed}:{index // 7}").shuffle(bag)
    return bag[index % 7]


def placements(piece: str) -> list[tuple[int, int]]:
    """Every (rotation, leftmost column) that fits inside the board width."""
    result = []
    for rotation, cells in enumerate(ROTATIONS[piece]):
        width = max(c for _, c in cells) + 1
        result.extend((rotation, column) for column in range(COLS - width + 1))
    return result


def _collides(board: Board, cells: Cells, row: int, column: int) -> bool:
    return any(r + row >= ROWS or board[r + row][c + column] for r, c in cells)


def landing_row(board: Board, cells: Cells, column: int) -> int | None:
    """Row the piece's top edge rests at after a straight drop, or None when
    it cannot even spawn (the stack reached the top)."""
    if _collides(board, cells, 0, column):
        return None
    row = 0
    while not _collides(board, cells, row + 1, column):
        row += 1
    return row


def lock(board: Board, cells: Cells, row: int, column: int) -> tuple[Board, int]:
    """Place the piece, clear full lines; returns the new board and the count."""
    grid = [list(r) for r in board]
    for r, c in cells:
        grid[r + row][c + column] = 1
    kept = [r for r in grid if not all(r)]
    cleared = ROWS - len(kept)
    rows = [[0] * COLS for _ in range(cleared)] + kept
    return tuple(tuple(r) for r in rows), cleared


def column_heights(board: Board) -> list[int]:
    heights = []
    for c in range(COLS):
        top = next((r for r in range(ROWS) if board[r][c]), ROWS)
        heights.append(ROWS - top)
    return heights


def count_holes(board: Board) -> int:
    holes = 0
    for c in range(COLS):
        seen = False
        for r in range(ROWS):
            if board[r][c]:
                seen = True
            elif seen:
                holes += 1
    return holes


def bumpiness(heights: list[int]) -> int:
    return sum(abs(a - b) for a, b in zip(heights, heights[1:]))


def placement_score(board: Board, lines: int) -> float:
    """Standard stacking heuristic: reward cleared lines, punish height,
    holes and an uneven surface. Higher is better."""
    heights = column_heights(board)
    return -0.51 * sum(heights) + 0.76 * lines - 0.36 * count_holes(board) - 0.18 * bumpiness(heights)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_tetris_board.py -q`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/games/tetris_board.py apps/mini_games/tests/test_tetris_board.py
git commit -m "feat(mini_games): tetris board, pieces and placement scoring"
```

---

### Task 5: Tetris plugin and the game registry

**Files:**
- Create: `apps/mini_games/src/games/tetris_game.py`, `apps/mini_games/src/games/registry.py`
- Test: `apps/mini_games/tests/test_tetris_game.py`, `apps/mini_games/tests/test_registry.py`

**Interfaces:**
- Consumes: everything from `src.games.base` and `src.games.tetris_board` (Tasks 3 and 4), `ChessGame`.
- Produces: `src.games.tetris_game.TetrisGame`, `TetrisState` (frozen dataclass: `seed, piece_limit, boards, scores, placed, topped_out`, each a 2-tuple indexed player=0, bot=1), `SIDES = ("player", "bot")`; `src.games.registry.build_games() -> dict[str, Game]`, `get_game(games, game_id) -> Game` (raises `InvalidOptions` listing valid ids).
- Tetris move: `{"rotation": int, "column": int}`. Turn order: `side_to_move` is the player while both sides have placed the same number of pieces, otherwise the bot. A placement that cannot spawn tops that side out (legal, ends the game).

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_tetris_game.py`

```python
import pytest

from src.games.base import IllegalMove, InvalidOptions
from src.games.tetris_board import EMPTY_BOARD, piece_at
from src.games.tetris_game import TetrisGame, TetrisState

game = TetrisGame()


def _state(**changes) -> TetrisState:
    base = game.new_state({"seed": 1, "piece_limit": 5})
    return TetrisState(**{**base.__dict__, **changes})


def test_new_state_defaults_and_sides():
    state = game.new_state({"seed": 3})
    assert state.piece_limit == 40 and state.scores == (0, 0)
    assert game.assign_sides({}) == ("player", "bot")


@pytest.mark.parametrize("options", [{"piece_limit": 4}, {"piece_limit": 201}, {"piece_limit": True}, {"seed": "x"}, {"x": 1}])
def test_bad_options_are_rejected(options):
    with pytest.raises(InvalidOptions):
        game.new_state(options)


def test_same_seed_gives_same_pieces():
    a = game.to_dict(game.new_state({"seed": 9}))
    b = game.to_dict(game.new_state({"seed": 9}))
    assert a == b and a["current_piece"] == piece_at(9, 0)


def test_turns_alternate_per_piece():
    state = game.new_state({"seed": 1, "piece_limit": 5})
    assert game.side_to_move(state) == "player"
    state = game.apply(state, game.legal_moves(state)[0])
    assert game.side_to_move(state) == "bot"
    state = game.apply(state, game.legal_moves(state)[0])
    assert game.side_to_move(state) == "player"
    assert state.placed == (1, 1)


@pytest.mark.parametrize("move", [{"rotation": 9, "column": 0}, {"rotation": 0, "column": 99}, {"rotation": "a", "column": 0}, {}])
def test_illegal_placements_are_rejected(move):
    with pytest.raises(IllegalMove):
        game.apply(game.new_state({"seed": 1}), move)


def test_a_placement_changes_only_the_movers_board():
    state = game.new_state({"seed": 1})
    after = game.apply(state, game.legal_moves(state)[0])
    assert after.boards[0] != EMPTY_BOARD and after.boards[1] == EMPTY_BOARD


def test_line_clear_scores_points():
    # Bottom row full except the two right columns; an O piece (seed 1 may not
    # start with O, so force the board and use whichever O placement exists).
    seed = next(s for s in range(200) if piece_at(s, 0) == "O")
    board = list(map(list, EMPTY_BOARD))
    board[19] = [1] * 8 + [0, 0]
    board[18] = [1] * 8 + [0, 0]
    state = TetrisState(seed, 5, (tuple(map(tuple, board)), EMPTY_BOARD), (0, 0), (0, 0), (False, False))
    after = game.apply(state, {"rotation": 0, "column": 8})
    assert after.scores[0] == 300  # two lines


def test_topping_out_ends_the_game_and_loses():
    full = tuple(tuple(1 for _ in range(10)) for _ in range(20))
    state = _state(boards=(full, EMPTY_BOARD))
    after = game.apply(state, game.legal_moves(state)[0])
    status = game.status(after)
    assert status.finished and status.winner == "bot" and "player topped out" in status.reason
    assert game.side_to_move(after) is None and game.legal_moves(after) == []


def test_game_ends_at_the_piece_limit_with_a_draw_on_equal_scores():
    state = game.new_state({"seed": 1, "piece_limit": 5})
    for _ in range(10):
        state = game.apply(state, game.candidates(state, 1, 1, 1.0)[0].move)
    status = game.status(state)
    assert status.finished and not any(state.topped_out)
    assert status.winner in (None, "player", "bot")


def test_moving_after_the_game_is_over_is_illegal():
    state = _state(placed=(5, 5))
    with pytest.raises(IllegalMove):
        game.apply(state, {"rotation": 0, "column": 0})


def test_candidates_sorted_limited_and_deterministic():
    state = game.new_state({"seed": 2})
    cands = game.candidates(state, 3, 1, 1.0)
    assert len(cands) == 3
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)
    assert cands == game.candidates(state, 3, 1, 1.0)


def test_candidates_when_every_placement_tops_out():
    full = tuple(tuple(1 for _ in range(10)) for _ in range(20))
    cands = game.candidates(_state(boards=(full, EMPTY_BOARD)), 3, 1, 1.0)
    assert len(cands) == 1 and cands[0].features == {"top_out": True}


def test_candidate_prefers_clearing_a_line():
    seed = next(s for s in range(200) if piece_at(s, 0) == "I")
    board = list(map(list, EMPTY_BOARD))
    board[19] = [0] * 4 + [1] * 6
    state = TetrisState(seed, 5, (tuple(map(tuple, board)), EMPTY_BOARD), (0, 0), (0, 0), (False, False))
    best = game.candidates(state, 1, 1, 1.0)[0]
    assert best.move == {"rotation": 0, "column": 0} and best.features["lines"] == 1


def test_summary_and_description():
    state = game.new_state({"seed": 2})
    cand = game.candidates(state, 1, 1, 1.0)[0]
    assert game.summarize(state, cand).startswith("rotation ")
    assert game.describe_position(state).startswith(f"Piece {piece_at(2, 0)}. Column heights 0 0 0")


def test_to_dict_shape():
    data = game.to_dict(game.new_state({"seed": 2, "piece_limit": 5}))
    assert data["turn"] == "player" and len(data["boards"]["player"]) == 20
    assert len(data["next_pieces"]) == 3 and data["piece_limit"] == 5


def test_evaluate_is_the_score_difference():
    state = _state(scores=(300, 100))
    assert game.evaluate(state, "player") == 200.0 and game.evaluate(state, "bot") == -200.0
```

`apps/mini_games/tests/test_registry.py`

```python
import pytest

from src.games.base import InvalidOptions
from src.games.registry import build_games, get_game


def test_registry_has_both_games():
    assert sorted(build_games()) == ["chess", "tetris"]


def test_get_game_returns_the_plugin():
    games = build_games()
    assert get_game(games, "chess").id == "chess"


@pytest.mark.parametrize("bad", ["go", None, 3])
def test_unknown_game_lists_the_valid_ones(bad):
    with pytest.raises(InvalidOptions, match="chess, tetris"):
        get_game(build_games(), bad)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_tetris_game.py tests/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'src.games.tetris_game'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/games/tetris_game.py`

```python
"""Tetris versus plugin: player and bot stack the same seeded pieces on their
own boards, in lockstep (player places piece n, then the bot places piece n).

A move is a placement {"rotation": int, "column": int}; column is the
leftmost column of the rotated piece. The browser owns gravity and sends the
final placement; this plugin only validates and simulates the drop.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Any

from src.games.base import Candidate, IllegalMove, InvalidOptions, Move, Status
from src.games.tetris_board import (
    COLS,
    EMPTY_BOARD,
    ROTATIONS,
    Board,
    bumpiness,
    column_heights,
    count_holes,
    landing_row,
    lock,
    piece_at,
    placement_score,
    placements,
)

SIDES = ("player", "bot")
LINE_POINTS = (0, 100, 300, 500, 800)
DEFAULT_PIECE_LIMIT = 40
MIN_PIECE_LIMIT, MAX_PIECE_LIMIT = 5, 200
_TOP_OUT_SCORE = -1e9


@dataclass(frozen=True)
class TetrisState:
    seed: int
    piece_limit: int
    boards: tuple[Board, Board]
    scores: tuple[int, int]
    placed: tuple[int, int]
    topped_out: tuple[bool, bool]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class TetrisGame:
    id = "tetris"

    def option_schema(self) -> dict[str, Any]:
        return {
            "seed": {"type": "integer", "default": "random"},
            "piece_limit": {
                "type": "integer", "minimum": MIN_PIECE_LIMIT, "maximum": MAX_PIECE_LIMIT,
                "default": DEFAULT_PIECE_LIMIT,
            },
        }

    def assign_sides(self, options: dict[str, Any]) -> tuple[str, str]:
        return SIDES

    def new_state(self, options: dict[str, Any]) -> TetrisState:
        unknown = set(options) - {"seed", "piece_limit"}
        if unknown:
            raise InvalidOptions(f"unknown tetris option(s): {', '.join(sorted(unknown))}")
        seed = options.get("seed", random.randrange(2**31))
        limit = options.get("piece_limit", DEFAULT_PIECE_LIMIT)
        if not _is_int(seed):
            raise InvalidOptions("seed must be an integer")
        if not _is_int(limit) or not MIN_PIECE_LIMIT <= limit <= MAX_PIECE_LIMIT:
            raise InvalidOptions(f"piece_limit must be an integer from {MIN_PIECE_LIMIT} to {MAX_PIECE_LIMIT}")
        return TetrisState(seed, limit, (EMPTY_BOARD, EMPTY_BOARD), (0, 0), (0, 0), (False, False))

    # -- turn and piece bookkeeping ------------------------------------------------

    def _finished(self, state: TetrisState) -> bool:
        return any(state.topped_out) or all(n >= state.piece_limit for n in state.placed)

    def side_to_move(self, state: TetrisState) -> str | None:
        if self._finished(state):
            return None
        return SIDES[0 if state.placed[0] == state.placed[1] else 1]

    def _piece(self, state: TetrisState, index: int) -> str:
        return piece_at(state.seed, state.placed[index])

    # -- rules ---------------------------------------------------------------------

    def legal_moves(self, state: TetrisState) -> list[Move]:
        side = self.side_to_move(state)
        if side is None:
            return []
        piece = self._piece(state, SIDES.index(side))
        return [{"rotation": r, "column": c} for r, c in placements(piece)]

    def apply(self, state: TetrisState, move: Move) -> TetrisState:
        side = self.side_to_move(state)
        if side is None:
            raise IllegalMove("the game is over")
        index = SIDES.index(side)
        piece = self._piece(state, index)
        rotation = move.get("rotation") if isinstance(move, dict) else None
        column = move.get("column") if isinstance(move, dict) else None
        if (rotation, column) not in placements(piece) or not (_is_int(rotation) and _is_int(column)):
            raise IllegalMove(f"{piece} cannot be placed at rotation {rotation!r}, column {column!r}")
        cells = ROTATIONS[piece][rotation]
        row = landing_row(state.boards[index], cells, column)
        placed = _set(state.placed, index, state.placed[index] + 1)
        if row is None:
            return replace(state, placed=placed, topped_out=_set(state.topped_out, index, True))
        board, cleared = lock(state.boards[index], cells, row, column)
        return replace(
            state,
            boards=_set(state.boards, index, board),
            scores=_set(state.scores, index, state.scores[index] + LINE_POINTS[cleared]),
            placed=placed,
        )

    def status(self, state: TetrisState) -> Status:
        if not self._finished(state):
            return Status(False)
        if state.topped_out[0] != state.topped_out[1]:
            loser = SIDES[0 if state.topped_out[0] else 1]
            return Status(True, SIDES[1 - SIDES.index(loser)], f"{loser} topped out")
        if state.scores[0] == state.scores[1]:
            return Status(True, None, "equal scores at the piece limit")
        return Status(True, SIDES[0 if state.scores[0] > state.scores[1] else 1], "higher score at the piece limit")

    def evaluate(self, state: TetrisState, side: str) -> float:
        me = SIDES.index(side)
        return float(state.scores[me] - state.scores[1 - me])

    # -- engine --------------------------------------------------------------------

    def candidates(self, state: TetrisState, k: int, depth: int, time_limit: float) -> list[Candidate]:
        side = self.side_to_move(state)
        if side is None:
            return []
        index = SIDES.index(side)
        piece = self._piece(state, index)
        board = state.boards[index]
        scored = []
        for rotation, column in placements(piece):
            cells = ROTATIONS[piece][rotation]
            row = landing_row(board, cells, column)
            if row is None:
                continue
            after, cleared = lock(board, cells, row, column)
            heights = column_heights(after)
            features = {
                "rotation": rotation, "column": column, "lines": cleared,
                "holes": count_holes(after), "max_height": max(heights), "bumpiness": bumpiness(heights),
            }
            scored.append(Candidate({"rotation": rotation, "column": column}, placement_score(after, cleared), features))
        if not scored:  # every placement tops out; the game is lost whatever is sent
            rotation, column = placements(piece)[0]
            return [Candidate({"rotation": rotation, "column": column}, _TOP_OUT_SCORE, {"top_out": True})]
        scored.sort(key=lambda c: (-c.score, c.move["rotation"], c.move["column"]))
        return scored[:k]

    def summarize(self, state: TetrisState, candidate: Candidate) -> str:
        f = candidate.features
        if f.get("top_out"):
            return "any placement tops out"
        lines = f"clears {f['lines']} line{'s' if f['lines'] != 1 else ''}"
        holes = f"{f['holes']} hole{'s' if f['holes'] != 1 else ''}"
        return f"rotation {f['rotation']} at column {f['column']}: {lines}, {holes}, max height {f['max_height']}"

    def describe_position(self, state: TetrisState) -> str:
        side = self.side_to_move(state)
        if side is None:
            return "Game over."
        index = SIDES.index(side)
        board = state.boards[index]
        heights = " ".join(str(h) for h in column_heights(board))
        return (
            f"Piece {self._piece(state, index)}. Column heights {heights}. "
            f"Holes {count_holes(board)}. Score {state.scores[index]} to {state.scores[1 - index]}."
        )

    def to_dict(self, state: TetrisState) -> dict[str, Any]:
        side = self.side_to_move(state)
        upcoming = []
        if side is not None:
            start = state.placed[SIDES.index(side)]
            upcoming = [piece_at(state.seed, start + i) for i in range(4) if start + i < state.piece_limit]
        return {
            "seed": state.seed,
            "piece_limit": state.piece_limit,
            "columns": COLS,
            "boards": {s: [list(r) for r in state.boards[i]] for i, s in enumerate(SIDES)},
            "scores": dict(zip(SIDES, state.scores)),
            "placed": dict(zip(SIDES, state.placed)),
            "topped_out": dict(zip(SIDES, state.topped_out)),
            "turn": side,
            "current_piece": upcoming[0] if upcoming else None,
            "next_pieces": upcoming[1:],
        }


def _set(pair: tuple, index: int, value: Any) -> tuple:
    return tuple(value if i == index else v for i, v in enumerate(pair))
```

`apps/mini_games/src/games/registry.py`

```python
"""The games the backend can host. A new game is one plugin file plus a line here."""

from __future__ import annotations

from src.games.base import Game, InvalidOptions
from src.games.chess_game import ChessGame
from src.games.tetris_game import TetrisGame


def build_games() -> dict[str, Game]:
    return {game.id: game for game in (ChessGame(), TetrisGame())}


def get_game(games: dict[str, Game], game_id: object) -> Game:
    if not isinstance(game_id, str) or game_id not in games:
        raise InvalidOptions(f"unknown game {game_id!r}; valid games: {', '.join(sorted(games))}")
    return games[game_id]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_tetris_game.py tests/test_registry.py -q`
Expected: 28 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/games apps/mini_games/tests/test_tetris_game.py apps/mini_games/tests/test_registry.py
git commit -m "feat(mini_games): tetris versus plugin and game registry"
```

---

### Task 6: Laya client

**Files:**
- Create: `apps/mini_games/src/opponent/__init__.py` (empty), `apps/mini_games/src/opponent/laya_client.py`
- Create: `apps/mini_games/tests/fake_laya.py`
- Test: `apps/mini_games/tests/test_laya_client.py`

**Interfaces:**
- Produces (`src.opponent.laya_client`): `LayaClient(engine=None, timeout=5.0)` with `is_available() -> bool`, `prepare()`, `async choose(text, instructions, options: dict[str, str], min_confidence=0.7) -> LayaChoice`; `LayaChoice(key, confidence, uncertain)`; `LayaError`, `LayaUnavailable(LayaError)`; constants `DEFAULT_MODEL`, `CONTEXT_WINDOW = 512`, `MAX_TEXT_CHARS = 4000`, `MIN_OPTIONS = 2`, `MAX_OPTIONS = 10`.
- Produces (`tests/fake_laya.py`): `FakeEngine(pick=None, confidence=0.9, delay=0.0, usage=None)` with `.calls`, mimicking `laya.load(...).predict(text, questions, max_len)`.
- The engine contract (copied from `ai_agent/src/llm/laya_provider.py`): `predict(text, questions, max_len=512)` returns `{"answers": {qid: {"choice", "probabilities", "answer_confidence"}}, "usage": {...}}`; `usage.truncated` or `usage.state_tokens_dropped` means the input was not fully read.

- [ ] **Step 1: Write the fake engine and the failing tests**

`apps/mini_games/tests/fake_laya.py`

```python
"""A stand-in for the real Laya engine: tests inject it into LayaClient."""

from __future__ import annotations

import time
from typing import Any


class FakeEngine:
    """Answers every choice question with `pick` (default: the first option)."""

    def __init__(self, pick: str | None = None, confidence: float = 0.9, delay: float = 0.0, usage: dict | None = None) -> None:
        self.pick, self.confidence, self.delay = pick, confidence, delay
        self.usage = usage if usage is not None else {"input_tokens": 10}
        self.calls: list[tuple[str, dict]] = []

    def predict(self, text: str, questions: dict[str, Any], max_len: int = 512) -> dict[str, Any]:
        self.calls.append((text, questions))
        if self.delay:
            time.sleep(self.delay)
        answers = {}
        for qid, spec in questions.items():
            keys = list(spec["criteria"])
            choice = self.pick if self.pick in keys else keys[0]
            probabilities = {key: (self.confidence if key == choice else (1 - self.confidence) / (len(keys) - 1)) for key in keys}
            answers[qid] = {"choice": choice, "probabilities": probabilities, "answer_confidence": self.confidence}
        return {"answers": answers, "usage": self.usage}
```

`apps/mini_games/tests/test_laya_client.py`

```python
import asyncio

import pytest

from src.opponent.laya_client import LayaChoice, LayaClient, LayaError
from tests.fake_laya import FakeEngine

OPTIONS = {"a": "first move", "b": "second move", "c": "third move"}


def ask(client, **kwargs):
    args = {"text": "Some position.", "instructions": "Which is best?", "options": OPTIONS, **kwargs}
    return asyncio.run(client.choose(**args))


def test_returns_the_chosen_key_and_confidence():
    result = ask(LayaClient(FakeEngine(pick="b", confidence=0.9)))
    assert result == LayaChoice("b", 0.9, False)


def test_low_confidence_is_flagged_uncertain():
    assert ask(LayaClient(FakeEngine(confidence=0.5))).uncertain is True


def test_custom_min_confidence():
    assert ask(LayaClient(FakeEngine(confidence=0.8)), min_confidence=0.9).uncertain is True


def test_question_sent_to_the_engine():
    engine = FakeEngine()
    ask(LayaClient(engine))
    text, questions = engine.calls[0]
    assert text == "Some position."
    assert questions == {"move": {"type": "choice", "instructions": "Which is best?", "criteria": OPTIONS}}


@pytest.mark.parametrize("options", [{"a": "only"}, {chr(97 + i): "x" for i in range(11)}])
def test_option_count_is_checked(options):
    with pytest.raises(LayaError, match="options"):
        ask(LayaClient(FakeEngine()), options=options)


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_text_length_is_checked(text):
    with pytest.raises(LayaError, match="characters"):
        ask(LayaClient(FakeEngine()), text=text)


def test_truncated_input_is_rejected():
    with pytest.raises(LayaError, match="complete input"):
        ask(LayaClient(FakeEngine(usage={"truncated": True})))


class BadEngine:
    def __init__(self, result):
        self.result = result

    def predict(self, text, questions, max_len=512):
        return self.result


@pytest.mark.parametrize("result", [
    {},
    {"answers": {"move": {"choice": "z", "probabilities": {"a": 1, "b": 0, "c": 0}, "answer_confidence": 0.9}}},
    {"answers": {"move": {"choice": "a", "probabilities": {"a": 1}, "answer_confidence": 0.9}}},
    {"answers": {"move": {"choice": "a", "probabilities": {"a": 1, "b": 0, "c": 0}, "answer_confidence": 2}}},
    {"answers": {"move": {"choice": "a", "probabilities": {"a": 1, "b": 0, "c": 0}, "answer_confidence": float("nan")}}},
])
def test_invalid_engine_output_is_rejected(result):
    with pytest.raises(LayaError, match="invalid result"):
        ask(LayaClient(BadEngine(result)))


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
Expected: `ModuleNotFoundError: No module named 'src.opponent'`.

- [ ] **Step 3: Write the implementation**

```bash
mkdir -p apps/mini_games/src/opponent && touch apps/mini_games/src/opponent/__init__.py
```

`apps/mini_games/src/opponent/laya_client.py`

```python
"""Local Laya wrapper: ask one typed `choice` question about a short text.

A copy of the contract in ai_agent's laya_provider.py (projects never import
each other). Lazy model load under a lock, inference in a worker thread, and
a timeout so a slow model never stalls a game turn. Laya reads text only; it
generates no text and is never trusted without its own confidence flag.
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
MIN_OPTIONS, MAX_OPTIONS = 2, 10
QUESTION_ID = "move"


class LayaError(RuntimeError):
    """Laya failed, timed out, or returned something unusable."""


class LayaUnavailable(LayaError):
    """The optional `laya` package is not installed."""


@dataclass(frozen=True)
class LayaChoice:
    key: str
    confidence: float
    uncertain: bool


def _unit(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid probability")
    return float(value)


class LayaClient:
    """Engine injection (`engine=`) lets tests run without the real model."""

    def __init__(self, engine: Any = None, timeout: float = 5.0) -> None:
        self._engine = engine
        self._timeout = timeout
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

    def _choose_sync(self, text: str, instructions: str, options: dict[str, str], min_confidence: float) -> LayaChoice:
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            raise LayaError(f"Laya needs {MIN_OPTIONS} to {MAX_OPTIONS} options, got {len(options)}")
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise LayaError(f"text must be 1 to {MAX_TEXT_CHARS} characters")
        questions = {QUESTION_ID: {"type": "choice", "instructions": instructions, "criteria": options}}
        with self._lock:
            prediction = self._load().predict(text, questions, max_len=CONTEXT_WINDOW)
        try:
            usage = prediction.get("usage", {})
            if usage.get("truncated") or usage.get("state_tokens_dropped", 0):
                raise LayaError("Laya could not read the complete input")
            raw = prediction["answers"][QUESTION_ID]
            key = raw["choice"]
            probabilities = raw["probabilities"]
            if key not in options or set(probabilities) != set(options):
                raise ValueError("unknown choice")
            for value in probabilities.values():
                _unit(value)
            confidence = _unit(raw["answer_confidence"])
        except LayaError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise LayaError("Laya returned an invalid result") from error
        return LayaChoice(key, confidence, confidence < min_confidence)

    async def choose(self, text: str, instructions: str, options: dict[str, str], min_confidence: float = 0.7) -> LayaChoice:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._choose_sync, text, instructions, options, min_confidence), self._timeout
            )
        except asyncio.TimeoutError as error:
            raise LayaError(f"Laya timed out after {self._timeout}s") from error
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_laya_client.py -q`
Expected: 18 passed (one test skips itself if the real `laya` package is installed).

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/opponent apps/mini_games/tests/fake_laya.py apps/mini_games/tests/test_laya_client.py
git commit -m "feat(mini_games): local Laya client"
```

---

### Task 7: Pickers

**Files:**
- Create: `apps/mini_games/src/opponent/base.py`, `engine_picker.py`, `variety_picker.py`, `laya_picker.py`
- Test: `apps/mini_games/tests/test_pickers.py`

**Interfaces:**
- Consumes: `Game`, `Candidate`, `GameError` (Task 3); `Difficulty` (Task 1); `LayaClient`, `LayaError`, `MAX_TEXT_CHARS` (Task 6); `FakeEngine` (tests).
- Produces: `src.opponent.base.Pick(move, source)` where `source` is `"engine"`, `"variety"`, `"laya"` or `"fallback"`; `Picker` protocol with `name` and `async pick(game, state, difficulty) -> Pick`; `top_candidates(game, state, difficulty)` (runs `game.candidates` in a thread; raises `GameError` when empty). `EnginePicker()`, `VarietyPicker(rng=None)`, `LayaPicker(client, min_confidence=0.7)`; module constant `INSTRUCTIONS` in `laya_picker`.
- `LayaPicker` asks one `choice` question; option keys are `a`, `b`, ...; values are `game.summarize(...)` lines; `text` is `game.describe_position(...)`. Uncertain answers use the engine's best unless `difficulty.trust_uncertain`; any `LayaError` falls back to the engine's best.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_pickers.py`

```python
import asyncio
import random

import pytest

from src.config import Difficulty
from src.games.base import GameError
from src.games.chess_game import ChessGame
from src.games.tetris_game import TetrisGame
from src.opponent.engine_picker import EnginePicker
from src.opponent.laya_client import LayaClient
from src.opponent.laya_picker import LayaPicker
from src.opponent.variety_picker import VarietyPicker
from tests.fake_laya import FakeEngine

chess_game = ChessGame()
START = chess_game.new_state({})
EASY = Difficulty(depth=1, k=4, time_limit=2.0, trust_uncertain=False)
TRUSTING = Difficulty(depth=1, k=4, time_limit=2.0, trust_uncertain=True)


def pick(picker, game=chess_game, state=START, difficulty=EASY):
    return asyncio.run(picker.pick(game, state, difficulty))


def best_move(difficulty=EASY):
    return chess_game.candidates(START, difficulty.k, difficulty.depth, difficulty.time_limit)[0].move


def test_engine_picker_takes_the_best_candidate():
    result = pick(EnginePicker())
    assert (result.move, result.source) == (best_move(), "engine")


def test_variety_picker_stays_within_the_top_candidates():
    allowed = [c.move for c in chess_game.candidates(START, 4, 1, 2.0)]
    picker = VarietyPicker(random.Random(1))
    results = {tuple(pick(picker).move.items()) for _ in range(30)}
    assert results <= {tuple(m.items()) for m in allowed} and len(results) > 1


def test_variety_picker_is_reproducible_with_a_seed():
    a = [pick(VarietyPicker(random.Random(5))).move for _ in range(3)]
    b = [pick(VarietyPicker(random.Random(5))).move for _ in range(3)]
    assert a == b


def test_laya_picker_uses_the_option_laya_chooses():
    cands = chess_game.candidates(START, 4, 1, 2.0)
    picker = LayaPicker(LayaClient(FakeEngine(pick="c", confidence=0.9)))
    result = pick(picker)
    assert (result.move, result.source) == (cands[2].move, "laya")


def test_laya_question_lists_each_candidate_summary():
    engine = FakeEngine()
    pick(LayaPicker(LayaClient(engine)))
    text, questions = engine.calls[0]
    criteria = questions["move"]["criteria"]
    assert list(criteria) == ["a", "b", "c", "d"] and text.startswith("White to move")
    assert all("eval" in line for line in criteria.values())


def test_uncertain_laya_falls_back_to_the_engine():
    picker = LayaPicker(LayaClient(FakeEngine(pick="d", confidence=0.5)))
    result = pick(picker)
    assert (result.move, result.source) == (best_move(), "fallback")


def test_trusting_difficulty_accepts_an_uncertain_answer():
    cands = chess_game.candidates(START, 4, 1, 2.0)
    picker = LayaPicker(LayaClient(FakeEngine(pick="d", confidence=0.5)))
    result = pick(picker, difficulty=TRUSTING)
    assert (result.move, result.source) == (cands[3].move, "laya")


def test_laya_exception_falls_back_to_the_engine():
    result = pick(LayaPicker(LayaClient(FakeEngine(usage={"truncated": True}))))
    assert (result.move, result.source) == (best_move(), "fallback")


def test_laya_timeout_falls_back_to_the_engine():
    result = pick(LayaPicker(LayaClient(FakeEngine(delay=0.5), timeout=0.05)))
    assert result.source == "fallback"


def test_missing_laya_package_falls_back():
    client = LayaClient()
    if client.is_available():
        pytest.skip("laya is installed here")
    assert pick(LayaPicker(client)).source == "fallback"


def test_single_candidate_skips_laya():
    engine = FakeEngine()
    one = Difficulty(depth=1, k=1, time_limit=1.0, trust_uncertain=False)
    result = pick(LayaPicker(LayaClient(engine)), difficulty=one)
    assert result.source == "engine" and engine.calls == []


def test_pickers_work_for_tetris_too():
    tetris = TetrisGame()
    state = tetris.new_state({"seed": 4})
    result = pick(LayaPicker(LayaClient(FakeEngine(pick="b", confidence=0.95))), game=tetris, state=state)
    assert result.source == "laya" and set(result.move) == {"rotation", "column"}


def test_no_legal_move_is_a_game_error():
    tetris = TetrisGame()
    state = tetris.new_state({"seed": 4, "piece_limit": 5})
    state = type(state)(**{**state.__dict__, "placed": (5, 5)})
    with pytest.raises(GameError):
        pick(EnginePicker(), game=tetris, state=state)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_pickers.py -q`
Expected: `ModuleNotFoundError: No module named 'src.opponent.engine_picker'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/opponent/base.py`

```python
"""The Picker interface: choose the bot's move for a position."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from src.config import Difficulty
from src.games.base import Candidate, Game, GameError, Move


@dataclass(frozen=True)
class Pick:
    move: Move
    source: str  # "engine", "variety", "laya" or "fallback" (Laya was asked but not used)


class Picker(Protocol):
    name: str

    async def pick(self, game: Game, state: Any, difficulty: Difficulty) -> Pick: ...


async def top_candidates(game: Game, state: Any, difficulty: Difficulty) -> list[Candidate]:
    """The engine's best moves, searched off the event loop."""
    cands = await asyncio.to_thread(game.candidates, state, difficulty.k, difficulty.depth, difficulty.time_limit)
    if not cands:
        raise GameError("the bot has no legal move")
    return cands
```

`apps/mini_games/src/opponent/engine_picker.py`

```python
"""Always the engine's best move."""

from __future__ import annotations

from typing import Any

from src.config import Difficulty
from src.games.base import Game
from src.opponent.base import Pick, top_candidates


class EnginePicker:
    name = "engine"

    async def pick(self, game: Game, state: Any, difficulty: Difficulty) -> Pick:
        return Pick((await top_candidates(game, state, difficulty))[0].move, "engine")
```

`apps/mini_games/src/opponent/variety_picker.py`

```python
"""A weighted random pick among the engine's top candidates: human-like play
without any model. Better-ranked candidates are more likely."""

from __future__ import annotations

import random
from typing import Any

from src.config import Difficulty
from src.games.base import Game
from src.opponent.base import Pick, top_candidates


class VarietyPicker:
    name = "variety"

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    async def pick(self, game: Game, state: Any, difficulty: Difficulty) -> Pick:
        cands = await top_candidates(game, state, difficulty)
        weights = [1.0 / (rank + 1) for rank in range(len(cands))]
        return Pick(self._rng.choices(cands, weights=weights)[0].move, "variety")
```

`apps/mini_games/src/opponent/laya_picker.py`

```python
"""Laya chooses among the engine's top candidates.

The engine proposes and scores the moves; Laya reads a short text summary of
the position and one feature line per candidate and picks one. The engine's
best move is the fallback whenever Laya is uncertain (unless the difficulty
trusts uncertain answers), unavailable, slow or wrong. A Laya failure never
fails a turn.
"""

from __future__ import annotations

import logging
from typing import Any

from src.config import Difficulty
from src.games.base import Game
from src.opponent.base import Pick, top_candidates
from src.opponent.laya_client import MAX_TEXT_CHARS, LayaClient, LayaError

log = logging.getLogger(__name__)
INSTRUCTIONS = "Which candidate move is the strongest for the side to move?"


class LayaPicker:
    name = "laya"

    def __init__(self, client: LayaClient, min_confidence: float = 0.7) -> None:
        self._client = client
        self._min_confidence = min_confidence

    async def pick(self, game: Game, state: Any, difficulty: Difficulty) -> Pick:
        cands = await top_candidates(game, state, difficulty)
        if len(cands) < 2:
            return Pick(cands[0].move, "engine")
        keys = [chr(ord("a") + i) for i in range(len(cands))]
        options = {key: game.summarize(state, cand) for key, cand in zip(keys, cands)}
        try:
            choice = await self._client.choose(
                game.describe_position(state)[:MAX_TEXT_CHARS], INSTRUCTIONS, options, self._min_confidence
            )
        except LayaError as error:
            log.warning("Laya unavailable for this move, using the engine: %s", error)
            return Pick(cands[0].move, "fallback")
        if choice.uncertain and not difficulty.trust_uncertain:
            return Pick(cands[0].move, "fallback")
        return Pick(cands[keys.index(choice.key)].move, "laya")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_pickers.py -q`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/opponent apps/mini_games/tests/test_pickers.py
git commit -m "feat(mini_games): engine, variety and Laya pickers"
```

---

### Task 8: Sessions

**Files:**
- Create: `apps/mini_games/src/sessions.py`
- Test: `apps/mini_games/tests/test_sessions.py`

**Interfaces:**
- Consumes: `AppConfig` (Task 1), `Game`, `IllegalMove`, `InvalidOptions`, `GameError`, `Move` (Task 3), `get_game` (Task 5), `Picker` (Task 7).
- Produces: `SessionStore(games, pickers, config, clock=time.monotonic)` with `async create(owner, game_id, options, difficulty, picker) -> Session`, `async get(owner, sid)`, `async delete(owner, sid)`, `async player_move(owner, sid, move) -> Session`, `async bot_move(owner, sid) -> (Session, entry)`, `count(owner)`, `view(session) -> dict`; `Session` dataclass; errors `SessionError(GameError)`, `SessionNotFound`, `WrongTurn`, `GameOver`, `SessionLimit`.
- `view` shape: `{id, game, difficulty, picker, player_side, bot_side, turn: "player" | "bot" | None, status: {finished, winner: "player" | "bot" | None, reason}, state: <game.to_dict>, history: [{side, by, move, source?}]}`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_sessions.py`

```python
import asyncio

import pytest

from src.games.base import GameError, IllegalMove, InvalidOptions
from src.games.registry import build_games
from src.opponent.engine_picker import EnginePicker
from src.opponent.variety_picker import VarietyPicker
from src.sessions import GameOver, SessionLimit, SessionNotFound, SessionStore, WrongTurn


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(config, clock):
    pickers = {"engine": EnginePicker(), "variety": VarietyPicker()}
    return SessionStore(build_games(), pickers, config, clock)


def run(coro):
    return asyncio.run(coro)


def create(store, owner="ann", game="chess", options=None, difficulty="easy", picker="engine"):
    return run(store.create(owner, game, options or {}, difficulty, picker))


def test_create_uses_the_default_picker_and_assigns_sides(store):
    session = run(store.create("ann", "chess", {"player_side": "black"}, "easy", None))
    assert (session.player_side, session.bot_side, session.picker) == ("black", "white", "variety")
    view = store.view(session)
    assert view["turn"] == "bot" and view["status"]["finished"] is False


@pytest.mark.parametrize("args", [("go", {}, "easy", None), ("chess", {}, "godlike", None), ("chess", {}, "easy", "magic"), ("chess", {"x": 1}, "easy", None)])
def test_bad_create_arguments_are_rejected(store, args):
    with pytest.raises(InvalidOptions):
        run(store.create("ann", *args))


def test_player_then_bot_move(store):
    session = create(store)
    run(store.player_move("ann", session.id, {"uci": "e2e4"}))
    _, entry = run(store.bot_move("ann", session.id))
    assert entry["by"] == "bot" and entry["source"] == "engine"
    assert [h["by"] for h in session.history] == ["player", "bot"]
    assert store.view(session)["turn"] == "player"


def test_wrong_turn_is_rejected_and_state_is_unchanged(store):
    session = create(store)
    before = session.state
    with pytest.raises(WrongTurn):
        run(store.bot_move("ann", session.id))
    run(store.player_move("ann", session.id, {"uci": "e2e4"}))
    with pytest.raises(WrongTurn):
        run(store.player_move("ann", session.id, {"uci": "d2d4"}))
    assert session.state != before and len(session.history) == 1


def test_illegal_move_leaves_the_session_alone(store):
    session = create(store)
    with pytest.raises(IllegalMove):
        run(store.player_move("ann", session.id, {"uci": "e2e5"}))
    assert session.history == []


def test_finished_game_rejects_moves(store):
    session = create(store, game="tetris", options={"seed": 1, "piece_limit": 5})
    for _ in range(5):
        run(store.player_move("ann", session.id, {"rotation": 0, "column": 0}))
        run(store.bot_move("ann", session.id))
    assert store.view(session)["status"]["finished"] is True
    with pytest.raises(GameOver):
        run(store.player_move("ann", session.id, {"rotation": 0, "column": 0}))


def test_other_users_get_not_found(store):
    session = create(store)
    for call in (store.get, store.delete):
        with pytest.raises(SessionNotFound):
            run(call("bob", session.id))
    with pytest.raises(SessionNotFound):
        run(store.player_move("bob", session.id, {"uci": "e2e4"}))


def test_unknown_id_is_not_found(store):
    with pytest.raises(SessionNotFound):
        run(store.get("ann", "nope"))


def test_idle_sessions_expire(store, clock):
    session = create(store)
    clock.now += 3601
    with pytest.raises(SessionNotFound):
        run(store.get("ann", session.id))


def test_activity_keeps_a_session_alive(store, clock):
    session = create(store)
    clock.now += 3000
    run(store.get("ann", session.id))
    clock.now += 3000
    assert run(store.get("ann", session.id)) is session


def test_per_user_cap_and_delete_frees_a_slot(store):
    sessions = [create(store) for _ in range(5)]
    with pytest.raises(SessionLimit):
        create(store)
    create(store, owner="bob")  # other users are unaffected
    run(store.delete("ann", sessions[0].id))
    create(store)


def test_concurrent_moves_do_not_interleave(store):
    session = create(store)

    async def scenario():
        results = await asyncio.gather(
            store.player_move("ann", session.id, {"uci": "e2e4"}),
            store.player_move("ann", session.id, {"uci": "d2d4"}),
            return_exceptions=True,
        )
        return results

    results = run(scenario())
    assert sum(isinstance(r, WrongTurn) for r in results) == 1
    assert len(session.history) == 1


def test_a_picker_returning_an_illegal_move_is_reported(config, clock):
    class BadPicker:
        name = "bad"

        async def pick(self, game, state, difficulty):
            from src.opponent.base import Pick

            return Pick({"uci": "a1a8"}, "engine")

    store = SessionStore(build_games(), {"bad": BadPicker()}, config, clock)
    session = run(store.create("ann", "chess", {"player_side": "black"}, "easy", "bad"))
    with pytest.raises(GameError, match="illegal move"):
        run(store.bot_move("ann", session.id))


def test_view_names_the_winner_by_role(store):
    session = create(store, game="tetris", options={"seed": 1, "piece_limit": 5})
    session.state = type(session.state)(**{**session.state.__dict__, "topped_out": (True, False)})
    view = store.view(session)
    assert view["status"]["winner"] == "bot" and view["turn"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_sessions.py -q`
Expected: `ModuleNotFoundError: No module named 'src.sessions'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/sessions.py`

```python
"""In-memory game sessions, owned by the asking user.

Every mutation holds the session's own lock, so a player move and a bot move
can never interleave, and two clients (the web page and the chat assistant)
can never both move at once. Idle sessions expire after a TTL; a per-user cap
bounds memory. A restart ends all games (no persistence in v1).
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.config import AppConfig
from src.games.base import Game, GameError, IllegalMove, InvalidOptions, Move
from src.games.registry import get_game
from src.opponent.base import Picker


class SessionError(GameError):
    """Base for session-level failures."""


class SessionNotFound(SessionError):
    """Unknown id, expired, or owned by someone else."""


class WrongTurn(SessionError):
    """It is not that side's turn."""


class GameOver(SessionError):
    """The game has finished."""


class SessionLimit(SessionError):
    """The user already holds the maximum number of sessions."""


@dataclass
class Session:
    id: str
    owner: str
    game_id: str
    player_side: str
    bot_side: str
    state: Any
    picker: str
    difficulty: str
    created: float
    last_used: float
    history: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    def __init__(
        self,
        games: dict[str, Game],
        pickers: dict[str, Picker],
        config: AppConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._games, self._pickers, self._config, self._clock = games, pickers, config, clock
        self._sessions: dict[str, Session] = {}

    # -- lookup --------------------------------------------------------------------

    def _purge(self) -> None:
        cutoff = self._clock() - self._config.session_ttl_seconds
        for sid in [s.id for s in self._sessions.values() if s.last_used < cutoff and not s.lock.locked()]:
            del self._sessions[sid]

    def _find(self, owner: str, sid: str) -> Session:
        self._purge()
        session = self._sessions.get(sid)
        if session is None or session.owner != owner:
            raise SessionNotFound("no such game session")
        return session

    async def get(self, owner: str, sid: str) -> Session:
        session = self._find(owner, sid)
        session.last_used = self._clock()
        return session

    def count(self, owner: str) -> int:
        return sum(1 for s in self._sessions.values() if s.owner == owner)

    # -- lifecycle -----------------------------------------------------------------

    async def create(
        self, owner: str, game_id: str, options: dict[str, Any], difficulty: str, picker: str | None
    ) -> Session:
        self._purge()
        game = get_game(self._games, game_id)
        if difficulty not in self._config.difficulties:
            raise InvalidOptions(f"unknown difficulty {difficulty!r}; valid: {', '.join(self._config.difficulties)}")
        picker = picker or self._config.default_picker.get(game_id, "engine")
        if picker not in self._pickers:
            raise InvalidOptions(f"unknown picker {picker!r}; valid: {', '.join(self._pickers)}")
        if self.count(owner) >= self._config.max_sessions_per_user:
            raise SessionLimit(f"limit of {self._config.max_sessions_per_user} game sessions reached; delete one first")
        state = game.new_state(options)
        player, bot = game.assign_sides(options)
        now = self._clock()
        session = Session(secrets.token_urlsafe(9), owner, game_id, player, bot, state, picker, difficulty, now, now)
        self._sessions[session.id] = session
        return session

    async def delete(self, owner: str, sid: str) -> None:
        del self._sessions[self._find(owner, sid).id]

    # -- moves ---------------------------------------------------------------------

    def _check_turn(self, session: Session, game: Game, expected: str) -> None:
        turn = game.side_to_move(session.state)
        if turn is None:
            raise GameOver("the game is over")
        if turn != expected:
            raise WrongTurn(f"it is {turn}'s turn")

    async def player_move(self, owner: str, sid: str, move: Move) -> Session:
        session = self._find(owner, sid)
        game = self._games[session.game_id]
        async with session.lock:
            self._check_turn(session, game, session.player_side)
            session.state = game.apply(session.state, move)
            session.history.append({"side": session.player_side, "by": "player", "move": move})
            session.last_used = self._clock()
        return session

    async def bot_move(self, owner: str, sid: str) -> tuple[Session, dict[str, Any]]:
        session = self._find(owner, sid)
        game = self._games[session.game_id]
        async with session.lock:
            self._check_turn(session, game, session.bot_side)
            pick = await self._pickers[session.picker].pick(
                game, session.state, self._config.difficulties[session.difficulty]
            )
            try:
                session.state = game.apply(session.state, pick.move)
            except IllegalMove as error:  # a picker bug; never leave the game stuck silently
                raise GameError(f"the bot chose an illegal move: {error}") from error
            entry = {"side": session.bot_side, "by": "bot", "move": pick.move, "source": pick.source}
            session.history.append(entry)
            session.last_used = self._clock()
        return session, entry

    # -- presentation --------------------------------------------------------------

    def view(self, session: Session) -> dict[str, Any]:
        game = self._games[session.game_id]
        turn_side = game.side_to_move(session.state)
        status = game.status(session.state)
        role = None if turn_side is None else ("player" if turn_side == session.player_side else "bot")
        winner = None
        if status.winner is not None:
            winner = "player" if status.winner == session.player_side else "bot"
        return {
            "id": session.id,
            "game": session.game_id,
            "difficulty": session.difficulty,
            "picker": session.picker,
            "player_side": session.player_side,
            "bot_side": session.bot_side,
            "turn": role,
            "status": {"finished": status.finished, "winner": winner, "reason": status.reason},
            "state": game.to_dict(session.state),
            "history": list(session.history),
        }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_sessions.py -q`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/sessions.py apps/mini_games/tests/test_sessions.py
git commit -m "feat(mini_games): per-user game sessions"
```

---

### Task 9: HTTP API, entry point and launcher

**Files:**
- Create: `apps/mini_games/src/api.py`, `apps/mini_games/src/run.py`, `apps/mini_games/run.bat`
- Test: `apps/mini_games/tests/test_api.py`

**Interfaces:**
- Consumes: `SessionStore`, session errors (Task 8); `InternalTokenMiddleware` (Task 2); `build_games`, `load_config`, `load_token`, the three pickers, `LayaClient`.
- Produces: `src.api.create_app(store, games, token="") -> FastAPI` with routes `GET /health`, `GET /games`, `POST /sessions` (201), `GET /sessions/{sid}`, `POST /sessions/{sid}/moves` (body `{"move": {...}}`), `POST /sessions/{sid}/bot-move` (adds `bot_move` to the view), `DELETE /sessions/{sid}` (204); `src.run.build_app() -> (app, config)` and `main()`.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_api.py`

```python
import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.games.registry import build_games
from src.opponent.engine_picker import EnginePicker
from src.opponent.variety_picker import VarietyPicker
from src.sessions import SessionStore

TOKEN = "t0ken"
ANN = {"X-Internal-Token": TOKEN, "X-Requester-Username": "ann"}
BOB = {"X-Internal-Token": TOKEN, "X-Requester-Username": "bob"}


@pytest.fixture
def client(config):
    games = build_games()
    store = SessionStore(games, {"engine": EnginePicker(), "variety": VarietyPicker()}, config)
    return TestClient(create_app(store, games, TOKEN))


def new_game(client, headers=ANN, **body):
    body = {"game": "chess", "difficulty": "easy", "picker": "engine", **body}
    return client.post("/sessions", json=body, headers=headers)


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-Requester-Username": "ann"}, {"X-Internal-Token": "wrong", "X-Requester-Username": "ann"}])
def test_token_is_required(client, headers):
    assert client.get("/games", headers=headers).status_code == 401


def test_requester_header_is_required(client):
    response = client.get("/games", headers={"X-Internal-Token": TOKEN})
    assert response.status_code == 400 and "X-Requester-Username" in response.json()["error"]


def test_list_games(client):
    games = client.get("/games", headers=ANN).json()["games"]
    assert [g["id"] for g in games] == ["chess", "tetris"]
    assert "player_side" in games[0]["options"]


def test_create_session_returns_the_view(client):
    response = new_game(client)
    assert response.status_code == 201
    body = response.json()
    assert body["game"] == "chess" and body["turn"] == "player" and len(body["state"]["legal_moves"]) == 20


def test_full_chess_exchange(client):
    sid = new_game(client).json()["id"]
    moved = client.post(f"/sessions/{sid}/moves", json={"move": {"uci": "e2e4"}}, headers=ANN)
    assert moved.status_code == 200 and moved.json()["turn"] == "bot"
    bot = client.post(f"/sessions/{sid}/bot-move", headers=ANN).json()
    assert bot["turn"] == "player" and bot["bot_move"]["by"] == "bot" and len(bot["history"]) == 2
    assert client.get(f"/sessions/{sid}", headers=ANN).json()["history"] == bot["history"]


def test_tetris_session(client):
    sid = new_game(client, game="tetris", options={"seed": 3, "piece_limit": 5}).json()["id"]
    moved = client.post(f"/sessions/{sid}/moves", json={"move": {"rotation": 0, "column": 0}}, headers=ANN)
    assert moved.status_code == 200 and moved.json()["state"]["placed"] == {"player": 1, "bot": 0}


def test_error_statuses(client):
    sid = new_game(client).json()["id"]
    assert client.post(f"/sessions/{sid}/moves", json={"move": {"uci": "e2e5"}}, headers=ANN).status_code == 400
    assert client.post(f"/sessions/{sid}/bot-move", headers=ANN).status_code == 409  # not the bot's turn
    assert new_game(client, game="go").status_code == 400
    assert new_game(client, difficulty="godlike").status_code == 400
    assert client.post("/sessions", json={"nope": 1}, headers=ANN).status_code == 400
    assert client.get("/sessions/missing", headers=ANN).status_code == 404


def test_other_users_cannot_see_or_touch_a_session(client):
    sid = new_game(client).json()["id"]
    assert client.get(f"/sessions/{sid}", headers=BOB).status_code == 404
    assert client.post(f"/sessions/{sid}/moves", json={"move": {"uci": "e2e4"}}, headers=BOB).status_code == 404
    assert client.delete(f"/sessions/{sid}", headers=BOB).status_code == 404


def test_delete_ends_the_session(client):
    sid = new_game(client).json()["id"]
    assert client.delete(f"/sessions/{sid}", headers=ANN).status_code == 204
    assert client.get(f"/sessions/{sid}", headers=ANN).status_code == 404


def test_session_cap_returns_409(client):
    for _ in range(5):
        assert new_game(client).status_code == 201
    assert new_game(client).status_code == 409
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_api.py -q`
Expected: `ModuleNotFoundError: No module named 'src.api'`.

- [ ] **Step 3: Write the implementation**

`apps/mini_games/src/api.py`

```python
"""HTTP API used by ember_api and, later, the MCP extension tools.

Every route but /health needs X-Internal-Token (once configured) and an
X-Requester-Username naming the session owner.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.auth import REQUESTER_USERNAME_HEADER, InternalTokenMiddleware
from src.games.base import Game, IllegalMove, InvalidOptions
from src.sessions import GameOver, SessionLimit, SessionNotFound, SessionStore, WrongTurn


class CreateBody(BaseModel):
    game: str
    options: dict[str, Any] = Field(default_factory=dict)
    difficulty: str = "medium"
    picker: str | None = None


class MoveBody(BaseModel):
    move: dict[str, Any]


def _owner(name: str) -> str:
    owner = name.strip()
    if not owner:
        raise HTTPException(400, f"{REQUESTER_USERNAME_HEADER} header is required")
    return owner


def _error(status: int):
    async def handler(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"error": str(error)}, status_code=status)

    return handler


def create_app(store: SessionStore, games: dict[str, Game], token: str = "") -> FastAPI:
    app = FastAPI(title="mini_games", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(InternalTokenMiddleware, token=token)

    for error, status in (
        (IllegalMove, 400), (InvalidOptions, 400), (SessionNotFound, 404),
        (WrongTurn, 409), (GameOver, 409), (SessionLimit, 409),
    ):
        app.add_exception_handler(error, _error(status))

    @app.exception_handler(RequestValidationError)
    async def bad_body(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "invalid request body", "detail": str(error.errors()[:3])}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"error": error.detail}, status_code=error.status_code)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/games")
    async def list_games(x_requester_username: str = Header(default="")) -> dict[str, Any]:
        _owner(x_requester_username)
        return {"games": [{"id": g.id, "options": g.option_schema()} for g in games.values()]}

    @app.post("/sessions", status_code=201)
    async def create_session(body: CreateBody, x_requester_username: str = Header(default="")) -> dict[str, Any]:
        session = await store.create(_owner(x_requester_username), body.game, body.options, body.difficulty, body.picker)
        return store.view(session)

    @app.get("/sessions/{sid}")
    async def get_session(sid: str, x_requester_username: str = Header(default="")) -> dict[str, Any]:
        return store.view(await store.get(_owner(x_requester_username), sid))

    @app.post("/sessions/{sid}/moves")
    async def player_move(sid: str, body: MoveBody, x_requester_username: str = Header(default="")) -> dict[str, Any]:
        return store.view(await store.player_move(_owner(x_requester_username), sid, body.move))

    @app.post("/sessions/{sid}/bot-move")
    async def bot_move(sid: str, x_requester_username: str = Header(default="")) -> dict[str, Any]:
        session, entry = await store.bot_move(_owner(x_requester_username), sid)
        return {**store.view(session), "bot_move": entry}

    @app.delete("/sessions/{sid}", status_code=204)
    async def delete_session(sid: str, x_requester_username: str = Header(default="")) -> None:
        await store.delete(_owner(x_requester_username), sid)

    return app
```

`apps/mini_games/src/run.py`

```python
"""Start the mini_games backend: `python -m src.run`."""

from __future__ import annotations

import logging

import uvicorn

from src.api import create_app
from src.auth import load_token
from src.config import load_config
from src.games.registry import build_games
from src.opponent.engine_picker import EnginePicker
from src.opponent.laya_client import LayaClient, LayaError
from src.opponent.laya_picker import LayaPicker
from src.opponent.variety_picker import VarietyPicker
from src.sessions import SessionStore

log = logging.getLogger("mini_games")


def build_app():
    config = load_config()
    games = build_games()
    laya = LayaClient(timeout=config.laya_timeout_seconds)
    if laya.is_available():
        try:
            laya.prepare()
            log.info("Laya loaded")
        except LayaError as error:
            log.warning("Laya could not be loaded; the laya picker will use the engine: %s", error)
    else:
        log.info("Laya is not installed; the laya picker will use the engine")
    pickers = {p.name: p for p in (EnginePicker(), VarietyPicker(), LayaPicker(laya))}
    store = SessionStore(games, pickers, config)
    return create_app(store, games, load_token()), config


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
REM mini_games dev launcher - serves the chess and Tetris backend over HTTP on the
REM port in configs\config_app.json (8060 by default).
REM LABEL: Mini Games
REM DESCRIPTION: Game backend for Ember (chess, Tetris): engines, a Laya-assisted opponent and per-user game sessions. No LLM, no billing.

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

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_api.py -q`
Expected: 13 passed (a starlette `httpx` deprecation warning is harmless).

- [ ] **Step 5: Smoke-test the real process**

Run in one terminal: `apps/mini_games/run.bat` (creates `configs/config_app.json` and `secrets/.env` from the examples on first start).
Then:

```bash
curl -s http://127.0.0.1:8060/health
curl -s -H "X-Requester-Username: ann" -X POST -H "Content-Type: application/json" -d '{"game":"chess","difficulty":"easy"}' http://127.0.0.1:8060/sessions
```

Expected: `{"status":"ok"}`, then a session JSON with `"turn":"player"`. With a token set in `secrets/.env` the second call returns 401 until `-H "X-Internal-Token: <value>"` is added. Stop the server (Ctrl+C, then `Q`).

- [ ] **Step 6: Commit**

```bash
git add apps/mini_games/src/api.py apps/mini_games/src/run.py apps/mini_games/run.bat apps/mini_games/tests/test_api.py
git status --short   # no configs/config_app.json, no secrets/.env
git commit -m "feat(mini_games): HTTP API, entry point and launcher"
```

---

### Task 10: Laya eval harness

**Files:**
- Create: `apps/mini_games/src/eval/__init__.py` (empty), `apps/mini_games/src/eval/laya_eval.py`
- Test: `apps/mini_games/tests/test_eval.py`

**Interfaces:**
- Consumes: `Game`, `build_games`, `LayaClient`, `LayaError`, `DEFAULT_MODEL`, `INSTRUCTIONS`.
- Produces: `GameReport` (frozen dataclass), `sample_states(game, count, rng)`, `async evaluate_game(game, client, positions, k, depth, seed) -> GameReport`, `render_report(reports, k, depth, seed, today) -> str`, `async run(positions, k, depth, seed, out)`, `main()`; constants `MIN_SAMPLES = 30`, `LOSS_RATIO = 0.75`, `LOSS_CAP = 20.0`, `OUT_PATH` (`docs/laya-eval.md`). Verdict is `"laya"` only with at least 30 scored samples and a Laya mean loss at most 75% of the random baseline's.

- [ ] **Step 1: Write the failing tests**

`apps/mini_games/tests/test_eval.py`

```python
import asyncio
import random
from datetime import date

from src.eval.laya_eval import MIN_SAMPLES, evaluate_game, render_report, sample_states
from src.games.chess_game import ChessGame
from src.games.tetris_game import TetrisGame
from src.opponent.laya_client import LayaClient
from tests.fake_laya import FakeEngine


def run_eval(game, engine, positions=MIN_SAMPLES):
    return asyncio.run(evaluate_game(game, LayaClient(engine), positions, k=4, depth=1, seed=1))


def test_sampled_positions_are_unfinished_and_reproducible():
    game = ChessGame()
    a = sample_states(game, 5, random.Random(3))
    assert a == sample_states(game, 5, random.Random(3))
    assert len(a) == 5 and all(not game.status(s).finished for s in a)


def test_tetris_positions_can_be_sampled_too():
    game = TetrisGame()
    states = sample_states(game, 5, random.Random(3))
    assert len(states) == 5


def test_always_best_laya_beats_random():
    # "a" is always the engine's best candidate, so Laya loses nothing.
    report = run_eval(ChessGame(), FakeEngine(pick="a"))
    assert report.samples == MIN_SAMPLES and report.failures == 0
    assert report.laya_agreement == 1.0 and report.laya_loss == 0.0
    assert report.random_loss > 0 and report.random_agreement < 0.5
    assert report.verdict == "laya"


def test_always_worst_laya_loses_to_random():
    report = run_eval(ChessGame(), FakeEngine(pick="d"))
    assert report.laya_loss > report.random_loss and report.verdict == "variety"


def test_too_few_samples_never_earn_a_laya_verdict():
    report = run_eval(ChessGame(), FakeEngine(pick="a"), positions=5)
    assert report.samples == 5 and report.verdict == "variety"


def test_failures_are_counted_not_scored():
    report = run_eval(ChessGame(), FakeEngine(usage={"truncated": True}), positions=5)
    assert report.samples == 0 and report.failures == 5 and report.verdict == "variety"


def test_report_renders_a_table_and_the_rule():
    report = run_eval(ChessGame(), FakeEngine(pick="a"))
    text = render_report([report], k=4, depth=1, seed=1, today=date(2026, 10, 9))
    assert "| chess | 30 |" in text and "Decision rule" in text and "2026-10-09" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest tests/test_eval.py -q`
Expected: `ModuleNotFoundError: No module named 'src.eval'`.

- [ ] **Step 3: Write the implementation**

```bash
mkdir -p apps/mini_games/src/eval && touch apps/mini_games/src/eval/__init__.py
```

`apps/mini_games/src/eval/laya_eval.py`

```python
"""Does Laya pick better candidate moves than chance? Run manually:

    python -m src.eval.laya_eval [--positions N] [--k K] [--depth D] [--seed S] [--out PATH]

Needs the real model (`pip install -e ".[laya]"`). Not part of the test suite.
For each sampled position it asks Laya to choose among the engine's top k
candidates and compares the engine score of the chosen move with the best one
and with a uniformly random pick from the same candidates.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.games.base import Game
from src.games.registry import build_games
from src.opponent.laya_client import DEFAULT_MODEL, LayaClient, LayaError
from src.opponent.laya_picker import INSTRUCTIONS

OUT_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "laya-eval.md"
MIN_SAMPLES = 30
LOSS_RATIO = 0.75  # Laya must lose at most this share of what a random pick loses
LOSS_CAP = 20.0  # a forced mate scores +-10000; cap each gap so one position cannot dominate the mean


@dataclass(frozen=True)
class GameReport:
    game: str
    samples: int
    failures: int
    laya_agreement: float  # share of positions where Laya chose the engine's best move
    random_agreement: float
    laya_loss: float  # mean score gap to the best candidate
    random_loss: float
    mean_latency: float
    verdict: str  # "laya" or "variety"


def sample_states(game: Game, count: int, rng: random.Random) -> list[Any]:
    """Unfinished positions reached by random legal play from the start."""
    states: list[Any] = []
    attempts = 0
    while len(states) < count and attempts < count * 20:
        attempts += 1
        state = game.new_state({})
        for _ in range(rng.randint(2, 24)):
            moves = game.legal_moves(state)
            if not moves or game.status(state).finished:
                break
            state = game.apply(state, rng.choice(moves))
        if not game.status(state).finished and game.side_to_move(state) is not None:
            states.append(state)
    return states


def _gap(best: float, score: float) -> float:
    return min(best - score, LOSS_CAP)


async def evaluate_game(game: Game, client: LayaClient, positions: int, k: int, depth: int, seed: int) -> GameReport:
    rng = random.Random(f"{game.id}:{seed}")
    agree = random_agree = failures = scored = 0
    laya_loss = random_loss = latency = 0.0
    for state in sample_states(game, positions * 2, rng):  # spare positions cover ones with a single candidate
        if scored + failures == positions:
            break
        cands = game.candidates(state, k, depth, 5.0)
        if len(cands) < 2:
            continue
        keys = [chr(ord("a") + i) for i in range(len(cands))]
        options = {key: game.summarize(state, c) for key, c in zip(keys, cands)}
        started = time.monotonic()
        try:
            choice = await client.choose(game.describe_position(state), INSTRUCTIONS, options)
        except LayaError:
            failures += 1
            continue
        latency += time.monotonic() - started
        best = cands[0].score
        chosen = keys.index(choice.key)
        scored += 1
        agree += chosen == 0
        laya_loss += _gap(best, cands[chosen].score)
        random_agree += 1 / len(cands)
        random_loss += sum(_gap(best, c.score) for c in cands) / len(cands)
    if scored == 0:
        return GameReport(game.id, 0, failures, 0.0, 0.0, 0.0, 0.0, 0.0, "variety")
    report = GameReport(
        game.id, scored, failures, agree / scored, random_agree / scored,
        laya_loss / scored, random_loss / scored, latency / scored, "variety",
    )
    better = scored >= MIN_SAMPLES and report.laya_loss <= LOSS_RATIO * report.random_loss
    return GameReport(**{**report.__dict__, "verdict": "laya" if better else "variety"})


def render_report(reports: list[GameReport], k: int, depth: int, seed: int, today: date) -> str:
    lines = [
        "# Laya eval", "",
        f"Date: {today.isoformat()}. Model: `{DEFAULT_MODEL}`. Candidates per position: {k}. "
        f"Engine depth: {depth}. Seed: {seed}.", "",
        "Laya chose among the engine's top candidates. Loss is the engine score gap to the best "
        "candidate (chess in pawns, Tetris in heuristic points, each gap capped at 20 so a forced mate "
        "cannot dominate); lower is better. The random baseline "
        "is the exact expectation of a uniform pick from the same candidates.", "",
        "| Game | Samples | Failed | Laya picks best | Random picks best | Laya loss | Random loss | Latency (s) | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| {r.game} | {r.samples} | {r.failures} | {r.laya_agreement:.0%} | {r.random_agreement:.0%} | "
            f"{r.laya_loss:.3f} | {r.random_loss:.3f} | {r.mean_latency:.2f} | {r.verdict} |"
        )
    lines += [
        "", f"Decision rule: Laya becomes a game's default picker only with at least {MIN_SAMPLES} samples "
        f"and a mean loss at most {LOSS_RATIO:.0%} of the random baseline's. Otherwise the default is `variety`.",
        "These are positions from random play, not a held-out benchmark of real games.", "",
    ]
    return "\n".join(lines)


async def run(positions: int, k: int, depth: int, seed: int, out: Path) -> str:
    client = LayaClient(timeout=30.0)
    if not client.is_available():
        raise SystemExit('Laya is not installed: pip install -e ".[laya]"')
    client.prepare()
    reports = [await evaluate_game(game, client, positions, k, depth, seed) for game in build_games().values()]
    text = render_report(reports, k, depth, seed, date.today())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--positions", type=int, default=60)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    print(asyncio.run(run(args.positions, args.k, args.depth, args.seed, args.out)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the whole suite**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest -q`
Expected: 144 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/mini_games/src/eval apps/mini_games/tests/test_eval.py
git commit -m "feat(mini_games): Laya eval harness"
```

---

### Task 11: README, scaffold audit and launcher check

**Files:**
- Create: `apps/mini_games/README.md`

**Interfaces:**
- Consumes: the finished project.

- [ ] **Step 1: Write the README**

`apps/mini_games/README.md`

````markdown
# mini_games

Game backend for Ember: chess and Tetris against a bot, over HTTP. It holds the
game engines, the opponent and the per-user game sessions. It never calls an LLM,
so a game costs nothing. Spec:
`docs/superpowers/specs/2026-10-09-mini-games-backend-design.md` (repo root).

Part 1 of 3. The `ember_api` proxy with the `ember_web` page, and the MCP
extension tools for starting a game from chat, come in later specs.

## How the bot plays

1. The game engine finds and scores the best moves (`k` of them, set by the
   difficulty).
2. A picker chooses one:
   - `engine` - always the best move.
   - `variety` - a weighted random pick among the top moves; no model.
   - `laya` - the local Laya model reads a short text summary of the position
     and one line per candidate and picks one. If Laya is uncertain, missing,
     slow or wrong, the engine's best move is used, so a turn never fails.
3. `configs/config_app.json` sets the default picker per game and the
   difficulty table. `docs/laya-eval.md` records whether Laya beat random choice
   and therefore which default was chosen.

Laya reads text only (512-token window); it cannot read a board, which is why
the engine proposes the candidates.

## Games

| Id | Notes |
|---|---|
| `chess` | `python-chess` rules, alpha-beta search. Option `player_side`: `white` or `black`. |
| `tetris` | Versus race on the same seeded pieces, in lockstep: the player places piece n, then the bot places piece n. Options `seed`, `piece_limit` (5 to 200, default 40). No garbage lines yet. |

A game is one plugin file in `src/games/` implementing the `Game` protocol in
`src/games/base.py`, plus a line in `src/games/registry.py`.

## Requirements

- Python 3.11 or newer on Windows (`py` launcher).
- Optional: the `laya` package for the Laya picker (`pip install -e ".[laya]"`).

## Run

```
run.bat
```

The first start creates `.venv_mini_games`, installs the project, and creates
`configs/config_app.json` and `secrets/.env` from their `.example` twins. Both
real files are gitignored. Put the same `INTERNAL_API_TOKEN` in `secrets/.env`
that `mcp_server`, `ai_agent` and `ember_api` use; once it is set, every route
except `/health` needs the `X-Internal-Token` header.

`server_launcher` lists this project from its `run.bat`.

## API

All routes except `/health` need `X-Internal-Token` (once configured) and
`X-Requester-Username`, the session owner.

| Route | Purpose |
|---|---|
| `GET /health` | Liveness, no auth |
| `GET /games` | Game ids and their option schemas |
| `POST /sessions` | Body `{"game", "options", "difficulty", "picker"}`; returns the session view |
| `GET /sessions/{id}` | Current state, turn, status and history |
| `POST /sessions/{id}/moves` | Body `{"move": {...}}`; the player's move |
| `POST /sessions/{id}/bot-move` | The bot picks and plays; the view gains `bot_move` |
| `DELETE /sessions/{id}` | End the session |

Moves: chess `{"uci": "e2e4"}`; Tetris `{"rotation": 0, "column": 3}` (`column` is
the leftmost column of the rotated piece).

Errors: 400 bad move, body, option or game; 401 bad token; 404 unknown or someone
else's session; 409 wrong turn, game over, or too many sessions. The `turn` field
of a session view is `player`, `bot` or `null` (finished). When the bot moves
first (chess with `player_side` black), call `bot-move` right after creating.

Sessions live in memory only: a restart ends all games, and idle sessions expire
(`session_ttl_seconds`). Each user may hold `max_sessions_per_user`.

## Tests and the Laya eval

```
.venv_mini_games\Scripts\python -m pytest
.venv_mini_games\Scripts\python -m src.eval.laya_eval
```

The tests use a fake Laya engine. The eval needs the real model and is run by
hand; it writes `docs/laya-eval.md`.

## Layout

- `src/games/` - game protocol, chess, Tetris and the registry.
- `src/opponent/` - the Laya client and the three pickers.
- `src/sessions.py` - sessions, locks, turn checks, expiry.
- `src/api.py`, `src/run.py` - HTTP app and entry point.
- `src/eval/` - the Laya evaluation harness.
- `configs/`, `secrets/` - gitignored real files with committed `.example` twins.
````

- [ ] **Step 2: Audit the folder against `root-project-scaffold`**

Run: `ls -A apps/mini_games`
Expected exactly: `.venv_mini_games  README.md  configs  pyproject.toml  run.bat  secrets  src  tests` (and `docs` once Task 12 writes it). Any other entry is a convention break: move it under `src/` or remove it.

Run: `git check-ignore apps/mini_games/configs/config_app.json apps/mini_games/secrets/.env apps/mini_games/.venv_mini_games`
Expected: all three paths are printed (ignored). `git ls-files apps/mini_games/configs apps/mini_games/secrets` lists only the two `.example` files.

- [ ] **Step 3: Check that server_launcher discovers it**

Run: `apps/server_launcher/run.bat`, or start the launcher the usual way.
Expected: "Mini Games" appears in the project list (it reads the `REM LABEL:` and `REM DESCRIPTION:` lines of `run.bat`) and starting it brings up port 8060. If the launcher keeps a hardcoded project list somewhere, add the entry there and say so in the commit message.

- [ ] **Step 4: Commit**

```bash
git add apps/mini_games/README.md
git commit -m "docs(mini_games): README"
```

---

### Task 12: Run the Laya eval and set the default pickers (manual, needs the real model)

**Files:**
- Create: `apps/mini_games/docs/laya-eval.md` (written by the harness)
- Modify: `apps/mini_games/configs/config_app.json.example`, and the real `configs/config_app.json` (gitignored)

This task needs the real `laya` package and checkpoint. If they cannot be installed here, do Step 4 instead and stop.

- [ ] **Step 1: Install Laya into the project venv**

```bash
cd apps/mini_games && .venv_mini_games/Scripts/python -m pip install -e ".[laya]" && cd ../..
```

Expected: `laya` installs. (`ai_agent` documents the same extra.)

- [ ] **Step 2: Run the eval**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m src.eval.laya_eval --positions 60 --k 4 --depth 2 --seed 1`
Expected: prints the table and writes `docs/laya-eval.md`. Takes a few minutes; Laya latency is in the table.

- [ ] **Step 3: Apply the decision rule from the table**

For each game whose Verdict column says `laya`, set that game to `"laya"` in `default_picker` in `configs/config_app.json.example` (and in the real `configs/config_app.json`). Leave games whose verdict is `variety` as they are. Example when only chess qualifies:

```json
"default_picker": {"chess": "laya", "tetris": "variety"},
```

Do not lower `MIN_SAMPLES` or `LOSS_RATIO` to make a game qualify; if results look noisy, re-run with a different `--seed` and more `--positions` and keep the same rule.

- [ ] **Step 4: If Laya could not be run**

Create `apps/mini_games/docs/laya-eval.md` containing the date, the reason it was not run, and that both games default to `variety` until `python -m src.eval.laya_eval` is run.

- [ ] **Step 5: Run the whole suite and commit**

Run: `cd apps/mini_games && .venv_mini_games/Scripts/python -m pytest -q`
Expected: 144 passed (a test that needs Laya to be absent will skip itself if it is installed).

```bash
git add apps/mini_games/docs apps/mini_games/configs/config_app.json.example
git commit -m "docs(mini_games): Laya eval results and default pickers"
```

---

## Self-Review

**Spec coverage**
- Project shape, port, token, config/secrets twins, no cross-imports: Tasks 1, 2, 9, 11.
- Game protocol, chess, Tetris (versus race, lockstep, seeded pieces, heuristic): Tasks 3 to 5.
- Opponent (`EnginePicker`, `VarietyPicker`, `LayaPicker`, fallback, difficulty `k` and trust): Task 7; Laya wrapper (lazy load, lock, worker thread, timeout): Task 6.
- Sessions (in-memory, per-session lock, turn check, owner isolation, TTL, per-user cap): Task 8.
- HTTP API routes and status codes: Task 9.
- Laya eval, decision rule, `docs/laya-eval.md`: Tasks 10 and 12.
- Testing list in the spec: covered by the per-task test files; the eval smoke test uses the fake engine.
- Out of scope (MCP tools, `ember_api`/`ember_web`, persistence, garbage lines): not planned here.

**Interpretations to confirm when reviewing**
- Tetris "versus" is lockstep alternation, so the session's turn check applies to Tetris exactly as to chess. The browser still owns gravity and only sends the final placement.
- The spec's "timeout" for Laya is `laya_timeout_seconds` in the config (default 5.0); the engine search limit is each difficulty's `time_limit`.
- The eval caps each score gap at 20 so a forced-mate score (10000) cannot dominate a chess average. The spec did not mention this.
- The session cap returns 409, as the spec's status list has no 429.
