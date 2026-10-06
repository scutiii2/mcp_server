<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { Conversation } from "../api/types";
import type { MenuPoint } from "./menuPoint";

// One row of the chat list. The sidebar owns which row is being renamed and
// which are ticked; this row owns only the text being typed.
// locked: a turn is running somewhere (every row gets the `locked` class).
// lockedHere: this chat is the one answering, so it can't be ticked.
// Its actions (pin, move, rename, delete) live in a menu the sidebar owns:
// the "..." button and a right-click ask for it (`openMenu`).
const props = withDefaults(defineProps<{
  chat: Conversation;
  active: boolean;
  locked: boolean;
  lockedHere: boolean;
  selecting: boolean;
  ticked: boolean;
  renaming: boolean;
  /** Its menu is open. */
  expanded?: boolean;
  /** It may be dragged to another section. */
  draggable?: boolean;
}>(), { expanded: false, draggable: false });
const emit = defineEmits<{
  select: [];
  toggle: [];
  startRename: [];
  finishRename: [save: boolean, title: string];
  openMenu: [point: MenuPoint];
  dragStart: [];
  dragEnd: [];
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
    renameInput.value?.focus();
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

const dragging = ref(false);

function onDragStart(event: DragEvent): void {
  if (!props.draggable) {
    event.preventDefault();
    return;
  }
  event.dataTransfer?.setData("text/plain", props.chat.id);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
  dragging.value = true;
  emit("dragStart");
}

function onDragEnd(): void {
  dragging.value = false;
  emit("dragEnd");
}
</script>

<template>
  <li
    :class="['row', { active, locked, ticked: selecting && ticked, dragging }]"
    :draggable="draggable"
    :title="chat.title"
    @click="onClick"
    @contextmenu="openFromContext"
    @dragstart="onDragStart"
    @dragend="onDragEnd"
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
      <!-- pointerdown.stop: an open menu closes on any press outside it, so a
           press on this button must not reach it; the sidebar toggles instead. -->
      <button
        ref="moreButton"
        type="button"
        :class="['icon', 'more', { expanded }]"
        title="Chat actions"
        aria-label="Chat actions"
        aria-haspopup="menu"
        :aria-expanded="expanded"
        @pointerdown.stop
        @click.stop="openFromButton"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <circle cx="5" cy="12" r="1.8" fill="currentColor" />
          <circle cx="12" cy="12" r="1.8" fill="currentColor" />
          <circle cx="19" cy="12" r="1.8" fill="currentColor" />
        </svg>
      </button>
    </template>
  </li>
</template>

<style scoped>
/* The row's own box (.row and its active / locked / ticked states) is styled by
 * the sidebar: a component's root element takes its parent's scoped styles too. */
.dragging {
  opacity: 0.45;
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
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--muted);
  background: transparent;
  opacity: 0;
}
.row:hover .icon,
.icon.expanded,
.icon:focus-visible {
  opacity: 1;
}
@media (hover: none) {
  .icon {
    opacity: 1;
  }
}
.icon:hover {
  color: var(--text);
}
.running {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
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
  border-radius: var(--radius-md);
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
