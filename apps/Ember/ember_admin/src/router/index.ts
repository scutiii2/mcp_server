import { createRouter, createWebHistory, type RouteLocationRaw } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { ADMIN_PAGES, ADMIN_PERMISSIONS, ADMIN_SECTIONS, ANALYTICS_PERMISSIONS } from "./pages";

declare module "vue-router" {
  interface RouteMeta {
    /** Reachable without logging in (login). */
    guestOnly?: boolean;
    /** The ember_api permission the page needs; a list = any one of them. */
    permission?: string | string[];
  }
}

function allowed(needed: string | string[], has: (p: string) => boolean): boolean {
  return Array.isArray(needed) ? needed.some(has) : has(needed);
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/admin" },
    { path: "/profile", name: "profile", component: () => import("../views/ProfileView.vue") },
    { path: "/account", redirect: "/profile" },
    { path: "/settings", name: "settings", component: () => import("../views/SettingsView.vue") },
    { path: "/verify-email", name: "verify-email", component: () => import("../views/VerifyEmailView.vue") },
    { path: "/capabilities", name: "capabilities", component: () => import("../views/CapabilitiesAdminView.vue"), meta: { permission: "capabilities.manage" } },
    { path: "/extensions", name: "extensions", component: () => import("../views/ExtensionsAdminView.vue"), meta: { permission: "extensions.manage" } },
    { path: "/agents", name: "agents", component: () => import("../views/AgentsAdminView.vue"), meta: { permission: "agents.manage" } },
    { path: "/analytics", name: "analytics", component: () => import("../views/AnalyticsView.vue"), meta: { permission: ANALYTICS_PERMISSIONS } },
    { path: "/usage", name: "usage", component: () => import("../views/UsageView.vue"), meta: { permission: "usage.all.view" } },
    {
      path: "/admin", component: () => import("../views/AdminView.vue"), meta: { permission: ADMIN_PERMISSIONS },
      children: [
        { path: "", name: "admin", component: () => import("../views/AdminOverviewView.vue") },
        { path: "accounts", name: "admin-accounts", component: () => import("../views/AccountsAdminView.vue"), meta: { permission: ADMIN_SECTIONS[1]!.permission } },
        { path: "roles", name: "admin-roles", component: () => import("../views/RolesAdminView.vue"), meta: { permission: ADMIN_SECTIONS[2]!.permission } },
        { path: "invites", name: "admin-invites", component: () => import("../views/InvitesAdminView.vue"), meta: { permission: "invites.manage" } },
        { path: "settings", name: "admin-settings", component: () => import("../views/WorkspaceSettingsView.vue"), meta: { permission: "settings.manage" } },
      ],
    },
    { path: "/login", name: "login", component: () => import("../views/LoginView.vue"), meta: { guestOnly: true } },
    { path: "/no-access", name: "no-access", component: () => import("../views/NoAccessView.vue") },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

// ember_api enforces every permission itself; the guard keeps the UI from
// showing pages whose calls would be refused.
router.beforeEach(async (to): Promise<true | RouteLocationRaw> => {
  const auth = useAuthStore();
  await auth.ensureLoaded();
  if (!auth.account) {
    return to.meta.guestOnly ? true : { name: "login", query: to.fullPath === "/" ? {} : { redirect: to.fullPath } };
  }
  if (auth.needsVerification && !["profile", "verify-email", "settings"].includes(String(to.name))) {
    return { name: "verify-email" };
  }
  if (to.name === "admin") {
    const section = ADMIN_SECTIONS.find((s) => s.to === `/admin/${String(to.query.tab)}`);
    if (section) {
      const { tab: _tab, ...query } = to.query;
      return { path: section.to, query, hash: to.hash };
    }
  }
  const home = ADMIN_PAGES.find((p) => allowed(p.permission, auth.hasPermission));
  if (to.meta.guestOnly) return { path: home?.to ?? "/no-access" };
  const needed = to.meta.permission;
  if (needed && !allowed(needed, auth.hasPermission)) return { path: home?.to ?? "/no-access" };
  if (to.name === "no-access" && home) return { path: home.to };
  return true;
});
