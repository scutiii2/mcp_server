/** The pages in the nav rail and on the Overview page, in that order, with
 * the permission each needs (a list: any one of them). One list, so the two
 * can't drift apart. */

// The Analytics page shows whichever log kinds these allow.
export const LOG_PERMISSIONS = ["logs.view", "logs.errors.view", "logs.chat.view"];
// ...and its Traffic tab needs traffic.view; any one of these opens the page.
export const ANALYTICS_PERMISSIONS = [...LOG_PERMISSIONS, "traffic.view"];

/** The alert icon in the nav rail for the Config issues page, which is not
 * one of NAV_PAGES: it shows (and the page opens) only while there are issues. */
export const CONFIG_ISSUES_ICON = ["M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z", "M12 9v4", "M12 17h.01"];

/** Icons for the two tabs of the narrow-screen bar that are not in NAV_PAGES:
 * Overview (it is the wordmark on the rail) and the account's Profile page. */
export const OVERVIEW_ICON = ["M3 3h7v9H3z", "M14 3h7v5h-7z", "M14 12h7v9h-7z", "M3 16h7v5H3z"];
export const PROFILE_ICON = ["M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2", "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z"];

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
    description: "What mcp_server offers: its capabilities and extensions (other MCP servers). Run their tools, read their resources, pick the extensions your chats may use; admins switch capabilities on and off.",
    permission: ["tools.use", "chat.use"],
  },
  {
    to: "/agents",
    label: "Agents",
    icon: ["M12 8V4H8", "M4 10a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z", "M2 14h2", "M20 14h2", "M15 13v2", "M9 13v2"],
    description: "The AI agents behind ember: which are running, which is the entry agent, and what each is for.",
    permission: "chat.use",
  },
  { to: "/watchers", label: "Watchers", icon: ["M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0z", "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z"], description: "Background watchers of every capability.", permission: "watchers.view" },
  { to: "/usage", label: "Usage", icon: ["M3 3v16a2 2 0 0 0 2 2h16", "M18 17V9", "M13 17V5", "M8 17v-3"], description: "Your token usage and limits.", permission: "chat.use" },
  {
    to: "/settings",
    label: "Settings",
    icon: [
      "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
      "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
    ],
    description: "Your chat and appearance preferences, with search and a reset for each; admins also set tool approval.",
    permission: "chat.use",
  },
  { to: "/analytics", label: "Analytics", icon: ["M22 12h-4l-3 9L9 3l-3 9H2"], description: "Charts and entries of activity, errors and chat turns, and network traffic.", permission: ANALYTICS_PERMISSIONS },
  { to: "/admin", label: "Admin", icon: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"], description: "Accounts, roles and invite codes.", permission: "admin.manage" },
];

/** The pages an account with these permissions may open. */
export function visiblePages(hasPermission: (permission: string) => boolean): NavPage[] {
  return NAV_PAGES.filter((p) =>
    Array.isArray(p.permission) ? p.permission.some(hasPermission) : hasPermission(p.permission),
  );
}
