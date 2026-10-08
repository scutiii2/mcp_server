import { quoteWord, type ToolField } from "./toolSchema";

/** One completion of the word being typed after "/<capability> <command> ". */
export interface ParamSuggestion {
  /** What the word becomes: "key=" or "key=value". */
  text: string;
  description: string;
  /** Where that word starts in the text it was suggested for. */
  start: number;
}

/** The words typed so far (quotes group, as splitWords does) and the one still
 * being typed. Null while inside an open quote: nothing to suggest there. */
function splitTail(tail: string): { done: string[]; current: string; start: number } | null {
  const done: string[] = [];
  let quote: string | null = null;
  let inWord = false;
  let wordStart = 0;
  for (let i = 0; i < tail.length; i += 1) {
    const ch = tail[i]!;
    if (quote) {
      if (ch === "\\" && quote === '"') i += 1;
      else if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") {
      if (!inWord) wordStart = i;
      inWord = true;
      quote = ch;
    } else if (/\s/.test(ch)) {
      if (inWord) done.push(tail.slice(wordStart, i));
      inWord = false;
    } else if (!inWord) {
      inWord = true;
      wordStart = i;
    }
  }
  if (quote) return null;
  return inWord
    ? { done, current: tail.slice(wordStart), start: wordStart }
    : { done, current: "", start: tail.length };
}

/** Values worth offering for a field: its choices, examples, or true/false. */
function valuesOf(field: ToolField): string[] {
  if (field.kind === "boolean") return ["true", "false"];
  return field.options.length > 0 ? field.options : field.examples;
}

/** Completions for the word being typed in `tail` (the text after the command
 * name): "key=" for parameters not given yet, then, after "key=", that
 * parameter's values. */
export function paramSuggestions(fields: ToolField[], tail: string): ParamSuggestion[] {
  const split = splitTail(tail);
  if (!split) return [];
  const { done, current, start } = split;
  const needle = current.toLowerCase();
  const eq = current.indexOf("=");

  if (eq < 0) {
    const used = new Set(done.map((w) => w.slice(0, Math.max(w.indexOf("="), 0))));
    return fields
      .filter((f) => !used.has(f.name) && f.name.toLowerCase().startsWith(needle))
      .map((f) => ({ text: `${f.name}=`, description: `${f.required ? "required · " : ""}${f.description}`.replace(/ · $/, ""), start }));
  }

  const field = fields.find((f) => f.name === current.slice(0, eq));
  const typed = current.slice(eq + 1);
  if (!field || /^["']/.test(typed)) return [];
  return valuesOf(field)
    .filter((v) => v.toLowerCase().startsWith(typed.toLowerCase()) && v !== typed)
    .map((v) => ({ text: `${field.name}=${quoteWord(v)}`, description: field.label, start }));
}
