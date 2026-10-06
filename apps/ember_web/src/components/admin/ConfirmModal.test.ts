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
});
