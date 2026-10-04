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
}

export interface FakeApi {
  /** Requests that no handler knew, as "METHOD /path". */
  unexpected: string[];
  /** The bodies of the questions the page sent, as JSON. */
  turns: Record<string, unknown>[];
  chats: Map<string, StoredChat>;
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
});

const event = (sequence: number, body: Record<string, unknown>) =>
  `id: ${sequence}\ndata: ${JSON.stringify({ sequence, ...body })}\n\n`;

/** What the fake agent answers, in the pieces ember_api would stream it. */
export const ANSWER_PIECES = ["The capital ", "of France ", "is Paris."];
export const ANSWER = ANSWER_PIECES.join("");

export async function installFakeApi(page: Page): Promise<FakeApi> {
  const api: FakeApi = { unexpected: [], turns: [], chats: new Map() };
  let loggedIn = false;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "GET" && path === "/api/auth/me") {
      return loggedIn ? json(route, ACCOUNT) : json(route, { detail: "Not logged in" }, 401);
    }
    if (method === "POST" && path === "/api/auth/login") {
      const body = request.postDataJSON() as { username: string; password: string };
      if (body.username !== ACCOUNT.username || body.password !== PASSWORD) {
        return json(route, { detail: "Wrong username or password" }, 401);
      }
      loggedIn = true;
      return json(route, ACCOUNT);
    }
    if (method === "GET" && path === "/api/settings") return json(route, { force_tool_approval: false });
    if (method === "GET" && path === "/api/agent") return json(route, ENTRY_AGENT);
    if (method === "GET" && path === "/api/chats") return json(route, [...api.chats.values()].map(summary));

    // No limits are set, so the sidebar shows no usage gauge.
    if (method === "GET" && path === "/api/usage") return json(route, NO_USAGE);
    if (method === "GET" && path === "/api/usage/records") return json(route, []);

    // The agent's MCP endpoint: only its `status` tool is called by the page.
    if (method === "POST" && path === "/api/mcp/agents/agent-1") return mcpAgent(route);
    // The page also tries to open a notification stream; "not offered" is a valid answer.
    if (method === "GET" && path === "/api/mcp/agents/agent-1") return route.fulfill({ status: 405, body: "" });

    const chatPath = /^\/api\/chats\/([A-Za-z0-9-]+)(\/[a-z]+)?$/.exec(path);
    if (chatPath) {
      const [, id, tail] = chatPath;
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

function startTurn(route: Route, api: FakeApi, id: string) {
  const body = route.request().postDataJSON() as { question: string; title?: string };
  api.turns.push(body);
  api.chats.set(id, {
    id,
    title: body.title ?? body.question,
    agent_id: ENTRY_AGENT.id, // what ember_api reports: the browser sends no agent
    messages: [{ role: "user", content: body.question }],
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
