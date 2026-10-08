import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Account } from "../api/AuthClient";
import { ApiError } from "../api/http";
import { userExtensionsClient, type UserExtension } from "../api/UserExtensionsClient";
import { useAuthStore } from "./auth";
import { useUserExtensionsStore } from "./userExtensions";

vi.mock("../api/UserExtensionsClient", () => ({
  userExtensionsClient: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const client = vi.mocked(userExtensionsClient);

const ext = (id: string, extra: Partial<UserExtension> = {}): UserExtension => ({
  id,
  label: id.toUpperCase(),
  description: "",
  url: `https://${id}.example.com/mcp`,
  header_names: [],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search"],
  ...extra,
});

const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: ["chat.use"] };

function setup(account: Account | null = ACCOUNT) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.account = account;
  return { auth, store: useUserExtensionsStore() };
}

beforeEach(() => {
  vi.resetAllMocks();
  client.list.mockResolvedValue([ext("notes"), ext("wiki")]);
});

describe("userExtensions store", () => {
  it("loads the account's extensions at sign-in", async () => {
    const { store } = setup();
    expect(store.ready).toBe(false);

    await flushPromises();

    expect(store.items.map((i) => i.id)).toEqual(["notes", "wiki"]);
    expect(store.ready).toBe(true);
  });

  it("asks for nothing while logged out or without chat.use", async () => {
    setup(null);
    setup({ ...ACCOUNT, permissions: ["tools.use"] });
    await flushPromises();

    expect(client.list).not.toHaveBeenCalled();
  });

  it("keeps what it had and says why when a load fails", async () => {
    const { store } = setup();
    await flushPromises();
    client.list.mockRejectedValue(new Error("down"));

    await store.refresh();

    expect(store.error).toBe("down");
    expect(store.items).toHaveLength(2);
  });

  it("refresh takes the server's copy (new statuses)", async () => {
    const { store } = setup();
    await flushPromises();
    client.list.mockResolvedValue([ext("notes", { status: "error", error: "Timed out" }), ext("wiki")]);

    await store.refresh();

    expect(store.items[0]!.status).toBe("error");
    expect(store.error).toBe("");
  });

  it("add puts the created extension in the list and returns it", async () => {
    const { store } = setup();
    await flushPromises();
    client.create.mockResolvedValue(ext("new"));

    const created = await store.add({ label: "New", url: "https://new.example.com/mcp" });

    expect(created.id).toBe("new");
    expect(store.items.map((i) => i.id)).toEqual(["notes", "wiki", "new"]);
  });

  it("add and update let the API error through, for the modal to show", async () => {
    const { store } = setup();
    await flushPromises();
    client.create.mockRejectedValue(new ApiError(422, "Enter an http or https address"));
    client.update.mockRejectedValue(new ApiError(409, "nope"));

    await expect(store.add({ label: "x", url: "ftp://x" })).rejects.toThrow("Enter an http or https address");
    await expect(store.update("notes", { label: "y" })).rejects.toThrow("nope");
    expect(store.items.map((i) => i.id)).toEqual(["notes", "wiki"]);
  });

  it("update replaces the extension with the server's answer", async () => {
    const { store } = setup();
    await flushPromises();
    client.update.mockResolvedValue(ext("notes", { label: "Renamed" }));

    await store.update("notes", { label: "Renamed" });

    expect(client.update).toHaveBeenCalledWith("notes", { label: "Renamed" });
    expect(store.items.find((i) => i.id === "notes")!.label).toBe("Renamed");
  });

  it("remove drops it", async () => {
    const { store } = setup();
    await flushPromises();
    client.remove.mockResolvedValue(undefined);

    await store.remove("notes");

    expect(client.remove).toHaveBeenCalledWith("notes");
    expect(store.items.map((i) => i.id)).toEqual(["wiki"]);
  });

  it("setEnabled shows the change at once and keeps the server's answer", async () => {
    const { store } = setup();
    await flushPromises();
    client.update.mockResolvedValue(ext("notes", { enabled: false, status: "unknown" }));

    const saving = store.setEnabled("notes", false);

    expect(store.items.find((i) => i.id === "notes")!.enabled).toBe(false);
    await saving;
    expect(client.update).toHaveBeenCalledWith("notes", { enabled: false });
    expect(store.items.find((i) => i.id === "notes")!.status).toBe("unknown");
  });

  it("setEnabled puts it back and says why when the save fails", async () => {
    const { store } = setup();
    await flushPromises();
    client.update.mockRejectedValue(new Error("offline"));

    await store.setEnabled("notes", false);

    expect(store.items.find((i) => i.id === "notes")!.enabled).toBe(true);
    expect(store.error).toBe("offline");
  });

  it("forgets everything when the account changes, and ignores a late answer for the old one", async () => {
    let finish!: (list: UserExtension[]) => void;
    client.list.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const { auth, store } = setup();

    client.list.mockResolvedValue([ext("mine")]);
    auth.account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish([ext("old")]);
    await flushPromises();

    expect(store.items.map((i) => i.id)).toEqual(["mine"]);
  });
});
