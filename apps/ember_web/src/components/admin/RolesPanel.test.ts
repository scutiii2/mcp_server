import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { adminClient, type PermissionInfo, type Role } from "../../api/AdminClient";
import { ApiError } from "../../api/http";
import { useAuthStore } from "../../stores/auth";
import BaseModal from "../BaseModal.vue";
import ConfirmModal from "./ConfirmModal.vue";
import RolesPanel from "./RolesPanel.vue";

vi.mock("../../api/AdminClient", () => ({
  adminClient: {
    listRoles: vi.fn(),
    listPermissions: vi.fn(),
    createRole: vi.fn(),
    updateRole: vi.fn(),
    deleteRole: vi.fn(),
    grantPermission: vi.fn(),
    revokePermission: vi.fn(),
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

const PERMISSIONS: PermissionInfo[] = [
  { name: "chat.use", description: "Chat with the agent" },
  { name: "admin.manage", description: "Manage accounts" },
];

const ADMIN: Role = {
  id: 1,
  name: "Administrator",
  description: null,
  is_protected: true,
  permissions: ["chat.use", "admin.manage"],
  account_count: 1,
};
const MEMBER: Role = {
  id: 2,
  name: "Member",
  description: "Default role",
  is_protected: false,
  permissions: ["chat.use"],
  account_count: 3,
};
const OPS: Role = { id: 3, name: "Ops", description: null, is_protected: false, permissions: [], account_count: 0 };

async function panel() {
  const wrapper = mount(RolesPanel);
  await flushPromises();
  return wrapper;
}

type Panel = Awaited<ReturnType<typeof panel>>;

const editor = (wrapper: Panel) => wrapper.find("section.editor");
const listItem = (wrapper: Panel, name: string) =>
  wrapper.findAll("nav button.role").find((b) => b.text().includes(name))!;
const confirmDialog = (wrapper: Panel) => wrapper.getComponent(ConfirmModal);
const createDialog = (wrapper: Panel) => wrapper.getComponent(BaseModal);
const clickIn = (root: { findAll: Panel["findAll"] }, label: string) =>
  root.findAll("button").find((b) => b.text() === label)!.trigger("click");

beforeEach(() => {
  vi.clearAllMocks();
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "admin", email: "admin@mail.com", email_verified: true, roles: ["Administrator"], permissions: [] };
  client.listRoles.mockResolvedValue([ADMIN, MEMBER, OPS]);
  client.listPermissions.mockResolvedValue(PERMISSIONS);
});

describe("RolesPanel", () => {
  it("lists the roles with their account counts and opens the first", async () => {
    const wrapper = await panel();

    // One text per child span: name, optional badge, count.
    const parts = (name: string) => listItem(wrapper, name).findAll("span").map((s) => s.text());
    expect(parts("Administrator")).toEqual(["Administrator", "protected", "1 account"]);
    expect(parts("Member")).toEqual(["Member", "3 accounts"]);
    expect(parts("Ops")).toEqual(["Ops", "0 accounts"]);
    expect(editor(wrapper).attributes("aria-label")).toBe("Role Administrator");
  });

  it("shows another role when it is clicked", async () => {
    const wrapper = await panel();

    await listItem(wrapper, "Member").trigger("click");

    expect(editor(wrapper).attributes("aria-label")).toBe("Role Member");
    expect(listItem(wrapper, "Member").attributes("aria-pressed")).toBe("true");
  });

  it("shows an error when the roles cannot be read", async () => {
    client.listRoles.mockRejectedValue(new ApiError(500, "boom"));
    const wrapper = await panel();

    expect(wrapper.text()).toContain("boom");
    expect(editor(wrapper).exists()).toBe(false);
  });

  it("grants a permission and shows the switch on", async () => {
    client.grantPermission.mockResolvedValue({ ...MEMBER, permissions: ["chat.use", "admin.manage"] });
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await editor(wrapper).get('input[aria-label="admin.manage"]').trigger("click");
    await flushPromises();

    expect(client.grantPermission).toHaveBeenCalledWith(2, "admin.manage");
    const box = editor(wrapper).get('input[aria-label="admin.manage"]').element as HTMLInputElement;
    expect(box.checked).toBe(true);
  });

  it("shows Saved after a permission change, and clears it on another role", async () => {
    client.grantPermission.mockResolvedValue({ ...MEMBER, permissions: ["chat.use", "admin.manage"] });
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");
    expect(editor(wrapper).find(".chip.saved").exists()).toBe(false);

    await editor(wrapper).get('input[aria-label="admin.manage"]').trigger("click");
    await flushPromises();
    expect(editor(wrapper).get(".chip.saved").text()).toBe("Saved");

    await listItem(wrapper, "Ops").trigger("click");
    expect(editor(wrapper).find(".chip.saved").exists()).toBe(false);
  });

  it("revokes a permission", async () => {
    client.revokePermission.mockResolvedValue({ ...MEMBER, permissions: [] });
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await editor(wrapper).get('input[aria-label="chat.use"]').trigger("click");
    await flushPromises();

    expect(client.revokePermission).toHaveBeenCalledWith(2, "chat.use");
  });

  it("shows the server's refusal and leaves the switch as it was", async () => {
    client.revokePermission.mockRejectedValue(new ApiError(409, "That would remove your own admin access"));
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await editor(wrapper).get('input[aria-label="chat.use"]').trigger("click");
    await flushPromises();

    expect(editor(wrapper).get(".error").text()).toContain("own admin access");
    expect((editor(wrapper).get('input[aria-label="chat.use"]').element as HTMLInputElement).checked).toBe(true);
  });

  it("re-reads the logged-in account when a role it holds changes", async () => {
    const auth = useAuthStore();
    const refresh = vi.spyOn(auth, "refresh").mockResolvedValue();
    client.updateRole.mockResolvedValue({ ...ADMIN, description: "Everything" });
    const wrapper = await panel();

    await clickIn(editor(wrapper), "Edit description");
    await editor(wrapper).get('input[aria-label="Description"]').setValue("Everything");
    await editor(wrapper).get("form").trigger("submit");
    await flushPromises();

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not re-read the account for a role it does not hold", async () => {
    const auth = useAuthStore();
    const refresh = vi.spyOn(auth, "refresh").mockResolvedValue();
    client.grantPermission.mockResolvedValue({ ...MEMBER, permissions: ["chat.use", "admin.manage"] });
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await editor(wrapper).get('input[aria-label="admin.manage"]').trigger("click");
    await flushPromises();

    expect(refresh).not.toHaveBeenCalled();
  });

  it("saves an edited description", async () => {
    client.updateRole.mockResolvedValue({ ...MEMBER, description: "Everyone" });
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await clickIn(editor(wrapper), "Edit details");
    await editor(wrapper).get('input[aria-label="Description"]').setValue("Everyone");
    await editor(wrapper).get("form").trigger("submit");
    await flushPromises();

    expect(client.updateRole).toHaveBeenCalledWith(2, { description: "Everyone" });
    expect(editor(wrapper).text()).toContain("Everyone");
  });

  it("creates a role, keeps the list sorted, and opens the new role", async () => {
    client.createRole.mockResolvedValue({ id: 4, name: "Auditors", description: null, is_protected: false, permissions: [], account_count: 0 });
    const wrapper = await panel();

    await clickIn(wrapper, "+ New role");
    expect(createDialog(wrapper).props("open")).toBe(true);
    await wrapper.get('form.create input[aria-label="Role name"]').setValue(" Auditors ");
    await wrapper.get("form.create").trigger("submit");
    await flushPromises();

    expect(client.createRole).toHaveBeenCalledWith("Auditors", null);
    expect(wrapper.findAll("nav button.role").map((b) => b.find(".role-name").text())).toEqual([
      "Administrator",
      "Auditors",
      "Member",
      "Ops",
    ]);
    expect(editor(wrapper).attributes("aria-label")).toBe("Role Auditors");
    expect(createDialog(wrapper).props("open")).toBe(false);
  });

  it("keeps the create dialog open and shows why it failed", async () => {
    client.createRole.mockRejectedValue(new ApiError(409, "Role name 'Ops' is already in use"));
    const wrapper = await panel();

    await clickIn(wrapper, "+ New role");
    await wrapper.get('form.create input[aria-label="Role name"]').setValue("Ops");
    await wrapper.get("form.create").trigger("submit");
    await flushPromises();

    expect(createDialog(wrapper).props("open")).toBe(true);
    expect(wrapper.get("form.create .error").text()).toContain("already in use");
  });

  it("asks before deleting, naming how many accounts lose the role", async () => {
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await clickIn(editor(wrapper), "Delete role");

    expect(confirmDialog(wrapper).props("open")).toBe(true);
    expect(confirmDialog(wrapper).props("message")).toBe("Delete role 'Member'? It is removed from 3 accounts.");
    expect(client.deleteRole).not.toHaveBeenCalled();
  });

  it("makes you type the role name before deleting a role that accounts hold", async () => {
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");
    await clickIn(editor(wrapper), "Delete role");

    expect(confirmDialog(wrapper).props("requireText")).toBe("Member");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    expect(client.deleteRole).not.toHaveBeenCalled();
  });

  it("asks for no typing when no account holds the role", async () => {
    const wrapper = await panel();
    await listItem(wrapper, "Ops").trigger("click");
    await clickIn(editor(wrapper), "Delete role");

    expect(confirmDialog(wrapper).props("requireText")).toBe("");
  });

  it("does nothing when the delete question is cancelled", async () => {
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");
    await clickIn(editor(wrapper), "Delete role");

    await confirmDialog(wrapper).get(".cancel").trigger("click");

    expect(confirmDialog(wrapper).props("open")).toBe(false);
    expect(client.deleteRole).not.toHaveBeenCalled();
  });

  it("deletes the role once confirmed and falls back to the first one", async () => {
    client.deleteRole.mockResolvedValue(undefined);
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await clickIn(editor(wrapper), "Delete role");
    await confirmDialog(wrapper).get(".require input").setValue("Member");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(client.deleteRole).toHaveBeenCalledWith(2);
    expect(wrapper.findAll("nav button.role")).toHaveLength(2);
    expect(editor(wrapper).attributes("aria-label")).toBe("Role Administrator");
    expect(confirmDialog(wrapper).props("open")).toBe(false);
  });

  it("shows why a delete was refused", async () => {
    client.deleteRole.mockRejectedValue(new ApiError(409, "That would remove your own admin access"));
    const wrapper = await panel();
    await listItem(wrapper, "Member").trigger("click");

    await clickIn(editor(wrapper), "Delete role");
    await confirmDialog(wrapper).get(".require input").setValue("Member");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(editor(wrapper).get(".error").text()).toContain("own admin access");
    expect(wrapper.findAll("nav button.role")).toHaveLength(3);
  });
});
