<script setup lang="ts">
import { nextTick, ref } from "vue";
import type { Conversation } from "../api/types";

// locked: a turn is running - switching or starting chats is blocked.
const props = defineProps<{
  conversations: Conversation[];
  activeId: string | null;
  locked: boolean;
}>();
const emit = defineEmits<{
  new: [];
  select: [id: string];
  delete: [id: string];
  rename: [id: string, title: string];
  deleteAll: [];
}>();

// The row being renamed, and its draft title.
const renamingId = ref<string | null>(null);
const draft = ref("");
const renameInput = ref<HTMLInputElement[]>([]);

async function startRename(c: Conversation): Promise<void> {
  renamingId.value = c.id;
  draft.value = c.title;
  await nextTick();
  renameInput.value[0]?.select();
}

function finishRename(save: boolean): void {
  const id = renamingId.value;
  if (id === null) return;
  renamingId.value = null; // before emitting: blur fires again when the input goes
  if (save) emit("rename", id, draft.value);
}

function confirmDelete(c: Conversation): void {
  if (confirm(`Delete "${c.title}"? This can't be undone.`)) emit("delete", c.id);
}

function confirmDeleteAll(): void {
  const count = props.conversations.length;
  if (confirm(`Delete all ${count} chat${count === 1 ? "" : "s"}? This can't be undone.`)) emit("deleteAll");
}
</script>

<template>
  <aside class="sidebar">
    <button type="button" class="new-chat" :disabled="locked" @click="emit('new')">
      <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
      </svg>
      New chat
    </button>

    <p v-if="conversations.length === 0" class="empty">No saved chats yet.</p>
    <ul v-else class="list">
      <li
        v-for="c in conversations"
        :key="c.id"
        :class="['row', { active: c.id === activeId, locked }]"
        :title="c.title"
        @click="renamingId !== c.id && emit('select', c.id)"
      >
        <input
          v-if="renamingId === c.id"
          ref="renameInput"
          v-model="draft"
          class="rename"
          aria-label="Chat title"
          maxlength="120"
          @click.stop
          @keydown.enter.prevent="finishRename(true)"
          @keydown.esc.prevent="finishRename(false)"
          @blur="finishRename(true)"
        />
        <template v-else>
          <span class="title" @dblclick.stop="startRename(c)">{{ c.title }}</span>
          <button type="button" class="icon" title="Rename chat" @click.stop="startRename(c)">
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
            :disabled="locked && c.id === activeId"
            @click.stop="confirmDelete(c)"
          >
            <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
            </svg>
          </button>
        </template>
      </li>
    </ul>

    <button
      v-if="conversations.length > 1"
      type="button"
      class="delete-all"
      :disabled="locked"
      @click="confirmDeleteAll"
    >
      Delete all chats
    </button>
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
.delete-all {
  margin-top: auto;
  padding: 6px 12px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.delete-all:hover:not(:disabled) {
  color: var(--danger);
}
.delete-all:disabled {
  cursor: default;
  opacity: 0.5;
}
</style>
