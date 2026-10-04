import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatSearchHit } from "../api/ChatsClient";
import type { Conversation } from "../api/types";
import { usageClient } from "../api/UsageClient";
import ConversationSidebar from "./ConversationSidebar.vue";

// The gauges at the bottom read the account usage; not under test here.
vi.mock("../api/UsageClient", () => ({ usageClient: { mine: vi.fn(() => new Promise(() => {})) } }));

const mine = vi.mocked(usageClient.mine);

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

describe("select mode", () => {
  const rows = (wrapper: ReturnType<typeof mountSidebar>) => wrapper.findAll("li.row");
  const ticks = (wrapper: ReturnType<typeof mountSidebar>) => wrapper.findAll("input.tick");
  const three = [chat("1"), chat("2"), chat("3")];
  const selecting = async (props: Partial<Props> = {}) => {
    const wrapper = mountSidebar({ conversations: three, ...props });
    await wrapper.find("button.link").trigger("click"); // "Select"
    return wrapper;
  };
  const bar = (wrapper: ReturnType<typeof mountSidebar>) => wrapper.find(".select-bar");

  afterEach(() => vi.restoreAllMocks());

  it("shows a Select button next to Delete all, and no boxes until it is pressed", () => {
    const wrapper = mountSidebar({ conversations: three });

    expect(wrapper.find(".footer").text()).toContain("Select");
    expect(wrapper.find(".delete-all").exists()).toBe(true);
    expect(ticks(wrapper)).toHaveLength(0);
  });

  it("offers Select with a single chat, but not Delete all", () => {
    const wrapper = mountSidebar({ conversations: [chat("1")] });

    expect(wrapper.find("button.link").text()).toBe("Select");
    expect(wrapper.find(".delete-all").exists()).toBe(false);
  });

  it("gives every chat a box and swaps the footer for the selection bar", async () => {
    const wrapper = await selecting();

    expect(ticks(wrapper)).toHaveLength(3);
    expect(bar(wrapper).exists()).toBe(true);
    expect(wrapper.find(".footer").exists()).toBe(false);
    expect(wrapper.find("button.icon").exists()).toBe(false);
    expect(bar(wrapper).text()).toContain("0 selected");
  });

  it("clicking a row ticks it instead of opening the chat", async () => {
    const wrapper = await selecting();

    await rows(wrapper)[1]!.trigger("click");

    expect(wrapper.emitted("select")).toBeUndefined();
    expect((ticks(wrapper)[1]!.element as HTMLInputElement).checked).toBe(true);
    expect(bar(wrapper).text()).toContain("1 selected");
  });

  it("clicking a box ticks it once, not twice", async () => {
    const wrapper = await selecting();

    await ticks(wrapper)[0]!.trigger("click");

    expect(bar(wrapper).text()).toContain("1 selected");
  });

  it("clicking a ticked row unticks it", async () => {
    const wrapper = await selecting();
    await rows(wrapper)[0]!.trigger("click");

    await rows(wrapper)[0]!.trigger("click");

    expect(bar(wrapper).text()).toContain("0 selected");
  });

  it("All ticks every chat, and again unticks them", async () => {
    const wrapper = await selecting();
    const all = bar(wrapper).find(".all input");

    await all.setValue(true);
    expect(bar(wrapper).text()).toContain("3 selected");

    await all.setValue(false);
    expect(bar(wrapper).text()).toContain("0 selected");
  });

  it("All stays unticked while only some chats are", async () => {
    const wrapper = await selecting();

    await rows(wrapper)[0]!.trigger("click");

    expect((bar(wrapper).find(".all input").element as HTMLInputElement).checked).toBe(false);
  });

  it("All is ticked once every chat is", async () => {
    const wrapper = await selecting();
    for (const row of rows(wrapper)) await row.trigger("click");

    expect((bar(wrapper).find(".all input").element as HTMLInputElement).checked).toBe(true);
  });

  it("Delete is off until something is ticked", async () => {
    const wrapper = await selecting();

    expect(bar(wrapper).find("button.danger").attributes("disabled")).toBeDefined();
    await rows(wrapper)[0]!.trigger("click");
    expect(bar(wrapper).find("button.danger").attributes("disabled")).toBeUndefined();
  });

  it("deletes the ticked chats after confirming, then leaves select mode", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const wrapper = await selecting();
    await rows(wrapper)[0]!.trigger("click");
    await rows(wrapper)[2]!.trigger("click");

    await bar(wrapper).find("button.danger").trigger("click");

    expect(confirmSpy).toHaveBeenCalledWith("Delete 2 chats? This can't be undone.");
    expect(wrapper.emitted("deleteMany")).toEqual([[["1", "3"]]]);
    expect(bar(wrapper).exists()).toBe(false);
    expect(ticks(wrapper)).toHaveLength(0);
  });

  it("says 'chat', not 'chats', for one", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const wrapper = await selecting();
    await rows(wrapper)[0]!.trigger("click");

    await bar(wrapper).find("button.danger").trigger("click");

    expect(confirmSpy).toHaveBeenCalledWith("Delete 1 chat? This can't be undone.");
  });

  it("deletes nothing when the confirmation is declined, and stays in select mode", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const wrapper = await selecting();
    await rows(wrapper)[0]!.trigger("click");

    await bar(wrapper).find("button.danger").trigger("click");

    expect(wrapper.emitted("deleteMany")).toBeUndefined();
    expect(bar(wrapper).text()).toContain("1 selected");
  });

  it("Cancel leaves select mode and forgets the ticks", async () => {
    const wrapper = await selecting();
    await rows(wrapper)[0]!.trigger("click");

    await bar(wrapper).findAll("button").at(-1)!.trigger("click"); // Cancel
    expect(bar(wrapper).exists()).toBe(false);

    await wrapper.find("button.link").trigger("click");
    expect(bar(wrapper).text()).toContain("0 selected");
  });

  it("will not tick the chat that is answering while the sidebar is locked", async () => {
    const wrapper = await selecting({ locked: true, activeId: "2" });

    expect(ticks(wrapper)[1]!.attributes("disabled")).toBeDefined();
    await rows(wrapper)[1]!.trigger("click");
    expect(bar(wrapper).text()).toContain("0 selected");
    expect((ticks(wrapper)[1]!.element as HTMLInputElement).checked).toBe(false);

    await bar(wrapper).find(".all input").setValue(true);
    expect(bar(wrapper).text()).toContain("2 selected");
  });

  it("leaves select mode when a search starts, since results can't be ticked", async () => {
    const wrapper = await selecting();

    await wrapper.setProps({ query: "ab", searchActive: true, hits: [hit("1")] });

    expect(bar(wrapper).exists()).toBe(false);
    expect(ticks(wrapper)).toHaveLength(0);
  });

  it("does not count a chat that vanished from the list", async () => {
    const wrapper = await selecting();
    await rows(wrapper)[0]!.trigger("click");
    await rows(wrapper)[1]!.trigger("click");

    await wrapper.setProps({ conversations: [chat("2"), chat("3")] });

    expect(bar(wrapper).text()).toContain("1 selected");
  });

  it("leaves select mode when the last chat is gone", async () => {
    const wrapper = await selecting({ conversations: [chat("1")] });

    await wrapper.setProps({ conversations: [] });

    expect(bar(wrapper).exists()).toBe(false);
  });

  it("a rename in progress ends when selecting starts", async () => {
    const wrapper = mountSidebar({ conversations: three });
    await wrapper.find("button.icon").trigger("click"); // rename the first chat
    expect(wrapper.find("input.rename").exists()).toBe(true);

    await wrapper.find("button.link").trigger("click");

    expect(wrapper.find("input.rename").exists()).toBe(false);
    expect(ticks(wrapper)).toHaveLength(3);
  });

  it("All is off, not ticked, when nothing can be selected", async () => {
    const wrapper = await selecting({ conversations: [chat("1")], locked: true, activeId: "1" });

    const all = bar(wrapper).find(".all input").element as HTMLInputElement;
    expect(all.disabled).toBe(true);
    expect(all.checked).toBe(false);
  });

  it("a rename abandoned by selecting does not come back after Cancel", async () => {
    const wrapper = mountSidebar({ conversations: three });
    await wrapper.find("button.icon").trigger("click");
    await wrapper.find("button.link").trigger("click");

    await bar(wrapper).findAll("button").at(-1)!.trigger("click"); // Cancel

    expect(wrapper.find("input.rename").exists()).toBe(false);
  });

  it("tells the usage gauges when an answer ends", async () => {
    mine.mockClear();
    const wrapper = mountSidebar({ busy: true });
    expect(mine).toHaveBeenCalledOnce();

    await wrapper.setProps({ busy: false });

    expect(mine).toHaveBeenCalledTimes(2);
  });

  it("shows the running dot beside the box", async () => {
    const wrapper = await selecting({ conversations: [{ ...chat("1"), running: true }, chat("2")] });

    expect(rows(wrapper)[0]!.find(".running").exists()).toBe(true);
  });
});
