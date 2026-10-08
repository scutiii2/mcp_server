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
    answerQuestion: vi.fn(),
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

async function storeWith(chats: Record<string, ChatMessage[]>, running: string[] = []) {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT;
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
  return chat;
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

const NOTICES = [{ id: "mynotes", label: "My notes", error: "Timed out" }];
const notice = () => fire({ type: "notice", notices: NOTICES });

describe("notices about private extensions", () => {
  it("are kept when the turn reports them", async () => {
    const chat = await running();

    notice();

    expect(chat.notices).toEqual(NOTICES);
  });

  it("stay after the answer finishes", async () => {
    const chat = await running();

    notice();
    fire({ type: "final", message: { role: "assistant", content: "done" }, cancelled: false });
    endStream("done");
    await flushPromises();

    expect(chat.notices).toEqual(NOTICES);
  });

  it("are cleared by dismissNotices", async () => {
    const chat = await running();
    notice();

    chat.dismissNotices();

    expect(chat.notices).toEqual([]);
  });

  it("are cleared when the next question is sent", async () => {
    const chat = await running();
    notice();
    fire({ type: "final", message: { role: "assistant", content: "done" }, cancelled: false });
    endStream("done");
    await flushPromises();

    await chat.send("and again");

    expect(chat.notices).toEqual([]);
  });

  it("are cleared by a new chat and by opening another chat", async () => {
    const chat = await running({ c1: TWO, c2: TWO });
    notice();
    chat.newChat();
    expect(chat.notices).toEqual([]);

    await chat.selectChat("c1");
    notice();
    await chat.selectChat("c2");
    expect(chat.notices).toEqual([]);
  });

  it("are cleared when the account changes", async () => {
    const chat = await running();
    notice();

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();

    expect(chat.notices).toEqual([]);
  });
});
