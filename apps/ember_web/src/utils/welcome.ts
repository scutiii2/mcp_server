import type { CommandInfo } from "../api/CommandsClient";

export const GREETINGS = [
  "Hello! How can I help you today?",
  "Hi there! What can I do for you?",
  "Hey! What's on your mind?",
  "Welcome back! What would you like to know?",
  "Hello! Ask me anything to get started.",
  "Hi! I'm ready when you are.",
  "Hey there! What are we working on today?",
] as const;

/** One greeting; `random` is injectable so a test can choose. */
export function pickGreeting(random: () => number = Math.random): string {
  return GREETINGS[Math.min(GREETINGS.length - 1, Math.floor(random() * GREETINGS.length))]!;
}

/** What to try first. Slash commands are offered only when there are some
 * (they need the tools.use permission). */
export function welcomeTip(hasCommands: boolean): string {
  return hasCommands
    ? "Type / to run a command, # for a saved prompt, or just ask a question."
    : "Type # for a saved prompt, or just ask a question.";
}

const MAX_CAPABILITIES = 10;

/** "files" -> "Files", "watcher_x" -> "Watcher x". */
function capabilityLabel(id: string): string {
  const words = id.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "I can help you with: Files (/files), Notes (/notes)"; empty when there are no commands. */
export function capabilityLine(commands: CommandInfo[]): string {
  const ids = [...new Set(commands.map((c) => c.capability))];
  if (ids.length === 0) return "";
  const shown = ids.slice(0, MAX_CAPABILITIES).map((id) => `${capabilityLabel(id)} (/${id})`);
  const more = ids.length - shown.length;
  return `I can help you with: ${shown.join(", ")}${more > 0 ? `, and ${more} more` : ""}`;
}
