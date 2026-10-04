import { apiRequest } from "./http";

/** A rolling limit window. limit 0 = unlimited; times are naive UTC. */
export interface UsageWindow {
  used: number;
  limit: number;
  reset_at: string | null;
}

export interface UsageReport {
  days: number;
  since: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  summary_tokens: number;
  turns: number;
  chats: number;
  by_agent: { agent: string; model: string; tokens: number }[];
  /** UTC days with usage, oldest first. */
  daily: { date: string; tokens: number }[];
  /** Tokens by UTC hour of day: 24 numbers, hour 0 first. */
  hourly: number[];
}

export interface MyUsage {
  six_hour: UsageWindow;
  weekly: UsageWindow;
  report: UsageReport;
}

export interface AccountUsage {
  account_id: number;
  username: string;
  tokens: number;
  turns: number;
  last_used_at: string | null;
}

/** The period of a request: the last `days` days, or from the UTC day `since`
 * ("YYYY-MM-DD", from its midnight) when given. */
function period(days: number, since?: string): string {
  return `days=${days}${since ? `&since=${encodeURIComponent(since)}` : ""}`;
}

/** ember_api's usage routes. */
export const usageClient = {
  mine: (days: number, since?: string) => apiRequest<MyUsage>("GET", `/api/usage?${period(days, since)}`),
  /** admin.manage only. */
  allAccounts: (days: number, since?: string) =>
    apiRequest<AccountUsage[]>("GET", `/api/admin/usage?${period(days, since)}`),
};
