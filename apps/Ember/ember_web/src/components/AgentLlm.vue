<script setup lang="ts">
import { computed } from "vue";
import type { AgentListing } from "../api/AgentsClient";

/** Which provider, gateway and model an agent runs on, and the model each
 * tier it may use resolves to (what a tier is for shows on hover). A value
 * the agent file does not set is left out; with nothing to show nothing is drawn. */
const props = defineProps<{ agent: Pick<AgentListing, "provider" | "gateway" | "model" | "tiers"> }>();

const rows = computed(() =>
  [
    { label: "Provider", value: props.agent.provider },
    { label: "Gateway", value: props.agent.gateway },
    { label: "Model", value: props.agent.model },
  ].filter((row): row is { label: string; value: string } => !!row.value),
);
</script>

<template>
  <div v-if="rows.length || agent.tiers.length" class="llm">
    <dl v-if="rows.length">
      <template v-for="row in rows" :key="row.label">
        <dt>{{ row.label }}</dt>
        <dd>{{ row.value }}</dd>
      </template>
    </dl>
    <ul v-if="agent.tiers.length" class="tiers" aria-label="Model tiers">
      <li v-for="t in agent.tiers" :key="t.tier">
        <span class="tier" :title="t.use_for">{{ t.tier }}</span>
        <span class="tier-model" :title="t.use_for">{{ t.id }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.llm {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 4px 0 0;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 0.8em;
}
dl,
.tiers {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 3px 10px;
  margin: 0;
}
.tiers {
  padding: 0;
  list-style: none;
}
.tiers li {
  display: contents;
}
dt,
.tier {
  color: var(--muted);
}
dd,
.tier-model {
  margin: 0;
  font-family: var(--mono);
  overflow-wrap: anywhere;
}
</style>
