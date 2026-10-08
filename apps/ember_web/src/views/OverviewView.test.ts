import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import { NAV_PAGES } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import OverviewView from "./OverviewView.vue";

function setup(permissions: string[], emailVerified = true) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  const account: Account = {
    id: 1, username: "ada", email: "ada@example.com", email_verified: emailVerified,
    roles: [], permissions,
  };
  auth.account = account;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [...NAV_PAGES.map((p) => ({ path: p.to, component: { template: "<div />" } })),
      { path: "/account", component: { template: "<div />" } }],
  });
  const wrapper = mount(OverviewView, { global: { plugins: [pinia, router] } });
  return { wrapper, auth, router };
}

describe("OverviewView", () => {
  it("only offers permitted pages, with real links and an account shortcut", async () => {
    const { wrapper, router } = setup(["chat.use"]);
    expect(wrapper.find(".primary").attributes("href")).toBe("/");
    expect(wrapper.findAll(".card").map((link) => link.attributes("href"))).toEqual([
      "/agents", "/capabilities", "/usage", "/settings", "/account",
    ]);
    expect(wrapper.text()).toContain("Signed in as ada");
    await wrapper.find('.card[href="/capabilities"]').trigger("click");
    await router.isReady();
    expect(router.currentRoute.value.path).toBe("/capabilities");
  });

  it("hides chat and empty groups without permissions, while keeping Account", async () => {
    const { wrapper, auth } = setup([]);
    expect(wrapper.find(".hero").exists()).toBe(false);
    expect(wrapper.find("#work-heading").exists()).toBe(false);
    expect(wrapper.find("#monitor-heading").exists()).toBe(false);
    expect(wrapper.findAll(".card").map((link) => link.attributes("href"))).toEqual(["/account"]);
    expect(wrapper.text()).toContain("Your role gives you no pages yet");
    auth.account = { ...auth.account!, permissions: ["traffic.view", "admin.manage"] };
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll(".card").map((link) => link.attributes("href"))).toEqual([
      "/account",
    ]);
    expect(wrapper.find(".hero").exists()).toBe(false);
  });

  it("does not offer permission-gated actions to unverified accounts", () => {
    const { wrapper } = setup(["chat.use", "tools.use", "watchers.view", "traffic.view", "admin.manage"], false);
    expect(wrapper.find(".hero").exists()).toBe(false);
    expect(wrapper.findAll(".card").map((link) => link.attributes("href"))).toEqual(["/account"]);
  });
});
