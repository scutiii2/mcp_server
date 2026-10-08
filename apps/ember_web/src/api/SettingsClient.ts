import { apiRequest } from "./http";

/** What the administrator has switched on for everyone (ember_api's /api/settings). */
export interface AppSettings {
  /** Every answer asks before each tool runs, and "allow for this chat" is not offered. */
  force_tool_approval: boolean;
}

export const settingsClient = {
  /** Any logged-in account may read these. */
  get: () => apiRequest<AppSettings>("GET", "/api/settings"),
};
