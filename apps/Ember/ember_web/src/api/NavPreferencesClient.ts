import { apiRequest } from "./http";

/** How the account arranges its nav rail: page ids (route paths such as
 * "/agents") in order, the pinned ones and the hidden ones. Empty lists mean
 * the default arrangement. */
export interface NavPrefs {
  order: string[];
  pinned: string[];
  hidden: string[];
}

/** ember_api's /api/nav-preferences routes (any logged-in account). */
export const navPreferencesClient = {
  get: () => apiRequest<NavPrefs>("GET", "/api/nav-preferences"),
  /** Replaces the whole arrangement; resolves to what ember_api stored. */
  save: (prefs: NavPrefs) => apiRequest<NavPrefs>("PUT", "/api/nav-preferences", prefs),
  reset: () => apiRequest<void>("DELETE", "/api/nav-preferences"),
};
