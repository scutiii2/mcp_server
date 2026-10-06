<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { ChatSearchHit, MatchSpan } from "../api/ChatsClient";
import { MAX_FOLDERS, type ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";
import { chatMenuItems, folderMenuItems, parseChatChoice } from "../utils/chatMenu";
import { dropOps, type DropTarget } from "../utils/chatDrop";
import { buildLayout } from "../utils/chatSections";
import ChatRow from "./ChatRow.vue";
import ChatSection from "./ChatSection.vue";
import PopupMenu from "./PopupMenu.vue";
import type { MenuPoint } from "./menuPoint";
import UsageGauges from "./UsageGauges.vue";

// locked: a turn is running - switching or starting chats is blocked.
// query / searchActive / hits: the search box and, once it holds enough
// characters, the results that replace the chat list.
// folders / collapsedFolders: the chat folders, and which of them are folded.
const props = withDefaults(
  defineProps<{
    conversations: Conversation[];
    activeId: string | null;
    locked: boolean;
    /** The chat list is still being fetched. */
    loading?: boolean;
    /** An answer is being written: the usage gauges refresh when it ends. */
    busy?: boolean;
    query?: string;
    searchActive?: boolean;
    hits?: ChatSearchHit[];
    searching?: boolean;
    searchError?: string;
    folders?: ChatFolder[];
    /** Why the folder list could not be loaded; empty when it could. */
    folderError?: string;
    /** Ids of the folders shown folded. */
    collapsedFolders?: number[];
  }>(),
  {
    busy: false,
    query: "",
    searchActive: false,
    hits: () => [],
    searching: false,
    searchError: "",
    folders: () => [],
    folderError: "",
    collapsedFolders: () => [],
  },
);
const emit = defineEmits<{
  new: [];
  /** messageIndex: a search result's first matching message. */
  select: [id: string, messageIndex?: number];
  delete: [id: string];
  rename: [id: string, title: string];
  deleteAll: [];
  deleteMany: [ids: string[]];
  search: [query: string];
  pin: [id: string, pinned: boolean];
  /** folderId null: out of its folder. */
  move: [id: string, folderId: number | null];
  /** "Move to > New folder...": the parent creates a folder, then moves the chat into it. */
  moveNew: [id: string];
  toggleFolder: [id: number];
  newFolder: [];
  retryFolders: [];
  renameFolder: [folder: ChatFolder];
  deleteFolder: [folder: ChatFolder];
}>();

/** `text` split around the match, for a <mark>; no match: all one part. */
function parts(text: string, span: MatchSpan | null): { before: string; match: string; after: string } {
  if (!span) return { before: text, match: "", after: "" };
  return {
    before: text.slice(0, span.start),
    match: text.slice(span.start, span.start + span.length),
    after: text.slice(span.start + span.length),
  };
}

// The row being renamed (its draft text lives in the row).
const renamingId = ref<string | null>(null);

function finishRename(id: string, save: boolean, title: string): void {
  if (renamingId.value !== id) return;
  renamingId.value = null;
  if (save) emit("rename", id, title);
}

// The chat being dragged. Set one tick after dragstart: Chrome cancels a drag
// whose source DOM changes inside the dragstart handler, and showing the drop
// zones changes the DOM.
const draggingId = ref<string | null>(null);
const dragging = computed(() => props.conversations.find((c) => c.id === draggingId.value) ?? null);
let dragTimer: ReturnType<typeof setTimeout> | undefined;

const layout = computed(() => buildLayout(props.conversations, props.folders, draggingId.value !== null));

type SectionRef = { kind: "pinned" | "folder" | "unfiled"; folder: ChatFolder | null };

function touchOnly(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(hover: none)").matches;
}

/** A row may be dragged unless something else owns it right now. */
function canDrag(c: Conversation): boolean {
  return !selecting.value && renamingId.value !== c.id && !answering(c) && !touchOnly();
}

function startDrag(c: Conversation): void {
  menu.value = null;
  clearTimeout(dragTimer);
  dragTimer = setTimeout(() => {
    draggingId.value = c.id;
  }, 0);
}

function endDrag(): void {
  clearTimeout(dragTimer);
  draggingId.value = null;
}

// An Esc-cancelled drag may never deliver dragend to the row, so the window listens too.
// A row that unmounted mid-drag (chat deleted elsewhere) is caught by the watch.
watch(dragging, (chat) => {
  if (chat === null) endDrag();
});
onMounted(() => window.addEventListener("dragend", endDrag));
onBeforeUnmount(() => {
  window.removeEventListener("dragend", endDrag);
  clearTimeout(dragTimer);
});

function targetOf(section: SectionRef): DropTarget | null {
  if (section.kind === "pinned") return { kind: "pinned" };
  if (section.kind === "unfiled") return { kind: "unfiled" };
  return section.folder ? { kind: "folder", folderId: section.folder.id } : null;
}

function accepts(section: SectionRef): boolean {
  const chat = dragging.value;
  const target = targetOf(section);
  return chat !== null && target !== null && dropOps(chat, target).length > 0;
}

function dropOn(section: SectionRef): void {
  const chat = dragging.value;
  const target = targetOf(section);
  endDrag();
  if (!chat || !target) return;
  for (const op of dropOps(chat, target)) {
    if (op.op === "move") emit("move", chat.id, op.folderId);
    else emit("pin", chat.id, op.pinned);
  }
}

const HINTS = { pinned: "Drop here to pin", unfiled: "Drop here to take it out of its folder" } as const;
function hintOf(kind: "pinned" | "folder" | "unfiled"): string | null {
  return kind === "folder" ? null : HINTS[kind];
}

const SECTION_TITLES = { pinned: "Pinned", unfiled: "Chats" } as const;
/** A section's header; null (no header) while the list is flat. */
function titleOf(section: { kind: "pinned" | "folder" | "unfiled"; folder: ChatFolder | null }): string | null {
  if (!layout.value.grouped) return null;
  return section.kind === "folder" ? (section.folder?.name ?? "") : SECTION_TITLES[section.kind];
}

// The open popup menu: for a chat row or for a folder header (by id, so it
// always works on the chat or folder as it is now), with where it opened and
// the button that gets focus back after Esc.
type OpenMenu = ({ kind: "chat"; id: string } & MenuPoint) | ({ kind: "folder"; id: number } & MenuPoint);
const menu = ref<OpenMenu | null>(null);

/** What the open menu is for, as it is now; null once it has gone away. */
const menuOwner = computed(() => {
  const m = menu.value;
  if (!m) return null;
  if (m.kind === "chat") {
    const chat = props.conversations.find((c) => c.id === m.id);
    return chat ? { kind: "chat" as const, chat } : null;
  }
  const folder = props.folders.find((f) => f.id === m.id);
  return folder ? { kind: "folder" as const, folder } : null;
});

// The chat or folder went away (deleted elsewhere, the list reloaded): the menu goes too.
watch(menuOwner, (owner) => {
  if (!owner) menu.value = null;
});

/** A new owner gets a new menu, so it is placed and focused afresh and no old flyout stays open. */
const menuKey = computed(() => (menu.value ? `${menu.value.kind}:${menu.value.id}` : ""));

const menuItems = computed(() => {
  const owner = menuOwner.value;
  if (!owner) return [];
  return owner.kind === "chat" ? chatMenuItems(owner.chat, props.folders, answering(owner.chat)) : folderMenuItems(props.loading);
});

// A press on the "..." button of the menu that is open closes it (the button
// keeps its pointerdown from the menu, which would otherwise close it first and
// let the click reopen it). Another row's button replaces the menu.
function openChatMenu(chat: Conversation, point: MenuPoint): void {
  if (menu.value?.kind === "chat" && menu.value.id === chat.id) void dismissMenu();
  else menu.value = { kind: "chat", id: chat.id, ...point };
}

function openFolderMenu(folder: ChatFolder, point: MenuPoint): void {
  if (menu.value?.kind === "folder" && menu.value.id === folder.id) void dismissMenu();
  else menu.value = { kind: "folder", id: folder.id, ...point };
}

/** Esc, a press outside, Tab or a resize: focus goes back to the button. */
async function dismissMenu(): Promise<void> {
  const trigger = menu.value?.trigger ?? null;
  menu.value = null;
  await nextTick();
  trigger?.focus();
}

async function chooseFromMenu(id: string): Promise<void> {
  const open = menuOwner.value;
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
      // The native dialog blocks rendering: let the menu leave the page first.
      await nextTick();
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

function confirmDelete(c: Conversation): void {
  if (confirm(`Delete "${c.title}"? This can't be undone.`)) emit("delete", c.id);
}

function confirmDeleteAll(): void {
  const count = props.conversations.length;
  if (confirm(`Delete all ${count} chat${count === 1 ? "" : "s"}? This can't be undone.`)) emit("deleteAll");
}

// Select mode: tick chats, then delete the ticked ones together.
const selecting = ref(false);
const ticked = ref<Set<string>>(new Set());

/** An answer is being written for this chat (it runs, or it is the open chat of
 * a busy page): it can be neither moved nor deleted from under its turn. */
function answering(c: Conversation): boolean {
  return c.running === true || (props.busy && c.id === props.activeId);
}

/** A chat that is answering right now can't be ticked for deletion. */
function isLocked(c: Conversation): boolean {
  return props.locked && c.id === props.activeId;
}

const selectable = computed(() => props.conversations.filter((c) => !isLocked(c)));
// Only chats still in the list count: one deleted elsewhere drops out.
const chosen = computed(() => selectable.value.filter((c) => ticked.value.has(c.id)).map((c) => c.id));
const allChosen = computed(() => selectable.value.length > 0 && chosen.value.length === selectable.value.length);

function startSelecting(): void {
  menu.value = null;
  endDrag();
  renamingId.value = null;
  ticked.value = new Set();
  selecting.value = true;
}

function stopSelecting(): void {
  selecting.value = false;
  ticked.value = new Set();
}

function toggle(c: Conversation): void {
  if (isLocked(c)) return;
  const next = new Set(ticked.value);
  if (!next.delete(c.id)) next.add(c.id);
  ticked.value = next;
}

function toggleAll(): void {
  ticked.value = allChosen.value ? new Set() : new Set(selectable.value.map((c) => c.id));
}

function confirmDeleteChosen(): void {
  const ids = chosen.value; // the Delete button is off while this is empty
  if (!confirm(`Delete ${ids.length} chat${ids.length === 1 ? "" : "s"}? This can't be undone.`)) return;
  emit("deleteMany", ids);
  stopSelecting();
}

// Search results replace the list; there is nothing to tick in them.
watch(
  () => props.searchActive,
  (active) => {
    if (!active) return;
    stopSelecting();
    menu.value = null;
    endDrag();
  },
);
// Nothing left to select.
watch(
  () => props.conversations.length,
  (count) => {
    if (count === 0) stopSelecting();
  },
);
</script>

<template>
  <!-- The menu is fixed to the page, so it would drift from its row: a scroll
       of the sidebar (the element that scrolls) closes it. -->
  <aside class="sidebar" @scroll="menu = null">
    <button type="button" class="new-chat" :disabled="locked" @click="emit('new')">
      <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
      </svg>
      New chat
    </button>

    <div v-if="conversations.length > 0 || query" class="search">
      <input
        type="search"
        :value="query"
        placeholder="Search chats"
        aria-label="Search chats"
        maxlength="100"
        @input="emit('search', ($event.target as HTMLInputElement).value)"
        @keydown.esc.prevent="emit('search', '')"
      />
    </div>

    <template v-if="searchActive">
      <p v-if="searchError" class="empty error" role="alert">Search failed: {{ searchError }}</p>
      <p v-else-if="searching && hits.length === 0" class="empty">Searching …</p>
      <p v-else-if="hits.length === 0" class="empty">No chats match "{{ query.trim() }}".</p>
      <ul v-else class="list" :aria-busy="searching">
        <li
          v-for="h in hits"
          :key="h.id"
          :class="['row', 'hit', { active: h.id === activeId, locked }]"
          @click="emit('select', h.id, h.message_index ?? undefined)"
        >
          <div class="hit-body">
            <span class="title">
              {{ parts(h.title, h.title_match).before }}<mark v-if="h.title_match">{{ parts(h.title, h.title_match).match }}</mark>{{ parts(h.title, h.title_match).after }}
            </span>
            <span v-if="h.snippet" class="snippet">
              {{ parts(h.snippet.text, h.snippet).before }}<mark>{{ parts(h.snippet.text, h.snippet).match }}</mark>{{ parts(h.snippet.text, h.snippet).after }}
            </span>
            <span v-if="h.message_matches > 1" class="count">{{ h.message_matches }} messages match</span>
          </div>
        </li>
      </ul>
    </template>
    <p v-else-if="conversations.length === 0 && folders.length === 0" class="empty">
      {{ loading ? "Loading chats …" : "No saved chats yet." }}
    </p>
    <div v-else class="sections">
      <ChatSection
        v-for="s in layout.sections"
        :key="s.key"
        :title="titleOf(s)"
        :count="s.chats.length"
        :collapsible="s.kind === 'folder'"
        :collapsed="s.kind === 'folder' && s.folder !== null && collapsedFolders.includes(s.folder.id)"
        :menu="s.kind === 'folder' && !selecting"
        :expanded="s.kind === 'folder' && menu?.kind === 'folder' && menu.id === s.folder?.id"
        :accepting="accepts(s)"
        :hint="hintOf(s.kind)"
        @toggle="s.folder && emit('toggleFolder', s.folder.id)"
        @open-menu="(point) => s.folder && openFolderMenu(s.folder, point)"
        @drop="dropOn(s)"
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
          :expanded="menu?.kind === 'chat' && menu.id === c.id"
          :draggable="canDrag(c)"
          @select="emit('select', c.id)"
          @toggle="toggle(c)"
          @start-rename="renamingId = c.id"
          @finish-rename="(save, title) => finishRename(c.id, save, title)"
          @open-menu="(point) => openChatMenu(c, point)"
          @drag-start="startDrag(c)"
          @drag-end="endDrag"
        />
      </ChatSection>
    </div>
    <p v-if="folderError && !searchActive" class="empty error folder-error" role="alert">
      Folders failed to load: {{ folderError }}
      <button type="button" class="link" @click="emit('retryFolders')">Retry</button>
    </p>

    <PopupMenu
      v-if="menu"
      :key="menuKey"
      :items="menuItems"
      :x="menu.x"
      :y="menu.y"
      :label="menu.kind === 'chat' ? 'Chat actions' : 'Folder actions'"
      @select="chooseFromMenu"
      @close="dismissMenu"
    />

    <div v-if="selecting" class="select-bar">
      <label class="all">
        <input type="checkbox" :checked="allChosen" :disabled="selectable.length === 0" @change="toggleAll" />
        All
      </label>
      <span class="count-chosen" aria-live="polite">{{ chosen.length }} selected</span>
      <button type="button" class="danger" :disabled="chosen.length === 0" @click="confirmDeleteChosen">
        Delete {{ chosen.length || "" }}
      </button>
      <button type="button" @click="stopSelecting">Cancel</button>
    </div>
    <div v-else-if="!searchActive" class="footer">
      <template v-if="conversations.length > 0">
        <button type="button" class="link" @click="startSelecting">Select</button>
        <button v-if="conversations.length > 1" type="button" class="link delete-all" :disabled="locked" @click="confirmDeleteAll">
          Delete all chats
        </button>
      </template>
      <button
        type="button"
        class="link new-folder"
        :disabled="folders.length >= MAX_FOLDERS"
        :title="folders.length >= MAX_FOLDERS ? `${MAX_FOLDERS} folders is the limit` : 'Create a folder'"
        @click="emit('newFolder')"
      >
        New folder
      </button>
    </div>
    <UsageGauges :busy="busy" />
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 260px;
  height: 100%;
  padding: 12px 8px;
  overflow-y: auto;
  border-right: 1px solid var(--border);
  background: var(--surface);
}
.new-chat {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  background: var(--bg);
}
.new-chat:hover:not(:disabled) {
  border-color: var(--accent);
}
.new-chat:disabled {
  cursor: default;
  opacity: 0.5;
}
.empty {
  padding: 0 8px;
  font-size: 0.9em;
  color: var(--muted);
}
.empty.error {
  color: var(--danger);
}
.search input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  outline: none;
  color: var(--text);
  background: var(--bg);
  font: inherit;
  font-size: 0.9em;
}
.search input:focus {
  border-color: var(--accent);
}
.hit {
  align-items: flex-start;
}
.hit-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.snippet {
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 0.8em;
  overflow-wrap: anywhere;
}
.count {
  font-size: 0.75em;
  opacity: 0.8;
}
mark {
  padding: 0 1px;
  border-radius: 3px;
  color: inherit;
  background: color-mix(in srgb, var(--accent) 30%, transparent);
}
.list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 7px 8px 7px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--muted);
}
.row:hover {
  color: var(--text);
  background: var(--bg);
}
.row.active {
  color: var(--text);
  background: var(--bg);
  box-shadow: inset 2px 0 0 var(--accent);
}
.row.locked:not(.active) {
  cursor: default;
}
.title {
  flex: 1;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.footer,
.select-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: auto;
}
.footer {
  flex-wrap: wrap;
  justify-content: space-between;
}
.sections {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.link,
.select-bar button {
  padding: 6px 12px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.link:hover:not(:disabled),
.select-bar button:hover:not(:disabled) {
  color: var(--text);
}
.delete-all:hover:not(:disabled),
.select-bar .danger:hover:not(:disabled) {
  color: var(--danger);
}
.link:disabled,
.select-bar button:disabled {
  cursor: default;
  opacity: 0.5;
}
.select-bar {
  flex-wrap: wrap;
  font-size: 0.85em;
  color: var(--muted);
}
.select-bar .all {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.count-chosen {
  flex: 1;
}
.row.ticked {
  color: var(--text);
  background: var(--bg);
}
</style>
