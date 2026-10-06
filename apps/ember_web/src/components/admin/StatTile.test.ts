import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import StatTile from "./StatTile.vue";

describe("StatTile", () => {
  it("shows the label and the value", () => {
    const wrapper = mount(StatTile, { props: { label: "Accounts", value: 24 } });

    expect(wrapper.text()).toContain("Accounts");
    expect(wrapper.text()).toContain("24");
  });

  it("shows a dash while the value loads, and a real zero once it is 0", () => {
    expect(mount(StatTile, { props: { label: "Disabled", value: null } }).text()).toContain("–");
    expect(mount(StatTile, { props: { label: "Disabled", value: 0 } }).text()).toContain("0");
  });

  it("only flags a non-zero value as a warning", () => {
    const classes = (value: number) =>
      mount(StatTile, { props: { label: "Unverified", value, warn: true } }).get(".value").classes();

    expect(classes(3)).toContain("warn");
    expect(classes(0)).not.toContain("warn");
  });
});
