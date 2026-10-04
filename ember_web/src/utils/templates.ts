import type { PromptTemplate } from "../api/TemplatesClient";

/** Templates whose name contains `query` (ignoring case), those that start
 * with it first; the given order is kept within each group. An empty query
 * keeps them all. */
export function filterTemplates(templates: PromptTemplate[], query: string): PromptTemplate[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return templates;
  const starts: PromptTemplate[] = [];
  const contains: PromptTemplate[] = [];
  for (const t of templates) {
    const name = t.name.toLowerCase();
    if (name.startsWith(needle)) starts.push(t);
    else if (name.includes(needle)) contains.push(t);
  }
  return [...starts, ...contains];
}

/** The text after a leading "#" while a template is being looked up, or null
 * when the draft isn't one: it must start with "#" and stay on one line. */
export function templateQuery(draft: string): string | null {
  return draft.startsWith("#") && !draft.includes("\n") ? draft.slice(1) : null;
}

/** `text` added to a draft: alone when the draft is empty, else on a new line. */
export function appendToDraft(draft: string, text: string): string {
  if (!draft.trim()) return text;
  return `${draft.replace(/\s+$/, "")}\n${text}`;
}

/** First non-empty line of a template's body, cut for a list row. */
export function preview(body: string, max = 90): string {
  const line = body.split("\n").find((l) => l.trim()) ?? "";
  const trimmed = line.trim().replace(/\s+/g, " ");
  return trimmed.length > max ? `${trimmed.slice(0, max - 1)}…` : trimmed;
}
