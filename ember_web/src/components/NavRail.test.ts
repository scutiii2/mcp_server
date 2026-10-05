import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import { authClient } from "../api/AuthClient";
import { configIssuesClient } from "../api/ConfigIssuesClient";
import { NAV_PAGES } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import NavRail from "./NavRail.vue";

vi.mock("../api/AuthClient", () => ({ authClient: { logout: vi.fn(() => Promise.resolve()) } }));
vi.mock("../api/ConfigIssuesClient", () => ({ configIssuesClient: { list: vi.fn(() => Promise.resolve([])) } }));

const ACCOUNT: Account = {
  id: 1,
  username: "lex",
  email: "lex@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use", "tools.use"],
};

function setup(account: Account | null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.account = account;
  const stub = { template: "<div />" };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      ...NAV_PAGES.map((p) => ({ path: p.to, component: stub })),
      { path: "/account", component: stub },
      { path: "/config-issues", component: stub },
      { path: "/login", name: "login", component: stub },
    ],
  });
  const wrapper = mount(NavRail, { global: { plugins: [pinia, router] } });
  return { wrapper, router, auth };
}

const pageLinks = (wrapper: ReturnType<typeof setup>["wrapper"]) => wrapper.findAll("nav a");

beforeEach(() => {
  vi.clearAllMocks();
});

describe("NavRail", () => {
  it("shows one icon-only link per page the account may open", () => {
    const { wrapper } = setup(ACCOUNT);

    const links = pageLinks(wrapper);

    // chat.use -> Chat, Extensions, Usage; tools.use -> Capabilities
    expect(links.map((l) => l.attributes("aria-label"))).toEqual(["Chat", "Capabilities", "Extensions", "Usage"]);
    for (const link of links) {
      expect(link.text()).toBe("");
      expect(link.find("svg").exists()).toBe(true);
    }
  });

  it("names each page for the hover tooltip", () => {
    const { wrapper } = setup(ACCOUNT);

    const [chat] = pageLinks(wrapper);

    expect(chat!.attributes("data-label")).toBe("Chat");
    expect(chat!.attributes("href")).toBe("/");
  });

  it("marks the page being viewed", async () => {
    const { wrapper, router } = setup(ACCOUNT);
    await router.push("/capabilities");
    await flushPromises();

    const current = pageLinks(wrapper).filter((l) => l.classes().includes("router-link-exact-active"));

    expect(current.map((l) => l.attributes("aria-label"))).toEqual(["Capabilities"]);
  });

  it("shows no pages while the email still has to be verified", () => {
    const { wrapper } = setup({ ...ACCOUNT, email_verified: false });

    expect(pageLinks(wrapper)).toHaveLength(0);
    expect(wrapper.find(".account").exists()).toBe(true);
  });

  it("shows no pages and no account controls to a visitor", () => {
    const { wrapper } = setup(null);

    expect(pageLinks(wrapper)).toHaveLength(0);
    expect(wrapper.find(".account").exists()).toBe(false);
    expect(wrapper.find("button.logout").exists()).toBe(false);
    expect(wrapper.find("button.theme").exists()).toBe(true);
  });

  describe("config issues alert", () => {
    const VIEWER: Account = { ...ACCOUNT, permissions: [...ACCOUNT.permissions, "config.issues.view"] };
    const issue = (severity: "error" | "warning") => ({ file: "f", key: "k", message: "m", severity });

    it("is hidden while there are no issues", async () => {
      const { wrapper } = setup(VIEWER);
      await flushPromises();

      expect(wrapper.find("a.alert").exists()).toBe(false);
    });

    it("is red and counts every issue when an error exists", async () => {
      vi.mocked(configIssuesClient.list).mockResolvedValueOnce([issue("error"), issue("warning"), issue("warning")]);
      const { wrapper } = setup(VIEWER);
      await flushPromises();

      const alert = wrapper.find("a.alert");
      expect(alert.classes()).toContain("has-errors");
      expect(alert.find(".count").text()).toBe("3");
      expect(alert.attributes("aria-label")).toBe("Config issues: 1 error, 2 warnings");
      expect(alert.attributes("href")).toBe("/config-issues");
    });

    it("is amber when only warnings exist", async () => {
      vi.mocked(configIssuesClient.list).mockResolvedValueOnce([issue("warning")]);
      const { wrapper } = setup(VIEWER);
      await flushPromises();

      expect(wrapper.find("a.alert").classes()).toContain("has-warnings");
    });

    it("is never asked for by an account without the permission", async () => {
      const { wrapper } = setup(ACCOUNT);
      await flushPromises();

      expect(configIssuesClient.list).not.toHaveBeenCalled();
      expect(wrapper.find("a.alert").exists()).toBe(false);
    });
  });

  it("links the account page by username and logs out to the login page", async () => {
    const { wrapper, router, auth } = setup(ACCOUNT);

    const account = wrapper.find(".account");
    expect(account.attributes("href")).toBe("/account");
    expect(account.attributes("aria-label")).toContain("lex");

    await wrapper.find("button.logout").trigger("click");
    await flushPromises();

    expect(authClient.logout).toHaveBeenCalled();
    expect(auth.account).toBeNull();
    expect(router.currentRoute.value.name).toBe("login");
  });
});
