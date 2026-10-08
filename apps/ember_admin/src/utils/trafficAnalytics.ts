import type { ChartPart } from "../components/analytics/useBucketCursor";

/** Status classes in stacking order, bottom to top. */
export const STATUS_CLASSES = ["2xx", "3xx", "4xx", "5xx"] as const;
export type StatusClass = (typeof STATUS_CLASSES)[number];

export const STATUS_PARTS: ChartPart[] = [
  { id: "2xx", label: "2xx success", color: "var(--http-2xx)" },
  { id: "3xx", label: "3xx redirect", color: "var(--http-3xx)" },
  { id: "4xx", label: "4xx client error", color: "var(--http-4xx)" },
  { id: "5xx", label: "5xx server error", color: "var(--http-5xx)" },
];

export const LATENCY_PARTS: ChartPart[] = [
  { id: "p50", label: "Median (p50)", color: "var(--latency-p50)" },
  { id: "p95", label: "Slowest 5% (p95)", color: "var(--latency-p95)" },
];

/** 80 ms / 1.2 s / 5 s. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1).replace(/\.0$/, "")} s`;
}

/** A latency from the API. The server only knows latency in bands, so a value
 * at the cap means "at least this slow" and is written with a plus. */
export function latencyLabel(ms: number | null, capMs: number): string {
  if (ms === null) return "–";
  return ms >= capMs ? `${formatDuration(capMs)}+` : formatDuration(ms);
}

/** A share from 0 to 1 as a percentage: 0.4% / 2.4% / 12%; a dash when there was nothing to measure. */
export function formatPercent(share: number | null): string {
  if (share === null) return "–";
  const percent = share * 100;
  if (percent === 0) return "0%";
  if (percent < 0.1) return "<0.1%";
  return `${percent < 10 ? percent.toFixed(1).replace(/\.0$/, "") : Math.round(percent)}%`;
}
