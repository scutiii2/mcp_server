import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AgentActivity from "./AgentActivity.vue";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";

vi.mock("../api/ChatsClient", () => ({ chatsClient: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn(() => Promise.resolve("aborted")) }));

const T0 = Date.parse("2026-10-04T09:12:00Z");
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0 + 3000);
  setActivePinia(createPinia());
  useEntryAgentStore().entry = { id: "main", label: "Ember" };
});
afterEach(() => vi.useRealTimers());

describe("AgentActivity", () => {
  it("is hidden while only the main agent works", () => {
    expect(mount(AgentActivity).text()).toBe("");
  });

  it("shows the chain of working agents with a clock for the innermost", () => {
    useChatStore().activeAgents = [
      { agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:00.000Z", step_id: "d1" },
    ];

    const text = mount(AgentActivity).text();

    expect(text).toContain("Ember → Calculator");
    expect(text).toContain("3.0 s");
  });

  it("shows nested agents in order", () => {
    useChatStore().activeAgents = [
      { agent_id: "a", label: "Alpha", since: "2026-10-04T09:12:00.000Z", step_id: "1" },
      { agent_id: "b", label: "Beta", since: "2026-10-04T09:12:01.000Z", step_id: "2" },
    ];

    expect(mount(AgentActivity).text()).toContain("Ember → Alpha → Beta");
  });
});
