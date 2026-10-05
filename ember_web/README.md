# ember_web

Browser chat frontend for this repo, built with Vue 3, TypeScript and Vite.
It talks only to [ember_api](../ember_api), its own backend, over the same
origin: ember_api owns the accounts and login sessions and proxies MCP to
`ai_agent` (chat) and `mcp_server` (tools). The browser never holds a server
URL, token or key.

## Features

- Log in, register with an invite code, verify your email (ember_api
  accounts - separate from chat_app's).
- Chat with the main agent, with live token streaming and the tools it runs.
  There is no agent picker: the header says "Talking to <agent>" and ember_api
  chooses the agent (`GET /api/agent`); the browser never sends an agent id.
  Each answer keeps a collapsed "Ran N tools" list (arguments and result per
  step), also after a reload. ember_api runs each answer: it
  keeps going and is saved even if the page closes; reopening the chat picks
  the live answer back up. Chats still being answered show a pulsing dot.
- When the main agent hands a question to another agent, a live line shows who
  is working ("Ember → Calculator", with a running clock for the innermost
  agent) until it finishes. In the tool list a step run by a delegated agent
  carries a badge with that agent's name, and the delegate step shows the text
  that agent has written so far while it works.
- Stop button (takes effect at the agent's next round).
- A running clock under the answer being written (`12.4 s`, then `1 min 03 s`),
  and beside "Running command ...". It counts from when you sent the question; for a
  chat you reopen while it is still answering it counts from the reopen.
- "Chime when done" (on by default, remembered per account): a short chime
  when an answer arrives while this tab is hidden or not focused. A stopped
  or failed answer does not chime, and neither does a chat you are not
  watching. Browsers may keep the chime silent until you have clicked on the page once.
- An empty chat shows a greeting (one of seven, picked once), a tip and, with
  `tools.use`, what you can run ("I can help you with: Files (/files), ...").
- Copy button on every answer, on your messages and on each code block.
- A usage chip under each answer (`Claude Agent · model · 12.4k tokens · 4.2 s · 3 tools`):
  the first part is the agent that wrote the answer, by its name (answers saved
  before ember_api kept it show the model only). Click it for input/output
  tokens, time, tools run and context use. Answers
  saved before ember_api stored the split and the time show less. An answer
  that delegated to other agents also lists each agent's model, input, output
  and total tokens there (older answers have no such list).
- Regenerate the last answer, or edit one of your questions and resend it
  (its attached files stay; the messages after it are dropped, with a
  confirm when that discards later exchanges). ember_api does the cut
  (`truncate_to`).
- Branch from any answer: the branch icon copies the chat up to and
  including that answer into a new chat ("Branch of <title>", same agent)
  and opens it, leaving the original as it is. Use it to try a different
  follow-up without losing the first one. The copy keeps tool steps and
  usage data; it does not record where it came from.
- Keyboard: `Esc` stops the running answer, `Ctrl/Cmd+K` focuses the input,
  `Ctrl/Cmd+Shift+O` starts a new chat. `Up` in an empty input brings back
  your last question, again `Up` the one before, `Down` goes forward and past
  the newest empties the box (a small note shows "Earlier question 3 of 12").
  Typing over a recalled question ends it; in a multi-line one the arrows
  move the caret until it reaches the first or last line. Slash commands you
  ran are in the list too.
- Slash commands: `/<capability> <command> key=value ...` runs an mcp_server
  tool directly (no AI), `/help` and `/<capability> help` show help; the input
  suggests commands as you type (needs `tools.use`). Tools of the extensions
  you switched on are commands too: `/<extension> <tool>`. Picking a command
  that takes parameters opens its form (chat_app's command form): selects
  filled from mcp_server, dependent selects, and file fields that upload
  the file and fill in its path on mcp_server. Close the form to type
  `key=value` instead. A command's reply carries a chip "No AI used · direct tool call · 0.8 s"
  (the time is saved with the reply, older replies show no time). When a tool's
  result lists `download_markers`, or an answer holds a
  `[[DOWNLOAD filename="..." bytes="..." url="/server/download?path=..." label="..."]]`
  marker, the marker becomes a download card ("⬇ Download name (size)") that opens
  ember_api's `/api/server/download`. A card whose URL is not that route shows as
  unavailable, with no link. The agent's provider and model come from ai_agent, so there are no pickers for them.
- Attach files to a question (paperclip, paste, or drag and drop anywhere on
  the input area): text and code files, PDF, Word and Excel. ember_api extracts their text (up to 20,000
  characters each), which goes into the question; the chat shows each file
  collapsed under what you typed.
- Summarize (condense the history into a summary the agent keeps) and Clear
  (start afresh); earlier messages stay readable as a collapsed log. A chat
  is also summarized automatically once its context is 60% full. A
  "Context n%" chip shows how full it is.
- Share a chat: the Share button makes a read-only link
  (`/shared/<token>`) that anyone can open without logging in. It is a frozen
  copy of your questions and the answers (tool output, summaries and attached
  files' text are left out); pick 1, 7 or 30 days or never. The link is shown
  once when created (copy it then); the dialog lists a chat's links and turns
  them off, and deleting the chat turns them off too.
- Saved prompts, kept per account in ember_api (they follow you to any
  browser): the bookmark button next to the paperclip lists them with a
  filter, and typing `#` at the start of the input looks them up by name
  (Tab or Enter inserts). A prompt goes into an empty input as it is, or on a
  new line after what you typed. "Manage" creates, edits and deletes them;
  "Save current text" starts a new one from what is typed. Names are unique
  per account (ignoring case), up to 60 characters; texts up to 10,000; 100
  prompts per account.
- Markdown rendering, sanitized with DOMPurify.
- Several conversations, saved per account in ember_api (they follow you to
  any browser; chats from the old browser-only storage are uploaded once):
  rename (double-click or pencil), export to Markdown, clear, delete, delete all.
  "Select" ticks several chats (click a row or its box, or "All") and deletes
  them together after a confirmation; searching leaves select mode.
- Every chat has its own address, `/chat/<id>`: bookmark it, reload it, or use
  the browser's back and forward buttons to move between chats you opened. An
  id that is not one of your chats goes back to `/` with a notice. A new chat
  gets its address when its first question is sent.
- Token limits in the sidebar: two slim bars (last 6 hours, last 7 days) with
  used and limit, shown only for a window that has a limit; hover for exact
  numbers and when the oldest tokens stop counting. They refresh when an
  answer ends. The Usage page has the detail.
  The sidebar search (2+ characters) looks through titles and message text
  (not attached files) and highlights the match; opening a result scrolls to
  the first matching message and flashes it.
- Capabilities page (the old Tools and Capabilities pages in one; `/tools` redirects here): each capability is a
  collapsed card, opened by clicking it or while a filter is typed. Its tools run in place from forms generated from their
  JSON Schema (the same form as the command form). Tools show readable titles (`tool_srv_startApp` -> "Start App")
  and JSON results render as fields and tables, with the raw JSON a click away.
- "Ask before tools" toggle (off by default, remembered per account): each
  tool the agent wants to run waits for you. A card shows the tool's name and
  arguments with Allow once, Allow for this chat and Deny; nothing runs until
  you answer, and no answer within 4 minutes counts as Deny. "Allow for this
  chat" is remembered in this browser per chat (a chip shows how many tools are
  allowed and resets them). Slash commands you type yourself never ask.
- "Terse replies" toggle in the chat header (ai_agent's `caveman`
  option), remembered per account.
- Usage page: your 6-hour and weekly token limits, totals, tokens per day and
  per agent; admins also see every account. A "By" selector regroups the
  totals by agent, provider, gateway or model, and a "Recent calls" table lists
  each call (when, agent and who delegated it, provider, gateway, model, input,
  output and total tokens). Periods: This month (from the 1st,
  UTC), 7, 30 and 90 days, 12 months. Also a "busiest hour" and a "favorite
  agent" tile, a 12-month heatmap (one square per UTC day, five shades
  relative to the busiest day; its own request, so it ignores the period) and
  "Export .md", a Markdown report of the chosen period built in the browser.
  The busiest hour is shown in your time zone by shifting the UTC hours by your
  current offset rounded to a whole hour, so a half-hour zone can be off by an
  hour and a daylight-saving change inside the period is ignored.
  The page also reads each capability's resources and lets admins switch capabilities on/off.
- Extensions page: mcp_server's extensions (other MCP servers) with their
  status and tools; switch on the ones the agent may use in your chats
  (remembered per account, shown in the chat header). Admins add and
  remove extensions.
- Watchers page (`watchers.view`): every capability's background watchers,
  refreshed every 15 s, with capability/status/date filters and search.
- Logs page (any `logs.*` permission): Activity, Errors and Chat turns tabs,
  each for the server or one account.
- Config page (`config.issues.view`): problems in ember_api's config and
  secret files.
- Account page (click your username): profile, change email (re-verify),
  change password (logs out other devices), and the devices you logged in
  from (forget one to have its next login noted as new). Reachable while
  unverified.
- Overview (click "Ember"): every page you may open, as tiles.
- Admin page: overview tiles (accounts, unverified, disabled, open invites)
  above four tabs. Accounts (search by name or email, filter by status, click a
  row for a drawer to edit, enable/disable, add/remove roles, send
  verification, delete), Roles (a list and an editor with a switch per
  permission; create, edit, delete), Invites (create, optionally email, list,
  revoke) and Settings
  ("Require approval for every tool": every account's answers then ask before
  each tool, the "Ask before tools" checkbox is locked on, and "Allow for this
  chat" is not offered).
- Pages and tabs follow your permissions (`chat.use`, `tools.use`,
  `admin.manage`, `watchers.view`, `logs.*`, `config.issues.view`);
  ember_api enforces the same rules on every call.
- Light and dark theme: a top-bar button cycles System, Light and Dark
  (remembered per browser, also on the login page). Colors are
  `light-dark()` tokens in `style.css`, so browsers older than Chrome 123,
  Firefox 120 or Safari 17.5 lose them.

## Requirements

- Node.js 24 (npm on `PATH`)
- A running **ember_api** (default `127.0.0.1:8030`), plus the `ai_agent`
  and `mcp_server` it proxies to.

## Setup and running

```bash
npm install
```

No `.env` is needed: nothing server-specific is compiled into the bundle.

Run with any of:

- `run.bat` - installs `node_modules` on first run, then starts Vite.
  Extra arguments go to Vite (e.g. `run.bat --open`).
- `server_launcher` - lists it as **Ember Web** (detected from `run.bat`).
- `npm run dev`

Then open <http://127.0.0.1:5173> and log in (first time: the ember_api
bootstrap admin - see ember_api's README).

| Env var | Default | Meaning |
|---|---|---|
| `EMBER_WEB_PORT` | `5173` | Vite's port. Vite fails instead of silently switching ports (`strictPort`). |
| `EMBER_API_PORT` | `8030` | Where Vite forwards `/api` (ember_api). |

## Tests

```bash
npm test
```

Vitest with jsdom, `@vue/test-utils` for components. Test files sit beside
their source as `*.test.ts` and are type-checked by `vue-tsc -b` (so
`npm run build` covers them) but never bundled. They need no running server:
ember_api calls are mocked. Covered so far: the chat store (regenerate, edit
and resend, search, jump to a result, delete several, deep-link readiness),
the templates store (including the chime and the clocks), the message list (welcome card, running clock,
command replies, agent tag, download cards), usage chip (agent breakdown), usage gauges, usage heatmap and page, elapsed clock, chime, copy button,
chat input (paste, drop, Up and Down recall, `#` prompts), prompt picker and
dialog, sidebar search and select mode, the shortcut, theme and chat-address
composables, clipboard, markdown code blocks, usage (stats, heatmap, export), welcome and attachment helpers and
the prompt helpers.

`turnStream` (the event stream: pieces of events, ping, reconnect with backoff, resume, give up, abort) is covered too.

### End-to-end test

```bash
npm run test:e2e
```

Playwright runs the built app in the Chrome installed on this machine (no browser download) on port
5199 (`EMBER_E2E_PORT`). One test logs in (a wrong password first), checks the header says "Talking to Test Agent" and
there is no agent picker, asks a question, sees the live "Test Agent → Calculator" line while a
delegated agent works, reads the streamed answer, then reloads. ember_api is not needed: `e2e/fakeApi.ts` answers every `/api` call,
and the test fails if the page asks for anything the fake does not know, so the fake cannot drift
from the app unnoticed. If the app starts calling a new route on these pages, add it there.

Other scripts: `npm run build` (type-check + production build into `dist/`),
`npm run preview` (serves `dist/`, with the same `/api` forwarding).

## How it connects

Vite forwards every `/api/...` request to ember_api (`vite.config.ts`), so
the browser only ever sees one origin: ember_api's `HttpOnly`,
`SameSite=Strict` session cookie rides along automatically and no CORS is
involved. Chat answers are started with `POST /api/chats/{id}/turns` and
watched through `/api/chats/{id}/events` (Server-Sent Events, read with
`fetch` so it can resume after a dropped connection). The MCP clients
(`@modelcontextprotocol/sdk`, Streamable HTTP) point at ember_api's proxy
routes - `/api/mcp/agents/{id}` (agent status only) and `/api/mcp/server`
(tools and resources) - and stream through unbuffered.

## Layout

```
src/
  api/          http + AuthClient / AdminClient / ChatsClient / UsageClient / CommandsClient /
                ExtensionsClient / WatchersClient / LogsClient / AttachmentsClient /
                ConfigIssuesClient / TemplatesClient / SharesClient / SettingsClient (ember_api REST),
                McpClientBase / AiAgentClient / McpServerClient (MCP via ember_api), types
  services/     ConversationStorage (chat history; one-time import of old local chats),
                turnStream (watching a running answer), slashCommands
  stores/       Pinia: auth, entryAgent, chat, templates
  composables/  useChatShortcuts (window-level chat keys), useChatRoute (address bar <-> open chat),
                useElapsed (running clock), useNotify (chime), useTheme (system / light / dark)
  views/        pages: Overview, Chat, Tools, Capabilities, Extensions, Watchers, Usage, Logs, ConfigIssues,
                Admin, Account, Login, Register, VerifyEmail, NoAccess, SharedChat (public)
  components/   reusable pieces: MessageList, ToolSteps, AgentActivity, ChatInput, CommandFormModal, MarkdownContent,
                CopyButton, UsageChip, UsageGauges, UsageHeatmap, ElapsedTime, WelcomeCard, DownloadCards, TemplatePicker, TemplatesModal, ShareDialog, ConversationSidebar, EntryAgentTag, ToolRunForm, ToolResultPanel, ToolCard, CapabilitySection, NavRail, ChatSettingsMenu, AuthCard
    admin/      the Admin page's Accounts / Roles / Invites / Settings panels, AccountDrawer, RoleEditor, StatTile, ConfirmModal + shared admin.css
    infoPage.css  shared look of the Extensions / Watchers / Logs / Config pages
  router/       routes + access guard, safe post-login redirect, pages (nav + Overview list)
  utils/        markdown rendering, download markers, tool-schema forms, error/time formatting, chat export,
                tool titles, tool-result formatting, attachment blocks in questions, clipboard, usage formatting, saved-prompt helpers
```

## Security notes

- A tool approval is enforced by ai_agent and ember_api, not the browser:
  the card only sends an answer, and an answer is accepted only from the
  chat's own account for a step that is waiting. When an admin requires
  approval for every tool, ember_api forces it on each turn and turns
  "allow for this chat" into "allow once"; the locked checkbox and the missing
  button only show it.
- Access checks in the router only decide what the UI shows; ember_api
  enforces every permission itself. The one public page is `/shared/:token`
  (`meta.public`): the guard lets anyone in without loading an account, and
  it shows only what `GET /api/shared/{token}` returns. The page and the app
  carry `<meta name="robots" content="noindex">`.
- A share link's token is kept only in the share dialog's memory while it
  is shown: never in a store, `localStorage` or the link list.
- Chats are stored in ember_api's database, and ember_api writes the
  answers itself. Renames and deletes are sent in order; a failed one shows
  a banner with Retry instead of being dropped.
- The browser can't call ai_agent's `ask` directly (ember_api's proxy allows
  only `status`), so usage limits can't be bypassed.
- `ai_agent` and `mcp_server` require the shared internal token on `/mcp`
  once it's configured (ember_api sends it); without one they must stay on
  `127.0.0.1`, with ember_api as the only gate.
- The MCP SDK loads on the first MCP call, in its own chunk, so the first
  page doesn't wait for it.
