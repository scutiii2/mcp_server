import { apiRequest } from "./http";

/** One slash command: "/<capability> <name>" runs tool `tool_name`. */
export interface CommandInfo {
  capability: string;
  name: string;
  description: string;
  tool_name: string;
}

/** A built-in mcp_server capability and what it contributes. */
export interface CapabilityInfo {
  name: string;
  enabled: boolean;
  label: string | null;
  tools: string[];
  resources: string[];
}

export type HelpTarget = "all" | "tools" | "commands" | "workflow";

const enc = encodeURIComponent;

/** ember_api's pass-through to mcp_server's command registry, capability
 * help (tools.use) and capability switchboard (switching: admin.manage). */
export const commandsClient = {
  list: () => apiRequest<CommandInfo[]>("GET", "/api/commands"),
  helpIndex: () => apiRequest<unknown>("GET", "/api/commands/help"),
  help: (capability: string, target: HelpTarget, command?: string) =>
    apiRequest<unknown>(
      "GET",
      `/api/commands/help/${enc(capability)}?target=${target}${command ? `&command=${enc(command)}` : ""}`,
    ),
  capabilities: () => apiRequest<CapabilityInfo[]>("GET", "/api/capabilities"),
  setCapability: (name: string, enabled: boolean) =>
    apiRequest<CapabilityInfo>("PATCH", `/api/capabilities/${enc(name)}`, { enabled }),
};
