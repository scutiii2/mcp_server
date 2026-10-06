import { describe, expect, it } from "vitest";
import { favoriteAgent, hourLabel, monthStart, peakHour, utcDay } from "./usageStats";

describe("favoriteAgent", () => {
  it("names the agent and model that used the most tokens", () => {
    expect(
      favoriteAgent([
        { agent: "openai", model: "gpt", tokens: 50 },
        { agent: "claude", model: "opus", tokens: 900 },
        { agent: "local", model: "llama", tokens: 20 },
      ]),
    ).toBe("claude opus");
  });

  it("does not rely on the rows being sorted", () => {
    expect(favoriteAgent([{ agent: "a", model: "m", tokens: 1 }, { agent: "b", model: "n", tokens: 2 }])).toBe("b n");
  });

  it("goes to the first of two that tie", () => {
    expect(favoriteAgent([{ agent: "a", model: "m", tokens: 5 }, { agent: "b", model: "n", tokens: 5 }])).toBe("a m");
  });

  it("drops the space when there is no model", () => {
    expect(favoriteAgent([{ agent: "claude", model: "", tokens: 5 }])).toBe("claude");
  });

  it("is null with no rows, or only rows that used nothing", () => {
    expect(favoriteAgent([])).toBeNull();
    expect(favoriteAgent([{ agent: "a", model: "m", tokens: 0 }])).toBeNull();
  });
});

describe("peakHour", () => {
  const at = (hour: number, tokens: number): number[] => {
    const hourly = new Array<number>(24).fill(0);
    hourly[hour] = tokens;
    return hourly;
  };

  it("is the busiest UTC hour when the viewer is on UTC", () => {
    expect(peakHour(at(14, 100), 0)).toBe(14);
  });

  it("moves to the viewer's time east of UTC", () => {
    expect(peakHour(at(14, 100), 120)).toBe(16);
  });

  it("moves to the viewer's time west of UTC", () => {
    expect(peakHour(at(14, 100), -300)).toBe(9);
  });

  it("wraps past midnight in both directions", () => {
    expect(peakHour(at(23, 1), 120)).toBe(1);
    expect(peakHour(at(1, 1), -180)).toBe(22);
  });

  it("keeps every hour's tokens: the hours are only rotated", () => {
    const hourly = at(5, 60);
    hourly[6] = 50;

    expect(peakHour(hourly, 0)).toBe(5);
    expect(peakHour(hourly, 18 * 60)).toBe(23); // 5 + 18
    expect(peakHour(hourly.map((n) => n * 2), 18 * 60)).toBe(23);
  });

  it("rounds a half-hour zone to a whole hour (halves go up)", () => {
    expect(peakHour(at(10, 1), 330)).toBe(16); // 5.5 -> 6
    expect(peakHour(at(10, 1), 270)).toBe(15); // 4.5 -> 5
    expect(peakHour(at(10, 1), -330)).toBe(5); // -5.5 -> -5
  });

  it("goes to the earlier hour on a tie", () => {
    const hourly = at(3, 10);
    hourly[20] = 10;
    expect(peakHour(hourly, 0)).toBe(3);
  });

  it("is null when nothing was used", () => {
    expect(peakHour(new Array<number>(24).fill(0), 0)).toBeNull();
  });

  it("is null for a histogram that is not 24 hours", () => {
    expect(peakHour([1, 2, 3], 0)).toBeNull();
    expect(peakHour([], 0)).toBeNull();
  });

  it("uses the browser's own offset when none is given", () => {
    const hourly = at(0, 1);
    const shift = Math.round(-new Date().getTimezoneOffset() / 60);

    expect(peakHour(hourly)).toBe((((0 + shift) % 24) + 24) % 24);
  });
});

describe("hourLabel", () => {
  it.each([
    [0, "12 AM"],
    [1, "1 AM"],
    [11, "11 AM"],
    [12, "12 PM"],
    [13, "1 PM"],
    [23, "11 PM"],
  ])("%d -> %s", (hour, expected) => {
    expect(hourLabel(hour)).toBe(expected);
  });
});

describe("monthStart and utcDay", () => {
  it("is the 1st of the month, in UTC", () => {
    expect(monthStart(new Date("2026-10-15T08:00:00Z"))).toBe("2026-10-01");
    expect(monthStart(new Date("2026-01-31T23:59:59Z"))).toBe("2026-01-01");
  });

  it("pads a one-digit month", () => {
    expect(monthStart(new Date("2026-03-05T00:00:00Z"))).toBe("2026-03-01");
  });

  it("goes by the UTC date, not the local one", () => {
    expect(monthStart(new Date("2026-03-01T00:30:00Z"))).toBe("2026-03-01");
    expect(monthStart(new Date("2026-02-28T23:30:00Z"))).toBe("2026-02-01");
  });

  it("utcDay is the UTC date", () => {
    expect(utcDay(new Date("2026-10-15T23:59:59Z"))).toBe("2026-10-15");
    expect(utcDay(new Date("2026-10-16T00:00:00Z"))).toBe("2026-10-16");
  });
});
