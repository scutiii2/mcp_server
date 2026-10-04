import { apiRequest } from "./http";

/** "failed" also stands for "timed_out". */
export type WatcherPhase = "running" | "completed" | "failed" | "timed_out";

/** One background watcher, as its capability reports it. */
export interface WatcherInfo {
  capability: string;
  key?: string;
  name?: string;
  phase: WatcherPhase | string;
  started_at?: string;
  last_polled_at?: string;
  detail?: Record<string, unknown>;
  recipients?: string[];
}

export interface WatchersReport {
  watchers: WatcherInfo[];
  /** "<capability>: <problem>" for each capability that didn't answer. */
  errors: string[];
}

export const watchersClient = {
  list: () => apiRequest<WatchersReport>("GET", "/api/watchers"),
};
