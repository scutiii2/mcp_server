import { accountCapabilitiesClient } from "../api/AccountCapabilitiesClient";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage, TurnEvent } from "../api/types";
import { watchTurn, type WatchEnd } from "../services/turnStream";
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
    suggestion: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({ chimeIfAway: vi.fn() }));
vi.mock("../services/slashCommands", () => ({
  SlashCommandRunner: class {
    run = vi.fn();
    list = vi.fn(async () => []);
    schemaFor = vi.fn(async () => null);
  },
}));

const client = vi.mocked(chatsClient);
const watch = vi.mocked(watchTurn);

const ACCOUNT = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"],
};

const summary = (id: string, count = 0, running = false): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: count,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running,
});

const TWO: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
];

let emit: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};
let endStream: (end: WatchEnd) => void = () => {
  throw new Error("no answer is being watched");
};
const fire = (event: Record<string, unknown>) => emit({ sequence: 1, ...event } as TurnEvent);
const finalEvent = (cancelled = false) => ({ type: "final", message: { role: "assistant", content: "done" }, cancelled });

async function storeWith(chats: Record<string, ChatMessage[]>, running: string[] = [], account = ACCOUNT) {
  setActivePinia(createPinia());
  useAuthStore().account = account;
  client.list.mockResolvedValue(Object.entries(chats).map(([id, m]) => summary(id, m.length, running.includes(id))));
  client.get.mockImplementation(async (id: string) => ({
    ...summary(id, chats[id]!.length, running.includes(id)),
    messages: structuredClone(chats[id]!),
  }));
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

/** A chat whose answer is being written. */
async function running(chats: Record<string, ChatMessage[]> = { c1: TWO }) {
  const chat = await storeWith(chats);
  await chat.selectChat("c1");
  await chat.send("ask something");
  client.suggestion.mockClear();
  return chat;
}

async function answered() {
  fire(finalEvent());
  endStream("done");
  await flushPromises();
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(accountCapabilitiesClient.get).mockResolvedValue({ capabilities: [], extensions: [], disabled_tools: [] });
  watch.mockImplementation(
    (_id, _after, onEvent) =>
      new Promise<WatchEnd>((resolve) => {
        emit = onEvent;
        endStream = resolve;
      }),
  );
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1", 2, true) }, sequence: 5 });
  client.append.mockResolvedValue(undefined as never);
  client.search.mockResolvedValue([]);
  client.suggestion.mockResolvedValue({ text: null });
});

describe("the suggested next prompt", () => {
  it("is fetched when an answer arrives", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });

    await answered();

    expect(client.suggestion).toHaveBeenCalledWith("c1");
    expect(chat.suggestion).toBe("Tell me more");
  });

  it("is not fetched for a stopped or a failed answer", async () => {
    const chat = await running();
    fire(finalEvent(true));
    endStream("done");
    await flushPromises();
    expect(client.suggestion).not.toHaveBeenCalled();

    await chat.send("again");
    client.suggestion.mockClear();
    fire({ type: "error", message: "boom" });
    endStream("done");
    await flushPromises();

    expect(client.suggestion).not.toHaveBeenCalled();
    expect(chat.suggestion).toBeNull();
  });

  it("is never fetched while the account has suggestions switched off", async () => {
    const chat = await storeWith({ c1: TWO }, [], { ...ACCOUNT, prompt_suggestions: false } as typeof ACCOUNT);
    await chat.selectChat("c1");
    await chat.send("ask something");

    await answered();

    expect(client.suggestion).not.toHaveBeenCalled();
    expect(chat.suggestion).toBeNull();
  });

  it("disappears when suggestions are switched off", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });
    await answered();
    expect(chat.suggestion).toBe("Tell me more");

    useAuthStore().account = { ...ACCOUNT, prompt_suggestions: false } as typeof ACCOUNT;
    await flushPromises();

    expect(chat.suggestion).toBeNull();
  });

  it("goes when the next question is sent", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });
    await answered();

    await chat.send("something else");

    expect(chat.suggestion).toBeNull();
  });

  it("goes when a new chat is started", async () => {
    const chat = await running();
    client.suggestion.mockResolvedValue({ text: "Tell me more" });
    await answered();

    chat.newChat();

    expect(chat.suggestion).toBeNull();
  });

  it("is dropped when it arrives after another chat was opened", async () => {
    const chat = await running({ c1: TWO, c2: TWO });
    const replies: Array<(value: { text: string | null }) => void> = [];
    client.suggestion.mockImplementation(() => new Promise((resolve) => replies.push(resolve)));
    await answered(); // asks for c1's suggestion; it is still on its way
    await chat.selectChat("c2"); // asks for c2's

    replies[0]!({ text: "meant for c1" });
    await flushPromises();
    expect(chat.suggestion).toBeNull();

    replies[1]!({ text: "meant for c2" });
    await flushPromises();
    expect(chat.suggestion).toBe("meant for c2");
  });

  it("is fetched when a finished chat is opened", async () => {
    const chat = await storeWith({ c1: TWO });
    client.suggestion.mockResolvedValue({ text: "What next?" });

    await chat.selectChat("c1");
    await flushPromises();

    expect(client.suggestion).toHaveBeenCalledWith("c1");
    expect(chat.suggestion).toBe("What next?");
  });

  it("is not fetched when the chat opened is still answering", async () => {
    const chat = await storeWith({ c1: TWO }, ["c1"]);

    await chat.selectChat("c1");
    await flushPromises();

    expect(client.suggestion).not.toHaveBeenCalled();
    expect(chat.suggestion).toBeNull();
  });

  it("a failed fetch leaves no suggestion and no error", async () => {
    const chat = await running();
    client.suggestion.mockRejectedValue(new Error("502"));

    await answered();

    expect(chat.suggestion).toBeNull();
    expect(chat.loadError).toBe("");
    expect(chat.sendError).toBe("");
  });
});
