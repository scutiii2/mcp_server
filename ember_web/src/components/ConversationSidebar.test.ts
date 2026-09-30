import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { ChatSearchHit } from "../api/ChatsClient";
import type { Conversation } from "../api/types";
import ConversationSidebar from "./ConversationSidebar.vue";

const chat = (id: string, title = `Chat ${id}`): Conversation => ({
  id,
  title,
  messages: [],
  createdAt: 0,
  updatedAt: 0,
});

const hit = (id: string, extra: Partial<ChatSearchHit> = {}): ChatSearchHit => ({
  id,
  title: `Chat ${id}`,
  updated_at: "2026-01-01T00:00:00",
  title_match: null,
  snippet: null,
  message_index: null,
  message_matches: 0,
  ...extra,
});

type Props = InstanceType<typeof ConversationSidebar>["$props"];

function mountSidebar(props: Partial<Props> = {}) {
  return mount(ConversationSidebar, {
    props: { conversations: [chat("1"), chat("2")], activeId: null, locked: false, ...props },
  });
}

const searching = (hits: ChatSearchHit[], extra: Partial<Props> = {}) =>
  mountSidebar({ query: "ab", searchActive: true, hits, ...extra });

describe("the search box", () => {
  it("shows once there are chats, and reports what is typed", async () => {
    const wrapper = mountSidebar();

    await wrapper.find('input[type="search"]').setValue("docker");

    expect(wrapper.emitted("search")).toEqual([["docker"]]);
  });

  it("Esc clears it", async () => {
    const wrapper = mountSidebar({ query: "abc" });

    await wrapper.find('input[type="search"]').trigger("keydown", { key: "Escape" });

    expect(wrapper.emitted("search")).toEqual([[""]]);
  });

  it("is hidden while there are no chats and nothing typed", () => {
    expect(mountSidebar({ conversations: [] }).find('input[type="search"]').exists()).toBe(false);
  });

  it("stays while a query has no chats left to show", () => {
    expect(mountSidebar({ conversations: [], query: "x" }).find('input[type="search"]').exists()).toBe(true);
  });
});

describe("search results", () => {
  it("replace the chat list, and hide Delete all", () => {
    const wrapper = searching([hit("2")]);

    expect(wrapper.findAll("li.row")).toHaveLength(1);
    expect(wrapper.find(".delete-all").exists()).toBe(false);
  });

  it("show the normal list, with Delete all, when the query is too short", () => {
    const wrapper = mountSidebar({ query: "a", searchActive: false });

    expect(wrapper.findAll("li.row")).toHaveLength(2);
    expect(wrapper.find(".delete-all").exists()).toBe(true);
  });

  it("highlight the match in the title", () => {
    const wrapper = searching([hit("1", { title: "Docker Compose notes", title_match: { start: 0, length: 6 } })]);

    expect(wrapper.find(".title mark").text()).toBe("Docker");
    expect(wrapper.find(".title").text()).toBe("Docker Compose notes");
  });

  it("show the snippet with its match highlighted, and how many messages match", () => {
    const wrapper = searching([
      hit("1", {
        snippet: { text: "…how do I restart the service?", start: 10, length: 7 },
        message_index: 4,
        message_matches: 3,
      }),
    ]);

    expect(wrapper.find(".snippet mark").text()).toBe("restart");
    expect(wrapper.find(".snippet").text()).toBe("…how do I restart the service?");
    expect(wrapper.find(".count").text()).toBe("3 messages match");
  });

  it("do not say '1 messages match'", () => {
    const wrapper = searching([hit("1", { snippet: { text: "abc", start: 0, length: 2 }, message_index: 0, message_matches: 1 })]);

    expect(wrapper.find(".count").exists()).toBe(false);
  });

  it("open the chat at the first matching message when clicked", async () => {
    const wrapper = searching([hit("2", { snippet: { text: "abc", start: 0, length: 2 }, message_index: 5, message_matches: 1 })]);

    await wrapper.find("li.row").trigger("click");

    expect(wrapper.emitted("select")).toEqual([["2", 5]]);
  });

  it("open a title-only match without a message to jump to", async () => {
    const wrapper = searching([hit("1", { title_match: { start: 0, length: 2 } })]);

    await wrapper.find("li.row").trigger("click");

    expect(wrapper.emitted("select")).toEqual([["1", undefined]]);
  });

  it("mark the open chat", () => {
    const wrapper = searching([hit("1"), hit("2")], { activeId: "2" });

    expect(wrapper.findAll("li.row").map((r) => r.classes().includes("active"))).toEqual([false, true]);
  });

  it("have no rename or delete buttons of their own", () => {
    expect(searching([hit("1")]).find("button.icon").exists()).toBe(false);
  });
});

describe("search states", () => {
  it("says it is searching before the first hits arrive", () => {
    expect(searching([], { searching: true }).find(".empty").text()).toBe("Searching …");
  });

  it("keeps showing the previous hits while a newer search runs", () => {
    const wrapper = searching([hit("1")], { searching: true });

    expect(wrapper.findAll("li.row")).toHaveLength(1);
    expect(wrapper.find("ul.list").attributes("aria-busy")).toBe("true");
  });

  it("says nothing matched, naming the query", () => {
    expect(searching([], { query: "  zzz " }).find(".empty").text()).toBe('No chats match "zzz".');
  });

  it("shows a failed search as an alert", () => {
    const wrapper = searching([], { searchError: "boom" });

    expect(wrapper.find('[role="alert"]').text()).toBe("Search failed: boom");
  });
});
