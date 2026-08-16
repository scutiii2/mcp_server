# Chat history design

Status: approved (architecture-level), pending spec review
Date: 2026-08-16
Scope: `chat_app` subproject only

## Problem

`chat_app`'s chat page is fully stateless server-side today: the client
holds the entire conversation in a JS array and replays it on every
`/api/chat` call; nothing is written to disk. Client-side, a
`sessionStorage` blob (`chat.session`) lets a reload/navigation within the
same tab resume the in-progress conversation, but it clears the moment the
tab closes and there is no way to have more than one conversation, list
past ones, or return to an earlier one. There is also no "New chat"
control anywhere in the UI.

The user wants: (1) chat history they can browse and return to, and (2)
the browser URL to carry the chat id as a query parameter, so a URL with
no id starts a fresh chat.

## Decisions already made (see brainstorming transcript)

- URL scheme: query parameter — `/chat?id=<chat_id>`. No `id` → new chat.
- History list lives in a new panel in the left sidebar, chat-page only.
- v1 includes rename and delete, in addition to list/switch/new.

## Scope cut made while writing this spec

The original in-chat design sketch included per-chat `provider_id`,
`model_id`, and `enabled_extensions` columns, so resuming a chat would
restore the settings it was created with. Writing this out revealed that
provider/model/extension selection is currently **global** UI state (the
provider/model `<select>`s just keep whatever was last picked; extensions
are a `localStorage`-backed toggle set shared across the whole page) —
making them per-chat would mean either fighting that existing global
state or introducing a second, conflicting notion of "current settings."
Since nothing in the request asked for per-chat settings memory, this
spec drops those three columns: **a chat stores only its message
transcript.** Provider/model/extensions stay exactly as global as they
are today, unaffected by which chat is open. Flagging this explicitly in
case per-chat settings memory turns out to matter later — it's a
reasonable follow-up, not part of this change.

## Data model

New package `chat_app/src/chat_app/chats/`, `store.py` mirrors
`auth/store.py`'s conventions exactly: plain `sqlite3`, no ORM, a
`_connect(db_path)` helper that creates the table if missing and returns
a connection, one open/close per public call.

```sql
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    title TEXT NOT NULL,
    messages TEXT NOT NULL,      -- JSON array of {"role": ..., "content": ...}
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
CREATE INDEX IF NOT EXISTS idx_chats_username_updated
    ON chats(username, updated_at DESC)
```

`id` is generated with `secrets.token_urlsafe(12)`, the same convention
`create_invite_code`'s `code_id` already uses. `messages` is one JSON
blob per chat, not a normalized per-message table — the app already
treats a conversation as "read/write the whole thing at once" (the
client replays the full history every request), so a blob matches the
real access pattern and keeps the store thin, same reasoning as the
original design discussion.

`username TEXT NOT NULL` (not a foreign key — `auth/store.py`'s own
`users` table isn't referenced by FK elsewhere in this codebase either)
scopes every row to its owner. Every store function takes `username` and
filters `WHERE id = ? AND username = ?` — a chat id belonging to another
user is indistinguishable from a nonexistent one, so nothing here can be
used to enumerate or read someone else's chats by guessing an id.

### Exceptions

```python
class UnknownChat(Exception):
    """Raised when chat_id doesn't exist, or doesn't belong to this user
    - the two cases are deliberately indistinguishable from the caller's
    side (see ownership note above)."""
```

### Functions (`chats/store.py`)

```python
def save_chat(
    db_path: Path,
    username: str,
    chat_id: str | None,
    messages: list[dict],
) -> str:
    """Create (chat_id is None) or overwrite (chat_id given) a chat's
    full transcript. Returns the chat id either way.

    Creating: generates an id, derives a title from the first message
    with role "user": stripped, and if longer than 60 characters, cut to
    57 characters plus "..."; "New chat" if no user-role message is
    found at all (shouldn't happen in practice - a chat is only ever
    created alongside a real question - but the store must not crash if
    it does). Inserts the row.

    Updating: UPDATE ... WHERE id = ? AND username = ?, bumping
    updated_at. Raises UnknownChat if that WHERE matches zero rows -
    covers both "no such chat" and "not yours".
    """


def list_chats(db_path: Path, username: str) -> list[dict]:
    """id, title, updated_at only (no messages) - this feeds the sidebar
    list, which must stay cheap regardless of how long individual chats
    get. Ordered newest-updated-first."""


def get_chat(db_path: Path, username: str, chat_id: str) -> dict | None:
    """Full record (id, title, messages, created_at, updated_at).
    None (not an exception) when missing/not-owned - the route layer
    turns that into a 404, this layer doesn't need a raise/catch for
    what's a normal, expected outcome of a GET."""


def rename_chat(db_path: Path, username: str, chat_id: str, title: str) -> None:
    """Raises ValueError if title is blank after stripping, UnknownChat
    if the id doesn't exist / isn't owned."""


def delete_chat(db_path: Path, username: str, chat_id: str) -> None:
    """Raises UnknownChat if the id doesn't exist / isn't owned."""
```

## Config

`chat_app/src/chat_app/config.py`'s `Settings` gains one field, directly
mirroring `users_db_path`:

```python
chats_db_path: Path = Path(_env("CHATS_DB_PATH", "data/chats.db"))
```

## Routes (`pages/chat/routes.py`)

`GET /chat` is unchanged — the frontend reads `?id=` from `location.search`
itself; no server-side path/query handling needed for the page route.

New endpoints, all scoped to `service.current_username()`:

- `GET /api/chats` → `list_chats(...)`, `200`.
- `GET /api/chats/<chat_id>` → `get_chat(...)`; `404 {"error": "Chat not found."}` if `None`.
- `PATCH /api/chats/<chat_id>` → body `{"title": "..."}`; `400` on blank title (`ValueError` from the store), `404` on `UnknownChat`, else `204`.
- `DELETE /api/chats/<chat_id>` → `404` on `UnknownChat`, else `204`.

`POST /api/chat` changes:

- The existing empty-question short-circuit (`if not question: return
  jsonify({"response": "Please enter a question."})`) is unchanged and
  returns before any of the persistence logic below runs - there is no
  turn to save.
- Accepts an optional `chat_id` in the request body (`data.get("chat_id")`).
- The three existing response branches (success / `ValueError` /
  generic `Exception`) are unified into one `response_text` before the
  final `jsonify`, so persistence happens exactly once regardless of
  which branch produced the text — an error turn is saved too (so
  reopening a chat shows it), matching what the client already does
  today (`history.push` runs unconditionally on the client, error text
  included).
- After computing `response_text`, builds the full transcript to persist
  as `data.get("history", []) + [{"role": "user", "content": question}, {"role": "assistant", "content": response_text}]`
  and calls `save_chat(settings.chats_db_path, service.current_username(), data.get("chat_id"), transcript)`
  inside its own `try/except Exception` — a persistence failure is
  logged via `errors.report` and otherwise ignored; **it must not
  prevent the chat answer itself from being returned.**
- Response JSON gains `"chat_id"`: the id `save_chat` returned, or (if
  the save itself failed) whatever `chat_id` the client already sent —
  `None` only when this was a brand-new chat AND the save failed, in
  which case the frontend simply doesn't get an id to push into the URL
  this turn and will retry the save implicitly on the next message.

## Frontend (`pages/chat/template/script.js`, `index.html`, shared `sidebar.html`)

**Removed entirely:** the `sessionStorage`-based resume mechanism —
`SESSION_STORAGE_KEY`, `sessionLog`, `loadSessionFromStorage()`,
`saveSessionToStorage()`, and the restore block at the bottom of the
file. Server-side persistence replaces its job; a resumed chat now comes
from `GET /api/chats/<id>`, not a per-tab blob, and correctly survives a
closed tab/browser restart, which `sessionStorage` deliberately never
did.

**New state:** `let currentChatId = new URLSearchParams(location.search).get('id');`

**Init sequence** (replacing today's "restore session, else greet"
block): if `currentChatId` is set, fetch `GET /api/chats/<id>`; on `200`,
replay each `{role, content}` via the existing `appendMsg()` +
`history.push()` path (no greeting); on `404`, treat exactly like "no
id" (see below) rather than showing an error — a stale/foreign link
should degrade to a fresh chat, not break the page. If `currentChatId`
is unset (or was just cleared by a 404), show today's greeting, same as
a first-ever visit.

**`send()`:** POST body gains `chat_id: currentChatId`. On a successful
response, if `data.chat_id` is truthy and differs from `currentChatId`,
set `currentChatId = data.chat_id` and
`history.pushState(null, '', '/chat?id=' + encodeURIComponent(currentChatId))`
(browser History API, unrelated to the removed `history` conversation
array — same name, this codebase's own naming collision, not mine to
fix here), then refresh the sidebar list.

**New "＋ New chat" control:** a plain `<a href="/chat">` — a full
navigation is the simplest way to fully reset client state, consistent
with this being a plain multi-page app with no client router.

**New sidebar history list:** `sidebar.html` gains a block gated on
`current_page == 'chat'` (same pattern as the existing `'invites' in
scopes` gate), holding the "New chat" link and an empty
`#chat-history-list` container that `script.js` populates via
`GET /api/chats` (title + relative time, e.g. "2h ago" — small new
`formatRelativeTime()` helper). The currently-open chat's entry is
visually marked active. Refreshed on init and after create/rename/delete.

**Rename:** a pencil affordance per list entry swaps the title into an
editable field; Enter/blur → `PATCH /api/chats/<id>`, Escape cancels.
**Delete:** a trash affordance → reuses the existing shared
`confirmModal()` (same pattern as `removeExtension()`) → `DELETE
/api/chats/<id>`; if the deleted chat is the one currently open,
navigate to `/chat`; otherwise just refresh the list.

Styling additions go in the existing shared `pages/_shared/template/sidebar.css`.

## Error handling summary

| Situation | Behavior |
|---|---|
| `?id=` points at a missing/foreign chat | Frontend treats the `404` as "no id" — falls back to a fresh chat, no error shown |
| `PATCH` with a blank title | `400`, existing `json_body()`/error-response conventions |
| `save_chat` fails during `/api/chat` | Logged via `errors.report`, chat answer still returned; `chat_id` omitted only if this was a brand-new, never-yet-saved chat |
| Renaming/deleting a chat you don't own | `404`, identical to "doesn't exist" (see `UnknownChat`) |

## Testing

- `tests/test_chats_store.py`, mirroring `tests/test_auth_store.py`'s
  shape: create/list/get/rename/delete, ownership enforcement (a second
  username can't read/rename/delete another user's chat — gets the same
  outcome as an unknown id), title auto-derivation and truncation, blank
  title rejected.
- `tests/test_chat_routes.py` additions: `POST /api/chat` without
  `chat_id` creates a chat and returns one; with `chat_id` updates the
  existing row; a save failure (mocked) doesn't break the chat response;
  `GET /api/chats` is scoped to the caller; `GET /api/chats/<id>` /
  `PATCH` / `DELETE` all 404 on missing-or-foreign ids.
- TDD throughout, per this project's established practice.
- No new `chats_db` fixture duplication needed beyond mirroring
  `conftest.py`'s existing `users_db` fixture pattern
  (`dataclasses.replace` + `monkeypatch.setattr` across every module that
  imported `settings`).
- Frontend behavior is verified manually (per this project's existing
  convention — this test suite doesn't cover the JS layer today either).

## Files touched

New:
- `chat_app/src/chat_app/chats/__init__.py`
- `chat_app/src/chat_app/chats/store.py`
- `chat_app/tests/test_chats_store.py`

Modified:
- `chat_app/src/chat_app/config.py` — `chats_db_path`
- `chat_app/src/chat_app/pages/chat/routes.py` — new endpoints, `/api/chat` changes
- `chat_app/src/chat_app/pages/chat/template/script.js` — URL/history rewiring
- `chat_app/src/chat_app/pages/chat/template/index.html` — minor, if any new top-level containers are needed beyond the sidebar
- `chat_app/src/chat_app/pages/_shared/template/sidebar.html` — new gated history section
- `chat_app/src/chat_app/pages/_shared/template/sidebar.css` — styling
- `chat_app/tests/test_chat_routes.py` — new endpoint + `/api/chat` tests
- `chat_app/tests/conftest.py` — a `chats_db` fixture mirroring `users_db`
