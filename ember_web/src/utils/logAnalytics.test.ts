import { describe, expect, it } from "vitest";
import { HEAT_LEVELS, accountLabel, axisLabel, bucketTitle, buildHourHeatmap, describeChange, formatCount, niceCeil } from "./logAnalytics";

describe("formatCount", () => {
  it("writes small numbers whole and big ones compact", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(1284)).toBe("1,284");
    expect(formatCount(12_900)).toBe("12.9K");
    expect(formatCount(20_000)).toBe("20K");
    expect(formatCount(1_240_000)).toBe("1.2M");
  });
});

describe("describeChange", () => {
  it("gives the percent against the previous period", () => {
    expect(describeChange(150, 100)).toEqual({ text: "+50%", direction: "up" });
    expect(describeChange(25, 100)).toEqual({ text: "−75%", direction: "down" });
    expect(describeChange(1, 3)).toEqual({ text: "−67%", direction: "down" });
  });

  it("says no change when equal or when the difference rounds away", () => {
    expect(describeChange(4, 4)).toEqual({ text: "no change", direction: "flat" });
    expect(describeChange(1001, 1000).direction).toBe("flat");
    expect(describeChange(0, 0)).toEqual({ text: "no change", direction: "flat" });
  });

  it("calls it new when there was nothing before (no division by zero)", () => {
    expect(describeChange(7, 0)).toEqual({ text: "new", direction: "new" });
  });
});

describe("niceCeil", () => {
  it("rounds up to a clean number with a whole half", () => {
    expect([0, 1, 2, 3, 5, 7, 10, 12, 45, 61, 99, 101, 450].map(niceCeil)).toEqual([
      2, 2, 2, 4, 6, 8, 10, 20, 60, 80, 100, 200, 600,
    ]);
    for (const n of [3, 13, 77, 123, 9999]) expect(niceCeil(n) % 2).toBe(0);
  });
});

describe("bucket labels", () => {
  it("shows the hour for hourly buckets and the date for daily ones, in UTC", () => {
    expect(axisLabel("2026-10-05T13:00:00", "hour")).toBe("13:00");
    expect(axisLabel("2026-10-05T00:00:00", "day")).toBe("Oct 5");
    expect(bucketTitle("2026-10-05T13:00:00", "hour")).toBe("Mon, Oct 5, 13:00 UTC");
    expect(bucketTitle("2026-10-05T00:00:00", "day")).toBe("Mon, Oct 5");
  });
});

describe("buildHourHeatmap", () => {
  const grid = buildHourHeatmap([
    { weekday: 1, hour: 13, count: 8 },
    { weekday: 0, hour: 20, count: 1 },
    { weekday: 6, hour: 0, count: 3 },
  ]);

  it("is a full week of 24 hours, Sunday first", () => {
    expect(grid).toHaveLength(7);
    expect(grid.every((row) => row.length === 24)).toBe(true);
    expect(grid[1]![13]).toMatchObject({ weekday: 1, hour: 13, count: 8 });
  });

  it("levels each hour against the busiest, any entry at least 1", () => {
    expect(grid[1]![13]!.level).toBe(HEAT_LEVELS);
    expect(grid[6]![0]!.level).toBe(2); // 3 of 8
    expect(grid[0]![20]!.level).toBe(1);
    expect(grid[3]![3]!.level).toBe(0);
  });

  it("is all empty with no entries", () => {
    expect(buildHourHeatmap([]).flat().every((c) => c.level === 0 && c.count === 0)).toBe(true);
  });
});

describe("accountLabel", () => {
  it("names the server, an account, or a deleted account", () => {
    expect(accountLabel({ account_id: null, username: null })).toBe("Server");
    expect(accountLabel({ account_id: 3, username: "alice" })).toBe("alice");
    expect(accountLabel({ account_id: 9, username: null })).toBe("Deleted account #9");
  });
});
