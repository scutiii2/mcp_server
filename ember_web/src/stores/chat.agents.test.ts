import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage, TurnEvent } from "../api/types";
import { watchTurn, type WatchEnd } from "../services/turnStream";
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
    importChats: vi.fn(),
    append: vi.fn(),
    branch: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({
  chimeIfAway: vi.fn(),
  notifyIfAway: vi.fn(),
  notificationsSupported: vi.fn(() => false),
  requestNotifyPermission: vi.fn(),
}));

const client = vi.mocked(chatsClient);
const watch = vi.mocked(watchTurn);

const summary = (id: string, count = 0, running = false): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "main",
  message_count: count,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running,
});
const TWO: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
];

let emitRaw: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};
const fire = (event: Record<string, unknown>) => emitRaw({ sequence: 1, ...event } as TurnEvent);

/** The store with chat c1 open and an answer being written; `emit` reaches its event handler. */
async function runningTurn() {
  setActivePinia(createPinia());
  useAuthStore().account = {
    id: 1,
    username: "root",
    email: "root@example.com",
    email_verified: true,
    roles: [],
    permissions: ["chat.use"],
  };
  client.list.mockResolvedValue([summary("c1", 2)]);
  client.get.mockImplementation(async (id: string) => ({ ...summary(id, 2), messages: structuredClone(TWO) }));
  const chat = useChatStore();
  await flushPromises();
  await chat.selectChat("c1");
  await chat.send("ask something");
  return { chat, emit: fire };
}

beforeEach(() => {
  vi.clearAllMocks();
  watch.mockImplementation(
    (_id, _after, onEvent) =>
      new Promise<WatchEnd>(() => {
        emitRaw = onEvent;
      }),
  );
  client.startTurn.mockResolvedValue({ chat: summary("c1", 2, true), sequence: 5 });
  client.search.mockResolvedValue([]);
});

describe("live agent activity", () => {
  it("tracks who is working from agent_start / agent_end", async () => {
    const { chat, emit } = await runningTurn();

    emit({ type: "agent_start", sequence: 1, agent_id: "calc", agent_label: "Calculator", delegated_by: "main", question: "2+2", step_id: "d1", at: "2026-10-04T09:12:03.512Z" });
    expect(chat.activeAgents).toEqual([{ agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:03.512Z", step_id: "d1" }]);

    emit({ type: "agent_end", sequence: 2, agent_id: "calc", agent_label: "Calculator", ok: true, step_id: "d1", at: "2026-10-04T09:12:07.044Z" });
    expect(chat.activeAgents).toEqual([]);
  });

  it("collects a specialist's text under its delegate step, and a reset clears it", async () => {
    const { chat, emit } = await runningTurn();

    emit({ type: "agent_token", sequence: 1, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "15% of " });
    emit({ type: "agent_token", sequence: 2, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "2,340" });
    expect(chat.agentText).toEqual({ "calc\td1": "15% of 2,340" });
    expect(chat.streaming).toBe(""); // never mixed into the answer

    emit({ type: "agent_token", sequence: 3, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "", reset: true });
    expect(chat.agentText).toEqual({ "calc\td1": "" });
  });

  it("restores the working agents from a snapshot", async () => {
    const { chat, emit } = await runningTurn();

    emit({
      type: "snapshot",
      sequence: 5,
      text: "so far",
      activity: "",
      steps: [],
      approvals: [],
      active_agents: [{ agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:03.512Z", step_id: "d1" }],
    });

    expect(chat.activeAgents.map((a) => a.agent_id)).toEqual(["calc"]);
  });

  it("clears everything when the answer ends, even if agent_end never came", async () => {
    const { chat, emit } = await runningTurn();
    emit({ type: "agent_start", sequence: 1, agent_id: "calc", agent_label: "Calculator", delegated_by: "main", question: "q", step_id: "d1", at: "2026-10-04T09:12:03.512Z" });
    emit({ type: "agent_token", sequence: 2, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "x" });

    emit({ type: "final", sequence: 3, message: { role: "assistant", content: "done" }, cancelled: false });

    expect(chat.activeAgents).toEqual([]);
    expect(chat.agentText).toEqual({});
  });
});

describe("a snapshot's steps", () => {
  const delegating = {
    type: "snapshot",
    sequence: 5,
    text: "so far",
    activity: "",
    approvals: [],
    steps: [
      { id: "d1", agent_id: "main", agent_label: "Ember", tool: "delegate_to_agent", label: "Delegate", arguments: {}, ok: null, result: "" },
      { id: "s1", agent_id: "calc", agent_label: "Calculator", tool: "tool_calc", label: "Calc", arguments: {}, ok: null, result: "" },
    ],
    active_agents: [{ agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:03.512Z", step_id: "d1" }],
  };

  it("keeps their ids, so a delegate's text still lands under its step", async () => {
    const { chat, emit } = await runningTurn();
    emit(delegating);

    emit({ type: "agent_token", sequence: 6, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "15% of " });

    expect(chat.liveSteps.map((s) => s.id)).toEqual(["d1", "s1"]);
    expect(chat.agentText).toEqual({ "calc\td1": "15% of " });
  });

  it("are finished by a step_end that comes after the snapshot, for the right agent", async () => {
    const { chat, emit } = await runningTurn();
    emit(delegating);

    emit({ type: "step_end", sequence: 6, id: "s1", ok: true, result: "4", agent_id: "calc", agent_label: "Calculator" });
    expect(chat.liveSteps.map((s) => [s.ok, s.result])).toEqual([[null, ""], [true, "4"]]);

    emit({ type: "step_end", sequence: 7, id: "d1", ok: true, result: "Delegated", agent_id: "main", agent_label: "Ember" });
    expect(chat.liveSteps.map((s) => [s.ok, s.result])).toEqual([[true, "Delegated"], [true, "4"]]);
  });
});

describe("live steps and agent events, edge cases", () => {
  const start = { sequence: 1, agent_id: "calc", agent_label: "Calculator", delegated_by: "main", question: "q", step_id: "d1", at: "2026-10-04T09:12:03.512Z" };

  it("matches live steps by agent and id, so two agents may reuse a step id", async () => {
    const { chat, emit } = await runningTurn();
    emit({ type: "step_start", id: "s1", tool: "t_main", arguments: {}, agent_id: "main", agent_label: "Ember" });
    emit({ type: "step_start", id: "s1", tool: "t_calc", arguments: {}, agent_id: "calc", agent_label: "Calculator" });

    emit({ type: "step_end", id: "s1", ok: true, result: "from calc", agent_id: "calc", agent_label: "Calculator" });
    expect(chat.liveSteps.map((s) => [s.ok, s.result])).toEqual([[null, ""], [true, "from calc"]]);

    emit({ type: "step_end", id: "s1", ok: false, result: "from main", agent_id: "main", agent_label: "Ember" });
    expect(chat.liveSteps.map((s) => [s.ok, s.result])).toEqual([[false, "from main"], [true, "from calc"]]);
  });

  it("an error resets the working agents and their text", async () => {
    const { chat, emit } = await runningTurn();
    emit({ type: "agent_start", ...start });
    emit({ type: "agent_token", sequence: 2, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "x" });

    emit({ type: "error", sequence: 3, message: "boom" });

    expect(chat.activeAgents).toEqual([]);
    expect(chat.agentText).toEqual({});
  });

  it("ignores an agent_end for a step it never saw", async () => {
    const { chat, emit } = await runningTurn();
    emit({ type: "agent_start", ...start });

    emit({ type: "agent_end", sequence: 2, agent_id: "calc", agent_label: "Calculator", ok: true, step_id: "nope", at: "2026-10-04T09:12:07.044Z" });

    expect(chat.activeAgents.map((a) => a.step_id)).toEqual(["d1"]);
  });

  it("keeps text that arrives before its agent_start, and clears it when the answer ends", async () => {
    const { chat, emit } = await runningTurn();

    emit({ type: "agent_token", sequence: 1, agent_id: "calc", agent_label: "Calculator", step_id: "d1", text: "early" });
    expect(chat.agentText).toEqual({ "calc\td1": "early" });
    expect(chat.activeAgents).toEqual([]);

    emit({ type: "final", sequence: 2, message: { role: "assistant", content: "done" }, cancelled: false });
    expect(chat.agentText).toEqual({});
  });

  it("does not list an agent twice when agent_start is repeated", async () => {
    const { chat, emit } = await runningTurn();

    emit({ type: "agent_start", ...start });
    emit({ type: "agent_start", ...start });

    expect(chat.activeAgents).toHaveLength(1);
  });
});
