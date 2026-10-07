import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import { commandsClient } from "../api/CommandsClient";
import { settingsClient } from "../api/SettingsClient";
import { watchTurn } from "../services/turnStream";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

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
vi.mock("../api/CommandsClient", () => ({ commandsClient: { capabilities: vi.fn(), list: vi.fn() } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));

const client = vi.mocked(chatsClient);
const commands = vi.mocked(commandsClient);

const ACCOUNT = { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.use"] };
const KEY = "ember_web.disabledCapabilities.1";

const summary = (id: string): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: 0,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running: false,
});

const CAPS = [
  { name: "pdf", enabled: true, label: "PDF files", tools: ["tool_pdf_merge", "tool_pdf_split"], resources: [] },
  { name: "calc", enabled: true, label: "Calculator", tools: ["tool_calc"], resources: [] },
];

async function store() {
  setActivePinia(createPinia());
  vi.mocked(settingsClient.get).mockResolvedValue({ force_tool_approval: false });
  useAuthStore().account = ACCOUNT;
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(watchTurn).mockResolvedValue("aborted");
  client.list.mockResolvedValue([]);
  client.search.mockResolvedValue([]);
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1"), running: true }, sequence: 1 });
  commands.capabilities.mockResolvedValue(CAPS);
  commands.list.mockResolvedValue([]);
});

describe("switching a built-in capability off for yourself", () => {
  it("has everything on to begin with, and sends no disabled tools", async () => {
    const chat = await store();

    expect(chat.disabledCapabilities).toEqual([]);
    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("disabled_tools");
    expect(commands.capabilities).not.toHaveBeenCalled();
  });

  it("remembers the choice per account, and a switch back on forgets it", async () => {
    const chat = await store();

    chat.setCapabilityEnabled("pdf", false);
    chat.setCapabilityEnabled("calc", false);
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual(["calc", "pdf"]);

    chat.setCapabilityEnabled("calc", true);
    expect(chat.disabledCapabilities).toEqual(["pdf"]);
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual(["pdf"]);

    expect((await store()).disabledCapabilities).toEqual(["pdf"]); // read again on the next login
  });

  it("sends the tools of what is switched off with the question", async () => {
    const chat = await store();
    chat.setCapabilityEnabled("pdf", false);

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ disabled_tools: ["tool_pdf_merge", "tool_pdf_split"] });
  });

  it("reads the capability list once, not on every question", async () => {
    const chat = await store();
    chat.setCapabilityEnabled("pdf", false);

    await chat.send("one");
    await flushPromises();
    chat.newChat(); // the first chat is still answering; ask in another
    chat.setCapabilityEnabled("calc", false);
    await chat.send("two");

    expect(commands.capabilities).toHaveBeenCalledTimes(1);
    expect(client.startTurn.mock.calls[1]![1]).toMatchObject({
      disabled_tools: ["tool_calc", "tool_pdf_merge", "tool_pdf_split"],
    });
  });

  it("does not send the question when the tools cannot be worked out", async () => {
    const chat = await store();
    chat.setCapabilityEnabled("pdf", false);
    commands.capabilities.mockRejectedValue(new Error("mcp_server is down"));

    const taken = await chat.send("hi");

    expect(taken).toBe(false);
    expect(client.startTurn).not.toHaveBeenCalled();
    expect(chat.sendError).toContain("mcp_server is down");
    expect(chat.messages).toEqual([]);
  });

  it("ignores a switched-off capability that no longer exists", async () => {
    const chat = await store();
    chat.setCapabilityEnabled("gone", false);

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("disabled_tools");
  });
});
