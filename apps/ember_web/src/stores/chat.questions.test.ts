import { accountCapabilitiesClient } from "../api/AccountCapabilitiesClient";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import { ApiError } from "../api/http";
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
      new Promise<WatchEnd>(() => {
        emit = onEvent;
      }),
  );
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1", 2, true) }, sequence: 5 });
  client.append.mockResolvedValue(undefined as never);
  client.search.mockResolvedValue([]);
  client.suggestion.mockResolvedValue({ text: null });
});

const QUESTIONS = [
  { header: "Format", question: "Which format?", multi_select: false, options: [{ label: "CSV" }, { label: "JSON" }] },
];
const ANSWERS = [{ selected: ["CSV"], other: null }];

const ask = (id = "q1") => fire({ type: "question_request", id, questions: QUESTIONS });

describe("the agent's questions", () => {
  it("appear when the agent asks and say so in the activity line", async () => {
    const chat = await running();

    ask();

    expect(chat.pendingQuestions).toEqual([{ id: "q1", questions: QUESTIONS }]);
    expect(chat.activity).toContain("waiting for your answer");
  });

  it("are not added twice for the same step", async () => {
    const chat = await running();

    ask();
    ask();

    expect(chat.pendingQuestions).toHaveLength(1);
  });

  it("come back from a snapshot (a reload in the middle of a question)", async () => {
    const chat = await running();

    fire({ type: "snapshot", text: "", activity: "", questions: [{ id: "q1", questions: QUESTIONS }] });

    expect(chat.pendingQuestions).toEqual([{ id: "q1", questions: QUESTIONS }]);
  });

  it("go when the agent reports them resolved, and when their step ends", async () => {
    const chat = await running();
    ask("q1");
    ask("q2");

    fire({ type: "question_resolved", id: "q1", outcome: "answered" });
    expect(chat.pendingQuestions.map((q) => q.id)).toEqual(["q2"]);
    fire({ type: "step_end", id: "q2", ok: true, result: "x" });

    expect(chat.pendingQuestions).toEqual([]);
  });

  it("are sent with the answers and stay (buttons off) until the agent confirms", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockResolvedValue({ answered: true });

    await chat.answerQuestion("q1", ANSWERS);

    expect(client.answerQuestion).toHaveBeenCalledWith("c1", "q1", { answers: ANSWERS, skipped: false });
    expect(chat.answeringQuestions).toEqual(["q1"]);
    expect(chat.pendingQuestions).toHaveLength(1);
    fire({ type: "question_resolved", id: "q1", outcome: "answered" });
    expect(chat.pendingQuestions).toEqual([]);
    expect(chat.answeringQuestions).toEqual([]);
  });

  it("can be skipped", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockResolvedValue({ answered: true });

    await chat.skipQuestion("q1");

    expect(client.answerQuestion).toHaveBeenCalledWith("c1", "q1", { answers: [], skipped: true });
  });

  it("are not sent twice while the first answer is on its way", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockResolvedValue({ answered: true });

    await chat.answerQuestion("q1", ANSWERS);
    await chat.answerQuestion("q1", ANSWERS);

    expect(client.answerQuestion).toHaveBeenCalledOnce();
  });

  it("are dropped quietly when the server says nothing is waiting any more", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockRejectedValue(new ApiError(409, "Nothing is waiting for that answer"));

    await chat.answerQuestion("q1", ANSWERS);

    expect(chat.pendingQuestions).toEqual([]);
    expect(chat.answeringQuestions).toEqual([]);
    expect(chat.sendError).toBe("");
  });

  it("give their buttons back and show the error for any other failure", async () => {
    const chat = await running();
    ask();
    client.answerQuestion.mockRejectedValue(new ApiError(502, "agent down"));

    await chat.answerQuestion("q1", ANSWERS);

    expect(chat.pendingQuestions).toHaveLength(1);
    expect(chat.answeringQuestions).toEqual([]);
    expect(chat.sendError).toBe("agent down");
  });

  it("are cleared when another chat is opened", async () => {
    const chat = await running({ c1: TWO, c2: TWO });
    ask();

    await chat.selectChat("c2");

    expect(chat.pendingQuestions).toEqual([]);
  });

  it("let every turn say it can show questions", async () => {
    await running();

    expect(client.startTurn.mock.calls[0]![1]).toMatchObject({ can_ask: true });
  });
});
