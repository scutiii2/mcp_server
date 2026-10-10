import { describe, expect, it } from "vitest";
import { HEAT_LEVELS, buildHeatmap } from "./usageHeatmap";

const TODAY = "2026-10-15"; // a Thursday

const day = (date: string, tokens: number) => ({ date, tokens });
const flat = (weeks: ReturnType<typeof buildHeatmap>) => weeks.flat();
const find = (weeks: ReturnType<typeof buildHeatmap>, date: string) => flat(weeks).find((d) => d.date === date)!;
const weekday = (date: string) => new Date(`${date}T00:00:00Z`).getUTCDay();

describe("the grid", () => {
  const weeks = buildHeatmap([], TODAY);

  it("has seven days in every week", () => {
    expect(weeks.every((w) => w.length === 7)).toBe(true);
  });

  it("starts on a Sunday and every week begins on one", () => {
    expect(weeks.every((w) => weekday(w[0]!.date) === 0)).toBe(true);
    expect(weekday(flat(weeks)[0]!.date)).toBe(0);
  });

  it("goes from the Sunday on or before a year back to the end of today's week", () => {
    expect(flat(weeks)[0]!.date).toBe("2025-10-12");
    expect(weeks).toHaveLength(53);
    expect(weeks.at(-1)![0]!.date).toBe("2026-10-11");
    expect(weeks.at(-1)![6]!.date).toBe("2026-10-17");
  });

  it("has one cell for every day with no gaps or repeats", () => {
    const dates = flat(weeks).map((d) => d.date);

    expect(new Set(dates).size).toBe(dates.length);
    for (let i = 1; i < dates.length; i += 1) {
      expect(Date.parse(`${dates[i]}T00:00:00Z`) - Date.parse(`${dates[i - 1]}T00:00:00Z`)).toBe(86_400_000);
    }
  });

  it("gives days after today no level", () => {
    expect(find(weeks, "2026-10-15").level).toBe(0);
    expect(find(weeks, "2026-10-16").level).toBeNull();
    expect(find(weeks, "2026-10-17").level).toBeNull();
  });

  it("has no future days when today is a Saturday", () => {
    const saturday = buildHeatmap([], "2026-10-17");

    expect(flat(saturday).every((d) => d.level !== null)).toBe(true);
    expect(saturday.at(-1)![6]!.date).toBe("2026-10-17");
  });

  it("starts the first week on today's year-ago date when that is a Sunday", () => {
    // 2025-10-12 is a Sunday: 2026-10-12 minus 365 days.
    const monday = buildHeatmap([], "2026-10-12");

    expect(flat(monday)[0]!.date).toBe("2025-10-12");
  });

  it("is all level 0 without usage", () => {
    expect(flat(weeks).filter((d) => d.level !== null).every((d) => d.level === 0)).toBe(true);
  });
});

describe("when today is a Sunday", () => {
  // 2026-10-11 is a Sunday, and a year before it (2025-10-11) is a Saturday.
  const weeks = buildHeatmap([day("2026-10-11", 40)], "2026-10-11");

  it("ends with a week that holds only today as a real day", () => {
    const last = weeks.at(-1)!;

    expect(last[0]!.date).toBe("2026-10-11");
    expect(last[0]!.level).toBe(4);
    expect(last.slice(1).every((d) => d.level === null)).toBe(true);
  });

  it("starts on the Sunday before the Saturday a year back, a day earlier than 364 days would", () => {
    expect(flat(weeks)[0]!.date).toBe("2025-10-05");
    expect(weeks).toHaveLength(54);
  });
});

describe("levels", () => {
  it("counts today toward the busiest day", () => {
    const weeks = buildHeatmap([day("2026-10-15", 10), day("2026-10-14", 5)], TODAY);

    expect(find(weeks, "2026-10-15").level).toBe(4);
    expect(find(weeks, "2026-10-14").level).toBe(2);
  });

  it("makes the busiest day level 4", () => {
    const weeks = buildHeatmap([day("2026-10-01", 1000), day("2026-10-02", 10)], TODAY);

    expect(find(weeks, "2026-10-01").level).toBe(4);
  });

  it("rounds up, so a day with any usage is at least level 1", () => {
    const weeks = buildHeatmap([day("2026-10-01", 1_000_000), day("2026-10-02", 1)], TODAY);

    expect(find(weeks, "2026-10-02").level).toBe(1);
  });

  it.each([
    [250, 1],
    [251, 2],
    [500, 2],
    [501, 3],
    [750, 3],
    [751, 4],
    [1000, 4],
  ])("%d of a 1000 peak is level %d", (tokens, level) => {
    const weeks = buildHeatmap([day("2026-10-01", 1000), day("2026-10-02", tokens)], TODAY);

    expect(find(weeks, "2026-10-02").level).toBe(level);
  });

  it("never goes past the top level", () => {
    const weeks = buildHeatmap([day("2026-10-01", 7)], TODAY);

    expect(find(weeks, "2026-10-01").level).toBe(HEAT_LEVELS);
  });

  it("leaves days without usage at 0 next to busy ones", () => {
    const weeks = buildHeatmap([day("2026-10-01", 500)], TODAY);

    expect(find(weeks, "2026-09-30").level).toBe(0);
    expect(find(weeks, "2026-10-02").level).toBe(0);
  });

  it("carries each day's tokens", () => {
    const weeks = buildHeatmap([day("2026-10-01", 500), day("2026-10-02", 20)], TODAY);

    expect(find(weeks, "2026-10-01").tokens).toBe(500);
    expect(find(weeks, "2026-10-02").tokens).toBe(20);
    expect(find(weeks, "2026-10-03").tokens).toBe(0);
  });

  it("measures against the busiest day inside the map, not a day that is too old to show", () => {
    const weeks = buildHeatmap([day("2024-01-01", 1_000_000), day("2026-10-01", 10)], TODAY);

    expect(find(weeks, "2026-10-01").level).toBe(4);
  });

  it("ignores a day that has not come yet", () => {
    const weeks = buildHeatmap([day("2026-10-01", 10), day("2026-10-16", 1_000_000)], TODAY);

    expect(find(weeks, "2026-10-01").level).toBe(4);
    expect(find(weeks, "2026-10-16").level).toBeNull();
  });
});
