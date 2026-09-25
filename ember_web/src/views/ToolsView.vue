<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { McpServerClient } from "../api/McpServerClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import ToolResultPanel from "../components/ToolResultPanel.vue";
import ToolRunForm from "../components/ToolRunForm.vue";

const server = new McpServerClient();

const tools = ref<ToolInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const query = ref("");

// One card open at a time; its last result stays until re-run or closed.
const openName = ref<string | null>(null);
const running = ref(false);
const result = ref<ToolRunResult | null>(null);

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return tools.value;
  return tools.value.filter(
    (t) =>
      t.title.toLowerCase().includes(q) || t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q),
  );
});

onMounted(async () => {
  try {
    tools.value = (await server.listTools()).sort((a, b) => a.title.localeCompare(b.title));
  } catch (err) {
    loadError.value = String(err);
  } finally {
    loading.value = false;
  }
});

function toggle(name: string): void {
  if (running.value) return; // keep the running tool's card (and its result) in place
  openName.value = openName.value === name ? null : name;
  result.value = null;
}

async function run(name: string, args: Record<string, unknown>): Promise<void> {
  running.value = true;
  result.value = null;
  try {
    result.value = await server.runTool(name, args);
  } catch (err) {
    // Transport/protocol failure - shown the same way as a tool-side error.
    result.value = { text: String(err), isError: true };
  } finally {
    running.value = false;
  }
}
</script>

<template>
  <section class="tools-view">
    <div class="column">
      <div class="head">
        <h2>mcp_server tools <span v-if="tools.length" class="count">{{ tools.length }}</span></h2>
        <input v-if="tools.length" v-model="query" type="search" class="search" placeholder="Filter tools" />
      </div>

      <p v-if="loading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-else-if="tools.length === 0" class="muted">No tools exposed.</p>
      <p v-else-if="filtered.length === 0" class="muted">No tools match "{{ query }}".</p>

      <ul v-else class="cards">
        <li v-for="t in filtered" :key="t.name" :class="['card', { open: openName === t.name }]">
          <button type="button" class="card-head" :aria-expanded="openName === t.name" @click="toggle(t.name)">
            <span class="heading">
              <span class="title">{{ t.title }}</span>
              <code class="name">{{ t.name }}</code>
            </span>
            <span class="chevron" aria-hidden="true">{{ openName === t.name ? "▾" : "▸" }}</span>
          </button>
          <p v-if="t.description" class="description">{{ t.description }}</p>

          <div v-if="openName === t.name" class="body">
            <!-- key: a fresh form (and its defaults) per tool -->
            <ToolRunForm :key="t.name" :schema="t.inputSchema" :running="running" @run="(args) => run(t.name, args)" />
            <ToolResultPanel v-if="result" :result="result" />
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.tools-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 1.2em;
}
.count {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.7em;
  color: var(--muted);
  background: var(--surface);
}
.search {
  flex: 0 1 260px;
  min-width: 0;
  padding: 7px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
}
.search:focus {
  outline: none;
  border-color: var(--accent);
}
.cards {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.card {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.card.open {
  border-color: var(--accent);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 12px 14px 0;
  border: none;
  cursor: pointer;
  text-align: left;
  background: transparent;
}
.heading {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
  min-width: 0;
}
.title {
  font-weight: 600;
}
.name {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.chevron {
  color: var(--muted);
}
.description {
  margin: 6px 0 0;
  padding: 0 14px 12px;
  white-space: pre-wrap;
  color: var(--muted);
}
.card:not(:has(.description)) .card-head {
  padding-bottom: 12px;
}
.body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 12px 14px 14px;
  border-top: 1px solid var(--border);
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
