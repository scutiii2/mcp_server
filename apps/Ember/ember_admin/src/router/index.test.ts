import { createPinia, setActivePinia } from "pinia";
import { beforeEach, expect, it, vi } from "vitest";
import { authClient } from "../api/AuthClient";
import { router } from "./index";

vi.mock("../api/AuthClient", () => ({ authClient: { me: vi.fn() } }));

beforeEach(() => {
  setActivePinia(createPinia());
  vi.mocked(authClient.me).mockResolvedValue({ id: 1, username: "viewer", email: "v@example.com", email_verified: true, roles: [], permissions: ["roles.view"] });
});

it("allows a role viewer directly into the roles page, but redirects accounts and settings", async () => {
  await router.push("/");
  expect(router.currentRoute.value.name).toBe("admin");
  await router.push("/admin/roles");
  expect(router.currentRoute.value.name).toBe("admin-roles");
  await router.push("/admin/accounts");
  expect(router.currentRoute.value.name).toBe("admin");
  await router.push("/admin/settings");
  expect(router.currentRoute.value.name).toBe("admin");
});

it("opens the overview for an extension-only account", async () => {
  vi.mocked(authClient.me).mockResolvedValue({ id: 3, username: "extensions", email: "e@example.com", email_verified: true, roles: [], permissions: ["extensions.manage"] });
  await router.replace({ path: "/", force: true });
  expect(router.currentRoute.value.name).toBe("admin");
});

it("preserves query options while redirecting old tab links", async () => {
  await router.push("/admin?tab=roles&source=bookmark#member");
  expect(router.currentRoute.value.fullPath).toBe("/admin/roles?source=bookmark#member");
});

it("checks permissions after redirecting an old settings tab", async () => {
  await router.push("/admin?tab=settings&source=bookmark");
  expect(router.currentRoute.value.name).toBe("admin");
  expect(router.currentRoute.value.query.tab).toBeUndefined();
});

it("allows an invitation manager without account or role grants", async () => {
  vi.mocked(authClient.me).mockResolvedValue({ id: 2, username: "inviter", email: "i@example.com", email_verified: true, roles: [], permissions: ["invites.manage"] });
  await router.push("/admin/invites");
  expect(router.currentRoute.value.name).toBe("admin-invites");
  await router.push("/admin/roles");
  expect(router.currentRoute.value.name).toBe("admin");
});

it("preserves a direct child URL through login", async () => {
  vi.mocked(authClient.me).mockRejectedValue(new Error("Not logged in"));
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  await router.push("/admin/accounts?status=unverified");
  expect(router.currentRoute.value.name).toBe("login");
  expect(router.currentRoute.value.query.redirect).toBe("/admin/accounts?status=unverified");
  warn.mockRestore();
});

it("allows personal pages without workspace permissions", async () => {
  vi.mocked(authClient.me).mockResolvedValue({ id: 4, username: "member", email: "m@example.com", email_verified: true, roles: [], permissions: [] });
  await router.replace({ path: "/profile", force: true });
  expect(router.currentRoute.value.name).toBe("profile");
  await router.push("/settings");
  expect(router.currentRoute.value.name).toBe("settings");
});

it("lets an unverified account recover through Profile and verification", async () => {
  vi.mocked(authClient.me).mockResolvedValue({ id: 5, username: "pending", email: "p@example.com", email_verified: false, roles: [], permissions: ["roles.view"] });
  await router.replace({ path: "/profile", force: true });
  expect(router.currentRoute.value.name).toBe("profile");
  await router.push("/verify-email");
  expect(router.currentRoute.value.name).toBe("verify-email");
  await router.push("/admin/roles");
  expect(router.currentRoute.value.name).toBe("verify-email");
});

it("opens Usage and its overview for a usage-only observer", async () => {
  vi.mocked(authClient.me).mockResolvedValue({ id: 4, username: "observer", email: "o@example.com", email_verified: true, roles: [], permissions: ["usage.all.view"] });
  await router.push("/");
  expect(router.currentRoute.value.name).toBe("admin");
  await router.push("/usage");
  expect(router.currentRoute.value.name).toBe("usage");
});
it("denies Usage without the usage permission", async () => {
  await router.replace({ path: "/usage", force: true });
  expect(router.currentRoute.value.name).toBe("admin");
});
