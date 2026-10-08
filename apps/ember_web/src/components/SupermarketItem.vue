<script setup lang="ts">
import { CAPABILITY_ICONS } from "../utils/capabilityIcons";

/** One row of the Supermarket: a built-in capability or an extension, what it
 * brings, and whether it is added to the account. The parent decides what Add
 * and Disable mean; extra actions (an admin's Remove) go in the `actions` slot. */
defineProps<{
  label: string;
  name: string;
  icon: "builtin" | "extension";
  summary: string;
  added: boolean;
  /** Off for everyone (an administrator turned it off): it cannot be added. */
  locked?: boolean;
  /** The summary is a problem (an extension that is not connected). */
  failed?: boolean;
}>();
const emit = defineEmits<{ add: []; disable: [] }>();
</script>

<template>
  <article :class="['item', { off: locked && !added }]">
    <span class="tile" aria-hidden="true">
      <svg viewBox="0 0 16 16" width="18" height="18"><path :d="CAPABILITY_ICONS[icon]" /></svg>
    </span>
    <span class="heading">
      <h3>{{ label }}</h3>
      <code class="name">{{ name }}</code>
    </span>
    <span :class="['summary', failed ? 'bad' : 'muted']">{{ summary }}</span>
    <span class="actions">
      <slot name="actions" />
      <template v-if="added">
        <span class="added">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5" /></svg>
          Added
        </span>
        <button type="button" class="secondary" :aria-label="`Disable ${label}`" @click="emit('disable')">Disable</button>
      </template>
      <span v-else-if="locked" class="badge">Off for everyone</span>
      <button v-else type="button" class="add" :aria-label="`Add ${label}`" @click="emit('add')">Add</button>
    </span>
  </article>
</template>

<style scoped>
.item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;
  margin-bottom: 8px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.item.off {
  opacity: 0.75;
}
.tile {
  display: grid;
  flex: none;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--bg);
}
.tile svg {
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.heading {
  display: flex;
  flex: 1 1 140px;
  flex-direction: column;
  min-width: 0;
}
h3 {
  margin: 0;
  font-size: 1em;
}
.name {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.summary {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75em;
  white-space: nowrap;
  background: var(--bg);
}
.muted {
  color: var(--muted);
}
.bad {
  color: var(--danger);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.added {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.85em;
  color: var(--success);
}
.added svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
}
button {
  padding: 4px 14px;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
}
button.add {
  border: 1px solid var(--accent);
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
button.secondary {
  border: 1px solid var(--border);
  color: var(--text);
  background: transparent;
}
button.secondary:hover {
  border-color: var(--accent);
}
button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
