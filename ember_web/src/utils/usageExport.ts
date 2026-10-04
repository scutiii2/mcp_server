import type { UsageReport } from "../api/UsageClient";
import { favoriteAgent, hourLabel, peakHour } from "./usageStats";

export interface UsageExportOptions {
  username: string;
  /** "30 days", "This month" ... */
  rangeLabel: string;
  generatedAt: Date;
  /** Offset of the viewer's time zone east of UTC, for the busiest hour. */
  utcOffsetMinutes?: number;
}

/** A table cell must not contain the column separator. */
function cell(text: string): string {
  return text.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function local(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The report as a Markdown document, like chat_app's usage export: a summary
 * table, then tokens by agent and by day. Built in the browser. */
export function usageToMarkdown(report: UsageReport, options: UsageExportOptions): string {
  const n = (value: number) => value.toLocaleString("en-US");
  const peak = peakHour(report.hourly, options.utcOffsetMinutes);
  const favorite = favoriteAgent(report.by_agent);

  const lines = [
    `# Token usage - ${options.username}`,
    "",
    `Range: ${options.rangeLabel} (since ${report.since.slice(0, 10)}). Generated ${local(options.generatedAt)}.`,
    "",
    "## Summary",
    "",
    "| Metric | Value |",
    "|---|---|",
    `| Total tokens | ${n(report.total_tokens)} |`,
    `| Input tokens | ${n(report.input_tokens)} |`,
    `| Output tokens | ${n(report.output_tokens)} |`,
    `| Tokens on summaries | ${n(report.summary_tokens)} |`,
    `| Chats | ${n(report.chats)} |`,
    `| Answers | ${n(report.turns)} |`,
    `| Peak hour | ${peak === null ? "-" : hourLabel(peak)} |`,
    `| Favorite agent | ${favorite === null ? "-" : cell(favorite)} |`,
    "",
    "## By agent",
    "",
  ];
  if (report.by_agent.length === 0) {
    lines.push("None.");
  } else {
    lines.push("| Agent | Model | Tokens |", "|---|---|---|");
    for (const row of report.by_agent) lines.push(`| ${cell(row.agent)} | ${cell(row.model || "-")} | ${n(row.tokens)} |`);
  }
  lines.push("", "## Per day (UTC)", "");
  if (report.daily.length === 0) {
    lines.push("None.");
  } else {
    lines.push("| Date | Tokens |", "|---|---|");
    for (const day of report.daily) lines.push(`| ${day.date} | ${n(day.tokens)} |`);
  }
  lines.push("");
  return lines.join("\n");
}
