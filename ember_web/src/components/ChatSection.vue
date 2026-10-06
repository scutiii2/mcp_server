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
