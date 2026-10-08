import type { Page, Route } from "@playwright/test";

// Workspace API fixture for the administration scenarios moved out of ember_web.

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
  permissions: ["chat.use", "tools.use", "admin.manage", "extensions.manage"],
};

export const PASSWORD = "correct horse battery";

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

export interface StoredRole {
  id: number;
  name: string;
  description: string | null;
  is_protected: boolean;
  permissions: string[];
  account_count: number;
}

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
const ADMIN_PERMISSIONS = [
  { name: "chat.use", description: "Chat with the agent" },
  { name: "tools.use", description: "Run mcp_server tools" },
  { name: "admin.manage", description: "Manage accounts" },
  { name: "extensions.manage", description: "Add and remove mcp_server extensions (other MCP servers offered to every client)" },
];

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export async function installFakeApi(page: Page) {
  const api = {
    settings: { forceToolApproval: false },
    accounts: new Map(ADMIN_ACCOUNTS.map(a => [a.id, { ...a }])),
    roles: new Map(ADMIN_ROLES.map(r => [r.id, { ...r }])),
    unexpected: [] as string[],
  };
  const account = ADMIN_ACCOUNT;
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
    api.unexpected.push(method + " " + path);
    return json(route, { detail: "not faked" }, 404);
  });
  return api;
}
