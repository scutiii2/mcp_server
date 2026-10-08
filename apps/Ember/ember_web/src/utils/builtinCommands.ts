/** Slash commands the browser handles itself, with no tool and no AI: each is
 * the keyboard form of a button above the composer. */
export type BuiltinCommand = "clear" | "compact" | "export" | "share";

export const BUILTIN_COMMANDS: { name: BuiltinCommand; description: string }[] = [
  { name: "clear", description: "Start this chat afresh; earlier messages stay as a log" },
  { name: "compact", description: "Condense the earlier messages into a summary the agent keeps" },
  { name: "export", description: "Download this chat as Markdown" },
  { name: "share", description: "Make a read-only link to this chat" },
];

/** The built-in command a sent text is, or null. Only the bare command counts
 * ("/clear", any case, spaces around it): with anything after it the text goes on
 * as before, so "/clear now" is not a built-in. */
export function builtinCommand(text: string): BuiltinCommand | null {
  const typed = text.trim().toLowerCase();
  return BUILTIN_COMMANDS.find((c) => typed === `/${c.name}`)?.name ?? null;
}
