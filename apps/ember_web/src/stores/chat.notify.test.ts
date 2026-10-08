import { accountCapabilitiesClient } from "../api/AccountCapabilitiesClient";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage, TurnEvent } from "../api/types";
import { chimeIfAway } from "../composables/useNotify";
import { watchTurn, type WatchEnd } from "../services/turnStream";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: vi.fn(), set: vi.fn() },
}));
vi.mock("../api/ChatsClient", () => ({
  chatsClient: {
    list: vi.fn(),
    get: vi.fn(),
    startTurn: vi.fn(),
    cancel: vi.fn(),
    search: vi.fn(),
    remove: vi.fn(),
    removeAll: vi.fn(),
    rename: vi.fn(),
    importChats: vi.fn(),
    append: vi.fn(),
    branch: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({
  chimeIfAway: vi.fn(),
}));

// Slash commands: what the runner returns is set per test.
const runCommand = vi.fn();
vi.mock("../services/slashCommands", () => ({
  SlashCommandRunner: class {
    run = runCommand;
    list = vi.fn(async () => []);
    schemaFor = vi.fn(async () => null);
  },
}));

const client = vi.mocked(chatsClient);
const watch = vi.mocked(watchTurn);
const chime = vi.mocked(chimeIfAway);

const ACCOUNT = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use", "tools.use"],
};
const CHIME_KEY = "ember_web.chime.1";

const summary = (id: string, count = 0, running = false): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "a1",
  message_count: count,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running,
});

const TWO: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
];

/** The live stream of the running answer: the store's event handler, and a
 * way to end the stream the way the real one does. */
let emit: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};
let endStream: (end: WatchEnd) => void = () => {
  throw new Error("no answer is being watched");
};
const fire = (event: Record<string, unknown>) => emit({ sequence: 1, ...event } as TurnEvent);
const finalEvent = (cancelled = false) => ({ type: "final", message: { role: "assistant", content: "done" }, cancelled });

async function storeWith(chats: Record<string, ChatMessage[]>, running: string[] = []) {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT;
  client.list.mockResolvedValue(Object.entries(chats).map(([id, m]) => summary(id, m.length, running.includes(id))));
  client.get.mockImplementation(async (id: string) => ({
    ...summary(id, chats[id]!.length, running.includes(id)),
    messages: structuredClone(chats[id]!),
  }));
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

/** A chat with an answer being written. */
async function running() {
  const chat = await storeWith({ c1: TWO });
  await chat.selectChat("c1");
  await chat.send("ask something");
  return chat;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(accountCapabilitiesClient.get).mockResolvedValue({ capabilities: [], extensions: [], disabled_tools: [] });
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-01T10:00:00Z"));
  watch.mockImplementation(
    (_id, _after, onEvent) =>
      new Promise<WatchEnd>((resolve) => {
        emit = onEvent;
        endStream = resolve;
      }),
  );
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1", 2, true) }, sequence: 5 });
  client.append.mockResolvedValue(undefined as never);
  client.search.mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the chime setting", () => {
  it("is on by default", async () => {
    const chat = await storeWith({ c1: TWO });

    expect(chat.chime).toBe(true);
  });

  it("is remembered per account", async () => {
    const chat = await storeWith({ c1: TWO });

    chat.setChime(false);
    expect(localStorage.getItem(CHIME_KEY)).toBe("0");
    chat.setChime(true);
    expect(localStorage.getItem(CHIME_KEY)).toBe("1");
  });

  it("is read back on login", async () => {
    localStorage.setItem(CHIME_KEY, "0");

    const chat = await storeWith({ c1: TWO });

    expect(chat.chime).toBe(false);
  });

  it("is on again when the stored value is anything but 0", async () => {
    localStorage.setItem(CHIME_KEY, "garbage");

    expect((await storeWith({ c1: TWO })).chime).toBe(true);
  });

  it("works when storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const chat = await storeWith({ c1: TWO });

    expect(() => chat.setChime(false)).not.toThrow();
    expect(chat.chime).toBe(false);
    vi.restoreAllMocks();
  });
});

describe("chiming when an answer ends", () => {
  it("chimes once for an answer that arrives", async () => {
    await running();

    fire(finalEvent());
    endStream("done");
    await flushPromises();

    expect(chime).toHaveBeenCalledOnce();
  });

  it("does not chime while the answer is still being written", async () => {
    await running();

    fire({ type: "token", text: "partial" });
    await flushPromises();

    expect(chime).not.toHaveBeenCalled();
  });

  it("does not chime for an answer the user stopped", async () => {
    await running();

    fire(finalEvent(true));
    endStream("done");
    await flushPromises();

    expect(chime).not.toHaveBeenCalled();
  });

  it("does not chime for a failed answer", async () => {
    await running();

    fire({ type: "error", message: "boom" });
    endStream("done");
    await flushPromises();

    expect(chime).not.toHaveBeenCalled();
  });

  it("does not chime when the watch was cut off", async () => {
    await running();

    fire(finalEvent());
    endStream("aborted");
    await flushPromises();

    expect(chime).not.toHaveBeenCalled();
  });

  it("does not chime when there was no turn to watch", async () => {
    await running();

    endStream("gone");
    await flushPromises();

    expect(chime).not.toHaveBeenCalled();
  });

  it("does not chime when the stream ends without a turn, even after a final event", async () => {
    await running();

    fire(finalEvent());
    endStream("gone");
    await flushPromises();

    expect(chime).not.toHaveBeenCalled();
  });

  it("does not chime when muted", async () => {
    const chat = await running();
    chat.setChime(false);

    fire(finalEvent());
    endStream("done");
    await flushPromises();

    expect(chime).not.toHaveBeenCalled();
  });

  it("does not carry one answer's outcome over to the next", async () => {
    const chat = await running();
    fire(finalEvent());
    endStream("done");
    await flushPromises();
    expect(chime).toHaveBeenCalledOnce();

    await chat.send("and again");
    endStream("done"); // ended without a final event of its own
    await flushPromises();

    expect(chime).toHaveBeenCalledOnce();
  });
});

describe("the clock of a running answer", () => {
  it("starts when the question is sent", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    expect(chat.clockStart).toBeNull();

    await chat.send("ask something");

    expect(chat.clockStart).toBe(Date.parse("2026-10-01T10:00:00Z"));
  });

  it("is already running while the server has not yet confirmed the question", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    let confirm!: () => void;
    client.startTurn.mockImplementation(
      () =>
        new Promise((resolve) => {
          confirm = () => resolve({ chat: { ...summary("c1", 2, true) }, sequence: 5 });
        }),
    );

    const sending = chat.send("ask something");
    await flushPromises();

    expect(chat.clockStart).toBe(Date.parse("2026-10-01T10:00:00Z"));
    confirm();
    await sending;
  });

  it("counts from the send, not from when the server confirmed it", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    client.startTurn.mockImplementation(async () => {
      vi.setSystemTime(new Date("2026-10-01T10:00:05Z"));
      return { chat: { ...summary("c1", 2, true) }, sequence: 5 };
    });

    await chat.send("ask something");

    expect(chat.clockStart).toBe(Date.parse("2026-10-01T10:00:00Z"));
  });

  it("stops when the answer ends", async () => {
    const chat = await running();

    fire(finalEvent());
    endStream("done");
    await flushPromises();

    expect(chat.clockStart).toBeNull();
  });

  it("is cleared when the question is not accepted", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    client.startTurn.mockRejectedValue(new Error("limit reached"));

    await chat.send("ask something");

    expect(chat.clockStart).toBeNull();
    expect(chat.sendError).toBe("limit reached");
  });

  it("is cleared when another chat is opened", async () => {
    const chat = await storeWith({ c1: TWO, c2: TWO });
    await chat.selectChat("c1");
    await chat.send("ask something");
    expect(chat.clockStart).not.toBeNull();

    await chat.selectChat("c2");

    expect(chat.clockStart).toBeNull();
  });

  it("starts at the moment a chat that is still answering is reopened", async () => {
    const chat = await storeWith({ c1: TWO }, ["c1"]);
    vi.setSystemTime(new Date("2026-10-01T10:03:00Z"));

    await chat.selectChat("c1");

    expect(chat.clockStart).toBe(Date.parse("2026-10-01T10:03:00Z"));
  });
});

describe("a slash command", () => {
  const appended = () => client.append.mock.calls.at(-1)![2] as ChatMessage[];

  it("saves how long the call took on its reply, and nothing on the command itself but its time", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    runCommand.mockImplementation(async () => {
      vi.setSystemTime(new Date("2026-10-01T10:00:02.340Z"));
      return "two files";
    });

    await chat.send("/files list");
    await flushPromises();

    const [command, reply] = appended();
    expect(command).toEqual({ role: "user", kind: "command", content: "/files list", at: "2026-10-01T10:00:00.000Z" });
    expect(reply).toEqual({
      role: "assistant",
      kind: "command",
      content: "two files",
      duration_s: 2.3,
      at: "2026-10-01T10:00:02.340Z",
    });
  });

  it("runs a clock while it works, and clears it after", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    let during: number | null = null;
    runCommand.mockImplementation(async () => {
      during = chat.clockStart;
      return "ok";
    });

    await chat.send("/files list");
    await flushPromises();

    expect(during).toBe(Date.parse("2026-10-01T10:00:00Z"));
    expect(chat.clockStart).toBeNull();
    expect(chat.working).toBe("");
  });

  it("clears the clock when the command fails", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    runCommand.mockRejectedValue(new Error("tool down"));

    await expect(chat.send("/files list")).rejects.toThrow("tool down");

    expect(chat.clockStart).toBeNull();
    expect(chat.working).toBe("");
  });

  it("keeps no time on a command it could not run for lack of permission", async () => {
    const chat = await storeWith({ c1: TWO });
    useAuthStore().account = { ...ACCOUNT, permissions: ["chat.use"] };
    await flushPromises();
    await chat.selectChat("c1");

    await chat.send("/files list");

    expect(chat.sendError).toContain("tools.use");
    expect(chat.clockStart).toBeNull();
    expect(runCommand).not.toHaveBeenCalled();
  });
});
