import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { adminClient, type AdminAccount, type Role } from "../../api/AdminClient";
import { ApiError } from "../../api/http";
import { useAuthStore } from "../../stores/auth";
import AccountsPanel from "./AccountsPanel.vue";
import ConfirmModal from "./ConfirmModal.vue";

vi.mock("../../api/AdminClient", () => ({
  adminClient: {
    listAccounts: vi.fn(),
    listRoles: vi.fn(),
    updateAccount: vi.fn(),
    deleteAccount: vi.fn(),
    assignRole: vi.fn(),
    removeRole: vi.fn(),
    sendVerification: vi.fn(),
  },
}));

const client = vi.mocked(adminClient);

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const ROLES: Role[] = [
  { id: 1, name: "Administrator", description: null, is_protected: true, permissions: [], account_count: 1 },
  { id: 2, name: "Member", description: null, is_protected: false, permissions: [], account_count: 2 },
];

function account(id: number, username: string, extra: Partial<AdminAccount> = {}): AdminAccount {
  return {
    id,
    username,
    email: `${username}@mail.com`,
    email_verified: true,
    is_active: true,
    is_protected: false,
    created_at: "2026-09-12T10:00:00",
    roles: [{ id: 2, name: "Member" }],
    ...extra,
  };
}

const ADMIN = account(1, "admin", { is_protected: true, roles: [{ id: 1, name: "Administrator" }] });
const MARIA = account(2, "maria", { email_verified: false });
const LI = account(3, "li", { is_active: false });

async function panel() {
  const wrapper = mount(AccountsPanel);
  await flushPromises();
  return wrapper;
}

type Panel = Awaited<ReturnType<typeof panel>>;

const rowFor = (wrapper: Panel, name: string) => wrapper.findAll("tbody tr").find((r) => r.text().includes(name))!;
const drawer = (wrapper: Panel) => wrapper.find("aside.drawer");
const confirmDialog = (wrapper: Panel) => wrapper.getComponent(ConfirmModal);
const clickIn = (root: { findAll: Panel["findAll"] }, label: string) =>
  root.findAll("button").find((b) => b.text() === label)!.trigger("click");

beforeEach(() => {
  vi.clearAllMocks();
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "admin", email: "admin@mail.com", email_verified: true, roles: [], permissions: ["accounts.view", "accounts.manage", "accounts.delete", "roles.view", "roles.manage", "roles.assign", "chat.use", "tools.view"] };
  client.listAccounts.mockResolvedValue([ADMIN, MARIA, LI]);
  client.listRoles.mockResolvedValue(ROLES);
});

afterEach(() => vi.useRealTimers());

describe("AccountsPanel", () => {
  it("lists accounts with their roles and status", async () => {
    const wrapper = await panel();

    expect(wrapper.findAll("tbody tr")).toHaveLength(3);
    expect(rowFor(wrapper, "admin").text()).toContain("you");
    expect(rowFor(wrapper, "admin").text()).toContain("protected");
    expect(rowFor(wrapper, "maria").text()).toContain("unverified");
    expect(rowFor(wrapper, "li").text()).toContain("disabled");
    expect(rowFor(wrapper, "maria").text()).toContain("Member");
    expect(client.listAccounts).toHaveBeenCalledWith({ q: "", status: "all" });
  });

  it("shows an empty message when nothing matches", async () => {
    client.listAccounts.mockResolvedValue([]);

    expect((await panel()).text()).toContain("No accounts match.");
  });

  it("shows an error when the list cannot be read", async () => {
    client.listAccounts.mockRejectedValue(new ApiError(500, "boom"));

    expect((await panel()).text()).toContain("boom");
  });

  it("searches after the typing pauses", async () => {
    vi.useFakeTimers();
    const wrapper = await panel();
    client.listAccounts.mockClear();

    await wrapper.get('input[aria-label="Search accounts"]').setValue("mar");
    await vi.advanceTimersByTimeAsync(100);
    expect(client.listAccounts).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(200);
    expect(client.listAccounts).toHaveBeenCalledTimes(1);
    expect(client.listAccounts).toHaveBeenCalledWith({ q: "mar", status: "all" });
  });

  it("filters by status", async () => {
    const wrapper = await panel();

    await clickIn(wrapper, "Unverified");
    await flushPromises();

    expect(client.listAccounts).toHaveBeenLastCalledWith({ q: "", status: "unverified" });
  });

  it("loads bookmark filters and follows updates from browser navigation", async () => {
    const wrapper = mount(AccountsPanel, { props: { filters: { q: 'mar', status: 'unverified' } } });
    await flushPromises();
    expect(client.listAccounts).toHaveBeenLastCalledWith({ q: 'mar', status: 'unverified' });
    await wrapper.setProps({ filters: { q: '', status: 'disabled' } });
    await flushPromises();
    expect(client.listAccounts).toHaveBeenLastCalledWith({ q: '', status: 'disabled' });
    expect(wrapper.emitted('filter')?.at(-1)).toEqual([{ q: '', status: 'disabled' }]);
  });

  it("ignores a slow answer to an older search", async () => {
    vi.useFakeTimers();
    const wrapper = await panel();
    let releaseOld!: (rows: AdminAccount[]) => void;
    client.listAccounts.mockReturnValueOnce(new Promise((resolve) => (releaseOld = resolve)));
    client.listAccounts.mockResolvedValueOnce([MARIA]);

    await clickIn(wrapper, "Unverified");
    await clickIn(wrapper, "Disabled");
    await flushPromises();
    releaseOld([ADMIN]);
    await flushPromises();

    expect(wrapper.findAll("tbody tr").map((r) => r.text())).toEqual([expect.stringContaining("maria")]);
  });

  it("opens the drawer for the clicked account and closes it again", async () => {
    const wrapper = await panel();
    expect(drawer(wrapper).exists()).toBe(false);

    await rowFor(wrapper, "maria").trigger("click");
    expect(drawer(wrapper).attributes("aria-label")).toBe("Account maria");

    await wrapper.get('dialog[aria-label="Account maria"] button[aria-label="Close"]').trigger("click");
    expect(drawer(wrapper).exists()).toBe(false);
  });

  it("gives the drawer the roles that can still be added", async () => {
    const wrapper = await panel();

    await rowFor(wrapper, "maria").trigger("click");

    expect(drawer(wrapper).findAll("select option").map((o) => o.text())).toEqual(["+ Add role", "Administrator"]);
  });

  it("assigns a role chosen in the drawer", async () => {
    client.assignRole.mockResolvedValue({ ...MARIA, roles: [...MARIA.roles, { id: 1, name: "Administrator" }] });
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await drawer(wrapper).get("select").setValue("1");
    await flushPromises();

    expect(client.assignRole).toHaveBeenCalledWith(2, 1);
    expect(rowFor(wrapper, "maria").text()).toContain("Administrator");
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("asks before removing a role, and removes it once confirmed", async () => {
    client.removeRole.mockResolvedValue({ ...MARIA, roles: [] });
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await drawer(wrapper).get(".chip-x").trigger("click");
    expect(confirmDialog(wrapper).props("open")).toBe(true);
    expect(confirmDialog(wrapper).props("message")).toBe("Remove role 'Member' from 'maria'?");
    expect(client.removeRole).not.toHaveBeenCalled();

    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(client.removeRole).toHaveBeenCalledWith(2, 2);
    expect(confirmDialog(wrapper).props("open")).toBe(false);
    expect(rowFor(wrapper, "maria").text()).toContain("No roles");
  });

  it("asks before disabling and does nothing when the question is cancelled", async () => {
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await drawer(wrapper).get('input[role="switch"]').setValue(!(drawer(wrapper).get('input[role="switch"]').element as HTMLInputElement).checked);
    expect(confirmDialog(wrapper).props("message")).toContain("Disable 'maria'?");

    await confirmDialog(wrapper).get(".cancel").trigger("click");

    expect(confirmDialog(wrapper).props("open")).toBe(false);
    expect(client.updateAccount).not.toHaveBeenCalled();
  });

  it("disables an account once confirmed", async () => {
    client.updateAccount.mockResolvedValue({ ...MARIA, is_active: false });
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await drawer(wrapper).get('input[role="switch"]').setValue(!(drawer(wrapper).get('input[role="switch"]').element as HTMLInputElement).checked);
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(client.updateAccount).toHaveBeenCalledWith(2, { is_active: false });
    expect(rowFor(wrapper, "maria").text()).toContain("disabled");
  });

  it("enables a disabled account without asking", async () => {
    client.updateAccount.mockResolvedValue({ ...LI, is_active: true });
    const wrapper = await panel();
    await rowFor(wrapper, "li").trigger("click");

    await drawer(wrapper).get('input[role="switch"]').setValue(!(drawer(wrapper).get('input[role="switch"]').element as HTMLInputElement).checked);
    await flushPromises();

    expect(confirmDialog(wrapper).props("open")).toBe(false);
    expect(client.updateAccount).toHaveBeenCalledWith(3, { is_active: true });
  });

  it("deletes an account once confirmed, then closes the drawer", async () => {
    client.deleteAccount.mockResolvedValue(undefined);
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await clickIn(drawer(wrapper), "Delete account");
    expect(confirmDialog(wrapper).props("message")).toContain("Delete 'maria' permanently?");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    expect(client.deleteAccount).not.toHaveBeenCalled();
    await confirmDialog(wrapper).get(".require input").setValue("maria");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(client.deleteAccount).toHaveBeenCalledWith(2);
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);
    expect(drawer(wrapper).exists()).toBe(false);
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("saves edited details", async () => {
    client.updateAccount.mockResolvedValue({ ...MARIA, email: "new@mail.com" });
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await clickIn(drawer(wrapper), "Edit details");
    await drawer(wrapper).get('input[aria-label="Email"]').setValue("new@mail.com");
    await drawer(wrapper).get("form").trigger("submit");
    await flushPromises();

    expect(client.updateAccount).toHaveBeenCalledWith(2, { email: "new@mail.com" });
    expect(rowFor(wrapper, "maria").text()).toContain("new@mail.com");
  });

  it("sends a verification email and says so", async () => {
    client.sendVerification.mockResolvedValue({ sent: true });
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await clickIn(drawer(wrapper), "Send verification");
    await flushPromises();

    expect(client.sendVerification).toHaveBeenCalledWith(2);
    expect(drawer(wrapper).text()).toContain("Verification email sent to maria@mail.com.");
  });

  it("shows a failed action in the drawer and leaves the row alone", async () => {
    client.updateAccount.mockRejectedValue(new ApiError(409, "Email 'x@y.z' is already in use"));
    const wrapper = await panel();
    await rowFor(wrapper, "maria").trigger("click");

    await clickIn(drawer(wrapper), "Edit details");
    await drawer(wrapper).get('input[aria-label="Email"]').setValue("x@y.z");
    await drawer(wrapper).get("form").trigger("submit");
    await flushPromises();

    expect(drawer(wrapper).get(".error").text()).toContain("already in use");
    expect(rowFor(wrapper, "maria").text()).toContain("maria@mail.com");
    expect(wrapper.emitted("changed")).toBeUndefined();
  });
});
