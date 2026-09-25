<script setup lang="ts">
import { onMounted, ref } from "vue";
import { McpServerClient } from "../api/McpServerClient";
import type { ToolInfo } from "../api/types";

const server = new McpServerClient(import.meta.env.VITE_MCP_SERVER_URL);

const tools = ref<ToolInfo[]>([]);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    tools.value = (await server.listTools()).sort((a, b) => a.name.localeCompare(b.name));
  } catch (err) {
    error.value = String(err);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="tools-view">
    <div class="column">
      <h2>mcp_server tools <span v-if="tools.length" class="count">{{ tools.length }}</span></h2>
      <p v-if="loading" class="muted">loading ...</p>
      <p v-else-if="error" class="error">error: {{ error }}</p>
      <p v-else-if="tools.length === 0" class="muted">No tools exposed.</p>
      <ul v-else class="cards">
        <li v-for="t in tools" :key="t.name" class="card">
          <code class="name">{{ t.name }}</code>
          <p v-if="t.description" class="description">{{ t.description }}</p>
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
h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 16px;
  font-size: 1.2em;
}
.count {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.7em;
  color: var(--muted);
  background: var(--surface);
}
.cards {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.card {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.name {
  font-family: var(--mono);
  font-weight: 600;
}
.description {
  margin: 6px 0 0;
  white-space: pre-wrap;
  color: var(--muted);
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
