import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../api/types";
import UsageChip from "./UsageChip.vue";

const step = (ok: boolean | null) => ({ tool: "t", label: "", arguments: {}, ok, result: "" });

const FULL: ChatMessage = {
  role: "assistant",
  content: "x",
  model: "claude-test",
  total_tokens: 12_400,
  input_tokens: 10_000,
  output_tokens: 2_400,
  duration_s: 4.2,
  context_tokens: 50_000,
  context_window: 200_000,
  steps: [step(true), step(false), step(null)],
};

function rows(wrapper: ReturnType<typeof mount>): Record<string, string> {
  const labels = wrapper.findAll("dt").map((d) => d.text());
  const values = wrapper.findAll("dd").map((d) => d.text());
  return Object.fromEntries(labels.map((label, i) => [label, values[i]!]));
}

describe("UsageChip", () => {
  it("shows the one-line summary", () => {
    const wrapper = mount(UsageChip, { props: { message: FULL } });

    expect(wrapper.find("button").text()).toBe("claude-test · 12.4k tokens · 4.2 s · 3 tools");
    expect(wrapper.find("dl").exists()).toBe(false);
  });

  it("starts the summary with the agent's name", () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, agent: "claude-agent" }, agentLabel: "Claude Agent" } });

    expect(wrapper.find("button").text()).toBe("Claude Agent · claude-test · 12.4k tokens · 4.2 s · 3 tools");
  });

  it("lists the agent first in the detail panel, by its name", async () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, agent: "claude-agent" }, agentLabel: "Claude Agent" } });

    await wrapper.find("button").trigger("click");

    expect(wrapper.findAll("dt")[0]!.text()).toBe("Agent");
    expect(rows(wrapper).Agent).toBe("Claude Agent");
  });

  it("shows the saved id when no name is given", async () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, agent: "old-agent" } } });

    await wrapper.find("button").trigger("click");

    expect(rows(wrapper).Agent).toBe("old-agent");
  });

  it("has no Agent row for an answer saved without one", async () => {
    const wrapper = mount(UsageChip, { props: { message: FULL } });

    await wrapper.find("button").trigger("click");

    expect(rows(wrapper).Agent).toBeUndefined();
  });

  it("opens a detail panel on click and closes it on a second click", async () => {
    const wrapper = mount(UsageChip, { props: { message: FULL } });
    const chip = wrapper.find("button");

    await chip.trigger("click");

    expect(chip.attributes("aria-expanded")).toBe("true");
    expect(rows(wrapper)).toEqual({
      Model: "claude-test",
      "Input tokens": (10_000).toLocaleString(),
      "Output tokens": (2_400).toLocaleString(),
      "Total tokens": (12_400).toLocaleString(),
      Time: "4.2 s",
      "Tools run": "3 (1 failed)",
      Context: `${(50_000).toLocaleString()} of ${(200_000).toLocaleString()} (25%)`,
    });

    await chip.trigger("click");
    expect(wrapper.find("dl").exists()).toBe(false);
    expect(chip.attributes("aria-expanded")).toBe("false");
  });

  it("closes on Esc", async () => {
    const wrapper = mount(UsageChip, { props: { message: FULL } });
    await wrapper.find("button").trigger("click");

    await wrapper.find("dl").trigger("keydown", { key: "Escape" });

    expect(wrapper.find("dl").exists()).toBe(false);
  });

  it("lists only what an older answer saved", async () => {
    const old: ChatMessage = { role: "assistant", content: "x", model: "m", total_tokens: 100 };
    const wrapper = mount(UsageChip, { props: { message: old } });

    await wrapper.find("button").trigger("click");

    expect(wrapper.find("button").text()).toBe("m · 100 tokens");
    expect(rows(wrapper)).toEqual({ Model: "m", "Total tokens": "100" });
  });

  it("caps the context percentage at 100", async () => {
    const wrapper = mount(UsageChip, {
      props: { message: { ...FULL, context_tokens: 250_000, steps: undefined } },
    });
    await wrapper.find("button").trigger("click");

    expect(rows(wrapper).Context).toContain("(100%)");
    expect(rows(wrapper)).not.toHaveProperty("Tools run");
  });

  it("renders nothing when the answer carries no usage", () => {
    const wrapper = mount(UsageChip, { props: { message: { role: "assistant", content: "x" } } });

    expect(wrapper.find(".usage").exists()).toBe(false);
    expect(wrapper.find("button").exists()).toBe(false);
  });
});

describe("UsageChip on a slash command's reply", () => {
  const reply = (extra: Partial<ChatMessage> = {}): ChatMessage => ({ role: "assistant", kind: "command", content: "ok", ...extra });

  it("says it was a direct tool call and how long it took", () => {
    const wrapper = mount(UsageChip, { props: { message: reply({ duration_s: 0.8 }) } });

    expect(wrapper.find("button").text()).toBe("No AI used · direct tool call · 0.8 s");
  });

  it("says only that for an older reply with no time", () => {
    const wrapper = mount(UsageChip, { props: { message: reply() } });

    expect(wrapper.find("button").text()).toBe("No AI used · direct tool call");
  });

  it("explains in the detail panel that no AI was used", async () => {
    const wrapper = mount(UsageChip, { props: { message: reply({ duration_s: 2 }) } });

    await wrapper.find("button").trigger("click");

    expect(rows(wrapper)).toEqual({ "Run as": "Direct tool call, no AI", Time: "2 s" });
  });

  it("shows no Run as row on a summary, which also carries a kind", async () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, kind: "summary" } } });

    await wrapper.find("button").trigger("click");

    expect(rows(wrapper)["Run as"]).toBeUndefined();
  });

  it("shows no Run as row on a model's answer", async () => {
    const wrapper = mount(UsageChip, { props: { message: FULL } });

    await wrapper.find("button").trigger("click");

    expect(rows(wrapper)["Run as"]).toBeUndefined();
  });
});

describe("UsageChip on an answer that ran several agents", () => {
  const AGENTS = [
    { agent: "claude", model: "opus", input_tokens: 70, output_tokens: 30, total_tokens: 100 },
    { agent: "openai", total_tokens: 50 },
  ];

  it("lists each agent in the detail panel", async () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, agent_usage: AGENTS } } });

    await wrapper.find("button").trigger("click");

    const shown = rows(wrapper);
    expect(shown["Agents"]).toBe("2 ran this answer");
    expect(shown["claude"]).toBe("opus · 70 in · 30 out · 100 total");
    expect(shown["openai"]).toBe("50 total");
  });

  it("keeps the one-line summary as it was", () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, agent_usage: AGENTS } } });

    expect(wrapper.find("button").text()).toBe("claude-test · 12.4k tokens · 4.2 s · 3 tools");
  });

  it("lists the agents after the answer's own figures", async () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, agent_usage: AGENTS } } });

    await wrapper.find("button").trigger("click");

    const labels = wrapper.findAll("dt").map((d) => d.text());
    expect(labels.indexOf("Context")).toBeLessThan(labels.indexOf("Agents"));
    expect(labels.slice(-3)).toEqual(["Agents", "claude", "openai"]);
  });

  it("shows no agent rows for an answer without a breakdown", async () => {
    const wrapper = mount(UsageChip, { props: { message: FULL } });

    await wrapper.find("button").trigger("click");

    expect(rows(wrapper)["Agents"]).toBeUndefined();
  });

  it("shows none for an empty breakdown", async () => {
    const wrapper = mount(UsageChip, { props: { message: { ...FULL, agent_usage: [] } } });

    await wrapper.find("button").trigger("click");

    expect(rows(wrapper)["Agents"]).toBeUndefined();
  });
});
