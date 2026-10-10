# Emberlings Ember Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an Ember user play Emberlings in the browser (collect Sparks, fight wild ones, answer the EMBLEM prompt, spend Insignia in the shop) through a validating ember_api pass-through to `apps/mini_games`.

**Architecture:** ember_api gains `routes/emberlings.py` (prefix `/api/emberlings`, permission `emberlings.play`, request models that reject unknown fields, a required `Idempotency-Key` on every change, audit lines for value changes) and `services/emberlings_gateway.py` (`EmberlingsGateway`, one fixed route list, owner header = account id, internal token, 10 s timeout) behind an `EmberlingsApi` Protocol that tests replace with `FakeEmberlings`. ember_web gains `EmberlingsClient.ts`, a Pinia store that owns the battle loop (1.5 s pace, pause when hidden or left, prompt countdown on the monotonic clock, stale-409 refresh, reconnect every 3 s), components under `src/components/emberlings/`, and `src/views/EmberlingsView.vue` at `/emberlings`. All game state stays in mini_games' SQLite; ember_api stores nothing new.

**Tech Stack:** Python 3.11, FastAPI, pydantic v2, httpx, pytest (ember_api). Vue 3 + TypeScript (`erasableSyntaxOnly`), Pinia setup stores, vue-router, Vitest + jsdom + `@vue/test-utils`, Playwright (ember_web).

**Spec:** `docs/superpowers/specs/2026-10-10-emberlings-ember-page-design.md` (binding). The backend it talks to: `apps/mini_games/README.md`, `apps/mini_games/src/sparks/api.py`, `battle_view.py`, `collection.py`, `encounters.py`, `shop.py`, `coordinator.py`, `progression.py`.

## Global Constraints

- The owner sent to mini_games is the account's id as text (`X-Requester-Username: str(account.id)`), never the username.
- New permission `emberlings.play` ("Play Emberlings"). The Administrator role gets it on the next start; the `Member` role does not (existing roles are never re-seeded). Say so at hand-over; it is granted from the roles page.
- No ember_api database table, model or Alembic migration. ember_api is a validating pass-through.
- Every mutation needs an `Idempotency-Key` header of 1 to 200 characters; without one ember_api answers 400 before anything reaches mini_games.
- Identity headers the browser sends (`X-Requester-Username`, `X-Requester-Email`, `X-Internal-Token`) are dropped; the gateway builds every upstream header itself.
- The mini_games address and the internal token never reach the browser (not in responses, not in the bundle).
- ember_web styling uses theme tokens only (`--bg`, `--surface`, `--text`, `--muted`, `--border`, `--accent`, `--accent-contrast`, `--danger`, `--warning`, `--success`, `--code-bg`) and the `--radius-*` scale; `src/radiusScale.test.ts` fails on a literal radius.
- Pages live in `src/views/`, reusable pieces in `src/components/`.
- TypeScript: no `enum`, no constructor parameter properties (`tsconfig.app.json` has `erasableSyntaxOnly`).
- Config key `emberlings_url` is optional, default `http://127.0.0.1:8060`; the token is the existing `INTERNAL_API_TOKEN` in `.env`.
- Autonomous round pace is 1.5 seconds, a constant in the store.
- Round actions and `advance` are not written to the activity log; only `emberlings.profile_create`, `battle_start`, `battle_forfeit`, `shop_buy`, `spark_sell`.
- No browser-verification agents: the user plays it by hand.

## How to run this plan

- **PART A (ember_api, Tasks A1 to A4) may run continuously**: each task ends green and is committed before the next starts.
- **PART B (ember_web, Tasks B1 to B9): stop before each task.** The user's standing rule is one step at a time: propose the task (files to create or change, nothing else), wait for approval, implement, verify, report, and commit only after the user agrees. Never start the next B task unasked.
- ember_api commands run from `apps/Ember/ember_api/` with its venv: `.venv_ember_api/Scripts/python -m pytest ...` (in PowerShell: `.\.venv_ember_api\Scripts\python -m pytest ...`).
- ember_web commands run from `apps/Ember/ember_web/`: `npx vue-tsc -b --noEmit` (must print nothing), `npm test`, `npx vite build` and then delete `dist/`.
- `git` commands run from the repo root `D:/User/Documents/Programming/Python/MCPServer`. Never stage the unrelated `Server Launcher.lnk` or `scuti_server_launcher.exe`; always `git add` explicit paths.

## Facts from the real code that this plan relies on

These differ from, or add to, what the spec assumed. Each task already accounts for them.

1. mini_games answers its own `HTTPException`s with `{"detail": ...}` (missing `Idempotency-Key` or requester header, a bad purchase `kind`) and pydantic errors with 422; only `SparkError`s use `{"error": ...}`. The gateway reads `error`, then `detail`, and maps any other 4xx (such as 422) to a 400 refusal.
2. A finished battle has `status: "terminal"` and `phase: "terminal"`; the outcome is `result.kind`, one of `won`, `knocked_out`, `captured`, `escaped`, `wild_escaped`, `forfeited`.
3. `POST /sparks/battles` refuses `mode: "autonomous"` unless both `preset_slot` and `emblem_limit` are set (and the preset holds a personality). The start form therefore keeps "None" as the default EMBLEM limit, as the spec says, but disables Fight in Autonomous mode until a preset and a limit are chosen.
4. The EMBLEM prompt only happens in autonomous mode (`advance` opens it). `advance` before the deadline returns the same view (`seconds_left` > 0), so the store simply restarts its countdown from the new `seconds_left`.
5. `actions` lists only ready abilities. Not-ready ones are taken from `player.abilities` (`ready: false`) and shown disabled with their cooldown length (the rounds remaining are not in the view).
6. The copy price depends on economy numbers that `GET /sparks/catalog` does not return (`purchase_factor`, `sale_level_bonus`), so the browser cannot know it. EMBLEM buttons are disabled when Insignia would not cover `emblem_price * quantity`; copy purchases are not price-gated and the server's 409 message ("that costs N Insignia and you have M") is shown.
7. `apiRequest` in `src/api/http.ts` has no way to send extra headers. Task B1 adds an optional `headers` argument.
8. `crypto.randomUUID()` exists only in secure contexts (HTTPS or localhost). ember over plain HTTP on a LAN address would throw, so `newIdempotencyKey()` falls back to `crypto.getRandomValues`.
9. `src/views/WatchersView.vue` no longer exists (removed in `0d3cc62`); view and test style follow `src/views/AgentsView.vue` and `AgentsView.test.ts` instead.
10. `SegmentedControl` has no per-option disabled state; Task B5 adds an optional `disabled` flag (used for the Autonomous switch and, in B7, the Battle and Shop tabs).
11. mini_games' times (`next_roll_at`, `faint_until`, `deadline`) are server epoch seconds. The roll cooldown and faint countdowns compare them with the device clock (no `seconds_left` exists for them; a cooldown 409 still explains itself). Only the EMBLEM prompt uses `seconds_left` on the monotonic clock, as the spec requires.
12. ember_api answers every error as `{"detail": ...}`; `apiRequest` already reads `detail`, so mini_games' message reaches the page unchanged.

## File Structure

| File | Part | Responsibility |
|---|---|---|
| `apps/Ember/ember_api/src/config.py` | A1 | `DEFAULT_EMBERLINGS_URL`, `Settings.emberlings_url`, read in `load_settings()` |
| `apps/Ember/ember_api/configs/config_app.json.example` | A1 | The new key with its default |
| `apps/Ember/ember_api/configs/README.md` | A1 | Row for `emberlings_url` |
| `apps/Ember/ember_api/src/services/config_validation.py` | A1 | Config issues page checks the key is an http(s) URL |
| `apps/Ember/ember_api/src/services/emberlings_gateway.py` | A2 | `EmberlingsGateway`, `EmberlingsApi` Protocol, `EmberlingsRefused`, `EmberlingsUnavailable`, route allow-list |
| `apps/Ember/ember_api/src/services/permissions.py` | A3 | `EMBERLINGS_PLAY` |
| `apps/Ember/ember_api/src/routes/emberlings.py` | A3 | Request models, id and key checks, every route, audit |
| `apps/Ember/ember_api/src/deps.py` | A3 | `get_emberlings` |
| `apps/Ember/ember_api/src/app.py` | A3 | `create_app(emberlings=...)`, lifespan wiring, router |
| `apps/Ember/ember_api/tests/conftest.py` | A3 | `FakeEmberlings`, `emberlings` fixture, passed by `client_factory` |
| `apps/Ember/ember_api/tests/test_config_issues.py` | A1 | Config key tests |
| `apps/Ember/ember_api/tests/test_emberlings_gateway.py` | A2 | Real gateway against `httpx.MockTransport` |
| `apps/Ember/ember_api/tests/test_emberlings.py` | A3 | Routes against `FakeEmberlings` |
| `apps/Ember/ember_api/tests/test_emberlings_proxy.py` | A4 | Routes with the real gateway: headers, no leaks |
| `apps/Ember/ember_api/README.md` | A4 | API table rows |
| `apps/Ember/ember_web/src/api/http.ts` | B1 | Optional extra headers |
| `apps/Ember/ember_web/src/api/EmberlingsClient.ts` | B1 | Types and `emberlingsClient` |
| `apps/Ember/ember_web/src/api/EmberlingsClient.fixtures.ts` | B1 | Shared test data (not a test file, never imported by app code) |
| `apps/Ember/ember_web/src/stores/emberlings.ts` | B2 | `useEmberlingsStore`: state, actions, battle loop |
| `apps/Ember/ember_web/src/utils/emberlings.ts` | B3 | Tier standing, words, countdown text, round-log lines |
| `apps/Ember/ember_web/src/composables/useNowSeconds.ts` | B3 | Ticking wall clock for countdowns |
| `apps/Ember/ember_web/src/components/emberlings/TierBadge.vue`, `SparkCard.vue`, `PresetEditor.vue`, `CollectionPanel.vue` | B3 | Collection tab |
| `apps/Ember/ember_web/src/components/emberlings/EncounterPanel.vue` | B4 | Look, preview, decline, start form |
| `apps/Ember/ember_web/src/components/SegmentedControl.vue` | B5 | Per-option `disabled` |
| `apps/Ember/ember_web/src/components/emberlings/HealthBar.vue`, `RoundLog.vue`, `BattleArena.vue`, `ActionBar.vue`, `EmblemPrompt.vue`, `BattleResult.vue` | B5 | Battle tab |
| `apps/Ember/ember_web/src/components/emberlings/ShopPanel.vue` | B6 | Shop tab |
| `apps/Ember/ember_web/src/views/EmberlingsView.vue` | B7 | The page: header, tabs, first-visit starter pick, unavailable state |
| `apps/Ember/ember_web/src/router/index.ts`, `src/router/pages.ts`, `src/App.vue` | B8 | Route, nav entry, KeepAlive |
| `apps/Ember/ember_web/e2e/fakeApi.ts`, `e2e/emberlings.spec.ts` | B9 | Playwright fake routes and one spec |
| `apps/Ember/ember_web/README.md`, `Brain/Projects/ember_web.md` | B9 | Docs |

`CollectionPanel.vue`, `EncounterPanel.vue` and `BattleResult.vue` are not in the spec's component list; they keep the view small and each carries its own tests. ember_admin needs no change: its role editor lists unknown permissions under "Other permissions".

---

# PART A: ember_api (may run continuously)

### Task A1: The `emberlings_url` config key

**Files:**
- Modify: `apps/Ember/ember_api/src/config.py`
- Modify: `apps/Ember/ember_api/configs/config_app.json.example`
- Modify: `apps/Ember/ember_api/configs/README.md`
- Modify: `apps/Ember/ember_api/src/services/config_validation.py:81`
- Test: `apps/Ember/ember_api/tests/test_config_issues.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `src.config.DEFAULT_EMBERLINGS_URL: str = "http://127.0.0.1:8060"`; `Settings.emberlings_url: str` (default `DEFAULT_EMBERLINGS_URL`).

- [ ] **Step 1: Write the failing tests**

Append to `apps/Ember/ember_api/tests/test_config_issues.py`:

```python
def test_emberlings_url_must_be_an_http_url(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    (tmp_path / "config_app.json").write_text(
        json.dumps({**GOOD_CONFIG, "emberlings_url": "ftp://games"}), encoding="utf-8"
    )

    assert ("config_app.json", "emberlings_url", "must be an http(s) URL") in issues(client)


def test_emberlings_url_is_optional(monkeypatch, tmp_path: Path) -> None:
    import src.config as config

    monkeypatch.setattr(config, "CONFIGS_DIR", tmp_path)
    (tmp_path / "config_app.json").write_text(json.dumps({}), encoding="utf-8")
    assert config.load_settings().emberlings_url == config.DEFAULT_EMBERLINGS_URL == "http://127.0.0.1:8060"

    (tmp_path / "config_app.json").write_text(json.dumps({"emberlings_url": "http://10.0.0.9:8060"}), encoding="utf-8")
    assert config.load_settings().emberlings_url == "http://10.0.0.9:8060"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_config_issues.py -q -k emberlings`
Expected: 2 failed (the issue is missing; `AttributeError: module 'src.config' has no attribute 'DEFAULT_EMBERLINGS_URL'`).

- [ ] **Step 3: Implement**

In `src/config.py`, below `LEGACY_SECRETS_DIR = PROJECT_DIR / "secrets"` add:

```python
# mini_games (the Emberlings game); a config without the key uses this.
DEFAULT_EMBERLINGS_URL = "http://127.0.0.1:8060"
```

In `class Settings`, directly below `mcp_server_url: str = "http://127.0.0.1:8010/mcp"` add:

```python
    # mini_games' root URL (the Emberlings game; its routes sit under /sparks).
    emberlings_url: str = DEFAULT_EMBERLINGS_URL
```

In `load_settings()`, directly below `mcp_server_url=raw.get("mcp_server_url") or "http://127.0.0.1:8010/mcp",` add:

```python
        emberlings_url=raw.get("emberlings_url") or DEFAULT_EMBERLINGS_URL,
```

In `src/services/config_validation.py`, in `_check_app`'s `rules`, directly below `("mcp_server_url", _is_http_url, "an http(s) URL"),` add:

```python
        ("emberlings_url", _is_http_url, "an http(s) URL"),
```

In `configs/config_app.json.example`, replace

```json
  "mcp_server_url": "http://127.0.0.1:8010/mcp",
```

with

```json
  "mcp_server_url": "http://127.0.0.1:8010/mcp",
  "emberlings_url": "http://127.0.0.1:8060",
```

In `configs/README.md`, directly below the row that starts with `| \`mcp_server_url\` |` add:

```markdown
| `emberlings_url` | Optional. mini_games' address (the Emberlings game), default `http://127.0.0.1:8060`. Called with `INTERNAL_API_TOKEN` from `.env`, so put the same token in mini_games' `.env`. The browser never sees this address. |
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_config_issues.py tests/test_backup.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src/config.py apps/Ember/ember_api/src/services/config_validation.py apps/Ember/ember_api/configs/config_app.json.example apps/Ember/ember_api/configs/README.md apps/Ember/ember_api/tests/test_config_issues.py
git commit -m "feat(ember-api): emberlings_url config key"
```

### Task A2: `EmberlingsGateway`

**Files:**
- Create: `apps/Ember/ember_api/src/services/emberlings_gateway.py`
- Test: `apps/Ember/ember_api/tests/test_emberlings_gateway.py`

**Interfaces:**
- Consumes: `src.models.Account` (uses `.id` only), `src.services.traffic.TrafficRecorder.timed(target, tool)`.
- Produces:
  - `TIMEOUT_SECONDS: float = 10.0`, `UNAVAILABLE_MESSAGE = "Emberlings is not available right now"`
  - `class EmberlingsUnavailable(Exception)`
  - `class EmberlingsRefused(Exception)` with `.status: int` and `str(error)` = mini_games' message
  - `class EmberlingsApi(Protocol)`: `async def request(self, method: str, path: str, account: Account, *, json: Any = None, params: dict[str, int | str] | None = None, idempotency_key: str | None = None) -> Any`
  - `class EmberlingsGateway(client: httpx.AsyncClient, base_url: str, internal_token: str | None, traffic: TrafficRecorder | None = None)` implementing `EmberlingsApi`
  - `def is_allowed(method: str, path: str) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `apps/Ember/ember_api/tests/test_emberlings_gateway.py`:

```python
"""EmberlingsGateway against a fake mini_games (httpx.MockTransport)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from src.models import Account
from src.services.emberlings_gateway import (
    TIMEOUT_SECONDS,
    EmberlingsGateway,
    EmberlingsRefused,
    EmberlingsUnavailable,
    is_allowed,
)
from src.services.traffic import TrafficRecorder

BASE = "http://games.internal:8060/"
ACCOUNT = cast(Account, SimpleNamespace(id=7, username="alice", email="alice@example.com"))

Handler = Callable[[httpx.Request], httpx.Response]


def call(handler: Handler, method: str, path: str, *, token: str | None = "tok", **kwargs: Any) -> tuple[Any, list[httpx.Request]]:
    """One gateway request against `handler`; returns the result and what was sent."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def run() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            return await EmberlingsGateway(client, BASE, token, TrafficRecorder()).request(method, path, ACCOUNT, **kwargs)

    return asyncio.run(run()), seen


def test_sends_the_owner_id_token_key_and_body() -> None:
    result, seen = call(
        lambda r: httpx.Response(200, json={"id": "b1"}),
        "POST",
        "/sparks/battles/b1/advance",
        json={"round": 1, "revision": 2},
        idempotency_key="key-1",
    )

    assert result == {"id": "b1"}
    sent = seen[0]
    assert str(sent.url) == "http://games.internal:8060/sparks/battles/b1/advance"
    # The account id, never the username: a renamed account keeps its Sparks.
    assert sent.headers["X-Requester-Username"] == "7"
    assert sent.headers["X-Internal-Token"] == "tok"
    assert sent.headers["Idempotency-Key"] == "key-1"
    assert "X-Requester-Email" not in sent.headers
    assert json.loads(sent.content) == {"round": 1, "revision": 2}
    assert sent.extensions["timeout"] == {
        "connect": TIMEOUT_SECONDS,
        "read": TIMEOUT_SECONDS,
        "write": TIMEOUT_SECONDS,
        "pool": TIMEOUT_SECONDS,
    }


def test_sends_a_query_and_leaves_out_headers_it_does_not_have() -> None:
    _, seen = call(
        lambda r: httpx.Response(200, json={"items": [], "next_cursor": None}),
        "GET",
        "/sparks/sparks/guardian/personalities",
        token=None,
        params={"limit": 10, "cursor": 5},
    )

    sent = seen[0]
    assert dict(sent.url.params) == {"limit": "10", "cursor": "5"}
    assert "X-Internal-Token" not in sent.headers
    assert "Idempotency-Key" not in sent.headers
    assert sent.content == b""


def test_no_content_is_none() -> None:
    result, _ = call(lambda r: httpx.Response(204), "GET", "/sparks/profile")

    assert result is None


@pytest.mark.parametrize("status", [400, 404, 409])
def test_refusals_keep_their_status_and_message(status: int) -> None:
    with pytest.raises(EmberlingsRefused) as raised:
        call(
            lambda r: httpx.Response(status, json={"error": "the battle moved on; reload it and try again"}),
            "POST",
            "/sparks/battles/b1/advance",
            json={"round": 1, "revision": 1},
            idempotency_key="k",
        )

    assert (raised.value.status, str(raised.value)) == (status, "the battle moved on; reload it and try again")


def test_a_fastapi_detail_is_read_and_other_client_errors_become_400() -> None:
    with pytest.raises(EmberlingsRefused) as raised:
        call(lambda r: httpx.Response(422, json={"detail": "bad body"}), "POST", "/sparks/profile", json={}, idempotency_key="k")

    assert (raised.value.status, str(raised.value)) == (400, "bad body")


def test_a_wrong_token_is_unavailable_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="src.services.emberlings_gateway"):
        with pytest.raises(EmberlingsUnavailable):
            call(lambda r: httpx.Response(401, json={"error": "Invalid or missing internal API token"}), "GET", "/sparks/catalog")

    assert "INTERNAL_API_TOKEN" in caplog.text


@pytest.mark.parametrize("response", [httpx.Response(500, json={"error": "boom"}), httpx.Response(200, text="not json")])
def test_server_errors_and_garbage_are_unavailable(response: httpx.Response) -> None:
    with pytest.raises(EmberlingsUnavailable):
        call(lambda r: response, "GET", "/sparks/catalog")


def test_no_connection_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(EmberlingsUnavailable):
        call(refuse, "GET", "/sparks/catalog")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/sparks/catalog"),
        ("POST", "/sparks/profile"),
        ("GET", "/sparks/profile"),
        ("GET", "/sparks/sparks/guardian/personalities"),
        ("GET", "/sparks/sparks/guardian/presets/1"),
        ("PUT", "/sparks/sparks/guardian/presets/5"),
        ("POST", "/sparks/encounters"),
        ("GET", "/sparks/encounters/Ab_c-1"),
        ("POST", "/sparks/encounters/Ab_c-1/decline"),
        ("POST", "/sparks/battles"),
        ("GET", "/sparks/battles/b1"),
        ("POST", "/sparks/battles/b1/actions"),
        ("POST", "/sparks/battles/b1/emblem"),
        ("POST", "/sparks/battles/b1/advance"),
        ("POST", "/sparks/battles/b1/mode"),
        ("POST", "/sparks/battles/b1/forfeit"),
        ("POST", "/sparks/shop/purchases"),
        ("POST", "/sparks/sparks/guardian/sales"),
    ],
)
def test_every_route_of_the_spec_is_allowed(method: str, path: str) -> None:
    assert is_allowed(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/sparks/admin"),
        ("DELETE", "/sparks/profile"),
        ("GET", "/sparks/battles/../profile"),
        ("POST", "/sparks/battles/b1/rewards"),
        ("GET", "/sparks/sparks/guardian/presets/9"),
        ("GET", "/health"),
    ],
)
def test_nothing_else_is_reachable(method: str, path: str) -> None:
    assert not is_allowed(method, path)
    with pytest.raises(ValueError):
        call(lambda r: httpx.Response(200, json={}), method, path)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_emberlings_gateway.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'src.services.emberlings_gateway'`.

- [ ] **Step 3: Implement**

Create `apps/Ember/ember_api/src/services/emberlings_gateway.py`:

```python
"""ember_api's client for apps/mini_games (the Emberlings game).

Only the fixed routes in _ROUTES are reachable; the browser never names a URL.
Every call carries the owner (the account id as text, never the username: an
administrator can rename an account, and its Sparks must not stay behind with
the old name), the internal token when one is configured, and the
Idempotency-Key of a change. Headers are built here only, so nothing the
browser sent is ever forwarded.

mini_games' own refusals (400, 404, 409) keep their status and message, which
is safe to show; any other 4xx becomes a 400. A token mismatch (401), a server
error, a body that is not JSON or no answer at all make Emberlings
"unavailable" (the routes answer 502)."""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

import httpx

from src.models import Account
from src.services.traffic import TrafficRecorder

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
UNAVAILABLE_MESSAGE = "Emberlings is not available right now"
_PASSED_THROUGH = (400, 404, 409)
# mini_games' ids: server-made tokens and catalog ids.
_ID = r"[A-Za-z0-9_-]{1,64}"
_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(pattern))
    for method, pattern in (
        ("GET", r"/sparks/catalog"),
        ("GET", r"/sparks/profile"),
        ("POST", r"/sparks/profile"),
        ("GET", rf"/sparks/sparks/{_ID}/personalities"),
        ("GET", rf"/sparks/sparks/{_ID}/presets/[1-5]"),
        ("PUT", rf"/sparks/sparks/{_ID}/presets/[1-5]"),
        ("POST", r"/sparks/encounters"),
        ("GET", rf"/sparks/encounters/{_ID}"),
        ("POST", rf"/sparks/encounters/{_ID}/decline"),
        ("POST", r"/sparks/battles"),
        ("GET", rf"/sparks/battles/{_ID}"),
        ("POST", rf"/sparks/battles/{_ID}/(?:actions|emblem|advance|mode|forfeit)"),
        ("POST", r"/sparks/shop/purchases"),
        ("POST", rf"/sparks/sparks/{_ID}/sales"),
    )
)
# Path words kept in traffic counter names; everything else (ids, slots) becomes {id}.
_WORDS = frozenset(
    "sparks catalog profile personalities presets encounters decline battles actions emblem advance mode "
    "forfeit shop purchases sales".split()
)


class EmberlingsUnavailable(Exception):
    """mini_games could not be used (maps to 502)."""


class EmberlingsRefused(Exception):
    """mini_games refused the request; the message is its own and safe to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class EmberlingsApi(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        account: Account,
        *,
        json: Any = None,
        params: dict[str, int | str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any: ...


def is_allowed(method: str, path: str) -> bool:
    return any(method == allowed and pattern.fullmatch(path) for allowed, pattern in _ROUTES)


def _message(body: Any, status: int) -> str:
    if isinstance(body, dict):
        for field in ("error", "detail"):
            value = body.get(field)
            if isinstance(value, str) and value:
                return value
    return f"Emberlings answered {status}"


def _traffic_name(method: str, path: str) -> str:
    """"POST /sparks/battles/abc/advance" -> "POST /sparks/battles/{id}/advance"."""
    return f"{method} /" + "/".join(part if part in _WORDS else "{id}" for part in path.strip("/").split("/"))


class EmberlingsGateway:
    def __init__(
        self, client: httpx.AsyncClient, base_url: str, internal_token: str | None, traffic: TrafficRecorder | None = None
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._internal_token = internal_token
        self._traffic = traffic or TrafficRecorder()

    def _headers(self, account: Account, idempotency_key: str | None) -> dict[str, str]:
        headers = {"X-Requester-Username": str(account.id)}
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def request(
        self,
        method: str,
        path: str,
        account: Account,
        *,
        json: Any = None,
        params: dict[str, int | str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        if not is_allowed(method, path):
            raise ValueError(f"not an Emberlings route: {method} {path}")
        try:
            with self._traffic.timed("mini_games", _traffic_name(method, path)) as timing:
                response = await self._client.request(
                    method,
                    f"{self._base}{path}",
                    json=json,
                    params=params,
                    headers=self._headers(account, idempotency_key),
                    timeout=TIMEOUT_SECONDS,
                )
                timing.ok = response.status_code < 500
        except httpx.HTTPError as error:
            logger.warning("mini_games %s %s unreachable: %s", method, path, error)
            raise EmberlingsUnavailable(str(error)) from error
        status = response.status_code
        if status == 204:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if status == 401:
            logger.warning(
                "mini_games refused ember_api's internal token: INTERNAL_API_TOKEN differs between the two .env files"
            )
            raise EmberlingsUnavailable("mini_games refused the internal token")
        if status in _PASSED_THROUGH:
            raise EmberlingsRefused(status, _message(body, status))
        if 400 <= status < 500:
            raise EmberlingsRefused(400, _message(body, status))
        if status >= 500 or body is None:
            raise EmberlingsUnavailable(f"mini_games answered {status}")
        return body
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_emberlings_gateway.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/src/services/emberlings_gateway.py apps/Ember/ember_api/tests/test_emberlings_gateway.py
git commit -m "feat(ember-api): EmberlingsGateway for mini_games"
```

### Task A3: Permission, routes, audit and app wiring

**Files:**
- Modify: `apps/Ember/ember_api/src/services/permissions.py`
- Create: `apps/Ember/ember_api/src/routes/emberlings.py`
- Modify: `apps/Ember/ember_api/src/deps.py`
- Modify: `apps/Ember/ember_api/src/app.py`
- Modify: `apps/Ember/ember_api/tests/conftest.py`
- Test: `apps/Ember/ember_api/tests/test_emberlings.py`

**Interfaces:**
- Consumes: from A2 `EmberlingsApi`, `EmberlingsGateway(client, base_url, internal_token, traffic)`, `EmberlingsRefused(status, message)`, `EmberlingsUnavailable`, `UNAVAILABLE_MESSAGE`; from A1 `Settings.emberlings_url`.
- Produces:
  - `src.services.permissions.EMBERLINGS_PLAY = "emberlings.play"`
  - `src.deps.get_emberlings(request) -> EmberlingsApi`
  - `create_app(..., emberlings: EmberlingsApi | None = None)`; `app.state.emberlings`
  - `tests.conftest.FakeEmberlings` (fields `calls: list[dict]`, `responses: dict[tuple[str, str], Any]`, `refuse: tuple[int, str] | None`, `unavailable: bool`) and fixture `emberlings`; each recorded call is `{"method", "path", "owner", "json", "params", "key"}`
  - The HTTP routes in the table under Step 3 (the browser contract Part B uses).

- [ ] **Step 1: Add the fake and the permission constant the tests import**

In `tests/conftest.py`, below `from src.services.email_service import EmailDeliveryError` add:

```python
from src.services.emberlings_gateway import EmberlingsRefused, EmberlingsUnavailable
```

Below the `FakeServerTools` class add:

```python
@dataclass
class FakeEmberlings:
    """Stands in for mini_games behind EmberlingsGateway. Records every call;
    `responses` maps (method, path) to a reply (default {"ok": True});
    `refuse` raises EmberlingsRefused(status, message) and `unavailable`
    raises EmberlingsUnavailable."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
    refuse: tuple[int, str] | None = None
    unavailable: bool = False

    async def request(self, method, path, account, *, json=None, params=None, idempotency_key=None):
        self.calls.append(
            {"method": method, "path": path, "owner": str(account.id), "json": json, "params": params, "key": idempotency_key}
        )
        if self.unavailable:
            raise EmberlingsUnavailable("connection refused (fake)")
        if self.refuse is not None:
            raise EmberlingsRefused(*self.refuse)
        return self.responses.get((method, path), {"ok": True})
```

Below the `server_tools` fixture add:

```python
@pytest.fixture
def emberlings() -> FakeEmberlings:
    return FakeEmberlings()
```

In `client_factory`, add `emberlings: FakeEmberlings,` to its parameters (after `traffic: TrafficRecorder,`) and `emberlings=emberlings,` to the `create_app(...)` call (after `traffic=traffic,`).

In `src/services/permissions.py`, below `AGENTS_MANAGE = "agents.manage"` add `EMBERLINGS_PLAY = "emberlings.play"`, and in `ALL_PERMISSIONS`, below the `AGENTS_MANAGE: ...` entry, add:

```python
    EMBERLINGS_PLAY: "Play Emberlings",
```

- [ ] **Step 2: Write the failing route tests**

Create `apps/Ember/ember_api/tests/test_emberlings.py`:

```python
"""/api/emberlings against FakeEmberlings: permission, validation, pass-through, audit."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.services.emberlings_gateway import UNAVAILABLE_MESSAGE
from tests.conftest import FakeEmailSender, FakeEmberlings
from tests.test_admin import login, make_member, role_by_name
from tests.test_registration import as_admin

KEY = {"Idempotency-Key": "key-1"}
ROUND = {"round": 1, "revision": 2}
START = {"encounter_id": "enc_1", "spark_id": "guardian", "preset_slot": 1, "mode": "autonomous", "emblem_limit": "rare"}

# (ember_api path, mini_games path, forwarded query)
READS = [
    ("/api/emberlings/catalog", "/sparks/catalog", None),
    ("/api/emberlings/profile", "/sparks/profile", None),
    (
        "/api/emberlings/sparks/guardian/personalities?limit=10&cursor=5",
        "/sparks/sparks/guardian/personalities",
        {"limit": 10, "cursor": 5},
    ),
    ("/api/emberlings/sparks/guardian/personalities", "/sparks/sparks/guardian/personalities", None),
    ("/api/emberlings/sparks/guardian/presets/2", "/sparks/sparks/guardian/presets/2", None),
    ("/api/emberlings/encounters/enc_1", "/sparks/encounters/enc_1", None),
    ("/api/emberlings/battles/bat-1", "/sparks/battles/bat-1", None),
]

ACTION = {**ROUND, "action": {"kind": "ability", "ability_id": "guardian_bulwark"}}
# (method, ember_api path, body sent, mini_games path, body forwarded, status)
MUTATIONS: list[tuple[str, str, dict[str, Any], str, Any, int]] = [
    ("POST", "/api/emberlings/profile", {"starter_spark_id": "guardian"}, "/sparks/profile", {"starter_spark_id": "guardian"}, 201),
    (
        "PUT",
        "/api/emberlings/sparks/guardian/presets/1",
        {"instance_ids": ["p1", "p2"]},
        "/sparks/sparks/guardian/presets/1",
        {"instance_ids": ["p1", "p2"]},
        200,
    ),
    ("POST", "/api/emberlings/encounters", {}, "/sparks/encounters", None, 201),
    ("POST", "/api/emberlings/encounters/enc_1/decline", {}, "/sparks/encounters/enc_1/decline", None, 200),
    ("POST", "/api/emberlings/battles", START, "/sparks/battles", START, 201),
    ("POST", "/api/emberlings/battles/b1/actions", ACTION, "/sparks/battles/b1/actions", ACTION, 200),
    ("POST", "/api/emberlings/battles/b1/emblem", {**ROUND, "tier": "normal"}, "/sparks/battles/b1/emblem", {**ROUND, "tier": "normal"}, 200),
    ("POST", "/api/emberlings/battles/b1/advance", ROUND, "/sparks/battles/b1/advance", ROUND, 200),
    ("POST", "/api/emberlings/battles/b1/mode", {**ROUND, "mode": "manual"}, "/sparks/battles/b1/mode", {**ROUND, "mode": "manual"}, 200),
    ("POST", "/api/emberlings/battles/b1/forfeit", {}, "/sparks/battles/b1/forfeit", None, 200),
    (
        "POST",
        "/api/emberlings/shop/purchases",
        {"kind": "emblem", "tier": "normal", "quantity": 2},
        "/sparks/shop/purchases",
        {"kind": "emblem", "tier": "normal", "quantity": 2},
        201,
    ),
    (
        "POST",
        "/api/emberlings/shop/purchases",
        {"kind": "copies", "tier": "rare", "spark_id": "bruiser"},
        "/sparks/shop/purchases",
        {"kind": "copies", "tier": "rare", "quantity": 1, "spark_id": "bruiser"},
        201,
    ),
    ("POST", "/api/emberlings/sparks/guardian/sales", {}, "/sparks/sparks/guardian/sales", None, 201),
]


def my_id(client: TestClient) -> int:
    return client.get("/api/auth/me").json()["id"]


# --- pass-through ---------------------------------------------------------------


@pytest.mark.parametrize(("path", "upstream_path", "params"), READS)
def test_reads_are_passed_through(client: TestClient, emberlings: FakeEmberlings, path, upstream_path, params) -> None:
    as_admin(client)

    response = client.get(path)

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    assert emberlings.calls == [
        {"method": "GET", "path": upstream_path, "owner": str(my_id(client)), "json": None, "params": params, "key": None}
    ]


@pytest.mark.parametrize(("method", "path", "body", "upstream_path", "forwarded", "status"), MUTATIONS)
def test_changes_are_passed_through_with_their_key(
    client: TestClient, emberlings: FakeEmberlings, method, path, body, upstream_path, forwarded, status
) -> None:
    as_admin(client)

    response = client.request(method, path, json=body, headers=KEY)

    assert response.status_code == status, response.text
    assert emberlings.calls == [
        {"method": method, "path": upstream_path, "owner": str(my_id(client)), "json": forwarded, "params": None, "key": "key-1"}
    ]


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "no such battle"),
        (409, "the battle moved on; reload it and try again"),
        (400, "choose a starter from: guardian, scout, striker"),
    ],
)
def test_refusals_keep_their_status_and_message(client: TestClient, emberlings: FakeEmberlings, status, message) -> None:
    as_admin(client)
    emberlings.refuse = (status, message)

    response = client.post("/api/emberlings/battles/b1/advance", json=ROUND, headers=KEY)

    assert (response.status_code, response.json()["detail"]) == (status, message)


def test_unavailable_is_502(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)
    emberlings.unavailable = True

    response = client.get("/api/emberlings/profile")

    assert (response.status_code, response.json()["detail"]) == (502, UNAVAILABLE_MESSAGE)


# --- access ---------------------------------------------------------------------


def test_logged_out_is_401_before_anything_else(client: TestClient, emberlings: FakeEmberlings) -> None:
    assert client.get("/api/emberlings/catalog").status_code == 401
    # No key either: the login check comes first.
    assert client.post("/api/emberlings/encounters", json={}).status_code == 401
    assert emberlings.calls == []


def test_needs_emberlings_play(client: TestClient, email: FakeEmailSender, emberlings: FakeEmberlings) -> None:
    make_member(client, email)
    login(client, "alice")

    assert client.get("/api/emberlings/profile").status_code == 403
    assert client.post("/api/emberlings/encounters", json={}, headers=KEY).status_code == 403
    assert emberlings.calls == []


def test_the_administrator_role_has_the_permission_and_member_does_not(client: TestClient) -> None:
    as_admin(client)

    assert "emberlings.play" in role_by_name(client, "Administrator")["permissions"]
    assert "emberlings.play" not in role_by_name(client, "Member")["permissions"]


# --- validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    "headers", [{}, {"Idempotency-Key": ""}, {"Idempotency-Key": "   "}, {"Idempotency-Key": "k" * 201}]
)
def test_a_change_needs_an_idempotency_key(client: TestClient, emberlings: FakeEmberlings, headers) -> None:
    as_admin(client)

    response = client.post("/api/emberlings/battles/b1/advance", json=ROUND, headers=headers)

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]
    assert emberlings.calls == []


def test_a_200_character_key_is_accepted(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)

    response = client.post("/api/emberlings/battles/b1/advance", json=ROUND, headers={"Idempotency-Key": "k" * 200})

    assert response.status_code == 200
    assert emberlings.calls[0]["key"] == "k" * 200


@pytest.mark.parametrize(
    ("path", "body", "word"),
    [
        ("/api/emberlings/battles/b1/advance", {**ROUND, "hp": 999}, "hp"),
        ("/api/emberlings/battles/b1/actions", {**ROUND, "action": {"kind": "attack", "damage": 50}}, "damage"),
        ("/api/emberlings/battles", {**START, "rewards": 1}, "rewards"),
        ("/api/emberlings/profile", {"starter_spark_id": "guardian", "owner": "bob"}, "owner"),
        ("/api/emberlings/battles/b1/advance", {"round": True, "revision": 2}, "round"),
        ("/api/emberlings/battles/b1/actions", {**ROUND, "action": {"kind": "steal"}}, "kind"),
        ("/api/emberlings/shop/purchases", {"kind": "copies", "tier": "rare"}, "spark_id"),
        ("/api/emberlings/shop/purchases", {"kind": "emblem", "tier": "normal", "quantity": 100}, "quantity"),
        ("/api/emberlings/battles", {**START, "spark_id": "../profile"}, "spark_id"),
    ],
)
def test_bad_bodies_are_400_and_never_forwarded(client: TestClient, emberlings: FakeEmberlings, path, body, word) -> None:
    as_admin(client)

    response = client.post(path, json=body, headers=KEY)

    assert response.status_code == 400, response.text
    assert word in response.json()["detail"]
    assert emberlings.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/emberlings/battles/bad.id"),
        ("GET", "/api/emberlings/encounters/" + "x" * 65),
        ("GET", "/api/emberlings/sparks/guardian/presets/9"),
        ("GET", "/api/emberlings/sparks/guardian/presets/one"),
        ("POST", "/api/emberlings/sparks/bad.spark/sales"),
        ("POST", "/api/emberlings/battles/bad.id/forfeit"),
    ],
)
def test_bad_ids_are_400(client: TestClient, emberlings: FakeEmberlings, method, path) -> None:
    as_admin(client)

    response = client.request(method, path, json={} if method == "POST" else None, headers=KEY)

    assert response.status_code == 400, response.text
    assert emberlings.calls == []


# --- audit ----------------------------------------------------------------------


def action_log(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/api/logs/action", params={"actor": str(my_id(client))})
    assert response.status_code == 200, response.text
    return [e for e in response.json() if e["source"].startswith("emberlings.")]


def test_only_changes_of_value_are_audited(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)
    emberlings.responses[("POST", "/sparks/battles")] = {"id": "b1", "wild": {"name": "Bruiser", "level": 4}}
    emberlings.responses[("POST", "/sparks/shop/purchases")] = {"kind": "emblems", "tier_id": "normal", "quantity": 2, "price": 20}
    emberlings.responses[("POST", "/sparks/sparks/guardian/sales")] = {"kind": "sale", "spark_id": "guardian", "value": 12}

    for method, path, body, *_ in MUTATIONS:
        assert client.request(method, path, json=body, headers=KEY).status_code < 300
    for path, *_ in READS:
        assert client.get(path).status_code == 200

    entries = action_log(client)
    assert sorted(e["source"] for e in entries) == [
        "emberlings.battle_forfeit",
        "emberlings.battle_start",
        "emberlings.profile_create",
        "emberlings.shop_buy",
        "emberlings.shop_buy",
        "emberlings.spark_sell",
    ]
    messages = {e["message"] for e in entries}
    assert "Started Emberlings with the starter 'guardian'" in messages
    assert "Started a battle against Bruiser (level 4)" in messages
    assert "Bought 2 normal EMBLEMs for 20 Insignia" in messages
    assert "Sold a guardian copy for 12 Insignia" in messages


def test_a_refused_change_is_not_audited(client: TestClient, emberlings: FakeEmberlings) -> None:
    as_admin(client)
    emberlings.refuse = (409, "that costs 40 Insignia and you have 3")

    assert client.post("/api/emberlings/shop/purchases", json={"kind": "emblem", "tier": "rare"}, headers=KEY).status_code == 409
    assert action_log(client) == []
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_emberlings.py -q`
Expected: failures with `TypeError: create_app() got an unexpected keyword argument 'emberlings'` (the fixture passes it already).

- [ ] **Step 4: Implement the routes**

The browser contract (ember_web Part B uses exactly these paths):

| ember_api route | mini_games route | Body / query | Key | Audit |
|---|---|---|---|---|
| `GET /api/emberlings/catalog` | `GET /sparks/catalog` | | | |
| `POST /api/emberlings/profile` | `POST /sparks/profile` | `{starter_spark_id}` | yes | `profile_create` |
| `GET /api/emberlings/profile` | `GET /sparks/profile` | | | |
| `GET /api/emberlings/sparks/{spark_id}/personalities` | same under `/sparks/sparks/...` | `?limit=1..100&cursor>=0` | | |
| `GET /api/emberlings/sparks/{spark_id}/presets/{slot}` | same | | | |
| `PUT /api/emberlings/sparks/{spark_id}/presets/{slot}` | same | `{instance_ids}` (at most 3) | yes | |
| `POST /api/emberlings/encounters` | `POST /sparks/encounters` | none | yes | |
| `GET /api/emberlings/encounters/{id}` | same | | | |
| `POST /api/emberlings/encounters/{id}/decline` | same | none | yes | |
| `POST /api/emberlings/battles` | same | `{encounter_id, spark_id, preset_slot?, mode, emblem_limit?}` | yes | `battle_start` |
| `GET /api/emberlings/battles/{id}` | same | | | |
| `POST /api/emberlings/battles/{id}/actions` | same | `{round, revision, action: {kind, ability_id?, emblem_tier?}}` | yes | |
| `POST /api/emberlings/battles/{id}/emblem` | same | `{round, revision, tier}` | yes | |
| `POST /api/emberlings/battles/{id}/advance` | same | `{round, revision}` | yes | |
| `POST /api/emberlings/battles/{id}/mode` | same | `{round, revision, mode, emblem_limit?}` | yes | |
| `POST /api/emberlings/battles/{id}/forfeit` | same | none | yes | `battle_forfeit` |
| `POST /api/emberlings/shop/purchases` | same | `{kind: "emblem", tier, quantity}` or `{kind: "copies", tier, spark_id}` | yes | `shop_buy` |
| `POST /api/emberlings/sparks/{spark_id}/sales` | same | none | yes | `spark_sell` |

Create `apps/Ember/ember_api/src/routes/emberlings.py`:

```python
"""/api/emberlings: the Emberlings game (apps/mini_games), passed through.

ember_api keeps no game data. It checks the session and emberlings.play,
validates every body against mini_games' own rules (unknown fields refused,
so a client can never send rewards, stats or an owner), requires an
Idempotency-Key on every change and forwards the call through the
EmberlingsGateway, which adds the owner (the account id as text) and the
internal token itself. Bad input is a 400 here and never reaches mini_games.

Changes of value (a new profile, a battle started or forfeited, a purchase,
a sale) are written to the activity log after they succeeded. Round actions
and advance are not: one line per round would flood the log, and mini_games
records every finished battle itself."""

from __future__ import annotations

import re
from collections.abc import Awaitable
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from src.deps import get_emberlings, get_log_writer, require_permission
from src.models import Account
from src.services.emberlings_gateway import UNAVAILABLE_MESSAGE, EmberlingsApi, EmberlingsRefused, EmberlingsUnavailable
from src.services.log_service import LogWriter
from src.services.permissions import EMBERLINGS_PLAY

router = APIRouter(prefix="/api/emberlings", tags=["emberlings"])
require_play = require_permission(EMBERLINGS_PLAY)

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_ID = re.compile(ID_PATTERN)
_SLOT = re.compile(r"^[1-5]$")
KEY_MAX = 200
PAGE_MAX = 100
EMBLEM_MAX = 99
PRESET_MAX = 3

Id = Annotated[str, Field(pattern=ID_PATTERN)]
Mode = Literal["manual", "autonomous"]
M = TypeVar("M", bound=BaseModel)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileIn(_In):
    starter_spark_id: Id


class PresetIn(_In):
    instance_ids: list[Id] = Field(max_length=PRESET_MAX)


class BattleStartIn(_In):
    encounter_id: Id
    spark_id: Id
    preset_slot: StrictInt | None = Field(default=None, ge=1, le=5)
    mode: Mode = "manual"
    emblem_limit: Id | None = None


class RoundIn(_In):
    round: StrictInt = Field(ge=0)
    revision: StrictInt = Field(ge=0)


class ActionChoiceIn(_In):
    kind: Literal["attack", "ability", "flee", "catch"]
    ability_id: Id | None = None
    emblem_tier: Id | None = None


class ActionIn(RoundIn):
    action: ActionChoiceIn


class EmblemIn(RoundIn):
    tier: Id


class ModeIn(RoundIn):
    mode: Mode
    emblem_limit: Id | None = None


class PurchaseIn(_In):
    kind: Literal["emblem", "copies"]
    tier: Id
    quantity: StrictInt = Field(default=1, ge=1, le=EMBLEM_MAX)
    spark_id: Id | None = None

    @model_validator(mode="after")
    def copies_name_a_spark(self) -> PurchaseIn:
        if self.kind == "copies" and self.spark_id is None:
            raise ValueError("copies need a spark_id")
        return self


def _parse(model: type[M], raw: Any) -> M:
    """A body checked here: a bad one is a 400 with a readable reason."""
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "body"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{where}: {first['msg']}") from error


def _id(value: str, what: str) -> str:
    if not _ID.fullmatch(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} is not a valid id")
    return value


def _slot(value: str) -> int:
    if not _SLOT.fullmatch(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "preset slot must be from 1 to 5")
    return int(value)


def idempotency_key(key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    value = (key or "").strip()
    if not 1 <= len(value) <= KEY_MAX:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"An Idempotency-Key header of 1 to {KEY_MAX} characters is required"
        )
    return value


async def _forward(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except EmberlingsUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE_MESSAGE) from error
    except EmberlingsRefused as error:
        raise HTTPException(error.status, str(error)) from error


def _field(result: Any, key: str, default: Any = "?") -> Any:
    return result.get(key, default) if isinstance(result, dict) else default


# --- reads ----------------------------------------------------------------------


@router.get("/catalog")
async def catalog(account: Account = Depends(require_play), game: EmberlingsApi = Depends(get_emberlings)) -> Any:
    return await _forward(game.request("GET", "/sparks/catalog", account))


@router.get("/profile")
async def get_profile(account: Account = Depends(require_play), game: EmberlingsApi = Depends(get_emberlings)) -> Any:
    return await _forward(game.request("GET", "/sparks/profile", account))


@router.get("/sparks/{spark_id}/personalities")
async def personalities(
    spark_id: str,
    limit: int | None = Query(default=None, ge=1, le=PAGE_MAX),
    cursor: int | None = Query(default=None, ge=0, le=2**63 - 1),
    account: Account = Depends(require_play),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    params = {name: value for name, value in (("limit", limit), ("cursor", cursor)) if value is not None}
    path = f"/sparks/sparks/{_id(spark_id, 'spark_id')}/personalities"
    return await _forward(game.request("GET", path, account, params=params or None))


@router.get("/sparks/{spark_id}/presets/{slot}")
async def get_preset(
    spark_id: str, slot: str, account: Account = Depends(require_play), game: EmberlingsApi = Depends(get_emberlings)
) -> Any:
    path = f"/sparks/sparks/{_id(spark_id, 'spark_id')}/presets/{_slot(slot)}"
    return await _forward(game.request("GET", path, account))


@router.get("/encounters/{encounter_id}")
async def get_encounter(
    encounter_id: str, account: Account = Depends(require_play), game: EmberlingsApi = Depends(get_emberlings)
) -> Any:
    return await _forward(game.request("GET", f"/sparks/encounters/{_id(encounter_id, 'encounter_id')}", account))


@router.get("/battles/{battle_id}")
async def get_battle(
    battle_id: str, account: Account = Depends(require_play), game: EmberlingsApi = Depends(get_emberlings)
) -> Any:
    return await _forward(game.request("GET", f"/sparks/battles/{_id(battle_id, 'battle_id')}", account))


# --- changes --------------------------------------------------------------------


@router.post("/profile", status_code=status.HTTP_201_CREATED)
async def create_profile(
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    body = _parse(ProfileIn, raw)
    result = await _forward(
        game.request("POST", "/sparks/profile", account, json=body.model_dump(exclude_none=True), idempotency_key=key)
    )
    await logs.action(account, "emberlings.profile_create", f"Started Emberlings with the starter '{body.starter_spark_id}'")
    return result


@router.put("/sparks/{spark_id}/presets/{slot}")
async def put_preset(
    spark_id: str,
    slot: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    path = f"/sparks/sparks/{_id(spark_id, 'spark_id')}/presets/{_slot(slot)}"
    body = _parse(PresetIn, raw)
    return await _forward(game.request("PUT", path, account, json=body.model_dump(exclude_none=True), idempotency_key=key))


@router.post("/encounters", status_code=status.HTTP_201_CREATED)
async def roll_encounter(
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    return await _forward(game.request("POST", "/sparks/encounters", account, idempotency_key=key))


@router.post("/encounters/{encounter_id}/decline")
async def decline_encounter(
    encounter_id: str,
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    path = f"/sparks/encounters/{_id(encounter_id, 'encounter_id')}/decline"
    return await _forward(game.request("POST", path, account, idempotency_key=key))


@router.post("/battles", status_code=status.HTTP_201_CREATED)
async def start_battle(
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    body = _parse(BattleStartIn, raw)
    result = await _forward(
        game.request("POST", "/sparks/battles", account, json=body.model_dump(exclude_none=True), idempotency_key=key)
    )
    wild = _field(result, "wild", {})
    await logs.action(
        account,
        "emberlings.battle_start",
        f"Started a battle against {_field(wild, 'name', 'a wild Spark')} (level {_field(wild, 'level')})",
    )
    return result


async def _round_change(
    battle_id: str, verb: str, model: type[RoundIn], raw: Any, account: Account, key: str, game: EmberlingsApi
) -> Any:
    path = f"/sparks/battles/{_id(battle_id, 'battle_id')}/{verb}"
    body = _parse(model, raw)
    return await _forward(game.request("POST", path, account, json=body.model_dump(exclude_none=True), idempotency_key=key))


@router.post("/battles/{battle_id}/actions")
async def submit_action(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    return await _round_change(battle_id, "actions", ActionIn, raw, account, key, game)


@router.post("/battles/{battle_id}/emblem")
async def answer_emblem(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    return await _round_change(battle_id, "emblem", EmblemIn, raw, account, key, game)


@router.post("/battles/{battle_id}/advance")
async def advance_battle(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    return await _round_change(battle_id, "advance", RoundIn, raw, account, key, game)


@router.post("/battles/{battle_id}/mode")
async def set_mode(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
) -> Any:
    return await _round_change(battle_id, "mode", ModeIn, raw, account, key, game)


@router.post("/battles/{battle_id}/forfeit")
async def forfeit(
    battle_id: str,
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    path = f"/sparks/battles/{_id(battle_id, 'battle_id')}/forfeit"
    result = await _forward(game.request("POST", path, account, idempotency_key=key))
    await logs.action(account, "emberlings.battle_forfeit", f"Forfeited battle {battle_id}")
    return result


@router.post("/shop/purchases", status_code=status.HTTP_201_CREATED)
async def purchase(
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    body = _parse(PurchaseIn, raw)
    result = await _forward(
        game.request("POST", "/sparks/shop/purchases", account, json=body.model_dump(exclude_none=True), idempotency_key=key)
    )
    if body.kind == "emblem":
        message = (
            f"Bought {_field(result, 'quantity', body.quantity)} {body.tier} EMBLEMs "
            f"for {_field(result, 'price')} Insignia"
        )
    else:
        message = (
            f"Bought {_field(result, 'copies_granted')} {body.spark_id} copies ({body.tier}) "
            f"for {_field(result, 'price')} Insignia"
        )
    await logs.action(account, "emberlings.shop_buy", message)
    return result


@router.post("/sparks/{spark_id}/sales", status_code=status.HTTP_201_CREATED)
async def sell_copy(
    spark_id: str,
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: EmberlingsApi = Depends(get_emberlings),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    spark = _id(spark_id, "spark_id")
    result = await _forward(game.request("POST", f"/sparks/sparks/{spark}/sales", account, idempotency_key=key))
    await logs.action(account, "emberlings.spark_sell", f"Sold a {spark} copy for {_field(result, 'value')} Insignia")
    return result
```

- [ ] **Step 5: Wire it into the app**

In `src/deps.py`, below `from src.services.email_service import EmailSender` add:

```python
from src.services.emberlings_gateway import EmberlingsApi
```

and below `def get_server_tools(...)` add:

```python
def get_emberlings(request: Request) -> EmberlingsApi:
    return request.app.state.emberlings
```

In `src/app.py`:

1. In the `from src.routes import (...)` block replace

```python
    config_issues,
    logs,
```

with

```python
    config_issues,
    emberlings as emberlings_routes,
    logs,
```

2. Below `from src.services.email_service import EmailSender, McpEmailSender` add:

```python
from src.services.emberlings_gateway import EmberlingsApi, EmberlingsGateway
```

3. In the `create_app` signature replace

```python
    traffic: TrafficRecorder | None = None,
) -> FastAPI:
```

with

```python
    traffic: TrafficRecorder | None = None,
    emberlings: EmberlingsApi | None = None,
) -> FastAPI:
```

and in its docstring replace `defaults to a recorder saving to the database; tests pass their own."""` with:

```python
    defaults to a recorder saving to the database; tests pass their own.
    emberlings defaults to an HTTP client for mini_games (the Emberlings game)."""
```

4. In the lifespan, directly below the line `app.state.server_tools = server_tools or McpServerTools(settings.mcp_server_url, internal_token or None, recorder)` add:

```python
        app.state.emberlings = emberlings or EmberlingsGateway(
            upstream, settings.emberlings_url, internal_token or None, recorder
        )
```

5. Below `app.include_router(config_issues.router)` add:

```python
    app.include_router(emberlings_routes.router)
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_emberlings.py tests/test_admin.py -q`
Expected: all passed. (`test_admin.py` checks the Administrator role holds every permission, now including `emberlings.play`.)

- [ ] **Step 7: Commit**

```bash
git add apps/Ember/ember_api/src/services/permissions.py apps/Ember/ember_api/src/routes/emberlings.py apps/Ember/ember_api/src/deps.py apps/Ember/ember_api/src/app.py apps/Ember/ember_api/tests/conftest.py apps/Ember/ember_api/tests/test_emberlings.py
git commit -m "feat(ember-api): /api/emberlings pass-through with emberlings.play"
```

### Task A4: End-to-end proxy checks and the API table

**Files:**
- Test: `apps/Ember/ember_api/tests/test_emberlings_proxy.py`
- Modify: `apps/Ember/ember_api/README.md` (API table)

**Interfaces:**
- Consumes: `create_app(...)` without `emberlings=` (so the real `EmberlingsGateway` runs over the `upstream_transport`), `make_settings(tmp_path, internal_token=...)`, `FakeUpstream`, `DEFAULT_EMBERLINGS_URL`.
- Produces: nothing new in code.

- [ ] **Step 1: Write the tests**

Create `apps/Ember/ember_api/tests/test_emberlings_proxy.py`:

```python
"""The real EmberlingsGateway behind /api/emberlings, talking to a fake
mini_games: what actually leaves ember_api, and what never reaches the browser."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import DEFAULT_EMBERLINGS_URL
from src.services.traffic import TrafficRecorder
from tests.conftest import FakeAgent, FakeEmailSender, FakeServerTools, FakeUpstream, make_settings
from tests.test_registration import as_admin

TOKEN = "shared-secret"


@pytest.fixture
def real_client(
    tmp_path: Path,
    email: FakeEmailSender,
    upstream: FakeUpstream,
    agent: FakeAgent,
    server_tools: FakeServerTools,
    traffic: TrafficRecorder,
) -> Iterator[TestClient]:
    app = create_app(
        make_settings(tmp_path, internal_token=TOKEN),
        email_sender=email,
        upstream_transport=httpx.MockTransport(upstream),
        agent_gateway=agent,
        server_tools=server_tools,
        traffic=traffic,
    )
    with TestClient(app) as client:
        yield client


def games(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "b1", "status": "active"})


def sent_to_games(upstream: FakeUpstream) -> list[httpx.Request]:
    return [r for r in upstream.requests if str(r.url).startswith(DEFAULT_EMBERLINGS_URL)]


def test_owner_and_token_come_from_ember_api_not_the_browser(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = games
    as_admin(real_client)
    me = real_client.get("/api/auth/me").json()

    response = real_client.post(
        "/api/emberlings/battles/b1/advance",
        json={"round": 1, "revision": 2},
        headers={
            "Idempotency-Key": "key-1",
            "X-Requester-Username": "mallory",
            "X-Requester-Email": "mallory@evil.example",
            "X-Internal-Token": "guess",
        },
    )

    assert response.status_code == 200, response.text
    [sent] = sent_to_games(upstream)
    assert str(sent.url) == f"{DEFAULT_EMBERLINGS_URL}/sparks/battles/b1/advance"
    assert sent.headers["X-Requester-Username"] == str(me["id"]) != me["username"]
    assert sent.headers["X-Internal-Token"] == TOKEN
    assert sent.headers["Idempotency-Key"] == "key-1"
    assert "X-Requester-Email" not in sent.headers
    assert json.loads(sent.content) == {"round": 1, "revision": 2}


def test_a_token_mismatch_shows_neither_address_nor_token(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda r: httpx.Response(401, json={"error": "Invalid or missing internal API token"})
    as_admin(real_client)

    response = real_client.get("/api/emberlings/catalog")

    assert response.status_code == 502
    assert response.json() == {"detail": "Emberlings is not available right now"}
    assert "8060" not in response.text and TOKEN not in response.text


def test_mini_games_down_is_502(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.unreachable = True
    as_admin(real_client)

    assert real_client.get("/api/emberlings/profile").status_code == 502


def test_a_refusal_reaches_the_browser_as_detail(real_client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda r: httpx.Response(409, json={"error": "a new encounter can be rolled in 12 seconds", "retry_after": 12})
    as_admin(real_client)

    response = real_client.post("/api/emberlings/encounters", json={}, headers={"Idempotency-Key": "k"})

    assert (response.status_code, response.json()) == (409, {"detail": "a new encounter can be rolled in 12 seconds"})
```

- [ ] **Step 2: Run them**

Run: `.venv_ember_api/Scripts/python -m pytest tests/test_emberlings_proxy.py -q`
Expected: all passed (the behavior was built in A2 and A3; these tests pin it at the HTTP boundary). If one fails, fix the gateway or route, not the test.

- [ ] **Step 3: Document the routes**

In `apps/Ember/ember_api/README.md`, directly above the row that starts with ``| `GET` `POST` `DELETE` | `/api/mcp/agents/{agent_id}` |`` insert:

```markdown
| `GET` | `/api/emberlings/catalog`, `/api/emberlings/profile`, `/api/emberlings/encounters/{id}`, `/api/emberlings/battles/{id}`, `/api/emberlings/sparks/{spark_id}/presets/{slot}`, `/api/emberlings/sparks/{spark_id}/personalities?limit=&cursor=` | `emberlings.play` | The Emberlings game (`apps/mini_games`, `emberlings_url` in config), passed through with mini_games' own JSON. `GET /profile` is `404` until a starter is chosen. Ids are 1 to 64 of `A-Za-z0-9_-` and a slot is 1 to 5, else `400`. |
| `POST` | `/api/emberlings/profile` `{starter_spark_id}`, `/encounters`, `/encounters/{id}/decline`, `/battles` `{encounter_id, spark_id, preset_slot?, mode, emblem_limit?}`, `/battles/{id}/actions` `{round, revision, action}`, `/battles/{id}/emblem` `{round, revision, tier}`, `/battles/{id}/advance` `{round, revision}`, `/battles/{id}/mode` `{round, revision, mode, emblem_limit?}`, `/battles/{id}/forfeit`, `/shop/purchases` `{kind: "emblem", tier, quantity}` or `{kind: "copies", tier, spark_id}`, `/sparks/{spark_id}/sales`; `PUT` `/sparks/{spark_id}/presets/{slot}` `{instance_ids}` | `emberlings.play` | Every change needs an `Idempotency-Key` header of 1 to 200 characters (`400` without; a retry with the same key returns the first result). Bodies reject unknown fields (`400`). mini_games' `400`/`404`/`409` come back with its message as `detail`; mini_games down, failing or refusing the internal token is `502` "Emberlings is not available right now". The owner sent upstream is the account id, never the username; browser-sent identity headers are dropped. Logged: `emberlings.profile_create`, `battle_start`, `battle_forfeit`, `shop_buy`, `spark_sell` (round actions are not). |
```

- [ ] **Step 4: Run the whole ember_api suite**

Run: `.venv_ember_api/Scripts/python -m pytest -q`
Expected: all passed, including `tests/test_migrations.py` (no model changed, so no migration is expected).

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_api/tests/test_emberlings_proxy.py apps/Ember/ember_api/README.md
git commit -m "test(ember-api): emberlings proxy headers and docs"
```

Part A is done. Report to the user before Part B: the routes, that `emberlings.play` is on Administrator only and must be granted to Member from the roles page in ember_admin, and that mini_games' `.env` needs the same `INTERNAL_API_TOKEN`.

---

# PART B: ember_web (stop before each task: propose, wait for approval, then implement)

The tasks are ordered so that nothing is written twice: the client, then the store, then the pieces of each tab with their own tests, then the page that puts them together, then the route that opens it. The page becomes reachable in the browser at Task B8.

### Task B1: `EmberlingsClient.ts`, its types and extra headers in `apiRequest`

**Files:**
- Modify: `apps/Ember/ember_web/src/api/http.ts`
- Create: `apps/Ember/ember_web/src/api/EmberlingsClient.ts`
- Create: `apps/Ember/ember_web/src/api/EmberlingsClient.fixtures.ts`
- Test: `apps/Ember/ember_web/src/api/http.test.ts`, `apps/Ember/ember_web/src/api/EmberlingsClient.test.ts`

**Interfaces:**
- Consumes: the ember_api routes of Task A3.
- Produces:
  - `apiRequest<T>(method, path, body?, headers?: Record<string, string>)`
  - Types: `BattleMode`, `ActionKind`, `ResultKind`, `Side`, `TierInfo`, `AbilityInfo`, `SparkInfo`, `Catalog`, `OwnedSpark`, `Profile`, `PersonalityItem`, `PersonalityPage`, `Preset`, `EncounterPreview`, `Buff`, `DefenseEffect`, `FighterAbility`, `Fighter`, `LegalAction`, `EmblemPromptState`, `BattleEvent`, `HistoryRound`, `RevealedPersonality`, `BattleResult`, `BattleView`, `RoundRef`, `ActionChoice`, `StartBattleInput`, `EmblemPurchase`, `CopyPurchase`, `Sale`
  - `newIdempotencyKey(): string`
  - `emberlingsClient`: `catalog()`, `profile()`, `createProfile(starterSparkId, key?)`, `personalities(sparkId, cursor = null, limit?)`, `preset(sparkId, slot)`, `savePreset(sparkId, slot, instanceIds, key?)`, `rollEncounter(key?)`, `encounter(id)`, `declineEncounter(id, key?)`, `startBattle(input, key?)`, `battle(id)`, `action(id, at: RoundRef, choice: ActionChoice, key?)`, `emblem(id, at, tier, key?)`, `advance(id, at, key?)`, `setMode(id, at, mode, emblemLimit: string | null, key?)`, `forfeit(id, key?)`, `buyEmblems(tier, quantity, key?)`, `buyCopies(sparkId, tier, key?)`, `sellCopy(sparkId, key?)`
  - Fixtures: `tier()`, `sparkInfo()`, `CATALOG`, `ownedSpark()`, `PROFILE`, `ENCOUNTER`, `fighter()`, `battleView()`, `ACCOUNT_WITH_EMBERLINGS`

- [ ] **Step 1: Write the failing tests**

Create `apps/Ember/ember_web/src/api/http.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";

const ok = () => ({ status: 200, ok: true, statusText: "OK", json: async () => ({ ok: true }) }) as unknown as Response;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("sends extra headers beside the JSON content type", async () => {
    const fetchMock = vi.fn(async (_path: string, _init: RequestInit) => ok());
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("POST", "/api/emberlings/encounters", undefined, { "Idempotency-Key": "k-1" });

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/emberlings/encounters", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Idempotency-Key": "k-1", "Content-Type": "application/json" },
      body: "{}",
    });
  });

  it("sends no headers and no body on a plain GET", async () => {
    const fetchMock = vi.fn(async (_path: string, _init: RequestInit) => ok());
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("GET", "/api/emberlings/catalog");

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/emberlings/catalog", { method: "GET", credentials: "same-origin" });
  });
});
```

Create `apps/Ember/ember_web/src/api/EmberlingsClient.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, newIdempotencyKey } from "./EmberlingsClient";
import { apiRequest } from "./http";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);
const KEY = { "Idempotency-Key": "k" };
const AT = { round: 3, revision: 7 };

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("emberlingsClient", () => {
  it("reads without a key and escapes ids", async () => {
    await emberlingsClient.catalog();
    await emberlingsClient.profile();
    await emberlingsClient.encounter("e 1");
    await emberlingsClient.battle("b1");
    await emberlingsClient.preset("guardian", 2);
    await emberlingsClient.personalities("guardian");
    await emberlingsClient.personalities("guardian", 40, 50);

    expect(request.mock.calls).toEqual([
      ["GET", "/api/emberlings/catalog"],
      ["GET", "/api/emberlings/profile"],
      ["GET", "/api/emberlings/encounters/e%201"],
      ["GET", "/api/emberlings/battles/b1"],
      ["GET", "/api/emberlings/sparks/guardian/presets/2"],
      ["GET", "/api/emberlings/sparks/guardian/personalities"],
      ["GET", "/api/emberlings/sparks/guardian/personalities?limit=50&cursor=40"],
    ]);
  });

  it("sends every change with the key it is given", async () => {
    await emberlingsClient.createProfile("guardian", "k");
    await emberlingsClient.savePreset("guardian", 1, ["p1"], "k");
    await emberlingsClient.rollEncounter("k");
    await emberlingsClient.declineEncounter("e1", "k");
    await emberlingsClient.startBattle({ encounter_id: "e1", spark_id: "guardian", preset_slot: null, mode: "manual", emblem_limit: null }, "k");
    await emberlingsClient.action("b1", AT, { kind: "ability", ability_id: "guardian_strike" }, "k");
    await emberlingsClient.emblem("b1", AT, "rare", "k");
    await emberlingsClient.advance("b1", AT, "k");
    await emberlingsClient.setMode("b1", AT, "autonomous", null, "k");
    await emberlingsClient.setMode("b1", AT, "autonomous", "rare", "k");
    await emberlingsClient.forfeit("b1", "k");
    await emberlingsClient.buyEmblems("normal", 3, "k");
    await emberlingsClient.buyCopies("bruiser", "rare", "k");
    await emberlingsClient.sellCopy("guardian", "k");

    expect(request.mock.calls).toEqual([
      ["POST", "/api/emberlings/profile", { starter_spark_id: "guardian" }, KEY],
      ["PUT", "/api/emberlings/sparks/guardian/presets/1", { instance_ids: ["p1"] }, KEY],
      ["POST", "/api/emberlings/encounters", undefined, KEY],
      ["POST", "/api/emberlings/encounters/e1/decline", undefined, KEY],
      ["POST", "/api/emberlings/battles", { encounter_id: "e1", spark_id: "guardian", preset_slot: null, mode: "manual", emblem_limit: null }, KEY],
      ["POST", "/api/emberlings/battles/b1/actions", { round: 3, revision: 7, action: { kind: "ability", ability_id: "guardian_strike" } }, KEY],
      ["POST", "/api/emberlings/battles/b1/emblem", { round: 3, revision: 7, tier: "rare" }, KEY],
      ["POST", "/api/emberlings/battles/b1/advance", { round: 3, revision: 7 }, KEY],
      ["POST", "/api/emberlings/battles/b1/mode", { round: 3, revision: 7, mode: "autonomous" }, KEY],
      ["POST", "/api/emberlings/battles/b1/mode", { round: 3, revision: 7, mode: "autonomous", emblem_limit: "rare" }, KEY],
      ["POST", "/api/emberlings/battles/b1/forfeit", undefined, KEY],
      ["POST", "/api/emberlings/shop/purchases", { kind: "emblem", tier: "normal", quantity: 3 }, KEY],
      ["POST", "/api/emberlings/shop/purchases", { kind: "copies", spark_id: "bruiser", tier: "rare" }, KEY],
      ["POST", "/api/emberlings/sparks/guardian/sales", undefined, KEY],
    ]);
  });

  it("makes a fresh key for each action when none is given", async () => {
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");

    await emberlingsClient.rollEncounter();
    await emberlingsClient.rollEncounter();

    expect(request.mock.calls.map((call) => call[3])).toEqual([
      { "Idempotency-Key": "00000000-0000-4000-8000-000000000001" },
      { "Idempotency-Key": "00000000-0000-4000-8000-000000000002" },
    ]);
  });

  it("makes keys without randomUUID too (plain HTTP on a LAN address)", () => {
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined });
    try {
      const first = newIdempotencyKey();
      expect(first).toMatch(/^[0-9a-f]{32}$/);
      expect(newIdempotencyKey()).not.toBe(first);
    } finally {
      Object.defineProperty(crypto, "randomUUID", { configurable: true, value: original });
    }
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/api/http.test.ts src/api/EmberlingsClient.test.ts`
Expected: `EmberlingsClient.test.ts` fails to import `./EmberlingsClient`; the first `http.test.ts` case fails (no `Idempotency-Key` sent).

- [ ] **Step 3: Implement**

In `src/api/http.ts` replace the whole `apiRequest` function with:

```ts
export async function apiRequest<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  // Every POST is JSON, even with no payload: ember_api rejects anything
  // else as a CSRF guard. Other methods send a body only when given one.
  // `headers` adds request headers such as an Idempotency-Key.
  const init: RequestInit = { method, credentials: "same-origin" };
  const sent: Record<string, string> = { ...headers };
  if (method === "POST" || body !== undefined) {
    sent["Content-Type"] = "application/json";
    init.body = JSON.stringify(body ?? {});
  }
  if (Object.keys(sent).length > 0) init.headers = sent;
  const response = await fetch(path, init);
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = messageOf(data, response.statusText || `HTTP ${response.status}`);
    if (response.status === 401) {
      unauthorizedHandler?.();
      throw new UnauthorizedError(401, message);
    }
    throw new ApiError(response.status, message);
  }
  return data as T;
}
```

Create `src/api/EmberlingsClient.ts`:

```ts
import { apiRequest } from "./http";

/** The Emberlings game (apps/mini_games) through ember_api's /api/emberlings
 * pass-through. Field names are mini_games' own. Every change carries an
 * Idempotency-Key: a fresh one per user action, unless the caller passes the
 * key of the action it is retrying. Times (`next_roll_at`, `faint_until`,
 * `deadline`, `created_at`) are server epoch seconds. */

export type BattleMode = "manual" | "autonomous";
export type ActionKind = "attack" | "ability" | "flee" | "catch";
export type ResultKind = "won" | "knocked_out" | "captured" | "escaped" | "wild_escaped" | "forfeited";
export type Side = "player" | "wild";

export interface TierInfo {
  id: string;
  stat_multiplier: number;
  /** Copies a regular Spark needs for this tier; null for the Forbidden tier. */
  copy_threshold: number | null;
  copy_reward: number;
  emblem_strength: number;
  emblem_price: number;
}

export interface AbilityInfo {
  id: string;
  name: string;
  unlock_level: number;
  category: string;
  percentage: number;
  cooldown: number;
  stat: string | null;
  duration: number | null;
}

export interface SparkInfo {
  id: string;
  name: string;
  starter: boolean;
  forbidden: boolean;
  base: Record<string, number>;
  growth: Record<string, number>;
  base_price: number;
  passive: { kind: string; params: Record<string, unknown> };
  abilities: AbilityInfo[];
}

export interface Catalog {
  version: number;
  /** Weakest first. */
  tiers: TierInfo[];
  levels: { regular_cap: number; forbidden_cap: number };
  sparks: SparkInfo[];
  personalities: { id: string; categories: string[] }[];
}

export interface OwnedSpark {
  spark_id: string;
  name: string;
  level: number;
  xp: number;
  /** null at the level cap. */
  xp_needed: number | null;
  level_cap: number;
  copies: number;
  tier_id: string;
  faint_until: number | null;
  fainted: boolean;
}

export interface Profile {
  owner: string;
  insignia: number;
  emblems: Record<string, number>;
  sparks: OwnedSpark[];
  pending_encounter: string | null;
  active_battle: string | null;
  next_roll_at: number | null;
}

export interface PersonalityItem {
  id: string;
  type: string;
  tier: number;
}

export interface PersonalityPage {
  items: PersonalityItem[];
  next_cursor: number | null;
}

export interface Preset {
  spark_id: string;
  slot: number;
  instance_ids: string[];
}

export interface EncounterPreview {
  id: string;
  spark_id: string;
  name: string;
  tier_id: string;
  level: number;
  status: string;
  created_at: number;
}

export interface Buff {
  source: string;
  stat: string;
  amount: number;
  /** null: lasts the whole battle. */
  rounds_left: number | null;
}

export interface DefenseEffect {
  rating: number;
  attacks_left: number;
  rounds_left: number;
}

export interface FighterAbility {
  id: string;
  name: string;
  category: string;
  percentage: number;
  cooldown: number;
  ready: boolean;
}

export interface Fighter {
  spark_id: string;
  name: string;
  tier_id: string;
  level: number;
  hp: number;
  max_hp: number;
  essence: number;
  speed: number;
  buffs: Buff[];
  defense: DefenseEffect | null;
  abilities: FighterAbility[];
}

export interface LegalAction {
  kind: ActionKind;
  category: string;
  ability_id: string | null;
  name: string | null;
  percentage: number;
}

export interface EmblemPromptState {
  /** Server time; the page never uses it (see seconds_left). */
  deadline: number;
  seconds_left: number;
  permitted_tiers: string[];
  owned: Record<string, number>;
}

export interface BattleEvent {
  type: string;
  side?: Side;
  [field: string]: unknown;
}

export interface HistoryRound {
  round: number;
  /** side -> [action key ("attack", "ability:<id>", "flee", "catch"), category] */
  actions: Record<Side, [string, string]>;
  events: BattleEvent[];
}

export interface RevealedPersonality {
  id: string;
  type: string;
  tier: number;
}

export interface BattleResult {
  kind: ResultKind;
  xp?: number;
  insignia?: number;
  level_before?: number;
  level_after?: number;
  spark_id?: string;
  copies_granted?: number;
  copies?: number;
  tier_id?: string;
  awarded_personality?: RevealedPersonality;
  revealed_personalities?: RevealedPersonality[];
  faint_until?: number;
}

export interface BattleView {
  id: string;
  status: "active" | "terminal";
  phase: "choosing" | "awaiting_emblem" | "terminal";
  mode: BattleMode;
  round: number;
  revision: number;
  emblem_limit: string | null;
  player: Fighter;
  wild: Fighter;
  actions: LegalAction[];
  emblems: Record<string, number>;
  prompt: EmblemPromptState | null;
  history: HistoryRound[];
  result: BattleResult | null;
}

/** The round and revision a round change was based on (a stale pair is a 409). */
export interface RoundRef {
  round: number;
  revision: number;
}

export interface ActionChoice {
  kind: ActionKind;
  ability_id?: string;
  emblem_tier?: string;
}

export interface StartBattleInput {
  encounter_id: string;
  spark_id: string;
  preset_slot: number | null;
  mode: BattleMode;
  emblem_limit: string | null;
}

export interface EmblemPurchase {
  kind: "emblems";
  tier_id: string;
  quantity: number;
  price: number;
}

export interface CopyPurchase {
  kind: "copies";
  spark_id: string;
  tier_id: string;
  copies_granted: number;
  price: number;
  resulting_tier_id: string;
}

export interface Sale {
  kind: "sale";
  spark_id: string;
  value: number;
  copies: number;
  tier_id: string;
  downgraded: boolean;
}

const BASE = "/api/emberlings";

/** A new Idempotency-Key for one user action. randomUUID exists only in
 * secure contexts (HTTPS or localhost); getRandomValues works everywhere. */
export function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

const withKey = (key: string): Record<string, string> => ({ "Idempotency-Key": key });
const part = (id: string): string => encodeURIComponent(id);
const round = (at: RoundRef) => ({ round: at.round, revision: at.revision });

export const emberlingsClient = {
  catalog: () => apiRequest<Catalog>("GET", `${BASE}/catalog`),
  /** 404 (ApiError) until the account has chosen a starter. */
  profile: () => apiRequest<Profile>("GET", `${BASE}/profile`),
  createProfile: (starterSparkId: string, key: string = newIdempotencyKey()) =>
    apiRequest<Profile>("POST", `${BASE}/profile`, { starter_spark_id: starterSparkId }, withKey(key)),
  personalities: (sparkId: string, cursor: number | null = null, limit?: number) => {
    const query = new URLSearchParams();
    if (limit !== undefined) query.set("limit", String(limit));
    if (cursor !== null) query.set("cursor", String(cursor));
    const text = query.toString();
    return apiRequest<PersonalityPage>("GET", `${BASE}/sparks/${part(sparkId)}/personalities${text ? `?${text}` : ""}`);
  },
  preset: (sparkId: string, slot: number) => apiRequest<Preset>("GET", `${BASE}/sparks/${part(sparkId)}/presets/${slot}`),
  savePreset: (sparkId: string, slot: number, instanceIds: string[], key: string = newIdempotencyKey()) =>
    apiRequest<Preset>("PUT", `${BASE}/sparks/${part(sparkId)}/presets/${slot}`, { instance_ids: instanceIds }, withKey(key)),
  rollEncounter: (key: string = newIdempotencyKey()) =>
    apiRequest<EncounterPreview>("POST", `${BASE}/encounters`, undefined, withKey(key)),
  encounter: (id: string) => apiRequest<EncounterPreview>("GET", `${BASE}/encounters/${part(id)}`),
  declineEncounter: (id: string, key: string = newIdempotencyKey()) =>
    apiRequest<EncounterPreview>("POST", `${BASE}/encounters/${part(id)}/decline`, undefined, withKey(key)),
  startBattle: (input: StartBattleInput, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles`, input, withKey(key)),
  battle: (id: string) => apiRequest<BattleView>("GET", `${BASE}/battles/${part(id)}`),
  action: (id: string, at: RoundRef, choice: ActionChoice, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/actions`, { ...round(at), action: choice }, withKey(key)),
  emblem: (id: string, at: RoundRef, tier: string, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/emblem`, { ...round(at), tier }, withKey(key)),
  advance: (id: string, at: RoundRef, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/advance`, round(at), withKey(key)),
  /** emblemLimit null keeps the battle's own limit. */
  setMode: (id: string, at: RoundRef, mode: BattleMode, emblemLimit: string | null, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>(
      "POST",
      `${BASE}/battles/${part(id)}/mode`,
      { ...round(at), mode, ...(emblemLimit === null ? {} : { emblem_limit: emblemLimit }) },
      withKey(key),
    ),
  forfeit: (id: string, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/forfeit`, undefined, withKey(key)),
  buyEmblems: (tier: string, quantity: number, key: string = newIdempotencyKey()) =>
    apiRequest<EmblemPurchase>("POST", `${BASE}/shop/purchases`, { kind: "emblem", tier, quantity }, withKey(key)),
  buyCopies: (sparkId: string, tier: string, key: string = newIdempotencyKey()) =>
    apiRequest<CopyPurchase>("POST", `${BASE}/shop/purchases`, { kind: "copies", spark_id: sparkId, tier }, withKey(key)),
  sellCopy: (sparkId: string, key: string = newIdempotencyKey()) =>
    apiRequest<Sale>("POST", `${BASE}/sparks/${part(sparkId)}/sales`, undefined, withKey(key)),
};
```

Create `src/api/EmberlingsClient.fixtures.ts` (test data shared by the Emberlings tests; app code never imports it):

```ts
import type { Account } from "./AuthClient";
import type { BattleView, Catalog, EncounterPreview, Fighter, OwnedSpark, Profile, SparkInfo, TierInfo } from "./EmberlingsClient";

/** Test data shaped like mini_games' answers, for the Emberlings tests. */

const nameOf = (id: string) => id.charAt(0).toUpperCase() + id.slice(1);

export function tier(id: string, emblemPrice: number, copyThreshold: number | null): TierInfo {
  return { id, stat_multiplier: 1, copy_threshold: copyThreshold, copy_reward: 1, emblem_strength: 1, emblem_price: emblemPrice };
}

export function sparkInfo(id: string, extra: Partial<SparkInfo> = {}): SparkInfo {
  return {
    id,
    name: nameOf(id),
    starter: false,
    forbidden: false,
    base: { hp: 100, essence: 10, speed: 10 },
    growth: { hp: 5, essence: 1, speed: 1 },
    base_price: 50,
    passive: { kind: "steady", params: {} },
    abilities: [
      { id: `${id}_strike`, name: "Strike", unlock_level: 1, category: "ATTACK", percentage: 120, cooldown: 1, stat: null, duration: null },
      { id: `${id}_rally`, name: "Rally", unlock_level: 5, category: "SUPPORT", percentage: 50, cooldown: 3, stat: "essence", duration: 2 },
    ],
    ...extra,
  };
}

export const CATALOG: Catalog = {
  version: 1,
  tiers: [
    tier("normal", 10, 0),
    tier("rare", 40, 3),
    tier("legendary", 90, 6),
    tier("royalty", 150, 10),
    tier("ascended", 250, 15),
    tier("forbidden", 500, null),
  ],
  levels: { regular_cap: 30, forbidden_cap: 50 },
  sparks: [
    sparkInfo("guardian", { starter: true }),
    sparkInfo("striker", { starter: true }),
    sparkInfo("bruiser"),
    sparkInfo("forbidden", { forbidden: true }),
  ],
  personalities: [
    { id: "AGGRESSIVE", categories: ["ATTACK"] },
    { id: "CAUTIOUS", categories: ["DEFENSE"] },
  ],
};

export function ownedSpark(id: string, extra: Partial<OwnedSpark> = {}): OwnedSpark {
  return {
    spark_id: id,
    name: nameOf(id),
    level: 3,
    xp: 40,
    xp_needed: 300,
    level_cap: 30,
    copies: 1,
    tier_id: "normal",
    faint_until: null,
    fainted: false,
    ...extra,
  };
}

export const PROFILE: Profile = {
  owner: "1",
  insignia: 100,
  emblems: { normal: 2 },
  sparks: [ownedSpark("guardian")],
  pending_encounter: null,
  active_battle: null,
  next_roll_at: null,
};

export const ENCOUNTER: EncounterPreview = {
  id: "e1",
  spark_id: "bruiser",
  name: "Bruiser",
  tier_id: "rare",
  level: 4,
  status: "pending",
  created_at: 1_700_000_000,
};

export function fighter(sparkId: string, extra: Partial<Fighter> = {}): Fighter {
  return {
    spark_id: sparkId,
    name: nameOf(sparkId),
    tier_id: "normal",
    level: 3,
    hp: 80,
    max_hp: 100,
    essence: 12,
    speed: 9,
    buffs: [],
    defense: null,
    abilities: [{ id: `${sparkId}_strike`, name: "Strike", category: "ATTACK", percentage: 120, cooldown: 1, ready: true }],
    ...extra,
  };
}

export function battleView(extra: Partial<BattleView> = {}): BattleView {
  return {
    id: "b1",
    status: "active",
    phase: "choosing",
    mode: "autonomous",
    round: 1,
    revision: 1,
    emblem_limit: "normal",
    player: fighter("guardian"),
    wild: fighter("bruiser"),
    actions: [
      { kind: "attack", category: "ATTACK", ability_id: null, name: null, percentage: 100 },
      { kind: "ability", category: "ATTACK", ability_id: "guardian_strike", name: "Strike", percentage: 120 },
      { kind: "flee", category: "FEAR", ability_id: null, name: null, percentage: 100 },
      { kind: "catch", category: "INTERCEPT", ability_id: null, name: null, percentage: 100 },
    ],
    emblems: { normal: 2 },
    prompt: null,
    history: [],
    result: null,
    ...extra,
  };
}

export const ACCOUNT_WITH_EMBERLINGS: Account = {
  id: 1,
  username: "lex",
  email: "lex@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use", "emberlings.play"],
};
```

- [ ] **Step 4: Run the tests and the type-check**

Run: `npx vitest run src/api/http.test.ts src/api/EmberlingsClient.test.ts` then `npm test` then `npx vue-tsc -b --noEmit`
Expected: all tests pass (the other clients' tests are unchanged because they pass no headers); vue-tsc prints nothing.

- [ ] **Step 5: Report and commit (after the user agrees)**

```bash
git add apps/Ember/ember_web/src/api/http.ts apps/Ember/ember_web/src/api/http.test.ts apps/Ember/ember_web/src/api/EmberlingsClient.ts apps/Ember/ember_web/src/api/EmberlingsClient.fixtures.ts apps/Ember/ember_web/src/api/EmberlingsClient.test.ts
git commit -m "feat(ember-web): Emberlings client and Idempotency-Key header support"
```

### Task B2: The Pinia store and the battle loop

**Files:**
- Create: `apps/Ember/ember_web/src/stores/emberlings.ts`
- Test: `apps/Ember/ember_web/src/stores/emberlings.test.ts`

**Interfaces:**
- Consumes: everything `emberlingsClient` exports (B1); `ApiError`, `UnauthorizedError` from `src/api/http.ts`; `useAuthStore().account`.
- Produces: `useEmberlingsStore` with
  - constants `ROUND_PACE_MS = 1500`, `RECONNECT_MS = 3000`
  - state: `catalog: Catalog | null`, `profile: Profile | null`, `needsStarter: boolean`, `encounter: EncounterPreview | null`, `battle: BattleView | null`, `loading`, `loaded`, `unavailable`, `reconnecting`, `busy` (shop, profile, encounter changes), `battleBusy` (a battle call in flight), `error: string`, `promptRemaining: number` (seconds), `promptTotal: number`, `promptOpen` (computed)
  - lifecycle: `attach()`, `detach()`, `retry(): Promise<void>`
  - actions: `createProfile(starterSparkId): Promise<Profile | null>`, `rollEncounter(): Promise<EncounterPreview | null>`, `declineEncounter(): Promise<EncounterPreview | null>`, `startBattle(input: StartBattleInput): Promise<BattleView | null>`, `savePreset(sparkId, slot, instanceIds): Promise<Preset | null>`, `buyEmblems(tier, quantity): Promise<EmblemPurchase | null>`, `buyCopies(sparkId, tier): Promise<CopyPurchase | null>`, `sellCopy(sparkId): Promise<Sale | null>`, `act(choice: ActionChoice): Promise<void>`, `answerEmblem(tier): Promise<void>`, `setMode(mode: BattleMode): Promise<void>`, `forfeit(): Promise<void>`, `refreshBattle(): Promise<void>`, `closeBattle(): void`
  - A failed change resolves to `null` and sets `error` (or `unavailable` on 502); components never catch.

How the loop works (the code below is the source of truth):
- `attach()` (the view mounted or reactivated) listens to `visibilitychange` and resumes: the first time it loads catalog and profile; later it re-reads the active battle with one `GET`, which also gives a fresh `seconds_left`. `detach()` and a hidden page clear every timer. `running` = attached and not hidden.
- After every battle view (`setBattle`) the store schedules: nothing unless running and `status === "active"`; while reconnecting, a `GET` in 3 s; with an open prompt, a countdown from `prompt.seconds_left` on `performance.now()`, calling `advance` at zero; in autonomous `choosing`, `advance` in 1.5 s; in manual mode nothing.
- A battle call never overlaps another (`battleBusy`) and clears the timers first. A 409 shows its message and does one `GET` (no silent retry); a late EMBLEM answer is a 409 like any other, and the refreshed view (prompt at 0 s) makes the loop call `advance` at once. A 404 drops the battle. A 502 sets `unavailable`. A network error (not an `ApiError`) sets `reconnecting` and retries the `GET` every 3 s.
- An account change bumps a generation counter, clears timers and empties everything; answers for the previous account are ignored.

- [ ] **Step 1: Write the failing tests**

Create `apps/Ember/ember_web/src/stores/emberlings.test.ts`:

```ts
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type BattleView, type EmblemPromptState } from "../api/EmberlingsClient";
import { ACCOUNT_WITH_EMBERLINGS, CATALOG, ENCOUNTER, PROFILE, battleView } from "../api/EmberlingsClient.fixtures";
import { ApiError } from "../api/http";
import { useAuthStore } from "./auth";
import { RECONNECT_MS, ROUND_PACE_MS, useEmberlingsStore } from "./emberlings";

vi.mock("../api/EmberlingsClient", () => ({
  emberlingsClient: {
    catalog: vi.fn(),
    profile: vi.fn(),
    createProfile: vi.fn(),
    personalities: vi.fn(),
    preset: vi.fn(),
    savePreset: vi.fn(),
    rollEncounter: vi.fn(),
    encounter: vi.fn(),
    declineEncounter: vi.fn(),
    startBattle: vi.fn(),
    battle: vi.fn(),
    action: vi.fn(),
    emblem: vi.fn(),
    advance: vi.fn(),
    setMode: vi.fn(),
    forfeit: vi.fn(),
    buyEmblems: vi.fn(),
    buyCopies: vi.fn(),
    sellCopy: vi.fn(),
  },
}));

const client = vi.mocked(emberlingsClient);
// The server's deadline is deliberately nonsense: only seconds_left may count.
const PROMPT: EmblemPromptState = { deadline: 0, seconds_left: 5, permitted_tiers: ["normal"], owned: { normal: 2 } };

let visibility: DocumentVisibilityState = "visible";
let store: ReturnType<typeof useEmberlingsStore> | null = null;

beforeAll(() => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
});

function setVisibility(state: DocumentVisibilityState): void {
  visibility = state;
  document.dispatchEvent(new Event("visibilitychange"));
}

async function attached(): Promise<ReturnType<typeof useEmberlingsStore>> {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT_WITH_EMBERLINGS;
  store = useEmberlingsStore();
  store.attach();
  await flushPromises();
  return store;
}

async function attachedWith(view: BattleView): Promise<ReturnType<typeof useEmberlingsStore>> {
  client.profile.mockResolvedValue({ ...PROFILE, active_battle: view.id });
  client.battle.mockResolvedValue(view);
  return attached();
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "performance"] });
  visibility = "visible";
  client.catalog.mockResolvedValue(CATALOG);
  client.profile.mockResolvedValue(PROFILE);
});

afterEach(() => {
  store?.detach();
  store = null;
  vi.useRealTimers();
});

describe("loading", () => {
  it("asks for a starter while there is no profile", async () => {
    client.profile.mockRejectedValue(new ApiError(404, "no profile yet; choose a starter first"));
    const s = await attached();

    expect(s.needsStarter).toBe(true);
    expect(s.profile).toBeNull();

    client.createProfile.mockResolvedValue(PROFILE);
    await s.createProfile("guardian");

    expect(client.createProfile).toHaveBeenCalledExactlyOnceWith("guardian");
    expect(s.profile).toEqual(PROFILE);
    expect(s.needsStarter).toBe(false);
  });

  it("restores a pending encounter instead of rolling a new one", async () => {
    client.profile.mockResolvedValue({ ...PROFILE, pending_encounter: "e1" });
    client.encounter.mockResolvedValue(ENCOUNTER);
    const s = await attached();

    expect(client.encounter).toHaveBeenCalledExactlyOnceWith("e1");
    expect(s.encounter?.id).toBe("e1");
    expect(client.rollEncounter).not.toHaveBeenCalled();
  });

  it("shows the page as unavailable on 502 and loads again on retry", async () => {
    client.catalog.mockRejectedValueOnce(new ApiError(502, "Emberlings is not available right now"));
    const s = await attached();

    expect(s.unavailable).toBe(true);

    await s.retry();

    expect(s.unavailable).toBe(false);
    expect(s.loaded).toBe(true);
  });

  it("forgets everything when the account changes", async () => {
    const s = await attachedWith(battleView());

    useAuthStore().account = { ...ACCOUNT_WITH_EMBERLINGS, id: 2 };
    await flushPromises();
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 3);

    expect(s.battle).toBeNull();
    expect(s.profile).toBeNull();
    expect(s.loaded).toBe(false);
    expect(client.advance).not.toHaveBeenCalled();
  });
});

describe("the autonomous loop", () => {
  it("plays a round every 1.5 s until the battle ends", async () => {
    const s = await attachedWith(battleView());
    client.advance
      .mockResolvedValueOnce(battleView({ round: 2, revision: 2 }))
      .mockResolvedValueOnce(
        battleView({ round: 3, revision: 3, status: "terminal", phase: "terminal", result: { kind: "won", xp: 5, insignia: 3 } }),
      );

    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS - 1);
    expect(client.advance).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(client.advance).toHaveBeenLastCalledWith("b1", { round: 1, revision: 1 });
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(client.advance).toHaveBeenLastCalledWith("b1", { round: 2, revision: 2 });
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);

    expect(client.advance).toHaveBeenCalledTimes(2);
    expect(s.battle?.result?.kind).toBe("won");
    // Loaded once, then again for the rewards.
    expect(client.profile).toHaveBeenCalledTimes(2);
  });

  it("stops when the page is left", async () => {
    const s = await attachedWith(battleView());

    s.detach();
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);

    expect(client.advance).not.toHaveBeenCalled();
  });

  it("pauses while the page is hidden and resumes from a fresh view", async () => {
    await attachedWith(battleView());

    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);
    expect(client.advance).not.toHaveBeenCalled();

    client.battle.mockClear();
    setVisibility("visible");
    await flushPromises();
    expect(client.battle).toHaveBeenCalledExactlyOnceWith("b1");

    client.advance.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 2 }));
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(client.advance).toHaveBeenCalledTimes(1);
  });

  it("pauses on a network error and asks again every 3 s until it answers", async () => {
    const s = await attachedWith(battleView());
    client.advance.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(s.reconnecting).toBe(true);

    client.battle.mockClear();
    client.battle.mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(battleView({ round: 2, revision: 2 }));
    await vi.advanceTimersByTimeAsync(RECONNECT_MS);
    expect(client.battle).toHaveBeenCalledTimes(1);
    expect(s.reconnecting).toBe(true);
    await vi.advanceTimersByTimeAsync(RECONNECT_MS);
    expect(client.battle).toHaveBeenCalledTimes(2);
    expect(s.reconnecting).toBe(false);

    client.advance.mockResolvedValue(battleView({ mode: "manual", round: 3, revision: 3 }));
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(client.advance).toHaveBeenLastCalledWith("b1", { round: 2, revision: 2 });
  });

  it("stops and shows the page as unavailable on 502", async () => {
    const s = await attachedWith(battleView());
    client.advance.mockRejectedValue(new ApiError(502, "Emberlings is not available right now"));

    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);

    expect(s.unavailable).toBe(true);
    expect(client.advance).toHaveBeenCalledTimes(1);
  });
});

describe("manual play", () => {
  it("never advances on its own and does not retry a stale action", async () => {
    const s = await attachedWith(battleView({ mode: "manual" }));
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);
    expect(client.advance).not.toHaveBeenCalled();

    client.action.mockRejectedValue(new ApiError(409, "the battle moved on; reload it and try again"));
    client.battle.mockClear();
    client.battle.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 3 }));
    await s.act({ kind: "attack" });

    expect(client.action).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, { kind: "attack" });
    expect(client.battle).toHaveBeenCalledExactlyOnceWith("b1");
    expect(s.battle?.revision).toBe(3);
    expect(s.error).toBe("the battle moved on; reload it and try again");
  });
});

describe("the EMBLEM prompt", () => {
  it("counts down on the local clock and lets the server settle it at zero", async () => {
    const s = await attachedWith(battleView({ phase: "awaiting_emblem", revision: 4, prompt: PROMPT }));

    expect(s.promptOpen).toBe(true);
    expect(s.promptRemaining).toBe(5);
    expect(s.promptTotal).toBe(5);

    await vi.advanceTimersByTimeAsync(2000);
    expect(s.promptRemaining).toBeCloseTo(3, 1);

    client.advance.mockResolvedValue(battleView({ round: 2, revision: 5 }));
    await vi.advanceTimersByTimeAsync(3000);

    expect(client.advance).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 });
    expect(s.promptOpen).toBe(false);
  });

  it("throws the chosen EMBLEM before the time is up", async () => {
    const s = await attachedWith(battleView({ phase: "awaiting_emblem", revision: 4, prompt: PROMPT }));
    client.emblem.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 5 }));

    await s.answerEmblem("normal");
    await vi.advanceTimersByTimeAsync(6000);

    expect(client.emblem).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 }, "normal");
    expect(client.advance).not.toHaveBeenCalled();
  });

  it("treats a late answer like an expired prompt: refresh and continue", async () => {
    const s = await attachedWith(battleView({ phase: "awaiting_emblem", revision: 4, prompt: PROMPT }));
    client.emblem.mockRejectedValue(new ApiError(409, "the prompt has expired; advance the battle instead"));
    client.battle.mockResolvedValue(
      battleView({ phase: "awaiting_emblem", revision: 4, prompt: { ...PROMPT, seconds_left: 0 } }),
    );
    client.advance.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 5 }));

    await s.answerEmblem("normal");
    await vi.advanceTimersByTimeAsync(0);

    expect(client.advance).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 });
    expect(s.battle?.revision).toBe(5);
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/stores/emberlings.test.ts`
Expected: fails to import `./emberlings`.

- [ ] **Step 3: Implement**

Create `src/stores/emberlings.ts`:

```ts
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import {
  emberlingsClient,
  type ActionChoice,
  type BattleMode,
  type BattleView,
  type Catalog,
  type CopyPurchase,
  type EmblemPurchase,
  type EncounterPreview,
  type Preset,
  type Profile,
  type Sale,
  type StartBattleInput,
} from "../api/EmberlingsClient";
import { ApiError, UnauthorizedError } from "../api/http";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";

/** Pause between autonomous rounds, so the round log stays readable. */
export const ROUND_PACE_MS = 1500;
/** How often a lost connection is tried again. */
export const RECONNECT_MS = 3000;
/** How often the EMBLEM prompt's countdown is redrawn. */
const PROMPT_TICK_MS = 200;

/** The Emberlings page's state: catalog, profile, the current encounter and
 * battle, and the battle loop. The loop runs only while the page is attached
 * (mounted or reactivated in KeepAlive) and visible; mini_games keeps the
 * battle between rounds, so stopping is always safe. Changes resolve to null
 * on failure and say why in `error` (or `unavailable` on 502). */
export const useEmberlingsStore = defineStore("emberlings", () => {
  const auth = useAuthStore();

  const catalog = ref<Catalog | null>(null);
  const profile = ref<Profile | null>(null);
  /** GET /profile answered 404: the account has not chosen a starter yet. */
  const needsStarter = ref(false);
  const encounter = ref<EncounterPreview | null>(null);
  const battle = ref<BattleView | null>(null);
  const loading = ref(false);
  const loaded = ref(false);
  const unavailable = ref(false);
  const reconnecting = ref(false);
  const busy = ref(false);
  const battleBusy = ref(false);
  const error = ref("");
  /** Seconds left on the EMBLEM prompt, counted on this device's monotonic clock. */
  const promptRemaining = ref(0);
  const promptTotal = ref(0);

  const promptOpen = computed(() => {
    const current = battle.value;
    return current !== null && current.status === "active" && current.phase === "awaiting_emblem" && current.prompt !== null;
  });

  let attached = false;
  // Bumped on every account change: answers for the previous account are ignored.
  let generation = 0;
  let roundTimer: ReturnType<typeof setTimeout> | null = null;
  let promptTimer: ReturnType<typeof setTimeout> | null = null;
  let promptTick: ReturnType<typeof setInterval> | null = null;
  let promptEndsAt = 0;
  let promptRevision: number | null = null;

  function visible(): boolean {
    return typeof document === "undefined" || document.visibilityState !== "hidden";
  }

  function running(): boolean {
    return attached && visible();
  }

  function clearTimers(): void {
    if (roundTimer !== null) clearTimeout(roundTimer);
    if (promptTimer !== null) clearTimeout(promptTimer);
    if (promptTick !== null) clearInterval(promptTick);
    roundTimer = null;
    promptTimer = null;
    promptTick = null;
  }

  function startPrompt(view: BattleView, secondsLeft: number): void {
    if (promptRevision !== view.revision) {
      promptRevision = view.revision;
      promptTotal.value = Math.max(0, secondsLeft);
    }
    const ms = Math.max(0, secondsLeft * 1000);
    promptEndsAt = performance.now() + ms;
    promptRemaining.value = ms / 1000;
    promptTick = setInterval(() => {
      promptRemaining.value = Math.max(0, (promptEndsAt - performance.now()) / 1000);
    }, PROMPT_TICK_MS);
    // At zero mini_games settles the prompt itself (the Spark's own choice, or a basic ATTACK).
    promptTimer = setTimeout(() => {
      promptRemaining.value = 0;
      void advance();
    }, ms);
  }

  function schedule(): void {
    clearTimers();
    const current = battle.value;
    if (!running() || current === null || current.status !== "active") return;
    if (reconnecting.value) {
      roundTimer = setTimeout(() => void refreshBattle(), RECONNECT_MS);
      return;
    }
    if (current.phase === "awaiting_emblem" && current.prompt !== null) {
      startPrompt(current, current.prompt.seconds_left);
      return;
    }
    if (current.mode === "autonomous" && current.phase === "choosing") {
      roundTimer = setTimeout(() => void advance(), ROUND_PACE_MS);
    }
  }

  function setBattle(view: BattleView): void {
    const justFinished = view.status !== "active" && battle.value?.status === "active";
    battle.value = view;
    if (profile.value !== null) profile.value = { ...profile.value, emblems: view.emblems };
    // XP, Insignia, copies and faint times changed with the result.
    if (justFinished) void refreshProfile();
    schedule();
  }

  function report(err: unknown): void {
    if (err instanceof UnauthorizedError) return;
    if (err instanceof ApiError && err.status === 502) {
      unavailable.value = true;
      clearTimers();
      return;
    }
    error.value = errorMessage(err);
  }

  async function refreshProfile(): Promise<void> {
    const started = generation;
    try {
      const next = await emberlingsClient.profile();
      if (started === generation) profile.value = next;
    } catch (err) {
      if (started === generation) report(err);
    }
  }

  /** One GET of the current battle: after a 409, on return to the page, and while reconnecting. */
  async function refreshBattle(): Promise<void> {
    const current = battle.value;
    if (current === null) return;
    const started = generation;
    try {
      const view = await emberlingsClient.battle(current.id);
      if (started !== generation) return;
      reconnecting.value = false;
      setBattle(view);
    } catch (err) {
      if (started !== generation) return;
      if (err instanceof ApiError) {
        report(err);
        return;
      }
      reconnecting.value = true;
      schedule();
    }
  }

  async function battleCall(call: (current: BattleView) => Promise<BattleView>): Promise<void> {
    const current = battle.value;
    if (current === null || battleBusy.value) return;
    const started = generation;
    clearTimers();
    battleBusy.value = true;
    error.value = "";
    try {
      const view = await call(current);
      if (started !== generation) return;
      battleBusy.value = false;
      setBattle(view);
    } catch (err) {
      if (started !== generation) return;
      battleBusy.value = false;
      if (!(err instanceof ApiError)) {
        reconnecting.value = true;
        schedule();
        return;
      }
      if (err.status === 409) {
        // Stale round or revision, wrong phase, a prompt answered too late: show
        // why, read the battle once, never resend the action on its own.
        error.value = err.message;
        await refreshBattle();
        return;
      }
      if (err.status === 404) {
        error.value = err.message;
        battle.value = null;
        void refreshProfile();
        return;
      }
      report(err);
    } finally {
      if (started === generation) battleBusy.value = false;
    }
  }

  function advance(): Promise<void> {
    return battleCall((b) => emberlingsClient.advance(b.id, { round: b.round, revision: b.revision }));
  }

  function act(choice: ActionChoice): Promise<void> {
    return battleCall((b) => emberlingsClient.action(b.id, { round: b.round, revision: b.revision }, choice));
  }

  function answerEmblem(tier: string): Promise<void> {
    if (!promptOpen.value || promptRemaining.value <= 0) return Promise.resolve();
    return battleCall((b) => emberlingsClient.emblem(b.id, { round: b.round, revision: b.revision }, tier));
  }

  function setMode(mode: BattleMode): Promise<void> {
    return battleCall((b) => emberlingsClient.setMode(b.id, { round: b.round, revision: b.revision }, mode, null));
  }

  function forfeit(): Promise<void> {
    return battleCall((b) => emberlingsClient.forfeit(b.id));
  }

  /** Leaves a finished battle's result for the encounter screen. */
  function closeBattle(): void {
    clearTimers();
    battle.value = null;
    reconnecting.value = false;
    error.value = "";
    void refreshProfile();
  }

  async function loadProfile(started: number): Promise<void> {
    let next: Profile;
    try {
      next = await emberlingsClient.profile();
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        if (started === generation) {
          profile.value = null;
          needsStarter.value = true;
          encounter.value = null;
          battle.value = null;
        }
        return;
      }
      throw err;
    }
    if (started !== generation) return;
    profile.value = next;
    needsStarter.value = false;
    // A reload restores what was open; it never rolls again.
    if (next.active_battle !== null) {
      const view = await emberlingsClient.battle(next.active_battle);
      if (started !== generation) return;
      encounter.value = null;
      setBattle(view);
    } else if (next.pending_encounter !== null) {
      const preview = await emberlingsClient.encounter(next.pending_encounter);
      if (started !== generation) return;
      encounter.value = preview;
    } else {
      encounter.value = null;
    }
  }

  async function load(): Promise<void> {
    const started = generation;
    loading.value = true;
    unavailable.value = false;
    error.value = "";
    try {
      if (catalog.value === null) {
        const fetched = await emberlingsClient.catalog();
        if (started !== generation) return;
        catalog.value = fetched;
      }
      await loadProfile(started);
      if (started === generation) loaded.value = true;
    } catch (err) {
      if (started === generation) report(err);
    } finally {
      if (started === generation) loading.value = false;
    }
  }

  function retry(): Promise<void> {
    loaded.value = false;
    return load();
  }

  async function resume(): Promise<void> {
    if (!running()) return;
    if (!loaded.value) {
      if (!loading.value) await load();
      return;
    }
    if (battle.value?.status === "active") await refreshBattle();
  }

  function onVisibilityChange(): void {
    if (visible()) void resume();
    else clearTimers();
  }

  /** The page is showing: load or refresh, and let the loop run. */
  function attach(): void {
    if (attached) return;
    attached = true;
    document.addEventListener("visibilitychange", onVisibilityChange);
    void resume();
  }

  /** The page is gone (unmounted, or deactivated in KeepAlive): stop the loop. */
  function detach(): void {
    if (!attached) return;
    attached = false;
    document.removeEventListener("visibilitychange", onVisibilityChange);
    clearTimers();
  }

  async function mutate<T>(call: () => Promise<T>, apply: (result: T) => void | Promise<void>): Promise<T | null> {
    const started = generation;
    busy.value = true;
    error.value = "";
    try {
      const result = await call();
      if (started !== generation) return null;
      await apply(result);
      return result;
    } catch (err) {
      if (started === generation) report(err);
      return null;
    } finally {
      if (started === generation) busy.value = false;
    }
  }

  function createProfile(starterSparkId: string): Promise<Profile | null> {
    return mutate(
      () => emberlingsClient.createProfile(starterSparkId),
      (created) => {
        profile.value = created;
        needsStarter.value = false;
      },
    );
  }

  function rollEncounter(): Promise<EncounterPreview | null> {
    return mutate(
      () => emberlingsClient.rollEncounter(),
      async (preview) => {
        encounter.value = preview;
        await refreshProfile();
      },
    );
  }

  function declineEncounter(): Promise<EncounterPreview | null> {
    const current = encounter.value;
    if (current === null) return Promise.resolve(null);
    return mutate(
      () => emberlingsClient.declineEncounter(current.id),
      async () => {
        encounter.value = null;
        await refreshProfile();
      },
    );
  }

  function startBattle(input: StartBattleInput): Promise<BattleView | null> {
    return mutate(
      () => emberlingsClient.startBattle(input),
      async (view) => {
        encounter.value = null;
        setBattle(view);
        await refreshProfile();
      },
    );
  }

  function savePreset(sparkId: string, slot: number, instanceIds: string[]): Promise<Preset | null> {
    return mutate(
      () => emberlingsClient.savePreset(sparkId, slot, instanceIds),
      () => undefined,
    );
  }

  function buyEmblems(tier: string, quantity: number): Promise<EmblemPurchase | null> {
    return mutate(() => emberlingsClient.buyEmblems(tier, quantity), () => refreshProfile());
  }

  function buyCopies(sparkId: string, tier: string): Promise<CopyPurchase | null> {
    return mutate(() => emberlingsClient.buyCopies(sparkId, tier), () => refreshProfile());
  }

  function sellCopy(sparkId: string): Promise<Sale | null> {
    return mutate(() => emberlingsClient.sellCopy(sparkId), () => refreshProfile());
  }

  watch(
    () => auth.account?.id ?? null,
    () => {
      generation += 1;
      clearTimers();
      catalog.value = null;
      profile.value = null;
      needsStarter.value = false;
      encounter.value = null;
      battle.value = null;
      loading.value = false;
      loaded.value = false;
      unavailable.value = false;
      reconnecting.value = false;
      busy.value = false;
      battleBusy.value = false;
      error.value = "";
      promptRemaining.value = 0;
      promptTotal.value = 0;
      promptRevision = null;
    },
  );

  return {
    catalog,
    profile,
    needsStarter,
    encounter,
    battle,
    loading,
    loaded,
    unavailable,
    reconnecting,
    busy,
    battleBusy,
    error,
    promptRemaining,
    promptTotal,
    promptOpen,
    attach,
    detach,
    retry,
    createProfile,
    rollEncounter,
    declineEncounter,
    startBattle,
    savePreset,
    buyEmblems,
    buyCopies,
    sellCopy,
    act,
    answerEmblem,
    setMode,
    forfeit,
    refreshBattle,
    closeBattle,
  };
});
```

- [ ] **Step 4: Run the tests and the type-check**

Run: `npx vitest run src/stores/emberlings.test.ts`, then `npm test`, then `npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Report and commit (after the user agrees)**

```bash
git add apps/Ember/ember_web/src/stores/emberlings.ts apps/Ember/ember_web/src/stores/emberlings.test.ts
git commit -m "feat(ember-web): Emberlings store with the battle loop"
```

### Task B3: Collection tab (`TierBadge`, `SparkCard`, `PresetEditor`, `CollectionPanel`)

**Files:**
- Create: `apps/Ember/ember_web/src/utils/emberlings.ts`
- Create: `apps/Ember/ember_web/src/composables/useNowSeconds.ts`
- Create: `apps/Ember/ember_web/src/components/emberlings/TierBadge.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/SparkCard.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/PresetEditor.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/CollectionPanel.vue`
- Test: `apps/Ember/ember_web/src/utils/emberlings.test.ts`, `apps/Ember/ember_web/src/components/emberlings/CollectionPanel.test.ts`

**Interfaces:**
- Consumes: `useEmberlingsStore()` (`catalog`, `profile`, `busy`, `savePreset`); `emberlingsClient.personalities(sparkId, cursor, limit)` and `emberlingsClient.preset(sparkId, slot)` (read directly: paging belongs to the open card, not the store); `BaseModal`, `SegmentedControl`, `ToggleSwitch`.
- Produces:
  - `utils/emberlings.ts`: `type TierStanding = "top" | "middle" | "low"`, `tierStanding(tiers, tierId)`, `titleCase(id)`, `formatCountdown(seconds)`, `RESULT_LABELS: Record<ResultKind, string>`, `interface SideNames { player: string; wild: string }`, `describeEvent(event, names)`, `describeAction(key, abilities)`
  - `composables/useNowSeconds.ts`: `useNowSeconds(): Ref<number>` (wall-clock epoch seconds, ticking each second while mounted)
  - `<TierBadge :tier-id>`; `<SparkCard :spark @open>`; `<PresetEditor :spark-id :personalities>`; `<CollectionPanel />` (no props)
  - CSS hooks the later tests use: `.spark-card`, `.missing-spark`, `.details`

- [ ] **Step 1: Write the failing tests**

Create `src/utils/emberlings.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { CATALOG } from "../api/EmberlingsClient.fixtures";
import { describeAction, describeEvent, formatCountdown, tierStanding, titleCase } from "./emberlings";

const NAMES = { player: "Guardian", wild: "Bruiser" };

describe("emberlings helpers", () => {
  it("draws the three strongest tiers as top and the one below as middle", () => {
    expect(CATALOG.tiers.map((t) => tierStanding(CATALOG.tiers, t.id))).toEqual(["low", "low", "middle", "top", "top", "top"]);
    expect(tierStanding(CATALOG.tiers, "unknown")).toBe("low");
  });

  it("writes ids as words", () => {
    expect(titleCase("knocked_out")).toBe("Knocked out");
    expect(titleCase("AGGRESSIVE")).toBe("Aggressive");
    expect(titleCase("rare")).toBe("Rare");
  });

  it("formats countdowns, rounding up", () => {
    expect(formatCountdown(4.2)).toBe("0:05");
    expect(formatCountdown(90)).toBe("1:30");
    expect(formatCountdown(3723)).toBe("1:02:03");
    expect(formatCountdown(-3)).toBe("0:00");
  });

  it("puts round-log events and actions in words", () => {
    expect(describeEvent({ type: "attack", side: "wild", damage: 12, protected: false, target_hp: 68 }, NAMES)).toBe(
      "Bruiser hits for 12; Guardian has 68 HP left",
    );
    expect(describeEvent({ type: "capture_attempt", side: "player", emblem: "rare", chance: 0.25, success: true }, NAMES)).toBe(
      "Guardian throws a Rare EMBLEM (25%): caught",
    );
    expect(describeEvent({ type: "order", first: "wild", chance_player_first: 0.4 }, NAMES)).toBe("Bruiser moves first");
    expect(describeEvent({ type: "something_new" }, NAMES)).toBe("Something new");
    expect(describeAction("ability:guardian_strike", [{ id: "guardian_strike", name: "Strike" }])).toBe("Strike");
    expect(describeAction("flee", [])).toBe("Flee");
  });
});
```

Create `src/components/emberlings/CollectionPanel.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type Profile } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, ownedSpark } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import CollectionPanel from "./CollectionPanel.vue";
import PresetEditor from "./PresetEditor.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { personalities: vi.fn(), preset: vi.fn(), savePreset: vi.fn() },
}));

const client = vi.mocked(emberlingsClient);

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  client.personalities.mockResolvedValue({ items: [], next_cursor: null });
  client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: [] });
});

function mountPanel(profile: Profile = PROFILE) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = profile;
  return mount(CollectionPanel);
}

describe("CollectionPanel", () => {
  it("shows a card per owned Spark and lists the others as not collected", () => {
    const wrapper = mountPanel({ ...PROFILE, sparks: [ownedSpark("guardian", { copies: 3, tier_id: "rare" })] });

    const cards = wrapper.findAll(".spark-card");
    expect(cards).toHaveLength(1);
    const text = cards[0]!.text();
    expect(text).toContain("Guardian");
    expect(text).toContain("Rare");
    expect(text).toContain("3 copies");
    expect(text).toContain("40 / 300 XP");
    expect(wrapper.findAll(".missing-spark").map((row) => row.find(".missing-name").text())).toEqual([
      "Striker",
      "Bruiser",
      "Forbidden",
    ]);
  });

  it("hides the XP bar at the level cap and counts a faint down", () => {
    const wrapper = mountPanel({
      ...PROFILE,
      sparks: [ownedSpark("guardian", { xp_needed: null, faint_until: Date.now() / 1000 + 65 })],
    });

    const text = wrapper.find(".spark-card").text();
    expect(text).toContain("Highest level reached");
    expect(text).toMatch(/Fainted · ready in 1:0[56]/);
  });

  it("opens a Spark's abilities, personalities (paged) and presets", async () => {
    client.personalities.mockResolvedValueOnce({ items: [{ id: "p1", type: "AGGRESSIVE", tier: 2 }], next_cursor: 7 });
    const wrapper = mountPanel();

    await wrapper.find(".spark-card").trigger("click");
    await flushPromises();

    expect(client.personalities).toHaveBeenCalledWith("guardian", null, 50);
    expect(client.preset).toHaveBeenCalledWith("guardian", 1);
    const details = wrapper.find(".details");
    expect(details.text()).toContain("Strike");
    expect(details.text()).toContain("Unlocks at level 5");
    expect(details.text()).toContain("Aggressive · tier 2");

    client.personalities.mockResolvedValueOnce({ items: [{ id: "p2", type: "CAUTIOUS", tier: 1 }], next_cursor: null });
    await details.findAll("button").find((b) => b.text() === "Show more")!.trigger("click");
    await flushPromises();

    expect(client.personalities).toHaveBeenLastCalledWith("guardian", 7, 50);
    expect(wrapper.find(".details").text()).toContain("Cautious · tier 1");
    expect(wrapper.find(".details").findAll("button").some((b) => b.text() === "Show more")).toBe(false);
  });
});

describe("PresetEditor", () => {
  const items = ["p1", "p2", "p3", "p4"].map((id) => ({ id, type: "BOLD", tier: 1 }));

  it("equips at most three personalities and saves the preset", async () => {
    client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: ["p1"] });
    client.savePreset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: ["p1", "p2", "p3"] });
    const wrapper = mount(PresetEditor, { props: { sparkId: "guardian", personalities: items } });
    await flushPromises();

    const switches = wrapper.findAll("input[role='switch']");
    expect(switches.map((s) => (s.element as HTMLInputElement).checked)).toEqual([true, false, false, false]);
    await switches[1]!.setValue(true);
    await switches[2]!.setValue(true);
    expect((switches[3]!.element as HTMLInputElement).disabled).toBe(true);

    await wrapper.findAll("button").find((b) => b.text() === "Save preset")!.trigger("click");
    await flushPromises();

    expect(client.savePreset).toHaveBeenCalledExactlyOnceWith("guardian", 1, ["p1", "p2", "p3"]);
  });

  it("loads the slot the user picks", async () => {
    const wrapper = mount(PresetEditor, { props: { sparkId: "guardian", personalities: items } });
    await flushPromises();

    await wrapper.findAll("button.segment").find((b) => b.text() === "Preset 3")!.trigger("click");
    await flushPromises();

    expect(client.preset).toHaveBeenLastCalledWith("guardian", 3);
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/utils/emberlings.test.ts src/components/emberlings/CollectionPanel.test.ts`
Expected: both fail to import the new modules.

- [ ] **Step 3: Implement the helpers**

Create `src/utils/emberlings.ts`:

```ts
import type { BattleEvent, FighterAbility, ResultKind, TierInfo } from "../api/EmberlingsClient";

/** How a tier badge is drawn: the three strongest tiers with the accent, the
 * one below them in full text colour, the rest muted. The tier name is always
 * written, so colour is never the only signal. */
export type TierStanding = "top" | "middle" | "low";

export function tierStanding(tiers: readonly Pick<TierInfo, "id">[], tierId: string): TierStanding {
  const index = tiers.findIndex((t) => t.id === tierId);
  if (index === -1) return "low";
  const fromTop = tiers.length - 1 - index;
  if (fromTop <= 2) return "top";
  return fromTop === 3 ? "middle" : "low";
}

/** "knocked_out" -> "Knocked out", "AGGRESSIVE" -> "Aggressive". */
export function titleCase(id: string): string {
  const text = id
    .split("_")
    .filter(Boolean)
    .map((word) => word.toLowerCase())
    .join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Seconds as m:ss (h:mm:ss from an hour), rounded up so 0:00 means done. */
export function formatCountdown(seconds: number): string {
  const total = Math.max(0, Math.ceil(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export const RESULT_LABELS: Record<ResultKind, string> = {
  won: "You won",
  knocked_out: "Your Spark was knocked out",
  captured: "Captured",
  escaped: "You escaped",
  wild_escaped: "The wild Spark escaped",
  forfeited: "You forfeited",
};

export interface SideNames {
  player: string;
  wild: string;
}

function sideName(side: unknown, names: SideNames): string {
  return side === "wild" ? names.wild : names.player;
}

function percent(value: unknown): string {
  return `${Math.round(Number(value) * 100)}%`;
}

/** One line of the round log for an engine event (mini_games' engine.py). */
export function describeEvent(event: BattleEvent, names: SideNames): string {
  const who = sideName(event.side, names);
  switch (event.type) {
    case "order":
      return `${sideName(event.first, names)} moves first`;
    case "attack": {
      const target = sideName(event.side === "wild" ? "player" : "wild", names);
      const defended = event.protected ? " (defended)" : "";
      return `${who} hits for ${String(event.damage)}${defended}; ${target} has ${String(event.target_hp)} HP left`;
    }
    case "defense":
      return `${who} braces (defense ${String(event.rating)})`;
    case "support":
      return `${who} raises ${String(event.stat)} by ${String(event.amount)}`;
    case "flee":
      return `${who} tries to flee (${percent(event.chance)}) and ${event.success ? "gets away" : "fails"}`;
    case "catch_counters_flee":
      return `${who} stops ${sideName(event.target, names)} from fleeing`;
    case "catch_ignored":
      return `${who} tries to catch, to no effect`;
    case "capture_attempt":
      return `${who} throws a ${titleCase(String(event.emblem))} EMBLEM (${percent(event.chance)}): ${event.success ? "caught" : "it broke free"}`;
    default:
      return titleCase(event.type);
  }
}

/** A history action key in words: "ability:<id>" -> the ability's name. */
export function describeAction(key: string, abilities: readonly Pick<FighterAbility, "id" | "name">[]): string {
  if (key.startsWith("ability:")) {
    const id = key.slice("ability:".length);
    return abilities.find((a) => a.id === id)?.name ?? titleCase(id);
  }
  return titleCase(key);
}
```

Create `src/composables/useNowSeconds.ts`:

```ts
import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";

/** Wall-clock epoch seconds (the unit of mini_games' timestamps), updated
 * every second while the component is mounted. */
export function useNowSeconds(): Ref<number> {
  const now = ref(Date.now() / 1000);
  let timer: ReturnType<typeof setInterval> | null = null;
  onMounted(() => {
    timer = setInterval(() => {
      now.value = Date.now() / 1000;
    }, 1000);
  });
  onBeforeUnmount(() => {
    if (timer !== null) clearInterval(timer);
  });
  return now;
}
```

- [ ] **Step 4: Implement the components**

Create `src/components/emberlings/TierBadge.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { tierStanding, titleCase } from "../../utils/emberlings";

/** A tier's name as a badge; the strongest tiers carry the accent. */
const props = defineProps<{ tierId: string }>();
const store = useEmberlingsStore();
const standing = computed(() => tierStanding(store.catalog?.tiers ?? [], props.tierId));
</script>

<template>
  <span class="tier-badge" :class="standing">{{ titleCase(tierId) }}</span>
</template>

<style scoped>
.tier-badge {
  display: inline-block;
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.75em;
  font-weight: 600;
  white-space: nowrap;
  color: var(--muted);
  background: var(--code-bg);
}
.tier-badge.middle {
  border-color: var(--text);
  color: var(--text);
}
.tier-badge.top {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
</style>
```

Create `src/components/emberlings/SparkCard.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import type { OwnedSpark } from "../../api/EmberlingsClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { formatCountdown } from "../../utils/emberlings";
import TierBadge from "./TierBadge.vue";

/** One owned Spark on the Collection tab; a click opens its details. */
const props = defineProps<{ spark: OwnedSpark }>();
const emit = defineEmits<{ open: [] }>();
const now = useNowSeconds();
const faintLeft = computed(() => (props.spark.faint_until === null ? 0 : Math.max(0, props.spark.faint_until - now.value)));
const xpPercent = computed(() =>
  props.spark.xp_needed ? Math.min(100, (props.spark.xp / props.spark.xp_needed) * 100) : 100,
);
</script>

<template>
  <button type="button" class="spark-card" @click="emit('open')">
    <span class="head">
      <span class="spark-name">{{ spark.name }}</span>
      <TierBadge :tier-id="spark.tier_id" />
    </span>
    <span class="meta">Level {{ spark.level }} · {{ spark.copies }} {{ spark.copies === 1 ? "copy" : "copies" }}</span>
    <span v-if="spark.xp_needed !== null" class="xp">
      <span class="xp-track" aria-hidden="true"><span class="xp-fill" :style="{ width: `${xpPercent}%` }" /></span>
      <span class="meta">{{ spark.xp }} / {{ spark.xp_needed }} XP</span>
    </span>
    <span v-else class="meta">Highest level reached</span>
    <span v-if="faintLeft > 0" class="fainted">Fainted · ready in {{ formatCountdown(faintLeft) }}</span>
  </button>
</template>

<style scoped>
.spark-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  background: var(--surface);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.spark-card:hover {
  border-color: var(--accent);
}
.spark-card:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.spark-name {
  font-weight: 600;
}
.meta {
  font-size: 0.85em;
  color: var(--muted);
}
.xp {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.xp-track {
  display: block;
  height: 6px;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--code-bg);
}
.xp-fill {
  display: block;
  height: 100%;
  background: var(--accent);
}
.fainted {
  font-size: 0.85em;
  color: var(--warning);
}
@media (prefers-reduced-motion: reduce) {
  .spark-card {
    transition: none;
  }
}
</style>
```

Create `src/components/emberlings/PresetEditor.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { emberlingsClient, type PersonalityItem } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import { errorMessage } from "../../utils/errors";
import { titleCase } from "../../utils/emberlings";
import SegmentedControl from "../SegmentedControl.vue";
import ToggleSwitch from "../ToggleSwitch.vue";

/** A Spark's five presets: up to three personality instances each. An
 * autonomous Spark lets one of them lead each round. */
const props = defineProps<{ sparkId: string; personalities: PersonalityItem[] }>();
const store = useEmberlingsStore();

const MAX_EQUIPPED = 3;
const SLOT_OPTIONS = [1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `Preset ${n}` }));

const slot = ref("1");
const chosen = ref<string[]>([]);
const saved = ref<string[]>([]);
const loading = ref(false);
const loadError = ref("");
const dirty = computed(() => chosen.value.join(",") !== saved.value.join(","));

async function load(): Promise<void> {
  const sparkId = props.sparkId;
  const wanted = slot.value;
  loading.value = true;
  loadError.value = "";
  try {
    const preset = await emberlingsClient.preset(sparkId, Number(wanted));
    if (sparkId !== props.sparkId || wanted !== slot.value) return;
    saved.value = preset.instance_ids;
    chosen.value = [...preset.instance_ids];
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

watch([() => props.sparkId, slot], () => void load(), { immediate: true });

function toggle(id: string, on: boolean): void {
  if (on && !chosen.value.includes(id) && chosen.value.length < MAX_EQUIPPED) chosen.value = [...chosen.value, id];
  else if (!on) chosen.value = chosen.value.filter((c) => c !== id);
}

async function save(): Promise<void> {
  const preset = await store.savePreset(props.sparkId, Number(slot.value), chosen.value);
  if (preset) {
    saved.value = preset.instance_ids;
    chosen.value = [...preset.instance_ids];
  }
}
</script>

<template>
  <section class="preset-editor">
    <h4>Presets</h4>
    <SegmentedControl v-model="slot" :options="SLOT_OPTIONS" aria-label="Preset slot" />
    <p class="muted hint">Up to {{ MAX_EQUIPPED }} personalities. An autonomous Spark lets one of them lead each round.</p>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <p v-else-if="loading" class="muted">Loading …</p>
    <p v-else-if="personalities.length === 0" class="muted">This Spark has no personalities yet.</p>
    <ul v-else class="choices">
      <li v-for="p in personalities" :key="p.id">
        <ToggleSwitch
          small
          :checked="chosen.includes(p.id)"
          :disabled="!chosen.includes(p.id) && chosen.length >= MAX_EQUIPPED"
          @change="toggle(p.id, ($event.target as HTMLInputElement).checked)"
        >
          {{ titleCase(p.type) }} · tier {{ p.tier }}
        </ToggleSwitch>
      </li>
    </ul>
    <button type="button" class="primary" :disabled="!dirty || store.busy" @click="save">Save preset</button>
  </section>
</template>

<style scoped>
.preset-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
}
h4 {
  margin: 0;
}
.hint {
  margin: 0;
  font-size: 0.85em;
}
.choices {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.primary {
  align-self: flex-start;
}
</style>
```

Create `src/components/emberlings/CollectionPanel.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import { emberlingsClient, type OwnedSpark, type PersonalityItem } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import { errorMessage } from "../../utils/errors";
import { titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import PresetEditor from "./PresetEditor.vue";
import SparkCard from "./SparkCard.vue";
import TierBadge from "./TierBadge.vue";

/** The Collection tab: owned Sparks as cards, the rest of the catalog greyed
 * out, and a card's details (abilities, personalities, presets) in a dialog. */
const store = useEmberlingsStore();
const PAGE_SIZE = 50;

const owned = computed(() => store.profile?.sparks ?? []);
const notOwned = computed(() => {
  const ids = new Set(owned.value.map((s) => s.spark_id));
  return (store.catalog?.sparks ?? []).filter((s) => !ids.has(s.id));
});

const open = ref<OwnedSpark | null>(null);
const abilities = computed(() => store.catalog?.sparks.find((s) => s.id === open.value?.spark_id)?.abilities ?? []);
const personalities = ref<PersonalityItem[]>([]);
const nextCursor = ref<number | null>(null);
const loadingMore = ref(false);
const detailError = ref("");

async function loadPersonalities(cursor: number | null): Promise<void> {
  const spark = open.value;
  if (spark === null) return;
  loadingMore.value = true;
  detailError.value = "";
  try {
    const page = await emberlingsClient.personalities(spark.spark_id, cursor, PAGE_SIZE);
    if (open.value?.spark_id !== spark.spark_id) return;
    personalities.value = cursor === null ? page.items : [...personalities.value, ...page.items];
    nextCursor.value = page.next_cursor;
  } catch (err) {
    detailError.value = errorMessage(err);
  } finally {
    loadingMore.value = false;
  }
}

function show(spark: OwnedSpark): void {
  open.value = spark;
  personalities.value = [];
  nextCursor.value = null;
  void loadPersonalities(null);
}
</script>

<template>
  <section class="collection">
    <h3>Your Sparks</h3>
    <div class="grid">
      <SparkCard v-for="spark in owned" :key="spark.spark_id" :spark="spark" @open="show(spark)" />
    </div>

    <template v-if="notOwned.length">
      <h3>Not collected yet</h3>
      <ul class="missing">
        <li v-for="spark in notOwned" :key="spark.id" class="missing-spark">
          <span class="missing-name">{{ spark.name }}</span>
          <span class="muted">{{ spark.forbidden ? "Only by capture" : "Catch one, or buy copies in the shop" }}</span>
        </li>
      </ul>
    </template>

    <BaseModal :open="open !== null" :title="open?.name ?? ''" @close="open = null">
      <div v-if="open" class="details">
        <p class="muted level">Level {{ open.level }} of {{ open.level_cap }} <TierBadge :tier-id="open.tier_id" /></p>

        <h4>Abilities</h4>
        <ul class="abilities">
          <li v-for="a in abilities" :key="a.id" :class="{ locked: a.unlock_level > open.level }">
            <span class="ability-name">{{ a.name }}</span>
            <span class="muted">{{ titleCase(a.category) }} · {{ a.percentage }}% · cooldown {{ a.cooldown }}</span>
            <span class="muted">
              {{ a.unlock_level > open.level ? `Unlocks at level ${a.unlock_level}` : `Unlocked at level ${a.unlock_level}` }}
            </span>
          </li>
        </ul>

        <h4>Personalities</h4>
        <p v-if="detailError" class="error">{{ detailError }}</p>
        <ul v-if="personalities.length" class="personalities">
          <li v-for="p in personalities" :key="p.id">{{ titleCase(p.type) }} · tier {{ p.tier }}</li>
        </ul>
        <p v-else-if="!loadingMore" class="muted">None collected yet.</p>
        <button v-if="nextCursor !== null" type="button" class="chip" :disabled="loadingMore" @click="loadPersonalities(nextCursor)">
          Show more
        </button>

        <PresetEditor :spark-id="open.spark_id" :personalities="personalities" />
      </div>
    </BaseModal>
  </section>
</template>

<style scoped>
.collection h3 {
  margin: 20px 0 10px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.missing {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.missing-spark {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 12px;
  padding: 8px 12px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  opacity: 0.6;
}
.details h4 {
  margin: 14px 0 6px;
}
.level {
  display: flex;
  align-items: center;
  gap: 8px;
}
.abilities,
.personalities {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.abilities li {
  display: flex;
  flex-direction: column;
}
.abilities li.locked {
  opacity: 0.6;
}
.ability-name {
  font-weight: 600;
}
</style>
```

- [ ] **Step 5: Run the tests, the type-check and the radius guard**

Run: `npx vitest run src/utils/emberlings.test.ts src/components/emberlings/CollectionPanel.test.ts src/radiusScale.test.ts`, then `npm test`, then `npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 6: Report and commit (after the user agrees)**

```bash
git add apps/Ember/ember_web/src/utils/emberlings.ts apps/Ember/ember_web/src/utils/emberlings.test.ts apps/Ember/ember_web/src/composables/useNowSeconds.ts apps/Ember/ember_web/src/components/emberlings/TierBadge.vue apps/Ember/ember_web/src/components/emberlings/SparkCard.vue apps/Ember/ember_web/src/components/emberlings/PresetEditor.vue apps/Ember/ember_web/src/components/emberlings/CollectionPanel.vue apps/Ember/ember_web/src/components/emberlings/CollectionPanel.test.ts
git commit -m "feat(ember-web): Emberlings collection tab components"
```

### Task B4: Battle tab, part 1: `EncounterPanel` (look, preview, decline, start form)

**Files:**
- Create: `apps/Ember/ember_web/src/components/emberlings/EncounterPanel.vue`
- Test: `apps/Ember/ember_web/src/components/emberlings/EncounterPanel.test.ts`

**Interfaces:**
- Consumes: `useEmberlingsStore()` (`catalog`, `profile`, `encounter`, `busy`, `rollEncounter()`, `declineEncounter()`, `startBattle(input)`); `useNowSeconds()`, `formatCountdown`, `titleCase` (B3); `TierBadge` (B3); `BaseModal`, `SegmentedControl`.
- Produces: `<EncounterPanel />` (no props). Test hooks: `form.start-form`, `select[name='spark']`, `select[name='preset']`, `select[name='limit']`.

- [ ] **Step 1: Write the failing tests**

Create `src/components/emberlings/EncounterPanel.test.ts`:

```ts
import { flushPromises, mount, type DOMWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type EncounterPreview, type Profile } from "../../api/EmberlingsClient";
import { CATALOG, ENCOUNTER, PROFILE, battleView, ownedSpark } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import EncounterPanel from "./EncounterPanel.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { rollEncounter: vi.fn(), declineEncounter: vi.fn(), startBattle: vi.fn(), profile: vi.fn() },
}));

const client = vi.mocked(emberlingsClient);

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  client.profile.mockResolvedValue(PROFILE);
});

function mountPanel(profile: Profile = PROFILE, encounter: EncounterPreview | null = null) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = profile;
  store.encounter = encounter;
  return { store, wrapper: mount(EncounterPanel) };
}

/** The first of `buttons` whose text is `text` (or matches it). */
function button(buttons: DOMWrapper<HTMLButtonElement>[], text: string | RegExp): DOMWrapper<HTMLButtonElement> {
  const found = buttons.find((b) => (typeof text === "string" ? b.text() === text : text.test(b.text())));
  if (!found) throw new Error(`no button ${String(text)}`);
  return found;
}

describe("EncounterPanel", () => {
  it("looks for a wild Spark once the cooldown is over", async () => {
    client.rollEncounter.mockResolvedValue(ENCOUNTER);
    const { store, wrapper } = mountPanel();

    const look = button(wrapper.findAll("button"), "Look for a wild Spark");
    expect(look.attributes("disabled")).toBeUndefined();
    await look.trigger("click");
    await flushPromises();

    expect(client.rollEncounter).toHaveBeenCalledOnce();
    expect(store.encounter?.id).toBe("e1");
    expect(wrapper.text()).toContain("A wild Bruiser");
  });

  it("waits out the cooldown with a countdown", () => {
    const { wrapper } = mountPanel({ ...PROFILE, next_roll_at: Date.now() / 1000 + 20 });

    const look = button(wrapper.findAll("button"), /Look again in/);
    expect(look.text()).toMatch(/Look again in 0:(19|20)/);
    expect(look.attributes("disabled")).toBeDefined();
  });

  it("declines for free", async () => {
    client.declineEncounter.mockResolvedValue({ ...ENCOUNTER, status: "declined" });
    const { store, wrapper } = mountPanel(PROFILE, ENCOUNTER);
    expect(wrapper.text()).toContain("Level 4");

    await button(wrapper.findAll("button"), "Decline").trigger("click");
    await flushPromises();

    expect(client.declineEncounter).toHaveBeenCalledExactlyOnceWith("e1");
    expect(store.encounter).toBeNull();
  });

  it("cannot fight while every Spark is fainted", () => {
    const { wrapper } = mountPanel(
      { ...PROFILE, sparks: [ownedSpark("guardian", { faint_until: Date.now() / 1000 + 600, fainted: true })] },
      ENCOUNTER,
    );

    expect(button(wrapper.findAll("button"), "Fight").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("All your Sparks are fainted");
  });

  it("starts an autonomous battle only with a preset and an EMBLEM limit", async () => {
    client.startBattle.mockResolvedValue(battleView());
    const { wrapper } = mountPanel(PROFILE, ENCOUNTER);

    await button(wrapper.findAll("button"), "Fight").trigger("click");
    const form = wrapper.find("form.start-form");
    await button(form.findAll("button"), "Autonomous").trigger("click");
    const submit = form.find("button[type='submit']");
    expect(submit.attributes("disabled")).toBeDefined();
    expect(form.text()).toContain("Autonomous play needs a preset and an EMBLEM limit.");

    await form.find("select[name='preset']").setValue("2");
    await form.find("select[name='limit']").setValue("rare");
    expect(submit.attributes("disabled")).toBeUndefined();
    await form.trigger("submit");
    await flushPromises();

    expect(client.startBattle).toHaveBeenCalledExactlyOnceWith({
      encounter_id: "e1",
      spark_id: "guardian",
      preset_slot: 2,
      mode: "autonomous",
      emblem_limit: "rare",
    });
  });

  it("starts a manual battle with no preset and no limit", async () => {
    client.startBattle.mockResolvedValue(battleView({ mode: "manual" }));
    const { wrapper } = mountPanel(PROFILE, ENCOUNTER);

    await button(wrapper.findAll("button"), "Fight").trigger("click");
    await wrapper.find("form.start-form").trigger("submit");
    await flushPromises();

    expect(client.startBattle).toHaveBeenCalledExactlyOnceWith({
      encounter_id: "e1",
      spark_id: "guardian",
      preset_slot: null,
      mode: "manual",
      emblem_limit: null,
    });
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/components/emberlings/EncounterPanel.test.ts`
Expected: fails to import `./EncounterPanel.vue`.

- [ ] **Step 3: Implement**

Create `src/components/emberlings/EncounterPanel.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import type { BattleMode } from "../../api/EmberlingsClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { useEmberlingsStore } from "../../stores/emberlings";
import { formatCountdown, titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import SegmentedControl from "../SegmentedControl.vue";
import TierBadge from "./TierBadge.vue";

/** The Battle tab without a battle: look for a wild Spark (once the cooldown
 * is over), then decline it for free or fight it. Fight asks which Spark,
 * which preset, who plays and the highest EMBLEM tier the Spark may throw on
 * its own. mini_games needs a preset and a limit for autonomous play. */
const store = useEmberlingsStore();
const now = useNowSeconds();

const MODE_OPTIONS: { value: BattleMode; label: string }[] = [
  { value: "manual", label: "Manual" },
  { value: "autonomous", label: "Autonomous" },
];
const PRESET_SLOTS = [1, 2, 3, 4, 5];

const rollWait = computed(() => {
  const at = store.profile?.next_roll_at ?? null;
  return at === null ? 0 : Math.max(0, at - now.value);
});
const ready = computed(() =>
  (store.profile?.sparks ?? []).filter((s) => s.faint_until === null || s.faint_until <= now.value),
);
const tiers = computed(() => store.catalog?.tiers ?? []);

const formOpen = ref(false);
const sparkId = ref("");
const presetSlot = ref("none");
const mode = ref<BattleMode>("manual");
const emblemLimit = ref("none");
const autonomousIncomplete = computed(
  () => mode.value === "autonomous" && (presetSlot.value === "none" || emblemLimit.value === "none"),
);
const canFight = computed(() => sparkId.value !== "" && !autonomousIncomplete.value && !store.busy);

function openForm(): void {
  sparkId.value = ready.value[0]?.spark_id ?? "";
  presetSlot.value = "none";
  mode.value = "manual";
  emblemLimit.value = "none";
  formOpen.value = true;
}

async function fight(): Promise<void> {
  const current = store.encounter;
  if (current === null || !canFight.value) return;
  const view = await store.startBattle({
    encounter_id: current.id,
    spark_id: sparkId.value,
    preset_slot: presetSlot.value === "none" ? null : Number(presetSlot.value),
    mode: mode.value,
    emblem_limit: emblemLimit.value === "none" ? null : emblemLimit.value,
  });
  if (view !== null) formOpen.value = false;
}
</script>

<template>
  <section class="encounter-panel">
    <div v-if="!store.encounter" class="card look">
      <p class="muted">Wild Sparks roam nearby. Looking is free; you can look again after a short rest.</p>
      <button type="button" class="primary" :disabled="rollWait > 0 || store.busy" @click="store.rollEncounter()">
        {{ rollWait > 0 ? `Look again in ${formatCountdown(rollWait)}` : "Look for a wild Spark" }}
      </button>
    </div>

    <div v-else class="card preview">
      <div class="card-head">
        <h3>A wild {{ store.encounter.name }}</h3>
        <TierBadge :tier-id="store.encounter.tier_id" />
      </div>
      <p class="muted">Level {{ store.encounter.level }}. Its personalities stay hidden until you capture it.</p>
      <div class="buttons">
        <button type="button" class="chip" :disabled="store.busy" @click="store.declineEncounter()">Decline</button>
        <button type="button" class="primary" :disabled="store.busy || ready.length === 0" @click="openForm">Fight</button>
      </div>
      <p v-if="ready.length === 0" class="muted">All your Sparks are fainted. Wait until one is ready again.</p>
    </div>

    <BaseModal :open="formOpen" title="Start the battle" @close="formOpen = false">
      <form class="start-form" @submit.prevent="fight">
        <label>
          <span>Spark</span>
          <select v-model="sparkId" name="spark">
            <option v-for="s in ready" :key="s.spark_id" :value="s.spark_id">{{ s.name }} (level {{ s.level }})</option>
          </select>
        </label>
        <label>
          <span>Preset</span>
          <select v-model="presetSlot" name="preset">
            <option value="none">None</option>
            <option v-for="n in PRESET_SLOTS" :key="n" :value="String(n)">Preset {{ n }}</option>
          </select>
        </label>
        <SegmentedControl v-model="mode" :options="MODE_OPTIONS" label="Who plays" />
        <label>
          <span>EMBLEM limit</span>
          <select v-model="emblemLimit" name="limit">
            <option value="none">None</option>
            <option v-for="t in tiers" :key="t.id" :value="t.id">{{ titleCase(t.id) }}</option>
          </select>
        </label>
        <p class="muted hint">The highest EMBLEM tier your Spark may throw on its own.</p>
        <p v-if="autonomousIncomplete" class="error">Autonomous play needs a preset and an EMBLEM limit.</p>
        <div class="buttons">
          <button type="button" class="chip" @click="formOpen = false">Cancel</button>
          <button type="submit" class="primary" :disabled="!canFight">Fight</button>
        </div>
      </form>
    </BaseModal>
  </section>
</template>

<style scoped>
.look,
.preview {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}
.look p,
.preview p {
  margin: 0;
}
.preview .card-head {
  width: 100%;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.start-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.start-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.9em;
}
.start-form select {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.start-form select:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.hint {
  margin: -6px 0 0;
  font-size: 0.85em;
}
.start-form .buttons {
  justify-content: flex-end;
}
</style>
```

- [ ] **Step 4: Run the tests and the type-check**

Run: `npx vitest run src/components/emberlings/EncounterPanel.test.ts src/radiusScale.test.ts`, then `npm test`, then `npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Report and commit (after the user agrees)**

```bash
git add apps/Ember/ember_web/src/components/emberlings/EncounterPanel.vue apps/Ember/ember_web/src/components/emberlings/EncounterPanel.test.ts
git commit -m "feat(ember-web): Emberlings encounter panel"
```

### Task B5: Battle tab, part 2: arena, actions, EMBLEM prompt, result

**Files:**
- Modify: `apps/Ember/ember_web/src/components/SegmentedControl.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/HealthBar.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/RoundLog.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/BattleArena.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/ActionBar.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/EmblemPrompt.vue`
- Create: `apps/Ember/ember_web/src/components/emberlings/BattleResult.vue`
- Test: `apps/Ember/ember_web/src/components/emberlings/BattlePanels.test.ts`

**Interfaces:**
- Consumes: `useEmberlingsStore()` (`catalog`, `battle`, `battleBusy`, `promptOpen`, `promptRemaining`, `promptTotal`, `act`, `answerEmblem`, `setMode`, `forfeit`, `closeBattle`), `ROUND_PACE_MS`; `describeEvent`, `describeAction`, `titleCase`, `RESULT_LABELS` (B3); `TierBadge` (B3); `BaseModal`, `ConfirmModal`, `CountdownRing`, `SegmentedControl`.
- Produces:
  - `SegmentedControl` options accept `disabled?: boolean` (the button gets `disabled`)
  - `<HealthBar :hp :max-hp :label>` (`role="meter"`), `<RoundLog :battle>`, `<BattleArena :battle>` (`.arena`), `<ActionBar :battle>` (`button.action`, `.action-name`), `<EmblemPrompt />`, `<BattleResult :battle>` (`.battle-result`)

- [ ] **Step 1: Write the failing tests**

Create `src/components/emberlings/BattlePanels.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type BattleView } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, battleView, fighter } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import ActionBar from "./ActionBar.vue";
import BattleArena from "./BattleArena.vue";
import BattleResult from "./BattleResult.vue";
import EmblemPrompt from "./EmblemPrompt.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { action: vi.fn(), emblem: vi.fn(), setMode: vi.fn(), forfeit: vi.fn(), profile: vi.fn() },
}));

const client = vi.mocked(emberlingsClient);

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  client.profile.mockResolvedValue(PROFILE);
});

function withBattle(view: BattleView) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = PROFILE;
  store.battle = view;
  return store;
}

const manual = () =>
  battleView({
    mode: "manual",
    player: fighter("guardian", {
      abilities: [
        { id: "guardian_strike", name: "Strike", category: "ATTACK", percentage: 120, cooldown: 1, ready: true },
        { id: "guardian_rally", name: "Rally", category: "SUPPORT", percentage: 50, cooldown: 3, ready: false },
      ],
    }),
  });

describe("BattleArena", () => {
  it("shows both Sparks, their health and the round log in words", () => {
    const view = battleView({
      wild: fighter("bruiser", { hp: 20, buffs: [{ source: "bruiser_rally", stat: "essence", amount: 4, rounds_left: 2 }] }),
      history: [
        {
          round: 1,
          actions: { player: ["ability:guardian_strike", "ATTACK"], wild: ["attack", "ATTACK"] },
          events: [{ type: "attack", side: "player", damage: 18, protected: false, target_hp: 20 }],
        },
      ],
    });
    withBattle(view);

    const wrapper = mount(BattleArena, { props: { battle: view } });

    expect(wrapper.findAll("[role='meter']").map((m) => m.attributes("aria-valuenow"))).toEqual(["80", "20"]);
    expect(wrapper.text()).toContain("+4 essence, 2 rounds left");
    const log = wrapper.find(".round-log").text();
    expect(log).toContain("Round 1: Guardian chose Strike, Bruiser chose Attack");
    expect(log).toContain("Guardian hits for 18; Bruiser has 20 HP left");
  });
});

describe("ActionBar", () => {
  it("offers one button per legal action and shows abilities cooling down", () => {
    const view = manual();
    withBattle(view);

    const wrapper = mount(ActionBar, { props: { battle: view } });

    const buttons = wrapper.findAll("button.action");
    expect(buttons.map((b) => b.find(".action-name").text())).toEqual(["Attack", "Strike", "Flee", "Catch", "Rally"]);
    expect(buttons[1]!.attributes("disabled")).toBeUndefined();
    expect(buttons[4]!.attributes("disabled")).toBeDefined();
    expect(buttons[4]!.text()).toContain("Cooling down (3 rounds)");
  });

  it("sends the chosen action with the round and revision it saw", async () => {
    const view = manual();
    withBattle(view);
    client.action.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 2 }));
    const wrapper = mount(ActionBar, { props: { battle: view } });

    await wrapper.findAll("button.action")[1]!.trigger("click");
    await flushPromises();

    expect(client.action).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, { kind: "ability", ability_id: "guardian_strike" });
  });

  it("asks which EMBLEM to throw for a catch", async () => {
    const view = manual();
    withBattle(view);
    client.action.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 2 }));
    const wrapper = mount(ActionBar, { props: { battle: view } });

    await wrapper.findAll("button.action")[3]!.trigger("click");
    expect(client.action).not.toHaveBeenCalled();
    await wrapper.findAll("button").find((b) => b.text() === "Normal (2)")!.trigger("click");
    await flushPromises();

    expect(client.action).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, { kind: "catch", emblem_tier: "normal" });
  });

  it("keeps a battle without an EMBLEM limit manual", async () => {
    const view = battleView({ mode: "manual", emblem_limit: null });
    withBattle(view);
    const wrapper = mount(ActionBar, { props: { battle: view } });

    const autonomous = wrapper.findAll("button.segment").find((b) => b.text() === "Autonomous")!;
    expect(autonomous.attributes("disabled")).toBeDefined();
    await autonomous.trigger("click");

    expect(client.setMode).not.toHaveBeenCalled();
  });

  it("switches to autonomous between rounds", async () => {
    const view = battleView({ mode: "manual" });
    withBattle(view);
    client.setMode.mockResolvedValue(battleView());
    const wrapper = mount(ActionBar, { props: { battle: view } });

    await wrapper.findAll("button.segment").find((b) => b.text() === "Autonomous")!.trigger("click");
    await flushPromises();

    expect(client.setMode).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, "autonomous", null);
  });

  it("forfeits only after confirming", async () => {
    const view = manual();
    withBattle(view);
    client.forfeit.mockResolvedValue(
      battleView({ status: "terminal", phase: "terminal", result: { kind: "forfeited", faint_until: 1_700_000_600 } }),
    );
    const wrapper = mount(ActionBar, { props: { battle: view } });

    await wrapper.find("button.danger").trigger("click");
    expect(client.forfeit).not.toHaveBeenCalled();
    await wrapper.find("button.confirm").trigger("click");
    await flushPromises();

    expect(client.forfeit).toHaveBeenCalledExactlyOnceWith("b1");
  });
});

describe("EmblemPrompt", () => {
  const prompting = () =>
    battleView({
      phase: "awaiting_emblem",
      revision: 4,
      prompt: { deadline: 0, seconds_left: 5, permitted_tiers: ["normal"], owned: { normal: 2 } },
    });

  it("offers the permitted tiers with their counts while time is left", async () => {
    const store = withBattle(prompting());
    store.promptRemaining = 3.2;
    store.promptTotal = 5;
    client.emblem.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 5 }));
    const wrapper = mount(EmblemPrompt);

    expect(wrapper.text()).toContain("4 s left");
    await wrapper.findAll("button").find((b) => b.text() === "Normal (2)")!.trigger("click");
    await flushPromises();

    expect(client.emblem).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 }, "normal");
  });

  it("disables the tiers at zero", () => {
    const store = withBattle(prompting());
    store.promptRemaining = 0;
    store.promptTotal = 5;

    const wrapper = mount(EmblemPrompt);

    expect(wrapper.text()).toContain("Time is up");
    expect(wrapper.findAll("button").find((b) => b.text() === "Normal (2)")!.attributes("disabled")).toBeDefined();
  });
});

describe("BattleResult", () => {
  it("shows a capture with the personalities it revealed, and Back leaves it", async () => {
    const view = battleView({
      status: "terminal",
      phase: "terminal",
      result: {
        kind: "captured",
        xp: 30,
        insignia: 12,
        level_before: 3,
        level_after: 4,
        spark_id: "bruiser",
        copies_granted: 2,
        copies: 2,
        tier_id: "rare",
        awarded_personality: { id: "w2", type: "BOLD", tier: 2 },
        revealed_personalities: [
          { id: "w1", type: "CAUTIOUS", tier: 1 },
          { id: "w2", type: "BOLD", tier: 2 },
        ],
      },
    });
    const store = withBattle(view);
    const wrapper = mount(BattleResult, { props: { battle: view } });

    const text = wrapper.text();
    expect(text).toContain("Captured");
    expect(text).toContain("+30 XP for Guardian, now level 4");
    expect(text).toContain("+12 Insignia");
    expect(text).toContain("+2 copies of Bruiser, now Rare");
    expect(text).toContain("Cautious · tier 1");
    expect(text).toContain("Bold · tier 2 (now yours)");

    await wrapper.findAll("button").find((b) => b.text() === "Back")!.trigger("click");
    await flushPromises();

    expect(store.battle).toBeNull();
    expect(client.profile).toHaveBeenCalledOnce();
  });

  it("says when the Spark fainted", () => {
    const view = battleView({ status: "terminal", phase: "terminal", result: { kind: "knocked_out", faint_until: 1_700_000_600 } });
    withBattle(view);

    const text = mount(BattleResult, { props: { battle: view } }).text();

    expect(text).toContain("Your Spark was knocked out");
    expect(text).toContain("Guardian fainted and needs rest before its next battle.");
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/components/emberlings/BattlePanels.test.ts`
Expected: fails to import the new components.

- [ ] **Step 3: Give `SegmentedControl` a per-option disabled state**

In `src/components/SegmentedControl.vue`:

1. Replace `options: readonly { value: T; label: string }[];` with:

```ts
  options: readonly { value: T; label: string; disabled?: boolean }[];
```

2. In the template's `<button ...>`, below `:aria-pressed="o.value === model"` add:

```vue
      :disabled="o.disabled"
```

3. Replace

```css
button.segment:hover {
  color: var(--accent);
}
```

with

```css
button.segment:hover:not(:disabled) {
  color: var(--accent);
}
button.segment:disabled {
  cursor: default;
  opacity: 0.45;
}
```

- [ ] **Step 4: Implement the components**

Create `src/components/emberlings/HealthBar.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";

/** A fighter's health as a meter, with the numbers written beside it. */
const props = defineProps<{ hp: number; maxHp: number; label: string }>();
const percent = computed(() => (props.maxHp > 0 ? Math.max(0, Math.min(100, (props.hp / props.maxHp) * 100)) : 0));
const low = computed(() => percent.value <= 25);
</script>

<template>
  <div class="health-bar">
    <div class="track" role="meter" :aria-label="label" aria-valuemin="0" :aria-valuemax="maxHp" :aria-valuenow="hp">
      <div class="fill" :class="{ low }" :style="{ width: `${percent}%` }" />
    </div>
    <span class="numbers">{{ hp }} / {{ maxHp }} HP</span>
  </div>
</template>

<style scoped>
.health-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.track {
  flex: 1;
  height: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--code-bg);
}
.fill {
  height: 100%;
  background: var(--success);
  transition: width 0.15s ease;
}
.fill.low {
  background: var(--danger);
}
.numbers {
  font-size: 0.85em;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--muted);
}
@media (prefers-reduced-motion: reduce) {
  .fill {
    transition: none;
  }
}
</style>
```

Create `src/components/emberlings/RoundLog.vue`:

```vue
<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { BattleView } from "../../api/EmberlingsClient";
import { describeAction, describeEvent } from "../../utils/emberlings";

/** The battle's revealed rounds in words, oldest first; new rounds scroll into view. */
const props = defineProps<{ battle: BattleView }>();
const names = computed(() => ({ player: props.battle.player.name, wild: props.battle.wild.name }));
const list = ref<HTMLElement | null>(null);

watch(
  () => props.battle.history.length,
  async () => {
    await nextTick();
    if (list.value) list.value.scrollTop = list.value.scrollHeight;
  },
);
</script>

<template>
  <section class="round-log">
    <h4>Round log</h4>
    <p v-if="battle.history.length === 0" class="muted">No rounds yet.</p>
    <ol v-else ref="list" class="rounds" aria-live="polite">
      <li v-for="entry in battle.history" :key="entry.round">
        <p class="round-title">
          Round {{ entry.round }}: {{ names.player }} chose {{ describeAction(entry.actions.player[0], battle.player.abilities) }},
          {{ names.wild }} chose {{ describeAction(entry.actions.wild[0], battle.wild.abilities) }}
        </p>
        <ul class="events">
          <li v-for="(event, index) in entry.events" :key="index">{{ describeEvent(event, names) }}</li>
        </ul>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.round-log h4 {
  margin: 0 0 6px;
}
.rounds {
  max-height: 260px;
  margin: 0;
  padding: 8px 12px 8px 32px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
}
.round-title {
  margin: 6px 0 2px;
  font-weight: 600;
}
.events {
  margin: 0;
  padding-left: 18px;
  font-size: 0.9em;
  color: var(--muted);
}
</style>
```

Create `src/components/emberlings/BattleArena.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import type { Buff, BattleView, Fighter } from "../../api/EmberlingsClient";
import HealthBar from "./HealthBar.vue";
import RoundLog from "./RoundLog.vue";
import TierBadge from "./TierBadge.vue";

/** Both Sparks side by side (name, tier, level, health, essence, speed,
 * buffs, defense) above the round log. Text only, no art. */
const props = defineProps<{ battle: BattleView }>();

const sides = computed<{ key: string; label: string; fighter: Fighter }[]>(() => [
  { key: "player", label: "Your Spark", fighter: props.battle.player },
  { key: "wild", label: "Wild Spark", fighter: props.battle.wild },
]);

function buffText(buff: Buff): string {
  const lasting =
    buff.rounds_left === null ? " for the whole battle" : `, ${buff.rounds_left} ${buff.rounds_left === 1 ? "round" : "rounds"} left`;
  return `+${buff.amount} ${buff.stat}${lasting}`;
}
</script>

<template>
  <section class="arena">
    <p class="muted round">Round {{ battle.round }} · {{ battle.mode === "autonomous" ? "Autonomous" : "Manual" }}</p>
    <div class="fighters">
      <article v-for="side in sides" :key="side.key" class="card fighter" :aria-label="`${side.label}: ${side.fighter.name}`">
        <div class="card-head">
          <h3>{{ side.fighter.name }}</h3>
          <TierBadge :tier-id="side.fighter.tier_id" />
        </div>
        <p class="muted">{{ side.label }} · level {{ side.fighter.level }}</p>
        <HealthBar :hp="side.fighter.hp" :max-hp="side.fighter.max_hp" :label="`${side.fighter.name} health`" />
        <p class="stats">Essence {{ side.fighter.essence }} · Speed {{ side.fighter.speed }}</p>
        <ul v-if="side.fighter.buffs.length" class="effects">
          <li v-for="(buff, index) in side.fighter.buffs" :key="index">{{ buffText(buff) }}</li>
        </ul>
        <p v-if="side.fighter.defense" class="effects">
          Defense {{ side.fighter.defense.rating }}: {{ side.fighter.defense.attacks_left }} attacks or
          {{ side.fighter.defense.rounds_left }} rounds left
        </p>
      </article>
    </div>
    <RoundLog :battle="battle" />
  </section>
</template>

<style scoped>
.arena {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.round {
  margin: 0;
}
.fighters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.fighter {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
}
.fighter p {
  margin: 0;
}
.stats {
  font-size: 0.9em;
}
.effects {
  margin: 0;
  padding-left: 18px;
  font-size: 0.85em;
  color: var(--muted);
}
p.effects {
  padding-left: 0;
}
</style>
```

Create `src/components/emberlings/ActionBar.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import type { ActionChoice, BattleMode, BattleView, LegalAction } from "../../api/EmberlingsClient";
import { ROUND_PACE_MS, useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import ConfirmModal from "../ConfirmModal.vue";
import SegmentedControl from "../SegmentedControl.vue";

/** Below the arena: who plays (manual or autonomous, switched between rounds),
 * Forfeit, and in manual mode one button per legal action. Abilities still
 * cooling down are shown disabled. A catch asks which EMBLEM to throw. */
const props = defineProps<{ battle: BattleView }>();
const store = useEmberlingsStore();

const BASIC_LABELS: Record<Exclude<LegalAction["kind"], "ability">, string> = {
  attack: "Attack",
  flee: "Flee",
  catch: "Catch",
};
const paceSeconds = ROUND_PACE_MS / 1000;

const active = computed(() => props.battle.status === "active");
const locked = computed(() => !active.value || props.battle.phase !== "choosing" || store.battleBusy);
const modeOptions = computed<{ value: BattleMode; label: string; disabled?: boolean }[]>(() => [
  { value: "manual", label: "Manual", disabled: locked.value },
  // mini_games needs an EMBLEM limit for autonomous play; a battle started without one stays manual.
  { value: "autonomous", label: "Autonomous", disabled: locked.value || props.battle.emblem_limit === null },
]);
const mode = computed<BattleMode>({
  get: () => props.battle.mode,
  set: (value) => {
    if (value !== props.battle.mode && !locked.value) void store.setMode(value);
  },
});
const coolingDown = computed(() => props.battle.player.abilities.filter((a) => !a.ready));
const ownedTiers = computed(() => (store.catalog?.tiers ?? []).filter((t) => (props.battle.emblems[t.id] ?? 0) > 0));
const catchOpen = ref(false);
const forfeitOpen = ref(false);

function label(action: LegalAction): string {
  if (action.kind === "ability") return action.name ?? titleCase(action.ability_id ?? "ability");
  return BASIC_LABELS[action.kind];
}

function choose(action: LegalAction): void {
  if (action.kind === "catch") {
    catchOpen.value = true;
    return;
  }
  const choice: ActionChoice =
    action.kind === "ability" && action.ability_id !== null ? { kind: "ability", ability_id: action.ability_id } : { kind: action.kind };
  void store.act(choice);
}

function throwEmblem(tier: string): void {
  catchOpen.value = false;
  void store.act({ kind: "catch", emblem_tier: tier });
}

function forfeit(): void {
  forfeitOpen.value = false;
  void store.forfeit();
}
</script>

<template>
  <section class="card action-bar">
    <div class="controls">
      <SegmentedControl v-model="mode" :options="modeOptions" label="Who plays" />
      <button type="button" class="danger" :disabled="!active || store.battleBusy" @click="forfeitOpen = true">Forfeit</button>
    </div>

    <p v-if="battle.mode === 'autonomous'" class="muted">Your Spark chooses on its own, one round every {{ paceSeconds }} seconds.</p>
    <div v-else class="actions">
      <button
        v-for="action in battle.actions"
        :key="`${action.kind}:${action.ability_id ?? ''}`"
        type="button"
        class="action"
        :disabled="locked"
        @click="choose(action)"
      >
        <span class="action-name">{{ label(action) }}</span>
        <span class="action-detail">{{ titleCase(action.category) }} · {{ action.percentage }}%</span>
      </button>
      <button v-for="ability in coolingDown" :key="`cooldown:${ability.id}`" type="button" class="action" disabled>
        <span class="action-name">{{ ability.name }}</span>
        <span class="action-detail">Cooling down ({{ ability.cooldown }} {{ ability.cooldown === 1 ? "round" : "rounds" }})</span>
      </button>
    </div>

    <BaseModal :open="catchOpen" title="Throw which EMBLEM?" @close="catchOpen = false">
      <p v-if="ownedTiers.length === 0" class="muted">You have no EMBLEMs. Buy some in the shop.</p>
      <div class="tiers">
        <button v-for="t in ownedTiers" :key="t.id" type="button" class="primary" @click="throwEmblem(t.id)">
          {{ titleCase(t.id) }} ({{ battle.emblems[t.id] }})
        </button>
      </div>
    </BaseModal>

    <ConfirmModal
      :open="forfeitOpen"
      title="Forfeit this battle?"
      message="It counts as a loss and your Spark faints for a while."
      confirm-label="Forfeit"
      :busy="store.battleBusy"
      @confirm="forfeit"
      @close="forfeitOpen = false"
    />
  </section>
</template>

<style scoped>
.action-bar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}
.action-bar > p {
  margin: 0;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}
.actions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
}
button.action {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
button.action:hover:not(:disabled) {
  border-color: var(--accent);
}
button.action:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.action-name {
  font-weight: 600;
}
.action-detail {
  font-size: 0.8em;
  color: var(--muted);
}
.tiers {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
@media (prefers-reduced-motion: reduce) {
  button.action {
    transition: none;
  }
}
</style>
```

Create `src/components/emberlings/EmblemPrompt.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import CountdownRing from "../CountdownRing.vue";

/** The five-second EMBLEM prompt over the arena: the tiers this battle's
 * limit permits, with owned counts and a countdown (the store's, counted on
 * this device). "Let my Spark decide" only closes it; at zero the store calls
 * advance and mini_games settles the prompt (the Spark's choice, or a basic ATTACK). */
const store = useEmberlingsStore();
const dismissed = ref(false);
const prompt = computed(() => (store.promptOpen ? (store.battle?.prompt ?? null) : null));
const expired = computed(() => store.promptRemaining <= 0);

watch(
  () => store.battle?.revision,
  () => {
    dismissed.value = false;
  },
);
</script>

<template>
  <BaseModal :open="prompt !== null && !dismissed" title="Throw an EMBLEM?" @close="dismissed = true">
    <div v-if="prompt" class="emblem-prompt">
      <div class="timer">
        <CountdownRing :remaining="store.promptRemaining" :total="store.promptTotal" />
        <span>{{ expired ? "Time is up" : `${Math.ceil(store.promptRemaining)} s left` }}</span>
      </div>
      <p class="muted">
        {{ store.battle?.player.name }} wants to catch {{ store.battle?.wild.name }}. Pick an EMBLEM, or let your Spark decide.
      </p>
      <div class="tiers">
        <button
          v-for="tier in prompt.permitted_tiers"
          :key="tier"
          type="button"
          class="primary"
          :disabled="expired || store.battleBusy"
          @click="store.answerEmblem(tier)"
        >
          {{ titleCase(tier) }} ({{ prompt.owned[tier] ?? 0 }})
        </button>
      </div>
      <p v-if="prompt.permitted_tiers.length === 0" class="muted">You own no EMBLEM within this battle's limit.</p>
      <button type="button" class="chip" @click="dismissed = true">Let my Spark decide</button>
    </div>
  </BaseModal>
</template>

<style scoped>
.emblem-prompt {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}
.emblem-prompt p {
  margin: 0;
}
.timer {
  display: flex;
  align-items: center;
  gap: 8px;
  font-variant-numeric: tabular-nums;
}
.tiers {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
```

Create `src/components/emberlings/BattleResult.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import type { BattleView } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import { RESULT_LABELS, titleCase } from "../../utils/emberlings";

/** A finished battle: the outcome, what it paid, the personalities a capture
 * revealed, and Back to the encounter screen. */
const props = defineProps<{ battle: BattleView }>();
const store = useEmberlingsStore();
const result = computed(() => props.battle.result);
const levelledUp = computed(() => {
  const r = result.value;
  return r?.level_before !== undefined && r.level_after !== undefined && r.level_after > r.level_before;
});
</script>

<template>
  <section v-if="result" class="card battle-result" role="status">
    <h3>{{ RESULT_LABELS[result.kind] }}</h3>
    <ul class="gains">
      <li v-if="result.xp !== undefined">
        +{{ result.xp }} XP for {{ battle.player.name }}<template v-if="levelledUp">, now level {{ result.level_after }}</template>
      </li>
      <li v-if="result.insignia !== undefined">+{{ result.insignia }} Insignia</li>
      <li v-if="result.copies_granted !== undefined">
        +{{ result.copies_granted }} {{ result.copies_granted === 1 ? "copy" : "copies" }} of {{ battle.wild.name
        }}<template v-if="result.tier_id">, now {{ titleCase(result.tier_id) }}</template>
      </li>
      <li v-if="result.faint_until !== undefined">{{ battle.player.name }} fainted and needs rest before its next battle.</li>
    </ul>
    <template v-if="result.revealed_personalities?.length">
      <h4>Personalities revealed</h4>
      <ul class="revealed">
        <li v-for="p in result.revealed_personalities" :key="p.id">
          {{ titleCase(p.type) }} · tier {{ p.tier }}<strong v-if="p.id === result.awarded_personality?.id"> (now yours)</strong>
        </li>
      </ul>
    </template>
    <button type="button" class="primary" @click="store.closeBattle()">Back</button>
  </section>
</template>

<style scoped>
.battle-result {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.battle-result h3,
.battle-result h4 {
  margin: 0;
}
.gains,
.revealed {
  margin: 0;
  padding-left: 18px;
}
</style>
```

- [ ] **Step 5: Run the tests and the type-check**

Run: `npx vitest run src/components/emberlings/BattlePanels.test.ts src/radiusScale.test.ts`, then `npm test` (the existing users of `SegmentedControl` must still pass), then `npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 6: Report and commit (after the user agrees)**

```bash
git add apps/Ember/ember_web/src/components/SegmentedControl.vue apps/Ember/ember_web/src/components/emberlings/HealthBar.vue apps/Ember/ember_web/src/components/emberlings/RoundLog.vue apps/Ember/ember_web/src/components/emberlings/BattleArena.vue apps/Ember/ember_web/src/components/emberlings/ActionBar.vue apps/Ember/ember_web/src/components/emberlings/EmblemPrompt.vue apps/Ember/ember_web/src/components/emberlings/BattleResult.vue apps/Ember/ember_web/src/components/emberlings/BattlePanels.test.ts
git commit -m "feat(ember-web): Emberlings battle arena, actions, EMBLEM prompt and result"
```

### Task B6: Shop tab: `ShopPanel`

**Files:**
- Create: `apps/Ember/ember_web/src/components/emberlings/ShopPanel.vue`
- Test: `apps/Ember/ember_web/src/components/emberlings/ShopPanel.test.ts`

**Interfaces:**
- Consumes: `useEmberlingsStore()` (`catalog`, `profile`, `busy`, `error`, `buyEmblems(tier, quantity)`, `buyCopies(sparkId, tier)`, `sellCopy(sparkId)`); `titleCase` (B3); `ConfirmModal`.
- Produces: `<ShopPanel />` (no props). Test hooks: `[data-tier="<id>"]` rows with an `input` and a `button`, `select[name='copy-spark']`, `select[name='copy-tier']`, `[data-sell="<spark_id>"]`, `.notice`.

- [ ] **Step 1: Write the failing tests**

Create `src/components/emberlings/ShopPanel.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, ownedSpark } from "../../api/EmberlingsClient.fixtures";
import { ApiError } from "../../api/http";
import { useEmberlingsStore } from "../../stores/emberlings";
import ShopPanel from "./ShopPanel.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { buyEmblems: vi.fn(), buyCopies: vi.fn(), sellCopy: vi.fn(), profile: vi.fn() },
}));

const client = vi.mocked(emberlingsClient);

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  client.profile.mockResolvedValue(PROFILE);
});

function mountShop(insignia = 25) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = { ...PROFILE, insignia, sparks: [ownedSpark("guardian", { copies: 2 })] };
  return { store, wrapper: mount(ShopPanel) };
}

const buyIn = (wrapper: ReturnType<typeof mountShop>["wrapper"], tier: string) => wrapper.find(`[data-tier="${tier}"] button`);

describe("ShopPanel", () => {
  it("disables EMBLEMs the Insignia does not cover", async () => {
    const { wrapper } = mountShop(25);

    expect(buyIn(wrapper, "normal").attributes("disabled")).toBeUndefined();
    expect(buyIn(wrapper, "rare").attributes("disabled")).toBeDefined();

    await wrapper.find('[data-tier="normal"] input').setValue("3");

    expect(buyIn(wrapper, "normal").text()).toBe("Buy for 30");
    expect(buyIn(wrapper, "normal").attributes("disabled")).toBeDefined();
  });

  it("buys EMBLEMs and says what it bought", async () => {
    client.buyEmblems.mockResolvedValue({ kind: "emblems", tier_id: "normal", quantity: 2, price: 20 });
    const { wrapper } = mountShop(25);

    await wrapper.find('[data-tier="normal"] input').setValue("2");
    await buyIn(wrapper, "normal").trigger("click");
    await flushPromises();

    expect(client.buyEmblems).toHaveBeenCalledExactlyOnceWith("normal", 2);
    expect(wrapper.find(".notice").text()).toBe("Bought 2 Normal EMBLEMs for 20 Insignia.");
  });

  it("leaves the copy price to the server and keeps its refusal", async () => {
    client.buyCopies.mockRejectedValue(new ApiError(409, "that costs 400 Insignia and you have 25"));
    const { store, wrapper } = mountShop(25);
    const buy = () => wrapper.findAll("button").find((b) => b.text() === "Buy copies")!;
    expect(buy().attributes("disabled")).toBeDefined();

    await wrapper.find("select[name='copy-spark']").setValue("bruiser");
    await wrapper.find("select[name='copy-tier']").setValue("rare");
    expect(buy().attributes("disabled")).toBeUndefined();
    await buy().trigger("click");
    await flushPromises();

    expect(client.buyCopies).toHaveBeenCalledExactlyOnceWith("bruiser", "rare");
    expect(store.error).toBe("that costs 400 Insignia and you have 25");
  });

  it("sells one copy after confirming", async () => {
    client.sellCopy.mockResolvedValue({ kind: "sale", spark_id: "guardian", value: 12, copies: 1, tier_id: "normal", downgraded: false });
    const { wrapper } = mountShop();

    await wrapper.find('[data-sell="guardian"] button').trigger("click");
    expect(client.sellCopy).not.toHaveBeenCalled();
    await wrapper.find("button.confirm").trigger("click");
    await flushPromises();

    expect(client.sellCopy).toHaveBeenCalledExactlyOnceWith("guardian");
    expect(wrapper.find(".notice").text()).toBe("Sold one copy for 12 Insignia.");
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/components/emberlings/ShopPanel.test.ts`
Expected: fails to import `./ShopPanel.vue`.

- [ ] **Step 3: Implement**

Create `src/components/emberlings/ShopPanel.vue`:

```vue
<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import ConfirmModal from "../ConfirmModal.vue";

/** The Shop tab: EMBLEMs per tier, copies of a regular Spark at a tier, and
 * selling one absorbed copy. EMBLEM buttons are disabled when Insignia would
 * not cover the price. A copy's price depends on numbers only mini_games
 * knows, so it says itself (a 409 with the cost) when Insignia falls short;
 * the page shows that message (the store's `error`). */
const store = useEmberlingsStore();
const MAX_QUANTITY = 99;

const insignia = computed(() => store.profile?.insignia ?? 0);
const tiers = computed(() => store.catalog?.tiers ?? []);
const quantities = reactive<Record<string, number>>({});
const message = ref("");

function quantityOf(tierId: string): number {
  return quantities[tierId] ?? 1;
}

function emblemCost(tierId: string, price: number): number {
  return price * quantityOf(tierId);
}

function canBuyEmblems(tierId: string, price: number): boolean {
  const quantity = quantityOf(tierId);
  const valid = Number.isInteger(quantity) && quantity >= 1 && quantity <= MAX_QUANTITY;
  return !store.busy && valid && emblemCost(tierId, price) <= insignia.value;
}

function setQuantity(tierId: string, event: Event): void {
  quantities[tierId] = Number((event.target as HTMLInputElement).value);
}

async function buyEmblems(tierId: string): Promise<void> {
  message.value = "";
  const bought = await store.buyEmblems(tierId, quantityOf(tierId));
  if (bought) {
    message.value = `Bought ${bought.quantity} ${titleCase(bought.tier_id)} EMBLEM${bought.quantity === 1 ? "" : "s"} for ${bought.price} Insignia.`;
  }
}

const regularSparks = computed(() => (store.catalog?.sparks ?? []).filter((s) => !s.forbidden));
const regularTiers = computed(() => tiers.value.filter((t) => t.copy_threshold !== null));
const copySpark = ref("");
const copyTier = ref("");

async function buyCopies(): Promise<void> {
  message.value = "";
  const bought = await store.buyCopies(copySpark.value, copyTier.value);
  if (bought) {
    const copies = `${bought.copies_granted} ${bought.copies_granted === 1 ? "copy" : "copies"}`;
    message.value = `Bought ${copies} for ${bought.price} Insignia; it is now ${titleCase(bought.resulting_tier_id)}.`;
  }
}

const sellable = computed(() => (store.profile?.sparks ?? []).filter((s) => s.copies > 0));
const selling = ref<string | null>(null);
const sellingName = computed(() => sellable.value.find((s) => s.spark_id === selling.value)?.name ?? "");

async function sell(): Promise<void> {
  const sparkId = selling.value;
  selling.value = null;
  if (sparkId === null) return;
  message.value = "";
  const sale = await store.sellCopy(sparkId);
  if (sale) {
    message.value = `Sold one copy for ${sale.value} Insignia${sale.downgraded ? `; it is now ${titleCase(sale.tier_id)}` : ""}.`;
  }
}
</script>

<template>
  <section class="shop">
    <p class="muted">You have {{ insignia }} Insignia.</p>
    <p v-if="message" class="notice" role="status">{{ message }}</p>

    <h3>EMBLEMs</h3>
    <ul class="rows">
      <li v-for="t in tiers" :key="t.id" class="row" :data-tier="t.id">
        <span class="row-name">{{ titleCase(t.id) }}</span>
        <span class="muted">{{ t.emblem_price }} Insignia each · you own {{ store.profile?.emblems[t.id] ?? 0 }}</span>
        <input
          type="number"
          min="1"
          :max="MAX_QUANTITY"
          :value="quantityOf(t.id)"
          :aria-label="`${titleCase(t.id)} EMBLEMs to buy`"
          @input="setQuantity(t.id, $event)"
        />
        <button type="button" class="primary" :disabled="!canBuyEmblems(t.id, t.emblem_price)" @click="buyEmblems(t.id)">
          Buy for {{ emblemCost(t.id, t.emblem_price) }}
        </button>
      </li>
    </ul>

    <h3>Copies</h3>
    <p class="muted">
      Copies raise a regular Spark's tier. The price depends on the copies you already have and the Spark's level; the shop
      tells you when your Insignia falls short.
    </p>
    <div class="copies">
      <select v-model="copySpark" name="copy-spark" aria-label="Spark">
        <option value="" disabled>Choose a Spark</option>
        <option v-for="s in regularSparks" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select v-model="copyTier" name="copy-tier" aria-label="Tier">
        <option value="" disabled>Choose a tier</option>
        <option v-for="t in regularTiers" :key="t.id" :value="t.id">{{ titleCase(t.id) }}</option>
      </select>
      <button type="button" class="primary" :disabled="store.busy || !copySpark || !copyTier" @click="buyCopies">Buy copies</button>
    </div>

    <h3>Sell</h3>
    <p v-if="sellable.length === 0" class="muted">No absorbed copies to sell.</p>
    <ul v-else class="rows">
      <li v-for="s in sellable" :key="s.spark_id" class="row" :data-sell="s.spark_id">
        <span class="row-name">{{ s.name }}</span>
        <span class="muted">{{ s.copies }} {{ s.copies === 1 ? "copy" : "copies" }} · {{ titleCase(s.tier_id) }}</span>
        <button type="button" class="chip" :disabled="store.busy" @click="selling = s.spark_id">Sell one copy</button>
      </li>
    </ul>

    <ConfirmModal
      :open="selling !== null"
      title="Sell one copy?"
      :message="`One absorbed copy of ${sellingName} goes back to the shop for Insignia. Its tier can drop.`"
      confirm-label="Sell"
      :busy="store.busy"
      @confirm="sell"
      @close="selling = null"
    />
  </section>
</template>

<style scoped>
.shop h3 {
  margin: 20px 0 8px;
}
.shop > p {
  margin: 0 0 8px;
}
.notice {
  color: var(--success);
}
.rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.row-name {
  min-width: 90px;
  font-weight: 600;
}
.row input {
  width: 72px;
}
.row button {
  margin-left: auto;
}
.copies {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
```

- [ ] **Step 4: Run the tests and the type-check**

Run: `npx vitest run src/components/emberlings/ShopPanel.test.ts src/radiusScale.test.ts`, then `npm test`, then `npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Report and commit (after the user agrees)**

```bash
git add apps/Ember/ember_web/src/components/emberlings/ShopPanel.vue apps/Ember/ember_web/src/components/emberlings/ShopPanel.test.ts
git commit -m "feat(ember-web): Emberlings shop panel"
```

### Task B7: The page: `EmberlingsView.vue`

**Files:**
- Create: `apps/Ember/ember_web/src/views/EmberlingsView.vue`
- Test: `apps/Ember/ember_web/src/views/EmberlingsView.test.ts`

**Interfaces:**
- Consumes: `useEmberlingsStore()` (`attach`, `detach`, `retry`, `createProfile`, `catalog`, `profile`, `needsStarter`, `battle`, `encounter`, `loaded`, `loading`, `unavailable`, `reconnecting`, `error`, `busy`); `SegmentedControl` with `disabled` options (B5); `CollectionPanel` (B3), `EncounterPanel` (B4), `BattleArena`, `ActionBar`, `EmblemPrompt`, `BattleResult` (B5), `ShopPanel` (B6); `titleCase` (B3); `components/infoPage.css` (`.info-page`, `.card`, `.primary`, `.chip`, `.muted`, `.error`).
- Produces: the default export `EmberlingsView` (component name inferred from the file name, which B8's `KeepAlive include` relies on). Test hooks: `.wallet`, `.unavailable`, `button.starter`, `.starter-name`.

- [ ] **Step 1: Write the failing tests**

Create `src/views/EmberlingsView.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient } from "../api/EmberlingsClient";
import { ACCOUNT_WITH_EMBERLINGS, CATALOG, PROFILE, battleView } from "../api/EmberlingsClient.fixtures";
import { ApiError } from "../api/http";
import { useAuthStore } from "../stores/auth";
import EmberlingsView from "./EmberlingsView.vue";

vi.mock("../api/EmberlingsClient", () => ({
  emberlingsClient: {
    catalog: vi.fn(),
    profile: vi.fn(),
    createProfile: vi.fn(),
    battle: vi.fn(),
    encounter: vi.fn(),
    personalities: vi.fn(),
    preset: vi.fn(),
    advance: vi.fn(),
  },
}));

const client = vi.mocked(emberlingsClient);

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  client.catalog.mockResolvedValue(CATALOG);
  client.profile.mockResolvedValue(PROFILE);
  client.personalities.mockResolvedValue({ items: [], next_cursor: null });
  client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

async function mountView() {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT_WITH_EMBERLINGS;
  const wrapper = mount(EmberlingsView);
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof mountView>>;
const tab = (wrapper: Wrapper, label: string) => wrapper.findAll("button.segment").find((b) => b.text() === label)!;

describe("EmberlingsView", () => {
  it("a first visit offers the starters and keeps Battle and Shop closed", async () => {
    client.profile.mockRejectedValue(new ApiError(404, "no profile yet; choose a starter first"));
    const wrapper = await mountView();

    expect(wrapper.text()).toContain("Choose your first Spark");
    expect(tab(wrapper, "Battle").attributes("disabled")).toBeDefined();
    expect(tab(wrapper, "Shop").attributes("disabled")).toBeDefined();
    expect(wrapper.findAll(".starter-name").map((n) => n.text())).toEqual(["Guardian", "Striker"]);

    client.createProfile.mockResolvedValue(PROFILE);
    await wrapper.findAll("button.starter")[0]!.trigger("click");
    await flushPromises();

    expect(client.createProfile).toHaveBeenCalledExactlyOnceWith("guardian");
    expect(wrapper.findAll(".spark-card")).toHaveLength(1);
    expect(tab(wrapper, "Battle").attributes("disabled")).toBeUndefined();
  });

  it("shows Insignia and EMBLEM counts in the header", async () => {
    const wrapper = await mountView();

    const wallet = wrapper.find(".wallet").text();
    expect(wallet).toContain("100");
    expect(wallet).toContain("Normal 2");
  });

  it("restores an active battle on the Battle tab instead of rolling", async () => {
    client.profile.mockResolvedValue({ ...PROFILE, active_battle: "b1" });
    client.battle.mockResolvedValue(battleView({ mode: "manual" }));
    const wrapper = await mountView();

    expect(tab(wrapper, "Battle").classes()).toContain("active");
    expect(wrapper.find(".arena").exists()).toBe(true);
    expect(wrapper.find(".action-bar").exists()).toBe(true);
  });

  it("replaces the page with a Retry when Emberlings is unavailable", async () => {
    client.catalog.mockRejectedValueOnce(new ApiError(502, "Emberlings is not available right now"));
    const wrapper = await mountView();

    expect(wrapper.find(".unavailable").text()).toContain("Emberlings is not available right now");
    expect(wrapper.find("button.segment").exists()).toBe(false);

    await wrapper.find(".unavailable button").trigger("click");
    await flushPromises();

    expect(wrapper.find(".unavailable").exists()).toBe(false);
    expect(tab(wrapper, "Collection").exists()).toBe(true);
  });

  it("stops the battle loop when the page goes away", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "performance"] });
    client.profile.mockResolvedValue({ ...PROFILE, active_battle: "b1" });
    client.battle.mockResolvedValue(battleView());
    const wrapper = await mountView();

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(client.advance).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/views/EmberlingsView.test.ts`
Expected: fails to import `./EmberlingsView.vue`.

- [ ] **Step 3: Implement**

Create `src/views/EmberlingsView.vue`:

```vue
<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
import "../components/infoPage.css";
import SegmentedControl from "../components/SegmentedControl.vue";
import ActionBar from "../components/emberlings/ActionBar.vue";
import BattleArena from "../components/emberlings/BattleArena.vue";
import BattleResult from "../components/emberlings/BattleResult.vue";
import CollectionPanel from "../components/emberlings/CollectionPanel.vue";
import EmblemPrompt from "../components/emberlings/EmblemPrompt.vue";
import EncounterPanel from "../components/emberlings/EncounterPanel.vue";
import ShopPanel from "../components/emberlings/ShopPanel.vue";
import { useEmberlingsStore } from "../stores/emberlings";
import { titleCase } from "../utils/emberlings";

/** Emberlings: collect Sparks, battle wild ones, spend Insignia. App.vue keeps
 * this page alive across tab switches, so an open battle survives; the store's
 * loop runs only while the page is attached and the browser tab is visible. */
type Tab = "collection" | "battle" | "shop";

const store = useEmberlingsStore();
const tab = ref<Tab>("collection");
const tabs = computed<{ value: Tab; label: string; disabled?: boolean }[]>(() => [
  { value: "collection", label: "Collection" },
  { value: "battle", label: "Battle", disabled: store.needsStarter },
  { value: "shop", label: "Shop", disabled: store.needsStarter },
]);
const starters = computed(() => (store.catalog?.sparks ?? []).filter((s) => s.starter));
const emblemSummary = computed(() => {
  const owned = store.profile?.emblems ?? {};
  const parts = (store.catalog?.tiers ?? [])
    .filter((t) => (owned[t.id] ?? 0) > 0)
    .map((t) => `${titleCase(t.id)} ${owned[t.id] ?? 0}`);
  return parts.length > 0 ? parts.join(" · ") : "none";
});

// A restored (or just started) battle, or an encounter, opens the Battle tab.
watch(
  () => store.battle?.id ?? store.encounter?.id ?? null,
  (id) => {
    if (id !== null) tab.value = "battle";
  },
  { immediate: true },
);
// Without a profile only the Collection tab (the starter pick) is open.
watch(
  () => store.needsStarter,
  (needs) => {
    if (needs) tab.value = "collection";
  },
);

onMounted(() => store.attach());
onActivated(() => store.attach());
onDeactivated(() => store.detach());
onUnmounted(() => store.detach());
</script>

<template>
  <section class="info-page emberlings-page">
    <div class="column page-column">
      <div class="top">
        <div>
          <h2 class="page-title">Emberlings</h2>
          <p class="page-description">Collect Sparks, battle wild ones and spend Insignia in the shop.</p>
        </div>
        <dl v-if="store.profile" class="wallet">
          <div>
            <dt>Insignia</dt>
            <dd>{{ store.profile.insignia }}</dd>
          </div>
          <div>
            <dt>EMBLEMs</dt>
            <dd>{{ emblemSummary }}</dd>
          </div>
        </dl>
      </div>

      <div v-if="store.unavailable" class="card unavailable" role="alert">
        <p>Emberlings is not available right now.</p>
        <button type="button" class="primary" :disabled="store.loading" @click="store.retry()">Retry</button>
      </div>

      <div v-else-if="!store.loaded" class="loading">
        <p v-if="store.error" class="error" role="alert">Could not load Emberlings: {{ store.error }}</p>
        <p v-else class="muted">Loading …</p>
        <button v-if="store.error && !store.loading" type="button" class="chip" @click="store.retry()">Retry</button>
      </div>

      <template v-else>
        <SegmentedControl v-model="tab" :options="tabs" aria-label="Emberlings sections" />
        <p v-if="store.reconnecting" class="muted status" role="status">Reconnecting...</p>
        <p v-if="store.error" class="error status" role="alert">{{ store.error }}</p>

        <div v-if="tab === 'collection'" class="tab-body">
          <section v-if="store.needsStarter" class="starters">
            <h3>Choose your first Spark</h3>
            <p class="muted">It stays yours. Other Sparks can be caught in battle or bought in the shop later.</p>
            <div class="starter-grid">
              <button
                v-for="s in starters"
                :key="s.id"
                type="button"
                class="starter"
                :disabled="store.busy"
                @click="store.createProfile(s.id)"
              >
                <span class="starter-name">{{ s.name }}</span>
                <span class="muted">{{ s.abilities.length }} abilities · passive: {{ titleCase(s.passive.kind) }}</span>
              </button>
            </div>
          </section>
          <CollectionPanel v-else />
        </div>

        <div v-else-if="tab === 'battle'" class="tab-body">
          <template v-if="store.battle">
            <BattleResult v-if="store.battle.result" :battle="store.battle" />
            <BattleArena :battle="store.battle" />
            <template v-if="!store.battle.result">
              <ActionBar :battle="store.battle" />
              <EmblemPrompt />
            </template>
          </template>
          <EncounterPanel v-else />
        </div>

        <ShopPanel v-else class="tab-body" />
      </template>
    </div>
  </section>
</template>

<style scoped>
.top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.wallet {
  display: flex;
  gap: 16px;
  margin: 0;
}
.wallet div {
  display: flex;
  flex-direction: column;
}
.wallet dt {
  font-size: 0.8em;
  color: var(--muted);
}
.wallet dd {
  margin: 0;
  font-weight: 600;
}
.unavailable {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.unavailable p {
  margin: 0;
}
.status {
  margin: 10px 0 0;
}
.tab-body {
  margin-top: 16px;
}
.starters h3 {
  margin: 0 0 4px;
}
.starter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.starter {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  background: var(--surface);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.starter:hover:not(:disabled) {
  border-color: var(--accent);
}
.starter:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.starter-name {
  font-weight: 600;
}
@media (prefers-reduced-motion: reduce) {
  .starter {
    transition: none;
  }
}
</style>
```

- [ ] **Step 4: Run the tests and the type-check**

Run: `npx vitest run src/views/EmberlingsView.test.ts src/radiusScale.test.ts`, then `npm test`, then `npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Report and commit (after the user agrees)**

```bash
git add apps/Ember/ember_web/src/views/EmberlingsView.vue apps/Ember/ember_web/src/views/EmberlingsView.test.ts
git commit -m "feat(ember-web): Emberlings page with tabs and the starter pick"
```

### Task B8: Route, nav entry, KeepAlive

**Files:**
- Modify: `apps/Ember/ember_web/src/router/index.ts`
- Modify: `apps/Ember/ember_web/src/router/pages.ts`
- Modify: `apps/Ember/ember_web/src/App.vue:30`
- Test: `apps/Ember/ember_web/src/router/index.test.ts`

**Interfaces:**
- Consumes: `EmberlingsView` (B7), permission `emberlings.play` (A3).
- Produces: route `{ path: "/emberlings", name: "emberlings", meta: { permission: "emberlings.play" } }`; a `NAV_PAGES` entry `{ to: "/emberlings", label: "Emberlings", permission: "emberlings.play" }`; `EmberlingsView` in `KeepAlive include`.

- [ ] **Step 1: Write the failing tests**

In `src/router/index.test.ts`, add below the existing imports:

```ts
import { NAV_PAGES } from "./pages";
```

and append at the end of the file:

```ts
describe("Emberlings page", () => {
  it("opens for an account that may play", async () => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: [...ACCOUNT.permissions, "emberlings.play"] });

    await router.push("/emberlings");

    expect(router.currentRoute.value.name).toBe("emberlings");
  });

  it("sends an account without emberlings.play to its home page", async () => {
    me.mockResolvedValue(ACCOUNT);

    await router.push("/emberlings");

    expect(router.currentRoute.value.name).toBe("chat");
  });

  it("is in the nav rail and on Overview only for that permission", () => {
    const page = NAV_PAGES.find((p) => p.to === "/emberlings");

    expect(page?.label).toBe("Emberlings");
    expect(page?.permission).toBe("emberlings.play");
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/router/index.test.ts`
Expected: the three new tests fail (the route falls through to the catch-all redirect; no nav entry).

- [ ] **Step 3: Implement**

In `src/router/index.ts`, directly below the `/agents` route

```ts
    {
      path: "/agents",
      name: "agents",
      component: () => import("../views/AgentsView.vue"),
      meta: { permission: "chat.use" },
    },
```

add:

```ts
    {
      path: "/emberlings",
      name: "emberlings",
      component: () => import("../views/EmberlingsView.vue"),
      meta: { permission: "emberlings.play" },
    },
```

In `src/router/pages.ts`, directly before the line that starts with `  { to: "/usage", label: "Usage",` add:

```ts
  {
    to: "/emberlings",
    label: "Emberlings",
    icon: [
      "M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z",
    ],
    description: "Collect Sparks, battle wild ones and spend Insignia in the shop.",
    permission: "emberlings.play",
  },
```

In `src/App.vue` replace

```vue
      <!-- KeepAlive: switching to Tools and back keeps the chat (and a turn in
           flight) intact. Keyed by account so a different user never gets the
           previous user's cached pages. -->
      <RouterView v-slot="{ Component }">
        <KeepAlive :key="account?.id ?? 'guest'" include="ChatView,CapabilitiesView">
```

with

```vue
      <!-- KeepAlive: switching to Tools and back keeps the chat (and a turn in
           flight) or an Emberlings battle intact. Keyed by account so a
           different user never gets the previous user's cached pages. -->
      <RouterView v-slot="{ Component }">
        <KeepAlive :key="account?.id ?? 'guest'" include="ChatView,CapabilitiesView,EmberlingsView">
```

- [ ] **Step 4: Run all checks**

Run: `npx vitest run src/router/index.test.ts`, then `npm test` (`NavRail.test.ts` and `OverviewView.test.ts` use accounts without `emberlings.play`, so their page counts stay the same), then `npx vue-tsc -b --noEmit`, then `npx vite build` and delete `dist/` afterwards (`Remove-Item -Recurse -Force dist` in PowerShell).
Expected: all pass; vue-tsc prints nothing; the build lists a separate `EmberlingsView` chunk.

- [ ] **Step 5: Report and commit (after the user agrees)**

Tell the user the page is now reachable at `/emberlings` for accounts holding `emberlings.play` (Administrator; grant it to other roles in ember_admin), with mini_games running on `emberlings_url`.

```bash
git add apps/Ember/ember_web/src/router/index.ts apps/Ember/ember_web/src/router/pages.ts apps/Ember/ember_web/src/App.vue apps/Ember/ember_web/src/router/index.test.ts
git commit -m "feat(ember-web): Emberlings route, nav entry and KeepAlive"
```

### Task B9: Playwright fake, e2e spec and docs

**Files:**
- Modify: `apps/Ember/ember_web/e2e/fakeApi.ts`
- Create: `apps/Ember/ember_web/e2e/emberlings.spec.ts`
- Modify: `apps/Ember/ember_web/README.md`
- Modify: `D:/User/Documents/Programming/Brain/Projects/ember_web.md` (the Obsidian vault, its own git repo; follow `Brain/AGENTS.md`)

**Interfaces:**
- Consumes: the routes `GET /api/emberlings/catalog`, `GET`/`POST /api/emberlings/profile`; `logIn(page)` from `e2e/helpers.ts`.
- Produces: `installFakeApi(page, { emberlings: true })`; `FakeApi.emberlings: { profile: Record<string, unknown> | null; keys: string[] }`.

- [ ] **Step 1: Extend the fake**

In `e2e/fakeApi.ts`:

1. In `interface FakeApi`, replace

```ts
  chats: Map<string, StoredChat>;
  folders: Map<number, StoredFolder>;
}
```

with

```ts
  chats: Map<string, StoredChat>;
  folders: Map<number, StoredFolder>;
  /** Emberlings (an account with emberlings.play only): the profile once a starter is chosen, and the Idempotency-Keys sent. */
  emberlings: { profile: Record<string, unknown> | null; keys: string[] };
}
```

2. Directly below the `ADMIN_PERMISSIONS` constant add:

```ts
/** A small Emberlings catalog: two starters, two tiers. */
const EMBERLINGS_CATALOG = {
  version: 1,
  tiers: [
    { id: "normal", stat_multiplier: 1, copy_threshold: 0, copy_reward: 1, emblem_strength: 1, emblem_price: 10 },
    { id: "rare", stat_multiplier: 1.2, copy_threshold: 3, copy_reward: 2, emblem_strength: 1.5, emblem_price: 40 },
  ],
  levels: { regular_cap: 30, forbidden_cap: 50 },
  sparks: ["guardian", "striker"].map((id) => ({
    id,
    name: id.charAt(0).toUpperCase() + id.slice(1),
    starter: true,
    forbidden: false,
    base: { hp: 100, essence: 10, speed: 10 },
    growth: { hp: 5, essence: 1, speed: 1 },
    base_price: 50,
    passive: { kind: "steady", params: {} },
    abilities: [
      { id: `${id}_strike`, name: "Strike", unlock_level: 1, category: "ATTACK", percentage: 120, cooldown: 1, stat: null, duration: null },
    ],
  })),
  personalities: [{ id: "AGGRESSIVE", categories: ["ATTACK"] }],
};

/** The profile mini_games makes for a new player with this starter. */
function emberlingsProfile(starter: string): Record<string, unknown> {
  return {
    owner: "1",
    insignia: 0,
    emblems: { normal: 3 },
    sparks: [
      {
        spark_id: starter,
        name: starter.charAt(0).toUpperCase() + starter.slice(1),
        level: 1,
        xp: 0,
        xp_needed: 100,
        level_cap: 30,
        copies: 0,
        tier_id: "normal",
        faint_until: null,
        fainted: false,
      },
    ],
    pending_encounter: null,
    active_battle: null,
    next_roll_at: null,
  };
}
```

3. Replace

```ts
export async function installFakeApi(page: Page, options: { admin?: boolean } = {}): Promise<FakeApi> {
```

with

```ts
export async function installFakeApi(page: Page, options: { admin?: boolean; emberlings?: boolean } = {}): Promise<FakeApi> {
```

4. Replace

```ts
    folders: new Map(),
  };
  const account = options.admin ? ADMIN_ACCOUNT : ACCOUNT;
```

with

```ts
    folders: new Map(),
    emberlings: { profile: null, keys: [] },
  };
  const base = options.admin ? ADMIN_ACCOUNT : ACCOUNT;
  const account = options.emberlings ? { ...base, permissions: [...base.permissions, "emberlings.play"] } : base;
```

5. Directly above the line `    api.unexpected.push(\`${method} ${path}\`);` add:

```ts
    if (method === "GET" && path === "/api/emberlings/catalog") return json(route, EMBERLINGS_CATALOG);
    if (method === "GET" && path === "/api/emberlings/profile") {
      if (api.emberlings.profile) return json(route, api.emberlings.profile);
      return json(route, { detail: "no profile yet; choose a starter first" }, 404);
    }
    if (method === "POST" && path === "/api/emberlings/profile") {
      api.emberlings.keys.push(request.headers()["idempotency-key"] ?? "");
      const { starter_spark_id } = request.postDataJSON() as { starter_spark_id: string };
      api.emberlings.profile = emberlingsProfile(starter_spark_id);
      return json(route, api.emberlings.profile, 201);
    }
```

- [ ] **Step 2: Write the spec**

Create `e2e/emberlings.spec.ts`:

```ts
/// <reference lib="dom" />
import { expect, test } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

test("a first visit picks a starter, then the collection and the Battle tab open", async ({ page }) => {
  const api = await installFakeApi(page, { emberlings: true });
  await logIn(page);
  await page.goto("/emberlings");

  await expect(page.getByRole("heading", { name: "Choose your first Spark" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Battle", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: /^Guardian/ }).click();

  await expect(page.locator(".spark-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Battle", exact: true })).toBeEnabled();
  expect(api.emberlings.keys).toHaveLength(1);
  expect(api.emberlings.keys[0]).toMatch(/^[0-9a-f-]{32,36}$/);
  expect(api.unexpected).toEqual([]);
});
```

- [ ] **Step 3: Run the end-to-end suite**

Run: `npm run test:e2e`, then delete `dist/` (the suite builds the app first).
Expected: every spec passes, the existing ones unchanged (their accounts lack `emberlings.play`, so the page never loads for them).

- [ ] **Step 4: Update the ember_web README**

In `apps/Ember/ember_web/README.md`:

1. Directly below the line `  always go to the entry agent, there is no per-agent chat.` (the end of the Agents page bullet) add:

```markdown
- Emberlings page (`/emberlings`, `emberlings.play`): the creature game from `apps/mini_games`, through ember_api's
  `/api/emberlings` pass-through (the browser never learns mini_games' address or token). A header shows Insignia and
  EMBLEM counts; tabs: Collection (Spark cards with tier badge, level, XP, copies and a faint countdown; a card opens
  its abilities, collected personalities and five presets), Battle (look for a wild Spark, decline or fight; an arena
  with health bars, round log and actions; autonomous rounds every 1.5 s; the five-second EMBLEM prompt counts down on
  this device) and Shop (EMBLEMs, copies, selling a copy). A first visit picks a starter. The battle loop pauses while
  the browser tab is hidden or another page is open and resumes where the battle is; a lost connection shows
  "Reconnecting..." and retries every 3 s; a stale action is refreshed, never resent. Kept alive across page switches.
  Every change sends a fresh `Idempotency-Key`.
```

2. Replace `ConfigIssuesClient / TemplatesClient / NavPreferencesClient / SharesClient / SettingsClient (ember_api REST),` with `ConfigIssuesClient / TemplatesClient / NavPreferencesClient / SharesClient / SettingsClient / EmberlingsClient (ember_api REST),`.

3. Replace `  stores/       Pinia: auth, entryAgent, chat, templates, navPrefs, accountCapabilities, configIssues` with `  stores/       Pinia: auth, entryAgent, chat, templates, navPrefs, accountCapabilities, configIssues, emberlings`.

4. Replace `  views/        pages: Overview, Chat, Capabilities, Agents, Usage, Settings, ConfigIssues,` with `  views/        pages: Overview, Chat, Capabilities, Agents, Emberlings, Usage, Settings, ConfigIssues,`.

5. Directly below `    infoPage.css  shared look of the Agents / Config pages` add:

```text
    emberlings/   the Emberlings page: CollectionPanel, SparkCard, TierBadge, PresetEditor, EncounterPanel,
                  BattleArena, HealthBar, RoundLog, ActionBar, EmblemPrompt, BattleResult, ShopPanel
```

6. Directly below the line `` `turnStream` (the event stream: pieces of events, ping, reconnect with backoff, resume, give up, abort) is covered too. `` add:

```markdown
Emberlings: the client (paths, Idempotency-Key per action), the store's battle loop with fake timers (1.5 s pace,
stop when left or hidden, prompt countdown and settle at zero, stale 409, reconnect, 502), each tab's components and
the page. `e2e/emberlings.spec.ts` picks a starter on a first visit.
```

- [ ] **Step 5: Update the vault note**

In `D:/User/Documents/Programming/Brain/Projects/ember_web.md` (follow `Brain/AGENTS.md`: plain short sentences, wikilinks only to notes that exist, no secrets):

1. In the `## Pages` paragraph replace `Agents (\`/agents\`), Usage,` with `Agents (\`/agents\`), Emberlings (\`/emberlings\`), Usage,`.
2. Directly above the line `## Architecture` add:

```markdown
## Emberlings page
`/emberlings` (permission `emberlings.play`; only Administrator holds it until a role is granted it) plays the Emberlings game from `apps/mini_games` through [[ember_api]]'s `/api/emberlings` pass-through. The owner sent to mini_games is the account id, so a renamed account keeps its Sparks. `src/stores/emberlings.ts` runs the battle loop: autonomous rounds every 1.5 s, paused while the page is hidden or left, the EMBLEM prompt counted down on the device's monotonic clock, one refresh after a 409, reconnect every 3 s. Code: `Python/MCPServer/apps/Ember/ember_web/src/views/EmberlingsView.vue` and `src/components/emberlings/`. Plan: `Python/MCPServer/docs/superpowers/plans/2026-10-10-emberlings-ember-page.md`.
```

The vault is its own git repository; its SessionEnd hook commits and pushes vault changes. Do not stage it from the MCPServer repo.

- [ ] **Step 6: Final checks**

Run from `apps/Ember/ember_web/`: `npx vue-tsc -b --noEmit` (prints nothing), `npm test`, `npx vite build`, then delete `dist/`. Run from `apps/Ember/ember_api/`: `.venv_ember_api/Scripts/python -m pytest -q`.
Expected: all green.

- [ ] **Step 7: Report and commit (after the user agrees)**

Report to the user: what changed, what was verified and how, what to test by hand (pick a starter, roll, fight manually and autonomously, let an EMBLEM prompt run out and answer one, switch pages mid-battle and come back, stop mini_games mid-battle to see "Reconnecting..." and the 502 page, buy and sell in the shop), and that `Member` needs `emberlings.play` granted in ember_admin.

```bash
git add apps/Ember/ember_web/e2e/fakeApi.ts apps/Ember/ember_web/e2e/emberlings.spec.ts apps/Ember/ember_web/README.md
git commit -m "docs(ember-web): Emberlings e2e fake routes, spec and README"
```

---

## Self-review

### Spec coverage

| Spec section / requirement | Task |
|---|---|
| Goal: play Emberlings in the browser | A1 to A4, B1 to B9 |
| Out of scope (no MCP tools, no `/mcp`, no mood reveal, no discovery route, no art) | Nothing built for them; text-only components (B3, B5) |
| Architecture: ember_web -> ember_api -> mini_games, no table or migration, browser never learns address or token, browser identity headers dropped | A2 (gateway builds every header), A3 (no model), A4 (`test_owner_and_token_come_from_ember_api_not_the_browser`, `test_a_token_mismatch_shows_neither_address_nor_token`, full suite incl. `test_migrations.py`) |
| Config `emberlings_url`, default, `.example`, missing key falls back | A1 |
| `EmberlingsGateway`: one client, base URL, token, `TrafficRecorder`, `request(method, path, account, json, params, idempotency_key)`, headers, 10 s timeout, fixed paths | A2 |
| Results: 2xx JSON, 204 None, 400/404/409 `EmberlingsRefused`, 401/5xx/no connection `EmberlingsUnavailable` -> 502, 401 logged as warning | A2 (tests for each), A3 (`_forward`), A4 |
| `EmberlingsApi` Protocol, `FakeEmberlings`, lifespan, `app.state`, `deps.py` getter, `create_app(...)` injection | A2, A3 |
| Permission `emberlings.play`, Administrator yes, Member no, said at hand-over | A3 (`test_the_administrator_role_has_the_permission_and_member_does_not`), end of Part A, B8, B9 reports |
| Routes table, prefix, `require_permission`, JSON bodies, request models rejecting unknown fields | A3 |
| Id patterns; missing `Idempotency-Key` (1 to 200) is a 400 before mini_games | A3 (`test_bad_ids_are_400`, `test_a_change_needs_an_idempotency_key`, `test_a_200_character_key_is_accepted`) |
| Audit for the five value changes only | A3 (`test_only_changes_of_value_are_audited`, `test_a_refused_change_is_not_audited`) |
| Owner identity = account id | A2 (`X-Requester-Username == "7"`), A4 (`!= me["username"]`) |
| ember_web files: client with interfaces and per-action key, store resetting on account change, view under `views/`, components list, reuse of shared controls | B1, B2, B3 to B7 |
| Router lazy route, `meta.permission`, `NAV_PAGES` entry with stroked icon, `KeepAlive include`, loop paused while hidden | B8 (route, nav, KeepAlive), B2 and B7 (attach/detach, visibility) |
| Styling: tokens only, tier badges accent for top tiers with the name as text, radius scale | B3 (`TierBadge`, `tierStanding`), every component's scoped CSS, `radiusScale.test.ts` run in B3 to B7 |
| Page: three tabs, Insignia and EMBLEM header | B7 |
| First visit: Battle and Shop disabled, starters, `POST /profile` | B5 (`SegmentedControl` disabled), B7 |
| Collection: cards with name, tier, level, XP bar hidden at cap, copies, faint countdown; abilities with unlock levels, personalities paged, five presets of up to three; unowned greyed | B3 |
| Battle state 1: look button disabled with countdown until `next_roll_at`; restore pending encounter or active battle without reroll | B4, B2 (`restores a pending encounter...`), B7 (`restores an active battle...`) |
| Battle state 2: preview, Decline, Fight form (Spark, preset, mode, EMBLEM limit "none" by default) | B4 (plus fact 3: autonomous needs preset and limit) |
| Battle state 3: arena (name, level, tier, health, essence, speed, buffs, defense), round log, action bar (mode switch, Forfeit, one button per action with name, category, percentage, not-ready ability disabled with cooldown), catch asks the tier, result with outcome, XP, Insignia, copies, revealed personalities, Back | B5 |
| Shop: EMBLEMs per tier with price and quantity, copies of a regular Spark, sell one copy, disabled when Insignia would not cover, 409 still shown | B6 (fact 6 for copies) |
| Loop: autonomous 1.5 s after each response, stops when not active, on unmount and when hidden, resumes | B2 tests, B7 (`stops the battle loop when the page goes away`) |
| Manual: `{round, revision, action}`, one `GET` on stale 409, no silent retry | B1 (body shape), B2 (`never advances on its own and does not retry a stale action`), B5 |
| EMBLEM prompt: modal, permitted tiers with counts, countdown from `seconds_left` on the monotonic clock, choose calls `/emblem`, at zero buttons disabled and `advance`, late 409 refresh and continue | B2 (three prompt tests), B5 (`EmblemPrompt` tests) |
| Mode switch between rounds; loop follows | B2 (`setMode` + `schedule`), B5 (`switches to autonomous between rounds`) |
| Errors: network pauses with "Reconnecting...", `GET` every 3 s, resumes; 502 replaces the page body with Retry | B2 (`pauses on a network error...`, `stops and shows the page as unavailable on 502`), B7 (`replaces the page with a Retry...`) |
| Data flow: fresh key per call, store replaces `battle`, log grows | B1 (`makes a fresh key for each action`), B2, B5 (`RoundLog`) |
| Reload rebuilds from `GET /profile` and `GET /battles/{id}` | B2 (`loadProfile`), B7 test |
| Testing, ember_api: every listed case | A2, A3, A4 |
| Testing, ember_web: loop, countdown with fake timers, encounter and shop disabled states, router guard, `e2e/fakeApi.ts` routes | B2, B4, B6, B8, B9 |
| Type-check and build; no browser-verification agents | Every B task's verify step; B8 and B9 build; hand-testing listed in B9's report |
| Docs: ember_api API table, ember_web features, Brain section, `.example` key | A4, B9, B9, A1 |
| Decisions: owner id, new permission not on Member, no table, rounds not logged, 1.5 s constant | A2/A4, A3, A3, A3, B2 (`ROUND_PACE_MS`) |

### Placeholder scan

Searched the plan for "TBD", "TODO", "implement later", "fill in", "add appropriate", "similar to Task", "handle edge cases" and "write tests for": none. Every code step shows complete file contents or an exact replace-this-with-that edit; every test step shows the test code and the command with its expected result.

### Type and name consistency

| Name | Defined in | Used in |
|---|---|---|
| `DEFAULT_EMBERLINGS_URL`, `Settings.emberlings_url` | A1 | A3 (`create_app`), A4 test |
| `EmberlingsGateway`, `EmberlingsApi`, `EmberlingsRefused(status, message)`, `EmberlingsUnavailable`, `UNAVAILABLE_MESSAGE`, `TIMEOUT_SECONDS`, `is_allowed` | A2 | A3 routes, `conftest.FakeEmberlings`, A3 and A4 tests |
| `EMBERLINGS_PLAY = "emberlings.play"` | A3 | routes, B1 fixture `ACCOUNT_WITH_EMBERLINGS`, B8 route and nav, B9 fake |
| `get_emberlings`, `create_app(emberlings=...)`, `app.state.emberlings` | A3 | A3, A4 |
| `FakeEmberlings.calls` keys `method, path, owner, json, params, key`; fixture `emberlings` | A3 | `test_emberlings.py` |
| ember_api paths `/api/emberlings/...` | A3 table | `EmberlingsClient.ts` (B1), `EmberlingsClient.test.ts`, `e2e/fakeApi.ts` (B9), README (A4) |
| `apiRequest(method, path, body?, headers?)` | B1 | `EmberlingsClient.ts` |
| `emberlingsClient.catalog / profile / createProfile / personalities / preset / savePreset / rollEncounter / encounter / declineEncounter / startBattle / battle / action / emblem / advance / setMode / forfeit / buyEmblems / buyCopies / sellCopy` | B1 | store (B2), `CollectionPanel` and `PresetEditor` (B3: `personalities`, `preset`), every test's `vi.mock` list |
| `RoundRef`, `ActionChoice`, `StartBattleInput`, `BattleView`, `EmblemPromptState`, `Profile`, `OwnedSpark`, `Catalog`, `TierInfo`, `LegalAction`, `Fighter`, `Buff`, `HistoryRound`, `BattleEvent`, `BattleResult`, `ResultKind`, `BattleMode` | B1 | B2 to B7 |
| Store: `attach, detach, retry, createProfile, rollEncounter, declineEncounter, startBattle, savePreset, buyEmblems, buyCopies, sellCopy, act, answerEmblem, setMode, forfeit, refreshBattle, closeBattle`; state `catalog, profile, needsStarter, encounter, battle, loading, loaded, unavailable, reconnecting, busy, battleBusy, error, promptRemaining, promptTotal, promptOpen`; `ROUND_PACE_MS`, `RECONNECT_MS` | B2 | B3 to B7 and their tests |
| `tierStanding, titleCase, formatCountdown, RESULT_LABELS, describeEvent, describeAction`, `useNowSeconds` | B3 | B3 to B7 |
| `SegmentedControl` option `disabled?` | B5 | `ActionBar` (B5), `EmberlingsView` tabs (B7) |
| Component names `TierBadge, SparkCard, PresetEditor, CollectionPanel, EncounterPanel, HealthBar, RoundLog, BattleArena, ActionBar, EmblemPrompt, BattleResult, ShopPanel, EmberlingsView` | B3 to B7 | B7 imports, B8 `KeepAlive include="...EmberlingsView"`, B9 README |
| Route `/emberlings`, name `emberlings` | B8 | B8 test, B9 spec (`page.goto("/emberlings")`), Brain note |

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-10-emberlings-ember-page.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

For this plan either way: Part A (A1 to A4) runs task after task; Part B stops before every task for the user's approval (propose, wait, implement, verify, report, commit on agreement).
