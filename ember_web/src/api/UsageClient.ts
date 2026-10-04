import { apiRequest } from "./http";

/** A rolling limit window. limit 0 = unlimited; times are naive UTC. */
export interface UsageWindow {
  used: number;
  limit: number;
  reset_at: string | null;
}

export type UsageGroupBy = "agent" | "provider" | "gateway" | "model";

export interface UsageGroup {
  key: string;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  turns: number;
}

/** One stored usage row: an agent's call in a turn. Times are naive UTC. */
export interface UsageRecordRow {
  id: number;
  turn_id: string;
  kind: string;
  chat_id: string | null;
  agent: string | null;
  agent_id: string | null;
  provider_id: string | null;
  gateway: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number;
  started_at: string | null;
  finished_at: string | null;
  delegated_by: string | null;
  created_at: string;
}

export interface UsageFilters {
  agent?: string;
  provider?: string;
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
  /** The totals grouped by `group_by`, biggest first. */
  group_by: UsageGroupBy;
  groups: UsageGroup[];
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

/** The period plus any filters that are set, as a query string. */
function query(days: number, since: string | undefined, extra: Record<string, string | number | undefined>): string {
  const parts = [period(days, since)];
  for (const [name, value] of Object.entries(extra)) {
    if (value !== undefined && value !== "") parts.push(`${name}=${encodeURIComponent(String(value))}`);
  }
  return parts.join("&");
}

/** ember_api's usage routes. */
export const usageClient = {
  mine: (days: number, since?: string, options: UsageFilters & { groupBy?: UsageGroupBy } = {}) =>
    apiRequest<MyUsage>(
      "GET",
      `/api/usage?${query(days, since, { group_by: options.groupBy, agent: options.agent, provider: options.provider })}`,
    ),
  /** This account's rows, newest first (limit 1-500). */
  records: (days: number, since?: string, options: UsageFilters & { limit?: number } = {}) =>
    apiRequest<UsageRecordRow[]>(
      "GET",
      `/api/usage/records?${query(days, since, { agent: options.agent, provider: options.provider, limit: options.limit })}`,
    ),
  /** admin.manage only. */
  allAccounts: (days: number, since?: string) =>
    apiRequest<AccountUsage[]>("GET", `/api/admin/usage?${period(days, since)}`),
};
