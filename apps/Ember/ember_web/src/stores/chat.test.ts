import { accountCapabilitiesClient } from "../api/AccountCapabilitiesClient";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSearchHit, type ChatSummary } from "../api/ChatsClient";
import { ApiError } from "../api/http";
import type { ChatMessage } from "../api/types";
import { withAttachments } from "../utils/attachments";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: vi.fn(), set: vi.fn() },
}));
vi.mock("../api/ChatsClient", () => ({
  chatsClient: {
    list: vi.fn(),
    get: vi.fn(),
    startTurn: vi.fn(),
    cancel: vi.fn(),
    search: vi.fn(),
    remove: vi.fn(),
    removeAll: vi.fn(),
    rename: vi.fn(),
    importChats: vi.fn(),
    append: vi.fn(),
    branch: vi.fn(),
  },
}));
// The live answer stream is not under test: a watch that ends at once.
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn(() => Promise.resolve("aborted")) }));

const client = vi.mocked(chatsClient);

const ACCOUNT = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"],
};

function summary(id: string, count = 0): ChatSummary {
  return {
    id,
    title: `Chat ${id}`,
    agent_id: "a1",
    message_count: count,
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    running: false,
  };
}

const user = (content: string): ChatMessage => ({ role: "user", content });
const assistant = (content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
  role: "assistant",
  content,
  ...extra,
});
const contents = (list: ChatMessage[]): string[] => list.map((m) => m.content);

const FOUR: ChatMessage[] = [user("q1"), assistant("a1"), user("q2"), assistant("a2")];

/** A logged-in chat store with the given chats in the list; `transcripts`
 * maps a chat id to what opening it returns. */
async function storeWith(transcripts: Record<string, ChatMessage[]>) {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT;
  client.list.mockResolvedValue(Object.entries(transcripts).map(([id, m]) => summary(id, m.length)));
  client.get.mockImplementation(async (id: string) => ({
    ...summary(id, transcripts[id]!.length),
    messages: structuredClone(transcripts[id]!),
  }));
  const chat = useChatStore();
  await flushPromises(); // the list loads as the store is created
  return chat;
}

/** A store with chat "c1" open. */
async function openChat(messages: ChatMessage[]) {
  const chat = await storeWith({ c1: messages });
  await chat.selectChat("c1");
  return chat;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(accountCapabilitiesClient.get).mockResolvedValue({ capabilities: [], extensions: [], disabled_tools: [] });
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1"), running: true }, sequence: 5 });
  client.search.mockResolvedValue([]);
  client.remove.mockResolvedValue(undefined);
  client.rename.mockResolvedValue(summary("c1"));
  client.cancel.mockResolvedValue({ cancelled: true });
});

describe("send with truncateTo (regenerate / edit)", () => {
  it("drops the replaced question and what followed, and tells ember_api", async () => {
    const chat = await openChat(FOUR);

    await chat.send("q2 edited", { truncateTo: 2 });

    expect(client.startTurn).toHaveBeenCalledWith(
      "c1",
      expect.objectContaining({ question: "q2 edited", truncate_to: 2 }),
    );
    expect(contents(chat.messages)).toEqual(["q1", "a1", "q2 edited"]);
  });

  it("truncateTo 0 restarts the conversation from the new question", async () => {
    const chat = await openChat(FOUR);

    await chat.send("fresh", { truncateTo: 0 });

    expect(contents(chat.messages)).toEqual(["fresh"]);
  });

  it("brings the old messages back when ember_api refuses", async () => {
    client.startTurn.mockRejectedValue(new ApiError(409, "An answer is still being written for this chat"));
    const chat = await openChat(FOUR);

    await chat.send("q2 edited", { truncateTo: 2 });

    expect(contents(chat.messages)).toEqual(["q1", "a1", "q2", "a2"]);
    expect(chat.sendError).toBe("An answer is still being written for this chat");
    expect(chat.busy).toBe(false);
  });

  it("says the question was not taken when there is no entry agent (503), so the typed text can be given back", async () => {
    client.startTurn.mockRejectedValue(new ApiError(503, "No entry agent registered"));
    const chat = await openChat(FOUR);

    const taken = await chat.send("a long question I typed");

    expect(taken).toBe(false);
    expect(chat.sendError).toBe("No entry agent registered");
    expect(contents(chat.messages)).toEqual(["q1", "a1", "q2", "a2"]);
  });

  it("says the question was taken when the turn starts", async () => {
    const chat = await openChat(FOUR);

    expect(await chat.send("q3")).toBe(true);
    expect(chat.sendError).toBe("");
  });

  it("sends nothing for a target that is not a typed question", async () => {
    const chat = await openChat([assistant("summary", { kind: "summary" }), user("/x y"), ...FOUR]);
    chat.messages[1]!.kind = "command";

    for (const index of [0, 1, 3, 99]) await chat.send("x", { truncateTo: index });

    expect(client.startTurn).not.toHaveBeenCalled();
    expect(chat.messages).toHaveLength(6);
  });

  it("a plain send has no truncate_to", async () => {
    const chat = await openChat(FOUR);

    await chat.send("q3");

    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("truncate_to");
    expect(contents(chat.messages)).toEqual(["q1", "a1", "q2", "a2", "q3"]);
  });

  it("sends a replacement that starts with '/' to the agent, not as a command", async () => {
    const chat = await openChat(FOUR);

    await chat.send("/not-a-command", { truncateTo: 2 });

    expect(client.startTurn).toHaveBeenCalledWith("c1", expect.objectContaining({ question: "/not-a-command" }));
    expect(chat.sendError).toBe("");
  });
});

describe("regenerateIndex", () => {
  it.each<[string, ChatMessage[], number]>([
    ["a question and its answer", [user("q"), assistant("a")], 0],
    ["the last of two exchanges", FOUR, 2],
    ["an error answer", [user("q"), assistant("error: down")], 0],
    ["history after a summary", [assistant("S", { kind: "summary" }), assistant("raw", { kind: "log_attachment" }), user("q"), assistant("a")], 2],
    ["a question still without an answer", [user("q")], -1],
    ["a chat that ends in a summary", [assistant("S", { kind: "summary" })], -1],
    ["nothing typed to redo (only a summary and an answer)", [assistant("S", { kind: "summary" }), assistant("a")], -1],
    ["an empty chat", [], -1],
  ])("%s", async (_name, messages, expected) => {
    const chat = await openChat(messages);

    expect(chat.regenerateIndex).toBe(expected);
  });

  it("is -1 when the chat ends with a slash command's result", async () => {
    const chat = await openChat([user("q"), assistant("a"), user("/x y"), assistant("result")]);
    chat.messages[2]!.kind = "command";
    chat.messages[3]!.kind = "command";

    expect(chat.regenerateIndex).toBe(-1);
  });
});

describe("regenerate", () => {
  it("asks the last question again, replacing its answer", async () => {
    const chat = await openChat(FOUR);

    await chat.regenerate();

    expect(client.startTurn).toHaveBeenCalledWith("c1", expect.objectContaining({ question: "q2", truncate_to: 2 }));
    expect(contents(chat.messages)).toEqual(["q1", "a1", "q2"]);
  });

  it("keeps an attached file in the resent question", async () => {
    const question = withAttachments("look", [{ filename: "f.txt", chars: 3, truncated: false, text: "abc" }]);
    const chat = await openChat([user(question), assistant("a")]);

    await chat.regenerate();

    expect(client.startTurn.mock.calls[0]![1].question).toBe(question);
  });

  it("does nothing when there is no answer to redo", async () => {
    const chat = await openChat([user("q")]);

    await chat.regenerate();

    expect(client.startTurn).not.toHaveBeenCalled();
  });
});

describe("editAndResend", () => {
  const FILE = { filename: "f.txt", chars: 3, truncated: false, text: "abc" };

  it("replaces the question and everything after it", async () => {
    const chat = await openChat(FOUR);

    await chat.editAndResend(0, "  q1 edited  ");

    expect(client.startTurn).toHaveBeenCalledWith("c1", expect.objectContaining({ question: "q1 edited", truncate_to: 0 }));
    expect(contents(chat.messages)).toEqual(["q1 edited"]);
  });

  it("keeps the attached files of the question it replaces", async () => {
    const chat = await openChat([user(withAttachments("old", [FILE])), assistant("a")]);

    await chat.editAndResend(0, "new");

    expect(client.startTurn.mock.calls[0]![1].question).toBe(withAttachments("new", [FILE]));
  });

  it("a blank edit of a question with a file still sends the file", async () => {
    const chat = await openChat([user(withAttachments("old", [FILE])), assistant("a")]);

    await chat.editAndResend(0, "   ");

    expect(client.startTurn.mock.calls[0]![1].question).toBe(withAttachments("", [FILE]));
  });

  it("a blank edit of a plain question sends nothing", async () => {
    const chat = await openChat(FOUR);

    await chat.editAndResend(0, "   ");

    expect(client.startTurn).not.toHaveBeenCalled();
    expect(contents(chat.messages)).toEqual(["q1", "a1", "q2", "a2"]);
  });

  it("refuses to edit an answer or an index that is not there", async () => {
    const chat = await openChat(FOUR);

    await chat.editAndResend(1, "x");
    await chat.editAndResend(42, "x");

    expect(client.startTurn).not.toHaveBeenCalled();
  });
});

describe("search", () => {
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

  /** A promise the test settles by hand. */
  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
  }

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function quietStore() {
    const chat = await storeWith({ c1: FOUR });
    return chat;
  }

  it("needs two characters and waits for a pause in typing", async () => {
    const chat = await quietStore();

    chat.setSearch("a");
    await vi.advanceTimersByTimeAsync(500);
    expect(client.search).not.toHaveBeenCalled();
    expect(chat.searchActive).toBe(false);

    chat.setSearch("ab");
    expect(chat.searchActive).toBe(true);
    expect(chat.searching).toBe(true);
    await vi.advanceTimersByTimeAsync(249);
    expect(client.search).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);

    expect(client.search).toHaveBeenCalledExactlyOnceWith("ab");
    expect(chat.searching).toBe(false);
  });

  it("sends only the last of several quick keystrokes, trimmed", async () => {
    const chat = await quietStore();

    chat.setSearch("ab");
    await vi.advanceTimersByTimeAsync(100);
    chat.setSearch("  abc ");
    await vi.advanceTimersByTimeAsync(250);

    expect(client.search).toHaveBeenCalledExactlyOnceWith("abc");
  });

  it("stores the hits", async () => {
    client.search.mockResolvedValue([hit("c1", { message_index: 1, message_matches: 2 })]);
    const chat = await quietStore();

    chat.setSearch("q1");
    await vi.advanceTimersByTimeAsync(250);

    expect(chat.searchHits.map((h) => h.id)).toEqual(["c1"]);
  });

  it("drops the answer to an older query that arrives late", async () => {
    const slow = deferred<ChatSearchHit[]>();
    const fast = deferred<ChatSearchHit[]>();
    client.search.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
    const chat = await quietStore();

    chat.setSearch("abc");
    await vi.advanceTimersByTimeAsync(250);
    chat.setSearch("abcd");
    await vi.advanceTimersByTimeAsync(250);
    fast.resolve([hit("new")]);
    await vi.advanceTimersByTimeAsync(0);
    slow.resolve([hit("old")]);
    await vi.advanceTimersByTimeAsync(0);

    expect(chat.searchHits.map((h) => h.id)).toEqual(["new"]);
    expect(chat.searching).toBe(false);
  });

  it("shows the error and no hits when the search fails", async () => {
    client.search.mockRejectedValue(new Error("boom"));
    const chat = await quietStore();

    chat.setSearch("ab");
    await vi.advanceTimersByTimeAsync(250);

    expect(chat.searchError).toBe("boom");
    expect(chat.searchHits).toEqual([]);
    expect(chat.searching).toBe(false);
  });

  it("clearing the box clears hits and cancels a request not yet sent", async () => {
    client.search.mockResolvedValue([hit("c1")]);
    const chat = await quietStore();
    chat.setSearch("ab");
    await vi.advanceTimersByTimeAsync(250);
    expect(chat.searchHits).toHaveLength(1);

    chat.setSearch("");
    expect(chat.searchHits).toEqual([]);
    expect(chat.searchActive).toBe(false);

    chat.setSearch("xy");
    chat.clearSearch();
    await vi.advanceTimersByTimeAsync(500);
    expect(client.search).toHaveBeenCalledTimes(1);
  });

  it("removes a deleted chat from the results", async () => {
    client.search.mockResolvedValue([hit("c1"), hit("c2")]);
    const chat = await storeWith({ c1: FOUR, c2: FOUR });
    chat.setSearch("q1");
    await vi.advanceTimersByTimeAsync(250);

    chat.deleteChat("c1");

    expect(chat.searchHits.map((h) => h.id)).toEqual(["c2"]);
  });

  it("shows a renamed chat's new title and drops the stale highlight", async () => {
    client.search.mockResolvedValue([hit("c1", { title_match: { start: 0, length: 4 } })]);
    const chat = await storeWith({ c1: FOUR });
    chat.setSearch("chat");
    await vi.advanceTimersByTimeAsync(250);

    chat.renameChat("c1", "Something else");

    expect(chat.searchHits[0]).toMatchObject({ title: "Something else", title_match: null });
  });

  it("empties the box and results when the account changes", async () => {
    client.search.mockResolvedValue([hit("c1")]);
    const chat = await quietStore();
    chat.setSearch("ab");
    await vi.advanceTimersByTimeAsync(250);

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await vi.advanceTimersByTimeAsync(0);

    expect(chat.searchQuery).toBe("");
    expect(chat.searchHits).toEqual([]);
  });
});

describe("jumpIndex (opening a search result)", () => {
  it("is set by selecting a chat with a message index, and cleared by clearJump", async () => {
    const chat = await storeWith({ c1: FOUR, c2: [user("x")] });

    await chat.selectChat("c1", { messageIndex: 3 });
    expect(chat.jumpIndex).toBe(3);
    expect(chat.activeId).toBe("c1");

    chat.clearJump();
    expect(chat.jumpIndex).toBeNull();
  });

  it("is set again by opening a result of the chat that is already open", async () => {
    const chat = await storeWith({ c1: FOUR });
    await chat.selectChat("c1", { messageIndex: 1 });
    chat.clearJump();

    await chat.selectChat("c1", { messageIndex: 2 });

    expect(chat.jumpIndex).toBe(2);
  });

  it("opening a chat without an index leaves no target behind", async () => {
    const chat = await storeWith({ c1: FOUR, c2: [user("x")] });
    await chat.selectChat("c1", { messageIndex: 3 });

    await chat.selectChat("c2");

    expect(chat.jumpIndex).toBeNull();
  });

  it("starting a new chat or deleting the open one clears it", async () => {
    const chat = await storeWith({ c1: FOUR, c2: FOUR });
    await chat.selectChat("c1", { messageIndex: 1 });

    chat.newChat();
    expect(chat.jumpIndex).toBeNull();

    await chat.selectChat("c2", { messageIndex: 1 });
    chat.deleteChat("c2");
    expect(chat.jumpIndex).toBeNull();
  });

  it("an unknown chat changes nothing", async () => {
    const chat = await storeWith({ c1: FOUR });
    await chat.selectChat("c1", { messageIndex: 1 });

    await chat.selectChat("nope", { messageIndex: 9 });

    expect(chat.jumpIndex).toBe(1);
    expect(chat.activeId).toBe("c1");
  });
});

describe("branchFrom (fork a chat at an answer)", () => {
  const branchOf = (id: string, messages: ChatMessage[], extra: Partial<ChatSummary> = {}) => ({
    ...summary(id, messages.length),
    title: "Branch of Chat c1",
    created_at: "2026-01-02T00:00:00",
    updated_at: "2026-01-02T00:00:00",
    messages,
    ...extra,
  });

  it("opens a new chat holding the copied messages, and leaves the original alone", async () => {
    client.branch.mockResolvedValue(branchOf("b1", FOUR.slice(0, 2)));
    const chat = await openChat(FOUR);

    await chat.branchFrom(1);

    expect(client.branch).toHaveBeenCalledExactlyOnceWith("c1", 1);
    expect(chat.activeId).toBe("b1");
    expect(chat.active?.title).toBe("Branch of Chat c1");
    expect(contents(chat.messages)).toEqual(["q1", "a1"]);
    expect(chat.working).toBe("");
    expect(chat.sendError).toBe("");
    // The original is still in the list, complete, and the branch is listed first.
    const original = chat.sortedConversations.find((c) => c.id === "c1")!;
    expect(contents(original.messages)).toEqual(["q1", "a1", "q2", "a2"]);
    expect(chat.sortedConversations.map((c) => c.id)).toEqual(["b1", "c1"]);
  });

  it("the branch is ready to talk in: loaded, not running, and remembers the agent", async () => {
    client.branch.mockResolvedValue(branchOf("b1", FOUR.slice(0, 2)));
    const chat = await openChat(FOUR);

    await chat.branchFrom(1);
    await chat.send("something else");

    expect(client.startTurn).toHaveBeenCalledWith("b1", expect.objectContaining({ question: "something else" }));
    expect(contents(chat.messages)).toEqual(["q1", "a1", "something else"]);
    expect(client.get).toHaveBeenCalledTimes(1); // only the original was ever fetched
  });

  it("can branch a branch", async () => {
    client.branch.mockResolvedValueOnce(branchOf("b1", FOUR.slice(0, 4))).mockResolvedValueOnce(branchOf("b2", FOUR.slice(0, 2)));
    const chat = await openChat(FOUR);

    await chat.branchFrom(3);
    await chat.branchFrom(1);

    expect(client.branch.mock.calls).toEqual([
      ["c1", 3],
      ["b1", 1],
    ]);
    expect(chat.activeId).toBe("b2");
  });

  it.each([
    ["a question", 0],
    ["another question", 2],
    ["an index past the end", 9],
    ["a negative index", -1],
  ])("does nothing for %s", async (_name, index) => {
    const chat = await openChat(FOUR);

    await chat.branchFrom(index);

    expect(client.branch).not.toHaveBeenCalled();
    expect(chat.activeId).toBe("c1");
  });

  it("does nothing for a summary or a slash command's result", async () => {
    const chat = await openChat([assistant("S", { kind: "summary" }), user("/x y"), assistant("result"), ...FOUR]);
    chat.messages[1]!.kind = "command";
    chat.messages[2]!.kind = "command";

    for (const index of [0, 1, 2]) await chat.branchFrom(index);

    expect(client.branch).not.toHaveBeenCalled();
  });

  it("does nothing without an open chat", async () => {
    const chat = await storeWith({ c1: FOUR });

    await chat.branchFrom(1);

    expect(client.branch).not.toHaveBeenCalled();
  });

  it("does nothing while an answer is being written", async () => {
    const chat = await openChat(FOUR);
    await chat.send("q3"); // the turn starts and stays running

    await chat.branchFrom(1);

    expect(client.branch).not.toHaveBeenCalled();
  });

  it("waits for unsent changes rather than counting messages ember_api does not have yet", async () => {
    client.rename.mockReturnValue(new Promise(() => {})); // a save that never lands
    const chat = await openChat(FOUR);
    chat.renameChat("c1", "Renamed");

    await chat.branchFrom(1);

    expect(client.branch).not.toHaveBeenCalled();
    expect(chat.sendError).toContain("Still saving");
  });

  it("shows ember_api's message and stays on the original when it fails", async () => {
    client.branch.mockRejectedValue(new ApiError(413, "At most 1000 chats per account - delete some first"));
    const chat = await openChat(FOUR);

    await chat.branchFrom(1);

    expect(chat.sendError).toBe("At most 1000 chats per account - delete some first");
    expect(chat.activeId).toBe("c1");
    expect(chat.sortedConversations).toHaveLength(1);
    expect(chat.working).toBe("");
  });

  it("shows the working state while the request is out", async () => {
    let finish!: (value: ReturnType<typeof branchOf>) => void;
    client.branch.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const chat = await openChat(FOUR);

    const pending = chat.branchFrom(1);
    expect(chat.working).toBe("Branching ...");
    // Nothing else can start meanwhile.
    await chat.send("q3");
    expect(client.startTurn).not.toHaveBeenCalled();

    finish(branchOf("b1", FOUR.slice(0, 2)));
    await pending;
    expect(chat.working).toBe("");
  });

  it("ignores an answer that arrives after the account changed", async () => {
    let finish!: (value: ReturnType<typeof branchOf>) => void;
    client.branch.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const chat = await openChat(FOUR);
    const pending = chat.branchFrom(1);

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish(branchOf("b1", FOUR.slice(0, 2)));
    await pending;

    expect(chat.sortedConversations.map((c) => c.id)).not.toContain("b1");
    expect(chat.activeId).toBeNull();
  });
});

describe("deleteChats (several at once)", () => {
  it("removes every listed chat and tells ember_api about each, in order", async () => {
    const chat = await storeWith({ c1: FOUR, c2: FOUR, c3: FOUR });

    chat.deleteChats(["c1", "c3"]);
    await flushPromises();

    expect(chat.sortedConversations.map((c) => c.id)).toEqual(["c2"]);
    expect(client.remove.mock.calls.map((call) => call[0])).toEqual(["c1", "c3"]);
  });

  it("closes the open chat when it is among them", async () => {
    const chat = await storeWith({ c1: FOUR, c2: FOUR });
    await chat.selectChat("c1");

    chat.deleteChats(["c1", "c2"]);

    expect(chat.activeId).toBeNull();
    expect(chat.messages).toEqual([]);
  });

  it("keeps the open chat when it is not among them", async () => {
    const chat = await storeWith({ c1: FOUR, c2: FOUR });
    await chat.selectChat("c1");

    chat.deleteChats(["c2"]);

    expect(chat.activeId).toBe("c1");
  });

  it("drops the deleted chats from search results and forgets their allowed tools", async () => {
    client.search.mockResolvedValue([
      { id: "c1", title: "Chat c1", updated_at: "x", title_match: null, snippet: null, message_index: null, message_matches: 0 },
      { id: "c2", title: "Chat c2", updated_at: "x", title_match: null, snippet: null, message_index: null, message_matches: 0 },
    ]);
    const chat = await storeWith({ c1: FOUR, c2: FOUR });
    chat.allowedTools = { c1: ["web__fetch"], c2: ["web__fetch"] };
    chat.searchHits = [
      { id: "c1", title: "Chat c1", updated_at: "x", title_match: null, snippet: null, message_index: null, message_matches: 0 },
      { id: "c2", title: "Chat c2", updated_at: "x", title_match: null, snippet: null, message_index: null, message_matches: 0 },
    ];

    chat.deleteChats(["c1"]);

    expect(chat.searchHits.map((h) => h.id)).toEqual(["c2"]);
    expect(chat.allowedTools).toEqual({ c2: ["web__fetch"] });
  });

  it("an empty list changes nothing", async () => {
    const chat = await storeWith({ c1: FOUR });

    chat.deleteChats([]);

    expect(chat.sortedConversations).toHaveLength(1);
    expect(client.remove).not.toHaveBeenCalled();
  });
});

describe("hasChat and listReady (deep links)", () => {
  it("knows which chats are in the list", async () => {
    const chat = await storeWith({ c1: FOUR });

    expect(chat.hasChat("c1")).toBe(true);
    expect(chat.hasChat("nope")).toBe(false);
  });

  it("is not ready until the list has loaded, then is", async () => {
    setActivePinia(createPinia());
    useAuthStore().account = ACCOUNT;
    client.list.mockResolvedValue([summary("c1")]);
    const chat = useChatStore();

    expect(chat.listReady).toBe(false);
    await flushPromises();

    expect(chat.listReady).toBe(true);
  });

  it("is ready even when the list could not be loaded, so a deep link stops waiting", async () => {
    setActivePinia(createPinia());
    useAuthStore().account = ACCOUNT;
    client.list.mockRejectedValue(new Error("down"));
    const chat = useChatStore();
    await flushPromises();

    expect(chat.listReady).toBe(true);
    expect(chat.loadError).toBe("down");
  });

  it("goes back to not ready when the account changes", async () => {
    const chat = await storeWith({ c1: FOUR });
    client.list.mockReturnValue(new Promise(() => {}));

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();

    expect(chat.listReady).toBe(false);
  });
});

describe("send without an agent", () => {
  it("sends no agent id: ember_api picks the agent, and the chat takes the id it reports", async () => {
    const chat = await storeWith({});
    client.startTurn.mockResolvedValue({
      chat: { ...summary("new", 1), agent_id: "main", running: true },
      sequence: 1,
    });

    await chat.send("hello");

    const body = client.startTurn.mock.calls[0]![1];
    expect(body).not.toHaveProperty("agent_id");
    expect(chat.active?.agentId).toBe("main");
  });
});
