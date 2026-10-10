import type { UsageWindow } from "../api/UsageClient";
/** An ISO time from the server as a timestamp; one without a zone is UTC. */
export function parseServerTime(value: string | undefined): number {
  if (!value) return NaN;
  return Date.parse(/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
}


/** How much of a limit window is used, 0 to 100; 0 when it has no limit. */
export function usagePercent(window: UsageWindow): number {
  return window.limit ? Math.min(100, Math.round((window.used / window.limit) * 100)) : 0;
}
