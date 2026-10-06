import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatSearchHit } from "../api/ChatsClient";
import type { ChatFolder } from "../api/FoldersClient";
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

// Mounted on the body: the menu teleports there, and focus needs an attached tree.
const mounted: { unmount(): void }[] = [];

function mountSidebar(props: Partial<Props> = {}) {
  const wrapper = mount(ConversationSidebar, {
    props: { conversations: [chat("1"), chat("2")], activeId: null, locked: false, ...props },
    attachTo: document.body,
  });
  mounted.push(wrapper);
  return wrapper;
}

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  document.body.innerHTML = "";
});

const searching = (hits: ChatSearchHit[], extra: Partial<Props> = {}) =>
  mountSidebar({ query: "ab", searchActive: true, hits, ...extra });

const folder = (id: number, name = `Folder ${id}`): ChatFolder => ({ id, name, position: id, chat_count: 0 });
const inFolder = (id: string, folderId: number | null, extra: Partial<Conversation> = {}): Conversation => ({
  ...chat(id),
  folderId,
  ...extra,
});
// A row's "..." button (folder headers have their own, found as "header button.more").
const menuButton = (wrapper: ReturnType<typeof mountSidebar>, index = 0) => wrapper.findAll("li.row button.more")[index]!;
const menuItem = (label: string) =>
  [...document.body.querySelectorAll<HTMLElement>('[role^="menuitem"]')].find((b) => b.textContent?.includes(label));
const openMenu = () => document.body.querySelector('[role="menu"]');

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
    await wrapper.find(".title").trigger("dblclick"); // rename the first chat
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
    await wrapper.find(".title").trigger("dblclick");
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

describe("sections", () => {
  it("shows a flat list with no headers when there are no pins or folders", () => {
    const wrapper = mountSidebar();

    expect(wrapper.find("header").exists()).toBe(false);
    expect(wrapper.findAll("li.row")).toHaveLength(2);
  });

  it("groups chats under Pinned, each folder and Chats", () => {
    const wrapper = mountSidebar({
      conversations: [chat("p"), inFolder("a", 1), inFolder("b", null)].map((c) => (c.id === "p" ? { ...c, pinned: true } : c)),
      folders: [folder(1, "Work"), folder(2, "Empty")],
    });

    const headers = wrapper.findAll("header").map((h) => h.find(".name").text());
    expect(headers).toEqual(["Pinned", "Work", "Empty", "Chats"]);
    expect(wrapper.findAll("header .count").map((c) => c.text())).toEqual(["1", "1", "0", "1"]);
  });

  it("hides the rows of a collapsed folder and asks to toggle one", async () => {
    const wrapper = mountSidebar({
      conversations: [inFolder("a", 1)],
      folders: [folder(1, "Work")],
      collapsedFolders: [1],
    });

    expect(wrapper.findAll("li.row")).toHaveLength(0);
    await wrapper.find("button.toggle").trigger("click");
    expect(wrapper.emitted("toggleFolder")).toEqual([[1]]);
  });

  it("shows folders even when there are no chats", () => {
    const wrapper = mountSidebar({ conversations: [], folders: [folder(1, "Work")] });

    expect(wrapper.find("header .name").text()).toBe("Work");
    expect(wrapper.text()).not.toContain("No saved chats yet.");
  });

  it("search results stay flat even with folders", () => {
    const wrapper = searching([hit("1")], { folders: [folder(1)] });

    expect(wrapper.find("header").exists()).toBe(false);
  });

  it("select mode hides the ... buttons of rows and folder headers", async () => {
    const wrapper = mountSidebar({ conversations: [inFolder("a", 1), chat("b")], folders: [folder(1, "Work")] });
    expect(wrapper.findAll("button.more").length).toBeGreaterThan(0);

    await wrapper.find("button.link").trigger("click"); // Select

    expect(wrapper.find("button.more").exists()).toBe(false);
  });
});

describe("the row menu", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens from the ... button with Pin, Move to..., Rename and Delete", async () => {
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");

    expect([...document.body.querySelectorAll('[role="menuitem"]')].map((b) => b.textContent?.replace("›", "").trim())).toEqual([
      "Pin",
      "Move to...",
      "Rename",
      "Delete",
    ]);
  });

  it("Pin and Unpin report the chat", async () => {
    const wrapper = mountSidebar({ conversations: [chat("1"), { ...chat("2"), pinned: true }], folders: [] });

    await menuButton(wrapper, 0).trigger("click"); // the pinned chat comes first
    menuItem("Unpin")!.click();
    await menuButton(wrapper, 1).trigger("click");
    menuItem("Pin")!.click();

    expect(wrapper.emitted("pin")).toEqual([["2", false], ["1", true]]);
  });

  it("Rename starts the inline rename of that row", async () => {
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");
    menuItem("Rename")!.click();
    await wrapper.vm.$nextTick();

    expect(wrapper.find("input.rename").exists()).toBe(true);
  });

  it("Delete asks first, then reports the chat", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");
    menuItem("Delete")!.click();

    expect(confirmSpy).toHaveBeenCalledWith('Delete "Chat 1"? This can\'t be undone.');
    expect(wrapper.emitted("delete")).toEqual([["1"]]);
  });

  it("Delete does nothing when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");
    menuItem("Delete")!.click();

    expect(wrapper.emitted("delete")).toBeUndefined();
  });

  it("Move to... reports the chosen folder, None, or a new folder", async () => {
    const wrapper = mountSidebar({ folders: [folder(1, "Work")] });
    const moveVia = async (label: string) => {
      await menuButton(wrapper).trigger("click");
      menuItem("Move to...")!.click();
      await wrapper.vm.$nextTick();
      menuItem(label)!.click();
      await wrapper.vm.$nextTick();
    };

    await moveVia("Work");
    await moveVia("No folder");
    await moveVia("New folder...");

    expect(wrapper.emitted("move")).toEqual([["1", 1], ["1", null]]);
    expect(wrapper.emitted("moveNew")).toEqual([["1"]]);
  });

  it("the chat that is answering cannot be moved or deleted from its menu", async () => {
    const wrapper = mountSidebar({ conversations: [chat("1")], activeId: "1", locked: true });

    await menuButton(wrapper).trigger("click");

    expect(menuItem("Move to...")!.hasAttribute("disabled")).toBe(true);
    expect(menuItem("Delete")!.hasAttribute("disabled")).toBe(true);
    expect(menuItem("Pin")!.hasAttribute("disabled")).toBe(false);
    expect(menuItem("Rename")!.hasAttribute("disabled")).toBe(false);
  });

  it("closes on Escape and gives focus back to its button", async () => {
    const wrapper = mountSidebar();
    const button = menuButton(wrapper);
    await button.trigger("click");
    await flushPromises(); // the menu focuses its first item once placed

    document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await flushPromises();

    expect(openMenu()).toBeNull();
    expect(document.activeElement).toBe(button.element);
  });

  it("does not give focus back to its button after a choice", async () => {
    const wrapper = mountSidebar();
    const button = menuButton(wrapper);
    await button.trigger("click");
    await flushPromises();

    menuItem("Pin")!.click();
    await flushPromises();

    expect(wrapper.emitted("pin")).toEqual([["1", true]]);
    expect(openMenu()).toBeNull();
    expect(document.activeElement).not.toBe(button.element);
  });

  it("the ... button of the open menu closes it instead of reopening it", async () => {
    const wrapper = mountSidebar();
    const button = menuButton(wrapper);
    await button.trigger("click");
    await flushPromises();
    expect(openMenu()).not.toBeNull();

    // A real press: pointerdown (which the button keeps from the menu), then click.
    button.element.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await button.trigger("click");
    await flushPromises();

    expect(openMenu()).toBeNull();
  });

  it("another row's ... button replaces the open menu", async () => {
    const wrapper = mountSidebar({ conversations: [chat("1"), { ...chat("2"), pinned: true }] });

    await menuButton(wrapper, 0).trigger("click"); // chat 2, pinned
    await menuButton(wrapper, 1).trigger("click"); // chat 1

    expect(document.body.querySelectorAll('[role="menu"][aria-label="Chat actions"]')).toHaveLength(1);
    expect(menuItem("Unpin")).toBeUndefined();
    expect(menuItem("Pin")).toBeDefined();
  });

  it("another owner's ... button opens a new menu at that button, with focus in it and no old flyout", async () => {
    const wrapper = mountSidebar({ folders: [folder(1, "Work")] });
    const at = (el: Element, left: number, bottom: number) => {
      el.getBoundingClientRect = () => ({ left, bottom, top: bottom - 20, right: left + 20, width: 20, height: 20, x: left, y: bottom - 20, toJSON: () => ({}) });
    };
    const first = menuButton(wrapper, 0);
    const second = menuButton(wrapper, 1);
    const header = wrapper.find("header button.more");
    at(first.element, 20, 40);
    at(second.element, 30, 80);
    at(header.element, 50, 120);

    await first.trigger("click");
    await flushPromises();
    const firstMenu = openMenu();
    menuItem("Move to...")!.click(); // opens the flyout
    await flushPromises();
    expect(document.body.querySelector(".flyout")).not.toBeNull();

    await second.trigger("click");
    await flushPromises();
    const secondMenu = openMenu() as HTMLElement;
    expect(secondMenu).not.toBe(firstMenu);
    expect(secondMenu.style.left).toBe("30px");
    expect(secondMenu.style.top).toBe("80px");
    expect(secondMenu.contains(document.activeElement)).toBe(true);
    expect(document.body.querySelector(".flyout")).toBeNull();

    await header.trigger("click"); // chat menu to folder menu
    await flushPromises();
    const folderMenu = openMenu() as HTMLElement;
    expect(folderMenu).not.toBe(secondMenu);
    expect(folderMenu.getAttribute("aria-label")).toBe("Folder actions");
    expect(folderMenu.style.left).toBe("50px");
    expect(folderMenu.style.top).toBe("120px");
    expect(folderMenu.contains(document.activeElement)).toBe(true);
  });

  it("closes when its chat leaves the list", async () => {
    const wrapper = mountSidebar();
    await menuButton(wrapper).trigger("click");

    await wrapper.setProps({ conversations: [chat("2")] });

    expect(openMenu()).toBeNull();
  });

  it("closes when its folder goes away", async () => {
    const wrapper = mountSidebar({ conversations: [], folders: [folder(1, "Work"), folder(2, "Home")] });
    await wrapper.find("header button.more").trigger("click");

    await wrapper.setProps({ folders: [folder(2, "Home")] });

    expect(openMenu()).toBeNull();
  });

  it("stays open, and follows the chat, when the list changes in other ways", async () => {
    const wrapper = mountSidebar();
    await menuButton(wrapper).trigger("click");
    expect(menuItem("Pin")).toBeDefined();

    await wrapper.setProps({ conversations: [{ ...chat("1"), pinned: true }, chat("2")] });

    expect(openMenu()).not.toBeNull();
    expect(menuItem("Unpin")).toBeDefined();
  });

  it("a folder menu reports the folder as it is now", async () => {
    const wrapper = mountSidebar({ conversations: [], folders: [folder(1, "Work")] });
    await wrapper.find("header button.more").trigger("click");

    await wrapper.setProps({ folders: [folder(1, "Renamed")] });
    menuItem("Rename")!.click();

    expect(wrapper.emitted("renameFolder")).toEqual([[folder(1, "Renamed")]]);
  });

  it("closes when the sidebar scrolls, since it would drift away from its row", async () => {
    const wrapper = mountSidebar();
    await menuButton(wrapper).trigger("click");

    await wrapper.find("aside").trigger("scroll");

    expect(openMenu()).toBeNull();
  });

  it("closes when select mode starts", async () => {
    const wrapper = mountSidebar();
    await menuButton(wrapper).trigger("click");

    await wrapper.find("button.link").trigger("click"); // Select

    expect(openMenu()).toBeNull();
  });

  it("closes when a search starts", async () => {
    const wrapper = mountSidebar();
    await menuButton(wrapper).trigger("click");

    await wrapper.setProps({ query: "ab", searchActive: true, hits: [hit("1")] });

    expect(openMenu()).toBeNull();
  });

  it("a folder header has a menu with Rename and Delete that report the folder", async () => {
    const wrapper = mountSidebar({ conversations: [], folders: [folder(1, "Work")] });

    await wrapper.find("header button.more").trigger("click");
    menuItem("Rename")!.click();
    await wrapper.vm.$nextTick();
    await wrapper.find("header button.more").trigger("click");
    menuItem("Delete")!.click();

    expect(wrapper.emitted("renameFolder")).toEqual([[folder(1, "Work")]]);
    expect(wrapper.emitted("deleteFolder")).toEqual([[folder(1, "Work")]]);
  });

  it("a folder header's ... button closes its own open menu", async () => {
    const wrapper = mountSidebar({ conversations: [], folders: [folder(1, "Work")] });
    const button = wrapper.find("header button.more");
    await button.trigger("click");
    expect(openMenu()).not.toBeNull();

    button.element.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await button.trigger("click");

    expect(openMenu()).toBeNull();
  });
});

describe("the footer", () => {
  it("has a New folder button that asks for a new folder", async () => {
    const wrapper = mountSidebar();

    await wrapper.find("button.new-folder").trigger("click");

    expect(wrapper.emitted("newFolder")).toHaveLength(1);
  });

  it("shows New folder even with no chats, and disables it at the folder limit", () => {
    const empty = mountSidebar({ conversations: [] });
    expect(empty.find("button.new-folder").exists()).toBe(true);

    const full = mountSidebar({ folders: Array.from({ length: 30 }, (_, i) => folder(i + 1)) });
    expect(full.find("button.new-folder").attributes("disabled")).toBeDefined();
  });

  it("is hidden while searching or selecting", async () => {
    expect(searching([hit("1")]).find("button.new-folder").exists()).toBe(false);

    const wrapper = mountSidebar();
    await wrapper.find("button.link").trigger("click"); // Select
    expect(wrapper.find("button.new-folder").exists()).toBe(false);
  });
});
