import { createRouter, createWebHistory, type RouteLocationRaw } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { ADMIN_PAGES, ADMIN_PERMISSIONS, ANALYTICS_PERMISSIONS } from "./pages";

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
    { path: "/", redirect: "/capabilities" },
    { path: "/capabilities", name: "capabilities", component: () => import("../views/CapabilitiesAdminView.vue"), meta: { permission: "capabilities.manage" } },
    { path: "/extensions", name: "extensions", component: () => import("../views/ExtensionsAdminView.vue"), meta: { permission: "extensions.manage" } },
    { path: "/analytics", name: "analytics", component: () => import("../views/AnalyticsView.vue"), meta: { permission: ANALYTICS_PERMISSIONS } },
    { path: "/admin", name: "admin", component: () => import("../views/AdminView.vue"), meta: { permission: ADMIN_PERMISSIONS } },
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
  const home = ADMIN_PAGES.find((p) => allowed(p.permission, auth.hasPermission));
  if (to.meta.guestOnly) return { name: home ? routeName(home.to) : "no-access" };
  const needed = to.meta.permission;
  if (needed && !allowed(needed, auth.hasPermission)) return { name: home ? routeName(home.to) : "no-access" };
  if (to.name === "no-access" && home) return { name: routeName(home.to) };
  return true;
});

function routeName(path: string): string {
  return path.slice(1);
}
