import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SupermarketItem from "./SupermarketItem.vue";

const base = { label: "PDF files", name: "pdf", icon: "builtin" as const, summary: "2 tools", added: false };

describe("SupermarketItem", () => {
  it("offers Add to something not added, and says what it is", () => {
    const w = mount(SupermarketItem, { props: base });

    expect(w.get("h3").text()).toBe("PDF files");
    expect(w.get("code").text()).toBe("pdf");
    expect(w.get(".summary").text()).toBe("2 tools");
    expect(w.get("button.add").attributes("aria-label")).toBe("Add PDF files");
    expect(w.find("button.secondary").exists()).toBe(false);
  });

  it("emits add", async () => {
    const w = mount(SupermarketItem, { props: base });

    await w.get("button.add").trigger("click");

    expect(w.emitted("add")).toHaveLength(1);
  });

  it("shows Added and a Disable button for something added", async () => {
    const w = mount(SupermarketItem, { props: { ...base, added: true } });

    expect(w.get(".added").text()).toContain("Added");
    expect(w.find("button.add").exists()).toBe(false);
    await w.get("button.secondary").trigger("click");
    expect(w.emitted("disable")).toHaveLength(1);
  });

  it("offers no Add for a capability that is off for everyone", () => {
    const w = mount(SupermarketItem, { props: { ...base, locked: true } });

    expect(w.get(".badge").text()).toBe("Off for everyone");
    expect(w.find("button.add").exists()).toBe(false);
  });

  it("still lets something added be disabled when it is off for everyone", () => {
    const w = mount(SupermarketItem, { props: { ...base, added: true, locked: true } });

    expect(w.find("button.secondary").exists()).toBe(true);
  });

  it("renders extra actions from the slot", () => {
    const w = mount(SupermarketItem, { props: base, slots: { actions: '<button class="extra">Remove</button>' } });

    expect(w.find("button.extra").exists()).toBe(true);
  });
});

describe("labels and detail", () => {
  it("can call the buttons Enable and Enabled", () => {
    const off = mount(SupermarketItem, { props: { ...base, addLabel: "Enable", addedLabel: "Enabled" } });
    const on = mount(SupermarketItem, { props: { ...base, added: true, addLabel: "Enable", addedLabel: "Enabled" } });

    expect(off.get("button.add").text()).toBe("Enable");
    expect(off.get("button.add").attributes("aria-label")).toBe("Enable PDF files");
    expect(on.get(".added").text()).toContain("Enabled");
  });

  it("keeps Add and Added by default", () => {
    const off = mount(SupermarketItem, { props: base });
    const on = mount(SupermarketItem, { props: { ...base, added: true } });

    expect(off.get("button.add").text()).toBe("Add");
    expect(on.get(".added").text()).toContain("Added");
  });

  it("shows a detail line only when given", () => {
    expect(mount(SupermarketItem, { props: base }).find(".detail").exists()).toBe(false);
    expect(mount(SupermarketItem, { props: { ...base, detail: "Timed out" } }).get(".detail").text()).toBe("Timed out");
  });
});
