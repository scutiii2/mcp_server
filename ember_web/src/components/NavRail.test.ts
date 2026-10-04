import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import { authClient } from "../api/AuthClient";
import { NAV_PAGES } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import NavRail from "./NavRail.vue";

vi.mock("../api/AuthClient", () => ({ authClient: { logout: vi.fn(() => Promise.resolve()) } }));

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

    // chat.use -> Chat, Extensions, Usage; tools.use -> Tools, Capabilities
    expect(links.map((l) => l.attributes("aria-label"))).toEqual(["Chat", "Tools", "Capabilities", "Extensions", "Usage"]);
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
    await router.push("/tools");
    await flushPromises();

    const current = pageLinks(wrapper).filter((l) => l.classes().includes("router-link-exact-active"));

    expect(current.map((l) => l.attributes("aria-label"))).toEqual(["Tools"]);
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
