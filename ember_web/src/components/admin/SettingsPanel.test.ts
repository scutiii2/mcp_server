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

  it("saves the switch when it is flipped", async () => {
    const wrapper = await panel(false);

    await box(wrapper).setValue(true);
    await flushPromises();

    expect(client.set).toHaveBeenCalledWith("force_tool_approval", true);
    expect((box(wrapper).element as HTMLInputElement).checked).toBe(true);
  });

  it("turns it off again", async () => {
    const wrapper = await panel(true);

    await box(wrapper).setValue(false);
    await flushPromises();

    expect(client.set).toHaveBeenCalledWith("force_tool_approval", false);
  });

  it("shows the error and the stored value when saving fails", async () => {
    const wrapper = await panel(false);
    client.set.mockRejectedValue(new ApiError(403, "Missing permission: admin.manage"));

    await box(wrapper).setValue(true);
    await flushPromises();

    expect(wrapper.text()).toContain("Missing permission: admin.manage");
    expect((box(wrapper).element as HTMLInputElement).checked).toBe(false);
  });

  it("shows an error when the setting cannot be read", async () => {
    client.get.mockRejectedValue(new ApiError(500, "boom"));
    const wrapper = mount(SettingsPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("boom");
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false);
  });
});
