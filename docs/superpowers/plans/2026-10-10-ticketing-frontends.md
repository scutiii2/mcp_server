# Ticketing Front Ends Implementation Plan (ember_web, ember_admin)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Standing rule for this repo's UI work:** before each task, tell the user which files you will create or change and wait for approval, then implement, verify, report. Commit only after verification passes. The user tests the UI by hand; do not launch browser-verification agents. (From the `ember-feature-scaffold` skill and the user's memory notes.)

**Goal:** Give reporters a Tickets page in ember_web (file, follow, comment, close their own tickets) and give staff a Tickets page in ember_admin (grouped triage, ticket drawer, group priority).

**Architecture:** Each app gets its own small API client for the ember_api routes built in plan 2, plus views and components that follow the app's existing patterns (info page + `BaseModal` in ember_web; list + drawer like `AccountsPanel` in ember_admin). No shared package exists between the two apps, so the few ticket helpers are duplicated, as the apps already do for their other shared controls.

**Tech Stack:** Vue 3 + TypeScript (`<script setup>`), Vite, Pinia, vue-router, Vitest + jsdom + `@vue/test-utils`, Playwright (existing e2e, only extended if a scenario breaks).

**Spec:** `docs/superpowers/specs/2026-10-10-ticketing-system-design.md` (sections 4 and 5). Routes this plan calls are defined in `docs/superpowers/plans/2026-10-10-ticketing-ember-api.md`.

## Global Constraints

- Run commands from the app folder (`apps/Ember/ember_web` or `apps/Ember/ember_admin`). Checks per task: `npx vue-tsc -b --noEmit` (prints nothing when clean) and `npx vitest run <file>`; after the last task of an app also `npm test`. Do not run `npm run test:e2e` unless a step says so.
- Radius only through `--radius-*` tokens, colors only through the tokens in `src/style.css` (`--bg --surface --text --muted --border --accent --accent-contrast --danger --warning --success --code-bg --mono`). `radiusScale.test.ts` enforces it in both apps. No literal hex colors or `px` radii in new CSS.
- `tsconfig.app.json` has `erasableSyntaxOnly`: no enums, no constructor parameter properties.
- Pages go in `src/views/`, reusable pieces in `src/components/`. New dialogs use `BaseModal` / `ConfirmModal`, never `confirm()`.
- Ticket text (titles, descriptions, comments, context) is plain text from users or staff: render with `{{ }}` and `white-space: pre-wrap`, never `v-html`.
- Status is shown with an icon and a word, never color alone. Switches and selects that call the server show only server-confirmed state: reset the DOM value right away, disable while busy, and let the reloaded data set the new value.
- mcp_server timestamps are ISO strings with a `+00:00` offset (unlike ember_api's naive UTC). Format them with `new Date(iso).toLocaleString()` (helper `formatTicketTime`), never with `formatUtc`, which appends `Z`.
- Permissions: ember_web page needs `tickets.create`; ember_admin page needs `tickets.manage`. Both are enforced by ember_api; the router only hides pages.
- Reporters never see tags, priority, assignee or other people's data. ember_web must not offer or send those.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `apps/Ember/ember_web/src/api/TicketsClient.ts` (+ `.test.ts`) | Types and calls for `/api/tickets*` |
| `apps/Ember/ember_web/src/utils/tickets.ts` | Labels, status icons, time formatting |
| `apps/Ember/ember_web/src/views/TicketsView.vue` (+ `.test.ts`) | List, filter, new-ticket modal, detail modal with thread, close |
| `apps/Ember/ember_web/src/router/index.ts`, `router/pages.ts` | Route and nav entry |
| `apps/Ember/ember_admin/src/api/TicketsAdminClient.ts` (+ `.test.ts`) | Types and calls for `/api/admin/tickets*`, `/api/admin/ticket-groups*` |
| `apps/Ember/ember_admin/src/utils/ticketFormat.ts` | Labels, status icons, time formatting |
| `apps/Ember/ember_admin/src/components/admin/TicketDrawer.vue` (+ test) | One ticket: details, controls, thread |
| `apps/Ember/ember_admin/src/components/admin/TicketsPanel.vue` (+ test) | Filters, groups list, expandable tickets, drawer |
| `apps/Ember/ember_admin/src/views/TicketsAdminView.vue` | Page shell, URL-kept filters |
| `apps/Ember/ember_admin/src/router/index.ts`, `router/pages.ts`, `views/AdminOverviewView.vue` | Route, nav entry, overview tiles |

---

# Part A: ember_web

### Task 1: TicketsClient and helpers (ember_web)

**Files:**
- Create: `apps/Ember/ember_web/src/api/TicketsClient.ts`
- Create: `apps/Ember/ember_web/src/utils/tickets.ts`
- Test: `apps/Ember/ember_web/src/api/TicketsClient.test.ts`

**Interfaces:**
- Consumes: `apiRequest<T>(method, path, body?)` from `./http`.
- Produces:

```ts
export type TicketType = "bug" | "feature" | "other";
export type TicketStatus = "open" | "in_progress" | "resolved" | "closed";
export interface TicketComment { id: number; ticket_id: number; author: string; author_role: "reporter" | "staff" | "ai"; body: string; created_at: string }
export interface Ticket { id: number; type: TicketType; title: string; description: string; status: TicketStatus; created_at: string; updated_at: string; closed_at: string | null; comments?: TicketComment[] }
export interface NewTicket { type: TicketType; title: string; description: string }
export interface CreatedTicket { ticket: Ticket; duplicate: boolean; group_size: number }
export const ticketsClient: {
  list(status?: TicketStatus): Promise<Ticket[]>;
  get(id: number): Promise<Ticket>;           // with comments
  create(body: NewTicket): Promise<CreatedTicket>;
  comment(id: number, body: string): Promise<Ticket>;
  close(id: number): Promise<Ticket>;
}
// utils/tickets.ts
STATUS_LABELS, TYPE_LABELS, STATUS_ICONS (SVG path data), COMMENT_ROLE_LABELS, formatTicketTime(iso: string): string
```

- [ ] **Step 1: Write the failing test**

`src/api/TicketsClient.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { ticketsClient } from "./TicketsClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);
const TICKET = { id: 7, type: "bug", title: "T", description: "D", status: "open", created_at: "x", updated_at: "x", closed_at: null };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ticketsClient", () => {
  it("lists tickets, optionally by status, and unwraps the list", async () => {
    request.mockResolvedValue({ tickets: [TICKET] });

    expect(await ticketsClient.list()).toEqual([TICKET]);
    expect(request).toHaveBeenLastCalledWith("GET", "/api/tickets");
    await ticketsClient.list("in_progress");
    expect(request).toHaveBeenLastCalledWith("GET", "/api/tickets?status=in_progress");
  });

  it("gets, comments on and closes one ticket and unwraps it", async () => {
    request.mockResolvedValue({ ticket: TICKET });

    expect(await ticketsClient.get(7)).toEqual(TICKET);
    expect(request).toHaveBeenLastCalledWith("GET", "/api/tickets/7");
    await ticketsClient.comment(7, "log attached");
    expect(request).toHaveBeenLastCalledWith("POST", "/api/tickets/7/comments", { body: "log attached" });
    await ticketsClient.close(7);
    expect(request).toHaveBeenLastCalledWith("POST", "/api/tickets/7/close");
  });

  it("creates a ticket with only type, title and description", async () => {
    request.mockResolvedValue({ ticket: TICKET, duplicate: false, group_size: 1 });

    const created = await ticketsClient.create({ type: "feature", title: "Dark mode", description: "Please" });

    expect(created.ticket.id).toBe(7);
    expect(request).toHaveBeenLastCalledWith("POST", "/api/tickets", { type: "feature", title: "Dark mode", description: "Please" });
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run src/api/TicketsClient.test.ts`
Expected: FAIL (cannot find `./TicketsClient`).

- [ ] **Step 3: Implement**

`src/api/TicketsClient.ts`:

```ts
import { apiRequest } from "./http";

export type TicketType = "bug" | "feature" | "other";
export type TicketStatus = "open" | "in_progress" | "resolved" | "closed";

export interface TicketComment {
  id: number;
  ticket_id: number;
  author: string;
  /** reporter = you, ai = the assistant writing for you, staff = support. */
  author_role: "reporter" | "staff" | "ai";
  body: string;
  created_at: string;
}

/** Only what a reporter may see: ember_api never sends tags, priority or other people's data here. */
export interface Ticket {
  id: number;
  type: TicketType;
  title: string;
  description: string;
  status: TicketStatus;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  /** Present when one ticket is fetched. */
  comments?: TicketComment[];
}

export interface NewTicket {
  type: TicketType;
  title: string;
  description: string;
}

export interface CreatedTicket {
  ticket: Ticket;
  duplicate: boolean;
  group_size: number;
}

export const ticketsClient = {
  list: async (status?: TicketStatus): Promise<Ticket[]> =>
    (await apiRequest<{ tickets: Ticket[] }>("GET", status ? `/api/tickets?status=${status}` : "/api/tickets")).tickets,
  get: async (id: number): Promise<Ticket> => (await apiRequest<{ ticket: Ticket }>("GET", `/api/tickets/${id}`)).ticket,
  create: (body: NewTicket) => apiRequest<CreatedTicket>("POST", "/api/tickets", body),
  comment: async (id: number, body: string): Promise<Ticket> =>
    (await apiRequest<{ ticket: Ticket }>("POST", `/api/tickets/${id}/comments`, { body })).ticket,
  close: async (id: number): Promise<Ticket> =>
    (await apiRequest<{ ticket: Ticket }>("POST", `/api/tickets/${id}/close`)).ticket,
};
```

`src/utils/tickets.ts`:

```ts
import type { TicketComment, TicketStatus, TicketType } from "../api/TicketsClient";

export const STATUS_LABELS: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  closed: "Closed",
};

export const TYPE_LABELS: Record<TicketType, string> = { bug: "Bug", feature: "Feature", other: "Other" };

/** Stroked 24x24 icon path data per status: a status is never shown by color alone. */
export const STATUS_ICONS: Record<TicketStatus, string> = {
  open: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  in_progress: "M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  resolved: "M20 6L9 17l-5-5",
  closed: "M8 12h8M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
};

export const COMMENT_ROLE_LABELS: Record<TicketComment["author_role"], string> = {
  reporter: "You",
  ai: "Assistant, for you",
  staff: "Support",
};

/** mcp_server times carry an offset ("+00:00"), so they parse as they are. */
export function formatTicketTime(iso: string): string {
  return new Date(iso).toLocaleString();
}
```

- [ ] **Step 4: Run test and type-check**

Run: `npx vitest run src/api/TicketsClient.test.ts` then `npx vue-tsc -b --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_web/src/api/TicketsClient.ts apps/Ember/ember_web/src/api/TicketsClient.test.ts apps/Ember/ember_web/src/utils/tickets.ts
git commit -m "feat(ember-web): tickets client"
```

---

### Task 2: Tickets page (ember_web)

**Files:**
- Create: `apps/Ember/ember_web/src/views/TicketsView.vue`
- Modify: `apps/Ember/ember_web/src/router/index.ts` (route, after `usage`)
- Modify: `apps/Ember/ember_web/src/router/pages.ts` (nav entry, after Usage)
- Test: `apps/Ember/ember_web/src/views/TicketsView.test.ts`

**Interfaces:**
- Consumes: `ticketsClient`, `STATUS_LABELS`, `TYPE_LABELS`, `STATUS_ICONS`, `COMMENT_ROLE_LABELS`, `formatTicketTime` (Task 1); existing `BaseModal` (props `open`, `title`; emits `close`), `ConfirmModal` (props `open`, `title`, `message`, `confirmLabel`, `danger`, `busy`; emits `confirm`, `close`), `SegmentedControl` (`v-model`, `options`, `label`), `errorMessage` from `../utils/errors`, `../components/infoPage.css`.
- Produces: route `/tickets` (name `tickets`, `meta.permission: "tickets.create"`), nav entry label "Tickets".

Behavior:
- On mount, loads the account's tickets; a segmented status filter (All, Open, In progress, Resolved, Closed) reloads them; the newest request wins.
- "New ticket" opens a modal: type (Bug, Feature, Other), title (max 120), description (max 4000). Submit is disabled until both texts are non-empty. On success: modal closes, notice "Ticket N filed. Support will review it.", list reloads. On failure: the error shows in the modal and the draft is kept.
- Clicking a ticket opens a detail modal (loads the ticket with its comments): type, status with icon, filed time, description, comment thread (role label, time, body), reply box (max 2000) with Send, and "Close ticket" (hidden when already closed) behind a `ConfirmModal`.
- Empty states: "You have no tickets yet." and "No tickets with this status."

- [ ] **Step 1: Write the failing test**

`src/views/TicketsView.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { ticketsClient, type Ticket } from "../api/TicketsClient";
import TicketsView from "./TicketsView.vue";

vi.mock("../api/TicketsClient", () => ({
  ticketsClient: { list: vi.fn(), get: vi.fn(), create: vi.fn(), comment: vi.fn(), close: vi.fn() },
}));

const client = vi.mocked(ticketsClient);

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const ticket = (id: number, extra: Partial<Ticket> = {}): Ticket => ({
  id,
  type: "bug",
  title: `Ticket ${id}`,
  description: `Description ${id}`,
  status: "open",
  created_at: "2026-10-10T10:00:00+00:00",
  updated_at: "2026-10-10T11:00:00+00:00",
  closed_at: null,
  ...extra,
});

async function mountView() {
  const wrapper = mount(TicketsView, { attachTo: document.body });
  await flushPromises();
  return wrapper;
}

const rows = (wrapper: ReturnType<typeof mount>) => wrapper.findAll("button.ticket-row");
const button = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll("button").find((b) => b.text() === text)!;

beforeEach(() => {
  vi.clearAllMocks();
  client.list.mockResolvedValue([ticket(2, { status: "in_progress" }), ticket(1)]);
});

describe("TicketsView", () => {
  it("lists the account's tickets with a status word", async () => {
    const wrapper = await mountView();

    expect(rows(wrapper)).toHaveLength(2);
    expect(rows(wrapper)[0]!.text()).toContain("Ticket 2");
    expect(rows(wrapper)[0]!.text()).toContain("In progress");
    expect(rows(wrapper)[1]!.text()).toContain("Open");
    expect(client.list).toHaveBeenCalledWith(undefined);
  });

  it("filters by status", async () => {
    const wrapper = await mountView();

    await wrapper.findAll("button.segment").find((b) => b.text() === "Closed")!.trigger("click");
    await flushPromises();

    expect(client.list).toHaveBeenLastCalledWith("closed");
  });

  it("explains an empty list", async () => {
    client.list.mockResolvedValue([]);
    const wrapper = await mountView();

    expect(wrapper.text()).toContain("You have no tickets yet.");
  });

  it("shows a load error", async () => {
    client.list.mockRejectedValue(new ApiError(502, "mcp_server is unreachable"));
    const wrapper = await mountView();

    expect(wrapper.find(".error").text()).toContain("mcp_server is unreachable");
  });

  it("files a ticket, tells the user its number and reloads", async () => {
    client.create.mockResolvedValue({ ticket: ticket(9), duplicate: false, group_size: 1 });
    const wrapper = await mountView();
    await button(wrapper, "New ticket").trigger("click");

    const submit = wrapper.find("button.submit-ticket");
    expect(submit.attributes("disabled")).toBeDefined();
    await wrapper.find("input[aria-label='Title']").setValue("Email fails");
    await wrapper.find("textarea[aria-label='Description']").setValue("It does not send");
    expect(submit.attributes("disabled")).toBeUndefined();
    await submit.trigger("click");
    await flushPromises();

    expect(client.create).toHaveBeenCalledWith({ type: "bug", title: "Email fails", description: "It does not send" });
    expect(wrapper.find(".notice").text()).toBe("Ticket 9 filed. Support will review it.");
    expect(client.list).toHaveBeenCalledTimes(2);
  });

  it("keeps the draft and shows the error when filing fails", async () => {
    client.create.mockRejectedValue(new ApiError(400, "The title is not acceptable."));
    const wrapper = await mountView();
    await button(wrapper, "New ticket").trigger("click");
    await wrapper.find("input[aria-label='Title']").setValue("x");
    await wrapper.find("textarea[aria-label='Description']").setValue("y");

    await wrapper.find("button.submit-ticket").trigger("click");
    await flushPromises();

    expect(wrapper.find(".form-error").text()).toBe("The title is not acceptable.");
    expect((wrapper.find("input[aria-label='Title']").element as HTMLInputElement).value).toBe("x");
  });

  it("opens a ticket with its thread and sends a reply", async () => {
    client.get.mockResolvedValue(
      ticket(1, {
        comments: [
          { id: 1, ticket_id: 1, author: "root", author_role: "staff", body: "Please send the log.", created_at: "2026-10-10T12:00:00+00:00" },
          { id: 2, ticket_id: 1, author: "ada", author_role: "ai", body: "Log attached.", created_at: "2026-10-10T12:05:00+00:00" },
        ],
      }),
    );
    client.comment.mockResolvedValue(ticket(1, { comments: [] }));
    const wrapper = await mountView();

    await rows(wrapper)[1]!.trigger("click");
    await flushPromises();

    expect(client.get).toHaveBeenCalledWith(1);
    const thread = wrapper.find(".thread").text();
    expect(thread).toContain("Support");
    expect(thread).toContain("Please send the log.");
    expect(thread).toContain("Assistant, for you");

    await wrapper.find("textarea[aria-label='Reply']").setValue("More details");
    await button(wrapper, "Send").trigger("click");
    await flushPromises();

    expect(client.comment).toHaveBeenCalledWith(1, "More details");
  });

  it("closes a ticket only after confirming", async () => {
    client.get.mockResolvedValue(ticket(1, { comments: [] }));
    client.close.mockResolvedValue(ticket(1, { status: "closed" }));
    const wrapper = await mountView();
    await rows(wrapper)[1]!.trigger("click");
    await flushPromises();

    await button(wrapper, "Close ticket").trigger("click");
    expect(client.close).not.toHaveBeenCalled();
    await button(wrapper, "Close the ticket").trigger("click");
    await flushPromises();

    expect(client.close).toHaveBeenCalledWith(1);
  });

  it("offers no close button on a closed ticket", async () => {
    client.get.mockResolvedValue(ticket(1, { status: "closed", comments: [] }));
    const wrapper = await mountView();
    await rows(wrapper)[1]!.trigger("click");
    await flushPromises();

    expect(wrapper.findAll("button").some((b) => b.text() === "Close ticket")).toBe(false);
  });
});
```

(The `ConfirmModal`'s confirm button text is its `confirmLabel`; this test expects the page to pass `confirm-label="Close the ticket"`.)

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run src/views/TicketsView.test.ts`
Expected: FAIL (cannot find `./TicketsView.vue`).

- [ ] **Step 3: Implement the view**

`src/views/TicketsView.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ticketsClient, type NewTicket, type Ticket, type TicketStatus } from "../api/TicketsClient";
import BaseModal from "../components/BaseModal.vue";
import ConfirmModal from "../components/ConfirmModal.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import "../components/infoPage.css";
import { errorMessage } from "../utils/errors";
import { COMMENT_ROLE_LABELS, STATUS_ICONS, STATUS_LABELS, TYPE_LABELS, formatTicketTime } from "../utils/tickets";

/** The signed-in account's own tickets (ember_api's /api/tickets): report a
 * bug or suggest a feature, follow what support answers, add details, close. */

type Filter = "all" | TicketStatus;
const FILTER_OPTIONS = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
] as const;
const TYPE_OPTIONS = [
  { value: "bug", label: "Bug" },
  { value: "feature", label: "Feature" },
  { value: "other", label: "Other" },
] as const;

const filter = ref<Filter>("all");
const tickets = ref<Ticket[]>([]);
const loading = ref(true);
const loadError = ref("");
const notice = ref("");

// Only the newest list request may fill the page.
let loadSeq = 0;
async function load(): Promise<void> {
  const seq = ++loadSeq;
  try {
    const rows = await ticketsClient.list(filter.value === "all" ? undefined : filter.value);
    if (seq !== loadSeq) return;
    tickets.value = rows;
    loadError.value = "";
  } catch (err) {
    if (seq === loadSeq) loadError.value = errorMessage(err);
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}
watch(filter, load);
onMounted(load);

// ---- new ticket ----
const newOpen = ref(false);
const draft = reactive<NewTicket>({ type: "bug", title: "", description: "" });
const saving = ref(false);
const formError = ref("");
const canSubmit = computed(() => draft.title.trim() !== "" && draft.description.trim() !== "" && !saving.value);

function startNew(): void {
  formError.value = "";
  newOpen.value = true;
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  saving.value = true;
  formError.value = "";
  try {
    const created = await ticketsClient.create({ type: draft.type, title: draft.title.trim(), description: draft.description.trim() });
    notice.value = `Ticket ${created.ticket.id} filed. Support will review it.`;
    draft.type = "bug";
    draft.title = "";
    draft.description = "";
    newOpen.value = false;
    await load();
  } catch (err) {
    formError.value = errorMessage(err);
  } finally {
    saving.value = false;
  }
}

// ---- one ticket ----
const current = ref<Ticket | null>(null);
const detailError = ref("");
const reply = ref("");
const replying = ref(false);
const confirmOpen = ref(false);
const closing = ref(false);

async function open(ticket: Ticket): Promise<void> {
  current.value = ticket;
  detailError.value = "";
  reply.value = "";
  try {
    current.value = await ticketsClient.get(ticket.id);
  } catch (err) {
    detailError.value = errorMessage(err);
  }
}

function dismiss(): void {
  current.value = null;
  confirmOpen.value = false;
}

async function sendReply(): Promise<void> {
  if (!current.value || reply.value.trim() === "" || replying.value) return;
  replying.value = true;
  detailError.value = "";
  try {
    current.value = await ticketsClient.comment(current.value.id, reply.value.trim());
    reply.value = "";
  } catch (err) {
    detailError.value = errorMessage(err);
  } finally {
    replying.value = false;
  }
}

async function closeTicket(): Promise<void> {
  if (!current.value || closing.value) return;
  closing.value = true;
  detailError.value = "";
  try {
    current.value = await ticketsClient.close(current.value.id);
    confirmOpen.value = false;
    await load();
  } catch (err) {
    detailError.value = errorMessage(err);
    confirmOpen.value = false;
  } finally {
    closing.value = false;
  }
}
</script>

<template>
  <section class="info-page tickets">
    <div class="column page-column">
      <div class="top">
        <div>
          <h2 class="page-title">Tickets</h2>
          <p class="muted intro page-description">Report a bug, suggest a feature, or ask for help. Support answers here.</p>
        </div>
        <button type="button" class="primary" @click="startNew">New ticket</button>
      </div>

      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
      <SegmentedControl v-model="filter" :options="FILTER_OPTIONS" label="Status" aria-label="Ticket status" />

      <p v-if="loadError" class="error" role="alert">Could not load your tickets: {{ loadError }}</p>
      <p v-if="loading" class="muted">Loading …</p>
      <p v-else-if="tickets.length === 0 && !loadError" class="muted">
        {{ filter === "all" ? "You have no tickets yet." : "No tickets with this status." }}
      </p>
      <ul v-else class="list">
        <li v-for="t in tickets" :key="t.id">
          <button type="button" class="ticket-row card" @click="open(t)">
            <span class="title">{{ t.title }}</span>
            <span class="meta">
              <span class="badge">{{ TYPE_LABELS[t.type] }}</span>
              <span class="status">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="STATUS_ICONS[t.status]" /></svg>{{ STATUS_LABELS[t.status] }}
              </span>
              <span class="muted">#{{ t.id }} · updated {{ formatTicketTime(t.updated_at) }}</span>
            </span>
          </button>
        </li>
      </ul>
    </div>

    <BaseModal :open="newOpen" title="New ticket" @close="newOpen = false">
      <form class="form" @submit.prevent="submit">
        <SegmentedControl v-model="draft.type" :options="TYPE_OPTIONS" label="Type" aria-label="Ticket type" />
        <label>Title<input v-model="draft.title" type="text" maxlength="120" aria-label="Title" /></label>
        <label>
          Description
          <textarea v-model="draft.description" rows="6" maxlength="4000" aria-label="Description" />
        </label>
        <p v-if="formError" class="form-error error" role="alert">{{ formError }}</p>
        <div class="actions">
          <button type="button" class="chip" @click="newOpen = false">Cancel</button>
          <button type="submit" class="primary submit-ticket" :disabled="!canSubmit" :aria-busy="saving">Submit</button>
        </div>
      </form>
    </BaseModal>

    <BaseModal :open="current !== null" :title="current ? `Ticket #${current.id}` : 'Ticket'" @close="dismiss">
      <template v-if="current">
        <h3 class="detail-title">{{ current.title }}</h3>
        <p class="meta">
          <span class="badge">{{ TYPE_LABELS[current.type] }}</span>
          <span class="status">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="STATUS_ICONS[current.status]" /></svg>{{ STATUS_LABELS[current.status] }}
          </span>
          <span class="muted">Filed {{ formatTicketTime(current.created_at) }}</span>
        </p>
        <p class="text">{{ current.description }}</p>
        <p v-if="detailError" class="error" role="alert">{{ detailError }}</p>

        <ul v-if="current.comments?.length" class="thread" aria-label="Comments">
          <li v-for="c in current.comments" :key="c.id">
            <div class="who">
              <b>{{ COMMENT_ROLE_LABELS[c.author_role] }}</b>
              <span class="muted">{{ formatTicketTime(c.created_at) }}</span>
            </div>
            <p class="text">{{ c.body }}</p>
          </li>
        </ul>

        <form class="form reply" @submit.prevent="sendReply">
          <textarea v-model="reply" rows="3" maxlength="2000" aria-label="Reply" placeholder="Add details or answer a question" />
          <div class="actions">
            <button v-if="current.status !== 'closed'" type="button" class="chip" @click="confirmOpen = true">Close ticket</button>
            <button type="submit" class="primary" :disabled="reply.trim() === '' || replying" :aria-busy="replying">Send</button>
          </div>
        </form>
      </template>
    </BaseModal>

    <ConfirmModal
      :open="confirmOpen"
      title="Close this ticket?"
      message="Support will see it as closed. You can still add a comment later."
      confirm-label="Close the ticket"
      :busy="closing"
      @confirm="closeTicket"
      @close="confirmOpen = false"
    />
  </section>
</template>

<style scoped>
.top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}
.ticket-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  margin: 0;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.ticket-row:hover {
  border-color: var(--accent);
}
.title {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  margin: 0;
  font-size: 0.85em;
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.9em;
  color: var(--muted);
}
.status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.status svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.notice {
  margin: 8px 0;
  color: var(--muted);
}
.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.9em;
}
.form textarea,
.form input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
  resize: vertical;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.detail-title {
  margin: 0 0 6px;
  overflow-wrap: anywhere;
}
.text {
  margin: 8px 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.thread {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 12px 0;
  padding: 0;
  list-style: none;
}
.thread li {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
}
.thread .who {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 0.85em;
}
.thread .text {
  margin: 4px 0 0;
}
.reply {
  margin-top: 12px;
}
</style>
```

- [ ] **Step 4: Register the route and the nav entry**

In `src/router/index.ts`, after the `usage` route add:

```ts
    {
      path: "/tickets",
      name: "tickets",
      component: () => import("../views/TicketsView.vue"),
      meta: { permission: "tickets.create" },
    },
```

In `src/router/pages.ts`, add to `NAV_PAGES` after the Usage entry (before Settings):

```ts
  {
    to: "/tickets",
    label: "Tickets",
    icon: ["M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z", "M13 5v2", "M13 17v2", "M13 11v2"],
    description: "Report a bug, suggest a feature or ask for help, and follow the answers.",
    permission: "tickets.create",
  },
```

- [ ] **Step 5: Run tests and checks**

Run: `npx vitest run src/views/TicketsView.test.ts`
Expected: PASS.

Run: `npx vue-tsc -b --noEmit` (prints nothing), then `npm test`
Expected: all pass, including `radiusScale.test.ts`. If `NavRail.test.ts` or `OverviewView.test.ts` enumerate pages for an account that holds `tickets.create`, update only those expectations. Accounts in the existing tests do not hold it.

- [ ] **Step 6: Hand-test note for the user (do not automate)**

Tell the user to test by hand: log in as a Member, open Tickets, file a ticket, open it, reply, close it; also check the page at 768 and 375 px wide and in dark mode. To check the UI without ember_api, run the e2e fake server approach in the `project-ember-web-ui-conventions` memory note (a fake `/api`).

- [ ] **Step 7: Commit**

```bash
git add apps/Ember/ember_web/src/views/TicketsView.vue apps/Ember/ember_web/src/views/TicketsView.test.ts apps/Ember/ember_web/src/router/index.ts apps/Ember/ember_web/src/router/pages.ts
git commit -m "feat(ember-web): tickets page"
```

---

# Part B: ember_admin

### Task 3: TicketsAdminClient and helpers (ember_admin)

**Files:**
- Create: `apps/Ember/ember_admin/src/api/TicketsAdminClient.ts`
- Create: `apps/Ember/ember_admin/src/utils/ticketFormat.ts`
- Test: `apps/Ember/ember_admin/src/api/TicketsAdminClient.test.ts`

**Interfaces:**
- Consumes: `apiRequest` from `./http` (same signature as ember_web's).
- Produces:

```ts
export type TicketType, TicketStatus, TicketPriority ("low"|"normal"|"high"|"urgent")
export interface TicketComment { id; ticket_id; author; author_role: "reporter"|"staff"|"ai"; body; created_at }
export interface AdminTicket { id; group_id; type; title; description; status; priority; effective_priority; assignee: string|null; reporter: string; source: "user"|"ai_user_request"|"ai_auto"; tags: string[]; context: { reported?: Record<string,string>; verified?: Record<string,string> }; possible_group_id: number|null; created_at; updated_at; closed_at: string|null; comments?: TicketComment[] }
export interface TicketGroup { id; title; priority; priority_pinned: boolean; ticket_count: number; recent_count: number; open_count: number; last_activity: string; tags: string[] }
export interface TicketFilters { status?; type?; tag?; priority?; assignee?; group_id?: number; possible?: boolean; limit?: number }
export interface TicketChanges { status?: TicketStatus; priority?: TicketPriority; assignee?: string; tags?: string[] }
export interface GroupChanges { priority?: TicketPriority; pinned?: boolean }
export interface TicketStats { open: number; urgent: number; groups: number }
export const ticketsAdminClient: {
  listGroups(filters?: Pick<TicketFilters,"status"|"tag"|"priority">): Promise<TicketGroup[]>;
  listTickets(filters?: TicketFilters): Promise<AdminTicket[]>;
  get(id: number): Promise<AdminTicket>;
  update(id: number, changes: TicketChanges): Promise<AdminTicket>;
  comment(id: number, body: string): Promise<AdminTicket>;
  move(id: number, groupId: number | null): Promise<AdminTicket>;
  updateGroup(id: number, changes: GroupChanges): Promise<TicketGroup>;
  stats(): Promise<TicketStats>;
}
// ticketFormat.ts
STATUS_LABELS, TYPE_LABELS, PRIORITY_LABELS, SOURCE_LABELS, STATUS_ICONS, COMMENT_ROLE_LABELS (reporter: "Reporter", ai: "Assistant for reporter", staff: "Staff"), formatTicketTime
```

`updateGroup` returns the `group` object (the client unwraps `{ group }`). A group returned by PATCH has no counts; callers reload the list after changing it.

- [ ] **Step 1: Write the failing test**

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { ticketsAdminClient } from "./TicketsAdminClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ticketsAdminClient", () => {
  it("lists groups with only the filters that are set", async () => {
    request.mockResolvedValue({ groups: [{ id: 3 }] });

    expect(await ticketsAdminClient.listGroups()).toEqual([{ id: 3 }]);
    expect(request).toHaveBeenLastCalledWith("GET", "/api/admin/ticket-groups");
    await ticketsAdminClient.listGroups({ status: "open", tag: "email", priority: undefined });
    expect(request).toHaveBeenLastCalledWith("GET", "/api/admin/ticket-groups?status=open&tag=email");
  });

  it("lists tickets by group, by possible duplicate, and encodes values", async () => {
    request.mockResolvedValue({ tickets: [] });

    await ticketsAdminClient.listTickets({ group_id: 3 });
    expect(request).toHaveBeenLastCalledWith("GET", "/api/admin/tickets?group_id=3");
    await ticketsAdminClient.listTickets({ possible: true, assignee: "a b" });
    expect(request).toHaveBeenLastCalledWith("GET", "/api/admin/tickets?assignee=a%20b&possible=true");
    await ticketsAdminClient.listTickets({ possible: false });
    expect(request).toHaveBeenLastCalledWith("GET", "/api/admin/tickets");
  });

  it("gets, updates, comments on and moves a ticket and unwraps it", async () => {
    request.mockResolvedValue({ ticket: { id: 7 } });

    expect(await ticketsAdminClient.get(7)).toEqual({ id: 7 });
    expect(request).toHaveBeenLastCalledWith("GET", "/api/admin/tickets/7");
    await ticketsAdminClient.update(7, { status: "closed", assignee: "" });
    expect(request).toHaveBeenLastCalledWith("PATCH", "/api/admin/tickets/7", { status: "closed", assignee: "" });
    await ticketsAdminClient.comment(7, "looking");
    expect(request).toHaveBeenLastCalledWith("POST", "/api/admin/tickets/7/comments", { body: "looking" });
    await ticketsAdminClient.move(7, null);
    expect(request).toHaveBeenLastCalledWith("POST", "/api/admin/tickets/7/move", { group_id: null });
  });

  it("changes a group's priority or pin and reads the stats", async () => {
    request.mockResolvedValue({ group: { id: 3, priority: "urgent" } });
    expect(await ticketsAdminClient.updateGroup(3, { priority: "urgent" })).toEqual({ id: 3, priority: "urgent" });
    expect(request).toHaveBeenLastCalledWith("PATCH", "/api/admin/ticket-groups/3", { priority: "urgent" });

    request.mockResolvedValue({ open: 2, urgent: 1, groups: 2 });
    expect(await ticketsAdminClient.stats()).toEqual({ open: 2, urgent: 1, groups: 2 });
    expect(request).toHaveBeenLastCalledWith("GET", "/api/admin/tickets/stats");
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run src/api/TicketsAdminClient.test.ts`
Expected: FAIL (cannot find the client).

- [ ] **Step 3: Implement**

`src/api/TicketsAdminClient.ts`:

```ts
import { apiRequest } from "./http";

export type TicketType = "bug" | "feature" | "other";
export type TicketStatus = "open" | "in_progress" | "resolved" | "closed";
export type TicketPriority = "low" | "normal" | "high" | "urgent";
export type TicketSource = "user" | "ai_user_request" | "ai_auto";

export interface TicketComment {
  id: number;
  ticket_id: number;
  author: string;
  author_role: "reporter" | "staff" | "ai";
  body: string;
  created_at: string;
}

export interface AdminTicket {
  id: number;
  group_id: number;
  type: TicketType;
  title: string;
  description: string;
  status: TicketStatus;
  /** The ticket's own priority; the group's can be higher. */
  priority: TicketPriority;
  /** The higher of the ticket's and its group's priority. */
  effective_priority: TicketPriority;
  assignee: string | null;
  reporter: string;
  source: TicketSource;
  tags: string[];
  /** `reported` came from the reporter or a model and is unverified; `verified` was added by ember_api. */
  context: { reported?: Record<string, string>; verified?: Record<string, string> };
  /** Laya was unsure whether this ticket belongs to that group. */
  possible_group_id: number | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  comments?: TicketComment[];
}

export interface TicketGroup {
  id: number;
  title: string;
  priority: TicketPriority;
  /** An admin set the priority by hand; automatic elevation is off. */
  priority_pinned: boolean;
  ticket_count: number;
  recent_count: number;
  open_count: number;
  last_activity: string;
  tags: string[];
}

export interface TicketFilters {
  status?: TicketStatus;
  type?: TicketType;
  tag?: string;
  priority?: TicketPriority;
  assignee?: string;
  group_id?: number;
  possible?: boolean;
  limit?: number;
}

/** An empty assignee clears it. */
export interface TicketChanges {
  status?: TicketStatus;
  priority?: TicketPriority;
  assignee?: string;
  tags?: string[];
}

/** A priority pins the group; pinned false hands it back to automatic elevation. */
export interface GroupChanges {
  priority?: TicketPriority;
  pinned?: boolean;
}

export interface TicketStats {
  open: number;
  urgent: number;
  groups: number;
}

function query(filters: TicketFilters = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === false || value === "") continue;
    params.set(key, String(value));
  }
  const text = params.toString().replaceAll("+", "%20");
  return text ? `?${text}` : "";
}

export const ticketsAdminClient = {
  listGroups: async (filters: Pick<TicketFilters, "status" | "tag" | "priority"> = {}): Promise<TicketGroup[]> =>
    (await apiRequest<{ groups: TicketGroup[] }>("GET", `/api/admin/ticket-groups${query(filters)}`)).groups,
  listTickets: async (filters: TicketFilters = {}): Promise<AdminTicket[]> =>
    (await apiRequest<{ tickets: AdminTicket[] }>("GET", `/api/admin/tickets${query(filters)}`)).tickets,
  get: async (id: number): Promise<AdminTicket> =>
    (await apiRequest<{ ticket: AdminTicket }>("GET", `/api/admin/tickets/${id}`)).ticket,
  update: async (id: number, changes: TicketChanges): Promise<AdminTicket> =>
    (await apiRequest<{ ticket: AdminTicket }>("PATCH", `/api/admin/tickets/${id}`, changes)).ticket,
  comment: async (id: number, body: string): Promise<AdminTicket> =>
    (await apiRequest<{ ticket: AdminTicket }>("POST", `/api/admin/tickets/${id}/comments`, { body })).ticket,
  move: async (id: number, groupId: number | null): Promise<AdminTicket> =>
    (await apiRequest<{ ticket: AdminTicket }>("POST", `/api/admin/tickets/${id}/move`, { group_id: groupId })).ticket,
  updateGroup: async (id: number, changes: GroupChanges): Promise<TicketGroup> =>
    (await apiRequest<{ group: TicketGroup }>("PATCH", `/api/admin/ticket-groups/${id}`, changes)).group,
  stats: () => apiRequest<TicketStats>("GET", "/api/admin/tickets/stats"),
};
```

The expected URL for `{ possible: true, assignee: "a b" }` in the test is `assignee=a%20b&possible=true`: `URLSearchParams` writes `a+b`, so the `replaceAll("+", "%20")` above makes it match (a literal `+` in a value is encoded as `%2B` by `URLSearchParams`, so the replacement is safe).

`src/utils/ticketFormat.ts`:

```ts
import type { TicketComment, TicketPriority, TicketSource, TicketStatus, TicketType } from "../api/TicketsAdminClient";

export const STATUS_LABELS: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  closed: "Closed",
};
export const TYPE_LABELS: Record<TicketType, string> = { bug: "Bug", feature: "Feature", other: "Other" };
export const PRIORITY_LABELS: Record<TicketPriority, string> = { low: "Low", normal: "Normal", high: "High", urgent: "Urgent" };
export const SOURCE_LABELS: Record<TicketSource, string> = {
  user: "Reporter",
  ai_user_request: "AI, asked by reporter",
  ai_auto: "AI, automatic",
};
export const COMMENT_ROLE_LABELS: Record<TicketComment["author_role"], string> = {
  reporter: "Reporter",
  ai: "Assistant for reporter",
  staff: "Staff",
};

/** Stroked 24x24 icon path data per status: a status is never shown by color alone. */
export const STATUS_ICONS: Record<TicketStatus, string> = {
  open: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  in_progress: "M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  resolved: "M20 6L9 17l-5-5",
  closed: "M8 12h8M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
};

/** The filters of the staff Tickets page, kept in the URL. */
export interface TicketFilterState {
  status: "all" | TicketStatus;
  priority: "all" | TicketPriority;
  tag: string;
  mode: "groups" | "review";
}

/** mcp_server times carry an offset ("+00:00"), so they parse as they are. */
export function formatTicketTime(iso: string): string {
  return new Date(iso).toLocaleString();
}
```

- [ ] **Step 4: Run test and type-check**

Run: `npx vitest run src/api/TicketsAdminClient.test.ts` then `npx vue-tsc -b --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_admin/src/api/TicketsAdminClient.ts apps/Ember/ember_admin/src/api/TicketsAdminClient.test.ts apps/Ember/ember_admin/src/utils/ticketFormat.ts
git commit -m "feat(ember-admin): tickets admin client"
```

---

### Task 4: TicketDrawer component

**Files:**
- Create: `apps/Ember/ember_admin/src/components/admin/TicketDrawer.vue`
- Test: `apps/Ember/ember_admin/src/components/admin/TicketDrawer.test.ts`

**Interfaces:**
- Consumes: types and helpers from Task 3, `admin.css`.
- Produces: `<TicketDrawer :ticket="AdminTicket" :busy="boolean" :error="string" :notice="string" />` emitting `close`, `update` (`TicketChanges`), `comment` (`string`), `move` (`number | null`). It only shows state and reports what staff chose; the parent runs calls and passes back the fresh ticket. Selects reset to the server value immediately after emitting, so a value the server has not confirmed is never shown. The assignee and tags fields have their own Save buttons (tags are entered comma-separated).

- [ ] **Step 1: Write the failing test**

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { AdminTicket } from "../../api/TicketsAdminClient";
import TicketDrawer from "./TicketDrawer.vue";

const TICKET: AdminTicket = {
  id: 7,
  group_id: 3,
  type: "bug",
  title: "Email fails",
  description: "It does not send\nsecond line",
  status: "open",
  priority: "normal",
  effective_priority: "high",
  assignee: null,
  reporter: "alice",
  source: "ai_auto",
  tags: ["email", "config"],
  context: { reported: { tool_name: "tool_email_sendEmail", error_text: "not configured" }, verified: { account_id: "4" } },
  possible_group_id: null,
  created_at: "2026-10-10T10:00:00+00:00",
  updated_at: "2026-10-10T11:00:00+00:00",
  closed_at: null,
  comments: [{ id: 1, ticket_id: 7, author: "alice", author_role: "reporter", body: "Here is the log", created_at: "2026-10-10T12:00:00+00:00" }],
};

function drawer(extra: Partial<AdminTicket> = {}, props: { busy?: boolean; error?: string; notice?: string } = {}) {
  return mount(TicketDrawer, { props: { ticket: { ...TICKET, ...extra }, busy: false, error: "", notice: "", ...props } });
}

describe("TicketDrawer", () => {
  it("shows the ticket, its source and its context as unverified text", () => {
    const text = drawer().text();

    expect(text).toContain("Email fails");
    expect(text).toContain("alice");
    expect(text).toContain("AI, automatic");
    expect(text).toContain("Priority: High");
    expect(text).toContain("Reported by the reporter or a model (unverified)");
    expect(text).toContain("tool_email_sendEmail");
    expect(text).toContain("Added by ember_api");
    expect(text).toContain("Here is the log");
  });

  it("emits a status change and puts the select back to the server value", async () => {
    const wrapper = drawer();
    const select = wrapper.find("select[aria-label='Status']");

    (select.element as HTMLSelectElement).value = "closed";
    await select.trigger("change");

    expect(wrapper.emitted("update")![0]).toEqual([{ status: "closed" }]);
    expect((select.element as HTMLSelectElement).value).toBe("open");
  });

  it("emits a priority change", async () => {
    const wrapper = drawer();
    const select = wrapper.find("select[aria-label='Priority']");

    (select.element as HTMLSelectElement).value = "urgent";
    await select.trigger("change");

    expect(wrapper.emitted("update")![0]).toEqual([{ priority: "urgent" }]);
  });

  it("saves the assignee, and an empty one clears it", async () => {
    const wrapper = drawer({ assignee: "root" });
    const input = wrapper.find("input[aria-label='Assignee']");

    await input.setValue("");
    await wrapper.find("button.save-assignee").trigger("click");

    expect(wrapper.emitted("update")![0]).toEqual([{ assignee: "" }]);
  });

  it("saves tags typed with commas", async () => {
    const wrapper = drawer();

    await wrapper.find("input[aria-label='Tags']").setValue(" auth, ui ,, ");
    await wrapper.find("button.save-tags").trigger("click");

    expect(wrapper.emitted("update")![0]).toEqual([{ tags: ["auth", "ui"] }]);
  });

  it("moves to a typed group, splits out, and offers the Laya hint", async () => {
    const wrapper = drawer({ possible_group_id: 5 });

    await wrapper.find("input[aria-label='Group number']").setValue("9");
    await wrapper.find("button.move").trigger("click");
    await wrapper.find("button.split").trigger("click");
    await wrapper.find("button.move-hint").trigger("click");

    expect(wrapper.emitted("move")).toEqual([[9], [null], [5]]);
    expect(wrapper.find("button.move-hint").text()).toContain("group 5");
  });

  it("does not offer the hint when there is none", () => {
    expect(drawer().find("button.move-hint").exists()).toBe(false);
  });

  it("sends a staff comment and clears the box only when the parent says the ticket changed", async () => {
    const wrapper = drawer();

    await wrapper.find("textarea[aria-label='Reply']").setValue("Looking into it");
    await wrapper.find("button.send-reply").trigger("click");

    expect(wrapper.emitted("comment")![0]).toEqual(["Looking into it"]);
    await wrapper.setProps({ ticket: { ...TICKET, comments: [...TICKET.comments!, { id: 2, ticket_id: 7, author: "root", author_role: "staff", body: "Looking into it", created_at: "2026-10-10T13:00:00+00:00" }] } });
    expect((wrapper.find("textarea[aria-label='Reply']").element as HTMLTextAreaElement).value).toBe("");
  });

  it("disables every control while busy and shows errors and notices", () => {
    const wrapper = drawer({}, { busy: true, error: "mcp_server is unreachable", notice: "Saved" });

    expect(wrapper.find("select[aria-label='Status']").attributes("disabled")).toBeDefined();
    expect(wrapper.find("button.send-reply").attributes("disabled")).toBeDefined();
    expect(wrapper.find(".error").text()).toBe("mcp_server is unreachable");
    expect(wrapper.find(".notice").text()).toBe("Saved");
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run src/components/admin/TicketDrawer.test.ts`
Expected: FAIL (cannot find the component).

- [ ] **Step 3: Implement**

`src/components/admin/TicketDrawer.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { AdminTicket, TicketChanges, TicketPriority, TicketStatus } from "../../api/TicketsAdminClient";
import {
  COMMENT_ROLE_LABELS,
  PRIORITY_LABELS,
  SOURCE_LABELS,
  STATUS_ICONS,
  STATUS_LABELS,
  TYPE_LABELS,
  formatTicketTime,
} from "../../utils/ticketFormat";
import "./admin.css";

/** One ticket for staff: details, the reporter's context (unverified), status,
 * priority, assignee, tags, group, and the thread. It only shows state and
 * reports what staff chose (the parent runs the call and passes the fresh
 * ticket back); `busy` disables the controls while a call is in flight. */
const props = defineProps<{ ticket: AdminTicket; busy: boolean; error: string; notice: string }>();
const emit = defineEmits<{
  close: [];
  update: [changes: TicketChanges];
  comment: [body: string];
  move: [groupId: number | null];
}>();

const STATUSES = Object.keys(STATUS_LABELS) as TicketStatus[];
const PRIORITIES = Object.keys(PRIORITY_LABELS) as TicketPriority[];

const assignee = ref("");
const tags = ref("");
const groupNumber = ref("");
const reply = ref("");

watch(
  () => props.ticket,
  (ticket, previous) => {
    assignee.value = ticket.assignee ?? "";
    tags.value = ticket.tags.join(", ");
    if (previous?.id !== ticket.id) groupNumber.value = "";
    // A new comment means the reply went through.
    if (previous?.id !== ticket.id || (ticket.comments?.length ?? 0) !== (previous?.comments?.length ?? 0)) reply.value = "";
  },
  { immediate: true },
);

const reported = computed(() => Object.entries(props.ticket.context.reported ?? {}));
const verified = computed(() => Object.entries(props.ticket.context.verified ?? {}));
const groupId = computed(() => {
  const value = Number.parseInt(groupNumber.value, 10);
  return Number.isInteger(value) && value > 0 ? value : null;
});

/** A server-confirmed control: report the choice, then show the server's value again until the ticket comes back. */
function choose<K extends "status" | "priority">(key: K, event: Event, current: string): void {
  const select = event.target as HTMLSelectElement;
  const value = select.value;
  select.value = current;
  if (value !== current) emit("update", { [key]: value } as TicketChanges);
}

function saveTags(): void {
  emit("update", { tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean) });
}

function send(): void {
  if (reply.value.trim() !== "") emit("comment", reply.value.trim());
}
</script>

<template>
  <aside class="drawer admin-panel" :aria-label="`Ticket ${ticket.id}`">
    <header class="head">
      <div>
        <b class="name">#{{ ticket.id }} {{ ticket.title }}</b>
        <p class="meta muted">
          {{ TYPE_LABELS[ticket.type] }} · from <b>{{ ticket.reporter }}</b> · {{ SOURCE_LABELS[ticket.source] }}
        </p>
        <p class="meta">
          <span class="status">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="STATUS_ICONS[ticket.status]" /></svg>{{ STATUS_LABELS[ticket.status] }}
          </span>
          <span>Priority: {{ PRIORITY_LABELS[ticket.effective_priority] }}</span>
          <span class="muted">Group {{ ticket.group_id }}</span>
        </p>
        <p class="meta muted">Filed {{ formatTicketTime(ticket.created_at) }} · updated {{ formatTicketTime(ticket.updated_at) }}</p>
      </div>
      <button type="button" class="x" aria-label="Close" @click="emit('close')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </header>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>

    <p class="text">{{ ticket.description }}</p>

    <section v-if="reported.length || verified.length" class="context">
      <h4>Context</h4>
      <template v-if="reported.length">
        <p class="muted small-text">Reported by the reporter or a model (unverified)</p>
        <dl>
          <template v-for="[key, value] in reported" :key="`r-${key}`">
            <dt>{{ key }}</dt>
            <dd class="mono">{{ value }}</dd>
          </template>
        </dl>
      </template>
      <template v-if="verified.length">
        <p class="muted small-text">Added by ember_api</p>
        <dl>
          <template v-for="[key, value] in verified" :key="`v-${key}`">
            <dt>{{ key }}</dt>
            <dd class="mono">{{ value }}</dd>
          </template>
        </dl>
      </template>
    </section>

    <section class="controls">
      <label>
        Status
        <select aria-label="Status" :disabled="busy" :value="ticket.status" @change="choose('status', $event, ticket.status)">
          <option v-for="s in STATUSES" :key="s" :value="s">{{ STATUS_LABELS[s] }}</option>
        </select>
      </label>
      <label>
        Priority
        <select aria-label="Priority" :disabled="busy" :value="ticket.priority" @change="choose('priority', $event, ticket.priority)">
          <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABELS[p] }}</option>
        </select>
      </label>
      <div class="row-form">
        <input v-model="assignee" type="text" maxlength="64" aria-label="Assignee" placeholder="Assignee (username)" :disabled="busy" />
        <button type="button" class="small save-assignee" :disabled="busy" @click="emit('update', { assignee })">Save</button>
      </div>
      <div class="row-form">
        <input v-model="tags" type="text" aria-label="Tags" placeholder="Tags, separated by commas" :disabled="busy" />
        <button type="button" class="small save-tags" :disabled="busy" @click="saveTags">Save</button>
      </div>
      <div class="row-form">
        <input v-model="groupNumber" type="text" inputmode="numeric" aria-label="Group number" placeholder="Group number" :disabled="busy" />
        <button type="button" class="small move" :disabled="busy || groupId === null" @click="emit('move', groupId)">Move</button>
        <button type="button" class="small split" :disabled="busy" @click="emit('move', null)">Split out</button>
      </div>
      <button
        v-if="ticket.possible_group_id !== null"
        type="button"
        class="small move-hint"
        :disabled="busy"
        @click="emit('move', ticket.possible_group_id)"
      >
        May belong to group {{ ticket.possible_group_id }}: move there
      </button>
    </section>

    <section class="thread-section">
      <h4>Thread</h4>
      <p v-if="!ticket.comments?.length" class="muted">No comments yet.</p>
      <ul v-else class="thread" aria-label="Comments">
        <li v-for="c in ticket.comments" :key="c.id">
          <div class="who">
            <b>{{ c.author }}</b> <span class="muted">{{ COMMENT_ROLE_LABELS[c.author_role] }} · {{ formatTicketTime(c.created_at) }}</span>
          </div>
          <p class="text">{{ c.body }}</p>
        </li>
      </ul>
      <form class="reply" @submit.prevent="send">
        <textarea v-model="reply" rows="3" maxlength="2000" aria-label="Reply" placeholder="Reply to the reporter or ask for details" :disabled="busy" />
        <button type="submit" class="primary send-reply" :disabled="busy || reply.trim() === ''" :aria-busy="busy">Reply</button>
      </form>
    </section>
  </aside>
</template>

<style scoped>
.drawer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.name {
  overflow-wrap: anywhere;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  margin: 4px 0 0;
  font-size: 0.85em;
}
.status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.status svg {
  width: 14px;
  height: 14px;
}
.x {
  padding: 4px;
  border: none;
  cursor: pointer;
  color: var(--muted);
  background: none;
}
.x svg {
  width: 18px;
  height: 18px;
}
.text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.context dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px 10px;
  margin: 4px 0 8px;
  font-size: 0.85em;
}
.context dt {
  color: var(--muted);
}
.context dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.mono {
  font-family: var(--mono);
}
.small-text {
  margin: 4px 0 0;
  font-size: 0.8em;
}
.controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.controls label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 0.9em;
}
.thread {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 10px;
  padding: 0;
  list-style: none;
}
.thread li {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
}
.thread .who {
  font-size: 0.85em;
}
.thread .text {
  margin-top: 4px;
}
.reply {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}
.reply textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
  resize: vertical;
}
</style>
```

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/components/admin/TicketDrawer.test.ts` then `npx vue-tsc -b --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add apps/Ember/ember_admin/src/components/admin/TicketDrawer.vue apps/Ember/ember_admin/src/components/admin/TicketDrawer.test.ts
git commit -m "feat(ember-admin): ticket drawer"
```

---

### Task 5: TicketsPanel, page, route and nav (ember_admin)

**Files:**
- Create: `apps/Ember/ember_admin/src/components/admin/TicketsPanel.vue`
- Create: `apps/Ember/ember_admin/src/views/TicketsAdminView.vue`
- Modify: `apps/Ember/ember_admin/src/router/index.ts` (route)
- Modify: `apps/Ember/ember_admin/src/router/pages.ts` (`ADMIN_PERMISSIONS` gains `"tickets.manage"`; `ADMIN_PAGES` gains Tickets)
- Test: `apps/Ember/ember_admin/src/components/admin/TicketsPanel.test.ts`

**Interfaces:**
- Consumes: `ticketsAdminClient`, `TicketDrawer` (Task 4), types and helpers (Task 3), `SegmentedControl`, `ToggleSwitch`, `errorMessage`.
- Produces: `<TicketsPanel :filters="TicketFilterState" @filter="..." />` (`TicketFilterState` is exported from `utils/ticketFormat.ts`) where `status: "all" | TicketStatus`, `priority: "all" | TicketPriority`, `tag: string`, `mode: "groups" | "review"`; route `/tickets` (name `tickets`, `meta.permission: "tickets.manage"`); nav page "Tickets".

Behavior:
- `mode "groups"`: one row per group (title of its oldest ticket, ticket count, tickets in the last 24 h, tags, priority select, Pinned switch). A row expands (button) to load that group's tickets (`listTickets({ group_id })`), each with reporter, a source badge, status icon and word. Clicking a ticket opens the drawer.
- `mode "review"`: a flat list of tickets whose `possible_group_id` is set (`listTickets({ possible: true })`); each row says which group it may belong to.
- Filters: status, priority, tag (select built from the tags in the loaded groups), mode. Filter changes reload; the newest request wins.
- Group priority select and Pinned switch show server-confirmed values only (reset after emitting, disabled while busy, reload after success). A group priority change pins it (ember_api/mcp_server do that); the switch off unpins.
- Every change (drawer or group) reloads the groups, the expanded group's tickets and the open ticket. Errors show above the list.

- [ ] **Step 1: Write the failing test**

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/http";
import { ticketsAdminClient, type AdminTicket, type TicketGroup } from "../../api/TicketsAdminClient";
import TicketsPanel from "./TicketsPanel.vue";

vi.mock("../../api/TicketsAdminClient", () => ({
  ticketsAdminClient: {
    listGroups: vi.fn(), listTickets: vi.fn(), get: vi.fn(), update: vi.fn(), comment: vi.fn(), move: vi.fn(), updateGroup: vi.fn(), stats: vi.fn(),
  },
}));

const client = vi.mocked(ticketsAdminClient);

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const group = (id: number, extra: Partial<TicketGroup> = {}): TicketGroup => ({
  id,
  title: `Group ${id}`,
  priority: "normal",
  priority_pinned: false,
  ticket_count: 2,
  recent_count: 1,
  open_count: 2,
  last_activity: "2026-10-10T12:00:00+00:00",
  tags: ["email"],
  ...extra,
});

const ticket = (id: number, extra: Partial<AdminTicket> = {}): AdminTicket => ({
  id,
  group_id: 1,
  type: "bug",
  title: `Ticket ${id}`,
  description: `Description ${id}`,
  status: "open",
  priority: "normal",
  effective_priority: "normal",
  assignee: null,
  reporter: "alice",
  source: "user",
  tags: ["email"],
  context: {},
  possible_group_id: null,
  created_at: "2026-10-10T10:00:00+00:00",
  updated_at: "2026-10-10T11:00:00+00:00",
  closed_at: null,
  comments: [],
  ...extra,
});

const FILTERS = { status: "all", priority: "all", tag: "", mode: "groups" } as const;

async function panel(filters: Record<string, string> = {}) {
  const wrapper = mount(TicketsPanel, { props: { filters: { ...FILTERS, ...filters } as never }, attachTo: document.body });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  client.listGroups.mockResolvedValue([group(1, { priority: "high" }), group(2, { tags: ["ui"], priority_pinned: true })]);
  client.listTickets.mockResolvedValue([ticket(11, { source: "ai_auto" }), ticket(12, { status: "closed", reporter: "bob" })]);
  client.get.mockResolvedValue(ticket(11));
  client.update.mockResolvedValue(ticket(11, { status: "closed" }));
  client.updateGroup.mockResolvedValue(group(1));
  client.comment.mockResolvedValue(ticket(11));
  client.move.mockResolvedValue(ticket(11));
});

describe("TicketsPanel", () => {
  it("lists groups with counts, tags and priority", async () => {
    const wrapper = await panel();

    const rows = wrapper.findAll(".group-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.text()).toContain("Group 1");
    expect(rows[0]!.text()).toContain("2 tickets");
    expect(rows[0]!.text()).toContain("1 in 24 h");
    expect((rows[0]!.find("select").element as HTMLSelectElement).value).toBe("high");
    expect(client.listGroups).toHaveBeenCalledWith({});
  });

  it("sends the filters to the server", async () => {
    await panel({ status: "open", priority: "urgent", tag: "email" });

    expect(client.listGroups).toHaveBeenCalledWith({ status: "open", priority: "urgent", tag: "email" });
  });

  it("expands a group to its tickets with source and status", async () => {
    const wrapper = await panel();

    await wrapper.find("button.expand").trigger("click");
    await flushPromises();

    expect(client.listTickets).toHaveBeenCalledWith({ group_id: 1 });
    const text = wrapper.find(".group-tickets").text();
    expect(text).toContain("Ticket 11");
    expect(text).toContain("AI, automatic");
    expect(text).toContain("bob");
    expect(text).toContain("Closed");
  });

  it("opens a ticket in the drawer", async () => {
    const wrapper = await panel();
    await wrapper.find("button.expand").trigger("click");
    await flushPromises();

    await wrapper.find("button.ticket-link").trigger("click");
    await flushPromises();

    expect(client.get).toHaveBeenCalledWith(11);
    expect(wrapper.find("aside.drawer").text()).toContain("Ticket 11");
  });

  it("changes a ticket from the drawer, then reloads groups and shows a notice", async () => {
    const wrapper = await panel();
    await wrapper.find("button.expand").trigger("click");
    await flushPromises();
    await wrapper.find("button.ticket-link").trigger("click");
    await flushPromises();
    client.listGroups.mockClear();

    const select = wrapper.find("select[aria-label='Status']");
    (select.element as HTMLSelectElement).value = "closed";
    await select.trigger("change");
    await flushPromises();

    expect(client.update).toHaveBeenCalledWith(11, { status: "closed" });
    expect(client.listGroups).toHaveBeenCalled();
    expect(wrapper.find("aside.drawer .notice").text()).toBe("Saved.");
  });

  it("shows an error from a failed change and leaves the server value", async () => {
    client.update.mockRejectedValue(new ApiError(400, "The status must be one of: open."));
    const wrapper = await panel();
    await wrapper.find("button.expand").trigger("click");
    await flushPromises();
    await wrapper.find("button.ticket-link").trigger("click");
    await flushPromises();

    const select = wrapper.find("select[aria-label='Status']");
    (select.element as HTMLSelectElement).value = "closed";
    await select.trigger("change");
    await flushPromises();

    expect(wrapper.find("aside.drawer .error").text()).toBe("The status must be one of: open.");
    expect((select.element as HTMLSelectElement).value).toBe("open");
  });

  it("sets a group's priority and shows only the server's value until it answers", async () => {
    const wrapper = await panel();
    const select = wrapper.find(".group-row select");

    (select.element as HTMLSelectElement).value = "urgent";
    await select.trigger("change");

    expect((select.element as HTMLSelectElement).value).toBe("high");
    expect(client.updateGroup).toHaveBeenCalledWith(1, { priority: "urgent" });
  });

  it("unpins a pinned group with the switch and keeps the shown state until the reload", async () => {
    const wrapper = await panel();
    const toggle = wrapper.findAll(".group-row")[1]!.find("input[role='switch']");
    expect((toggle.element as HTMLInputElement).checked).toBe(true);

    (toggle.element as HTMLInputElement).checked = false;
    await toggle.trigger("change");

    expect(client.updateGroup).toHaveBeenCalledWith(2, { pinned: false });
    expect((toggle.element as HTMLInputElement).checked).toBe(true);
  });

  it("lists possible duplicates in review mode", async () => {
    client.listTickets.mockResolvedValue([ticket(21, { possible_group_id: 5, group_id: 9, title: "Mail broken" })]);
    const wrapper = await panel({ mode: "review" });

    expect(client.listTickets).toHaveBeenCalledWith({ possible: true });
    expect(client.listGroups).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Mail broken");
    expect(wrapper.text()).toContain("May belong to group 5");
  });

  it("emits the filters when the user changes them", async () => {
    const wrapper = await panel();

    await wrapper.findAll("button.segment").find((b) => b.text() === "Open")!.trigger("click");

    expect(wrapper.emitted("filter")!.at(-1)).toEqual([{ ...FILTERS, status: "open" }]);
  });

  it("shows a load error and an empty state", async () => {
    client.listGroups.mockRejectedValue(new ApiError(502, "mcp_server is unreachable"));
    let wrapper = await panel();
    expect(wrapper.find(".error").text()).toContain("mcp_server is unreachable");

    client.listGroups.mockResolvedValue([]);
    wrapper = await panel();
    expect(wrapper.text()).toContain("No tickets match.");
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run src/components/admin/TicketsPanel.test.ts`
Expected: FAIL (cannot find the component).

- [ ] **Step 3: Implement the panel**

`src/components/admin/TicketsPanel.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  ticketsAdminClient,
  type AdminTicket,
  type TicketChanges,
  type TicketGroup,
  type TicketPriority,
} from "../../api/TicketsAdminClient";
import { errorMessage } from "../../utils/errors";
import {
  PRIORITY_LABELS,
  SOURCE_LABELS,
  STATUS_ICONS,
  STATUS_LABELS,
  formatTicketTime,
  type TicketFilterState,
} from "../../utils/ticketFormat";
import SegmentedControl from "../SegmentedControl.vue";
import ToggleSwitch from "../ToggleSwitch.vue";
import TicketDrawer from "./TicketDrawer.vue";
import "./admin.css";

/** Staff triage: groups of similar tickets (Laya groups them), each expandable
 * to its tickets, a review list of tickets Laya was unsure about, and the
 * ticket drawer. Every control shows only what the server has confirmed. */
const props = defineProps<{ filters: TicketFilterState }>();
const emit = defineEmits<{ filter: [value: TicketFilterState] }>();

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
] as const;
const MODE_OPTIONS = [
  { value: "groups", label: "Groups" },
  { value: "review", label: "Needs review" },
] as const;
const PRIORITIES = Object.keys(PRIORITY_LABELS) as TicketPriority[];

const status = ref(props.filters.status);
const priority = ref(props.filters.priority);
const tag = ref(props.filters.tag);
const mode = ref(props.filters.mode);

const groups = ref<TicketGroup[]>([]);
const reviewTickets = ref<AdminTicket[]>([]);
const expanded = ref<number | null>(null);
const groupTickets = ref<AdminTicket[]>([]);
const selected = ref<AdminTicket | null>(null);
const loadError = ref("");
const actionError = ref("");
const notice = ref("");
const busy = ref(false);
const loading = ref(true);

const tagOptions = computed(() => [...new Set([...groups.value.flatMap((g) => g.tags), ...(tag.value ? [tag.value] : [])])].sort());

// Only the newest list request may fill the page.
let loadSeq = 0;
async function load(): Promise<void> {
  const seq = ++loadSeq;
  try {
    if (mode.value === "review") {
      const rows = await ticketsAdminClient.listTickets({ possible: true });
      if (seq !== loadSeq) return;
      reviewTickets.value = rows;
    } else {
      const rows = await ticketsAdminClient.listGroups({
        ...(status.value !== "all" ? { status: status.value } : {}),
        ...(priority.value !== "all" ? { priority: priority.value } : {}),
        ...(tag.value ? { tag: tag.value } : {}),
      });
      if (seq !== loadSeq) return;
      groups.value = rows;
      if (expanded.value !== null && !rows.some((g) => g.id === expanded.value)) expanded.value = null;
    }
    loadError.value = "";
  } catch (err) {
    if (seq === loadSeq) loadError.value = errorMessage(err);
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

async function loadExpanded(): Promise<void> {
  if (expanded.value === null) {
    groupTickets.value = [];
    return;
  }
  try {
    groupTickets.value = await ticketsAdminClient.listTickets({ group_id: expanded.value });
  } catch (err) {
    loadError.value = errorMessage(err);
  }
}

watch([status, priority, tag, mode], () => {
  emit("filter", { status: status.value, priority: priority.value, tag: tag.value, mode: mode.value });
  void load();
});
watch(
  () => props.filters,
  (next) => {
    status.value = next.status;
    priority.value = next.priority;
    tag.value = next.tag;
    mode.value = next.mode;
  },
);
onMounted(load);

async function toggle(group: TicketGroup): Promise<void> {
  expanded.value = expanded.value === group.id ? null : group.id;
  await loadExpanded();
}

async function select(ticket: AdminTicket): Promise<void> {
  actionError.value = "";
  notice.value = "";
  selected.value = ticket;
  try {
    selected.value = await ticketsAdminClient.get(ticket.id);
  } catch (err) {
    actionError.value = errorMessage(err);
  }
}

/** Everything a change can touch: the lists and the open ticket. */
async function refreshAll(): Promise<void> {
  await Promise.all([load(), loadExpanded()]);
  if (selected.value) {
    try {
      selected.value = await ticketsAdminClient.get(selected.value.id);
    } catch (err) {
      actionError.value = errorMessage(err);
    }
  }
}

async function act(call: () => Promise<unknown>, done = "Saved."): Promise<void> {
  if (busy.value) return;
  actionError.value = "";
  notice.value = "";
  busy.value = true;
  try {
    await call();
    await refreshAll();
    notice.value = done;
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    busy.value = false;
  }
}

const update = (changes: TicketChanges) => act(() => ticketsAdminClient.update(selected.value!.id, changes));
const comment = (body: string) => act(() => ticketsAdminClient.comment(selected.value!.id, body), "Reply sent.");
const move = (groupId: number | null) =>
  act(() => ticketsAdminClient.move(selected.value!.id, groupId), groupId === null ? "Split out into a new group." : `Moved to group ${groupId}.`);

/** The shown value stays the server's until the reload brings the new one. */
function setGroupPriority(group: TicketGroup, event: Event): void {
  const element = event.target as HTMLSelectElement;
  const value = element.value as TicketPriority;
  element.value = group.priority;
  if (value !== group.priority) void act(() => ticketsAdminClient.updateGroup(group.id, { priority: value }));
}

function setPinned(group: TicketGroup, event: Event): void {
  const element = event.target as HTMLInputElement;
  const value = element.checked;
  element.checked = group.priority_pinned;
  void act(() => ticketsAdminClient.updateGroup(group.id, { pinned: value }));
}
</script>

<template>
  <div class="admin-panel tickets-panel">
    <div class="toolbar">
      <SegmentedControl v-model="mode" :options="MODE_OPTIONS" label="View" aria-label="Ticket view" />
      <template v-if="mode === 'groups'">
        <SegmentedControl v-model="status" :options="STATUS_OPTIONS" label="Status" aria-label="Ticket status" />
        <label class="field">
          Priority
          <select v-model="priority" aria-label="Priority filter">
            <option value="all">All</option>
            <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABELS[p] }}</option>
          </select>
        </label>
        <label class="field">
          Tag
          <select v-model="tag" aria-label="Tag filter">
            <option value="">All</option>
            <option v-for="t in tagOptions" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
      </template>
    </div>

    <p v-if="loadError" class="error" role="alert">Could not load tickets: {{ loadError }}</p>
    <p v-if="actionError && !selected" class="error" role="alert">{{ actionError }}</p>
    <p v-if="notice && !selected" class="notice" role="status">{{ notice }}</p>

    <div :class="['layout', { open: selected }]">
      <div class="list">
        <p v-if="loading" class="muted">Loading …</p>

        <template v-else-if="mode === 'groups'">
          <p v-if="groups.length === 0 && !loadError" class="muted empty">No tickets match.</p>
          <div v-for="g in groups" :key="g.id" class="group">
            <div class="group-row card">
              <button type="button" class="expand" :aria-expanded="expanded === g.id" @click="toggle(g)">
                <span class="title">{{ g.title }}</span>
                <span class="muted summary">
                  Group {{ g.id }} · {{ g.ticket_count }} {{ g.ticket_count === 1 ? "ticket" : "tickets" }} · {{ g.recent_count }} in 24 h ·
                  {{ g.open_count }} open
                </span>
              </button>
              <div class="chips">
                <span v-for="t in g.tags" :key="t" class="chip">{{ t }}</span>
              </div>
              <div class="priority">
                <label>
                  Priority
                  <select :aria-label="`Priority of group ${g.id}`" :value="g.priority" :disabled="busy" @change="setGroupPriority(g, $event)">
                    <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABELS[p] }}</option>
                  </select>
                </label>
                <ToggleSwitch
                  small
                  :checked="g.priority_pinned"
                  :disabled="busy"
                  :aria-label="`Pin priority of group ${g.id}`"
                  title="Pinned: set by hand, never raised automatically"
                  @change="setPinned(g, $event)"
                >
                  Pinned
                </ToggleSwitch>
              </div>
            </div>
            <ul v-if="expanded === g.id" class="group-tickets">
              <li v-for="t in groupTickets" :key="t.id">
                <button type="button" class="ticket-link" :aria-pressed="selected?.id === t.id" @click="select(t)">
                  <span class="title">#{{ t.id }} {{ t.title }}</span>
                  <span class="meta">
                    <span>{{ t.reporter }}</span>
                    <span class="badge">{{ SOURCE_LABELS[t.source] }}</span>
                    <span class="status">
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="STATUS_ICONS[t.status]" /></svg>{{ STATUS_LABELS[t.status] }}
                    </span>
                    <span class="muted">{{ formatTicketTime(t.updated_at) }}</span>
                  </span>
                </button>
              </li>
            </ul>
          </div>
        </template>

        <template v-else>
          <p v-if="reviewTickets.length === 0 && !loadError" class="muted empty">Nothing needs review.</p>
          <ul class="group-tickets review">
            <li v-for="t in reviewTickets" :key="t.id">
              <button type="button" class="ticket-link" :aria-pressed="selected?.id === t.id" @click="select(t)">
                <span class="title">#{{ t.id }} {{ t.title }}</span>
                <span class="meta">
                  <span>{{ t.reporter }}</span>
                  <span class="badge">May belong to group {{ t.possible_group_id }}</span>
                  <span class="muted">Now in group {{ t.group_id }}</span>
                </span>
              </button>
            </li>
          </ul>
        </template>
      </div>

      <TicketDrawer
        v-if="selected"
        :ticket="selected"
        :busy="busy"
        :error="actionError"
        :notice="notice"
        @close="selected = null"
        @update="update"
        @comment="comment"
        @move="move"
      />
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 16px;
  margin-bottom: 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.8em;
  color: var(--muted);
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.layout.open {
  grid-template-columns: minmax(0, 1fr) minmax(300px, 420px);
}
.group {
  margin-bottom: 10px;
}
.group-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 14px;
  margin-bottom: 0;
}
.expand {
  display: flex;
  flex: 1 1 220px;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 0;
  border: none;
  color: var(--text);
  background: none;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.title {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.summary {
  font-size: 0.85em;
}
.priority {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.85em;
}
.priority label {
  display: flex;
  align-items: center;
  gap: 6px;
}
.group-tickets {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 6px 0 0 14px;
  padding: 0;
  list-style: none;
}
.ticket-link {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.ticket-link:hover,
.ticket-link[aria-pressed="true"] {
  border-color: var(--accent);
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 10px;
  font-size: 0.85em;
}
.status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.status svg {
  width: 14px;
  height: 14px;
}
.empty {
  margin: 16px 0;
}
@media (max-width: 767px) {
  .layout.open {
    grid-template-columns: minmax(0, 1fr);
  }
  .group-tickets {
    margin-left: 0;
  }
}
</style>
```

`src/views/TicketsAdminView.vue` (filters kept in the URL like `AccountsAdminView`):

```vue
<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import TicketsPanel from "../components/admin/TicketsPanel.vue";
import type { TicketFilterState } from "../utils/ticketFormat";
import "../components/admin/admin.css";
import "../components/infoPage.css";

const STATUSES = ["open", "in_progress", "resolved", "closed"] as const;
const PRIORITIES = ["low", "normal", "high", "urgent"] as const;

const route = useRoute();
const router = useRouter();

const filters = computed<TicketFilterState>(() => {
  const { status, priority, tag, mode } = route.query;
  return {
    status: (STATUSES as readonly unknown[]).includes(status) ? (status as TicketFilterState["status"]) : "all",
    priority: (PRIORITIES as readonly unknown[]).includes(priority) ? (priority as TicketFilterState["priority"]) : "all",
    tag: typeof tag === "string" ? tag : "",
    mode: mode === "review" ? "review" : "groups",
  };
});

function updateFilters(next: TicketFilterState): void {
  void router.replace({
    query: {
      ...route.query,
      status: next.status === "all" ? undefined : next.status,
      priority: next.priority === "all" ? undefined : next.priority,
      tag: next.tag || undefined,
      mode: next.mode === "review" ? "review" : undefined,
    },
  });
}
</script>

<template>
  <section class="info-page tickets-admin">
    <div class="column page-column">
      <h2 class="page-title">Tickets</h2>
      <p class="intro page-description">
        Reports from people and from the assistant, grouped by similar issue. Priority rises as a group grows; set one by hand to pin it.
      </p>
      <TicketsPanel :filters="filters" @filter="updateFilters" />
    </div>
  </section>
</template>
```

- [ ] **Step 4: Register the route and the nav entry**

In `src/router/pages.ts` change `ADMIN_PERMISSIONS` to include the new permission:

```ts
export const ADMIN_PERMISSIONS = ["accounts.view", "accounts.manage", "accounts.delete", "roles.view", "roles.manage", "roles.assign", "invites.manage", "settings.manage", "capabilities.manage", "extensions.manage", "agents.manage", "tickets.manage", "usage.all.view", ...ANALYTICS_PERMISSIONS];
```

and add to `ADMIN_PAGES` after Agents:

```ts
  { to: "/tickets", label: "Tickets", icon: ["M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z", "M13 5v2", "M13 17v2", "M13 11v2"], permission: "tickets.manage" },
```

In `src/router/index.ts` add after the `agents` route:

```ts
    { path: "/tickets", name: "tickets", component: () => import("../views/TicketsAdminView.vue"), meta: { permission: "tickets.manage" } },
```

- [ ] **Step 5: Run tests and checks**

Run: `npx vitest run src/components/admin/TicketsPanel.test.ts`
Expected: PASS.

Run: `npx vue-tsc -b --noEmit` (prints nothing), then `npm test`
Expected: all pass, including `radiusScale.test.ts`. If `router/index.test.ts` or `AdminNav.test.ts` list every page, update only their expectations for the new Tickets page.

- [ ] **Step 6: Hand-test note for the user**

Tell the user to test by hand as an Administrator: Tickets page, filters (kept in the URL), expand a group, open a ticket, change status, priority, assignee and tags, add a reply, move and split a ticket, set a group priority and toggle Pinned, "Needs review" mode; at 768 and 375 px and in dark mode.

- [ ] **Step 7: Commit**

```bash
git add apps/Ember/ember_admin/src/components/admin/TicketsPanel.vue apps/Ember/ember_admin/src/components/admin/TicketsPanel.test.ts apps/Ember/ember_admin/src/views/TicketsAdminView.vue apps/Ember/ember_admin/src/utils/ticketFormat.ts apps/Ember/ember_admin/src/router
git commit -m "feat(ember-admin): tickets page"
```

---

### Task 6: Overview tiles, docs

**Files:**
- Modify: `apps/Ember/ember_admin/src/views/AdminOverviewView.vue`
- Test: `apps/Ember/ember_admin/src/views/AdminView.test.ts` (append, it already mounts the overview; if it does not, create `AdminOverviewView.test.ts` following its mocking style)
- Modify: `apps/Ember/ember_admin/README.md`, `apps/Ember/ember_web/README.md`

**Interfaces:**
- Consumes: `ticketsAdminClient.stats()` (Task 3), `StatTile` (props `label`, `value: number | null`, `warn?`).
- Produces: two overview tiles ("Open tickets", "Urgent tickets") linking to `/tickets` and `/tickets?priority=urgent`, shown only to accounts with `tickets.manage`; a "Tickets" destination card.

- [ ] **Step 1: Write the failing test**

Append to the overview test (mock `TicketsAdminClient` with `vi.mock("../api/TicketsAdminClient", () => ({ ticketsAdminClient: { stats: vi.fn() } }))` at the top of that file, if it does not mock it yet):

```ts
it("shows ticket counts only to accounts that can manage tickets", async () => {
  vi.mocked(ticketsAdminClient.stats).mockResolvedValue({ open: 4, urgent: 1, groups: 3 });
  const auth = useAuthStore();
  auth.account = { ...auth.account!, permissions: ["tickets.manage"] };   // use the file's existing way to log in as a given permission set
  const wrapper = mount(AdminOverviewView, { global: { stubs: { RouterLink: RouterLinkStub } } });
  await flushPromises();

  expect(wrapper.text()).toContain("Open tickets");
  expect(wrapper.text()).toContain("4");
  expect(wrapper.text()).toContain("Urgent tickets");
  expect(wrapper.text()).toContain("Tickets");
});

it("does not ask for ticket counts without the permission", async () => {
  const wrapper = mount(AdminOverviewView, { global: { stubs: { RouterLink: RouterLinkStub } } });
  await flushPromises();

  expect(ticketsAdminClient.stats).not.toHaveBeenCalled();
  expect(wrapper.text()).not.toContain("Open tickets");
});
```

(Match the existing file's helpers for mounting with Pinia, the router stub and setting permissions; the two assertions above are the contract. Reset `vi.mocked(ticketsAdminClient.stats)` in `beforeEach`.)

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run src/views/AdminView.test.ts`
Expected: FAIL (no "Open tickets" text).

- [ ] **Step 3: Implement**

In `AdminOverviewView.vue`:

- import: `import { ticketsAdminClient, type TicketStats } from "../api/TicketsAdminClient";`
- state: `const ticketStats = ref<TicketStats | null>(null);`
- in `onMounted`, before the existing early `return`, add (the stats call must not depend on the accounts permission):

```ts
onMounted(async () => {
  if (auth.hasPermission("tickets.manage")) {
    ticketsAdminClient.stats().then((s) => (ticketStats.value = s), (err) => (error.value = errorMessage(err)));
  }
  if (!auth.hasPermission("accounts.view") && !auth.hasPermission("invites.manage")) return;
  try { summary.value = await adminClient.summary(); }
  catch (err) { error.value = errorMessage(err); }
});
```

- add to the `descriptions` record: `"/tickets": "Triage reports and suggestions, grouped by similar issue.",`
- in the template, after the existing `v-if="auth.hasPermission('accounts.view') || auth.hasPermission('invites.manage')"` stats block add a second block:

```vue
    <div v-if="auth.hasPermission('tickets.manage')" class="stats">
      <RouterLink to="/tickets"><StatTile label="Open tickets" :value="ticketStats?.open ?? null" /><span class="stat-link">Triage tickets →</span></RouterLink>
      <RouterLink to="/tickets?priority=urgent"><StatTile label="Urgent tickets" :value="ticketStats?.urgent ?? null" warn /><span class="stat-link">Review urgent →</span></RouterLink>
    </div>
```

- [ ] **Step 4: Docs**

`apps/Ember/ember_web/README.md`: add Tickets to the pages list (permission `tickets.create`, what a reporter can do, that tags and priority are not shown) and the `/api/tickets*` calls to the API table. `apps/Ember/ember_admin/README.md`: add the Tickets page (permission `tickets.manage`, groups, Needs review, drawer, pinned priority, URL filters `status`, `priority`, `tag`, `mode`) and the `/api/admin/tickets*`, `/api/admin/ticket-groups*` calls.

- [ ] **Step 5: Run everything**

Run in `apps/Ember/ember_admin`: `npx vue-tsc -b --noEmit`, `npm test`.
Run in `apps/Ember/ember_web`: `npx vue-tsc -b --noEmit`, `npm test`.
Expected: all pass.

Run in both apps: `npm run test:e2e`.
Expected: pass. The existing scenarios use accounts without the ticket permissions, so no new `/api` call should appear; if an e2e fails with an unexpected-call report naming a ticket route, add that route to the app's fake API (`e2e/fakeApi.ts` in ember_web, `e2e/workspaceFakeApi.ts` in ember_admin) answering `{ "open": 0, "urgent": 0, "groups": 0 }` for `/api/admin/tickets/stats` and `{ "tickets": [] }` for `/api/tickets`.

- [ ] **Step 6: Commit**

```bash
git add apps/Ember/ember_admin/src/views apps/Ember/ember_admin/README.md apps/Ember/ember_web/README.md
git commit -m "feat(ember-admin): ticket counts on the overview, docs"
```

---

## Self-Review (done)

**Spec coverage (sections 4 and 5):**
- ember_web: `/tickets` page, my list with status chip and type, detail with thread, reply, Close with in-app confirm, new-ticket form with type/title/description, tags not shown, rail entry via the page list, design-system tokens: Tasks 1 and 2.
- ember_admin: groups table (title, count, tags, effective priority, newest activity), expand into tickets with reporter and source badge and status, URL-kept filters (status, priority, tag, mode; assignee and type filters are supported by the client but have no UI control, a deliberate YAGNI cut), ticket drawer (description, unverified context, thread, status/priority/assignee/tags, move to group, split out, Laya hint), group priority with pin toggle, server-confirmed controls, overview card with open and urgent counts: Tasks 3 to 6.
- "Possible duplicates" filter from the spec is the "Needs review" mode.
- Section 5's "native dialog drawer" is implemented as an inline side panel (`aside.drawer`) like `AccountsPanel`'s drawer layout, not a modal `<dialog>`; this keeps the list visible, matches the existing Accounts pattern, and stacks under the list on mobile.

**Placeholders:** none in code steps. Task 6 Step 1 tells the implementer to reuse the existing overview test file's mounting helpers; the two assertions are the contract and the setup differs per file, so it cannot be spelled out without reading that test first (its first step in execution is to read it).

**Type consistency:** client method names and shapes match plan 2's routes (`list`/`get`/`create`/`comment`/`close` on `/api/tickets*`; `listGroups`/`listTickets`/`get`/`update`/`comment`/`move`/`updateGroup`/`stats` on `/api/admin/*`). `TicketFilterState` lives in `ticketFormat.ts` and is imported by the panel and the view (Task 5 calls this out). Labels and icons are duplicated per app on purpose (no shared package).
