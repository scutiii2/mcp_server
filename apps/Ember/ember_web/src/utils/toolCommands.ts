import type { CommandInfo } from "../api/CommandsClient";
import { EXTENSION_SEPARATOR } from "../api/ExtensionsClient";

/** Slash command per tool name: built-in commands from the registry, plus
 * "/<extension> <tool>" for each tool of a shared extension. */
export function commandsByTool(
  commands: readonly CommandInfo[],
  toolNames: readonly string[],
  extensionId: string | null,
): Map<string, string> {
  const byTool = new Map<string, string>();
  for (const c of commands) byTool.set(c.tool_name, `/${c.capability} ${c.name}`);
  if (extensionId) {
    const prefix = `${extensionId}${EXTENSION_SEPARATOR}`;
    for (const name of toolNames) {
      if (name.startsWith(prefix) && name.length > prefix.length) byTool.set(name, `/${extensionId} ${name.slice(prefix.length)}`);
    }
  }
  return byTool;
}
