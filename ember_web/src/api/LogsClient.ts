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

/** actor: "server" or an account id. */
export type LogActor = "server" | number;

export const logsClient = {
  index: () => apiRequest<LogsIndex>("GET", "/api/logs"),
  list: (kind: LogKind, actor: LogActor) =>
    apiRequest<LogEntry[]>("GET", `/api/logs/${kind}?actor=${encodeURIComponent(String(actor))}`),
};
