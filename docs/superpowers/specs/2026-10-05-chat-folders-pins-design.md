# Chat folders and pins: design

Date: 2026-10-05. Projects: `ember_api`, `ember_web`.

## Goal

Let a user organize saved chats in the Ember sidebar: pin chats to the top and
file chats into folders. Today the sidebar is one flat list (with search,
rename, select mode and delete).

## Decisions

| Question | Decision |
|---|---|
| Folder shape | One level. A folder holds chats, never other folders. |
| Deleting a folder | Deletes the folder and every chat in it. The confirm text names the folder and the chat count. Refused (409) while any chat in it has a running turn. |
| Moving a chat | Both a "Move to..." menu (phase 4) and drag and drop (phase 5). The menu is the primary path and works on touch screens. |
| Pinning | A "Pinned" section above the folders. A pinned chat shows only there; its `folder_id` is kept, so unpinning returns it to its folder. |
| Storage | Server side: a `chat_folders` table plus columns on `chats`. Not `localStorage`, so organization syncs across devices. |

Out of scope: nested folders, bulk move, folder colors, sharing folders,
folder names in search hits, chat_cli support (it ignores the new fields).

## ember_api

### Model

New table `chat_folders`:
- `id` (pk), `account_id` (FK to `accounts.id`, `ON DELETE CASCADE`, indexed),
  `name` (String 60), `position` (int), `created_at` (naive UTC).
- Unique on `(account_id, lower(name))`.

`chats` gains:
- `folder_id`: nullable FK to `chat_folders.id`, `ON DELETE CASCADE`, indexed.
- `pinned`: bool, default false (`server_default` in the migration).

One Alembic migration. `tests/test_migrations.py` must pass.

Limits: 30 folders per account. Names are trimmed and whitespace-collapsed;
empty names are rejected (422); a duplicate name is 409.

### Service

`FolderService(session, account_id)`: `list` (with chat counts), `create`,
`rename`, `reorder`, `delete`. `delete` first checks the running-turn registry
for any chat in the folder and raises a conflict if one is found. It then
deletes the folder's chats through the same path the single-chat delete uses,
so shares and usage references are handled the way they are today, and then the
folder, in one transaction. A raw SQL cascade is a backstop, not the main path.

### Routes (all `chat.use`, JSON bodies, audited with `logs.action`)

- `GET /api/chat-folders` returns `[{id, name, position, chat_count}]`.
- `POST /api/chat-folders` `{name}` returns 201.
- `PATCH /api/chat-folders/{id}` `{name?, position?}`.
- `DELETE /api/chat-folders/{id}` returns 204, or 409 if a chat in it is running.
- Existing `PATCH /api/chats/{id}` accepts `folder_id` (nullable) and `pinned`.
- Existing `GET /api/chats` rows include `folder_id` and `pinned`. Messages stay
  out of list rows.
- A folder id the account does not own is 404 (never reveals other accounts' ids).
- A branched chat inherits the source's `folder_id` and is not pinned.

README API table updated.

## ember_web

### Data

- `api/FoldersClient.ts`: `list`, `create`, `rename`, `reorder`, `remove`
  through `apiRequest`. `ChatsClient` gains `update` (`chatsClient.update`); the chat store
  exposes `setChatFolder` and `setChatPinned`.
- `Conversation` gains `folderId?: number | null` and `pinned?: boolean`.
- New Pinia store `stores/folders.ts`, reset when the account changes, like
  `stores/chat.ts`.
- Collapsed-folder state is kept in `localStorage`, keyed per account, wrapped
  in try/catch, like `ConversationStorage`.
- A chat with a running turn is locked for move, pin-changes that would hide it
  mid-answer are allowed, and delete stays blocked as today.

### Sidebar

`ConversationSidebar.vue` is about 490 lines, so it is split first with no
behavior change:
- `ChatRow.vue`: one row (title, running dot, rename, delete, plus new pin and
  move buttons).
- `FolderGroup.vue`: collapsible header (name, count, rename, delete) plus rows.
- `MoveToMenu.vue`: folders, "No folder", "New folder...".

Layout order: Pinned, folders by `position`, then Unfiled. Empty sections are
hidden. Search results still replace the list, flat and unchanged. Select mode
and "Delete all chats" keep working across all sections. New and rename folder
use `BaseModal`. Only theme tokens are used for color.

Drag and drop: a row is dropped onto a folder header, the Pinned header or the
Unfiled area, and calls the same store actions as the menu. It is off on touch
screens and for locked chats.

## Phases (each committed separately after approval)

1. ember_api: model, migration, service, routes, PATCH fields, README, tests.
2. ember_web data layer: clients, store, types, `e2e/fakeApi.ts`, unit tests.
3. Sidebar extraction (`ChatRow`, `FolderGroup`) with no behavior change; all
   existing tests still pass.
4. Sidebar features: pinned section, folder groups, Move menu, folder dialogs.
5. Drag and drop.

## Testing

- ember_api tests: create, rename, duplicate 409, limit 30, move, wrong-account
  404, delete removes its chats and spares other folders and other accounts,
  delete blocked 409 during a running turn, 401 and 403, list fields, branch
  inheritance, migration.
- ember_web: unit tests per component and store with ember_api mocked; run
  `npx vue-tsc -b --noEmit`, `npm test`, `npx vite build` (then delete `dist/`).
- The user tests in the browser by hand; a short manual checklist is given with
  each phase. No browser-verification agents.

## Risks

- Cascade deletion of chats is the sharp edge: covered by the confirm text, the
  running-turn guard, and tests that other data survives.
- Shares and usage rows refer to chats by `chat_id`: the folder delete reuses
  the single-chat delete path, and phase 1 checks what that path does for them.
- The sidebar extraction touches tested code: it is its own phase.

## Phase 4 design (approved 2026-10-05): sidebar UI

This section refines the "Sidebar" part above; where they differ, this section wins.

### Decisions

| Question | Decision |
|---|---|
| Row actions | One "..." button per row (also right-click) opens a menu: Pin or Unpin, Move to..., Rename, Delete. The rename and delete hover icons go away. Double-clicking the title still renames. |
| Move to... | A flyout beside the menu: folders (check mark on the current one), "No folder", "New folder...". On narrow or touch screens the flyout opens over the main menu. |
| Managing folders | The folder header has its own "..." menu (Rename, Delete). A "New folder" button sits in the sidebar footer and in the Move flyout. Naming and deleting use `BaseModal` dialogs that show the server's errors. |
| Chat delete | Still the browser `confirm()` it uses today. |

### Layout

- Sections in order: Pinned, one group per folder (creation order), then Unfiled (headed "Chats").
- Pinned and Unfiled are hidden when empty. **Folders are always shown, even when empty** (this changes the earlier "empty sections are hidden"): a folder that vanished could not be renamed, deleted or moved into.
- With no pins and no folders the list is flat with no headers, exactly as before.
- A chat whose folder is unknown to the loaded folder list (or whose `folderId` is undefined) is Unfiled.
- Search results still replace the whole list, flat. Select mode and "Delete all chats" work across all sections.
- Folder counts are derived from the chat store, not the server's `chat_count`.
- Collapsed folders are remembered per account in `localStorage` (try/catch). Pinned and Unfiled do not collapse.

### Rules

- A chat that is answering: Move to... and Delete are disabled in its menu; Pin stays available; Rename stays available.
- At 30 folders "New folder" is disabled (footer button and flyout entry).
- Deleting a folder: the dialog says `Delete folder "<name>" and its <n> chat(s)? This can't be undone.`; a 409 from the server is shown inside the dialog and nothing is removed; on success the chat store forgets the folder's chats (the open chat closes if it was one of them).
- The menu is rendered with `Teleport` to the page body, so the sidebar's scrolling never clips it. Esc closes it (first the flyout, then the menu); arrow keys, Home, End, Enter and Space work; focus returns to the button after Esc or an outside click.

### Units

`utils/chatSections.ts` (layout), `utils/chatMenu.ts` (menu items and parsing), `composables/useFolderCollapse.ts`, `components/PopupMenu.vue`, `components/ChatSection.vue` (section header and rows; replaces the spec's `FolderGroup.vue` because Pinned and Unfiled use the same header), `components/FolderDialogs.vue` (create, rename and delete dialogs, driven through exposed methods), changes to `ChatRow.vue`, `ConversationSidebar.vue`, `ChatView.vue`, and the carry-overs (list-sequence guard, `ensureLoaded` promise, `e2e/fakeApi.ts`).
