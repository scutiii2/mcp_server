import { apiRequest } from "./http";
import type { CapabilityInfo } from "./CommandsClient";

/** A built-in mcp_server capability as the admin sees it: `enabled` is online,
 * `load_error` why it could not be brought online, `missing` its folder is
 * gone, `loaded` its tools were imported (false for a folder only discovered). */
export interface CapabilityStatus extends CapabilityInfo {
  load_error: string | null;
  missing: boolean;
  loaded: boolean;
}

const enc = encodeURIComponent;

/** ember_api's capability switchboard, for admins (admin.manage). Going online
 * re-imports the capability's code; refresh finds folders added while mcp_server runs. */
export const capabilitiesAdminClient = {
  list: () => apiRequest<CapabilityStatus[]>("GET", "/api/capabilities"),
  setOnline: (name: string, online: boolean) =>
    apiRequest<CapabilityStatus>("PATCH", `/api/capabilities/${enc(name)}`, { enabled: online }),
  refresh: () => apiRequest<CapabilityStatus[]>("POST", "/api/capabilities/refresh"),
};
