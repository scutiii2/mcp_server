import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { accountCapabilitiesClient, type AccountCapabilities } from "../api/AccountCapabilitiesClient";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import { commandsClient } from "../api/CommandsClient";
import { settingsClient } from "../api/SettingsClient";
import { watchTurn } from "../services/turnStream";
import { useAccountCapabilitiesStore } from "./accountCapabilities";
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
vi.mock("../api/CommandsClient", () => ({ commandsClient: { list: vi.fn() } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));

const client = vi.mocked(chatsClient);
const account = vi.mocked(accountCapabilitiesClient);
const commands = vi.mocked(commandsClient);

const ACCOUNT = { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.use"] };

const summary = (id: string): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: 0,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running: false,
});

const NOTHING: AccountCapabilities = {
  capabilities: [],
  extensions: [],
  disabled_tools: ["tool_calc", "tool_pdf_merge", "tool_pdf_split"],
};

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
  commands.list.mockResolvedValue([]);
  account.get.mockResolvedValue(NOTHING);
});

describe("what the account has added decides what a question may use", () => {
  it("sends the tools of everything not added, as ember_api worked them out", async () => {
    const chat = await store();

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({
      disabled_tools: ["tool_calc", "tool_pdf_merge", "tool_pdf_split"],
      enabled_extensions: [],
    });
  });

  it("sends no disabled tools when everything is added", async () => {
    account.get.mockResolvedValue({ capabilities: ["calc", "pdf"], extensions: [], disabled_tools: [] });
    const chat = await store();

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("disabled_tools");
  });

  it("sends the extensions the account added", async () => {
    account.get.mockResolvedValue({ capabilities: [], extensions: ["notes"], disabled_tools: [] });
    const chat = await store();

    await chat.send("hi");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ enabled_extensions: ["notes"] });
    expect(chat.enabledExtensions).toEqual(["notes"]);
  });

  it("uses the new answer after a change", async () => {
    const chat = await store();
    account.set.mockResolvedValue({ capabilities: ["pdf"], extensions: [], disabled_tools: ["tool_calc"] });

    await useAccountCapabilitiesStore().setCapability("pdf", true);
    await chat.send("hi");

    expect(chat.enabledCapabilities).toEqual(["pdf"]);
    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ disabled_tools: ["tool_calc"] });
  });

  it("waits for a change that is still being saved", async () => {
    const chat = await store();
    let finish!: (value: AccountCapabilities) => void;
    account.set.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    void useAccountCapabilitiesStore().setCapability("pdf", true);

    const sending = chat.send("hi");
    await flushPromises();
    expect(client.startTurn).not.toHaveBeenCalled();

    finish({ capabilities: ["pdf"], extensions: [], disabled_tools: ["tool_calc"] });
    await sending;
    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ disabled_tools: ["tool_calc"] });
  });

  it("does not send the question when the account's choices could not be read", async () => {
    account.get.mockRejectedValue(new Error("mcp_server is unreachable"));
    const chat = await store();

    const taken = await chat.send("hi");

    expect(taken).toBe(false);
    expect(client.startTurn).not.toHaveBeenCalled();
    expect(chat.sendError).toContain("mcp_server is unreachable");
    expect(chat.messages).toEqual([]);
  });
});
