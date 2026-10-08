import { MAX_ATTACHMENT_BYTES, toBase64 } from "./AttachmentsClient";
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
  /** A page to open at /capabilities/<name> (mcp_server's gui/page.json). */
  has_gui?: boolean;
}

export type HelpTarget = "all" | "tools" | "commands" | "workflow";

/** One choice of a select whose options come from mcp_server; `extra` holds
 * the option's other fields (for a param's `sets` / `shows`). */
export interface ParamOption {
  value: string;
  label: string;
  extra: Record<string, string>;
}

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
  /** A select's options from a tool's `options_url`; `args` fill its {placeholders}. */
  options: (template: string, args: Record<string, string> = {}) => {
    const query = new URLSearchParams({ template });
    for (const [name, value] of Object.entries(args)) query.set(`arg.${name}`, value);
    return apiRequest<ParamOption[]>("GET", `/api/commands/options?${query.toString()}`);
  },
  /** Stores a file on mcp_server for a file-path parameter; returns its path there. */
  async upload(file: File): Promise<string> {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      throw new Error(`Too large - the limit is ${MAX_ATTACHMENT_BYTES / (1024 * 1024)} MB`);
    }
    const body = { filename: file.name, data: await toBase64(file) };
    return (await apiRequest<{ path: string }>("POST", "/api/uploads", body)).path;
  },
};
