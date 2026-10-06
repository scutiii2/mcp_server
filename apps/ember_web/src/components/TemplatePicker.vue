<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import type { PromptTemplate } from "../api/TemplatesClient";
import { filterTemplates, preview } from "../utils/templates";

// canSave: the input holds text that "Save current text" can turn into a template.
const props = defineProps<{
  templates: PromptTemplate[];
  loading: boolean;
  error: string;
  canSave: boolean;
}>();
const emit = defineEmits<{
  /** The list is about to be shown: load it if it isn't yet. */
  open: [];
  pick: [template: PromptTemplate];
  manage: [];
  save: [];
}>();

const open = ref(false);
const query = ref("");
const root = ref<HTMLElement | null>(null);
const filter = ref<HTMLInputElement | null>(null);

const shown = computed(() => filterTemplates(props.templates, query.value));

async function toggle(): Promise<void> {
  open.value = !open.value;
  if (!open.value) return;
  query.value = "";
  emit("open");
  await nextTick();
  filter.value?.focus();
}

function close(): void {
  open.value = false;
}

function pick(template: PromptTemplate): void {
  close();
  emit("pick", template);
}

function choose(action: "manage" | "save"): void {
  close();
  if (action === "manage") emit("manage");
  else emit("save");
}

// Clicking anywhere else closes the popover.
function onOutside(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) close();
}

watch(open, (isOpen) => {
  if (isOpen) document.addEventListener("pointerdown", onOutside);
  else document.removeEventListener("pointerdown", onOutside);
});

onBeforeUnmount(() => document.removeEventListener("pointerdown", onOutside));
</script>

<template>
  <div ref="root" class="picker" @keydown.esc.prevent="close">
    <button
      type="button"
      class="trigger"
      title="Saved prompts"
      aria-label="Saved prompts"
      :aria-expanded="open"
      @click="toggle"
    >
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path
          d="M6 4h12v17l-6-4-6 4V4z"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    <div v-if="open" class="popover" role="dialog" aria-label="Saved prompts">
      <input ref="filter" v-model="query" type="search" placeholder="Filter prompts" aria-label="Filter prompts" />
      <p v-if="error" class="note error" role="alert">
        {{ error }} <button type="button" class="link" @click="emit('open')">Retry</button>
      </p>
      <p v-else-if="loading && templates.length === 0" class="note">Loading …</p>
      <p v-else-if="templates.length === 0" class="note">No saved prompts yet.</p>
      <p v-else-if="shown.length === 0" class="note">No prompt matches.</p>
      <ul v-else class="list">
        <li v-for="t in shown" :key="t.id">
          <button type="button" class="item" @click="pick(t)">
            <span class="name">{{ t.name }}</span>
            <span class="body">{{ preview(t.body) }}</span>
          </button>
        </li>
      </ul>
      <div class="foot">
        <button type="button" class="link" :disabled="!canSave" title="Save what is typed as a new prompt" @click="choose('save')">
          Save current text …
        </button>
        <button type="button" class="link" @click="choose('manage')">Manage …</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.picker {
  position: relative;
  display: flex;
  flex-shrink: 0;
}
.trigger {
  display: grid;
  place-items: center;
  width: 30px;
  height: 34px;
  padding: 0;
  border: none;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
}
.trigger:hover,
.trigger[aria-expanded="true"] {
  color: var(--text);
}
.popover {
  position: absolute;
  bottom: calc(100% + 10px);
  left: -8px;
  z-index: 16; /* above the settings menu (15) that sits over the composer */
  width: min(340px, calc(100vw - 48px));
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}
.popover input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
  color: var(--text);
  background: var(--bg);
  font: inherit;
  font-size: 0.9em;
}
.popover input:focus {
  border-color: var(--accent);
}
.note {
  margin: 8px 4px;
  font-size: 0.85em;
  color: var(--muted);
}
.note.error {
  color: var(--danger);
}
.list {
  max-height: 260px;
  margin: 6px 0 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}
.item {
  display: flex;
  flex-direction: column;
  gap: 1px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
  color: var(--text);
  background: transparent;
}
.item:hover,
.item:focus-visible {
  background: var(--bg);
}
.name {
  font-size: 0.9em;
}
.body {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 0.78em;
  color: var(--muted);
}
.foot {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}
.link {
  padding: 2px 6px;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.8em;
  color: var(--muted);
  background: transparent;
}
.link:hover:not(:disabled) {
  color: var(--text);
  background: var(--bg);
}
.link:disabled {
  cursor: default;
  opacity: 0.4;
}
</style>
