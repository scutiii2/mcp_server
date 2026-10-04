import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../api/types";
import { agentUsageText, compactNumber, formatClock, formatDuration, usagePercent, usageSummary } from "./usageFormat";

describe("compactNumber", () => {
  it.each([
    [0, "0"],
    [950, "950"],
    [1000, "1k"],
    [12_400, "12.4k"],
    [99_949, "99.9k"],
    [124_000, "124k"],
    [1_250_000, "1.3M"],
    [12_000_000, "12M"],
  ])("%d -> %s", (n, expected) => {
    expect(compactNumber(n)).toBe(expected);
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0 s"],
    [4.2, "4.2 s"],
    [4, "4 s"],
    [59.9, "59.9 s"],
    [60, "1 min"],
    [65, "1 min 5 s"],
    [125.4, "2 min 5 s"],
  ])("%d s -> %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});

describe("usageSummary", () => {
  const answer = (extra: Partial<ChatMessage>): ChatMessage => ({ role: "assistant", content: "x", ...extra });

  it("starts with the agent's name when it is known", () => {
    expect(usageSummary(answer({ agent: "claude-agent", model: "m", total_tokens: 100 }), "Claude Agent")).toBe(
      "Claude Agent · m · 100 tokens",
    );
  });

  it("falls back to the saved agent id when the agent has no name here", () => {
    expect(usageSummary(answer({ agent: "gone-agent", model: "m" }))).toBe("gone-agent · m");
  });

  it("shows no agent for an answer saved before the agent was kept", () => {
    expect(usageSummary(answer({ model: "m" }))).toBe("m");
  });

  it("shows the agent alone when nothing else was saved", () => {
    expect(usageSummary(answer({ agent: "claude-agent" }), "Claude Agent")).toBe("Claude Agent");
  });

  it("joins model, tokens, time and tools", () => {
    const summary = usageSummary(
      answer({
        model: "claude-test",
        total_tokens: 12_400,
        duration_s: 4.2,
        steps: [
          { tool: "a", label: "", arguments: {}, ok: true, result: "" },
          { tool: "b", label: "", arguments: {}, ok: false, result: "" },
          { tool: "c", label: "", arguments: {}, ok: null, result: "" },
        ],
      }),
    );

    expect(summary).toBe("claude-test · 12.4k tokens · 4.2 s · 3 tools");
  });

  it("says '1 tool' in the singular", () => {
    const summary = usageSummary(answer({ steps: [{ tool: "a", label: "", arguments: {}, ok: true, result: "" }] }));

    expect(summary).toBe("1 tool");
  });

  it("copes with answers saved before the split and the time existed", () => {
    expect(usageSummary(answer({ model: "m", total_tokens: 100 }))).toBe("m · 100 tokens");
  });

  it("shows a zero-second answer's time but hides zero tokens", () => {
    expect(usageSummary(answer({ duration_s: 0, total_tokens: 0 }))).toBe("0 s");
  });

  it("is empty when nothing was saved", () => {
    expect(usageSummary(answer({}))).toBe("");
    expect(usageSummary(answer({ steps: [] }))).toBe("");
  });
});

describe("usagePercent", () => {
  const window = (used: number, limit: number) => ({ used, limit, reset_at: null });

  it.each([
    [0, 100, 0],
    [50, 100, 50],
    [1, 3, 33],
    [2, 3, 67],
    [100, 100, 100],
    [250, 100, 100],
  ])("%d of %d -> %d%%", (used, limit, expected) => {
    expect(usagePercent(window(used, limit))).toBe(expected);
  });

  it("is 0 when there is no limit", () => {
    expect(usagePercent(window(5000, 0))).toBe(0);
  });
});

describe("formatClock", () => {
  it.each([
    [0, "0.0 s"],
    [-500, "0.0 s"],
    [2400, "2.4 s"],
    [12_345, "12.3 s"],
    [59_940, "59.9 s"],
    [60_000, "1 min 00 s"],
    [63_000, "1 min 03 s"],
    [125_900, "2 min 05 s"],
    [3_600_000, "60 min 00 s"],
  ])("%d ms -> %s", (ms, expected) => {
    expect(formatClock(ms)).toBe(expected);
  });
});

describe("usageSummary for a slash command's reply", () => {
  const reply = (extra: Partial<ChatMessage> = {}): ChatMessage => ({ role: "assistant", kind: "command", content: "ok", ...extra });

  it("says it was a direct tool call, with how long it took", () => {
    expect(usageSummary(reply({ duration_s: 0.8 }))).toBe("No AI used · direct tool call · 0.8 s");
  });

  it("says only that, for an older reply without a time", () => {
    expect(usageSummary(reply())).toBe("No AI used · direct tool call");
  });

  it("does not show model or tokens even when some were saved", () => {
    expect(usageSummary(reply({ model: "m", total_tokens: 5, duration_s: 1 }))).toBe("No AI used · direct tool call · 1 s");
  });

  it("does not name an agent on a command reply", () => {
    expect(usageSummary(reply({ agent: "claude-agent" }), "Claude")).toBe("No AI used · direct tool call");
  });

  it("is not used for the command the user typed", () => {
    expect(usageSummary({ role: "user", kind: "command", content: "/x" })).toBe("");
  });

  it("leaves a model's answer as it was", () => {
    expect(usageSummary({ role: "assistant", content: "a", model: "m", duration_s: 4.2 })).toBe("m · 4.2 s");
  });
});

describe("agentUsageText", () => {
  it("lists the model, the split and the total", () => {
    expect(agentUsageText({ agent: "claude", model: "opus", input_tokens: 1200, output_tokens: 300, total_tokens: 1500 })).toBe(
      `opus · ${(1200).toLocaleString()} in · 300 out · ${(1500).toLocaleString()} total`,
    );
  });

  it("leaves out what was not reported", () => {
    expect(agentUsageText({ agent: "openai", total_tokens: 50 })).toBe("50 total");
    expect(agentUsageText({ agent: "openai", model: "gpt", total_tokens: 50 })).toBe("gpt · 50 total");
  });

  it("keeps a reported 0 instead of treating it as missing", () => {
    expect(agentUsageText({ agent: "a", input_tokens: 0, output_tokens: 0, total_tokens: 0 })).toBe("0 in · 0 out · 0 total");
  });
});
