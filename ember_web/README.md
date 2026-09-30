# ember_web

Browser chat frontend for this repo, built with Vue 3, TypeScript and Vite.
It talks only to [ember_api](../ember_api), its own backend, over the same
origin: ember_api owns the accounts and login sessions and proxies MCP to
`ai_agent` (chat) and `mcp_server` (tools). The browser never holds a server
URL, token or key.

## Features

- Log in, register with an invite code, verify your email (ember_api
  accounts - separate from chat_app's).
- Chat with any registered `ai_agent` instance (Agent dropdown), with live
  token streaming and the tools it runs. Each answer keeps a collapsed
  "Ran N tools" list (arguments and result per step), also after a reload. ember_api runs each answer: it
  keeps going and is saved even if the page closes; reopening the chat picks
  the live answer back up. Chats still being answered show a pulsing dot.
- Stop button (takes effect at the agent's next round).
- Copy button on every answer, on your messages and on each code block.
- A usage chip under each answer (`model · 12.4k tokens · 4.2 s · 3 tools`);
  click it for input/output tokens, time, tools run and context use. Answers
  saved before ember_api stored the split and the time show less.
- Regenerate the last answer, or edit one of your questions and resend it
  (its attached files stay; the messages after it are dropped, with a
  confirm when that discards later exchanges). ember_api does the cut
  (`truncate_to`).
- Keyboard: `Esc` stops the running answer, `Ctrl/Cmd+K` focuses the input,
  `Ctrl/Cmd+Shift+O` starts a new chat, `Up` in an empty input recalls your
  last question.
- Slash commands: `/<capability> <command> key=value ...` runs an mcp_server
  tool directly (no AI), `/help` and `/<capability> help` show help; the input
  suggests commands as you type (needs `tools.use`). Tools of the extensions
  you switched on are commands too: `/<extension> <tool>`. Picking a command
  that takes parameters opens its form (chat_app's command form): selects
  filled from mcp_server, dependent selects, and file fields that upload
  the file and fill in its path on mcp_server. Close the form to type
  `key=value` instead.
- Attach files to a question (paperclip, paste, or drag and drop anywhere on
  the input area): text and code files, PDF, Word and Excel. ember_api extracts their text (up to 20,000
  characters each), which goes into the question; the chat shows each file
  collapsed under what you typed.
- Summarize (condense the history into a summary the agent keeps) and Clear
  (start afresh); earlier messages stay readable as a collapsed log. A chat
  is also summarized automatically once its context is 60% full. A
  "Context n%" chip shows how full it is.
- Markdown rendering, sanitized with DOMPurify.
- Several conversations, saved per account in ember_api (they follow you to
  any browser; chats from the old browser-only storage are uploaded once):
  rename (double-click or pencil), export to Markdown, clear, delete, delete all.
  The sidebar search (2+ characters) looks through titles and message text
  (not attached files) and highlights the match; opening a result scrolls to
  the first matching message and flashes it.
- Tools page: list and run `mcp_server` tools from forms generated from their
  JSON Schema (the same form as the command form). Tools show readable titles (`tool_srv_startApp` -> "Start App")
  and JSON results render as fields and tables, with the raw JSON a click away.
- "Terse replies" toggle next to the Agent picker (ai_agent's `caveman`
  option), remembered per account.
- Usage page: your 6-hour and weekly token limits, totals, tokens per day and
  per agent; admins also see every account.
- Capabilities page: mcp_server's capabilities with their tools and
  resources, reading resources, and (admins) switching capabilities on/off.
- Extensions page: mcp_server's extensions (other MCP servers) with their
  status and tools; switch on the ones the agent may use in your chats
  (remembered per account, shown next to the Agent picker). Admins add and
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
- Admin page, three tabs: Accounts (edit, enable/disable, add/remove roles,
  send verification, delete), Roles (create, edit, delete, permission
  checkboxes) and Invites (create, optionally email, list, revoke).
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
and resend, search, jump to a result), the message list, usage chip, copy
button, chat input (paste, drop, Up recall), sidebar search, the shortcut and
theme composables, clipboard, markdown code blocks and usage formatting.

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
                ConfigIssuesClient (ember_api REST),
                McpClientBase / AiAgentClient / McpServerClient (MCP via ember_api), types
  services/     ConversationStorage (chat history; one-time import of old local chats),
                turnStream (watching a running answer), slashCommands
  stores/       Pinia: auth, agents, chat
  composables/  useChatShortcuts (window-level chat keys), useTheme (system / light / dark)
  views/        pages: Overview, Chat, Tools, Capabilities, Extensions, Watchers, Usage, Logs, ConfigIssues,
                Admin, Account, Login, Register, VerifyEmail, NoAccess
  components/   reusable pieces: MessageList, ToolSteps, ChatInput, CommandFormModal, MarkdownContent,
                CopyButton, UsageChip, ConversationSidebar, AgentPicker, ToolRunForm, ToolResultPanel, AuthCard
    admin/      the Admin page's Accounts / Roles / Invites panels + shared admin.css
    infoPage.css  shared look of the Extensions / Watchers / Logs / Config pages
  router/       routes + access guard, safe post-login redirect, pages (nav + Overview list)
  utils/        markdown rendering, tool-schema forms, error/time formatting, chat export,
                tool titles, tool-result formatting, attachment blocks in questions, clipboard, usage formatting
```

## Security notes

- Access checks in the router only decide what the UI shows; ember_api
  enforces every permission itself.
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
