<script setup lang="ts">
import { ref, watch } from "vue";
import type { MenuPoint } from "./menuPoint";

// One block of the chat list: a header (title, count, a "..." menu button) and
// the rows in the default slot. A folder can fold; Pinned and "Chats" cannot.
// With title null it is just the list, which is how an ungrouped list looks.
const props = withDefaults(defineProps<{
  title: string | null;
  count: number;
  collapsible: boolean;
  collapsed: boolean;
  menu: boolean;
  /** The folder menu is open. */
  expanded?: boolean;
  /** The drag in progress may be dropped here. */
  accepting?: boolean;
  /** Shown in place of the rows while there are none and a drop is accepted. */
  hint?: string | null;
  /** The Pinned section: its heading gets a pin mark. */
  pinned?: boolean;
}>(), { expanded: false, accepting: false, hint: null, pinned: false });
const emit = defineEmits<{ toggle: []; openMenu: [point: MenuPoint]; drop: [] }>();

// The whole section is the zone, so a folded folder still takes a drop.
const over = ref(false);

function onDragOver(event: DragEvent): void {
  if (!props.accepting) return;
  event.preventDefault(); // without this the browser refuses the drop
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  over.value = true;
}

function onDragLeave(event: DragEvent): void {
  // Moving between the zone's own children fires dragleave too; only leaving the zone counts.
  const zone = event.currentTarget as HTMLElement;
  const next = event.relatedTarget as Node | null;
  if (next) {
    if (zone.contains(next)) return;
  } else {
    // Some browsers give no relatedTarget: decide by where the pointer is.
    const box = zone.getBoundingClientRect();
    const inside = event.clientX >= box.left && event.clientX <= box.right
      && event.clientY >= box.top && event.clientY <= box.bottom;
    if (inside) return;
  }
  over.value = false;
}

// A cancelled or outside drop may never fire dragleave; never carry `over` into the next drag.
watch(() => props.accepting, (accepting) => {
  if (!accepting) over.value = false;
});

function onDrop(event: DragEvent): void {
  if (!props.accepting) return;
  event.preventDefault();
  over.value = false;
  emit("drop");
}

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
  <section
    :class="['section', { accepting, over: over && accepting }]"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
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
        <svg class="kind" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M2 4h4l1.5 1.5H14V12H2z" /></svg>
        <span class="name">{{ title }}</span>
        <span class="count">{{ count }}</span>
      </button>
      <h4 v-else class="plain">
        <svg v-if="pinned" class="kind" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <path d="M6 2h4l-.5 4 2 2.5H4.5L6.5 6zM8 8.5V14" />
        </svg>
        <span class="name">{{ title }}</span>
        <span class="count">{{ count }}</span>
      </h4>
      <button
        v-if="menu"
        ref="moreButton"
        type="button"
        :class="['more', { expanded }]"
        title="Folder actions"
        aria-label="Folder actions"
        aria-haspopup="menu"
        :aria-expanded="expanded"
        @pointerdown.stop
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
    <p v-if="accepting && hint && count === 0" class="hint">{{ hint }}</p>
  </section>
</template>

<style scoped>
.section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.accepting {
  outline: 1px dashed var(--border);
  outline-offset: -1px;
  border-radius: var(--radius-md);
}
.over {
  outline: 1px solid var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.hint {
  margin: 0;
  padding: 8px 12px;
  font-size: 0.85em;
  color: var(--muted);
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
  border-radius: var(--radius-md);
  color: var(--muted);
  background: transparent;
  font: inherit;
  font-size: 0.8em;
  font-weight: 500;
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
  padding: 0 7px;
  border-radius: var(--radius-full);
  font-weight: 400;
  background: var(--bg);
}
.kind {
  flex-shrink: 0;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.plain .kind {
  stroke: var(--accent);
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
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--muted);
  background: transparent;
  opacity: 0;
}
header:hover .more,
.more.expanded,
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
