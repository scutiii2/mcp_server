# ember_api

Backend for [ember_web](../ember_web). It owns ember_web's user accounts and
login sessions (its own database, separate from chat_app's) and will proxy
all of ember_web's MCP traffic to `ai_agent` and `mcp_server`, so the
browser never talks to those servers or holds their credentials.

Built with FastAPI + async SQLAlchemy (SQLite via aiosqlite). The auth logic
mirrors chat_app's `services/auth_service.py`: same werkzeug password
hashes, same bootstrap-admin rules, same role/permission tables.

Chat turn streams relay bounded `plan_update` checklist snapshots by agent.
Reconnect snapshots include the latest plans for that turn; plans are not
stored in the chat transcript.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Accounts, bootstrap admin, login/logout/me, sessions | done |
| 2 | Registration with invite codes, email verification (MCP Email capability) | done |
| 3 | MCP proxy to ai_agent / mcp_server with permission checks | done |
| 4 | ember_web switches to ember_api (login pages, `/api` via Vite proxy) | done |
| 5 | Cleanup: drop the old direct CORS on ai_agent / mcp_server | done |

## Requirements

- Python 3.11+ (developed on 3.14)

## Setup and running

`run.bat` creates `.venv_ember_api`, installs the project (editable, with dev
extras) on first run, then starts the server on `EMBER_API_PORT` (default
`8030`). server_launcher lists it as **Ember API**.

Manually:

```bash
py -m venv .venv_ember_api
.venv_ember_api\Scripts\pip install -e ".[dev]"
.venv_ember_api\Scripts\python -m src.run
```

On first start, a missing `configs/config_app.json` is copied from its
`.example` twin and a missing `.env` is built from an old
`secrets/secret_*.env` set if there is one, else from `.env.example`,
`data/ember_api.db` is created, and the bootstrap admin account is made. If
`BOOTSTRAP_ADMIN_PASSWORD` is empty, a random password is printed to the
console once - save it.

Tests:

```bash
.venv_ember_api\Scripts\python -m pytest
```

## Moving from chat_app

`scripts/import_chat_app.py` copies chat_app's accounts, chats, token usage,
activity log and known devices into ember_api, so chat_app can be retired. Run it from `apps/ember_api/` with
ember_api stopped:

```bash
.venv_ember_api\Scripts\python -m scripts.import_chat_app --chat-app ..\chat_app
.venv_ember_api\Scripts\python -m scripts.import_chat_app --chat-app ..\chat_app --apply
.venv_ember_api\Scripts\python -m scripts.import_chat_app --chat-app ..\chat_app --apply --agent-map anthropic=claude-agent
```

The first command is a dry run: it prints what would happen and writes nothing.
`--apply` first copies ember_api's database to `<name>.bak-<timestamp>`.
chat_app's files (`data/app.db`, `chats.db`, `usage.db`) are only read. A file
that is missing leaves that part out and is named in the report.

- **Accounts:** username, email, password hash, active and verified flags and
  creation time are kept, so people log in with the password they had. Roles are
  matched by name; a role ember_api lacks is created with no permissions (the
  report lists them: give them some in the Admin page, since chat_app's
  permission names differ from ember_api's). The protected flag is not copied.
  An account whose username or email is already used by a different account is
  skipped, and so are its chats and usage rows.
- **Chats:** every chat of an imported account, with its text, title and times.
  Characters ember_api's routes refuse in an id (chat_app ids may hold `_`) become
  `-`. The chat's agent is the one in its latest usage row, else none. A chat that
  is broken, over 2 MB or beyond the 1000-per-account cap is reported and left
  out; the rest still import.
- **Usage:** every row with tokens, with its agent, model, input/output split and
  chat, so the 6-hour and weekly limits and the Usage page carry on from the old
  history. Rows chat_app wrote at the same moment stay one turn.
- **Log entries:** chat_app's Logs rows (logins, admin actions, errors, chat
  turns) with their times. An entry of an imported account belongs to it. An
  entry of an account that was skipped (ember_api has its own `admin`) or that
  chat_app no longer has is kept with no account, and a skipped account's name
  is added to the message (` [chat_app: admin]`); it is never given to another
  person. ember_api deletes log entries older than 90 days at startup, so these
  go with the rest.
- **Devices:** the devices an imported account logged in from. chat_app and
  ember_api hash the same signals the same way (User-Agent, language, /24
  network), so a login from the same browser and network is not reported as a
  new device. The browser and network were never stored, so the Account page
  shows them as unknown. This holds only while `security.fingerprint.signals`
  is the default three in both apps.
- **Agent names:** chat_app stored its provider name (such as `anthropic`) as
  the agent. `--agent-map OLD=NEW` (repeatable) gives rows that name an ember
  agent id instead, for rows being imported and for rows imported earlier under
  the old name (the report counts them as relabelled). NEW must be an agent
  ai_agent has registered, so ai_agent has to be running; a typo stops the
  command before anything is written. A chat or usage row is renamed only if
  it matches a chat_app row and still carries the old name.
- **Left out:** chat_app's login attempts and security events.
- **Safe to repeat:** an account already imported (same username, email and
  password hash) is recognised, and only chats, usage rows, log entries and
  devices not yet there are added. Apart from a `--agent-map` relabel, nothing
  already in ember_api is changed.

## API

Every `POST` must send `Content-Type: application/json` (anything else gets
`415`) - with the `SameSite=Strict` cookie this blocks cross-site request
forgery. (Other methods need a CORS preflight cross-site, which ember_api
never grants; the MCP client's session `DELETE` has no body at all.)

| Method | Path | Auth | Returns |
|---|---|---|---|
| `POST` | `/api/auth/login` | - | `{username, password}` -> the account; sets the session cookie. `401` with one generic message on any failure; `429` + `Retry-After` after too many failures (`security.rate_limit`). |
| `POST` | `/api/auth/logout` | cookie | `204`; deletes the session server-side and clears the cookie. |
| `GET` | `/api/auth/me` | cookie | `{id, username, email, email_verified, email_verification_required, prompt_suggestions, roles, permissions}` or `401`. `email_verification_required` mirrors `require_email_verification` in config. |
| `POST` | `/api/auth/register` | - | `{username, email, password, invite_code}` -> `201 {account, verification_email_sent, email_error}`; logs in. `400` bad/expired/used invite, `409` taken username/email, `422` invalid fields. |
| `POST` | `/api/auth/verify-email` | cookie | `{code}` -> the account, now verified. `400` wrong/expired code. |
| `POST` | `/api/auth/verify-email/resend` | cookie | `{sent: true}`; `503` if SMTP failed, `409` if already verified. |
| `POST` | `/api/account/email` | cookie | `{current_password, email}` -> `{account, verification_email_sent, email_error}`. The new email is unverified (permissions off) until its emailed code is entered. `400` wrong password, `409` email taken or bootstrap admin. |
| `POST` | `/api/account/password` | cookie | `{current_password, new_password}` (8+ chars) -> the account. Logs out every other session. `400` wrong password, `409` bootstrap admin (change it in `.env`). |
| `PATCH` | `/api/account/preferences` | logged in | `{prompt_suggestions: bool}`: whether chat suggests the next prompt. Returns the account. |
| `GET` | `/api/account/devices` | cookie | Devices this account logged in from, most recent first: `[{id, label, user_agent, ip_subnet, first_seen_at, last_seen_at, current}]`. |
| `DELETE` | `/api/account/devices/{id}` | cookie | `204`; its next login counts as a new device again. `404` unknown or another account's. |
| `POST` | `/api/admin/invites` | `invites.manage` | `{invitee_email?, delivery_method: "manual"\|"email"}` -> `201 {invite, code, email_sent, email_error}`. The code is shown only here. |
| `PUT` | `/api/admin/settings/{name}` | `settings.manage` | `{value: true\|false}` -> `{name: value}`. Switches a setting everyone is held to; the only one is `force_tool_approval`. `404` unknown name, `422` for a non-boolean value. Logged as `admin.setting` with the old and new value. |
| `GET` | `/api/settings` | any logged-in account | `{force_tool_approval}`: what the administrator requires of everyone. |
| `GET` | `/api/admin/invites` | `invites.manage` | Open (unused, unexpired) invites, without codes. |
| `DELETE` | `/api/admin/invites/{id}` | `invites.manage` | `204`; the code stops working. `409` if already used. |
| `GET` | `/api/admin/summary` | `any administrative permission; unrelated counts are null` | `{accounts, unverified, disabled, open_invites, roles}`: counts for the Admin overview tiles. |
| `GET` | `/api/admin/accounts` | `accounts.view (also accounts.manage/accounts.delete/roles.assign)` | `[{id, username, email, email_verified, is_active, is_protected, created_at, roles: [{id, name}]}]`. Optional `?q=` (username/email substring, case-insensitive) and `?status=all\|unverified\|disabled`; `422` for any other status. |
| `PATCH` | `/api/admin/accounts/{id}` | `accounts.manage` | Any of `{username, email, is_active}` -> the account. Disabling ends its sessions. `409` taken name/email, protected account, or disabling yourself. |
| `DELETE` | `/api/admin/accounts/{id}` | `accounts.delete` | `204`. `409` for the protected account or yourself. |
| `PUT` `DELETE` | `/api/admin/accounts/{id}/roles/{role_id}` | `roles.assign` | Assign / remove a role -> the account. `409` removing from the protected account, or removing your own last role management/assignment access. |
| `POST` | `/api/admin/accounts/{id}/send-verification` | `accounts.manage` | `{sent: true}`; `409` already verified, `503` SMTP failed. |
| `GET` | `/api/admin/roles` | `roles.view (also roles.manage/roles.assign)` | `[{id, name, description, is_protected, permissions, account_count}]` |
| `POST` | `/api/admin/roles` | `roles.manage` | `{name, description?}` -> `201` role. `409` name taken (case-insensitive). |
| `PATCH` | `/api/admin/roles/{id}` | `roles.manage` | Any of `{name, description, permissions}` (`""` clears the description) -> the role. `permissions` replaces the full permission set; omitted leaves it unchanged. Details and permissions save atomically. Administrator can't be renamed or lose permissions; delegated authority and own admin access remain enforced. |
| `DELETE` | `/api/admin/roles/{id}` | `roles.manage` | `204`. `409` for Administrator, or if it's your only source of role management/assignment access. |
| `PUT` `DELETE` | `/api/admin/roles/{id}/permissions/{name}` | `roles.manage` | Grant / revoke -> the role. `404` unknown permission; `409` changing Administrator or revoking your own last role management/assignment access. |
| `GET` | `/api/admin/permissions` | `roles.view (also roles.manage/roles.assign)` | `[{name, description}]` - defined in code (`services/permissions.py`), not editable. |
| `GET` | `/api/chats` | `chat.use` | This account's chats, newest first: `[{id, title, agent_id, message_count, folder_id, pinned, created_at, updated_at}]` (no messages; `folder_id` is null for a chat in no folder). |
| `GET` | `/api/chats/search?q=` | `chat.use` | `q` 2-100 characters. Chats whose title or message text contains `q` (case-insensitive, literal; attached files' text is not searched), newest first, at most 50: `[{id, title, folder_id, updated_at, title_match: {start, length}\|null, snippet: {text, start, length}\|null, message_index, message_matches}]`. The snippet is one line around the first matching message. |
| `GET` | `/api/chats/{id}` | `chat.use` | One chat with `messages`. `404` if missing or another account's. |
| `PUT` | `/api/chats/{id}` | `chat.use` | `{title, agent_id, messages: [{role, content}]}` creates or replaces the chat. `413` over 2 MB or 1000 chats. |
| `PATCH` | `/api/chats/{id}` | `chat.use` | `{title?, folder_id?, pinned?}` (at least one) -> the chat row. `folder_id: null` takes the chat out of its folder. `404` unknown chat or a folder that is not this account's. Allowed while an answer is being written; filing and pinning do not change `updated_at`. |
| `DELETE` | `/api/chats/{id}`, `/api/chats` | `chat.use` | `204`; one chat, or all of this account's. |
| `POST` | `/api/chats/import` | `chat.use` | `{chats: [{id, title, agent_id, messages, created_at, updated_at}]}` (times in ms) -> `{imported, skipped}`. Existing ids are skipped, never replaced. |
| `POST` | `/api/chats/{id}/turns` | `chat.use` | `{question, agent_id?, caveman?, enabled_extensions?, disabled_tools?, title?, truncate_to?, ask_before_tools?, allowed_tools?, can_ask?}` -> `202 {chat, sequence}`. `enabled_extensions`: extension ids whose tools the agent may use (none by default). `disabled_tools`: mcp_server tool names (at most 500) of the built-in capabilities the account switched off for its own chats; the agent neither offers nor runs them, and the turn fails with an error if the agent is too old to leave them out. `truncate_to` (regenerate / edit): index of the typed question this one replaces; it and everything after it are dropped first (`422` unless that message is a question the user typed, `404` for an unknown chat). `ask_before_tools`: the agent asks before each tool runs, except `allowed_tools` (names, at most 200; the tools the user allowed for this chat); see `/approvals` below. `can_ask: true` lets the agent ask clickable questions; clients that cannot show them, such as `chat_cli`, leave it out. Older agents that do not report `user_questions: true` simply never get the question tool. `agent_id` is accepted but ignored: every turn goes to the entry agent (`GET /api/agent`). Saves the question (creating the chat) and starts the answer **in ember_api**: it finishes, is saved and counts toward the usage limits even if the browser leaves. `503` no entry agent is registered, `409` already answering, `429` usage limit or 3 answers already running. |
| `GET` | `/api/chats/{id}/events?after=N` | `chat.use` | Server-Sent Events of the chat's running (or just finished) answer: a `snapshot` of the text and tool steps so far when joining late, then `token` / `step_*` / `summarizing` / `question_request` / `question_resolved` events and, when the entry agent delegates, `agent_start` / `agent_end` (a specialist begins or finishes; keys `agent_id`, `agent_label`, `delegated_by`, `question` cut to 500 characters, `step_id`, `ok`, `at`) and `agent_token` (the specialist's streamed `text`, chunks cut to 4,000 characters; never saved with the answer). The `snapshot` carries pending `questions: [{id, questions}]` so a reload restores them; `question_request` carries `{id, questions}` and `question_resolved` carries `{id, outcome}` (answered, skipped, timeout or cancelled). ai_agent-only `keepalive` events are dropped. It also carries `active_agents: [{agent_id, label, since, step_id}]`, the delegated agents working now, outermost first (the entry agent itself is not listed; the browser adds it); it is cleared when the turn ends. Its `steps` carry their `id` (live viewers only; the id is not saved) and `agent_id` / `agent_label`. Then last `final` `{message, cancelled}` or `error`. `404` when there's nothing to watch. The saved answer carries `model`, `total_tokens`, `input_tokens`, `output_tokens`, `duration_s` (the whole turn, seconds), `context_tokens` / `context_window` when ai_agent reported them, and `steps: [{tool, label, arguments, ok, result, agent_id?, agent_label?}]` (`agent_id` / `agent_label` only on steps a delegated agent ran; results cut to 4,000 characters, at most 50 steps), and, when the answer ran more than one agent (its own plus delegated ones), `agent_usage: [{agent, agent_label?, provider_id?, gateway?, model?, input_tokens?, output_tokens?, total_tokens, started_at?, finished_at?}]` (times ISO-8601 UTC with `Z`) (at most 20; an answer from one agent has none). Every answer also carries `agent`, the id of the ember agent that wrote it (older answers lack it). |
| `POST` | `/api/chats/{id}/approvals` | `chat.use` | `{step_id, decision: allow \| always \| deny}` answers a tool the running answer waits to run (the `id` of an `approval_request` event) -> `{decided: true}`. `404` no answer running, `409` nothing waiting for that step (unknown or already answered), `502` agent unreachable. Only the chat's own account can; logged as `tool.approval`. |
| `POST` | `/api/chats/{id}/questions` | `chat.use` | Answers or skips the clickable questions the running answer waits on (`question_request` event): `{step_id, skipped?, answers?: [{selected, other}]}` -> `{answered: true}`. `404` no answer running, `409` nothing waiting, `422` invalid answer, `502` agent unreachable. |
| `POST` | `/api/chats/{id}/cancel` | `chat.use` | `{cancelled}`; ai_agent stops at its next round, keeping what streamed. |
| `POST` | `/api/chats/{id}/summarize` | `chat.use` | `{agent_id?}` (accepted but ignored; the entry agent summarizes) -> the chat, its history replaced by a `summary` message plus a `log_attachment` (raw messages, never sent to the agent again). `503` no entry agent is registered, `502` if the agent couldn't; nothing changes then. |
| `GET` | `/api/chats/{id}/suggestion` | `chat.use` | The message the user will probably type next, `{text}` (null for none). One small model call per answer, cached, counted in usage as kind `suggestion`; off when the account's `prompt_suggestions` is off. |
| `POST` | `/api/chats/{id}/clear` | `chat.use` | -> the chat, restarted: everything kept as one `log_attachment`. |
| `POST` | `/api/chats/{id}/branch` | `chat.use` | `{upto}` -> `201` a new chat (server-made id, title `Branch of <title>`, same agent) holding the messages up to and including message `upto`, which must be one of the assistant's answers (`422` for a question, summary, raw log or command result, or an index past the end). The original is untouched and may still be answering. `404` unknown chat, `413` at the chat limit. |
| `POST` | `/api/chats/{id}/messages` | `chat.use` | `{title, messages}` appends (slash-command calls and results), creating the chat if needed. |
| `GET` | `/api/chat-folders` | `chat.use` | `[{id, name, position, chat_count}]` in display order. |
| `POST` | `/api/chat-folders` | `chat.use` | `{name}` (1 to 60 characters, trimmed) -> `201` folder. `409` duplicate name (ignoring case) or 30 folders already. Logged as `chat_folder.create`. |
| `PATCH` | `/api/chat-folders/{id}` | `chat.use` | `{name?, position?}` (at least one), or `{direction: "up"|"down"}` on its own. Direction moves one place and saves all affected positions in one transaction; moving past an end is a no-op. `404` unknown, `409` duplicate name. Logged as `chat_folder.rename` for renames and `chat_folder.move` for moves. |
| `DELETE` | `/api/chat-folders/{id}` | `chat.use` | Deletes the folder **and every chat in it**, with their share links. `404` unknown, `409` while a chat in it is writing an answer. Logged as `chat_folder.delete`. |
| `GET` | `/api/templates` | `chat.use` | This account's saved prompts, most recently edited first: `[{id, name, body, created_at, updated_at}]`. |
| `POST` | `/api/templates` | `chat.use` | `{name, body}` -> `201` the template. Name up to 60 characters (trimmed), body up to 10,000, at most 100 per account. `409` for a name the account already has (ignoring case) or the limit, `422` for a blank or too-long field. |
| `PUT` | `/api/templates/{id}` | `chat.use` | `{name, body}` replaces one. `404` if missing or another account's, `409` name taken. |
| `DELETE` | `/api/templates/{id}` | `chat.use` | `204`; `404` if missing or another account's. |
| `GET` | `/api/nav-preferences` | any logged-in account | How this account arranges its nav rail: `{order, pinned, hidden}`, lists of page ids (route paths such as `/agents`). All empty means the default arrangement. |
| `PUT` | `/api/nav-preferences` | any logged-in account | Replaces it with the same shape. At most 50 ids per list, each 1-64 characters (`422` otherwise). Repeats are dropped; `pinned` and `hidden` keep only ids in `order`, and a hidden page is never pinned. ember_api does not know the page list, so unknown ids are kept. Returns what was stored. |
| `DELETE` | `/api/nav-preferences` | any logged-in account | Back to the default arrangement. `204`, also when nothing was saved. |
| `GET` | `/api/account-capabilities` | any logged-in account | Which built-in capabilities and server-listed extensions this account has added: `{capabilities, extensions, disabled_tools}`. A new account has nothing added. `disabled_tools` is the sorted tool names of every mcp_server capability not added, read from mcp_server's `/capabilities` (`502` if it is unreachable). |
| `PUT` | `/api/account-capabilities/{kind}/{key}` | any logged-in account | `{enabled: bool}` adds or removes one item (`kind`: `capability` or `extension`; `key` 1-64 characters of `A-Za-z0-9_.-`, else `422`). Same reply as `GET`. Repeating a change is a no-op; at most 200 items per account (`409`). Logged as `account.capability_enable` / `_disable` (or `extension`). Removing an extension through `DELETE /api/extensions/{id}` clears it from every account. |
| `GET` | `/api/user-extensions` | `chat.use` | This account's own MCP servers ("private extensions"): `[{id, label, description, url, header_names, enabled, status, error, tools}]`. `id` is a slug of the label, unique per account. `status` is `connected`, `error` or `unknown`, from `ai_agent`'s `probe_extension`, cached for 60 seconds; a disabled extension is not probed and reports `unknown`. Header **values** are never returned, only their names. |
| `POST` | `/api/user-extensions` | `chat.use` | `{label, url, description?, headers?}` -> `201` the extension, probed once. Saved even if it cannot be reached right now. `422` with a message for a bad address (http or https only, no username or password) or header (up to 20; name `A-Za-z0-9-`; value 1-2000 characters, no control characters; `Host`, `Content-Length`, `Transfer-Encoding`, `Connection`, `Upgrade`, `TE`, `Trailer`, `Proxy-Authorization` and `Cookie` are refused); `409` at 20 extensions. |
| `PATCH` | `/api/user-extensions/{id}` | `chat.use` | Any of `{label, description, url, headers, enabled}` -> the extension. `headers`, when present, replaces all of them (send it only when the user retyped them). A URL with a new host and no `headers` clears the saved headers, so a token is never sent to another host unasked. `404` for another account's id, `422` for an empty body. |
| `DELETE` | `/api/user-extensions/{id}` | `chat.use` | `204`; `404` for another account's id. |
| `POST` | `/api/chats/{id}/shares` | `chat.use + chat.share` | `{expires_in_days: 1 \| 7 \| 30 \| null}` (default 7; null: never) -> `201 {id, chat_id, title, message_count, created_at, expires_at, token}`. Freezes a sanitized copy of the chat behind a new link; **`token` is in this response only** (ember_api stores its SHA-256). `404` unknown chat, `409` at 50 active links, `422` bad expiry or nothing shareable. Logged as `share.create`. |
| `GET` | `/api/shares?chat_id=` | `chat.use` | This account's active links, newest first: `[{id, chat_id, title, message_count, created_at, expires_at}]`. Never a token. |
| `DELETE` | `/api/shares/{id}` | `chat.use` | `204`, the link stops working at once; `404` if missing or another account's. Logged as `share.revoke`. |
| `GET` | `/api/shared/{token}` | **none** | `{title, messages: [{role, content}], created_at, expires_at}` - the read-only snapshot. Unknown, malformed, revoked and expired tokens all get the same `404`. `429` past 60 requests a minute from one address. `Cache-Control: no-store`, `X-Robots-Tag: noindex`. |
| `GET` | `/api/usage?days=30&since=YYYY-MM-DD&group_by=agent&agent=&provider=` | `chat.use` | `{six_hour, weekly: {used, limit, reset_at}, report: {days, since, total_tokens, input_tokens, output_tokens, summary_tokens, turns, chats, by_agent, group_by, groups: [{key, tokens, input_tokens, output_tokens, turns}], daily, hourly}}`. `group_by`: `agent` (default), `provider`, `gateway` or `model`; `groups` is the report grouped that way, biggest first (a missing value is `unknown`). `agent` and `provider` (optional) keep only that agent's / provider's rows. `hourly`: 24 token counts by UTC hour of day. `since` (optional, a UTC day) replaces `days` and starts the report at that day's midnight ("this month" is the 1st); `days` in the report is then the span covered. `422` for a future `since`, one older than 366 days, or a malformed one. |
| `GET` | `/api/usage/records?days=30&since=YYYY-MM-DD&agent=&provider=&limit=100` | `chat.use` | This account's usage rows in the period, newest first: `[{id, turn_id, kind, chat_id, agent, agent_id, provider_id, gateway, model, input_tokens, output_tokens, total_tokens, started_at, finished_at, delegated_by, created_at}]` (UTC times; same `days` / `since` rules and filters). `limit` 1-500, default 100. |
| `GET` | `/api/admin/usage?days=30&since=YYYY-MM-DD` | `admin.manage` | Every account's tokens and answers in the period (same `days` / `since` rules). |
| `GET` | `/api/commands` | `tools.use` | mcp_server's slash commands: `[{capability, name, description, tool_name}]`. |
| `GET` | `/api/commands/help`, `/api/commands/help/{capability}?target=&command=` | `tools.use` | mcp_server's capability help (what `/help` shows). |
| `GET` | `/api/commands/options?template=...&arg.<name>=...` | `tools.use` | A command-form select's options: `[{value, label, extra}]` from the mcp_server path `template`, which must be an `options_url` some tool's schema declares (its `{name}` placeholders filled from `arg.<name>`). `400` undeclared template or missing arg, `502` mcp_server down. |
| `POST` | `/api/uploads` | `files.upload` | `{filename, data}` (base64, up to 15 MB) -> `201 {path}`: stored by mcp_server's `/upload` (which picks the allowed file types) for a command's file-path parameter. `400` refused type. |
| `GET` | `/api/server/download?path=` | `tools.use` | A file a tool offered with a `[[DOWNLOAD ...]]` marker, streamed from mcp_server's `/download?path=` (identity and internal token added). Always sent as an attachment of type `application/octet-stream`, named by mcp_server's `Content-Disposition` filename (cleaned to a bare name) or else the last part of `path`, so a file never runs as a page on ember's origin. `path` is 1 to 1000 characters without control characters (`422`). `404` unknown file, `400` refused, `502` mcp_server unreachable or failing. mcp_server's `/download` takes an opaque id (see "Downloads" under Security). |
| `GET` | `/api/capabilities` | `tools.view (also capabilities.manage)` | mcp_server's built-in capabilities: `[{name, label, enabled, tools, resources, has_gui}]`. |
| `GET` | `/api/capabilities/{name}/gui` | `tools.view (also capabilities.manage)` | The capability's page layout (`{version, title, description, sections}`) as mcp_server validated it; `404` when it has no page. |
| `PATCH` | `/api/capabilities/{name}` | `capabilities.manage` | `{enabled}` turns a capability on/off for every mcp_server client. |
| `GET` | `/api/extensions` | `chat.use` or `tools.use` | mcp_server's extensions: `[{id, label, description, status, error, tools, web_url}]`. `web_url` is the extension's own web app (an http(s) address from mcp_server's config, or `null`); ember_web links to it. |
| `POST` | `/api/extensions` | `extensions.manage` | `{label, url, description?}` (http/https URL) -> `201` the extension; mcp_server connects to it and saves it (an unreachable one is still added, `status: "error"`). |
| `DELETE` | `/api/extensions/{id}` | `extensions.manage` | `204`; `404` unknown id. |
| `GET` | `/api/logs` | any `logs.*` | `{kinds, accounts}`: the log kinds this account may read and every account to filter by. |
| `GET` | `/api/logs/analytics?range=24h\|7d\|30d\|90d` | any `logs.*` | Counts for the Analytics page, only for the kinds this account may read (default `7d`): `{period, bucket (hour\|day), kinds, totals {kind: {current, previous}}, series [{bucket, counts}] (zero-filled), top_sources {kind: [{source, count}]}, accounts {kind: [{account_id, username, count}]}, heatmap [{weekday, hour, count}]}`. Top lists hold 10; `account_id` null is the server, `username` null a deleted account; heatmap is UTC, weekday 0 = Sunday. `422` bad range. |
| `GET` | `/api/logs/{kind}?actor=server\|<account id>` | `logs.view` (action), `logs.errors.view` (error), `logs.chat.view` (chat_trace) | The 200 newest entries: `[{id, kind, account_id, source, message, details, created_at}]`. |
| `POST` | `/api/attachments/text` | `files.upload` | `{filename, data}` (base64, up to 15 MB) -> `{filename, text, char_count, truncated}`: text from a text/code, `.pdf`, `.docx` or `.xlsx` file, at most 20,000 characters. The file isn't kept. `400` with a readable reason when it can't be read. |
| `POST` | `/api/attachments/pdf` | `files.upload` | `{filename, data}` (base64, up to 15 MB) -> `{filename, file_id, pages, kind, expires_at, text, char_count, truncated}`. Stores PDF/image originals via mcp_server in PDFMerger for the signed-in account. Text preview is optional, including for scanned PDFs. Requires the configured `pdf_merger` HTTP extension with requester forwarding and its internal token. |
| `GET` | `/api/traffic/analytics?range=24h\|7d\|30d\|90d` | `traffic.view` | Network traffic for the Analytics Traffic tab (default `7d`): `{period, bucket (hour\|day), latency_cap_ms, totals {requests, error_rate, p95_ms, upstream_failures: {current, previous}}, series [{bucket, requests {2xx,3xx,4xx,5xx}, p50_ms, p95_ms}] (zero-filled), routes {busiest, slowest: [{name, count, error_rate, p95_ms}]}, upstream [{target, calls, failures, failure_rate, p95_ms, tools [{name, calls, failures, p95_ms}]}]}`. Counts come from `traffic_buckets` (written by `TrafficMiddleware` and the upstream timing, flushed every 30 s); names are route templates, never raw paths. Latency is kept as bands (50/100/250/500/1000/2500/5000 ms), so a percentile is its band's upper bound, and one in the slowest band shows as `latency_cap_ms` (meaning "at least"). `error_rate` is 5xx over all requests (`null` with no requests); `slowest` needs 5 requests per route; top lists hold 10. `422` bad range. |
| `GET` | `/api/config-issues` | `config.issues.view` | `[{file, key, message}]`: problems in `config_app.json`, the agent registry and the secret files. Never includes secret values. |
| `GET` | `/api/agent` | `chat.use` | The agent every question goes to, as `{id, label}` - no URL. `503` "No agent is running" when none is registered. |
| `GET` | `/api/agents` | `chat.use` | Every agent, for the Agents page: `[{id, label, entry, orchestrator, focus, status, provider, gateway, model}]` - no URL. `provider`, `gateway` and `model` come from the agent's `llm` block in the definitions and are `null` when not set. `status` is `running` (in ai_agent's registry), `offline` (defined in `agents/` but not running) or `disabled` (`enabled: false`); running first, the entry agent leading its group. Definitions come from `agent_definitions.json` beside the registry file, or `defined` in `GET /registry`; without them only running agents are listed. `[]` when none. |
| `GET` | `/api/admin/agents/gateways` | `agents.manage` | `{providers: {<provider>: [{id, label, model, tiers}]}}`: the providers and gateways from ai_agent's `gateways/<provider>/<gateway>.json` files (no keys), for the agent form's pickers. |
| `GET` `POST` | `/api/admin/agents` | `agents.manage` | `GET` -> `{agents: [{id, ...agent file}]}` (a broken file carries `error`). `POST {id, config}` creates `agents/<id>.json` -> `201`. `config` is the agent file (`label`, `port`, `url` (the address the agent registers under; empty = the host and port it listens on), `enabled`, `entry`, `llm`, `persona`, `instructions`, `focus`, `tools`, `orchestrator`); ai_agent validates it: `400` invalid or unknown gateway, `409` id or enabled port already used or a second entry agent. `502` when no agent is running or ai_agent does not answer (the call goes to the entry agent). Logged as `agents.create`. |
| `PUT` `DELETE` | `/api/admin/agents/{id}` | `agents.manage` | `PUT {config}` replaces the file (`404` unknown, same `400`/`409` rules); `DELETE` removes it (`409` for the entry agent, `404` unknown) -> `204`. ai_agent's supervisor starts, restarts or stops the agent within a few seconds. Logged as `agents.update` / `agents.delete`. |
| `GET` `PUT` | `/api/admin/agent-prompts` | `agents.manage` | The prompt texts every agent shares (`app_name`, `app_description`, `identity_template`, `default_instructions`, `roster_intro`, `caveman_instructions`). `GET` -> `{values, defaults, overridden}`. `PUT {name: text \| null}` changes some; `null` or blank resets one to its default; `400` for an unknown name, a text over 8,000 characters or an `identity_template` with a placeholder other than `{app_name}`, `{app_description}`, `{role}`. ai_agent restarts every agent to apply it. Logged as `agents.prompts`. |
| `POST` | `/api/admin/agent-prompt-preview` | `agents.manage` | `{id, config, caveman?}` -> `{prompt}`: the system prompt the draft agent file would get (an orchestrator's includes its roster). Only the draft itself is validated (`400`). |
| `GET` | `/api/emberlings/catalog`, `/api/emberlings/profile`, `/api/emberlings/encounters/{id}`, `/api/emberlings/battles/{id}`, `/api/emberlings/sparks/{spark_id}/presets/{slot}`, `/api/emberlings/sparks/{spark_id}/personalities?limit=&cursor=` | `emberlings.play` | The Emberlings game (`apps/mini_games`, `emberlings_url` in config), passed through with mini_games' own JSON. `GET /profile` is `404` until a starter is chosen. Ids are 1 to 64 of `A-Za-z0-9_-` and a slot is 1 to 5, else `400`. |
| `POST` | `/api/emberlings/profile` `{starter_spark_id}`, `/encounters`, `/encounters/{id}/decline`, `/battles` `{encounter_id, spark_id, preset_slot?, mode, emblem_limit?}`, `/battles/{id}/actions` `{round, revision, action}`, `/battles/{id}/emblem` `{round, revision, tier}`, `/battles/{id}/advance` `{round, revision}`, `/battles/{id}/mode` `{round, revision, mode, emblem_limit?}`, `/battles/{id}/forfeit`, `/shop/purchases` `{kind: "emblem", tier, quantity}` or `{kind: "copies", tier, spark_id}`, `/sparks/{spark_id}/sales`; `PUT` `/sparks/{spark_id}/presets/{slot}` `{instance_ids}` | `emberlings.play` | Every change needs an `Idempotency-Key` header of 1 to 200 characters (`400` without; a retry with the same key returns the first result). Bodies reject unknown fields (`400`). mini_games' `400`/`404`/`409` come back with its message as `detail`; mini_games down, failing or refusing the internal token is `502` "Emberlings is not available right now". The owner sent upstream is the account id, never the username; browser-sent identity headers are dropped. Logged: `emberlings.profile_create`, `battle_start`, `battle_forfeit`, `shop_buy`, `spark_sell` (round actions are not). |
| `GET` `POST` `DELETE` | `/api/mcp/agents/{agent_id}` | `chat.use` | MCP Streamable HTTP proxy to that agent. `404` if the id isn't in ai_agent's registry. |
| `GET` `POST` `DELETE` | `/api/mcp/server` | `tools.use` | MCP Streamable HTTP proxy to mcp_server. |
| `GET` | `/api/health` | - | `{status: "ok"}` |

## Private extensions

A user can add an MCP server of their own (`/api/user-extensions`). Only that
account sees it and only its chats use it. `ember_api` stores it; `ai_agent`
makes every connection (it holds the address guard: public and private-LAN
addresses only, never loopback, link-local or cloud-metadata ones).

- **Headers are secrets.** They are stored as one Fernet token per extension,
  made with `EMBER_SECRETS_KEY` in `.env`. The key is generated and appended to
  `.env` on first start (a warning line, without the key, is logged once).
  Keep it with any backup of `.env`. If it is lost or replaced, the affected
  extensions show "Its headers can't be read" and are left out of turns until
  their headers are entered again; the others keep working. A value that is
  not a valid key stops startup with a one-line message. Needs the
  `cryptography` package.
- **Nothing leaks.** The API returns header names only. The activity log
  (`account.user_extension_add`, `_edit`, `_remove`) names the label and the
  URL's host, never the full URL (it may carry a token) or a header value.
- **On a turn**, the account's enabled extensions are read from the database
  and sent to `ai_agent` as `private_extensions` (the browser cannot name one).
  An `ai_agent` that does not report `private_extensions` in `status` is
  refused: the turn fails with a message rather than quietly running without
  them. Their tools are named `u_<id>__<tool>` and always ask for approval
  (the agent raises the usual `approval_request`).
- **Notices.** An extension the agent could not use, or whose headers could not
  be read, is reported to the watcher as a live turn event
  `{type: "notice", notices: [{id, label, error}]}`. It is not saved in the chat.

## Security model

- **Sessions:** a random 256-bit token in an `HttpOnly`, `SameSite=Strict`
  cookie (`Secure` when `cookie_secure` is on). The database stores only its
  SHA-256, with an expiry (`session_hours`); logout deletes the row.
- **Passwords:** werkzeug hashes, checked on a worker thread so hashing
  never blocks the event loop. Unknown usernames are checked against a dummy
  hash so they take as long as a wrong password.
- **Audit:** every login attempt is stored in `login_attempts` (IP, matched
  account if any, success). The activity log (`log_entries`, Logs page)
  records logins, logouts, registration, email verification, account
  changes, every admin action and capability/extension changes; errors and
  one line per answered chat turn go there too. Entries older than 90 days
  are deleted on startup; a deleted account's entries stay.
- **Permissions:** `chat.use`, `chat.share`, `tools.view`, `tools.execute`, `files.upload`, `files.download`,
  `accounts.view`, `accounts.manage`, `accounts.delete`, `roles.view`, `roles.manage`, `roles.assign`,
  `invites.manage`, `settings.manage`, `capabilities.manage`, `usage.all.view`,
  `extensions.personal.manage`, `extensions.manage`,
  `logs.view`, `logs.errors.view`, `logs.chat.view`, `config.issues.view`,
  `traffic.view` (`src/services/permissions.py`). The Administrator role always holds all
  of them (new ones are added to it on startup). New registrations get `default_role` (config, default `Member`:
  `chat.use`, `chat.share`, `tools.view`, `tools.execute`,
  `extensions.personal.manage`, `files.upload`, `files.download`) - unlike chat_app, where new accounts get no
  role. An account with an unverified email holds no permissions at all, unless
  `require_email_verification` is `false` in config.
- **Invites and verification codes:** 10 random characters, stored as
  SHA-256, single use. Invites expire after 7 days, verification codes after
  15 minutes. Registration
  checks the invite before revealing whether a username is taken, and a
  failed registration leaves the invite unused.
- **Email:** invite and verification templates are delivered through MCP Server's
  Email capability at `mcp_server_url`, with the existing internal token and service
  identity `ember`. Configure SMTP only in MCP's `configs/config_email.json` and
  enable **Email** in capability controls (refresh first on existing deployments).
  Ember's old `SMTP_*` / `MAIL_FROM_ADDRESS` variables are no longer used.
  Original subjects and template wording are preserved; MCP adds the notice once.
  If MCP is unreachable, Email is disabled, or sending fails, registration still succeeds and
  `/verify-email/resend` retries; an invite's code is still returned to the
  admin. Sends are not automatically retried because a lost response can follow
  SMTP acceptance. Check delivery status before manually retrying. Config issues
  no longer asks for local SMTP settings; it does not assert upstream mail readiness.

- **MCP proxy:** the browser only ever talks to ember_api. Upstream URLs come
  from server-side config (`mcp_server_url`) and ai_agent's own registry file
  (`agents_registry_path`), never from the request. Only
  `content-type`, `accept`, `mcp-session-id`, `mcp-protocol-version` and
  `last-event-id` are forwarded; the browser's cookie and any
  `X-Requester-*` / `X-Internal-Token` it sends are dropped, and ember_api
  adds `X-Requester-Username` / `X-Requester-Email` from the session (plus
  `X-Internal-Token` from `INTERNAL_API_TOKEN` in `.env`, if set).
  Responses, including SSE, are relayed chunk by chunk; the upstream request
  closes when the browser disconnects.
- **What may pass** (`src/services/mcp_policy.py`, bodies up to 1 MB): the
  MCP handshake (`initialize`, `ping`, a few notifications) for everyone;
  on agents only `tools/call` of `status` - chat turns run inside ember_api
  (`/api/chats/{id}/turns`), so the browser can't bypass the usage limits or
  skip saving an answer; on mcp_server `tools/list`, any `tools/call` and
  `resources/list` / `resources/templates/list` / `resources/read`.
  Anything else gets a JSON-RPC error (`403`) and never reaches the server.

ai_agent and mcp_server require that token on `/mcp` once they have one
configured (use the same value in all four projects' `.env`
files); without a token they're protected only by listening on
`127.0.0.1`. ai_agent passes the asking user on to the mcp_server tools it
calls (in each call's `_meta`), so mcp_server sees who asked either way.

- **Chat turns** (`services/turns.py`, `services/agent_gateway.py`):
  ember_api calls ai_agent's `ask` itself over MCP (the `mcp` SDK), with the
  account's identity headers, and saves the answer. Watchers only subscribe;
  the event buffer stays small because streamed text is kept as one string
  and late joiners get it as a snapshot. At most 3 running answers per
  account. On shutdown a running answer is saved as interrupted.
- **Asking before tools** (`ask_before_tools`, `services/turns.py`,
  `POST /api/chats/{id}/approvals`): the turn calls the agent's `ask` with
  `approval_mode: "ask"`. The agent's `approval_request` / `approval_resolved`
  events are relayed to watchers, and the requests still waiting are kept in
  the turn and sent in the late-joiner snapshot (`approvals`), so a reloaded
  page still shows the question. An answer goes to the agent's `decide` tool;
  the agent's own `approval_resolved` event then clears it. It fails closed:
  `AgentGateway.ask` checks the agent's `status` for `tool_approval` first and
  refuses an agent that would ignore the option, so no tool can run unasked.
  **Required for everyone** (`force_tool_approval`, stored in `app_settings`,
  switched by an admin with `PUT /api/admin/settings/force_tool_approval`):
  every turn then asks, whatever `ask_before_tools` says; `allowed_tools` from
  the browser is dropped; and an `always` answer is passed to the agent as
  `allow`, so a tool never stops asking. Typed commands (`/tool`) call
  mcp_server directly with no agent and are not affected.
- **Regenerate / edit** (`truncate_to` on `POST /api/chats/{id}/turns`): the
  server cuts the history before a typed question and asks again, so the
  browser never rewrites saved history itself.
- **Branching** (`ChatService.branch`, `POST /api/chats/{id}/branch`): a copy
  of the saved messages up to one answer becomes a new chat with a
  server-made id. Only saved messages are read, so a chat that is still
  answering can be branched.
- **Chat folders and pins** (`services/folder_service.py`, `routes/chat_folders.py`): folders are one level deep per account. A branch stays in its source's folder and is not pinned. The schema change is migration `0005`.
- **Share links** (`services/share_service.py`, `routes/shares.py`): the one
  feature that lets someone read a chat without logging in, so its rules live
  on the server. A link's token is 256 random bits and only its SHA-256 is
  stored (shown once, at creation). What is shared is a frozen copy taken
  then, cut to the questions the user typed and the assistant's plain
  answers: tool steps and results, usage data, summaries, raw logs,
  slash-command results, error texts, download markers and the text of
  attached files are left out. Links expire (1, 7 or 30 days, or never; expired
  ones are purged at startup), can be revoked, and die with their chat
  (deleting one chat or all of them) or account. Unknown, revoked and expired
  links answer alike, and `GET /api/shared/{token}` is limited per address
  (`PublicReadLimiter`, in memory).
- **Chat search** (`services/chat_search.py`, `GET /api/chats/search`): a
  literal, case-insensitive scan of the account's titles and messages,
  streamed and stopped at 50 hits; ASCII queries are pre-filtered in SQL.
- **Usage limits** (`services/usage_service.py`, config `usage`): tokens of
  every answer and summary are recorded per agent; a question over the
  6-hour or weekly cap is refused with `429` before anything is saved.
- **Extensions:** the agent only gets tools of the extensions the user
  switched on (`enabled_extensions`, validated as ids); adding one makes
  mcp_server connect to any URL, so that is admin-only.
- **Tools switched off by the user:** `disabled_tools` (validated as tool
  names) is passed to the agent as it is; ember_web works the names out from
  the built-in capabilities the account switched off on the Capabilities page.
- **Errors:** an unhandled exception answers a generic `500` and is written
  to the error log with its traceback (under the account, when logged in).
- **Summaries** (`services/summarization.py`, port of chat_app's): manual
  (Summarize) or automatic before a question once the chat's context is 60%
  full. Written only when a usable summary came back.
- **Chat history:** every query is filtered by the logged-in account, and
  chat ids are unique per account, so another user's chat looks exactly like
  a missing one (`404`). Limits: 2 MB per chat, 1000 chats per account.
- **Body size:** requests over 32 MB are refused with `413` before they are
  read (`src/body_limit.py`).
- **Login rate limiting** (`services/rate_limiter.py`, config
  `security.rate_limit`): after 5 failed logins in 15 minutes from one IP or
  for one account, login answers `429` with `Retry-After` until 15 minutes
  after the last failure - checked before the password, so no hashing work
  and no password answer during a lockout. Refused tries aren't recorded.
- **Client IP** (`src/security.py`): the socket address, or the last
  `X-Forwarded-For` hop when the peer is a `trusted_proxies` entry (Vite's
  loopback proxy, which sets it). Used for the audit, rate limit and IP filter.
- **IP filter:** optional allow/deny lists, `403` on every route.
- **Headers:** nosniff, `X-Frame-Options: DENY`, `Referrer-Policy:
  no-referrer`, `default-src 'none'` CSP on every response; HSTS when
  `hsts_max_age` is set. ember_web's `vite preview` sets its own CSP.

- **Devices** (`services/device_service.py`, config `security.fingerprint`,
  port of chat_app's fingerprinting): a hash of User-Agent, Accept-Language
  and the /24 (IPv4) or /64 (IPv6) network. A login from one the account
  never used is allowed and written to the activity log
  (`auth.new_device`); users see and forget theirs on the Account page.
- **Command form:** option lists come only from `options_url`s a tool
  declares, as plain paths on mcp_server (never a host); uploads go through
  mcp_server's own `/upload` checks.

- **Hardening (security review of 2026-10-03):**
  - *Verification codes* are voided when the email changes (a code sent to the
    old address cannot verify the new one) and verification emails are limited
    to one per 30 seconds and five per hour per account (`429` with
    `Retry-After`), on resend and on email change.
  - *Wrong passwords* typed into "change password" or "change email" count
    towards the login lockout, so a stolen session cannot guess the password
    there.
  - *Request bodies* are capped at 1 MB everywhere except `/api/chats`,
    `/api/attachments` and `/api/uploads` (32 MB), so the pre-login routes
    cannot be fed huge bodies.
  - *Attachments* are refused when an office file claims to unpack to more than
    100 MB or 5,000 entries, and reading stops at 500 PDF pages, 200,000 sheet
    rows, or as soon as 20,000 characters are read.
  - *Usernames and emails* are unique ignoring case at registration.
  - A command-form option value of `.` or `..` is refused. Old `login_attempts`
    rows (over 30 days) are deleted at startup.
  - *Downloads:* `GET /api/server/download?path=` forwards `path` to mcp_server
    as it is. It must therefore be an **opaque id that mcp_server checks against
    the requesting account**, never a file path mcp_server would serve to anyone
    who names it. mcp_server's `/download` does exactly that: ids are random,
    held in memory for 10 minutes, bound to the asking username (sent as
    `X-Requester-Username`), and an unknown, expired or someone else's id are
    the same `404`. Today `/server logs` is the one tool that offers a file.
  - Known and left as is: five wrong logins lock that account (and address)
    out for the lockout time, so someone can lock a known username out on
    purpose; and any member with `tools.use` can run any tool (that is what the
    permission means; "ask before each tool" is opt-in per chat).
- **Backups:** the `backup` block in `config_app.json` copies the database
  every 24 hours (default) into `data/backups` and keeps 14. See the config
  README. `python -m scripts.backup_db` makes one now. The Config issues page
  warns when backups are off, when `cookie_secure` is off on a host other
  machines can reach, when HSTS is off while cookies are secure, and when
  `INTERNAL_API_TOKEN` is empty.

## Changing the schema

The database schema is versioned with Alembic. At startup ember_api brings
the database to the newest revision (`migrations/versions/`):

- a new database gets every migration;
- a database made before migrations existed is marked as the baseline
  (`0001`) without being rebuilt;
- `usage_records` keeps `agent_id`, `provider_id`, `gateway`, `started_at`, `finished_at` and `delegated_by` for each agent's share of an answer (migration `0003`; older rows have them empty);
- a database that is behind gets the missing migrations, after a backup
  (`data/backups/`). SQLite cannot undo a half-finished migration, so the
  backup is the way back; if the backup fails, nothing is changed.

To change a table or add a column:

1. Edit the model in `src/models/`.
2. Stop ember_api, then run `python -m scripts.migrate_db revision "what changed"`.
   It writes a new file in `migrations/versions/`.
3. Read that file. Check it does what you meant (a new `NOT NULL` column on a
   table with rows needs a `server_default`). SQLite edits go through
   `op.batch_alter_table`, which the generator already uses.
4. Start ember_api, or run `python -m scripts.migrate_db upgrade`.
   `python -m scripts.migrate_db status` shows where the database is.

`tests/test_migrations.py` fails when a model differs from what the
migrations build, so a model edit without its migration is caught.

## Layout

```
configs/   config_app.json(.example)          host, port, db path, session/cookie settings
.env       BOOTSTRAP_ADMIN_*, INTERNAL_API_TOKEN (+ .env.example); secrets/ is the old layout, read once to build it
data/      ember_api.db (runtime, gitignored)
src/
  run.py, app.py, config.py, db.py, deps.py, json_only.py, security.py, body_limit.py
  models/     Account, AppSetting, Role, Permission, LoginAttempt, AuthSession, InviteCode, EmailVerificationCode, Chat,
              UsageRecord, LogEntry, KnownDevice, PromptTemplate, SharedChat
  services/   ChatAppImporter (chat_app_import), DatabaseBackup / BackupScheduler (backup_service), MigrationRunner (migrations), SettingsService (settings_service), AuthService, SessionService, OtpService, RegistrationService, EmailSender (MCP Email capability),
              AccountService, AdminService, AgentDirectory, AgentGateway, ChatService, ChatSearch, TemplateService, ShareService, PublicReadLimiter, TurnRegistry,
              UsageService, summarization, McpServerInfo, McpServerTools, mcp_session, LogWriter,
              text_extraction, config_validation, DeviceService, LoginRateLimiter, McpPolicy, McpProxy,
              permissions
  routes/     auth, account, admin, settings, chats, templates, shares, usage, mcp, server_info, logs,
              attachments, config_issues
  utils/      config_loader
scripts/   import_chat_app.py                   one-off move of chat_app's data (see "Moving from chat_app")
           backup_db.py                         back up the database now
           migrate_db.py                        schema status / upgrade / new migration (see "Changing the schema")
migrations/  Alembic environment and versions/ (0001_baseline.py)
tests/
```

### Permission split (migration 0010)

Startup backs up existing databases, then grants the equivalents of the old
`admin.manage`, `tools.use`, and `chat.use` permissions to each existing role.
This runs once: subsequent restarts preserve revoked grants. Legacy broad
permission rows remain only for rollback and are neither listed nor authorized.
The Administrator role receives all currently known permissions on startup.

Read-only permissions do not grant mutation access. Account and role management
permissions include the corresponding discovery routes needed to perform their
actions. Role assignment, role changes, and account edits/deletions cannot affect
permissions beyond the actor's own authority. Invitations currently have no role
picker; the inviter must hold every permission in the configured default role.

`chat.share` controls creating public links; owners can still list and revoke
existing links with `chat.use`. Personal extension listing and use remain under
`chat.use`; creating, editing, switching, or removing one also requires
`extensions.personal.manage`. File attachment extraction requires `files.upload`.

`tools.execute` applies to both direct MCP calls and agent calls, including shared
and private extensions and delegated agents. Without it, chat sends a server-owned
block-all filter; an older agent lacking `tool_filter_all` is refused before it
answers. Update/restart ai_agent together with ember_api. `tools.view` still allows
tool discovery and resource reads. File download permission gates Ember's server
file-transfer route; it does not prohibit copying chat text or tool results.

To roll back, deploy the previous code with the pre-migration backup. Alembic
downgrade to 0009 retains original broad grants and removes the new permission
rows, but does not undo role edits made after upgrading.
