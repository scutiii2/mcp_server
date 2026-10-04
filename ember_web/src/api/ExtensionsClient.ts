import { apiRequest } from "./http";

/** Another MCP server mcp_server re-exposes; its tools are named
 * "<id>__<tool>". */
export interface ExtensionInfo {
  id: string;
  label: string;
  description: string;
  status: "connected" | "error" | string;
  error: string | null;
  tools: string[];
}

export interface ExtensionCreate {
  label: string;
  url: string;
  description: string;
}

/** Separates an extension tool's id from its own name. */
export const EXTENSION_SEPARATOR = "__";

/** ember_api's pass-through to mcp_server's extensions: listing needs
 * chat.use or tools.use, adding/removing admin.manage. */
export const extensionsClient = {
  list: () => apiRequest<ExtensionInfo[]>("GET", "/api/extensions"),
  add: (extension: ExtensionCreate) => apiRequest<ExtensionInfo>("POST", "/api/extensions", extension),
  remove: (id: string) => apiRequest<void>("DELETE", `/api/extensions/${encodeURIComponent(id)}`),
};
