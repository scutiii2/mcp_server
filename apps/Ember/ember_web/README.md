# ember_web

Browser chat frontend for this repo, built with Vue 3, TypeScript and Vite.
It talks only to [ember_api](../ember_api), its own backend, over the same
origin: ember_api owns the accounts and login sessions and proxies MCP to
`ai_agent` (chat) and `mcp_server` (tools). The browser never holds a server
URL, token or key.

## Features

- Workspace administration, activity logs, and traffic analytics live in [ember_admin](../ember_admin).

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
- Suggested next prompt: after an answer the chat box shows a predicted next
  message as its placeholder; Tab fills it in. Switch: Settings > Chat >
  Suggest next prompt (saved to the account, off means no model call).
- Stop button (takes effect at the agent's next round).
- A live task plan panel shows each agent's checklist with Pending, In progress,
  and Done labels. It resumes after a reconnect and clears when the turn ends.
- A running clock under the answer being written (`12.4 s`, then `1 min 03 s`),
  and beside "Running command ...". It counts from when you sent the question; for a
  chat you reopen while it is still answering it counts from the reopen.
- Completion alerts for the watched answer: while the page is hidden or unfocused,
  the tab title shows an unread "Answer ready" count, cleared when you return.
  Settings → Chat → Desktop notifications enables optional browser notifications
  (off by default, remembered per account on this device). Enabling requests browser
  permission; denied or unsupported browsers show an explanation. Click a notification
  to open its chat. Notifications contain no chat title or answer text. Requires
  browser support and a secure context (HTTPS or localhost); the tab indicator works
  even if desktop notifications are blocked. The page must remain open and watching
  the turn; stopped, failed and abandoned streams do not notify.
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
- Lists format in the typing box: begin a line with `- `, `* `, `+ ` or
  a number followed by `. `. Bullets and numbers have automatic left
  indentation, including wrapped lines. Enter sends; Shift+Enter continues
  the next item, or exits an empty item. Tab/Shift+Tab indent/outdent list
  items. Questions are sent as Markdown; sent user bubbles continue to show
  the original Markdown text. The list editor loads when needed; ordinary
  text, command suggestions, attachments and saved prompts use the same composer.
- Attach files to a question (paperclip, paste, or drag and drop anywhere on
  the input area): text and code files, PDF, Word, Excel and supported images.
  Text previews (up to 20,000 characters each) go into the question; the chat
  shows each file collapsed under what you typed. PDF/image originals are also
  stored in PDFMerger under your account so PDF Assistant can inspect and merge
  them using their uploaded IDs, including scans without readable text. IDs are
  retained when delegating to specialists. Uploads are limited to 15 MB each.
  PDFMerger must be running and configured as the `pdf_merger` HTTP extension
  with a valid internal token and `forward_requester: true`. Stored files expire
  according to PDFMerger's TTL; upload again if an ID expires. Removing a chip
  removes it from the question; its stored original expires through that TTL.
  Images can be inspected for metadata and merged; this integration adds no OCR.
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
  Folder menus offer Move up / Move down; the order follows the account
  across browsers. End-of-list moves and moves during a save are disabled.
- Every chat has its own address, `/chat/<id>`: bookmark it, reload it, or use
  the browser's back and forward buttons to move between chats you opened. An
  id that is not one of your chats goes back to `/` with a notice. A new chat
  gets its address when its first question is sent.
- Token limits in the sidebar: two slim bars (last 6 hours, last 7 days) with
  used and limit, shown only for a window that has a limit; hover for exact
  numbers and when the oldest tokens stop counting. They refresh when an
  answer ends. The Usage page has the detail.
  The sidebar search (2+ characters) looks through titles and message text
  (not attached files), highlights the match and shows the current folder
  name on filed chats; opening a result scrolls to
  the first matching message and flashes it.
- Capabilities page (the old Tools and Capabilities pages in one; `/tools` redirects here): only what the account has added is listed. Each capability is a
  collapsed card, opened by clicking it or while a filter is typed. Its tools run in place from forms generated from their
  JSON Schema (the same form as the command form). Tools show readable titles (`tool_srv_startApp` -> "Start App")
  and JSON results render as fields and tables, with the raw JSON a click away. The card switch turns the item off for the
  account and its card leaves the page. An account that has added nothing sees "Nothing added yet" with a link to the Supermarket.
- Supermarket (`/capabilities/supermarket`, `tools.use` or `chat.use`; opened from a button on the Capabilities page): every built-in
  capability and extension in two sections, with Add and Disable per row. What an account has added is kept in ember_api
  (`/api/account-capabilities`), so it follows the account across devices; a new account starts with nothing added. Two exclusive
  filter chips, Enabled and Disabled, narrow the lists (clicking the active chip clears it; the choice is in the address as
  `?state=`). A capability an administrator turned off for everyone shows "Off for everyone" and cannot be added. Global capability switches and shared extension management live in ember_admin.
- Private extensions (`chat.use`): the Supermarket's "My extensions" section adds an MCP server only this account can see, with an
  optional set of headers (a token or key). Header values are write-only: they are stored encrypted by ember_api and never shown
  again; editing offers "Replace headers", which replaces the whole set. Each row has Enable/Disable, Edit and Remove, and shows
  its live status (a probe cached for a minute). Enabled ones also appear as "Private" cards on the Capabilities page, listing
  their tools; those tools work in chats only (always asking first, and every later tool in that turn asks too) and cannot be run
  from the page. When a private extension could not be used in an answer, a banner above the messages says which and why until
  the next question. It is live only and not saved with the chat.
- "Ask before tools" toggle (off by default, remembered per account): each
  tool the agent wants to run waits for you. A card shows the tool's name and
  arguments with Allow once, Allow for this chat and Deny; nothing runs until
  you answer, and no answer within 4 minutes counts as Deny. "Allow for this
  chat" is remembered in this browser per chat (a chip shows how many tools are
  allowed and resets them). Slash commands you type yourself never ask.
- Clickable questions: the agent can stop mid-answer and ask 1-4 questions with options (single or multiple
  choice) plus your own typed answer. The question card appears inside the live answer; answer and Submit, or Skip
  to let the agent go on with its best guess. There is no time limit while you decide, and Stop cancels the
  answer. A reload brings the card back. Saved answers show the questions and what you chose under "Ran N tools".
- "Terse replies" toggle in the chat header (ai_agent's `caveman`
  option), remembered per account.
- Settings page (`/settings`, `chat.use`): your preferences in one place, grouped by task: Chat (terse
  replies, ask before tools, chime, desktop notifications), Appearance (theme), Sidebar (see below). Workspace tool approval is configured in ember_admin.
  A search box filters them as you type (label, description and extra keywords; Enter focuses the first
  match, Esc clears it). A setting that differs from its default shows an accent dot and a reset
  button ("Back to default"), and the header counts how many are changed. Chat and theme apply instantly and
  are saved in this browser. The chat gear menu keeps its quick switches and links here.
- Sidebar arrangement, per account (Settings, Sidebar card; saved through `/api/nav-preferences`): one row per
  page you may open. Drag a row or use its arrows to reorder, pin it to a group at the top of the rail (a divider
  separates the groups), or switch it off to hide it from the rail (hidden pages stay on the Overview page).
  Changes apply at once; a failed save reloads the server's copy and shows the error. Reset puts back the default.
  The rail draws nothing until the arrangement has loaded, so the icons don't jump. The rules are pure functions
  in `src/utils/navArrangement.ts`.
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
- Capabilities page (`tools.use` or `chat.use`): only mcp_server's built-in capabilities and extensions the account has added
  (other MCP servers) as one list of identical collapsible cards (All / Built-in / Extensions filter,
  and a tool filter). A card shows a status dot, name and id, what it brings, an Open button and an
  on/off switch with who it is for. Every card's switch is for "Account": turning it off removes the item from the account
  and its card leaves the page. What the account has added follows it across devices; a new account starts with nothing added.
  An account that has added nothing sees "Nothing added yet" with a link to the Supermarket. The tools of capabilities not
  added are sent as `disabled_tools` with each question. Global switches live in ember_admin. A capability off for everyone stays dimmed and its account switch can still be turned off.
  An extension's Open button leads to its `web_url` (for
  example `pdf_merger` and its web app) in a new tab, labelled "Open app"; only http(s) addresses
  count, and it works without `tools.use` and when the extension is not connected. An extension with no
  web app has no Open button: its card lists its tools as rows that open the run form (a failed
  extension shows its error and no tools). `/extensions` and `/extensions/<id>` redirect to this page. Without `tools.use` only the extensions are listed. Tools that
  no capability or extension lists go under "Other tools".
- Supermarket (`/capabilities/supermarket`, `tools.use` or `chat.use`; opened from a button on the Capabilities page): every built-in
  capability and extension in two sections, with Add and Disable per row. What an account has added is kept in ember_api
  (`/api/account-capabilities`), so it follows the account across devices; a new account starts with nothing added. Two exclusive
  filter chips, Enabled and Disabled, narrow the lists (clicking the active chip clears it; the choice is in the address as
  `?state=`). A capability an administrator turned off for everyone shows "Off for everyone" and cannot be added. Global capability switches and shared extension management live in ember_admin.
- Agents page (`chat.use`): a card per agent from `GET /api/agents` - name, id,
  Entry / Orchestrator badges, what it is for, its provider / gateway / model
  (a value the agent file does not set is left out), and a status (running,
  offline, disabled; an icon and a word). Read-only, refreshed every 15 s: new chats
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

- Config issues page (`config.issues.view`): problems in ember_api's config and
  secret files, as errors (broken) or warnings (risky or incomplete), grouped by
  file. Not a nav tab: a red (errors) or amber (warnings only) alert with a count
  shows in the rail, and the page opens, only while there are issues.
- Account page (click your username): profile with email verification status,
  separate security and roles/access panels, expandable permissions, and a
  responsive remembered-device list. Change email (re-verify),
  change password (logs out other devices), and the devices you logged in
  from (forget one to have its next login noted as new). Reachable while
  unverified.
- Overview (click "Ember"): every page you may open, as tiles.

- Confirmations: no native `confirm()` is used anywhere. Every destructive or
  discarding action asks in `ConfirmModal`, and the friction scales with the
  severity. One chat, a few ticked chats, a forgotten device, a share link, a
  saved prompt and a question edit that drops later messages ask once. A severe action also makes you type
  something before its button unlocks (`requireText`, with a character counter,
  the field focused when the dialog opens): `delete all` for
  "Delete all chats". Account and role deletion confirmations live in ember_admin. The dialog always has Cancel; Escape and a click outside
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
  api/          http + AuthClient / ChatsClient / UsageClient / CommandsClient /
                ExtensionsClient / AgentsClient / WatchersClient / AttachmentsClient /
                ConfigIssuesClient / TemplatesClient / NavPreferencesClient / SharesClient / SettingsClient (ember_api REST),
                McpClientBase / AiAgentClient / McpServerClient (MCP via ember_api), types
  services/     ConversationStorage (chat history; one-time import of old local chats),
                turnStream (watching a running answer), slashCommands
  stores/       Pinia: auth, entryAgent, chat, templates, navPrefs, accountCapabilities, configIssues
  composables/  useChatShortcuts (window-level chat keys), useChatRoute (address bar <-> open chat),
                useElapsed (running clock), useNotify (chime), useCompletionNotify (completion alerts), useSidebarCollapse (chat list),
                useTheme (system / light / dark)
  views/        pages: Overview, Chat, Capabilities, Agents, Watchers, Usage, Settings, ConfigIssues,
                Account, Login, Register, VerifyEmail, NoAccess, SharedChat (public)
  components/   reusable pieces: MessageList, ToolSteps, AgentActivity, ChatInput, CommandFormModal, MarkdownContent,
                CopyButton, UsageChip, UsageGauges, UsageHeatmap, ElapsedTime, WelcomeCard, DownloadCards, TemplatePicker, TemplatesModal, ShareDialog, ConversationSidebar, EntryAgentTag, ToolRunForm, ToolResultPanel, ToolCard, CapabilitySection, ConfirmModal, NavRail, SidebarEditor, ChatSettingsMenu, SettingRow, AuthCard
    analytics/  shared LineChart, hover/keyboard state in useBucketCursor and chart.css, used by Usage
    watchers/   the Watchers page's WatcherTimeline, WatcherList, CapabilityFocus (status colours `--status-*`)
    infoPage.css  shared look of the Agents / Watchers / Config pages
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

### Granular permissions

Ember now separates tool browsing (`tools.view`) from execution (`tools.execute`),
including tools called through chat. Public link creation needs `chat.share`,
personal MCP connection changes need `extensions.personal.manage`, and file
transfers use `files.upload` / `files.download`. Existing roles retain equivalent
access through the one-time API migration; role editors list the new permissions.

Administration uses `accounts.view`, `accounts.manage`, `accounts.delete`,
`roles.view`, `roles.manage`, `roles.assign`, `invites.manage`, and
`settings.manage`. Shared capability controls use `capabilities.manage`; shared
extension management remains `extensions.manage`. The all-account usage report
uses `usage.all.view`. Navigation and controls follow these permissions, and the
API enforces every action. Delegated administrators can only grant or change
roles within their own permissions.

Administrators can open Ember Admin from the desktop rail or the Overview page (also on mobile). The link opens in a new tab and uses this host on port 5176 by default (matching Server Launcher; port 5175 is used by Video Downloader). Set `VITE_EMBER_ADMIN_URL` before starting Vite or building to use a different address, such as `https://admin.example.com/` or a reverse-proxy path `/admin/`. It appears for verified accounts with access to an Ember Admin page, including delegated administrators.

Content pages share heading typography, description typography, and horizontal spacing through `ember_web/src/components/pageLayout.css` (also imported by Ember Admin).

Capabilities uses compact cards matching Ember Admin. Selecting a card opens a fixed-height tool workspace with a searchable tool sidebar, parameter form and results. Resources are readable inside the modal; private extensions remain available only in chats. Account switches and custom page links remain on the cards.

Settings edits are drafts until Save. A fixed bottom Save/Revert bar covers chat preferences, theme and sidebar arrangement, with error retry and unsaved-change protection.

## Mobile and installation

Phone layouts use bottom navigation, touch controls, safe-area padding for notches
and the home indicator, and the dynamic viewport for browser chrome and keyboards.
Ember and Ember Admin install separately, each from its own origin.

Build with `npm run build`, then serve `dist/` over HTTPS (localhost also works).
For phone layout testing on the same Wi-Fi, run `npm run preview -- --host 0.0.0.0`
and open this computer's LAN address and preview port; use an HTTPS reverse proxy
for installation and offline testing on a phone.
The browser can install the app from its menu; when an install prompt is available,
an **Install app** button appears. On iPhone/iPad, use Safari → Share → Add to Home Screen.
The PWA service worker is enabled in production builds, including `npm run preview`,
and is disabled in the Vite development server so it does not interfere with HMR.
An HTTP LAN address can serve the mobile layout, but installation/offline support
requires HTTPS. Keep the existing same-origin `/api` proxy and SPA route fallback.
Serve `sw.js` and `index.html` with revalidation (`Cache-Control: no-cache`), hashed
`assets/` with immutable caching, and the manifest as `application/manifest+json`.

After one connected visit, static HTML, JavaScript, CSS and app icons are available
offline. An offline banner explains that chat, sign-in and administration actions
need a connection; use **Retry** once connected. The service worker never caches
API responses, transcripts, account data or generated downloads, and never queues
or replays writes. A cold offline start cannot restore the server session.
New builds show **Reload to update** / **Later**; save drafts first. There is no
automatic update reload during a chat or an administration edit.

App icons: `public/icons/`. Regenerate both sets from their SVG logos with
`node ../scripts/generate-pwa-icons.mjs` (from either app; uses local Chrome).
Production browser tests cover phone layouts, installation metadata, offline shell
loading, API cache exclusion and reconnection.
