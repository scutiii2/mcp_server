# Chat folders and pins: ember_web data layer and row extraction (phases 2 and 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ember_web talks to ember_api's new folder and pin routes (client, store, chat-store actions), and the sidebar's chat row becomes its own component, with no change in what the user sees.

**Architecture:** A `foldersClient` and a lazily loaded `useFoldersStore` (same pattern as `stores/templates.ts`). The chat store keeps owning chats: `Conversation` gains `folderId` and `pinned`, and the store gets `setChatFolder`, `setChatPinned` and `forgetFolder`. Folder deletion in the folders store calls `chat.forgetFolder` so the deleted chats leave the screen. The chat row is split out of `ConversationSidebar.vue` into `ChatRow.vue` with no behavior change. No UI for folders or pins is added in this plan (that is phase 4).

**Tech Stack:** Vue 3 (script setup), TypeScript (`erasableSyntaxOnly`: no enums, no constructor parameter properties), Pinia setup stores, Vitest + jsdom + @vue/test-utils.

**Spec:** `docs/superpowers/specs/2026-10-05-chat-folders-pins-design.md` (the "ember_web" section: Data, and the sidebar split). Backend plan already merged: `docs/superpowers/plans/2026-10-05-chat-folders-pins-api.md`.

## Global Constraints

- ember_api contract (already shipped): `GET/POST /api/chat-folders`, `PATCH/DELETE /api/chat-folders/{id}`; `PATCH /api/chats/{id}` takes `{title?, folder_id?, pinned?}` (`folder_id: null` takes a chat out of its folder); chat rows carry `folder_id` (number or null) and `pinned` (boolean); at most 30 folders; folder name 1 to 60 characters; deleting a folder deletes its chats.
- No hardcoded colors; theme tokens only (`--bg`, `--surface`, `--text`, `--muted`, `--border`, `--accent`, `--danger`).
- Pages live in `src/views/`, reusable pieces in `src/components/`.
- Anything saved in `localStorage` is keyed per account and wrapped in try/catch (this plan adds none).
- Verify from `ember_web/`: `npx vue-tsc -b --noEmit` must print nothing, `npm test` must pass (1087 tests before this work), and `npx vite build` must succeed (then delete `ember_web/dist/`). Do not start browser verification; the user tests by hand.
- Work on branch `feat/chat-folders-web`. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- The new `ChatSummary` fields are optional in TypeScript (`folder_id?`, `pinned?`) so existing test fixtures keep type-checking and an older ember_api still works; code maps them with `?? null` and `?? false`.

Deviation from the spec, on purpose: the spec lists `FolderGroup.vue` in the phase 3 extraction. There is no folder behavior to extract yet, so phase 3 extracts only `ChatRow.vue`; `FolderGroup.vue` is created in phase 4.

## File Structure

- Create `ember_web/src/api/FoldersClient.ts` and `FoldersClient.test.ts`.
- Modify `ember_web/src/api/ChatsClient.ts`: optional fields on `ChatSummary`, `ChatChanges`, `update`.
- Create `ember_web/src/api/ChatsClient.test.ts`.
- Modify `ember_web/src/api/types.ts`: `Conversation.folderId`, `Conversation.pinned`.
- Create `ember_web/src/stores/folders.ts` and `folders.test.ts`.
- Modify `ember_web/src/services/ConversationStorage.ts`: `fromSummary`, `update`.
- Modify `ember_web/src/stores/chat.ts`: `loadList` merge, branch mapping, three new actions.
- Create `ember_web/src/stores/chat.folders.test.ts`.
- Create `ember_web/src/components/ChatRow.vue` and `ChatRow.test.ts`.
- Modify `ember_web/src/components/ConversationSidebar.vue`: use `ChatRow`.

---

### Task 1: Clients and types

**Files:**
- Create: `ember_web/src/api/FoldersClient.ts`, `ember_web/src/api/FoldersClient.test.ts`, `ember_web/src/api/ChatsClient.test.ts`
- Modify: `ember_web/src/api/ChatsClient.ts` (the `ChatSummary` interface at line 5 and the `chatsClient` object at line 77)
- Modify: `ember_web/src/api/types.ts` (`Conversation`, around line 173)

**Interfaces:**
- Produces: `ChatFolder {id: number; name: string; position: number; chat_count: number}`, `FOLDER_NAME_MAX = 60`, `MAX_FOLDERS = 30`, `foldersClient.{list, create, rename, reorder, remove}`; `ChatChanges {title?: string; folder_id?: number | null; pinned?: boolean}`, `chatsClient.update(id, changes)`; `ChatSummary.folder_id?: number | null`, `ChatSummary.pinned?: boolean`; `Conversation.folderId?: number | null`, `Conversation.pinned?: boolean`.

- [ ] **Step 1: Write the failing tests**

Create `ember_web/src/api/FoldersClient.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { foldersClient } from "./FoldersClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("foldersClient", () => {
  it("lists folders", async () => {
    await foldersClient.list();

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/chat-folders");
  });

  it("creates a folder from a name", async () => {
    await foldersClient.create("Work");

    expect(request).toHaveBeenCalledExactlyOnceWith("POST", "/api/chat-folders", { name: "Work" });
  });

  it("renames and reorders with separate PATCH bodies", async () => {
    await foldersClient.rename(3, "Home");
    await foldersClient.reorder(3, 7);

    expect(request.mock.calls).toEqual([
      ["PATCH", "/api/chat-folders/3", { name: "Home" }],
      ["PATCH", "/api/chat-folders/3", { position: 7 }],
    ]);
  });

  it("deletes a folder", async () => {
    await foldersClient.remove(3);

    expect(request).toHaveBeenCalledExactlyOnceWith("DELETE", "/api/chat-folders/3");
  });
});
```

Create `ember_web/src/api/ChatsClient.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient } from "./ChatsClient";
import { apiRequest } from "./http";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("chatsClient.update", () => {
  it("sends only the fields that change", async () => {
    await chatsClient.update("c-1", { pinned: true });

    expect(request).toHaveBeenCalledExactlyOnceWith("PATCH", "/api/chats/c-1", { pinned: true });
  });

  it("sends folder_id null to take a chat out of its folder", async () => {
    await chatsClient.update("c-1", { folder_id: null });

    expect(request).toHaveBeenCalledExactlyOnceWith("PATCH", "/api/chats/c-1", { folder_id: null });
  });

  it("rename keeps sending only the title", async () => {
    await chatsClient.rename("c-1", "New");

    expect(request).toHaveBeenCalledExactlyOnceWith("PATCH", "/api/chats/c-1", { title: "New" });
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run (from `ember_web/`): `npx vitest run src/api/FoldersClient.test.ts src/api/ChatsClient.test.ts`
Expected: FAIL (`FoldersClient` module not found; `update is not a function`).

- [ ] **Step 3: Implement**

Create `ember_web/src/api/FoldersClient.ts`:

```ts
import { apiRequest } from "./http";

/** A chat folder as ember_api lists it (private to the account). */
export interface ChatFolder {
  id: number;
  name: string;
  /** Display order, lowest first; ties are broken by id. */
  position: number;
  chat_count: number;
}

// The limits ember_api enforces (services/folder_service.py).
export const FOLDER_NAME_MAX = 60;
export const MAX_FOLDERS = 30;

const path = (id: number) => `/api/chat-folders/${id}`;

/** ember_api's /api/chat-folders routes (chat.use). */
export const foldersClient = {
  /** In display order. */
  list: () => apiRequest<ChatFolder[]>("GET", "/api/chat-folders"),
  create: (name: string) => apiRequest<ChatFolder>("POST", "/api/chat-folders", { name }),
  rename: (id: number, name: string) => apiRequest<ChatFolder>("PATCH", path(id), { name }),
  reorder: (id: number, position: number) => apiRequest<ChatFolder>("PATCH", path(id), { position }),
  /** Deletes the folder and every chat in it; refused while one of them is answering. */
  remove: (id: number) => apiRequest<void>("DELETE", path(id)),
};
```

In `ember_web/src/api/ChatsClient.ts` add the two optional fields to `ChatSummary` (after `running`):

```ts
  /** The folder it is filed in; absent from an older ember_api. */
  folder_id?: number | null;
  pinned?: boolean;
```

Add before `const path = ...`:

```ts
/** What PATCH /api/chats/{id} can change; send only what changes
 * (`folder_id: null` takes the chat out of its folder). */
export interface ChatChanges {
  title?: string;
  folder_id?: number | null;
  pinned?: boolean;
}
```

Add inside `chatsClient`, after `rename`:

```ts
  update: (id: string, changes: ChatChanges) => apiRequest<ChatSummary>("PATCH", path(id), changes),
```

In `ember_web/src/api/types.ts`, in `interface Conversation` after `running?: boolean;` add:

```ts
  /** The folder it is filed in (ember_api's id), or none. */
  folderId?: number | null;
  /** Shown in the Pinned section, above the folders. */
  pinned?: boolean;
```

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/api && npx vue-tsc -b --noEmit`
Expected: tests pass; vue-tsc prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/api
git commit -m "feat(ember_web): folders client and chat update call"
```

---

### Task 2: Folders store

**Files:**
- Create: `ember_web/src/stores/folders.ts`, `ember_web/src/stores/folders.test.ts`
- Modify: `ember_web/src/stores/chat.ts` (adds `forgetFolder`; Task 3 writes it, so this task calls it through a minimal stub, see Step 3)

**Interfaces:**
- Consumes: `foldersClient`, `ChatFolder` (Task 1); `useAuthStore().hasPermission`, `.account`; `errorMessage` from `../utils/errors`; `ApiError` from `../api/http`.
- Produces: `useFoldersStore()` returning `{folders: Ref<ChatFolder[]>` (display order), `loading`, `loadError`, `ensureLoaded(): Promise<void>`, `reload(): Promise<void>`, `create(name): Promise<ChatFolder>`, `rename(id, name): Promise<ChatFolder>`, `reorder(id, position): Promise<ChatFolder>`, `remove(id): Promise<void>}`. Calls `useChatStore().forgetFolder(id: number)` after a successful remove.

To keep Task 2 independent of Task 3, Step 3 adds a one-line no-op `forgetFolder` to the chat store; Task 3 replaces it with the real implementation.

- [ ] **Step 1: Write the failing tests**

Create `ember_web/src/stores/folders.test.ts`:

```ts
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
```

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run src/stores/folders.test.ts`
Expected: FAIL (`./folders` not found).

- [ ] **Step 3: Implement the store, plus the temporary chat-store stub**

Create `ember_web/src/stores/folders.ts`:

```ts
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { foldersClient, type ChatFolder } from "../api/FoldersClient";
import { ApiError } from "../api/http";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

const byPosition = (a: ChatFolder, b: ChatFolder) => a.position - b.position || a.id - b.id;

/** The account's chat folders. Loaded on first use and dropped when the user
 * changes (same pattern as the templates store). create / rename / reorder /
 * remove throw ember_api's error message so the dialog that called them can
 * show it. Which chat sits in which folder lives on the chat (`folderId`), in
 * the chat store. */
export const useFoldersStore = defineStore("folders", () => {
  const auth = useAuthStore();

  const items = ref<ChatFolder[]>([]);
  const loading = ref(false);
  const loadError = ref("");
  let loaded = false;
  // Bumped on every account change: a load started for the previous account
  // is ignored when it arrives.
  let generation = 0;

  /** In display order. */
  const folders = computed(() => [...items.value].sort(byPosition));

  watch(
    () => (auth.hasPermission("chat.use") ? (auth.account?.id ?? null) : null),
    () => {
      generation += 1;
      items.value = [];
      loaded = false;
      loading.value = false;
      loadError.value = "";
    },
  );

  /** Loads the list once; a failed load can be retried by calling this again. */
  async function ensureLoaded(): Promise<void> {
    if (loaded || loading.value || !auth.hasPermission("chat.use")) return;
    await reload();
  }

  async function reload(): Promise<void> {
    const started = generation;
    loading.value = true;
    loadError.value = "";
    try {
      const list = await foldersClient.list();
      if (started !== generation) return;
      items.value = list;
      loaded = true;
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) loading.value = false;
    }
  }

  function upsert(folder: ChatFolder): void {
    items.value = [...items.value.filter((f) => f.id !== folder.id), folder];
  }

  async function create(name: string): Promise<ChatFolder> {
    const started = generation;
    const folder = await foldersClient.create(name);
    if (started === generation) upsert(folder);
    return folder;
  }

  async function rename(id: number, name: string): Promise<ChatFolder> {
    const started = generation;
    const folder = await foldersClient.rename(id, name);
    if (started === generation) upsert(folder);
    return folder;
  }

  async function reorder(id: number, position: number): Promise<ChatFolder> {
    const started = generation;
    const folder = await foldersClient.reorder(id, position);
    if (started === generation) upsert(folder);
    return folder;
  }

  /** Deletes the folder and, on the server, every chat in it; the chat store
   * then drops those chats from the screen. A folder that is already gone
   * (404, another tab) is treated as deleted. A 409 (a chat in it is
   * answering) leaves everything as it was and throws. */
  async function remove(id: number): Promise<void> {
    const started = generation;
    try {
      await foldersClient.remove(id);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
    if (started !== generation) return;
    items.value = items.value.filter((f) => f.id !== id);
    useChatStore().forgetFolder(id);
  }

  return { folders, loading, loadError, ensureLoaded, reload, create, rename, reorder, remove };
});
```

In `ember_web/src/stores/chat.ts`, add this temporary no-op before the `return {` block and add `forgetFolder,` to the returned object (after `hasChat,`). Task 3 replaces the body:

```ts
  /** Temporary: replaced in the next task. */
  function forgetFolder(_folderId: number): void {}
```

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/stores/folders.test.ts && npx vue-tsc -b --noEmit`
Expected: tests pass; vue-tsc prints nothing. (If `noUnusedParameters` rejects `_folderId`, remove the parameter name from the stub only.)

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/stores/folders.ts ember_web/src/stores/folders.test.ts ember_web/src/stores/chat.ts
git commit -m "feat(ember_web): folders store"
```

---

### Task 3: Chat store knows folders and pins

**Files:**
- Modify: `ember_web/src/services/ConversationStorage.ts` (interface, `fromSummary`, `ServerConversationStorage`)
- Modify: `ember_web/src/stores/chat.ts` (`loadList` merge at about line 316, `branchFrom` push at about line 729, new actions near `renameChat` at about line 939, the returned object)
- Test: `ember_web/src/stores/chat.folders.test.ts`

**Interfaces:**
- Consumes: `chatsClient.update`, `ChatChanges` (Task 1); `Conversation.folderId/pinned` (Task 1).
- Produces: `ConversationStorage.update(id: string, changes: ChatChanges): Promise<void>`; chat store `setChatFolder(id: string, folderId: number | null): void`, `setChatPinned(id: string, pinned: boolean): void`, `forgetFolder(folderId: number): void` (replaces the Task 2 stub).

- [ ] **Step 1: Write the failing tests**

Create `ember_web/src/stores/chat.folders.test.ts`:

```ts
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage } from "../api/types";
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
    update: vi.fn(),
    importChats: vi.fn(),
    append: vi.fn(),
    branch: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({ chimeIfAway: vi.fn() }));

const client = vi.mocked(chatsClient);

const summary = (id: string, extra: Partial<ChatSummary> = {}): ChatSummary => ({
  id,
  title: `Chat ${id}`,
  agent_id: "main",
  message_count: 2,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  running: false,
  ...extra,
});
const TWO: ChatMessage[] = [
  { role: "user", content: "q1" },
  { role: "assistant", content: "a1" },
];

async function setup(list: ChatSummary[]) {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions: ["chat.use"] };
  client.list.mockResolvedValue(list);
  client.get.mockImplementation(async (id: string) => ({ ...summary(id), messages: structuredClone(TWO) }));
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

const row = (chat: ReturnType<typeof useChatStore>, id: string) => chat.sortedConversations.find((c) => c.id === id);

beforeEach(() => {
  vi.clearAllMocks();
  client.search.mockResolvedValue([]);
  client.update.mockResolvedValue(summary("x"));
});

describe("listing", () => {
  it("reads folder and pin from the list, with defaults for an older ember_api", async () => {
    const chat = await setup([summary("a", { folder_id: 4, pinned: true }), summary("b")]);

    expect([row(chat, "a")?.folderId, row(chat, "a")?.pinned]).toEqual([4, true]);
    expect([row(chat, "b")?.folderId, row(chat, "b")?.pinned]).toEqual([null, false]);
  });

  it("a reload brings in a folder change made elsewhere, even for a chat whose messages are loaded", async () => {
    const chat = await setup([summary("a")]);
    await chat.selectChat("a");
    client.list.mockResolvedValue([summary("a", { folder_id: 9, pinned: true })]);

    await chat.reload();

    expect([row(chat, "a")?.folderId, row(chat, "a")?.pinned]).toEqual([9, true]);
    expect(row(chat, "a")?.messages).toHaveLength(2); // messages kept
  });
});

describe("moving and pinning", () => {
  it("setChatFolder changes the screen first, then tells ember_api once", async () => {
    const chat = await setup([summary("a")]);

    chat.setChatFolder("a", 3);
    expect(row(chat, "a")?.folderId).toBe(3);
    await flushPromises();

    expect(client.update).toHaveBeenCalledExactlyOnceWith("a", { folder_id: 3 });
  });

  it("setChatFolder null takes the chat out of its folder", async () => {
    const chat = await setup([summary("a", { folder_id: 3 })]);

    chat.setChatFolder("a", null);
    await flushPromises();

    expect(row(chat, "a")?.folderId).toBeNull();
    expect(client.update).toHaveBeenCalledWith("a", { folder_id: null });
  });

  it("does nothing when the folder is already that one, or the chat is unknown", async () => {
    const chat = await setup([summary("a", { folder_id: 3 })]);

    chat.setChatFolder("a", 3);
    chat.setChatFolder("nope", 3);
    await flushPromises();

    expect(client.update).not.toHaveBeenCalled();
  });

  it("setChatPinned pins and unpins", async () => {
    const chat = await setup([summary("a")]);

    chat.setChatPinned("a", true);
    await flushPromises();
    expect(row(chat, "a")?.pinned).toBe(true);
    chat.setChatPinned("a", false);
    await flushPromises();

    expect(client.update.mock.calls).toEqual([
      ["a", { pinned: true }],
      ["a", { pinned: false }],
    ]);
  });

  it("a 404 from ember_api (chat gone) is not an error", async () => {
    const { ApiError } = await import("../api/http");
    client.update.mockRejectedValue(new ApiError(404, "Chat not found"));
    const chat = await setup([summary("a")]);

    chat.setChatPinned("a", true);
    await flushPromises();

    expect(chat.saveError).toBe("");
  });
});

describe("branching", () => {
  it("a branch lands in the same folder as its source, unpinned", async () => {
    const chat = await setup([summary("a", { folder_id: 3, pinned: true })]);
    await chat.selectChat("a");
    client.branch.mockResolvedValue({
      ...summary("b", { folder_id: 3, pinned: false }),
      messages: structuredClone(TWO),
    });

    await chat.branchFrom(1);

    expect([row(chat, "b")?.folderId, row(chat, "b")?.pinned]).toEqual([3, false]);
  });
});

describe("forgetFolder", () => {
  it("drops that folder's chats from the screen without telling ember_api", async () => {
    const chat = await setup([summary("a", { folder_id: 3 }), summary("b", { folder_id: 3 }), summary("c", { folder_id: 4 }), summary("d")]);

    chat.forgetFolder(3);
    await flushPromises();

    expect(chat.sortedConversations.map((c) => c.id).sort()).toEqual(["c", "d"]);
    expect(client.remove).not.toHaveBeenCalled();
  });

  it("closes the open chat when it was in the folder", async () => {
    const chat = await setup([summary("a", { folder_id: 3 }), summary("d")]);
    await chat.selectChat("a");
    expect(chat.activeId).toBe("a");

    chat.forgetFolder(3);

    expect(chat.activeId).toBeNull();
  });

  it("leaves everything alone when no chat is in it", async () => {
    const chat = await setup([summary("a")]);

    chat.forgetFolder(99);

    expect(chat.sortedConversations).toHaveLength(1);
  });
});
```

The branch test calls `chat.branchFrom(1)`; check the real signature in `chat.ts` (around line 709, `branchFrom(index)` working on the active chat) and the `chatLoading`/`pending` guards, and adapt only the call, not the assertion.

- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run src/stores/chat.folders.test.ts`
Expected: FAIL (`setChatFolder is not a function`, `folderId` undefined).

- [ ] **Step 3: Implement**

In `ember_web/src/services/ConversationStorage.ts`:

1. Import: `import { chatsClient, type ChatChanges, type ChatSummary } from "../api/ChatsClient";`
2. Interface, after `rename`:
```ts
  /** Moves a chat into a folder (null: out of its folder) and/or pins it. */
  update(id: string, changes: ChatChanges): Promise<void>;
```
3. In `ServerConversationStorage`, after `rename`:
```ts
  async update(id: string, changes: ChatChanges): Promise<void> {
    await ignoreMissing(chatsClient.update(id, changes));
  }
```
4. In `fromSummary`, after `running: s.running,` add:
```ts
    folderId: s.folder_id ?? null,
    pinned: s.pinned ?? false,
```

In `ember_web/src/stores/chat.ts`:

1. `loadList` merge: replace the two `known` branches (lines about 319 and 320) with:
```ts
        // Folder and pin come from the server on every reload: changing them is
        // not activity, so `updatedAt` stays the same and the "unchanged" check
        // alone would keep a stale value.
        const filing = { folderId: c.folderId, pinned: c.pinned };
        if (c.id === activeId.value && known) return { ...known, title: c.title, running: known.running, ...filing };
        return unchanged ? { ...known, title: c.title, ...filing } : c;
```
2. `branchFrom` push: add after `running: false,`:
```ts
        folderId: chat.folder_id ?? null,
        pinned: chat.pinned ?? false,
```
3. Replace the Task 2 stub with the three actions, placed right after `renameChat`:
```ts
  /** Files a chat in a folder (null: takes it out). The screen changes first;
   * ember_api is told through the same ordered queue as renames. */
  function setChatFolder(id: string, folderId: number | null): void {
    const conversation = find(id);
    if (!conversation || (conversation.folderId ?? null) === folderId) return;
    conversation.folderId = folderId;
    enqueue(() => storage.update(id, { folder_id: folderId }));
  }

  function setChatPinned(id: string, pinned: boolean): void {
    const conversation = find(id);
    if (!conversation || (conversation.pinned ?? false) === pinned) return;
    conversation.pinned = pinned;
    enqueue(() => storage.update(id, { pinned }));
  }

  /** A folder was deleted on the server, which deleted its chats: drop them
   * from the screen. Nothing is sent to ember_api; it already did it. */
  function forgetFolder(folderId: number): void {
    const doomed = new Set(conversations.value.filter((c) => c.folderId === folderId).map((c) => c.id));
    if (doomed.size === 0) return;
    if (activeId.value !== null && doomed.has(activeId.value)) {
      unfollow();
      jumpIndex.value = null;
      activeId.value = null;
    }
    conversations.value = conversations.value.filter((c) => !doomed.has(c.id));
    searchHits.value = searchHits.value.filter((h) => !doomed.has(h.id));
    for (const id of doomed) clearAllowedTools(id);
  }
```
4. In the returned object add `setChatFolder,` and `setChatPinned,` after `renameChat,` (`forgetFolder` is already there from Task 2).

- [ ] **Step 4: Run the new tests, then the whole chat family**

Run: `npx vitest run src/stores src/services && npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/services ember_web/src/stores
git commit -m "feat(ember_web): chat store files and pins chats, forgets deleted folders"
```

---

### Task 4: Extract `ChatRow.vue` from the sidebar (no behavior change)

**Files:**
- Create: `ember_web/src/components/ChatRow.vue`, `ember_web/src/components/ChatRow.test.ts`
- Modify: `ember_web/src/components/ConversationSidebar.vue` (the `<li v-for="c in conversations">` block at about lines 181 to 238, the script's rename state at lines 48 to 65, and the styles)
- Test: the existing `ember_web/src/components/ConversationSidebar.test.ts` (389 lines) must pass unchanged.

**Interfaces:**
- Produces: `ChatRow` props `{chat: Conversation; active: boolean; locked: boolean; lockedHere: boolean; selecting: boolean; ticked: boolean; renaming: boolean}`; emits `select`, `toggle`, `startRename`, `finishRename(save: boolean, title: string)`, `delete`.
  `locked` is the sidebar-wide "a turn is running" flag (it only adds the `locked` class); `lockedHere` is true for the chat that is answering (its tick box and delete button are disabled).

Behavior to preserve exactly (from the current template): clicking a row selects it, or toggles its tick in select mode, and does nothing while it is being renamed; double-clicking the title or clicking the pencil starts a rename; Enter or blur saves, Esc cancels; the running dot shows in select mode and normal mode; the delete button is disabled for the answering chat; `.row` classes `active`, `locked`, `ticked`.

- [ ] **Step 1: Write the ChatRow tests**

Create `ember_web/src/components/ChatRow.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { Conversation } from "../api/types";
import ChatRow from "./ChatRow.vue";

const chat = (extra: Partial<Conversation> = {}): Conversation => ({
  id: "c1",
  title: "My chat",
  messages: [],
  createdAt: 0,
  updatedAt: 0,
  ...extra,
});

type Props = InstanceType<typeof ChatRow>["$props"];

function mountRow(props: Partial<Props> = {}) {
  return mount(ChatRow, {
    props: { chat: chat(), active: false, locked: false, lockedHere: false, selecting: false, ticked: false, renaming: false, ...props },
  });
}

describe("ChatRow", () => {
  it("shows the title and selects on click", async () => {
    const wrapper = mountRow();

    expect(wrapper.text()).toContain("My chat");
    await wrapper.find("li").trigger("click");

    expect(wrapper.emitted("select")).toHaveLength(1);
    expect(wrapper.emitted("toggle")).toBeUndefined();
  });

  it("toggles instead of selecting while selecting chats", async () => {
    const wrapper = mountRow({ selecting: true });

    await wrapper.find("li").trigger("click");

    expect(wrapper.emitted("toggle")).toHaveLength(1);
    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("does not select while its title is being renamed", async () => {
    const wrapper = mountRow({ renaming: true });

    await wrapper.find("li").trigger("click");

    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("starts a rename from the pencil and from a double click on the title", async () => {
    const wrapper = mountRow();

    await wrapper.find('button[title="Rename chat"]').trigger("click");
    await wrapper.find(".title").trigger("dblclick");

    expect(wrapper.emitted("startRename")).toHaveLength(2);
    expect(wrapper.emitted("select")).toBeUndefined(); // the pencil does not also select
  });

  it("edits the title: Enter saves, once, even if blur follows", async () => {
    const wrapper = mountRow({ renaming: true });
    const input = wrapper.find("input.rename");
    expect((input.element as HTMLInputElement).value).toBe("My chat");

    await input.setValue("Renamed");
    await input.trigger("keydown", { key: "Enter" });
    await input.trigger("blur");

    expect(wrapper.emitted("finishRename")).toEqual([[true, "Renamed"]]);
  });

  it("Esc cancels the edit", async () => {
    const wrapper = mountRow({ renaming: true });
    const input = wrapper.find("input.rename");

    await input.setValue("Renamed");
    await input.trigger("keydown", { key: "Escape" });

    expect(wrapper.emitted("finishRename")).toEqual([[false, "Renamed"]]);
  });

  it("deleting emits delete; the answering chat cannot be deleted", async () => {
    const free = mountRow();
    await free.find("button.delete").trigger("click");
    expect(free.emitted("delete")).toHaveLength(1);
    expect(free.emitted("select")).toBeUndefined();

    const answering = mountRow({ lockedHere: true });
    expect(answering.find("button.delete").attributes("disabled")).toBeDefined();
  });

  it("shows the running dot and the tick box state while selecting; the answering chat's box is disabled", () => {
    const wrapper = mountRow({ chat: chat({ running: true }), selecting: true, ticked: true, lockedHere: true });

    expect(wrapper.find(".running").exists()).toBe(true);
    const tick = wrapper.find("input.tick");
    expect((tick.element as HTMLInputElement).checked).toBe(true);
    expect(tick.attributes("disabled")).toBeDefined();
  });

  it("clicking the tick box toggles once, without also counting as a row click", async () => {
    const wrapper = mountRow({ selecting: true });

    await wrapper.find("input.tick").trigger("click");

    expect(wrapper.emitted("toggle")).toHaveLength(1);
  });

  it("carries the active, locked and ticked classes", () => {
    const wrapper = mountRow({ active: true, locked: true, selecting: true, ticked: true });

    expect(wrapper.find("li").classes()).toEqual(expect.arrayContaining(["row", "active", "locked", "ticked"]));
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run src/components/ChatRow.test.ts`
Expected: FAIL (`./ChatRow.vue` not found).

- [ ] **Step 3: Create `ChatRow.vue`**

Create `ember_web/src/components/ChatRow.vue`:

```vue
<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { Conversation } from "../api/types";

// One row of the chat list. The sidebar owns which row is being renamed and
// which are ticked; this row owns only the text being typed.
// locked: a turn is running somewhere (every row gets the `locked` class).
// lockedHere: this chat is the one answering, so it can't be ticked or deleted.
const props = defineProps<{
  chat: Conversation;
  active: boolean;
  locked: boolean;
  lockedHere: boolean;
  selecting: boolean;
  ticked: boolean;
  renaming: boolean;
}>();
const emit = defineEmits<{
  select: [];
  toggle: [];
  startRename: [];
  finishRename: [save: boolean, title: string];
  delete: [];
}>();

const draft = ref("");
const renameInput = ref<HTMLInputElement | null>(null);
// Enter, then the blur that follows when the input goes away, must save once.
let finished = false;

watch(
  () => props.renaming,
  async (renaming) => {
    if (!renaming) return;
    finished = false;
    draft.value = props.chat.title;
    await nextTick();
    renameInput.value?.select();
  },
  { immediate: true },
);

function finish(save: boolean): void {
  if (!props.renaming || finished) return;
  finished = true;
  emit("finishRename", save, draft.value);
}

function onClick(): void {
  if (props.selecting) emit("toggle");
  else if (!props.renaming) emit("select");
}
</script>

<template>
  <li
    :class="['row', { active, locked, ticked: selecting && ticked }]"
    :title="chat.title"
    @click="onClick"
  >
    <template v-if="selecting">
      <input
        type="checkbox"
        class="tick"
        :checked="ticked"
        :disabled="lockedHere"
        :aria-label="`Select ${chat.title}`"
        @click.stop="emit('toggle')"
      />
      <span v-if="chat.running" class="running" title="An answer is being written" />
      <span class="title">{{ chat.title }}</span>
    </template>
    <input
      v-else-if="renaming"
      ref="renameInput"
      v-model="draft"
      class="rename"
      aria-label="Chat title"
      maxlength="120"
      @click.stop
      @keydown.enter.prevent="finish(true)"
      @keydown.esc.prevent="finish(false)"
      @blur="finish(true)"
    />
    <template v-else>
      <span v-if="chat.running" class="running" title="An answer is being written" />
      <span class="title" @dblclick.stop="emit('startRename')">{{ chat.title }}</span>
      <button type="button" class="icon" title="Rename chat" @click.stop="emit('startRename')">
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <path
            d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linejoin="round"
          />
        </svg>
      </button>
      <button
        type="button"
        class="icon delete"
        title="Delete chat"
        :disabled="lockedHere"
        @click.stop="emit('delete')"
      >
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
        </svg>
      </button>
    </template>
  </li>
</template>

<style scoped>
/* The row's own box (.row and its active / locked / ticked states) is styled by
 * the sidebar: a component's root element takes its parent's scoped styles too. */
.title {
  flex: 1;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
/* Shown on hover (or always on touch screens, which have no hover). */
.icon {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
  opacity: 0;
}
.row:hover .icon,
.icon:focus-visible {
  opacity: 1;
}
@media (hover: none) {
  .icon {
    opacity: 1;
  }
}
.icon:hover:not(:disabled) {
  color: var(--text);
}
.delete:hover:not(:disabled) {
  color: var(--danger);
}
.icon:disabled {
  cursor: default;
  opacity: 0;
}
.running {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
.rename {
  flex: 1;
  min-width: 0;
  padding: 2px 6px;
  border: 1px solid var(--accent);
  border-radius: 6px;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.tick {
  flex-shrink: 0;
  margin: 0 2px 0 0;
  cursor: pointer;
}
</style>
```

- [ ] **Step 4: Use it in the sidebar**

In `ember_web/src/components/ConversationSidebar.vue`:

1. Script: add `import ChatRow from "./ChatRow.vue";` and remove `nextTick` from the vue import only if it is no longer used. Replace the rename block (the `renamingId`, `draft`, `renameInput`, `startRename`, `finishRename` code at lines 48 to 65) with:
```ts
// The row being renamed (its draft text lives in the row).
const renamingId = ref<string | null>(null);

function finishRename(id: string, save: boolean, title: string): void {
  if (renamingId.value !== id) return;
  renamingId.value = null;
  if (save) emit("rename", id, title);
}
```
Keep `startSelecting`'s `renamingId.value = null;` line as it is. `isLocked`, `toggle`, `confirmDelete`, selecting state and everything else stay.

2. Template: replace the whole `<li v-for="c in conversations" ...> ... </li>` block inside `<ul v-else class="list">` with:
```vue
      <ChatRow
        v-for="c in conversations"
        :key="c.id"
        :chat="c"
        :active="c.id === activeId"
        :locked="locked"
        :locked-here="isLocked(c)"
        :selecting="selecting"
        :ticked="ticked.has(c.id)"
        :renaming="renamingId === c.id"
        @select="emit('select', c.id)"
        @toggle="toggle(c)"
        @start-rename="renamingId = c.id"
        @finish-rename="(save, title) => finishRename(c.id, save, title)"
        @delete="confirmDelete(c)"
      />
```
Note `isLocked(c)` is `props.locked && c.id === props.activeId`, the same condition the old template used for the tick box (`isLocked(c)`) and the delete button (`locked && c.id === activeId`).

3. Styles: remove from the sidebar `<style scoped>` the rules that moved into `ChatRow.vue`: `.icon`, `.row:hover .icon, .icon:focus-visible`, the `@media (hover: none) .icon` block, `.icon:hover:not(:disabled)`, `.delete:hover:not(:disabled)`, `.icon:disabled`, `.running`, `@keyframes pulse`, `.rename`, `.tick`. Keep in the sidebar: `.row`, `.row:hover`, `.row.active`, `.row.locked:not(.active)`, `.row.ticked`, `.title` (search-hit rows still use it), the `.hit*`, `.snippet`, `.count`, `mark`, `.list`, footer and select-bar rules. If `.delete-all:hover` shares a selector with `.delete:hover`, leave `.delete-all` alone.

- [ ] **Step 5: Run the sidebar tests, then everything**

Run: `npx vitest run src/components/ConversationSidebar.test.ts src/components/ChatRow.test.ts`
Expected: all pass, with ConversationSidebar.test.ts unchanged. If a sidebar test fails, fix `ChatRow.vue` or the sidebar wiring, never the sidebar test (it defines the behavior to preserve). A test that looks for `li.row` still works because `ChatRow`'s root is the `<li class="row">`.

Then: `npm test && npx vue-tsc -b --noEmit && npx vite build`, then delete `ember_web/dist/`.
Expected: 1087 plus the new tests pass; vue-tsc prints nothing; the build succeeds.

- [ ] **Step 6: Commit**

```bash
git add ember_web/src/components
git commit -m "refactor(ember_web): extract ChatRow from the conversation sidebar"
```

---

### Task 5: Final check and manual checklist

**Files:** none (verification only; update `ember_web/README.md` only if it already lists the stores or API clients, in which case add one line each for `stores/folders.ts` and `api/FoldersClient.ts`).

- [ ] **Step 1: Full verification from `ember_web/`**

Run: `npm test`, `npx vue-tsc -b --noEmit`, `npx vite build` (then delete `dist/`).
Expected: all green.

- [ ] **Step 2: Report**

Report what changed and the results. Give the user this short manual checklist (no UI for folders exists yet, so it only proves nothing broke): open Ember, the chat list looks and behaves as before; rename a chat by double-click, by the pencil, with Enter, with Esc, and by clicking away; delete one chat; use Select, tick two, and delete them; search and open a result; a chat that is answering cannot be deleted. Then say that phase 4 (pinned section, folder groups, Move menu, dialogs) is next and needs its own plan.

---

## Self-review

**Spec coverage (ember_web Data section and phase 3):** `FoldersClient` and `ChatsClient` additions (Task 1); `Conversation` fields (Task 1); folders store with per-account reset (Task 2); chat store actions with a locked-chat rule left to the UI (Task 3); `ChatRow` split with no behavior change and the existing 1087 tests as the guard (Task 4). Not in this plan, by design: collapsed-folder `localStorage` state, the Pinned and folder sections, `FolderGroup`, `MoveToMenu`, the new/rename folder dialog (phase 4); drag and drop (phase 5); `e2e/fakeApi.ts` (no page calls `/api/chat-folders` until phase 4, which then adds it).

**Spec difference:** `FolderGroup.vue` moves from phase 3 to phase 4 (stated under Global Constraints).

**Placeholders:** none. Task 3 Step 1 tells the implementer to check the real `branchFrom` call shape and adapt only the call; that is a lookup, not a gap.

**Type consistency:** `ChatFolder`, `foldersClient.*`, `ChatChanges`, `chatsClient.update`, `Conversation.folderId/pinned`, `setChatFolder`, `setChatPinned`, `forgetFolder`, and the `ChatRow` props and emits use the same names in every task.

## Carry into the phase 4 plan (from the final review of this plan's work)

- `ember_web/e2e/fakeApi.ts` needs `GET/POST/PATCH/DELETE /api/chat-folders` and `PATCH /api/chats/{id}` handling before the sidebar UI calls them (the Playwright test fails on any call the fake does not know).
- `forgetFolder` does not invalidate a `loadList` that started before the folder delete; its late result can bring the deleted chats back. Add a list sequence counter that `forgetFolder` bumps, or filter forgotten folder ids until a newer list arrives.
- Derive folder chat counts from the chat store; `ChatFolder.chat_count` goes stale after `setChatFolder` and `forgetFolder`.
- Treat an undefined `folderId` like null (unfiled): chats created locally by `send` have neither field until the next reload.
- `ensureLoaded` in the folders store returns at once while a load is running, so `await ensureLoaded()` does not wait for it; store the in-flight promise and return it. This also closes the create-during-initial-load race.
- Spec text drift: the spec says `folderId?: string | null` and names `setFolder`/`setPinned`; the code uses `number | null` and `setChatFolder`/`setChatPinned`.
- The folders-store test "create passes ember_api's error on" should call `ensureLoaded()` first so its `folders` assertion proves something.
