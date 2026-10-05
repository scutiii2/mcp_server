import type { WatcherInfo } from "../api/WatchersClient";

/** What the Watchers page shows of a run. "other": a phase this page does not know. */
export type WatcherStatus = "running" | "succeeded" | "failed" | "other";

export const STATUS_LABELS: Record<WatcherStatus, string> = {
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  other: "Other",
};
export const STATUS_COLORS: Record<WatcherStatus, string> = {
  running: "var(--status-running)",
  succeeded: "var(--status-ok)",
  failed: "var(--status-failed)",
  other: "var(--muted)",
};
/** A glyph per status, so colour is never the only cue. */
export const STATUS_ICONS: Record<WatcherStatus, string> = { running: "●", succeeded: "✓", failed: "✕", other: "?" };

export type WatcherRange = "24h" | "7d" | "all";
export const RANGE_OPTIONS: { value: WatcherRange; label: string; long: string }[] = [
  { value: "24h", label: "24h", long: "the last 24 hours" },
  { value: "7d", label: "7d", long: "the last 7 days" },
  { value: "all", label: "All", long: "all time" },
];

const HOUR_MS = 3_600_000;
const SPAN_MS: Record<Exclude<WatcherRange, "all">, number> = { "24h": 24 * HOUR_MS, "7d": 7 * 24 * HOUR_MS };
/** "All" never zooms tighter than this, so a lone fresh run is still a visible bar. */
const MIN_SPAN_MS = HOUR_MS;

export function watcherKey(w: WatcherInfo): string {
  return w.key ?? w.name ?? "";
}

/** "failed" also covers "timed_out". */
export function statusOf(w: WatcherInfo): WatcherStatus {
  switch (w.phase) {
    case "running":
      return "running";
    case "completed":
      return "succeeded";
    case "failed":
    case "timed_out":
      return "failed";
    default:
      return "other";
  }
}

export interface Interval {
  start: number;
  end: number;
}

function time(iso?: string): number {
  return iso ? Date.parse(iso) : NaN;
}

/** When the run began and ended (a running one ends now); null if it never said when it began. */
export function intervalOf(w: WatcherInfo, now: number): Interval | null {
  const start = time(w.started_at);
  if (Number.isNaN(start)) return null;
  if (statusOf(w) === "running") return { start, end: Math.max(start, now) };
  const polled = time(w.last_polled_at);
  return { start, end: Number.isNaN(polled) ? start : Math.max(start, polled) };
}

/** The stretch of time the timeline covers: the range back from now, or for "All" from the first run. */
export function windowOf(range: WatcherRange, watchers: WatcherInfo[], now: number): Interval {
  if (range !== "all") return { start: now - SPAN_MS[range], end: now };
  const starts = watchers.map((w) => intervalOf(w, now)?.start).filter((s): s is number => s !== undefined);
  const first = starts.length ? Math.min(...starts) : now;
  return { start: Math.min(first, now - MIN_SPAN_MS), end: now };
}

/** Whether a run touches the window. A run that never said when it began cannot be placed, so no range hides it. */
export function overlaps(w: WatcherInfo, window: Interval, now: number): boolean {
  const interval = intervalOf(w, now);
  return interval === null || (interval.end >= window.start && interval.start <= window.end);
}

/** A run's bar as fractions (0 to 1) of the window, clipped to it. */
export function barSpan(interval: Interval, window: Interval): { from: number; to: number } {
  const span = window.end - window.start;
  const clamp = (t: number) => Math.min(1, Math.max(0, (t - window.start) / span));
  return { from: clamp(interval.start), to: clamp(interval.end) };
}

export interface Counts {
  running: number;
  succeeded: number;
  failed: number;
  other: number;
}

export interface CapabilityGroup {
  capability: string;
  /** Failed first, then running, then the rest, each newest first. */
  watchers: WatcherInfo[];
  counts: Counts;
}

const STATUS_RANK: Record<WatcherStatus, number> = { failed: 0, running: 1, succeeded: 2, other: 3 };

function startedAt(w: WatcherInfo): number {
  const t = time(w.started_at);
  return Number.isNaN(t) ? 0 : t;
}

function emptyCounts(): Counts {
  return { running: 0, succeeded: 0, failed: 0, other: 0 };
}

export function countStatuses(watchers: WatcherInfo[]): Counts {
  const counts = emptyCounts();
  for (const w of watchers) counts[statusOf(w)] += 1;
  return counts;
}

/** Watchers by capability, ranked to put attention first: a capability with a failure, then one with a
 * running watcher, then the most recently active; ties by name. */
export function groupByCapability(watchers: WatcherInfo[]): CapabilityGroup[] {
  const byName = new Map<string, WatcherInfo[]>();
  for (const w of watchers) byName.set(w.capability, [...(byName.get(w.capability) ?? []), w]);
  const groups = [...byName].map(([capability, list]): CapabilityGroup => ({
    capability,
    watchers: [...list].sort(
      (a, b) => STATUS_RANK[statusOf(a)] - STATUS_RANK[statusOf(b)] || startedAt(b) - startedAt(a) || watcherKey(a).localeCompare(watcherKey(b)),
    ),
    counts: countStatuses(list),
  }));
  const rank = (g: CapabilityGroup) => (g.counts.failed ? 0 : g.counts.running ? 1 : 2);
  const latest = (g: CapabilityGroup) => Math.max(...g.watchers.map(startedAt));
  return groups.sort((a, b) => rank(a) - rank(b) || latest(b) - latest(a) || a.capability.localeCompare(b.capability));
}

/** Lane order that holds still while the page refreshes: capabilities keep the place they first got,
 * and new ones join at the end in rank order. Without this, lanes would jump under the pointer every 15 s. */
export function stableOrder(previous: string[], groups: CapabilityGroup[]): string[] {
  const present = new Set(groups.map((g) => g.capability));
  const kept = previous.filter((name) => present.has(name));
  const known = new Set(kept);
  return [...kept, ...groups.map((g) => g.capability).filter((name) => !known.has(name))];
}

/** The groups in `order`; unlisted ones last. */
export function inOrder(groups: CapabilityGroup[], order: string[]): CapabilityGroup[] {
  const place = new Map(order.map((name, i) => [name, i]));
  return [...groups].sort((a, b) => (place.get(a.capability) ?? order.length) - (place.get(b.capability) ?? order.length));
}

/** The lanes to draw: the first `limit`, plus every capability with a failure (a failure never hides
 * behind "show all"), in `ordered` order. `all` draws everything. */
export function visibleGroups(ordered: CapabilityGroup[], limit: number, all: boolean): CapabilityGroup[] {
  if (all) return ordered;
  return ordered.filter((g, i) => i < limit || g.counts.failed > 0);
}

/** 42m, 5h, 3d: a length of time as one short unit. */
export function formatSpan(ms: number): string {
  if (ms < HOUR_MS) return `${Math.max(1, Math.round(ms / 60_000))}m`;
  if (ms < 48 * HOUR_MS) return `${Math.round(ms / HOUR_MS)}h`;
  return `${Math.round(ms / (24 * HOUR_MS))}d`;
}

/** The timeline's ticks, left to right: where each sits (0 to 1) and how far back from now it is. */
export function axisTicks(window: Interval): { at: number; label: string }[] {
  const span = window.end - window.start;
  return [0, 0.25, 0.5, 0.75, 1].map((at) => ({ at, label: at === 1 ? "now" : `-${formatSpan(span * (1 - at))}` }));
}

/** 1h 52m 03s style, leaving off leading zero units. */
export function formatDuration(ms: number): string {
  let seconds = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(seconds / 3600);
  seconds -= hours * 3600;
  const minutes = Math.floor(seconds / 60);
  seconds -= minutes * 60;
  return [hours ? `${hours}h` : "", hours || minutes ? `${minutes}m` : "", `${seconds}s`].filter(Boolean).join(" ");
}

/** How long the run took (a running one: so far); "" when unknown. */
export function durationOf(w: WatcherInfo, now: number): string {
  const interval = intervalOf(w, now);
  return interval ? formatDuration(interval.end - interval.start) : "";
}

/** "5m ago", "3h ago", "2d ago". */
export function timeAgo(then: number, now: number): string {
  const ms = Math.max(0, now - then);
  return ms < 60_000 ? "just now" : `${formatSpan(ms)} ago`;
}

/** The watchers whose capability and key contain the search text (any case); no text keeps them all. */
export function matching(watchers: WatcherInfo[], search: string): WatcherInfo[] {
  const needle = search.trim().toLowerCase();
  return needle ? watchers.filter((w) => `${w.capability} ${watcherKey(w)}`.toLowerCase().includes(needle)) : watchers;
}
