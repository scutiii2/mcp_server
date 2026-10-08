import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { templatesClient, type PromptTemplate } from "../api/TemplatesClient";
import { useAuthStore } from "./auth";
import { useTemplatesStore } from "./templates";

vi.mock("../api/TemplatesClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/TemplatesClient")>()),
  templatesClient: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const client = vi.mocked(templatesClient);

const ACCOUNT = { id: 1, username: "u", email: "u@example.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"] };

const tpl = (id: number, name = `T${id}`, body = "body"): PromptTemplate => ({
  id,
  name,
  body,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
});

function setup(account: typeof ACCOUNT | null = ACCOUNT) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.account = account;
  return { auth, store: useTemplatesStore() };
}

beforeEach(() => {
  vi.clearAllMocks();
  client.list.mockResolvedValue([tpl(1), tpl(2)]);
});

describe("loading", () => {
  it("does not load until asked", async () => {
    setup();
    await flushPromises();

    expect(client.list).not.toHaveBeenCalled();
  });

  it("loads once, however often it is asked", async () => {
    const { store } = setup();

    await Promise.all([store.ensureLoaded(), store.ensureLoaded()]);
    await store.ensureLoaded();

    expect(client.list).toHaveBeenCalledOnce();
    expect(store.templates.map((t) => t.id)).toEqual([1, 2]);
    expect(store.loading).toBe(false);
  });

  it("shows the error and tries again on the next ask", async () => {
    client.list.mockRejectedValueOnce(new Error("down"));
    const { store } = setup();

    await store.ensureLoaded();
    expect(store.loadError).toBe("down");
    expect(store.templates).toEqual([]);

    await store.ensureLoaded();
    expect(store.loadError).toBe("");
    expect(store.templates).toHaveLength(2);
  });

  it("does not load without chat.use", async () => {
    const { store } = setup({ ...ACCOUNT, permissions: [] });

    await store.ensureLoaded();

    expect(client.list).not.toHaveBeenCalled();
  });

  it("drops the list when the account changes, and ignores a load still in flight", async () => {
    let finish!: (list: PromptTemplate[]) => void;
    client.list.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const { auth, store } = setup();
    const pending = store.ensureLoaded();

    auth.account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish([tpl(9, "the previous user's")]);
    await pending;

    expect(store.templates).toEqual([]);
    expect(store.loading).toBe(false);
    // The new account loads for itself.
    await store.ensureLoaded();
    expect(client.list).toHaveBeenCalledTimes(2);
    expect(store.templates.map((t) => t.id)).toEqual([1, 2]);
  });

  it("empties on logout", async () => {
    const { auth, store } = setup();
    await store.ensureLoaded();

    auth.account = null;
    await flushPromises();

    expect(store.templates).toEqual([]);
  });
});

describe("changing templates", () => {
  it("a new template goes to the front", async () => {
    client.create.mockResolvedValue(tpl(3, "New", "text"));
    const { store } = setup();
    await store.ensureLoaded();

    const created = await store.create("New", "text");

    expect(client.create).toHaveBeenCalledWith("New", "text");
    expect(created.id).toBe(3);
    expect(store.templates.map((t) => t.id)).toEqual([3, 1, 2]);
  });

  it("an edited template moves to the front, once", async () => {
    client.update.mockResolvedValue(tpl(2, "Renamed", "changed"));
    const { store } = setup();
    await store.ensureLoaded();

    await store.update(2, "Renamed", "changed");

    expect(client.update).toHaveBeenCalledWith(2, "Renamed", "changed");
    expect(store.templates.map((t) => [t.id, t.name])).toEqual([
      [2, "Renamed"],
      [1, "T1"],
    ]);
  });

  it("passes ember_api's error on and leaves the list alone", async () => {
    client.create.mockRejectedValue(new ApiError(409, 'You already have a template named "T1"'));
    const { store } = setup();
    await store.ensureLoaded();

    await expect(store.create("T1", "x")).rejects.toThrow('You already have a template named "T1"');

    expect(store.templates.map((t) => t.id)).toEqual([1, 2]);
  });

  it("removes a template", async () => {
    client.remove.mockResolvedValue(undefined);
    const { store } = setup();
    await store.ensureLoaded();

    await store.remove(1);

    expect(client.remove).toHaveBeenCalledWith(1);
    expect(store.templates.map((t) => t.id)).toEqual([2]);
  });

  it("treats one that is already gone (another tab) as removed", async () => {
    client.remove.mockRejectedValue(new ApiError(404, "Template not found"));
    const { store } = setup();
    await store.ensureLoaded();

    await store.remove(1);

    expect(store.templates.map((t) => t.id)).toEqual([2]);
  });

  it("keeps the template and rethrows other failures", async () => {
    client.remove.mockRejectedValue(new ApiError(500, "boom"));
    const { store } = setup();
    await store.ensureLoaded();

    await expect(store.remove(1)).rejects.toThrow("boom");

    expect(store.templates.map((t) => t.id)).toEqual([1, 2]);
  });
});
