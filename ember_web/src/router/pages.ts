/** The pages in the top bar and on the Overview page, in that order, with
 * the permission each needs (a list: any one of them). One list, so the two
 * can't drift apart. */

// The Logs page shows whichever of its tabs these allow.
export const LOG_PERMISSIONS = ["logs.view", "logs.errors.view", "logs.chat.view"];

export interface NavPage {
  to: string;
  label: string;
  /** One line for the Overview page. */
  description: string;
  permission: string | string[];
}

export const NAV_PAGES: NavPage[] = [
  { to: "/", label: "Chat", description: "Ask an AI agent; it can use mcp_server's tools.", permission: "chat.use" },
  { to: "/tools", label: "Tools", description: "Run mcp_server's tools and browse its resources.", permission: "tools.use" },
  {
    to: "/capabilities",
    label: "Capabilities",
    description: "What each built-in capability offers; admins switch them on and off.",
    permission: "tools.use",
  },
  {
    to: "/extensions",
    label: "Extensions",
    description: "Other MCP servers behind mcp_server; pick the ones your chats may use.",
    permission: "chat.use",
  },
  { to: "/watchers", label: "Watchers", description: "Background watchers of every capability.", permission: "watchers.view" },
  { to: "/usage", label: "Usage", description: "Your token usage and limits.", permission: "chat.use" },
  { to: "/logs", label: "Logs", description: "Activity, errors and chat turns.", permission: LOG_PERMISSIONS },
  { to: "/config-issues", label: "Config", description: "Problems in ember_api's config and secret files.", permission: "config.issues.view" },
  { to: "/admin", label: "Admin", description: "Accounts, roles and invite codes.", permission: "admin.manage" },
];

/** The pages an account with these permissions may open. */
export function visiblePages(hasPermission: (permission: string) => boolean): NavPage[] {
  return NAV_PAGES.filter((p) =>
    Array.isArray(p.permission) ? p.permission.some(hasPermission) : hasPermission(p.permission),
  );
}
