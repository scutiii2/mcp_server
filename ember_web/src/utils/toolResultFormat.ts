/** Readable Markdown for a tool's JSON result (port of chat_app's
 * services/command_formatting.py).
 *
 * Generic on purpose: it walks whatever JSON object comes back instead of
 * knowing tools by name, so a new tool needs no entry here. mcp_server's
 * result contracts are flat scalars, lists of same-shaped dicts and a
 * `message` - or a nested `status` plus a preformatted `report`. Keys render
 * in the tool's own field order (a contract's declared order is its intended
 * display order).
 */

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type JsonObject = { [key: string]: Json };

// chat_app-only download plumbing: those links point at chat_app, not ember.
const SKIPPED_KEYS = new Set(["download_url", "file_path", "remote_filename", "size_bytes", "download_markers"]);

/** Markdown for `raw`, or null when it isn't a JSON object (then the caller
 * shows the text as it is - never worse than the original). */
export function formatToolResult(raw: string): string | null {
  const text = raw.trim();
  if (!text.startsWith("{")) return null;
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isObject(data)) return null;
  return formatObject(data) || null;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEmpty(value: Json): boolean {
  return (
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0) ||
    (isObject(value) && Object.keys(value).length === 0)
  );
}

function formatKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatScalar(value: Json | undefined): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatTable(rows: JsonObject[]): string {
  // Columns in first-seen order across all rows, so a row with an extra key
  // still gets its column.
  const columns: string[] = [];
  for (const row of rows) for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key);
  const cell = (row: JsonObject, column: string) =>
    formatScalar(row[column]).replace(/\|/g, "\\|").replace(/\n/g, " ");
  return [
    `| ${columns.map(formatKey).join(" | ")} |`,
    `| ${columns.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${columns.map((c) => cell(row, c)).join(" | ")} |`),
  ].join("\n");
}

function formatList(key: string, items: Json[]): string {
  const heading = `**${formatKey(key)}** (${items.length})`;
  if (items.every(isObject)) return `${heading}\n\n${formatTable(items as JsonObject[])}`;
  return `${heading}\n${items.map((item) => `- ${formatScalar(item)}`).join("\n")}`;
}

function formatMapping(key: string, value: JsonObject): string {
  const body = Object.entries(value)
    .map(([k, v]) => `- **${formatKey(k)}:** ${formatScalar(v)}`)
    .join("\n");
  return `**${formatKey(key)}**\n${body}`;
}

function formatObject(data: JsonObject): string {
  const report = typeof data.report === "string" && data.report.trim() ? data.report : null;
  const blocks: string[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (SKIPPED_KEYS.has(key)) continue;
    if (key === "message") {
      if (typeof value === "string" && value.trim()) blocks.push(value.trim());
      continue;
    }
    if (key === "report") {
      // Fenced: reports are preformatted (aligned columns) and Markdown
      // would collapse their whitespace.
      if (report) blocks.push("```\n" + report.trim() + "\n```");
      continue;
    }
    if (isEmpty(value)) continue;
    // The report already shows a nested object's fields readably.
    if (report && isObject(value)) continue;
    if (Array.isArray(value)) blocks.push(formatList(key, value));
    else if (isObject(value)) blocks.push(formatMapping(key, value));
    else blocks.push(`**${formatKey(key)}:** ${formatScalar(value)}`);
  }
  return blocks.join("\n\n");
}
