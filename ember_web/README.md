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
  token streaming and tool-step indicators. ember_api runs each answer: it
  keeps going and is saved even if the page closes; reopening the chat picks
  the live answer back up. Chats still being answered show a pulsing dot.
- Stop button (takes effect at the agent's next round).
- Slash commands: `/<capability> <command> key=value ...` runs an mcp_server
  tool directly (no AI), `/help` and `/<capability> help` show help; the input
  suggests commands as you type (needs `tools.use`). Tools of the extensions
  you switched on are commands too: `/<extension> <tool>`.
- Attach files to a question (paperclip or drag and drop): text and code
  files, PDF, Word and Excel. ember_api extracts their text (up to 20,000
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
- Tools page: list and run `mcp_server` tools from forms generated from their
  JSON Schema. Tools show readable titles (`tool_srv_startApp` -> "Start App")
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
  change password (logs out other devices). Reachable while unverified.
- Admin page, three tabs: Accounts (edit, enable/disable, add/remove roles,
  send verification, delete), Roles (create, edit, delete, permission
  checkboxes) and Invites (create, optionally email, list, revoke).
- Pages and tabs follow your permissions (`chat.use`, `tools.use`,
  `admin.manage`, `watchers.view`, `logs.*`, `config.issues.view`);
  ember_api enforces the same rules on every call.
- Light and dark theme following the system setting.

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
  views/        pages: Chat, Tools, Capabilities, Extensions, Watchers, Usage, Logs, ConfigIssues, Admin,
                Account, Login, Register, VerifyEmail, NoAccess
  components/   reusable pieces: MessageList, ChatInput, MarkdownContent,
                ConversationSidebar, AgentPicker, ToolRunForm, ToolResultPanel, AuthCard
    admin/      the Admin page's Accounts / Roles / Invites panels + shared admin.css
    infoPage.css  shared look of the Extensions / Watchers / Logs / Config pages
  router/       routes + access guard, safe post-login redirect
  utils/        markdown rendering, tool-schema forms, error/time formatting, chat export,
                tool titles, tool-result formatting, attachment blocks in questions
```

## Security notes

- Access checks in the router only decide what the UI shows; ember_api
  enforces every permission itself.
- Chats are stored in ember_api's database, and ember_api writes the
  answers itself. Renames and deletes are sent in order; a failed one shows
  a banner with Retry instead of being dropped.
- The browser can't call ai_agent's `ask` directly (ember_api's proxy allows
  only `status`), so usage limits can't be bypassed.
- `ai_agent` and `mcp_server` must stay unreachable from outside this
  machine (bound to `127.0.0.1`): they don't check tokens on `/mcp`
  themselves - ember_api is the gate.
