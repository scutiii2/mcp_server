/** Icons for the Capabilities page tiles. Capabilities carry no icon of their
 * own, so one is picked from keywords in the capability's name and label; a
 * wrench stands in for anything unrecognised. SVG path data, 24x24, stroked. */

const WRENCH = [
  "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z",
];
const SERVER = [
  "M4 3h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
  "M4 13h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2z",
  "M6 7h.01",
  "M6 17h.01",
];
const FILE = [
  "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z",
  "M14 2v4a2 2 0 0 0 2 2h4",
  "M10 9H8",
  "M16 13H8",
  "M16 17H8",
];
const MAIL = [
  "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
  "m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7",
];
const CALENDAR = ["M8 2v4", "M16 2v4", "M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M3 10h18"];
const DATABASE = [
  "M12 2c4.97 0 9 1.34 9 3s-4.03 3-9 3-9-1.34-9-3 4.03-3 9-3z",
  "M21 12c0 1.66-4 3-9 3s-9-1.34-9-3",
  "M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5",
];
const GLOBE = [
  "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z",
  "M2 12h20",
  "M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z",
];
const CODE = ["m16 18 6-6-6-6", "m8 6-6 6 6 6"];
const CLOCK = ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M12 6v6l4 2"];
const IMAGE = [
  "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
  "M9 8.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z",
  "m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21",
];

/** The plug of the Extensions page, for tools that come from extensions. */
export const EXTENSION_ICON = ["M12 22v-5", "M9 8V2", "M15 8V2", "M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"];

// First match wins. Each pattern matches from the start of a word, so "net"
// does not fire inside "planet".
const RULES: [RegExp, string[]][] = [
  [/\b(pdf|file|doc|folder|text|note)/, FILE],
  [/\b(e?mail|smtp|imap|inbox)/, MAIL],
  [/\b(calendar|schedule|event)/, CALENDAR],
  [/\b(database|db\b|sql|storage)/, DATABASE],
  [/\b(web|http|browser|search|url|network|internet)/, GLOBE],
  [/\b(code|git|script|shell|develop)/, CODE],
  [/\b(time|clock|timer|cron|watch)/, CLOCK],
  [/\b(image|photo|picture|screenshot|camera)/, IMAGE],
  [/\b(server|service|system|process|host)/, SERVER],
];

/** The icon for a capability, picked from its name and label. */
export function capabilityIcon(name: string, label?: string | null): string[] {
  const text = `${name} ${label ?? ""}`.toLowerCase();
  return RULES.find(([pattern]) => pattern.test(text))?.[1] ?? WRENCH;
}
