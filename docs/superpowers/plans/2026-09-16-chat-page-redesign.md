# Chat Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the redesigned Chat sidebar and Manage Chats workspace with concurrent, resumable conversation responses.

**Architecture:** Keep markup, styles, and browser behavior in the existing Chat page files. Move request lifetime from a selected browser view to a per-user, per-conversation server job registry with a replayable event buffer. SQLite remains the persisted transcript and response-time source.

**Tech Stack:** Python 3.11, Flask, SQLite, server-sent events, vanilla JavaScript, CSS, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-chat-page-redesign-design.md`

## Global Constraints

- Preserve greeting copy, providers, extensions, transcript rendering, export, and title derivation.
- Require `chat.access` and `current_user.username` ownership for all job and chat operations.
- Add no dependency.
- Use approximately 220px expanded and 48px collapsed sidebar widths.
- Only completed AI responses update `last_response_at`.
- Active deletion cancels the owned job before deleting its chat.

---

### Task 1: Add response timestamp and activity list contract

**Files:**
- Modify: `chat_app/src/services/chats_store.py:35-145`
- Modify: `chat_app/tests/test_chats_store.py`

**Interfaces:**
- Produces `record_last_response(db_path: Path, username: str, chat_id: str, timestamp: str) -> None`.
- Produces `list_chats(db_path: Path, username: str, activity_by_chat: dict[str, dict] | None = None) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Add a test that saves two chats, records a timestamp only for the first, supplies a `running` activity record only for the second, and asserts the returned order is second then first and that the second record carries `activity.status == "running"`.

- [ ] **Step 2: Run it to verify failure**

Run: `cd chat_app; py -m pytest tests/test_chats_store.py -q`

Expected: FAIL because `record_last_response` and list activity do not exist.

- [ ] **Step 3: Write the minimal implementation**

Use guarded `PRAGMA table_info(chats)` plus `ALTER TABLE` to add nullable `last_response_at`; backfill legacy nulls from `updated_at`. Implement username-scoped `record_last_response` with the existing `UnknownChat` convention. Return `last_response_at` and supplied `activity`; sort running rows by `started_at DESC`, then completed rows by `last_response_at DESC`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd chat_app; py -m pytest tests/test_chats_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add chat_app/src/services/chats_store.py chat_app/tests/test_chats_store.py; git commit -m "feat: track chat response timestamps"`

### Task 2: Create user-owned background response jobs

**Files:**
- Create: `chat_app/src/services/chat_jobs.py`
- Modify: `chat_app/src/pages/Chat/__index__.py:386-760`
- Modify: `chat_app/tests/test_chat_page.py`

**Interfaces:**
- Produces `ChatJobRegistry.start(username, chat_id, provider_id, request_id, question, history) -> ChatJob`.
- Produces `status_for_user(username) -> dict[str, dict]`, `subscribe(username, chat_id, after_sequence) -> Iterator[dict]`, and `cancel(username, chat_id) -> bool`.
- Produces `GET /chat/api/chats/<chat_id>/events` and `POST /chat/api/chats/<chat_id>/cancel`.

- [ ] **Step 1: Write failing ownership and cancellation tests**

Start Alice's delayed job; assert only Alice sees `activity.status == "running"`. Assert an active owned delete invokes `registry.cancel(username, chat_id)` before removing the row.

- [ ] **Step 2: Run tests to verify failure**

Run: `cd chat_app; py -m pytest tests/test_chat_page.py -q`

Expected: FAIL because no job registry/routes exist.

- [ ] **Step 3: Implement server-owned jobs and replay**

Give each job a sequence-numbered bounded event buffer. A worker consumes `ask_stream`, publishes intermediate events, writes the terminal transcript once, calls `record_last_response`, and marks completion/cancellation/failure. Subscription replays events newer than `after_sequence` then waits for terminal or new events. Lookup, list activity, subscription, and cancellation reject mismatched usernames. Reuse the existing provider/request-id cancellation client.

- [ ] **Step 4: Run focused verification**

Run: `cd chat_app; py -m pytest tests/test_chat_page.py -q`

Expected: PASS, including existing streaming, cancellation, and ownership tests.

- [ ] **Step 5: Commit**

Run: `git add chat_app/src/services/chat_jobs.py chat_app/src/pages/Chat/__index__.py chat_app/tests/test_chat_page.py; git commit -m "feat: run chat responses in background"`

### Task 3: Build the sidebar and Manage Chats shell

**Files:**
- Modify: `chat_app/src/pages/Chat/chat.html`
- Modify: `chat_app/src/pages/Chat/styles.css:975-1145`
- Modify: `chat_app/tests/test_chat_page.py`

**Interfaces:**
- Produces `#chat-sidebar`, `#chat-sidebar-list`, `#manage-chats-view`, and `#chat-main-view`.

- [ ] **Step 1: Write a failing markup test**

GET `/chat/` as a `chat.access` user and assert the page includes `id="chat-sidebar"` and `id="manage-chats-view"`.

- [ ] **Step 2: Run it to verify failure**

Run: `cd chat_app; py -m pytest tests/test_chat_page.py::test_chat_page_contains_sidebar_and_manage_view -q`

Expected: FAIL because redesigned containers are absent.

- [ ] **Step 3: Implement static layout and responsive rules**

Place New Chat alone at the top, a scrollable list centrally, and a pinned footer. Expanded footer contains Manage Chats plus `<<`; collapsed contains only `>>`. Render vertical title/time row content and reserve the left slot for ellipsis/spinner. Add `aria-label` and title text to icon controls. Preserve functionality in the existing <=700px stacked layout.

- [ ] **Step 4: Verify markup and layout**

Run: `cd chat_app; py -m pytest tests/test_chat_page.py::test_chat_page_contains_sidebar_and_manage_view -q`

Expected: PASS. Manually inspect expanded/collapsed and narrow layouts for overflow and focus visibility.

- [ ] **Step 5: Commit**

Run: `git add chat_app/src/pages/Chat/chat.html chat_app/src/pages/Chat/styles.css chat_app/tests/test_chat_page.py; git commit -m "feat: redesign chat sidebar layout"`

### Task 4: Implement client conversation state and management

**Files:**
- Modify: `chat_app/src/pages/Chat/script.js:1-20, 1339-1705, 2124-2504, 2616-2623`
- Modify: `chat_app/tests/test_chat_page.py`

**Interfaces:**
- Produces `activeChats: Map<string, {requestId: string, providerId: string, lastSequence: number}>`.
- Produces `openChat(chatId)`, `startChatJob(question)`, `subscribeToChat(chatId)`, `renderChatHistory(rows)`, and `showManageChats()`.

- [ ] **Step 1: Add failing helper tests**

Cover relative response labels “Just now”, “12m ago”, and “Yesterday”; also cover active rows sorting before completed rows.

- [ ] **Step 2: Run tests to verify failure**

Run: `cd chat_app; py -m pytest tests/test_chat_page.py -q`

Expected: FAIL until new helpers and client state exist.

- [ ] **Step 3: Implement client behavior**

Replace global active-request state with per-chat map entries. New Chat shows the greeting without persistence. Sending starts a job and refreshes the list; switching chats never cancels jobs. Poll the list while visible; subscribe only to the selected active chat. Render ellipsis actions, spinner state, inline rename (Enter/blur/Escape), select-all, and confirmation-backed single/bulk deletion. Active deletion cancels before delete. Restore prior chat on leaving Manage Chats.

- [ ] **Step 4: Run relevant verification**

Run: `cd chat_app; py -m pytest tests/test_chats_store.py tests/test_chat_page.py -q`

Expected: PASS. Manually verify two delayed responses, switching/reopening, Stop, single delete, and bulk delete.

- [ ] **Step 5: Commit**

Run: `git add chat_app/src/pages/Chat/script.js chat_app/tests/test_chat_page.py; git commit -m "feat: manage concurrent chat conversations"`

### Task 5: Document and fully verify

**Files:**
- Modify: `chat_app/src/pages/Chat/README.md`

- [ ] **Step 1: Document the lifecycle**

Explain server-owned jobs, username-scoped status, `last_response_at`, event replay, and cancellation; retain the existing permission and cross-site security notes.

- [ ] **Step 2: Run full verification**

Run: `cd chat_app; py -m pytest tests/test_chats_store.py tests/test_chat_page.py -q; py -m pytest -q; git diff --check`

Expected: every test passes and `git diff --check` has no output.

- [ ] **Step 3: Commit**

Run: `git add chat_app/src/pages/Chat/README.md; git commit -m "docs: describe chat background jobs"`

## Self-review

Tasks 1-2 cover time, ordering, background jobs, reconnection, ownership, and active deletion. Tasks 3-4 cover every sidebar, management, and accessibility requirement. Task 5 provides regression proof and documentation. Interfaces from each task match later consumers; no implementation step is deferred.
