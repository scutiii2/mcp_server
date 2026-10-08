import { accountCapabilitiesClient } from "../api/AccountCapabilitiesClient";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import { settingsClient } from "../api/SettingsClient";
import type { ChatMessage, TurnEvent } from "../api/types";
import { watchTurn } from "../services/turnStream";
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
    decide: vi.fn(),
    search: vi.fn(),
    remove: vi.fn(),
  },
}));
vi.mock("../api/SettingsClient", () => ({ settingsClient: { get: vi.fn(), set: vi.fn() } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));

const client = vi.mocked(chatsClient);
const settings = vi.mocked(settingsClient);
const watch = vi.mocked(watchTurn);

const ACCOUNT = { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"] };
const ALLOWED_KEY = "ember_web.allowedTools.1";

const FOUR: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
];

const summary = (id: string, count = 0): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: count,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running: false,
});

let emit: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};

async function storeWith(forced: boolean | Error) {
  setActivePinia(createPinia());
  if (forced instanceof Error) settings.get.mockRejectedValue(forced);
  else settings.get.mockResolvedValue({ force_tool_approval: forced });
  useAuthStore().account = ACCOUNT;
  client.list.mockResolvedValue([summary("c1", FOUR.length)]);
  client.get.mockImplementation(async (id: string) => ({ ...summary(id, FOUR.length), messages: structuredClone(FOUR) }));
  const chat = useChatStore();
  await flushPromises();
  await chat.selectChat("c1");
  return chat;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(accountCapabilitiesClient.get).mockResolvedValue({ capabilities: [], extensions: [], disabled_tools: [] });
  watch.mockImplementation(async (_id, _after, onEvent) => {
    emit = onEvent;
    return "aborted";
  });
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1"), running: true }, sequence: 5 });
  client.decide.mockResolvedValue({ decided: true });
  client.remove.mockResolvedValue(undefined);
  client.search.mockResolvedValue([]);
});

describe("what the administrator requires", () => {
  it("is read when the account logs in", async () => {
    expect((await storeWith(true)).forceToolApproval).toBe(true);
    expect((await storeWith(false)).forceToolApproval).toBe(false);
  });

  it("stays off, without an error, when it cannot be read", async () => {
    const chat = await storeWith(new Error("down"));

    expect(chat.forceToolApproval).toBe(false);
    expect(chat.sendError).toBe("");
  });

  it("is forgotten when the account logs out", async () => {
    const chat = await storeWith(true);

    useAuthStore().account = null;
    await flushPromises();

    expect(chat.forceToolApproval).toBe(false);
  });

  it("is read again when a question is sent, so a change since login shows", async () => {
    const chat = await storeWith(false);
    settings.get.mockResolvedValue({ force_tool_approval: true });

    await chat.send("hello");
    await flushPromises();

    expect(chat.forceToolApproval).toBe(true);
  });
});

describe("a question while approval is required", () => {
  it("asks before tools although the checkbox is off", async () => {
    const chat = await storeWith(true);
    expect(chat.askBeforeTools).toBe(false);

    await chat.send("hello");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ ask_before_tools: true, allowed_tools: [] });
  });

  it("does not list tools allowed earlier", async () => {
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: ["tool_a"] }));
    const chat = await storeWith(true);
    chat.setAskBeforeTools(true);

    await chat.send("hello");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ ask_before_tools: true, allowed_tools: [] });
  });

  it("keeps the old behaviour when nothing is required", async () => {
    const chat = await storeWith(false);

    await chat.send("hello");

    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("ask_before_tools");
  });

  it("does not turn an Allow-for-this-chat answer into a stored rule", async () => {
    const chat = await storeWith(true);
    await chat.send("run it");
    emit({ sequence: 1, type: "approval_request", id: "step0", tool: "tool_a", label: "A", arguments: {} } as TurnEvent);

    await chat.decideApproval("step0", "always");

    expect(client.decide).toHaveBeenCalledWith("c1", "step0", "always");
    expect(chat.allowedTools).toEqual({});
    expect(localStorage.getItem(ALLOWED_KEY)).toBeNull();
  });

  it("still makes the rule when nothing is required", async () => {
    const chat = await storeWith(false);
    await chat.send("run it");
    emit({ sequence: 1, type: "approval_request", id: "step0", tool: "tool_a", label: "A", arguments: {} } as TurnEvent);

    await chat.decideApproval("step0", "always");

    expect(chat.allowedTools).toEqual({ c1: ["tool_a"] });
  });
});
