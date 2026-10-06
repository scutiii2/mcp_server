/** Small readings of a usage report: the favorite agent, the busiest hour and
 * the start of the month. Pure, so they are easy to check. */

export interface AgentTokens {
  agent: string;
  model: string;
  tokens: number;
}

/** "claude claude-opus": the agent and model that used the most tokens;
 * null when nothing was used. */
export function favoriteAgent(byAgent: AgentTokens[]): string | null {
  let best: AgentTokens | null = null;
  for (const row of byAgent) {
    if (row.tokens > 0 && (best === null || row.tokens > best.tokens)) best = row;
  }
  return best ? `${best.agent} ${best.model}`.trim() : null;
}

/** The hour of day (0-23) with the most tokens, in the viewer's time; null
 * when nothing was used. `hourly` is by UTC hour (24 numbers); `utcOffsetMinutes`
 * is the viewer's offset east of UTC. The offset is rounded to whole hours
 * and is today's, so a half-hour zone can be off by up to an hour and a
 * daylight-saving change inside the period is ignored. Ties go to the earlier hour. */
export function peakHour(hourly: number[], utcOffsetMinutes: number = -new Date().getTimezoneOffset()): number | null {
  if (hourly.length !== 24) return null;
  const shift = Math.round(utcOffsetMinutes / 60);
  const local = new Array<number>(24).fill(0);
  hourly.forEach((tokens, utcHour) => {
    local[(((utcHour + shift) % 24) + 24) % 24]! += tokens;
  });
  let best: number | null = null;
  local.forEach((tokens, hour) => {
    if (tokens > 0 && (best === null || tokens > local[best]!)) best = hour;
  });
  return best;
}

/** 0 -> "12 AM", 15 -> "3 PM". */
export function hourLabel(hour: number): string {
  return `${hour % 12 || 12} ${hour < 12 ? "AM" : "PM"}`;
}

/** The first day of `now`'s month in UTC, as "YYYY-MM-01". */
export function monthStart(now: Date): string {
  return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}-01`;
}

/** `now`'s UTC day as "YYYY-MM-DD". */
export function utcDay(now: Date): string {
  return now.toISOString().slice(0, 10);
}
