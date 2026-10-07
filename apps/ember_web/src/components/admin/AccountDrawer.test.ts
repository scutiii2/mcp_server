import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { AdminAccount, Role } from "../../api/AdminClient";
import AccountDrawer from "./AccountDrawer.vue";

const ROLES: Role[] = [
  { id: 1, name: "Administrator", description: null, is_protected: true, permissions: [], account_count: 1 },
  { id: 2, name: "Member", description: null, is_protected: false, permissions: [], account_count: 2 },
  { id: 3, name: "Ops", description: null, is_protected: false, permissions: [], account_count: 0 },
];

const MARIA: AdminAccount = {
  id: 7,
  username: "maria",
  email: "maria@mail.com",
  email_verified: false,
  is_active: true,
  is_protected: false,
  created_at: "2026-09-12T10:00:00",
  roles: [{ id: 2, name: "Member" }],
};

function drawer(account: Partial<AdminAccount> = {}, props: { isSelf?: boolean; busy?: boolean } = {}) {
  return mount(AccountDrawer, {
    props: { account: { ...MARIA, ...account }, roles: ROLES, isSelf: false, busy: false, error: "", notice: "", ...props },
  });
}

const buttonLabels = (wrapper: ReturnType<typeof drawer>) => wrapper.findAll("button").map((b) => b.text());

describe("AccountDrawer", () => {
  it("shows who the account is and its roles", () => {
    const wrapper = drawer();

    expect(wrapper.text()).toContain("maria");
    expect(wrapper.text()).toContain("maria@mail.com");
    expect(wrapper.findAll(".chip").map((c) => c.text().replace(/\s+/g, " "))).toEqual(["Member ×"]);
  });

  it("offers only the roles the account does not hold", () => {
    const options = drawer().findAll("select option").map((o) => o.text());

    expect(options).toEqual(["+ Add role", "Administrator", "Ops"]);
  });

  it("reports an added role and resets the dropdown", async () => {
    const wrapper = drawer();
    const select = wrapper.get("select");

    await select.setValue("3");

    expect(wrapper.emitted("addRole")).toEqual([[3]]);
    expect((select.element as HTMLSelectElement).value).toBe("");
  });

  it("reports a removed role", async () => {
    const wrapper = drawer();

    await wrapper.get(".chip-x").trigger("click");

    expect(wrapper.emitted("removeRole")).toEqual([[{ id: 2, name: "Member" }]]);
  });

  it("saves only the fields that changed", async () => {
    const wrapper = drawer();
    await wrapper.findAll("button").find((b) => b.text() === "Edit details")!.trigger("click");

    await wrapper.get('input[aria-label="Email"]').setValue("new@mail.com");
    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("save")).toEqual([[{ email: "new@mail.com" }]]);
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("closes the edit form without saving when nothing changed", async () => {
    const wrapper = drawer();
    await wrapper.findAll("button").find((b) => b.text() === "Edit details")!.trigger("click");

    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("save")).toBeUndefined();
  });

  it("asks to disable an active account when the switch is clicked", async () => {
    const wrapper = drawer();

    await wrapper.get('input[role="switch"]').trigger("click");

    expect(wrapper.emitted("setActive")).toEqual([[false]]);
  });

  it("asks to enable a disabled account", async () => {
    const wrapper = drawer({ is_active: false });

    await wrapper.get('input[role="switch"]').trigger("click");

    expect(wrapper.emitted("setActive")).toEqual([[true]]);
  });

  it("offers send verification only while the email is unverified", () => {
    expect(buttonLabels(drawer())).toContain("Send verification");
    expect(buttonLabels(drawer({ email_verified: true }))).not.toContain("Send verification");
  });

  it("reports delete, send verification and close", async () => {
    const wrapper = drawer();
    const click = (label: string) => wrapper.findAll("button").find((b) => b.text() === label)!.trigger("click");

    await click("Delete account");
    await click("Send verification");
    await wrapper.get('button[aria-label="Close"]').trigger("click");

    expect(wrapper.emitted("remove")).toHaveLength(1);
    expect(wrapper.emitted("sendVerification")).toHaveLength(1);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("keeps your own account from being disabled or deleted", () => {
    const wrapper = drawer({}, { isSelf: true });

    expect(wrapper.find('input[role="switch"]').exists()).toBe(false);
    expect(buttonLabels(wrapper)).not.toContain("Delete account");
  });

  it("offers nothing to change on the protected account", () => {
    const wrapper = drawer({ is_protected: true, roles: [{ id: 1, name: "Administrator" }] });

    expect(wrapper.text()).toContain("protected admin account");
    expect(wrapper.find('input[role="switch"]').exists()).toBe(false);
    expect(wrapper.find("select").exists()).toBe(false);
    expect(wrapper.find(".chip-x").exists()).toBe(false);
    expect(wrapper.findAll("button").map((button) => button.attributes("aria-label"))).toEqual(["Close"]);
  });

  it("disables the controls while a call runs", () => {
    const wrapper = drawer({}, { busy: true });

    expect(wrapper.get(".chip-x").attributes("disabled")).toBeDefined();
    expect(wrapper.get("select").attributes("disabled")).toBeDefined();
    expect(wrapper.get('input[role="switch"]').attributes("disabled")).toBeDefined();
  });

  it("shows the error and the notice it is given", () => {
    const wrapper = mount(AccountDrawer, {
      props: { account: MARIA, roles: ROLES, isSelf: false, busy: false, error: "Email already in use", notice: "Sent" },
    });

    expect(wrapper.get(".error").text()).toBe("Email already in use");
    expect(wrapper.get(".notice").text()).toBe("Sent");
  });
});
