<script setup lang="ts">
import type { ToolInfo, ToolRunResult } from "../api/types";
import ToolResultPanel from "./ToolResultPanel.vue";
import ToolRunForm from "./ToolRunForm.vue";

/** One mcp_server tool as an expandable card: its description, and once open
 * a form to run it and the last result. The parent decides which is open. */
defineProps<{ tool: ToolInfo; open: boolean; running: boolean; result: ToolRunResult | null }>();
const emit = defineEmits<{ toggle: []; run: [args: Record<string, unknown>] }>();
</script>

<template>
  <li :class="['card', { open }]">
    <button type="button" class="card-head" :aria-expanded="open" @click="emit('toggle')">
      <span class="heading">
        <span class="title">{{ tool.title }}</span>
        <code class="name">{{ tool.name }}</code>
      </span>
      <span class="chevron" aria-hidden="true">{{ open ? "▾" : "▸" }}</span>
    </button>
    <p v-if="tool.description" class="description">{{ tool.description }}</p>

    <div v-if="open" class="body">
      <!-- key: a fresh form (and its defaults) per tool -->
      <ToolRunForm :key="tool.name" :schema="tool.inputSchema" :running="running" @run="(args) => emit('run', args)" />
      <ToolResultPanel v-if="result" :result="result" />
    </div>
  </li>
</template>

<style scoped>
.card {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg);
}
.card.open {
  border-color: var(--accent);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 10px 14px 0;
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
  padding: 0 14px 10px;
  white-space: pre-wrap;
  color: var(--muted);
}
.card:not(:has(.description)) .card-head {
  padding-bottom: 10px;
}
.body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 12px 14px 14px;
  border-top: 1px solid var(--border);
}
</style>
