import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { adminClient } from "../api/AdminClient";
import { ApiError } from "../api/http";
import AdminView from "./AdminView.vue";

vi.mock("../api/AdminClient", () => ({ adminClient: { summary: vi.fn() } }));
vi.mock("../components/admin/AccountsPanel.vue", () => ({ default: { template: "<div>accounts panel</div>" } }));
vi.mock("../components/admin/RolesPanel.vue", () => ({ default: { template: "<div>roles panel</div>" } }));
vi.mock("../components/admin/InvitesPanel.vue", () => ({ default: { template: "<div>invites panel</div>" } }));
vi.mock("../components/admin/SettingsPanel.vue", () => ({ default: { template: "<div>settings panel</div>" } }));

const client = vi.mocked(adminClient);
const SUMMARY = { accounts: 24, unverified: 3, disabled: 1, open_invites: 5, roles: 2 };

async function view() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/admin", component: AdminView }] });
  await router.push("/admin");
  const wrapper = mount(AdminView, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  vi.clearAllMocks();
  client.summary.mockResolvedValue(SUMMARY);
});

describe("AdminView", () => {
  it("shows the overview counts above the tabs", async () => {
    const { wrapper } = await view();

    expect(wrapper.findAll(".stats .tile").map((t) => t.text())).toEqual([
      "Accounts24",
      "Unverified3",
      "Disabled1",
      "Open invites5",
    ]);
  });

  it("reads the counts again when the tab changes", async () => {
    const { wrapper, router } = await view();
    expect(client.summary).toHaveBeenCalledTimes(1);

    await router.replace({ query: { tab: "roles" } });
    await flushPromises();

    expect(client.summary).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("roles panel");
  });

  it("keeps the tabs usable when the overview cannot load", async () => {
    client.summary.mockRejectedValue(new ApiError(500, "boom"));
    const { wrapper } = await view();

    expect(wrapper.text()).toContain("boom");
    expect(wrapper.text()).toContain("accounts panel");
  });
});
