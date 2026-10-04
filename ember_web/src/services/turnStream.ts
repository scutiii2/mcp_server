import { chatsClient } from "../api/ChatsClient";
import { reportUnauthorized, UnauthorizedError } from "../api/http";
import type { TurnEvent } from "../api/types";

/** How a watch ended. "done": the final/error event arrived. "gone": no turn
 * to watch (it finished and its replay expired) - reload the chat. */
export type WatchEnd = "done" | "gone" | "aborted";

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

/** Watches a turn ember_api is running, via its Server-Sent Events stream.
 * fetch() rather than EventSource: it can be aborted, sees the 401/404
 * status, and resumes from the last sequence after a dropped connection. */
export async function watchTurn(
  chatId: string,
  after: number,
  onEvent: (event: TurnEvent) => void,
  signal: AbortSignal,
): Promise<WatchEnd> {
  let cursor = after;
  for (let attempt = 0; ; attempt += 1) {
    try {
      const outcome = await readStream(chatId, cursor, signal, (event) => {
        cursor = event.sequence;
        attempt = 0;
        onEvent(event);
      });
      if (outcome !== "dropped") return outcome;
    } catch (err) {
      if (signal.aborted) return "aborted";
      if (err instanceof UnauthorizedError) throw err;
    }
    const delay = RECONNECT_DELAYS_MS[attempt];
    if (delay === undefined) throw new Error("Lost the connection to ember_api");
    await sleep(delay, signal);
    if (signal.aborted) return "aborted";
  }
}

async function readStream(
  chatId: string,
  after: number,
  signal: AbortSignal,
  onEvent: (event: TurnEvent) => void,
): Promise<WatchEnd | "dropped"> {
  const response = await fetch(chatsClient.eventsUrl(chatId, after), {
    credentials: "same-origin",
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (response.status === 404) return "gone";
  if (response.status === 401) {
    reportUnauthorized();
    throw new UnauthorizedError(401, "Not logged in");
  }
  if (!response.ok || !response.body) return "dropped";

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return "dropped"; // ended without a final event
    buffer += value;
    // Events are separated by a blank line; a partial one waits for more.
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (!data) continue; // a ": ping" keep-alive
      const event = JSON.parse(data) as TurnEvent;
      onEvent(event);
      if (event.type === "final" || event.type === "error") {
        await reader.cancel();
        return "done";
      }
    }
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}
