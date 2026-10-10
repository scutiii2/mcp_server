import type { Page, Route } from "@playwright/test";

/** A stand-in for ember_api: answers the calls the admin app makes, so the
 * built app runs in a real browser without ember_api or mcp_server. Any call
 * not listed is recorded in `unexpected`, and the test fails on it. */

export const ADMIN_ACCOUNT = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: ["Administrator"],
  permissions: ["chat.use", "tools.view", "tools.execute", "files.upload", "files.download", "accounts.view", "accounts.manage", "accounts.delete", "roles.view", "roles.manage", "roles.assign", "invites.manage", "settings.manage", "capabilities.manage", "usage.all.view", "extensions.manage", "logs.view", "traffic.view"],
};

export interface FakeCapability {
  name: string;
  enabled: boolean;
  label: string;
  tools: string[];
  resources: string[];
  has_gui: boolean;
  load_error: string | null;
  missing: boolean;
  loaded: boolean;
}

export interface FakeState {
  permissions?: string[];
  usageFailure?: boolean;
  usageAgent?: string;
  capabilities: FakeCapability[];
  /** Folders a Refresh will discover. */
  discoverable: FakeCapability[];
  /** Names whose next "online" fails. */
  failing: Set<string>;
  unexpected: string[];
}

export function newState(): FakeState {
  const cap = (name: string, over: Partial<FakeCapability> = {}): FakeCapability => ({
    name, enabled: true, label: name[0].toUpperCase() + name.slice(1), tools: [`tool_${name}_run`], resources: [],
    has_gui: false, load_error: null, missing: false, loaded: true, ...over,
  });
  return {
    capabilities: [cap("vault"), cap("gen")],
    discoverable: [cap("fresh", { enabled: false, loaded: false, tools: [] })],
    failing: new Set(["fresh"]),
    unexpected: [],
  };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export async function installFakeApi(page: Page, state: FakeState): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();

    if (pathname === "/api/commands/help" && method === "GET") return json(route, { capabilities: state.capabilities.map((c) => ({ capability: `/${c.name}`, summary: `Explore the tools provided by ${c.label}.` })) });
    if (pathname === "/api/commands" && method === "GET") return json(route, []);
    if (pathname === "/api/auth/me") return json(route, { ...ADMIN_ACCOUNT, permissions: state.permissions ?? ADMIN_ACCOUNT.permissions });
    if (method === "GET" && pathname === "/api/admin/usage") return json(route, [
      { account_id: 2, username: "alice", tokens: 123, turns: 1, last_used_at: null },
      { account_id: 3, username: "bob", tokens: 456, turns: 2, last_used_at: null },
      { account_id: 4, username: "empty", tokens: 0, turns: 0, last_used_at: null },
    ]);
    const usage = pathname.match(/^\/api\/admin\/usage\/(\d+)(\/records)?$/);
    if (method === "GET" && usage) {
      const id = Number(usage[1]);
      const tokens = id === 2 ? 123 : id === 3 ? 456 : 0;
      const agent = state.usageAgent ?? `agent-${id}`;
      const today = new Date().toISOString().slice(0, 10);
      if (usage[2]) return json(route, tokens ? [{ id, turn_id: `turn-${id}`, kind: "chat", chat_id: null,
        agent, agent_id: agent, provider_id: "provider", gateway: null, model: "claude-3-5-sonnet-20241022",
        input_tokens: tokens, output_tokens: 0, total_tokens: tokens, started_at: null, finished_at: null,
        delegated_by: null, created_at: `${today}T12:00:00` }] : []);
      if (state.usageFailure) return json(route, { detail: "Report unavailable" }, 503);
      const query = new URL(request.url()).searchParams;
      const group = query.get("group_by") ?? "agent";
      return json(route, {
        six_hour: { used: tokens, limit: 1000, reset_at: null }, weekly: { used: tokens, limit: 0, reset_at: null },
        report: { days: Number(query.get("days") ?? 30), since: `${today}T00:00:00`, total_tokens: tokens,
          input_tokens: tokens, output_tokens: 0, summary_tokens: 0, turns: tokens ? 1 : 0, chats: tokens ? 1 : 0,
          by_agent: tokens ? [{ agent, model: "claude-3-5-sonnet-20241022", tokens }] : [],
          daily: tokens ? [{ date: today, tokens }] : [], hourly: Array(24).fill(0), group_by: group,
          groups: tokens ? [{ key: group === "agent" ? agent : group === "model" ? "claude-3-5-sonnet-20241022" : group, tokens, input_tokens: tokens, output_tokens: 0, turns: 1 }] : [],
        },
      });
    }
    if (pathname === "/api/capabilities" && method === "GET") return json(route, state.capabilities);
    if (pathname === "/api/capabilities/refresh" && method === "POST") {
      for (const found of state.discoverable) if (!state.capabilities.some((c) => c.name === found.name)) state.capabilities.push(found);
      return json(route, state.capabilities);
    }
    const patch = pathname.match(/^\/api\/capabilities\/([^/]+)$/);
    if (patch && method === "PATCH") {
      const name = decodeURIComponent(patch[1]);
      const target = state.capabilities.find((c) => c.name === name);
      const { enabled } = request.postDataJSON() as { enabled: boolean };
      if (!target) return json(route, { detail: `Unknown capability '${name}'` }, 404);
      if (enabled && state.failing.has(name)) {
        target.load_error = "RuntimeError: boom in tool.py";
        return json(route, { detail: "RuntimeError: boom in tool.py" }, 400);
      }
      target.enabled = enabled;
      if (enabled) { target.loaded = true; target.load_error = null; target.tools = [`tool_${name}_run`]; }
      return json(route, target);
    }
    if (pathname === "/api/extensions" && method === "GET") return json(route, []);

    state.unexpected.push(`${method} ${pathname}`);
    return json(route, { detail: "not faked" }, 404);
  });
}
