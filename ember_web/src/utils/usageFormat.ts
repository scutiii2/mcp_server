import type { ChatMessage } from "../api/types";

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

/** The chip's one line for an answer: model, tokens, time and tools. Empty
 * when the message carries none of them (old chats, errors). */
export function usageSummary(m: ChatMessage): string {
  return [
    m.model,
    m.total_tokens ? `${compactNumber(m.total_tokens)} tokens` : "",
    m.duration_s !== undefined ? formatDuration(m.duration_s) : "",
    m.steps?.length ? `${m.steps.length} ${m.steps.length === 1 ? "tool" : "tools"}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}
