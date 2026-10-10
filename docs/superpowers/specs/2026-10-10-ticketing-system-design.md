# Ticketing system design

Date: 2026-10-10
Status: design approved in chat, spec awaiting review

## Goal

Users report bugs, errors and failures, suggest features, or file anything else as tickets. Admins triage them in ember_admin. The AI can file tickets in chat, including automatically when it sees a failure caused by configuration or code.

The core ticketing system lives in `mcp_server`. A `tickets` capability only exposes chat tools over it. `ember_api` proxies the core and owns permissions. `ember_web` (reporters) and `ember_admin` (staff) are the two UIs.

## Scope

In scope (phase 1):
- Tickets with type, status, priority, assignee, tags, comment thread and context.
- Laya-assisted grouping of similar tickets and Laya-assisted tagging.
- Deterministic automatic priority elevation per group.
- The `tickets` capability (`/ticket`) and agent instructions, including auto-reporting.
- ember_api routes and permissions, an ember_web page, an ember_admin page.

Out of scope (phase 2, after phase 1 works):
- Attachments (screenshots, files).
- Email notifications on ticket changes.
- Free-form labels beyond the closed tag vocabulary.

Not building: followers or voting. Every report keeps its own ticket so the reporter's details are never lost. Laya groups tickets instead of merging them.

## Architecture

```
ember_web ---\                     /--> mcp_server core: services/tickets.py + /tickets routes (always on)
              > ember_api (auth) --                      ^
ember_admin -/                     \                     | thin domain calls
                                      tickets capability (/ticket tools, switchable)
                                                         ^
                                      ai_agent agents (MCP tools, requester in _meta)
mcp_server core --(optional, HTTP)--> Laya agent in ai_agent (classification only)
```

- The core and its HTTP routes stay available when the `tickets` capability is switched off. The switch only removes the chat tools (and so AI filing).
- Routes use `X-Internal-Token`, like `/upload`. ember_api sends requester headers and chooses reporter (`/tickets`) or staff (`/ticket-admin`) routes; reporter identity is never taken from a request body or a tool argument.

## 1. mcp_server core

Files: `src/services/tickets.py` (async orchestration), `ticket_store.py` (SQLite), `ticket_rules.py` (pure rules), `ticket_config.py` (configuration), `src/ticket_routes.py` (HTTP), `ticket_laya.py` (classifier) and `ticket_laya_transport.py` (MCP transport), registered in `run.py` beside the other routes. Storage defaults to `specifics/tickets/.data/tickets.db`, configurable with `MCP_TICKETS_DB_PATH`. Reads never create the file.

### Data model

`tickets`
- `id`, `group_id`, `type` (`bug` | `feature` | `other`), `title`, `description`
- `status` (`open` | `in_progress` | `resolved` | `closed`)
- `priority` (`low` | `normal` | `high` | `urgent`); the pin flag lives on the group
- `assignee` (username or null), `reporter` (username)
- `source` (`user` | `ai_user_request` | `ai_auto`)
- `tags` (JSON list from the vocabulary)
- `context` (JSON: `reported` = model- or client-supplied fields marked unverified, `verified` = fields added by ember_api)
- `fingerprint` (auto reports only), `possible_group_id` (hint when Laya was uncertain)
- `created_at`, `updated_at`, `closed_at`

`ticket_groups`
- `id`, `title` (taken from the oldest ticket), `priority`, `priority_pinned` (bool), `created_at`, `updated_at`

`ticket_comments`
- `id`, `ticket_id`, `author`, `author_role` (`reporter` | `staff` | `ai`), `body`, `created_at`

Effective priority of a ticket is the higher of its own priority and its group's priority.

### Auto-report guards

- Fingerprint = hash of tool name plus normalized error text (numbers, ids, paths collapsed).
- One open `ai_auto` ticket per reporter per fingerprint. A second filing returns the existing ticket id instead of creating one.
- A second user hitting the same error still gets their own ticket.
- Per-reporter hourly cap on `ai_auto` tickets (config value).
- Error text passes `utils/redact.py` and is length-capped before it is stored. Stored context is never logged.

### Tags

Closed vocabulary in config (`configs/config_tickets.json`), for example `config`, `tool-failure`, `auth`, `ui`, `chat`, `performance`, `email`, `feature-request`. A closed set is needed because Laya `choice` questions need fixed options. Config tags are `tag: description` pairs (Laya needs a description per option); 2 to 10 tags. Laya assigns at most one tag, and only when it is confident. The filing AI may pass tags; each ticket keeps at most five valid, unique tags. Unknown tags are dropped. When no valid tag remains, Laya picks from the vocabulary (`choice`); if Laya is unavailable the ticket gets no tags. Staff can edit tags afterwards.

### Grouping

On creation:
1. Candidates: open tickets of the same type with overlapping tags (all open tickets of the same type when the new ticket has no tags), newest first, at most 5. The fingerprint is checked first for `ai_auto`.
2. For each candidate, ask Laya a pairwise `noul` question ("same underlying issue?") over title plus the first ~500 characters of each description. Input stays under Laya's 512-token limit; over-long text is truncated before sending.
3. A confident yes joins the candidate's group. A no for every candidate creates a new group. An uncertain answer or Laya being unreachable creates a new group and records `possible_group_id` for staff.
4. Staff can move a ticket to another group or split it out manually.

Laya runs only on creation, never blocks it for long (short timeout; failure means "no grouping").

### Priority elevation

Deterministic code, not Laya. For each group, count tickets (`n`) and tickets created in the last 24 h (`r`). Thresholds come from config, for example `n >= 3` or `r >= 2` raises to `high`, `n >= 6` or `r >= 4` raises to `urgent`. Elevation only raises, never lowers, and stops while `priority_pinned` is true (set when staff sets the group's priority by hand). Re-evaluated when a ticket joins a group or is moved into one, and when staff unpins it. The rate shown to staff is computed live on read; because elevation never lowers priority, no periodic job is needed.

### HTTP routes

Reporter scope (requester must own the ticket):
- `POST /tickets` create, `GET /tickets` list own, `GET /tickets/{id}` get with comments, `POST /tickets/{id}/comments`, `POST /tickets/{id}/close`.

Staff scope (ember_api only calls these for `tickets.manage`):
- `GET /ticket-admin/tickets` (filters: status, type, tag, effective priority, assignee, `group_id`, `possible=1`, limit), `GET /ticket-admin/tickets/{id}`, `PATCH /ticket-admin/tickets/{id}` (status, priority, assignee, tags), `POST /ticket-admin/tickets/{id}/comments` with staff role, `POST /ticket-admin/tickets/{id}/move` (`group_id`, or `null` to split out), `GET /ticket-admin/groups` (status, tag, group priority, limit), `PATCH /ticket-admin/groups/{id}` (priority, `pinned`), `GET /ticket-admin/stats` (open tickets, urgent tickets, open groups).

Errors: 400 with a safe message for bad input, 401 for a bad token, 404 for a missing or not-owned ticket (same response, so existence does not leak).

### Laya link

The link is `LAYA_URL` (ai_agent's Laya agent MCP address); mcp_server opens one short MCP session per question and sends the shared internal token. Classifier limits live in `configs/config_tickets.json.example`. Unset means grouping and Laya tagging are skipped. Laya answers are advisory: the confidence gate follows ai_agent's `min_confidence` semantics, and the smoke test showed many answers fall under 0.70, so expect frequent hints instead of automatic grouping at first. The admin move/split action covers that.

## 2. `tickets` capability

Path `src/capabilities/tickets/` with `contract.py`, `domain.py`, `tool.py`, `help.json`, README and a toggle in `config_capabilities.json`. Follows the `mcp-capability-scaffold` skill. `domain.py` only calls the core service. Requester comes from `identity_context` (`_meta.requester`), never from a tool argument.

| Tool | Slash | Purpose |
|---|---|---|
| `tool_ticket_createTicket` | `/ticket create` | type, title, description, optional tags, `source`, context fields. Returns id, duplicate flag and a status message. |
| `tool_ticket_listMyTickets` | `/ticket list` | Own tickets, optional status filter. |
| `tool_ticket_getTicket` | `/ticket show` | Own ticket with its comment thread. |
| `tool_ticket_addComment` | `/ticket reply` | Add information to an own ticket. |

No close, priority or assignee tools in chat. The `source` argument of `createTicket` defaults to `user`, so the default slash form records `user`; agents pass `ai_user_request` or `ai_auto`. Model-supplied context (`chat_id`, `agent`, `tool_name`, `error_text`) is stored as unverified.

### Agent behavior

Instruction text in the shared agent prompts (not code):
- When a user says to report a bug or suggest a feature, the AI drafts title, type, description and tags from the conversation and files the ticket without a confirm step. It replies with the ticket id.
- Auto-report: file when a tool failure points at configuration or code (missing config key, validation error, "not configured", unhandled exception, schema mismatch). Do not file for user mistakes, bad input, network blips, rate limits or permission denials. Always tell the user a ticket was filed, with its id.
- Specialist agents get the ticket tools in their tool globs (`tool_ticket_createTicket` at minimum, plus list/show/reply where useful), because they see most tool failures first. Agent files change in `apps/ai_agent/agents/`.
- Capability offline means no tools and so no auto-reporting; core and UIs keep working.

## 3. ember_api

Files: `routes/tickets.py`, `services/ticket_gateway.py`, permission entries in `services/permissions.py`, a migration.

- Gateway proxies to mcp_server with internal token and requester headers, like `mcp_server_info.py`. `McpServerUnavailable` maps to 502; a 4xx message passes through.
- Permissions:
  - `tickets.create`: file, list, view, comment on, close own tickets. Added to the default role, and a migration grants it to existing roles holding `chat.use`.
  - `tickets.manage`: see all tickets and groups, change status, priority, assignee, tags, move tickets, comment as staff. The Administrator role holds it automatically.
- Reporter routes (`tickets.create`): `POST /api/tickets`, `GET /api/tickets` (own, optional status), `GET /api/tickets/{id}`, `POST /api/tickets/{id}/comments`, `POST /api/tickets/{id}/close` (JSON `{}`). Reporters cannot set tags, source, reporter, status, priority or assignee.
- Staff routes (`tickets.manage`): `GET /api/admin/tickets` (status, type, tag, effective priority, assignee, group_id, possible, limit), `GET /api/admin/tickets/stats`, `GET /api/admin/tickets/{id}`, `PATCH /api/admin/tickets/{id}`, `POST /api/admin/tickets/{id}/comments`, `POST /api/admin/tickets/{id}/move` (group_id or null to split), `GET /api/admin/ticket-groups` (status, tag, group priority, limit), `PATCH /api/admin/ticket-groups/{id}` (priority, pin).
- Tickets filed through ember_api carry `source: user` and `verified_context` with `via: ember_api` and `account_id` as text. No browser context is accepted. Manual creation has no additional rate limiter; mcp_server limits automatic reports.
- Ticket storage remains entirely in mcp_server. Ownership uses usernames, so an account rename orphans its existing tickets; the verified stable account id is retained for a later migration, as with memory notes.
- Every staff change is written to the activity log.
- Tests: permission matrix, own-only isolation, proxy error mapping, migration.

## 4. ember_web

Route `/tickets`, permission `tickets.create`.
- My tickets list (status chip, type, last update) and a detail view with the comment thread, a reply box and Close (in-app confirm).
- New ticket form: type, title, description. Tags are not shown to reporters.
- Entry in the rail through the existing page list. Follows the ember design system (radius tokens, pill controls, light/dark tokens).

## 5. ember_admin

Route `/tickets`, permission `tickets.manage`, registered in `router/pages.ts`.
- Table of groups (title, ticket count, tags, effective priority, newest activity, status). A row expands into its tickets (reporter, source badge `user` / `ai request` / `ai auto`, status).
- Filters kept in the URL like Accounts: status, type, tag, priority, assignee, possible duplicates.
- Ticket drawer (native dialog): description, reported context marked unverified, comment thread, controls for status, priority, assignee, tags and "move to group". Controls show only the server-confirmed state.
- Group priority control with a pin toggle; shows whether priority is auto-elevated or pinned.
- Overview card on `/admin`: open and urgent counts.

## Testing

- Core: pytest for the service (create, own-only access, guards, fingerprint dedupe, hourly cap, grouping with a fake Laya client for yes / no / uncertain / unreachable, priority elevation and pin, tag filtering), and the routes (token, scope, 404 behavior).
- Capability: tools call the core with the requester from `_meta`; offline behavior.
- ember_api: as above. Frontends: Vitest and Playwright e2e against a fake `/api`, per each app's convention.

## Build order

1. mcp_server core (service, routes, Laya client, tests).
2. `tickets` capability, agent instructions, specialist tool globs.
3. ember_api permissions, migration, routes.
4. ember_web page (propose each step and wait for approval).
5. ember_admin page (same).
6. Phase 2: attachments and email notifications.

## Risks and open points

- Laya confidence is weak today; grouping will often fall back to "own group with a hint". Acceptable because grouping is advisory and ticket creation never depends on it.
- Model-judged auto-reporting can misfire. The guards (fingerprint, hourly cap, redaction, unverified context, visible announcement to the user) make a wrong call cheap.
- Thresholds, tag vocabulary and the Laya timeout are first guesses; they live in config so they can be tuned without code changes.
