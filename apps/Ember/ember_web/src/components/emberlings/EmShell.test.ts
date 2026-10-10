import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import EmShell from "./EmShell.vue";

describe("EmShell", () => {
  it("shows the logo, the tagline, the Insignia wallet and the content", () => {
    const wrapper = mount(EmShell, { props: { insignia: 240 }, slots: { default: "<p class='body'>Hello</p>" } });

    expect(wrapper.find("h1").text()).toBe("EMBERLINGS");
    expect(wrapper.text()).toContain("Collect. Forge. Battle.");
    expect(wrapper.find(".wallet").text()).toBe("240 Insignia");
    expect(wrapper.find(".body").text()).toBe("Hello");
  });

  it("has no wallet before there is a profile", () => {
    const wrapper = mount(EmShell, { props: { insignia: null } });

    expect(wrapper.find(".wallet").exists()).toBe(false);
  });
});
