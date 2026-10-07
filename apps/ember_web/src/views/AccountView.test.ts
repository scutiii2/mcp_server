import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { authClient, type KnownDevice } from "../api/AuthClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { useAuthStore } from "../stores/auth";
import AccountView from "./AccountView.vue";

vi.mock("../api/AuthClient", () => ({ authClient: { devices: vi.fn(), forgetDevice: vi.fn() } }));

const client = vi.mocked(authClient);

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const device = (id: number, label: string, current = false): KnownDevice => ({
  id,
  label,
  user_agent: "UA",
  ip_subnet: "10.0.0.0/24",
  first_seen_at: "2026-10-01T10:00:00",
  last_seen_at: "2026-10-05T10:00:00",
  current,
});

async function mountView(devices: KnownDevice[]) {
  setActivePinia(createPinia());
  useAuthStore().account = {
    id: 1,
    username: "maria",
    email: "maria@example.com",
    email_verified: true,
    roles: ["Member"],
    permissions: ["chat.use"],
  };
  client.devices.mockResolvedValue(devices);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/", component: { render: () => null } }] });
  const wrapper = mount(AccountView, { global: { plugins: [router] } });
  await flushPromises();
  return wrapper;
}

const forgetButtons = (wrapper: Awaited<ReturnType<typeof mountView>>) => wrapper.findAll("button.forget");

beforeEach(() => vi.clearAllMocks());

describe("AccountView", () => {
  it("shows the account identity, security, access and remembered devices", async () => {
    const wrapper = await mountView([]);

    expect(wrapper.findAll("section.card").map((s) => s.get("h3").text())).toEqual(["Security", "Roles & access", "Remembered devices"]);
    expect(wrapper.get(".profile .name").text()).toBe("maria");
    expect(wrapper.get(".avatar").text()).toBe("M");
    expect(wrapper.get(".profile .chip.ok").text()).toBe("Email verified");
    expect(wrapper.get(".roles").text()).toBe("Member");
  });

  it("folds the permissions away behind a count", async () => {
    const wrapper = await mountView([]);

    expect(wrapper.get(".permissions summary").text()).toBe("1 permission");
    expect(wrapper.get(".perm-list").text()).toBe("chat.use");
  });

  it("shows no banner for a verified email", async () => {
    const wrapper = await mountView([]);

    expect(wrapper.find(".banner").exists()).toBe(false);
  });

  it("shows paused permissions and an unverified status when verification is required", async () => {
    const wrapper = await mountView([]);
    useAuthStore().account!.email_verified = false;
    await flushPromises();

    expect(wrapper.get(".profile-status").text()).toContain("Verification needed");
    expect(wrapper.get(".banner").text()).toContain("Permissions are paused");
    expect(wrapper.get(".permissions").text()).toContain("inactive until your email is verified");
    expect(wrapper.find(".profile .chip.ok").exists()).toBe(false);
  });

  it("keeps optional verification distinct from paused access", async () => {
    const wrapper = await mountView([]);
    Object.assign(useAuthStore().account!, { email_verified: false, email_verification_required: false });
    await flushPromises();

    expect(wrapper.get(".profile-status").text()).toContain("Verification optional");
    expect(wrapper.get(".banner").text()).toContain("Verifying it is optional");
    expect(wrapper.get(".permissions").text()).not.toContain("inactive");
  });

  it("opens one security form at a time, and closes it again", async () => {
    const wrapper = await mountView([]);
    expect(wrapper.find("form").exists()).toBe(false);

    await wrapper.get(".toggle-email").trigger("click");
    expect(wrapper.findAll("form")).toHaveLength(1);
    expect(wrapper.get("form").text()).toContain("New email");
    expect(wrapper.get(".toggle-email").text()).toBe("Close");
    expect(wrapper.get(".toggle-email").attributes("aria-expanded")).toBe("true");

    await wrapper.get(".toggle-password").trigger("click");
    expect(wrapper.findAll("form")).toHaveLength(1);
    expect(wrapper.get("form").text()).toContain("New password");

    await wrapper.get(".toggle-password").trigger("click");
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("asks before forgetting a device, and forgets nothing when cancelled", async () => {
    const wrapper = await mountView([device(1, "Chrome on Windows", true), device(2, "Safari on iPhone")]);
    expect(forgetButtons(wrapper)).toHaveLength(1);

    await forgetButtons(wrapper)[0]!.trigger("click");

    expect(wrapper.getComponent(ConfirmModal).props("message")).toContain("Forget Safari on iPhone?");
    await wrapper.getComponent(ConfirmModal).get(".cancel").trigger("click");
    expect(wrapper.findComponent(ConfirmModal).exists()).toBe(false);
    expect(client.forgetDevice).not.toHaveBeenCalled();
  });

  it("forgets the device once confirmed and drops it from the list", async () => {
    client.forgetDevice.mockResolvedValue(undefined);
    const wrapper = await mountView([device(1, "Chrome on Windows", true), device(2, "Safari on iPhone")]);

    await forgetButtons(wrapper)[0]!.trigger("click");
    await wrapper.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(client.forgetDevice).toHaveBeenCalledExactlyOnceWith(2);
    expect(wrapper.findAll(".devices li")).toHaveLength(1);
    expect(wrapper.get(".device-count").text()).toBe("1 device");
    expect(wrapper.findComponent(ConfirmModal).exists()).toBe(false);
  });
});
