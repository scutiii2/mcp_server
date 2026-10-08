// The time of a chat message ("at": ISO 8601 UTC from ember_api) as the reader
// sees it: in their own time zone. Messages saved before times existed have none.

function parse(at: string | undefined): Date | null {
  if (!at) return null;
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dayStart(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** The clock time, e.g. "14:03". Empty for a message without a time. */
export function clockTime(at: string | undefined): string {
  const date = parse(at);
  return date ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}

/** Date and time in full, e.g. for a tooltip. Empty for a message without a time. */
export function fullTime(at: string | undefined): string {
  const date = parse(at);
  return date ? date.toLocaleString([], { dateStyle: "full", timeStyle: "medium" }) : "";
}

/** "Today", "Yesterday", or the date (with the year when it is not this one). */
export function dayLabel(at: string, now: Date = new Date()): string {
  const date = parse(at);
  if (!date) return "";
  const days = Math.round((dayStart(now) - dayStart(date)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  const sameYear = date.getFullYear() === now.getFullYear();
  return date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: sameYear ? undefined : "numeric" });
}

/** For each message, the divider to show above it: its day when that differs
 * from the day of the message with a time before it (or it is the first one
 * with a time); null otherwise, and always null without a time. */
export function dayDividers(messages: { at?: string }[], now: Date = new Date()): (string | null)[] {
  let previous: number | null = null;
  return messages.map((m) => {
    const date = parse(m.at);
    if (!date) return null;
    const day = dayStart(date);
    if (day === previous) return null;
    previous = day;
    return dayLabel(m.at!, now);
  });
}
