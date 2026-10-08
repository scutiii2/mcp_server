import { apiRequest } from "./http";
import type { AnalyticsRange } from "./LogsClient";

export type { AnalyticsRange };

/** The same window now and just before it. A rate or latency is null with nothing to measure. */
export interface Compared<T> {
  current: T;
  /** The same length of time just before. */
  previous: T;
}

export interface RouteStat {
  /** "GET /api/chats/{chat_id}": the route template, never a raw path. */
  name: string;
  count: number;
  /** 5xx over all requests, 0 to 1. */
  error_rate: number;
  p95_ms: number | null;
}

export interface ToolStat {
  name: string;
  calls: number;
  failures: number;
  p95_ms: number | null;
}

export interface UpstreamStat {
  /** "ai_agent" or "mcp_server". */
  target: string;
  calls: number;
  failures: number;
  failure_rate: number;
  p95_ms: number | null;
  tools: ToolStat[];
}

export interface TrafficReport {
  period: AnalyticsRange;
  bucket: "hour" | "day";
  /** Latency is kept in bands: a value at this cap means "at least this slow". */
  latency_cap_ms: number;
  totals: {
    requests: Compared<number>;
    /** 5xx over all requests, 0 to 1; null with no requests. */
    error_rate: Compared<number | null>;
    p95_ms: Compared<number | null>;
    upstream_failures: Compared<number>;
  };
  /** Zero-filled, oldest first; `bucket` is a naive-UTC start. Latency is null with no requests. */
  series: {
    bucket: string;
    requests: Record<"2xx" | "3xx" | "4xx" | "5xx", number>;
    p50_ms: number | null;
    p95_ms: number | null;
  }[];
  routes: { busiest: RouteStat[]; slowest: RouteStat[] };
  upstream: UpstreamStat[];
}

export const trafficClient = {
  analytics: (range: AnalyticsRange) => apiRequest<TrafficReport>("GET", `/api/traffic/analytics?range=${range}`),
};
