import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import ChatSettingsMenu from "./ChatSettingsMenu.vue";

const BASE = {
  caveman: false,
  askBeforeTools: false,
  forceToolApproval: false,
  chime: true,
  allowedCount: 0,
  enabledExtensions: [] as string[],
  attention: false,
};

let wrapper: ReturnType<typeof mount> | null = null;

function open(props: Partial<typeof BASE> = {}) {
  wrapper = mount(ChatSettingsMenu, {
    props: { ...BASE, ...props },
    attachTo: document.body,
    global: { stubs: { RouterLink: { props: ["to"], template: '<a :href="to"><slot /></a>' } } },
  });
  return wrapper;
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

const gear = (w: ReturnType<typeof mount>) => w.get("button.gear");
const panel = (w: ReturnType<typeof mount>) => w.find(".panel");

describe("ChatSettingsMenu", () => {
  it("is closed on load, with only the gear showing", () => {
    const w = open();

    expect(panel(w).exists()).toBe(false);
    expect(gear(w).attributes("aria-expanded")).toBe("false");
  });

  it("says its switches apply instantly and stay on this device", async () => {
    const w = open();

    await gear(w).trigger("click");

    expect(panel(w).get(".note").text()).toBe("Applies instantly. Saved on this device.");
  });

  it("links to the full Settings page", async () => {
    const w = open();

    await gear(w).trigger("click");

    expect(panel(w).get("a.all-settings").attributes("href")).toBe("/settings");
  });

  it("opens and closes from the gear", async () => {
    const w = open();

    await gear(w).trigger("click");
    expect(panel(w).exists()).toBe(true);
    expect(gear(w).attributes("aria-expanded")).toBe("true");

    await gear(w).trigger("click");
    expect(panel(w).exists()).toBe(false);
  });

  it("closes on Escape and hands focus back to the gear", async () => {
    const w = open();
    await gear(w).trigger("click");

    await w.get(".panel").trigger("keydown", { key: "Escape" });
    await w.vm.$nextTick();

    expect(panel(w).exists()).toBe(false);
    expect(document.activeElement).toBe(gear(w).element);
  });

  it("closes on a click outside, but not on a click inside", async () => {
    const w = open();
    await gear(w).trigger("click");

    await w.get(".panel").trigger("click");
    expect(panel(w).exists()).toBe(true);

    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await w.vm.$nextTick();
    expect(panel(w).exists()).toBe(false);
  });

  it("shows each setting and reports a change", async () => {
    const w = open();
    await gear(w).trigger("click");

    expect(w.findAll("label").map((l) => l.text())).toEqual([
      "Terse replies",
      "Ask before tools",
      "Chime when done",
    ]);
    const boxes = w.findAll("input[type=checkbox]");
    expect(boxes.map((b) => (b.element as HTMLInputElement).checked)).toEqual([false, false, true]);

    await boxes[0]!.setValue(true);
    await boxes[1]!.setValue(true);
    await boxes[2]!.setValue(false);

    expect(w.emitted("update:caveman")).toEqual([[true]]);
    expect(w.emitted("update:askBeforeTools")).toEqual([[true]]);
    expect(w.emitted("update:chime")).toEqual([[false]]);
  });

  it("locks 'Ask before tools' on when an administrator forces it", async () => {
    const w = open({ forceToolApproval: true });
    await gear(w).trigger("click");

    const box = w.findAll("input[type=checkbox]")[1]!.element as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
    expect(w.find("button.allowed").exists()).toBe(false);
  });

  it("offers to reset allowed tools only while asking and some are allowed", async () => {
    const w = open({ askBeforeTools: true, allowedCount: 2 });
    await gear(w).trigger("click");

    const reset = w.get("button.allowed");
    expect(reset.text()).toBe("2 tools allowed - reset");
    await reset.trigger("click");
    expect(w.emitted("clear-allowed")).toHaveLength(1);
  });

  it("names the enabled extensions and links to the page", async () => {
    const w = open({ enabledExtensions: ["pdf", "fs"] });
    await gear(w).trigger("click");

    const link = w.get("a.extensions");
    expect(link.text()).toBe("Extensions: pdf, fs");
    expect(link.attributes("href")).toBe("/extensions");
  });

  it("says extensions are off when none are enabled", async () => {
    const w = open();
    await gear(w).trigger("click");

    expect(w.get("a.extensions").text()).toBe("Extensions: off");
  });

  it("marks the gear only when something needs attention", () => {
    expect(open({ attention: true }).find(".dot").exists()).toBe(true);
    wrapper?.unmount();
    expect(open().find(".dot").exists()).toBe(false);
  });
});
