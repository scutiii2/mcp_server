import { apiRequest } from "./http";

export type LogKind = "action" | "error" | "chat_trace";

export interface LogEntry {
  id: number;
  kind: LogKind;
  /** null: the server itself. */
  account_id: number | null;
  source: string;
  message: string;
  details: string | null;
  /** Naive UTC. */
  created_at: string;
}

export interface LogsIndex {
  /** The kinds this account may read, in tab order. */
  kinds: LogKind[];
  accounts: { id: number; username: string }[];
}

export type AnalyticsRange = "24h" | "7d" | "30d" | "90d";

export interface KindTotal {
  current: number;
  /** The same length of time just before. */
  previous: number;
}

export interface AnalyticsReport {
  period: AnalyticsRange;
  bucket: "hour" | "day";
  /** Only the kinds this account may read, in tab order. */
  kinds: LogKind[];
  totals: Partial<Record<LogKind, KindTotal>>;
  /** Zero-filled, oldest first; `bucket` is a naive-UTC start. */
  series: { bucket: string; counts: Partial<Record<LogKind, number>> }[];
  top_sources: Partial<Record<LogKind, { source: string; count: number }[]>>;
  /** account_id null: the server; username null: a deleted account. */
  accounts: Partial<Record<LogKind, { account_id: number | null; username: string | null; count: number }[]>>;
  /** UTC; weekday 0 is Sunday. Only the cells that have entries. */
  heatmap: { weekday: number; hour: number; count: number }[];
}

/** actor: "server" or an account id. */
export type LogActor = "server" | number;

export const logsClient = {
  index: () => apiRequest<LogsIndex>("GET", "/api/logs"),
  list: (kind: LogKind, actor: LogActor) =>
    apiRequest<LogEntry[]>("GET", `/api/logs/${kind}?actor=${encodeURIComponent(String(actor))}`),
  analytics: (range: AnalyticsRange) => apiRequest<AnalyticsReport>("GET", `/api/logs/analytics?range=${range}`),
};
