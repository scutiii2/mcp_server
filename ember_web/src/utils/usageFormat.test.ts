import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../api/types";
import { compactNumber, formatDuration, usageSummary } from "./usageFormat";

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
