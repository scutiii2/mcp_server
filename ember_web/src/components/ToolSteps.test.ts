import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ToolStep } from "../api/types";
import ToolSteps from "./ToolSteps.vue";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";

vi.mock("../api/ChatsClient", () => ({ chatsClient: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn(() => Promise.resolve("aborted")) }));

beforeEach(() => {
  setActivePinia(createPinia());
  useEntryAgentStore().entry = { id: "main", label: "Ember" };
});

const own: ToolStep = { tool: "delegate_to_agent", label: "Delegate", arguments: {}, ok: true, result: "4", id: "d1", agent_id: "main", agent_label: "Ember" };
const nested: ToolStep = { tool: "tool_calc", label: "Calc", arguments: {}, ok: true, result: "4", id: "d1", agent_id: "calc", agent_label: "Calculator" };

describe("ToolSteps agents", () => {
  it("badges only the steps a delegated agent ran", () => {
    const wrapper = mount(ToolSteps, { props: { steps: [own, nested] } });

    const badges = wrapper.findAll(".agent-badge");
    expect(badges.map((b) => b.text())).toEqual(["Calculator"]);
  });

  it("shows no badge on older answers whose steps name no agent", () => {
    const old: ToolStep = { tool: "t", label: "T", arguments: {}, ok: true, result: "" };

    expect(mount(ToolSteps, { props: { steps: [old] } }).find(".agent-badge").exists()).toBe(false);
  });

  it("shows a delegated agent's live text inside its delegate step, labelled by the working agent", () => {
    const chat = useChatStore();
    chat.agentText = { d1: "15% of 2,340 is 351" };
    chat.activeAgents = [{ agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:03.512Z", step_id: "d1" }];
    const live: ToolStep = { ...own, ok: null, result: "" };

    const wrapper = mount(ToolSteps, { props: { steps: [live], live: true } });

    expect(wrapper.text()).toContain("Calculator is working");
    expect(wrapper.text()).toContain("15% of 2,340 is 351");
  });

  it("falls back to a generic label when the working agent is not known", () => {
    useChatStore().agentText = { d1: "text" };
    const live: ToolStep = { ...own, ok: null, result: "" };

    expect(mount(ToolSteps, { props: { steps: [live], live: true } }).text()).toContain("Delegated agent is working");
  });

  it("does not show live text on a saved answer", () => {
    useChatStore().agentText = { d1: "leftover" };

    expect(mount(ToolSteps, { props: { steps: [own] } }).text()).not.toContain("leftover");
  });
});
