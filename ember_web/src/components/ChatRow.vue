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
