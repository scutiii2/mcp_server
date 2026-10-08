/** Permissions that open a page in Ember Admin, including delegated administrators. */
export const ADMIN_ACCESS_PERMISSIONS = [
  "accounts.view", "accounts.manage", "accounts.delete", "roles.view", "roles.manage", "roles.assign",
  "invites.manage", "settings.manage", "capabilities.manage", "extensions.manage",
  "logs.view", "logs.errors.view", "logs.chat.view", "traffic.view",
];

/** Override for hosted deployments; otherwise use the admin port on this host. */
export function emberAdminUrl(current = window.location.href, configured = import.meta.env.VITE_EMBER_ADMIN_URL): string {
  if (configured) {
    try {
      const url = new URL(configured, current);
      if (["http:", "https:"].includes(url.protocol)) return url.href;
    } catch { /* Invalid deployment URL: use the default below. */ }
  }
  const url = new URL(current);
  url.port = "5176";
  url.pathname = "/";
  url.search = url.hash = "";
  return url.href;
}
