import { describe, expect, it } from "vitest";
import type { WatcherInfo } from "../api/WatchersClient";
import {
  axisTicks,
  barSpan,
  countStatuses,
  durationOf,
  formatDuration,
  formatSpan,
  groupByCapability,
  inOrder,
  intervalOf,
  matching,
  overlaps,
  stableOrder,
  statusOf,
  timeAgo,
  visibleGroups,
  watcherKey,
  windowOf,
} from "./watchers";

const NOW = Date.parse("2026-10-05T12:00:00Z");
const HOUR = 3_600_000;
const ago = (hours: number) => new Date(NOW - hours * HOUR).toISOString();

function watcher(capability: string, key: string, phase: string, startedHoursAgo?: number, endedHoursAgo?: number): WatcherInfo {
  return {
    capability,
    key,
    phase,
    started_at: startedHoursAgo === undefined ? undefined : ago(startedHoursAgo),
    last_polled_at: endedHoursAgo === undefined ? undefined : ago(endedHoursAgo),
  };
}

describe("statusOf", () => {
  it("maps phases, with timed_out counted as failed", () => {
    expect(["running", "completed", "failed", "timed_out", "paused"].map((phase) => statusOf(watcher("a", "k", phase)))).toEqual([
      "running",
      "succeeded",
      "failed",
      "failed",
      "other",
    ]);
  });
});

describe("watcherKey", () => {
  it("uses the key, then the name, then nothing", () => {
    expect(watcherKey({ capability: "a", phase: "running", key: "k", name: "n" })).toBe("k");
    expect(watcherKey({ capability: "a", phase: "running", name: "n" })).toBe("n");
    expect(watcherKey({ capability: "a", phase: "running" })).toBe("");
  });
});

describe("intervalOf", () => {
  it("runs a running watcher up to now", () => {
    expect(intervalOf(watcher("a", "k", "running", 2), NOW)).toEqual({ start: NOW - 2 * HOUR, end: NOW });
  });

  it("ends a finished watcher when it was last polled", () => {
    expect(intervalOf(watcher("a", "k", "completed", 5, 4), NOW)).toEqual({ start: NOW - 5 * HOUR, end: NOW - 4 * HOUR });
  });

  it("gives a finished watcher with no poll time no length", () => {
    const start = NOW - 5 * HOUR;
    expect(intervalOf(watcher("a", "k", "failed", 5), NOW)).toEqual({ start, end: start });
  });

  it("is null when it never said when it began", () => {
    expect(intervalOf(watcher("a", "k", "running"), NOW)).toBeNull();
    expect(intervalOf({ capability: "a", phase: "running", started_at: "not a date" }, NOW)).toBeNull();
  });
});

describe("windowOf", () => {
  it("is the range back from now", () => {
    expect(windowOf("24h", [], NOW)).toEqual({ start: NOW - 24 * HOUR, end: NOW });
    expect(windowOf("7d", [], NOW)).toEqual({ start: NOW - 7 * 24 * HOUR, end: NOW });
  });

  it("starts at the first run for All, but never tighter than an hour", () => {
    expect(windowOf("all", [watcher("a", "k", "completed", 30, 29), watcher("a", "j", "running", 2)], NOW)).toEqual({
      start: NOW - 30 * HOUR,
      end: NOW,
    });
    expect(windowOf("all", [watcher("a", "k", "running", 0.1)], NOW).start).toBe(NOW - HOUR);
    expect(windowOf("all", [], NOW).start).toBe(NOW - HOUR);
  });
});

describe("overlaps", () => {
  const window = { start: NOW - 24 * HOUR, end: NOW };

  it("keeps a run that touches the window, even if it began before it", () => {
    expect(overlaps(watcher("a", "k", "running", 30), window, NOW)).toBe(true);
    expect(overlaps(watcher("a", "k", "completed", 30, 25), window, NOW)).toBe(false);
    expect(overlaps(watcher("a", "k", "completed", 30, 23), window, NOW)).toBe(true);
  });

  it("never hides a run that cannot be placed", () => {
    expect(overlaps(watcher("a", "k", "running"), window, NOW)).toBe(true);
  });
});

describe("barSpan", () => {
  const window = { start: 0, end: 100 };

  it("gives the fractions of the window the run covers", () => {
    expect(barSpan({ start: 25, end: 50 }, window)).toEqual({ from: 0.25, to: 0.5 });
  });

  it("clips a run that began before the window or runs past it", () => {
    expect(barSpan({ start: -50, end: 40 }, window)).toEqual({ from: 0, to: 0.4 });
    expect(barSpan({ start: 80, end: 300 }, window)).toEqual({ from: 0.8, to: 1 });
  });
});

describe("groupByCapability", () => {
  const groups = groupByCapability([
    watcher("quiet", "q1", "completed", 1, 0.5),
    watcher("busy", "b1", "running", 3),
    watcher("broken", "x1", "completed", 5, 4),
    watcher("broken", "x2", "failed", 9, 8),
    watcher("broken", "x3", "running", 2),
    watcher("recent", "r1", "completed", 0.2, 0.1),
  ]);

  it("ranks a capability with a failure first, then a running one, then the most recent", () => {
    expect(groups.map((g) => g.capability)).toEqual(["broken", "busy", "recent", "quiet"]);
  });

  it("puts failed watchers first inside a capability, then running, then newest first", () => {
    expect(groups[0]!.watchers.map(watcherKey)).toEqual(["x2", "x3", "x1"]);
  });

  it("counts each status", () => {
    expect(groups[0]!.counts).toEqual({ running: 1, succeeded: 1, failed: 1, other: 0 });
    expect(countStatuses([watcher("a", "k", "paused")])).toEqual({ running: 0, succeeded: 0, failed: 0, other: 1 });
  });

  it("is deterministic on ties, by name", () => {
    const tied = groupByCapability([watcher("b", "k", "completed", 1, 0), watcher("a", "k", "completed", 1, 0)]);
    expect(tied.map((g) => g.capability)).toEqual(["a", "b"]);
  });
});

describe("stableOrder", () => {
  const rank = (...names: string[]) => groupByCapability(names.map((n) => watcher(n, "k", "completed", 1, 0)));

  it("keeps the places capabilities already have, even when the ranking changes", () => {
    expect(stableOrder(["b", "a"], rank("a", "b"))).toEqual(["b", "a"]);
  });

  it("adds new capabilities at the end and drops gone ones", () => {
    expect(stableOrder(["a", "gone", "b"], rank("a", "b", "c"))).toEqual(["a", "b", "c"]);
  });

  it("starts from the ranking", () => {
    expect(stableOrder([], groupByCapability([watcher("ok", "k", "completed", 1, 0), watcher("bad", "k", "failed", 1, 0)]))).toEqual(["bad", "ok"]);
  });
});

describe("visibleGroups", () => {
  const groups = groupByCapability(
    ["a", "b", "c", "d"].map((n) => watcher(n, "k", n === "d" ? "failed" : "completed", 1, 0)),
  );
  const ordered = inOrder(groups, ["a", "b", "c", "d"]);

  it("keeps the first few plus any capability with a failure", () => {
    expect(visibleGroups(ordered, 2, false).map((g) => g.capability)).toEqual(["a", "b", "d"]);
  });

  it("shows everything on request", () => {
    expect(visibleGroups(ordered, 2, true)).toHaveLength(4);
  });
});

describe("formatting", () => {
  it("writes a span as one short unit", () => {
    expect([30_000, 42 * 60_000, 5 * HOUR, 47 * HOUR, 72 * HOUR].map(formatSpan)).toEqual(["1m", "42m", "5h", "47h", "3d"]);
  });

  it("labels the axis back from now", () => {
    expect(axisTicks({ start: NOW - 24 * HOUR, end: NOW }).map((t) => t.label)).toEqual(["-24h", "-18h", "-12h", "-6h", "now"]);
    expect(axisTicks({ start: NOW - 7 * 24 * HOUR, end: NOW }).map((t) => t.at)).toEqual([0, 0.25, 0.5, 0.75, 1]);
  });

  it("writes a duration without leading zero units", () => {
    expect([12, 4 * 60 + 12, HOUR / 1000 + 5 * 60 + 3].map((s) => formatDuration(s * 1000))).toEqual(["12s", "4m 12s", "1h 5m 3s"]);
    expect(formatDuration(HOUR)).toBe("1h 0m 0s");
  });

  it("measures a run so far while it is running", () => {
    expect(durationOf(watcher("a", "k", "running", 1.5), NOW)).toBe("1h 30m 0s");
    expect(durationOf(watcher("a", "k", "completed", 1, 0.5), NOW)).toBe("30m 0s");
    expect(durationOf(watcher("a", "k", "running"), NOW)).toBe("");
  });

  it("says how long ago", () => {
    expect(timeAgo(NOW - 20_000, NOW)).toBe("just now");
    expect(timeAgo(NOW - 5 * HOUR, NOW)).toBe("5h ago");
  });
});

describe("matching", () => {
  const list = [watcher("email", "invoice-1", "running"), watcher("ssh", "deploy", "running")];

  it("searches capability and key in any case", () => {
    expect(matching(list, " EMAIL ").map(watcherKey)).toEqual(["invoice-1"]);
    expect(matching(list, "deploy").map(watcherKey)).toEqual(["deploy"]);
  });

  it("keeps everything with no text", () => {
    expect(matching(list, "  ")).toEqual(list);
  });
});
