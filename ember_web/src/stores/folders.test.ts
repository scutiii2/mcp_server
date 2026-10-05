import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { foldersClient, type ChatFolder } from "../api/FoldersClient";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";
import { useFoldersStore } from "./folders";

vi.mock("../api/FoldersClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/FoldersClient")>()),
  foldersClient: { list: vi.fn(), create: vi.fn(), rename: vi.fn(), reorder: vi.fn(), remove: vi.fn() },
}));
// The chat store is only asked to forget a deleted folder's chats here.
vi.mock("./chat", () => ({ useChatStore: vi.fn() }));

const client = vi.mocked(foldersClient);
const forgetFolder = vi.fn();

const ACCOUNT = { id: 1, username: "u", email: "u@example.com", email_verified: true, roles: [], permissions: ["chat.use"] };

const folder = (id: number, position = id, name = `F${id}`): ChatFolder => ({ id, name, position, chat_count: 0 });

function setup(account: typeof ACCOUNT | null = ACCOUNT) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.account = account;
  return { auth, store: useFoldersStore() };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useChatStore).mockReturnValue({ forgetFolder } as unknown as ReturnType<typeof useChatStore>);
  client.list.mockResolvedValue([folder(2), folder(1)]);
});

describe("loading", () => {
  it("does not load until asked", async () => {
    setup();
    await flushPromises();

    expect(client.list).not.toHaveBeenCalled();
  });

  it("loads once and keeps display order (position, then id)", async () => {
    const { store } = setup();

    await Promise.all([store.ensureLoaded(), store.ensureLoaded()]);
    await store.ensureLoaded();

    expect(client.list).toHaveBeenCalledOnce();
    expect(store.folders.map((f) => f.id)).toEqual([1, 2]);
  });

  it("shows the error and tries again on the next ask", async () => {
    client.list.mockRejectedValueOnce(new Error("down"));
    const { store } = setup();

    await store.ensureLoaded();
    expect(store.loadError).toBe("down");
    await store.ensureLoaded();

    expect(store.loadError).toBe("");
    expect(store.folders).toHaveLength(2);
  });

  it("does not load without chat.use", async () => {
    const { store } = setup({ ...ACCOUNT, permissions: [] });

    await store.ensureLoaded();

    expect(client.list).not.toHaveBeenCalled();
  });

  it("drops the folders when the account changes, and ignores a load that was still running", async () => {
    let finish: (list: ChatFolder[]) => void = () => {};
    client.list.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const { auth, store } = setup();
    const loading = store.ensureLoaded();

    auth.account = { ...ACCOUNT, id: 2 };
    await flushPromises();
    finish([folder(9)]);
    await loading;

    expect(store.folders).toEqual([]);
  });
});

describe("changing folders", () => {
  it("create adds the folder in order", async () => {
    const { store } = setup();
    await store.ensureLoaded();
    client.create.mockResolvedValue(folder(3, 0, "New"));

    const made = await store.create("New");

    expect(made.name).toBe("New");
    expect(client.create).toHaveBeenCalledWith("New");
    expect(store.folders.map((f) => f.id)).toEqual([3, 1, 2]);
  });

  it("create passes ember_api's error on", async () => {
    const { store } = setup();
    client.create.mockRejectedValue(new ApiError(409, "A folder with that name already exists"));

    await expect(store.create("Work")).rejects.toThrow("A folder with that name already exists");
    expect(store.folders).toEqual([]);
  });

  it("rename replaces the folder", async () => {
    const { store } = setup();
    await store.ensureLoaded();
    client.rename.mockResolvedValue(folder(1, 1, "Office"));

    await store.rename(1, "Office");

    expect(store.folders.find((f) => f.id === 1)?.name).toBe("Office");
  });

  it("reorder moves the folder", async () => {
    const { store } = setup();
    await store.ensureLoaded();
    client.reorder.mockResolvedValue(folder(1, 10));

    await store.reorder(1, 10);

    expect(store.folders.map((f) => f.id)).toEqual([2, 1]);
  });
});

describe("remove", () => {
  it("drops the folder and tells the chat store to forget its chats", async () => {
    const { store } = setup();
    await store.ensureLoaded();
    client.remove.mockResolvedValue(undefined);

    await store.remove(1);

    expect(store.folders.map((f) => f.id)).toEqual([2]);
    expect(forgetFolder).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("a folder that is already gone (404) is dropped the same way", async () => {
    const { store } = setup();
    await store.ensureLoaded();
    client.remove.mockRejectedValue(new ApiError(404, "Folder not found"));

    await store.remove(1);

    expect(store.folders.map((f) => f.id)).toEqual([2]);
    expect(forgetFolder).toHaveBeenCalledWith(1);
  });

  it("keeps everything and passes the error on when a chat in it is answering (409)", async () => {
    const { store } = setup();
    await store.ensureLoaded();
    client.remove.mockRejectedValue(new ApiError(409, "A chat in this folder is still writing an answer."));

    await expect(store.remove(1)).rejects.toThrow("still writing an answer");

    expect(store.folders.map((f) => f.id)).toEqual([1, 2]);
    expect(forgetFolder).not.toHaveBeenCalled();
  });
});
