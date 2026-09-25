import { createRouter, createWebHistory, type RouteLocationRaw } from "vue-router";
import { useAuthStore } from "../stores/auth";
import ChatView from "../views/ChatView.vue";

declare module "vue-router" {
  interface RouteMeta {
    /** Reachable without logging in (login, register). */
    guestOnly?: boolean;
    /** The ember_api permission the page needs. */
    permission?: string;
    /** Open to any logged-in account, verified or not (the Account page,
     * so a mistyped email can be fixed). */
    anyAccount?: boolean;
  }
}

// Pages a logged-in, verified user may land on, in order of preference.
const HOME_PAGES: { name: string; permission: string }[] = [
  { name: "chat", permission: "chat.use" },
  { name: "tools", permission: "tools.use" },
  { name: "admin", permission: "admin.manage" },
];

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "chat", component: ChatView, meta: { permission: "chat.use" } },
    // Lazy: each of these loads its own chunk only when first opened.
    {
      path: "/tools",
      name: "tools",
      component: () => import("../views/ToolsView.vue"),
      meta: { permission: "tools.use" },
    },
    {
      path: "/admin",
      name: "admin",
      component: () => import("../views/AdminView.vue"),
      meta: { permission: "admin.manage" },
    },
    {
      path: "/account",
      name: "account",
      component: () => import("../views/AccountView.vue"),
      meta: { anyAccount: true },
    },
    { path: "/login", name: "login", component: () => import("../views/LoginView.vue"), meta: { guestOnly: true } },
    {
      path: "/register",
      name: "register",
      component: () => import("../views/RegisterView.vue"),
      meta: { guestOnly: true },
    },
    { path: "/verify-email", name: "verify-email", component: () => import("../views/VerifyEmailView.vue") },
    { path: "/no-access", name: "no-access", component: () => import("../views/NoAccessView.vue") },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

// Access rules. ember_api enforces every one of these itself; the guard only
// keeps the UI from showing pages whose calls would be refused.
router.beforeEach(async (to): Promise<true | RouteLocationRaw> => {
  const auth = useAuthStore();
  await auth.ensureLoaded();
  const account = auth.account;

  if (!account) {
    return to.meta.guestOnly ? true : { name: "login", query: to.fullPath === "/" ? {} : { redirect: to.fullPath } };
  }
  if (!account.email_verified) {
    return to.name === "verify-email" || to.meta.anyAccount ? true : { name: "verify-email" };
  }

  const home = HOME_PAGES.find((p) => auth.hasPermission(p.permission));
  if (to.meta.guestOnly || to.name === "verify-email") {
    return { name: home?.name ?? "no-access" };
  }
  if (to.meta.permission && !auth.hasPermission(to.meta.permission)) {
    return { name: home?.name ?? "no-access" };
  }
  if (to.name === "no-access" && home) return { name: home.name };
  return true;
});
