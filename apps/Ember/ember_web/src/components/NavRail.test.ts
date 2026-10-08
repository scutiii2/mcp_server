import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import { authClient } from "../api/AuthClient";
import { configIssuesClient } from "../api/ConfigIssuesClient";
import { navPreferencesClient, type NavPrefs } from "../api/NavPreferencesClient";
import { NAV_PAGES } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import NavRail from "./NavRail.vue";

vi.mock("../api/AuthClient", () => ({ authClient: { logout: vi.fn(() => Promise.resolve()) } }));
vi.mock("../api/NavPreferencesClient", () => ({
  navPreferencesClient: { get: vi.fn(() => Promise.resolve({ order: [], pinned: [], hidden: [] })) },
}));
vi.mock("../api/ConfigIssuesClient", () => ({ configIssuesClient: { list: vi.fn(() => Promise.resolve([])) } }));

const ACCOUNT: Account = {
  id: 1,
  username: "lex",
  email: "lex@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use", "tools.view", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"],
};

async function setup(account: Account | null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.account = account;
  const stub = { template: "<div />" };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      ...NAV_PAGES.map((p) => ({ path: p.to, component: stub })),
      { path: "/capabilities/:name", name: "capability-page", component: stub },
      { path: "/account", component: stub },
      { path: "/overview", component: stub },
      { path: "/config-issues", component: stub },
      { path: "/login", name: "login", component: stub },
    ],
  });
  const wrapper = mount(NavRail, { global: { plugins: [pinia, router] } });
  await flushPromises(); // the arrangement loads first
  return { wrapper, router, auth };
}

const pageLinks = (wrapper: Awaited<ReturnType<typeof setup>>["wrapper"]) => wrapper.findAll("nav.pages a");

beforeEach(() => {
  vi.clearAllMocks();
});

describe("NavRail", () => {
  it("shows one icon-only link per page the account may open", async () => {
    const { wrapper } = await setup(ACCOUNT);

    const links = pageLinks(wrapper);

    // chat.use -> Chat, Agents, Usage, Settings; tools.view or chat.use -> Capabilities
    expect(links.map((l) => l.attributes("aria-label"))).toEqual(["Chat", "Capabilities", "Agents", "Usage", "Settings"]);
    for (const link of links) {
      expect(link.text()).toBe("");
      expect(link.find("svg").exists()).toBe(true);
    }
  });

  it("names each page for the hover tooltip", async () => {
    const { wrapper } = await setup(ACCOUNT);

    const [chat] = pageLinks(wrapper);

    expect(chat!.attributes("data-label")).toBe("Chat");
    expect(chat!.attributes("href")).toBe("/");
  });

  it("marks the page being viewed", async () => {
    const { wrapper, router } = await setup(ACCOUNT);
    await router.push("/capabilities");
    await flushPromises();

    const current = pageLinks(wrapper).filter((l) => l.classes().includes("router-link-exact-active"));

    expect(current.map((l) => l.attributes("aria-label"))).toEqual(["Capabilities"]);
  });

  it("keeps Capabilities marked while one of its pages is open", async () => {
    const { wrapper, router } = await setup(ACCOUNT);
    await router.push("/capabilities/pdf");
    await flushPromises();

    const current = pageLinks(wrapper).filter((l) => l.classes().includes("current"));

    expect(current.map((l) => l.attributes("aria-label"))).toEqual(["Capabilities"]);
  });

  it("shows no pages while the email still has to be verified", async () => {
    const { wrapper } = await setup({ ...ACCOUNT, email_verified: false });

    expect(pageLinks(wrapper)).toHaveLength(0);
    expect(wrapper.find(".account").exists()).toBe(true);
  });

  it("shows no pages and no account controls to a visitor", async () => {
    const { wrapper } = await setup(null);

    expect(pageLinks(wrapper)).toHaveLength(0);
    expect(wrapper.find(".account").exists()).toBe(false);
    expect(wrapper.find("button.logout").exists()).toBe(false);
    expect(wrapper.find("button.theme").exists()).toBe(true);
  });

  describe("the narrow-screen tab bar", () => {
    const tabLinks = (wrapper: Awaited<ReturnType<typeof setup>>["wrapper"]) => wrapper.findAll("nav.tabs a");

    it("has five fixed tabs, Chat in the middle", async () => {
      const { wrapper } = await setup(ACCOUNT);

      const labels = tabLinks(wrapper).map((l) => l.attributes("aria-label"));

      // Chat is drawn last (it floats over the middle gap); the rest read left to right.
      expect(labels).toEqual(["Overview", "Capabilities", "Usage", "Profile", "Chat"]);
      expect(wrapper.find("nav.tabs .gap").exists()).toBe(true);
      expect(wrapper.find("nav.tabs a.chat").attributes("href")).toBe("/");
    });

    it("marks the two tabs beside Chat", async () => {
      const { wrapper } = await setup(ACCOUNT);

      expect(wrapper.find("nav.tabs a.near-l").attributes("aria-label")).toBe("Capabilities");
      expect(wrapper.find("nav.tabs a.near-r").attributes("aria-label")).toBe("Usage");
    });

    it("drops the tabs the account may not open but keeps Overview and Profile", async () => {
      const { wrapper } = await setup({ ...ACCOUNT, permissions: [] });

      expect(tabLinks(wrapper).map((l) => l.attributes("aria-label"))).toEqual(["Overview", "Profile"]);
    });

    it("keeps Chat marked while a chat is open by id", async () => {
      const { wrapper, router } = await setup(ACCOUNT);
      router.addRoute({ path: "/chat/:id", name: "chat-id", component: { template: "<div />" } });
      await router.push("/chat/7");
      await flushPromises();

      expect(wrapper.find("nav.tabs a.chat").classes()).toContain("current");
    });

    it("is absent for a visitor", async () => {
      const { wrapper } = await setup(null);

      expect(wrapper.find("nav.tabs").exists()).toBe(false);
    });
  });

  describe("config issues alert", () => {
    const VIEWER: Account = { ...ACCOUNT, permissions: [...ACCOUNT.permissions, "config.issues.view"] };
    const issue = (severity: "error" | "warning") => ({ file: "f", key: "k", message: "m", severity });

    it("is hidden while there are no issues", async () => {
      const { wrapper } = await setup(VIEWER);
      await flushPromises();

      expect(wrapper.find("a.alert").exists()).toBe(false);
    });

    it("is red and counts every issue when an error exists", async () => {
      vi.mocked(configIssuesClient.list).mockResolvedValueOnce([issue("error"), issue("warning"), issue("warning")]);
      const { wrapper } = await setup(VIEWER);
      await flushPromises();

      const alert = wrapper.find("a.alert");
      expect(alert.classes()).toContain("has-errors");
      expect(alert.find(".count").text()).toBe("3");
      expect(alert.attributes("aria-label")).toBe("Config issues: 1 error, 2 warnings");
      expect(alert.attributes("href")).toBe("/config-issues");
    });

    it("is amber when only warnings exist", async () => {
      vi.mocked(configIssuesClient.list).mockResolvedValueOnce([issue("warning")]);
      const { wrapper } = await setup(VIEWER);
      await flushPromises();

      expect(wrapper.find("a.alert").classes()).toContain("has-warnings");
    });

    it("is never asked for by an account without the permission", async () => {
      const { wrapper } = await setup(ACCOUNT);
      await flushPromises();

      expect(configIssuesClient.list).not.toHaveBeenCalled();
      expect(wrapper.find("a.alert").exists()).toBe(false);
    });
  });

  describe("the account's arrangement", () => {
    const arrangement = (prefs: NavPrefs) => vi.mocked(navPreferencesClient.get).mockResolvedValueOnce(prefs);
    const labels = (wrapper: Awaited<ReturnType<typeof setup>>["wrapper"]) => pageLinks(wrapper).map((l) => l.attributes("aria-label"));

    it("puts pinned pages first, then a divider, then the rest", async () => {
      arrangement({ order: ["/usage", "/agents"], pinned: ["/usage"], hidden: [] });
      const { wrapper } = await setup(ACCOUNT);

      expect(labels(wrapper)).toEqual(["Usage", "Agents", "Chat", "Capabilities", "Settings"]);
      expect(wrapper.findAll("nav .divider")).toHaveLength(1);
      expect(wrapper.find("nav.pages").element.children[1]!.classList.contains("divider")).toBe(true);
    });

    it("leaves hidden pages out", async () => {
      arrangement({ order: [], pinned: [], hidden: ["/agents", "/usage"] });
      const { wrapper } = await setup(ACCOUNT);

      expect(labels(wrapper)).toEqual(["Chat", "Capabilities", "Settings"]);
      expect(wrapper.find("nav .divider").exists()).toBe(false);
    });

    it("draws no pages until the arrangement has loaded", async () => {
      let release: (prefs: NavPrefs) => void = () => {};
      vi.mocked(navPreferencesClient.get).mockReturnValueOnce(new Promise((resolve) => (release = resolve)));
      const { wrapper } = await setup(ACCOUNT);
      expect(pageLinks(wrapper)).toHaveLength(0);

      release({ order: [], pinned: [], hidden: [] });
      await flushPromises();

      expect(pageLinks(wrapper)).toHaveLength(5);
    });
  });

  it("links the account page by username and logs out to the login page", async () => {
    const { wrapper, router, auth } = await setup(ACCOUNT);

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

it("offers Ember Admin to delegated admins and hides it for members and unverified accounts", async () => {
  const { wrapper, auth } = await setup(ACCOUNT);
  expect(wrapper.find(".admin-link").exists()).toBe(false);
  auth.account = { ...ACCOUNT, permissions: ["roles.view"] };
  await flushPromises();
  expect(wrapper.get(".admin-link").attributes("href")).toBe("http://localhost:5176/");
  expect(wrapper.get(".admin-link").attributes("target")).toBe("_blank");
  expect(wrapper.get(".admin-link").attributes("rel")).toBe("noopener noreferrer");
  auth.account = { ...auth.account, email_verified: false };
  await flushPromises();
  expect(wrapper.find(".admin-link").exists()).toBe(false);
});
