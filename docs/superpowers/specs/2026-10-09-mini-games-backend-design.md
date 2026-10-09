# mini_games backend

Date: 2026-10-09. Scope: new project `apps/mini_games`. This is spec 1 of 3.

## Problem

The user wants to play chess and Tetris against an AI inside Ember, at no
billing cost. The opponent should use the local Laya model in its decision
making. Laya is a 512-token typed-question classifier (`choice`, `score`,
`noul`). It reads text only, generates no text, and cannot read a board. It
cannot be trusted to find moves on its own.

## Decision

1. `mini_games` is its own project in `apps/mini_games/`: a backend that hosts
   the game engines, the opponent and the game sessions. It has no web UI.
2. A conventional engine proposes and scores moves. Laya chooses among the
   engine's top candidates, described as short feature text. The engine's best
   move is the fallback.
3. The backend exposes an HTTP API that `ember_api` (spec 2) and MCP extension
   tools (spec 3) both use. Neither is built here.
4. Laya's real value is measured before it is trusted (see Laya eval).

## Series

| Spec | Scope |
|---|---|
| 1 (this) | Backend: game plugins, opponent, sessions, HTTP API, Laya eval |
| 2 | `ember_api` proxy routes and the `ember_web` `/mini_games` page |
| 3 | MCP extension tools, chat "Play" card, floating modal |

## Project shape

Follows `root-project-scaffold`:

- `README.md`, `pyproject.toml`, `run.bat`, `configs/`, `secrets/`, `src/`,
  `tests/`, and `docs/` for the Laya eval results.
- Own venv. Dependencies: `fastapi`, `uvicorn`, `python-chess`. Optional extra
  `laya`, same name as in `ai_agent`.
- Port 8060 (8010 mcp_server, 8020 catalog_service, 8030 ember_api,
  8040 pdf_merger, 8050 video_downloader are taken).
- `secrets/.env` holds `INTERNAL_API_TOKEN`, the same shared value as the other
  projects, with a committed `.env.example`. Every route requires it
  (`X-Internal-Token`) once set, like `ai_agent` and `mcp_server`.
- `configs/config_app.json` (gitignored, with a committed `.example`) holds the
  port, session idle TTL, the default picker and the difficulty table.
- No imports from other projects. The Laya wrapper is a copy, not an import
  from `ai_agent`.
- `server_launcher` discovers the project from `run.bat`.

## Game plugins (`src/games/`)

One protocol, `Game`, in `base.py`:

- `new_state(options)`: start a game. Options are per game (chess: player
  colour; Tetris: seed and piece limit).
- `legal_moves(state)`: all moves for the side to move.
- `apply(state, move)`: returns the new state; raises on an illegal move.
- `status(state)`: `ongoing`, or the result and reason.
- `evaluate(state, side)`: engine score from `side`'s view.
- `candidates(state, k)`: top `k` moves by engine score, best first.
- `summarize(state, move)`: one short feature line for a candidate, used in the
  Laya question.
- `to_dict(state)` / `move_from_dict(raw)`: the JSON shapes the API sends.

A new game is one new file that implements this protocol and is listed in a
registry dict.

### Chess (`chess_game.py`)

Wraps `python-chess`. Rules, legality and results come from the library.
`evaluate` is material plus a simple positional term, searched with shallow
alpha-beta (depth from the difficulty table). State is a FEN string.

### Tetris (`tetris_game.py`)

- 10 by 20 board, the 7 standard pieces, and a seeded piece sequence so both
  sides see the same pieces.
- A move is a placement: `{rotation, column}`. The server simulates the drop,
  clears full lines and detects top-out. The browser owns the gravity loop and
  sends the final placement; the server only validates it.
- `candidates` enumerates every placement (at most 4 rotations by 10 columns)
  and scores it with a standard heuristic: aggregate height, holes, bumpiness
  and lines cleared.
- Versus mode (v1): player and bot each have their own board and receive the
  same seeded pieces. The game ends at the piece limit or when either side
  tops out. Higher score wins. Garbage lines are out of scope.

## Opponent (`src/opponent/`)

`Picker` interface: `async pick(game, state) -> Move`.

- `EnginePicker`: returns `candidates(state, 1)[0]`.
- `VarietyPicker`: weighted random pick among the top `k` engine candidates.
  No Laya.
- `LayaPicker`: builds one `choice` question from the top `k` candidates and
  asks Laya.
  - `text`: a compact position summary (chess: side to move, material balance,
    check state, move number; Tetris: column heights, holes, current piece),
    kept well under the 4000-character limit.
  - `questions`: one `choice` question. Option keys are `a`, `b`, `c`, ...
    Option values are the candidates' `summarize` lines. Instructions ask which
    move is strongest.
  - If Laya reports `uncertain`, raises, is not installed or times out, the
    picker returns the engine's top move. A Laya failure never fails a turn.
  - The difficulty table sets `k` and whether an uncertain answer is trusted.

`laya_client.py` is the wrapper: lazy load under a lock, inference in a worker
thread (`anyio.to_thread`), the same request and response contract as
`ai_agent`'s `laya_provider.py` (`choice` question, `answer_confidence`,
`uncertain`). The model loads at startup if the `laya` extra is installed.

The default picker is set by the eval result: `LayaPicker` only if the eval
shows it clearly beats random choice among the same candidates, otherwise
`VarietyPicker`. Laya stays selectable per session either way.

## Sessions (`src/sessions.py`)

- In-memory `SessionStore`. A session holds the game id, state, owner, the
  picker, move history, creation time and last-used time. There is no
  persistence in v1: a restart ends all games.
- Each session has its own `asyncio.Lock`. Every mutation takes it, so a player
  move and a bot move cannot interleave, and two clients (the page and the
  chat assistant) cannot both move at once.
- Turn check: a move from the player on the bot's turn, or a bot move on the
  player's turn, is rejected with a clear error.
- Owner is the `X-Requester-Username` header. A session id belonging to
  another user returns 404, the same as a missing id.
- Idle sessions are dropped after the configured TTL. A cap on sessions per
  user bounds memory.

## HTTP API (`src/api.py`)

All routes need `X-Internal-Token` and `X-Requester-Username`.

| Route | Purpose |
|---|---|
| `GET /games` | List game ids and their option schemas |
| `POST /sessions` | Create a session: `{game, options, difficulty, picker?}` |
| `GET /sessions/{id}` | State, status, whose turn, history |
| `POST /sessions/{id}/moves` | Player move; returns the new state |
| `POST /sessions/{id}/bot-move` | Bot picks and applies its move; returns the move and state |
| `DELETE /sessions/{id}` | End the session |

Errors: 400 illegal move or bad body, 401 bad token, 404 unknown or foreign
session, 409 wrong turn or game over. Bodies are JSON and fully validated;
nothing reaches a game plugin unvalidated.

## Laya eval (`src/eval/laya_eval.py`)

Run manually with `python -m src.eval.laya_eval`; it needs the real model and
is not part of the test suite.

- Builds sample positions: chess positions from random-opening self-play,
  Tetris boards from random piece sequences.
- For each, asks Laya to choose among the engine's top `k` candidates, then
  records the engine score of the chosen move.
- Reports, per game: how often Laya picks the engine's best move, the average
  evaluation loss against the best candidate, and the same numbers for a
  random pick among the same candidates, plus the mean latency per question.
- Writes `docs/laya-eval.md` with the date, model name, sample sizes and
  numbers.
- Decision rule: Laya becomes the default picker for a game only if its average
  evaluation loss is clearly lower than random's, with the sample size stated.
  Otherwise that game defaults to `VarietyPicker`.

## Error handling

- Laya missing or failing: fall back to the engine's best move; log once.
- Bad move or wrong turn: typed API errors; session state unchanged.
- Unknown game id or option: 400 with the valid choices.
- Engine search must not block the event loop: run it in a worker thread with a
  time limit from the difficulty table.

## Testing

- Chess: wrapper, `evaluate` and `candidates` ordering, status mapping, FEN
  round trip.
- Tetris: collision, rotation, line clear, top-out, placement enumeration,
  seeded sequence repeatability, versus end conditions.
- Pickers: engine, variety and Laya using an injected fake engine, covering
  uncertain answers, exceptions, a missing package and a timeout.
- Sessions: lock prevents interleaved moves, turn check, owner isolation, TTL
  expiry, per-user cap.
- API: token and header checks, every error status, happy path per route.
- The eval harness is exercised by the fake engine in a smoke test; its real
  run is manual.
- Run the whole `mini_games` suite.

## Out of scope

- MCP extension tools, the chat "Play" card and the modal (spec 3).
- The `ember_api` proxy and the `ember_web` page (spec 2).
- Session persistence, accounts of its own, Tetris garbage lines, more games.
- Any LLM call. The backend never bills.
