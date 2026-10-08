import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, expect, it } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import AdminNav from "./AdminNav.vue";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.style.colorScheme = "";
});

async function show(permissions: string[] | null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  if (permissions) auth.account = { id: 1, username: "ada", email: "ada@example.com", email_verified: true, roles: [], permissions };
  const router = createRouter({ history: createMemoryHistory(), routes: ["/", "/capabilities", "/extensions", "/analytics", "/admin"].map(path => ({ path, component: { template: "<div />" } })) });
  await router.push("/admin");
  const w = mount(AdminNav, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return w;
}

it("names icon-only links and marks the current page", async () => {
  const w = await show(["admin.manage"]);
  const links = w.findAll("nav[aria-label='Admin sections'] a");
  expect(links.map(a => a.attributes("aria-label"))).toEqual(["Capabilities", "Extensions", "Admin"]);
  expect(links.every(a => a.text() === "" && a.find("svg").exists())).toBe(true);
  expect(w.get("a[aria-label='Admin']").attributes("aria-current")).toBe("page");
});

it("lets an extension manager reach Extensions without offering other pages", async () => {
  const w = await show(["extensions.manage"]);
  expect(w.findAll("nav[aria-label='Admin sections'] a").map(a => a.attributes("aria-label"))).toEqual(["Extensions"]);
});

it("lets visitors cycle and save their theme", async () => {
  const w = await show(null);
  expect(w.find("nav[aria-label='Admin sections']").exists()).toBe(false);
  const button = w.get("button[aria-label^='Theme:']");
  await button.trigger("click");
  expect(document.documentElement.style.colorScheme).toBe("light");
  expect(localStorage.getItem("ember_admin.theme")).toBe("light");
  await button.trigger("click");
  expect(document.documentElement.style.colorScheme).toBe("dark");
  await button.trigger("click");
  expect(document.documentElement.style.colorScheme).toBe("light dark");
});
