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
  token streaming and tool-step indicators (the MCP progress notifications
  `ask()` sends).
- Stop button (`ai_agent`'s `cancel` tool; takes effect at the next round).
- Markdown rendering, sanitized with DOMPurify.
- Several conversations, saved in this browser's `localStorage` per account.
- Tools page: list and run `mcp_server` tools from forms generated from their
  JSON Schema.
- Admin page, three tabs: Accounts (edit, enable/disable, add/remove roles,
  send verification, delete), Roles (create, edit, delete, permission
  checkboxes) and Invites (create, optionally email, list, revoke).
- Pages and tabs follow your permissions (`chat.use`, `tools.use`,
  `admin.manage`); ember_api enforces the same rules on every call.
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
involved. The MCP clients (`@modelcontextprotocol/sdk`, Streamable HTTP)
point at ember_api's proxy routes - `/api/mcp/agents/{id}` and
`/api/mcp/server` - and streamed responses come through unbuffered.

## Layout

```
src/
  api/          http + AuthClient / AdminClient (ember_api REST),
                McpClientBase / AiAgentClient / McpServerClient (MCP via ember_api), types
  services/     ConversationStorage (localStorage per account, swappable)
  stores/       Pinia: auth, agents, chat
  views/        pages: Chat, Tools, Admin, Login, Register, VerifyEmail, NoAccess
  components/   reusable pieces: MessageList, ChatInput, MarkdownContent,
                ConversationSidebar, AgentPicker, ToolRunForm, ToolResultPanel, AuthCard
    admin/      the Admin page's Accounts / Roles / Invites panels + shared admin.css
  router/       routes + access guard, safe post-login redirect
  utils/        markdown rendering, tool-schema forms, error/time formatting
```

## Security notes

- Access checks in the router only decide what the UI shows; ember_api
  enforces every permission itself.
- Chats live in the browser (`localStorage`, one key per account), not on a
  server: they don't follow you to another browser, and anyone with access
  to this browser profile can read them.
- `ai_agent` and `mcp_server` must stay unreachable from outside this
  machine (bound to `127.0.0.1`): they don't check tokens on `/mcp`
  themselves - ember_api is the gate.
