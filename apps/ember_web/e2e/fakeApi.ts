import type { Page, Route } from "@playwright/test";

/** A stand-in for ember_api, answering what the browser asks of it. The real
 * server (and ai_agent behind it) is not needed: the point is to run the built
 * app in a real browser, through login, sending a question and reading the
 * streamed answer. Anything the app asks that is not listed here is recorded in
 * `unexpected`, and the test fails on it, so the fake cannot drift unnoticed. */

export const ACCOUNT = {
  id: 1,
  username: "ada",
  email: "ada@example.com",
  email_verified: true,
  roles: ["Member"],
  permissions: ["chat.use"],
};

/** The same person with the Administrator role, for the pages that need `admin.manage`. */
export const ADMIN_ACCOUNT = {
  ...ACCOUNT,
  roles: ["Administrator"],
  permissions: ["chat.use", "tools.use", "admin.manage"],
};

/** The agent GET /api/agent returns, and the one every new chat is stored with. */
const ENTRY_AGENT = { id: "agent-1", label: "Test Agent" };

/** The agent the main one hands a question to during the turn. */
const DELEGATE = { id: "calc", label: "Calculator", step_id: "d1" };

export const PASSWORD = "correct horse battery";

export interface StoredChat {
  id: string;
  title: string;
  agent_id: string;
  messages: Record<string, unknown>[];
  running: boolean;
  folder_id?: number | null;
  pinned?: boolean;
}

export interface StoredFolder {
  id: number;
  name: string;
  position: number;
}

export interface StoredAccount {
  id: number;
  username: string;
  email: string;
  email_verified: boolean;
  is_active: boolean;
  is_protected: boolean;
  created_at: string;
  roles: { id: number; name: string }[];
}

export interface StoredCapability {
  name: string;
  enabled: boolean;
  label: string | null;
  /** The tools it offers while it is on; mcp_server lists no tool of a capability that is off. */
  tools: string[];
  resources: string[];
}

export interface StoredRole {
  id: number;
  name: string;
  description: string | null;
  is_protected: boolean;
  permissions: string[];
  account_count: number;
}

export interface StoredTemplate {
  id: number;
  name: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface StoredShare {
  id: number;
  chat_id: string;
  title: string;
  message_count: number;
  created_at: string;
  expires_at: string | null;
}

export interface FakeApi {
  /** The capabilities the Capabilities page lists and an administrator can switch (an administrator login only). */
  capabilities: Map<string, StoredCapability>;
  /** The roles the Admin page lists (an administrator login only). */
  roles: Map<number, StoredRole>;
  /** The member's saved prompts. */
  templates: Map<number, StoredTemplate>;
  /** The read-only links of the member's chats. */
  shares: Map<number, StoredShare>;
  /** What the Settings tab saves: the administrator's "require approval for every tool". */
  settings: { forceToolApproval: boolean };
  /** The accounts the Admin page lists (an administrator login only). */
  accounts: Map<number, StoredAccount>;
  /** Requests that no handler knew, as "METHOD /path". */
  unexpected: string[];
  /** The bodies of the questions the page sent, as JSON. */
  turns: Record<string, unknown>[];
  chats: Map<string, StoredChat>;
  folders: Map<number, StoredFolder>;
}

const NO_USAGE = {
  six_hour: { used: 0, limit: 0, reset_at: null },
  weekly: { used: 0, limit: 0, reset_at: null },
  report: {
    days: 30,
    since: "2026-09-03",
    total_tokens: 0,
    input_tokens: 0,
    output_tokens: 0,
    summary_tokens: 0,
    turns: 0,
    chats: 0,
    by_agent: [],
    groups: [],
    daily: [],
    hourly: Array.from({ length: 24 }, () => 0),
  },
};

const ADMIN_ACCOUNTS: StoredAccount[] = [
  { id: 1, username: "ada", email: "ada@example.com", email_verified: true, is_active: true, is_protected: true, created_at: "2026-09-01T10:00:00", roles: [{ id: 1, name: "Administrator" }] },
  { id: 2, username: "maria", email: "maria@example.com", email_verified: true, is_active: true, is_protected: false, created_at: "2026-09-12T10:00:00", roles: [{ id: 2, name: "Member" }] },
  { id: 3, username: "joe", email: "joe@example.com", email_verified: false, is_active: true, is_protected: false, created_at: "2026-09-20T10:00:00", roles: [] },
];
const ADMIN_ROLES = [
  { id: 1, name: "Administrator", description: "Everything", is_protected: true, permissions: ["chat.use", "tools.use", "admin.manage"], account_count: 1 },
  { id: 2, name: "Member", description: "Default role", is_protected: false, permissions: ["chat.use"], account_count: 1 },
  { id: 3, name: "Ops", description: null, is_protected: false, permissions: [], account_count: 0 },
];
const ADMIN_CAPABILITIES: StoredCapability[] = [
  { name: "pdf", enabled: true, label: "PDF files", tools: ["pdf_merge"], resources: [] },
  { name: "legacy", enabled: true, label: "Legacy", tools: ["legacy_tool"], resources: [] },
];
const ADMIN_PERMISSIONS = [
  { name: "chat.use", description: "Chat with the agent" },
  { name: "tools.use", description: "Run mcp_server tools" },
  { name: "admin.manage", description: "Manage accounts" },
];

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const summary = (chat: StoredChat) => ({
  id: chat.id,
  title: chat.title,
  agent_id: chat.agent_id,
  message_count: chat.messages.length,
  created_at: "2026-10-03T09:00:00",
  updated_at: "2026-10-03T09:00:00",
  running: chat.running,
  folder_id: chat.folder_id ?? null,
  pinned: chat.pinned ?? false,
});

const event = (sequence: number, body: Record<string, unknown>) =>
  `id: ${sequence}\ndata: ${JSON.stringify({ sequence, ...body })}\n\n`;

/** What the fake agent answers, in the pieces ember_api would stream it. */
export const ANSWER_PIECES = ["The capital ", "of France ", "is Paris."];
export const ANSWER = ANSWER_PIECES.join("");

export async function installFakeApi(page: Page, options: { admin?: boolean } = {}): Promise<FakeApi> {
  const api: FakeApi = {
    settings: { forceToolApproval: false },
    accounts: new Map(),
    capabilities: new Map(),
    roles: new Map(),
    templates: new Map(),
    shares: new Map(),
    unexpected: [],
    turns: [],
    chats: new Map(),
    folders: new Map(),
  };
  const account = options.admin ? ADMIN_ACCOUNT : ACCOUNT;
  if (options.admin) {
    for (const a of ADMIN_ACCOUNTS) api.accounts.set(a.id, { ...a });
    for (const r of ADMIN_ROLES) api.roles.set(r.id, { ...r });
    for (const c of ADMIN_CAPABILITIES) api.capabilities.set(c.name, { ...c });
  }
  let loggedIn = false;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "GET" && path === "/api/auth/me") {
      return loggedIn ? json(route, account) : json(route, { detail: "Not logged in" }, 401);
    }
    if (method === "POST" && path === "/api/auth/login") {
      const body = request.postDataJSON() as { username: string; password: string };
      if (body.username !== ACCOUNT.username || body.password !== PASSWORD) {
        return json(route, { detail: "Wrong username or password" }, 401);
      }
      loggedIn = true;
      return json(route, account);
    }
    if (method === "GET" && path === "/api/settings") {
      return json(route, { force_tool_approval: api.settings.forceToolApproval });
    }
    if (method === "PUT" && path === "/api/admin/settings/force_tool_approval") {
      const { value } = request.postDataJSON() as { value: boolean };
      api.settings.forceToolApproval = value;
      return json(route, { force_tool_approval: value });
    }

    // The Admin page: overview counts, the accounts list and deleting one.
    if (method === "GET" && path === "/api/admin/summary") {
      const all = [...api.accounts.values()];
      return json(route, {
        accounts: all.length,
        unverified: all.filter((a) => !a.email_verified).length,
        disabled: all.filter((a) => !a.is_active).length,
        open_invites: 0,
        roles: api.roles.size,
      });
    }
    if (method === "GET" && path === "/api/admin/accounts") {
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const all = [...api.accounts.values()].filter((a) => !q || `${a.username} ${a.email}`.toLowerCase().includes(q));
      return json(route, all);
    }
    const accountPath = /^\/api\/admin\/accounts\/(\d+)$/.exec(path);
    if (method === "DELETE" && accountPath) {
      const id = Number(accountPath[1]);
      if (!api.accounts.has(id)) return json(route, { detail: "Account not found" }, 404);
      api.accounts.delete(id);
      return route.fulfill({ status: 204, body: "" });
    }
    if (method === "GET" && path === "/api/admin/roles") return json(route, [...api.roles.values()]);
    const rolePath = /^\/api\/admin\/roles\/(\d+)$/.exec(path);
    if (method === "DELETE" && rolePath) {
      if (!api.roles.delete(Number(rolePath[1]))) return json(route, { detail: "Role not found" }, 404);
      return route.fulfill({ status: 204, body: "" });
    }
    if (method === "GET" && path === "/api/admin/permissions") return json(route, ADMIN_PERMISSIONS);
    if (method === "GET" && path === "/api/admin/invites") return json(route, []);
    if (method === "GET" && path === "/api/agent") return json(route, ENTRY_AGENT);
    if (method === "GET" && path === "/api/agents") {
      return json(route, [{ ...ENTRY_AGENT, entry: true, orchestrator: true, focus: "General questions.", status: "running", provider: "anthropic", gateway: null, model: null }]);
    }
    if (method === "GET" && path === "/api/chats") return json(route, [...api.chats.values()].map(summary));
    // Deleting every chat, or one.
    if (method === "DELETE" && path === "/api/chats") {
      api.chats.clear();
      return route.fulfill({ status: 204, body: "" });
    }

    // The Capabilities page: the list, the on/off switch, and (through MCP below) the tools each one offers.
    if (method === "GET" && path === "/api/capabilities") return json(route, [...api.capabilities.values()]);
    const capabilityPath = /^\/api\/capabilities\/([a-z_]+)$/.exec(path);
    if (method === "PATCH" && capabilityPath) {
      const found = api.capabilities.get(capabilityPath[1]!);
      if (!found) return json(route, { detail: "Capability not found" }, 404);
      found.enabled = (request.postDataJSON() as { enabled: boolean }).enabled;
      return json(route, found);
    }
    if (method === "GET" && path === "/api/extensions") return json(route, []);
    if (method === "POST" && path === "/api/mcp/server") return mcpServer(route, api);
    if (method === "GET" && path === "/api/mcp/server") return route.fulfill({ status: 405, body: "" });

    // An account with tools.use also asks for the slash commands; none are offered here.
    if (method === "GET" && path === "/api/commands") return json(route, []);

    // The member's saved prompts: none unless a test adds them.
    if (method === "GET" && path === "/api/templates") return json(route, [...api.templates.values()]);
    const templatePath = /^\/api\/templates\/(\d+)$/.exec(path);
    if (method === "DELETE" && templatePath) {
      if (!api.templates.delete(Number(templatePath[1]))) return json(route, { detail: "Prompt not found" }, 404);
      return route.fulfill({ status: 204, body: "" });
    }

    // Read-only chat links: listing them for one chat, and turning one off.
    if (method === "GET" && path === "/api/shares") {
      const chatId = url.searchParams.get("chat_id");
      return json(route, [...api.shares.values()].filter((s) => !chatId || s.chat_id === chatId));
    }
    const sharePath = /^\/api\/shares\/(\d+)$/.exec(path);
    if (method === "DELETE" && sharePath) {
      if (!api.shares.delete(Number(sharePath[1]))) return json(route, { detail: "Link not found" }, 404);
      return route.fulfill({ status: 204, body: "" });
    }

    // No limits are set, so the sidebar shows no usage gauge.
    if (method === "GET" && path === "/api/usage") return json(route, NO_USAGE);
    if (method === "GET" && path === "/api/usage/records") return json(route, []);

    // The agent's MCP endpoint: only its `status` tool is called by the page.
    if (method === "POST" && path === "/api/mcp/agents/agent-1") return mcpAgent(route);
    // The page also tries to open a notification stream; "not offered" is a valid answer.
    if (method === "GET" && path === "/api/mcp/agents/agent-1") return route.fulfill({ status: 405, body: "" });

    // Chat folders, as ember_api keeps them: names unique per account (any
    // case), and deleting a folder deletes every chat in it, pinned or not.
    if (method === "GET" && path === "/api/chat-folders") {
      return json(route, [...api.folders.values()].map((f) => ({ ...f, chat_count: chatsIn(api, f.id) })));
    }
    if (method === "POST" && path === "/api/chat-folders") {
      const { name } = request.postDataJSON() as { name: string };
      if ([...api.folders.values()].some((f) => f.name.toLowerCase() === name.toLowerCase())) {
        return json(route, { detail: "A folder with that name already exists" }, 409);
      }
      const id = Math.max(0, ...api.folders.keys()) + 1;
      api.folders.set(id, { id, name, position: id });
      return json(route, { id, name, position: id, chat_count: 0 }, 201);
    }
    const folderPath = /^\/api\/chat-folders\/(\d+)$/.exec(path);
    if (folderPath) {
      const id = Number(folderPath[1]);
      const found = api.folders.get(id);
      if (!found) return json(route, { detail: "Folder not found" }, 404);
      if (method === "PATCH") {
        const body = request.postDataJSON() as { name?: string; position?: number };
        if (body.name !== undefined) found.name = body.name;
        if (body.position !== undefined) found.position = body.position;
        return json(route, { ...found, chat_count: chatsIn(api, id) });
      }
      if (method === "DELETE") {
        for (const [chatId, c] of api.chats) if (c.folder_id === id) api.chats.delete(chatId);
        api.folders.delete(id);
        return route.fulfill({ status: 204, body: "" });
      }
    }

    const chatPath = /^\/api\/chats\/([A-Za-z0-9-]+)(\/[a-z]+)?$/.exec(path);
    if (chatPath) {
      const [, id, tail] = chatPath;
      if (method === "PATCH" && !tail) {
        const chat = api.chats.get(id!);
        if (!chat) return json(route, { detail: "Chat not found" }, 404);
        const body = request.postDataJSON() as { title?: string; folder_id?: number | null; pinned?: boolean };
        if (body.title !== undefined) chat.title = body.title;
        if ("folder_id" in body) chat.folder_id = body.folder_id ?? null;
        if (body.pinned !== undefined) chat.pinned = body.pinned;
        return json(route, summary(chat));
      }
      if (method === "DELETE" && !tail) {
        if (!api.chats.delete(id!)) return json(route, { detail: "Chat not found" }, 404);
        return route.fulfill({ status: 204, body: "" });
      }
      if (method === "GET" && !tail) {
        const chat = api.chats.get(id!);
        return chat ? json(route, { ...summary(chat), messages: chat.messages }) : json(route, { detail: "Not found" }, 404);
      }
      if (method === "POST" && tail === "/turns") return startTurn(route, api, id!);
      if (method === "GET" && tail === "/events") return streamTurn(route, api, id!);
    }

    api.unexpected.push(`${method} ${path}`);
    return json(route, { detail: "not part of the fake" }, 404);
  });

  return api;
}

function chatsIn(api: FakeApi, folderId: number): number {
  return [...api.chats.values()].filter((c) => c.folder_id === folderId).length;
}

function startTurn(route: Route, api: FakeApi, id: string) {
  const body = route.request().postDataJSON() as { question: string; title?: string; truncate_to?: number };
  api.turns.push(body);
  // An edited question cuts the chat back to before it (`truncate_to`), as ember_api does.
  const kept = body.truncate_to === undefined ? [] : (api.chats.get(id)?.messages.slice(0, body.truncate_to) ?? []);
  api.chats.set(id, {
    id,
    title: body.title ?? api.chats.get(id)?.title ?? body.question,
    agent_id: ENTRY_AGENT.id, // what ember_api reports: the browser sends no agent
    messages: [...kept, { role: "user", content: body.question }],
    running: true,
  });
  return json(route, { chat: summary(api.chats.get(id)!), sequence: 0 }, 202);
}

/** How long the fake delegated agent keeps working before the stream resumes. */
const DELEGATE_WORKING_MS = 1000;

/** The answer streams in two requests, like a connection that drops and resumes
 * from the last sequence: the first ends with the delegated agent working (so the
 * page shows "Test Agent → Calculator" for a moment), the second finishes it. */
async function streamTurn(route: Route, api: FakeApi, id: string) {
  const chat = api.chats.get(id);
  if (!chat) return json(route, { detail: "No answer is being written for this chat" }, 404);
  const after = Number(new URL(route.request().url()).searchParams.get("after") ?? 0);
  const headers = { "Cache-Control": "no-cache" };
  const sse = (body: string) => route.fulfill({ status: 200, contentType: "text/event-stream", headers, body });

  if (after < 1) {
    return sse(
      event(1, {
        type: "agent_start",
        agent_id: DELEGATE.id,
        agent_label: DELEGATE.label,
        step_id: DELEGATE.step_id,
        at: new Date().toISOString(),
        question: "What is 6 times 7?",
        delegated_by: ENTRY_AGENT.id,
      }),
    );
  }

  await new Promise((resolve) => setTimeout(resolve, DELEGATE_WORKING_MS));
  const answer = {
    role: "assistant",
    content: ANSWER,
    agent: chat.agent_id,
    model: "test-model",
    total_tokens: 120,
    input_tokens: 90,
    output_tokens: 30,
    duration_s: 1.2,
  };
  const body =
    event(2, {
      type: "agent_end",
      agent_id: DELEGATE.id,
      agent_label: DELEGATE.label,
      ok: true,
      step_id: DELEGATE.step_id,
      at: new Date().toISOString(),
    }) +
    ANSWER_PIECES.map((text, i) => event(i + 3, { type: "token", text })).join("") +
    event(ANSWER_PIECES.length + 3, { type: "final", message: answer, cancelled: false });
  // What the page loads once the answer ends: the saved chat, answer included.
  chat.messages = [...chat.messages, answer];
  chat.running = false;
  return sse(body);
}

/** Just enough of MCP over HTTP for the Capabilities page's session with mcp_server: it lists the
 * tools of the capabilities that are on, so switching one changes what the page shows. */
async function mcpServer(route: Route, api: FakeApi) {
  const message = route.request().postDataJSON() as { id?: number; method: string };
  if (message.id === undefined) return route.fulfill({ status: 202, body: "" });
  const tools = [...api.capabilities.values()].filter((c) => c.enabled).flatMap((c) => c.tools);
  let result: unknown = {};
  if (message.method === "initialize") {
    result = { protocolVersion: "2025-06-18", capabilities: { tools: {}, resources: {} }, serverInfo: { name: "fake-server", version: "1" } };
  } else if (message.method === "tools/list") {
    result = { tools: tools.map((name) => ({ name, description: `The ${name} tool.`, inputSchema: { type: "object", properties: {} } })) };
  } else if (message.method === "resources/list") {
    result = { resources: [] };
  } else if (message.method === "resources/templates/list") {
    result = { resourceTemplates: [] };
  }
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "Mcp-Session-Id": "fake-server-session" },
    body: JSON.stringify({ jsonrpc: "2.0", id: message.id, result }),
  });
}

/** Just enough of MCP over HTTP for the page's session with the agent. */
async function mcpAgent(route: Route) {
  const message = route.request().postDataJSON() as { id?: number; method: string };
  if (message.id === undefined) return route.fulfill({ status: 202, body: "" });
  const result =
    message.method === "initialize"
      ? { protocolVersion: "2025-06-18", capabilities: { tools: {} }, serverInfo: { name: "fake-agent", version: "1" } }
      : { content: [{ type: "text", text: JSON.stringify({ available: true }) }], isError: false };
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "Mcp-Session-Id": "fake-session" },
    body: JSON.stringify({ jsonrpc: "2.0", id: message.id, result }),
  });
}
