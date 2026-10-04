import { describe, expect, it } from "vitest";
import type { UsageReport } from "../api/UsageClient";
import { usageToMarkdown } from "./usageExport";

const hourly = (hour: number, tokens: number): number[] => {
  const list = new Array<number>(24).fill(0);
  list[hour] = tokens;
  return list;
};

const REPORT: UsageReport = {
  days: 30,
  since: "2026-09-15T08:00:00.123456",
  total_tokens: 1_234_567,
  input_tokens: 1_000_000,
  output_tokens: 234_567,
  summary_tokens: 4200,
  turns: 12,
  chats: 3,
  by_agent: [
    { agent: "claude", model: "opus", tokens: 1_000_000 },
    { agent: "openai", model: "", tokens: 234_567 },
  ],
  daily: [
    { date: "2026-09-20", tokens: 1000 },
    { date: "2026-10-01", tokens: 1_233_567 },
  ],
  hourly: hourly(14, 1_234_567),
  group_by: "agent",
  groups: [],
};

const OPTIONS = { username: "root", rangeLabel: "30 days", generatedAt: new Date(2026, 9, 1, 9, 5), utcOffsetMinutes: 0 };

const lines = (text: string) => text.split("\n");

describe("usageToMarkdown", () => {
  const text = usageToMarkdown(REPORT, OPTIONS);

  it("starts with the account, the range, where it begins and when it was made", () => {
    expect(lines(text).slice(0, 3)).toEqual([
      "# Token usage - root",
      "",
      "Range: 30 days (since 2026-09-15). Generated 2026-10-01 09:05.",
    ]);
  });

  it("has a summary table with every figure, thousands separated", () => {
    expect(text).toContain("| Total tokens | 1,234,567 |");
    expect(text).toContain("| Input tokens | 1,000,000 |");
    expect(text).toContain("| Output tokens | 234,567 |");
    expect(text).toContain("| Tokens on summaries | 4,200 |");
    expect(text).toContain("| Chats | 3 |");
    expect(text).toContain("| Answers | 12 |");
  });

  it("shows the busiest hour in the viewer's time and the favorite agent", () => {
    expect(text).toContain("| Peak hour | 2 PM |");
    expect(text).toContain("| Favorite agent | claude opus |");
    expect(usageToMarkdown(REPORT, { ...OPTIONS, utcOffsetMinutes: 120 })).toContain("| Peak hour | 4 PM |");
  });

  it("lists the agents, with a dash for a missing model", () => {
    expect(text).toContain("| Agent | Model | Tokens |");
    expect(text).toContain("| claude | opus | 1,000,000 |");
    expect(text).toContain("| openai | - | 234,567 |");
  });

  it("lists the days, marked as UTC", () => {
    expect(text).toContain("## Per day (UTC)");
    expect(text).toContain("| 2026-09-20 | 1,000 |");
    expect(text).toContain("| 2026-10-01 | 1,233,567 |");
  });

  it("has no extra table when grouped by agent", () => {
    expect(text).not.toContain("## By provider");
    expect(text.match(/## By /g)).toHaveLength(1);
  });

  it("adds a table for the chosen grouping", () => {
    const grouped = usageToMarkdown(
      {
        ...REPORT,
        group_by: "provider",
        groups: [{ key: "open|ai", tokens: 1_000_000, input_tokens: 900_000, output_tokens: 100_000, turns: 7 }],
      },
      OPTIONS,
    );

    expect(grouped).toContain("## By provider");
    expect(grouped).toContain("| Provider | Tokens | Turns |");
    expect(grouped).toContain("| open\\|ai | 1,000,000 | 7 |");
    expect(grouped).toContain("## By agent");
  });

  it("ends with a newline", () => {
    expect(text.endsWith("\n")).toBe(true);
  });

  it("says None, with no empty tables, when nothing was used", () => {
    const empty = usageToMarkdown(
      { ...REPORT, total_tokens: 0, by_agent: [], daily: [], hourly: new Array<number>(24).fill(0) },
      OPTIONS,
    );

    expect(empty).toContain("## By agent\n\nNone.");
    expect(empty).toContain("## Per day (UTC)\n\nNone.");
    expect(empty).not.toContain("| Agent | Model | Tokens |");
    expect(empty).toContain("| Peak hour | - |");
    expect(empty).toContain("| Favorite agent | - |");
  });

  it("does not let an agent name break the table", () => {
    const odd = usageToMarkdown({ ...REPORT, by_agent: [{ agent: "a|b", model: "m\nn", tokens: 5 }] }, OPTIONS);

    expect(odd).toContain("| a\\|b | m n | 5 |");
    expect(odd).toContain("| Favorite agent | a\\|b m n |");
  });

  it("pads a one-digit hour and minute in the time it was made", () => {
    const early = usageToMarkdown(REPORT, { ...OPTIONS, generatedAt: new Date(2026, 0, 2, 3, 4) });

    expect(early).toContain("Generated 2026-01-02 03:04.");
  });
});
