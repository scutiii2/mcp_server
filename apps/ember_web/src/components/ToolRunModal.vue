<script setup lang="ts">
import { useAuthStore } from "../stores/auth";
import type { ToolInfo, ToolRunResult } from "../api/types";
import BaseModal from "./BaseModal.vue";
import ToolResultPanel from "./ToolResultPanel.vue";
import ToolRunForm from "./ToolRunForm.vue";

/** A tool's details in a modal: its description, the form for its parameters
 * to run it, and the last result. Open while `tool` is set; the parent holds
 * the run state. */
defineProps<{ tool: ToolInfo | null; running: boolean; result: ToolRunResult | null }>();
const auth = useAuthStore();
const emit = defineEmits<{ close: []; run: [args: Record<string, unknown>] }>();
</script>

<template>
  <BaseModal :open="tool !== null" :title="tool?.title ?? ''" @close="emit('close')">
    <div v-if="tool" class="body">
      <code class="name">{{ tool.name }}</code>
      <p v-if="tool.description" class="description">{{ tool.description }}</p>
      <!-- key: a fresh form (and its defaults) per tool -->
      <ToolRunForm v-if="auth.hasPermission('tools.execute')" :key="tool.name" :schema="tool.inputSchema" :running="running" @run="(args) => emit('run', args)" />
      <ToolResultPanel v-if="result" :result="result" />
    </div>
  </BaseModal>
</template>

<style scoped>
.body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.name {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.description {
  margin: 0;
  white-space: pre-wrap;
  color: var(--muted);
}
</style>
