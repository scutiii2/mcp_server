# ember_web

Browser chat frontend for this repo, built with Vue 3, TypeScript and Vite.
Unlike `chat_app`, it has no backend of its own: the browser talks MCP
directly to `ai_agent` (chat) and `mcp_server` (tool listing) using
`@modelcontextprotocol/sdk`'s Streamable HTTP client.

## Features

- Chat with one `ai_agent` instance, with live token streaming and tool-step
  indicators (from the MCP progress notifications `ask()` sends).
- Stop button (`ai_agent`'s `cancel` tool; takes effect at the next round).
- Markdown rendering, sanitized with DOMPurify.
- Several conversations, saved in this browser's `localStorage`.
- Tools page listing every tool `mcp_server` exposes.
- Light and dark theme following the system setting.

## Requirements

- Node.js 24 (npm on `PATH`)
- A running `ai_agent` (default `127.0.0.1:9100`) and `mcp_server`
  (default `127.0.0.1:8010`), both with CORS allowing this app's origin
  (see [Ports and CORS](#ports-and-cors))

## Setup

```bash
npm install
cp .env.example .env
```

`.env` holds the server URLs. Every `VITE_*` value is compiled into the
JavaScript the browser downloads, so **never put a token or key in it**.

| Variable | Default |
|---|---|
| `VITE_AI_AGENT_URL` | `http://127.0.0.1:9100/mcp` |
| `VITE_MCP_SERVER_URL` | `http://127.0.0.1:8010/mcp` |

## Running

Any of:

- `run.bat` - installs `node_modules` on first run, then starts Vite.
  Extra arguments go to Vite (e.g. `run.bat --open`).
- `server_launcher` - lists it as **Ember Web** (detected from `run.bat`).
- `npm run dev`

Then open <http://127.0.0.1:5173>. The port comes from `EMBER_WEB_PORT`
(default `5173`); Vite fails instead of silently switching ports
(`strictPort`), so the launcher's port is always the real one.

Other scripts: `npm run build` (type-check + production build into `dist/`),
`npm run preview`.

## Ports and CORS

The browser only lets this page call `ai_agent` and `mcp_server` because
both servers add `CORSMiddleware` allowing `http://127.0.0.1:5173` and
`http://localhost:5173` and exposing the `Mcp-Session-Id` header
(`ai_agent/src/server.py`, `mcp_server/src/run.py`). Serving ember_web from
any other origin or port means adding it to both lists.

## Layout

```
src/
  api/          MCP clients (McpClientBase, AiAgentClient, McpServerClient) and types
  services/     ConversationStorage (localStorage today, swappable)
  stores/       Pinia stores (chat)
  views/        pages: ChatView, ToolsView
  components/   reusable pieces: MessageList, ChatInput, MarkdownContent, ConversationSidebar
  router/       vue-router routes
  utils/        markdown rendering
```

## Security status

**Localhost only for now.** `ai_agent` and `mcp_server` do not authenticate
browser callers: anyone who can reach their ports can run chats (spending
LLM budget) and call tools, and `mcp_server` trusts the
`X-Requester-Username` header, which a browser can set to anything.
Per-user auth is required before ember_web is served anywhere else.
