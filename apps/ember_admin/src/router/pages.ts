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

export const ADMIN_PAGES: AdminPage[] = [
  { to: "/capabilities", label: "Capabilities", icon: ["m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z", "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65", "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"], permission: "capabilities.manage" },
  { to: "/extensions", label: "Extensions", icon: ["M12 2v6", "M8 8h8v4a4 4 0 0 1-8 0z", "M12 16v6"], permission: "extensions.manage" },
  { to: "/analytics", label: "Analytics", icon: ["M22 12h-4l-3 9L9 3l-3 9H2"], permission: ANALYTICS_PERMISSIONS },
  { to: "/admin", label: "Admin", icon: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"], permission: ADMIN_PERMISSIONS },
];
