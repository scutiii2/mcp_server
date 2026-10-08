import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/http";
import { settingsClient } from "../../api/SettingsClient";
import SettingsPanel from "./SettingsPanel.vue";

vi.mock("../../api/SettingsClient", () => ({ settingsClient: { get: vi.fn(), set: vi.fn() } }));

const client = vi.mocked(settingsClient);

async function panel(forced: boolean) {
  client.get.mockResolvedValue({ force_tool_approval: forced });
  const wrapper = mount(SettingsPanel);
  await flushPromises();
  return wrapper;
}

const box = (wrapper: Awaited<ReturnType<typeof panel>>) => wrapper.get('input[type="checkbox"]');

beforeEach(() => {
  vi.clearAllMocks();
  client.set.mockResolvedValue({ force_tool_approval: true });
});

describe("SettingsPanel", () => {
  it("shows whether approval is required", async () => {
    expect((box(await panel(true)).element as HTMLInputElement).checked).toBe(true);
    expect((box(await panel(false)).element as HTMLInputElement).checked).toBe(false);
  });

  it("explains what the switch does", async () => {
    const text = (await panel(false)).text();

    expect(text).toContain("Require approval for every tool");
    expect(text).toContain("Allow for this chat");
  });

  it("says the setting applies to every account", async () => {
    expect((await panel(false)).text()).toContain("Applies to all accounts");
  });

  it("holds a flip as an unsaved change until Save", async () => {
    const wrapper = await panel(false);
    expect(wrapper.find(".save-bar").exists()).toBe(false);

    await box(wrapper).setValue(true);

    expect(client.set).not.toHaveBeenCalled();
    expect(wrapper.get(".save-bar").text()).toContain("unsaved change");
    expect(wrapper.get(".save-bar").text()).toContain("on applies to every account");
  });

  it("saves the draft on Save, then shows Saved", async () => {
    const wrapper = await panel(false);
    await box(wrapper).setValue(true);

    await wrapper.get(".save-bar .primary").trigger("click");
    await flushPromises();

    expect(client.set).toHaveBeenCalledWith("force_tool_approval", true);
    expect(wrapper.find(".save-bar").exists()).toBe(false);
    expect(wrapper.get(".chip.saved").text()).toBe("Saved");
    expect((box(wrapper).element as HTMLInputElement).checked).toBe(true);
  });

  it("turns it off again", async () => {
    const wrapper = await panel(true);

    await box(wrapper).setValue(false);
    await wrapper.get(".save-bar .primary").trigger("click");
    await flushPromises();

    expect(client.set).toHaveBeenCalledWith("force_tool_approval", false);
  });

  it("drops the draft on Cancel without saving", async () => {
    const wrapper = await panel(false);
    await box(wrapper).setValue(true);

    await wrapper.get(".save-bar button:not(.primary)").trigger("click");

    expect(client.set).not.toHaveBeenCalled();
    expect(wrapper.find(".save-bar").exists()).toBe(false);
    expect((box(wrapper).element as HTMLInputElement).checked).toBe(false);
  });

  it("flipping back to the stored value clears the unsaved change", async () => {
    const wrapper = await panel(false);

    await box(wrapper).setValue(true);
    await box(wrapper).setValue(false);

    expect(wrapper.find(".save-bar").exists()).toBe(false);
  });

  it("shows the error and keeps the draft when saving fails", async () => {
    const wrapper = await panel(false);
    client.set.mockRejectedValue(new ApiError(403, "Missing permission: roles.manage"));
    await box(wrapper).setValue(true);

    await wrapper.get(".save-bar .primary").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Missing permission: roles.manage");
    expect(wrapper.find(".save-bar").exists()).toBe(true);
    expect(wrapper.find(".chip.saved").exists()).toBe(false);
  });

  it("tells its page whether the stored value differs from the default", async () => {
    const off = await panel(false);
    const on = await panel(true);

    expect(off.emitted("modified")?.at(-1)).toEqual([false]);
    expect(on.emitted("modified")?.at(-1)).toEqual([true]);
    expect(on.find(".dot").exists()).toBe(true);
    expect(off.find(".dot").exists()).toBe(false);
  });

  it("offers Back to default only while the switch is on, and it makes an unsaved draft", async () => {
    const wrapper = await panel(true);
    const reset = () => wrapper.findAll("button").find((b) => b.text() === "Back to default");
    expect(reset()).toBeDefined();

    await reset()!.trigger("click");

    expect(client.set).not.toHaveBeenCalled();
    expect((box(wrapper).element as HTMLInputElement).checked).toBe(false);
    expect(wrapper.get(".save-bar").text()).toContain("off applies to every account");
    expect(reset()).toBeUndefined();

    await wrapper.get(".save-bar .primary").trigger("click");
    await flushPromises();
    expect(client.set).toHaveBeenCalledWith("force_tool_approval", false);
    expect(wrapper.emitted("modified")?.at(-1)).toEqual([false]);
  });

  it("has no Back to default when the switch is already off", async () => {
    const wrapper = await panel(false);

    expect(wrapper.findAll("button").some((b) => b.text() === "Back to default")).toBe(false);
  });

  it("shows an error when the setting cannot be read", async () => {
    client.get.mockRejectedValue(new ApiError(500, "boom"));
    const wrapper = mount(SettingsPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("boom");
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false);
  });
});
