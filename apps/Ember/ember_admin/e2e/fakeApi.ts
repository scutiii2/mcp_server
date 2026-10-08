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
    if (pathname === "/api/auth/me") return json(route, ADMIN_ACCOUNT);
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
