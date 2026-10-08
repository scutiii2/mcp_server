# Prompt Suggestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After an answered turn, the ember_web chat box shows a predicted next prompt as its placeholder; Tab on an empty box fills it in.

**Architecture:** ember_api gets a per-account `prompt_suggestions` preference (default on, enforced server-side) and a new `GET /api/chats/{id}/suggestion` route. The route runs one `gateway.interpret()` call over the last exchange (same pattern as `services/summarization.py`), records usage as kind `suggestion`, and caches the result. ember_web fetches it after an answered turn or when a finished chat is opened, and `ChatInput.vue` shows it as the placeholder. The turn/SSE event contract does not change, so `chat_cli` is unaffected.

**Tech Stack:** FastAPI + async SQLAlchemy + Alembic (SQLite), pytest; Vue 3 + TypeScript + Pinia, Vitest, Playwright fake API.

**Spec:** `docs/superpowers/specs/2026-10-08-prompt-suggestion-design.md`

## Global Constraints

- Preference column: `accounts.prompt_suggestions`, `Boolean`, `NOT NULL`, `server_default` true. Needs an Alembic migration.
- Suggestion: at most 120 characters, one line, plain text; usage kind is exactly `suggestion` (the `usage.kind` column is `String(20)`).
- Route: `GET /api/chats/{chat_id}/suggestion`, gated by `chat.use`, returns `{text: string | null}`. Any failure returns `{text: null}`, never an error status (except 401/403/404 for auth and unknown chat).
- Route: `PATCH /api/account/preferences`, JSON body `{prompt_suggestions: bool}`, any logged-in account, writes audit entry source `account.preferences`.
- ember_web: no hardcoded colors (theme tokens only), no `v-html`, no constructor parameter properties or enums (`erasableSyntaxOnly`). Pages stay in `src/views/`.
- Commit rule of this user: commit only after verification passes AND the user agrees; push only when asked. Stage only the files named in the task (the working tree has unrelated uncommitted changes: do not touch or stage them).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## File Structure

ember_api (`apps/ember_api/`):
- Modify `src/models/account.py` - new column.
- Create `migrations/versions/0007_prompt_suggestions.py` - adds the column.
- Modify `src/routes/auth.py` - `AccountOut.prompt_suggestions`.
- Modify `src/routes/account.py` - `PATCH /preferences`.
- Create `src/services/suggestions.py` - prompt, cleaning, exchange extraction, cache, `suggest()`.
- Modify `src/routes/chats.py` - `GET /{chat_id}/suggestion`.
- Create `tests/test_suggestions.py`; modify `tests/test_account.py`.
- Modify `README.md` - API table.

ember_web (`apps/ember_web/`):
- Modify `src/api/AuthClient.ts`, `src/stores/auth.ts` - preference.
- Modify `src/api/ChatsClient.ts` - `suggestion()`.
- Modify `src/stores/chat.ts` - `suggestion` state and fetch logic.
- Modify `src/components/ChatInput.vue`, `src/views/ChatView.vue` - display and Tab.
- Modify `src/views/SettingsView.vue` - toggle row.
- Create `src/stores/chat.suggestion.test.ts`; modify `src/components/ChatInput.test.ts`, `src/views/SettingsView.test.ts`.
- Modify `e2e/fakeApi.ts`, `README.md`.

---

### Task 1: Account preference (ember_api)

**Files:**
- Modify: `apps/ember_api/src/models/account.py`
- Create: `apps/ember_api/migrations/versions/0007_prompt_suggestions.py`
- Modify: `apps/ember_api/src/routes/auth.py` (`AccountOut`, lines 53-74)
- Modify: `apps/ember_api/src/routes/account.py`
- Test: `apps/ember_api/tests/test_account.py`

**Interfaces:**
- Produces: `Account.prompt_suggestions: bool`; `AccountOut.prompt_suggestions: bool` (so `GET /api/auth/me`, login and register return it); `PATCH /api/account/preferences` body `{"prompt_suggestions": bool}` returning `AccountOut`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/ember_api/tests/test_account.py`:

```python
# --- preferences ----------------------------------------------------------------


def test_preferences_need_login(client: TestClient) -> None:
    assert client.patch("/api/account/preferences", json={"prompt_suggestions": False}).status_code == 401


def test_prompt_suggestions_start_on_and_can_be_turned_off_and_on(client: TestClient) -> None:
    as_admin(client)
    assert client.get("/api/auth/me").json()["prompt_suggestions"] is True

    off = client.patch("/api/account/preferences", json={"prompt_suggestions": False})

    assert off.status_code == 200
    assert off.json()["prompt_suggestions"] is False
    assert client.get("/api/auth/me").json()["prompt_suggestions"] is False
    on = client.patch("/api/account/preferences", json={"prompt_suggestions": True})
    assert on.json()["prompt_suggestions"] is True
    assert client.get("/api/auth/me").json()["prompt_suggestions"] is True


def test_preferences_refuse_anything_but_a_boolean(client: TestClient) -> None:
    as_admin(client)

    for body in ({"prompt_suggestions": "maybe"}, {"prompt_suggestions": 1}, {}):
        assert client.patch("/api/account/preferences", json=body).status_code == 422, body
    assert client.get("/api/auth/me").json()["prompt_suggestions"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run (from `apps/ember_api/`): `.venv_ember_api\Scripts\python -m pytest tests/test_account.py -q -k "preferences or prompt_suggestions"`
Expected: FAIL (404 / `KeyError: 'prompt_suggestions'`).

- [ ] **Step 3: Add the model column**

In `apps/ember_api/src/models/account.py` change the import line and add the column after `email_verified`:

```python
from sqlalchemy import String, true
```

```python
    email_verified: Mapped[bool] = mapped_column(default=False)
    # Chat shows a predicted next prompt after each answer (costs one small
    # model call per answer, so the account can switch it off).
    prompt_suggestions: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

- [ ] **Step 4: Write the migration**

Create `apps/ember_api/migrations/versions/0007_prompt_suggestions.py`:

```python
"""Per-account switch for the chat's next-prompt suggestion (accounts.prompt_suggestions).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("prompt_suggestions", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("prompt_suggestions")
```

- [ ] **Step 5: Expose it on `AccountOut`**

In `apps/ember_api/src/routes/auth.py` add the field after `email_verification_required` and fill it in `of`:

```python
    email_verification_required: bool = True
    # The chat suggests the next prompt after each answer.
    prompt_suggestions: bool = True

    @classmethod
    def of(cls, account: Account, settings: Settings) -> AccountOut:
        return cls(
            id=account.id,
            username=account.username,
            email=account.email,
            email_verified=account.email_verified,
            roles=sorted(r.name for r in account.roles),
            permissions=sorted(account.permission_names),
            email_verification_required=settings.require_email_verification,
            prompt_suggestions=account.prompt_suggestions,
        )
```

- [ ] **Step 6: Add the route**

In `apps/ember_api/src/routes/account.py`: add `StrictBool` to the pydantic import (`from pydantic import BaseModel, EmailStr, Field, StrictBool`), add the model after `ChangePasswordRequest`:

```python
class PreferencesRequest(BaseModel):
    # Strict: "maybe", 1 and a missing field are all refused (422).
    prompt_suggestions: StrictBool
```

and the route after `change_password`:

```python
@router.patch("/preferences")
async def set_preferences(
    body: PreferencesRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    account: Account = Depends(current_account),
    logs: LogWriter = Depends(get_log_writer),
) -> AccountOut:
    """Switches the account keeps on the server because the server acts on
    them: today, whether chat makes a model call to suggest the next prompt."""
    if account.prompt_suggestions != body.prompt_suggestions:
        account.prompt_suggestions = body.prompt_suggestions
        await db.commit()
        await logs.action(
            account, "account.preferences", f"Prompt suggestions {'on' if body.prompt_suggestions else 'off'}"
        )
    return AccountOut.of(account, settings)
```

Update the module docstring's first line to: `"""/api/account: the logged-in user changes their own email, password or preferences,`.

- [ ] **Step 7: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_account.py tests/test_migrations.py -q`
Expected: PASS (the migration test confirms model and migration agree).

- [ ] **Step 8: Run the whole ember_api suite**

Run: `.venv_ember_api\Scripts\python -m pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit (ask the user first)**

```bash
git add apps/ember_api/src/models/account.py apps/ember_api/migrations/versions/0007_prompt_suggestions.py apps/ember_api/src/routes/auth.py apps/ember_api/src/routes/account.py apps/ember_api/tests/test_account.py
git commit -m "feat(ember_api): per-account prompt_suggestions preference"
```

---

### Task 2: Suggestion service (ember_api)

**Files:**
- Create: `apps/ember_api/src/services/suggestions.py`
- Test: `apps/ember_api/tests/test_suggestions.py` (service part; Task 3 appends the route tests)

**Interfaces:**
- Consumes: `AgentGateway.interpret(url: str, caller: Caller, text: str) -> dict` (returns `{"response": str, ...usage fields}`); raises `AgentCallError`.
- Produces (used by Task 3):
  - `last_exchange(messages: list[ChatMessage]) -> tuple[str, str] | None` - `(question, answer)` of the last plain user/assistant pair, or `None` when no suggestion should be made.
  - `async suggest(gateway, url: str, caller: Caller, question: str, answer: str) -> SuggestionOutcome | None` - `None` only when the agent call failed.
  - `SuggestionOutcome(text: str | None, result: dict)` - `text` is `None` when the model had no natural follow-up; `result` is the raw `interpret` result (for usage).
  - `SuggestionCache` with `lookup(key) -> tuple[bool, str | None]` and `put(key, text)`; module singleton `CACHE`; `cache_key(account_id, chat_id, messages, answer) -> tuple`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_api/tests/test_suggestions.py`:

```python
from __future__ import annotations

import asyncio

from src.services import suggestions
from src.services.agent_gateway import Caller
from tests.conftest import FakeAgent

CALLER = Caller(username="alice", email="alice@example.com")


def run(agent: FakeAgent, question: str = "Who wrote Dune?", answer: str = "Frank Herbert."):
    return asyncio.run(suggestions.suggest(agent, "http://agent", CALLER, question, answer))


# --- suggest ---------------------------------------------------------------------


def test_returns_the_cleaned_one_line_suggestion(agent: FakeAgent) -> None:
    agent.summary = '  "Who wrote the sequel?"\nBecause that is next.  '

    outcome = run(agent)

    assert outcome is not None
    assert outcome.text == "Who wrote the sequel?"
    assert outcome.result["total_tokens"] == 10
    sent = agent.interprets[0]
    assert "Who wrote Dune?" in sent and "Frank Herbert." in sent


def test_none_and_empty_replies_mean_no_suggestion_but_keep_the_usage(agent: FakeAgent) -> None:
    for reply in ("NONE", "none.", "", "   "):
        agent.summary = reply
        outcome = run(agent)
        assert outcome is not None and outcome.text is None, reply
        assert outcome.result["total_tokens"] == 10


def test_collapses_whitespace_and_caps_the_length(agent: FakeAgent) -> None:
    agent.summary = "tell   me\tmore"
    assert run(agent).text == "tell me more"

    agent.summary = "word " * 100
    text = run(agent).text
    assert text is not None and len(text) <= suggestions.SUGGESTION_MAX


def test_an_agent_failure_is_none(agent: FakeAgent) -> None:
    agent.fail = "agent down"

    assert run(agent) is None


def test_the_prompt_keeps_the_start_of_the_question_and_the_end_of_the_answer(agent: FakeAgent) -> None:
    question = "Q" * 5000 + "END_OF_QUESTION"
    answer = "START_OF_ANSWER" + "A" * 5000

    prompt = suggestions.build_prompt(question, answer)

    assert "END_OF_QUESTION" not in prompt and "START_OF_ANSWER" not in prompt
    assert prompt.count("Q") <= suggestions.EXCHANGE_MAX + 50
    assert prompt.count("A") <= suggestions.EXCHANGE_MAX + 50


# --- last_exchange ---------------------------------------------------------------

ASK = {"role": "user", "content": "What is the capital of France?"}
REPLY = {"role": "assistant", "content": "Paris."}


def test_last_exchange_is_the_final_plain_pair() -> None:
    earlier = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]

    assert suggestions.last_exchange([*earlier, ASK, REPLY]) == ("What is the capital of France?", "Paris.")


def test_last_exchange_is_none_when_there_is_nothing_to_follow_up() -> None:
    cases = {
        "empty": [],
        "only a question": [ASK],
        "ends on a question": [REPLY, ASK],
        "question too short": [{"role": "user", "content": "hi"}, REPLY],
        "empty answer": [ASK, {"role": "assistant", "content": "  "}],
        "an error answer": [ASK, {"role": "assistant", "content": "error: the agent is down"}],
        "a cancelled answer": [ASK, {"role": "assistant", "content": "⏹️ Cancelled."}],
        "a cancelled answer from the agent": [ASK, {"role": "assistant", "content": "Cancelled."}],
        "an interrupted answer": [ASK, {"role": "assistant", "content": "partial\n\n⚠️ Interrupted: ember_api stopped before the answer finished."}],
        "a slash command": [{**ASK, "kind": "command"}, {**REPLY, "kind": "command"}],
        "a summary": [{"role": "assistant", "kind": "summary", "content": "S"}, {"role": "assistant", "kind": "log_attachment", "content": "L"}],
    }
    for name, messages in cases.items():
        assert suggestions.last_exchange(messages) is None, name


# --- cache -----------------------------------------------------------------------


def test_cache_remembers_a_miss_and_a_none_and_forgets_the_oldest() -> None:
    cache = suggestions.SuggestionCache(size=2)
    assert cache.lookup("a") == (False, None)

    cache.put("a", "first")
    cache.put("b", None)
    assert cache.lookup("a") == (True, "first")
    assert cache.lookup("b") == (True, None)

    cache.put("c", "third")  # lookup order was a, b: "a" is the least recently used

    assert cache.lookup("c") == (True, "third")
    assert cache.lookup("b") == (True, None)
    assert cache.lookup("a") == (False, None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_suggestions.py -q`
Expected: FAIL (`ImportError: cannot import name 'suggestions'`).

- [ ] **Step 3: Implement the service**

Create `apps/ember_api/src/services/suggestions.py`:

```python
"""Prompt suggestion: the message the user is most likely to type next.

One plain model call (`interpret`, no tools) over the last question and
answer, made after a turn ended. It is a nicety: every failure just means "no
suggestion", and it never touches the turn itself.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from src.services.agent_gateway import AgentCallError, AgentGateway, Caller
from src.services.chat_service import ChatMessage

logger = logging.getLogger(__name__)

SUGGESTION_MAX = 120
# How much of the question (its start) and the answer (its end) the model sees.
EXCHANGE_MAX = 2000
MIN_QUESTION = 3
NO_SUGGESTION = "NONE"
CACHE_SIZE = 256
# Saved assistant messages that are not an answer to follow up on.
_NOT_ANSWERS = ("error:", "⏹️")
_CANCELLED = "Cancelled."
_INTERRUPTED = "⚠️ Interrupted"


@dataclass(frozen=True)
class SuggestionOutcome:
    """`text` is None when the model saw no natural follow-up; `result` is
    the raw interpret() result, so its tokens are still accounted for."""

    text: str | None
    result: dict[str, Any]


def build_prompt(question: str, answer: str) -> str:
    return (
        "Below is the last exchange of a chat between a user and an AI assistant. "
        "Predict the single message the user is most likely to type next, written "
        "exactly as the user would type it. Rules: at most 120 characters, one "
        "line, plain text, no quotes, no preamble, no explanation. If there is no "
        f"natural follow-up, reply with exactly {NO_SUGGESTION}.\n\n"
        f"--- USER ---\n{question[:EXCHANGE_MAX]}\n\n"
        f"--- ASSISTANT ---\n{answer[-EXCHANGE_MAX:]}"
    )


def clean(raw: str) -> str | None:
    """The first line of the model's reply, tidied; None for NONE or nothing."""
    lines = raw.strip().splitlines()
    line = " ".join(lines[0].split()) if lines else ""
    line = line.strip("\"'`“”‘’ ")
    if not line or line.rstrip(".").upper() == NO_SUGGESTION:
        return None
    return line[:SUGGESTION_MAX].rstrip()


def _is_answer(text: str) -> bool:
    return bool(text) and not text.startswith(_NOT_ANSWERS) and text != _CANCELLED and _INTERRUPTED not in text


def last_exchange(messages: list[ChatMessage]) -> tuple[str, str] | None:
    """(question, answer) of the chat's last plain user/assistant pair; None
    when the chat does not end on one (a slash command, a summary, an error or
    cancelled answer, a question too short to say anything)."""
    if len(messages) < 2:
        return None
    question, answer = messages[-2], messages[-1]
    if question.get("role") != "user" or answer.get("role") != "assistant":
        return None
    if question.get("kind") or answer.get("kind"):
        return None
    asked = str(question.get("content") or "").strip()
    replied = str(answer.get("content") or "").strip()
    if len(asked) < MIN_QUESTION or not _is_answer(replied):
        return None
    return asked, replied


async def suggest(
    gateway: AgentGateway, url: str, caller: Caller, question: str, answer: str
) -> SuggestionOutcome | None:
    """None only when the agent call failed (nothing was spent)."""
    try:
        result = await gateway.interpret(url, caller, build_prompt(question, answer))
    except AgentCallError as error:
        logger.info("prompt suggestion skipped: %s", error)
        return None
    return SuggestionOutcome(clean(str(result.get("response") or "")), result)


class SuggestionCache:
    """The last few answers, so reopening a chat (or a second tab) does not pay
    for the same suggestion again. A "no suggestion" is remembered too."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self._size = size
        self._items: OrderedDict[Any, str | None] = OrderedDict()

    def lookup(self, key: Any) -> tuple[bool, str | None]:
        if key not in self._items:
            return False, None
        self._items.move_to_end(key)
        return True, self._items[key]

    def put(self, key: Any, text: str | None) -> None:
        self._items[key] = text
        self._items.move_to_end(key)
        while len(self._items) > self._size:
            self._items.popitem(last=False)


CACHE = SuggestionCache()


def cache_key(account_id: int, chat_id: str, message_count: int, answer: str) -> tuple[int, str, int, int]:
    return account_id, chat_id, message_count, hash(answer)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_suggestions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (ask the user first)**

```bash
git add apps/ember_api/src/services/suggestions.py apps/ember_api/tests/test_suggestions.py
git commit -m "feat(ember_api): suggestion service (one interpret call over the last exchange)"
```

---

### Task 3: Suggestion route (ember_api)

**Files:**
- Modify: `apps/ember_api/src/routes/chats.py` (imports ~lines 28-61; new model near `TurnOut` ~line 357; route after `get_chat`, ~line 474)
- Test: `apps/ember_api/tests/test_suggestions.py` (append)
- Modify: `apps/ember_api/README.md`

**Interfaces:**
- Consumes (Task 2): `suggestions.last_exchange`, `suggestions.suggest`, `suggestions.CACHE`, `suggestions.cache_key`, `SuggestionOutcome`. (Task 1): `Account.prompt_suggestions`.
- Produces: `GET /api/chats/{chat_id}/suggestion` -> `{"text": str | None}`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/ember_api/tests/test_suggestions.py`. First extend the imports at the top of the file:

```python
from fastapi.testclient import TestClient

from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin
from tests.test_turns import AGENT_ID, chat as get_chat, new_id, start, wait_until
```

(replace the existing `from tests.conftest import FakeAgent` line), then add at the end:

```python
# --- GET /api/chats/{id}/suggestion -------------------------------------------------


def seed(client: TestClient, chat_id: str, question: str = "What is the capital of France?", answer: str = "Paris.") -> None:
    messages = [{"role": "user", "content": question}]
    if answer:
        messages.append({"role": "assistant", "content": answer})
    response = client.put(
        f"/api/chats/{chat_id}", json={"title": "t", "agent_id": AGENT_ID, "messages": messages}
    )
    assert response.status_code == 200, response.text


def suggestion(client: TestClient, chat_id: str):
    return client.get(f"/api/chats/{chat_id}/suggestion")


def test_suggestion_needs_login(client: TestClient) -> None:
    assert suggestion(client, new_id()).status_code == 401


def test_suggestion_needs_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, verify=False)
    login(client, "alice")

    assert suggestion(client, new_id()).status_code == 403


def test_suggestion_of_an_unknown_or_foreign_chat_is_404(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    assert suggestion(client, new_id()).status_code == 404
    make_member(client, email)  # logs the admin out
    login(client, "alice")

    assert suggestion(client, chat_id).status_code == 404


def test_suggests_after_an_answer_records_usage_and_asks_only_once(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.summary = "And what about Germany?"

    first = suggestion(client, chat_id)

    assert first.status_code == 200
    assert first.json() == {"text": "And what about Germany?"}
    assert "What is the capital of France?" in agent.interprets[0]
    rows = client.get("/api/usage/records").json()
    assert [r["kind"] for r in rows] == ["suggestion"]
    assert rows[0]["chat_id"] == chat_id
    # Reopening the chat asks nobody and costs nothing.
    assert suggestion(client, chat_id).json() == {"text": "And what about Germany?"}
    assert len(agent.interprets) == 1
    assert len(client.get("/api/usage/records").json()) == 1


def test_suggests_for_an_answer_written_by_a_real_turn(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.summary = "Tell me more"
    start(client, chat_id, "hi there")
    wait_until(lambda: not get_chat(client, chat_id)["running"])

    assert suggestion(client, chat_id).json() == {"text": "Tell me more"}


def test_a_new_answer_gets_a_new_suggestion(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.summary = "first"
    assert suggestion(client, chat_id).json() == {"text": "first"}
    seed(client, chat_id, question="And Spain?", answer="Madrid.")
    agent.summary = "second"

    assert suggestion(client, chat_id).json() == {"text": "second"}


def test_no_call_when_the_account_switched_suggestions_off(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    client.patch("/api/account/preferences", json={"prompt_suggestions": False})

    assert suggestion(client, chat_id).json() == {"text": None}
    assert agent.interprets == []


def test_no_call_while_an_answer_is_running(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    agent.hold = True
    start(client, chat_id, "a long question")
    wait_until(lambda: len(agent.asks) == 1)

    assert suggestion(client, chat_id).json() == {"text": None}
    assert agent.interprets == []
    agent.release()
    wait_until(lambda: not get_chat(client, chat_id)["running"])


def test_no_call_when_there_is_nothing_to_follow_up(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    cases = {
        "no answer yet": dict(answer=""),
        "a question too short": dict(question="hi"),
        "an error answer": dict(answer="error: the agent is down"),
        "a cancelled answer": dict(answer="⏹️ Cancelled."),
    }
    for name, kwargs in cases.items():
        chat_id = new_id()
        seed(client, chat_id, **kwargs)

        assert suggestion(client, chat_id).json() == {"text": None}, name
    assert agent.interprets == []


def test_a_failing_agent_gives_no_suggestion_and_no_error(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.fail = "agent down"

    response = suggestion(client, chat_id)

    assert response.status_code == 200
    assert response.json() == {"text": None}
    assert client.get("/api/usage/records").json() == []
    # Not remembered: the next try may work.
    agent.fail = None
    agent.summary = "back again"
    assert suggestion(client, chat_id).json() == {"text": "back again"}


def test_a_none_reply_is_no_suggestion_but_is_accounted_for(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    agent.summary = "NONE"

    assert suggestion(client, chat_id).json() == {"text": None}
    assert [r["kind"] for r in client.get("/api/usage/records").json()] == ["suggestion"]
    assert suggestion(client, chat_id).json() == {"text": None}
    assert len(agent.interprets) == 1


def test_no_suggestion_without_a_running_agent(client: TestClient, agent: FakeAgent, tmp_path) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)
    (tmp_path / "config_agents.json").write_text('{"agents": []}', encoding="utf-8")

    assert suggestion(client, chat_id).json() == {"text": None}
    assert agent.interprets == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_suggestions.py -q -k "suggestion or suggests or no_call or none_reply"`
Expected: FAIL (404 from the missing route, or 405).

- [ ] **Step 3: Add the route**

In `apps/ember_api/src/routes/chats.py`:

Add `suggestions` to the services import (line 31): `from src.services import suggestions, summarization`.

Add the response model after `TurnOut` (~line 357-361):

```python
class SuggestionOut(BaseModel):
    # The message the user will probably type next; null for "none".
    text: str | None = None
```

Add the route right after `get_chat` (before `put_chat`):

```python
@router.get("/{chat_id}/suggestion")
async def chat_suggestion(
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_db_session),
    turns: TurnRegistry = Depends(get_turns),
    directory: AgentDirectory = Depends(get_agent_directory),
    gateway: AgentGateway = Depends(get_agent_gateway),
    settings: Settings = Depends(get_settings),
) -> SuggestionOut:
    """The message the user will probably type next, for the chat box's
    placeholder. Never an error: anything that stops it (switched off, an
    answer still running, nothing to follow up, no agent, usage limit, agent
    failure) is `{text: null}`. One small model call, counted in the usage
    like a chat turn, remembered per answer."""
    try:
        chat = await chats.get(chat_id)
    except ChatNotFound as error:
        raise _not_found() from error
    if not account.prompt_suggestions or turns.is_running(account.id, chat_id):
        return SuggestionOut()
    messages = decode_messages(chat)
    exchange = suggestions.last_exchange(messages)
    if exchange is None:
        return SuggestionOut()
    question, answer = exchange
    key = suggestions.cache_key(account.id, chat_id, len(messages), answer)
    known, cached = suggestions.CACHE.lookup(key)
    if known:
        return SuggestionOut(text=cached)
    agent = await directory.entry()
    if agent is None:
        return SuggestionOut()
    usage = UsageService(session, settings.usage)
    if await usage.check(account.id) is not None:
        return SuggestionOut()
    outcome = await suggestions.suggest(gateway, agent.url, _caller(account), question, answer)
    if outcome is None:
        return SuggestionOut()
    await usage.record(account.id, uuid.uuid4().hex, "suggestion", chat_id, outcome.result)
    suggestions.CACHE.put(key, outcome.text)
    return SuggestionOut(text=outcome.text)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv_ember_api\Scripts\python -m pytest tests/test_suggestions.py -q`
Expected: PASS.

- [ ] **Step 5: Update the README API table**

In `apps/ember_api/README.md`, in the API table, add next to the other `/api/chats/{id}/...` rows:

```
| `GET /api/chats/{id}/suggestion` | `chat.use` | The message the user will probably type next, `{text}` (null for none). One small model call per answer, cached, counted in usage as kind `suggestion`; off when the account's `prompt_suggestions` is off. |
```

and next to the other `/api/account/...` rows:

```
| `PATCH /api/account/preferences` | logged in | `{prompt_suggestions: bool}`: whether chat suggests the next prompt. Returns the account. |
```

Match the column layout of the existing rows exactly (read the table first). Also mention `prompt_suggestions` in the description of the account object if the README lists its fields.

- [ ] **Step 6: Run the whole ember_api suite**

Run: `.venv_ember_api\Scripts\python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit (ask the user first)**

```bash
git add apps/ember_api/src/routes/chats.py apps/ember_api/tests/test_suggestions.py apps/ember_api/README.md
git commit -m "feat(ember_api): GET /api/chats/{id}/suggestion"
```

---

### Task 4: Preference in ember_web (client, store, Settings toggle)

**Files:**
- Modify: `apps/ember_web/src/api/AuthClient.ts`
- Modify: `apps/ember_web/src/stores/auth.ts`
- Modify: `apps/ember_web/src/views/SettingsView.vue`
- Test: `apps/ember_web/src/views/SettingsView.test.ts`

**Interfaces:**
- Consumes (Task 1): `PATCH /api/account/preferences`, `Account.prompt_suggestions`.
- Produces (used by Tasks 5-6): `Account.prompt_suggestions?: boolean`; `authClient.setPreferences({prompt_suggestions: boolean}): Promise<Account>`; auth store `promptSuggestions: ComputedRef<boolean>` (absent counts as true) and `setPromptSuggestions(on: boolean): Promise<void>`.

- [ ] **Step 1: Write the failing tests**

In `apps/ember_web/src/views/SettingsView.test.ts`:

1. Add imports: `import { authClient } from "../api/AuthClient";`.
2. Update the existing expectations for the new row. Line 72 becomes
   `expect(rowIds(w)).toEqual(["chat-terse", "chat-ask-tools", "chat-chime", "chat-suggestions", "appearance-theme", "sidebar-pages"]);`
   and every `toHaveLength(5)` (lines ~176, 186, 197, 238, 251) becomes `toHaveLength(6)`. Read each of those tests first: if one is for an admin account, its count is one higher than a member's - keep the difference, add 1.
3. Add inside `describe("SettingsView", ...)`:

```ts
  it("turns prompt suggestions off on the server and marks the setting as modified", async () => {
    const w = await mountView();
    const set = vi
      .spyOn(authClient, "setPreferences")
      .mockResolvedValue({ ...useAuthStore().account!, prompt_suggestions: false });
    expect(row(w, "chat-suggestions").find("button.reset").exists()).toBe(false);

    await row(w, "chat-suggestions").get("input").setValue(false);
    await flushPromises();

    expect(set).toHaveBeenCalledWith({ prompt_suggestions: false });
    expect(useAuthStore().promptSuggestions).toBe(false);
    expect(row(w, "chat-suggestions").find("button.reset").exists()).toBe(true);
  });

  it("resets prompt suggestions to on, which is their default", async () => {
    const w = await mountView();
    useAuthStore().account = { ...useAuthStore().account!, prompt_suggestions: false };
    const set = vi
      .spyOn(authClient, "setPreferences")
      .mockResolvedValue({ ...useAuthStore().account!, prompt_suggestions: true });
    await flushPromises();

    await row(w, "chat-suggestions").get("button.reset").trigger("click");
    await flushPromises();

    expect(set).toHaveBeenCalledWith({ prompt_suggestions: true });
    expect(useAuthStore().promptSuggestions).toBe(true);
  });

  it("keeps the old value when the server refuses the change", async () => {
    const w = await mountView();
    vi.spyOn(authClient, "setPreferences").mockRejectedValue(new Error("down"));
    vi.spyOn(console, "warn").mockImplementation(() => undefined);

    await row(w, "chat-suggestions").get("input").setValue(false);
    await flushPromises();

    expect(useAuthStore().promptSuggestions).toBe(true);
  });
```

- [ ] **Step 2: Run to verify they fail**

Run (from `apps/ember_web/`): `npx vitest run src/views/SettingsView.test.ts`
Expected: FAIL (`setPreferences` not a function / row missing).

- [ ] **Step 3: Client**

In `apps/ember_web/src/api/AuthClient.ts` add to `Account` (after `email_verification_required`):

```ts
  /** The chat suggests the next prompt after each answer. Absent counts as true. */
  prompt_suggestions?: boolean;
```

and to `authClient` (after `changePassword`):

```ts
  setPreferences: (prefs: { prompt_suggestions: boolean }) =>
    apiRequest<Account>("PATCH", "/api/account/preferences", prefs),
```

- [ ] **Step 4: Auth store**

In `apps/ember_web/src/stores/auth.ts`, after `needsVerification`:

```ts
  /** The chat suggests the next prompt (an account switch kept on the server). */
  const promptSuggestions = computed(() => account.value?.prompt_suggestions !== false);
```

after `changePassword`:

```ts
  /** The server makes the model call only while this is on. */
  async function setPromptSuggestions(on: boolean): Promise<void> {
    account.value = await authClient.setPreferences({ prompt_suggestions: on });
  }
```

and add `promptSuggestions` and `setPromptSuggestions` to the returned object.

- [ ] **Step 5: Settings row**

In `apps/ember_web/src/views/SettingsView.vue`:

Add to `DEFS` after `chat-chime`:

```ts
  {
    id: "chat-suggestions",
    group: "chat",
    label: "Suggest next prompt",
    description: "Show a predicted next message in the chat box; press Tab to use it. Uses a small model call per answer. Saved to your account.",
    keywords: ["autocomplete", "tab", "placeholder", "prediction", "follow-up"],
  },
```

Add to the `modified` computed: `"chat-suggestions": !auth.promptSuggestions,`.

Add a function in the script:

```ts
/** Saved on the server; the switch only moves once it has said yes. */
function setSuggestions(on: boolean): void {
  auth.setPromptSuggestions(on).catch((err: unknown) => console.warn("ember_web: saving the preference failed", err));
}
```

Add the row after the `chat-chime` row inside the chat card:

```vue
          <SettingRow
            v-if="shown.has('chat-suggestions')"
            setting-id="chat-suggestions"
            label="Suggest next prompt"
            description="Show a predicted next message in the chat box; press Tab to use it. Uses a small model call per answer. Saved to your account."
            :modified="modified['chat-suggestions']"
            @reset="setSuggestions(true)"
          >
            <ToggleSwitch
              small
              aria-label="Suggest next prompt"
              :checked="auth.promptSuggestions"
              @change="setSuggestions(checked($event))"
            />
          </SettingRow>
```

- [ ] **Step 6: Run to verify they pass**

Run: `npx vitest run src/views/SettingsView.test.ts`
Expected: PASS. If the "keeps the old value" test fails because the checkbox DOM stays unchecked-but-store-true, that is fine only if the store assertion passes; the assertion is on the store.

- [ ] **Step 7: Commit (ask the user first)**

```bash
git add apps/ember_web/src/api/AuthClient.ts apps/ember_web/src/stores/auth.ts apps/ember_web/src/views/SettingsView.vue apps/ember_web/src/views/SettingsView.test.ts
git commit -m "feat(ember_web): prompt suggestion setting"
```

---

### Task 5: Suggestion state in the chat store

**Files:**
- Modify: `apps/ember_web/src/api/ChatsClient.ts`
- Modify: `apps/ember_web/src/stores/chat.ts`
- Test: `apps/ember_web/src/stores/chat.suggestion.test.ts` (create)

**Interfaces:**
- Consumes (Task 4): `useAuthStore().promptSuggestions`. (Task 3): `GET /api/chats/{id}/suggestion`.
- Produces (used by Task 6): `chatsClient.suggestion(id: string): Promise<{ text: string | null }>`; chat store `suggestion: Ref<string | null>` and `clearSuggestion(): void`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_web/src/stores/chat.suggestion.test.ts`:

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
    list: vi.fn(),
    get: vi.fn(),
    startTurn: vi.fn(),
    cancel: vi.fn(),
    search: vi.fn(),
    remove: vi.fn(),
    removeAll: vi.fn(),
    rename: vi.fn(),
    importChats: vi.fn(),
    append: vi.fn(),
    branch: vi.fn(),
    suggestion: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({ chimeIfAway: vi.fn() }));
vi.mock("../services/slashCommands", () => ({
  SlashCommandRunner: class {
    run = vi.fn();
    list = vi.fn(async () => []);
    schemaFor = vi.fn(async () => null);
  },
}));

const client = vi.mocked(chatsClient);
const watch = vi.mocked(watchTurn);

const ACCOUNT = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use"],
};

const summary = (id: string, count = 0, running = false): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: count,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running,
});

const TWO: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
];

let emit: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};
let endStream: (end: WatchEnd) => void = () => {
  throw new Error("no answer is being watched");
};
const fire = (event: Record<string, unknown>) => emit({ sequence: 1, ...event } as TurnEvent);
const finalEvent = (cancelled = false) => ({ type: "final", message: { role: "assistant", content: "done" }, cancelled });

async function storeWith(chats: Record<string, ChatMessage[]>, running: string[] = [], account = ACCOUNT) {
  setActivePinia(createPinia());
  useAuthStore().account = account;
  client.list.mockResolvedValue(Object.entries(chats).map(([id, m]) => summary(id, m.length, running.includes(id))));
  client.get.mockImplementation(async (id: string) => ({
    ...summary(id, chats[id]!.length, running.includes(id)),
    messages: structuredClone(chats[id]!),
  }));
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

/** A chat whose answer is being written. */
async function running(chats: Record<string, ChatMessage[]> = { c1: TWO }) {
  const chat = await storeWith(chats);
  await chat.selectChat("c1");
  await chat.send("ask something");
  client.suggestion.mockClear();
  return chat;
}

async function answered() {
  fire(finalEvent());
  endStream("done");
  await flushPromises();
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  watch.mockImplementation(
    (_id, _after, onEvent) =>
      new Promise<WatchEnd>((resolve) => {
        emit = onEvent;
        endStream = resolve;
      }),
  );
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1", 2, true) }, sequence: 5 });
  client.append.mockResolvedValue(undefined as never);
  client.search.mockResolvedValue([]);
  client.suggestion.mockResolvedValue({ text: null });
});

describe("the suggested next prompt", () => {
  it("is fetched when an answer arrives", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });

    await answered();

    expect(client.suggestion).toHaveBeenCalledWith("c1");
    expect(chat.suggestion).toBe("Tell me more");
  });

  it("is not fetched for a stopped or a failed answer", async () => {
    const chat = await running();
    fire(finalEvent(true));
    endStream("done");
    await flushPromises();
    expect(client.suggestion).not.toHaveBeenCalled();

    await chat.send("again");
    client.suggestion.mockClear();
    fire({ type: "error", message: "boom" });
    endStream("done");
    await flushPromises();

    expect(client.suggestion).not.toHaveBeenCalled();
    expect(chat.suggestion).toBeNull();
  });

  it("is never fetched while the account has suggestions switched off", async () => {
    const chat = await storeWith({ c1: TWO }, [], { ...ACCOUNT, prompt_suggestions: false } as typeof ACCOUNT);
    await chat.selectChat("c1");
    await chat.send("ask something");

    await answered();

    expect(client.suggestion).not.toHaveBeenCalled();
    expect(chat.suggestion).toBeNull();
  });

  it("disappears when suggestions are switched off", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });
    await answered();
    expect(chat.suggestion).toBe("Tell me more");

    useAuthStore().account = { ...ACCOUNT, prompt_suggestions: false } as typeof ACCOUNT;
    await flushPromises();

    expect(chat.suggestion).toBeNull();
  });

  it("goes when the next question is sent", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });
    await answered();

    await chat.send("something else");

    expect(chat.suggestion).toBeNull();
  });

  it("goes when a new chat is started", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });
    await answered();

    chat.newChat();

    expect(chat.suggestion).toBeNull();
  });

  it("is dropped when it arrives after another chat was opened", async () => {
    const chat = await running({ c1: TWO, c2: TWO });
    const replies: Array<(value: { text: string | null }) => void> = [];
    client.suggestion.mockImplementation(() => new Promise((resolve) => replies.push(resolve)));
    await answered(); // asks for c1's suggestion; it is still on its way
    await chat.selectChat("c2"); // asks for c2's

    replies[0]!({ text: "meant for c1" });
    await flushPromises();
    expect(chat.suggestion).toBeNull();

    replies[1]!({ text: "meant for c2" });
    await flushPromises();
    expect(chat.suggestion).toBe("meant for c2");
  });

  it("is fetched when a finished chat is opened", async () => {
    const chat = await storeWith({ c1: TWO });
    client.suggestion.mockResolvedValue({ text: "What next?" });

    await chat.selectChat("c1");
    await flushPromises();

    expect(client.suggestion).toHaveBeenCalledWith("c1");
    expect(chat.suggestion).toBe("What next?");
  });

  it("is not fetched when the chat opened is still answering", async () => {
    const chat = await storeWith({ c1: TWO }, ["c1"]);

    await chat.selectChat("c1");
    await flushPromises();

    expect(client.suggestion).not.toHaveBeenCalled();
    expect(chat.suggestion).toBeNull();
  });

  it("a failed fetch leaves no suggestion and no error", async () => {
    const chat = await running();
    client.suggestion.mockRejectedValue(new Error("502"));

    await answered();

    expect(chat.suggestion).toBeNull();
    expect(chat.loadError).toBe("");
    expect(chat.sendError).toBe("");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/stores/chat.suggestion.test.ts`
Expected: FAIL (`chat.suggestion` is undefined / `chatsClient.suggestion` missing).

- [ ] **Step 3: Client method**

In `apps/ember_web/src/api/ChatsClient.ts` add to `chatsClient` after `get`:

```ts
  /** The message the user will probably type next ({text: null} for none). */
  suggestion: (id: string) => apiRequest<{ text: string | null }>("GET", `${path(id)}/suggestion`),
```

- [ ] **Step 4: Store state and fetch**

In `apps/ember_web/src/stores/chat.ts`:

After the `chime` ref (line ~180) add:

```ts
  // The predicted next question, for the chat box's placeholder (Tab takes it).
  // A new request number makes a slower, older answer harmless.
  const suggestion = ref<string | null>(null);
  let suggestionRequest = 0;
```

Before `loadChat` (line ~376) add:

```ts
  function clearSuggestion(): void {
    suggestionRequest += 1;
    suggestion.value = null;
  }

  /** Asks ember_api for chat `id`'s suggestion. Silent on any failure: it is
   * a nicety, and a stale answer (another chat opened, a question sent) is dropped. */
  async function fetchSuggestion(id: string): Promise<void> {
    clearSuggestion();
    if (!auth.promptSuggestions || activeId.value !== id) return;
    const request = suggestionRequest;
    try {
      const { text } = await chatsClient.suggestion(id);
      if (request === suggestionRequest && activeId.value === id) suggestion.value = text;
    } catch {
      // No suggestion; nothing to tell the user.
    }
  }

  watch(
    () => auth.promptSuggestions,
    (on) => {
      if (!on) clearSuggestion();
    },
  );
```

In the account watcher (the `watch(() => (auth.hasPermission("chat.use") ...` callback), add `clearSuggestion();` right after `unfollow();`.

In `follow` replace the `.then(async (end) => {...` body so it reads:

```ts
      .then(async (end) => {
        if (end === "aborted" || started !== generation) return;
        const answered = end === "done" && turnOutcome === "answered";
        if (answered && chime.value) chimeIfAway();
        const conversation = find(id);
        if (conversation) conversation.running = false;
        if (watcher === controller) unfollow();
        await loadChat(id);
        if (answered && activeId.value === id) void fetchSuggestion(id);
      })
```

In `send`, after `sendError.value = "";` (line ~645) add `clearSuggestion();`.

In `newChat` add `clearSuggestion();` after `unfollow();`.

In `selectChat` replace the body after the early `if (id === activeId.value) return;` with:

```ts
    unfollow();
    clearSuggestion();
    sendError.value = "";
    activeId.value = id;
    scheduleBackgroundPoll();
    if (conversation.messagesLoaded === false || conversation.running) await loadChat(id);
    if (activeId.value === id && !find(id)?.running) void fetchSuggestion(id);
```

In `deleteChats`, inside the `if (activeId.value !== null && doomed.has(activeId.value)) {` block (after `unfollow();`) add `clearSuggestion();`. Do the same in the second identical block near line ~1050 (find it with Grep for `doomed.has(activeId.value)`).

At the top of the functions `clearChat` and `summarizeChat` (find with Grep `function clearChat|function summarizeChat`), add `clearSuggestion();` as the first statement, so a stale suggestion about the old history is not offered.

Add `suggestion,` and `clearSuggestion,` to the returned object (next to `chime`).

- [ ] **Step 5: Run to verify they pass**

Run: `npx vitest run src/stores/chat.suggestion.test.ts`
Expected: PASS.

- [ ] **Step 6: Run the other chat store tests**

Run: `npx vitest run src/stores`
Expected: PASS. Other test files mock `chatsClient` without a `suggestion` function: `selectChat` now calls `chatsClient.suggestion` on open, which throws `TypeError` inside the `try`, so it is swallowed. If any test fails anyway, add `suggestion: vi.fn().mockResolvedValue({ text: null })` to that file's `chatsClient` mock.

- [ ] **Step 7: Commit (ask the user first)**

```bash
git add apps/ember_web/src/api/ChatsClient.ts apps/ember_web/src/stores/chat.ts apps/ember_web/src/stores/chat.suggestion.test.ts
git commit -m "feat(ember_web): fetch the suggested next prompt after an answer"
```

---

### Task 6: Placeholder and Tab in the chat box

**Files:**
- Modify: `apps/ember_web/src/components/ChatInput.vue` (props ~line 22, emits ~38, `onKeydown` ~368, textarea ~428, hint ~423)
- Modify: `apps/ember_web/src/views/ChatView.vue` (`storeToRefs` block ~33-65, `<ChatInput>` ~391)
- Modify: `apps/ember_web/e2e/fakeApi.ts` (before the `/api/chats` list route, ~line 259)
- Modify: `apps/ember_web/README.md`
- Test: `apps/ember_web/src/components/ChatInput.test.ts`

**Interfaces:**
- Consumes (Task 5): `chat.suggestion`, `chat.clearSuggestion`.
- Produces: `ChatInput` prop `suggestion?: string | null`, emit `suggestionUsed` (template event `@suggestion-used`).

- [ ] **Step 1: Write the failing tests**

Append to `apps/ember_web/src/components/ChatInput.test.ts`:

```ts
describe("the suggested next prompt", () => {
  const valueOf = (wrapper: ReturnType<typeof mountInput>) => (wrapper.find("textarea").element as HTMLTextAreaElement).value;
  const placeholder = (wrapper: ReturnType<typeof mountInput>) => wrapper.find("textarea").attributes("placeholder");

  it("is the placeholder while the box is empty", () => {
    const wrapper = mountInput({ suggestion: "Tell me more" });

    expect(placeholder(wrapper)).toBe("Tell me more");
    expect(wrapper.find(".recall").text()).toBe("Tab to use the suggestion");
  });

  it("keeps the usual placeholder without one", () => {
    const wrapper = mountInput();

    expect(placeholder(wrapper)).toContain("Ask something");
    expect(wrapper.find(".recall").exists()).toBe(false);
  });

  it("gives way to what is typed and comes back when the box is emptied", async () => {
    const wrapper = mountInput({ suggestion: "Tell me more" });

    await wrapper.find("textarea").setValue("hel");
    expect(placeholder(wrapper)).toContain("Ask something");
    expect(wrapper.find(".recall").exists()).toBe(false);
    await wrapper.find("textarea").setValue("");

    expect(placeholder(wrapper)).toBe("Tell me more");
  });

  it("Tab puts it in the box and tells the parent, without sending", async () => {
    const wrapper = mountInput({ suggestion: "Tell me more" });

    await wrapper.find("textarea").trigger("keydown", { key: "Tab" });

    expect(valueOf(wrapper)).toBe("Tell me more");
    expect(wrapper.emitted("suggestionUsed")).toHaveLength(1);
    expect(wrapper.emitted("send")).toBeUndefined();
  });

  it("can be edited after Tab, then sent as typed", async () => {
    const wrapper = mountInput({ suggestion: "Tell me more" });
    await wrapper.find("textarea").trigger("keydown", { key: "Tab" });

    await wrapper.find("textarea").setValue("Tell me more about Dune");
    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("send")).toEqual([["Tell me more about Dune"]]);
  });

  it("Enter on an empty box does not send it", async () => {
    const wrapper = mountInput({ suggestion: "Tell me more" });

    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("send")).toBeUndefined();
    expect(valueOf(wrapper)).toBe("");
  });

  it("Tab does nothing special when something is typed, or with Shift, or while composing", async () => {
    const wrapper = mountInput({ suggestion: "Tell me more" });
    await wrapper.find("textarea").setValue("my own words");

    await wrapper.find("textarea").trigger("keydown", { key: "Tab" });
    expect(valueOf(wrapper)).toBe("my own words");

    await wrapper.find("textarea").setValue("");
    await wrapper.find("textarea").trigger("keydown", { key: "Tab", shiftKey: true });
    await wrapper.find("textarea").trigger("keydown", { key: "Tab", isComposing: true });
    expect(valueOf(wrapper)).toBe("");
    expect(wrapper.emitted("suggestionUsed")).toBeUndefined();
  });

  it("Tab does nothing without a suggestion", async () => {
    const wrapper = mountInput();

    await wrapper.find("textarea").trigger("keydown", { key: "Tab" });

    expect(valueOf(wrapper)).toBe("");
    expect(wrapper.emitted("suggestionUsed")).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/ChatInput.test.ts`
Expected: FAIL (placeholder is the default text; no `suggestionUsed`).

- [ ] **Step 3: ChatInput**

In `apps/ember_web/src/components/ChatInput.vue`:

Props: add `suggestion?: string | null;` to the `defineProps` type (after `templatesError?: string;`) and `suggestion: null` to the defaults object.

Add above the props comment block's `// form:` lines, extending the doc comment:

```ts
// suggestion: the predicted next question. It is the placeholder while the box
// is empty; Tab on the empty box takes it (suggestionUsed), and it can be edited.
```

Emits: add `suggestionUsed: [];` to `defineEmits`.

After the `canSend` computed add:

```ts
const placeholder = computed(() => {
  if (draft.value === "" && props.suggestion) return props.suggestion;
  return props.commands.length
    ? "Ask something, / for commands, # for saved prompts"
    : "Ask something, # for saved prompts";
});
```

In `onKeydown`, right after `const open = suggestions.value.length > 0;` add:

```ts
  // The predicted next question: Tab on an empty box takes it.
  if (
    event.key === "Tab" &&
    !event.shiftKey &&
    !event.isComposing &&
    !open &&
    draft.value === "" &&
    props.suggestion
  ) {
    event.preventDefault();
    draft.value = props.suggestion;
    recallIndex.value = null;
    emit("suggestionUsed");
    void nextTick(() => {
      autoGrow();
      const end = draft.value.length;
      textarea.value?.setSelectionRange(end, end);
    });
    return;
  }
```

Template: replace the textarea's `:placeholder="commands.length ? ... : ..."` line with `:placeholder="placeholder"`. Add, just above the existing `<p v-if="recallIndex !== null" class="recall" ...>`:

```vue
    <p v-if="draft === '' && suggestion && recallIndex === null" class="recall">Tab to use the suggestion</p>
```

- [ ] **Step 4: Wire ChatView**

In `apps/ember_web/src/views/ChatView.vue`, add `suggestion,` to the destructure of `storeToRefs(chat)` (lines 33-65, alphabetical order not required), and on `<ChatInput>` add:

```vue
          :suggestion="suggestion"
```
after `:history="history"`, and
```vue
          @suggestion-used="chat.clearSuggestion"
```
after `@form="openCommandForm"`.

- [ ] **Step 5: Fake API for the Playwright test**

In `apps/ember_web/e2e/fakeApi.ts`, insert before the line `if (method === "GET" && path === "/api/chats") return json(...)`:

```ts
    // The predicted next prompt: the fake has none to offer. And the account switch for it.
    if (method === "GET" && /^\/api\/chats\/[^/]+\/suggestion$/.test(path)) return json(route, { text: null });
    if (method === "PATCH" && path === "/api/account/preferences") {
      return json(route, { ...account, ...(request.postDataJSON() as Record<string, unknown>) });
    }
```

- [ ] **Step 6: Run to verify the tests pass**

Run: `npx vitest run src/components/ChatInput.test.ts`
Expected: PASS.

- [ ] **Step 7: Full web verification**

Run each from `apps/ember_web/`:
- `npm test` - Expected: all PASS.
- `npx vue-tsc -b --noEmit` - Expected: prints nothing.
- `npx vite build` - Expected: succeeds; then delete `dist/` (`Remove-Item -Recurse -Force dist`).
- `npm run test:e2e` - Expected: PASS (no "unknown call" failures). If Playwright browsers are not installed, say so in the report instead of skipping silently.

- [ ] **Step 8: Update the README**

In `apps/ember_web/README.md` add a bullet in the Chat features list: "Suggested next prompt: after an answer the chat box shows a predicted next message as its placeholder; Tab fills it in. Switch: Settings > Chat > Suggest next prompt (saved to the account, off means no model call)." Match the surrounding list style (read it first).

- [ ] **Step 9: Hand over for manual testing, then commit (ask the user first)**

The user tests manually (do not launch browser verification agents). Tell them what to check:
1. Ask a question; about a second after the answer the box placeholder becomes a predicted follow-up; Tab fills it; Enter sends.
2. Type something: placeholder returns to normal; clear it: the suggestion returns.
3. Reopen an old chat: its suggestion appears (the second time with no extra model call).
4. Settings > Chat > Suggest next prompt off: no placeholder suggestion; Usage page shows no new `suggestion` rows.

```bash
git add apps/ember_web/src/components/ChatInput.vue apps/ember_web/src/components/ChatInput.test.ts apps/ember_web/src/views/ChatView.vue apps/ember_web/e2e/fakeApi.ts apps/ember_web/README.md
git commit -m "feat(ember_web): show the suggested next prompt as the placeholder, Tab to use it"
```

---

## Self-Review

**Spec coverage:** preference column + migration + `AccountOut` + `PATCH` + audit (Task 1); service with prompt, cleaning, 120-char cap, `NONE`, usage kind `suggestion`, failures non-blocking (Task 2); route with all null conditions and 401/403/404 (Task 3); web client, store fetch on answered and on open, stale guard, clear on send/switch/pref-off (Tasks 4-5); placeholder + Tab + toggle + fakeApi + READMEs (Tasks 4, 6); tests for each listed case.

**Differences from the spec, to tell the user:**
1. `suggest()` returns an outcome object (not `None`) for an empty or `NONE` reply, so the spent tokens are still recorded in usage; `None` only when the call failed.
2. A small in-memory cache (256 entries, keyed by account, chat, message count and answer) was added so reopening a chat does not pay for another model call. The spec's "fetch on open" would otherwise cost a call on every chat open.
3. "Cleared on typing" is implemented as "hidden while the box is non-empty, back when emptied" (the store keeps it until a send, chat switch, or Tab). Same visible behavior, no extra event.
4. The route also returns `null` without a call when the usage limit is reached (same check as summarize).

**Type consistency:** `last_exchange`, `suggest`, `SuggestionOutcome`, `SuggestionCache.lookup/put`, `CACHE`, `cache_key` are defined in Task 2 and used with the same names/signatures in Task 3. `promptSuggestions`/`setPromptSuggestions` (Task 4) are used in Task 5. `suggestion`/`clearSuggestion` (Task 5) are used in Task 6; the `suggestionUsed` emit maps to `@suggestion-used`.
