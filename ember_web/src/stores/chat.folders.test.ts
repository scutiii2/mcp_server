import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage } from "../api/types";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

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
    update: vi.fn(),
    importChats: vi.fn(),
    append: vi.fn(),
    branch: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({ chimeIfAway: vi.fn() }));

const client = vi.mocked(chatsClient);

const summary = (id: string, extra: Partial<ChatSummary> = {}): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "main",
  message_count: 2,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running: false,
  ...extra,
});
const TWO: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
];

async function setup(list: ChatSummary[]) {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use"] };
  client.list.mockResolvedValue(list);
  client.get.mockImplementation(async (id: string) => ({ ...summary(id), messages: structuredClone(TWO) }));
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

const row = (chat: ReturnType<typeof useChatStore>, id: string) => chat.sortedConversations.find((c) => c.id === id);

beforeEach(() => {
  vi.clearAllMocks();
  client.search.mockResolvedValue([]);
  client.update.mockResolvedValue(summary("x"));
});

describe("listing", () => {
  it("reads folder and pin from the list, with defaults for an older ember_api", async () => {
    const chat = await setup([summary("a", { folder_id: 4, pinned: true }), summary("b")]);

    expect([row(chat, "a")?.folderId, row(chat, "a")?.pinned]).toEqual([4, true]);
    expect([row(chat, "b")?.folderId, row(chat, "b")?.pinned]).toEqual([null, false]);
  });

  it("a reload brings in a folder change made elsewhere, even for a chat whose messages are loaded", async () => {
    const chat = await setup([summary("a")]);
    await chat.selectChat("a");
    client.list.mockResolvedValue([summary("a", { folder_id: 9, pinned: true })]);

    await chat.reload();

    expect([row(chat, "a")?.folderId, row(chat, "a")?.pinned]).toEqual([9, true]);
    expect(row(chat, "a")?.messages).toHaveLength(2); // messages kept
  });
});

describe("moving and pinning", () => {
  it("setChatFolder changes the screen first, then tells ember_api once", async () => {
    const chat = await setup([summary("a")]);

    chat.setChatFolder("a", 3);
    expect(row(chat, "a")?.folderId).toBe(3);
    await flushPromises();

    expect(client.update).toHaveBeenCalledExactlyOnceWith("a", { folder_id: 3 });
  });

  it("setChatFolder null takes the chat out of its folder", async () => {
    const chat = await setup([summary("a", { folder_id: 3 })]);

    chat.setChatFolder("a", null);
    await flushPromises();

    expect(row(chat, "a")?.folderId).toBeNull();
    expect(client.update).toHaveBeenCalledWith("a", { folder_id: null });
  });

  it("does nothing when the folder is already that one, or the chat is unknown", async () => {
    const chat = await setup([summary("a", { folder_id: 3 })]);

    chat.setChatFolder("a", 3);
    chat.setChatFolder("nope", 3);
    await flushPromises();

    expect(client.update).not.toHaveBeenCalled();
  });

  it("setChatPinned pins and unpins", async () => {
    const chat = await setup([summary("a")]);

    chat.setChatPinned("a", true);
    await flushPromises();
    expect(row(chat, "a")?.pinned).toBe(true);
    chat.setChatPinned("a", false);
    await flushPromises();

    expect(client.update.mock.calls).toEqual([
      ["a", { pinned: true }],
      ["a", { pinned: false }],
    ]);
  });

  it("a 404 from ember_api (chat gone) is not an error", async () => {
    const { ApiError } = await import("../api/http");
    client.update.mockRejectedValue(new ApiError(404, "Chat not found"));
    const chat = await setup([summary("a")]);

    chat.setChatPinned("a", true);
    await flushPromises();

    expect(chat.saveError).toBe("");
  });
});

describe("branching", () => {
  it("a branch lands in the same folder as its source, unpinned", async () => {
    const chat = await setup([summary("a", { folder_id: 3, pinned: true })]);
    await chat.selectChat("a");
    client.branch.mockResolvedValue({
      ...summary("b", { folder_id: 3, pinned: false }),
      messages: structuredClone(TWO),
    });

    await chat.branchFrom(1);

    expect([row(chat, "b")?.folderId, row(chat, "b")?.pinned]).toEqual([3, false]);
  });
});

describe("forgetFolder", () => {
  it("drops that folder's chats from the screen without telling ember_api", async () => {
    const chat = await setup([summary("a", { folder_id: 3 }), summary("b", { folder_id: 3 }), summary("c", { folder_id: 4 }), summary("d")]);

    chat.forgetFolder(3);
    await flushPromises();

    expect(chat.sortedConversations.map((c) => c.id).sort()).toEqual(["c", "d"]);
    expect(client.remove).not.toHaveBeenCalled();
  });

  it("closes the open chat when it was in the folder", async () => {
    const chat = await setup([summary("a", { folder_id: 3 }), summary("d")]);
    await chat.selectChat("a");
    expect(chat.activeId).toBe("a");

    chat.forgetFolder(3);

    expect(chat.activeId).toBeNull();
  });

  it("leaves everything alone when no chat is in it", async () => {
    const chat = await setup([summary("a")]);

    chat.forgetFolder(99);

    expect(chat.sortedConversations).toHaveLength(1);
  });
});
