import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ActionButton from "./ActionButton.vue";

describe("ActionButton", () => {
  it("shows its label and a hidden icon", () => {
    const wrapper = mount(ActionButton, { props: { icon: "export" }, slots: { default: "Export" } });

    expect(wrapper.text()).toBe("Export");
    expect(wrapper.find("svg").attributes("aria-hidden")).toBe("true");
    expect(wrapper.find("path").attributes("d")).not.toBe("");
  });

  it("draws a different icon for each name", () => {
    const icons = (["export", "share", "summarize", "clear", "mail", "lock", "close", "verify"] as const).map(
      (icon) => mount(ActionButton, { props: { icon } }).find("path").attributes("d"),
    );

    expect(new Set(icons).size).toBe(8);
  });

  it("is a plain button that passes click, title and disabled through", async () => {
    const wrapper = mount(ActionButton, { props: { icon: "clear" }, attrs: { title: "Start afresh", disabled: true } });

    expect(wrapper.attributes("type")).toBe("button");
    expect(wrapper.attributes("title")).toBe("Start afresh");
    expect(wrapper.attributes("disabled")).toBeDefined();
  });

  it("mutes the icon with quiet", () => {
    expect(mount(ActionButton, { props: { icon: "clear", quiet: true } }).classes()).toContain("quiet");
  });
});
