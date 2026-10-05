import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { PermissionInfo, Role } from "../../api/AdminClient";
import RoleEditor from "./RoleEditor.vue";

const PERMISSIONS: PermissionInfo[] = [
  { name: "chat.use", description: "Chat with the agent" },
  { name: "tools.use", description: "Run mcp_server tools" },
  { name: "admin.manage", description: null },
];

const MEMBER: Role = {
  id: 2,
  name: "Member",
  description: "Default role",
  is_protected: false,
  permissions: ["chat.use", "tools.use"],
  account_count: 2,
};

const ADMIN: Role = {
  id: 1,
  name: "Administrator",
  description: null,
  is_protected: true,
  permissions: ["chat.use", "tools.use", "admin.manage"],
  account_count: 1,
};

function editor(role: Role = MEMBER, props: { busy?: boolean; error?: string } = {}) {
  return mount(RoleEditor, { props: { role, permissions: PERMISSIONS, busy: false, error: "", ...props } });
}

const switchFor = (wrapper: ReturnType<typeof editor>, name: string) => wrapper.get(`input[aria-label="${name}"]`);
const click = (wrapper: ReturnType<typeof editor>, label: string) =>
  wrapper.findAll("button").find((b) => b.text() === label)!.trigger("click");

describe("RoleEditor", () => {
  it("shows the role, its description and its account count", () => {
    const text = editor().text();

    expect(text).toContain("Member");
    expect(text).toContain("Default role");
    expect(text).toContain("2 accounts");
    expect(editor({ ...MEMBER, account_count: 1 }).text()).toContain("1 account");
  });

  it("shows a switch per permission, on for the ones the role holds", () => {
    const wrapper = editor();

    expect(wrapper.findAll('input[role="switch"]')).toHaveLength(3);
    expect((switchFor(wrapper, "chat.use").element as HTMLInputElement).checked).toBe(true);
    expect((switchFor(wrapper, "admin.manage").element as HTMLInputElement).checked).toBe(false);
    expect(wrapper.text()).toContain("Run mcp_server tools");
  });

  it("asks to grant a permission the role lacks, and to revoke one it holds", async () => {
    const wrapper = editor();

    await switchFor(wrapper, "admin.manage").trigger("click");
    await switchFor(wrapper, "chat.use").trigger("click");

    expect(wrapper.emitted("togglePermission")).toEqual([
      ["admin.manage", true],
      ["chat.use", false],
    ]);
  });

  it("saves only the fields that changed", async () => {
    const wrapper = editor();
    await click(wrapper, "Edit details");

    await wrapper.get('input[aria-label="Description"]').setValue("New text");
    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("save")).toEqual([[{ description: "New text" }]]);
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("closes the edit form without saving when nothing changed", async () => {
    const wrapper = editor();
    await click(wrapper, "Edit details");

    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("save")).toBeUndefined();
  });

  it("can clear the description", async () => {
    const wrapper = editor();
    await click(wrapper, "Edit details");

    await wrapper.get('input[aria-label="Description"]').setValue("");
    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("save")).toEqual([[{ description: "" }]]);
  });

  it("asks to delete the role", async () => {
    const wrapper = editor();

    await click(wrapper, "Delete role");

    expect(wrapper.emitted("remove")).toHaveLength(1);
  });

  it("locks the Administrator role: no deleting, no renaming, no permission changes", async () => {
    const wrapper = editor(ADMIN);

    expect(wrapper.text()).toContain("always holds every permission");
    expect(wrapper.findAll("button").map((b) => b.text())).toEqual(["Edit description"]);
    for (const input of wrapper.findAll('input[role="switch"]')) {
      expect(input.attributes("disabled")).toBeDefined();
    }

    await click(wrapper, "Edit description");
    expect(wrapper.get('input[aria-label="Role name"]').attributes("disabled")).toBeDefined();
  });

  it("never sends a name for the protected role", async () => {
    const wrapper = editor(ADMIN);
    await click(wrapper, "Edit description");

    await wrapper.get('input[aria-label="Description"]').setValue("Everything");
    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("save")).toEqual([[{ description: "Everything" }]]);
  });

  it("disables the controls while a call runs", () => {
    const wrapper = editor(MEMBER, { busy: true });

    for (const input of wrapper.findAll('input[role="switch"]')) {
      expect(input.attributes("disabled")).toBeDefined();
    }
    expect(wrapper.findAll("button").every((b) => b.attributes("disabled") !== undefined)).toBe(true);
  });

  it("shows the error it is given", () => {
    expect(editor(MEMBER, { error: "That would remove your own admin access" }).get(".error").text()).toBe(
      "That would remove your own admin access",
    );
  });
});
