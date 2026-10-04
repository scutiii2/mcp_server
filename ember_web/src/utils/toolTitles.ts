/** Human-friendly titles for MCP tool names (port of chat_app's
 * services/tool_titles.py). `restart_service_tool` -> "Restart Service",
 * `tool_srv_startApp` -> "Start App". */

// Tools whose automatic title wouldn't read well, e.g.
// get_cpu_usage_tool: "Get CPU Usage".
const OVERRIDES: Record<string, string> = {};

// Splits camelCase without breaking up a run of capitals ("srvAPI" -> "srv API").
const CAMEL_BOUNDARY = /(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/g;

// mcp_server capability tools are "tool_{capabilityPrefix}_{camelAction}";
// only the action belongs in the title.
const CAPABILITY_TOOL = /^tool_[A-Za-z0-9]+_(.+)$/;

function capitalize(word: string): string {
  // All-caps words (acronyms) stay as they are.
  if (word === word.toUpperCase() && /[A-Z]/.test(word)) return word;
  return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
}

export function toolTitle(name: string): string {
  const override = OVERRIDES[name];
  if (override) return override;
  let base = name.endsWith("_tool") ? name.slice(0, -5) : name;
  base = CAPABILITY_TOOL.exec(base)?.[1] ?? base;
  const words = base
    .split("_")
    .flatMap((part) => part.replace(CAMEL_BOUNDARY, " ").split(" "))
    .filter(Boolean);
  return words.map(capitalize).join(" ") || name;
}
