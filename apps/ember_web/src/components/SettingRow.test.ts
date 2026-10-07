import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SettingRow from "./SettingRow.vue";

const props = { settingId: "chat-chime", label: "Chime when done", description: "Play a sound." };

describe("SettingRow", () => {
  it("shows the label, the description and the control", () => {
    const wrapper = mount(SettingRow, { props, slots: { default: '<input type="checkbox" />' } });

    expect(wrapper.text()).toContain("Chime when done");
    expect(wrapper.text()).toContain("Play a sound.");
    expect(wrapper.find("input").exists()).toBe(true);
    expect(wrapper.get("[data-setting-id]").attributes("data-setting-id")).toBe("chat-chime");
  });

  it("shows no dot and no reset while the setting is at its default", () => {
    const wrapper = mount(SettingRow, { props });

    expect(wrapper.find(".dot").exists()).toBe(false);
    expect(wrapper.find("button.reset").exists()).toBe(false);
  });

  it("marks a modified setting and resets it on click", async () => {
    const wrapper = mount(SettingRow, { props: { ...props, modified: true } });

    expect(wrapper.find(".dot").exists()).toBe(true);
    expect(wrapper.text()).toContain("changed from the default");
    const reset = wrapper.get("button.reset");
    expect(reset.attributes("aria-label")).toBe("Reset Chime when done to its default");

    await reset.trigger("click");

    expect(wrapper.emitted("reset")).toHaveLength(1);
  });
});
