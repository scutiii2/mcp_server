import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
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

function mountRow(props: Partial<Props> = {}) {
  return mount(ChatRow, {
    props: { chat: chat(), active: false, locked: false, lockedHere: false, selecting: false, ticked: false, renaming: false, ...props },
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

  it("starts a rename from the pencil and from a double click on the title", async () => {
    const wrapper = mountRow();

    await wrapper.find('button[title="Rename chat"]').trigger("click");
    await wrapper.find(".title").trigger("dblclick");

    expect(wrapper.emitted("startRename")).toHaveLength(2);
    expect(wrapper.emitted("select")).toBeUndefined(); // the pencil does not also select
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

  it("Esc cancels the edit", async () => {
    const wrapper = mountRow({ renaming: true });
    const input = wrapper.find("input.rename");

    await input.setValue("Renamed");
    await input.trigger("keydown", { key: "Escape" });

    expect(wrapper.emitted("finishRename")).toEqual([[false, "Renamed"]]);
  });

  it("deleting emits delete; the answering chat cannot be deleted", async () => {
    const free = mountRow();
    await free.find("button.delete").trigger("click");
    expect(free.emitted("delete")).toHaveLength(1);
    expect(free.emitted("select")).toBeUndefined();

    const answering = mountRow({ lockedHere: true });
    expect(answering.find("button.delete").attributes("disabled")).toBeDefined();
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
