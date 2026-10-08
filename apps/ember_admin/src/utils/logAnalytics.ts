import type { AnalyticsRange, AnalyticsReport, LogKind } from "../api/LogsClient";

/** How wide one bucket of a time chart is. */
export type BucketSize = AnalyticsReport["bucket"];

export const KIND_LABELS: Record<LogKind, string> = { action: "Activity", error: "Errors", chat_trace: "Chat turns" };

/** Each kind keeps its colour on every chart (never by rank), see style.css. */
export const KIND_COLORS: Record<LogKind, string> = {
  action: "var(--kind-action)",
  error: "var(--kind-error)",
  chat_trace: "var(--kind-chat)",
};

/** The range picker's choices; the long form names the period in a tile's "vs previous ...". */
export const RANGE_OPTIONS: { value: AnalyticsRange; label: string; long: string }[] = [
  { value: "24h", label: "24h", long: "24 hours" },
  { value: "7d", label: "7d", long: "7 days" },
  { value: "30d", label: "30d", long: "30 days" },
  { value: "90d", label: "90d", long: "90 days" },
];

export const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
export const HEAT_LEVELS = 4;

/** 1,284 / 12.9K / 1.2M. */
export function formatCount(n: number): string {
  if (n < 10_000) return n.toLocaleString("en-US");
  const compact = (value: number, unit: string) => `${value.toFixed(1).replace(/\.0$/, "")}${unit}`;
  return n < 1_000_000 ? compact(n / 1000, "K") : compact(n / 1_000_000, "M");
}

export interface Change {
  text: string;
  /** "new": there was nothing in the previous period to compare with. */
  direction: "up" | "down" | "flat" | "new";
}

/** The change from the previous period to this one, as the tile's delta. */
export function describeChange(current: number, previous: number): Change {
  if (previous === 0) return current === 0 ? { text: "no change", direction: "flat" } : { text: "new", direction: "new" };
  const percent = Math.round(((current - previous) / previous) * 100);
  if (percent === 0) return { text: "no change", direction: "flat" };
  return percent > 0
    ? { text: `+${percent.toLocaleString("en-US")}%`, direction: "up" }
    : { text: `−${Math.abs(percent).toLocaleString("en-US")}%`, direction: "down" };
}

/** The change in a share (0 to 1) between two periods, in percentage points: "+1.2 pts". */
export function describeRateChange(current: number | null, previous: number | null): Change {
  if (current === null) return { text: "no requests", direction: "flat" };
  if (previous === null) return { text: "new", direction: "new" };
  const points = Math.round((current - previous) * 1000) / 10;
  if (points === 0) return { text: "no change", direction: "flat" };
  const text = `${Math.abs(points).toLocaleString("en-US", { maximumFractionDigits: 1 })} pts`;
  return points > 0 ? { text: `+${text}`, direction: "up" } : { text: `−${text}`, direction: "down" };
}

const NICE_STEPS = [1, 2, 4, 6, 8, 10];

/** The axis top for a count: a clean number whose half is whole too (2, 4, 10, 60, 200 ...). */
export function niceCeil(max: number): number {
  if (max <= 2) return 2;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  return NICE_STEPS.map((step) => step * magnitude).find((value) => value >= max)!;
}

const utcDate = (bucket: string) => new Date(`${bucket}Z`);
const SHORT_DATE: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", timeZone: "UTC" };

/** A bucket's tick on the time axis (UTC, like the buckets themselves). */
export function axisLabel(bucket: string, size: BucketSize): string {
  return size === "hour" ? bucket.slice(11, 16) : utcDate(bucket).toLocaleDateString("en-US", SHORT_DATE);
}

/** A bucket named in full, for the tooltip and the table. */
export function bucketTitle(bucket: string, size: BucketSize): string {
  const day = utcDate(bucket).toLocaleDateString("en-US", { ...SHORT_DATE, weekday: "short" });
  return size === "hour" ? `${day}, ${bucket.slice(11, 16)} UTC` : day;
}

export interface HourCell {
  weekday: number;
  hour: number;
  count: number;
  /** 0 (none) to HEAT_LEVELS (the busiest hour). */
  level: number;
}

/** The sparse heatmap cells as a full 7 (Sunday first) x 24 grid. */
export function buildHourHeatmap(cells: AnalyticsReport["heatmap"]): HourCell[][] {
  const counts = new Map(cells.map((c) => [c.weekday * 24 + c.hour, c.count]));
  const peak = Math.max(0, ...cells.map((c) => c.count));
  return WEEKDAYS.map((_, weekday) =>
    Array.from({ length: 24 }, (_, hour) => {
      const count = counts.get(weekday * 24 + hour) ?? 0;
      return { weekday, hour, count, level: count > 0 ? Math.ceil((count * HEAT_LEVELS) / peak) : 0 };
    }),
  );
}

/** Who an entry concerns: null is the server itself, a missing name a deleted account. */
export function accountLabel(account: { account_id: number | null; username: string | null }): string {
  if (account.account_id === null) return "Server";
  return account.username ?? `Deleted account #${account.account_id}`;
}
