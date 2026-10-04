/** The pages in the nav rail and on the Overview page, in that order, with
 * the permission each needs (a list: any one of them). One list, so the two
 * can't drift apart. */

// The Logs page shows whichever of its tabs these allow.
export const LOG_PERMISSIONS = ["logs.view", "logs.errors.view", "logs.chat.view"];

export interface NavPage {
  to: string;
  label: string;
  /** SVG path data (24x24, stroked) drawn as the page's icon in the nav rail. */
  icon: string[];
  /** One line for the Overview page. */
  description: string;
  permission: string | string[];
}

export const NAV_PAGES: NavPage[] = [
  { to: "/", label: "Chat", icon: ["M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"], description: "Ask an AI agent; it can use mcp_server's tools.", permission: "chat.use" },
  {
    to: "/capabilities",
    label: "Capabilities",
    icon: ["m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z", "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65", "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"],
    description: "What mcp_server offers, by capability: run its tools, read its resources; admins switch capabilities on and off.",
    permission: "tools.use",
  },
  {
    to: "/extensions",
    label: "Extensions",
    icon: ["M12 22v-5", "M9 8V2", "M15 8V2", "M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"],
    description: "Other MCP servers behind mcp_server; pick the ones your chats may use.",
    permission: "chat.use",
  },
  { to: "/watchers", label: "Watchers", icon: ["M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0z", "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z"], description: "Background watchers of every capability.", permission: "watchers.view" },
  { to: "/usage", label: "Usage", icon: ["M3 3v16a2 2 0 0 0 2 2h16", "M18 17V9", "M13 17V5", "M8 17v-3"], description: "Your token usage and limits.", permission: "chat.use" },
  { to: "/logs", label: "Logs", icon: ["M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z", "M14 2v4a2 2 0 0 0 2 2h4", "M10 9H8", "M16 13H8", "M16 17H8"], description: "Activity, errors and chat turns.", permission: LOG_PERMISSIONS },
  { to: "/config-issues", label: "Config", icon: ["M3 7h2", "M9 7h12", "M3 17h10", "M17 17h4", "M9 7a2 2 0 1 1-4 0 2 2 0 0 1 4 0z", "M17 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0z"], description: "Problems in ember_api's config and secret files.", permission: "config.issues.view" },
  { to: "/admin", label: "Admin", icon: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"], description: "Accounts, roles and invite codes.", permission: "admin.manage" },
];

/** The pages an account with these permissions may open. */
export function visiblePages(hasPermission: (permission: string) => boolean): NavPage[] {
  return NAV_PAGES.filter((p) =>
    Array.isArray(p.permission) ? p.permission.some(hasPermission) : hasPermission(p.permission),
  );
}
