import { apiRequest } from "./http";

export type AccountItemKind = "capability" | "extension";

/** What the account has added, kept in ember_api. `disabled_tools` is the tool
 * names of every capability it has not added, sent with each question. */
export interface AccountCapabilities {
  capabilities: string[];
  extensions: string[];
  disabled_tools: string[];
}

/** ember_api's /api/account-capabilities routes (any logged-in account). */
export const accountCapabilitiesClient = {
  get: () => apiRequest<AccountCapabilities>("GET", "/api/account-capabilities"),
  /** Adds or removes one item; resolves to the whole set as stored. */
  set: (kind: AccountItemKind, key: string, enabled: boolean) =>
    apiRequest<AccountCapabilities>("PUT", `/api/account-capabilities/${kind}/${encodeURIComponent(key)}`, { enabled }),
};
