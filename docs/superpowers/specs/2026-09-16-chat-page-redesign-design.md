# Chat Page Redesign Design

## Goal

Redesign the desktop Chat page as a persistent sidebar and main work area while allowing several conversation responses to continue in the background.

## Scope

- Replace the Chat-specific history controls with the sidebar described below.
- Add a main-pane Manage Chats mode for rename and deletion.
- Persist per-conversation last-AI-response and active-work state.
- Keep a usable narrow-screen fallback; a dedicated mobile design is out of scope.

Out of scope: providers, extensions, prompt composition, transcript rendering, automatic title generation, export, and greeting copy.

## Sidebar

The expanded sidebar is approximately 220px wide; the collapsed rail is 48px and its state persists in browser-local storage.

- A full-width **+ New Chat** control is alone at the top. Collapsed, it shows only the plus icon.
- The middle is the conversation list. Active conversations sort first by newest start time; completed conversations then sort by last completed AI response.
- The footer is pinned at the bottom. Expanded, **Manage Chats** and `<<` share its row. Collapsed, it contains only `>>`.
- A normal conversation row has an ellipsis action button on the left. The remaining area stacks a one-line ellipsized title and relative last-AI-response time. Native tooltips and accessible labels expose the full title and exact timestamp.
- Ellipsis opens Rename and Delete. Rename is inline: Enter or blur saves, Escape cancels. Delete always requires confirmation.
- Active conversations replace the ellipsis with a rotating indicator and remain selectable.

## Main pane and management

**+ New Chat** clears selection and renders the existing canned greeting. It creates no saved record until the first prompt is sent.

**Manage Chats** replaces main-pane content rather than opening a modal or route. It has a back control, checkboxes, Select all, a bulk Delete action, and per-row Rename/Delete. Deletion confirmation states the count and irreversibility. Leaving Manage Chats restores the previously open chat, or the greeting if no chat was open.

## Background response model

Multiple conversations may run concurrently. Sending a prompt creates or reuses the persisted conversation before starting a server-owned response job; it continues if the user navigates away. A job records conversation id, request id, provider id, status (`running`, `completed`, `cancelled`, or `failed`), start time, and event sequence.

The browser subscribes to the selected conversation's event stream. Reopening a running conversation replays its transcript and receives subsequent events, including the Stop control. A terminal assistant response persists the transcript and `last_response_at`, then clears active status. Deleting an active conversation first performs explicit Cancel and delete; all job and chat access is user-scoped.

## Persistence and API

`chats` gains nullable `last_response_at`; existing rows are backfilled from `updated_at`. List records contain `id`, `title`, `last_response_at`, and `activity` (`null` or `{ status, started_at }`). Renaming changes neither timestamp. The page polls its lightweight list while visible; the selected active chat additionally uses the job event stream. Existing Chat permission and ownership protection apply to all new endpoints.

## Accessibility and acceptance

Icon-only controls have accessible names and tooltips. Menus, inline rename, checkboxes, confirmations, and focus restoration are keyboard operable. At narrow widths the sidebar may stack before the main pane without losing controls.

Acceptance requires: matching sidebar states; no empty saved chat after New Chat; two background responses with accurate live status; completed sorting/time labels from AI responses; and correctly scoped rename, individual delete, and confirmed bulk delete.
