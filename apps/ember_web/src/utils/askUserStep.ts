import type { ToolStep } from "../api/types";

const PREFIX = "- ";

/** What a saved `ask_user` step shows instead of its raw JSON: one line per
 * question, "<header>: <what the user chose>". Null for any other step. The
 * answer lines are the text ai_agent gave the model ("- <question>: <answer>"),
 * read back by position. A question ends with "?", so the answer is what follows
 * the last "?: " of the line; a typed answer that itself contains "?: " is
 * shown cut (display only). */
export function describeAskUser(step: ToolStep): string[] | null {
  if (step.tool !== "ask_user") return null;
  const asked = step.arguments.questions;
  if (!Array.isArray(asked) || asked.length === 0) return null;
  const headers = asked.map((q) => {
    const header = q && typeof q === "object" ? (q as { header?: unknown }).header : undefined;
    return typeof header === "string" ? header : "Question";
  });
  const lines = step.result.split("\n").filter((line) => line.startsWith(PREFIX));
  if (step.result.startsWith("The user answered:") && lines.length === headers.length) {
    return headers.map((header, i) => {
      const body = lines[i]!.slice(PREFIX.length);
      const at = body.lastIndexOf("?: ");
      const answer = at >= 0 ? body.slice(at + 3) : body.slice(body.indexOf(": ") + 2);
      return `${header}: ${answer}`;
    });
  }
  if (step.result.startsWith("The user skipped")) return headers.map((header) => `${header}: skipped`);
  if (step.result.startsWith("The user did not answer")) return headers.map((header) => `${header}: no answer`);
  return headers;
}
