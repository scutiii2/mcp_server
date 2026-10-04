export interface HeatDay {
  /** UTC day, "YYYY-MM-DD". */
  date: string;
  tokens: number;
  /** 0 (none) to 4 (the busiest day); null for a day that has not come yet. */
  level: number | null;
}

export const HEAT_LEVELS = 4;
// Days back from today the map reaches (ember_api reports at most 366).
const SPAN_DAYS = 365;
const DAY_MS = 86_400_000;

function toTime(day: string): number {
  return Date.parse(`${day}T00:00:00Z`);
}

function toDay(time: number): string {
  return new Date(time).toISOString().slice(0, 10);
}

/**
 * The last 12 months as weeks (Sunday first, seven days each) up to the end of
 * the week that holds `today` (a UTC day). Each day has a level from 0 to 4
 * relative to the busiest day in the map; days after today have none.
 */
export function buildHeatmap(daily: { date: string; tokens: number }[], today: string): HeatDay[][] {
  const end = toTime(today);
  let start = end - SPAN_DAYS * DAY_MS;
  start -= new Date(start).getUTCDay() * DAY_MS; // back to the Sunday

  const tokensByDay = new Map(daily.map((d) => [d.date, d.tokens]));
  let peak = 0;
  for (let time = start; time <= end; time += DAY_MS) peak = Math.max(peak, tokensByDay.get(toDay(time)) ?? 0);

  const weeks: HeatDay[][] = [];
  for (let weekStart = start; weekStart <= end; weekStart += 7 * DAY_MS) {
    const week: HeatDay[] = [];
    for (let i = 0; i < 7; i += 1) {
      const time = weekStart + i * DAY_MS;
      const date = toDay(time);
      const tokens = tokensByDay.get(date) ?? 0;
      let level: number | null = 0;
      if (time > end) level = null;
      else if (tokens > 0) level = Math.ceil((tokens * HEAT_LEVELS) / peak); // 1 to 4: no day is above the peak
      week.push({ date, tokens, level });
    }
    weeks.push(week);
  }
  return weeks;
}
