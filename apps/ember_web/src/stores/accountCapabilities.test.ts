import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { accountCapabilitiesClient, type AccountCapabilities } from "../api/AccountCapabilitiesClient";
import type { Account } from "../api/AuthClient";
import { useAccountCapabilitiesStore } from "./accountCapabilities";
import { useAuthStore } from "./auth";

vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: vi.fn(), set: vi.fn() },
}));

const client = vi.mocked(accountCapabilitiesClient);
const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: [] };
const STORED: AccountCapabilities = { capabilities: ["pdf"], extensions: [], disabled_tools: ["tool_calc"] };

function setup(account: Account | null = ACCOUNT) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.account = account;
  return { auth, store: useAccountCapabilitiesStore() };
}

beforeEach(() => {
  vi.resetAllMocks();
  client.get.mockResolvedValue(STORED);
  client.set.mockImplementation(async (kind, key, enabled) => ({
    capabilities: kind === "capability" ? (enabled ? ["calc", "pdf"] : []) : [],
    extensions: kind === "extension" && enabled ? [key] : [],
    disabled_tools: enabled ? [] : ["tool_calc", "tool_pdf"],
  }));
});

describe("accountCapabilities store", () => {
  it("loads what the account added at login", async () => {
    const { store } = setup();
    expect(store.ready).toBe(false);

    await flushPromises();

    expect(store.capabilities).toEqual(["pdf"]);
    expect(store.disabledTools).toEqual(["tool_calc"]);
    expect(store.ready).toBe(true);
  });

  it("asks for nothing while logged out", async () => {
    const { store } = setup(null);
    await flushPromises();

    expect(client.get).not.toHaveBeenCalled();
    expect(store.ready).toBe(false);
  });

  it("is not ready, and says why, when the load fails", async () => {
    client.get.mockRejectedValue(new Error("mcp_server is unreachable"));
    const { store } = setup();

    await flushPromises();

    expect(store.ready).toBe(false);
    expect(store.error).toBe("mcp_server is unreachable");
    expect(store.capabilities).toEqual([]);
  });

  it("shows a change at once, saves it, and takes the server's answer", async () => {
    const { store } = setup();
    await flushPromises();

    const saving = store.setCapability("calc", true);

    expect(store.capabilities).toEqual(["calc", "pdf"]);
    await saving;
    expect(client.set).toHaveBeenCalledWith("capability", "calc", true);
    expect(store.disabledTools).toEqual([]);
    expect(store.error).toBe("");
  });

  it("changes extensions the same way", async () => {
    const { store } = setup();
    await flushPromises();

    await store.setExtension("notes", true);

    expect(client.set).toHaveBeenCalledWith("extension", "notes", true);
    expect(store.extensions).toEqual(["notes"]);
  });

  it("puts the server's copy back, and says why, when a save fails", async () => {
    const { store } = setup();
    await flushPromises();
    client.set.mockRejectedValue(new Error("Too many items added to this account"));

    await store.setCapability("calc", true);

    expect(store.capabilities).toEqual(["pdf"]);
    expect(store.error).toBe("Too many items added to this account");
    expect(client.get).toHaveBeenCalledTimes(2);
    expect(store.ready).toBe(true);
  });

  it("saves changes one at a time, in order, and the last answer wins", async () => {
    const { store } = setup();
    await flushPromises();
    const order: string[] = [];
    client.set.mockImplementation(async (_kind, key, enabled) => {
      order.push(`${key}:${enabled}`);
      return { capabilities: [key], extensions: [], disabled_tools: [] };
    });

    void store.setCapability("a", true);
    await store.setCapability("b", true);

    expect(order).toEqual(["a:true", "b:true"]);
    expect(store.capabilities).toEqual(["b"]);
  });

  it("settled() waits for a save that is still going", async () => {
    const { store } = setup();
    await flushPromises();
    let finish!: (value: AccountCapabilities) => void;
    client.set.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    void store.setCapability("calc", true);
    let done = false;
    void store.settled().then(() => (done = true));

    await flushPromises();
    expect(done).toBe(false);

    finish({ capabilities: ["calc", "pdf"], extensions: [], disabled_tools: [] });
    await flushPromises();
    expect(done).toBe(true);
    expect(store.disabledTools).toEqual([]);
  });

  it("never saves a queued change for the previous account after switching accounts", async () => {
    const { auth, store } = setup();
    await flushPromises();
    expect(store.capabilities).toEqual(["pdf"]);
    let finish!: (value: AccountCapabilities) => void;
    client.set.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));

    const firstSave = store.setCapability("a", true);
    await flushPromises();
    expect(client.set).toHaveBeenCalledWith("capability", "a", true);
    const queuedSave = store.setCapability("b", true);

    const nextAccountState: AccountCapabilities = {
      capabilities: ["account-two"], extensions: ["wiki"], disabled_tools: ["tool_other"],
    };
    client.get.mockResolvedValue(nextAccountState);
    auth.account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish({ capabilities: ["a", "pdf"], extensions: [], disabled_tools: [] });
    await Promise.all([firstSave, queuedSave]);

    expect(client.set).toHaveBeenCalledTimes(1);
    expect(client.set).not.toHaveBeenCalledWith("capability", "b", true);
    expect(store.capabilities).toEqual(nextAccountState.capabilities);
    expect(store.extensions).toEqual(nextAccountState.extensions);
    expect(store.disabledTools).toEqual(nextAccountState.disabled_tools);
    expect(store.ready).toBe(true);
  });

  it("refresh() reads the server again", async () => {
    const { store } = setup();
    await flushPromises();
    client.get.mockResolvedValue({ capabilities: [], extensions: ["wiki"], disabled_tools: [] });

    await store.refresh();

    expect(store.extensions).toEqual(["wiki"]);
  });

  it("forgets everything when the account changes, and ignores a late answer for the old one", async () => {
    let finish!: (value: AccountCapabilities) => void;
    client.get.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const { auth, store } = setup();

    auth.account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish({ capabilities: ["old"], extensions: [], disabled_tools: [] });
    await flushPromises();

    expect(store.capabilities).toEqual(["pdf"]);
  });
});
