<script setup lang="ts">
import { computed } from "vue";
import type { AgentListing } from "../api/AgentsClient";

/** Which provider, gateway and model an agent runs on. A value the agent file
 * does not set is left out; with none set nothing is drawn. */
const props = defineProps<{ agent: Pick<AgentListing, "provider" | "gateway" | "model"> }>();

const rows = computed(() =>
  [
    { label: "Provider", value: props.agent.provider },
    { label: "Gateway", value: props.agent.gateway },
    { label: "Model", value: props.agent.model },
  ].filter((row): row is { label: string; value: string } => !!row.value),
);
</script>

<template>
  <dl v-if="rows.length" class="llm">
    <template v-for="row in rows" :key="row.label">
      <dt>{{ row.label }}</dt>
      <dd>{{ row.value }}</dd>
    </template>
  </dl>
</template>

<style scoped>
.llm {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 3px 10px;
  margin: 4px 0 0;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 0.8em;
}
dt {
  color: var(--muted);
}
dd {
  margin: 0;
  font-family: var(--mono);
  overflow-wrap: anywhere;
}
</style>
