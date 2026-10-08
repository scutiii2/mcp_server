import { accountCapabilitiesClient } from "../api/AccountCapabilitiesClient";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import { ApiError } from "../api/http";
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
    removeAll: vi.fn(),
    rename: vi.fn(),
    importChats: vi.fn(),
    append: vi.fn(),
    branch: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));

const client = vi.mocked(chatsClient);
const watch = vi.mocked(watchTurn);

const ACCOUNT = { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use"] };
const ASK_KEY = "ember_web.askBeforeTools.1";
const ALLOWED_KEY = "ember_web.allowedTools.1";

const summary = (id: string, count = 0): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: count,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running: false,
});

const FOUR: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
  { role: "user", content: "q2" },
  { role: "assistant", content: "a2" },
];

/** The event handler the store gave to the live stream of the running answer. */
let emit: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};
let sequence = 0;
const fire = (event: Record<string, unknown>) => emit({ sequence: (sequence += 1), ...event } as TurnEvent);

async function storeWith(chats: Record<string, ChatMessage[]>) {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT;
  client.list.mockResolvedValue(Object.entries(chats).map(([id, m]) => summary(id, m.length)));
  client.get.mockImplementation(async (id: string) => ({ ...summary(id, chats[id]!.length), messages: structuredClone(chats[id]!) }));
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

/** A chat with an answer being written, so events can be fired at it. */
async function running(chats: Record<string, ChatMessage[]> = { c1: FOUR }) {
  const chat = await storeWith(chats);
  await chat.selectChat(Object.keys(chats)[0]!);
  await chat.send("run the tool");
  return chat;
}

const REQUEST = { type: "approval_request", id: "step0", tool: "tool_srv_stopApp", label: "Stop App", arguments: { app: "web" } };

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(accountCapabilitiesClient.get).mockResolvedValue({ capabilities: [], extensions: [], disabled_tools: [] });
  sequence = 0;
  watch.mockImplementation(async (_id, _after, onEvent) => {
    emit = onEvent;
    return "aborted";
  });
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1"), running: true }, sequence: 5 });
  client.decide.mockResolvedValue({ decided: true });
  client.remove.mockResolvedValue(undefined);
  client.search.mockResolvedValue([]);
});

describe("the setting", () => {
  it("is off until switched on, and remembered per account", async () => {
    const chat = await storeWith({ c1: FOUR });
    expect(chat.askBeforeTools).toBe(false);

    chat.setAskBeforeTools(true);

    expect(localStorage.getItem(ASK_KEY)).toBe("1");
    chat.setAskBeforeTools(false);
    expect(localStorage.getItem(ASK_KEY)).toBe("0");
  });

  it("is read back for the account on login, and not shared with another account", async () => {
    localStorage.setItem(ASK_KEY, "1");
    const chat = await storeWith({ c1: FOUR });
    expect(chat.askBeforeTools).toBe(true);

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    expect(chat.askBeforeTools).toBe(false);

    useAuthStore().account = ACCOUNT;
    await flushPromises();
    expect(chat.askBeforeTools).toBe(true);
  });
});

describe("what a question sends", () => {
  it("asks nothing extra while the setting is off", async () => {
    const chat = await storeWith({ c1: FOUR });
    await chat.selectChat("c1");

    await chat.send("hello");

    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("ask_before_tools");
    expect(client.startTurn.mock.calls[0]![1]).not.toHaveProperty("allowed_tools");
  });

  it("turns asking on and lists the tools already allowed for this chat", async () => {
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: ["tool_a", "tool_b"], other: ["tool_z"] }));
    const chat = await storeWith({ c1: FOUR });
    chat.setAskBeforeTools(true);
    await chat.selectChat("c1");

    await chat.send("hello");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ ask_before_tools: true, allowed_tools: ["tool_a", "tool_b"] });
  });

  it("sends an empty allow list for a chat with none", async () => {
    const chat = await storeWith({ c1: FOUR });
    chat.setAskBeforeTools(true);
    await chat.selectChat("c1");

    await chat.send("hello");

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ ask_before_tools: true, allowed_tools: [] });
  });

  it("regenerate and edit ask too", async () => {
    const chat = await storeWith({ c1: FOUR });
    chat.setAskBeforeTools(true);
    await chat.selectChat("c1");

    await chat.regenerate();

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ ask_before_tools: true, truncate_to: 2 });
  });
});

describe("waiting tool runs", () => {
  it("a request from the agent becomes a card", async () => {
    const chat = await running();

    fire(REQUEST);

    expect(chat.pendingApprovals).toEqual([
      { id: "step0", tool: "tool_srv_stopApp", label: "Stop App", arguments: { app: "web" } },
    ]);
    expect(chat.activity).toBe("waiting for your approval ...");
  });

  it("the same request twice is one card, and odd fields are made safe", async () => {
    const chat = await running();

    fire({ type: "approval_request", id: "s", tool: "t", arguments: "not an object" });
    fire({ type: "approval_request", id: "s", tool: "t", arguments: {} });

    expect(chat.pendingApprovals).toEqual([{ id: "s", tool: "t", label: "", arguments: {} }]);
  });

  it("the agent's word that it is answered removes the card", async () => {
    const chat = await running();
    fire(REQUEST);
    fire({ ...REQUEST, id: "step1" });

    fire({ type: "approval_resolved", id: "step0", outcome: "allow" });

    expect(chat.pendingApprovals.map((a) => a.id)).toEqual(["step1"]);
    expect(chat.activity).toBe("");
  });

  it("so does the step ending, whatever the reason", async () => {
    const chat = await running();
    fire(REQUEST);

    fire({ type: "step_end", id: "step0", ok: false, result: "Stopped before it ran." });

    expect(chat.pendingApprovals).toEqual([]);
  });

  it("a snapshot replaces the cards with what is waiting now", async () => {
    const chat = await running();
    fire(REQUEST);

    fire({ type: "snapshot", text: "so far", activity: "", steps: [], approvals: [{ id: "s9", tool: "t9", label: "", arguments: {} }] });
    expect(chat.pendingApprovals.map((a) => a.id)).toEqual(["s9"]);

    fire({ type: "snapshot", text: "so far", activity: "", steps: [] }); // an older ember_api: none
    expect(chat.pendingApprovals).toEqual([]);
  });

  it("switching chats or starting a new one drops them", async () => {
    const chat = await running({ c1: FOUR, c2: FOUR });
    fire(REQUEST);

    chat.newChat();

    expect(chat.pendingApprovals).toEqual([]);
    expect(chat.deciding).toEqual([]);
  });
});

describe("answering", () => {
  it.each(["allow", "always", "deny"] as const)("%s is sent for the chat and step", async (decision) => {
    const chat = await running();
    fire(REQUEST);

    await chat.decideApproval("step0", decision);

    expect(client.decide).toHaveBeenCalledExactlyOnceWith("c1", "step0", decision);
  });

  it("keeps the card, buttons off, until the agent confirms", async () => {
    const chat = await running();
    fire(REQUEST);

    await chat.decideApproval("step0", "allow");
    expect(chat.pendingApprovals).toHaveLength(1);
    expect(chat.deciding).toEqual(["step0"]);

    fire({ type: "approval_resolved", id: "step0", outcome: "allow" });
    expect(chat.pendingApprovals).toEqual([]);
    expect(chat.deciding).toEqual([]);
  });

  it("does not answer twice while an answer is on its way", async () => {
    const chat = await running();
    fire(REQUEST);

    await chat.decideApproval("step0", "allow");
    await chat.decideApproval("step0", "deny");

    expect(client.decide).toHaveBeenCalledOnce();
  });

  it("ignores a step that is not waiting, and any answer without an open chat", async () => {
    const chat = await running();
    await chat.decideApproval("nope", "allow");
    expect(client.decide).not.toHaveBeenCalled();

    const idle = await storeWith({ c1: FOUR });
    await idle.decideApproval("step0", "allow");
    expect(client.decide).not.toHaveBeenCalled();
  });

  it("an answer that ember_api says is too late (409 or 404) just clears the card", async () => {
    for (const status of [409, 404]) {
      client.decide.mockRejectedValueOnce(new ApiError(status, "Nothing is waiting for that answer"));
      const chat = await running();
      fire(REQUEST);

      await chat.decideApproval("step0", "allow");

      expect(chat.pendingApprovals).toEqual([]);
      expect(chat.sendError).toBe("");
    }
  });

  it("any other failure shows the message, keeps the card and turns the buttons back on", async () => {
    client.decide.mockRejectedValue(new ApiError(502, "Could not reach the agent: refused"));
    const chat = await running();
    fire(REQUEST);

    await chat.decideApproval("step0", "allow");

    expect(chat.sendError).toBe("Could not reach the agent: refused");
    expect(chat.pendingApprovals).toHaveLength(1);
    expect(chat.deciding).toEqual([]);
    client.decide.mockResolvedValue({ decided: true });
    await chat.decideApproval("step0", "allow"); // can try again
    expect(client.decide).toHaveBeenCalledTimes(2);
  });

  it("an answer that arrives after the account changed is ignored", async () => {
    let finish!: (value: { decided: boolean }) => void;
    client.decide.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const chat = await running();
    fire(REQUEST);
    const pending = chat.decideApproval("step0", "always");

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish({ decided: true });
    await pending;

    expect(chat.sendError).toBe("");
  });
});

describe("allowing a tool for the chat", () => {
  it("'always' becomes a rule for this chat, kept in storage, and is sent with the next question", async () => {
    const chat = await running();
    chat.setAskBeforeTools(true);
    fire(REQUEST);

    await chat.decideApproval("step0", "always");

    expect(chat.allowedTools).toEqual({ c1: ["tool_srv_stopApp"] });
    expect(JSON.parse(localStorage.getItem(ALLOWED_KEY)!)).toEqual({ c1: ["tool_srv_stopApp"] });
    fire({ type: "approval_resolved", id: "step0", outcome: "always" });
    client.startTurn.mockClear();
    // The next question is sent once the running one has ended.
    const conversation = chat.active!;
    conversation.running = false;
    await chat.send("again");
    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ allowed_tools: ["tool_srv_stopApp"] });
  });

  it("'allow' and 'deny' leave no rule", async () => {
    const chat = await running();
    fire(REQUEST);
    fire({ ...REQUEST, id: "step1", tool: "tool_other" });

    await chat.decideApproval("step0", "allow");
    await chat.decideApproval("step1", "deny");

    expect(chat.allowedTools).toEqual({});
    expect(localStorage.getItem(ALLOWED_KEY)).toBeNull();
  });

  it("'always' is not remembered when ember_api did not accept the answer", async () => {
    client.decide.mockRejectedValue(new ApiError(500, "boom"));
    const chat = await running();
    fire(REQUEST);

    await chat.decideApproval("step0", "always");

    expect(chat.allowedTools).toEqual({});
  });

  it("the same tool is listed once", async () => {
    const chat = await running();
    fire(REQUEST);
    fire({ ...REQUEST, id: "step1" });

    await chat.decideApproval("step0", "always");
    await chat.decideApproval("step1", "always");

    expect(chat.allowedTools).toEqual({ c1: ["tool_srv_stopApp"] });
  });

  it("clearAllowedTools asks about everything again in the open chat only", async () => {
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: ["a"], c2: ["b"] }));
    const chat = await storeWith({ c1: FOUR, c2: FOUR });
    await chat.selectChat("c1");

    chat.clearAllowedTools();

    expect(chat.allowedTools).toEqual({ c2: ["b"] });
    expect(JSON.parse(localStorage.getItem(ALLOWED_KEY)!)).toEqual({ c2: ["b"] });
  });

  it("deleting a chat forgets its rules; deleting all forgets every one", async () => {
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: ["a"], c2: ["b"] }));
    const chat = await storeWith({ c1: FOUR, c2: FOUR });

    chat.deleteChat("c1");
    expect(chat.allowedTools).toEqual({ c2: ["b"] });

    chat.deleteAllChats();
    expect(chat.allowedTools).toEqual({});
    expect(JSON.parse(localStorage.getItem(ALLOWED_KEY)!)).toEqual({});
  });

  it("rules belong to the account, not to the browser", async () => {
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: ["a"] }));
    const chat = await storeWith({ c1: FOUR });
    expect(chat.allowedTools).toEqual({ c1: ["a"] });

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();

    expect(chat.allowedTools).toEqual({});
  });

  it("a branch starts with no rules of its own", async () => {
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: ["a"] }));
    client.branch.mockResolvedValue({
      ...summary("b1", 2),
      created_at: "2026-01-02T00:00:00",
      updated_at: "2026-01-02T00:00:00",
      messages: FOUR.slice(0, 2),
    });
    const chat = await storeWith({ c1: FOUR });
    chat.setAskBeforeTools(true);
    await chat.selectChat("c1");

    await chat.branchFrom(1);
    await chat.send("new question");

    expect(client.startTurn.mock.calls.at(-1)![1]).toMatchObject({ ask_before_tools: true, allowed_tools: [] });
  });
});

describe("stored rules that cannot be trusted", () => {
  it.each([
    ["not json", "{oops"],
    ["not an object", JSON.stringify(["a"])],
    ["a string", JSON.stringify("x")],
    ["null", "null"],
  ])("%s gives no rules", async (_name, raw) => {
    localStorage.setItem(ALLOWED_KEY, raw);

    const chat = await storeWith({ c1: FOUR });

    expect(chat.allowedTools).toEqual({});
  });

  it("keeps the good entries and drops the rest", async () => {
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: ["ok", 5, null, "also ok"], c2: "nope", c3: [], c4: [1, 2] }));

    const chat = await storeWith({ c1: FOUR });

    expect(chat.allowedTools).toEqual({ c1: ["ok", "also ok"] });
  });

  it("never holds more tools per chat than ember_api accepts", async () => {
    const many = Array.from({ length: 300 }, (_, i) => `tool_${i}`);
    localStorage.setItem(ALLOWED_KEY, JSON.stringify({ c1: many }));

    const chat = await storeWith({ c1: FOUR });

    expect(chat.allowedTools.c1).toHaveLength(200);
  });
});
