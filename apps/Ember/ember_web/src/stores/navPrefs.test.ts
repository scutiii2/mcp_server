import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { navPreferencesClient, type NavPrefs } from "../api/NavPreferencesClient";
import type { Account } from "../api/AuthClient";
import { useAuthStore } from "./auth";
import { useNavPrefsStore } from "./navPrefs";

vi.mock("../api/NavPreferencesClient", () => ({
  navPreferencesClient: { get: vi.fn(), save: vi.fn(), reset: vi.fn() },
}));

const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: [] };
const STORED: NavPrefs = { order: ["/b", "/a"], pinned: ["/b"], hidden: [] };
const NEXT: NavPrefs = { order: ["/a", "/b"], pinned: [], hidden: ["/b"] };

function setup(account: Account | null = ACCOUNT) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.account = account;
  return { auth, store: useNavPrefsStore() };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(navPreferencesClient.get).mockResolvedValue(STORED);
  vi.mocked(navPreferencesClient.save).mockImplementation(async (p) => p);
  vi.mocked(navPreferencesClient.reset).mockResolvedValue(undefined);
});

describe("navPrefs store", () => {
  it("loads the account's arrangement at login", async () => {
    const { store } = setup();
    expect(store.ready).toBe(false);

    await flushPromises();

    expect(store.prefs).toEqual(STORED);
    expect(store.ready).toBe(true);
  });

  it("asks for nothing while logged out", async () => {
    const { store } = setup(null);
    await flushPromises();

    expect(navPreferencesClient.get).not.toHaveBeenCalled();
    expect(store.ready).toBe(false);
  });

  it("is ready with the default arrangement when the load fails", async () => {
    vi.mocked(navPreferencesClient.get).mockRejectedValue(new Error("down"));
    const { store } = setup();

    await flushPromises();

    expect(store.ready).toBe(true);
    expect(store.prefs.order).toEqual([]);
    expect(store.error).toBe("down");
  });

  it("shows a change at once and saves it", async () => {
    const { store } = setup();
    await flushPromises();

    const saving = store.update(NEXT);

    expect(store.prefs).toEqual(NEXT);
    await saving;
    expect(navPreferencesClient.save).toHaveBeenCalledWith(NEXT);
  });

  it("saves changes one at a time, in order, and keeps the newest", async () => {
    const { store } = setup();
    await flushPromises();
    const order: string[] = [];
    vi.mocked(navPreferencesClient.save).mockImplementation(async (p) => {
      order.push(p.order.join());
      return p;
    });
    const second: NavPrefs = { order: ["/x"], pinned: [], hidden: [] };

    void store.update(NEXT);
    await store.update(second);

    expect(order).toEqual(["/a,/b", "/x"]);
    expect(store.prefs).toEqual(second);
  });

  it("loads the server's copy back when a save fails", async () => {
    const { store } = setup();
    await flushPromises();
    vi.mocked(navPreferencesClient.save).mockRejectedValue(new Error("boom"));

    await store.update(NEXT);

    expect(store.error).toBe("boom");
    expect(store.prefs).toEqual(STORED);
  });

  it("resets to the default arrangement", async () => {
    const { store } = setup();
    await flushPromises();

    await store.reset();

    expect(navPreferencesClient.reset).toHaveBeenCalled();
    expect(store.prefs).toEqual({ order: [], pinned: [], hidden: [] });
  });

  it("drops the arrangement when another account logs in", async () => {
    const { store, auth } = setup();
    await flushPromises();
    vi.mocked(navPreferencesClient.get).mockResolvedValue({ order: [], pinned: [], hidden: ["/z"] });

    auth.account = { ...ACCOUNT, id: 2 };
    await nextTick();
    await flushPromises();

    expect(store.prefs.hidden).toEqual(["/z"]);
  });
});
