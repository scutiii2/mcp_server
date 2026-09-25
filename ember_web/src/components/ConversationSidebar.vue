<script setup lang="ts">
import type { Conversation } from "../api/types";

// locked: a turn is running - switching or starting chats is blocked.
defineProps<{
  conversations: Conversation[];
  activeId: string | null;
  locked: boolean;
}>();
const emit = defineEmits<{ new: []; select: [id: string]; delete: [id: string] }>();
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
        @click="emit('select', c.id)"
      >
        <span class="title">{{ c.title }}</span>
        <button
          type="button"
          class="delete"
          title="Delete chat"
          :disabled="locked && c.id === activeId"
          @click.stop="emit('delete', c.id)"
        >
          <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
          </svg>
        </button>
      </li>
    </ul>
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
.delete {
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
.row:hover .delete,
.delete:focus-visible {
  opacity: 1;
}
@media (hover: none) {
  .delete {
    opacity: 1;
  }
}
.delete:hover:not(:disabled) {
  color: var(--danger);
}
.delete:disabled {
  cursor: default;
  opacity: 0;
}
</style>
