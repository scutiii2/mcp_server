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
- Every message shows its time in your own time zone (hover for the full date),
  and a divider ("Today", "Yesterday" or the date) appears where the day
  changes. Messages saved before times existed show none. When you have
  scrolled up and more arrives, a "↓ New messages" pill brings you back down.
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
- The input grows with what you type, up to 5 lines, then scrolls. A small
  paper plane flies off the send button on each send (hidden when the system
  asks for reduced motion). Four built-in commands run in the browser with no
  tool and no AI, as the keyboard form of the buttons above the input:
  `/clear`, `/compact` (Summarize), `/export` and `/share`. Only the bare
  command counts ("/clear now" is sent as a normal message), the chat needs
  messages, and `/clear` and `/compact` wait for the current answer to finish.
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
- Settings page (`/settings`, `chat.use`): your preferences in one place, grouped by task: Chat (terse
  replies, ask before tools, chime), Appearance (theme) and, for admins, Administration (tool approval).
  A search box filters them as you type (label, description and extra keywords; Enter focuses the first
  match, Esc clears it). A setting that differs from its default shows an accent dot and a reset
  button ("Back to default"), and the header counts how many are changed. Chat and theme apply instantly and
  are saved in this browser; tool approval applies to every account, so a flip (or its reset) waits for
  Save in an unsaved bar. The chat gear menu keeps its quick switches and links here.
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
- Capabilities page (`tools.use` or `chat.use`): mcp_server's built-in capabilities and its extensions
  (other MCP servers) as one list of identical collapsible cards (All / Built-in / Extensions filter,
  and a tool filter). A card shows a status dot, name and id, what it brings, an Open button and an
  on/off switch with who it is for. A capability's switch is for "Everyone" (admins only; a dialog asks
  first). An extension's is for "You": it picks the extensions the agent may use in your chats
  (remembered per account, shown in the chat header). Admins add extensions (button on top) and remove
  them (in the card; a dialog asks first). An extension's Open button leads to its `web_url` (for
  example `pdf_merger` and its web app) in a new tab, labelled "Open app"; only http(s) addresses
  count, and it works without `tools.use` and when the extension is not connected. Any other extension
  (with `tools.use`) gets "Open page" to `/extensions/<id>`: its label, description, web app link and
  its tools as rows that open the same run form (a failed extension shows its error and no tools).
  `/extensions` redirects to this page. Without `tools.use` only the extensions are listed. Tools that
  no capability or extension lists go under "Other tools".
- Agents page (`chat.use`): a card per agent from `GET /api/agents` - name, id,
  Entry / Orchestrator badges, what it is for, and a status (running, offline,
  disabled; an icon and a word). Read-only, refreshed every 15 s: new chats
  always go to the entry agent, there is no per-agent chat.
- Watchers page (`watchers.view`): every capability's background watchers,
  refreshed every 15 s ("Live - updated Ns ago"). Status tiles (running with
  the oldest age, succeeded, failed), a timeline with one lane per capability
  that opens (click its name) into one lane per watcher, and a list under it
  that follows the same open lanes. Failed is red, running blue, finished a
  quiet gray, each with a glyph and a label (a running bar ends in a dot, a
  failed one in a tick). Lanes keep their place across refreshes; the top 8 are
  drawn ("Show all N") and a capability with a failure always is. Search, a
  24h / 7d / All range, and a "Focus" menu for one capability (kept in the
  address as `?capability=`).
- Analytics page (`/analytics`, any `logs.*` or `traffic.view` permission; `/logs`
  redirects here), three tabs, each shown only if the account may use it. Overview: a 24h / 7d / 30d / 90d range, a tile per log kind
  (count, change vs the previous period, trend), entries over time (stacked
  columns, hover or arrow keys for a tooltip, table view), top sources and
  busiest accounts per kind (click an account to open its entries), and a
  weekday-by-hour heatmap; only the kinds the account may read, times in UTC.
  Traffic (`traffic.view`): the same range, tiles for requests, error rate (change
  in percentage points), slowest 5% and upstream failures, requests over time by
  status class (2xx to 5xx), response time (median and slowest 5% lines), busiest
  and slowest routes, and calls to ai_agent and mcp_server per target. Counts
  only, never who made a request; latency is kept in bands, so a time at the top
  band reads "5 s+" (at least that). Entries: the Activity, Errors and Chat turns
  lists, each for the server or one account.
- Config issues page (`config.issues.view`): problems in ember_api's config and
  secret files, as errors (broken) or warnings (risky or incomplete), grouped by
  file. Not a nav tab: a red (errors) or amber (warnings only) alert with a count
  shows in the rail, and the page opens, only while there are issues.
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
  chat" is not offered). Delete account and Delete role sit in a red Danger
  zone, last in the drawer and the editor.
- Confirmations: no native `confirm()` is used anywhere. Every destructive or
  discarding action asks in `ConfirmModal`, and the friction scales with the
  severity. One chat, a few ticked chats, a forgotten device, a share link, a
  saved prompt and a question edit that drops later messages ask once. Turning
  a capability off uses the danger style. A severe action also makes you type
  something before its button unlocks (`requireText`, with a character counter,
  the field focused when the dialog opens): the username to delete an account,
  the role's name to delete a role that accounts still hold, and `delete all` for
  "Delete all chats". The dialog always has Cancel; Escape and a click outside
  close it too.
- Capability pages (`/capabilities/<name>`, needs `tools.use`): a capability
  that ships a `gui/page.json` gets its own page, and its card on the
  Capabilities page shows an "Open page" link while the capability is on.
  `CapabilityPageView` draws it with a fixed set of widgets; nothing in the
  file runs as code, and the browser checks the layout again before drawing it.
  Sections are text notes, forms and tabs. A form is built from its tool's own
  input schema, with fields reordered, relabelled or hidden by the page. A tabs
  section holds 2 to 8 forms shown one at a time (arrows, Home and End move
  between the tabs; a tab you opened stays alive and keeps its controls and
  result) and drops each form's card and title. A `live` form has no submit
  button: it runs when it opens and again 300 ms after a control changes
  (toggles are chips in a row, a field whose schema asks for `input: "range"` is
  a slider), and its result offers "Generate again". A result is a secret,
  message, table or fields list. A secret can be hidden and copied, shown in
  groups of 2 to 8 characters, and, when it has letters, its digits and symbols
  are coloured. A `strength` field (bits of entropy) draws a bar labelled Weak
  (under 45 bits), Fair (under 70), Strong (under 100) or Excellent, full at
  128 bits.
  The layout comes from mcp_server via ember_api
  (`GET /api/capabilities/{name}/gui`); buttons call the capability's own tools
  through the `/api/mcp/server` proxy. A capability with no page, or one that is
  off, shows "This capability has no page". Results and typed secrets stay in
  component memory only: never in `localStorage`, the URL or ember_api. A result
  with `refresh_after` shows a countdown ring ("New code in N s") and re-runs
  the tool at zero; it stops when you leave the page and while the tab is hidden.
- Pages and tabs follow your permissions (`chat.use`, `tools.use`,
  `admin.manage`, `watchers.view`, `logs.*`, `traffic.view`, `config.issues.view`);
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
the prompt helpers. Also covered: the Settings page and its search, the
confirmation dialog (including the typed phrase), the capability page widgets,
and `src/radiusScale.test.ts`, which fails when a `.vue` or `.css` file sets a
border radius with a literal length or percentage instead of a `--radius-*`
token (five 2 px chart marks are allow-listed).

`turnStream` (the event stream: pieces of events, ping, reconnect with backoff, resume, give up, abort) is covered too.

### End-to-end test

```bash
npm run test:e2e
```

Playwright runs the built app in the Chrome installed on this machine (no browser download) on port
5199 (`EMBER_E2E_PORT`). Fourteen tests in four files (`chat`, `settings`, `delete`, `confirm`).
The first logs in (a wrong password first), checks the header says "Talking to Test Agent" and
there is no agent picker, asks a question, sees the live "Test Agent → Calculator" line while a
delegated agent works, reads the streamed answer, then reloads. Two more cover chat folders and
dragging chats. The rest cover the Settings page (search, the modified badge and reset, tool
approval through the unsaved bar) and every confirmation: deleting a chat, all chats (by typing
`delete all`), an account and a role (by typing the name), a saved prompt, turning a share link off,
switching a capability, and editing a question that has later messages. ember_api is not needed:
`e2e/fakeApi.ts` answers every `/api` call,
and the test fails if the page asks for anything the fake does not know, so the fake cannot drift
from the app unnoticed. If the app starts calling a new route on these pages, add it there.

Both suites use a fake `/api`. `SMOKE_TEST.md` is a checklist for trying the
same screens by hand against the real ember_api (throwaway accounts, real saves
and deletes).

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
                ExtensionsClient / AgentsClient / WatchersClient / LogsClient / TrafficClient / AttachmentsClient /
                ConfigIssuesClient / TemplatesClient / SharesClient / SettingsClient (ember_api REST),
                McpClientBase / AiAgentClient / McpServerClient (MCP via ember_api), types
  services/     ConversationStorage (chat history; one-time import of old local chats),
                turnStream (watching a running answer), slashCommands
  stores/       Pinia: auth, entryAgent, chat, templates, configIssues
  composables/  useChatShortcuts (window-level chat keys), useChatRoute (address bar <-> open chat),
                useElapsed (running clock), useNotify (chime), useSidebarCollapse (chat list),
                useTheme (system / light / dark)
  views/        pages: Overview, Chat, Capabilities, Agents, Watchers, Usage, Settings, Analytics, ConfigIssues,
                Admin, Account, Login, Register, VerifyEmail, NoAccess, SharedChat (public)
  components/   reusable pieces: MessageList, ToolSteps, AgentActivity, ChatInput, CommandFormModal, MarkdownContent,
                CopyButton, UsageChip, UsageGauges, UsageHeatmap, ElapsedTime, WelcomeCard, DownloadCards, TemplatePicker, TemplatesModal, ShareDialog, ConversationSidebar, EntryAgentTag, ToolRunForm, ToolResultPanel, ToolCard, CapabilitySection, LogEntries, NavRail, ChatSettingsMenu, SettingRow, AuthCard
    admin/      the Admin page's Accounts / Roles / Invites / Settings panels, AccountDrawer, RoleEditor, StatTile, ConfirmModal + shared admin.css
    analytics/  the Analytics Overview and Traffic tabs: ActivityChart (stacked columns), LineChart, StatTile / KindStatTile, Sparkline, BarList, HourHeatmap, TrafficPanel
                (hand-drawn SVG/CSS; shared hover/keyboard state in useBucketCursor, shared frame in chart.css; series colours `--kind-*`, `--http-*`, `--latency-*`)
    watchers/   the Watchers page's WatcherTimeline, WatcherList, CapabilityFocus (status colours `--status-*`)
    infoPage.css  shared look of the Agents / Watchers / Analytics / Config pages
  router/       routes + access guard, safe post-login redirect, pages (nav + Overview list)
  utils/        markdown rendering, download markers, tool-schema forms, error/time formatting, chat export,
                tool titles, tool-result formatting, attachment blocks in questions, clipboard, usage formatting, log-analytics and watcher helpers, saved-prompt helpers
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
