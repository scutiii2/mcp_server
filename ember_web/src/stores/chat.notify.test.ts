import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage, TurnEvent } from "../api/types";
import { chimeIfAway, notificationsSupported, notifyIfAway, requestNotifyPermission } from "../composables/useNotify";
import { watchTurn, type WatchEnd } from "../services/turnStream";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

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
  notifyIfAway: vi.fn(),
  notificationsSupported: vi.fn(() => true),
  requestNotifyPermission: vi.fn(),
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

  it("saves how long the call took on its reply, and nothing on the command itself", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.selectChat("c1");
    runCommand.mockImplementation(async () => {
      vi.setSystemTime(new Date("2026-10-01T10:00:02.340Z"));
      return "two files";
    });

    await chat.send("/files list");
    await flushPromises();

    const [command, reply] = appended();
    expect(command).toEqual({ role: "user", kind: "command", content: "/files list" });
    expect(reply).toEqual({ role: "assistant", kind: "command", content: "two files", duration_s: 2.3 });
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

// --- browser notification ----------------------------------------------------------------------

const NOTIFY_KEY = "ember_web.notify.1";
const notifyIfAwayMock = vi.mocked(notifyIfAway);
const permission = vi.mocked(requestNotifyPermission);
const supported = vi.mocked(notificationsSupported);

function browserPermission(state: NotificationPermission): void {
  vi.stubGlobal("Notification", { permission: state });
}

describe("the notification setting", () => {
  beforeEach(() => {
    supported.mockReturnValue(true);
    browserPermission("granted");
    permission.mockResolvedValue("granted");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is off by default", async () => {
    expect((await storeWith({ c1: TWO })).notify).toBe(false);
  });

  it("asks the browser when switched on, then stays on and is remembered", async () => {
    const chat = await storeWith({ c1: TWO });

    await chat.setNotify(true);

    expect(permission).toHaveBeenCalledOnce();
    expect(chat.notify).toBe(true);
    expect(chat.notifyError).toBe("");
    expect(localStorage.getItem(NOTIFY_KEY)).toBe("1");
  });

  it("stays off, says why and remembers nothing is wanted when the browser refuses", async () => {
    permission.mockResolvedValue("denied");
    const chat = await storeWith({ c1: TWO });

    await chat.setNotify(true);

    expect(chat.notify).toBe(false);
    expect(chat.notifyError).toContain("blocked for this site");
    expect(localStorage.getItem(NOTIFY_KEY)).toBe("0");
  });

  it("says so when the browser cannot show notifications", async () => {
    permission.mockResolvedValue("unsupported");
    const chat = await storeWith({ c1: TWO });

    await chat.setNotify(true);

    expect(chat.notify).toBe(false);
    expect(chat.notifyError).toContain("cannot show notifications");
  });

  it("clears an earlier error on the next try", async () => {
    permission.mockResolvedValueOnce("denied").mockResolvedValueOnce("granted");
    const chat = await storeWith({ c1: TWO });
    await chat.setNotify(true);
    expect(chat.notifyError).not.toBe("");

    await chat.setNotify(true);

    expect(chat.notifyError).toBe("");
    expect(chat.notify).toBe(true);
  });

  it("switches itself off when it was on and the browser now refuses", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.setNotify(true);
    expect(chat.notify).toBe(true);
    permission.mockResolvedValue("denied");

    await chat.setNotify(true);

    expect(chat.notify).toBe(false);
  });

  it("forgets an error when another account logs in", async () => {
    permission.mockResolvedValue("denied");
    const chat = await storeWith({ c1: TWO });
    await chat.setNotify(true);
    expect(chat.notifyError).not.toBe("");

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();

    expect(chat.notifyError).toBe("");
  });

  it("switching off does not ask the browser", async () => {
    const chat = await storeWith({ c1: TWO });
    await chat.setNotify(true);
    permission.mockClear();

    await chat.setNotify(false);

    expect(permission).not.toHaveBeenCalled();
    expect(chat.notify).toBe(false);
    expect(localStorage.getItem(NOTIFY_KEY)).toBe("0");
  });

  it("is read back on login while the browser still allows it", async () => {
    localStorage.setItem(NOTIFY_KEY, "1");

    expect((await storeWith({ c1: TWO })).notify).toBe(true);
  });

  it("is off on login when the browser's permission was taken back since", async () => {
    localStorage.setItem(NOTIFY_KEY, "1");
    browserPermission("denied");

    expect((await storeWith({ c1: TWO })).notify).toBe(false);
  });

  it("is off on login when the browser cannot show notifications", async () => {
    localStorage.setItem(NOTIFY_KEY, "1");
    supported.mockReturnValue(false);

    expect((await storeWith({ c1: TWO })).notify).toBe(false);
  });

  it("is not shared with another account", async () => {
    localStorage.setItem(NOTIFY_KEY, "1");
    const chat = await storeWith({ c1: TWO });
    expect(chat.notify).toBe(true);

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();

    expect(chat.notify).toBe(false);
  });
});

describe("notifying when an answer ends", () => {
  beforeEach(() => {
    supported.mockReturnValue(true);
    browserPermission("granted");
    permission.mockResolvedValue("granted");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function runningWithNotify() {
    const chat = await running();
    await chat.setNotify(true);
    return chat;
  }

  it("notifies once for an answer that arrives, with the chat's title and no sound of its own", async () => {
    await runningWithNotify();

    fire(finalEvent());
    endStream("done");
    await flushPromises();

    expect(notifyIfAwayMock).toHaveBeenCalledOnce();
    expect(notifyIfAwayMock.mock.calls[0]![0]).toMatchObject({ chatId: "c1", title: "Chat c1", silent: true });
  });

  it("lets the notification make its own sound when the chime is off", async () => {
    const chat = await runningWithNotify();
    chat.setChime(false);

    fire(finalEvent());
    endStream("done");
    await flushPromises();

    expect(notifyIfAwayMock.mock.calls[0]![0].silent).toBe(false);
  });

  it("opens the chat when the notification is clicked", async () => {
    const chat = await runningWithNotify();
    fire(finalEvent());
    endStream("done");
    await flushPromises();
    await chat.newChat();
    expect(chat.activeId).not.toBe("c1");

    notifyIfAwayMock.mock.calls[0]![0].onOpen();
    await flushPromises();

    expect(chat.activeId).toBe("c1");
  });

  it("does not notify while the setting is off", async () => {
    await running();

    fire(finalEvent());
    endStream("done");
    await flushPromises();

    expect(notifyIfAwayMock).not.toHaveBeenCalled();
  });

  it.each([
    ["an answer still being written", () => fire({ type: "token", text: "partial" }), null],
    ["a stopped answer", () => fire(finalEvent(true)), "done"],
    ["a failed answer", () => fire({ type: "error", message: "boom" }), "done"],
    ["a watch that was cut off", () => fire(finalEvent()), "aborted"],
    ["a turn that is gone", () => fire(finalEvent()), "gone"],
  ] as const)("does not notify for %s", async (_name, happen, end) => {
    await runningWithNotify();

    happen();
    if (end) endStream(end);
    await flushPromises();

    expect(notifyIfAwayMock).not.toHaveBeenCalled();
  });
});
