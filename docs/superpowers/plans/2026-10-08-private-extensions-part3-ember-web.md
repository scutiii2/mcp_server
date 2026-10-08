# Private Extensions, Part 3: ember_web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user can add, edit, enable, disable and remove their own MCP servers from the Supermarket ("My extensions"), see the enabled ones as cards on the Capabilities page, and is told in the chat when one could not be used.

**Architecture:** A `userExtensions` Pinia store over a new `UserExtensionsClient` (the `/api/user-extensions` routes from part 2). A `UserExtensionModal` for add and edit. `SupermarketView` and `CapabilitiesView` each gain a section that reads the store. The chat store handles the new `notice` turn event and `ChatView` shows it in a small banner until the next question.

**Tech Stack:** Vue 3, TypeScript, Pinia, vue-router, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-08-private-extensions-design.md` (its `ember_web` section). Parts 1 (`ai_agent`) and 2 (`ember_api`) are merged.

## Global Constraints

- All work is in `apps/ember_web`; run tests from there: `npx vitest run <path>`; type check and build: `npm run build`; e2e: `npx playwright test <spec>`.
- API shape (from part 2): `{id, label, description, url, header_names, enabled, status, error, tools}`; `status` is `connected`, `error` or `unknown`. Header **values** never come back from the server; only names.
- Headers: editing replaces the whole set. The modal sends `headers` only when the user chose to replace them (an empty set removes them all). Value inputs are masked (`type="password"`) and never pre-filled.
- Private tools work for the agent only: the Capabilities card has no run button, no resources, and no Open button.
- A private extension is "added" when it is enabled. The Supermarket row says **Enable** / **Enabled** / **Disable** (the built-in and server-listed rows keep **Add** / **Added** / **Disable**).
- Remove uses the in-app `ConfirmModal`, not type-to-confirm.
- The notice banner shows until the next question, a new chat, another chat, or the user's Dismiss.
- ember_web UI follows the `ember-design-system` skill: tokens only (no hex colours, no literal px radius), pill buttons, `:focus-visible` ring, icon-only controls need an `aria-label`, in-app confirms.
- Project workflow rules: each ember_web task starts with a checkpoint where the change is described to the user and approved before editing. Do not spawn browser-verification agents; the user tests the UI by hand. Never run git at `D:\User\Documents\Programming`; run git inside this repo.
- Commit style: `feat(ember_web): ...`. Do not add Co-Authored-By lines when ChatGPT executes this plan; Claude adds `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## File Structure

Create:
- `src/api/UserExtensionsClient.ts`, `src/stores/userExtensions.ts` (+ test)
- `src/utils/userExtensions.ts` (+ test): `userExtensionSummary`, `matchesUserExtension`
- `src/components/UserExtensionModal.vue` (+ test)
- `src/components/TurnNotices.vue` (+ test), `src/stores/chat.notices.test.ts`

Modify:
- `src/components/SupermarketItem.vue` (+ test): `addLabel`, `addedLabel`, `detail`
- `src/views/SupermarketView.vue` (+ test), `src/views/CapabilitiesView.vue` (+ test)
- `src/api/types.ts` (`TurnNotice`, the `notice` event), `src/stores/chat.ts`, `src/views/ChatView.vue`
- `e2e/fakeApi.ts`, `e2e/capabilities.spec.ts`, `README.md`, and the spec.

---

### Task 0: Fold what the investigation found back into the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-08-private-extensions-design.md`

- [ ] **Step 1: Edit the spec's `ember_web` section**

1. Replace the `UserExtensionModal.vue` bullet's sentence about editing headers ("On edit, the existing header **names** are shown with an empty value and the note "Leave blank to keep the saved value"; headers are sent only if the user changed any, as the whole set.") with: "On edit, the saved header **names** are listed and the editor stays closed. **Replace headers** opens an empty editor; saving then sends the whole new set (none removes them all). Without it, `headers` is not sent and the saved ones stay. If the address changes to another host and the headers are not being replaced, the modal says the saved headers will be removed (that is what `ember_api` does)."
2. In the **My extensions** bullet, replace "with **Enable** or **Disable**, **Edit** and **Remove**" with "with **Enable** (shown as **Enabled** once on) or **Disable**, **Edit** and **Remove**; a row that cannot be reached shows the reason under its name".
3. In the notice bullet ("The chat shows a `notice` turn event as a small line under the answer.") replace with: "The chat shows a `notice` turn event as a banner above the messages ("<label> wasn't used in this answer: <reason>") until the next question, a new chat, another chat, or Dismiss. A watcher that joins after the notice was sent does not see it."
4. Add to the `ember_web` section: "A `userExtensions` store loads the account's extensions at sign-in (accounts with `chat.use`); the Supermarket and the Capabilities page refresh it when they open, because the status comes from a live probe."

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-10-08-private-extensions-design.md docs/superpowers/plans/2026-10-08-private-extensions-part3-ember-web.md
git commit -m "docs: private extensions spec refinements for ember_web; part 3 plan"
```

---

### Task 1: Client, store and summary helpers

**Checkpoint:** before editing, tell the user in two sentences that this adds an API client, a store and two small helpers (no UI yet), and wait for a yes.

**Files:**
- Create: `apps/ember_web/src/api/UserExtensionsClient.ts`
- Create: `apps/ember_web/src/stores/userExtensions.ts`
- Create: `apps/ember_web/src/utils/userExtensions.ts`
- Test: `apps/ember_web/src/stores/userExtensions.test.ts`, `apps/ember_web/src/utils/userExtensions.test.ts`

**Interfaces:**
- Produces: type `UserExtension`; `UserExtensionInput {label, url, description?, headers?}`; `UserExtensionPatch` (any of the input fields plus `enabled`); `userExtensionsClient.{list, create, update, remove}`.
- Produces: `useUserExtensionsStore()` with refs `items: UserExtension[]`, `ready: boolean`, `error: string`, and functions `refresh(): Promise<void>`, `add(input): Promise<UserExtension>`, `update(id, patch): Promise<UserExtension>`, `remove(id): Promise<void>`, `setEnabled(id, on): Promise<void>`. `add`, `update` and `remove` let the API error propagate (the modal shows it); `setEnabled` rolls back and sets `error`.
- Produces: `userExtensionSummary(item): string`, `matchesUserExtension(item, query): boolean`.

- [ ] **Step 1: Write the client**

Create `apps/ember_web/src/api/UserExtensionsClient.ts`:

```ts
import { apiRequest } from "./http";

/** One of the account's own MCP servers. `status` comes from a live probe by
 * ai_agent (cached a minute by ember_api): "connected", "error" (it could not be
 * reached), or "unknown" (not checked). Header values are never sent back, only
 * their names. */
export interface UserExtension {
  id: string;
  label: string;
  description: string;
  url: string;
  header_names: string[];
  enabled: boolean;
  status: "connected" | "error" | "unknown" | string;
  error: string | null;
  tools: string[];
}

export interface UserExtensionInput {
  label: string;
  url: string;
  description?: string;
  /** Replaces every saved header; leave it out to keep them. */
  headers?: Record<string, string>;
}

export type UserExtensionPatch = Partial<UserExtensionInput> & { enabled?: boolean };

const enc = encodeURIComponent;

/** ember_api's /api/user-extensions routes (chat.use, own rows only). */
export const userExtensionsClient = {
  list: () => apiRequest<UserExtension[]>("GET", "/api/user-extensions"),
  create: (input: UserExtensionInput) => apiRequest<UserExtension>("POST", "/api/user-extensions", input),
  update: (id: string, patch: UserExtensionPatch) =>
    apiRequest<UserExtension>("PATCH", `/api/user-extensions/${enc(id)}`, patch),
  remove: (id: string) => apiRequest<void>("DELETE", `/api/user-extensions/${enc(id)}`),
};
```

- [ ] **Step 2: Write the failing helper tests**

Create `apps/ember_web/src/utils/userExtensions.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { UserExtension } from "../api/UserExtensionsClient";
import { matchesUserExtension, userExtensionSummary } from "./userExtensions";

const base: UserExtension = {
  id: "notes",
  label: "My notes",
  description: "",
  url: "https://notes.example.com/mcp",
  header_names: [],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search", "add"],
};

describe("userExtensionSummary", () => {
  it("counts the tools of a connected extension", () => {
    expect(userExtensionSummary(base)).toBe("2 tools");
    expect(userExtensionSummary({ ...base, tools: ["search"] })).toBe("1 tool");
    expect(userExtensionSummary({ ...base, tools: [] })).toBe("0 tools");
  });

  it("says why it brings nothing", () => {
    expect(userExtensionSummary({ ...base, enabled: false })).toBe("Not enabled");
    expect(userExtensionSummary({ ...base, status: "error", error: "Timed out" })).toBe("Not connected");
    expect(userExtensionSummary({ ...base, status: "unknown", error: "Couldn't check right now" })).toBe("Not checked yet");
  });
});

describe("matchesUserExtension", () => {
  it("matches everything for a blank query", () => {
    expect(matchesUserExtension(base, "")).toBe(true);
    expect(matchesUserExtension(base, "   ")).toBe(true);
  });

  it("matches the label, the id and the tool names, ignoring case", () => {
    expect(matchesUserExtension(base, "NOTES")).toBe(true);
    expect(matchesUserExtension(base, "notes")).toBe(true);
    expect(matchesUserExtension(base, "sear")).toBe(true);
    expect(matchesUserExtension(base, "zzz")).toBe(false);
  });
});
```

- [ ] **Step 3: Run to verify failure, then write the helpers**

Run: `npx vitest run src/utils/userExtensions.test.ts` — Expected: FAIL (module not found).

Create `apps/ember_web/src/utils/userExtensions.ts`:

```ts
import type { UserExtension } from "../api/UserExtensionsClient";

/** The short pill text of a private extension: what it brings, or why it brings nothing. */
export function userExtensionSummary(item: UserExtension): string {
  if (!item.enabled) return "Not enabled";
  if (item.status === "connected") return `${item.tools.length} tool${item.tools.length === 1 ? "" : "s"}`;
  if (item.status === "error") return "Not connected";
  return "Not checked yet";
}

/** Whether `item` matches the filter typed on the Capabilities page (label, id or a tool name). */
export function matchesUserExtension(item: UserExtension, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [item.label, item.id, ...item.tools].some((text) => text.toLowerCase().includes(needle));
}
```

Run: `npx vitest run src/utils/userExtensions.test.ts` — Expected: PASS.

- [ ] **Step 4: Write the failing store tests**

Create `apps/ember_web/src/stores/userExtensions.test.ts`:

```ts
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
```

- [ ] **Step 5: Run to verify failure, then write the store**

Run: `npx vitest run src/stores/userExtensions.test.ts` — Expected: FAIL (module not found).

Create `apps/ember_web/src/stores/userExtensions.ts`:

```ts
import { defineStore } from "pinia";
import { ref, watch } from "vue";
import {
  userExtensionsClient,
  type UserExtension,
  type UserExtensionInput,
  type UserExtensionPatch,
} from "../api/UserExtensionsClient";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";

/** The account's own MCP servers ("private extensions"), kept in ember_api.
 * Loaded at sign-in for accounts with chat.use and dropped when the account
 * changes; the Supermarket and the Capabilities page call `refresh()` when they
 * open, because each one's status comes from a live probe. `add`, `update` and
 * `remove` let the API's error propagate (the modal shows it); `setEnabled`
 * shows the change at once and rolls it back, with `error`, if the save fails. */
export const useUserExtensionsStore = defineStore("userExtensions", () => {
  const auth = useAuthStore();

  const items = ref<UserExtension[]>([]);
  const ready = ref(false);
  const error = ref("");
  // Bumped on every account change: answers for the previous account are ignored.
  let generation = 0;

  async function refresh(): Promise<void> {
    const started = generation;
    try {
      const list = await userExtensionsClient.list();
      if (started !== generation) return;
      items.value = list;
      ready.value = true;
      error.value = "";
    } catch (err) {
      if (started === generation) error.value = errorMessage(err);
    }
  }

  watch(
    () => (auth.hasPermission("chat.use") ? (auth.account?.id ?? null) : null),
    (id) => {
      generation += 1;
      items.value = [];
      ready.value = false;
      error.value = "";
      if (id !== null) void refresh();
    },
    { immediate: true },
  );

  function put(item: UserExtension): void {
    const index = items.value.findIndex((i) => i.id === item.id);
    if (index === -1) items.value = [...items.value, item];
    else items.value = items.value.map((i) => (i.id === item.id ? item : i));
  }

  async function add(input: UserExtensionInput): Promise<UserExtension> {
    const started = generation;
    const created = await userExtensionsClient.create(input);
    if (started === generation) put(created);
    return created;
  }

  async function update(id: string, patch: UserExtensionPatch): Promise<UserExtension> {
    const started = generation;
    const updated = await userExtensionsClient.update(id, patch);
    if (started === generation) put(updated);
    return updated;
  }

  async function remove(id: string): Promise<void> {
    const started = generation;
    await userExtensionsClient.remove(id);
    if (started === generation) items.value = items.value.filter((i) => i.id !== id);
  }

  async function setEnabled(id: string, on: boolean): Promise<void> {
    const started = generation;
    const before = items.value.find((i) => i.id === id);
    if (!before) return;
    error.value = "";
    put({ ...before, enabled: on });
    try {
      const updated = await userExtensionsClient.update(id, { enabled: on });
      if (started === generation) put(updated);
    } catch (err) {
      if (started !== generation) return;
      put(before);
      error.value = errorMessage(err);
    }
  }

  return { items, ready, error, refresh, add, update, remove, setEnabled };
});
```

Run: `npx vitest run src/stores/userExtensions.test.ts src/utils/userExtensions.test.ts` — Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ember_web/src/api/UserExtensionsClient.ts apps/ember_web/src/stores/userExtensions.ts apps/ember_web/src/stores/userExtensions.test.ts apps/ember_web/src/utils/userExtensions.ts apps/ember_web/src/utils/userExtensions.test.ts
git commit -m "feat(ember_web): userExtensions store and client"
```

---

### Task 2: The add and edit modal

**Checkpoint:** before editing, tell the user in three sentences what the modal does (label, address, description, optional masked headers; editing keeps saved headers unless Replace headers is used) and wait for a yes.

**Files:**
- Create: `apps/ember_web/src/components/UserExtensionModal.vue`
- Test: `apps/ember_web/src/components/UserExtensionModal.test.ts`

**Interfaces:**
- Consumes: `useUserExtensionsStore()` (`add`, `update`) from Task 1; `BaseModal` (props `open`, `title`; emits `close`).
- Produces: component `UserExtensionModal` with props `open: boolean`, `extension: UserExtension | null` (null = add) and emits `close`, `saved(extension: UserExtension)`.

- [ ] **Step 1: Write the failing tests**

Create `apps/ember_web/src/components/UserExtensionModal.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Account } from "../api/AuthClient";
import { ApiError } from "../api/http";
import { userExtensionsClient, type UserExtension } from "../api/UserExtensionsClient";
import { useAuthStore } from "../stores/auth";
import UserExtensionModal from "./UserExtensionModal.vue";

vi.mock("../api/UserExtensionsClient", () => ({
  userExtensionsClient: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const client = vi.mocked(userExtensionsClient);

const SAVED: UserExtension = {
  id: "notes",
  label: "Notes",
  description: "work",
  url: "https://notes.example.com/mcp",
  header_names: ["X-Key"],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search"],
};
const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: ["chat.use"] };

function open(extension: UserExtension | null = null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = ACCOUNT;
  return mount(UserExtensionModal, { props: { open: true, extension }, global: { plugins: [pinia] } });
}

const type = (w: ReturnType<typeof open>, name: string, value: string) => w.get(`input[name=${name}]`).setValue(value);

beforeEach(() => {
  // jsdom has no modal dialogs.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  vi.resetAllMocks();
  client.list.mockResolvedValue([]);
});

describe("adding", () => {
  it("sends the label, address and description, and no headers when none were typed", async () => {
    client.create.mockResolvedValue({ ...SAVED, id: "mine" });
    const w = open();
    await type(w, "label", "Mine");
    await type(w, "url", "https://mine.example.com/mcp");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.create).toHaveBeenCalledWith({ label: "Mine", url: "https://mine.example.com/mcp", description: "" });
    expect(w.emitted("saved")![0]![0]).toMatchObject({ id: "mine" });
  });

  it("sends typed headers, with the value masked", async () => {
    client.create.mockResolvedValue(SAVED);
    const w = open();
    await type(w, "label", "Notes");
    await type(w, "url", "https://notes.example.com/mcp");
    await w.get("button.add-header").trigger("click");
    await w.get("input.header-name").setValue("X-Key");
    await w.get("input.header-value").setValue("s3cret");

    expect(w.get("input.header-value").attributes("type")).toBe("password");
    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.create).toHaveBeenCalledWith({
      label: "Notes",
      url: "https://notes.example.com/mcp",
      description: "",
      headers: { "X-Key": "s3cret" },
    });
  });

  it("ignores a header row left empty and lets a row be removed", async () => {
    client.create.mockResolvedValue(SAVED);
    const w = open();
    await type(w, "label", "Notes");
    await type(w, "url", "https://notes.example.com/mcp");
    await w.get("button.add-header").trigger("click");
    await w.get("button.add-header").trigger("click");
    await w.findAll("input.header-name")[0]!.setValue("A");
    await w.findAll("input.header-value")[0]!.setValue("1");
    await w.findAll("button.remove-header")[1]!.trigger("click");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.create.mock.calls[0]![0]).toMatchObject({ headers: { A: "1" } });
    expect(w.findAll("input.header-name")).toHaveLength(1);
  });

  it("shows the server's message and stays open when it refuses", async () => {
    client.create.mockRejectedValue(new ApiError(422, "Enter an http or https address"));
    const w = open();
    await type(w, "label", "Bad");
    await type(w, "url", "ftp://bad");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(w.get("[role=alert]").text()).toBe("Enter an http or https address");
    expect(w.emitted("saved")).toBeUndefined();
    expect(w.emitted("close")).toBeUndefined();
  });

  it("disables the button while saving", async () => {
    let finish!: (value: UserExtension) => void;
    client.create.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const w = open();
    await type(w, "label", "Notes");
    await type(w, "url", "https://notes.example.com/mcp");

    await w.get("form").trigger("submit");

    expect(w.get("button[type=submit]").attributes("disabled")).toBeDefined();
    finish(SAVED);
    await flushPromises();
    expect(w.get("button[type=submit]").attributes("disabled")).toBeUndefined();
  });

  it("closes from Cancel", async () => {
    const w = open();

    await w.findAll("button").find((b) => b.text() === "Cancel")!.trigger("click");

    expect(w.emitted("close")).toHaveLength(1);
  });
});

describe("editing", () => {
  it("fills the form, lists the saved header names and shows no value inputs", () => {
    const w = open(SAVED);

    expect((w.get("input[name=label]").element as HTMLInputElement).value).toBe("Notes");
    expect((w.get("input[name=url]").element as HTMLInputElement).value).toBe("https://notes.example.com/mcp");
    expect((w.get("input[name=description]").element as HTMLInputElement).value).toBe("work");
    expect(w.get(".saved-headers").text()).toContain("X-Key");
    expect(w.find("input.header-value").exists()).toBe(false);
  });

  it("keeps the saved headers by not sending any", async () => {
    client.update.mockResolvedValue({ ...SAVED, label: "Renamed" });
    const w = open(SAVED);
    await type(w, "label", "Renamed");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.update).toHaveBeenCalledWith("notes", {
      label: "Renamed",
      url: "https://notes.example.com/mcp",
      description: "work",
    });
    expect(w.emitted("saved")![0]![0]).toMatchObject({ label: "Renamed" });
  });

  it("replaces the headers with what is typed after Replace headers", async () => {
    client.update.mockResolvedValue(SAVED);
    const w = open(SAVED);

    await w.get("button.replace-headers").trigger("click");
    await w.get("button.add-header").trigger("click");
    await w.get("input.header-name").setValue("Authorization");
    await w.get("input.header-value").setValue("Bearer t0ken");
    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.update.mock.calls[0]![1]).toMatchObject({ headers: { Authorization: "Bearer t0ken" } });
  });

  it("removes every header when the editor is opened and left empty", async () => {
    client.update.mockResolvedValue({ ...SAVED, header_names: [] });
    const w = open(SAVED);

    await w.get("button.replace-headers").trigger("click");
    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.update.mock.calls[0]![1]).toMatchObject({ headers: {} });
  });

  it("warns that saved headers go when the address moves to another host", async () => {
    const w = open(SAVED);
    expect(w.find(".host-warning").exists()).toBe(false);

    await type(w, "url", "https://other.example.org/mcp");
    expect(w.get(".host-warning").text()).toContain("saved headers");

    await type(w, "url", "https://notes.example.com/other-path");
    expect(w.find(".host-warning").exists()).toBe(false);

    await type(w, "url", "https://other.example.org/mcp");
    await w.get("button.replace-headers").trigger("click");
    expect(w.find(".host-warning").exists()).toBe(false);
  });

  it("does not warn about headers an extension never had", async () => {
    const w = open({ ...SAVED, header_names: [] });

    await type(w, "url", "https://other.example.org/mcp");

    expect(w.find(".host-warning").exists()).toBe(false);
    expect(w.get(".saved-headers").text()).toContain("No headers");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/components/UserExtensionModal.test.ts`
Expected: FAIL (component missing).

- [ ] **Step 3: Write the component**

Create `apps/ember_web/src/components/UserExtensionModal.vue`:

```vue
<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { UserExtension } from "../api/UserExtensionsClient";
import { useUserExtensionsStore } from "../stores/userExtensions";
import { errorMessage } from "../utils/errors";
import BaseModal from "./BaseModal.vue";

/** Adds a private extension (`extension` null) or edits one. Saved headers are
 * secrets ember_api never sends back, so an edit lists their names only and
 * keeps them unless the user opens "Replace headers": then what is typed
 * becomes the whole set (none removes them all). Value inputs are masked. The
 * server's message for a refused address or header is shown here. */
const props = defineProps<{ open: boolean; extension: UserExtension | null }>();
const emit = defineEmits<{ close: []; saved: [extension: UserExtension] }>();

const store = useUserExtensionsStore();

const form = reactive({ label: "", url: "", description: "" });
const rows = ref<{ name: string; value: string }[]>([]);
// Editing: the saved headers are being replaced by the rows below.
const replacing = ref(false);
const saving = ref(false);
const error = ref("");

const editing = computed(() => props.extension !== null);
const showEditor = computed(() => !editing.value || replacing.value);

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

// An edit that moves the address to another host drops the saved headers (ember_api does that
// so a token is never sent to a host the user did not give it to).
const hostWarning = computed(
  () =>
    props.extension !== null &&
    !replacing.value &&
    props.extension.header_names.length > 0 &&
    hostOf(form.url) !== "" &&
    hostOf(form.url) !== hostOf(props.extension.url),
);

// A fresh form each time it opens.
watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    form.label = props.extension?.label ?? "";
    form.url = props.extension?.url ?? "";
    form.description = props.extension?.description ?? "";
    rows.value = [];
    replacing.value = false;
    error.value = "";
  },
  { immediate: true },
);

function addRow(): void {
  rows.value.push({ name: "", value: "" });
}

function startReplacing(): void {
  replacing.value = true;
  rows.value = [];
}

function typedHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const row of rows.value) {
    if (row.name.trim() === "" && row.value === "") continue;
    headers[row.name.trim()] = row.value;
  }
  return headers;
}

async function save(): Promise<void> {
  error.value = "";
  saving.value = true;
  try {
    const base = { label: form.label, url: form.url, description: form.description };
    const withHeaders = showEditor.value && (!editing.value || replacing.value);
    const headers = withHeaders ? typedHeaders() : null;
    const saved = props.extension
      ? await store.update(props.extension.id, headers ? { ...base, headers } : base)
      : await store.add(headers && Object.keys(headers).length > 0 ? { ...base, headers } : base);
    emit("saved", saved);
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <BaseModal :open="open" :title="editing ? 'Edit private extension' : 'Add your own extension'" @close="emit('close')">
    <form class="form" @submit.prevent="save">
      <p class="muted">
        The address of an MCP server you run or trust (Streamable HTTP). Only you can see it and only your chats use it.
        Its tools always ask before they run.
      </p>
      <label>Label <input v-model="form.label" name="label" required maxlength="60" /></label>
      <label>
        Address
        <input v-model="form.url" name="url" required type="url" maxlength="1000" placeholder="https://host/mcp" />
      </label>
      <label>Description <input v-model="form.description" name="description" maxlength="300" /></label>

      <fieldset class="headers">
        <legend>Headers</legend>
        <template v-if="editing && !replacing">
          <p class="saved-headers muted">
            <template v-if="extension!.header_names.length">Saved headers: {{ extension!.header_names.join(", ") }}</template>
            <template v-else>No headers saved.</template>
            Their values are never shown.
          </p>
          <button type="button" class="ghost replace-headers" @click="startReplacing">Replace headers</button>
        </template>
        <template v-else>
          <p v-if="editing" class="muted">These replace every saved header. Leave none to remove them all.</p>
          <p v-else class="muted">Optional: for a server that wants a token or key.</p>
          <div v-for="(row, index) in rows" :key="index" class="row">
            <input
              v-model="row.name"
              class="header-name"
              :aria-label="`Header name ${index + 1}`"
              placeholder="X-Api-Key"
              maxlength="64"
              autocomplete="off"
              spellcheck="false"
            />
            <input
              v-model="row.value"
              class="header-value"
              type="password"
              :aria-label="`Header value ${index + 1}`"
              placeholder="value"
              maxlength="2000"
              autocomplete="off"
            />
            <button type="button" class="remove-header" :aria-label="`Remove header ${index + 1}`" @click="rows.splice(index, 1)">
              &times;
            </button>
          </div>
          <button type="button" class="ghost add-header" :disabled="rows.length >= 20" @click="addRow">Add header</button>
        </template>
        <p v-if="hostWarning" class="host-warning">
          The address is on another host, so the saved headers will be removed. Use Replace headers to set new ones.
        </p>
      </fieldset>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button type="button" class="ghost" @click="emit('close')">Cancel</button>
        <button type="submit" class="primary" :disabled="saving">{{ saving ? "Saving ..." : editing ? "Save" : "Add" }}</button>
      </div>
    </form>
  </BaseModal>
</template>

<style scoped>
.form {
  display: grid;
  gap: 10px;
}
.form p {
  margin: 0;
  font-size: 0.9em;
}
.form label {
  display: grid;
  gap: 4px;
  font-size: 0.85em;
  color: var(--muted);
}
input {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  outline: none;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
input:focus {
  border-color: var(--accent);
}
.headers {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.headers legend {
  padding: 0 6px;
  font-size: 0.85em;
  color: var(--muted);
}
.row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 6px;
}
.muted {
  color: var(--muted);
}
.error,
.host-warning {
  color: var(--danger);
}
.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.ghost,
.primary,
.remove-header {
  padding: 5px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
}
.ghost,
.remove-header {
  color: var(--muted);
  background: transparent;
}
.ghost {
  justify-self: start;
}
.remove-header {
  padding: 5px 12px;
}
.primary {
  border-color: var(--accent);
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.primary:disabled,
.ghost:disabled {
  cursor: default;
  opacity: 0.5;
}
button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/components/UserExtensionModal.test.ts`
Expected: PASS. If the `host-warning` test fails on the third step (a path-only change), check that `hostOf` compares host names and not whole URLs.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src/components/UserExtensionModal.vue apps/ember_web/src/components/UserExtensionModal.test.ts
git commit -m "feat(ember_web): modal to add and edit a private extension"
```

---

### Task 3: "My extensions" in the Supermarket

**Checkpoint:** before editing, tell the user in three sentences what the new section shows (rows with Enable/Disable, Edit and Remove, an "Add your own extension" button, the reason under a row that cannot be reached) and wait for a yes.

**Files:**
- Modify: `apps/ember_web/src/components/SupermarketItem.vue`
- Modify: `apps/ember_web/src/components/SupermarketItem.test.ts`
- Modify: `apps/ember_web/src/views/SupermarketView.vue`
- Modify: `apps/ember_web/src/views/SupermarketView.test.ts`

**Interfaces:**
- Consumes: `useUserExtensionsStore()`, `userExtensionSummary` (Task 1), `UserExtensionModal` (Task 2), `ConfirmModal`.
- Produces: `SupermarketItem` props `addLabel?: string` (default `"Add"`), `addedLabel?: string` (default `"Added"`), `detail?: string` (a muted line under the name).

- [ ] **Step 1: Write the failing tests for the row**

In `apps/ember_web/src/components/SupermarketItem.test.ts` append inside the file (after the last test, still importing the existing `mount`, `SupermarketItem`, `base`):

```ts
describe("labels and detail", () => {
  it("can call the buttons Enable and Enabled", () => {
    const off = mount(SupermarketItem, { props: { ...base, addLabel: "Enable", addedLabel: "Enabled" } });
    const on = mount(SupermarketItem, { props: { ...base, added: true, addLabel: "Enable", addedLabel: "Enabled" } });

    expect(off.get("button.add").text()).toBe("Enable");
    expect(off.get("button.add").attributes("aria-label")).toBe("Enable PDF files");
    expect(on.get(".added").text()).toContain("Enabled");
  });

  it("keeps Add and Added by default", () => {
    const off = mount(SupermarketItem, { props: base });
    const on = mount(SupermarketItem, { props: { ...base, added: true } });

    expect(off.get("button.add").text()).toBe("Add");
    expect(on.get(".added").text()).toContain("Added");
  });

  it("shows a detail line only when given", () => {
    expect(mount(SupermarketItem, { props: base }).find(".detail").exists()).toBe(false);
    expect(mount(SupermarketItem, { props: { ...base, detail: "Timed out" } }).get(".detail").text()).toBe("Timed out");
  });
});
```

Add `describe` to that file's `vitest` import if it is not there.

- [ ] **Step 2: Run to verify failure, then change the row**

Run: `npx vitest run src/components/SupermarketItem.test.ts` — Expected: FAIL (labels and `.detail`).

In `apps/ember_web/src/components/SupermarketItem.vue`:
- Replace `defineProps<{ ... }>();` with `withDefaults(defineProps<{ ... }>(), { addLabel: "Add", addedLabel: "Added", detail: "" });` and add to the props type, after `failed?: boolean;`:

```ts
  /** The add button's text and what "added" says; a private extension is "Enable" / "Enabled". */
  addLabel?: string;
  addedLabel?: string;
  /** A muted line under the name (why an extension cannot be reached). */
  detail?: string;
```

- In the template change the heading block to:

```vue
    <span class="heading">
      <h3>{{ label }}</h3>
      <code class="name">{{ name }}</code>
      <span v-if="detail" class="detail">{{ detail }}</span>
    </span>
```

- Replace the literal `Added` text in the `.added` span with `{{ addedLabel }}`, the add button's `aria-label` with `` :aria-label="`${addLabel} ${label}`" `` and its text with `{{ addLabel }}`.
- Add to the scoped styles:

```css
.detail {
  font-size: 0.8em;
  color: var(--danger);
  overflow-wrap: anywhere;
}
```

Run: `npx vitest run src/components/SupermarketItem.test.ts` — Expected: PASS.

- [ ] **Step 3: Update and add the view tests**

In `apps/ember_web/src/views/SupermarketView.test.ts`:

a) In the hoisted `mocks` add `userList: vi.fn(), userUpdate: vi.fn(), userCreate: vi.fn(), userRemove: vi.fn(),`; after the other `vi.mock` calls add:

```ts
vi.mock("../api/UserExtensionsClient", () => ({
  userExtensionsClient: {
    list: mocks.userList,
    create: mocks.userCreate,
    update: mocks.userUpdate,
    remove: mocks.userRemove,
  },
}));
```

b) Add imports: `import type { UserExtension } from "../api/UserExtensionsClient";` and `import UserExtensionModal from "../components/UserExtensionModal.vue";`.

c) After `BROKEN` add:

```ts
const MINE: UserExtension = {
  id: "mynotes",
  label: "My notes",
  description: "",
  url: "https://notes.example.com/mcp",
  header_names: ["X-Key"],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search", "add"],
};
const MINE_OFF: UserExtension = { ...MINE, id: "draft", label: "Draft", enabled: false, status: "unknown", tools: [] };
const MINE_DOWN: UserExtension = {
  ...MINE,
  id: "flaky",
  label: "Flaky",
  status: "error",
  error: "That address is not allowed",
  tools: [],
};
```

d) In `show()`'s options type add `userExtensions?: UserExtension[]`, and before `const router = ...` add `mocks.userList.mockResolvedValue(options.userExtensions ?? []);`. In `beforeEach` add `mocks.userUpdate.mockImplementation(async (id: string, patch: Partial<UserExtension>) => ({ ...MINE, id, ...patch }));`.

e) Change the two existing `group-title` assertions: `["Built-in", "Extensions"]` becomes `["Built-in", "Extensions", "My extensions"]`, and in the test for an account without `tools.use` `["Extensions"]` becomes `["Extensions", "My extensions"]`. Check that no existing assertion counts `article.item` rows with a private extension present (the default is none, so counts stay).

f) Append:

```ts
describe("My extensions", () => {
  const privateRows = (w: Wrapper) => rows(w).filter((r) => r.find("button.edit").exists());

  it("lists the account's own extensions with what each brings", async () => {
    const { w } = await show({ userExtensions: [MINE, MINE_OFF, MINE_DOWN] });

    expect(privateRows(w).map((r) => r.find("h3").text())).toEqual(["Draft", "Flaky", "My notes"]);
    expect(row(w, "My notes").find(".summary").text()).toBe("2 tools");
    expect(row(w, "Draft").find(".summary").text()).toBe("Not enabled");
    expect(row(w, "Flaky").find(".summary").text()).toBe("Not connected");
    expect(row(w, "Flaky").find(".detail").text()).toBe("That address is not allowed");
  });

  it("says so when there are none", async () => {
    const { w } = await show();

    expect(w.text()).toContain("You haven't added any private extensions.");
    expect(w.text()).toContain("Add your own extension");
  });

  it("is there for an account with only chat.use", async () => {
    const { w } = await show({ permissions: ["chat.use"], userExtensions: [MINE] });

    expect(names(w)).toContain("My notes");
  });

  it("is not there without chat.use", async () => {
    const { w } = await show({ permissions: ["tools.use"], userExtensions: [MINE] });

    expect(w.text()).not.toContain("My extensions");
    expect(mocks.userList).not.toHaveBeenCalled();
  });

  it("enables and disables with Enable and Disable", async () => {
    const { w } = await show({ userExtensions: [MINE, MINE_OFF] });

    expect(row(w, "Draft").get("button.add").text()).toBe("Enable");
    expect(row(w, "My notes").get(".added").text()).toContain("Enabled");

    await row(w, "Draft").get("button.add").trigger("click");
    await flushPromises();
    expect(mocks.userUpdate).toHaveBeenCalledWith("draft", { enabled: true });
    expect(row(w, "Draft").find(".added").exists()).toBe(true);

    await row(w, "My notes").get("button.secondary").trigger("click");
    await flushPromises();
    expect(mocks.userUpdate).toHaveBeenCalledWith("mynotes", { enabled: false });
  });

  it("follows the Enabled and Disabled chips", async () => {
    const { w } = await show({ userExtensions: [MINE, MINE_OFF], query: "state=enabled" });

    expect(privateRows(w).map((r) => r.find("h3").text())).toEqual(["My notes"]);
  });

  it("opens the add form from the button and the edit form from a row", async () => {
    const { w } = await show({ userExtensions: [MINE] });

    await w.findAll("button.primary").find((b) => b.text() === "Add your own extension")!.trigger("click");
    expect(w.getComponent(UserExtensionModal).props("open")).toBe(true);
    expect(w.getComponent(UserExtensionModal).props("extension")).toBeNull();

    await row(w, "My notes").get("button.edit").trigger("click");
    expect(w.getComponent(UserExtensionModal).props("extension")).toMatchObject({ id: "mynotes" });
  });

  it("adds the saved extension to the list and closes the form", async () => {
    mocks.userCreate.mockResolvedValue({ ...MINE, id: "fresh", label: "Fresh" });
    const { w } = await show();
    await w.findAll("button.primary").find((b) => b.text() === "Add your own extension")!.trigger("click");

    await w.get("input[name=label]").setValue("Fresh");
    await w.get("input[name=url]").setValue("https://fresh.example.com/mcp");
    await w.get("form.form").trigger("submit");
    await flushPromises();

    expect(names(w)).toContain("Fresh");
    expect(w.getComponent(UserExtensionModal).props("open")).toBe(false);
  });

  it("asks before removing, and removes", async () => {
    mocks.userRemove.mockResolvedValue(undefined);
    const { w } = await show({ userExtensions: [MINE] });

    await row(w, "My notes").get("button.remove").trigger("click");
    expect(w.getComponent(ConfirmModal).props("message")).toContain('Remove "My notes"');
    await w.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(mocks.userRemove).toHaveBeenCalledWith("mynotes");
    expect(names(w)).not.toContain("My notes");
  });

  it("refreshes the statuses when the page opens", async () => {
    await show({ userExtensions: [MINE] });

    expect(mocks.userList).toHaveBeenCalledTimes(2); // once at sign-in, once for the page
  });

  it("shows why a change failed", async () => {
    mocks.userUpdate.mockRejectedValue(new Error("offline"));
    const { w } = await show({ userExtensions: [MINE] });

    await row(w, "My notes").get("button.secondary").trigger("click");
    await flushPromises();

    expect(w.get("[role=alert]").text()).toContain("offline");
    expect(row(w, "My notes").find(".added").exists()).toBe(true); // rolled back
  });
});
```

If an existing helper `names`/`row`/`rows`/`Wrapper` is named differently in the file, use the file's own names (they are defined near the top, next to `show`).

- [ ] **Step 4: Run to verify failure**

Run: `npx vitest run src/views/SupermarketView.test.ts`
Expected: FAIL (no "My extensions" section).

- [ ] **Step 5: Change the view**

In `apps/ember_web/src/views/SupermarketView.vue`:

a) Imports: add `import UserExtensionModal from "../components/UserExtensionModal.vue";`, `import type { UserExtension } from "../api/UserExtensionsClient";`, `import { useUserExtensionsStore } from "../stores/userExtensions";` and `import { userExtensionSummary } from "../utils/userExtensions";`.

b) After `const chat = useChatStore();` add `const userExt = useUserExtensionsStore();`. After `const removing = ref(false);` add:

```ts
const canUsePrivate = computed(() => auth.hasPermission("chat.use"));
const modalOpen = ref(false);
const editing = ref<UserExtension | null>(null);
const pendingRemovePrivate = ref<UserExtension | null>(null);
const removingPrivate = ref(false);
```

c) After the `extensionRows` computed add:

```ts
const privateRows = computed(() =>
  [...userExt.items].sort(byLabel).filter((i) => shown(i.enabled)),
);

function openAdd(): void {
  editing.value = null;
  modalOpen.value = true;
}

function openEdit(item: UserExtension): void {
  editing.value = item;
  modalOpen.value = true;
}

async function confirmRemovePrivate(): Promise<void> {
  const item = pendingRemovePrivate.value;
  if (!item) return;
  actionError.value = "";
  removingPrivate.value = true;
  try {
    await userExt.remove(item.id);
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    removingPrivate.value = false;
    pendingRemovePrivate.value = null;
  }
}
```

d) Replace `onMounted(load);` with:

```ts
onMounted(() => {
  void load();
  // Each one's status comes from a live probe, so look again whenever the page opens.
  if (canUsePrivate.value) void userExt.refresh();
});
```

e) In the template: add `|| userExt.error` to the alert condition and text:

```vue
      <p v-if="actionError || switchError || (account.ready && account.error) || userExt.error" class="error" role="alert">
        {{ actionError || switchError || account.error || userExt.error }}
      </p>
```

f) After the closing of the Extensions block (`<p v-if="extensionRows.length === 0" ...>No extensions match this filter.</p>`) and still inside `<template v-if="!loading && !loadError && account.ready">`, add:

```vue
        <template v-if="canUsePrivate">
          <div class="section-head">
            <h4 class="group-title">My extensions</h4>
            <button type="button" class="primary" @click="openAdd">Add your own extension</button>
          </div>
          <p class="muted hint">MCP servers only you can see. Their tools always ask before they run.</p>
          <SupermarketItem
            v-for="i in privateRows"
            :key="i.id"
            :label="i.label"
            :name="i.id"
            icon="extension"
            :summary="userExtensionSummary(i)"
            :detail="i.enabled && i.status !== 'connected' ? (i.error ?? '') : ''"
            :failed="i.enabled && i.status === 'error'"
            :added="i.enabled"
            add-label="Enable"
            added-label="Enabled"
            @add="userExt.setEnabled(i.id, true)"
            @disable="userExt.setEnabled(i.id, false)"
          >
            <template #actions>
              <button type="button" class="edit" :aria-label="`Edit ${i.label}`" @click="openEdit(i)">Edit</button>
              <button type="button" class="remove" :aria-label="`Remove ${i.label}`" @click="pendingRemovePrivate = i">
                Remove
              </button>
            </template>
          </SupermarketItem>
          <p v-if="privateRows.length === 0" class="muted">
            {{ userExt.items.length ? "No private extensions match this filter." : "You haven't added any private extensions." }}
          </p>
        </template>
```

g) After the existing `<AddExtensionModal ... />` line add:

```vue
    <UserExtensionModal
      v-if="canUsePrivate"
      :open="modalOpen"
      :extension="editing"
      @close="modalOpen = false"
      @saved="modalOpen = false"
    />

    <ConfirmModal
      v-if="pendingRemovePrivate"
      open
      title="Remove private extension"
      :message="`Remove &quot;${pendingRemovePrivate.label}&quot;? Its saved headers are deleted too.`"
      confirm-label="Remove"
      danger
      :busy="removingPrivate"
      @confirm="confirmRemovePrivate"
      @close="pendingRemovePrivate = null"
    />
```

h) In the scoped styles change the rule `.everyone,\n.remove {` to `.everyone,\n.edit,\n.remove {`, and add:

```css
.edit:hover {
  color: var(--text);
  border-color: var(--accent);
}
.hint {
  margin: 0 2px 8px;
  font-size: 0.85em;
}
```

and add `.edit` to the `:focus-visible` selector list that already lists `.everyone`, `.remove`, `.primary`.

- [ ] **Step 6: Run to verify it passes**

Run: `npx vitest run src/views/SupermarketView.test.ts src/components/SupermarketItem.test.ts` then `npm run build`.
Expected: PASS and a clean build. If a test in `SupermarketView.test.ts` fails because the Add extension button is now one of two `button.primary` elements, select by text as the new tests do.

- [ ] **Step 7: Commit**

```bash
git add apps/ember_web/src
git commit -m "feat(ember_web): My extensions in the Supermarket"
```

---

### Task 4: Private cards on the Capabilities page

**Checkpoint:** before editing, tell the user in two sentences what the card shows (status dot, tool names, a switch that disables it, a "Private" label, no run button) and wait for a yes.

**Files:**
- Modify: `apps/ember_web/src/views/CapabilitiesView.vue`
- Modify: `apps/ember_web/src/views/CapabilitiesView.test.ts`

**Interfaces:**
- Consumes: `useUserExtensionsStore()`, `userExtensionSummary`, `matchesUserExtension` (Task 1); `CapabilitySection` (props `status: "ok"|"bad"|"off"`, `scope`, `control`, `checked`, `switchTitle`, `open`, `summary`, `icon`, slot).

- [ ] **Step 1: Write the failing tests**

In `apps/ember_web/src/views/CapabilitiesView.test.ts`:

a) In the hoisted `mocks` add `userList: vi.fn(), userUpdate: vi.fn(),`; after the other `vi.mock` calls add:

```ts
vi.mock("../api/UserExtensionsClient", () => ({
  userExtensionsClient: { list: mocks.userList, create: vi.fn(), update: mocks.userUpdate, remove: vi.fn() },
}));
```

b) Add `import type { UserExtension } from "../api/UserExtensionsClient";`.

c) Near the other fixtures add:

```ts
const MINE: UserExtension = {
  id: "mynotes",
  label: "My notes",
  description: "Notes on my server",
  url: "https://notes.example.com/mcp",
  header_names: [],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search", "add"],
};
```

d) In `show()`'s options type add `userExtensions?: UserExtension[]` and before `const router = ...` add `mocks.userList.mockResolvedValue(options.userExtensions ?? []);`. In `beforeEach` add `mocks.userUpdate.mockImplementation(async (id: string, patch: Partial<UserExtension>) => ({ ...MINE, id, ...patch }));`.

e) Append:

```ts
describe("private extensions on the page", () => {
  const WITH_CHAT = ["tools.use", "chat.use"];

  it("shows an enabled private extension as a card with its status and tools", async () => {
    const w = await show({ permissions: WITH_CHAT, userExtensions: [MINE] });

    expect(sectionNames(w)).toContain("My notes");
    expect(head(w, "My notes").text()).toContain("2 tools");
    expect(sections(w).find((s) => s.find("h3").text() === "My notes")!.find(".scope").text()).toBe("Private");
    await head(w, "My notes").trigger("click");
    expect(w.findAll("ul.private-tools code").map((c) => c.text())).toEqual(["search", "add"]);
    expect(w.text()).toContain("Notes on my server");
    expect(w.text()).toContain("always ask first");
  });

  it("gives it no run button, no Open button and no resources", async () => {
    const w = await show({ permissions: WITH_CHAT, userExtensions: [MINE] });
    await head(w, "My notes").trigger("click");
    const card = sections(w).find((s) => s.find("h3").text() === "My notes")!;

    expect(card.findAll("li.tool")).toHaveLength(0);
    expect(card.findAll("a")).toHaveLength(0);
    expect(card.find(".res-label").exists()).toBe(false);
  });

  it("does not show one that is not enabled", async () => {
    const w = await show({ permissions: WITH_CHAT, userExtensions: [{ ...MINE, enabled: false }] });

    expect(sectionNames(w)).not.toContain("My notes");
  });

  it("marks one that cannot be reached, with the reason", async () => {
    const w = await show({
      permissions: WITH_CHAT,
      userExtensions: [{ ...MINE, status: "error", error: "That address is not allowed", tools: [] }],
    });

    expect(head(w, "My notes").text()).toContain("Not connected");
    await head(w, "My notes").trigger("click");
    expect(w.text()).toContain("Not connected: That address is not allowed");
  });

  it("turns it off from its switch: the card goes and the extension is disabled", async () => {
    const w = await show({ permissions: WITH_CHAT, userExtensions: [MINE], attach: true });
    const box = sections(w).find((s) => s.find("h3").text() === "My notes")!.get("input[type=checkbox]").element as HTMLInputElement;

    box.click();
    await flushPromises();

    expect(mocks.userUpdate).toHaveBeenCalledWith("mynotes", { enabled: false });
    expect(sectionNames(w)).not.toContain("My notes");
    w.unmount();
  });

  it("follows the filter box and the kind toggle", async () => {
    const w = await show({ permissions: WITH_CHAT, userExtensions: [MINE] });
    const pick = (label: string) => w.findAll(".kinds button").find((b) => b.text() === label)!.trigger("click");

    await w.get("input[type=search]").setValue("sear");
    expect(sectionNames(w)).toContain("My notes");

    await w.get("input[type=search]").setValue("zzz-nothing");
    expect(sectionNames(w)).not.toContain("My notes");

    await w.get("input[type=search]").setValue("");
    await pick("Built-in");
    expect(sectionNames(w)).not.toContain("My notes");
    await pick("Extensions");
    expect(sectionNames(w)).toContain("My notes");
  });

  it("counts as something added, so the empty invitation is not shown", async () => {
    const w = await show({
      permissions: WITH_CHAT,
      added: { capabilities: [], extensions: [] },
      userExtensions: [MINE],
    });

    expect(w.text()).not.toContain("Nothing added yet");
    expect(sectionNames(w)).toEqual(["My notes"]);
  });

  it("refreshes the statuses when the page opens, for accounts that can have any", async () => {
    await show({ permissions: WITH_CHAT, userExtensions: [MINE] });
    expect(mocks.userList).toHaveBeenCalledTimes(2);

    mocks.userList.mockClear();
    await show({ permissions: ["tools.use"] });
    expect(mocks.userList).not.toHaveBeenCalled();
  });
});
```

If this file's helper names differ (`sections`, `sectionNames`, `head`), use the file's own; they are defined next to `show`.

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/views/CapabilitiesView.test.ts`
Expected: FAIL (no private cards).

- [ ] **Step 3: Change the view**

In `apps/ember_web/src/views/CapabilitiesView.vue`:

a) Imports: add `import { useUserExtensionsStore } from "../stores/userExtensions";` and `import { matchesUserExtension, userExtensionSummary } from "../utils/userExtensions";`. After `const account = useAccountCapabilitiesStore();` add `const userExt = useUserExtensionsStore();`.

b) After the `grouped` computed add:

```ts
// The account's own MCP servers that are on: they show with the extensions, as cards that only list
// their tools (their tools work for the agent, not on this page).
const privateShown = computed(() => userExt.items.filter((i) => i.enabled && matchesUserExtension(i, query.value)));
const privateKey = (id: string): string => `\0private:${id}`;
```

c) Replace `nothingShown` and `nothingAdded` with:

```ts
const nothingShown = computed(
  () =>
    (!showBuiltin.value || (grouped.value.groups.length === 0 && !showOther.value)) &&
    (!showExtensions.value || (grouped.value.extensionGroups.length === 0 && privateShown.value.length === 0)),
);
// Nothing at all is added (not just filtered away): invite the user to the Supermarket.
const nothingAdded = computed(
  () =>
    added.value.capabilities.length === 0 &&
    added.value.extensions.length === 0 &&
    added.value.tools.length === 0 &&
    !userExt.items.some((i) => i.enabled),
);
```

d) Replace `onMounted(load);` with:

```ts
onMounted(() => {
  void load();
  // Each one's status comes from a live probe, so look again whenever the page opens.
  if (auth.hasPermission("chat.use")) void userExt.refresh();
});
```

e) In the template: change the Extensions heading condition to `v-if="groupHeadings && (grouped.extensionGroups.length || privateShown.length)"`; add `|| userExt.error` to the alert line and text like in Task 3; and after the closing `</CapabilitySection>` of the extension groups loop (inside `<template v-if="showExtensions">`) add:

```vue
          <CapabilitySection
            v-for="i in privateShown"
            :key="`private:${i.id}`"
            :label="i.label"
            :name="i.id"
            icon="extension"
            :open="isOpen(privateKey(i.id))"
            :summary="userExtensionSummary(i)"
            :status="i.status === 'connected' ? 'ok' : i.status === 'error' ? 'bad' : 'off'"
            control="switch"
            :checked="true"
            scope="Private"
            switch-title="Turn off. It stays in your Supermarket under My extensions."
            @toggle="toggleSection(privateKey(i.id))"
            @switch="userExt.setEnabled(i.id, false)"
          >
            <p v-if="i.description" class="muted">{{ i.description }}</p>
            <p v-if="i.status === 'error'" class="error">Not connected{{ i.error ? `: ${i.error}` : "" }}</p>
            <p v-else-if="i.status === 'unknown'" class="muted">{{ i.error ?? "Not checked yet" }}</p>
            <ul v-if="i.tools.length" class="private-tools">
              <li v-for="t in i.tools" :key="t"><code class="name">{{ t }}</code></li>
            </ul>
            <p class="muted">Its tools work in your chats and always ask first. They can't be run from this page.</p>
          </CapabilitySection>
```

f) Add to the scoped styles:

```css
.private-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/views/CapabilitiesView.test.ts` then `npm run build`.
Expected: PASS and a clean build. An existing test that mounts with `chat.use` and counts `article.card` is unaffected because the default list is empty.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src/views/CapabilitiesView.vue apps/ember_web/src/views/CapabilitiesView.test.ts
git commit -m "feat(ember_web): private extension cards on the Capabilities page"
```

---

### Task 5: The notice in the chat

**Checkpoint:** before editing, tell the user in two sentences that a banner above the messages will say which private extension was not used and why, until the next question, and wait for a yes.

**Files:**
- Modify: `apps/ember_web/src/api/types.ts`, `apps/ember_web/src/stores/chat.ts`, `apps/ember_web/src/views/ChatView.vue`
- Create: `apps/ember_web/src/components/TurnNotices.vue`, `apps/ember_web/src/components/TurnNotices.test.ts`, `apps/ember_web/src/stores/chat.notices.test.ts`

**Interfaces:**
- Produces: type `TurnNotice {id: string; label: string; error: string}`; the `TurnEvent` variant `{type: "notice"; notices: TurnNotice[]}`; chat store `notices: TurnNotice[]` and `dismissNotices(): void`; component `TurnNotices` (props `notices`, emits `dismiss`).

- [ ] **Step 1: Write the failing component test**

Create `apps/ember_web/src/components/TurnNotices.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import TurnNotices from "./TurnNotices.vue";

describe("TurnNotices", () => {
  it("shows nothing without notices", () => {
    expect(mount(TurnNotices, { props: { notices: [] } }).find(".notices").exists()).toBe(false);
  });

  it("says which extension was not used and why", () => {
    const w = mount(TurnNotices, {
      props: {
        notices: [
          { id: "notes", label: "My notes", error: "Timed out" },
          { id: "wiki", label: "", error: "That address is not allowed" },
        ],
      },
    });

    const lines = w.findAll("li").map((li) => li.text());
    expect(lines).toEqual(["My notes wasn't used in this answer: Timed out", "wiki wasn't used in this answer: That address is not allowed"]);
    expect(w.get(".notices").attributes("role")).toBe("status");
  });

  it("emits dismiss", async () => {
    const w = mount(TurnNotices, { props: { notices: [{ id: "a", label: "A", error: "x" }] } });

    await w.get("button").trigger("click");

    expect(w.emitted("dismiss")).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run to verify failure, then write the component and the type**

Run: `npx vitest run src/components/TurnNotices.test.ts` — Expected: FAIL.

In `apps/ember_web/src/api/types.ts`, directly before `export type TurnEvent`, add:

```ts
/** An extension the agent could not use in an answer (or whose headers could not be read): why. */
export interface TurnNotice {
  id: string;
  label: string;
  error: string;
}
```

and in the `TurnEvent` union, directly after the `question_resolved` line, add `  | { type: "notice"; notices: TurnNotice[] }`.

Create `apps/ember_web/src/components/TurnNotices.vue`:

```vue
<script setup lang="ts">
import type { TurnNotice } from "../api/types";

/** Which of the user's private extensions the last answer could not use, and why. */
defineProps<{ notices: TurnNotice[] }>();
const emit = defineEmits<{ dismiss: [] }>();
</script>

<template>
  <div v-if="notices.length" class="notices" role="status">
    <ul>
      <li v-for="n in notices" :key="n.id">
        <strong>{{ n.label || n.id }}</strong> wasn't used in this answer: {{ n.error }}
      </li>
    </ul>
    <button type="button" @click="emit('dismiss')">Dismiss</button>
  </div>
</template>

<style scoped>
.notices {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px 16px;
  padding: 8px 16px;
  font-size: 0.9em;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
button {
  padding: 2px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  color: var(--muted);
  background: transparent;
}
button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
```

Run: `npx vitest run src/components/TurnNotices.test.ts` — Expected: PASS.

- [ ] **Step 3: Write the failing store tests**

Create `apps/ember_web/src/stores/chat.notices.test.ts` (same harness as `chat.questions.test.ts`):

```ts
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { accountCapabilitiesClient } from "../api/AccountCapabilitiesClient";
import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import type { ChatMessage, TurnEvent } from "../api/types";
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
    suggestion: vi.fn(),
    answerQuestion: vi.fn(),
  },
}));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn() }));
vi.mock("../composables/useNotify", () => ({ chimeIfAway: vi.fn() }));
vi.mock("../services/slashCommands", () => ({
  SlashCommandRunner: class {
    run = vi.fn();
    list = vi.fn(async () => []);
    schemaFor = vi.fn(async () => null);
  },
}));

const client = vi.mocked(chatsClient);
const watch = vi.mocked(watchTurn);

const ACCOUNT = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use"],
};

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

let emit: (event: TurnEvent) => void = () => {
  throw new Error("no answer is being watched");
};
const fire = (event: Record<string, unknown>) => emit({ sequence: 1, ...event } as TurnEvent);

async function storeWith(chats: Record<string, ChatMessage[]>) {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT;
  client.list.mockResolvedValue(Object.entries(chats).map(([id, m]) => summary(id, m.length)));
  client.get.mockImplementation(async (id: string) => ({
    ...summary(id, chats[id]!.length),
    messages: structuredClone(chats[id]!),
  }));
  const chat = useChatStore();
  await flushPromises();
  return chat;
}

/** A chat whose answer is being written. */
async function running() {
  const chat = await storeWith({ c1: TWO, c2: TWO });
  await chat.selectChat("c1");
  await chat.send("ask something");
  return chat;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(accountCapabilitiesClient.get).mockResolvedValue({ capabilities: [], extensions: [], disabled_tools: [] });
  watch.mockImplementation(
    (_id, _after, onEvent) =>
      new Promise<WatchEnd>(() => {
        emit = onEvent;
      }),
  );
  client.startTurn.mockResolvedValue({ chat: { ...summary("c1", 2, true) }, sequence: 5 });
  client.append.mockResolvedValue(undefined as never);
  client.search.mockResolvedValue([]);
  client.suggestion.mockResolvedValue({ text: null });
});

const NOTICES = [{ id: "notes", label: "My notes", error: "Timed out" }];

describe("notices about private extensions", () => {
  it("start empty", async () => {
    const chat = await storeWith({ c1: TWO });

    expect(chat.notices).toEqual([]);
  });

  it("are kept when the agent reports an extension it could not use", async () => {
    const chat = await running();

    fire({ type: "notice", notices: NOTICES });

    expect(chat.notices).toEqual(NOTICES);
  });

  it("stay after the answer has finished", async () => {
    const chat = await running();
    fire({ type: "notice", notices: NOTICES });

    fire({ type: "final", message: { role: "assistant", content: "done" }, cancelled: false });

    expect(chat.notices).toEqual(NOTICES);
  });

  it("go when the next question is sent", async () => {
    const chat = await running();
    fire({ type: "notice", notices: NOTICES });
    client.startTurn.mockResolvedValue({ chat: { ...summary("c1", 4, true) }, sequence: 9 });

    await chat.send("another question");

    expect(chat.notices).toEqual([]);
  });

  it("go when a new chat is started or another chat is opened", async () => {
    const chat = await running();
    fire({ type: "notice", notices: NOTICES });
    chat.newChat();
    expect(chat.notices).toEqual([]);

    fire({ type: "notice", notices: NOTICES });
    await chat.selectChat("c2");
    expect(chat.notices).toEqual([]);
  });

  it("can be dismissed", async () => {
    const chat = await running();
    fire({ type: "notice", notices: NOTICES });

    chat.dismissNotices();

    expect(chat.notices).toEqual([]);
  });

  it("go when the account changes", async () => {
    const chat = await running();
    fire({ type: "notice", notices: NOTICES });

    useAuthStore().account = { ...ACCOUNT, id: 2 };
    await flushPromises();

    expect(chat.notices).toEqual([]);
  });
});
```

- [ ] **Step 4: Run to verify failure, then change the chat store**

Run: `npx vitest run src/stores/chat.notices.test.ts` — Expected: FAIL (`notices` undefined).

In `apps/ember_web/src/stores/chat.ts` make these edits:

1. In the `import type { ... } from "../api/types";` list add `  TurnNotice,` directly after `  TurnEvent,`.
2. After the line `const pendingQuestions = ref<PendingQuestion[]>([]);` add:

```ts
  // Private extensions the last answer could not use (the `notice` event), shown until the next
  // question, a new chat, another chat, or Dismiss.
  const notices = ref<TurnNotice[]>([]);
```

3. In `onEvent`, directly before `case "question_request":` add:

```ts
      case "notice":
        notices.value = event.notices;
        break;
```

4. Clear it in four places, each a single line `notices.value = [];`:
   - in the account-change `watch` callback, directly after `clearSuggestion();` (the one followed by `generation += 1;`);
   - in `send()`, directly after the line `sendError.value = "";` that sits between `if (truncateTo !== undefined && !canReplaceFrom(truncateTo)) return false;` and `if (truncateTo === undefined && question.startsWith("/")) {`;
   - in `newChat()`, directly after `clearSuggestion();`;
   - in `selectChat()`, directly after `if (id === activeId.value) return;` and its following `unfollow();` and `clearSuggestion();` (i.e. only when the user really switches chats).
5. Add the function next to `clearJump`/`clearSearch` (anywhere among the plain functions):

```ts
  function dismissNotices(): void {
    notices.value = [];
  }
```

6. Add `notices,` and `dismissNotices,` to the returned object (next to `pendingQuestions`).

Run: `npx vitest run src/stores/chat.notices.test.ts src/stores/chat.questions.test.ts` — Expected: PASS.

- [ ] **Step 5: Show it in `ChatView`**

In `apps/ember_web/src/views/ChatView.vue`: add `import TurnNotices from "../components/TurnNotices.vue";` with the other component imports; add `notices,` to the same destructuring that provides `sendError` and `pendingQuestions` (from `storeToRefs(chat)`); and directly after the `sendError` banner `</div>` add:

```vue
      <TurnNotices :notices="notices" @dismiss="chat.dismissNotices()" />
```

- [ ] **Step 6: Run to verify**

Run: `npx vitest run src/views/ChatView.test.ts src/components/TurnNotices.test.ts src/stores` then `npm run build`.
Expected: PASS and a clean build. (If `ChatView.test.ts` does not exist, run `npx vitest run src/views`.)

- [ ] **Step 7: Commit**

```bash
git add apps/ember_web/src
git commit -m "feat(ember_web): tell the user when a private extension was not used"
```

---

### Task 6: Fake API, e2e, docs and the full check

**Checkpoint:** before editing, tell the user in two sentences that this only touches the e2e fake API, the e2e spec and the README, and wait for a yes.

**Files:**
- Modify: `apps/ember_web/e2e/fakeApi.ts`, `apps/ember_web/e2e/capabilities.spec.ts`, `apps/ember_web/README.md`

**Interfaces:**
- Consumes: the real routes' shape from part 2.

- [ ] **Step 1: Teach the fake API the new routes**

In `apps/ember_web/e2e/fakeApi.ts`:

a) In `interface FakeApi` add:

```ts
  /** The account's own MCP servers (/api/user-extensions), by id. */
  userExtensions: Map<string, StoredUserExtension>;
```

and next to `StoredCapability` add:

```ts
export interface StoredUserExtension {
  id: string;
  label: string;
  description: string;
  url: string;
  header_names: string[];
  enabled: boolean;
  status: string;
  error: string | null;
  tools: string[];
}
```

b) In the `const api: FakeApi = {` literal add `userExtensions: new Map(),`.

c) In the route handler, directly before the line `if (method === "GET" && path === "/api/extensions") return json(route, []);` add:

```ts
    // The account's own MCP servers.
    if (path === "/api/user-extensions" && method === "GET") return json(route, [...api.userExtensions.values()]);
    if (path === "/api/user-extensions" && method === "POST") {
      const body = request.postDataJSON() as { label: string; url: string; description?: string; headers?: Record<string, string> };
      const base = body.label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "extension";
      let id = base;
      for (let n = 2; api.userExtensions.has(id); n += 1) id = `${base}_${n}`;
      const created: StoredUserExtension = {
        id,
        label: body.label,
        description: body.description ?? "",
        url: body.url,
        header_names: Object.keys(body.headers ?? {}).sort(),
        enabled: true,
        status: "connected",
        error: null,
        tools: ["search", "add"],
      };
      api.userExtensions.set(id, created);
      return json(route, created, 201);
    }
    const userExtensionPath = /^\/api\/user-extensions\/([a-z0-9_]+)$/.exec(path);
    if (userExtensionPath && method === "PATCH") {
      const found = api.userExtensions.get(userExtensionPath[1]!);
      if (!found) return json(route, { detail: "No such extension" }, 404);
      const patch = request.postDataJSON() as Partial<StoredUserExtension> & { headers?: Record<string, string> };
      if (patch.label !== undefined) found.label = patch.label;
      if (patch.description !== undefined) found.description = patch.description;
      if (patch.url !== undefined) found.url = patch.url;
      if (patch.headers !== undefined) found.header_names = Object.keys(patch.headers).sort();
      if (patch.enabled !== undefined) {
        found.enabled = patch.enabled;
        found.status = patch.enabled ? "connected" : "unknown";
      }
      return json(route, found);
    }
    if (userExtensionPath && method === "DELETE") {
      api.userExtensions.delete(userExtensionPath[1]!);
      return route.fulfill({ status: 204, body: "" });
    }
```

- [ ] **Step 2: Add the e2e tests**

Append to `apps/ember_web/e2e/capabilities.spec.ts` (it already imports `expect`, `test`, `installFakeApi`, `logIn` and defines `card` and `item` helpers):

```ts
test("a private extension is added in the Supermarket, shows on Capabilities, and can be disabled and enabled", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await logIn(page);
  await page.goto("/capabilities/supermarket");

  await expect(page.getByText("You haven't added any private extensions.")).toBeVisible();
  await page.getByRole("button", { name: "Add your own extension" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Label").fill("My notes");
  await dialog.getByLabel("Address").fill("https://notes.example.com/mcp");
  await dialog.getByRole("button", { name: "Add header" }).click();
  await dialog.getByLabel("Header name 1").fill("X-Api-Key");
  await dialog.getByLabel("Header value 1").fill("s3cret");
  await dialog.getByRole("button", { name: "Add", exact: true }).click();

  await expect(item(page, "My notes").getByText("Enabled")).toBeVisible();
  expect(JSON.stringify([...api.userExtensions.values()])).not.toContain("s3cret");

  await page.getByRole("link", { name: "Back to capabilities" }).click();
  const mine = card(page, "My notes");
  await expect(mine).toBeVisible();
  await expect(mine.getByText("Private")).toBeVisible();
  await expect(mine.getByText("2 tools")).toBeVisible();

  await mine.locator("label.toggle").click();
  await expect(mine).toHaveCount(0);

  await page.getByRole("link", { name: "Supermarket" }).click();
  await item(page, "My notes").getByRole("button", { name: "Enable My notes" }).click();
  await expect(item(page, "My notes").getByText("Enabled")).toBeVisible();
  expect(api.unexpected).toEqual([]);
});

test("a private extension can be edited and removed", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  api.userExtensions.set("mynotes", {
    id: "mynotes",
    label: "My notes",
    description: "",
    url: "https://notes.example.com/mcp",
    header_names: ["X-Api-Key"],
    enabled: true,
    status: "connected",
    error: null,
    tools: ["search"],
  });
  await logIn(page);
  await page.goto("/capabilities/supermarket");

  await item(page, "My notes").getByRole("button", { name: "Edit My notes" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Saved headers: X-Api-Key")).toBeVisible();
  await dialog.getByLabel("Label").fill("Work notes");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(item(page, "Work notes")).toBeVisible();

  await item(page, "Work notes").getByRole("button", { name: "Remove Work notes" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove", exact: true }).click();
  await expect(item(page, "Work notes")).toHaveCount(0);
  expect(api.unexpected).toEqual([]);
});
```

- [ ] **Step 3: Update the README**

In `apps/ember_web/README.md`, in the Supermarket bullet (search `grep -n "Supermarket" README.md`) append these sentences: "A third section, **My extensions** (any account with `chat.use`), lists the account's own MCP servers kept in ember_api (`/api/user-extensions`): each row shows what it brings or why it cannot be reached, with Enable / Disable, Edit and Remove, and an **Add your own extension** button opens a modal with a label, an address, a description and optional masked headers (header values are never shown again; editing lists the saved names and **Replace headers** sets a new set). Enabled ones appear on the Capabilities page as cards labelled Private that list their tools but cannot run them: their tools work for the agent in chat and always ask first. When the agent could not use one, a banner above the messages says so until the next question." In the `stores/` line add `userExtensions` to the list of Pinia stores.

- [ ] **Step 4: Run everything**

Run: `npx vitest run`, then `npm run build`, then `npx playwright test e2e/capabilities.spec.ts`.
Expected: all PASS. If Playwright cannot run in this environment (browsers not installed), say so; do not claim the e2e passed. If an unrelated test fails only once and passes on rerun, say so and name it.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/e2e apps/ember_web/README.md
git commit -m "test(ember_web): e2e for private extensions; document them"
```

---

## Self-review (done while writing)

- **Spec coverage (ember_web section):** client and store (Task 1); add/edit modal with masked values and the replace-headers editing model, server messages inline, host-change hint (Task 2); Supermarket "My extensions" with Enable/Disable, Edit, Remove, the Add button, the filter chips, the reason under an unreachable row, the confirm for removal (Task 3); Capabilities cards with status dot, tool names, a switch, "Private" label, no run/Open/resources, search and kind filtering, empty-state interplay (Task 4); the `notice` event, banner until next question and Dismiss (Task 5); fake API, e2e, README (Task 6). The spec's "leave blank to keep the saved value" was replaced by Replace headers (Task 0) because ember_api replaces the whole set and cannot keep individual values.
- **Placeholder scan:** none. Where an existing test file's helper names might differ, the step says to use the file's own and names where they are defined.
- **Type consistency:** `UserExtension` and the store functions (`items`, `ready`, `error`, `refresh`, `add`, `update`, `remove`, `setEnabled`) are used identically in Tasks 1 to 4; `userExtensionSummary` and `matchesUserExtension` (Task 1) in Tasks 3 and 4; `UserExtensionModal` props (`open`, `extension`) and events (`close`, `saved`) in Tasks 2 and 3; `SupermarketItem`'s `addLabel`, `addedLabel`, `detail` (Task 3) are the only new props; `TurnNotice`, `notices` and `dismissNotices` match across Task 5; the fake API's `StoredUserExtension` matches the client's `UserExtension`.
