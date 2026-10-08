# Private Extensions, Part 2: ember_api Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ember_api` stores each account's private extensions (URL, optional headers encrypted at rest), serves them through `/api/user-extensions` with a cached live probe, and hands the account's enabled ones to `ai_agent` with every turn.

**Architecture:** A `user_extensions` table and a `UserExtensionService` (validation, slugs, encryption through a `SecretBox`). An `ExtensionProbe` calls `ai_agent`'s `probe_extension` tool (merged in part 1) through the gateway and caches results for 60 seconds. `routes/chats.py` loads the caller's enabled rows when a turn starts and puts them in `TurnOptions`; `TurnRegistry` passes them to `AgentGateway.ask` and turns the reply's `private_extension_errors` into a `notice` turn event.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy async, Alembic, `cryptography` (Fernet), pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-private-extensions-design.md` (its `ember_api` section). Part 1 (`ai_agent`) is merged; part 3 (`ember_web`) comes after this.

## Global Constraints

- All work is in `apps/ember_api`; run tests from there: `python -m pytest <path> -q`.
- Migration revision is `0009` (`down_revision = "0008"`). `tests/test_migrations.py` gets `HEAD = "0009"`, `NEXT = "0010"`.
- Table `user_extensions`: `id` pk, `account_id` FK `accounts.id` `ON DELETE CASCADE` indexed, `slug` String(40), `label` String(60), `description` String(300), `url` String(1000), `headers_encrypted` Text nullable, `enabled` Boolean (default true), `created_at`, `updated_at` (naive UTC); unique `(account_id, slug)`.
- Slug: lowercase letters and digits joined by single `_` (`^[a-z0-9]+(_[a-z0-9]+)*$`), at most 40 characters, never contains `__`; made from the label, with `_2`, `_3` on collision.
- Limits: 20 extensions per account; at most 20 headers; header name `^[A-Za-z0-9-]{1,64}$`; header value 1 to 2000 characters with no control characters; refused header names `host`, `content-length`, `transfer-encoding`, `connection`, `upgrade`, `te`, `trailer`, `proxy-authorization`, `cookie`; URL `http` or `https`, a host, at most 1000 characters, no username or password.
- Header values never appear in an API reply, a log line, an error message or `repr()` of a turn. The activity log names the label and the URL's host only, never the full URL.
- `EMBER_SECRETS_KEY` is a Fernet key in `.env`; generated and appended on first start if missing; an invalid key stops startup with a clear message; never printed.
- A signed-in account with `chat.use` may manage only its own extensions; another account's slug is 404.
- Probe cache: 60 seconds per `(account, slug)`, keyed by a fingerprint of url and headers; at most 5 probes at once; a result of status `unknown` is not cached.
- The browser can never name an extension URL for a turn: `TurnRequest` gets no new field.
- A turn sends `private_extensions` to `ai_agent` only when the list is non-empty.
- Commit style: `feat(ember_api): ...`. Do not add Co-Authored-By lines when ChatGPT executes this plan; Claude adds `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## File Structure

Create:
- `src/services/secret_box.py`: `SecretBox`, `SecretBoxError`, `ensure_secrets_key`.
- `src/models/user_extension.py`: `UserExtension`.
- `migrations/versions/0009_user_extensions.py`.
- `src/services/user_extension_service.py`: validation helpers, `StoredExtension`, `TurnExtensions`, `UserExtensionService`, errors.
- `src/services/extension_probe.py`: `ProbeResult`, `ExtensionProbe`.
- `src/routes/user_extensions.py`: the routes.
- `tests/test_secret_box.py`, `tests/test_user_extension_service.py`, `tests/test_extension_probe.py`, `tests/test_user_extensions.py`, `tests/test_user_extension_turn.py`.

Modify: `pyproject.toml`, `src/models/__init__.py`, `src/app.py`, `src/deps.py`, `src/services/agent_gateway.py`, `src/services/turns.py`, `src/routes/chats.py`, `tests/conftest.py` (`FakeAgent`), `tests/test_agent_gateway.py`, `tests/test_migrations.py`, `README.md`, and the spec.

---

### Task 0: Fold what the investigation found back into the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-08-private-extensions-design.md`

- [ ] **Step 1: Edit the spec's `ember_api` section**

1. In "Turn path", replace the bullet starting "A turn that has private extensions is approval-capable" with: "Approvals already work for any turn: `TurnRegistry.decide` and the `approvals` route only need a pending `approval_request` event, not `ask_before_tools`. Nothing changes there."
2. In "Turn path", replace the bullet about `private_extension_errors` with: "`ai_agent`'s result may carry `private_extension_errors: [{id, label, error}]`. `TurnRegistry` publishes them as a live `notice` turn event `{type: "notice", notices: [...]}` just before the turn finishes; they are not saved in the chat. A private extension whose headers cannot be decrypted is left out of the turn and reported the same way, in a `notice` event at the start."
3. In "Secret key", replace the last bullet (config-issues) with: "When the key had to be generated, one warning line (without the key) is logged saying where it was written and that it must be kept with backups of `.env`."
4. In "Service", add: "`update` clears the saved headers when the URL's host changes and the request sends no `headers`, so a saved token is never silently sent to another host. `TurnOptions.private_extensions` is excluded from `repr`."
5. In "Routes", under `GET /api/user-extensions`, replace "missing or expired entries are probed concurrently (at most 5 at once, 5 seconds each)" with "missing or expired entries of enabled extensions are probed concurrently (at most 5 at once); a disabled extension is not probed and reports `unknown`".

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-10-08-private-extensions-design.md docs/superpowers/plans/2026-10-08-private-extensions-part2-ember-api.md
git commit -m "docs: private extensions spec refinements; part 2 plan"
```

---

### Task 1: Secret box and the secrets key

**Files:**
- Create: `apps/ember_api/src/services/secret_box.py`
- Modify: `apps/ember_api/pyproject.toml` (dependencies), `apps/ember_api/src/app.py`, `apps/ember_api/src/deps.py`
- Test: `apps/ember_api/tests/test_secret_box.py`

**Interfaces:**
- Produces: `KEY_NAME = "EMBER_SECRETS_KEY"`; `SecretBoxError(Exception)`; `ensure_secrets_key(env_path: Path) -> str`; `SecretBox(key: str)` with `encrypt_map(values: dict[str, str]) -> str` and `decrypt_map(token: str) -> dict[str, str]` (raises `SecretBoxError`); `deps.get_secret_box(request) -> SecretBox`; `app.state.secret_box`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_api/tests/test_secret_box.py`:

```python
"""secret_box.py: the key in .env and the encryption of header maps."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.services.secret_box import KEY_NAME, SecretBox, SecretBoxError, ensure_secrets_key
from src.utils.config_loader import load_env_secrets
from tests.conftest import make_settings


def key() -> str:
    return Fernet.generate_key().decode("ascii")


def test_round_trip_and_the_token_hides_the_values():
    box = SecretBox(key())

    token = box.encrypt_map({"X-Api-Key": "s3cret-value", "Authorization": "Bearer t0ken"})

    assert "s3cret-value" not in token and "t0ken" not in token
    assert box.decrypt_map(token) == {"X-Api-Key": "s3cret-value", "Authorization": "Bearer t0ken"}


def test_a_token_made_with_another_key_cannot_be_read():
    token = SecretBox(key()).encrypt_map({"A": "b"})

    with pytest.raises(SecretBoxError):
        SecretBox(key()).decrypt_map(token)


def test_garbage_cannot_be_read():
    with pytest.raises(SecretBoxError):
        SecretBox(key()).decrypt_map("not a token")


def test_an_invalid_key_is_refused_with_a_clear_message():
    with pytest.raises(SecretBoxError, match=KEY_NAME):
        SecretBox("short")


def test_a_missing_key_is_generated_once_and_appended(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("INTERNAL_API_TOKEN=abc", encoding="utf-8")  # no trailing newline

    first = ensure_secrets_key(env)
    second = ensure_secrets_key(env)

    assert first == second
    text = env.read_text(encoding="utf-8")
    assert text.startswith("INTERNAL_API_TOKEN=abc\n")
    assert text.count(KEY_NAME) == 1
    assert load_env_secrets(env)[KEY_NAME] == first
    SecretBox(first)  # a usable key


def test_an_existing_key_is_kept(tmp_path: Path):
    env = tmp_path / ".env"
    mine = key()
    env.write_text(f"{KEY_NAME}={mine}\nOTHER=1\n", encoding="utf-8")

    assert ensure_secrets_key(env) == mine
    assert env.read_text(encoding="utf-8") == f"{KEY_NAME}={mine}\nOTHER=1\n"


def test_an_empty_key_line_is_filled_in_place(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(f"A=1\n{KEY_NAME}=\nB=2\n", encoding="utf-8")

    generated = ensure_secrets_key(env)

    text = env.read_text(encoding="utf-8")
    assert text == f"A=1\n{KEY_NAME}={generated}\nB=2\n"


def test_starting_the_app_creates_the_key_and_a_box(tmp_path: Path, client: TestClient):
    env = tmp_path / ".env"

    assert KEY_NAME in load_env_secrets(env)
    assert isinstance(client.app.state.secret_box, SecretBox)


def test_an_invalid_key_in_env_stops_startup(tmp_path: Path):
    from src.app import create_app

    settings = make_settings(tmp_path)
    settings.env_path.write_text(
        settings.env_path.read_text(encoding="utf-8") + f"{KEY_NAME}=not-a-key\n", encoding="utf-8"
    )

    with pytest.raises(SecretBoxError):
        with TestClient(create_app(settings)):
            pass
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_secret_box.py -q`
Expected: FAIL (module `src.services.secret_box` not found).

- [ ] **Step 3: Add the dependency and write `secret_box.py`**

In `apps/ember_api/pyproject.toml`, in the `dependencies` list after the `alembic` line add:

```toml
    # Encrypts the header values of users' private extensions at rest.
    "cryptography>=42",
```

Create `apps/ember_api/src/services/secret_box.py`:

```python
"""Encrypting the header values of private extensions at rest.

Header values are secrets (a token the user's own MCP server wants). They are
stored as one Fernet token per extension, made with the key in ``.env``
(`EMBER_SECRETS_KEY`). The key is generated on first start. If it is later
lost or replaced, the stored headers cannot be read; the extensions that need
them report an error until their headers are entered again. The key is never
printed or logged.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from src.utils.config_loader import load_env_secrets

KEY_NAME = "EMBER_SECRETS_KEY"

logger = logging.getLogger(__name__)


class SecretBoxError(Exception):
    """A key that is not valid, or a token that cannot be read. The message is safe to show."""


def ensure_secrets_key(env_path: Path) -> str:
    """The key in `env_path`; generated and written there first if it is missing or empty."""
    existing = load_env_secrets(env_path).get(KEY_NAME, "").strip()
    if existing:
        return existing
    key = Fernet.generate_key().decode("ascii")
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    empty_line = re.compile(rf"(?m)^{KEY_NAME}=\s*$")
    if empty_line.search(text):
        text = empty_line.sub(f"{KEY_NAME}={key}", text, count=1)
    else:
        text = f"{text}{'' if not text or text.endswith(chr(10)) else chr(10)}{KEY_NAME}={key}{chr(10)}"
    env_path.write_text(text, encoding="utf-8")
    logger.warning(
        "Generated %s and wrote it to %s. Keep it with any backup of that file: without it the saved "
        "headers of private extensions cannot be read.",
        KEY_NAME,
        env_path.name,
    )
    return key


class SecretBox:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError, UnicodeEncodeError) as error:
            raise SecretBoxError(
                f"{KEY_NAME} in .env is not a valid key. Remove the line to have a new one made "
                "(saved headers of private extensions will then need to be entered again)."
            ) from None

    def encrypt_map(self, values: dict[str, str]) -> str:
        payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt_map(self, token: str) -> dict[str, str]:
        try:
            loaded = json.loads(self._fernet.decrypt(token.encode("ascii")))
        except (InvalidToken, ValueError, UnicodeError):
            raise SecretBoxError("The stored headers can't be read") from None
        if not isinstance(loaded, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in loaded.items()):
            raise SecretBoxError("The stored headers can't be read")
        return loaded
```

- [ ] **Step 4: Wire it into the app**

In `apps/ember_api/src/app.py` add the import `from src.services.secret_box import SecretBox, ensure_secrets_key` with the other service imports, and in `lifespan`, directly after the line `internal_token = load_env_secrets(settings.env_path).get("INTERNAL_API_TOKEN")` add:

```python
        # Raises SecretBoxError (a clear one-line message) when .env holds a key that is not valid.
        secret_box = SecretBox(ensure_secrets_key(settings.env_path))
```

and, next to `app.state.internal_token = ...`, add `app.state.secret_box = secret_box`.

In `apps/ember_api/src/deps.py` add (after `get_turns`):

```python
def get_secret_box(request: Request) -> SecretBox:
    return request.app.state.secret_box
```

with `from src.services.secret_box import SecretBox` among the imports.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_secret_box.py tests/test_auth.py -q`
Expected: PASS. If the dependency is missing, install it in the project's environment (`pip install "cryptography>=42"`).

- [ ] **Step 6: Commit**

```bash
git add apps/ember_api/pyproject.toml apps/ember_api/src apps/ember_api/tests/test_secret_box.py
git commit -m "feat(ember_api): secrets key and SecretBox for private extension headers"
```

---

### Task 2: Model and migration

**Files:**
- Create: `apps/ember_api/src/models/user_extension.py`
- Create: `apps/ember_api/migrations/versions/0009_user_extensions.py`
- Modify: `apps/ember_api/src/models/__init__.py`
- Test: `apps/ember_api/tests/test_migrations.py`

**Interfaces:**
- Produces: ORM class `UserExtension(id, account_id, slug, label, description, url, headers_encrypted, enabled, created_at, updated_at)` exported from `src.models`.

- [ ] **Step 1: Update the migration tests**

In `apps/ember_api/tests/test_migrations.py`:
- `HEAD = "0008"` becomes `HEAD = "0009"`; `NEXT = "0009"` becomes `NEXT = "0010"`.
- Both occurrences of the line `conn.execute("DROP TABLE account_capabilities")  # likewise` (replace all) become:

```python
            conn.execute("DROP TABLE account_capabilities")  # likewise
            conn.execute("DROP TABLE user_extensions")  # likewise
```

- In the `ignore_patterns(... "0007*", "0008*")` call add `"0009*"`.
- In the `scripts_with_a_new_migration` fixture change `"0009_add_nickname.py"` to `"0010_add_nickname.py"`, `'revision = "0009"\n'` to `'revision = "0010"\n'`, and `'down_revision = "0008"\n'` to `'down_revision = "0009"\n'`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_migrations.py -q`
Expected: FAIL (the database is at `0008`; no table `user_extensions`).

- [ ] **Step 3: Write the model**

Create `apps/ember_api/src/models/user_extension.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base, utcnow


class UserExtension(Base):
    """An MCP server one account added for itself. Only that account sees it,
    and only its chats use it. Deleted with the account.

    `slug` names the extension in tool names (`u_<slug>__<tool>`). The header
    values (a token the server wants) are in `headers_encrypted`: one Fernet
    token of a JSON object, or None when there are none (see secret_box.py)."""

    __tablename__ = "user_extensions"
    __table_args__ = (UniqueConstraint("account_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[str] = mapped_column(String(1000))
    headers_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
```

In `apps/ember_api/src/models/__init__.py` add `from src.models.user_extension import UserExtension` after the `shared_chat`/`traffic_bucket` imports (keep imports sorted by module name) and `"UserExtension",` in `__all__` after `"UsageRecord",`.

- [ ] **Step 4: Write the migration**

Create `apps/ember_api/migrations/versions/0009_user_extensions.py`:

```python
"""Private extensions: MCP servers an account added for itself (user_extensions).

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_extensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("headers_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "slug"),
    )
    op.create_index("ix_user_extensions_account_id", "user_extensions", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_user_extensions_account_id", table_name="user_extensions")
    op.drop_table("user_extensions")
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_migrations.py -q`
Expected: PASS (including `test_the_migrations_match_the_models_exactly`).

- [ ] **Step 6: Commit**

```bash
git add apps/ember_api/src/models apps/ember_api/migrations apps/ember_api/tests/test_migrations.py
git commit -m "feat(ember_api): user_extensions table (migration 0009)"
```

---

### Task 3: The service

**Files:**
- Create: `apps/ember_api/src/services/user_extension_service.py`
- Test: `apps/ember_api/tests/test_user_extension_service.py`

**Interfaces:**
- Consumes: `UserExtension` (Task 2), `SecretBox`, `SecretBoxError` (Task 1).
- Produces: constants `MAX_EXTENSIONS = 20`; errors `InvalidExtension(ValueError)`, `ExtensionNotFound`, `ExtensionLimit`; `StoredExtension(row, headers)` with `.header_names` (sorted list) and `.readable`; `TurnExtensions(items, skipped)`; `UserExtensionService(session, account_id, box)` with `list()`, `get(slug)`, `create(*, label, url, description="", headers=None)`, `update(slug, *, label=None, description=None, url=None, headers=None, enabled=None)`, `delete(slug)`, `enabled_for_turn()`; helpers `slugify(label)`, `clean_url(url)`, `clean_headers(headers)`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_api/tests/test_user_extension_service.py`:

```python
"""user_extension_service.py: validation, slugs, encryption and what a turn gets."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from src.db import Database
from src.models import Account
from src.services import user_extension_service as svc
from src.services.secret_box import SecretBox
from src.services.user_extension_service import (
    ExtensionLimit,
    ExtensionNotFound,
    InvalidExtension,
    UserExtensionService,
    clean_headers,
    clean_url,
    slugify,
)

URL = "https://notes.example.com/mcp"


def new_box() -> SecretBox:
    return SecretBox(Fernet.generate_key().decode("ascii"))


class Env:
    """A real SQLite database with two accounts, and a service per account."""

    def __init__(self, tmp_path: Path, box: SecretBox | None = None):
        self.path = tmp_path / "ext.db"
        self.database = Database(f"sqlite+aiosqlite:///{self.path.as_posix()}")
        self.box = box or new_box()

    async def setup(self) -> None:
        await self.database.create_tables()
        async with self.database.sessions() as session:
            for name in ("alice", "bob"):
                session.add(Account(username=name, email=f"{name}@example.com", password_hash="x"))
            await session.commit()

    def service(self, session, account_id: int = 1) -> UserExtensionService:
        return UserExtensionService(session, account_id, self.box)


def run(tmp_path: Path, scenario, box: SecretBox | None = None):
    env = Env(tmp_path, box)

    async def go():
        await env.setup()
        try:
            async with env.database.sessions() as session:
                return await scenario(env, session)
        finally:
            await env.database.dispose()

    return asyncio.run(go())


def test_slugify():
    assert slugify("My Notes!") == "my_notes"
    assert slugify("  Wiki -- Team  ") == "wiki_team"
    assert slugify("a__b") == "a_b"
    assert slugify("???") == "extension"
    assert len(slugify("x" * 100)) == 40
    assert "__" not in slugify("a  _  b")


@pytest.mark.parametrize("url", ["", "ftp://x.com/m", "notes.example.com", "https:///m", "https://u:p@x.com/m", "https://x.com/" + "a" * 1000])
def test_bad_urls_are_refused(url):
    with pytest.raises(InvalidExtension):
        clean_url(url)


def test_a_good_url_is_trimmed():
    assert clean_url(f"  {URL}  ") == URL


@pytest.mark.parametrize(
    "headers",
    [{"Host": "x"}, {"Cookie": "a=b"}, {"bad name": "v"}, {"X": ""}, {"X": "a\nb"}, {"X": "a" * 2001}, {f"H{i}": "v" for i in range(21)}],
)
def test_bad_headers_are_refused(headers):
    with pytest.raises(InvalidExtension):
        clean_headers(headers)


def test_no_headers_is_an_empty_map():
    assert clean_headers(None) == {}


def test_create_stores_the_headers_encrypted(tmp_path):
    async def scenario(env, session):
        stored = await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "s3cret-value"})
        return stored.row.slug, stored.headers, stored.header_names

    assert run(tmp_path, scenario) == ("notes", {"X-Key": "s3cret-value"}, ["X-Key"])
    with sqlite3.connect(tmp_path / "ext.db") as conn:
        (token,) = conn.execute("SELECT headers_encrypted FROM user_extensions").fetchone()
    assert token and "s3cret-value" not in token


def test_no_headers_is_stored_as_null(tmp_path):
    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL)

    run(tmp_path, scenario)
    with sqlite3.connect(tmp_path / "ext.db") as conn:
        assert conn.execute("SELECT headers_encrypted FROM user_extensions").fetchone() == (None,)


def test_slugs_stay_unique_per_account(tmp_path):
    async def scenario(env, session):
        first = await env.service(session).create(label="Notes", url=URL)
        second = await env.service(session).create(label="Notes", url=URL)
        other = await env.service(session, 2).create(label="Notes", url=URL)
        return first.row.slug, second.row.slug, other.row.slug

    assert run(tmp_path, scenario) == ("notes", "notes_2", "notes")


def test_the_limit_is_per_account(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "MAX_EXTENSIONS", 2)

    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="One", url=URL)
        await service.create(label="Two", url=URL)
        with pytest.raises(ExtensionLimit):
            await service.create(label="Three", url=URL)
        await env.service(session, 2).create(label="Three", url=URL)

    run(tmp_path, scenario)


def test_label_rules(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        with pytest.raises(InvalidExtension):
            await service.create(label="   ", url=URL)
        with pytest.raises(InvalidExtension):
            await service.create(label="x" * 61, url=URL)
        with pytest.raises(InvalidExtension):
            await service.create(label="Notes", url=URL, description="d" * 301)
        stored = await service.create(label="  My   notes ", url=URL)
        return stored.row.label

    assert run(tmp_path, scenario) == "My notes"


def test_an_account_only_sees_its_own(tmp_path):
    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL)
        assert [s.row.slug for s in await env.service(session, 2).list()] == []
        for action in (
            lambda: env.service(session, 2).get("notes"),
            lambda: env.service(session, 2).update("notes", enabled=False),
            lambda: env.service(session, 2).delete("notes"),
        ):
            with pytest.raises(ExtensionNotFound):
                await action()
        return len(await env.service(session).list())

    assert run(tmp_path, scenario) == 1


def test_update_changes_fields_and_replaces_headers_only_when_sent(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL, headers={"X-Key": "one"})
        a = await service.update("notes", label="My notes", description="d", enabled=False)
        b = await service.update("notes", headers={"Authorization": "Bearer two"})
        c = await service.update("notes", headers={})
        return (a.row.label, a.row.description, a.row.enabled, a.headers), b.headers, c.headers

    first, second, third = run(tmp_path, scenario)
    assert first == ("My notes", "d", False, {"X-Key": "one"})
    assert second == {"Authorization": "Bearer two"}
    assert third == {}


def test_a_new_host_without_new_headers_clears_the_saved_ones(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL, headers={"X-Key": "one"})
        same = await service.update("notes", url="https://notes.example.com/other")
        moved = await service.update("notes", url="https://evil.example.org/mcp")
        again = await service.update("notes", url="https://elsewhere.example.net/mcp", headers={"X-Key": "two"})
        return same.headers, moved.headers, again.headers

    assert run(tmp_path, scenario) == ({"X-Key": "one"}, {}, {"X-Key": "two"})


def test_delete_removes_it(tmp_path):
    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL)
        await service.delete("notes")
        return await service.list()

    assert run(tmp_path, scenario) == []


def test_headers_that_cannot_be_decrypted_are_reported_not_fatal(tmp_path):
    first_box = new_box()

    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "one"})
        await env.service(session).create(label="Wiki", url="https://wiki.example.com/mcp")
        # A different key now: the first extension's headers are unreadable.
        other = UserExtensionService(session, 1, new_box())
        listed = await other.list()
        return [(s.row.slug, s.readable, s.header_names) for s in listed]

    assert run(tmp_path, scenario, first_box) == [("notes", False, []), ("wiki", True, [])]


def test_an_unreadable_row_can_be_repaired_by_sending_headers(tmp_path):
    first_box = new_box()

    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "one"})
        other = UserExtensionService(session, 1, new_box())
        repaired = await other.update("notes", headers={"X-Key": "two"})
        return repaired.readable, repaired.headers

    assert run(tmp_path, scenario, first_box) == (True, {"X-Key": "two"})


def test_enabled_for_turn_gives_only_enabled_readable_rows_with_their_headers(tmp_path):
    first_box = new_box()

    async def scenario(env, session):
        service = env.service(session)
        await service.create(label="Notes", url=URL, headers={"X-Key": "one"})
        await service.create(label="Off", url="https://off.example.com/mcp")
        await service.update("off", enabled=False)
        await service.create(label="Plain", url="https://plain.example.com/mcp")
        await env.service(session, 2).create(label="Bobs", url="https://bob.example.com/mcp")
        turn = await service.enabled_for_turn()
        return list(turn.items), list(turn.skipped)

    items, skipped = run(tmp_path, scenario, first_box)
    assert items == [
        {"id": "notes", "label": "Notes", "url": URL, "headers": {"X-Key": "one"}},
        {"id": "plain", "label": "Plain", "url": "https://plain.example.com/mcp", "headers": {}},
    ]
    assert skipped == []


def test_enabled_for_turn_skips_and_reports_an_unreadable_row(tmp_path):
    first_box = new_box()

    async def scenario(env, session):
        await env.service(session).create(label="Notes", url=URL, headers={"X-Key": "one"})
        turn = await UserExtensionService(session, 1, new_box()).enabled_for_turn()
        return list(turn.items), list(turn.skipped)

    items, skipped = run(tmp_path, scenario, first_box)
    assert items == []
    assert skipped == [{"id": "notes", "label": "Notes", "error": svc.UNREADABLE_MESSAGE}]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_user_extension_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write the service**

Create `apps/ember_api/src/services/user_extension_service.py`:

```python
"""Private extensions: the MCP servers an account added for itself.

Every query filters by account. Header values are secrets: they are validated
here, encrypted with the SecretBox before they reach the database, and only
this service decrypts them. `ai_agent` validates again (it is the one that
connects), so the limits below are duplicated there on purpose.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import UserExtension
from src.services.secret_box import SecretBox, SecretBoxError

MAX_EXTENSIONS = 20
MAX_HEADERS = 20
MAX_VALUE = 2000
MAX_URL = 1000
MAX_LABEL = 60
MAX_DESCRIPTION = 300
MAX_SLUG = 40
SLUG_PATTERN = r"^[a-z0-9]+(_[a-z0-9]+)*$"
UNREADABLE_MESSAGE = "Its headers can't be read (the secrets key changed). Edit it to set them again."

_HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,64}")
_FORBIDDEN_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "proxy-authorization", "cookie"}
)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


class InvalidExtension(ValueError):
    """Input that cannot be saved. The message is safe to show the user."""


class ExtensionNotFound(Exception):
    """No such extension for this account."""


class ExtensionLimit(Exception):
    """The account already has MAX_EXTENSIONS extensions."""


def slugify(label: str) -> str:
    slug = _NOT_SLUG.sub("_", label.strip().lower()).strip("_")[:MAX_SLUG].strip("_")
    return slug or "extension"


def clean_label(label: str) -> str:
    cleaned = " ".join(label.split())
    if not cleaned:
        raise InvalidExtension("Enter a name")
    if len(cleaned) > MAX_LABEL:
        raise InvalidExtension(f"The name can be at most {MAX_LABEL} characters")
    return cleaned


def clean_description(description: str) -> str:
    cleaned = description.strip()
    if len(cleaned) > MAX_DESCRIPTION:
        raise InvalidExtension(f"The description can be at most {MAX_DESCRIPTION} characters")
    return cleaned


def clean_url(url: str) -> str:
    cleaned = url.strip()
    parts = urlsplit(cleaned)
    if not cleaned or len(cleaned) > MAX_URL or parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidExtension("Enter an http or https address")
    if parts.username is not None or parts.password is not None:
        raise InvalidExtension("Put credentials in a header, not in the address")
    return cleaned


def clean_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    if len(headers) > MAX_HEADERS:
        raise InvalidExtension(f"At most {MAX_HEADERS} headers are allowed")
    cleaned: dict[str, str] = {}
    for name, value in headers.items():
        if not _HEADER_NAME.fullmatch(name):
            raise InvalidExtension("A header name may only use letters, digits and hyphens (64 at most)")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise InvalidExtension(f"The header {name} can't be set")
        if not 1 <= len(value) <= MAX_VALUE:
            raise InvalidExtension(f"The value of {name} must be 1 to {MAX_VALUE} characters")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise InvalidExtension(f"The value of {name} has a control character")
        cleaned[name] = value
    return cleaned


@dataclass(frozen=True)
class StoredExtension:
    row: UserExtension
    # None: the stored headers could not be decrypted (the key changed).
    headers: dict[str, str] | None

    @property
    def readable(self) -> bool:
        return self.headers is not None

    @property
    def header_names(self) -> list[str]:
        return sorted(self.headers or {})

    def __repr__(self) -> str:  # never show header values
        return f"StoredExtension(slug={self.row.slug!r}, readable={self.readable})"


@dataclass(frozen=True)
class TurnExtensions:
    # What ai_agent gets: {"id", "label", "url", "headers"}.
    items: tuple[dict[str, Any], ...]
    # Enabled extensions left out of the turn: {"id", "label", "error"}.
    skipped: tuple[dict[str, str], ...]


class UserExtensionService:
    def __init__(self, session: AsyncSession, account_id: int, box: SecretBox) -> None:
        self._session = session
        self._account_id = account_id
        self._box = box

    def _stored(self, row: UserExtension) -> StoredExtension:
        if row.headers_encrypted is None:
            return StoredExtension(row, {})
        try:
            return StoredExtension(row, self._box.decrypt_map(row.headers_encrypted))
        except SecretBoxError:
            return StoredExtension(row, None)

    async def _rows(self) -> list[UserExtension]:
        result = await self._session.scalars(
            select(UserExtension)
            .where(UserExtension.account_id == self._account_id)
            .order_by(UserExtension.created_at, UserExtension.id)
        )
        return list(result)

    async def _row(self, slug: str) -> UserExtension:
        row = await self._session.scalar(
            select(UserExtension).where(UserExtension.account_id == self._account_id, UserExtension.slug == slug)
        )
        if row is None:
            raise ExtensionNotFound(slug)
        return row

    async def list(self) -> list[StoredExtension]:
        return [self._stored(row) for row in await self._rows()]

    async def get(self, slug: str) -> StoredExtension:
        return self._stored(await self._row(slug))

    async def create(
        self, *, label: str, url: str, description: str = "", headers: Mapping[str, str] | None = None
    ) -> StoredExtension:
        label = clean_label(label)
        url = clean_url(url)
        description = clean_description(description)
        values = clean_headers(headers)
        rows = await self._rows()
        if len(rows) >= MAX_EXTENSIONS:
            raise ExtensionLimit
        taken = {row.slug for row in rows}
        base = slugify(label)
        slug, number = base, 2
        while slug in taken:
            suffix = f"_{number}"
            slug = f"{base[: MAX_SLUG - len(suffix)].rstrip('_')}{suffix}"
            number += 1
        row = UserExtension(
            account_id=self._account_id,
            slug=slug,
            label=label,
            description=description,
            url=url,
            headers_encrypted=self._box.encrypt_map(values) if values else None,
            enabled=True,
        )
        self._session.add(row)
        await self._session.commit()
        return StoredExtension(row, values)

    async def update(
        self,
        slug: str,
        *,
        label: str | None = None,
        description: str | None = None,
        url: str | None = None,
        headers: Mapping[str, str] | None = None,
        enabled: bool | None = None,
    ) -> StoredExtension:
        """`headers`, when given (even empty), replaces the whole set. A new host
        without new headers clears the saved ones: a token is never silently
        sent to another host."""
        row = await self._row(slug)
        if label is not None:
            row.label = clean_label(label)
        if description is not None:
            row.description = clean_description(description)
        host_changed = False
        if url is not None:
            new_url = clean_url(url)
            host_changed = urlsplit(new_url).hostname != urlsplit(row.url).hostname
            row.url = new_url
        if headers is not None:
            values = clean_headers(headers)
            row.headers_encrypted = self._box.encrypt_map(values) if values else None
        elif host_changed:
            row.headers_encrypted = None
        if enabled is not None:
            row.enabled = enabled
        row.updated_at = utcnow()
        await self._session.commit()
        return self._stored(row)

    async def delete(self, slug: str) -> None:
        await self._session.delete(await self._row(slug))
        await self._session.commit()

    async def enabled_for_turn(self) -> TurnExtensions:
        items: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for row in await self._rows():
            if not row.enabled:
                continue
            stored = self._stored(row)
            if stored.headers is None:
                skipped.append({"id": row.slug, "label": row.label, "error": UNREADABLE_MESSAGE})
            else:
                items.append({"id": row.slug, "label": row.label, "url": row.url, "headers": dict(stored.headers)})
        return TurnExtensions(tuple(items), tuple(skipped))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_user_extension_service.py -q`
Expected: PASS. If `test_slugify` fails on `slugify("x" * 100)`, check that the truncation happens before the final `strip("_")`.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_api/src/services/user_extension_service.py apps/ember_api/tests/test_user_extension_service.py
git commit -m "feat(ember_api): user extension service with encrypted headers"
```

---

### Task 4: Gateway support and the fake agent

**Files:**
- Modify: `apps/ember_api/src/services/agent_gateway.py`
- Modify: `apps/ember_api/tests/conftest.py` (`FakeAgent`)
- Modify: `apps/ember_api/tests/test_agent_gateway.py`

**Interfaces:**
- Produces: `AgentGateway.ask(..., private_extensions: list[dict[str, Any]] | None = None)`; `AgentGateway.probe_extension(url, caller, *, extension_url: str, headers: dict[str, str] | None) -> dict` returning `{status, error, tools}`; on `FakeAgent`: `asks[-1]["private_extensions"]`, `probes: list[dict]`, `probe_results: dict[str, dict]`, `probe_fail: str | None`, and a tool whose name starts with `u_` asks for approval even when `approval_mode` is `"off"`.

- [ ] **Step 1: Write the failing gateway tests**

In `apps/ember_api/tests/test_agent_gateway.py`:

a) Change `_build_agent` to `def _build_agent(approvals: bool = True, private: bool | None = None) -> FastMCP:` and add as its first statements after the docstring `private = approvals if private is None else private`. Add `private_extensions: list[dict] | None = None,` to the fake `ask` signature (after `disabled_tools`), add `"private": private_extensions,` to the dict `ask` returns, change `status` to:

```python
    @mcp.tool()
    def status() -> dict[str, Any]:
        flags = {"tool_approval": True, "tool_filter": True} if approvals else {}
        return {"available": True, **flags, **({"private_extensions": True} if private else {})}
```

and add the tool:

```python
    @mcp.tool()
    def probe_extension(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        if url.endswith("/down"):
            return {"status": "error", "error": "Timed out", "tools": []}
        return {"status": "connected", "error": None, "tools": ["add", "search"], "seen": [url, headers]}
```

b) Append these tests at the end of the file:

```python
# --- private extensions ---------------------------------------------------------------------


RAW_PRIVATE = [{"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}]


def test_ask_sends_private_extensions(agent_url: str) -> None:
    result = _ask(McpAgentGateway(None), agent_url, private_extensions=RAW_PRIVATE)

    assert result["private"] == RAW_PRIVATE


def test_ask_leaves_the_argument_out_when_there_are_none(agent_url: str) -> None:
    assert _ask(McpAgentGateway(None), agent_url)["private"] is None
    assert _ask(McpAgentGateway(None), agent_url, private_extensions=[])["private"] is None


def test_private_extensions_refuse_an_agent_that_would_ignore_them(old_agent_url: str) -> None:
    gateway = McpAgentGateway(None)
    before = _asks_made(gateway, old_agent_url)

    with pytest.raises(AgentCallError, match="cannot use your private extensions"):
        _ask(gateway, old_agent_url, private_extensions=RAW_PRIVATE)

    assert _asks_made(gateway, old_agent_url) == before  # ask() never ran


def test_probe_extension_returns_status_error_and_tools(agent_url: str) -> None:
    gateway = McpAgentGateway(None)

    ok = asyncio.run(gateway.probe_extension(agent_url, CALLER, extension_url="https://x.example.com/mcp", headers={"A": "b"}))
    down = asyncio.run(gateway.probe_extension(agent_url, CALLER, extension_url="https://x.example.com/down", headers=None))

    assert ok == {"status": "connected", "error": None, "tools": ["add", "search"]}
    assert down == {"status": "error", "error": "Timed out", "tools": []}


def test_probe_extension_of_an_unreachable_agent_raises_agent_call_error() -> None:
    gateway = McpAgentGateway(None)

    with pytest.raises(AgentCallError, match="Could not reach the agent"):
        asyncio.run(
            gateway.probe_extension(f"http://127.0.0.1:{_free_port()}/mcp", CALLER, extension_url="https://x.example.com/mcp", headers=None)
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_agent_gateway.py -q`
Expected: FAIL (`ask() got an unexpected keyword argument 'private_extensions'`, no `probe_extension`).

- [ ] **Step 3: Change the gateway**

In `apps/ember_api/src/services/agent_gateway.py`:

- In the `AgentGateway` Protocol, add `private_extensions: list[dict[str, Any]] | None = None,` after `disabled_tools` in `ask`, and add:

```python
    async def probe_extension(
        self, url: str, caller: Caller, *, extension_url: str, headers: dict[str, str] | None
    ) -> dict[str, Any]: ...
```

- In `McpAgentGateway.ask` add the parameter `private_extensions=None,` after `disabled_tools=None,` and, directly before `return await self._call(url, caller, "ask", arguments, on_event)`:

```python
        if private_extensions:
            # Fail closed, like approvals: an ai_agent that predates this would ignore the
            # argument and the user's private tools would silently be missing (or, worse, a
            # laya agent that cannot use them).
            status = await self._call(url, caller, "status", {})
            if not status.get("private_extensions"):
                raise AgentCallError(
                    "This agent cannot use your private extensions (it needs updating and restarting, or it "
                    "does not support them). Turn them off in the Supermarket or restart the agent."
                )
            arguments["private_extensions"] = private_extensions
```

- Add after `decide`:

```python
    async def probe_extension(self, url, caller, *, extension_url, headers):
        """Asks the agent to connect once to a user's MCP server and say what it offers.
        The agent never raises for a bad server: its answer carries the error."""
        result = await self._call(url, caller, "probe_extension", {"url": extension_url, "headers": headers or None})
        tools = result.get("tools")
        return {
            "status": str(result.get("status") or "error"),
            "error": result.get("error") if isinstance(result.get("error"), str) else None,
            "tools": [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else [],
        }
```

- [ ] **Step 4: Teach `FakeAgent`**

In `apps/ember_api/tests/conftest.py`, in `FakeAgent`:

- Add fields after `ran`: 

```python
    # Private extensions: what probe_extension() was asked, what it answers per URL
    # (default: connected with two tools), and a forced failure.
    probes: list = field(default_factory=list)
    probe_results: dict = field(default_factory=dict)
    probe_fail: str | None = None
```

- Add `private_extensions=None,` to `ask`'s parameters (after `disabled_tools=None`) and `"private_extensions": private_extensions,` to the dict appended to `self.asks`.
- In `_run_tool` change the condition `if approval_mode == "ask" and tool not in allowed_tools:` to:

```python
        # Like the real agent: a private tool (u_...) asks even when approvals are off.
        if (approval_mode == "ask" or tool.startswith("u_")) and tool not in allowed_tools:
```

- Add after `decide`:

```python
    async def probe_extension(self, url, caller, *, extension_url, headers):
        self.probes.append({"url": url, "caller": caller, "extension_url": extension_url, "headers": headers})
        if self.probe_fail:
            raise AgentCallError(self.probe_fail)
        return self.probe_results.get(
            extension_url, {"status": "connected", "error": None, "tools": ["add", "search"]}
        )
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_agent_gateway.py tests/test_turns.py tests/test_approvals.py tests/test_forced_approval.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ember_api/src/services/agent_gateway.py apps/ember_api/tests/conftest.py apps/ember_api/tests/test_agent_gateway.py
git commit -m "feat(ember_api): gateway passes private extensions and probes them"
```

---

### Task 5: The probe cache

**Files:**
- Create: `apps/ember_api/src/services/extension_probe.py`
- Modify: `apps/ember_api/src/app.py`, `apps/ember_api/src/deps.py`
- Test: `apps/ember_api/tests/test_extension_probe.py`

**Interfaces:**
- Consumes: `StoredExtension` (Task 3), `AgentGateway.probe_extension` (Task 4).
- Produces: `ProbeResult(status, error, tools)` (frozen dataclass, `tools` a tuple); `ExtensionProbe(gateway, *, ttl=60.0, concurrency=5, clock=time.monotonic)` with `async check(agent_url: str | None, caller: Caller, account_id: int, stored: StoredExtension) -> ProbeResult` and `forget(account_id: int, slug: str)`; `deps.get_extension_probe(request)`; `app.state.extension_probe`; constants `NO_AGENT`, `UNKNOWN_MESSAGE = "Couldn't check right now"`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_api/tests/test_extension_probe.py`:

```python
"""extension_probe.py: live status of a private extension, cached and bounded."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.services.agent_gateway import AgentCallError, Caller
from src.services.extension_probe import NO_AGENT, UNKNOWN_MESSAGE, ExtensionProbe, ProbeResult
from src.services.user_extension_service import UNREADABLE_MESSAGE, StoredExtension

CALLER = Caller(username="alice", email="alice@example.com")


def stored(slug="notes", url="https://notes.example.com/mcp", headers=None) -> StoredExtension:
    row = SimpleNamespace(slug=slug, url=url)
    return StoredExtension(row, {} if headers is None else headers)  # type: ignore[arg-type]


class Gateway:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []
        self.answer = {"status": "connected", "error": None, "tools": ["add", "search"]}
        self.fail: str | None = None
        self.running = 0
        self.peak = 0

    async def probe_extension(self, url, caller, *, extension_url, headers):
        self.calls.append((extension_url, headers))
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(0.01)
            if self.fail:
                raise AgentCallError(self.fail)
            return self.answer
        finally:
            self.running -= 1


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make(**kwargs):
    gateway, clock = Gateway(), Clock()
    return ExtensionProbe(gateway, clock=clock, **kwargs), gateway, clock


def run(coro):
    return asyncio.run(coro)


def test_a_connected_extension_reports_its_tools():
    probe, gateway, _ = make()

    result = run(probe.check("http://agent", CALLER, 1, stored(headers={"X-Key": "s3cret"})))

    assert result == ProbeResult("connected", None, ("add", "search"))
    assert gateway.calls == [("https://notes.example.com/mcp", {"X-Key": "s3cret"})]


def test_no_headers_are_sent_as_none():
    probe, gateway, _ = make()

    run(probe.check("http://agent", CALLER, 1, stored()))

    assert gateway.calls[0][1] is None


def test_a_result_is_cached_for_the_ttl_then_asked_again():
    probe, gateway, clock = make(ttl=60)

    async def go():
        await probe.check("http://agent", CALLER, 1, stored())
        await probe.check("http://agent", CALLER, 1, stored())
        clock.now += 59
        await probe.check("http://agent", CALLER, 1, stored())
        clock.now += 2
        await probe.check("http://agent", CALLER, 1, stored())

    run(go())
    assert len(gateway.calls) == 2


def test_an_error_result_is_cached_too():
    probe, gateway, _ = make()
    gateway.answer = {"status": "error", "error": "That address is not allowed", "tools": []}

    async def go():
        first = await probe.check("http://agent", CALLER, 1, stored())
        await probe.check("http://agent", CALLER, 1, stored())
        return first

    assert run(go()) == ProbeResult("error", "That address is not allowed", ())
    assert len(gateway.calls) == 1


def test_a_change_of_url_or_headers_is_asked_again_at_once():
    probe, gateway, _ = make()

    async def go():
        await probe.check("http://agent", CALLER, 1, stored(headers={"X-Key": "one"}))
        await probe.check("http://agent", CALLER, 1, stored(headers={"X-Key": "two"}))
        await probe.check("http://agent", CALLER, 1, stored(url="https://other.example.com/mcp", headers={"X-Key": "two"}))

    run(go())
    assert len(gateway.calls) == 3


def test_forget_drops_the_cached_result():
    probe, gateway, _ = make()

    async def go():
        await probe.check("http://agent", CALLER, 1, stored())
        probe.forget(1, "notes")
        await probe.check("http://agent", CALLER, 1, stored())

    run(go())
    assert len(gateway.calls) == 2


def test_accounts_do_not_share_results():
    probe, gateway, _ = make()

    async def go():
        await probe.check("http://agent", CALLER, 1, stored())
        await probe.check("http://agent", CALLER, 2, stored())

    run(go())
    assert len(gateway.calls) == 2


def test_an_agent_that_cannot_be_reached_is_unknown_and_not_cached():
    probe, gateway, _ = make()
    gateway.fail = "Could not reach the agent: refused"

    async def go():
        first = await probe.check("http://agent", CALLER, 1, stored())
        gateway.fail = None
        second = await probe.check("http://agent", CALLER, 1, stored())
        return first, second

    first, second = run(go())
    assert first == ProbeResult("unknown", UNKNOWN_MESSAGE, ())
    assert second.status == "connected"


def test_no_agent_running_is_unknown():
    probe, gateway, _ = make()

    assert run(probe.check(None, CALLER, 1, stored())) == NO_AGENT
    assert gateway.calls == []


def test_unreadable_headers_are_an_error_without_asking_the_agent():
    probe, gateway, _ = make()

    result = run(probe.check("http://agent", CALLER, 1, StoredExtension(SimpleNamespace(slug="n", url="u"), None)))  # type: ignore[arg-type]

    assert result == ProbeResult("error", UNREADABLE_MESSAGE, ())
    assert gateway.calls == []


def test_an_odd_status_from_the_agent_becomes_unknown():
    probe, gateway, _ = make()
    gateway.answer = {"status": "weird", "error": None, "tools": []}

    assert run(probe.check("http://agent", CALLER, 1, stored())).status == "unknown"


def test_at_most_concurrency_probes_run_at_once():
    probe, gateway, _ = make(concurrency=2)

    async def go():
        await asyncio.gather(*(probe.check("http://agent", CALLER, 1, stored(slug=f"e{i}")) for i in range(6)))

    run(go())
    assert gateway.peak == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_extension_probe.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `extension_probe.py`**

Create `apps/ember_api/src/services/extension_probe.py`:

```python
"""The live status of a private extension: connected or not, and its tools.

`ai_agent` makes the connection (it holds the address guard); this asks it
through the gateway and remembers the answer for a minute per account and
extension, keyed by what was asked (url and headers), so an edit is probed at
once. At most `concurrency` probes run at a time. A probe that could not be
asked at all (`unknown`) is not remembered.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from src.services.agent_gateway import AgentCallError, AgentGateway, Caller
from src.services.user_extension_service import UNREADABLE_MESSAGE, StoredExtension

TTL_SECONDS = 60.0
CONCURRENCY = 5
UNKNOWN_MESSAGE = "Couldn't check right now"


@dataclass(frozen=True)
class ProbeResult:
    # "connected", "error" (the agent tried and could not), or "unknown" (not tried).
    status: str
    error: str | None
    tools: tuple[str, ...]


NO_AGENT = ProbeResult("unknown", "No agent is running", ())


def _fingerprint(stored: StoredExtension) -> str:
    payload = json.dumps([stored.row.url, sorted((stored.headers or {}).items())])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExtensionProbe:
    def __init__(
        self,
        gateway: AgentGateway,
        *,
        ttl: float = TTL_SECONDS,
        concurrency: int = CONCURRENCY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._gateway = gateway
        self._ttl = ttl
        self._clock = clock
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cache: dict[tuple[int, str], tuple[str, float, ProbeResult]] = {}

    async def check(
        self, agent_url: str | None, caller: Caller, account_id: int, stored: StoredExtension
    ) -> ProbeResult:
        if not stored.readable:
            return ProbeResult("error", UNREADABLE_MESSAGE, ())
        if agent_url is None:
            return NO_AGENT
        key = (account_id, stored.row.slug)
        fingerprint = _fingerprint(stored)
        cached = self._cache.get(key)
        if cached is not None and cached[0] == fingerprint and cached[1] > self._clock():
            return cached[2]
        try:
            async with self._semaphore:
                answer = await self._gateway.probe_extension(
                    agent_url, caller, extension_url=stored.row.url, headers=stored.headers or None
                )
        except AgentCallError:
            return ProbeResult("unknown", UNKNOWN_MESSAGE, ())
        status = answer.get("status") if answer.get("status") in ("connected", "error") else "unknown"
        result = ProbeResult(status, answer.get("error"), tuple(answer.get("tools") or ()))
        if status != "unknown":
            self._cache[key] = (fingerprint, self._clock() + self._ttl, result)
        return result

    def forget(self, account_id: int, slug: str) -> None:
        self._cache.pop((account_id, slug), None)
```

- [ ] **Step 4: Wire it into the app**

In `apps/ember_api/src/app.py` add `from src.services.extension_probe import ExtensionProbe` with the other service imports and, directly after the line `app.state.agent_gateway = agent_gateway or McpAgentGateway(...)`, add:

```python
        app.state.extension_probe = ExtensionProbe(app.state.agent_gateway)
```

In `apps/ember_api/src/deps.py` add (after `get_secret_box`):

```python
def get_extension_probe(request: Request) -> ExtensionProbe:
    return request.app.state.extension_probe
```

with `from src.services.extension_probe import ExtensionProbe` among the imports.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_extension_probe.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ember_api/src apps/ember_api/tests/test_extension_probe.py
git commit -m "feat(ember_api): cached live probe of private extensions"
```

---

### Task 6: The routes

**Files:**
- Create: `apps/ember_api/src/routes/user_extensions.py`
- Modify: `apps/ember_api/src/app.py` (import list and `include_router`)
- Test: `apps/ember_api/tests/test_user_extensions.py`

**Interfaces:**
- Consumes: `UserExtensionService` and its errors (Task 3), `ExtensionProbe`, `ProbeResult` (Task 5), `get_secret_box`, `get_extension_probe` (Tasks 1, 5), `get_log_writer`, `get_db_session` from `src.deps`, and `get_agent_directory` from `src.routes.mcp`.
- Produces: `GET/POST /api/user-extensions`, `PATCH/DELETE /api/user-extensions/{slug}`. Reply shape: `{id, label, description, url, header_names, enabled, status, error, tools}`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_api/tests/test_user_extensions.py`:

```python
"""/api/user-extensions: an account's own MCP servers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.services import user_extension_service as svc
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

URL = "/api/user-extensions"
EXT_URL = "https://notes.example.com/mcp"


def add(client: TestClient, label: str = "Notes", url: str = EXT_URL, **extra):
    return client.post(URL, json={"label": label, "url": url, **extra})


def test_needs_login(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert add(client).status_code == 401
    assert client.patch(f"{URL}/notes", json={"enabled": False}).status_code == 401
    assert client.delete(f"{URL}/notes").status_code == 401


def test_add_returns_the_extension_with_its_live_status(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.probe_results[EXT_URL] = {"status": "connected", "error": None, "tools": ["search", "add"]}

    created = add(client, headers={"X-Key": "s3cret", "Authorization": "Bearer t0ken"})

    assert created.status_code == 201
    assert created.json() == {
        "id": "notes", "label": "Notes", "description": "", "url": EXT_URL,
        "header_names": ["Authorization", "X-Key"], "enabled": True,
        "status": "connected", "error": None, "tools": ["search", "add"],
    }
    assert agent.probes[-1]["extension_url"] == EXT_URL
    assert agent.probes[-1]["headers"] == {"X-Key": "s3cret", "Authorization": "Bearer t0ken"}


def test_no_reply_ever_contains_a_header_value(client: TestClient) -> None:
    as_admin(client)
    created = add(client, headers={"X-Key": "s3cret-value"})
    listed = client.get(URL)
    patched = client.patch(f"{URL}/notes", json={"label": "Renamed"})

    for response in (created, listed, patched):
        assert "s3cret-value" not in response.text


def test_an_unreachable_extension_is_still_saved(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.probe_results[EXT_URL] = {"status": "error", "error": "That address is not allowed", "tools": []}

    created = add(client)

    assert created.status_code == 201
    assert (created.json()["status"], created.json()["error"]) == ("error", "That address is not allowed")
    assert [e["id"] for e in client.get(URL).json()] == ["notes"]


def test_an_agent_that_cannot_be_asked_leaves_the_status_unknown(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.probe_fail = "Could not reach the agent: refused"

    created = add(client)

    assert created.status_code == 201
    assert (created.json()["status"], created.json()["error"]) == ("unknown", "Couldn't check right now")


def test_slugs_are_made_from_the_label_and_stay_unique(client: TestClient) -> None:
    as_admin(client)

    assert add(client, label="My Notes!").json()["id"] == "my_notes"
    assert add(client, label="My Notes!").json()["id"] == "my_notes_2"


def test_bad_input_is_refused_with_a_message(client: TestClient) -> None:
    as_admin(client)

    for body in (
        {"label": "x", "url": "ftp://x.com/m"},
        {"label": "x", "url": "https://u:p@x.com/m"},
        {"label": "  ", "url": EXT_URL},
        {"label": "x", "url": EXT_URL, "headers": {"Host": "evil"}},
        {"label": "x", "url": EXT_URL, "headers": {"X": ""}},
        {"label": "x", "url": EXT_URL, "headers": {"bad name": "v"}},
    ):
        response = client.post(URL, json=body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], str) and response.json()["detail"]
    assert client.post(URL, json={"url": EXT_URL}).status_code == 422  # a label is required


def test_the_limit_is_a_conflict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "MAX_EXTENSIONS", 1)
    as_admin(client)
    add(client)

    assert add(client, label="Two").status_code == 409


def test_an_account_only_sees_and_changes_its_own(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    add(alice, headers={"X-Key": "s3cret"})

    bob = client_factory()
    login(bob, "bob")

    assert bob.get(URL).json() == []
    assert bob.patch(f"{URL}/notes", json={"enabled": False}).status_code == 404
    assert bob.delete(f"{URL}/notes").status_code == 404
    assert [e["id"] for e in alice.get(URL).json()] == ["notes"]
    assert add(bob).json()["id"] == "notes"  # slugs are per account


def test_patch_changes_fields_and_enabled(client: TestClient) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "s3cret"})

    renamed = client.patch(f"{URL}/notes", json={"label": "My notes", "description": "work"}).json()
    off = client.patch(f"{URL}/notes", json={"enabled": False}).json()

    assert (renamed["label"], renamed["description"], renamed["id"]) == ("My notes", "work", "notes")
    assert off["enabled"] is False
    assert off["header_names"] == ["X-Key"]  # headers untouched


def test_patch_headers_replace_them_and_a_new_host_clears_them(client: TestClient) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "one"})

    replaced = client.patch(f"{URL}/notes", json={"headers": {"Authorization": "Bearer two"}}).json()
    same_host = client.patch(f"{URL}/notes", json={"url": "https://notes.example.com/other"}).json()
    moved = client.patch(f"{URL}/notes", json={"url": "https://elsewhere.example.org/mcp"}).json()

    assert replaced["header_names"] == ["Authorization"]
    assert same_host["header_names"] == ["Authorization"]
    assert moved["header_names"] == []


def test_patch_needs_something_to_change(client: TestClient) -> None:
    as_admin(client)
    add(client)

    assert client.patch(f"{URL}/notes", json={}).status_code == 422
    assert client.patch(f"{URL}/Bad_Slug", json={"enabled": False}).status_code == 422


def test_delete(client: TestClient) -> None:
    as_admin(client)
    add(client)

    assert client.delete(f"{URL}/notes").status_code == 204
    assert client.get(URL).json() == []
    assert client.delete(f"{URL}/notes").status_code == 404


def test_the_status_is_cached_and_an_edit_asks_again(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client)
    asked = len(agent.probes)

    client.get(URL)
    client.get(URL)
    assert len(agent.probes) == asked  # served from the cache

    client.patch(f"{URL}/notes", json={"url": "https://notes.example.com/v2"})
    assert len(agent.probes) == asked + 1


def test_a_disabled_extension_is_not_probed(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client)
    client.patch(f"{URL}/notes", json={"enabled": False})
    asked = len(agent.probes)

    listed = client.get(URL).json()[0]

    assert len(agent.probes) == asked
    assert (listed["enabled"], listed["status"], listed["tools"]) == (False, "unknown", [])


def test_the_headers_are_encrypted_in_the_database(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "s3cret-value"})

    with sqlite3.connect(tmp_path / "data" / "test.db") as conn:
        (token,) = conn.execute("SELECT headers_encrypted FROM user_extensions").fetchone()

    assert token and "s3cret-value" not in token


def test_unreadable_headers_show_an_error_and_can_be_repaired(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "one"})
    add(client, label="Wiki", url="https://wiki.example.com/mcp")
    with sqlite3.connect(tmp_path / "data" / "test.db") as conn:
        conn.execute("UPDATE user_extensions SET headers_encrypted = 'garbage' WHERE slug = 'notes'")

    broken = next(e for e in client.get(URL).json() if e["id"] == "notes")
    wiki = next(e for e in client.get(URL).json() if e["id"] == "wiki")
    repaired = client.patch(f"{URL}/notes", json={"headers": {"X-Key": "two"}}).json()

    assert (broken["status"], broken["header_names"]) == ("error", [])
    assert "can't be read" in broken["error"]
    assert wiki["status"] == "connected"
    assert (repaired["status"], repaired["header_names"]) == ("connected", ["X-Key"])


def test_changes_are_logged_without_secrets_or_the_query_string(client: TestClient) -> None:
    as_admin(client)
    add(client, url="https://notes.example.com/mcp?token=abc123", headers={"X-Key": "s3cret-value"})
    client.patch(f"{URL}/notes", json={"enabled": False})
    client.patch(f"{URL}/notes", json={"enabled": True})
    client.patch(f"{URL}/notes", json={"label": "Renamed"})
    client.delete(f"{URL}/notes")
    me = client.get("/api/auth/me").json()["id"]

    logged = [e["message"] for e in client.get("/api/logs/action", params={"actor": me}).json()]

    assert logged[:5] == [
        "Removed private extension 'Renamed'",
        "Edited private extension 'Renamed' (notes.example.com)",
        "Enabled private extension 'Notes'",
        "Disabled private extension 'Notes'",
        "Added private extension 'Notes' (notes.example.com)",
    ]
    assert not any("abc123" in m or "s3cret-value" in m for m in logged)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_user_extensions.py -q`
Expected: FAIL (404 on every route).

- [ ] **Step 3: Write the routes**

Create `apps/ember_api/src/routes/user_extensions.py`:

```python
"""/api/user-extensions: the logged-in account's own MCP servers ("private
extensions", chat.use). Private to the account: another account's slug is 404.
The reply carries each one's live status and tools (from ai_agent, cached for a
minute) and the NAMES of its headers; a header value is never sent back."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import (
    get_db_session,
    get_extension_probe,
    get_log_writer,
    get_secret_box,
    require_permission,
)
from src.models import Account
from src.routes.mcp import get_agent_directory
from src.services.agent_directory import AgentDirectory
from src.services.agent_gateway import Caller
from src.services.extension_probe import ExtensionProbe, ProbeResult
from src.services.log_service import LogWriter
from src.services.permissions import CHAT_USE
from src.services.secret_box import SecretBox
from src.services.user_extension_service import (
    MAX_SLUG,
    SLUG_PATTERN,
    ExtensionLimit,
    ExtensionNotFound,
    InvalidExtension,
    StoredExtension,
    UserExtensionService,
)

router = APIRouter(prefix="/api/user-extensions", tags=["user-extensions"])

require_chat = require_permission(CHAT_USE)

NOT_PROBED = ProbeResult("unknown", None, ())


def get_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
    box: SecretBox = Depends(get_secret_box),
) -> UserExtensionService:
    return UserExtensionService(session, account.id, box)


class ExtensionCreate(BaseModel):
    label: str = Field(max_length=200)
    url: str = Field(max_length=2000)
    description: str = Field(default="", max_length=1000)
    headers: dict[str, str] | None = None


class ExtensionUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=1000)
    # When present (even empty) it replaces every header; the browser sends it only if the user retyped them.
    headers: dict[str, str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def something_to_change(self) -> ExtensionUpdate:
        if not self.model_fields_set:
            raise ValueError("send something to change")
        return self


class ExtensionOut(BaseModel):
    id: str
    label: str
    description: str
    url: str
    header_names: list[str]
    enabled: bool
    status: str
    error: str | None
    tools: list[str]

    @classmethod
    def of(cls, stored: StoredExtension, probe: ProbeResult) -> ExtensionOut:
        row = stored.row
        return cls(
            id=row.slug,
            label=row.label,
            description=row.description,
            url=row.url,
            header_names=stored.header_names,
            enabled=row.enabled,
            status=probe.status,
            error=probe.error,
            tools=list(probe.tools),
        )


def _caller(account: Account) -> Caller:
    return Caller(username=account.username, email=account.email)


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


async def _probe(
    stored: StoredExtension, account: Account, probe: ExtensionProbe, directory: AgentDirectory
) -> ProbeResult:
    if not stored.row.enabled:
        return NOT_PROBED
    agent = await directory.entry()
    return await probe.check(agent.url if agent else None, _caller(account), account.id, stored)


@router.get("")
async def list_extensions(
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    directory: AgentDirectory = Depends(get_agent_directory),
) -> list[ExtensionOut]:
    stored = await service.list()
    results = await asyncio.gather(*(_probe(item, account, probe, directory) for item in stored))
    return [ExtensionOut.of(item, result) for item, result in zip(stored, results)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_extension(
    body: ExtensionCreate,
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    directory: AgentDirectory = Depends(get_agent_directory),
    logs: LogWriter = Depends(get_log_writer),
) -> ExtensionOut:
    """Saves the extension (even if it cannot be reached right now) and probes it once."""
    try:
        stored = await service.create(
            label=body.label, url=body.url, description=body.description, headers=body.headers
        )
    except InvalidExtension as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except ExtensionLimit as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have added as many private extensions as allowed") from error
    await logs.action(
        account, "account.user_extension_add", f"Added private extension '{stored.row.label}' ({_host(stored.row.url)})"
    )
    return ExtensionOut.of(stored, await _probe(stored, account, probe, directory))


@router.patch("/{slug}")
async def update_extension(
    body: ExtensionUpdate,
    slug: str = Path(pattern=SLUG_PATTERN, max_length=MAX_SLUG),
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    directory: AgentDirectory = Depends(get_agent_directory),
    logs: LogWriter = Depends(get_log_writer),
) -> ExtensionOut:
    try:
        before = await service.get(slug)
        was_enabled = before.row.enabled
        stored = await service.update(
            slug,
            label=body.label,
            description=body.description,
            url=body.url,
            headers=body.headers,
            enabled=body.enabled,
        )
    except ExtensionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such extension") from error
    except InvalidExtension as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if body.url is not None or body.headers is not None:
        probe.forget(account.id, slug)
    label = stored.row.label
    if body.enabled is not None and body.enabled != was_enabled and not (body.model_fields_set - {"enabled"}):
        message = f"{'Enabled' if body.enabled else 'Disabled'} private extension '{label}'"
    else:
        message = f"Edited private extension '{label}' ({_host(stored.row.url)})"
    await logs.action(account, "account.user_extension_edit", message)
    return ExtensionOut.of(stored, await _probe(stored, account, probe, directory))


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_extension(
    slug: str = Path(pattern=SLUG_PATTERN, max_length=MAX_SLUG),
    account: Account = Depends(require_chat),
    service: UserExtensionService = Depends(get_service),
    probe: ExtensionProbe = Depends(get_extension_probe),
    logs: LogWriter = Depends(get_log_writer),
) -> Response:
    try:
        label = (await service.get(slug)).row.label
        await service.delete(slug)
    except ExtensionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such extension") from error
    probe.forget(account.id, slug)
    await logs.action(account, "account.user_extension_remove", f"Removed private extension '{label}'")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

In `apps/ember_api/src/app.py` add `user_extensions,` to the `from src.routes import (...)` list (alphabetical) and `app.include_router(user_extensions.router)` after `app.include_router(account_capabilities.router)`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_user_extensions.py tests/test_extension_probe.py tests/test_user_extension_service.py -q`
Expected: PASS. If `test_changes_are_logged...` fails on the order of messages, the activity log lists newest first (as in `test_server_info.py`); if the repo's order differs, compare with that test and fix the expected list, not the messages.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_api/src apps/ember_api/tests/test_user_extensions.py
git commit -m "feat(ember_api): /api/user-extensions"
```

---

### Task 7: Turn integration

**Files:**
- Modify: `apps/ember_api/src/services/turns.py` (`TurnOptions`, `_answer`)
- Modify: `apps/ember_api/src/routes/chats.py` (`start_turn`)
- Test: `apps/ember_api/tests/test_user_extension_turn.py`

**Interfaces:**
- Consumes: `UserExtensionService.enabled_for_turn()` and `TurnExtensions` (Task 3), `AgentGateway.ask(private_extensions=...)` (Task 4).
- Produces: `TurnOptions.private_extensions: tuple[dict, ...]` (excluded from `repr`) and `TurnOptions.private_skipped: tuple[dict, ...]`; a `notice` turn event `{type: "notice", notices: [{id, label, error}]}`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_api/tests/test_user_extension_turn.py`:

```python
"""Private extensions on a turn: only the caller's enabled ones go to the agent,
the browser cannot name one, notices reach the watcher, and a private tool asks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from src.services.turns import TurnOptions
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin
from tests.test_turns import chat, events, new_id, start, wait_until

URL = "/api/user-extensions"


def add(client: TestClient, label: str, url: str, **extra):
    response = client.post(URL, json={"label": label, "url": url, **extra})
    assert response.status_code == 201, response.text
    return response


def finished(client: TestClient, chat_id: str) -> list[dict]:
    wait_until(lambda: chat(client, chat_id)["running"] is False)
    return events(client, chat_id)


def test_only_the_callers_enabled_extensions_are_sent(client_factory, email: FakeEmailSender, agent: FakeAgent) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    add(alice, "Notes", "https://notes.example.com/mcp", headers={"X-Key": "s3cret"})
    add(alice, "Off", "https://off.example.com/mcp")
    alice.patch(f"{URL}/off", json={"enabled": False})
    bob = client_factory()
    login(bob, "bob")
    add(bob, "Bobs", "https://bob.example.com/mcp")

    chat_id = new_id()
    assert start(alice, chat_id).status_code == 202
    finished(alice, chat_id)

    assert agent.asks[-1]["private_extensions"] == [
        {"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}
    ]


def test_a_turn_without_private_extensions_sends_none(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id)
    finished(client, chat_id)

    assert not agent.asks[-1]["private_extensions"]


def test_the_browser_cannot_name_an_extension_for_a_turn(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id, private_extensions=[{"id": "evil", "label": "x", "url": "http://10.0.0.5/mcp", "headers": {}}])
    finished(client, chat_id)

    assert not agent.asks[-1]["private_extensions"]


def test_what_the_agent_could_not_connect_to_reaches_the_watcher_as_a_notice(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp")
    notices = [{"id": "notes", "label": "Notes", "error": "Timed out"}]
    agent.result_extra = {"private_extension_errors": notices}
    chat_id = new_id()

    start(client, chat_id)
    stream = finished(client, chat_id)

    assert [e["notices"] for e in stream if e["type"] == "notice"] == [notices]


def test_no_notice_when_everything_connected(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp")
    chat_id = new_id()

    start(client, chat_id)

    assert not [e for e in finished(client, chat_id) if e["type"] == "notice"]


def test_an_extension_whose_headers_cannot_be_read_is_left_out_with_a_notice(
    client: TestClient, agent: FakeAgent, tmp_path: Path
) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp", headers={"X-Key": "one"})
    add(client, "Wiki", "https://wiki.example.com/mcp")
    with sqlite3.connect(tmp_path / "data" / "test.db") as conn:
        conn.execute("UPDATE user_extensions SET headers_encrypted = 'garbage' WHERE slug = 'notes'")
    chat_id = new_id()

    start(client, chat_id)
    stream = finished(client, chat_id)

    assert [e["id"] for e in agent.asks[-1]["private_extensions"]] == ["wiki"]
    notice = next(e for e in stream if e["type"] == "notice")
    assert notice["notices"][0]["id"] == "notes"
    assert "can't be read" in notice["notices"][0]["error"]


def test_a_private_tool_asks_even_when_ask_before_tools_is_off(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp")
    agent.tool_calls = ["u_notes__search"]
    chat_id = new_id()

    start(client, chat_id)  # no ask_before_tools
    wait_until(lambda: agent._waiting)
    assert agent.ran == []

    decided = client.post(f"/api/chats/{chat_id}/approvals", json={"step_id": "step0", "decision": "allow"})
    assert decided.status_code == 200
    finished(client, chat_id)

    assert agent.ran == ["u_notes__search"]


def test_turn_options_never_show_header_values_in_repr() -> None:
    options = TurnOptions(private_extensions=({"id": "notes", "label": "N", "url": "u", "headers": {"X-Key": "s3cret"}},))

    assert "s3cret" not in repr(options)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_user_extension_turn.py -q`
Expected: FAIL (`TurnOptions` has no `private_extensions`; agent never receives them).

- [ ] **Step 3: `TurnOptions` and `_answer`**

In `apps/ember_api/src/services/turns.py`:

- Add `field` to the `dataclasses` import if it is not imported there already (check the top of the file: `from dataclasses import dataclass, field` is likely present because `Turn` uses `field`).
- In `TurnOptions` add after `disabled_tools`:

```python
    # The account's enabled private extensions as ai_agent wants them ({id, label, url, headers});
    # headers are secrets, so this never shows in repr(). Loaded server-side, never from the browser.
    private_extensions: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    # Enabled ones left out because their headers cannot be read: {id, label, error}.
    private_skipped: tuple[dict[str, str], ...] = ()
```

- In `_answer`, directly before `turn.asking = True` add:

```python
        if turn.options.private_skipped:
            await self._publish(turn, {"type": "notice", "notices": [dict(n) for n in turn.options.private_skipped]})
```

- In the `self._gateway.ask(...)` call add after `disabled_tools=...,`:

```python
                private_extensions=list(turn.options.private_extensions) or None,
```

- After the `finally: turn.asking = False` block and the `cancelled = ...` line, before `response = ...`, add:

```python
        errors = result.get("private_extension_errors")
        if isinstance(errors, list) and errors:
            await self._publish(
                turn,
                {
                    "type": "notice",
                    "notices": [
                        {k: str(n.get(k) or "")[:300] for k in ("id", "label", "error")}
                        for n in errors[:20]
                        if isinstance(n, dict)
                    ],
                },
            )
```

- [ ] **Step 4: `start_turn`**

In `apps/ember_api/src/routes/chats.py`:

- Add the imports `from src.deps import get_secret_box` (extend the existing `from src.deps import ...` line), `from src.services.secret_box import SecretBox`, and `from src.services.user_extension_service import UserExtensionService`.
- Add the parameter `box: SecretBox = Depends(get_secret_box),` to `start_turn` (after `app_settings`).
- In `start_turn`, directly before `try:` that builds `options` (after `forced = await app_settings.get_bool(FORCE_TOOL_APPROVAL)`), add:

```python
    # The caller's own private extensions, read here from the database: the browser cannot name one.
    private = await UserExtensionService(session, account.id, box).enabled_for_turn()
```

- Add to the `TurnOptions(...)` call:

```python
            private_extensions=private.items,
            private_skipped=private.skipped,
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_user_extension_turn.py tests/test_turns.py tests/test_approvals.py tests/test_disabled_tools.py tests/test_forced_approval.py -q`
Expected: PASS. If `test_a_private_tool_asks_even_when_ask_before_tools_is_off` times out, check that `agent._waiting` is set (the fake's `u_` rule from Task 4) and that the turn's `approval_request` event reached `pending_approvals`.

- [ ] **Step 6: Commit**

```bash
git add apps/ember_api/src apps/ember_api/tests/test_user_extension_turn.py
git commit -m "feat(ember_api): turns carry the account's private extensions and report notices"
```

---

### Task 8: Docs and the full suite

**Files:**
- Modify: `apps/ember_api/README.md`

- [ ] **Step 1: Document**

In `apps/ember_api/README.md`:
- Add rows to the routes table, after the `/api/account-capabilities` rows: `GET /api/user-extensions`, `POST /api/user-extensions`, `PATCH /api/user-extensions/{id}`, `DELETE /api/user-extensions/{id}`, all `chat.use`, own rows only. Say: the reply shape `{id, label, description, url, header_names, enabled, status, error, tools}`; `status` is `connected`, `error` or `unknown` and comes from `ai_agent`'s `probe_extension`, cached 60 seconds, disabled extensions are not probed; header values are never returned; `POST` saves even an unreachable server; the limits (20 extensions, 20 headers, name and value rules, refused header names, URL rules) with the status codes (`422` for a rule, `409` at the limit, `404` for another account's id); `PATCH` with `headers` replaces them all, and a changed host without new headers clears them; each change is logged as `account.user_extension_add`, `_edit` and `_remove` with the label and the URL's host only.
- Add a "Private extensions" subsection under the configuration notes: `EMBER_SECRETS_KEY` in `.env` (generated on first start, a warning line is logged once, keep it with `.env` backups), what happens if it is lost (affected extensions show an error and are left out of turns until their headers are entered again), that an invalid value stops startup, and the new `cryptography` dependency.
- In the notes about turns: a turn sends the account's enabled private extensions to `ai_agent` as `private_extensions`; an `ai_agent` that does not report `private_extensions` in `status` is refused (the turn fails with a message); `notice` turn events `{type: "notice", notices: [{id, label, error}]}` report extensions that could not be used; private tools always ask for approval (the agent raises the `approval_request`).

- [ ] **Step 2: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS. If an old test fails only because its fake gateway or settings lack something new, fix the test fake and name the file in the commit message.

- [ ] **Step 3: Commit**

```bash
git add apps/ember_api/README.md
git commit -m "docs(ember_api): private extensions"
```

---

## Self-review (done while writing)

- **Spec coverage (ember_api section):** table and migration (Task 2); limits, slug rules and URL/header validation (Task 3); encryption and key bootstrap, clear failure on a bad key, unreadable-key handling (Tasks 1, 3, 6); routes with own-rows-only, 20-limit, header names only (Task 6); probe with 60-second cache, fingerprint, concurrency, unknown not cached, disabled not probed (Tasks 5, 6); gateway argument with fail-closed status check and `probe_extension` (Task 4); turn path loaded server-side so the browser cannot name a URL, skipped-unreadable notice, `private_extension_errors` to a `notice` event, approvals already independent of `ask_before_tools` (Task 7); activity log without secrets or query string (Task 6); README (Task 8). The host-change-clears-headers rule and the `repr=False` rule were added in Task 0.
- **Placeholder scan:** none. The only conditional instructions are "check against the existing log order" and "check the dataclasses import", each with the exact thing to compare.
- **Type consistency:** `StoredExtension` (`row`, `headers`, `readable`, `header_names`) is used the same way in Tasks 3, 5 and 6; `ProbeResult(status, error, tools)` in Tasks 5 and 6; `TurnExtensions(items, skipped)` in Tasks 3 and 7; `private_extensions` items are `{id, label, url, headers}` in Tasks 3, 4 and 7 and match what `ai_agent`'s `PrivateSpec.parse` expects; `UNREADABLE_MESSAGE` is defined once (Task 3) and reused (Tasks 5, 7 via the service); slug rules match `ai_agent`'s `SLUG`.
