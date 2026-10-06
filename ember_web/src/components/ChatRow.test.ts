import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import type { Conversation } from "../api/types";
import ChatRow from "./ChatRow.vue";

const chat = (extra: Partial<Conversation> = {}): Conversation => ({
  id: "c1",
  title: "My chat",
  messages: [],
  createdAt: 0,
  updatedAt: 0,
  ...extra,
});

type Props = InstanceType<typeof ChatRow>["$props"];

function mountRow(props: Partial<Props> = {}, attach = false) {
  return mount(ChatRow, {
    props: { chat: chat(), active: false, locked: false, lockedHere: false, selecting: false, ticked: false, renaming: false, ...props },
    ...(attach ? { attachTo: document.body } : {}),
  });
}

describe("ChatRow", () => {
  it("shows the title and selects on click", async () => {
    const wrapper = mountRow();

    expect(wrapper.text()).toContain("My chat");
    await wrapper.find("li").trigger("click");

    expect(wrapper.emitted("select")).toHaveLength(1);
    expect(wrapper.emitted("toggle")).toBeUndefined();
  });

  it("toggles instead of selecting while selecting chats", async () => {
    const wrapper = mountRow({ selecting: true });

    await wrapper.find("li").trigger("click");

    expect(wrapper.emitted("toggle")).toHaveLength(1);
    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("does not select while its title is being renamed", async () => {
    const wrapper = mountRow({ renaming: true });

    await wrapper.find("li").trigger("click");

    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("starts a rename from a double click on the title", async () => {
    const wrapper = mountRow();

    await wrapper.find(".title").trigger("dblclick");

    expect(wrapper.emitted("startRename")).toHaveLength(1);
    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("has a ... button that opens the menu without selecting the row", async () => {
    const wrapper = mountRow();

    await wrapper.find("button.more").trigger("click");

    expect(wrapper.emitted("openMenu")).toHaveLength(1);
    expect(wrapper.emitted("select")).toBeUndefined();
    expect(wrapper.find("button.more").attributes("aria-haspopup")).toBe("menu");
  });

  it("a press on the ... button does not reach the document (an open menu would close on it)", () => {
    const wrapper = mountRow({}, true);
    const seen = vi.fn();
    document.addEventListener("pointerdown", seen);

    wrapper.find("button.more").element.dispatchEvent(new Event("pointerdown", { bubbles: true }));

    document.removeEventListener("pointerdown", seen);
    wrapper.unmount();
    expect(seen).not.toHaveBeenCalled();
  });

  it("opens the menu on right-click at the pointer, but not while selecting or renaming", async () => {
    const wrapper = mountRow();
    await wrapper.find("li").trigger("contextmenu", { clientX: 12, clientY: 34 });
    expect(wrapper.emitted("openMenu")![0]![0]).toMatchObject({ x: 12, y: 34 });

    const selecting = mountRow({ selecting: true });
    await selecting.find("li").trigger("contextmenu");
    expect(selecting.emitted("openMenu")).toBeUndefined();

    const renaming = mountRow({ renaming: true });
    await renaming.find("li").trigger("contextmenu");
    expect(renaming.emitted("openMenu")).toBeUndefined();
  });

  it("no longer has rename or delete buttons of its own", () => {
    const wrapper = mountRow();

    expect(wrapper.find('button[title="Rename chat"]').exists()).toBe(false);
    expect(wrapper.find("button.delete").exists()).toBe(false);
  });

  it("edits the title: Enter saves, once, even if blur follows", async () => {
    const wrapper = mountRow({ renaming: true });
    const input = wrapper.find("input.rename");
    expect((input.element as HTMLInputElement).value).toBe("My chat");

    await input.setValue("Renamed");
    await input.trigger("keydown", { key: "Enter" });
    await input.trigger("blur");

    expect(wrapper.emitted("finishRename")).toEqual([[true, "Renamed"]]);
  });

  it("focuses the rename box when renaming starts", async () => {
    const wrapper = mountRow({}, true);

    await wrapper.setProps({ renaming: true });
    await nextTick();

    expect(document.activeElement).toBe(wrapper.find("input.rename").element);
    wrapper.unmount();
  });

  it("the ... button reports an open menu and stays visible", async () => {
    const wrapper = mountRow();
    const button = () => wrapper.find("button.more");
    expect(button().attributes("aria-expanded")).toBe("false");
    expect(button().classes()).not.toContain("expanded");

    await wrapper.setProps({ expanded: true });

    expect(button().attributes("aria-expanded")).toBe("true");
    expect(button().classes()).toContain("expanded");
  });

  it("Esc cancels the edit", async () => {
    const wrapper = mountRow({ renaming: true });
    const input = wrapper.find("input.rename");

    await input.setValue("Renamed");
    await input.trigger("keydown", { key: "Escape" });

    expect(wrapper.emitted("finishRename")).toEqual([[false, "Renamed"]]);
  });

  it("shows the running dot and the tick box state while selecting; the answering chat's box is disabled", () => {
    const wrapper = mountRow({ chat: chat({ running: true }), selecting: true, ticked: true, lockedHere: true });

    expect(wrapper.find(".running").exists()).toBe(true);
    const tick = wrapper.find("input.tick");
    expect((tick.element as HTMLInputElement).checked).toBe(true);
    expect(tick.attributes("disabled")).toBeDefined();
  });

  it("clicking the tick box toggles once, without also counting as a row click", async () => {
    const wrapper = mountRow({ selecting: true });

    await wrapper.find("input.tick").trigger("click");

    expect(wrapper.emitted("toggle")).toHaveLength(1);
  });

  it("carries the active, locked and ticked classes", () => {
    const wrapper = mountRow({ active: true, locked: true, selecting: true, ticked: true });

    expect(wrapper.find("li").classes()).toEqual(expect.arrayContaining(["row", "active", "locked", "ticked"]));
  });
});
