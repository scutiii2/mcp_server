import { mount } from "@vue/test-utils";
import { beforeAll, describe, expect, it } from "vitest";
import ConfirmModal from "./ConfirmModal.vue";

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const props = { open: true, title: "Delete account", message: "Delete 'maria' permanently?", confirmLabel: "Delete" };

describe("ConfirmModal", () => {
  it("shows the question and the confirm label", () => {
    const wrapper = mount(ConfirmModal, { props });

    expect(wrapper.text()).toContain("Delete 'maria' permanently?");
    expect(wrapper.get(".confirm").text()).toBe("Delete");
  });

  it("emits confirm and close from its buttons", async () => {
    const wrapper = mount(ConfirmModal, { props });

    await wrapper.get(".confirm").trigger("click");
    await wrapper.get(".cancel").trigger("click");

    expect(wrapper.emitted("confirm")).toHaveLength(1);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("disables both buttons while busy", () => {
    const wrapper = mount(ConfirmModal, { props: { ...props, busy: true } });

    expect(wrapper.get(".confirm").attributes("disabled")).toBeDefined();
    expect(wrapper.get(".cancel").attributes("disabled")).toBeDefined();
  });

  it("marks a dangerous action", () => {
    expect(mount(ConfirmModal, { props: { ...props, danger: true } }).get(".confirm").classes()).toContain("danger");
  });

  it("keeps confirm locked until the required text is typed", async () => {
    const wrapper = mount(ConfirmModal, { props: { ...props, danger: true, requireText: "maria" } });
    const confirm = wrapper.get(".confirm");

    expect(wrapper.text()).toContain("to confirm");
    expect(confirm.attributes("disabled")).toBeDefined();
    await wrapper.get(".require input").setValue("mari");
    expect(confirm.attributes("disabled")).toBeDefined();
    expect(wrapper.get(".count").text()).toBe("4/5");

    await wrapper.get(".require input").setValue("maria");
    expect(confirm.attributes("disabled")).toBeUndefined();
    await confirm.trigger("click");
    expect(wrapper.emitted("confirm")).toHaveLength(1);
  });

  it("clears the typed text when it reopens", async () => {
    const wrapper = mount(ConfirmModal, { props: { ...props, requireText: "maria" } });
    await wrapper.get(".require input").setValue("maria");

    await wrapper.setProps({ open: false });
    await wrapper.setProps({ open: true });

    expect((wrapper.get(".require input").element as HTMLInputElement).value).toBe("");
  });

  it("shows no text field without requireText", () => {
    expect(mount(ConfirmModal, { props }).find(".require").exists()).toBe(false);
  });
});
