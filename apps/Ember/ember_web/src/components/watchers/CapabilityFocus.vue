<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

/** Narrow the page to one capability: a button that opens a searchable menu. Built for many
 * capabilities - the menu filters as you type - and each option carries a status dot and its
 * watcher count. `null` is "All capabilities". */
export interface FocusOption {
  name: string;
  watchers: number;
  failed: boolean;
  running: boolean;
}

const props = defineProps<{ options: FocusOption[] }>();
const model = defineModel<string | null>({ required: true });

const open = ref(false);
const query = ref("");
const root = ref<HTMLElement | null>(null);
const search = ref<HTMLInputElement | null>(null);
const button = ref<HTMLButtonElement | null>(null);

const shown = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return props.options.filter((o) => o.name.toLowerCase().includes(needle));
});

function dot(o: FocusOption): string {
  return o.failed ? "var(--status-failed)" : o.running ? "var(--status-running)" : "var(--status-ok)";
}

function close(refocus = false): void {
  open.value = false;
  query.value = "";
  if (refocus) void nextTick(() => button.value?.focus());
}

function choose(name: string | null): void {
  model.value = name;
  close(true);
}

function onOutside(event: MouseEvent): void {
  if (!root.value?.contains(event.target as Node)) close();
}

watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener("click", onOutside);
    void nextTick(() => search.value?.focus());
  } else {
    document.removeEventListener("click", onOutside);
  }
});
onBeforeUnmount(() => document.removeEventListener("click", onOutside));
</script>

<template>
  <div ref="root" class="focus" @keydown.esc="close(true)">
    <button ref="button" type="button" class="chip trigger" aria-haspopup="true" :aria-expanded="open" @click="open = !open">
      Focus: <strong>{{ model ?? "All capabilities" }}</strong> <span aria-hidden="true">▾</span>
    </button>
    <div v-if="open" class="menu">
      <input ref="search" v-model="query" type="search" placeholder="Find a capability" aria-label="Find a capability" />
      <ul class="options">
        <li>
          <button type="button" :class="['option', { current: model === null }]" @click="choose(null)">All capabilities</button>
        </li>
        <li v-for="o in shown" :key="o.name">
          <button type="button" :class="['option', { current: model === o.name }]" @click="choose(o.name)">
            <span class="dot" :style="{ background: dot(o) }" />
            <span class="name">{{ o.name }}</span>
            <span class="n">{{ o.watchers }}</span>
          </button>
        </li>
        <li v-if="shown.length === 0" class="none">No capability matches.</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.focus {
  position: relative;
}
.trigger strong {
  font-weight: 500;
}
.menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 5;
  width: 260px;
  max-width: calc(100vw - 32px);
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: 0 6px 20px rgb(0 0 0 / 0.14);
}
.menu input {
  width: 100%;
  margin-bottom: 6px;
}
.options {
  max-height: 220px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}
.option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 5px 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--text);
  font: inherit;
  font-size: 0.85em;
  text-align: left;
  cursor: pointer;
}
.option:hover,
.option:focus-visible {
  background: color-mix(in srgb, var(--text) 7%, transparent);
}
.option.current {
  font-weight: 600;
}
.dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
}
.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-family: var(--mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.n {
  color: var(--muted);
}
.none {
  padding: 6px 8px;
  font-size: 0.85em;
  color: var(--muted);
}
</style>
