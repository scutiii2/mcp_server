// Pure helpers for drawing a generated secret: how strong it is, how it is
// spaced for reading, and which characters get a colour.

export type StrengthLevel = "weak" | "fair" | "strong" | "excellent";

/** The strength bar is full at this many bits of entropy. */
export const STRENGTH_FULL_BITS = 128;

const LABELS: Record<StrengthLevel, string> = { weak: "Weak", fair: "Fair", strong: "Strong", excellent: "Excellent" };

export function strengthOf(bits: number): { level: StrengthLevel; label: string; fraction: number } {
  const level: StrengthLevel = bits < 45 ? "weak" : bits < 70 ? "fair" : bits < 100 ? "strong" : "excellent";
  return { level, label: LABELS[level], fraction: Math.max(0, Math.min(bits / STRENGTH_FULL_BITS, 1)) };
}

/** `text` with a space every `size` characters ("123456" -> "123 456"). */
export function groupText(text: string, size: number): string {
  if (size < 1 || text.length <= size) return text;
  const groups: string[] = [];
  for (let i = 0; i < text.length; i += size) groups.push(text.slice(i, i + size));
  return groups.join(" ");
}

export interface Segment {
  text: string;
  kind: "plain" | "digit" | "symbol";
}

/** Runs of the same kind of character. Only a value with letters in it (a
 * password, a passphrase) is coloured; digits-only values (a PIN, a TOTP
 * code) stay plain, since colouring every character says nothing. */
export function segmentsOf(text: string): Segment[] {
  if (text === "") return [];
  if (!/[A-Za-z]/.test(text)) return [{ text, kind: "plain" }];
  const segments: Segment[] = [];
  for (const ch of text) {
    const kind: Segment["kind"] = /[0-9]/.test(ch) ? "digit" : /[A-Za-z\s]/.test(ch) ? "plain" : "symbol";
    const last = segments[segments.length - 1];
    if (last && last.kind === kind) last.text += ch;
    else segments.push({ text: ch, kind });
  }
  return segments;
}
