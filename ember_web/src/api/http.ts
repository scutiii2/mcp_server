/** JSON calls to ember_api's REST routes (same origin, session cookie). */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** 401: no session, or it expired. */
export class UnauthorizedError extends ApiError {}

let unauthorizedHandler: (() => void) | null = null;

/** Called on every 401 (the auth store uses it to drop the account). */
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler;
}

/** For requests made outside apiRequest (the turn event stream). */
export function reportUnauthorized(): void {
  unauthorizedHandler?.();
}

/** FastAPI errors: `detail` is a string, or a list of field errors (422). */
function messageOf(data: unknown, fallback: string): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d as { msg?: unknown } | null)?.msg)
      .filter((m): m is string => typeof m === "string");
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export async function apiRequest<T>(method: HttpMethod, path: string, body?: unknown): Promise<T> {
  // Every POST is JSON, even with no payload: ember_api rejects anything
  // else as a CSRF guard. Other methods send a body only when given one.
  const init: RequestInit = { method, credentials: "same-origin" };
  if (method === "POST" || body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body ?? {});
  }
  const response = await fetch(path, init);
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = messageOf(data, response.statusText || `HTTP ${response.status}`);
    if (response.status === 401) {
      unauthorizedHandler?.();
      throw new UnauthorizedError(401, message);
    }
    throw new ApiError(response.status, message);
  }
  return data as T;
}
