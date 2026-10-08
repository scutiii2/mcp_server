import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { agentsAdminClient, type SharedPrompts } from "../../api/AgentsAdminClient";
import SharedPromptsModal from "./SharedPromptsModal.vue";

const DEFAULTS = {
  app_name: "Ember", app_description: "Support tool.", identity_template: "Your name is {app_name}: {role}.",
  default_instructions: "Be helpful.", roster_intro: "You coordinate:", caveman_instructions: "Be terse.",
};
const LOADED: SharedPrompts = { values: { ...DEFAULTS, app_name: "Spark" }, defaults: DEFAULTS, overridden: ["app_name"] };

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.spyOn(agentsAdminClient, "prompts").mockResolvedValue(LOADED);
});
afterEach(() => vi.restoreAllMocks());

async function opened() {
  const wrapper = mount(SharedPromptsModal, { attachTo: document.body, props: { open: true } });
  await flushPromises();
  return wrapper;
}

describe("SharedPromptsModal", () => {
  it("shows every shared text and marks the ones that differ from the default", async () => {
    const wrapper = await opened();
    expect(wrapper.findAll("textarea")).toHaveLength(6);
    expect(wrapper.find<HTMLTextAreaElement>("[data-test=app_name]").element.value).toBe("Spark");
    expect(wrapper.find("[data-key=app_name] .dot").exists()).toBe(true);
    expect(wrapper.find("[data-key=roster_intro] .dot").exists()).toBe(false);
  });

  it("resets one text to its default in the form", async () => {
    const wrapper = await opened();
    await wrapper.find("[data-test=reset-app_name]").trigger("click");
    expect(wrapper.find<HTMLTextAreaElement>("[data-test=app_name]").element.value).toBe("Ember");
    expect(wrapper.find("[data-key=app_name] .dot").exists()).toBe(false);
  });

  it("saves only the changed texts after the restart confirmation", async () => {
    const set = vi.spyOn(agentsAdminClient, "setPrompts").mockResolvedValue({ ...LOADED, values: { ...LOADED.values, roster_intro: "Hand off:" } });
    const wrapper = await opened();
    expect(wrapper.find<HTMLButtonElement>("[data-test=save-prompts]").element.disabled).toBe(true);

    await wrapper.find("[data-test=roster_intro]").setValue("Hand off:");
    await wrapper.find("[data-test=save-prompts]").trigger("click");
    expect(set).not.toHaveBeenCalled();
    const confirm = wrapper.findComponent({ name: "ConfirmModal" });
    expect(confirm.props("message")).toContain("Every agent restarts");
    await confirm.vm.$emit("confirm");
    await flushPromises();

    expect(set).toHaveBeenCalledWith({ roster_intro: "Hand off:" });
    expect(wrapper.emitted("saved")).toHaveLength(1);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("shows the server's reason and stays open when a save is refused", async () => {
    vi.spyOn(agentsAdminClient, "setPrompts").mockRejectedValue(new Error("identity_template can only use {app_name}"));
    const wrapper = await opened();
    await wrapper.find("[data-test=identity_template]").setValue("Hi {nope}");
    await wrapper.find("[data-test=save-prompts]").trigger("click");
    await wrapper.findComponent({ name: "ConfirmModal" }).vm.$emit("confirm");
    await flushPromises();

    expect(wrapper.find("[data-test=prompts-error]").text()).toContain("identity_template");
    expect(wrapper.emitted("saved")).toBeUndefined();
  });
});
