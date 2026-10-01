import type { ChatMessage } from "../api/types";
import type { UsageWindow } from "../api/UsageClient";

/** 950 -> "950", 12,400 -> "12.4k", 1,250,000 -> "1.3M": the short form for
 * the chip; the detail panel shows the full number. */
export function compactNumber(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${trim(n / 1000)}k`;
  return `${trim(n / 1_000_000)}M`;
}

function trim(value: number): string {
  // One decimal below 100, none above: "12.4k", "124k".
  return value < 100 ? value.toFixed(1).replace(/\.0$/, "") : String(Math.round(value));
}

/** 4.2 -> "4.2 s", 65 -> "1 min 5 s". */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1).replace(/\.0$/, "")} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

/** A running clock: 12.4 s under a minute, then 1 min 03 s. */
export function formatClock(ms: number): string {
  const seconds = Math.max(0, ms) / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${String(Math.floor(seconds - minutes * 60)).padStart(2, "0")} s`;
}

/** The chip's one line for an answer: model, tokens, time and tools. Empty
 * when the message carries none of them (old chats, errors). A slash
 * command's reply was no model's answer: it says so, with how long the call took. */
export function usageSummary(m: ChatMessage): string {
  if (m.kind === "command" && m.role === "assistant") {
    return ["Direct tool call", m.duration_s !== undefined ? formatDuration(m.duration_s) : ""].filter(Boolean).join(" · ");
  }
  return [
    m.model,
    m.total_tokens ? `${compactNumber(m.total_tokens)} tokens` : "",
    m.duration_s !== undefined ? formatDuration(m.duration_s) : "",
    m.steps?.length ? `${m.steps.length} ${m.steps.length === 1 ? "tool" : "tools"}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** How much of a limit window is used, 0 to 100; 0 when it has no limit. */
export function usagePercent(window: UsageWindow): number {
  return window.limit ? Math.min(100, Math.round((window.used / window.limit) * 100)) : 0;
}
