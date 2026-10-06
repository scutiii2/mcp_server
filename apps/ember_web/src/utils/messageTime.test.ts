import { describe, expect, it } from "vitest";
import { clockTime, dayDividers, dayLabel, fullTime } from "./messageTime";

// Local noon, so a time zone never moves these onto another day.
const NOW = new Date(2026, 9, 6, 12, 0, 0);
const at = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h, 0, 0).toISOString();

describe("dayLabel", () => {
  it("names today and yesterday", () => {
    expect(dayLabel(at(2026, 10, 6, 1), NOW)).toBe("Today");
    expect(dayLabel(at(2026, 10, 5, 23), NOW)).toBe("Yesterday");
  });

  it("gives the date otherwise, with the year only when it is not this one", () => {
    expect(dayLabel(at(2026, 10, 1), NOW)).toContain("1");
    expect(dayLabel(at(2026, 10, 1), NOW)).not.toContain("2026");
    expect(dayLabel(at(2025, 12, 31), NOW)).toContain("2025");
  });

  it("is empty for a time it cannot read", () => {
    expect(dayLabel("not a time", NOW)).toBe("");
  });
});

describe("clockTime and fullTime", () => {
  it("are empty without a time", () => {
    expect(clockTime(undefined)).toBe("");
    expect(fullTime(undefined)).toBe("");
    expect(clockTime("garbage")).toBe("");
  });

  it("show the time", () => {
    expect(clockTime(at(2026, 10, 6, 14))).toMatch(/14|2/);
    expect(fullTime(at(2026, 10, 6, 14))).toContain("2026");
  });
});

describe("dayDividers", () => {
  it("puts one above the first message of each day", () => {
    const messages = [
      { at: at(2026, 10, 5, 9) },
      { at: at(2026, 10, 5, 10) },
      { at: at(2026, 10, 6, 9) },
      { at: at(2026, 10, 6, 10) },
    ];
    expect(dayDividers(messages, NOW)).toEqual(["Yesterday", null, "Today", null]);
  });

  it("skips messages without a time and does not repeat a day around them", () => {
    const messages = [{ at: at(2026, 10, 6, 9) }, {}, { at: at(2026, 10, 6, 11) }];
    expect(dayDividers(messages, NOW)).toEqual(["Today", null, null]);
  });

  it("is all null for a chat from before times existed", () => {
    expect(dayDividers([{}, {}], NOW)).toEqual([null, null]);
  });
});
