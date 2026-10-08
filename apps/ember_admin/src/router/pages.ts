/** The pages of the admin app, in nav order, with the permission each needs
 * (a list: any one of them). One list, so the nav and the router cannot drift. */

// The Analytics page shows whichever log kinds these allow.
export const LOG_PERMISSIONS = ["logs.view", "logs.errors.view", "logs.chat.view"];
// ...and its Traffic tab needs traffic.view; any one of these opens the page.
export const ANALYTICS_PERMISSIONS = [...LOG_PERMISSIONS, "traffic.view"];

export interface AdminPage {
  to: string;
  label: string;
  /** SVG path data (24x24, stroked) drawn as the page's icon. */
  icon: string[];
  permission: string | string[];
}

export const ADMIN_PERMISSIONS = ["accounts.view", "accounts.manage", "accounts.delete", "roles.view", "roles.manage", "roles.assign", "invites.manage", "settings.manage"];

/** Administration destinations share their permission rules with nested routes. */
export const ADMIN_SECTIONS: AdminPage[] = [
  { to: "/admin", label: "Overview", icon: ["m3 10 9-7 9 7v11h-7v-7h-4v7H3z"], permission: ADMIN_PERMISSIONS },
  { to: "/admin/accounts", label: "Accounts", icon: ["M3 21v-3a5 5 0 0 1 5-5h3a5 5 0 0 1 5 5v3M20 21v-3a5 5 0 0 0-3-4", "M13.5 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0"], permission: ["accounts.view", "accounts.manage", "accounts.delete", "roles.assign"] },
  { to: "/admin/roles", label: "Roles & permissions", icon: ["M12 3 3 7v5c0 5 5 8 9 10 4-2 9-5 9-10V7zM8 12l3 3 5-6"], permission: ["roles.view", "roles.manage", "roles.assign"] },
  { to: "/admin/invites", label: "Invites", icon: ["M3 5h18v14H3zM3 5l9 8 9-8"], permission: "invites.manage" },
  { to: "/admin/settings", label: "Workspace settings", icon: ["M4 6h3M11 6h9M4 12h9M17 12h3M4 18h5M13 18h7", "M11 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0M17 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0M13 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0"], permission: "settings.manage" },
];

export const ADMIN_PAGES: AdminPage[] = [
  { to: "/capabilities", label: "Capabilities", icon: ["m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z", "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65", "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"], permission: "capabilities.manage" },
  { to: "/extensions", label: "Extensions", icon: ["M12 2v6", "M8 8h8v4a4 4 0 0 1-8 0z", "M12 16v6"], permission: "extensions.manage" },
  { to: "/analytics", label: "Analytics", icon: ["M22 12h-4l-3 9L9 3l-3 9H2"], permission: ANALYTICS_PERMISSIONS },
  { to: "/admin", label: "Admin", icon: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"], permission: ADMIN_PERMISSIONS },
];
