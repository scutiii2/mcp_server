import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onUnauthorized, UnauthorizedError } from "../api/http";
import type { TurnEvent } from "../api/types";
import { watchTurn } from "./turnStream";

const encoder = new TextEncoder();

/** An event as ember_api writes it: `id` and `data` lines, ended by a blank line. */
const sse = (event: Record<string, unknown>) => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`;
const token = (sequence: number, text = "x") => ({ sequence, type: "token", text });
const final = (sequence: number) => ({ sequence, type: "final", message: { role: "assistant", content: "done" } });

/** A response whose body delivers `chunks` one by one, then ends (or stays open). */
function streamResponse(chunks: string[], options: { keepOpen?: boolean; status?: number } = {}) {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (!options.keepOpen) controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
  const response = new Response(body, {
    status: options.status ?? 200,
    headers: { "Content-Type": "text/event-stream" },
  });
  return { response, wasCancelled: () => cancelled };
}

const fetchMock = vi.fn();
let unauthorized = vi.fn();

function urls(): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0]));
}

/** Runs the watch to the end, collecting what it reported. */
async function watch(after = 0, signal = new AbortController().signal) {
  const events: TurnEvent[] = [];
  const end = await watchTurn("chat-0001", after, (e) => events.push(e), signal);
  return { end, events };
}

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  unauthorized = vi.fn();
  onUnauthorized(unauthorized);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  onUnauthorized(() => {});
});

describe("reading events", () => {
  it("asks for the chat's events after the given sequence, with the session cookie", async () => {
    fetchMock.mockResolvedValue(streamResponse([sse(final(8))]).response);

    await watch(7);

    expect(urls()).toEqual(["/api/chats/chat-0001/events?after=7"]);
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>).Accept).toBe("text/event-stream");
  });

  it("hands every event to the caller in order and ends done at the final one", async () => {
    fetchMock.mockResolvedValue(streamResponse([sse(token(1, "Hel")), sse(token(2, "lo")), sse(final(3))]).response);

    const { end, events } = await watch();

    expect(end).toBe("done");
    expect(events.map((e) => e.sequence)).toEqual([1, 2, 3]);
    expect(events[2]!.type).toBe("final");
  });

  it("ends done at an error event too", async () => {
    fetchMock.mockResolvedValue(streamResponse([sse(token(1)), sse({ sequence: 2, type: "error", message: "boom" })]).response);

    const { end, events } = await watch();

    expect(end).toBe("done");
    expect(events.at(-1)!.type).toBe("error");
  });

  it("puts an event back together when it arrives in pieces", async () => {
    const whole = sse(token(1, "split"));
    const cut = [whole.slice(0, 7), whole.slice(7, 20), whole.slice(20), sse(final(2))];
    fetchMock.mockResolvedValue(streamResponse(cut).response);

    const { events } = await watch();

    expect(events.map((e) => e.sequence)).toEqual([1, 2]);
    expect((events[0] as { text: string }).text).toBe("split");
  });

  it("takes several events from one chunk", async () => {
    fetchMock.mockResolvedValue(streamResponse([sse(token(1)) + sse(token(2)) + sse(final(3))]).response);

    expect((await watch()).events.map((e) => e.sequence)).toEqual([1, 2, 3]);
  });

  it("waits when a chunk ends in the middle of the blank line between events", async () => {
    const first = sse(token(1));
    fetchMock.mockResolvedValue(streamResponse([first.slice(0, -1), first.slice(-1), sse(final(2))]).response);

    expect((await watch()).events.map((e) => e.sequence)).toEqual([1, 2]);
  });

  it("ignores a keep-alive ping", async () => {
    fetchMock.mockResolvedValue(streamResponse([": ping\n\n", sse(token(1)), ": ping\n\n", sse(final(2))]).response);

    expect((await watch()).events.map((e) => e.sequence)).toEqual([1, 2]);
  });

  it("joins the data lines of one event", async () => {
    // Joined with a newline, which JSON allows between tokens.
    const block = `id: 4\ndata: {"sequence":4,\ndata: "type":"final","message":{"role":"assistant","content":"x"}}\n\n`;
    fetchMock.mockResolvedValue(streamResponse([block]).response);

    const { events } = await watch();

    expect(events.map((e) => e.sequence)).toEqual([4]);
    expect(events[0]!.type).toBe("final");
  });

  it("decodes multi-byte text split inside a character", async () => {
    const bytes = encoder.encode(sse(token(1, "café 世界")));
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 30));
        controller.enqueue(bytes.slice(30));
        controller.enqueue(encoder.encode(sse(final(2))));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue(new Response(body, { status: 200 }));

    const { events } = await watch();

    expect((events[0] as { text: string }).text).toBe("café 世界");
  });

  it("closes the stream once it has the final event", async () => {
    const { response, wasCancelled } = streamResponse([sse(final(1))], { keepOpen: true });
    fetchMock.mockResolvedValue(response);

    await watch();

    expect(wasCancelled()).toBe(true);
  });

  it("does not look at events that come after the final one", async () => {
    fetchMock.mockResolvedValue(streamResponse([sse(final(1)) + sse(token(2))]).response);

    expect((await watch()).events.map((e) => e.sequence)).toEqual([1]);
  });
});

describe("when there is nothing to watch", () => {
  it("says gone for a 404 and does not retry", async () => {
    fetchMock.mockResolvedValue(new Response("no turn", { status: 404 }));

    const { end } = await watch();

    expect(end).toBe("gone");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reports a 401 and throws, without retrying", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 401 }));

    await expect(watch()).rejects.toBeInstanceOf(UnauthorizedError);

    expect(unauthorized).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("reconnecting", () => {
  it("tries again after a dropped stream and carries on from the last sequence it saw", async () => {
    fetchMock
      .mockResolvedValueOnce(streamResponse([sse(token(1)), sse(token(2))]).response) // ends without a final event
      .mockResolvedValueOnce(streamResponse([sse(token(3)), sse(final(4))]).response);

    const promise = watch(0);
    await vi.advanceTimersByTimeAsync(500);
    const { end, events } = await promise;

    expect(end).toBe("done");
    expect(events.map((e) => e.sequence)).toEqual([1, 2, 3, 4]);
    expect(urls()).toEqual(["/api/chats/chat-0001/events?after=0", "/api/chats/chat-0001/events?after=2"]);
  });

  it("waits 0.5 s before the first retry, not less", async () => {
    fetchMock.mockResolvedValueOnce(new Response("", { status: 500 })).mockResolvedValueOnce(streamResponse([sse(final(1))]).response);

    const promise = watch();
    await vi.advanceTimersByTimeAsync(499);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await promise;

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries on a server error and on a network error", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockRejectedValueOnce(new TypeError("network down"))
      .mockResolvedValueOnce(streamResponse([sse(final(1))]).response);

    const promise = watch();
    await vi.advanceTimersByTimeAsync(500 + 1000);
    const { end } = await promise;

    expect(end).toBe("done");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not read events from an error response", async () => {
    fetchMock
      .mockResolvedValueOnce(streamResponse([sse(token(1, "not real")), sse(final(2))], { status: 502 }).response)
      .mockResolvedValueOnce(streamResponse([sse(final(1))]).response);

    const promise = watch();
    await vi.advanceTimersByTimeAsync(500);
    const { end, events } = await promise;

    expect(end).toBe("done");
    expect(events.map((e) => e.sequence)).toEqual([1]);
    expect((events[0] as { message: { content: string } }).message.content).toBe("done");
  });

  it("backs off 0.5, 1, 2, 4 and 8 s, then gives up", async () => {
    fetchMock.mockImplementation(async () => new Response("", { status: 500 }));

    const promise = watch();
    const failure = promise.then(
      () => "resolved",
      (error: Error) => error.message,
    );
    const gaps = [500, 1000, 2000, 4000, 8000];
    let calls = 1;
    for (const gap of gaps) {
      await vi.advanceTimersByTimeAsync(gap - 1);
      expect(fetchMock).toHaveBeenCalledTimes(calls); // not yet
      await vi.advanceTimersByTimeAsync(1);
      calls += 1;
      expect(fetchMock).toHaveBeenCalledTimes(calls);
    }

    expect(await failure).toBe("Lost the connection to ember_api");
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("starts the backoff over after an event arrives", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("", { status: 500 }))
      .mockResolvedValueOnce(new Response("", { status: 500 }))
      .mockResolvedValueOnce(streamResponse([sse(token(1))]).response) // an event, then it drops
      .mockResolvedValueOnce(streamResponse([sse(final(2))]).response);

    const promise = watch();
    await vi.advanceTimersByTimeAsync(500); // after the first failure
    await vi.advanceTimersByTimeAsync(1000); // after the second
    await vi.advanceTimersByTimeAsync(500); // after the drop: back to the first delay, not 2 s
    const { end } = await promise;

    expect(end).toBe("done");
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("treats an event that is not JSON as a broken stream and tries again", async () => {
    fetchMock
      .mockResolvedValueOnce(streamResponse(["id: 1\ndata: {not json\n\n"]).response)
      .mockResolvedValueOnce(streamResponse([sse(final(1))]).response);

    const promise = watch();
    await vi.advanceTimersByTimeAsync(500);
    const { end, events } = await promise;

    expect(end).toBe("done");
    expect(events.map((e) => e.sequence)).toEqual([1]);
  });

  it("does not retry a 401 that arrives during a reconnect", async () => {
    fetchMock.mockResolvedValueOnce(streamResponse([sse(token(1))]).response).mockResolvedValueOnce(new Response("", { status: 401 }));

    const promise = watch();
    const outcome = promise.then(
      () => "resolved",
      (error: unknown) => error,
    );
    await vi.advanceTimersByTimeAsync(500);

    expect(await outcome).toBeInstanceOf(UnauthorizedError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("says gone when the turn has disappeared by the time it reconnects", async () => {
    fetchMock.mockResolvedValueOnce(streamResponse([sse(token(1))]).response).mockResolvedValueOnce(new Response("", { status: 404 }));

    const promise = watch();
    await vi.advanceTimersByTimeAsync(500);

    expect((await promise).end).toBe("gone");
  });
});

describe("stopping", () => {
  it("answers aborted when the signal fires while the stream is open", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = new ReadableStream<Uint8Array>({
        start(stream) {
          init.signal!.addEventListener("abort", () => stream.error(new DOMException("aborted", "AbortError")));
        },
      });
      return new Response(body, { status: 200 });
    });

    const promise = watch(0, controller.signal);
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();

    expect((await promise).end).toBe("aborted");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("answers aborted when the signal fires while waiting to reconnect, without trying again", async () => {
    const controller = new AbortController();
    fetchMock.mockResolvedValue(new Response("", { status: 500 }));

    const promise = watch(0, controller.signal);
    await vi.advanceTimersByTimeAsync(100);
    controller.abort();
    await vi.advanceTimersByTimeAsync(10_000);

    expect((await promise).end).toBe("aborted");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("answers aborted when the fetch itself is rejected after the signal fired", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation(async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });

    expect((await watch(0, controller.signal)).end).toBe("aborted");
  });
});
