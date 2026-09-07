# Chat file attachments (drag/drop, attach button, command file params)

Date: 2026-09-07

## Problem

The chat page has no way to hand the model (or a `/` command) a file's
contents. Everything has to be pasted inline as text. This adds:

1. Drag-and-drop and a paperclip "attach" button on the Chat page.
2. Server-side, per-chat storage for attached files.
3. Attached files inlined as text into the next LLM turn (not persisted
   into the visible transcript).
4. A `format: "file"` convention for a command tool's JSON-schema
   param, so a slash command can declare "this param's value is an
   attached file's contents" - discoverable via the existing `/`
   autocomplete, resolved server-side at execution time.

## Non-goals

- No image/binary/vision support. Only text-decodable files (UTF-8).
  Anything else is rejected at upload time with a plain error.
- No changes to `mcp_server`. `format` is a standard JSON-Schema
  keyword already passed through `inputSchema` untouched - no new
  wire-protocol surface, no server-side capability changes.
- No re-sending of a file's content on every subsequent LLM turn -
  it's inlined once, for the turn it was attached to. Later turns see
  only the plain conversation text (same as today), not a growing pile
  of re-included file dumps.
- No cross-chat attachment reuse. An attachment belongs to exactly one
  chat and is deleted when that chat is deleted.

## Storage (`chat_app/src/services/attachments_store.py`)

New module, same conventions as `chats_store.py`: plain filesystem,
one `_safe_name()` guard against path traversal, no ORM.

```
save_attachment(attachments_dir, chat_id, filename, data: bytes) -> dict
    # validates size (see Config below) and UTF-8 decodability,
    # sanitizes filename, writes attachments_dir/chat_id/filename,
    # returns {"filename": ..., "size": len(data)}.
    # Raises AttachmentError (a plain-message, user-facing exception,
    # same shape as commands.py's CommandError) for either violation.

list_attachments(attachments_dir, chat_id) -> list[dict]
    # [{"filename": ..., "size": ...}, ...] sorted by filename.
    # Empty list (not an error) for a chat with no attachments folder.

read_attachment_text(attachments_dir, chat_id, filename) -> str | None
    # None if the file doesn't exist (also None, never a crash, for a
    # filename that fails the safe-name check - same "doesn't exist"
    # treatment as a missing file, no distinction leaked).

delete_attachment(attachments_dir, chat_id, filename) -> bool
    # True if a file was actually removed.

delete_chat_attachments(attachments_dir, chat_id) -> None
    # Removes the whole chat_id folder, if present. Called from
    # chats_store.delete_chat's call site in __index__.py's
    # delete_chat_api, right after the store delete succeeds.
```

`_safe_name(filename)` rejects anything containing `/`, `\`, or that
resolves outside `attachments_dir/chat_id` once joined (the same
one-line defense already implicit in `chats_store`'s use of a
parameterized chat_id, made explicit here since a filename is
user-supplied in a way a chat_id never is).

## Config

New `chat_app/src/configs/config_attachments.json` (+
`config_attachments.json.example`, same pattern as
`config_chat.json`):

```json
{ "max_file_size_mb": 5 }
```

`Settings` (`chat_app/src/services/llm/settings.py`) gains two fields,
same `_env`-default pattern as `chats_db_path`:

```python
attachments_config_path: Path = field(default_factory=lambda: Path(_env("ATTACHMENTS_CONFIG_PATH", "src/configs/config_attachments.json")))
attachments_dir: Path = field(default_factory=lambda: Path(_env("ATTACHMENTS_DIR", "data/attachments")))
```

`max_file_size_mb` is read via `config_loader.load_json_config` at the
point `attachments_store.save_attachment` needs it (loaded fresh per
call, not cached - config files this small are already read this way
elsewhere in the codebase, and it lets an admin change the cap without
a restart).

## API endpoints (`chat_app/src/pages/Chat/__index__.py`)

```
POST /chat/api/attachments
    multipart/form-data: file=<binary>, chat_id=<optional string>
    - chat_id blank/absent: create the chat first via
      chats_store.save_chat(..., None, []) - the exact lazy-create
      chat_api() already performs for a brand-new chat's first message
      - so an attachment dropped before anything is typed still lands
      in a real, durable chat.
    -> 200 {"chat_id": ..., "filename": ..., "size": ...}
    -> 400 {"error": "..."} for AttachmentError (too big / not text)

GET /chat/api/chats/<chat_id>/attachments
    -> 200 [{"filename": ..., "size": ...}, ...]

DELETE /chat/api/chats/<chat_id>/attachments/<filename>
    -> 204, or 404 if no such attachment
```

All three behind the existing `@require_permission("chat.access")`,
same as every other route in this blueprint. `<chat_id>` in the GET/
DELETE routes is scoped implicitly the same way chat history already
is - `attachments_store` calls take `chat_id` as given, but the route
handlers first confirm `chats_store.get_chat(..., current_user.username,
chat_id)` isn't `None`, so one user can't list or delete another's
attachments by guessing an id (same pattern `get_chat_api` already
uses).

## Command-registry integration (`chat_app/src/services/commands.py`)

`CommandParam` gains a `format: str | None` field, populated in
`_params_from_schema` exactly like `enum` is today:

```python
format=prop_schema.get("format")
```

`commands_api()` in `__index__.py` includes `"format": p.format` in
the per-param JSON it already builds.

`execute_command`'s signature gains `chat_id: str | None`:

```python
def execute_command(question: str, enabled_extensions: list[str], chat_id: str | None) -> str:
```

threaded through from `chat_api()` (which already knows `chat_id` by
this point in the request). After the existing required/unknown-param
checks and before type coercion, any param whose registry entry has
`format == "file"` is resolved against attachments instead of coerced
normally:

```python
if params_by_name[name].format == "file":
    text = attachments_store.read_attachment_text(settings.attachments_dir, chat_id, value)
    if text is None:
        raise CommandError(f"No attachment named {value!r} in this chat. Attach it first, then try again.")
    arguments[name] = text
else:
    arguments[name] = _coerce(value, params_by_name[name].type, name)
```

A `format: "file"` param is therefore always effectively a string
param whose value must name an existing attachment - `_coerce` is
never reached for it, so a non-string `type` alongside `format: "file"`
in some future tool's schema is simply not a case this needs to
handle (schema authors are expected to pair `format: "file"` with
`type: "string"`, same as JSON Schema's own convention for `format`).

## Wiring attachments into the LLM turn (`chat_api()`)

The `/api/chat` POST body gains an optional `attachments: list[str]`
(filenames staged client-side for this message - see UI section).
Only consulted for a non-command turn:

```python
if not is_command and data.get("attachments"):
    blocks = []
    for filename in data["attachments"]:
        text = attachments_store.read_attachment_text(settings.attachments_dir, chat_id, filename)
        if text is not None:
            blocks.append(f"\n\n📎 **{filename}**\n```\n{text}\n```")
    llm_question = question + "".join(blocks)
else:
    llm_question = question
```

`llm_question` (not `question`) is what's passed to
`router.run_chat(...)`. The **persisted and displayed** transcript
entry still stores the original, clean `question` - the file dump is
never written to `chats_store` or shown in a bubble, only sent to the
model for that one turn. This keeps replay (`loadChat()`) identical to
what the user actually typed, and avoids ever-growing bubbles.

A silently-skipped filename (deleted between staging and send,
`text is None`) is not an error - the turn just proceeds without that
one block, same "degrade quietly" spirit as `loadCommands()`'s failed
fetch elsewhere in this file.

## UI (`chat_app/src/pages/Chat/`)

### Attach button + drag-and-drop (`chat.html`, `script.js`, `styles.css`)

- A paperclip `<button id="attach-btn">` next to `#q`, wired to a
  hidden `<input id="attach-input" type="file" multiple>` (click ->
  native picker).
- Drag-and-drop: `dragenter`/`dragover`/`drop` listeners on the
  `.page-content` wrapper, toggling a `.drag-over` CSS class for
  visual feedback (a dashed-outline overlay) and calling
  `preventDefault()` so the browser doesn't navigate to the dropped
  file. `drop`'s `event.dataTransfer.files` feeds the same
  `uploadFiles()` entry point as the picker.

### Upload flow (`script.js`)

```js
let stagedAttachments = []; // [{filename, size}], cleared after send()

async function uploadFiles(fileList) {
  for (const file of fileList) {
    const form = new FormData();
    form.append('file', file);
    if (currentChatId) form.append('chat_id', currentChatId);
    const res = await fetch('/chat/api/attachments', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) { showAttachError(data.error); continue; }
    if (data.chat_id && data.chat_id !== currentChatId) {
      currentChatId = data.chat_id;
      window.history.pushState(null, '', `/chat?id=${encodeURIComponent(currentChatId)}`);
      loadChatHistory();
    }
    stagedAttachments.push({ filename: data.filename, size: data.size });
    renderStagedAttachments();
  }
}
```

`renderStagedAttachments()` draws a chip row (`#staged-attachments`,
between `#log` and `#row`) - one chip per staged file with a ✕ that
calls `DELETE /chat/api/chats/<id>/attachments/<filename>` and removes
it from `stagedAttachments`.

`send()` changes: includes `attachments: stagedAttachments.map(a =>
a.filename)` in the POST body, and clears `stagedAttachments` +
re-renders the (now empty) chip row once the request settles - success
or failure alike, matching how `input`/`sendBtn` are already
re-enabled in the existing `finally` block.

### Command autocomplete (`computeCommandSuggestions` in `script.js`)

The per-param branch that currently only offers `enum` values gains a
`format === 'file'` case, fetched from the same list endpoint used by
the chip row (cached per `currentChatId`, refreshed whenever a new
attachment is uploaded or removed so the suggestions can't go stale
mid-session):

```js
if (param.format === 'file') {
  return attachmentFilenames
    .filter(f => f.startsWith(partialValue))
    .map(f => ({ stage: 'value', text: `${paramName}=${quoteCommandValue(f)}`, display: f, hint: '' }));
}
```

placed as a sibling check right alongside the existing `if (!param ||
!param.enum) return [];` branch, before it (a `format: "file"` param
is never expected to also carry an `enum`, so the two branches don't
need to compose).

## Testing

- `attachments_store`: size-cap rejection, non-UTF-8 rejection, path
  traversal in `filename` (`../../etc/passwd`-style), list/read/delete
  round-trip, `delete_chat_attachments` removing everything for a
  chat_id and leaving other chats' folders untouched.
- `commands.py`: `execute_command` resolving a `format: "file"` param
  from a stubbed attachments folder (happy path, missing attachment ->
  `CommandError`), and that a normal (non-file) param is unaffected.
- Flask test-client tests for the three new endpoints: upload creates
  a chat when none given, upload into an existing chat, oversized/
  non-text upload returns 400, list/delete scoped to the owning user
  (a second user's `chat_id` gets 404, same as `get_chat_api` today).
- Manual browser verification of drag-and-drop, the attach button, chip
  removal, and the file-param autocomplete - left to the user per
  their stated preference not to have this done via automated browser
  agents.
