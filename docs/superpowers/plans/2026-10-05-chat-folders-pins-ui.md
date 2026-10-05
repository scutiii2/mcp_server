# Chat folders and pins: sidebar UI (phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Ember sidebar shows a Pinned section, folder groups and an Unfiled section; each chat has a "..." menu (Pin, Move to..., Rename, Delete); folders can be created, renamed and deleted.

**Architecture:** Pure helpers build the section layout and the menu items. A generic `PopupMenu` (teleported to the page body) renders menus with a flyout. `ChatSection` renders a section header plus rows. `ConversationSidebar` stays presentational (props and emits only); `ChatView` wires it to the chat and folders stores, and a `FolderDialogs` component owns the create, rename and delete dialogs. Two store carry-overs are fixed first.

**Tech Stack:** Vue 3 (script setup), TypeScript (`erasableSyntaxOnly`), Pinia, Vitest + jsdom + @vue/test-utils, Playwright (one e2e spec, a fake API).

**Spec:** `docs/superpowers/specs/2026-10-05-chat-folders-pins-design.md`, section "Phase 4 design (approved 2026-10-05): sidebar UI" (it wins over the earlier sidebar text). Earlier plan with the carry-over list: `docs/superpowers/plans/2026-10-05-chat-folders-pins-web-data.md`.

## Global Constraints

- Layout: Pinned, then folders in creation order, then Unfiled (headed "Chats"). Pinned and Unfiled hidden when empty; **folders always shown, even empty**; with no pins and no folders the list is flat with no headers (unchanged look).
- A chat with `folderId` null, undefined, or not among the loaded folders is Unfiled. Pinned chats appear only in Pinned.
- Row menu items, in order: Pin or Unpin; Move to... (flyout: "No folder", each folder with a check mark on the current one, then "New folder..."); Rename; Delete. Chat delete keeps the browser `confirm()` text `Delete "<title>"? This can't be undone.`
- A chat that is answering (`running && it is the active chat while locked`, i.e. the sidebar's existing `isLocked(c)`): Move to... and Delete disabled; Pin and Rename stay available.
- At 30 folders (`MAX_FOLDERS`) "New folder" is disabled in the footer and in the flyout.
- Folder delete dialog text: `Delete folder "<name>" and its <n> chat(s)? This can't be undone.` (`chat` when n is 1, `chats` otherwise); a server error (409: a chat in it is answering) is shown inside the dialog and nothing is removed.
- Menu: `Teleport` to `body`; Esc closes (flyout first, then menu); ArrowUp/Down/Home/End move; Enter/Space activate; ArrowRight opens a flyout, ArrowLeft closes it; focus returns to the opening button after Esc or an outside click, but not after choosing an item.
- Collapsed folder ids are saved per account in `localStorage`, key `ember_web.collapsedFolders.<accountId>`, wrapped in try/catch.
- Search results still replace the whole list, flat. Select mode and "Delete all chats" work across all sections.
- Theme tokens only (`--bg`, `--surface`, `--text`, `--muted`, `--border`, `--accent`, `--danger`); no hardcoded colors. tsconfig `erasableSyntaxOnly`.
- Reuse `BaseModal` for every dialog. Pages stay in `src/views/`, reusable pieces in `src/components/`.
- Verify from `ember_web/`: `npx vue-tsc -b --noEmit` prints nothing; `npm test` passes (1129 tests before this work); `npx vite build` succeeds (then delete `dist/`). Do not run a dev server or browser by hand; the user tests manually. `npm run test:e2e` is run only in Task 7.
- Work on branch `feat/chat-folders-ui`. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

Deviation from the spec text, recorded in the spec's phase 4 section: `ChatSection.vue` replaces `FolderGroup.vue`; dialogs live in `FolderDialogs.vue`.

## File Structure

- Modify `ember_web/src/stores/folders.ts` (+ `folders.test.ts`): `ensureLoaded` returns the in-flight promise.
- Modify `ember_web/src/stores/chat.ts` (+ `chat.folders.test.ts`): list-sequence guard bumped by `forgetFolder`.
- Create `ember_web/src/utils/chatSections.ts` (+ test), `ember_web/src/utils/chatMenu.ts` (+ test).
- Create `ember_web/src/composables/useFolderCollapse.ts` (+ test).
- Create `ember_web/src/components/PopupMenu.vue` (+ test).
- Create `ember_web/src/components/ChatSection.vue` (+ test).
- Modify `ember_web/src/components/ChatRow.vue` (+ `ChatRow.test.ts`): "..." button and context menu.
- Modify `ember_web/src/components/ConversationSidebar.vue` (+ `ConversationSidebar.test.ts`): sections, menus, footer button.
- Create `ember_web/src/components/FolderDialogs.vue` (+ test).
- Modify `ember_web/src/views/ChatView.vue`: wiring.
- Modify `ember_web/e2e/fakeApi.ts`, `ember_web/e2e/chat.spec.ts`.

---

### Task 1: Store carry-overs

**Files:**
- Modify: `ember_web/src/stores/folders.ts` (`ensureLoaded`, the watcher)
- Modify: `ember_web/src/stores/chat.ts` (`loadList`, `forgetFolder`)
- Test: `ember_web/src/stores/folders.test.ts`, `ember_web/src/stores/chat.folders.test.ts`

**Interfaces:**
- Produces: `useFoldersStore().ensureLoaded(): Promise<void>` that resolves only after a load already in flight has finished; `useChatStore().forgetFolder(folderId)` additionally makes any `loadList` that started before it discard its result.

- [ ] **Step 1: Write the failing tests**

In `ember_web/src/stores/folders.test.ts`, inside `describe("loading", ...)` add:

```ts
  it("a second ask waits for the load already running", async () => {
    let finish: (list: ChatFolder[]) => void = () => {};
    client.list.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const { store } = setup();

    const first = store.ensureLoaded();
    let secondDone = false;
    const second = store.ensureLoaded().then(() => (secondDone = true));
    await flushPromises();
    expect(secondDone).toBe(false);

    finish([folder(1)]);
    await Promise.all([first, second]);

    expect(client.list).toHaveBeenCalledOnce();
    expect(store.folders.map((f) => f.id)).toEqual([1]);
  });
```

Also change the existing test `create passes ember_api's error on` so its last assertion proves something: add `await store.ensureLoaded();` as the first line after `setup()` and change the final assertion to `expect(store.folders.map((f) => f.id)).toEqual([1, 2]);`.

In `ember_web/src/stores/chat.folders.test.ts`, inside `describe("forgetFolder", ...)` add:

```ts
  it("a list that was requested before the folder was deleted cannot bring its chats back", async () => {
    const chat = await setup([summary("a", { folder_id: 3 }), summary("d")]);
    let finish: (list: ChatSummary[]) => void = () => {};
    client.list.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));

    const reloading = chat.reload();
    chat.forgetFolder(3);
    finish([summary("a", { folder_id: 3 }), summary("d")]); // what the server said before it deleted the folder
    await reloading;

    expect(chat.sortedConversations.map((c) => c.id)).toEqual(["d"]);
  });
```

- [ ] **Step 2: Run them to see them fail**

Run (from `ember_web/`): `npx vitest run src/stores/folders.test.ts src/stores/chat.folders.test.ts`
Expected: the two new tests FAIL (second ask returned at once; chat "a" came back). The edited `create passes ember_api's error on` passes.

- [ ] **Step 3: Implement**

In `ember_web/src/stores/folders.ts` replace the `ensureLoaded` function and add the in-flight variable and reset:

```ts
  // The load in progress, so a second ask waits for it instead of returning early.
  let inflight: Promise<void> | null = null;
```
(next to `let loaded = false;`), in the `watch` callback add `inflight = null;`, and:

```ts
  /** Loads the list once; a failed load can be retried by calling this again.
   * Asked while a load is running, it waits for that load. */
  function ensureLoaded(): Promise<void> {
    if (loaded || !auth.hasPermission("chat.use")) return Promise.resolve();
    if (inflight) return inflight;
    const started = generation;
    const run = reload().finally(() => {
      if (inflight === run && started === generation) inflight = null;
    });
    inflight = run;
    return run;
  }
```

In `ember_web/src/stores/chat.ts`: add `let listSeq = 0;` near the other `let` counters used by `loadList` (next to `generation`); in `loadList` capture `const seq = listSeq;` right after `const started = generation;` and change the guard after `await storage.list()` to `if (started !== generation || seq !== listSeq) return;`; in `forgetFolder` add `listSeq += 1;` as its first statement (before the `doomed` computation, so a delete that finds no chats loaded still invalidates an in-flight list).

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/stores && npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/stores
git commit -m "fix(ember_web): ensureLoaded waits for a running load; a folder delete outranks an older chat list"
```

---

### Task 2: Layout and menu helpers, collapse composable

**Files:**
- Create: `ember_web/src/utils/chatSections.ts`, `ember_web/src/utils/chatSections.test.ts`
- Create: `ember_web/src/utils/chatMenu.ts`, `ember_web/src/utils/chatMenu.test.ts`
- Create: `ember_web/src/composables/useFolderCollapse.ts`, `ember_web/src/composables/useFolderCollapse.test.ts`

**Interfaces:**
- Produces: `ChatSection {kind: "pinned" | "folder" | "unfiled"; key: string; folder: ChatFolder | null; chats: Conversation[]}`, `ChatLayout {grouped: boolean; sections: ChatSection[]}`, `buildLayout(chats, folders): ChatLayout`.
- Produces: `MenuItem {id: string; label: string; checked?: boolean; danger?: boolean; disabled?: boolean; separator?: boolean; children?: MenuItem[]}`, `chatMenuItems(chat, folders, answering): MenuItem[]`, `folderMenuItems(): MenuItem[]`, `ChatChoice` and `parseChatChoice(id): ChatChoice | null`.
- Produces: `useFolderCollapse(): {collapsed: Ref<number[]>; isCollapsed(id: number): boolean; toggle(id: number): void}`.

- [ ] **Step 1: Write the failing tests**

Create `ember_web/src/utils/chatSections.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";
import { buildLayout } from "./chatSections";

const chat = (id: string, extra: Partial<Conversation> = {}): Conversation => ({
  id,
  title: id,
  messages: [],
  createdAt: 0,
  updatedAt: 0,
  ...extra,
});
const folder = (id: number, name = `F${id}`): ChatFolder => ({ id, name, position: id, chat_count: 0 });
const ids = (chats: Conversation[]) => chats.map((c) => c.id);

describe("buildLayout", () => {
  it("is flat, with no headers, when there are no pins and no folders", () => {
    const layout = buildLayout([chat("a"), chat("b")], []);

    expect(layout.grouped).toBe(false);
    expect(layout.sections).toHaveLength(1);
    expect(layout.sections[0]).toMatchObject({ kind: "unfiled" });
    expect(ids(layout.sections[0]!.chats)).toEqual(["a", "b"]);
  });

  it("puts pinned chats first, then folders in order, then the rest", () => {
    const layout = buildLayout(
      [chat("p", { pinned: true }), chat("in2", { folderId: 2 }), chat("in1", { folderId: 1 }), chat("free")],
      [folder(1), folder(2)],
    );

    expect(layout.grouped).toBe(true);
    expect(layout.sections.map((s) => s.key)).toEqual(["pinned", "folder-1", "folder-2", "unfiled"]);
    expect(layout.sections.map((s) => ids(s.chats))).toEqual([["p"], ["in1"], ["in2"], ["free"]]);
  });

  it("shows a pinned chat only in Pinned, whatever folder it is in", () => {
    const layout = buildLayout([chat("p", { pinned: true, folderId: 1 })], [folder(1)]);

    expect(layout.sections.map((s) => ids(s.chats))).toEqual([["p"], []]);
  });

  it("always shows folders, even empty ones, and hides empty Pinned and Unfiled", () => {
    const layout = buildLayout([], [folder(1)]);

    expect(layout.grouped).toBe(true);
    expect(layout.sections.map((s) => s.key)).toEqual(["folder-1"]);
    expect(layout.sections[0]!.folder?.name).toBe("F1");
  });

  it("treats undefined, null and unknown folders as unfiled", () => {
    const layout = buildLayout(
      [chat("a"), chat("b", { folderId: null }), chat("c", { folderId: 99 })],
      [folder(1)],
    );

    expect(layout.sections.map((s) => s.key)).toEqual(["folder-1", "unfiled"]);
    expect(ids(layout.sections[1]!.chats)).toEqual(["a", "b", "c"]);
  });

  it("keeps the order it was given inside a section", () => {
    const layout = buildLayout([chat("z", { folderId: 1 }), chat("y", { folderId: 1 })], [folder(1)]);

    expect(ids(layout.sections[0]!.chats)).toEqual(["z", "y"]);
  });
});
```

Create `ember_web/src/utils/chatMenu.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { MAX_FOLDERS, type ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";
import { chatMenuItems, folderMenuItems, parseChatChoice } from "./chatMenu";

const chat = (extra: Partial<Conversation> = {}): Conversation => ({
  id: "c1",
  title: "T",
  messages: [],
  createdAt: 0,
  updatedAt: 0,
  ...extra,
});
const folder = (id: number): ChatFolder => ({ id, name: `F${id}`, position: id, chat_count: 0 });
const byId = (items: ReturnType<typeof chatMenuItems>, id: string) => items.find((i) => i.id === id);

describe("chatMenuItems", () => {
  it("offers Pin, Move to..., Rename and Delete in that order", () => {
    const items = chatMenuItems(chat(), [], false).filter((i) => !i.separator);

    expect(items.map((i) => i.id)).toEqual(["pin", "move", "rename", "delete"]);
  });

  it("offers Unpin for a pinned chat", () => {
    const items = chatMenuItems(chat({ pinned: true }), [], false);

    expect(byId(items, "unpin")?.label).toBe("Unpin");
    expect(byId(items, "pin")).toBeUndefined();
  });

  it("lists No folder, the folders and New folder in the flyout, checking the current one", () => {
    const move = byId(chatMenuItems(chat({ folderId: 2 }), [folder(1), folder(2)], false), "move")!;
    const children = move.children!.filter((i) => !i.separator);

    expect(children.map((i) => i.id)).toEqual(["move:none", "move:1", "move:2", "move:new"]);
    expect(children.map((i) => !!i.checked)).toEqual([false, false, true, false]);
  });

  it("checks No folder for an unfiled chat", () => {
    const move = byId(chatMenuItems(chat(), [folder(1)], false), "move")!;

    expect(move.children!.find((i) => i.id === "move:none")?.checked).toBe(true);
  });

  it("disables Move to... and Delete while the chat is answering, but not Pin or Rename", () => {
    const items = chatMenuItems(chat(), [], true);

    expect([byId(items, "move")?.disabled, byId(items, "delete")?.disabled]).toEqual([true, true]);
    expect([byId(items, "pin")?.disabled, byId(items, "rename")?.disabled]).toEqual([undefined, undefined]);
  });

  it("disables New folder at the folder limit", () => {
    const many = Array.from({ length: MAX_FOLDERS }, (_, i) => folder(i + 1));
    const move = byId(chatMenuItems(chat(), many, false), "move")!;

    expect(move.children!.find((i) => i.id === "move:new")?.disabled).toBe(true);
  });

  it("marks Delete as dangerous", () => {
    expect(byId(chatMenuItems(chat(), [], false), "delete")?.danger).toBe(true);
  });
});

describe("folderMenuItems", () => {
  it("offers Rename and Delete", () => {
    expect(folderMenuItems().map((i) => i.id)).toEqual(["rename", "delete"]);
  });
});

describe("parseChatChoice", () => {
  it("reads the simple actions", () => {
    expect(parseChatChoice("pin")).toEqual({ action: "pin" });
    expect(parseChatChoice("unpin")).toEqual({ action: "unpin" });
    expect(parseChatChoice("rename")).toEqual({ action: "rename" });
    expect(parseChatChoice("delete")).toEqual({ action: "delete" });
  });

  it("reads the move choices", () => {
    expect(parseChatChoice("move:none")).toEqual({ action: "move", folderId: null });
    expect(parseChatChoice("move:7")).toEqual({ action: "move", folderId: 7 });
    expect(parseChatChoice("move:new")).toEqual({ action: "moveNew" });
  });

  it("returns null for anything else", () => {
    expect(parseChatChoice("move")).toBeNull();
    expect(parseChatChoice("move:abc")).toBeNull();
    expect(parseChatChoice("")).toBeNull();
  });
});
```

Create `ember_web/src/composables/useFolderCollapse.test.ts`:

```ts
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "../stores/auth";
import { useFolderCollapse } from "./useFolderCollapse";

const account = (id: number) => ({ id, username: "u", email: "u@example.com", email_verified: true, roles: [], permissions: ["chat.use"] });

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  useAuthStore().account = account(1);
});

describe("useFolderCollapse", () => {
  it("starts with every folder open", () => {
    const { isCollapsed } = useFolderCollapse();

    expect(isCollapsed(5)).toBe(false);
  });

  it("toggles a folder and remembers it for the next visit", () => {
    const first = useFolderCollapse();
    first.toggle(5);
    expect(first.isCollapsed(5)).toBe(true);

    expect(useFolderCollapse().isCollapsed(5)).toBe(true);
    first.toggle(5);
    expect(useFolderCollapse().isCollapsed(5)).toBe(false);
  });

  it("keeps each account's choices apart", () => {
    useFolderCollapse().toggle(5);

    useAuthStore().account = account(2);

    expect(useFolderCollapse().isCollapsed(5)).toBe(false);
  });

  it("ignores damaged storage", () => {
    localStorage.setItem("ember_web.collapsedFolders.1", "not json");

    expect(useFolderCollapse().isCollapsed(5)).toBe(false);
  });

  it("still works in memory when storage is blocked", () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("blocked");
    };
    try {
      const { toggle, isCollapsed } = useFolderCollapse();
      toggle(5);
      expect(isCollapsed(5)).toBe(true);
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run src/utils/chatSections.test.ts src/utils/chatMenu.test.ts src/composables/useFolderCollapse.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement**

Create `ember_web/src/utils/chatSections.ts`:

```ts
import type { ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";

/** One block of the chat list: the pinned chats, one folder, or the chats in no folder. */
export interface ChatSection {
  kind: "pinned" | "folder" | "unfiled";
  key: string;
  /** Set for a folder section. */
  folder: ChatFolder | null;
  chats: Conversation[];
}

export interface ChatLayout {
  /** False with no pins and no folders: one flat list, shown without headers. */
  grouped: boolean;
  sections: ChatSection[];
}

/** Sorts `chats` (already in display order) into Pinned, the folders in the
 * order given, then Unfiled. Folders always appear, even empty; Pinned and
 * Unfiled only when they hold chats. A chat in a folder this list does not
 * know (not loaded yet, or deleted elsewhere) counts as unfiled. */
export function buildLayout(chats: Conversation[], folders: ChatFolder[]): ChatLayout {
  const known = new Set(folders.map((f) => f.id));
  const pinned: Conversation[] = [];
  const unfiled: Conversation[] = [];
  const byFolder = new Map<number, Conversation[]>();

  for (const chat of chats) {
    if (chat.pinned) {
      pinned.push(chat);
    } else if (chat.folderId != null && known.has(chat.folderId)) {
      const list = byFolder.get(chat.folderId);
      if (list) list.push(chat);
      else byFolder.set(chat.folderId, [chat]);
    } else {
      unfiled.push(chat);
    }
  }

  if (pinned.length === 0 && folders.length === 0) {
    return { grouped: false, sections: [{ kind: "unfiled", key: "unfiled", folder: null, chats: unfiled }] };
  }

  const sections: ChatSection[] = [];
  if (pinned.length > 0) sections.push({ kind: "pinned", key: "pinned", folder: null, chats: pinned });
  for (const folder of folders) {
    sections.push({ kind: "folder", key: `folder-${folder.id}`, folder, chats: byFolder.get(folder.id) ?? [] });
  }
  if (unfiled.length > 0) sections.push({ kind: "unfiled", key: "unfiled", folder: null, chats: unfiled });
  return { grouped: true, sections };
}
```

Create `ember_web/src/utils/chatMenu.ts`:

```ts
import { MAX_FOLDERS, type ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";

/** One line of a popup menu. `children` makes it open a flyout. */
export interface MenuItem {
  id: string;
  label: string;
  checked?: boolean;
  danger?: boolean;
  disabled?: boolean;
  separator?: boolean;
  children?: MenuItem[];
}

const separator = (id: string): MenuItem => ({ id, label: "", separator: true });

/** The menu of a chat row. `answering`: an answer is being written for this
 * chat, so it can be neither moved nor deleted (pinning and renaming change
 * no messages and stay available). */
export function chatMenuItems(chat: Conversation, folders: ChatFolder[], answering: boolean): MenuItem[] {
  const current = chat.folderId ?? null;
  const flyout: MenuItem[] = [
    { id: "move:none", label: "No folder", checked: current === null },
    ...folders.map((f) => ({ id: `move:${f.id}`, label: f.name, checked: current === f.id })),
    separator("sep-new"),
    { id: "move:new", label: "New folder...", disabled: folders.length >= MAX_FOLDERS },
  ];
  return [
    chat.pinned ? { id: "unpin", label: "Unpin" } : { id: "pin", label: "Pin" },
    { id: "move", label: "Move to...", disabled: answering, children: flyout },
    separator("sep-edit"),
    { id: "rename", label: "Rename" },
    { id: "delete", label: "Delete", danger: true, disabled: answering },
  ];
}

/** The menu of a folder header. */
export function folderMenuItems(): MenuItem[] {
  return [
    { id: "rename", label: "Rename" },
    { id: "delete", label: "Delete", danger: true },
  ];
}

export type ChatChoice =
  | { action: "pin" | "unpin" | "rename" | "delete" }
  | { action: "move"; folderId: number | null }
  | { action: "moveNew" };

/** Turns a chat-menu item id back into what the user chose. */
export function parseChatChoice(id: string): ChatChoice | null {
  if (id === "pin" || id === "unpin" || id === "rename" || id === "delete") return { action: id };
  if (id === "move:none") return { action: "move", folderId: null };
  if (id === "move:new") return { action: "moveNew" };
  const match = /^move:(\d+)$/.exec(id);
  return match ? { action: "move", folderId: Number(match[1]) } : null;
}
```

Create `ember_web/src/composables/useFolderCollapse.ts`:

```ts
import { ref, type Ref } from "vue";
import { useAuthStore } from "../stores/auth";

const keyFor = (accountId: number) => `ember_web.collapsedFolders.${accountId}`;

// Per-browser convenience: damaged or blocked storage just means "all open".
function read(key: string): number[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((v): v is number => typeof v === "number") : [];
  } catch {
    return [];
  }
}

function write(key: string, ids: number[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(ids));
  } catch {
    // ignore - see read
  }
}

/** Which folders of the chat list are folded away, remembered per account in this browser. */
export function useFolderCollapse(): {
  collapsed: Ref<number[]>;
  isCollapsed: (id: number) => boolean;
  toggle: (id: number) => void;
} {
  const accountId = useAuthStore().account?.id;
  const key = accountId === undefined ? null : keyFor(accountId);
  const collapsed = ref<number[]>(key ? read(key) : []);

  function isCollapsed(id: number): boolean {
    return collapsed.value.includes(id);
  }

  function toggle(id: number): void {
    collapsed.value = isCollapsed(id) ? collapsed.value.filter((v) => v !== id) : [...collapsed.value, id];
    if (key) write(key, collapsed.value);
  }

  return { collapsed, isCollapsed, toggle };
}
```

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/utils src/composables && npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/utils ember_web/src/composables
git commit -m "feat(ember_web): chat list layout, row menu items and folder collapse state"
```

---

### Task 3: `PopupMenu.vue`

**Files:**
- Create: `ember_web/src/components/PopupMenu.vue`, `ember_web/src/components/PopupMenu.test.ts`

**Interfaces:**
- Consumes: `MenuItem` from `../utils/chatMenu`.
- Produces: `<PopupMenu :items :x :y :label @select="(id: string) => void" @close="() => void" />`. Renders into `document.body` (Teleport). `select` carries the item id (a leaf, never a parent); the owner closes the menu. `close` is emitted on Esc, an outside pointerdown, Tab and window resize.

- [ ] **Step 1: Write the failing tests**

Create `ember_web/src/components/PopupMenu.test.ts`:

```ts
import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";
import type { MenuItem } from "../utils/chatMenu";
import PopupMenu from "./PopupMenu.vue";

const ITEMS: MenuItem[] = [
  { id: "pin", label: "Pin" },
  {
    id: "move",
    label: "Move to...",
    children: [
      { id: "move:none", label: "No folder", checked: false },
      { id: "move:1", label: "Work", checked: true },
    ],
  },
  { id: "sep", label: "", separator: true },
  { id: "off", label: "Off", disabled: true },
  { id: "delete", label: "Delete", danger: true },
];

let wrapper: VueWrapper | null = null;

function open(items: MenuItem[] = ITEMS) {
  wrapper = mount(PopupMenu, { props: { items, x: 40, y: 60, label: "Chat actions" }, attachTo: document.body });
  return wrapper;
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

const q = (selector: string) => document.body.querySelector<HTMLElement>(selector);
const all = (selector: string) => [...document.body.querySelectorAll<HTMLElement>(selector)];
const key = (el: Element | null, name: string) => {
  el?.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true }));
  return nextTick();
};

describe("PopupMenu", () => {
  it("renders the items in the page body, at the given place, with a label", () => {
    const w = open();

    expect(w.element.parentElement).not.toBe(document.body); // teleported away from the mount point
    expect(q('[role="menu"]')?.getAttribute("aria-label")).toBe("Chat actions");
    expect(all('[role="menuitem"]').map((b) => b.textContent?.replace("›", "").trim())).toEqual([
      "Pin",
      "Move to...",
      "Off",
      "Delete",
    ]);
    expect(q('[role="menu"]')?.style.left).toBe("40px");
    expect(q('[role="menu"]')?.style.top).toBe("60px");
  });

  it("selects an item by click and reports its id", async () => {
    const w = open();

    q('[role="menuitem"]')!.click();

    expect(w.emitted("select")).toEqual([["pin"]]);
  });

  it("does not select a disabled item", () => {
    const w = open();

    all('[role="menuitem"]').find((b) => b.textContent?.includes("Off"))!.click();

    expect(w.emitted("select")).toBeUndefined();
  });

  it("marks a dangerous item", () => {
    open();

    expect(all('[role="menuitem"]').find((b) => b.textContent?.includes("Delete"))?.classList.contains("danger")).toBe(true);
  });

  it("focuses the first enabled item when it opens", async () => {
    open();
    await nextTick();

    expect(document.activeElement?.textContent).toContain("Pin");
  });

  it("moves focus with the arrow keys, skipping disabled items, and wraps", async () => {
    open();
    await nextTick();
    const menu = q('[role="menu"]');

    await key(menu, "ArrowDown");
    expect(document.activeElement?.textContent).toContain("Move to...");
    await key(menu, "ArrowDown");
    expect(document.activeElement?.textContent).toContain("Delete"); // "Off" is skipped
    await key(menu, "ArrowDown");
    expect(document.activeElement?.textContent).toContain("Pin");
    await key(menu, "ArrowUp");
    expect(document.activeElement?.textContent).toContain("Delete");
  });

  it("Home and End jump to the first and last item", async () => {
    open();
    await nextTick();
    const menu = q('[role="menu"]');

    await key(menu, "End");
    expect(document.activeElement?.textContent).toContain("Delete");
    await key(menu, "Home");
    expect(document.activeElement?.textContent).toContain("Pin");
  });

  it("Enter activates the focused item", async () => {
    const w = open();
    await nextTick();

    (document.activeElement as HTMLElement).click(); // Enter on a button is a click

    expect(w.emitted("select")).toEqual([["pin"]]);
  });

  it("opens the flyout on click, shows the current choice, and selects a child", async () => {
    const w = open();

    all('[role="menuitem"]').find((b) => b.textContent?.includes("Move to..."))!.click();
    await nextTick();
    const radios = all('[role="menuitemradio"]');

    expect(radios.map((r) => [r.textContent?.trim(), r.getAttribute("aria-checked")])).toEqual([
      ["No folder", "false"],
      ["Work", "true"],
    ]);
    radios[1]!.click();
    expect(w.emitted("select")).toEqual([["move:1"]]);
  });

  it("ArrowRight opens the flyout and focuses its first item; ArrowLeft closes it", async () => {
    open();
    await nextTick();
    const menu = q('[role="menu"]');
    await key(menu, "ArrowDown"); // on Move to...

    await key(document.activeElement, "ArrowRight");
    await nextTick();
    expect(document.activeElement?.textContent).toContain("No folder");

    await key(document.activeElement, "ArrowLeft");
    await nextTick();
    expect(all('[role="menuitemradio"]')).toHaveLength(0);
    expect(document.activeElement?.textContent).toContain("Move to...");
  });

  it("Esc closes the flyout first, then the menu", async () => {
    const w = open();
    await nextTick();
    all('[role="menuitem"]').find((b) => b.textContent?.includes("Move to..."))!.click();
    await nextTick();

    await key(document.activeElement, "Escape");
    expect(all('[role="menuitemradio"]')).toHaveLength(0);
    expect(w.emitted("close")).toBeUndefined();

    await key(document.activeElement, "Escape");
    expect(w.emitted("close")).toHaveLength(1);
  });

  it("closes on a press outside, but not on a press inside", () => {
    const w = open();

    q('[role="menu"]')!.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(w.emitted("close")).toBeUndefined();

    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(w.emitted("close")).toHaveLength(1);
  });

  it("closes on Tab", async () => {
    const w = open();
    await nextTick();

    await key(q('[role="menu"]'), "Tab");

    expect(w.emitted("close")).toHaveLength(1);
  });

  it("does not open the flyout of a disabled parent", () => {
    open([{ id: "move", label: "Move to...", disabled: true, children: [{ id: "x", label: "X" }] }]);

    q('[role="menuitem"]')!.click();

    expect(all('[role="menuitemradio"]')).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run src/components/PopupMenu.test.ts`
Expected: FAIL (`PopupMenu.vue` not found).

- [ ] **Step 3: Implement**

Create `ember_web/src/components/PopupMenu.vue`:

```vue
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import type { MenuItem } from "../utils/chatMenu";

// A small popup menu at a point of the page, with an optional flyout for items
// that have `children`. It is teleported to <body>, so no scrolling or clipping
// parent (the sidebar) can cut it off. It reports what was chosen (`select`) or
// that it should go away (`close`: Esc, a press outside, Tab, a resize); the
// owner removes it, and puts focus back where it came from after a `close`.
const MENU_WIDTH = 210;
const FLYOUT_WIDTH = 220;
const MARGIN = 8;

const props = defineProps<{ items: MenuItem[]; x: number; y: number; label: string }>();
const emit = defineEmits<{ select: [id: string]; close: [] }>();

const root = ref<HTMLElement | null>(null);
const left = ref(props.x);
const top = ref(props.y);
// The item whose flyout is open.
const openId = ref<string | null>(null);
// A flyout needs room to the right; without it (or on touch screens, which have
// no hover) it opens over the main menu instead.
const overlay = ref(false);

function touchOnly(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(hover: none)").matches;
}

function place(): void {
  const box = root.value?.getBoundingClientRect();
  const width = box?.width || MENU_WIDTH;
  const height = box?.height || 0;
  left.value = Math.max(MARGIN, Math.min(props.x, window.innerWidth - width - MARGIN));
  top.value = Math.max(MARGIN, Math.min(props.y, window.innerHeight - height - MARGIN));
  overlay.value = touchOnly() || left.value + width + FLYOUT_WIDTH > window.innerWidth;
}

/** The enabled buttons of the level (main menu or flyout) that holds `from`. */
function levelButtons(from: Element | null): HTMLButtonElement[] {
  const flyout = from?.closest(".flyout");
  const scope = flyout ?? root.value;
  if (!scope) return [];
  const all = [...scope.querySelectorAll<HTMLButtonElement>("button[role^='menuitem']:not([disabled])")];
  return flyout ? all : all.filter((b) => !b.closest(".flyout"));
}

function focusFirst(): void {
  levelButtons(root.value?.querySelector("button"))[0]?.focus();
}

function move(step: 1 | -1 | "first" | "last"): void {
  const buttons = levelButtons(document.activeElement);
  if (buttons.length === 0) return;
  const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
  let next: number;
  if (step === "first") next = 0;
  else if (step === "last") next = buttons.length - 1;
  else next = (at + step + buttons.length) % buttons.length;
  buttons[next]!.focus();
}

async function openFlyout(item: MenuItem, focusChild: boolean): Promise<void> {
  if (item.disabled || !item.children) return;
  openId.value = item.id;
  if (!focusChild) return;
  await nextTick();
  root.value?.querySelector<HTMLButtonElement>(".flyout button:not([disabled])")?.focus();
}

async function closeFlyout(): Promise<void> {
  const id = openId.value;
  if (id === null) return;
  openId.value = null;
  await nextTick();
  root.value?.querySelector<HTMLButtonElement>(`button[data-id="${id}"]`)?.focus();
}

function activate(item: MenuItem): void {
  if (item.disabled) return;
  if (item.children) void openFlyout(item, true);
  else emit("select", item.id);
}

function hover(item: MenuItem): void {
  if (touchOnly()) return;
  if (item.children && !item.disabled) openId.value = item.id;
  else openId.value = null;
}

function focusedItem(): MenuItem | undefined {
  const id = (document.activeElement as HTMLElement | null)?.dataset.id;
  return props.items.find((i) => i.id === id);
}

function onKey(event: KeyboardEvent): void {
  switch (event.key) {
    case "Escape":
      event.preventDefault();
      event.stopPropagation();
      if (openId.value !== null) void closeFlyout();
      else emit("close");
      break;
    case "ArrowDown":
      event.preventDefault();
      move(1);
      break;
    case "ArrowUp":
      event.preventDefault();
      move(-1);
      break;
    case "Home":
      event.preventDefault();
      move("first");
      break;
    case "End":
      event.preventDefault();
      move("last");
      break;
    case "ArrowRight": {
      const item = focusedItem();
      if (item?.children) {
        event.preventDefault();
        void openFlyout(item, true);
      }
      break;
    }
    case "ArrowLeft":
      if (openId.value !== null) {
        event.preventDefault();
        void closeFlyout();
      }
      break;
    case "Tab":
      emit("close");
      break;
  }
}

function onPointerDown(event: Event): void {
  if (root.value && !root.value.contains(event.target as Node)) emit("close");
}

const onResize = () => emit("close");

onMounted(async () => {
  document.addEventListener("pointerdown", onPointerDown);
  window.addEventListener("resize", onResize);
  await nextTick();
  place();
  focusFirst();
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onPointerDown);
  window.removeEventListener("resize", onResize);
});
</script>

<template>
  <Teleport to="body">
    <div
      ref="root"
      class="popup"
      role="menu"
      :aria-label="label"
      :style="{ left: `${left}px`, top: `${top}px` }"
      @keydown="onKey"
    >
      <template v-for="item in items" :key="item.id">
        <hr v-if="item.separator" role="separator" />
        <div v-else class="entry">
          <button
            type="button"
            role="menuitem"
            :data-id="item.id"
            :class="['item', { danger: item.danger }]"
            :disabled="item.disabled"
            :aria-haspopup="item.children ? 'menu' : undefined"
            :aria-expanded="item.children ? openId === item.id : undefined"
            @click="activate(item)"
            @mouseenter="hover(item)"
          >
            <span>{{ item.label }}</span>
            <span v-if="item.children" class="chevron" aria-hidden="true">›</span>
          </button>
          <div
            v-if="item.children && openId === item.id"
            :class="['flyout', { overlay }]"
            role="menu"
            :aria-label="item.label"
          >
            <template v-for="child in item.children" :key="child.id">
              <hr v-if="child.separator" role="separator" />
              <button
                v-else
                type="button"
                role="menuitemradio"
                :aria-checked="child.checked ?? false"
                :data-id="child.id"
                :class="['item', { danger: child.danger }]"
                :disabled="child.disabled"
                @click="activate(child)"
              >
                <span class="check" aria-hidden="true">{{ child.checked ? "✓" : "" }}</span>
                <span>{{ child.label }}</span>
              </button>
            </template>
          </div>
        </div>
      </template>
    </div>
  </Teleport>
</template>

<style scoped>
.popup {
  position: fixed;
  z-index: 50;
  min-width: 170px;
  max-width: 260px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text);
  background: var(--surface);
  box-shadow: 0 6px 24px rgb(0 0 0 / 22%);
}
.entry {
  position: relative;
}
.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  text-align: left;
  font: inherit;
  font-size: 0.9em;
  color: var(--text);
  background: transparent;
}
.item:hover:not(:disabled),
.item:focus-visible {
  outline: none;
  background: var(--bg);
}
.item:disabled {
  cursor: default;
  opacity: 0.45;
}
.danger {
  color: var(--danger);
}
.chevron {
  color: var(--muted);
}
.check {
  width: 1em;
  flex-shrink: 0;
  color: var(--accent);
}
hr {
  margin: 4px 6px;
  border: none;
  border-top: 1px solid var(--border);
}
.flyout {
  position: absolute;
  z-index: 1;
  top: 0;
  left: 100%;
  min-width: 170px;
  max-height: 60vh;
  padding: 4px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 6px 24px rgb(0 0 0 / 22%);
}
/* No room to the right (or no hover): cover the main menu instead. */
.flyout.overlay {
  top: 0;
  left: 0;
  right: 0;
  min-width: 100%;
}
.flyout .item {
  justify-content: flex-start;
}
</style>
```

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/components/PopupMenu.test.ts && npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing. If a test fails only because jsdom lacks a browser behavior (focus after a `nextTick`), fix the test's awaiting, not the component's behavior; report any such change.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/components/PopupMenu.vue ember_web/src/components/PopupMenu.test.ts
git commit -m "feat(ember_web): popup menu with a flyout, keyboard support and outside-click close"
```

---

### Task 4: `ChatSection.vue`

**Files:**
- Create: `ember_web/src/components/ChatSection.vue`, `ember_web/src/components/ChatSection.test.ts`

**Interfaces:**
- Produces: `ChatSection` props `{title: string | null; count: number; collapsible: boolean; collapsed: boolean; menu: boolean}`, default slot (the rows), emits `toggle`, `openMenu(point: MenuPoint)`; `title === null` renders only the list (no header). Exports type `MenuPoint {x: number; y: number; trigger: HTMLElement | null}` from `ember_web/src/components/menuPoint.ts`.

- [ ] **Step 1: Write the failing tests**

Create `ember_web/src/components/menuPoint.ts`:

```ts
/** Where a menu should open, and which button to give focus back to afterwards. */
export interface MenuPoint {
  x: number;
  y: number;
  trigger: HTMLElement | null;
}
```

Create `ember_web/src/components/ChatSection.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ChatSection from "./ChatSection.vue";

type Props = InstanceType<typeof ChatSection>["$props"];

function mountSection(props: Partial<Props> = {}) {
  return mount(ChatSection, {
    props: { title: "Work", count: 3, collapsible: true, collapsed: false, menu: true, ...props },
    slots: { default: '<li class="row-stub">row</li>' },
  });
}

describe("ChatSection", () => {
  it("shows the title, the count and the rows", () => {
    const wrapper = mountSection();

    expect(wrapper.text()).toContain("Work");
    expect(wrapper.find(".count").text()).toBe("3");
    expect(wrapper.find(".row-stub").exists()).toBe(true);
  });

  it("hides the rows while collapsed, and says so to assistive tech", () => {
    const wrapper = mountSection({ collapsed: true });

    expect(wrapper.find(".row-stub").exists()).toBe(false);
    expect(wrapper.find("button.toggle").attributes("aria-expanded")).toBe("false");
  });

  it("toggles from the header", async () => {
    const wrapper = mountSection();

    await wrapper.find("button.toggle").trigger("click");

    expect(wrapper.emitted("toggle")).toHaveLength(1);
  });

  it("is not a button when it cannot collapse", () => {
    const wrapper = mountSection({ collapsible: false, title: "Pinned" });

    expect(wrapper.find("button.toggle").exists()).toBe(false);
    expect(wrapper.text()).toContain("Pinned");
  });

  it("opens its menu from the ... button and by right-click on the header", async () => {
    const wrapper = mountSection();

    await wrapper.find("button.more").trigger("click");
    await wrapper.find("header").trigger("contextmenu", { clientX: 5, clientY: 9 });

    const points = wrapper.emitted("openMenu")!.map((e) => e[0] as { x: number; y: number });
    expect(points).toHaveLength(2);
    expect(points[1]).toMatchObject({ x: 5, y: 9 });
  });

  it("has no ... button when it has no menu", () => {
    expect(mountSection({ menu: false }).find("button.more").exists()).toBe(false);
  });

  it("renders only the list, with no header, when the title is null", () => {
    const wrapper = mountSection({ title: null });

    expect(wrapper.find("header").exists()).toBe(false);
    expect(wrapper.find(".row-stub").exists()).toBe(true);
  });
});
```


- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run src/components/ChatSection.test.ts`
Expected: FAIL (`ChatSection.vue` not found).

- [ ] **Step 3: Implement**

Create `ember_web/src/components/ChatSection.vue`:

```vue
<script setup lang="ts">
import { ref } from "vue";
import type { MenuPoint } from "./menuPoint";

// One block of the chat list: a header (title, count, a "..." menu button) and
// the rows in the default slot. A folder can fold; Pinned and "Chats" cannot.
// With title null it is just the list, which is how an ungrouped list looks.
const props = defineProps<{
  title: string | null;
  count: number;
  collapsible: boolean;
  collapsed: boolean;
  menu: boolean;
}>();
const emit = defineEmits<{ toggle: []; openMenu: [point: MenuPoint] }>();

const moreButton = ref<HTMLButtonElement | null>(null);

function openFromButton(): void {
  const box = moreButton.value?.getBoundingClientRect();
  emit("openMenu", { x: box?.left ?? 0, y: box?.bottom ?? 0, trigger: moreButton.value });
}

function openFromContext(event: MouseEvent): void {
  if (!props.menu) return;
  event.preventDefault();
  emit("openMenu", { x: event.clientX, y: event.clientY, trigger: moreButton.value });
}
</script>

<template>
  <section class="section">
    <header v-if="title !== null" @contextmenu="openFromContext">
      <button
        v-if="collapsible"
        type="button"
        class="toggle"
        :aria-expanded="!collapsed"
        @click="emit('toggle')"
      >
        <svg :class="['chevron', { turned: collapsed }]" viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
        </svg>
        <span class="name">{{ title }}</span>
        <span class="count">{{ count }}</span>
      </button>
      <h4 v-else class="plain">
        <span class="name">{{ title }}</span>
        <span class="count">{{ count }}</span>
      </h4>
      <button
        v-if="menu"
        ref="moreButton"
        type="button"
        class="more"
        title="Folder actions"
        aria-label="Folder actions"
        aria-haspopup="menu"
        @click="openFromButton"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <circle cx="5" cy="12" r="1.8" fill="currentColor" />
          <circle cx="12" cy="12" r="1.8" fill="currentColor" />
          <circle cx="19" cy="12" r="1.8" fill="currentColor" />
        </svg>
      </button>
    </header>
    <ul v-if="!collapsed" class="list">
      <slot />
    </ul>
  </section>
</template>

<style scoped>
.section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
header {
  display: flex;
  align-items: center;
  gap: 2px;
  padding-right: 4px;
}
.toggle,
.plain {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 5px 8px;
  border: none;
  border-radius: 8px;
  color: var(--muted);
  background: transparent;
  font: inherit;
  font-size: 0.78em;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  text-align: left;
}
.toggle {
  cursor: pointer;
}
.toggle:hover {
  color: var(--text);
  background: var(--bg);
}
.name {
  flex: 1;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.count {
  font-weight: 400;
  opacity: 0.8;
}
.chevron {
  flex-shrink: 0;
  transition: transform 0.12s;
}
.chevron.turned {
  transform: rotate(-90deg);
}
.more {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
  opacity: 0;
}
header:hover .more,
.more:focus-visible {
  opacity: 1;
}
@media (hover: none) {
  .more {
    opacity: 1;
  }
}
.more:hover {
  color: var(--text);
}
.list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
```


- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/components/ChatSection.test.ts && npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/components/ChatSection.vue ember_web/src/components/ChatSection.test.ts ember_web/src/components/menuPoint.ts
git commit -m "feat(ember_web): chat section header component"
```

---

### Task 5: Sidebar sections, menus and footer

**Files:**
- Modify: `ember_web/src/components/ChatRow.vue`, `ember_web/src/components/ChatRow.test.ts`
- Modify: `ember_web/src/components/ConversationSidebar.vue`
- Modify: `ember_web/src/components/ConversationSidebar.test.ts`

**Interfaces:**
- Produces (ChatRow): emit `delete` is removed; new emit `openMenu(point: MenuPoint)`; the pencil and delete hover buttons are replaced by one "..." button (`button.more`, `title="Chat actions"`, `aria-haspopup="menu"`); right-click on the row also emits `openMenu` (not while selecting or renaming).
- Consumes: `buildLayout`, `chatMenuItems`, `folderMenuItems`, `parseChatChoice`, `MenuItem`, `PopupMenu`, `ChatSection`, `ChatRow` (new emits), `ChatFolder`, `MAX_FOLDERS`, `MenuPoint`.
- Produces: new optional props `folders: ChatFolder[]` (default `[]`) and `collapsedFolders: number[]` (default `[]`); new emits `pin(id: string, pinned: boolean)`, `move(id: string, folderId: number | null)`, `moveNew(id: string)`, `toggleFolder(id: number)`, `newFolder()`, `renameFolder(folder: ChatFolder)`, `deleteFolder(folder: ChatFolder)`. All existing props and emits stay.

This is the integration task: read the whole current `ConversationSidebar.vue` and its test first.

- [ ] **Step 1: Write the failing tests**

First, ChatRow. In `ember_web/src/components/ChatRow.test.ts`: remove the tests `starts a rename from the pencil and from a double click on the title` and `deleting emits delete; the answering chat cannot be deleted`, and replace them with:

```ts
  it("starts a rename from a double click on the title", async () => {
    const wrapper = mountRow();

    await wrapper.find(".title").trigger("dblclick");

    expect(wrapper.emitted("startRename")).toHaveLength(1);
    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("has a ... button that opens the menu without selecting the row", async () => {
    const wrapper = mountRow();

    await wrapper.find("button.more").trigger("click");

    expect(wrapper.emitted("openMenu")).toHaveLength(1);
    expect(wrapper.emitted("select")).toBeUndefined();
    expect(wrapper.find("button.more").attributes("aria-haspopup")).toBe("menu");
  });

  it("opens the menu on right-click at the pointer, but not while selecting or renaming", async () => {
    const wrapper = mountRow();
    await wrapper.find("li").trigger("contextmenu", { clientX: 12, clientY: 34 });
    expect(wrapper.emitted("openMenu")![0]![0]).toMatchObject({ x: 12, y: 34 });

    const selecting = mountRow({ selecting: true });
    await selecting.find("li").trigger("contextmenu");
    expect(selecting.emitted("openMenu")).toBeUndefined();

    const renaming = mountRow({ renaming: true });
    await renaming.find("li").trigger("contextmenu");
    expect(renaming.emitted("openMenu")).toBeUndefined();
  });

  it("no longer has rename or delete buttons of its own", () => {
    const wrapper = mountRow();

    expect(wrapper.find('button[title="Rename chat"]').exists()).toBe(false);
    expect(wrapper.find("button.delete").exists()).toBe(false);
  });
```


Then the sidebar. In `ember_web/src/components/ConversationSidebar.test.ts`:

(a) Add imports and helpers near the top:
```ts
import type { ChatFolder } from "../api/FoldersClient";

const folder = (id: number, name = `Folder ${id}`): ChatFolder => ({ id, name, position: id, chat_count: 0 });
const inFolder = (id: string, folderId: number | null, extra: Partial<Conversation> = {}): Conversation => ({
  ...chat(id),
  folderId,
  ...extra,
});
const menuButton = (wrapper: ReturnType<typeof mountSidebar>, index = 0) => wrapper.findAll("button.more")[index]!;
const menuItem = (label: string) =>
  [...document.body.querySelectorAll<HTMLElement>('[role^="menuitem"]')].find((b) => b.textContent?.includes(label));
```
Make `mountSidebar` mount with `attachTo: document.body` (the menu teleports to the body, and focus tests need an attached tree), and add an `afterEach` that unmounts wrappers (keep a module-level array of wrappers and call `unmount()` on each) and empties `document.body`.

(b) Update the tests that used the removed icons:
- The test at about line 133 `have no rename or delete buttons of their own` (search results): keep as is (hit rows still have none).
- The two tests around lines 345 to 372 (`a rename in progress ends when selecting starts`, `a rename abandoned by selecting does not come back after Cancel`) start a rename with `wrapper.find("button.icon").trigger("click")`. Replace that line in both with: `await wrapper.find(".title").trigger("dblclick");` (double-click still renames). Keep every other assertion.
- Any other test that clicks a pencil `button.icon`/`title="Rename chat"` or a delete `button.delete` to rename or delete one chat must go through the menu instead (see (c)). For each such test keep its assertions and change only the way it starts the action; list every test you changed in your report.

(c) Add new tests (inside new `describe` blocks):

```ts
describe("sections", () => {
  it("shows a flat list with no headers when there are no pins or folders", () => {
    const wrapper = mountSidebar();

    expect(wrapper.find("header").exists()).toBe(false);
    expect(wrapper.findAll("li.row")).toHaveLength(2);
  });

  it("groups chats under Pinned, each folder and Chats", () => {
    const wrapper = mountSidebar({
      conversations: [chat("p", ), inFolder("a", 1), inFolder("b", null)].map((c) => (c.id === "p" ? { ...c, pinned: true } : c)),
      folders: [folder(1, "Work"), folder(2, "Empty")],
    });

    const headers = wrapper.findAll("header").map((h) => h.find(".name").text());
    expect(headers).toEqual(["Pinned", "Work", "Empty", "Chats"]);
    expect(wrapper.findAll("header .count").map((c) => c.text())).toEqual(["1", "1", "0", "1"]);
  });

  it("hides the rows of a collapsed folder and asks to toggle one", async () => {
    const wrapper = mountSidebar({
      conversations: [inFolder("a", 1)],
      folders: [folder(1, "Work")],
      collapsedFolders: [1],
    });

    expect(wrapper.findAll("li.row")).toHaveLength(0);
    await wrapper.find("button.toggle").trigger("click");
    expect(wrapper.emitted("toggleFolder")).toEqual([[1]]);
  });

  it("shows folders even when there are no chats", () => {
    const wrapper = mountSidebar({ conversations: [], folders: [folder(1, "Work")] });

    expect(wrapper.find("header .name").text()).toBe("Work");
    expect(wrapper.text()).not.toContain("No saved chats yet.");
  });

  it("search results stay flat even with folders", () => {
    const wrapper = searching([hit("1")], { folders: [folder(1)] });

    expect(wrapper.find("header").exists()).toBe(false);
  });
});

describe("the row menu", () => {
  it("opens from the ... button with Pin, Move to..., Rename and Delete", async () => {
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");

    expect([...document.body.querySelectorAll('[role="menuitem"]')].map((b) => b.textContent?.replace("›", "").trim())).toEqual([
      "Pin",
      "Move to...",
      "Rename",
      "Delete",
    ]);
  });

  it("Pin and Unpin report the chat", async () => {
    const wrapper = mountSidebar({ conversations: [chat("1"), { ...chat("2"), pinned: true }], folders: [] });

    await menuButton(wrapper, 0).trigger("click"); // the pinned chat comes first
    menuItem("Unpin")!.click();
    await menuButton(wrapper, 1).trigger("click");
    menuItem("Pin")!.click();

    expect(wrapper.emitted("pin")).toEqual([["2", false], ["1", true]]);
  });

  it("Rename starts the inline rename of that row", async () => {
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");
    menuItem("Rename")!.click();
    await wrapper.vm.$nextTick();

    expect(wrapper.find("input.rename").exists()).toBe(true);
  });

  it("Delete asks first, then reports the chat", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");
    menuItem("Delete")!.click();

    expect(confirmSpy).toHaveBeenCalledWith('Delete "Chat 1"? This can\'t be undone.');
    expect(wrapper.emitted("delete")).toEqual([["1"]]);
  });

  it("Delete does nothing when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const wrapper = mountSidebar();

    await menuButton(wrapper).trigger("click");
    menuItem("Delete")!.click();

    expect(wrapper.emitted("delete")).toBeUndefined();
  });

  it("Move to... reports the chosen folder, None, or a new folder", async () => {
    const wrapper = mountSidebar({ folders: [folder(1, "Work")] });

    await menuButton(wrapper).trigger("click");
    menuItem("Move to...")!.click();
    await wrapper.vm.$nextTick();
    menuItem("Work")!.click();

    await menuButton(wrapper).trigger("click");
    menuItem("Move to...")!.click();
    await wrapper.vm.$nextTick();
    menuItem("No folder")!.click();

    await menuButton(wrapper).trigger("click");
    menuItem("Move to...")!.click();
    await wrapper.vm.$nextTick();
    menuItem("New folder...")!.click();

    expect(wrapper.emitted("move")).toEqual([["1", 1], ["1", null]]);
    expect(wrapper.emitted("moveNew")).toEqual([["1"]]);
  });

  it("the chat that is answering cannot be moved or deleted from its menu", async () => {
    const wrapper = mountSidebar({ conversations: [chat("1")], activeId: "1", locked: true });

    await menuButton(wrapper).trigger("click");

    expect(menuItem("Move to...")!.hasAttribute("disabled")).toBe(true);
    expect(menuItem("Delete")!.hasAttribute("disabled")).toBe(true);
    expect(menuItem("Pin")!.hasAttribute("disabled")).toBe(false);
  });

  it("closes on Escape and gives focus back to its button, but not after a choice", async () => {
    const wrapper = mountSidebar();
    const button = menuButton(wrapper);
    await button.trigger("click");

    document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await wrapper.vm.$nextTick();
    await wrapper.vm.$nextTick();

    expect(document.body.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(button.element);
  });

  it("a folder header has a menu with Rename and Delete that report the folder", async () => {
    const wrapper = mountSidebar({ conversations: [], folders: [folder(1, "Work")] });

    await wrapper.find("header button.more").trigger("click");
    menuItem("Rename")!.click();
    await wrapper.find("header button.more").trigger("click");
    menuItem("Delete")!.click();

    expect(wrapper.emitted("renameFolder")).toEqual([[folder(1, "Work")]]);
    expect(wrapper.emitted("deleteFolder")).toEqual([[folder(1, "Work")]]);
  });
});

describe("the footer", () => {
  it("has a New folder button that asks for a new folder", async () => {
    const wrapper = mountSidebar();

    await wrapper.find("button.new-folder").trigger("click");

    expect(wrapper.emitted("newFolder")).toHaveLength(1);
  });

  it("shows New folder even with no chats, and disables it at the folder limit", () => {
    const empty = mountSidebar({ conversations: [] });
    expect(empty.find("button.new-folder").exists()).toBe(true);

    const full = mountSidebar({ folders: Array.from({ length: 30 }, (_, i) => folder(i + 1)) });
    expect(full.find("button.new-folder").attributes("disabled")).toBeDefined();
  });

  it("is hidden while searching or selecting", async () => {
    expect(searching([hit("1")]).find("button.new-folder").exists()).toBe(false);

    const wrapper = mountSidebar();
    await wrapper.find("button.link").trigger("click"); // Select
    expect(wrapper.find("button.new-folder").exists()).toBe(false);
  });
});
```
(The `Select` button is the first `button.link` in the footer today; if the test file already finds it another way, reuse that.)

- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run src/components/ConversationSidebar.test.ts`
Expected: the new tests FAIL, and the old tests that clicked the removed icons fail (they are the ones changed in (b)).

- [ ] **Step 3: Implement**

In `ember_web/src/components/ConversationSidebar.vue`:

ChatRow changes first:

In `ember_web/src/components/ChatRow.vue`:

1. Import: `import type { MenuPoint } from "./menuPoint";`.
2. Emits: remove `delete: [];` and add `openMenu: [point: MenuPoint];`.
3. Script, add after `onClick`:
```ts
const moreButton = ref<HTMLButtonElement | null>(null);

function openFromButton(): void {
  const box = moreButton.value?.getBoundingClientRect();
  emit("openMenu", { x: box?.left ?? 0, y: box?.bottom ?? 0, trigger: moreButton.value });
}

function openFromContext(event: MouseEvent): void {
  if (props.selecting || props.renaming) return; // the browser's own menu, as before
  event.preventDefault();
  emit("openMenu", { x: event.clientX, y: event.clientY, trigger: moreButton.value });
}
```
4. Template: add `@contextmenu="openFromContext"` to the `<li>`. Replace the two buttons (pencil `button.icon` and `button.icon.delete`) in the final `<template v-else>` with:
```vue
      <button
        ref="moreButton"
        type="button"
        class="icon more"
        title="Chat actions"
        aria-label="Chat actions"
        aria-haspopup="menu"
        @click.stop="openFromButton"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <circle cx="5" cy="12" r="1.8" fill="currentColor" />
          <circle cx="12" cy="12" r="1.8" fill="currentColor" />
          <circle cx="19" cy="12" r="1.8" fill="currentColor" />
        </svg>
      </button>
```
5. Styles: delete the `.delete:hover:not(:disabled)` rule (the delete button is gone); keep `.icon` rules (the "..." button uses `.icon`). `lockedHere` stays a prop (it still disables the tick box).


Then the sidebar.

Script changes:
1. Imports: `import { computed, nextTick, ref, watch } from "vue";` (keep what is used), plus
```ts
import { MAX_FOLDERS, type ChatFolder } from "../api/FoldersClient";
import { buildLayout } from "../utils/chatSections";
import { chatMenuItems, folderMenuItems, parseChatChoice } from "../utils/chatMenu";
import ChatSection from "./ChatSection.vue";
import PopupMenu from "./PopupMenu.vue";
import type { MenuPoint } from "./menuPoint";
```
2. Props: add `folders?: ChatFolder[]; collapsedFolders?: number[];` to the props type and defaults `folders: () => [], collapsedFolders: () => []`.
3. Emits: add
```ts
  pin: [id: string, pinned: boolean];
  /** folderId null: out of its folder. */
  move: [id: string, folderId: number | null];
  /** "Move to > New folder...": the parent creates a folder, then moves the chat into it. */
  moveNew: [id: string];
  toggleFolder: [id: number];
  newFolder: [];
  renameFolder: [folder: ChatFolder];
  deleteFolder: [folder: ChatFolder];
```
4. After the rename state, add:
```ts
const layout = computed(() => buildLayout(props.conversations, props.folders));

const SECTION_TITLES = { pinned: "Pinned", unfiled: "Chats" } as const;
function titleOf(section: { kind: "pinned" | "folder" | "unfiled"; folder: ChatFolder | null }): string | null {
  if (!layout.value.grouped) return null;
  return section.kind === "folder" ? (section.folder?.name ?? "") : SECTION_TITLES[section.kind];
}

// The open popup menu: for a chat row or for a folder header, with where it
// opened and the button that gets focus back after Esc.
type OpenMenu =
  | ({ kind: "chat"; chat: Conversation } & MenuPoint)
  | ({ kind: "folder"; folder: ChatFolder } & MenuPoint);
const menu = ref<OpenMenu | null>(null);

const menuItems = computed(() => {
  const m = menu.value;
  if (!m) return [];
  return m.kind === "chat" ? chatMenuItems(m.chat, props.folders, isLocked(m.chat)) : folderMenuItems();
});

function openChatMenu(chat: Conversation, point: MenuPoint): void {
  menu.value = { kind: "chat", chat, ...point };
}

function openFolderMenu(folder: ChatFolder, point: MenuPoint): void {
  menu.value = { kind: "folder", folder, ...point };
}

/** Esc, a press outside, Tab or a resize: focus goes back to the button. */
async function dismissMenu(): Promise<void> {
  const trigger = menu.value?.trigger ?? null;
  menu.value = null;
  await nextTick();
  trigger?.focus();
}

function chooseFromMenu(id: string): void {
  const open = menu.value;
  menu.value = null; // a choice hands focus on (a rename box, a dialog), so it is not given back
  if (!open) return;
  if (open.kind === "folder") {
    if (id === "rename") emit("renameFolder", open.folder);
    else if (id === "delete") emit("deleteFolder", open.folder);
    return;
  }
  const choice = parseChatChoice(id);
  if (!choice) return;
  const chat = open.chat;
  switch (choice.action) {
    case "pin":
      emit("pin", chat.id, true);
      break;
    case "unpin":
      emit("pin", chat.id, false);
      break;
    case "rename":
      renamingId.value = chat.id;
      break;
    case "delete":
      confirmDelete(chat);
      break;
    case "move":
      emit("move", chat.id, choice.folderId);
      break;
    case "moveNew":
      emit("moveNew", chat.id);
      break;
  }
}
```
Keep `confirmDelete`, but change its text to `Delete "${c.title}"? This can't be undone.` only if it differs (it already uses that text; do not change it) and keep `emit("delete", c.id)`.
Also hide the menu if the search starts or select mode starts: in the existing `watch(() => props.searchActive, ...)` add `menu.value = null;` when active, and in `startSelecting` add `menu.value = null;`.

Template changes (replace the `<ul v-else class="list"> ... </ul>` chat list block, and the footer):

```vue
    <p v-else-if="conversations.length === 0 && folders.length === 0" class="empty">{{ loading ? "Loading chats …" : "No saved chats yet." }}</p>
    <div v-else class="sections">
      <ChatSection
        v-for="s in layout.sections"
        :key="s.key"
        :title="titleOf(s)"
        :count="s.chats.length"
        :collapsible="s.kind === 'folder'"
        :collapsed="s.kind === 'folder' && s.folder !== null && collapsedFolders.includes(s.folder.id)"
        :menu="s.kind === 'folder'"
        @toggle="s.folder && emit('toggleFolder', s.folder.id)"
        @open-menu="(point) => s.folder && openFolderMenu(s.folder, point)"
      >
        <ChatRow
          v-for="c in s.chats"
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
          @open-menu="(point) => openChatMenu(c, point)"
        />
      </ChatSection>
    </div>

    <PopupMenu
      v-if="menu"
      :items="menuItems"
      :x="menu.x"
      :y="menu.y"
      :label="menu.kind === 'chat' ? 'Chat actions' : 'Folder actions'"
      @select="chooseFromMenu"
      @close="dismissMenu"
    />
```
The `.hit` search branch (`<template v-if="searchActive">`) is unchanged. The footer block becomes:
```vue
    <div v-if="selecting" class="select-bar"> ...unchanged... </div>
    <div v-else-if="!searchActive" class="footer">
      <button
        type="button"
        class="link new-folder"
        :disabled="folders.length >= MAX_FOLDERS"
        :title="folders.length >= MAX_FOLDERS ? `${MAX_FOLDERS} folders is the limit` : 'Create a folder'"
        @click="emit('newFolder')"
      >
        New folder
      </button>
      <template v-if="conversations.length > 0">
        <button type="button" class="link" @click="startSelecting">Select</button>
        <button v-if="conversations.length > 1" type="button" class="link delete-all" :disabled="locked" @click="confirmDeleteAll">
          Delete all chats
        </button>
      </template>
    </div>
```
Check the footer's existing CSS (`.footer { justify-content: space-between }`): with three buttons use `flex-wrap: wrap; justify-content: space-between` so they wrap in 260 px. Add `.sections { display: flex; flex-direction: column; gap: 10px; }`. The `.list` rule can stay for the hit list. Remove the sidebar's now-unused `.row.ticked` only if nothing uses it (ChatRow root still gets it: keep).

Existing test `shows a Select button next to Delete all` expects `.delete-all` and Select in the footer: they still exist when there are chats. A test that expects the footer to be absent with zero chats must be updated to expect only the New folder button (list those changes in your report).

- [ ] **Step 4: Run tests, type-check, build**

Run: `npx vitest run src/components && npx vue-tsc -b --noEmit && npx vite build` (delete `dist/` afterwards).
Expected: all pass; vue-tsc silent; the build has no CSS warnings.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/components/ConversationSidebar.vue ember_web/src/components/ConversationSidebar.test.ts
git commit -m "feat(ember_web): sidebar sections, row and folder menus, New folder button"
```

---

### Task 6: `FolderDialogs.vue`

**Files:**
- Create: `ember_web/src/components/FolderDialogs.vue`, `ember_web/src/components/FolderDialogs.test.ts`

**Interfaces:**
- Consumes: `BaseModal`, `useFoldersStore` (`create`, `rename`, `remove`), `FOLDER_NAME_MAX`, `ChatFolder`, `errorMessage` from `../utils/errors`.
- Produces: `FolderDialogs` exposing (via `defineExpose`) `openCreate(onCreated?: (folder: ChatFolder) => void): void`, `openRename(folder: ChatFolder): void`, `openDelete(folder: ChatFolder, chatCount: number): void`. It renders at most one dialog at a time. Create and rename: a name field (maxlength 60, trimmed, Save disabled while blank or busy), errors from the store shown in the dialog (role alert), closing on success. Delete: the text `Delete folder "<name>" and its <n> chat(s)? This can't be undone.` with Cancel and a danger Delete button; an error is shown in the dialog and the dialog stays open.

- [ ] **Step 1: Write the failing tests**

Create `ember_web/src/components/FolderDialogs.test.ts`:

```ts
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
```
If jsdom's `<dialog>` support differs from the shims above, adjust the shims in the test only (not the component).

- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run src/components/FolderDialogs.test.ts`
Expected: FAIL (`FolderDialogs.vue` not found).

- [ ] **Step 3: Implement**

Create `ember_web/src/components/FolderDialogs.vue`:

```vue
<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { FOLDER_NAME_MAX, type ChatFolder } from "../api/FoldersClient";
import { useFoldersStore } from "../stores/folders";
import { errorMessage } from "../utils/errors";
import BaseModal from "./BaseModal.vue";

// The folder dialogs of the chat page (new, rename, delete), driven from the
// outside through the exposed open* methods. One dialog at a time. Every
// failure ember_api reports (a duplicate name, the folder limit, a chat that is
// still answering) is shown inside the dialog, which stays open.
type Mode =
  | { kind: "create"; onCreated?: (folder: ChatFolder) => void }
  | { kind: "rename"; folder: ChatFolder }
  | { kind: "delete"; folder: ChatFolder; chatCount: number };

const store = useFoldersStore();

const mode = ref<Mode | null>(null);
const name = ref("");
const error = ref("");
const busy = ref(false);
const nameInput = ref<HTMLInputElement | null>(null);

const title = computed(() => {
  switch (mode.value?.kind) {
    case "create":
      return "New folder";
    case "rename":
      return "Rename folder";
    case "delete":
      return "Delete folder";
    default:
      return "";
  }
});
const canSave = computed(() => name.value.trim() !== "" && !busy.value);
const deleteText = computed(() => {
  const m = mode.value;
  if (m?.kind !== "delete") return "";
  return `Delete folder "${m.folder.name}" and its ${m.chatCount} ${m.chatCount === 1 ? "chat" : "chats"}? This can't be undone.`;
});

function begin(next: Mode, initialName = ""): void {
  mode.value = next;
  name.value = initialName;
  error.value = "";
  busy.value = false;
  void nextTick(() => nameInput.value?.focus());
}

function openCreate(onCreated?: (folder: ChatFolder) => void): void {
  begin({ kind: "create", onCreated });
}
function openRename(folder: ChatFolder): void {
  begin({ kind: "rename", folder }, folder.name);
}
function openDelete(folder: ChatFolder, chatCount: number): void {
  begin({ kind: "delete", folder, chatCount });
}
defineExpose({ openCreate, openRename, openDelete });

function close(): void {
  mode.value = null;
}

async function save(): Promise<void> {
  const m = mode.value;
  if (!m || m.kind === "delete" || !canSave.value) return;
  const trimmed = name.value.replace(/\s+/g, " ").trim();
  busy.value = true;
  error.value = "";
  try {
    if (m.kind === "create") {
      const folder = await store.create(trimmed);
      close();
      m.onCreated?.(folder);
    } else {
      if (trimmed !== m.folder.name) await store.rename(m.folder.id, trimmed);
      close();
    }
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    busy.value = false;
  }
}

async function confirmDelete(): Promise<void> {
  const m = mode.value;
  if (m?.kind !== "delete" || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await store.remove(m.folder.id);
    close();
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseModal :open="mode !== null" :title="title" @close="close">
    <form v-if="mode && mode.kind !== 'delete'" class="form" @submit.prevent="save">
      <label>
        Name
        <input ref="nameInput" v-model="name" type="text" :maxlength="FOLDER_NAME_MAX" autocomplete="off" />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button type="button" class="ghost" @click="close">Cancel</button>
        <button type="submit" class="primary" :disabled="!canSave">{{ busy ? "Saving …" : "Save" }}</button>
      </div>
    </form>
    <div v-else-if="mode" class="form">
      <p class="confirm">{{ deleteText }}</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button type="button" class="ghost" @click="close">Cancel</button>
        <button type="button" class="danger" :disabled="busy" @click="confirmDelete">{{ busy ? "Deleting …" : "Delete" }}</button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.9em;
  color: var(--muted);
}
input[type="text"] {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  outline: none;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
input[type="text"]:focus {
  border-color: var(--accent);
}
.confirm {
  margin: 0;
}
.error {
  margin: 0;
  color: var(--danger);
  font-size: 0.9em;
}
.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
button {
  padding: 7px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
button:disabled {
  cursor: default;
  opacity: 0.5;
}
.primary {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.danger {
  border-color: var(--danger);
  color: var(--danger);
}
.ghost {
  background: transparent;
}
</style>
```

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/components/FolderDialogs.test.ts && npx vue-tsc -b --noEmit`
Expected: all pass; vue-tsc silent.

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/components/FolderDialogs.vue ember_web/src/components/FolderDialogs.test.ts
git commit -m "feat(ember_web): create, rename and delete folder dialogs"
```

---

### Task 7: Wire it into `ChatView`, the fake API and the e2e test

**Files:**
- Modify: `ember_web/src/views/ChatView.vue`
- Modify: `ember_web/e2e/fakeApi.ts`, `ember_web/e2e/chat.spec.ts`

**Interfaces:**
- Consumes: everything above. `ChatView` passes `folders` (display order) and `collapsedFolders` to the sidebar, loads folders on mount, and connects the new sidebar events.

- [ ] **Step 1: Wire `ChatView.vue`**

In the script (imports at the top, state after `const chat = useChatStore();`):

```ts
import FolderDialogs from "../components/FolderDialogs.vue";
import { useFolderCollapse } from "../composables/useFolderCollapse";
import { useFoldersStore } from "../stores/folders";
import type { ChatFolder } from "../api/FoldersClient";

const folderStore = useFoldersStore();
const folderCollapse = useFolderCollapse();
const folderDialogs = ref<InstanceType<typeof FolderDialogs> | null>(null);

onMounted(() => void folderStore.ensureLoaded());

function chatsIn(folder: ChatFolder): number {
  return chat.sortedConversations.filter((c) => c.folderId === folder.id).length;
}

/** "Move to > New folder...": make the folder, then put the chat in it. */
function moveToNewFolder(chatId: string): void {
  folderDialogs.value?.openCreate((folder) => chat.setChatFolder(chatId, folder.id));
}
```
(`ref` and `onMounted` are already imported in ChatView; reuse the existing `onMounted` import, adding a second `onMounted` call is fine.)

In the template, pass to `<ConversationSidebar>` the new props and listeners (next to the existing ones):
```vue
      :folders="folderStore.folders"
      :collapsed-folders="folderCollapse.collapsed.value"
      @pin="chat.setChatPinned"
      @move="chat.setChatFolder"
      @move-new="moveToNewFolder"
      @toggle-folder="folderCollapse.toggle"
      @new-folder="folderDialogs?.openCreate()"
      @rename-folder="(f) => folderDialogs?.openRename(f)"
      @delete-folder="(f) => folderDialogs?.openDelete(f, chatsIn(f))"
```
and add `<FolderDialogs ref="folderDialogs" />` once, as a sibling inside the root `<section class="chat-view">` (the dialogs are `<dialog>` elements shown modally, so their place does not matter).

- [ ] **Step 2: Extend the fake API**

In `ember_web/e2e/fakeApi.ts`:
- `StoredChat` gets `folder_id?: number | null; pinned?: boolean;`.
- `summary(chat)` adds `folder_id: chat.folder_id ?? null, pinned: chat.pinned ?? false,`.
- `FakeApi` gets `folders: Map<number, { id: number; name: string; position: number }>;` and `installFakeApi` initialises `folders: new Map()`.
- Before the `chatPath` block add the folder routes:

```ts
    if (method === "GET" && path === "/api/chat-folders") {
      return json(route, [...api.folders.values()].map((f) => ({ ...f, chat_count: [...api.chats.values()].filter((c) => c.folder_id === f.id).length })));
    }
    if (method === "POST" && path === "/api/chat-folders") {
      const { name } = request.postDataJSON() as { name: string };
      if ([...api.folders.values()].some((f) => f.name.toLowerCase() === name.toLowerCase())) {
        return json(route, { detail: "A folder with that name already exists" }, 409);
      }
      const id = api.folders.size + 1;
      api.folders.set(id, { id, name, position: id });
      return json(route, { id, name, position: id, chat_count: 0 }, 201);
    }
    const folderPath = /^\/api\/chat-folders\/(\d+)$/.exec(path);
    if (folderPath) {
      const id = Number(folderPath[1]);
      const found = api.folders.get(id);
      if (!found) return json(route, { detail: "Folder not found" }, 404);
      if (method === "PATCH") {
        const body = request.postDataJSON() as { name?: string; position?: number };
        Object.assign(found, body);
        return json(route, { ...found, chat_count: 0 });
      }
      if (method === "DELETE") {
        for (const [chatId, c] of api.chats) if (c.folder_id === id) api.chats.delete(chatId);
        api.folders.delete(id);
        return route.fulfill({ status: 204, body: "" });
      }
    }
```
- In the `chatPath` block add (before the `POST /turns` line):
```ts
      if (method === "PATCH" && !tail) {
        const chat = api.chats.get(id!);
        if (!chat) return json(route, { detail: "Chat not found" }, 404);
        const body = request.postDataJSON() as { title?: string; folder_id?: number | null; pinned?: boolean };
        if (body.title !== undefined) chat.title = body.title;
        if ("folder_id" in body) chat.folder_id = body.folder_id ?? null;
        if (body.pinned !== undefined) chat.pinned = body.pinned;
        return json(route, summary(chat));
      }
```

- [ ] **Step 3: Add the e2e scenario**

Read `ember_web/e2e/chat.spec.ts` (its login steps) and append a second test to it that mirrors those login steps and then:
1. Before navigating, seeds `api.chats.set("seed-chat-0001", { id: "seed-chat-0001", title: "Seeded chat", agent_id: "agent-1", messages: [{ role: "user", content: "hi" }, { role: "assistant", content: "hello" }], running: false })`.
2. After logging in, in the sidebar (`page.getByRole("complementary")`): clicks "New folder", types `Work` into the name field, clicks "Save", and expects a header named "Work" to be visible.
3. Opens the seeded chat's "Chat actions" menu, chooses "Move to...", then the folder "Work"; expects the seeded chat to be listed under the Work group and `api.chats.get("seed-chat-0001")?.folder_id` to equal `1`.
4. Opens the chat's menu and chooses "Pin"; expects a "Pinned" header; expects the fake's `pinned` to be `true`.
5. Opens the "Folder actions" menu on the Work header, chooses "Delete", expects the dialog text to contain `Delete folder "Work" and its 1 chat? This can't be undone.`, clicks "Delete" in the dialog, expects the Work header to disappear. (The pinned chat is deleted with its folder: its `folder_id` was kept when pinned, so it goes with it; assert `api.chats.has("seed-chat-0001")` is `false` and the Pinned header is gone.)
6. Finally `expect(api.unexpected).toEqual([])`.
Use `getByRole("menuitem", { name: ... })` for menu entries (they live in the page body, not inside the sidebar) and `getByRole("dialog")` for the dialog.

- [ ] **Step 4: Verify**

Run from `ember_web/`: `npx vue-tsc -b --noEmit`, `npm test`, `npx vite build` (then delete `dist/`), and `npm run test:e2e`. If the e2e run cannot start because the Playwright browser is not installed, say exactly that in the report and do not install anything; the unit tests and the build are then the evidence, and the user will run the e2e test.
Expected: all pass (1129 plus the tests added in Tasks 1 to 6).

- [ ] **Step 5: Commit**

```bash
git add ember_web/src/views/ChatView.vue ember_web/e2e
git commit -m "feat(ember_web): folders and pins in the chat page, with fake-API routes and an e2e scenario"
```

---

## Self-review

**Spec coverage (phase 4 section):** row "..." menu with Pin, Move to... flyout, Rename, Delete and right-click (Tasks 3 to 5); flyout with check mark, No folder, New folder... and overlay fallback (Task 3); folder header menu and New folder button (Tasks 4 and 5); `BaseModal` dialogs with server errors and the delete text and 409 handling (Task 6); layout rules including always-shown folders and the flat fallback (Task 2); answering-chat rules and the 30-folder limit (Tasks 2 and 5); Teleport and keyboard behavior (Task 3); collapse state in `localStorage` (Task 2); counts from the chat store (`chatsIn`, Task 7, and section counts, Task 5); carry-overs: `ensureLoaded` promise and list-sequence guard (Task 1), undefined `folderId` as unfiled (Task 2), fakeApi (Task 7), spec text (done in the spec commit). Not here by design: drag and drop (phase 5), folder reordering UI, folder names in search hits.

**Placeholders:** none. Task 5 (b) and (c) tell the implementer to adapt a few existing tests whose way of starting an action changed; each is named and the rule is explicit (keep assertions, change only the trigger, list each change in the report). Task 7 Step 3 describes the e2e steps with exact assertions because the spec file's login helper has to be read first.

**Type consistency:** `MenuItem`, `MenuPoint`, `ChatLayout`/`ChatSection`, `ChatChoice`, the sidebar's new props and emits, `FolderDialogs`' exposed methods, and the store method names (`setChatFolder`, `setChatPinned`, `forgetFolder`, `ensureLoaded`) use the same names in every task.
