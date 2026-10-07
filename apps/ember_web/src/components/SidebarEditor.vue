<script setup lang="ts">
// The Settings page's "Sidebar" card: one row per page the account may open, in
// the order the rail shows them (pinned first). Drag a row, or use the arrows,
// to reorder; pin keeps a page at the top; the switch shows or hides it in the
// rail (a hidden page stays reachable from the Overview page). Every change
// applies at once and is saved to the account.
import { computed, ref } from "vue";
import SettingRow from "./SettingRow.vue";
import ToggleSwitch from "./ToggleSwitch.vue";
import { visiblePages } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import { useNavPrefsStore } from "../stores/navPrefs";
import { arrange, dropPage, isDefault, setHidden, setPinned } from "../utils/navArrangement";

const PIN_ICON = "M12 17v5M9 3h6l-1 6 3 3v2H7v-2l3-3z";
const GRIP_ICON = "M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01";

const auth = useAuthStore();
const navPrefs = useNavPrefsStore();

const pages = computed(() => visiblePages((p) => auth.hasPermission(p)));
const groups = computed(() => arrange(pages.value, navPrefs.prefs));
const rows = computed(() => [
  ...groups.value.pinned.map((page) => ({ page, pinned: true })),
  ...groups.value.rest.map((page) => ({ page, pinned: false })),
]);
const hidden = computed(() => new Set(navPrefs.prefs.hidden));
const modified = computed(() => !isDefault(navPrefs.prefs));

const dragging = ref<string | null>(null);
const over = ref<string | null>(null);

function checked(event: Event): boolean {
  return (event.target as HTMLInputElement).checked;
}

/** The neighbour a row would swap with, if it is in the same group. */
function neighbour(index: number, delta: -1 | 1): string | null {
  const row = rows.value[index];
  const other = rows.value[index + delta];
  return row && other && row.pinned === other.pinned ? other.page.to : null;
}

function move(index: number, delta: -1 | 1): void {
  const row = rows.value[index];
  const target = neighbour(index, delta);
  if (row && target) void navPrefs.update(dropPage(pages.value, navPrefs.prefs, row.page.to, target));
}

function onDrop(target: string): void {
  const from = dragging.value;
  dragging.value = over.value = null;
  if (from && from !== target) void navPrefs.update(dropPage(pages.value, navPrefs.prefs, from, target));
}

function onDragStart(event: DragEvent, id: string): void {
  dragging.value = id;
  event.dataTransfer?.setData("text/plain", id); // Firefox starts no drag without data
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
}
</script>

<template>
  <div class="sidebar-editor">
    <SettingRow
      setting-id="sidebar-pages"
      label="Pages"
      description="Order, pin or hide the pages in the sidebar. Hidden pages stay on the Overview page."
      :modified="modified"
      @reset="navPrefs.reset()"
    />
    <p v-if="navPrefs.error" class="error" role="alert">{{ navPrefs.error }}</p>
    <ul class="rows" aria-label="Sidebar pages">
      <li
        v-for="(row, i) in rows"
        :key="row.page.to"
        :class="['row', { off: hidden.has(row.page.to), dragging: dragging === row.page.to, over: over === row.page.to && dragging !== row.page.to }]"
        draggable="true"
        @dragstart="onDragStart($event, row.page.to)"
        @dragend="dragging = over = null"
        @dragover.prevent="over = row.page.to"
        @dragleave="over === row.page.to && (over = null)"
        @drop.prevent="onDrop(row.page.to)"
      >
        <svg class="grip" viewBox="0 0 24 24" aria-hidden="true"><path :d="GRIP_ICON" /></svg>
        <svg class="page-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path v-for="d in row.page.icon" :key="d" :d="d" />
        </svg>
        <span class="name">{{ row.page.label }}</span>
        <span v-if="row.pinned" class="tag">Pinned</span>
        <span class="actions">
          <button
            type="button"
            class="icon-btn"
            :aria-label="`Move ${row.page.label} up`"
            :disabled="!neighbour(i, -1)"
            @click="move(i, -1)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 15l6-6 6 6" /></svg>
          </button>
          <button
            type="button"
            class="icon-btn"
            :aria-label="`Move ${row.page.label} down`"
            :disabled="!neighbour(i, 1)"
            @click="move(i, 1)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
          </button>
          <button
            type="button"
            :class="['icon-btn', { on: row.pinned }]"
            :aria-pressed="row.pinned"
            :aria-label="`Pin ${row.page.label} to the top`"
            :title="row.pinned ? 'Unpin' : 'Pin to the top'"
            @click="navPrefs.update(setPinned(pages, navPrefs.prefs, row.page.to, !row.pinned))"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="PIN_ICON" /></svg>
          </button>
          <ToggleSwitch
            small
            :aria-label="`Show ${row.page.label} in the sidebar`"
            :checked="!hidden.has(row.page.to)"
            @change="navPrefs.update(setHidden(pages, navPrefs.prefs, row.page.to, !checked($event)))"
          />
        </span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.rows {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 0 6px;
  padding: 0;
  list-style: none;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: grab;
}
.row:hover {
  background: var(--bg);
}
.row.off .name,
.row.off .page-icon {
  opacity: 0.5;
}
.row.dragging {
  opacity: 0.4;
}
.row.over {
  border-color: var(--accent);
}
svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.grip {
  flex: none;
  width: 16px;
  height: 16px;
  color: var(--muted);
}
.page-icon {
  flex: none;
  width: 20px;
  height: 20px;
}
.name {
  flex: 1;
  min-width: 0;
}
.tag {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--accent);
  background: var(--code-bg);
}
.actions {
  display: flex;
  align-items: center;
  gap: 2px;
}
.icon-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--muted);
  background: transparent;
}
.icon-btn svg {
  width: 16px;
  height: 16px;
}
.icon-btn:hover:not(:disabled) {
  color: var(--text);
  background: var(--code-bg);
}
.icon-btn.on {
  color: var(--accent);
}
.icon-btn:disabled {
  cursor: default;
  opacity: 0.3;
}
.actions :deep(.toggle) {
  margin-left: 6px;
}
.error {
  margin: 0 0 6px;
  color: var(--danger);
  font-size: 0.9em;
}
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
</style>
