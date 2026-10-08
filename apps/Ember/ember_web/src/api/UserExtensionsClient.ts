import { apiRequest } from "./http";

/** One of the account's own MCP servers. `status` comes from a live probe by
 * ai_agent (cached a minute by ember_api): "connected", "error" (it could not be
 * reached), or "unknown" (not checked). Header values are never sent back, only
 * their names. */
export interface UserExtension {
  id: string;
  label: string;
  description: string;
  url: string;
  header_names: string[];
  enabled: boolean;
  status: "connected" | "error" | "unknown" | string;
  error: string | null;
  tools: string[];
}

export interface UserExtensionInput {
  label: string;
  url: string;
  description?: string;
  /** Replaces every saved header; leave it out to keep them. */
  headers?: Record<string, string>;
}

export type UserExtensionPatch = Partial<UserExtensionInput> & { enabled?: boolean };

const enc = encodeURIComponent;

/** ember_api's /api/user-extensions routes (chat.use; mutations also need extensions.personal.manage, own rows only). */
export const userExtensionsClient = {
  list: () => apiRequest<UserExtension[]>("GET", "/api/user-extensions"),
  create: (input: UserExtensionInput) => apiRequest<UserExtension>("POST", "/api/user-extensions", input),
  update: (id: string, patch: UserExtensionPatch) =>
    apiRequest<UserExtension>("PATCH", `/api/user-extensions/${enc(id)}`, patch),
  remove: (id: string) => apiRequest<void>("DELETE", `/api/user-extensions/${enc(id)}`),
};
