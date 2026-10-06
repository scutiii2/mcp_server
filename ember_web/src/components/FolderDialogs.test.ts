import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { foldersClient, type ChatFolder } from "../api/FoldersClient";
import { useAuthStore } from "../stores/auth";
import FolderDialogs from "./FolderDialogs.vue";

vi.mock("../api/FoldersClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/FoldersClient")>()),
  foldersClient: { list: vi.fn(), create: vi.fn(), rename: vi.fn(), reorder: vi.fn(), remove: vi.fn() },
}));
const forgetFolder = vi.fn();
vi.mock("../stores/chat", () => ({ useChatStore: () => ({ forgetFolder }) }));

const client = vi.mocked(foldersClient);
const folder = (id: number, name = `F${id}`): ChatFolder => ({ id, name, position: id, chat_count: 0 });

type Exposed = { openCreate: (cb?: (f: ChatFolder) => void) => void; openRename: (f: ChatFolder) => void; openDelete: (f: ChatFolder, n: number) => void };
let wrapper: VueWrapper | null = null;

function setup() {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "u", email: "u@example.com", email_verified: true, roles: [], permissions: ["chat.use"] };
  wrapper = mount(FolderDialogs, { attachTo: document.body });
  return wrapper.vm as unknown as Exposed;
}

const realShowModal = HTMLDialogElement.prototype.showModal;
const realClose = HTMLDialogElement.prototype.close;

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom does not implement <dialog>.showModal; give it the open flag the component reads.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
afterEach(() => {
  HTMLDialogElement.prototype.showModal = realShowModal;
  HTMLDialogElement.prototype.close = realClose;
  wrapper?.unmount();
  wrapper = null;
});

const dialog = () => document.body.querySelector<HTMLDialogElement>("dialog[open]");
const input = () => dialog()!.querySelector<HTMLInputElement>("input[type=text]")!;
const button = (text: string) => [...dialog()!.querySelectorAll("button")].find((b) => b.textContent?.trim() === text)!;

describe("create", () => {
  it("opens an empty name form and saves the trimmed name", async () => {
    client.create.mockResolvedValue(folder(1, "Work"));
    const dialogs = setup();

    dialogs.openCreate();
    await flushPromises();
    expect(dialog()?.getAttribute("aria-label")).toBe("New folder");
    expect(input().value).toBe("");
    expect(document.activeElement).toBe(input());
    expect(button("Save").hasAttribute("disabled")).toBe(true); // blank

    input().value = "  Work ";
    input().dispatchEvent(new Event("input"));
    await flushPromises();
    button("Save").click();
    await flushPromises();

    expect(client.create).toHaveBeenCalledWith("Work");
    expect(dialog()).toBeNull(); // closed
  });

  it("tells the caller which folder was made", async () => {
    client.create.mockResolvedValue(folder(7, "New"));
    const onCreated = vi.fn();
    const dialogs = setup();

    dialogs.openCreate(onCreated);
    await flushPromises();
    input().value = "New";
    input().dispatchEvent(new Event("input"));
    await flushPromises();
    button("Save").click();
    await flushPromises();

    expect(onCreated).toHaveBeenCalledWith(folder(7, "New"));
  });

  it("shows the server's error and stays open", async () => {
    client.create.mockRejectedValue(new ApiError(409, "A folder with that name already exists"));
    const dialogs = setup();

    dialogs.openCreate();
    await flushPromises();
    input().value = "Work";
    input().dispatchEvent(new Event("input"));
    await flushPromises();
    button("Save").click();
    await flushPromises();

    expect(dialog()?.querySelector('[role="alert"]')?.textContent).toContain("already exists");
  });

  it("limits the name length", async () => {
    const dialogs = setup();

    dialogs.openCreate();
    await flushPromises();

    expect(input().getAttribute("maxlength")).toBe("60");
  });
});

describe("busy and reopen", () => {
  it("ignores Esc and double submit while saving, then reopens clean after a failure", async () => {
    let reject!: (e: unknown) => void;
    client.create.mockReturnValueOnce(new Promise((_, r) => (reject = r)));
    const dialogs = setup();

    dialogs.openCreate();
    await flushPromises();
    input().value = "Work";
    input().dispatchEvent(new Event("input"));
    await flushPromises();
    button("Save").click();
    await flushPromises();
    expect(button("Saving …").hasAttribute("disabled")).toBe(true);
    button("Saving …").click(); // disabled while busy
    dialog()!.dispatchEvent(new Event("cancel", { cancelable: true })); // Esc
    await flushPromises();
    expect(client.create).toHaveBeenCalledTimes(1);
    expect(dialog()).not.toBeNull();

    reject(new ApiError(409, "A folder with that name already exists"));
    await flushPromises();
    expect(dialog()?.querySelector('[role="alert"]')).not.toBeNull();

    button("Cancel").click();
    await flushPromises();
    dialogs.openCreate();
    await flushPromises();
    expect(dialog()?.querySelector('[role="alert"]')).toBeNull();
    expect(input().value).toBe("");
    expect(button("Save").textContent?.trim()).toBe("Save");
  });
});

describe("rename", () => {
  it("starts with the current name and saves the new one", async () => {
    client.rename.mockResolvedValue(folder(1, "Office"));
    const dialogs = setup();

    dialogs.openRename(folder(1, "Work"));
    await flushPromises();
    expect(dialog()?.getAttribute("aria-label")).toBe("Rename folder");
    expect(input().value).toBe("Work");

    input().value = "Office";
    input().dispatchEvent(new Event("input"));
    await flushPromises();
    button("Save").click();
    await flushPromises();

    expect(client.rename).toHaveBeenCalledWith(1, "Office");
    expect(dialog()).toBeNull();
  });

  it("does not call the server when the name did not change", async () => {
    const dialogs = setup();

    dialogs.openRename(folder(1, "Work"));
    await flushPromises();
    button("Save").click();
    await flushPromises();

    expect(client.rename).not.toHaveBeenCalled();
    expect(dialog()).toBeNull();
  });
});

describe("delete", () => {
  it("names the folder and counts the chats, in the singular and the plural", async () => {
    const dialogs = setup();

    dialogs.openDelete(folder(1, "Work"), 12);
    await flushPromises();
    expect(dialog()?.textContent).toContain(`Delete folder "Work" and its 12 chats? This can't be undone.`);
    wrapper!.unmount();

    const again = setup();
    again.openDelete(folder(1, "Work"), 1);
    await flushPromises();
    expect(dialog()?.textContent).toContain(`Delete folder "Work" and its 1 chat? This can't be undone.`);
  });

  it("deletes, tells the chat store, and closes", async () => {
    client.remove.mockResolvedValue(undefined);
    const dialogs = setup();

    dialogs.openDelete(folder(1, "Work"), 2);
    await flushPromises();
    button("Delete").click();
    await flushPromises();

    expect(client.remove).toHaveBeenCalledWith(1);
    expect(forgetFolder).toHaveBeenCalledWith(1);
    expect(dialog()).toBeNull();
  });

  it("shows a refusal (a chat is answering) inside the dialog and keeps everything", async () => {
    client.remove.mockRejectedValue(new ApiError(409, "A chat in this folder is still writing an answer. Wait for it to finish."));
    const dialogs = setup();

    dialogs.openDelete(folder(1, "Work"), 2);
    await flushPromises();
    button("Delete").click();
    await flushPromises();

    expect(dialog()?.querySelector('[role="alert"]')?.textContent).toContain("still writing an answer");
    expect(forgetFolder).not.toHaveBeenCalled();
  });

  it("Cancel closes without deleting", async () => {
    const dialogs = setup();

    dialogs.openDelete(folder(1, "Work"), 2);
    await flushPromises();
    button("Cancel").click();
    await flushPromises();

    expect(client.remove).not.toHaveBeenCalled();
    expect(dialog()).toBeNull();
  });
});

async function type(value: string) {
  input().value = value;
  input().dispatchEvent(new Event("input"));
  await flushPromises();
}

describe("details", () => {
  it("collapses inner whitespace before creating", async () => {
    client.create.mockResolvedValue(folder(1, "Work stuff"));
    const dialogs = setup();
    dialogs.openCreate();
    await flushPromises();
    await type("  Work   stuff ");
    button("Save").click();
    await flushPromises();
    expect(client.create).toHaveBeenCalledWith("Work stuff");
  });

  it("does not call the server when only inner whitespace differs", async () => {
    const dialogs = setup();
    dialogs.openRename(folder(1, "Work stuff"));
    await flushPromises();
    await type("Work  stuff");
    button("Save").click();
    await flushPromises();
    expect(client.rename).not.toHaveBeenCalled();
    expect(dialog()).toBeNull();
  });

  it("keeps the delete dialog open and enables Delete again after a 409", async () => {
    client.remove.mockRejectedValue(new ApiError(409, "still writing"));
    const dialogs = setup();
    dialogs.openDelete(folder(1, "Work"), 2);
    await flushPromises();
    button("Delete").click();
    await flushPromises();
    expect(dialog()).not.toBeNull();
    expect(button("Delete").hasAttribute("disabled")).toBe(false);
  });

  it("just closes when the server says the folder is already gone", async () => {
    client.remove.mockRejectedValue(new ApiError(404, "Folder not found"));
    const dialogs = setup();
    dialogs.openDelete(folder(1, "Work"), 2);
    await flushPromises();
    button("Delete").click();
    await flushPromises();
    expect(dialog()).toBeNull();
  });

  it("does not call onCreated when create fails", async () => {
    client.create.mockRejectedValue(new ApiError(409, "exists"));
    const onCreated = vi.fn();
    const dialogs = setup();
    dialogs.openCreate(onCreated);
    await flushPromises();
    await type("Work");
    button("Save").click();
    await flushPromises();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("calls onCreated after the dialog closed, and survives it throwing", async () => {
    client.create.mockResolvedValue(folder(1, "Work"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    let openAtCall: boolean | null = null;
    const dialogs = setup();
    dialogs.openCreate(() => {
      openAtCall = dialog() !== null;
      throw new Error("boom");
    });
    await flushPromises();
    await type("Work");
    button("Save").click();
    await flushPromises();
    expect(openAtCall).toBe(false);
    expect(dialog()).toBeNull();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe("a save that outlives its dialog", () => {
  async function startSave() {
    let settle!: { resolve: (f: ChatFolder) => void; reject: (e: unknown) => void };
    client.create.mockReturnValueOnce(new Promise<ChatFolder>((resolve, reject) => (settle = { resolve, reject })));
    const onCreated = vi.fn();
    const dialogs = setup();
    dialogs.openCreate(onCreated);
    await flushPromises();
    await type("Work");
    button("Save").click();
    await flushPromises();
    dialogs.openRename(folder(2, "Other"));
    await flushPromises();
    return { settle, dialogs, onCreated };
  }

  it("does not close the new dialog when the old save succeeds", async () => {
    const { settle, onCreated } = await startSave();
    settle.resolve(folder(9, "Work"));
    await flushPromises();
    expect(dialog()?.getAttribute("aria-label")).toBe("Rename folder");
    expect(input().value).toBe("Other");
    expect(onCreated).toHaveBeenCalledWith(folder(9, "Work"));
  });

  it("does not show the old save's error in the new dialog or clear its busy flag", async () => {
    const { settle } = await startSave();
    // make the new dialog busy so a stray `finally` would be visible
    let settleRename!: (f: ChatFolder) => void;
    client.rename.mockReturnValueOnce(new Promise<ChatFolder>((r) => (settleRename = r)));
    await type("Another");
    button("Save").click();
    await flushPromises();
    expect(button("Saving …").hasAttribute("disabled")).toBe(true);

    settle.reject(new ApiError(409, "A folder with that name already exists"));
    await flushPromises();
    expect(dialog()?.querySelector('[role="alert"]')).toBeNull();
    expect(button("Saving …").hasAttribute("disabled")).toBe(true); // still busy with its own save
    settleRename(folder(2, "Another"));
    await flushPromises();
    expect(dialog()).toBeNull();
  });
});