<script setup lang="ts">
import type { ToolInfo } from "../api/types";

/** One mcp_server tool as a compact row: just its label and tool name. A click
 * asks the parent to open its details and run form (a modal). */
defineProps<{ tool: ToolInfo }>();
const emit = defineEmits<{ open: [] }>();
</script>

<template>
  <li class="tool">
    <button type="button" class="row" aria-haspopup="dialog" @click="emit('open')">
      <span class="heading">
        <span class="title">{{ tool.title }}</span>
        <code class="name">{{ tool.name }}</code>
      </span>
      <span class="chevron" aria-hidden="true">›</span>
    </button>
  </li>
</template>

<style scoped>
.tool {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg);
}
.tool:hover,
.tool:focus-within {
  border-color: var(--accent);
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 10px 14px;
  border: none;
  border-radius: calc(var(--radius-lg) - 1px);
  cursor: pointer;
  text-align: left;
  color: inherit;
  background: transparent;
  font: inherit;
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
</style>
